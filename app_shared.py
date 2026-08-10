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


def clear_catalog_cache() -> None:
    """Drop the cached frames so the next load picks up a rebuilt catalog."""
    _load_frames.clear()


def catalog(required: bool = True) -> Catalog | None:
    """The catalog, cached across reruns and sessions.

    ``required=False`` returns None instead of halting the page, so the settings
    page can still offer to build a catalog that does not exist yet.
    """
    try:
        frames = _load_frames()
    except CatalogNotBuilt as exc:
        if not required:
            return None
        st.error(str(exc))
        st.info("Build it from the Settings page, or run `ipumsi refresh`.")
        st.stop()
    return Catalog(
        samples=frames["samples"],
        variables=frames["variables"],
        countries=frames["countries"],
        variable_samples=frames["variable_samples"],
        meta=frames["meta"],
    )


# Canonical selection, shared by every page.
#
# These are PLAIN session-state keys, deliberately not widget keys. Streamlit
# discards widget state for widgets that were not rendered on the current run,
# so a `key="required_vars"` multiselect loses its value the moment you navigate
# to another page. Each page therefore mounts its own widget (keyed by page) and
# mirrors it back here on change; plain keys are never culled.
REQUIRED = "required_vars"
OPTIONAL = "optional_vars"


def init_state() -> None:
    for key in (REQUIRED, OPTIONAL):
        st.session_state.setdefault(key, [])


# --------------------------------------------------------------- sticky widgets
#
# Streamlit throws away the state of any widget that was not rendered on the
# current run, so every control on a page is reset the moment you navigate away
# and back. These wrappers mirror each widget's value into a plain session-state
# key (never culled) and re-seed the widget from it, so a page you return to
# looks the way you left it.


def _remember(key: str) -> None:
    st.session_state[f"_keep_{key}"] = st.session_state[key]


def sticky(kind: str, label: str, key: str, *, options=None, default=None, **kwargs):
    """Render ``st.<kind>`` with a value that survives page switches."""
    store = f"_keep_{key}"
    if store not in st.session_state:
        st.session_state[store] = default
    kept = st.session_state[store]
    widget = getattr(st, kind)
    common = {"key": key, "on_change": _remember, "args": (key,), **kwargs}

    if kind in ("selectbox", "radio"):
        choices = list(options)
        index = choices.index(kept) if kept in choices else 0
        return widget(label, choices, index=index, **common)
    if kind == "multiselect":
        allowed = set(options)
        return widget(
            label, options, default=[v for v in (kept or []) if v in allowed], **common
        )
    if kind in ("segmented_control", "pills"):
        return widget(label, options, default=kept, **common)
    # value-based: checkbox, toggle, number_input, slider, text_input, text_area
    return widget(label, value=kept, **common)


def get_selection() -> tuple[list[str], list[str]]:
    init_state()
    return list(st.session_state[REQUIRED]), list(st.session_state[OPTIONAL])


def add_variable(name: str, tier: str = REQUIRED) -> bool:
    """Add a variable to one tier, removing it from the other. True if it moved."""
    init_state()
    other = OPTIONAL if tier == REQUIRED else REQUIRED
    if name in st.session_state[tier]:
        return False
    st.session_state[tier] = st.session_state[tier] + [name]
    st.session_state[other] = [v for v in st.session_state[other] if v != name]
    return True


def _mirror(canonical: str, widget_key: str) -> None:
    st.session_state[canonical] = st.session_state[widget_key]


def _picker(cat: Catalog, page: str, canonical: str, label: str, help: str, placeholder: str):
    options = cat.variables["variable"].tolist()
    labels = dict(zip(cat.variables["variable"], cat.variables["label"].fillna("")))
    widget_key = f"{page}__{canonical}"
    # `default` only applies when the widget key is absent -- which is exactly
    # the case after a page switch, so the canonical value is restored then.
    return st.multiselect(
        label,
        options,
        default=[v for v in st.session_state[canonical] if v in set(options)],
        key=widget_key,
        on_change=_mirror,
        args=(canonical, widget_key),
        format_func=lambda v: f"{v} — {labels.get(v, '')}"[:110],
        placeholder=placeholder,
        help=help,
    )


def variable_pickers(cat: Catalog, page: str, show_optional: bool = True):
    """The must-have / nice-to-have picker pair. Selections persist across pages."""
    init_state()
    required = _picker(
        cat, page, REQUIRED,
        "Must have",
        "Only samples carrying every one of these are counted as usable.",
        "e.g. GEOMIG1_P, GEOLEV1",
    )
    if not show_optional:
        return required, []
    optional = _picker(
        cat, page, OPTIONAL,
        "Nice to have",
        "Included wherever they exist, but they never rule a sample out.",
        "e.g. INCTOT, EDATTAIN",
    )
    # A variable cannot sit in both tiers; must-have wins. Promoting one from the
    # must-have box has to evict it from the canonical nice-to-have list too,
    # otherwise it reappears the moment it is unpicked from must-have.
    deduped = [v for v in optional if v not in set(required)]
    if deduped != optional:
        st.session_state[OPTIONAL] = deduped
        # Drop the widget's own key so `default` re-applies on the next run.
        st.session_state.pop(f"{page}__{OPTIONAL}", None)
        st.rerun()
    return required, deduped


