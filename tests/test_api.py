"""Extract API client, against recorded response shapes.

The shapes here were captured from the live IPUMS API, not from the docs --
the docs name a ``stataCommandFile`` link that a CSV extract does not actually
return, and say nothing about completed extracts whose files have expired.
"""

from __future__ import annotations

import pytest

from ipumsi.api import IpumsAPIError, IpumsClient

READY = {
    "number": 99,
    "status": "completed",
    "downloadLinks": {
        "data": {"url": "https://api.ipums.org/d/ipumsi_00099.csv.gz", "bytes": 220783409},
        "ddiCodebook": {"url": "https://api.ipums.org/d/ipumsi_00099.xml", "bytes": 133000},
        "basicCodebook": {"url": "https://api.ipums.org/d/ipumsi_00099.cbk", "bytes": 50000},
        "stsCommandFile": {"url": "https://api.ipums.org/d/ipumsi_00099.sts", "bytes": 30000},
    },
    "extractDefinition": {
        "description": "ipumsi: EDATTAIN, ESTABSZ, PERWT",
        "dataFormat": "csv",
        "samples": {f"s{i}": {} for i in range(88)},
        "variables": {f"V{i}": {} for i in range(12)},
    },
}

# Completed, but IPUMS has removed the files. This is the common case for
# anything more than a few days old, and it is NOT the same as "not ready".
EXPIRED = {
    "number": 98,
    "status": "completed",
    "downloadLinks": {},
    "extractDefinition": {"description": "Brazil rent study", "samples": {"br2010a": {}},
                          "variables": {"AGE": {}}, "dataFormat": "csv"},
}

QUEUED = {
    "number": 100,
    "status": "queued",
    "downloadLinks": {},
    "extractDefinition": {"description": "new one", "samples": {}, "variables": {}},
}


@pytest.fixture
def client(monkeypatch) -> IpumsClient:
    monkeypatch.setenv("IPUMS_API_KEY", "test-key")
    return IpumsClient()


def test_recent_flattens_and_classifies(client, monkeypatch):
    monkeypatch.setattr(client, "list_extracts", lambda limit=25: [READY, EXPIRED, QUEUED])
    rows = {row["number"]: row for row in client.recent()}

    ready = rows[99]
    assert ready["downloadable"] is True and ready["expired"] is False
    assert ready["n_samples"] == 88 and ready["n_variables"] == 12
    assert ready["bytes"] == 220783409
    assert ready["files"] == ["basicCodebook", "data", "ddiCodebook", "stsCommandFile"]

    # The distinction the UI depends on: completed but nothing left to fetch.
    assert rows[98]["status"] == "completed"
    assert rows[98]["downloadable"] is False
    assert rows[98]["expired"] is True

    # Queued is also not downloadable, but it is not expired -- it will arrive.
    assert rows[100]["downloadable"] is False
    assert rows[100]["expired"] is False


def test_download_refuses_an_unfinished_extract(client, monkeypatch):
    monkeypatch.setattr(client, "status", lambda number: QUEUED)
    with pytest.raises(IpumsAPIError, match="not completed"):
        client.download(100)


def test_download_explains_expiry_rather_than_silently_doing_nothing(client, monkeypatch):
    monkeypatch.setattr(client, "status", lambda number: EXPIRED)
    with pytest.raises(IpumsAPIError, match="no longer on the IPUMS servers"):
        client.download(98)


def test_local_files_reports_what_is_on_disk(client, tmp_path):
    assert client.local_files(99, dest=tmp_path) == []

    folder = tmp_path / "ipumsi_00099"
    folder.mkdir()
    (folder / "ipumsi_00099.csv.gz").write_bytes(b"data")
    (folder / "ipumsi_00099.xml").write_bytes(b"<codeBook/>")
    # A half-finished download must not be reported as a file you have.
    (folder / "ipumsi_00099.csv.gz.part").write_bytes(b"incomplete")

    names = [p.name for p in client.local_files(99, dest=tmp_path)]
    assert names == ["ipumsi_00099.csv.gz", "ipumsi_00099.xml"]


def test_download_streams_verifies_and_reports_progress(client, tmp_path, monkeypatch):
    import hashlib

    payload = b"x" * 3_000_000
    digest = hashlib.sha256(payload).hexdigest()
    info = {
        "number": 7,
        "status": "completed",
        "downloadLinks": {
            "data": {"url": "https://example/d.csv.gz", "bytes": len(payload), "sha256": digest}
        },
    }
    monkeypatch.setattr(client, "status", lambda number: info)

    class FakeResponse:
        status_code = 200
        content = payload

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1 << 20):
            for i in range(0, len(payload), chunk_size):
                yield payload[i : i + chunk_size]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse())

    seen = []
    paths = client.download(7, dest=tmp_path, which=("data",),
                            on_progress=lambda n, d, t: seen.append((d, t)))

    assert paths[0].read_bytes() == payload
    assert not list(paths[0].parent.glob("*.part")), "temp file left behind"
    assert seen[-1] == (len(payload), len(payload))
    assert [d for d, _ in seen] == sorted(d for d, _ in seen), "progress went backwards"


def test_download_rejects_a_corrupt_file(client, tmp_path, monkeypatch):
    info = {
        "number": 7,
        "status": "completed",
        "downloadLinks": {
            "data": {"url": "https://example/d", "bytes": 4, "sha256": "not-the-right-hash"}
        },
    }
    monkeypatch.setattr(client, "status", lambda number: info)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1 << 20):
            yield b"data"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse())

    with pytest.raises(IpumsAPIError, match="checksum mismatch"):
        client.download(7, dest=tmp_path, which=("data",))
    # A file that failed verification must not be left lying around.
    assert not (tmp_path / "ipumsi_00007" / "d").exists()
