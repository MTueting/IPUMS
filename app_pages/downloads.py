import streamlit as st

from app_keys import require_key
from app_shared import human_bytes
from ipumsi.api import IpumsAPIError, IpumsClient
from ipumsi.config import EXTRACT_DIR

st.write(
    "Extracts you have submitted to IPUMS. Submitting only queues the job — "
    "IPUMS takes minutes to hours to build it, and the files are fetched here."
)

key = require_key("IPUMS_API_KEY", "Listing your extracts")
if not key:
    st.stop()

client = IpumsClient(key=key)

@st.cache_data(show_spinner="Asking IPUMS…", ttl=60)
def _recent(_key: str, n: int) -> list[dict]:
    return IpumsClient(key=_key).recent(limit=n)


with st.container(horizontal=True):
    limit = st.slider("How many to list", 5, 50, 15)
    if st.button("Refresh", icon=":material/refresh:"):
        # Only this list -- st.cache_data.clear() would also drop the catalog.
        _recent.clear()


try:
    extracts = _recent(key, limit)
except IpumsAPIError as exc:
    st.error(f"Could not list your extracts: {exc}")
    st.stop()

if not extracts:
    st.info("No extracts yet. Build one on the **Build extract** page.")
    st.stop()

ready = [e for e in extracts if e["downloadable"]]
working = [e for e in extracts if e["status"] in ("queued", "started")]
expired = [e for e in extracts if e["expired"]]

with st.container(horizontal=True):
    st.metric("Ready to download", len(ready))
    st.metric("Still processing", len(working))
    st.metric("Expired", len(expired))

st.caption(f"Files are saved to `{EXTRACT_DIR}`, one folder per extract.")

# Worth mentioning once, quietly: a single extract can be hundreds of megabytes,
# and inside a synced folder all of that goes to the cloud. Set
# IPUMSI_EXTRACT_DIR to somewhere local if that is not what you want.
SYNCED = ("dropbox", "onedrive", "google drive", "icloud", "nextcloud")
folder = str(EXTRACT_DIR).lower()
if any(name in folder for name in SYNCED):
    service = next(name for name in SYNCED if name in folder).title()
    st.caption(
        f"That folder syncs to {service}. Set `IPUMSI_EXTRACT_DIR` before starting "
        "the app to keep extracts local instead."
    )

if working:
    st.info(
        f"{len(working)} extract(s) still building at IPUMS — press Refresh in a "
        "few minutes."
    )

STATUS_ICON = {
    "completed": ":material/check_circle:",
    "queued": ":material/schedule:",
    "started": ":material/hourglass_top:",
    "failed": ":material/error:",
    "canceled": ":material/cancel:",
}

for extract in extracts:
    number = extract["number"]
    local = client.local_files(number)

    with st.container(border=True):
        header, action = st.columns([3, 1], vertical_alignment="center")
        with header:
            st.markdown(
                f"{STATUS_ICON.get(extract['status'], '')} **Extract {number}** — "
                f"{extract['description'] or '(no description)'}"
            )
            bits = [
                f"{extract['n_samples']} samples",
                f"{extract['n_variables']} variables",
                extract["status"],
            ]
            if extract["data_format"]:
                bits.append(extract["data_format"])
            if extract["bytes"]:
                bits.append(human_bytes(extract["bytes"]))
            st.caption(" · ".join(bits))

            if local:
                total = sum(p.stat().st_size for p in local)
                st.success(
                    f"Downloaded — {len(local)} file(s), {human_bytes(total)} in "
                    f"`{local[0].parent}`"
                )

        with action:
            if extract["expired"]:
                st.button(
                    "Expired", key=f"exp{number}", disabled=True,
                    help="IPUMS has removed the files. Resubmit the request to rebuild it.",
                )
            elif not extract["downloadable"]:
                st.button(
                    "Not ready", key=f"nr{number}", disabled=True,
                    help="IPUMS is still building this extract.",
                )
            else:
                everything = st.toggle(
                    "All files", key=f"all{number}",
                    help="Also fetch the codebooks and the Stata/SPSS/SAS/R command files.",
                )
                if st.button(
                    "Download", key=f"dl{number}", type="primary",
                    icon=":material/download:",
                ):
                    bar = st.progress(0.0, text="Starting…")

                    def report(name, done, total, _bar=bar):
                        fraction = (done / total) if total else 0.0
                        _bar.progress(
                            min(fraction, 1.0),
                            text=f"{name} — {human_bytes(done)} of {human_bytes(total)}",
                        )

                    try:
                        paths = client.download(
                            number,
                            which="all" if everything else ("data", "ddiCodebook"),
                            on_progress=report,
                        )
                    except IpumsAPIError as exc:
                        bar.empty()
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001 - network, disk, checksum
                        bar.empty()
                        st.error(f"Download failed: {exc}")
                    else:
                        bar.progress(1.0, text="Done")
                        st.success(f"Saved {len(paths)} file(s) to {paths[0].parent}")
                        st.rerun()

        if extract["downloadable"]:
            with st.expander("Files IPUMS has for this extract"):
                st.write(", ".join(f"`{f}`" for f in extract["files"]))

        # The data file is often hundreds of megabytes, so it is not offered as a
        # browser download; the codebook is small and useful to grab directly.
        for path in local:
            if path.stat().st_size <= 20_000_000:
                with open(path, "rb") as fh:
                    st.download_button(
                        f"Save {path.name} to your browser's downloads",
                        fh.read(),
                        file_name=path.name,
                        key=f"br{number}{path.name}",
                        icon=":material/save:",
                    )

with st.expander("Or from the command line"):
    st.code(
        "ipumsi status              # list recent extracts\n"
        "ipumsi status 99           # one extract\n"
        "ipumsi download 99         # data + codebook\n"
        "ipumsi download 99 --wait  # poll until ready, then fetch\n"
        "ipumsi download 99 --which all",
        language="bash",
    )
