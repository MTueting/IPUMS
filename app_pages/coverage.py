import altair as alt
import streamlit as st

from app_shared import (
    AXIS_GREY,
    availability_status,
    catalog,
    coverage_chart,
    palette,
    sample_filters,
    variable_picker,
    _mode,
)

cat = catalog()

st.write(
    "Pick the variables your analysis needs. The grid below shows how many of them "
    "each country-year actually carries — only the fully saturated cells are usable."
)

variables = variable_picker(cat)
if not variables:
    st.info("Pick at least one variable, or add some from the Browse page.")
    st.stop()

filters = sample_filters(cat, prefix="cov")

partial = availability_status(cat, variables, **filters)
complete = (
    partial[partial["n_variables_present"] == len(variables)]
    if not partial.empty
    else partial
)

with st.container(horizontal=True):
    st.metric("Variables", len(variables))
    st.metric("Samples with all of them", len(complete))
    st.metric("Countries with all of them", complete["country"].nunique())
    st.metric("Samples with at least one", len(partial))

if partial.empty:
    st.warning("No samples carry any of these variables under the current filters.")
    st.stop()

st.subheader("Country × year coverage")
st.altair_chart(coverage_chart(partial, len(variables)))

st.subheader("Countries where every variable is present")
coverage = cat.coverage(variables, how="all")
if coverage.empty:
    st.warning(
        "No country carries all of these variables. Drop one — the heatmap above "
        "shows which is doing the damage — or switch to a smaller set."
    )
else:
    left, right = st.columns([1, 1])
    with left:
        st.dataframe(
            coverage[["country", "iso3", "n_samples", "years"]],
            hide_index=True,
            column_config={
                "country": st.column_config.TextColumn("Country"),
                "iso3": st.column_config.TextColumn("ISO3", width="small"),
                "n_samples": st.column_config.NumberColumn("Samples", width="small"),
                "years": st.column_config.TextColumn("Years", width="large"),
            },
            height=420,
        )
    with right:
        bars = (
            alt.Chart(coverage.head(30))
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
            .properties(height=max(240, 20 * min(30, len(coverage))))
            .configure_axis(grid=False, domainColor=AXIS_GREY[_mode()], tickColor=AXIS_GREY[_mode()])
            .configure_view(stroke=None)
        )
        st.altair_chart(bars)

with st.expander("Which variable is the binding constraint?"):
    st.caption(
        "Sample counts for each variable on its own, under the current filters. "
        "The smallest number is what is limiting the intersection."
    )
    per_variable = [
        {"variable": v, "samples": len(cat.samples_with([v], how="all", **filters))}
        for v in variables
    ]
    st.dataframe(per_variable, hide_index=True)
