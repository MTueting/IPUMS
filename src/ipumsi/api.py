"""Client for the IPUMS extract API (https://api.ipums.org).

Submit a request, poll it to completion, download the files. Extract processing
is genuinely slow -- minutes to hours for large international samples -- so
:meth:`IpumsClient.wait` polls on a long interval and every call is resumable
from the extract number alone.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import API_BASE, API_VERSION, COLLECTION, EXTRACT_DIR, USER_AGENT, api_key
from .extract import ExtractDefinition

log = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "canceled"}


class IpumsAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class IpumsClient:
    def __init__(
        self,
        key: str | None = None,
        collection: str = COLLECTION,
        base_url: str = API_BASE,
        timeout: float = 120.0,
    ):
        self.key = api_key(key)
        self.collection = collection
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": self.key, "User-Agent": USER_AGENT}
        )

    # ------------------------------------------------------------- internals

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        params = {"collection": self.collection, "version": API_VERSION}
        params.update(kwargs.pop("params", {}))
        response = self.session.request(
            method, url, params=params, timeout=self.timeout, **kwargs
        )
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:1000]
            raise IpumsAPIError(
                f"{method} {url} -> {response.status_code}: {body}",
                status_code=response.status_code,
                body=body,
            )
        return response.json() if response.content else None

    # --------------------------------------------------------------- extracts

    def submit(self, definition: ExtractDefinition | dict) -> dict:
        """POST an extract request. Returns the API response (``number`` is the ID)."""
        payload = definition.to_json() if isinstance(definition, ExtractDefinition) else definition
        result = self._request("POST", "/extracts", json=payload)
        log.info("submitted extract %s (%s)", result.get("number"), result.get("status"))
        return result

    def status(self, number: int) -> dict:
        return self._request("GET", f"/extracts/{number}")

    def list_extracts(self, limit: int = 25) -> list[dict]:
        result = self._request("GET", "/extracts", params={"pageSize": limit})
        if isinstance(result, dict):
            return result.get("data", [])
        return result or []

    def recent(self, limit: int = 25) -> list[dict]:
        """Recent extracts, flattened into something a table can render.

        Note the two different meanings of "completed": IPUMS keeps the extract
        record forever but removes the files after a while, so a completed
        extract with no ``downloadLinks`` cannot be downloaded -- it has to be
        resubmitted. ``downloadable`` is the flag that actually matters.
        """
        out = []
        for entry in self.list_extracts(limit=limit):
            definition = entry.get("extractDefinition") or {}
            links = entry.get("downloadLinks") or {}
            data = links.get("data") or {}
            out.append(
                {
                    "number": entry.get("number"),
                    "status": entry.get("status"),
                    "description": definition.get("description") or "",
                    "n_samples": len(definition.get("samples") or {}),
                    "n_variables": len(definition.get("variables") or {}),
                    "data_format": definition.get("dataFormat"),
                    "bytes": int(data.get("bytes") or 0),
                    "files": sorted(links),
                    "downloadable": bool(links),
                    "expired": entry.get("status") == "completed" and not links,
                }
            )
        return out

    def local_files(self, number: int, dest: str | Path | None = None) -> list[Path]:
        """Files already downloaded for this extract, if any."""
        folder = Path(dest or EXTRACT_DIR) / f"{self.collection}_{number:05d}"
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix != ".part")

    def wait(
        self,
        number: int,
        poll_seconds: float = 60.0,
        timeout_seconds: float | None = 6 * 3600,
        on_poll=None,
    ) -> dict:
        """Poll until the extract reaches a terminal status."""
        started = time.monotonic()
        while True:
            info = self.status(number)
            state = info.get("status")
            if on_poll:
                on_poll(info)
            log.info("extract %s: %s", number, state)
            if state in TERMINAL_STATUSES:
                if state != "completed":
                    raise IpumsAPIError(f"extract {number} ended with status {state!r}", body=info)
                return info
            if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                raise TimeoutError(
                    f"extract {number} still {state!r} after {timeout_seconds:.0f}s; "
                    f"re-check later with `ipumsi status {number}`"
                )
            time.sleep(poll_seconds)

    # -------------------------------------------------------------- downloads

    def download(
        self,
        number: int,
        dest: str | Path | None = None,
        which: Iterable[str] = ("data", "ddiCodebook"),
        overwrite: bool = False,
        on_progress=None,
    ) -> list[Path]:
        """Download files from a completed extract.

        ``which`` names keys of the API's ``downloadLinks`` object. Which keys
        exist depends on the request's ``dataFormat`` -- a CSV extract offers
        ``data``, ``ddiCodebook``, ``basicCodebook`` and ``stsCommandFile``.
        Pass ``which="all"`` for whatever the extract actually has.

        ``on_progress(name, downloaded_bytes, total_bytes)`` is called as each
        file streams; data files run to hundreds of megabytes, so a caller with
        a UI needs to be able to show something.
        """
        info = self.status(number)
        if info.get("status") != "completed":
            raise IpumsAPIError(
                f"extract {number} is {info.get('status')!r}, not completed", body=info
            )
        links = info.get("downloadLinks", {})
        if not links:
            # IPUMS removes the files after a while; the extract stays "completed".
            raise IpumsAPIError(
                f"extract {number} is completed but its files are no longer on the "
                "IPUMS servers (they expire after a period). Resubmit the request "
                "to regenerate it.",
                body=info,
            )
        keys = list(links) if which == "all" else [k for k in which if k in links]
        skipped = [k for k in (which if which != "all" else []) if k not in links]
        if skipped:
            log.warning("extract %s has no %s link(s); available: %s",
                        number, ", ".join(skipped), ", ".join(sorted(links)))

        dest = Path(dest or EXTRACT_DIR) / f"{self.collection}_{number:05d}"
        dest.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        for key in keys:
            link = links[key]
            url = link["url"]
            path = dest / url.rsplit("/", 1)[-1]
            if path.exists() and not overwrite and path.stat().st_size == link.get("bytes", -1):
                log.info("%s already downloaded", path.name)
                written.append(path)
                continue

            total = int(link.get("bytes") or 0)
            log.info("downloading %s (%s bytes)", path.name, total)
            with self.session.get(url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                digest = hashlib.sha256()
                done = 0
                # Write to a .part file so an interrupted download can never be
                # mistaken for a complete one on the next run.
                partial = path.with_suffix(path.suffix + ".part")
                with open(partial, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(path.name, done, total)
                partial.replace(path)
            expected = link.get("sha256")
            if expected and digest.hexdigest() != expected:
                path.unlink(missing_ok=True)
                raise IpumsAPIError(
                    f"checksum mismatch for {path.name}: expected {expected}, "
                    f"got {digest.hexdigest()}"
                )
            written.append(path)

        return written
