"""Paths, endpoints and API-key resolution."""

from __future__ import annotations

import os
from pathlib import Path

# Repo layout: <root>/src/ipumsi/config.py
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("IPUMSI_DATA_DIR", ROOT / "data"))
CACHE_DIR = Path(os.environ.get("IPUMSI_CACHE_DIR", ROOT / ".cache"))
EXTRACT_DIR = Path(os.environ.get("IPUMSI_EXTRACT_DIR", ROOT / "extracts"))

# Catalog artifacts (committed to the repo so the package works offline).
SAMPLES_CSV = DATA_DIR / "samples.csv"
VARIABLES_CSV = DATA_DIR / "variables.csv"
AVAILABILITY_PARQUET = DATA_DIR / "availability.parquet"
VAR_SAMPLES_PARQUET = DATA_DIR / "variable_samples.parquet"
COUNTRIES_CSV = DATA_DIR / "countries.csv"
CATALOG_META = DATA_DIR / "catalog_meta.json"

# Website (scraped -- IPUMS has no metadata API for microdata collections).
SITE = "https://international.ipums.org/international-action"
SAMPLE_IDS_URL = f"{SITE}/samples/sample_ids"
GROUP_INDEX_URL = f"{SITE}/variables/group"
VARIABLE_URL = f"{SITE}/variables/{{var}}"

# Extract API.
API_BASE = "https://api.ipums.org"
COLLECTION = "ipumsi"
API_VERSION = 2

USER_AGENT = (
    "ipumsi-catalog/0.1 (+https://github.com/; research metadata harvesting; "
    "contact via repository issues)"
)


def api_key(explicit: str | None = None) -> str:
    """Resolve the IPUMS API key. See :mod:`ipumsi.credentials` for the search order."""
    from .credentials import get_key

    return get_key("IPUMS_API_KEY", explicit)


def __getattr__(name: str):
    # `MissingAPIKey` moved to ipumsi.credentials.MissingKey; keep the old name
    # importable so existing code and notebooks don't break.
    if name == "MissingAPIKey":
        from .credentials import MissingKey

        return MissingKey
    raise AttributeError(name)
