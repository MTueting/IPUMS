import streamlit as st

from app_shared import OPTIONAL, REQUIRED, catalog, init_state, tier_summary
from ipumsi.assistant import (
    AssistantError,
    MissingAnthropicKey,
    anthropic_key,
    suggest_variables,
)

cat = catalog()
init_state()

st.write(
    "Describe the project in your own words. Claude reads the full catalog of "
    f"{len(cat.variables):,} harmonised variables and proposes a must-have / "
    "nice-to-have split, which lands in the picker on every other page."
)

EXAMPLES = {
    "Internal migration and income": (
        "I want to look at the relationship between GDP per capita and the internal "
        "migration rate of low-income individuals — ideally origin-destination flows "
        "between subnational units, so I can map them and merge World Bank indicators "
        "on the country-year."
    ),
    "Education and fertility": (
        "How does women's educational attainment relate to completed fertility across "
        "developing countries, controlling for urban/rural residence and age at first birth?"
    ),
    "Urbanisation and housing quality": (
        "I'm studying how housing quality and access to utilities differ between recent "
        "rural-to-urban migrants and long-term urban residents."
    ),
}

with st.container(horizontal=True):
    example = st.selectbox("Start from an example", ["(write my own)"] + list(EXAMPLES))
if example != "(write my own)" and st.session_state.get("_last_example") != example:
    st.session_state["pitch"] = EXAMPLES[example]
    st.session_state["_last_example"] = example

pitch = st.text_area(
    "Project description",
    key="pitch",
    height=140,
    placeholder="e.g. I want to map internal migration flows and relate them to income…",
)

try:
    anthropic_key()
    has_key = True
    key_error = ""
except MissingAnthropicKey as exc:
    has_key = False
    key_error = str(exc)

with st.container(horizontal=True):
    go = st.button(
        "Suggest variables",
        type="primary",
        icon=":material/auto_awesome:",
        disabled=not (has_key and pitch.strip()),
    )
    if st.session_state.get("suggestion"):
        if st.button("Clear", icon=":material/close:"):
            st.session_state.pop("suggestion", None)
            st.rerun()

if not has_key:
    st.info(key_error)
    st.caption(
        "The catalog is sent as a cached prompt, so the first question costs a few "
        "cents and later ones are roughly a tenth of that."
    )

if go:
    try:
        st.session_state["suggestion"] = suggest_variables(cat, pitch)
    except (AssistantError, MissingAnthropicKey) as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - surface the API's message verbatim
        st.error(f"Request failed: {exc}")

suggestion = st.session_state.get("suggestion")
if not suggestion:
    st.stop()

if suggestion.strategy:
    st.info(suggestion.strategy)

if suggestion.dropped:
    st.warning(
        "Claude proposed variable(s) that are not in the catalog, so they were "
        f"dropped: {', '.join(sorted(set(suggestion.dropped)))}"
    )

left, right = st.columns(2)
with left:
    st.subheader(f"Must have ({len(suggestion.must_have)})")
    st.caption("Every one of these must be present for a country-year to be usable.")
    for pick in suggestion.must_have:
        with st.container(border=True):
            st.markdown(f"**{pick.variable}** — {pick.label}")
            st.caption(pick.reason)
with right:
    st.subheader(f"Nice to have ({len(suggestion.nice_to_have)})")
    st.caption("Included wherever they exist; they never rule a sample out.")
    for pick in suggestion.nice_to_have:
        with st.container(border=True):
            st.markdown(f"**{pick.variable}** — {pick.label}")
            st.caption(pick.reason)

required = [p.variable for p in suggestion.must_have]
optional = [p.variable for p in suggestion.nice_to_have]

if required:
    usable = cat.samples_for(required, optional)
    with st.container(horizontal=True):
        st.metric("Usable samples", len(usable))
        st.metric("Usable countries", usable["country"].nunique() if not usable.empty else 0)
        if not usable.empty and optional:
            st.metric(
                "Average extras present",
                f"{usable['n_optional_present'].mean():.1f} of {len(optional)}",
            )
    if usable.empty:
        st.warning(
            "No sample carries all of the must-haves. Move one to nice-to-have on the "
            "Coverage page — the heatmap there shows which is the binding constraint."
        )

if suggestion.caveats:
    with st.expander("Caveats"):
        for caveat in suggestion.caveats:
            st.markdown(f"- {caveat}")

st.subheader("Apply")
tier_summary(
    st.session_state.get(REQUIRED, []), st.session_state.get(OPTIONAL, [])
)
with st.container(horizontal=True):
    if st.button("Use this selection", type="primary", icon=":material/check:"):
        st.session_state[REQUIRED] = required
        st.session_state[OPTIONAL] = [v for v in optional if v not in set(required)]
        # Clear the per-page widget copies so each page re-seeds from the new selection.
        for page in ("browse", "coverage", "extract"):
            st.session_state.pop(f"{page}__{REQUIRED}", None)
            st.session_state.pop(f"{page}__{OPTIONAL}", None)
        st.success("Applied — the Browse, Coverage and Build extract pages are now loaded with it.")

    if st.button("Add to what I already have", icon=":material/add:"):
        merged = list(dict.fromkeys(list(st.session_state.get(REQUIRED, [])) + required))
        st.session_state[REQUIRED] = merged
        st.session_state[OPTIONAL] = [
            v for v in dict.fromkeys(list(st.session_state.get(OPTIONAL, [])) + optional)
            if v not in set(merged)
        ]
        for page in ("browse", "coverage", "extract"):
            st.session_state.pop(f"{page}__{REQUIRED}", None)
            st.session_state.pop(f"{page}__{OPTIONAL}", None)
        st.success("Merged into the existing selection.")

if suggestion.countries or suggestion.year_min or suggestion.year_max:
    bits = []
    if suggestion.countries:
        bits.append(f"countries: {', '.join(suggestion.countries)}")
    if suggestion.year_min:
        bits.append(f"from {suggestion.year_min}")
    if suggestion.year_max:
        bits.append(f"to {suggestion.year_max}")
    st.caption("Claude also suggested filters (" + "; ".join(bits) + ") — set them on the Coverage page.")

if suggestion.usage:
    usage = suggestion.usage
    cached = usage.get("cache_read_input_tokens") or 0
    st.caption(
        f"{usage.get('input_tokens', 0):,} input + {usage.get('output_tokens', 0):,} output tokens"
        + (f" · {cached:,} read from cache" if cached else "")
    )
