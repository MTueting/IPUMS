"""Match a plain-English research question to IPUMS variables, with no model.

Type "the role of education on fertility" and get `EDATTAIN`, `YRSCHOOL`,
`CHBORN`, `CHSURV` back. This is ordinary string matching, so it is instant,
free, offline, deterministic, and the same for everyone.

Three signals, in decreasing weight:

1. **Concepts.** A small hand-written table maps everyday words onto the
   catalog's own vocabulary: "fertility" onto the *Fertility and Mortality*
   group and the mnemonic fragments IPUMS actually uses (`CHBORN`, `CHSURV`,
   `BIRTH`). This is what makes "education" find `YRSCHOOL`, which shares no
   letters with the word typed.
2. **Mnemonic and label text.** Stemmed word matching, so "migration" matches
   "migrant" and "fertility" matches "fertile".
3. **Description text.** Same matching, weighted low, as a long tail.

Naive substring matching is deliberately avoided: searching "income" for the
substring `inc` matches `PRINCE`, and "wage" matches `SEWAGE`. Everything here
works on whole stemmed tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# Words that carry no signal in a research question.
STOPWORDS = {
    "a", "about", "across", "after", "against", "all", "also", "am", "an", "analyse",
    "analysis", "analyze", "and", "any", "are", "as", "at", "be", "because", "been",
    "being", "below", "between", "both", "but", "by", "can", "compare", "could",
    "data", "did", "do", "does", "doing", "during", "each", "effect", "effects",
    "estimate", "explore", "few", "find", "for", "from", "further", "get", "had",
    "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how",
    "however", "i", "if", "im", "impact", "in", "influence", "interested", "into",
    "is", "it", "its", "just", "know", "like", "look", "looking", "made", "make",
    "many", "may", "me", "measure", "might", "more", "most", "much", "must", "my",
    "need", "no", "nor", "not", "now", "of", "on", "once", "only", "or", "other",
    "ought", "our", "out", "over", "own", "paper", "project", "question", "relate",
    "related", "relationship", "research", "role", "s", "same", "see", "she",
    "should", "so", "some", "study", "studying", "such", "t", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "through",
    "to", "too", "under", "understand", "until", "up", "us", "use", "using", "very",
    "want", "was", "we", "were", "what", "when", "where", "whether", "which",
    "while", "who", "whom", "why", "will", "with", "within", "would", "you", "your",
}

_SUFFIXES = (
    "ational", "ization", "iveness", "fulness", "ousness", "ability", "ibility",
    "ations", "ation", "ities", "ility", "ments", "ment", "ness", "ance", "ence",
    "ical", "ing", "ies", "ive", "ise", "ize", "ers", "est", "ed", "es", "al", "s",
)


def stem(word: str) -> str:
    """Crude but predictable suffix stripping.

    ``education``/``educational`` -> ``educ``; ``fertility``/``fertile`` ->
    ``fertil``; ``migration``/``migrants`` -> ``migrat``/``migrant``. A real
    stemmer would be better, but this needs no dependency and every rule here is
    visible and testable.
    """
    word = word.lower()
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    """Content words of a sentence, stemmed and de-duplicated in order."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    out, seen = [], set()
    for word in words:
        if len(word) < 3 or word in STOPWORDS:
            continue
        stemmed = stem(word)
        if stemmed in seen or stemmed in STOPWORDS:
            continue
        seen.add(stemmed)
        out.append(stemmed)
    return out


