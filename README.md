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

# Is it actually populated? (availability != usable data)
ipumsi codes GEOMIG1_P --sample br2010a --nonzero

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

Five pages:

- **Find variables** — describe your project in plain English and get ranked
  variables back, with a plain-English reason for each match. No account, no
  API, no cost — see "Finding variables" below.
- **Browse & profile** — search variables, see a country × year availability
  heatmap, and profile a variable's **case counts** per category for up to
  three samples.
- **Coverage** — pick a variable set, see which country-years carry all of it and
  which variable is the binding constraint.
- **Build extract** — assemble, validate, download the JSON or submit it.
- **Settings** — catalog stats and a one-click refresh with live progress.

A worked end-to-end example — internal migration by income, including what each
income measure costs in coverage — is in `examples/internal_migration.py`.

## Must-have vs nice-to-have

Most analyses have a core set you cannot do without and a wish list that buys
extra controls where it happens to exist. Only the must-haves filter the sample
set; nice-to-haves are scored per sample so you can see what each country-year
would additionally give you:

```bash
# GEOMIG1_P + GEOLEV1 decide the panel; income and education are a bonus
ipumsi samples GEOMIG1_P GEOLEV1 --optional INCTOT EDATTAIN
ipumsi plan GEOMIG1_P GEOLEV1 --optional INCTOT EDATTAIN -o request.json
```

Moving one variable between tiers is usually the difference between 13 samples
and 130 — the Coverage page shows the trade-off directly.

## Case counts

Availability says a variable *exists* in a sample. It does not say the variable
is *populated*: `GEOMIG1_P` is available in Brazil 2010 and 85% of its cases sit
in "Unknown". The Browse page fetches the per-category counts IPUMS publishes
(from the same JSON endpoint its own "Case-count view" uses) and flags that
before the variable ends up in an extract.

These are pulled on demand rather than committed — one variable can be 100k+
category × sample cells, which would dwarf the rest of the catalog.

## Finding variables

Type a research question, get variables. Plain string matching — instant, free,
offline, deterministic, identical for everyone:

```bash
ipumsi find I am interested in the role of education on fertility
```
```
# topics recognised: education, fertility

EDATTAIN  Educational attainment       key education variable; in the Education group
CHBORN    Children ever born           key fertility variable; in the Fertility group
SCHOOL    School attendance            key education variable; in the Education group
CHSURV    Children surviving           key fertility variable; in the Fertility group
```

Three things make this work better than a `LIKE '%...%'` query:

1. **A concept table** maps everyday words onto IPUMS's own vocabulary. This is
   why "education" finds `YRSCHOOL`, which shares no letters with the word you
   typed.
2. **Single-country recodes are demoted.** 1,439 of the 1,709 variables exist in
   exactly one country — `EDUCUS` is US-only across 9 samples, while `EDATTAIN`
   spans 98 countries. Unranked, the country-specific ones swamp everything.
   `--all-countries` turns the demotion off.
3. **Topics are interleaved.** "education on fertility" is two topics; a flat
   relevance sort returns ten education variables and no fertility.

Every result says *why* it matched, and the search is whole-token, so `income`
does not match `SEWAGE` and `PRINCE` the way a substring search does.

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

Case counts are deliberately *not* in this table — see "Case counts" above.

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

## API keys

**Nothing in the catalog needs a key.** Finding variables, availability,
coverage, case counts and building a request all work offline. One key exists,
and only for the last step:

| Key | Used for | Get one |
|---|---|---|
| `IPUMS_API_KEY` | Submitting extracts and downloading data | <https://account.ipums.org/api_keys> (needs an approved IPUMS International account) |

### Easiest: let the app ask

Just use the app. The first time you press **Submit to IPUMS**, a dialog opens
with a box to paste the key into. It checks the key against the live API before
saving, and lets you choose where to keep it. You can also set it up front on
the **Settings** page.

### From the terminal

```bash
ipumsi key set IPUMS_API_KEY      # prompts without echoing, verifies, saves
ipumsi key list                   # which keys are set, and where they came from
ipumsi key check IPUMS_API_KEY    # verify against the live API
ipumsi key forget IPUMS_API_KEY   # delete a saved key
```

### Where keys are looked for

First match wins:

1. a key typed into the app this session (never written to disk)
2. `.streamlit/secrets.toml` — for deployed apps
3. the `IPUMS_API_KEY` environment variable
4. a `.env` file in the project folder (`cp .env.example .env`)
5. `~/.ipumsi/credentials.json` — what the app and `ipumsi key set` write

Saved keys go to your **home folder, never the project folder**, so they cannot
be committed by accident. `.env` is gitignored for the same reason.

### If you are sharing this app with other people

Two things to know:

- A key saved through the app is saved on **the machine running the app**. If
  you serve it to colleagues, whoever opens it can use that key. The dialog
  detects a non-localhost connection, defaults to session-only, and warns you.
- For a real deployment, use `.streamlit/secrets.toml` (gitignored) or
  environment variables, and have each user bring their own key via the
  session-only option.

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
  credentials.py  where API keys live, and checking they work
  search.py       plain-English question -> ranked variables (no model)
  scrape/
    samples.py       the sample-ID table
    variables.py     the 29 variable groups, paginated
    availability.py  per-variable country/year lists -> sample IDs
    frequencies.py   per-category case counts (on demand)
    build.py         orchestration; writes data/
streamlit_app.py + app_pages/    the explorer
app_keys.py                      in-app key entry dialog
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
