import altair as alt
import streamlit as st

from app_shared import (
    AXIS_GREY,
    _mode,
    availability_chart,
    availability_status,
    catalog,
    coverage_chart,
    palette,
    sample_filters,
    tier_summary,
    variable_pickers,
)

cat = catalog()

st.write(
    "**Must have** decides which country-years are usable at all. "
    "**Nice to have** never rules a sample out — it just tells you how much extra "
    "each usable country-year would give you."
)

required, optional = variable_pickers(cat, page="coverage")
if not required and not optional:
    st.info("Pick at least one variable, or add some from the Browse page.")
    st.stop()

filters = sample_filters(cat, prefix="cov")

if not required:
    st.info("Nothing is marked must-have, so every sample qualifies and the chart scores the nice-to-haves.")

usable = cat.samples_for(required, optional, **filters)

with st.container(horizontal=True):
    st.metric("Must have", len(required))
    st.metric("Usable samples", len(usable))
    st.metric("Usable countries", usable["country"].nunique() if not usable.empty else 0)
    if optional:
        full = int((usable["n_optional_present"] == len(optional)).sum()) if not usable.empty else 0
        st.metric(f"…with all {len(optional)} extras", full)

if usable.empty:
    st.warning(
        "No sample carries every must-have variable under these filters. "
        "Move one to nice-to-have, or loosen the filters."
    )
    near = availability_status(cat, required, **filters)
    if not near.empty:
        st.subheader("Near misses")
        st.caption("Blue where all must-haves are present, orange where some are missing.")
        st.altair_chart(availability_chart(near, len(required)))
    st.stop()

st.subheader("Country × year coverage")
if optional:
    st.caption("Cells are samples that already satisfy every must-have; shade shows how many extras they add.")
    st.altair_chart(
        coverage_chart(
            usable,
            len(optional),
            field="n_optional_present",
            missing_field="optional_missing",
            title=f"Nice-to-haves present (of {len(optional)})",
        )
    )
else:
    st.caption("Every cell satisfies all must-have variables.")
    st.altair_chart(availability_chart(availability_status(cat, required, **filters), len(required)))

st.subheader("Countries")
per_country = (
    usable.groupby(["country", "iso3"], dropna=False, as_index=False)
    .agg(
        n_samples=("sample_id", "size"),
        years=("year", lambda s: ", ".join(str(y) for y in sorted(set(s.dropna())))),
        avg_extras=("n_optional_present", "mean"),
    )
    .sort_values(["n_samples", "country"], ascending=[False, True])
    .reset_index(drop=True)
)

left, right = st.columns([1, 1])
with left:
    columns = ["country", "iso3", "n_samples", "years"]
    config = {
        "country": st.column_config.TextColumn("Country"),
        "iso3": st.column_config.TextColumn("ISO3", width="small"),
        "n_samples": st.column_config.NumberColumn("Samples", width="small"),
        "years": st.column_config.TextColumn("Years", width="large"),
    }
    if optional:
        columns.insert(3, "avg_extras")
        config["avg_extras"] = st.column_config.NumberColumn(
            "Avg extras", width="small", format="%.1f"
        )
    st.dataframe(per_country[columns], hide_index=True, column_config=config, height=420)
with right:
    bars = (
        alt.Chart(per_country.head(30))
        .mark_bar(cornerRadiusEnd=4, size=12, color=palette()[0])
        .encode(
            x=alt.X("n_samples:Q", title="Usable samples"),
            y=alt.Y(
                "country:N",
                title=None,
                sort="-x",
                axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=11),
            ),
            tooltip=["country", "n_samples", "years"],
        )
        .properties(height=max(240, 20 * min(30, len(per_country))))
        .configure_axis(grid=False, domainColor=AXIS_GREY[_mode()], tickColor=AXIS_GREY[_mode()])
        .configure_view(stroke=None)
    )
    st.altair_chart(bars)

with st.expander("What is each variable costing you?"):
    st.caption(
        "Samples each variable reaches on its own under the current filters. A "
        "must-have with a small number is what is capping the panel — try moving "
        "it to nice-to-have and watch the usable count above."
    )
    rows = [
        {
            "variable": v,
            "tier": "must have" if v in set(required) else "nice to have",
            "samples_alone": len(cat.samples_with([v], how="all", **filters)),
            "samples_among_usable": (
                int(usable["optional_present"].str.split(";").map(lambda p: v in p).sum())
                if v in set(optional)
                else len(usable)
            ),
        }
        for v in required + optional
    ]
    st.dataframe(
        sorted(rows, key=lambda r: r["samples_alone"]),
        hide_index=True,
        column_config={
            "variable": st.column_config.TextColumn("Variable"),
            "tier": st.column_config.TextColumn("Tier", width="small"),
            "samples_alone": st.column_config.NumberColumn("Samples alone", width="small"),
            "samples_among_usable": st.column_config.NumberColumn(
                "Present in usable", width="small"
            ),
        },
    )

tier_summary(required, optional)
