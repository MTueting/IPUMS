"""Scrape the IPUMS International sample-ID table.

Source: https://international.ipums.org/international-action/samples/sample_ids

Each row is ``sample_id | description``, e.g. ``br2010a | Brazil 2010``.
Descriptions carry a handful of shapes worth normalising:

    Armenia 2001                          -> country=Armenia, year=2001
    Nigeria 2006-07                       -> year=2006, year_end=2007
    Spain 2005 Q1 LFS                     -> quarter=1, kind=LFS
    United Kingdom 1851 [England and Wales] -> subsample="England and Wales"
    United States 1850 (100%)             -> subsample="100%"
    Germany [Mecklenburg-Schwerin] 1819   -> subsample="Mecklenburg-Schwerin"
"""

from __future__ import annotations

import re

import pandas as pd
from bs4 import BeautifulSoup

from ..config import SAMPLE_IDS_URL
from ..countries import iso2, iso3, normalize_country
from ..http import Fetcher

SAMPLE_ID_RE = re.compile(r"^([a-z]{2})(\d{4})([a-z0-9]*)$")


def _parse_description(desc: str) -> dict:
    """Split a sample description into country / year / qualifiers."""
    out: dict[str, object] = {
        "country": None,
        "year": None,
        "year_end": None,
        "quarter": None,
        "kind": "census",
        "subsample": None,
    }

    text = desc.strip()

    if re.search(r"\bLFS\b", text):
        out["kind"] = "LFS"
        text = re.sub(r"\s*\bLFS\b", "", text)

    quarter = re.search(r"\bQ([1-4])\b", text)
    if quarter:
        out["quarter"] = int(quarter.group(1))
        text = text.replace(quarter.group(0), "")

    # Bracketed or parenthesised qualifiers, wherever they sit.
    qualifiers = re.findall(r"[\[(]([^\])]+)[\])]", text)
    if qualifiers:
        out["subsample"] = "; ".join(q.strip() for q in qualifiers)
        text = re.sub(r"\s*[\[(][^\])]+[\])]", "", text)

    # Year, optionally a hyphenated span ("2006-07" or "1990-1991").
    span = re.search(r"\b(\d{4})(?:\s*-\s*(\d{2,4}))?\b", text)
    if span:
        year = int(span.group(1))
        out["year"] = year
        if span.group(2):
            end = span.group(2)
            out["year_end"] = int(end) if len(end) == 4 else year - year % 100 + int(end)
            # Handle a century rollover such as 1999-00.
            if out["year_end"] < year:
                out["year_end"] = int(out["year_end"]) + 100
        text = text[: span.start()] + " " + text[span.end() :]

    out["country"] = normalize_country(re.sub(r"\s+", " ", text).strip(" ,-"))
    return out


def parse_samples(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="supplementalTable")
    if table is None:
        raise ValueError("sample-ID table not found; the page layout may have changed")

    records = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        sample_id = cells[0].get_text(" ", strip=True)
        description = cells[1].get_text(" ", strip=True)
        if not sample_id:
            continue

        rec: dict[str, object] = {"sample_id": sample_id, "description": description}
        rec.update(_parse_description(description))

        match = SAMPLE_ID_RE.match(sample_id)
        prefix = match.group(1) if match else sample_id[:2]
        rec["country_prefix"] = prefix
        rec["iso2"] = iso2(prefix)
        rec["iso3"] = iso3(prefix)
        # The trailing letter distinguishes samples of the same country-year.
        rec["sample_suffix"] = match.group(3) if match else None
        records.append(rec)

    if not records:
        raise ValueError("sample-ID table parsed to zero rows")

    df = pd.DataFrame.from_records(records)
    df["year"] = df["year"].astype("Int64")
    df["year_end"] = df["year_end"].astype("Int64")
    df["quarter"] = df["quarter"].astype("Int64")
    columns = [
        "sample_id", "country", "iso2", "iso3", "country_prefix", "year",
        "year_end", "quarter", "kind", "subsample", "sample_suffix", "description",
    ]
    return df[columns].sort_values("sample_id").reset_index(drop=True)


def scrape_samples(fetcher: Fetcher, refresh: bool = False) -> pd.DataFrame:
    return parse_samples(fetcher.get(SAMPLE_IDS_URL, refresh=refresh))
