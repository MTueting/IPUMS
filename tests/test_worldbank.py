"""World Bank indicator fetch and join.

The join is deliberately exact on ``(iso3, year)``. Interpolating or snapping to
a nearest year would silently invent observations for census years the World
Bank does not cover, which is the sort of thing that ends up in a regression.
"""

from __future__ import annotations

import importlib

import pandas as pd
import pytest


@pytest.fixture
def wb(tmp_path, monkeypatch):
    from ipumsi import worldbank

    module = importlib.reload(worldbank)
    monkeypatch.setattr(module, "CACHE_DIR", tmp_path / "worldbank")
    yield module
    importlib.reload(worldbank)


def fake_api(pages: list[list[dict]]):
    """Stand in for requests.get, one call per page."""
    calls = {"n": 0}

    class Response:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def get(url, params=None, headers=None, timeout=None):
        page = params["page"]
        calls["n"] += 1
        return Response([{"page": page, "pages": len(pages)}, pages[page - 1]])

    return get, calls


def obs(iso3, year, value):
    return {"countryiso3code": iso3, "date": str(year), "value": value}


def test_fetch_drops_aggregates_and_nulls(wb, monkeypatch):
    get, _ = fake_api([[
        obs("BRA", 2010, 15000.0),
        obs("MEX", 2010, 18000.0),
        obs("BRA", 2011, None),          # no observation that year
        {"countryiso3code": "", "date": "2010", "value": 99.0},   # "World" aggregate
        {"countryiso3code": "EUU", "date": "2010", "value": 5.0}, # region: 3 letters, kept
    ]])
    monkeypatch.setattr(wb.requests, "get", get)

    df = wb.fetch_indicator("NY.GDP.PCAP.PP.KD")
    assert set(df.columns) == {"iso3", "year", "value"}
    assert ("BRA", 2011) not in set(zip(df["iso3"], df["year"]))
    assert "" not in set(df["iso3"])
    assert df["year"].dtype.kind == "i"


def test_fetch_follows_pagination(wb, monkeypatch):
    get, calls = fake_api([[obs("BRA", 2000, 1.0)], [obs("MEX", 2000, 2.0)]])
    monkeypatch.setattr(wb.requests, "get", get)

    df = wb.fetch_indicator("X")
    assert calls["n"] == 2
    assert sorted(df["iso3"]) == ["BRA", "MEX"]


def test_second_call_uses_the_cache(wb, monkeypatch):
    get, calls = fake_api([[obs("BRA", 2000, 1.0)]])
    monkeypatch.setattr(wb.requests, "get", get)

    wb.fetch_indicator("X")
    wb.fetch_indicator("X")
    assert calls["n"] == 1, "cached series was re-fetched"


def test_empty_response_raises_rather_than_returning_nothing(wb, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"message": "Invalid indicator"}]

    monkeypatch.setattr(wb.requests, "get", lambda *a, **k: Response())
    with pytest.raises(ValueError, match="no data"):
        wb.fetch_indicator("NOT.A.CODE")


def test_attach_joins_exactly_and_does_not_invent_years(wb, monkeypatch):
    get, _ = fake_api([[obs("BRA", 2010, 15000.0), obs("BRA", 2000, 11000.0)]])
    monkeypatch.setattr(wb.requests, "get", get)

    frame = pd.DataFrame({
        "iso3": ["BRA", "BRA", "MEX"],
        "year": [2010, 1991, 2010],     # 1991 has no observation; MEX has none at all
        "value": [0.5, 0.4, 0.6],
    })
    out = wb.attach(frame, "X", column="gdp")

    assert len(out) == len(frame), "join changed the number of rows"
    by_year = out.set_index("year")["gdp"]
    assert by_year[2010] .iloc[0] == 15000.0
    assert pd.isna(by_year[1991])       # not back-filled from 2000
    assert pd.isna(out.set_index("iso3").loc["MEX", "gdp"])


def test_attach_requires_the_join_keys(wb):
    with pytest.raises(KeyError, match="iso3"):
        wb.attach(pd.DataFrame({"year": [2010]}), "X")


def test_indicator_label_falls_back_to_the_code(wb):
    assert wb.indicator_label("NY.GDP.PCAP.PP.KD").startswith("GDP per capita")
    assert wb.indicator_label("MADE.UP") == "MADE.UP"
