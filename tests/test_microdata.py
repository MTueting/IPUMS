"""Country-year aggregation from a downloaded extract.

This is the one place in the repo where a silent arithmetic bug would produce
plausible-looking economics, so the maths is checked against hand-computed
numbers rather than against itself. The chunk-boundary test matters most: real
extracts are tens of millions of rows and are aggregated in pieces, so a
per-chunk accumulation error would never announce itself.
"""

from __future__ import annotations

import gzip

import pandas as pd
import pytest

from ipumsi.microdata import Extract, Measure, add_iso3, aggregate, find_extracts, read_ddi

DDI = """<?xml version="1.0" encoding="UTF-8"?>
<codeBook xmlns="ddi:codebook:2_5">
  <dataDscr>
    <var ID="COUNTRY" name="COUNTRY"><labl>Country</labl>
      <catgry><catValu>076</catValu><labl>Brazil</labl></catgry>
      <catgry><catValu>484</catValu><labl>Mexico</labl></catgry>
    </var>
    <var ID="EDATTAIN" name="EDATTAIN"><labl>Educational attainment</labl>
      <catgry><catValu>0</catValu><labl>NIU (not in universe)</labl></catgry>
      <catgry><catValu>1</catValu><labl>Less than primary completed</labl></catgry>
      <catgry><catValu>3</catValu><labl>Secondary completed</labl></catgry>
      <catgry><catValu>9</catValu><labl>Unknown</labl></catgry>
    </var>
  </dataDscr>
</codeBook>
"""

# Brazil 2010: weights 10,10,20,20 on EDATTAIN 3,1,3,1 -> share(3) = 30/60 = 0.5
# plus one NIU and one Unknown row that must land in neither numerator nor
# denominator once excluded.
ROWS = [
    # COUNTRY, YEAR, EDATTAIN, PERWT, AGE
    (76, 2010, 3, 10, 30),
    (76, 2010, 1, 10, 40),
    (76, 2010, 3, 20, 50),
    (76, 2010, 1, 20, 20),
    (76, 2010, 0, 99, 10),   # NIU
    (76, 2010, 9, 99, 60),   # Unknown
    (484, 2010, 3, 5, 33),
    (484, 2010, 1, 15, 44),
]


@pytest.fixture
def extract(tmp_path) -> Extract:
    folder = tmp_path / "ipumsi_00001"
    folder.mkdir()
    ddi = folder / "ipumsi_00001.xml"
    ddi.write_text(DDI, encoding="utf-8")

    data = folder / "ipumsi_00001.csv.gz"
    with gzip.open(data, "wt", encoding="utf-8", newline="") as fh:
        fh.write("COUNTRY,YEAR,EDATTAIN,PERWT,AGE\n")
        for row in ROWS:
            fh.write(",".join(str(v) for v in row) + "\n")

    variable_labels, value_labels = read_ddi(ddi)
    return Extract(1, data, ddi, variable_labels, value_labels)


def test_read_ddi_gives_variable_and_value_labels(extract):
    assert extract.label_of("EDATTAIN") == "Educational attainment"
    assert extract.labels_for("COUNTRY")[76] == "Brazil"
    assert extract.labels_for("EDATTAIN")[3] == "Secondary completed"


def test_weighted_share_is_weighted_not_counted(extract):
    """Two of four Brazilians finished secondary, but they carry 30 of 60 weight."""
    df = aggregate(
        extract,
        Measure("EDATTAIN", "share", categories=(3,), exclude=(0, 9), weight="PERWT"),
    ).set_index("country")

    assert df.loc["Brazil", "value"] == pytest.approx(0.5)
    assert df.loc["Brazil", "weighted_n"] == pytest.approx(60)
    assert df.loc["Brazil", "n"] == 4          # NIU and Unknown excluded
    assert df.loc["Mexico", "value"] == pytest.approx(5 / 20)


def test_excluded_codes_leave_the_denominator(extract):
    """Without excluding NIU/Unknown the denominator grows by their weight."""
    kept = aggregate(
        extract, Measure("EDATTAIN", "share", categories=(3,), weight="PERWT")
    ).set_index("country")
    assert kept.loc["Brazil", "weighted_n"] == pytest.approx(60 + 99 + 99)
    assert kept.loc["Brazil", "value"] == pytest.approx(30 / 258)


def test_weighted_mean(extract):
    df = aggregate(
        extract, Measure("AGE", "mean", weight="PERWT")
    ).set_index("country")
    expected = (30 * 10 + 40 * 10 + 50 * 20 + 20 * 20 + 10 * 99 + 60 * 99) / (10 + 10 + 20 + 20 + 99 + 99)
    assert df.loc["Brazil", "value"] == pytest.approx(expected)


def test_filters_restrict_the_universe(extract):
    df = aggregate(
        extract,
        Measure("EDATTAIN", "share", categories=(3,), exclude=(0, 9),
                weight="PERWT", filters={"AGE": (25.0, 45.0)}),
    ).set_index("country")
    # Only the 30-year-old (EDATTAIN 3, w=10) and 40-year-old (1, w=10) qualify.
    assert df.loc["Brazil", "value"] == pytest.approx(0.5)
    assert df.loc["Brazil", "weighted_n"] == pytest.approx(20)
    assert df.loc["Brazil", "n"] == 2


@pytest.mark.parametrize("chunksize", [1, 2, 3, 5, 1000])
def test_chunking_never_changes_the_answer(extract, chunksize):
    """Aggregation streams in chunks; the result must not depend on where they split."""
    measure = Measure("EDATTAIN", "share", categories=(3,), exclude=(0, 9), weight="PERWT")
    df = aggregate(extract, measure, chunksize=chunksize).set_index("country")
    assert df.loc["Brazil", "value"] == pytest.approx(0.5)
    assert df.loc["Brazil", "n"] == 4
    assert df.loc["Mexico", "value"] == pytest.approx(0.25)


def test_progress_is_monotonic_and_reaches_the_end(extract):
    seen: list[int] = []
    aggregate(
        extract,
        Measure("EDATTAIN", "share", categories=(3,), weight="PERWT"),
        chunksize=2,
        on_progress=seen.append,
    )
    assert seen == sorted(seen)
    assert seen[-1] == len(ROWS)


def test_missing_column_says_what_is_available(extract):
    with pytest.raises(KeyError, match="INCTOT"):
        aggregate(extract, Measure("INCTOT", "mean", weight="PERWT"))


def test_add_iso3_matches_catalog_names():
    from ipumsi.catalog import Catalog

    frame = pd.DataFrame({"country": ["Brazil", "Mexico", "Atlantis"], "year": [2010, 2010, 2010]})
    out = add_iso3(frame, Catalog.load())
    assert out.set_index("country").loc["Brazil", "iso3"] == "BRA"
    assert out.set_index("country").loc["Mexico", "iso3"] == "MEX"
    assert pd.isna(out.set_index("country").loc["Atlantis", "iso3"])


def test_find_extracts_reads_a_folder(extract, tmp_path):
    found = find_extracts(tmp_path)
    assert [e.number for e in found] == [1]
    assert found[0].labels_for("COUNTRY")[484] == "Mexico"
    assert "EDATTAIN" in found[0].columns
