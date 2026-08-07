"""In-app API key entry.

Nothing in the catalog needs a key, so the app never blocks on one. A key is
asked for at the moment it is actually required — pressing "Submit to IPUMS" or
"Suggest variables" — and the dialog explains what that specific key unlocks.

Two ways to keep it:

* **This session only** — held in ``st.session_state`` and gone when the tab
  closes. Nothing is written to disk. This is the right choice on a shared or
  hosted app, where a key written to disk would be handed to whoever opens the
  app next.
* **Save on this computer** — written to ``~/.ipumsi/credentials.json`` (user
  home, never the repo), so it is there next time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ipumsi.credentials import (  # noqa: E402
    CREDENTIALS_FILE,
    SPECS,
    delete_key,
    find_key,
    mask,
    save_key,
    verify_key,
    write_dotenv,
)

SESSION_PREFIX = "_key_"


def _session_key(name: str) -> str | None:
    return st.session_state.get(SESSION_PREFIX + name)


def _from_secrets(name: str) -> str | None:
    """Streamlit's own secrets store, used when the app is deployed."""
    try:
        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - no secrets.toml is the normal case
        return None
    return str(value).strip() if value else None


def resolve(name: str) -> tuple[str | None, str]:
    """``(key, source)`` including the two Streamlit-only sources."""
    session = _session_key(name)
    if session:
        return session, "entered for this session"
    secret = _from_secrets(name)
    if secret:
        return secret, "Streamlit secrets"
    return find_key(name)


def key_for(name: str) -> str | None:
    return resolve(name)[0]


def is_remote() -> bool:
    """True when the app is probably being served to someone else's browser.

    Used only to pick the safer default in the dialog — a key typed into a
    shared deployment should not be written to that server's disk.
    """
    try:
        host = (st.context.headers.get("host") or "").split(":")[0].lower()
    except Exception:  # noqa: BLE001 - headers unavailable in tests
        return False
    return host not in ("localhost", "127.0.0.1", "[::1]", "")


WHERE_HOME = "On this computer (recommended)"
WHERE_ENV = "In this project's .env file"
WHERE_SESSION = "Just this session"


def _save(name: str, value: str, where: str) -> str:
    st.session_state[SESSION_PREFIX + name] = value
    if where == WHERE_HOME:
        return f"Saved to {save_key(name, value)} — it will be there next time."
    if where == WHERE_ENV:
        return f"Saved to {write_dotenv(name, value)} — it will be there next time."
    return "Held for this session only. Nothing was written to disk."


def _form(name: str, *, on_saved=None) -> None:
    """The shared body of the dialog and the Settings panel."""
    spec = SPECS[name]
    st.caption(spec.what_it_unlocks)
    st.markdown(f"Get a key at [{spec.signup_url}]({spec.signup_url}).")

    remote = is_remote()
    options = [WHERE_HOME, WHERE_ENV, WHERE_SESSION]
    with st.form(f"key_form_{name}", clear_on_submit=False):
        value = st.text_input(
            spec.label,
            type="password",
            placeholder=spec.prefix + "…" if spec.prefix else "paste your key here",
            help="The key is sent only to the API it belongs to.",
        )
        where = st.radio(
            "Keep it",
            options,
            index=options.index(WHERE_SESSION if remote else WHERE_HOME),
            captions=[
                str(CREDENTIALS_FILE),
                "Alongside the code. Gitignored, so it is not committed.",
                "Nothing written to disk; gone when you close the tab.",
            ],
        )
        check = st.checkbox("Check the key works before saving", value=True)
        submitted = st.form_submit_button("Save key", type="primary", icon=":material/key:")

    if remote and where != WHERE_SESSION:
        st.warning(
            "This app looks like it is being served over a network. A key saved "
            "here is saved on the **server**, so anyone else who opens the app "
            "would be able to use it. Prefer 'just this session' unless this "
            "machine is only yours."
        )

    if not submitted:
        return
    if not value.strip():
        st.error("Paste a key first.")
        return

    if check:
        with st.spinner("Checking the key…"):
            ok, message = verify_key(name, value)
        if not ok:
            st.error(message)
            return
        st.success(message)

    st.success(_save(name, value.strip(), where))
    # Let the caller finish whatever action needed the key.
    if st.session_state.pop(f"_resume_{name}", None):
        st.session_state[f"_resumed_{name}"] = True
    if on_saved:
        on_saved()


@st.dialog("API key needed", width="medium")
def _dialog(name: str) -> None:
    def close():
        st.rerun()

    _form(name, on_saved=close)
    if st.button("Not now"):
        st.rerun()


def require_key(name: str, action: str) -> str | None:
    """Return the key, or open the entry dialog now and return None.

    The dialog opens on *this* run rather than behind a second button. Putting a
    button here would never work: it only exists while the triggering action is
    True, so clicking it starts a rerun in which the action is False, the block
    is skipped, and the button disappears without doing anything.

    ``action`` names what the user was trying to do, so the prompt explains
    itself rather than being a bare "enter a key".
    """
    key = key_for(name)
    if key:
        return key
    st.session_state[f"_resume_{name}"] = action
    _dialog(name)
    return None


def resume_after_key(name: str) -> bool:
    """True once, right after a key was saved for a pending action.

    Lets the page finish what the user originally clicked instead of making them
    click it a second time.
    """
    return bool(st.session_state.pop(f"_resumed_{name}", False))


def key_status_panel(name: str) -> None:
    """Full manage-this-key UI, for the Settings page."""
    spec = SPECS[name]
    key, source = resolve(name)

    with st.container(border=True):
        if key:
            st.success(f"**{spec.label}** is set — `{mask(key)}` (from {source})")
            st.caption(spec.what_it_unlocks)
            with st.container(horizontal=True):
                if st.button("Check it works", key=f"verify_{name}", icon=":material/check:"):
                    with st.spinner("Checking…"):
                        ok, message = verify_key(name, key)
                    (st.success if ok else st.error)(message)
                if st.button("Replace", key=f"replace_{name}", icon=":material/edit:"):
                    _dialog(name)
                if st.button("Forget", key=f"forget_{name}", icon=":material/delete:"):
                    removed = delete_key(name)
                    st.session_state.pop(SESSION_PREFIX + name, None)
                    if removed:
                        st.success("Removed from this computer.")
                    else:
                        st.info(
                            "Cleared for this session. It came from "
                            f"{source}, which this app does not manage — remove it there."
                        )
                    st.rerun()
        else:
            st.info(f"**{spec.label}** is not set. {spec.what_it_unlocks}")
            _form(name)
