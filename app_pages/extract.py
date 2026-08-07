import json

import streamlit as st

from app_shared import catalog, sample_filters, variable_picker
from ipumsi.config import MissingAPIKey, api_key
from ipumsi.extract import ExtractDefinition

cat = catalog()

st.write(
    "Assemble an IPUMS extract request from the catalog, check it before it is sent, "
    "then download the JSON or submit it directly."
)

variables = variable_picker(cat, key="selected_variables")
if not variables:
    st.info("Pick the variables you want in the extract.")
    st.stop()

filters = sample_filters(cat, prefix="ext")

with st.container(horizontal=True):
    require = st.segmented_control(
        "Include samples carrying",
        ["all variables", "any variable"],
        default="all variables",
    )
    data_format = st.selectbox("Data format", ["csv", "fixed_width", "stata", "spss", "sas9"])
    structure = st.segmented_control(
        "Structure", ["Rectangular (person)", "Hierarchical"], default="Rectangular (person)"
    )

how = "all" if require in (None, "all variables") else "any"
candidates = cat.samples_with(variables, how=how, **filters)

if candidates.empty:
    st.warning("No samples match. Loosen the filters or drop a variable.")
    st.stop()

st.subheader(f"{len(candidates)} candidate samples")
chosen = st.multiselect(
    "Samples to include",
    candidates["sample_id"].tolist(),
    default=candidates["sample_id"].tolist(),
    format_func=lambda s: f"{s} — {candidates.loc[candidates.sample_id == s, 'description'].iloc[0]}",
)
if not chosen:
    st.warning("Select at least one sample.")
    st.stop()

description = st.text_input(
    "Extract description",
    value=f"ipumsi: {', '.join(variables[:4])}" + (" …" if len(variables) > 4 else ""),
)

definition = ExtractDefinition(
    samples=chosen,
    variables=variables,
    description=description,
    data_format=data_format,
    hierarchical=(structure == "Hierarchical"),
    rectangular_on=None if structure == "Hierarchical" else "P",
)

problems = definition.validate(cat)
if problems:
    st.warning(
        "This request asks for combinations IPUMS does not harmonise — those columns "
        "come back entirely missing rather than erroring:\n\n"
        + "\n".join(f"- {p}" for p in problems)
    )
else:
    st.success("Every variable is available in every selected sample.")

payload = definition.to_json()
request_json = json.dumps(payload, indent=2)

request_tab, curl_tab = st.tabs(["Request JSON", "curl"])
with request_tab:
    st.code(request_json, language="json")
with curl_tab:
    st.code(definition.to_curl(), language="bash")

with st.container(horizontal=True):
    st.download_button(
        "Download request JSON",
        request_json,
        file_name="ipumsi_extract_request.json",
        mime="application/json",
        icon=":material/download:",
    )

    try:
        api_key()
        has_key = True
    except MissingAPIKey:
        has_key = False

    submit = st.button(
        "Submit to IPUMS",
        type="primary",
        icon=":material/send:",
        disabled=not has_key,
        help=None if has_key else "Set IPUMS_API_KEY to enable submission",
    )

if not has_key:
    st.caption(
        "No API key found. Set `IPUMS_API_KEY`, or copy `.env.example` to `.env`. "
        "Keys: https://account.ipums.org/api_keys"
    )

if submit:
    from ipumsi.api import IpumsClient

    with st.spinner("Submitting…"):
        try:
            result = IpumsClient().submit(definition)
        except Exception as exc:  # noqa: BLE001 - surface the API's message verbatim
            st.error(f"Submission failed: {exc}")
        else:
            number = result.get("number")
            st.success(f"Submitted as extract {number} ({result.get('status')}).")
            st.caption(
                f"IPUMS processes international extracts in minutes to hours. Check with "
                f"`ipumsi status {number}`, then `ipumsi download {number}`."
            )
