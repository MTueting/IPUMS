"""Country x year covariates from the World Bank indicator API.

The catalog already carries an ISO 3166-1 alpha-3 code for every IPUMS country,
which is exactly what the World Bank keys on -- so a country-year measure from a
census extract joins straight onto GDP per capita, urbanisation, life expectancy
or anything else in the WDI.

Series are cached under ``data/worldbank/`` so a plot redraws offline.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from .config import DATA_DIR, USER_AGENT

log = logging.getLogger(__name__)

API = "https://api.worldbank.org/v2/country/all/indicator/{code}"
CACHE_DIR = DATA_DIR / "worldbank"

#: A short, opinionated list of the covariates this kind of work usually wants.
#: Any other WDI indicator code works too -- these are just the ones offered up
#: front so nobody has to go hunting for a code.
INDICATORS: dict[str, str] = {
    "NY.GDP.PCAP.PP.KD": "GDP per capita, PPP (constant 2021 international $)",
    "NY.GDP.PCAP.KD": "GDP per capita (constant 2015 US$)",
    "NY.GDP.MKTP.PP.KD": "GDP, PPP (constant 2021 international $)",
    "SP.POP.TOTL": "Population, total",
    "SP.URB.TOTL.IN.ZS": "Urban population (% of total)",
    "SP.DYN.LE00.IN": "Life expectancy at birth (years)",
    "SP.DYN.TFRT.IN": "Fertility rate, total (births per woman)",
    "SE.SEC.ENRR": "School enrollment, secondary (% gross)",
    "SI.POV.GINI": "Gini index",
    "SL.TLF.CACT.FE.ZS": "Labour force participation rate, female (%)",
}

DEFAULT_INDICATOR = "NY.GDP.PCAP.PP.KD"


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.csv"


def fetch_indicator(
    code: str = DEFAULT_INDICATOR,
    refresh: bool = False,
    timeout: float = 120.0,
) -> pd.DataFrame:
    """Return ``(iso3, year, value)`` for one WDI indicator, all countries, all years."""
    path = _cache_path(code)
    if path.exists() and not refresh:
        return pd.read_csv(path)

    rows: list[dict] = []
    page = 1
    while True:
        response = requests.get(
            API.format(code=code),
            params={"format": "json", "per_page": 20000, "page": page},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            message = ""
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                message = str(payload[0].get("message", ""))
            raise ValueError(f"World Bank returned no data for {code!r}. {message}".strip())

        meta, batch = payload[0], payload[1]
        for entry in batch:
            iso3 = (entry.get("countryiso3code") or "").strip()
            value = entry.get("value")
            # Aggregates ("World", "Low income") have no 3-letter code; skip them.
            if len(iso3) != 3 or value is None:
                continue
            rows.append({"iso3": iso3, "year": int(entry["date"]), "value": float(value)})

        if page >= int(meta.get("pages", 1)):
            break
        page += 1

    df = pd.DataFrame(rows).sort_values(["iso3", "year"]).reset_index(drop=True)
    if df.empty:
        raise ValueError(f"World Bank returned no usable observations for {code!r}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("%s: %d observations, %d countries", code, len(df), df["iso3"].nunique())
    return df


def indicator_label(code: str) -> str:
    return INDICATORS.get(code, code)


def attach(
    frame: pd.DataFrame,
    code: str = DEFAULT_INDICATOR,
    column: str | None = None,
    how: str = "left",
    refresh: bool = False,
) -> pd.DataFrame:
    """Join an indicator onto a frame that already has ``iso3`` and ``year``.

    Census years rarely line up with nothing, but they are ordinary years, so a
    plain exact join on ``(iso3, year)`` is right -- no interpolation, no
    nearest-year fudging that would quietly invent observations.
    """
    missing = {"iso3", "year"} - set(frame.columns)
    if missing:
        raise KeyError(f"frame needs {sorted(missing)} to join World Bank data")

    series = fetch_indicator(code, refresh=refresh).rename(
        columns={"value": column or code}
    )
    return frame.merge(series, on=["iso3", "year"], how=how)