@dataclass(frozen=True)
class Concept:
    """A topic in a researcher's words, mapped to the catalog's words."""

    name: str
    triggers: tuple[str, ...]          # stems that switch this concept on
    groups: tuple[str, ...] = ()       # catalog group labels it covers
    mnemonics: tuple[str, ...] = ()    # exact variables worth surfacing first
    fragments: tuple[str, ...] = ()    # mnemonic substrings IPUMS actually uses


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "education",
        ("educ", "school", "literac", "literat", "univers", "colleg", "degre",
         "qualif", "learn", "student", "teach", "attain", "grade"),
        groups=("Education",),
        mnemonics=("EDATTAIN", "YRSCHOOL", "SCHOOL", "LIT", "EDATTAND"),
        fragments=("EDUC", "SCHOOL", "YRSCH", "LIT", "EDAT"),
    ),
    Concept(
        "fertility",
        ("fertil", "birth", "babi", "child", "children", "born", "parit",
         "reproduct", "pregnan", "mother"),
        groups=("Fertility and Mortality",),
        mnemonics=("CHBORN", "CHSURV", "NCHILD", "YNGCH", "ELDCH", "BIRTHYR"),
        fragments=("CHBORN", "CHSURV", "CHILD", "BIRTH", "FERT"),
    ),
    Concept(
        "mortality",
        ("mortal", "death", "die", "dead", "surviv", "widow"),
        groups=("Fertility and Mortality",),
        mnemonics=("CHSURV", "DEATHS"),
        fragments=("SURV", "DEATH", "MORT"),
    ),
    Concept(
        "migration",
        ("migrat", "migrant", "mobil", "move", "reloc", "resid", "flow",
         "internal", "origin", "destinat"),
        groups=("Migration: Global", "Migration: A-E", "Migration: F-N", "Migration: O-Z"),
        mnemonics=("MIGRATE1", "MIGRATE5", "MIGRATEP", "GEOMIG1_P", "GEOMIG1_1", "GEOMIG1_5"),
        fragments=("MIG", "GEOMIG"),
    ),
    Concept(
        "immigration",
        ("immigr", "emigr", "foreign", "abroad", "nativ", "citizen", "nation",
         "birthplac", "diaspora"),
        groups=("Nativity and Birthplace",),
        mnemonics=("BPLCOUNTRY", "CITIZEN", "YRIMM", "YRSIMM", "NATIVITY"),
        fragments=("BPL", "CITIZ", "IMM", "NATIV"),
    ),
    Concept(
        "income",
        ("incom", "wage", "earn", "salari", "pay", "wealth", "poverti", "poor",
         "rich", "afflu", "remitt"),
        groups=("Income",),
        mnemonics=("INCTOT", "INCWAGE", "INCEARN", "INCBUS1", "INCRETIR"),
        fragments=("INC",),
    ),
    Concept(
        "work",
        ("work", "employ", "unemploy", "labour", "labor", "job", "occupat",
         "industri", "profess", "career", "worker"),
        groups=("Work", "Occupation, Industry"),
        mnemonics=("EMPSTAT", "LABFORCE", "OCC", "IND", "OCCISCO", "INDGEN", "CLASSWK"),
        fragments=("EMP", "LAB", "OCC", "IND", "WORK", "HRSWORK"),
    ),
    Concept(
        "demographics",
        ("age", "sex", "gender", "male", "femal", "marit", "marriag", "marri",
         "spous", "cohort", "individu", "person", "adult", "elder"),
        groups=("Demographic",),
        mnemonics=("AGE", "SEX", "MARST", "RELATE", "AGE2"),
        fragments=("AGE", "SEX", "MARST"),
    ),
    Concept(
        "household",
        ("household", "famili", "hous", "home", "dwell", "member", "head",
         "coresid", "size"),
        groups=("Constructed Household", "Other Household", "Dwelling Characteristics"),
        mnemonics=("PERSONS", "NFAMS", "HHTYPE", "RELATE", "OWNERSHIP"),
        fragments=("HH", "FAM", "PERSONS", "OWNERSH"),
    ),
    Concept(
        "housing quality",
        ("sanitat", "water", "electr", "toilet", "sewag", "floor", "roof",
         "wall", "amenit", "utiliti", "infrastructur", "fuel", "applianc"),
        groups=("Utilities", "Dwelling Characteristics", "Appliances, Mechanicals, Other Amenities"),
        mnemonics=("WATSUP", "SEWAGE", "ELECTRIC", "TOILET", "FLOOR", "ROOF"),
        fragments=("WAT", "SEWAGE", "ELECTRIC", "TOILET", "FLOOR", "ROOF", "FUEL"),
    ),
    Concept(
        "geography",
        ("geograph", "region", "district", "provinc", "state", "municip",
         "spatial", "subnat", "area", "place", "map"),
        groups=("Geography: Global", "Geography: A-E", "Geography: F-N",
                "Geography: O-Z", "Geography: IPUMS-I, IPUMS-DHS"),
        mnemonics=("GEOLEV1", "GEOLEV2", "COUNTRY", "REGIONW"),
        fragments=("GEO", "REGION"),
    ),
    Concept(
        "urbanisation",
        ("urban", "rural", "citi", "town", "villag", "metropolitan"),
        mnemonics=("URBAN", "URBANMX"),
        fragments=("URBAN", "RURAL"),
    ),
    Concept(
        "ethnicity",
        ("ethnic", "languag", "religion", "race", "racial", "indigen", "tribe",
         "caste", "minor"),
        groups=("Ethnicity and Language",),
        mnemonics=("ETHNICPH", "RELIGION", "LANGUAGE", "RACE"),
        fragments=("ETHNIC", "RELIG", "LANG", "RACE", "INDIG"),
    ),
    Concept(
        "disability",
        ("disabil", "handicap", "impair", "blind", "deaf", "health", "ill"),
        groups=("Disability",),
        mnemonics=("DISABLED", "DISBLND", "DISDEAF"),
        fragments=("DIS",),
    ),
)

