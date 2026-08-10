"""Turn a downloaded extract into country x year measures.

An IPUMS extract is person-level and large -- extract 99 here is 47 million rows
across 88 country-years -- so nothing loads the whole file. Everything streams in
chunks and accumulates weighted sums, which keeps memory flat regardless of size.

Weights matter and are not optional: an IPUMS sample is not self-weighting, so an
unweighted share is not an estimate of anything. ``PERWT`` (or ``HHWT``) is used
throughout, and the result records how many unweighted cases sat behind each
point so a country-year resting on 40 observations is visible as such.

The DDI codebook that ships with every extract supplies the value labels, so the
country codes and category names come from the extract itself rather than from a
table here that could drift.
"""

from __future__ import annotations

import gzip
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import EXTRACT_DIR

log = logging.getLogger(__name__)

DDI_NS = {"d": "ddi:codebook:2_5"}
CHUNK_ROWS = 2_000_000


@dataclass
class Extract:
    """A downloaded extract: its data file, and the labels from its codebook."""

    number: int
    data_path: Path
    ddi_path: Path | None = None
    variable_labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict[int, str]] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return _header(self.data_path)

    def labels_for(self, variable: str) -> dict[int, str]:
        return self.value_labels.get(variable.upper(), {})

    def label_of(self, variable: str) -> str:
        return self.variable_labels.get(variable.upper(), variable.upper())


def find_extracts(folder: Path | None = None) -> list[Extract]:
    """Every downloaded extract, newest number first."""
    root = Path(folder or EXTRACT_DIR)
    if not root.is_dir():
        return []

    found: list[Extract] = []
    for sub in sorted(root.iterdir(), reverse=True):
        if not sub.is_dir():
            continue
        match = re.search(r"(\d+)$", sub.name)
        if not match:
            continue
        data = next(
            (p for p in sorted(sub.iterdir())
             if p.suffixes[-2:] in ([".csv", ".gz"], [".dat", ".gz"]) or p.suffix == ".csv"),
            None,
        )
        if data is None:
            continue
        if data.name.endswith(".dat.gz"):
            # Fixed-width needs the DDI column layout to parse; not supported yet.
            log.info("skipping %s: fixed-width extracts are not readable here", data.name)
            continue
        ddi = next((p for p in sub.iterdir() if p.suffix == ".xml"), None)
        extract = Extract(number=int(match.group(1)), data_path=data, ddi_path=ddi)
        if ddi is not None:
            extract.variable_labels, extract.value_labels = read_ddi(ddi)
        found.append(extract)
    return found


def read_ddi(path: Path) -> tuple[dict[str, str], dict[str, dict[int, str]]]:
    """Variable labels and value labels from an IPUMS DDI codebook."""
    root = ET.parse(path).getroot()
    variable_labels: dict[str, str] = {}
    value_labels: dict[str, dict[int, str]] = {}

    for var in root.iter(f"{{{DDI_NS['d']}}}var"):
        name = (var.get("name") or var.get("ID") or "").upper()
        if not name:
            continue
        label = var.find("d:labl", DDI_NS)
        if label is not None and label.text:
            variable_labels[name] = label.text.strip()

        codes: dict[int, str] = {}
        for category in var.findall("d:catgry", DDI_NS):
            value = category.find("d:catValu", DDI_NS)
            text = category.find("d:labl", DDI_NS)
            if value is None or value.text is None or text is None:
                continue
            try:
                codes[int(value.text)] = (text.text or "").strip()
            except ValueError:
                continue
        if codes:
            value_labels[name] = codes

    return variable_labels, value_labels


