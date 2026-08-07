"""Scrape per-variable sample availability.

Each variable page (``.../variables/GEOMIG1_P``) carries an ``<ul
id="availability">`` listing every country that harmonises the variable and the
sample tokens it is available in::

    United Kingdom: 1851a, 1851b, 1861a, ..., 1911, 1961, 1971, 1991, 2001
    Spain: 1981, 1991, 2001, 2005Q1, 2005Q2, ..., 2020Q4

Those tokens map one-to-one onto sample IDs:

    ``1911``   -> the country's plain census that year   (uk1911a)
    ``1851b``  -> the explicitly-suffixed sample         (uk1851b)
    ``2005Q1`` -> that quarter's labour-force survey     (es2005h)

:func:`resolve_samples` performs the mapping against the scraped sample table
rather than hard-coding the suffix conventions, and reports anything it cannot
place so a silent gap can never masquerade as "not available".
"""

from __future__ import annotations

import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

from ..config import VARIABLE_URL
from ..countries import normalize_country
from ..http import Fetcher

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^(\d{4})(?:Q([1-4])|([a-z]))?$")


def parse_variable_page(html: str, variable: str) -> tuple[list[dict], str | None]:
    """Return ``(availability_rows, description)`` for one variable page."""
    soup = BeautifulSoup(html, "lxml")

    rows: list[dict] = []
    ul = soup.find("ul", id="availability")
    if ul is not None:
        for li in ul.find_all("li"):
            text = " ".join(li.get_text(" ", strip=True).split())
            if ":" not in text:
                continue
            country, _, tokens = text.partition(":")
            country = normalize_country(country)
            for token in tokens.split(","):
                token = token.strip()
                if not token:
                    continue
                match = TOKEN_RE.match(token)
                rows.append(
                    {
                        "variable": variable,
                        "country": country,
                        "token": token,
                        "year": int(match.group(1)) if match else None,
                        "quarter": int(match.group(2)) if match and match.group(2) else None,
                        "suffix": match.group(3) if match else None,
                    }
                )

    description = None
    section = soup.find(id="description_section")
    if section is not None:
        text = " ".join(section.get_text(" ", strip=True).split())
        description = re.sub(r"^Description\s*", "", text)[:2000] or None

    return rows, description


def scrape_availability(
    fetcher: Fetcher,
    variables: list[str],
    refresh: bool = False,
    progress: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch every variable page. Returns ``(availability, descriptions)``."""
    rows: list[dict] = []
    descriptions: list[dict] = []
    missing: list[str] = []

    for i, variable in enumerate(variables, start=1):
        html = fetcher.get(VARIABLE_URL.format(var=variable), refresh=refresh)
        var_rows, description = parse_variable_page(html, variable)
        if not var_rows:
            missing.append(variable)
        rows.extend(var_rows)
        descriptions.append({"variable": variable, "description": description})
        if progress and (i % 50 == 0 or i == len(variables)):
            log.info("availability: %d/%d variables (%d rows)", i, len(variables), len(rows))

    if missing:
        log.warning(
            "%d variables had no availability list (e.g. %s)",
            len(missing),
            ", ".join(missing[:8]),
        )

    availability = pd.DataFrame.from_records(
        rows, columns=["variable", "country", "token", "year", "quarter", "suffix"]
    )
    availability["year"] = availability["year"].astype("Int64")
    availability["quarter"] = availability["quarter"].astype("Int64")
    return availability, pd.DataFrame.from_records(descriptions)


def resolve_samples(availability: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    """Map ``(country, token)`` availability onto concrete sample IDs.

    Returns one row per ``(variable, sample_id)``. Tokens that cannot be matched
    to a sample are dropped and logged -- they should be zero in a healthy
    scrape, and a nonzero count means the two pages have drifted apart.

    A country that appears in availability but nowhere in the sample table is a
    naming mismatch rather than a data gap, and raises: it would otherwise wipe
    out every one of that country's samples silently. Add the spelling to
    :data:`ipumsi.countries.COUNTRY_ALIASES`.
    """
    orphans = sorted(set(availability["country"]) - set(samples["country"]))
    if orphans:
        raise ValueError(
            "these countries appear in variable availability but not in the sample "
            f"table: {orphans}. Add them to ipumsi.countries.COUNTRY_ALIASES."
        )

    samples = samples.copy()
    samples["suffix"] = samples["sample_suffix"].fillna("")

    # A quarter token identifies the LFS sample for that country-year-quarter.
    quarterly = samples[samples["quarter"].notna()][["country", "year", "quarter", "sample_id"]]
    # A letter token identifies the sample with that exact suffix.
    suffixed = samples[["country", "year", "suffix", "sample_id"]]
    # A bare year token means "the" census that year: prefer suffix 'a', and
    # fall back to a unique non-quarterly sample if the suffix differs.
    non_quarterly = samples[samples["quarter"].isna()]
    plain = (
        non_quarterly.sort_values(["country", "year", "suffix"])
        .groupby(["country", "year"], as_index=False)
        .first()[["country", "year", "sample_id"]]
    )

    work = availability.copy()
    work["suffix"] = work["suffix"].fillna("")

    resolved = work.merge(quarterly, on=["country", "year", "quarter"], how="left")
    resolved = resolved.merge(
        suffixed, on=["country", "year", "suffix"], how="left", suffixes=("", "_sfx")
    )
    resolved = resolved.merge(
        plain, on=["country", "year"], how="left", suffixes=("", "_plain")
    )
    resolved["sample_id"] = (
        resolved["sample_id"]
        .fillna(resolved["sample_id_sfx"])
        .fillna(resolved["sample_id_plain"])
    )

    unmatched = resolved[resolved["sample_id"].isna()]
    if len(unmatched):
        examples = unmatched[["variable", "country", "token"]].head(10).to_dict("records")
        log.warning(
            "%d availability tokens could not be matched to a sample ID; examples: %s",
            len(unmatched),
            examples,
        )

    out = resolved[resolved["sample_id"].notna()][
        ["variable", "sample_id", "country", "year", "quarter", "token"]
    ]
    return out.drop_duplicates(["variable", "sample_id"]).sort_values(
        ["variable", "sample_id"]
    ).reset_index(drop=True)
