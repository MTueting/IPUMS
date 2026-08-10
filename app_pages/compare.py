import numpy as np
import pandas as pd
import streamlit as st

from app_shared import catalog, scatter_chart, sticky
from ipumsi.microdata import Measure, add_iso3, aggregate, find_extracts
from ipumsi.worldbank import DEFAULT_INDICATOR, INDICATORS, attach, indicator_label

cat = catalog()

st.write(
    "Plot a country-level measure from your census microdata against a World Bank "
    "indicator, or against a second measure. Everything is computed at the "
    "**country × year** level from a downloaded extract, weighted by `PERWT`."
)

extracts = find_extracts()
if not extracts:
    st.info(
        "This needs a downloaded extract. Build one on the **Build extract** page, "
        "then fetch it on **Downloads** — the data has to be on disk before it can "
        "be aggregated."
    )
    st.stop()

numbers = [e.number for e in extracts]
picked_number = sticky(
    "selectbox", "Extract", "cmp_extract",
    options=numbers, default=numbers[0],
    format_func=lambda n: f"Extract {n}",
)
chosen = next(e for e in extracts if e.number == picked_number)

TECHNICAL = {"COUNTRY", "YEAR", "SAMPLE", "SERIAL", "PERNUM", "PERWT", "HHWT",
             "QUARTER", "WAVE", "STRATA", "GEOLEV1", "GEOLEV2"}
analysable = [c for c in chosen.columns if c not in TECHNICAL]
weights = [c for c in ("PERWT", "HHWT") if c in chosen.columns] or ["PERWT"]

if not analysable:
    st.warning("This extract has only technical variables — nothing to aggregate.")
    st.stop()


def measure_controls(prefix: str, default_variable: str) -> Measure | None:
    """The share/mean builder, used for the y-axis and optionally the x-axis."""
    variable = sticky(
        "selectbox", "Variable", f"{prefix}_var",
        options=analysable,
        default=default_variable if default_variable in analysable else analysable[0],
        format_func=lambda v: f"{v} — {chosen.label_of(v)}"[:90],
    )
    labels = chosen.labels_for(variable)

    kind = sticky(
        "segmented_control", "Measure", f"{prefix}_kind",
        options=["Share", "Mean"], default="Share",
    ) or "Share"

    categories: tuple[int, ...] = ()
    exclude: tuple[int, ...] = ()
    if kind == "Share":
        if not labels:
            st.warning(
                f"{variable} has no value labels in the codebook, so there are no "
                "categories to choose. Use Mean instead."
            )
            return None
        options = sorted(labels)
        # Codes for "not in universe" and "unknown" belong in neither the
        # numerator nor the denominator; pre-select them for exclusion.
        junk = [c for c, t in labels.items()
                if any(w in t.lower() for w in ("niu", "not in universe", "unknown", "missing"))]
        categories = tuple(
            sticky(
                "multiselect", "Counted in the numerator", f"{prefix}_cats",
                options=options, default=[],
                format_func=lambda c: f"{c} — {labels.get(c, '')}",
            )
        )
        exclude = tuple(
            sticky(
                "multiselect", "Excluded from the denominator", f"{prefix}_excl",
                options=options, default=junk,
                format_func=lambda c: f"{c} — {labels.get(c, '')}",
                help="Not-in-universe and unknown codes should usually sit outside both.",
            )
        )
        if not categories:
            st.info("Pick at least one category for the numerator.")
            return None

    weight = sticky("selectbox", "Weight", f"{prefix}_wt",
                    options=weights, default=weights[0])

    filters: dict[str, tuple[float, float]] = {}
    if "AGE" in chosen.columns:
        if sticky("checkbox", "Restrict by age", f"{prefix}_agef", default=False):
            low, high = sticky("slider", "Age range", f"{prefix}_age",
                               default=(25, 64), min_value=0, max_value=100)
            filters["AGE"] = (float(low), float(high))

    return Measure(
        variable=variable,
        kind=kind.lower(),
        categories=categories,
        exclude=exclude,
        weight=weight,
        filters=filters,
    )


@st.cache_data(show_spinner=False, max_entries=16)
def _aggregate(number: int, spec: tuple) -> pd.DataFrame:
    """Cached country-year aggregate. `spec` is the Measure, made hashable."""
    extract = next(e for e in find_extracts() if e.number == number)
    variable, kind, categories, exclude, weight, filters = spec
    measure = Measure(
        variable=variable, kind=kind, categories=categories, exclude=exclude,
        weight=weight, filters=dict(filters),
    )
    return add_iso3(aggregate(extract, measure), cat)


def spec_of(measure: Measure) -> tuple:
    return (
        measure.variable, measure.kind, measure.categories, measure.exclude,
        measure.weight, tuple(sorted(measure.filters.items())),
    )


def run(measure: Measure) -> pd.DataFrame:
    key = spec_of(measure)
    bar = st.empty()
    bar.info(
        f"Streaming the extract to compute **{measure.variable}** — this takes a "
        "minute or two the first time, then it is cached."
    )
    try:
        result = _aggregate(chosen.number, key)
    finally:
        bar.empty()
    return result


left, right = st.columns(2)
with left:
    st.subheader("Y axis")
    y_measure = measure_controls("y", "EDATTAIN")
with right:
    st.subheader("X axis")
    x_source = sticky(
        "radio", "From", "cmp_xsrc",
        options=["World Bank indicator", "Another measure in this extract"],
        default="World Bank indicator",
    )
    if x_source == "World Bank indicator":
        indicator = sticky(
            "selectbox", "Indicator", "cmp_indicator",
            options=list(INDICATORS), default=DEFAULT_INDICATOR,
            format_func=indicator_label,
        )
        take_log = sticky("checkbox", "Log scale", "cmp_log", default=True)
        x_measure = None
    else:
        indicator, take_log = None, False
        x_measure = measure_controls("x", analysable[0])

