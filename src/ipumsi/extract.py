"""Build IPUMS International extract-request payloads.

The API contract lives at
https://developer.ipums.org/docs/v2/workflows/create_extracts/microdata/ ;
this wraps it so a request can be assembled from catalog queries and checked
against the catalog *before* it is submitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import COLLECTION

DataFormat = Literal["fixed_width", "csv", "stata", "spss", "sas9"]
RecordType = Literal["P", "H"]

# Features the API supports for IPUMS International specifically.
ATTACHED_CHARACTERISTICS = ("mother", "father", "spouse", "head", "mother2", "father2")


@dataclass
class VariableSpec:
    """Per-variable extract options."""

    name: str
    case_selections: dict[str, list[str]] | None = None
    attached_characteristics: list[str] | None = None
    data_quality_flags: bool = False
    adjust_monetary_values: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.case_selections:
            out["caseSelections"] = {k: [str(v) for v in vs] for k, vs in self.case_selections.items()}
        if self.attached_characteristics:
            bad = set(self.attached_characteristics) - set(ATTACHED_CHARACTERISTICS)
            if bad:
                raise ValueError(
                    f"unsupported attachedCharacteristics {sorted(bad)}; "
                    f"allowed: {list(ATTACHED_CHARACTERISTICS)}"
                )
            out["attachedCharacteristics"] = list(self.attached_characteristics)
        if self.data_quality_flags:
            out["dataQualityFlags"] = True
        if self.adjust_monetary_values:
            out["adjustMonetaryValues"] = True
        return out


@dataclass
class ExtractDefinition:
    """An IPUMS International extract request."""

    samples: list[str]
    variables: list[str | VariableSpec]
    description: str = "ipumsi extract"
    data_format: DataFormat = "csv"
    rectangular_on: RecordType | None = "P"
    hierarchical: bool = False
    case_select_who: Literal["individuals", "households"] = "individuals"
    collection: str = COLLECTION
    extra: dict[str, Any] = field(default_factory=dict)

    def _variable_specs(self) -> list[VariableSpec]:
        return [v if isinstance(v, VariableSpec) else VariableSpec(name=str(v)) for v in self.variables]

    def to_json(self) -> dict[str, Any]:
        if not self.samples:
            raise ValueError("an extract needs at least one sample")
        specs = self._variable_specs()
        if not specs:
            raise ValueError("an extract needs at least one variable")

        if self.hierarchical:
            structure: dict[str, Any] = {"hierarchical": {}}
        else:
            if self.rectangular_on not in ("P", "H"):
                raise ValueError("rectangular_on must be 'P' or 'H'")
            # IPUMS International only supports rectangularising on person records.
            if self.collection == COLLECTION and self.rectangular_on != "P":
                raise ValueError(
                    "IPUMS International extracts can only be rectangularised on "
                    "person records (rectangular_on='P'); use hierarchical=True instead"
                )
            structure = {"rectangular": {"on": self.rectangular_on}}

        payload: dict[str, Any] = {
            "description": self.description,
            "dataStructure": structure,
            "dataFormat": self.data_format,
            "caseSelectWho": self.case_select_who,
            "samples": {s.strip().lower(): {} for s in self.samples},
            "variables": {s.name.strip().upper(): s.to_json() for s in specs},
            "collection": self.collection,
        }
        payload.update(self.extra)
        return payload

    def to_curl(self, api_key_env: str = "IPUMS_API_KEY") -> str:
        """Render the request as a copy-pasteable curl command."""
        body = json.dumps(self.to_json(), indent=2)
        return (
            f"curl --location --request POST "
            f"'https://api.ipums.org/extracts?collection={self.collection}&version=2' \\\n"
            f'  --header "Authorization: ${api_key_env}" \\\n'
            f"  --header 'Content-Type: application/json' \\\n"
            f"  --data-raw '{body}'"
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, path: str | Path) -> "ExtractDefinition":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        structure = payload.get("dataStructure", {})
        variables: list[str | VariableSpec] = []
        for name, opts in payload.get("variables", {}).items():
            if opts and set(opts) - {"preselected"}:
                variables.append(
                    VariableSpec(
                        name=name,
                        case_selections=opts.get("caseSelections"),
                        attached_characteristics=opts.get("attachedCharacteristics"),
                        data_quality_flags=bool(opts.get("dataQualityFlags")),
                        adjust_monetary_values=bool(opts.get("adjustMonetaryValues")),
                    )
                )
            else:
                variables.append(name)
        return cls(
            samples=list(payload.get("samples", {})),
            variables=variables,
            description=payload.get("description", "ipumsi extract"),
            data_format=payload.get("dataFormat", "csv"),
            rectangular_on=structure.get("rectangular", {}).get("on"),
            hierarchical="hierarchical" in structure,
            case_select_who=payload.get("caseSelectWho", "individuals"),
            collection=payload.get("collection", COLLECTION),
        )

    # ------------------------------------------------------------- validation

    def validate(self, catalog) -> list[str]:
        """Check the request against the scraped catalog.

        Returns a list of human-readable problems: unknown samples or variables,
        and variable/sample combinations IPUMS does not harmonise. Requesting an
        unavailable combination is not an API error -- the columns come back all
        missing -- so catching it here is the point of having the catalog.
        """
        problems: list[str] = []

        known_samples = set(catalog.samples["sample_id"])
        unknown_samples = [s for s in self.samples if s.lower() not in known_samples]
        if unknown_samples:
            problems.append(f"unknown sample(s): {', '.join(sorted(unknown_samples))}")

        known_vars = set(catalog.variables["variable"])
        names = [s.name.upper() for s in self._variable_specs()]
        unknown_vars = [v for v in names if v not in known_vars]
        if unknown_vars:
            problems.append(f"unknown variable(s): {', '.join(sorted(unknown_vars))}")

        pairs = catalog.variable_samples
        valid_samples = [s.lower() for s in self.samples if s.lower() in known_samples]
        for var in names:
            if var in unknown_vars:
                continue
            have = set(pairs.loc[pairs["variable"] == var, "sample_id"])
            missing = [s for s in valid_samples if s not in have]
            if missing:
                problems.append(
                    f"{var} is not available in {len(missing)} requested sample(s): "
                    + ", ".join(sorted(missing)[:10])
                    + (" ..." if len(missing) > 10 else "")
                )
        return problems


def build_extract(
    catalog,
    variables: list[str],
    countries: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    kind: str | None = None,
    require: str = "all",
    description: str | None = None,
    data_format: DataFormat = "csv",
    **kwargs,
) -> ExtractDefinition:
    """Build an extract over every sample that satisfies a variable requirement.

    This is the shortcut from a research question to a request: name the
    variables, optionally restrict the country-years, and get back a definition
    covering exactly the samples where the variable set holds.
    """
    hits = catalog.samples_with(
        variables,
        how=require,
        countries=countries,
        year_min=year_min,
        year_max=year_max,
        kind=kind,
    )
    if hits.empty:
        raise ValueError(
            f"no samples carry {require} of {variables} under the given filters"
        )
    return ExtractDefinition(
        samples=hits["sample_id"].tolist(),
        variables=catalog.resolve_variables(variables),
        description=description or f"ipumsi: {', '.join(catalog.resolve_variables(variables))}",
        data_format=data_format,
        **kwargs,
    )