def sample_filters(cat: Catalog, prefix: str) -> dict:
    """The country / year / sample-kind filter row shared by pages."""
    with st.container(horizontal=True):
        countries = sticky(
            "multiselect", "Countries", f"{prefix}_countries",
            options=sorted(cat.samples["country"].dropna().unique()),
            default=[], placeholder="All countries",
        )
        kind = sticky(
            "segmented_control", "Sample kind", f"{prefix}_kind",
            options=["All", "census", "LFS"], default="All",
        )
    years = cat.samples["year"].dropna()
    lo, hi = int(years.min()), int(years.max())
    # Default to the full span -- a narrower default would silently hide samples.
    year_range = sticky(
        "slider", "Year range", f"{prefix}_years",
        default=(lo, hi), min_value=lo, max_value=hi,
    )
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


@st.cache_data(show_spinner="Fetching case counts from IPUMS…", ttl=86400, max_entries=64)
def frequencies(variable: str) -> pd.DataFrame:
    """Case counts for one variable, fetched on demand and cached.

    Not part of the committed catalog: a single variable can be 100k+ category x
    sample cells, so these are pulled only for whatever the user is looking at.
    """
    from ipumsi.http import Fetcher
    from ipumsi.scrape.frequencies import fetch_frequencies

    return fetch_frequencies(Fetcher(), variable)