# Variables that almost every analysis needs but nobody types into a search box.
ESSENTIALS: dict[str, str] = {
    "PERWT": "Person weight - needed for any population-representative estimate.",
    "HHWT": "Household weight - the household-level equivalent.",
    "YEAR": "Census year.",
    "SAMPLE": "IPUMS sample identifier.",
    "SERIAL": "Household identifier, for linking person and household records.",
    "GEOLEV1": "First subnational unit, harmonised across countries.",
    "AGE": "Age - almost always a control.",
    "SEX": "Sex - almost always a control.",
}


@dataclass
class Match:
    variable: str
    label: str
    group: str
    record_type: str
    n_samples: int
    score: float
    n_countries: int = 0
    why: list[str] = field(default_factory=list)
    concept: str = ""


def _label_tokens(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) >= 3}


def _matches(token: str, tokens: set[str]) -> bool:
    """Prefix-tolerant stem comparison.

    Suffix stripping is not perfectly consistent -- "fertility" reduces to
    "fertil" but "fertile" stays whole -- so exact equality would miss obvious
    matches. Comparing on a shared prefix of at least four characters keeps
    those together without letting "age" match "agency".
    """
    if token in tokens:
        return True
    return any(
        len(other) >= 4 and len(token) >= 4
        and (other.startswith(token) or token.startswith(other))
        for other in tokens
    )


def matched_concepts(query: str) -> list[Concept]:
    """Concepts whose trigger words appear in the query."""
    stems = set(tokenize(query))
    hits = []
    for concept in CONCEPTS:
        # A trigger matches if the query stem starts with it, or vice versa --
        # "educ" from the table meets "educ" from "education" either way round.
        if any(s.startswith(t) or t.startswith(s) for t in concept.triggers for s in stems):
            hits.append(concept)
    return hits


