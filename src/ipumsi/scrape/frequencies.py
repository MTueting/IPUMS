"""Scrape per-variable case counts (the "Case-count view" on a variable page).

The counts table on a variable page is populated by JavaScript, so it is empty
in the served HTML. Two pieces are needed:

* the variable page itself carries a ``var codeData = {...}`` block with the
  sample list (numeric id -> sample name) and the category list (numeric id ->
  code and label);
* ``/international-action/frequencies/{VAR}`` returns the counts as JSON, keyed
  ``{sample_id: {category_id: {"count": N, "availability": "X"|"."}}}``.

Joining the two gives a tidy ``(variable, sample_id, code, label, count)`` frame.

This is deliberately fetched on demand rather than for all 1,709 variables:
AGE alone is ~100 categories x ~600 samples, so a full harvest would dwarf the
rest of the catalog. The page cache makes a repeat look-up free.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from ..config import SITE, VARIABLE_URL
from ..http import Fetcher

log = logging.getLogger(__name__)

FREQUENCIES_URL = f"{SITE}/frequencies/{{var}}"
CODE_DATA_RE = re.compile(r"var\s+codeData\s*=\s*\{", re.S)


def _extract_object(text: str, start: int) -> str:
    """Return the balanced ``{...}`` literal beginning at ``start``.

    A regex can't do this: the object contains category labels with braces and
    hundreds of nested entries. Counting depth outside of string literals can.
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unterminated codeData object")


def parse_code_data(html: str) -> tuple[dict[int, str], list[dict]]:
    """Return ``({sample_id: sample_name}, [category, ...])`` from a variable page."""
    match = CODE_DATA_RE.search(html)
    if match is None:
        raise ValueError("no codeData block on the page; the layout may have changed")

    literal = _extract_object(html, match.end() - 1)
    # codeData is a JS object literal with bare keys; its two values are valid
    # JSON arrays, so pull those out rather than trying to parse the whole thing.
    samples_at = literal.find("samples:")
    categories_at = literal.find("categories:")
    if samples_at < 0 or categories_at < 0:
        raise ValueError("codeData is missing samples or categories")

    def array_after(index: int) -> list:
        start = literal.index("[", index)
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(literal)):
            ch = literal[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return json.loads(literal[start : i + 1])
        raise ValueError("unterminated array in codeData")

    samples = {int(s["id"]): s["name"] for s in array_after(samples_at)}
    categories = array_after(categories_at)
    return samples, categories


def parse_frequencies(
    payload: dict, samples: dict[int, str], categories: list[dict], variable: str
) -> pd.DataFrame:
    """Join the counts JSON onto the sample and category maps."""
    by_id = {int(c["id"]): c for c in categories}
    rows = []
    for sample_key, counts in (payload or {}).items():
        sample = samples.get(int(sample_key))
        if sample is None:
            continue
        for category_key, entry in (counts or {}).items():
            category = by_id.get(int(category_key))
            if category is None:
                continue
            rows.append(
                {
                    "variable": variable,
                    "sample_id": sample,
                    "code": str(category.get("code", "")),
                    "label": category.get("label", ""),
                    "general": bool(category.get("general")),
                    "indent": int(category.get("indent", 0) or 0),
                    "count": int(entry.get("count", 0) or 0),
                    "available": entry.get("availability") == "X",
                }
            )

    df = pd.DataFrame.from_records(
        rows,
        columns=["variable", "sample_id", "code", "label", "general", "indent", "count", "available"],
    )
    if df.empty:
        return df
    # Share within each sample, so distributions are comparable across samples
    # of wildly different size.
    totals = df.groupby("sample_id")["count"].transform("sum")
    df["share"] = (df["count"] / totals).where(totals > 0, 0.0)
    return df


def fetch_frequencies(
    fetcher: Fetcher, variable: str, refresh: bool = False
) -> pd.DataFrame:
    """Case counts for one variable, as ``(sample_id, code, label, count, share)``."""
    variable = variable.strip().upper()
    page = fetcher.get(VARIABLE_URL.format(var=variable), refresh=refresh)
    samples, categories = parse_code_data(page)

    raw = fetcher.get(FREQUENCIES_URL.format(var=variable), refresh=refresh)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"frequencies for {variable} were not JSON") from exc

    df = parse_frequencies(payload, samples, categories, variable)
    log.info("%s: %d category x sample counts", variable, len(df))
    return df
