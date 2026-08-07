import streamlit as st

from app_shared import OPTIONAL, REQUIRED, catalog, init_state, tier_summary
from ipumsi.search import matched_concepts, search_text, suggest_essentials, tokenize

cat = catalog()
init_state()

st.write(
    "Describe what you are working on in plain English. This searches all "
    f"{len(cat.variables):,} harmonised variables by keyword and topic — no account, "
    "no API, no cost."
)

EXAMPLES = [
    "the role of education on fertility",
    "internal migration of low-income individuals between subnational units",
    "housing quality and utilities for rural-to-urban migrants",
    "women's labour force participation and marital status",
]

with st.container(horizontal=True):
    for i, example in enumerate(EXAMPLES):
        if st.button(example, key=f"eg{i}"):
            st.session_state["query"] = example
            st.rerun()

query = st.text_input(
    "What are you interested in?",
    key="query",
    placeholder="e.g. I am interested in the role of education on fertility",
)

with st.container(horizontal=True):
    record_type = st.segmented_control(
        "Record type", ["All", "P", "H"], default="All", label_visibility="collapsed"
    )
    limit = st.slider("Results", 10, 100, 30)
    include_country = st.toggle(
        "Include single-country variables",
        value=False,
        help=(
            "1,439 of the 1,709 variables exist in only one country (EDUCUS is "
            "US-only). They are ranked below the harmonised ones unless you turn "
            "this on."
        ),
    )

if not query.strip():
    st.info("Type a sentence above, or pick one of the examples.")
    st.stop()

concepts = matched_concepts(query)
stems = tokenize(query)
st.caption(
    ("Topics recognised: **" + "**, **".join(c.name for c in concepts) + "**. ")
    if concepts
    else "No topic recognised — matching on keywords alone. "
    + f"Search terms: {', '.join(stems) or '(none)'}"
)

hits = search_text(
    cat,
    query,
    limit=limit,
    record_type=None if record_type in (None, "All") else record_type,
    include_country_specific=include_country,
)

if hits.empty:
    st.warning(
        "Nothing matched. Try naming the concept directly — 'fertility', "
        "'education', 'migration', 'income', 'housing' — or browse by group on "
        "the Browse page."
    )
    st.stop()

st.subheader(f"{len(hits)} matches")
st.caption("Tick the ones you want, then send them to a tier at the bottom.")

event = st.dataframe(
    hits[["variable", "label", "why", "record_type", "n_countries", "n_samples", "topic"]],
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
    column_config={
        "variable": st.column_config.TextColumn("Mnemonic", width="small"),
        "label": st.column_config.TextColumn("Label", width="large"),
        "why": st.column_config.TextColumn("Why it matched", width="medium"),
        "record_type": st.column_config.TextColumn("Rec", width="small"),
        "n_countries": st.column_config.NumberColumn("Countries", width="small"),
        "n_samples": st.column_config.NumberColumn("Samples", width="small"),
        "topic": st.column_config.TextColumn("Topic", width="small"),
    },
    height=430,
)

rows = event.selection.get("rows", []) if event and event.selection else []
picked = hits.iloc[rows]["variable"].tolist() if rows else []

if not picked:
    st.info("Select rows above to add them to your selection.")
else:
    st.subheader(f"{len(picked)} selected: {', '.join(picked)}")

    coverage = cat.samples_with(picked, how="all")
    with st.container(horizontal=True):
        st.metric("Samples with all of them", len(coverage))
        st.metric("Countries", coverage["country"].nunique() if not coverage.empty else 0)
    if coverage.empty and len(picked) > 1:
        st.warning(
            "No single sample carries all of these. That is normal for a wide "
            "selection — put the core ones in must-have and the rest in "
            "nice-to-have, then check the Coverage page."
        )

    with st.container(horizontal=True):
        if st.button("Add to must have", type="primary", icon=":material/push_pin:"):
            current = list(st.session_state[REQUIRED])
            st.session_state[REQUIRED] = list(dict.fromkeys(current + picked))
            st.session_state[OPTIONAL] = [
                v for v in st.session_state[OPTIONAL] if v not in set(picked)
            ]
            for page in ("browse", "coverage", "extract"):
                st.session_state.pop(f"{page}__{REQUIRED}", None)
                st.session_state.pop(f"{page}__{OPTIONAL}", None)
            st.success("Added. They are now on the Browse, Coverage and Build extract pages.")

        if st.button("Add to nice to have", icon=":material/add:"):
            current = list(st.session_state[OPTIONAL])
            merged = list(dict.fromkeys(current + picked))
            required_now = set(st.session_state[REQUIRED])
            st.session_state[OPTIONAL] = [v for v in merged if v not in required_now]
            for page in ("browse", "coverage", "extract"):
                st.session_state.pop(f"{page}__{OPTIONAL}", None)
            st.success("Added as nice-to-have.")

st.divider()
tier_summary(st.session_state[REQUIRED], st.session_state[OPTIONAL])

essentials = suggest_essentials(
    cat, list(st.session_state[REQUIRED]) + list(st.session_state[OPTIONAL]) + picked
)
if not essentials.empty:
    with st.expander(f"{len(essentials)} standard variables you have not picked yet"):
        st.caption(
            "Weights, identifiers and the usual controls. Nobody searches for these, "
            "but most analyses need them."
        )
        st.dataframe(
            essentials,
            hide_index=True,
            column_config={
                "variable": st.column_config.TextColumn("Mnemonic", width="small"),
                "reason": st.column_config.TextColumn("Why you probably want it", width="large"),
            },
        )
        if st.button("Add all of these to must have", icon=":material/playlist_add:"):
            current = list(st.session_state[REQUIRED])
            st.session_state[REQUIRED] = list(
                dict.fromkeys(current + essentials["variable"].tolist())
            )
            for page in ("browse", "coverage", "extract"):
                st.session_state.pop(f"{page}__{REQUIRED}", None)
            st.rerun()
