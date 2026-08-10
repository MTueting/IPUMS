import streamlit as st

from app_shared import (
    OPTIONAL,
    REQUIRED,
    add_variable,
    availability_chart,
    availability_status,
    catalog,
    frequencies,
    frequency_chart,
    get_selection,
    sticky,
    variable_pickers,
)

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
        with st.container(horizontal=True):
            if st.button("Add to must have", icon=":material/push_pin:", type="primary"):
                add_variable(row["variable"], REQUIRED)
                st.rerun()
            if st.button("Add to nice to have", icon=":material/add:"):
                add_variable(row["variable"], OPTIONAL)
                st.rerun()

    # Seed the selection from the row so the chart below is never empty.
    if not any(get_selection()):
        add_variable(row["variable"], REQUIRED)

st.subheader("Availability")
required, optional = variable_pickers(cat, page="browse")
if not required and not optional:
    st.info("Select a row above, or pick variables here, to see where they are available.")
    st.stop()

# This chart answers "can I use this sample at all", which is the must-have
# question. Nice-to-haves never disqualify a sample, so scoring them here would
# paint usable country-years orange; the Coverage page scores them instead.
focus = required or optional
if required and optional:
    st.caption(
        f"Showing the {len(required)} must-have variable(s). The "
        f"{len(optional)} nice-to-have one(s) are scored on the Coverage page."
    )

data = availability_status(cat, focus)
if data.empty:
    st.warning("None of these variables are harmonised in any sample.")
    st.stop()

complete = data[data["n_variables_present"] == len(focus)]
if len(focus) == 1:
    st.caption(f"{len(data)} samples across {data['country'].nunique()} countries")
else:
    st.caption(
        f"All {len(focus)} variables together: **{len(complete)} samples** across "
        f"**{complete['country'].nunique()} countries**. "
        f"{len(data)} samples carry at least one."
    )

st.altair_chart(availability_chart(data, len(focus)))

if len(focus) > 1 and complete.empty:
    st.warning(
        "No single sample carries all of these at once. The orange cells show where "
        "some are present — either drop whichever variable the tooltips keep listing "
        "as missing, or move it to nice-to-have."
    )

with st.expander("Sample list"):
    show = complete if len(focus) > 1 else data
    st.dataframe(
        show[["sample_id", "country", "year", "kind", "subsample"]].sort_values("sample_id"),
        hide_index=True,
    )

# --- Case counts -----------------------------------------------------------
# Availability tells you a variable exists in a sample; the case counts tell you
# whether it is actually populated. A variable can be "available" and still be
# 85% unknown, which is worth seeing before it goes into an extract.
if len(focus) == 1:
    st.subheader("Case counts")
    variable = focus[0]
    ordered = data.sort_values(["year", "sample_id"])
    usable = ordered["sample_id"].tolist()
    labels = dict(zip(ordered["sample_id"], ordered["description"]))
    with st.container(horizontal=True):
        chosen = st.multiselect(
            "Samples to profile",
            usable,
            default=usable[-1:],  # most recent, not last alphabetically
            format_func=lambda s: f"{s} — {labels.get(s, '')}",
            max_selections=3,
            help="Up to three, so the colours stay distinguishable.",
        )
        top_n = sticky("slider", "Categories shown", "brw_topn",
                       default=15, min_value=5, max_value=40)

    if not chosen:
        st.info("Pick a sample to see how the variable's categories are distributed.")
    else:
        try:
            counts = frequencies(variable)
        except Exception as exc:  # noqa: BLE001 - network/layout issues surface here
            st.warning(f"Could not load case counts for {variable}: {exc}")
        else:
            subset = counts[counts["sample_id"].isin(chosen)]
            if subset.empty:
                st.info(f"IPUMS publishes no case counts for {variable} in these samples.")
            else:
                populated = subset[subset["count"] > 0]
                unknown = populated[populated["label"].str.contains(
                    "unknown|not reported|niu|missing", case=False, na=False
                )]
                if not unknown.empty:
                    worst = unknown.groupby("sample_id")["share"].sum().max()
                    if worst > 0.25:
                        st.warning(
                            f"Up to {worst:.0%} of cases fall in unknown / not-in-universe "
                            "categories in the selected sample(s) — the variable is present "
                            "but thinly populated."
                        )
                st.altair_chart(frequency_chart(subset, chosen, top_n))
                with st.expander("Full category table"):
                    st.dataframe(
                        subset[["sample_id", "code", "label", "count", "share"]]
                        .sort_values(["sample_id", "count"], ascending=[True, False]),
                        hide_index=True,
                        column_config={
                            "sample_id": st.column_config.TextColumn("Sample", width="small"),
                            "code": st.column_config.TextColumn("Code", width="small"),
                            "label": st.column_config.TextColumn("Category", width="large"),
                            "count": st.column_config.NumberColumn("Cases", format="localized"),
                            "share": st.column_config.NumberColumn("Share", format="percent"),
                        },
                    )
else:
    st.caption("Select a single variable to profile its case counts.")
