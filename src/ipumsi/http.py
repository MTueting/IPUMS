"""A deliberately polite HTTP session for scraping the IPUMS website.

IPUMS publishes no metadata API for its microdata collections, so the catalog
has to come off the public HTML pages. This module keeps that well-behaved:
one request at a time, a fixed delay between them, retries with backoff, and an
on-disk cache so a re-run costs nothing.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import requests

from .config import CACHE_DIR, USER_AGENT

log = logging.getLogger(__name__)

DEFAULT_DELAY = 0.34  # seconds between requests (~3/s ceiling)


class Fetcher:
    def __init__(
        self,
        cache_dir: Path | None = None,
        delay: float = DEFAULT_DELAY,
        use_cache: bool = True,
        timeout: float = 60.0,
        max_retries: int = 4,
    ):
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self.delay = delay
        self.use_cache = use_cache
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.html"

    def get(self, url: str, refresh: bool = False) -> str:
        """Return the decoded body of ``url``, using the disk cache when possible."""
        path = self._cache_path(url)
        if self.use_cache and not refresh and path.exists():
            return path.read_text(encoding="utf-8")

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(
                        f"{response.status_code} for {url}", response=response
                    )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - retry on anything transient
                last_error = exc
                backoff = 2.0 * (2**attempt)
                log.warning("GET %s failed (%s); retrying in %.0fs", url, exc, backoff)
                time.sleep(backoff)
                continue

            # IPUMS pages declare utf-8; requests sometimes guesses latin-1.
            response.encoding = response.encoding or "utf-8"
            if response.encoding.lower() in ("iso-8859-1", "latin-1"):
                response.encoding = "utf-8"
            text = response.text
            if self.use_cache:
                path.write_text(text, encoding="utf-8")
            return text

        raise RuntimeError(f"GET {url} failed after {self.max_retries} attempts") from last_error
