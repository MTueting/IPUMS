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


class MissingAPIKey(RuntimeError):
    pass


def api_key(explicit: str | None = None) -> str:
    """Resolve the IPUMS API key.

    Order: explicit argument, ``IPUMS_API_KEY`` env var, a ``.env`` file at the
    repo root, then ``~/.ipums_api_key``.
    """
    if explicit:
        return explicit.strip()

    if os.environ.get("IPUMS_API_KEY"):
        return os.environ["IPUMS_API_KEY"].strip()

    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("IPUMS_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value and value != "your_key_here":
                    return value

    keyfile = Path.home() / ".ipums_api_key"
    if keyfile.exists():
        value = keyfile.read_text(encoding="utf-8").strip()
        if value:
            return value

    raise MissingAPIKey(
        "No IPUMS API key found. Set IPUMS_API_KEY, copy .env.example to .env, "
        "or write the key to ~/.ipums_api_key. Keys: https://account.ipums.org/api_keys"
    )
