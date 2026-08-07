import json
import logging
import queue
import threading

import streamlit as st

from app_shared import catalog, clear_catalog_cache
from ipumsi import config
from ipumsi.scrape.build import build_catalog

cat = catalog(required=False)

st.subheader("Catalog")
if cat is None:
    st.warning("No catalog yet. Build one with the refresh button below.")
else:
    meta = cat.meta
    with st.container(horizontal=True):
        st.metric("Variables", f"{meta.get('n_variables', len(cat.variables)):,}")
        st.metric("Samples", f"{meta.get('n_samples', len(cat.samples)):,}")
        st.metric("Countries", f"{meta.get('n_countries', 0):,}")
        st.metric("Variable × sample pairs", f"{meta.get('n_variable_sample_pairs', 0):,}")
    st.caption(f"Scraped {meta.get('scraped_at', 'unknown')} from {meta.get('source', 'IPUMS')}")

st.subheader("Refresh")
st.write(
    "Re-scrapes the IPUMS browse pages and rewrites `data/`. IPUMS revises its "
    "harmonised samples a few times a year, so quarterly is plenty."
)

with st.container(horizontal=True):
    ignore_cache = st.toggle(
        "Ignore page cache",
        value=False,
        help=(
            "Off: pages already in .cache/ are reused, so an interrupted refresh "
            "resumes almost instantly. On: re-fetches all ~2,400 pages."
        ),
    )
    start = st.button("Refresh catalog", icon=":material/refresh:", type="primary")

st.caption(
    "About 2,400 requests, one at a time with a courtesy delay — roughly 10 minutes "
    "from cold. Leave this page open; navigating away cancels it."
)


class _QueueHandler(logging.Handler):
    """Pipe the scraper's log lines to the UI thread."""

    def __init__(self, sink: queue.Queue):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink.put(record.getMessage())


def _run(sink: queue.Queue, refresh: bool):
    handler = _QueueHandler(sink)
    handler.setLevel(logging.INFO)
    scraper_log = logging.getLogger("ipumsi.scrape")
    scraper_log.setLevel(logging.INFO)
    scraper_log.addHandler(handler)
    try:
        frames = build_catalog(refresh=refresh)
        sink.put(("done", {name: len(df) for name, df in frames.items()}))
    except Exception as exc:  # noqa: BLE001 - reported in the UI
        sink.put(("error", str(exc)))
    finally:
        scraper_log.removeHandler(handler)


if start:
    sink: queue.Queue = queue.Queue()
    worker = threading.Thread(target=_run, args=(sink, ignore_cache), daemon=True)
    worker.start()

    progress = st.progress(0.0, text="Starting…")
    log_box = st.empty()
    lines: list[str] = []
    result = None

    # The scraper reports "availability: N/M variables", which is the only phase
    # long enough to be worth a real progress bar.
    while worker.is_alive() or not sink.empty():
        try:
            item = sink.get(timeout=0.5)
        except queue.Empty:
            continue
        if isinstance(item, tuple):
            result = item
            break
        lines.append(item)
        fraction = 0.0
        if "availability:" in item and "/" in item:
            try:
                done, total = item.split("availability:")[1].split("variables")[0].strip().split("/")
                fraction = int(done) / int(total)
            except (ValueError, IndexError):
                pass
        progress.progress(min(fraction, 0.99), text=item[:110])
        log_box.code("\n".join(lines[-12:]), language="text")

    if result and result[0] == "done":
        progress.progress(1.0, text="Done")
        clear_catalog_cache()
        st.success("Catalog rebuilt.")
        st.dataframe(
            [{"table": k, "rows": v} for k, v in result[1].items()], hide_index=True
        )
        st.caption(f"Written to {config.DATA_DIR}")
        if st.button("Reload the app with the new catalog", icon=":material/check:"):
            st.rerun()
    elif result:
        progress.empty()
        st.error(f"Refresh failed: {result[1]}")
        st.caption("Nothing was overwritten — the previous catalog is still in place.")
    else:
        progress.empty()
        st.warning("Refresh stopped before finishing.")

with st.expander("Or refresh from the command line"):
    st.code("ipumsi refresh          # resume from cache\nipumsi refresh --refresh  # re-fetch everything", language="bash")
    st.caption(
        "The command line is the better option for an unattended rebuild — it does "
        "not depend on this page staying open."
    )

st.subheader("API key")
try:
    config.api_key()
    st.success("An IPUMS API key is configured; extract submission is enabled.")
except config.MissingAPIKey as exc:
    st.info(str(exc))

st.subheader("Current selection")
required = st.session_state.get("required_vars", [])
optional = st.session_state.get("optional_vars", [])
if not required and not optional:
    st.caption("Nothing selected yet.")
else:
    st.json({"must_have": required, "nice_to_have": optional})
    if st.button("Clear selection", icon=":material/delete:"):
        st.session_state["required_vars"] = []
        st.session_state["optional_vars"] = []
        st.rerun()
