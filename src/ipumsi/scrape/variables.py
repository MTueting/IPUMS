"""Scrape the IPUMS International variable list.

Source: https://international.ipums.org/international-action/variables/group

The browse pages are organised into 29 groups (Education, Migration: A-E,
Geography: Global, ...) and paginate at 60 variables per page. Each row gives
the mnemonic, its label, and the record type (P = person, H = household).

The availability matrix printed on these pages is *session dependent* -- it only
covers whichever samples happen to be in the visitor's cart -- so it is ignored
here. Real availability comes from the per-variable pages; see
:mod:`ipumsi.scrape.availability`.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

from ..config import GROUP_INDEX_URL, SITE
from ..http import Fetcher

log = logging.getLogger(__name__)

VAR_HREF_RE = re.compile(r"^/international-action/variables/([A-Z][A-Z0-9_]*)$")
GROUP_HREF_RE = re.compile(r"variables/group\?id=([A-Za-z0-9_-]+)")


def discover_groups(fetcher: Fetcher, refresh: bool = False) -> dict[str, str]:
    """Return ``{group_id: group_label}`` for every variable group.

    The group index only links the top-level groups; sub-groups (``h-geog1``,
    ``occ-ind``, ...) appear in the sidebar of the group pages themselves, so
    this walks to closure.
    """
    labels: dict[str, str] = {}
    queue: list[str | None] = [None]
    visited: set[str | None] = set()

    while queue:
        group = queue.pop()
        if group in visited:
            continue
        visited.add(group)

        url = GROUP_INDEX_URL if group is None else f"{GROUP_INDEX_URL}?id={group}"
        soup = BeautifulSoup(fetcher.get(url, refresh=refresh), "lxml")
        for anchor in soup.find_all("a", href=GROUP_HREF_RE):
            match = GROUP_HREF_RE.search(anchor["href"])
            if not match:
                continue
            gid = match.group(1)
            label = anchor.get_text(" ", strip=True)
            if label:
                labels.setdefault(gid, label)
            if gid not in visited:
                queue.append(gid)

    if not labels:
        raise ValueError("no variable groups discovered; the page layout may have changed")
    return labels


def _parse_group_page(html: str) -> tuple[list[dict], str | None]:
    """Return the variable rows on one page plus the next page's path."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tr.variables"):
        anchor = tr.find("a", href=VAR_HREF_RE)
        if anchor is None:
            continue
        label_cell = tr.find("td", class_="labelColumn")
        record_cell = tr.find("td", title=re.compile(r"^(Person|Household)$"))
        rows.append(
            {
                "variable": VAR_HREF_RE.match(anchor["href"]).group(1),
                "label": label_cell.get_text(" ", strip=True) if label_cell else None,
                "record_type": record_cell.get_text(strip=True) if record_cell else None,
            }
        )

    next_link = soup.select_one("a.next_page[href]")
    return rows, next_link["href"] if next_link else None


def scrape_variables(fetcher: Fetcher, refresh: bool = False) -> pd.DataFrame:
    groups = discover_groups(fetcher, refresh=refresh)
    log.info("discovered %d variable groups", len(groups))

    records: list[dict] = []
    for gid, glabel in sorted(groups.items()):
        url: str | None = f"{GROUP_INDEX_URL}?id={gid}"
        page = 1
        while url:
            rows, next_href = _parse_group_page(fetcher.get(url, refresh=refresh))
            for row in rows:
                records.append({**row, "group": gid, "group_label": glabel})
            log.info("group %s page %d: %d variables", gid, page, len(rows))
            if next_href:
                url = next_href if next_href.startswith("http") else (
                    "https://international.ipums.org" + next_href
                )
                page += 1
            else:
                url = None

    if not records:
        raise ValueError("variable browse pages parsed to zero rows")

    df = pd.DataFrame.from_records(records)
    # A variable can be listed under more than one group; keep the memberships
    # as a single semicolon-joined field so the table stays one row per variable.
    grouped = (
        df.groupby("variable", as_index=False)
        .agg(
            label=("label", "first"),
            record_type=("record_type", "first"),
            group=("group", lambda s: ";".join(sorted(set(s)))),
            group_label=("group_label", lambda s: "; ".join(sorted(set(s)))),
        )
    )
    grouped["url"] = SITE + "/variables/" + grouped["variable"]
    return grouped.sort_values("variable").reset_index(drop=True)
