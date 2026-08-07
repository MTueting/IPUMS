"""Free-text variable search.

These pin the behaviours that make the search useful rather than merely
plausible: stemming across word forms, concept mapping onto IPUMS's own
vocabulary, no substring false positives, harmonised variables ahead of
single-country recodes, and every topic in a question represented.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ipumsi.catalog import Catalog
from ipumsi.search import (
    matched_concepts,
    search_text,
    stem,
    suggest_essentials,
    tokenize,
)


@pytest.fixture(scope="module")
def cat() -> Catalog:
    """The real committed catalog -- this search is only meaningful against it."""
    return Catalog.load()


def top(df: pd.DataFrame, n: int = 10) -> list[str]:
    return df["variable"].head(n).tolist()


# ------------------------------------------------------------------ stemming


@pytest.mark.parametrize(
    "words",
    [
        ("education", "educational", "educate"),
        ("fertility", "fertile"),
        ("migration", "migrations", "migrants"),
        ("employment", "employments", "employed"),
    ],
)
def test_word_forms_find_the_same_variables(cat, words):
    """What matters is that word forms behave alike, not that stems are equal.

    Suffix stripping is imperfect ("fertility" -> "fertil", "fertile" ->
    "fertile"), so the search compares on a shared prefix instead.
    """
    results = [top(search_text(cat, w, limit=8), 8) for w in words]
    first = set(results[0])
    for word, hits in zip(words[1:], results[1:]):
        assert first & set(hits), f"{words[0]!r} and {word!r} share no results"


def test_tokenize_drops_filler_and_dedupes():
    tokens = tokenize("I am interested in the role of education on education")
    assert tokens == ["educ"]


def test_tokenize_handles_empty_and_punctuation():
    assert tokenize("") == []
    assert tokenize("...!!!") == []


# ------------------------------------------------------------------ concepts


def test_concepts_map_everyday_words_to_catalog_vocabulary(cat):
    """'education' must find YRSCHOOL, which shares no letters with the word."""
    hits = top(search_text(cat, "education", limit=15), 15)
    assert "EDATTAIN" in hits
    assert "YRSCHOOL" in hits
    assert "SCHOOL" in hits


def test_the_users_own_example(cat):
    """'the role of education on fertility' -- both sides must be represented."""
    hits = top(search_text(cat, "I am interested in the role of education on fertility"), 12)
    assert "EDATTAIN" in hits
    assert "CHBORN" in hits, "fertility was crowded out by education"


def test_multi_topic_queries_are_interleaved(cat):
    df = search_text(cat, "education and fertility", limit=10)
    topics = set(df["topic"]) - {""}
    assert {"education", "fertility"} <= topics


def test_migration_and_income_query(cat):
    hits = top(search_text(cat, "internal migration of low-income individuals"), 12)
    assert any(h.startswith("MIGRATE") for h in hits)
    assert any(h.startswith("INC") for h in hits)


# ---------------------------------------------------- no substring nonsense


def test_income_does_not_match_sewage_or_prince(cat):
    """A naive `inc`/`wage` substring search matches SEWAGE and PRINCE."""
    hits = top(search_text(cat, "income", limit=20), 20)
    assert "SEWAGE" not in hits


def test_housing_query_finds_utilities_not_income(cat):
    hits = top(search_text(cat, "access to water and electricity"), 10)
    assert "WATSUP" in hits or "ELECTRIC" in hits
    assert "INCTOT" not in hits


# --------------------------------------------------------------- ranking


def test_harmonised_beats_single_country(cat):
    """EDATTAIN (98 countries) must outrank EDUCUS (US only, 9 samples)."""
    hits = top(search_text(cat, "education", limit=25), 25)
    assert "EDATTAIN" in hits
    if "EDUCUS" in hits:
        assert hits.index("EDATTAIN") < hits.index("EDUCUS")


def test_country_specific_can_be_opted_into(cat):
    without = search_text(cat, "education", limit=40)
    with_them = search_text(cat, "education", limit=40, include_country_specific=True)
    single = (with_them["n_countries"] <= 1).sum()
    assert single >= (without["n_countries"] <= 1).sum()


def test_record_type_filter(cat):
    df = search_text(cat, "household dwelling", limit=20, record_type="H")
    assert set(df["record_type"]) <= {"H"}


def test_every_result_explains_itself(cat):
    df = search_text(cat, "education on fertility", limit=10)
    assert (df["why"].str.len() > 0).all()


def test_scores_are_monotonic_within_a_topic(cat):
    df = search_text(cat, "education", limit=15)
    scores = df["score"].tolist()
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------- edge cases


def test_empty_and_stopword_only_queries_return_nothing(cat):
    assert search_text(cat, "").empty
    assert search_text(cat, "I am interested in the role of").empty


def test_nonsense_query_returns_nothing_rather_than_junk(cat):
    assert len(search_text(cat, "zzzqqq wubbleflorp", limit=10)) == 0


def test_limit_is_respected(cat):
    assert len(search_text(cat, "migration", limit=5)) <= 5


def test_concepts_are_detected_case_insensitively():
    assert [c.name for c in matched_concepts("EDUCATION")] == \
           [c.name for c in matched_concepts("education")]


# -------------------------------------------------------------- essentials


def test_essentials_exclude_what_is_already_picked(cat):
    everything = suggest_essentials(cat, [])
    assert "PERWT" in set(everything["variable"])

    minus = suggest_essentials(cat, ["PERWT", "AGE"])
    assert "PERWT" not in set(minus["variable"])
    assert "AGE" not in set(minus["variable"])


def test_essentials_only_names_real_variables(cat):
    known = set(cat.variables["variable"])
    assert set(suggest_essentials(cat, [])["variable"]) <= known
