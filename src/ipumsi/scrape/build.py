"""Build the whole catalog and write it to ``data/``."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd

from .. import config
from ..countries import ISO2, ISO3
from ..http import Fetcher
from .availability import resolve_samples, scrape_availability
from .samples import scrape_samples
from .variables import scrape_variables

log = logging.getLogger(__name__)


def build_catalog(
    refresh: bool = False,
    limit_variables: int | None = None,
    delay: float | None = None,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Scrape everything and write the catalog files. Returns the frames."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(delay=delay if delay is not None else 0.34, use_cache=use_cache)

    log.info("scraping sample IDs")
    samples = scrape_samples(fetcher, refresh=refresh)
    log.info("  %d samples", len(samples))

    log.info("scraping variable list")
    variables = scrape_variables(fetcher, refresh=refresh)
    log.info("  %d variables", len(variables))

    names = variables["variable"].tolist()
    if limit_variables:
        names = names[:limit_variables]
    log.info("scraping availability for %d variables", len(names))
    availability, descriptions = scrape_availability(fetcher, names, refresh=refresh)
    log.info("  %d (variable, country, token) rows", len(availability))

    variables = variables.merge(descriptions, on="variable", how="left")
    counts = availability.groupby("variable").agg(
        n_countries=("country", "nunique"), n_samples=("token", "size")
    )
    variables = variables.merge(counts, on="variable", how="left")
    variables[["n_countries", "n_samples"]] = (
        variables[["n_countries", "n_samples"]].fillna(0).astype(int)
    )

    variable_samples = resolve_samples(availability, samples)
    log.info("  %d resolved (variable, sample) pairs", len(variable_samples))

    countries = (
        samples.groupby("country", as_index=False)
        .agg(
            country_prefix=("country_prefix", "first"),
            n_samples=("sample_id", "size"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .sort_values("country")
    )
    countries["iso2"] = countries["country_prefix"].map(ISO2)
    countries["iso3"] = countries["country_prefix"].map(ISO3)

    samples.to_csv(config.SAMPLES_CSV, index=False, encoding="utf-8")
    variables.to_csv(config.VARIABLES_CSV, index=False, encoding="utf-8")
    countries.to_csv(config.COUNTRIES_CSV, index=False, encoding="utf-8")
    availability.to_parquet(config.AVAILABILITY_PARQUET, index=False)
    variable_samples.to_parquet(config.VAR_SAMPLES_PARQUET, index=False)

    meta = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_samples": int(len(samples)),
        "n_variables": int(len(variables)),
        "n_countries": int(len(countries)),
        "n_availability_rows": int(len(availability)),
        "n_variable_sample_pairs": int(len(variable_samples)),
        "source": "https://international.ipums.org (public browse pages)",
    }
    config.CATALOG_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("catalog written to %s", config.DATA_DIR)

    return {
        "samples": samples,
        "variables": variables,
        "countries": countries,
        "availability": availability,
        "variable_samples": variable_samples,
    }
