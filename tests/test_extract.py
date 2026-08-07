from __future__ import annotations

import pandas as pd
import pytest

from ipumsi.catalog import Catalog
from ipumsi.extract import ExtractDefinition, VariableSpec, build_extract


@pytest.fixture
def catalog() -> Catalog:
    samples = pd.DataFrame(
        [
            {"sample_id": "br2000a", "country": "Brazil", "iso2": "BR", "iso3": "BRA",
             "country_prefix": "br", "year": 2000, "year_end": None, "quarter": None,
             "kind": "census", "subsample": None, "sample_suffix": "a",
             "description": "Brazil 2000"},
            {"sample_id": "br2010a", "country": "Brazil", "iso2": "BR", "iso3": "BRA",
             "country_prefix": "br", "year": 2010, "year_end": None, "quarter": None,
             "kind": "census", "subsample": None, "sample_suffix": "a",
             "description": "Brazil 2010"},
            {"sample_id": "mx2010a", "country": "Mexico", "iso2": "MX", "iso3": "MEX",
             "country_prefix": "mx", "year": 2010, "year_end": None, "quarter": None,
             "kind": "census", "subsample": None, "sample_suffix": "a",
             "description": "Mexico 2010"},
        ]
    )
    variables = pd.DataFrame(
        [
            {"variable": "GEOMIG1_P", "label": "Previous residence", "record_type": "P",
             "group": "mig", "group_label": "Migration", "description": "", "url": "",
             "n_countries": 2, "n_samples": 3},
            {"variable": "INCTOT", "label": "Total income", "record_type": "P",
             "group": "inc", "group_label": "Income", "description": "", "url": "",
             "n_countries": 1, "n_samples": 1},
        ]
    )
    pairs = pd.DataFrame(
        [
            {"variable": "GEOMIG1_P", "sample_id": "br2000a", "country": "Brazil", "year": 2000, "quarter": None, "token": "2000"},
            {"variable": "GEOMIG1_P", "sample_id": "br2010a", "country": "Brazil", "year": 2010, "quarter": None, "token": "2010"},
            {"variable": "GEOMIG1_P", "sample_id": "mx2010a", "country": "Mexico", "year": 2010, "quarter": None, "token": "2010"},
            {"variable": "INCTOT", "sample_id": "br2010a", "country": "Brazil", "year": 2010, "quarter": None, "token": "2010"},
        ]
    )
    return Catalog(samples=samples, variables=variables, countries=pd.DataFrame(),
                   variable_samples=pairs, meta={})


def test_samples_with_all_is_the_intersection(catalog):
    both = catalog.samples_with(["GEOMIG1_P", "INCTOT"], how="all")
    assert list(both["sample_id"]) == ["br2010a"]

    either = catalog.samples_with(["GEOMIG1_P", "INCTOT"], how="any")
    assert set(either["sample_id"]) == {"br2000a", "br2010a", "mx2010a"}
    assert either.set_index("sample_id").loc["br2000a", "missing_variables"] == "INCTOT"


def test_samples_with_filters(catalog):
    assert list(
        catalog.samples_with(["GEOMIG1_P"], countries=["BRA"], year_min=2005)["sample_id"]
    ) == ["br2010a"]


def test_coverage_ranks_countries(catalog):
    coverage = catalog.coverage(["GEOMIG1_P"], how="all")
    assert list(coverage["country"]) == ["Brazil", "Mexico"]
    assert coverage.iloc[0]["years"] == "2000, 2010"


def test_variables_in_requires_every_sample(catalog):
    assert list(catalog.variables_in(["br2010a"])["variable"]) == ["GEOMIG1_P", "INCTOT"]
    assert list(catalog.variables_in(["br2000a", "br2010a"])["variable"]) == ["GEOMIG1_P"]


def test_unknown_names_raise(catalog):
    with pytest.raises(KeyError):
        catalog.resolve_variables(["NOPE"])
    with pytest.raises(KeyError):
        catalog.variables_in(["zz9999a"])


def test_extract_payload_shape():
    payload = ExtractDefinition(
        samples=["BR2010A"],
        variables=["geomig1_p", VariableSpec("INCTOT", adjust_monetary_values=True)],
        description="test",
    ).to_json()
    assert payload["collection"] == "ipumsi"
    assert payload["samples"] == {"br2010a": {}}
    assert payload["variables"] == {"GEOMIG1_P": {}, "INCTOT": {"adjustMonetaryValues": True}}
    assert payload["dataStructure"] == {"rectangular": {"on": "P"}}


def test_hierarchical_and_household_rectangular():
    hierarchical = ExtractDefinition(samples=["br2010a"], variables=["AGE"], hierarchical=True)
    assert hierarchical.to_json()["dataStructure"] == {"hierarchical": {}}

    # IPUMS International only rectangularises on person records.
    with pytest.raises(ValueError, match="person records"):
        ExtractDefinition(samples=["br2010a"], variables=["AGE"], rectangular_on="H").to_json()


def test_bad_attached_characteristic_rejected():
    with pytest.raises(ValueError, match="attachedCharacteristics"):
        ExtractDefinition(
            samples=["br2010a"],
            variables=[VariableSpec("BPL", attached_characteristics=["sibling"])],
        ).to_json()


def test_validate_flags_unavailable_combinations(catalog):
    problems = ExtractDefinition(
        samples=["br2000a", "mx2010a", "zz9999a"], variables=["INCTOT", "NOPE"]
    ).validate(catalog)
    assert any("unknown sample" in p for p in problems)
    assert any("unknown variable" in p for p in problems)
    assert any(p.startswith("INCTOT is not available in 2") for p in problems)


def test_validate_passes_on_a_clean_request(catalog):
    definition = build_extract(catalog, ["GEOMIG1_P", "INCTOT"])
    assert definition.samples == ["br2010a"]
    assert definition.validate(catalog) == []


def test_build_extract_raises_when_nothing_matches(catalog):
    with pytest.raises(ValueError, match="no samples"):
        build_extract(catalog, ["GEOMIG1_P", "INCTOT"], year_max=2005)


def test_roundtrip_through_json(tmp_path):
    original = ExtractDefinition(
        samples=["br2010a"],
        variables=[VariableSpec("MARST", case_selections={"general": ["1", "2"]})],
        data_format="stata",
    )
    path = original.save(tmp_path / "req.json")
    restored = ExtractDefinition.from_json(path)
    assert restored.to_json() == original.to_json()