def frequency_chart(data: pd.DataFrame, samples: list[str], top_n: int):
    """Category shares within each selected sample.

    One sample is a single series -- one hue, no legend, since the bar length
    already carries the value. Several samples get the validated categorical
    slots, which is why the picker is capped at three.
    """
    hues = palette() + ["#1baf7a"]  # slots 1-3; validated all-pairs in both modes
    grey = AXIS_GREY[_mode()]
    ranked = (
        data.groupby("label", as_index=False)["share"].max()
        .nlargest(top_n, "share")["label"].tolist()
    )
    subset = data[data["label"].isin(ranked)]

    encoding = {
        "x": alt.X("share:Q", title="Share of the sample", axis=alt.Axis(format="%")),
        "y": alt.Y("label:N", title=None, sort=ranked,
                   axis=alt.Axis(labelOverlap=False, labelLimit=260, labelFontSize=11)),
        "tooltip": [
            alt.Tooltip("label", title="Category"),
            alt.Tooltip("code", title="Code"),
            alt.Tooltip("sample_id", title="Sample"),
            alt.Tooltip("count", title="Cases", format=","),
            alt.Tooltip("share", title="Share", format=".2%"),
        ],
    }
    if len(samples) > 1:
        encoding["color"] = alt.Color(
            "sample_id:N",
            scale=alt.Scale(domain=samples, range=hues[: len(samples)]),
            legend=alt.Legend(orient="top", title=None),
        )
        encoding["yOffset"] = alt.YOffset("sample_id:N", sort=samples)
        mark = alt.Chart(subset).mark_bar(cornerRadiusEnd=3, height=9)
    else:
        mark = alt.Chart(subset).mark_bar(cornerRadiusEnd=3, color=hues[0])

    return (
        mark.encode(**encoding)
        .properties(height=max(220, 26 * len(ranked) * max(1, len(samples) // 2)))
        .configure_axis(grid=False, domainColor=grey, tickColor=grey)
        .configure_view(stroke=None)
    )


# The eight reference hues, then four more for datasets with more countries.
# Measured worst-case pairwise separation (OKLab dE x100, normal vision): 7.1 --
# below the documented floor of 15. That floor is unreachable here: in a scatter
# any two points can end up adjacent, and the reference palette itself only
# clears all-pairs for its first three slots. So colour is never the only
# identity channel below -- shape varies with it, the legend is always drawn,
# points are labelled when few enough, and every point has a tooltip.
SERIES_HUES = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
              "#4a3aa7", "#e34948", "#8a5a2b", "#00707f", "#b0006e", "#6b7a00"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300",
             "#9085e9", "#e66767", "#a06a35", "#00899b", "#d4308c", "#8a9c00"],
}
SERIES_SHAPES = ["circle", "square", "triangle-up", "diamond", "cross",
                 "triangle-down", "triangle-right", "triangle-left"]


def scatter_chart(
    data: pd.DataFrame,
    x_label: str,
    y_label: str,
    show_fit: bool = True,
    colour_by_group: bool = True,
    x_domain: tuple[float, float] | None = None,
    y_domain: tuple[float, float] | None = None,
    highlight: str | None = None,
    legend_title: str = "Series",
):
    """Scatter over whatever the unit of analysis is.

    ``data`` needs ``x_plot``, ``y``, ``n_y`` and a ``group`` column naming each
    series -- a country, or a region within one, depending on how the measure was
    aggregated. Each group gets its own colour *and* shape, plus a legend, so a
    series can be traced across years. ``highlight`` greys everything else, which
    is the only fully reliable way to follow one series when there are many.
    """
    grey = AXIS_GREY[_mode()]
    hues = SERIES_HUES[_mode()]
    if "group" not in data.columns:
        data = data.assign(group=data.get("country", "all"))
    groups = sorted(data["group"].unique())
    base = alt.Chart(data)

    x_scale = alt.Scale(zero=False, **({"domain": list(x_domain)} if x_domain else {}))
    y_scale = alt.Scale(zero=False, **({"domain": list(y_domain)} if y_domain else {}))

    encoding = {
        "x": alt.X("x_plot:Q", title=x_label, scale=x_scale),
        "y": alt.Y("y:Q", title=y_label, scale=y_scale),
        "size": alt.Size("n_y:Q", legend=None, scale=alt.Scale(range=[60, 420])),
        "tooltip": [
            alt.Tooltip("group", title="Series"),
            alt.Tooltip("year", title="Year"),
            alt.Tooltip("y:Q", title="y", format=".4f"),
            alt.Tooltip("x:Q", title="x", format=",.1f"),
            alt.Tooltip("n_y:Q", title="Cases", format=","),
        ],
    }

    if colour_by_group and len(groups) > 1:
        # Cycle only if there are more groups than hues; shape keeps those apart,
        # since it cycles on a different period.
        colours = [hues[i % len(hues)] for i in range(len(groups))]
        shapes = [SERIES_SHAPES[i % len(SERIES_SHAPES)] for i in range(len(groups))]
        legend = alt.Legend(title=legend_title, orient="right", symbolLimit=0)
        encoding["color"] = alt.Color(
            "group:N", scale=alt.Scale(domain=groups, range=colours), legend=legend
        )
        encoding["shape"] = alt.Shape(
            "group:N", scale=alt.Scale(domain=groups, range=shapes), legend=legend
        )
        if highlight and highlight in groups:
            encoding["opacity"] = alt.condition(
                alt.datum.group == highlight, alt.value(0.95), alt.value(0.12)
            )
        else:
            encoding["opacity"] = alt.value(0.8)
        points = base.mark_point(filled=True, strokeWidth=1, stroke="white").encode(**encoding)
    else:
        encoding["opacity"] = alt.value(0.75)
        points = base.mark_point(
            filled=True, color=hues[0], strokeWidth=1, stroke="white"
        ).encode(**encoding)

    layers = [points]

    labelled = data if not highlight else data[data["group"] == highlight]
    if len(labelled) <= 30:
        layers.append(
            alt.Chart(labelled)
            .mark_text(dx=10, dy=-8, align="left", fontSize=10, color=grey)
            .encode(x=alt.X("x_plot:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale),
                    text="group:N")
        )

    if show_fit and len(data) >= 3:
        # One fit across all points -- a per-country fit on a handful of census
        # years each would be noise dressed up as a finding.
        layers.append(
            base.transform_regression("x_plot", "y")
            .mark_line(color=grey, strokeDash=[5, 4], size=2)
            .encode(x=alt.X("x_plot:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale))
        )

    return (
        alt.layer(*layers)
        .properties(height=480)
        .configure_axis(grid=True, gridColor=grey, gridOpacity=0.25,
                        domainColor=grey, tickColor=grey)
        .configure_view(stroke=None)
        .configure_legend(labelLimit=180)
    )


def human_bytes(n: int | float) -> str:
    """Sizes a person can read: extracts run from kilobytes to gigabytes."""
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def tier_summary(required: list[str], optional: list[str]) -> None:
    """One line naming what is currently selected, so it is visible on every page."""
    parts = []
    if required:
        parts.append(f"**Must have ({len(required)}):** {', '.join(required)}")
    if optional:
        parts.append(f"**Nice to have ({len(optional)}):** {', '.join(optional)}")
    if parts:
        st.caption(" · ".join(parts))


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


def coverage_chart(
    data: pd.DataFrame,
    n_variables: int,
    field: str = "n_variables_present",
    missing_field: str = "missing_variables",
    title: str | None = None,
):
    """How many of the set each sample carries -- ordinal, so a stepped one-hue ramp."""
    color = alt.Color(
        f"{field}:O",
        title=title or f"Variables present (of {n_variables})",
        scale=alt.Scale(scheme=SEQUENTIAL_SCHEME),
        legend=alt.Legend(orient="top"),
    )
    tooltip = [
        alt.Tooltip("country", title="Country"),
        alt.Tooltip("year", title="Year"),
        alt.Tooltip("sample_id", title="Sample"),
        alt.Tooltip(field, title="Present"),
        alt.Tooltip(missing_field, title="Missing"),
    ]
    return _country_year_base(data, color, tooltip)
