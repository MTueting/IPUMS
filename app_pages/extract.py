import json

import streamlit as st

from app_keys import require_key, resume_after_key
from app_shared import catalog, sample_filters, tier_summary, variable_pickers
from ipumsi.extract import ExtractDefinition

cat = catalog()

st.write(
    "Assemble an IPUMS extract request from the catalog, check it before it is sent, "
    "then download the JSON or submit it directly."
)

required, optional = variable_pickers(cat, page="extract")
if not required and not optional:
    st.info("Pick the variables you want. Anything selected on Browse or Coverage is already here.")
    st.stop()
tier_summary(required, optional)

filters = sample_filters(cat, prefix="ext")

with st.container(horizontal=True):
    data_format = st.selectbox("Data format", ["csv", "fixed_width", "stata", "spss", "sas9"])
    structure = st.segmented_control(
        "Structure", ["Rectangular (person)", "Hierarchical"], default="Rectangular (person)"
    )

candidates = cat.samples_for(required, optional, **filters)
if candidates.empty:
    st.warning("No sample carries every must-have variable. Loosen the filters or move one to nice-to-have.")
    st.stop()

st.subheader(f"{len(candidates)} candidate samples")
if optional:
    st.caption(
        "Every candidate satisfies all must-haves. The number in brackets is how many "
        "nice-to-haves that sample adds."
    )
    extras = dict(zip(candidates["sample_id"], candidates["n_optional_present"]))
else:
    extras = {}

descriptions = dict(zip(candidates["sample_id"], candidates["description"]))


def _label(sample: str) -> str:
    base = f"{sample} — {descriptions.get(sample, '')}"
    return f"{base}  [+{extras[sample]}/{len(optional)}]" if extras else base


chosen = st.multiselect(
    "Samples to include",
    candidates["sample_id"].tolist(),
    default=candidates["sample_id"].tolist(),
    format_func=_label,
)
if not chosen:
    st.warning("Select at least one sample.")
    st.stop()

description = st.text_input(
    "Extract description",
    value=f"ipumsi: {', '.join(required[:4])}" + (" …" if len(required) > 4 else ""),
)

definition = ExtractDefinition(
    samples=chosen,
    variables=required + optional,
    description=description,
    data_format=data_format,
    hierarchical=(structure == "Hierarchical"),
    rectangular_on=None if structure == "Hierarchical" else "P",
)

# Nice-to-haves are expected to be patchy -- that was the point of the tier -- so
# only must-haves count as validation problems.
problems = definition.validate(cat, optional=optional)
if problems:
    st.warning(
        "This request asks for combinations IPUMS does not harmonise — those columns "
        "come back entirely missing rather than erroring:\n\n"
        + "\n".join(f"- {p}" for p in problems)
    )
else:
    st.success("Every must-have variable is available in every selected sample.")

report = definition.coverage_report(cat)
patchy = report[report["samples_missing"] > 0]
if not patchy.empty:
    with st.expander(f"{len(patchy)} variable(s) will be blank in some samples"):
        st.caption("Expected for nice-to-haves; worth a look if a must-have shows up here.")
        st.dataframe(
            patchy[["variable", "samples_present", "samples_missing", "share"]],
            hide_index=True,
            column_config={
                "variable": st.column_config.TextColumn("Variable"),
                "samples_present": st.column_config.NumberColumn("Present in", width="small"),
                "samples_missing": st.column_config.NumberColumn("Blank in", width="small"),
                "share": st.column_config.ProgressColumn(
                    "Coverage", min_value=0.0, max_value=1.0, format="percent"
                ),
            },
        )

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

    submit = st.button("Submit to IPUMS", type="primary", icon=":material/send:")

if submit or resume_after_key("IPUMS_API_KEY"):
    from ipumsi.api import IpumsClient

    key = require_key("IPUMS_API_KEY", "Submitting an extract")
    if not key:
        st.stop()

    with st.spinner("Submitting…"):
        try:
            result = IpumsClient(key=key).submit(definition)
        except Exception as exc:  # noqa: BLE001 - surface the API's message verbatim
            st.error(f"Submission failed: {exc}")
        else:
            number = result.get("number")
            st.success(f"Submitted as extract {number} ({result.get('status')}).")
            st.caption(
                "IPUMS processes international extracts in minutes to hours. "
                "The **Downloads** page lists it and fetches the files when ready."
            )
