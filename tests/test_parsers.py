"""Parser tests against fixture HTML captured from the IPUMS website.

These lock the scraper to the page shapes it was written for: if IPUMS
restructures a page, the failure shows up here rather than as a catalog that
quietly loses half its rows.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ipumsi.scrape.availability import parse_variable_page, resolve_samples
from ipumsi.scrape.samples import _parse_description, parse_samples
from ipumsi.scrape.variables import _parse_group_page

SAMPLES_HTML = """
<table class="supplementalTable">
  <tr class="supplementalHeader"><th>Sample ID</th><th>Description</th></tr>
  <tr><td><span>br2010a</span></td><td>Brazil 2010</td></tr>
  <tr><td><span>es2005h</span></td><td>Spain 2005 Q1 LFS</td></tr>
  <tr><td><span>uk1851b</span></td><td>United Kingdom 1851 [Scotland]</td></tr>
  <tr><td><span>us1850a</span></td><td>United States 1850 (100%)</td></tr>
  <tr><td><span>ng2006a</span></td><td>Nigeria 2006-07</td></tr>
  <tr><td><span>de1819a</span></td><td>Germany [Mecklenburg-Schwerin] 1819</td></tr>
</table>
"""

GROUP_HTML = """
<table class="variablesList">
  <tr class="variables">
    <td class="checkbox-column"></td>
    <td class="mbasic"><a href="/international-action/variables/GEOMIG1_P">GEOMIG1_P</a></td>
    <td class="labelColumn">1st subnational geographic level of previous residence</td>
    <td title="Person">P</td>
    <td class="unselectedSamples"><span title="Available">X</span></td>
  </tr>
  <tr class="variables">
    <td class="checkbox-column"></td>
    <td class="mbasic"><a href="/international-action/variables/HHWT">HHWT</a></td>
    <td class="labelColumn">Household weight</td>
    <td title="Household">H</td>
  </tr>
</table>
<a class="next_page" href="/international-action/variables/group/mig?page=2">Next</a>
"""

VARIABLE_HTML = """
<div id="description_section">Description GEOMIG1_P indicates the major administrative unit.</div>
<ul id="availability">
  <li>Brazil:
      2000, 2010
  </li>
  <li>Spain:
      2011, 2005Q1
  </li>
  <li>United Kingdom:
      1851b, 1911
  </li>
</ul>
"""


def test_parse_samples_columns_and_ids():
    df = parse_samples(SAMPLES_HTML)
    assert list(df["sample_id"]) == [
        "br2010a", "de1819a", "es2005h", "ng2006a", "uk1851b", "us1850a",
    ]
    row = df.set_index("sample_id").loc["br2010a"]
    assert (row["country"], row["year"], row["iso3"], row["kind"]) == ("Brazil", 2010, "BRA", "census")
    assert df.set_index("sample_id").loc["uk1851b", "iso3"] == "GBR"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Brazil 2010", {"country": "Brazil", "year": 2010, "kind": "census"}),
        ("Spain 2005 Q1 LFS", {"country": "Spain", "year": 2005, "quarter": 1, "kind": "LFS"}),
        ("United Kingdom 1851 [Scotland]", {"country": "United Kingdom", "year": 1851, "subsample": "Scotland"}),
        ("United States 1850 (100%)", {"country": "United States", "year": 1850, "subsample": "100%"}),
        ("Nigeria 2006-07", {"country": "Nigeria", "year": 2006, "year_end": 2007}),
        ("Germany [Mecklenburg-Schwerin] 1819", {"country": "Germany", "year": 1819, "subsample": "Mecklenburg-Schwerin"}),
    ],
)
def test_parse_description(description, expected):
    parsed = _parse_description(description)
    for key, value in expected.items():
        assert parsed[key] == value, f"{description}: {key}"


def test_parse_group_page():
    rows, next_href = _parse_group_page(GROUP_HTML)
    assert rows[0] == {
        "variable": "GEOMIG1_P",
        "label": "1st subnational geographic level of previous residence",
        "record_type": "P",
    }
    assert rows[1]["record_type"] == "H"
    assert next_href == "/international-action/variables/group/mig?page=2"


def test_parse_variable_page_tokens():
    rows, description = parse_variable_page(VARIABLE_HTML, "GEOMIG1_P")
    tokens = {(r["country"], r["token"]) for r in rows}
    assert tokens == {
        ("Brazil", "2000"), ("Brazil", "2010"),
        ("Spain", "2011"), ("Spain", "2005Q1"),
        ("United Kingdom", "1851b"), ("United Kingdom", "1911"),
    }
    spain_q1 = next(r for r in rows if r["token"] == "2005Q1")
    assert (spain_q1["year"], spain_q1["quarter"]) == (2005, 1)
    uk_b = next(r for r in rows if r["token"] == "1851b")
    assert (uk_b["year"], uk_b["suffix"]) == (1851, "b")
    assert description.startswith("GEOMIG1_P indicates")


def test_resolve_samples_maps_every_token_shape():
    samples = parse_samples(
        SAMPLES_HTML.replace(
            "<tr><td><span>br2010a</span></td><td>Brazil 2010</td></tr>",
            "<tr><td><span>br2000a</span></td><td>Brazil 2000</td></tr>"
            "<tr><td><span>br2010a</span></td><td>Brazil 2010</td></tr>"
            "<tr><td><span>es2011a</span></td><td>Spain 2011</td></tr>"
            "<tr><td><span>uk1851a</span></td><td>United Kingdom 1851 [England and Wales]</td></tr>"
            "<tr><td><span>uk1911a</span></td><td>United Kingdom 1911</td></tr>",
        )
    )
    rows, _ = parse_variable_page(VARIABLE_HTML, "GEOMIG1_P")
    availability = pd.DataFrame(rows)
    availability["year"] = availability["year"].astype("Int64")
    availability["quarter"] = availability["quarter"].astype("Int64")

    resolved = resolve_samples(availability, samples)
    mapping = dict(zip(resolved["token"], resolved["sample_id"]))
    assert mapping == {
        "2000": "br2000a",
        "2010": "br2010a",
        "2011": "es2011a",
        "2005Q1": "es2005h",   # quarter token -> LFS sample
        "1851b": "uk1851b",    # letter token -> that exact suffix
        "1911": "uk1911a",     # bare year -> the plain census
    }
