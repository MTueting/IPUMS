"""Shared loaders and helpers for the Streamlit explorer.

Kept out of the page scripts so each page stays a straight top-to-bottom script.
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ipumsi.catalog import Catalog, CatalogNotBuilt  # noqa: E402

# Availability is a yes/no fact, so it takes categorical hues -- slots 1 and 2 of
# the reference palette, which are validated as a pair in both modes. Counts of
# variables present are ordinal instead, and take a single-hue ramp.
CATEGORICAL = {"light": ["#2a78d6", "#eb6834"], "dark": ["#3987e5", "#d95926"]}
SEQUENTIAL_SCHEME = "teals"  # one hue, light -> dark
AXIS_GREY = {"light": "#b8b7b2", "dark": "#52514e"}


def _mode() -> str:
    return "dark" if getattr(st.context.theme, "type", "light") == "dark" else "light"


def palette() -> list[str]:
    return CATEGORICAL[_mode()]


@st.cache_data(show_spinner="Loading catalog…", ttl=3600)
def _load_frames() -> dict:
    cat = Catalog.load()
    return {
        "samples": cat.samples,
        "variables": cat.variables,
        "countries": cat.countries,
        "variable_samples": cat.variable_samples,
        "meta": cat.meta,
    }


def catalog() -> Catalog:
    """The catalog, cached across reruns and sessions."""
    try:
        frames = _load_frames()
    except CatalogNotBuilt as exc:
        st.error(str(exc))
        st.info("Run `ipumsi refresh` (about 10 minutes) to build it, then reload.")
        st.stop()
    return Catalog(
        samples=frames["samples"],
        variables=frames["variables"],
        countries=frames["countries"],
        variable_samples=frames["variable_samples"],
        meta=frames["meta"],
    )


def selected_variables() -> list[str]:
    return list(st.session_state.get("selected_variables", []))


def variable_picker(cat: Catalog, key: str = "selected_variables") -> list[str]:
    """A multiselect over every variable, labelled with its description."""
    options = cat.variables["variable"].tolist()
    labels = dict(zip(cat.variables["variable"], cat.variables["label"].fillna("")))
    return st.multiselect(
        "Variables",
        options,
        key=key,
        format_func=lambda v: f"{v} — {labels.get(v, '')}"[:110],
        placeholder="Search by mnemonic or label, e.g. GEOMIG1_P",
        help="Availability is computed for the intersection of everything you pick.",
    )


def sample_filters(cat: Catalog, prefix: str) -> dict:
    """The country / year / sample-kind filter row shared by pages."""
    with st.container(horizontal=True):
        countries = st.multiselect(
            "Countries",
            sorted(cat.samples["country"].dropna().unique()),
            key=f"{prefix}_countries",
            placeholder="All countries",
        )
        kind = st.segmented_control(
            "Sample kind",
            ["All", "census", "LFS"],
            default="All",
            key=f"{prefix}_kind",
        )
    years = cat.samples["year"].dropna()
    lo, hi = int(years.min()), int(years.max())
    # Default to the full span -- a narrower default would silently hide samples.
    year_range = st.slider("Year range", lo, hi, (lo, hi), key=f"{prefix}_years")
    return {
        "countries": countries or None,
        "kind": None if kind in (None, "All") else kind,
        "year_min": year_range[0],
        "year_max": year_range[1],
    }


def availability_status(cat: Catalog, variables: list[str], **filters) -> pd.DataFrame:
    """Per-sample availability for a variable set, labelled all-vs-partial."""
    hits = cat.samples_with(variables, how="any", **filters)
    if hits.empty:
        return hits
    n = len(variables)
    hits = hits.copy()
    complete = hits["n_variables_present"] == n
    hits["status"] = pd.Series(
        ["Available" if n == 1 else f"All {n} variables"] * len(hits), index=hits.index
    ).where(complete, "Some variables missing")
    hits["missing_variables"] = hits["missing_variables"].replace("", "—")
    return hits


def _country_year_base(data: pd.DataFrame, color, tooltip):
    """Shared country x year cell chart.

    Every country label is drawn: ``labelOverlap=False`` stops Vega thinning them
    out, and the height grows with the number of countries so there is room.
    """
    n_countries = data["country"].nunique()
    grey = AXIS_GREY[_mode()]
    return (
        alt.Chart(data)
        .mark_rect(cornerRadius=2)
        .encode(
            x=alt.X(
                "year:O",
                title="Year",
                axis=alt.Axis(labelAngle=-90, labelOverlap=False, labelFontSize=10),
            ),
            y=alt.Y(
                "country:N",
                title=None,
                axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=11),
            ),
            color=color,
            tooltip=tooltip,
        )
        .properties(height=max(200, 19 * n_countries))
        .configure_axis(grid=False, domainColor=grey, tickColor=grey)
        .configure_view(stroke=None)
        .configure_legend(orient="top", title=None)
    )


def availability_chart(data: pd.DataFrame, n_variables: int):
    """Categorical yes/no availability. One variable = one series, so no legend."""
    hues = palette()
    if n_variables == 1:
        color = alt.value(hues[0])
    else:
        color = alt.Color(
            "status:N",
            scale=alt.Scale(
                domain=[f"All {n_variables} variables", "Some variables missing"],
                range=hues,
            ),
            legend=alt.Legend(orient="top", title=None),
        )
    tooltip = [
        alt.Tooltip("country", title="Country"),
        alt.Tooltip("year", title="Year"),
        alt.Tooltip("sample_id", title="Sample"),
        alt.Tooltip("kind", title="Type"),
    ]
    if n_variables > 1:
        tooltip += [
            alt.Tooltip("n_variables_present", title="Present"),
            alt.Tooltip("missing_variables", title="Missing"),
        ]
    return _country_year_base(data, color, tooltip)


def coverage_chart(data: pd.DataFrame, n_variables: int):
    """How many of the set each sample carries -- ordinal, so a stepped one-hue ramp."""
    color = alt.Color(
        "n_variables_present:O",
        title=f"Variables present (of {n_variables})",
        scale=alt.Scale(scheme=SEQUENTIAL_SCHEME),
        legend=alt.Legend(orient="top"),
    )
    tooltip = [
        alt.Tooltip("country", title="Country"),
        alt.Tooltip("year", title="Year"),
        alt.Tooltip("sample_id", title="Sample"),
        alt.Tooltip("n_variables_present", title="Present"),
        alt.Tooltip("missing_variables", title="Missing"),
    ]
    return _country_year_base(data, color, tooltip)
