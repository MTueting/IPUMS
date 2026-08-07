"""Key resolution, storage and masking.

The resolution order is the contract other people rely on: a key set one way
must not be silently shadowed by one set another way.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def creds(tmp_path, monkeypatch):
    """A credentials module pointed at a throwaway config dir and repo root."""
    monkeypatch.setenv("IPUMSI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("IPUMS_API_KEY", raising=False)

    from ipumsi import credentials

    module = importlib.reload(credentials)
    monkeypatch.setattr(module, "ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    # Legacy dotfiles live in the real home directory; point them at tmp too.
    monkeypatch.setattr(
        module.KeySpec, "legacy_path",
        property(lambda self: tmp_path / "home" / self.legacy_file),
    )
    (tmp_path / "home").mkdir()
    yield module
    importlib.reload(credentials)


def test_nothing_set(creds):
    key, source = creds.find_key("IPUMS_API_KEY")
    assert key is None and source == "not set"
    assert not creds.has_key("IPUMS_API_KEY")
    with pytest.raises(creds.MissingKey):
        creds.get_key("IPUMS_API_KEY")


def test_save_roundtrip_and_forget(creds):
    path = creds.save_key("IPUMS_API_KEY", "  abc123  ")
    assert json.loads(path.read_text())["IPUMS_API_KEY"] == "abc123"

    key, source = creds.find_key("IPUMS_API_KEY")
    assert key == "abc123"
    assert str(path) in source

    assert creds.delete_key("IPUMS_API_KEY") is True
    assert creds.find_key("IPUMS_API_KEY")[0] is None
    assert creds.delete_key("IPUMS_API_KEY") is False


def test_resolution_order(creds, monkeypatch, tmp_path):
    """Later sources must never shadow earlier ones."""
    creds.save_key("IPUMS_API_KEY", "from-store")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-store"

    (creds.ROOT / ".env").write_text("IPUMS_API_KEY=from-dotenv\n", encoding="utf-8")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-dotenv"

    monkeypatch.setenv("IPUMS_API_KEY", "from-env")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-env"

    assert creds.find_key("IPUMS_API_KEY", explicit="from-arg")[0] == "from-arg"


def test_dotenv_placeholder_is_not_a_key(creds):
    """.env.example ships `your_key_here`; that must not read as configured."""
    (creds.ROOT / ".env").write_text("IPUMS_API_KEY=your_key_here\n", encoding="utf-8")
    assert creds.find_key("IPUMS_API_KEY")[0] is None


def test_dotenv_handles_quotes_and_other_lines(creds):
    (creds.ROOT / ".env").write_text(
        "# a comment\nOTHER=1\nIPUMS_API_KEY='quoted-key'\n", encoding="utf-8"
    )
    assert creds.find_key("IPUMS_API_KEY")[0] == "quoted-key"




def test_rejects_unknown_names_and_empty_values(creds):
    with pytest.raises(KeyError):
        creds.find_key("NOT_A_KEY")
    with pytest.raises(KeyError):
        creds.save_key("NOT_A_KEY", "x")
    with pytest.raises(ValueError):
        creds.save_key("IPUMS_API_KEY", "   ")


def test_mask_is_ascii_and_hides_the_middle(creds):
    masked = creds.mask("sk-ant-api03-SECRETSECRETSECRET-1234")
    assert masked == "sk-ant...1234"
    assert masked.isascii()  # printed to non-UTF-8 Windows consoles
    assert "SECRET" not in masked
    assert creds.mask("short") == "*****"



def test_empty_key_never_verifies(creds):
    for name in creds.SPECS:
        ok, _ = creds.verify_key(name, "   ")
        assert ok is False


def test_legacy_dotfile_still_read(creds):
    legacy = creds.SPECS["IPUMS_API_KEY"].legacy_path
    legacy.write_text("legacy-key\n", encoding="utf-8")
    key, source = creds.find_key("IPUMS_API_KEY")
    assert key == "legacy-key"
    assert str(legacy) in source


def test_write_dotenv_replaces_not_appends(creds):
    dotenv = creds.ROOT / ".env"
    dotenv.write_text("OTHER=keep\nIPUMS_API_KEY=old\n", encoding="utf-8")

    creds.write_dotenv("IPUMS_API_KEY", "new")

    lines = dotenv.read_text(encoding="utf-8").splitlines()
    assert "OTHER=keep" in lines
    assert lines.count("IPUMS_API_KEY=new") == 1
    assert "IPUMS_API_KEY=old" not in lines
    assert creds.find_key("IPUMS_API_KEY")[0] == "new"


def test_write_dotenv_creates_the_file(creds):
    path = creds.write_dotenv("IPUMS_API_KEY", "fresh")
    assert path.read_text(encoding="utf-8").strip() == "IPUMS_API_KEY=fresh"
