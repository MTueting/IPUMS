"""Worked example: internal migration by income, and what it costs in coverage.

Run with ``python examples/internal_migration.py``. Everything here reads the
committed catalog -- no API key, no network.

The point is the trade-off this catalog makes visible. IPUMS harmonises
subnational previous-residence (``GEOMIG1_P``) for 47 countries, but harmonised
total income (``INCTOT``) for far fewer, and the *intersection* is what an
analysis can actually use. Seeing that before submitting an extract is the whole
reason for the catalog.
"""

from __future__ import annotations

import sys

from ipumsi import Catalog, build_extract

cat = Catalog.load()

# Origin-destination internal migration at the 1st subnational level.
# GEOLEV1 is current residence; GEOMIG1_P is residence before the last move.
MIGRATION = ["GEOLEV1", "GEOMIG1_P"]
DEMOGRAPHICS = ["AGE", "SEX", "EDATTAIN"]
WEIGHTS = ["PERWT"]

print("=" * 78)
print("1. How far does each candidate income measure reach?")
print("=" * 78)
for income in ["INCTOT", "INCWAGE", "INCBUS", "INCEARN"]:
    if income not in set(cat.variables["variable"]):
        print(f"  {income:8s} not harmonised in IPUMS International")
        continue
    alone = cat.samples_with([income])
    joint = cat.samples_with(MIGRATION + [income])
    print(
        f"  {income:8s} {len(alone):>4} samples on its own, "
        f"{len(joint):>3} once joined to subnational migration "
        f"({joint['country'].nunique()} countries)"
    )

print()
print("=" * 78)
print("2. Coverage of the full analysis set")
print("=" * 78)
analysis = MIGRATION + ["INCTOT"] + DEMOGRAPHICS + WEIGHTS
coverage = cat.coverage(analysis)
print(f"variables: {', '.join(analysis)}\n")
print(coverage.to_string(index=False))

print()
print("=" * 78)
print("3. Which variable is the binding constraint?")
print("=" * 78)
for variable in analysis:
    n = len(cat.samples_with([variable]))
    print(f"  {variable:12s} {n:>4} samples")
print("\nDrop the smallest number and the panel grows; that is the whole trade-off.")

print()
print("=" * 78)
print("4. The extract request this implies")
print("=" * 78)
request = build_extract(
    cat,
    analysis,
    description="Internal migration flows by income, 1st subnational level",
    data_format="csv",
)
problems = request.validate(cat)
print(f"samples:   {len(request.samples)}  ({', '.join(request.samples)})")
print(f"variables: {len(request.variables)}")
print(f"validation: {'clean' if not problems else problems}")
print("\nWrite it out and submit with:")
print("  python examples/internal_migration.py --save   # then")
print("  ipumsi submit migration_request.json --wait")

if "--save" in sys.argv:
    path = request.save("migration_request.json")
    print(f"\nwrote {path}")

print()
print("=" * 78)
print("5. Joining to World Bank indicators later")
print("=" * 78)
hits = cat.samples_with(analysis)
print("Every usable sample already carries an ISO3 code and a year:\n")
print(hits[["sample_id", "country", "iso3", "year"]].to_string(index=False))
print("\n-> join WDI series on (iso3, year).")