def _header(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        line = fh.readline()
    return [c.strip().strip('"') for c in line.rstrip("\n").split(",")]


@dataclass
class Measure:
    """What to compute per country-year."""

    variable: str
    kind: str = "share"                       # "share" | "mean"
    categories: tuple[int, ...] = ()          # codes counted in the numerator
    exclude: tuple[int, ...] = ()             # codes dropped from the denominator
    weight: str = "PERWT"
    filters: dict[str, tuple[float, float]] = field(default_factory=dict)

    def describe(self, extract: Extract) -> str:
        labels = extract.labels_for(self.variable)
        if self.kind == "mean":
            text = f"Weighted mean of {self.variable}"
        else:
            names = [labels.get(c, str(c)) for c in self.categories]
            shown = ", ".join(names[:3]) + (" …" if len(names) > 3 else "")
            text = f"Weighted share: {self.variable} in [{shown}]"
        if self.filters:
            bits = ", ".join(f"{lo:g}≤{k}≤{hi:g}" for k, (lo, hi) in self.filters.items())
            text += f", among {bits}"
        return text


def aggregate(
    extract: Extract,
    measure: Measure,
    chunksize: int = CHUNK_ROWS,
    on_progress=None,
) -> pd.DataFrame:
    """Country x year weighted measure, computed by streaming the extract.

    Returns one row per ``(COUNTRY, YEAR)`` with the weighted value, the weighted
    denominator, and the unweighted case count behind it.
    """
    columns = set(extract.columns)
    needed = {"COUNTRY", "YEAR", measure.variable.upper(), measure.weight.upper()}
    needed |= {k.upper() for k in measure.filters}
    missing = sorted(needed - columns)
    if missing:
        raise KeyError(
            f"extract {extract.number} has no column(s) {missing}. "
            f"It contains: {', '.join(sorted(columns))}"
        )

    variable = measure.variable.upper()
    weight = measure.weight.upper()
    usecols = sorted(needed)
    numerator: dict[tuple[int, int], float] = {}
    denominator: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    rows_seen = 0

    reader = pd.read_csv(
        extract.data_path,
        usecols=usecols,
        chunksize=chunksize,
        dtype="float64",
        na_values=[""],
    )
    for chunk in reader:
        rows_seen += len(chunk)

        for column, (low, high) in measure.filters.items():
            series = chunk[column.upper()]
            chunk = chunk[(series >= low) & (series <= high)]
        if measure.exclude:
            chunk = chunk[~chunk[variable].isin(measure.exclude)]
        chunk = chunk.dropna(subset=[variable, weight])
        if chunk.empty:
            continue

        w = chunk[weight].to_numpy()
        if measure.kind == "mean":
            contribution = chunk[variable].to_numpy() * w
        else:
            hit = chunk[variable].isin(measure.categories).to_numpy()
            contribution = np.where(hit, w, 0.0)

        keys = list(zip(chunk["COUNTRY"].astype("int64"), chunk["YEAR"].astype("int64")))
        frame = pd.DataFrame({"key": keys, "num": contribution, "den": w})
        grouped = frame.groupby("key").agg(num=("num", "sum"), den=("den", "sum"), n=("den", "size"))
        for key, row in grouped.iterrows():
            numerator[key] = numerator.get(key, 0.0) + row["num"]
            denominator[key] = denominator.get(key, 0.0) + row["den"]
            counts[key] = counts.get(key, 0) + int(row["n"])

        if on_progress:
            on_progress(rows_seen)

    records = []
    country_labels = extract.labels_for("COUNTRY")
    for (country_code, year), den in denominator.items():
        if den <= 0:
            continue
        records.append(
            {
                "country_code": country_code,
                "country": country_labels.get(country_code, str(country_code)),
                "year": year,
                "value": numerator[(country_code, year)] / den,
                "weighted_n": den,
                "n": counts[(country_code, year)],
            }
        )

    result = pd.DataFrame(records).sort_values(["country", "year"]).reset_index(drop=True)
    log.info("%s: %d country-years from %d rows", measure.variable, len(result), rows_seen)
    return result


def add_iso3(frame: pd.DataFrame, catalog) -> pd.DataFrame:
    """Attach ISO3 by matching the extract's country names to the catalog's."""
    lookup = (
        catalog.samples.dropna(subset=["iso3"])
        .drop_duplicates("country")
        .set_index("country")["iso3"]
        .to_dict()
    )
    # The DDI spells a few countries differently from the sample table.
    aliases = {
        "Dominican Rep": "Dominican Republic",
        "Cote d'Ivoire": "Côte d'Ivoire",
        "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
    }
    out = frame.copy()
    out["iso3"] = out["country"].map(lambda c: lookup.get(aliases.get(c, c)))
    unmatched = sorted(out.loc[out["iso3"].isna(), "country"].unique())
    if unmatched:
        log.warning("no ISO3 for: %s", ", ".join(unmatched))
    return out
