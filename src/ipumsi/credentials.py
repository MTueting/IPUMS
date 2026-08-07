"""One place that knows where API keys live, and how to check they work.

One key is involved, and it is not needed to browse the catalog:

* ``IPUMS_API_KEY`` -- submitting and downloading extracts

Resolution order, first match wins:

1. an explicit argument (or a Streamlit-session override, for keys the user
   typed in but chose not to persist)
2. the ``IPUMS_API_KEY`` environment variable
3. a ``.env`` file at the repo root
4. ``~/.ipumsi/credentials.json`` -- what the app writes when you save a key
5. the legacy single-key dotfile ``~/.ipums_api_key``

Keys are stored outside the repository on purpose, so a saved key can never be
committed by accident.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

CONFIG_DIR = Path(os.environ.get("IPUMSI_CONFIG_DIR", Path.home() / ".ipumsi"))
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"


class MissingKey(RuntimeError):
    """Raised when a key is needed and none could be found."""

    def __init__(self, name: str):
        spec = SPECS[name]
        super().__init__(
            f"No {spec.label} found. Add one on the Settings page of the app, set "
            f"the {name} environment variable, or copy .env.example to .env. "
            f"Get a key at {spec.signup_url}"
        )
        self.name = name


@dataclass(frozen=True)
class KeySpec:
    name: str
    label: str
    signup_url: str
    what_it_unlocks: str
    legacy_file: str
    prefix: str | None = None  # a soft format check, not a hard rule

    @property
    def legacy_path(self) -> Path:
        return Path.home() / self.legacy_file


SPECS: dict[str, KeySpec] = {
    "IPUMS_API_KEY": KeySpec(
        name="IPUMS_API_KEY",
        label="IPUMS API key",
        signup_url="https://account.ipums.org/api_keys",
        what_it_unlocks="Submitting extracts and downloading data.",
        legacy_file=".ipums_api_key",
    ),
}


# ------------------------------------------------------------------ storage


def _read_store() -> dict[str, str]:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _read_dotenv(name: str) -> str | None:
    dotenv = ROOT / ".env"
    if not dotenv.exists():
        return None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            # .env.example ships placeholders; don't mistake one for a real key.
            if value and not value.startswith("your_"):
                return value
    return None


def save_key(name: str, value: str) -> Path:
    """Persist a key to ``~/.ipumsi/credentials.json`` for this user only."""
    if name not in SPECS:
        raise KeyError(name)
    value = value.strip()
    if not value:
        raise ValueError("empty key")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store = _read_store()
    store[name] = value
    CREDENTIALS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    try:
        # Best effort: meaningful on POSIX, largely cosmetic on Windows.
        CREDENTIALS_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return CREDENTIALS_FILE


def write_dotenv(name: str, value: str) -> Path:
    """Write a key into the project's ``.env``, replacing any existing line.

    ``.env`` is gitignored, so this stays out of version control -- but it does
    sit next to the code, so it travels if the folder is copied or shared.
    """
    if name not in SPECS:
        raise KeyError(name)
    value = value.strip()
    if not value:
        raise ValueError("empty key")

    dotenv = ROOT / ".env"
    lines = dotenv.read_text(encoding="utf-8").splitlines() if dotenv.exists() else []
    kept = [ln for ln in lines if not ln.strip().startswith(f"{name}=")]
    kept.append(f"{name}={value}")
    dotenv.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")
    return dotenv


def delete_key(name: str) -> bool:
    """Remove a saved key. Returns True if one was there."""
    store = _read_store()
    if name not in store:
        return False
    del store[name]
    if store:
        CREDENTIALS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    else:
        CREDENTIALS_FILE.unlink(missing_ok=True)
    return True


# ------------------------------------------------------------------ lookup


def find_key(name: str, explicit: str | None = None) -> tuple[str | None, str]:
    """Return ``(key, source)``; ``key`` is None when nothing was found."""
    if name not in SPECS:
        raise KeyError(name)
    spec = SPECS[name]

    if explicit and explicit.strip():
        return explicit.strip(), "provided"

    env = os.environ.get(name, "").strip()
    if env:
        return env, f"{name} environment variable"

    dotenv = _read_dotenv(name)
    if dotenv:
        return dotenv, ".env file"

    stored = _read_store().get(name, "").strip()
    if stored:
        return stored, str(CREDENTIALS_FILE)

    if spec.legacy_path.exists():
        legacy = spec.legacy_path.read_text(encoding="utf-8").strip()
        if legacy:
            return legacy, str(spec.legacy_path)

    return None, "not set"


def get_key(name: str, explicit: str | None = None) -> str:
    """Resolve a key or raise :class:`MissingKey`."""
    key, _ = find_key(name, explicit)
    if not key:
        raise MissingKey(name)
    return key


def has_key(name: str) -> bool:
    return find_key(name)[0] is not None


def mask(key: str) -> str:
    """A recognisable fingerprint that is useless if it leaks."""
    # ASCII only: this is printed to Windows consoles that are not UTF-8.
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


# ------------------------------------------------------------- verification


def verify_key(name: str, key: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Check a key against the live API. Returns ``(ok, message)``.

    Worth doing before saving: a typo here otherwise surfaces much later, as a
    confusing failure in the middle of an extract.
    """
    key = key.strip()
    if not key:
        return False, "The key is empty."

    spec = SPECS[name]
    if spec.prefix and not key.startswith(spec.prefix):
        return False, f"An {spec.label} normally starts with {spec.prefix!r}."

    if name == "IPUMS_API_KEY":
        return _verify_ipums(key, timeout)
    return True, "No check available for this key."


def _verify_ipums(key: str, timeout: float) -> tuple[bool, str]:
    import requests

    from .config import API_BASE, API_VERSION, COLLECTION, USER_AGENT

    try:
        response = requests.get(
            f"{API_BASE}/extracts",
            params={"collection": COLLECTION, "version": API_VERSION, "pageSize": 1},
            headers={"Authorization": key, "User-Agent": USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"Could not reach the IPUMS API: {exc}"

    if response.status_code == 200:
        return True, "Key works - the IPUMS API accepted it."
    if response.status_code in (401, 403):
        return False, (
            "IPUMS rejected this key. Check it at https://account.ipums.org/api_keys, "
            "and that your account has IPUMS International access approved."
        )
    return False, f"Unexpected response from IPUMS ({response.status_code})."
