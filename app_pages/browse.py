import streamlit as st

from app_shared import availability_chart, availability_status, catalog, variable_picker

cat = catalog()
meta = cat.meta

st.caption(
    f"{meta.get('n_variables', len(cat.variables)):,} variables · "
    f"{meta.get('n_samples', len(cat.samples)):,} samples · "
    f"scraped {meta.get('scraped_at', 'unknown')}"
)

with st.container(horizontal=True):
    query = st.text_input(
        "Search", placeholder="migration, income, subnational…", label_visibility="collapsed"
    )
    record_type = st.segmented_control(
        "Record type", ["All", "P", "H"], default="All", label_visibility="collapsed"
    )
    group = st.selectbox(
        "Group",
        ["All groups"] + sorted(cat.variables["group_label"].dropna().unique()),
        label_visibility="collapsed",
    )

hits = cat.search(query, record_type=None if record_type in (None, "All") else record_type)
if group != "All groups":
    hits = hits[hits["group_label"] == group]

st.write(f"{len(hits):,} variables")

event = st.dataframe(
    hits[["variable", "label", "record_type", "n_countries", "n_samples", "group_label"]],
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "variable": st.column_config.TextColumn("Mnemonic", width="small"),
        "label": st.column_config.TextColumn("Label", width="large"),
        "record_type": st.column_config.TextColumn("Rec", width="small"),
        "n_countries": st.column_config.NumberColumn("Countries", width="small"),
        "n_samples": st.column_config.NumberColumn("Samples", width="small"),
        "group_label": st.column_config.TextColumn("Group"),
    },
    height=340,
)

rows = event.selection.get("rows", []) if event and event.selection else []
if rows:
    row = hits.iloc[rows[0]]
    with st.container(border=True):
        st.subheader(f"{row['variable']} — {row['label']}")
        st.caption(
            f"{row['group_label']} · record type {row['record_type']} · "
            f"[IPUMS page]({row['url']})"
        )
        if isinstance(row.get("description"), str) and row["description"]:
            st.write(row["description"])
        if st.button("Add to selection", icon=":material/add:", type="primary"):
            if row["variable"] not in st.session_state.selected_variables:
                st.session_state.selected_variables = (
                    st.session_state.selected_variables + [row["variable"]]
                )
                st.rerun()

    # Seed the availability selection from the row so the chart is never empty.
    if not st.session_state.selected_variables:
        st.session_state.selected_variables = [row["variable"]]

st.subheader("Availability")
variables = variable_picker(cat)
if not variables:
    st.info("Select a row above, or pick variables here, to see where they are available.")
    st.stop()

data = availability_status(cat, variables)
if data.empty:
    st.warning("None of these variables are harmonised in any sample.")
    st.stop()

complete = data[data["n_variables_present"] == len(variables)]
if len(variables) == 1:
    st.caption(f"{len(data)} samples across {data['country'].nunique()} countries")
else:
    st.caption(
        f"All {len(variables)} variables together: **{len(complete)} samples** across "
        f"**{complete['country'].nunique()} countries**. "
        f"{len(data)} samples carry at least one."
    )

st.altair_chart(availability_chart(data, len(variables)))

if len(variables) > 1 and complete.empty:
    st.warning(
        "No single sample carries all of these at once. The orange cells show where "
        "some are present — drop whichever variable the tooltips keep listing as missing."
    )

with st.expander("Sample list"):
    show = complete if len(variables) > 1 else data
    st.dataframe(
        show[["sample_id", "country", "year", "kind", "subsample"]].sort_values("sample_id"),
        hide_index=True,
    )
