"""Query the scraped IPUMS International catalog.

Everything here reads the committed files in ``data/`` -- no network, no API
key. The question this is built to answer is the one that blocks every project
before it starts: *given the variables I need, which country-years can I
actually use?*

    >>> cat = Catalog.load()
    >>> cat.coverage(["GEOMIG1_P", "INCTOT", "EDATTAIN"])          # doctest: +SKIP
    >>> cat.samples_with(["GEOMIG1_P", "INCTOT"], how="all")       # doctest: +SKIP
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config


class CatalogNotBuilt(FileNotFoundError):
    pass


@dataclass
class Catalog:
    samples: pd.DataFrame
    variables: pd.DataFrame
    countries: pd.DataFrame
    variable_samples: pd.DataFrame
    meta: dict

    # ---------------------------------------------------------------- loading

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Catalog":
        data_dir = Path(data_dir or config.DATA_DIR)
        samples_csv = data_dir / config.SAMPLES_CSV.name
        variables_csv = data_dir / config.VARIABLES_CSV.name
        countries_csv = data_dir / config.COUNTRIES_CSV.name
        pairs_parquet = data_dir / config.VAR_SAMPLES_PARQUET.name
        meta_json = data_dir / config.CATALOG_META.name

        for path in (samples_csv, variables_csv, pairs_parquet):
            if not path.exists():
                raise CatalogNotBuilt(
                    f"{path} is missing. Build the catalog first: `ipumsi refresh`"
                )

        return cls(
            samples=pd.read_csv(samples_csv, encoding="utf-8"),
            variables=pd.read_csv(variables_csv, encoding="utf-8"),
            countries=(
                pd.read_csv(countries_csv, encoding="utf-8")
                if countries_csv.exists()
                else pd.DataFrame()
            ),
            variable_samples=pd.read_parquet(pairs_parquet),
            meta=(
                json.loads(meta_json.read_text(encoding="utf-8"))
                if meta_json.exists()
                else {}
            ),
        )

    # ------------------------------------------------------------- variables

    def search(self, query: str, record_type: str | None = None) -> pd.DataFrame:
        """Case-insensitive substring search over mnemonic, label and description."""
        df = self.variables
        if record_type:
            df = df[df["record_type"] == record_type.upper()]
        q = query.strip().lower()
        if not q:
            return df
        haystack = (
            df["variable"].str.lower()
            + " " + df["label"].fillna("").str.lower()
            + " " + df.get("description", pd.Series("", index=df.index)).fillna("").str.lower()
        )
        return df[haystack.str.contains(q, regex=False)]

    def variable(self, name: str) -> pd.Series:
        hit = self.variables[self.variables["variable"] == name.upper()]
        if hit.empty:
            raise KeyError(f"unknown variable {name!r}")
        return hit.iloc[0]

    def resolve_variables(self, names: list[str]) -> list[str]:
        """Upper-case and validate a list of mnemonics."""
        wanted = [n.strip().upper() for n in names if n.strip()]
        known = set(self.variables["variable"])
        unknown = [n for n in wanted if n not in known]
        if unknown:
            raise KeyError(f"unknown variable(s): {', '.join(unknown)}")
        return wanted

    # ---------------------------------------------------------- availability

    def availability(self, variables: list[str]) -> pd.DataFrame:
        """Long ``(variable, sample_id, country, year)`` rows for the given variables."""
        wanted = self.resolve_variables(variables)
        pairs = self.variable_samples[self.variable_samples["variable"].isin(wanted)]
        return pairs.merge(
            self.samples[["sample_id", "iso3", "kind", "subsample", "description"]],
            on="sample_id",
            how="left",
        )

    def matrix(self, variables: list[str]) -> pd.DataFrame:
        """Wide sample x variable boolean matrix; useful for eyeballing coverage."""
        wanted = self.resolve_variables(variables)
        pairs = self.variable_samples[self.variable_samples["variable"].isin(wanted)]
        if pairs.empty:
            return pd.DataFrame(columns=wanted)
        wide = (
            pairs.assign(available=True)
            .pivot_table(
                index=["country", "year", "sample_id"],
                columns="variable",
                values="available",
                aggfunc="first",
                observed=True,
            )
            .reindex(columns=wanted)
            .fillna(False)
            .astype(bool)
        )
        return wide.sort_index()

    def samples_with(
        self,
        variables: list[str],
        how: str = "all",
        countries: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        kind: str | None = None,
    ) -> pd.DataFrame:
        """Samples carrying ``all`` (default) or ``any`` of ``variables``.

        ``how="all"`` is the one that matters for extract planning: an extract
        is only usable where every variable in the analysis is present.
        """
        if how not in ("all", "any"):
            raise ValueError("how must be 'all' or 'any'")
        wanted = self.resolve_variables(variables)

        pairs = self.variable_samples[self.variable_samples["variable"].isin(wanted)]
        counts = pairs.groupby("sample_id")["variable"].nunique()
        keep = counts.index[counts == len(wanted)] if how == "all" else counts.index

        out = self.samples[self.samples["sample_id"].isin(keep)].copy()
        out["n_variables_present"] = out["sample_id"].map(counts).fillna(0).astype(int)
        out["missing_variables"] = out["sample_id"].map(
            lambda s: ";".join(sorted(set(wanted) - set(pairs.loc[pairs["sample_id"] == s, "variable"])))
        )

        if countries:
            wanted_countries = {c.strip().lower() for c in countries}
            out = out[
                out["country"].str.lower().isin(wanted_countries)
                | out["iso3"].fillna("").str.lower().isin(wanted_countries)
                | out["iso2"].fillna("").str.lower().isin(wanted_countries)
            ]
        if year_min is not None:
            out = out[out["year"] >= year_min]
        if year_max is not None:
            out = out[out["year"] <= year_max]
        if kind:
            out = out[out["kind"] == kind]

        return out.sort_values(["country", "year", "sample_id"]).reset_index(drop=True)

    def coverage(self, variables: list[str], how: str = "all") -> pd.DataFrame:
        """One row per country: how many samples satisfy the variable set, and which years."""
        hits = self.samples_with(variables, how=how)
        if hits.empty:
            return pd.DataFrame(
                columns=["country", "iso3", "n_samples", "years", "first_year", "last_year"]
            )
        return (
            hits.groupby(["country", "iso3"], dropna=False, as_index=False)
            .agg(
                n_samples=("sample_id", "size"),
                years=("year", lambda s: ", ".join(str(y) for y in sorted(set(s.dropna())))),
                first_year=("year", "min"),
                last_year=("year", "max"),
            )
            .sort_values(["n_samples", "country"], ascending=[False, True])
            .reset_index(drop=True)
        )

    def variables_in(self, samples: list[str]) -> pd.DataFrame:
        """Variables available in *every* one of the given samples."""
        wanted = [s.strip().lower() for s in samples if s.strip()]
        known = set(self.samples["sample_id"])
        unknown = [s for s in wanted if s not in known]
        if unknown:
            raise KeyError(f"unknown sample(s): {', '.join(unknown)}")
        pairs = self.variable_samples[self.variable_samples["sample_id"].isin(wanted)]
        counts = pairs.groupby("variable")["sample_id"].nunique()
        keep = counts.index[counts == len(wanted)]
        return (
            self.variables[self.variables["variable"].isin(keep)]
            .sort_values("variable")
            .reset_index(drop=True)
        )


@lru_cache(maxsize=1)
def load() -> Catalog:
    """Cached catalog load, for interactive and Streamlit use."""
    return Catalog.load()
