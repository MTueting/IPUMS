# ipumsi — make IPUMS International queryable

IPUMS International harmonises ~1,700 variables across ~650 census and labour-force
samples from 100+ countries. Finding out *which of those variables exist for which
country-years* normally means clicking through the extract-builder web interface,
because **IPUMS publishes no metadata API for its microdata collections** — the API
supports extracts only.

This repo closes that gap in two steps:

1. **Catalog** — scrape the public browse pages into three tidy tables (samples,
   variables, and the variable × sample availability edge list), committed to
   `data/` so they work offline.
2. **Extract** — build, validate and submit IPUMS extract requests *from* that
   catalog, so a request is checked against real availability before it is sent.

The motivating use case is internal migration: `GEOMIG1_P` and friends give
subnational origin–destination flows over consistent boundaries, which pair
naturally with country-level covariates (World Bank WDI etc.) once you know which
country-years you actually have.

## Install

```bash
pip install -e .            # core
pip install -e ".[app]"     # + Streamlit explorer
pip install -e ".[dev]"     # + pytest
```

## Quick start

The catalog in `data/` is already built, so this works immediately:

```bash
# What migration variables exist?
ipumsi search migration --record-type P

# One variable, and every country-year it covers
ipumsi info GEOMIG1_P

# Where do I have BOTH internal-migration origin and income?
ipumsi coverage GEOMIG1_P INCTOT

# The sample IDs themselves, post-1990, censuses only
ipumsi samples GEOMIG1_P INCTOT --year-min 1990 --kind census --ids-only

# Turn that into an extract request, then send it
ipumsi plan GEOMIG1_P INCTOT EDATTAIN AGE SEX --year-min 1990 -o request.json
ipumsi submit request.json --wait
```

From Python:

```python
from ipumsi import Catalog, build_extract

cat = Catalog.load()
cat.coverage(["GEOMIG1_P", "INCTOT"])            # countries where both exist
cat.samples_with(["GEOMIG1_P", "INCTOT"])        # the samples themselves
cat.variables_in(["br2010a", "mx2010a"])         # what those two samples share

req = build_extract(cat, ["GEOMIG1_P", "INCTOT", "AGE", "SEX"], year_min=1990)
req.validate(cat)                                # [] means every combination exists
req.save("request.json")
```

And the explorer:

```bash
streamlit run streamlit_app.py
```

On Windows, double-click **`Start app.bat`** instead. Double-clicking
`streamlit_app.py` will not work: Streamlit apps are web servers and have to be
started through the `streamlit run` launcher, not by executing the script.

Three pages: **Browse** (search variables, see a country × year availability
heatmap), **Coverage** (pick a variable set, see which country-years carry all of
it and which variable is the binding constraint), **Build extract** (assemble,
validate, download the JSON or submit it).

A worked end-to-end example — internal migration by income, including what each
income measure costs in coverage — is in `examples/internal_migration.py`.

## The one thing worth knowing

`samples_with(..., how="all")` is the query that matters. An analysis is only
possible where *every* variable it needs is present, and IPUMS does not error on
an impossible request — it returns the missing columns entirely blank. So
`ExtractDefinition.validate()` checks the request against the catalog first and
tells you exactly which variable × sample pairs would come back empty.

## Data files

| File | Rows | What it is |
|---|---|---|
| `data/samples.csv` | ~655 | sample ID → country, year, quarter, kind, ISO codes |
| `data/variables.csv` | ~1,709 | mnemonic → label, record type, group, description, counts |
| `data/variable_samples.parquet` | ~350k | the edge list: which variable exists in which sample |
| `data/availability.parquet` | ~350k | the raw `(variable, country, token)` scrape, pre-resolution |
| `data/countries.csv` | ~101 | country → ISO2/ISO3 (the join key for World Bank data) |
| `data/catalog_meta.json` | — | scrape timestamp and row counts |

`country_prefix` in `samples.csv` is ISO 3166-1 alpha-2 with one exception (`uk`,
not `gb`); `iso3` is already normalised for World Bank joins.

## Refreshing the catalog

```bash
ipumsi refresh              # ~2,400 requests, ~10 min, cached in .cache/
ipumsi refresh --refresh    # ignore the cache and re-fetch everything
```

The scraper makes one request at a time with a ~0.34 s delay and caches every page
to `.cache/`, so a re-run after a failure is nearly free. IPUMS updates its
harmonised samples a few times a year; re-running quarterly is plenty.

## API key

Only needed for `submit` / `status` / `download` — all catalog queries work
offline. Get one at <https://account.ipums.org/api_keys> (requires an approved
IPUMS International account), then either:

```bash
export IPUMS_API_KEY=...            # env var
cp .env.example .env                # or a .env at the repo root
echo "$KEY" > ~/.ipums_api_key      # or a dotfile
```

Extract requests support case selection, attached characteristics, data-quality
flags, monetary-value adjustment and hierarchical output; IPUMS International
rectangular extracts are person-level only (use `--hierarchical` for household
records).

## Layout

```
src/ipumsi/
  catalog.py      query the built catalog (no network, no key)
  extract.py      build + validate extract requests
  api.py          submit / poll / download against api.ipums.org
  cli.py          the `ipumsi` command
  http.py         cached, rate-limited scraping session
  countries.py    sample prefix -> ISO 3166 alpha-2/alpha-3
  scrape/
    samples.py       the sample-ID table
    variables.py     the 29 variable groups, paginated
    availability.py  per-variable country/year lists -> sample IDs
    build.py         orchestration; writes data/
streamlit_app.py + app_pages/    the explorer
tests/                           parser + query tests
```

## Scraping etiquette

The catalog comes from public pages that need no login, fetched serially with a
delay and cached. It exists to answer availability questions that IPUMS has said
it intends to expose via API eventually; when that lands, `scrape/` can be
replaced without touching anything above it. Extract *data* is not redistributed
here — `extracts/` is gitignored — and IPUMS's terms of use govern it.

## Next: external covariates

`data/countries.csv` carries ISO3 codes, so World Bank WDI series join on
`(iso3, year)` against `samples.csv`. That layer is not built yet.