def search_text(
    catalog,
    query: str,
    limit: int = 40,
    record_type: str | None = None,
    include_country_specific: bool = False,
) -> pd.DataFrame:
    """Rank catalog variables against a free-text research question.

    Two things stop the ranking being a naive relevance sort:

    * **Country-specific recodes are demoted.** 1,439 of the 1,709 variables
      exist in exactly one country (``EDUCUS`` is US-only, 9 samples), and they
      otherwise swamp the harmonised ones that make cross-country work possible
      (``EDATTAIN``, 98 countries). Set ``include_country_specific`` to rank them
      normally.
    * **Concepts are interleaved.** "education on fertility" is two topics, and a
      flat sort returns ten education variables and no fertility. Results are
      taken round-robin per concept so every topic in the question is
      represented.
    """
    stems = tokenize(query)
    concepts = matched_concepts(query)
    if not stems and not concepts:
        return pd.DataFrame(
            columns=["variable", "label", "group_label", "record_type", "n_samples", "score", "why"]
        )

    concept_groups: dict[str, list[str]] = {}
    concept_mnemonics: dict[str, list[str]] = {}
    concept_fragments: dict[str, list[str]] = {}
    for concept in concepts:
        for group in concept.groups:
            concept_groups.setdefault(group, []).append(concept.name)
        for mnemonic in concept.mnemonics:
            concept_mnemonics.setdefault(mnemonic, []).append(concept.name)
        for fragment in concept.fragments:
            concept_fragments.setdefault(fragment, []).append(concept.name)

    variables = catalog.variables
    if record_type:
        variables = variables[variables["record_type"] == record_type.upper()]

    max_samples = max(int(variables["n_samples"].max() or 1), 1)
    matches: list[Match] = []

    for row in variables.itertuples():
        score = 0.0
        why: list[str] = []
        mnemonic = row.variable
        primary_concept = ""

        # 1. Concepts.
        if mnemonic in concept_mnemonics:
            score += 12
            names = concept_mnemonics[mnemonic]
            primary_concept = names[0]
            why.append(f"key {'/'.join(names)} variable")
        else:
            for fragment, names in concept_fragments.items():
                if mnemonic.startswith(fragment):
                    score += 5
                    primary_concept = primary_concept or names[0]
                    why.append(f"{'/'.join(names)} variable")
                    break
        if row.group_label in concept_groups:
            score += 6
            primary_concept = primary_concept or concept_groups[row.group_label][0]
            why.append(f"in the {row.group_label} group")

        # 2. Mnemonic and label text.
        label_tokens = _label_tokens(row.label)
        mnemonic_stem = stem(mnemonic)
        for token in stems:
            if mnemonic_stem.startswith(token) or token.startswith(mnemonic.lower()):
                score += 8
                why.append(f"name matches '{token}'")
            elif _matches(token, label_tokens):
                score += 5
                why.append(f"label mentions '{token}'")

        # 3. Description text, as a long tail.
        description = getattr(row, "description", "") or ""
        if description and score:
            description_tokens = _label_tokens(description[:600])
            overlap = [t for t in stems if _matches(t, description_tokens)]
            if overlap:
                score += min(len(overlap), 3)
                why.append("described in these terms")

        if score <= 0:
            continue

        # Nudge widely-available variables up; never let this outrank relevance.
        score += 2.0 * (int(row.n_samples) / max_samples)

        # Technical variables (PERNUM, SERIAL, ...) are auto-included in every
        # extract anyway, and they match words like "person" that appear in
        # almost any research question. Keep them findable, out of the way.
        if (row.group_label or "").startswith("Technical"):
            score *= 0.5
            why.append("technical variable, added automatically")

        n_countries = int(getattr(row, "n_countries", 0) or 0)
        country_specific = n_countries <= 1
        if country_specific:
            if not include_country_specific:
                score *= 0.45
            why.append("single-country recode")

        matches.append(
            Match(
                variable=mnemonic,
                label=row.label or "",
                group=row.group_label or "",
                record_type=row.record_type or "",
                n_samples=int(row.n_samples),
                n_countries=n_countries,
                score=round(score, 2),
                why=list(dict.fromkeys(why))[:3],
                concept=primary_concept or "",
            )
        )

    matches.sort(key=lambda m: (-m.score, -m.n_samples, m.variable))
    ordered = _interleave(matches, limit) if len(concepts) > 1 else matches[:limit]
    return pd.DataFrame(
        [
            {
                "variable": m.variable,
                "label": m.label,
                "group_label": m.group,
                "record_type": m.record_type,
                "n_countries": m.n_countries,
                "n_samples": m.n_samples,
                "score": m.score,
                "why": "; ".join(m.why),
                "topic": m.concept,
            }
            for m in ordered
        ]
    )


def _interleave(matches: list["Match"], limit: int) -> list["Match"]:
    """Take results round-robin per topic so no one topic swamps the rest."""
    by_concept: dict[str, list[Match]] = {}
    for match in matches:
        by_concept.setdefault(match.concept, []).append(match)

    out: list[Match] = []
    while len(out) < limit and any(by_concept.values()):
        for bucket in by_concept.values():
            if bucket and len(out) < limit:
                out.append(bucket.pop(0))
    return out


def suggest_essentials(catalog, picked: list[str]) -> pd.DataFrame:
    """Weights, identifiers and standard controls the user has not picked yet."""
    known = set(catalog.variables["variable"])
    chosen = {v.upper() for v in picked}
    rows = [
        {"variable": name, "reason": reason}
        for name, reason in ESSENTIALS.items()
        if name in known and name not in chosen
    ]
    return pd.DataFrame(rows, columns=["variable", "reason"])