if y_measure is None or (x_source != "World Bank indicator" and x_measure is None):
    st.stop()

if st.button("Plot", type="primary", icon=":material/scatter_plot:"):
    st.session_state["cmp_plotted"] = True
if not st.session_state.get("cmp_plotted"):
    st.caption("Set the axes, then press Plot. Results are cached per measure.")
    st.stop()

data = run(y_measure).rename(columns={"value": "y", "n": "n_y"})
y_label = y_measure.describe(chosen)

if indicator:
    data = attach(data, indicator, column="x")
    x_label = indicator_label(indicator)
else:
    other = run(x_measure).rename(columns={"value": "x", "n": "n_x"})
    data = data.merge(
        other[["country", "year", "x", "n_x"]], on=["country", "year"], how="inner"
    )
    x_label = x_measure.describe(chosen)

before = len(data)
data = data.dropna(subset=["x", "y"])
dropped = before - len(data)

if data.empty:
    st.warning(
        "Nothing to plot — no country-year in this extract matched the x-axis "
        "series. World Bank coverage starts around 1960 and is patchy for older "
        "census years."
    )
    st.stop()

if take_log:
    data = data[data["x"] > 0]
    data["x_plot"] = np.log(data["x"])
    x_axis_label = f"log {x_label}"
else:
    data["x_plot"] = data["x"]
    x_axis_label = x_label

with st.container(horizontal=True):
    st.metric("Country-years plotted", len(data))
    st.metric("Countries", data["country"].nunique())
    correlation = np.corrcoef(data["x_plot"], data["y"])[0, 1]
    st.metric("Correlation", f"{correlation:.3f}")
if dropped:
    st.caption(f"{dropped} country-year(s) dropped for having no x-axis value.")

st.subheader("Display")
with st.container(horizontal=True):
    show_fit = sticky("checkbox", "Linear fit", "cmp_fit", default=True)
    colour_by_country = sticky("checkbox", "Colour by country", "cmp_colour", default=True)
    countries = sorted(data["country"].unique())
    highlight = sticky(
        "selectbox", "Highlight one", "cmp_highlight",
        options=["(none)"] + countries, default="(none)",
        help="Greys out the rest — the reliable way to trace a single country.",
    )
highlight = None if highlight == "(none)" else highlight

if colour_by_country and len(countries) > 3:
    st.caption(
        f"{len(countries)} countries share the palette, so some colours sit close "
        "together. Each country also has its own marker shape, and 'Highlight one' "
        "isolates a single series when the distinction matters."
    )

x_lo, x_hi = float(data["x_plot"].min()), float(data["x_plot"].max())
y_lo, y_hi = float(data["y"].min()), float(data["y"].max())
x_pad, y_pad = (x_hi - x_lo) * 0.05 or 1.0, (y_hi - y_lo) * 0.05 or 0.01

with st.expander("Axis limits"):
    manual = sticky("checkbox", "Set limits manually", "cmp_manual", default=False)
    left_col, right_col = st.columns(2)
    with left_col:
        st.caption(f"x — data runs {x_lo:,.3g} to {x_hi:,.3g}")
        x_min = sticky("number_input", "x min", "cmp_xmin",
                       default=round(x_lo - x_pad, 4), disabled=not manual)
        x_max = sticky("number_input", "x max", "cmp_xmax",
                       default=round(x_hi + x_pad, 4), disabled=not manual)
    with right_col:
        st.caption(f"y — data runs {y_lo:,.3g} to {y_hi:,.3g}")
        y_min = sticky("number_input", "y min", "cmp_ymin",
                       default=round(y_lo - y_pad, 4), disabled=not manual)
        y_max = sticky("number_input", "y max", "cmp_ymax",
                       default=round(y_hi + y_pad, 4), disabled=not manual)

x_domain = y_domain = None
if manual:
    if x_min >= x_max or y_min >= y_max:
        st.error("Each axis needs its minimum below its maximum.")
    else:
        x_domain, y_domain = (x_min, x_max), (y_min, y_max)
        hidden = len(data) - len(
            data[(data["x_plot"].between(x_min, x_max)) & (data["y"].between(y_min, y_max))]
        )
        if hidden:
            st.caption(f"{hidden} point(s) fall outside these limits and are not shown.")

st.altair_chart(
    scatter_chart(
        data, x_axis_label, y_label,
        show_fit=show_fit,
        colour_by_country=colour_by_country,
        x_domain=x_domain,
        y_domain=y_domain,
        highlight=highlight,
    )
)

st.caption(
    f"**y**: {y_label}. **x**: {x_axis_label}. Point size is the unweighted case "
    "count behind each estimate — small points rest on few observations."
)

table = data[["country", "iso3", "year", "y", "x", "n_y", "weighted_n"]].sort_values(
    ["country", "year"]
)
with st.expander("The underlying country-year table"):
    st.dataframe(
        table,
        hide_index=True,
        column_config={
            "y": st.column_config.NumberColumn(y_measure.variable, format="%.4f"),
            "x": st.column_config.NumberColumn(x_label, format="%.1f"),
            "n_y": st.column_config.NumberColumn("Cases", format="localized"),
            "weighted_n": st.column_config.NumberColumn("Weighted N", format="localized"),
        },
    )
st.download_button(
    "Download this table as CSV",
    table.to_csv(index=False),
    file_name=f"ipumsi_{chosen.number}_{y_measure.variable}_country_year.csv",
    mime="text/csv",
    icon=":material/download:",
)
