"""Command-line interface: ``ipumsi <command>``.

    ipumsi key set IPUMS_API_KEY            save a key (prompts without echo)
    ipumsi key list                         which keys are set, and from where
    ipumsi refresh                          rebuild the catalog from the website
    ipumsi search migration                 find variables
    ipumsi info GEOMIG1_P                   one variable, with availability
    ipumsi codes EDATTAIN --sample br2010a  case counts per category
    ipumsi coverage GEOMIG1_P INCTOT        country-years carrying all of them
    ipumsi samples GEOMIG1_P INCTOT         the sample IDs themselves
    ipumsi plan GEOMIG1_P INCTOT -o req.json    write an extract request
    ipumsi submit req.json                  send it to IPUMS
    ipumsi status 42                        check on it
    ipumsi download 42                      fetch the data + codebook
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import pandas as pd

from . import config
from .catalog import Catalog, CatalogNotBuilt
from .extract import ExtractDefinition, build_extract


def _print(df: pd.DataFrame, limit: int | None = 50, csv: bool = False) -> None:
    if df.empty:
        print("(no matches)")
        return
    if csv:
        df.to_csv(sys.stdout, index=False)
        return
    shown = df if limit is None else df.head(limit)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(shown.to_string(index=False))
    if limit is not None and len(df) > limit:
        print(f"... {len(df) - limit} more rows (use --limit 0 for all, --csv to pipe)")


def _filters(args) -> dict:
    return {
        "countries": args.country,
        "year_min": args.year_min,
        "year_max": args.year_max,
        "kind": args.kind,
    }


def _catalog() -> Catalog:
    try:
        return Catalog.load()
    except CatalogNotBuilt as exc:
        raise SystemExit(str(exc))


# --------------------------------------------------------------- subcommands


def cmd_refresh(args) -> None:
    from .scrape.build import build_catalog

    frames = build_catalog(
        refresh=args.refresh,
        limit_variables=args.limit_variables,
        delay=args.delay,
        use_cache=not args.no_cache,
    )
    for name, df in frames.items():
        print(f"{name:20s} {len(df):>8,d} rows")
    print(f"\nwritten to {config.DATA_DIR}")


def cmd_key(args) -> None:
    from .credentials import (
        CREDENTIALS_FILE, SPECS, delete_key, find_key, mask, save_key, verify_key,
    )

    if args.key_command == "list":
        rows = []
        for name, spec in SPECS.items():
            key, source = find_key(name)
            rows.append({
                "key": name,
                "status": mask(key) if key else "not set",
                "source": source,
                "used for": spec.what_it_unlocks,
            })
        _print(pd.DataFrame(rows), None, args.csv)
        print(f"\nSaved keys live in {CREDENTIALS_FILE}", file=sys.stderr)
        return

    name = args.name
    if name not in SPECS:
        raise SystemExit(f"unknown key {name!r}; expected one of {', '.join(SPECS)}")

    if args.key_command == "check":
        key, source = find_key(name)
        if not key:
            raise SystemExit(f"{name} is not set")
        ok, message = verify_key(name, key)
        print(f"{name} (from {source}): {message}")
        raise SystemExit(0 if ok else 1)

    if args.key_command == "forget":
        print(f"removed {name}" if delete_key(name) else f"{name} was not saved here")
        return

    # set
    import getpass

    value = args.value or getpass.getpass(f"Paste your {SPECS[name].label} (input hidden): ")
    if not value.strip():
        raise SystemExit("no key given")
    if not args.no_check:
        ok, message = verify_key(name, value)
        print(message, file=sys.stderr)
        if not ok:
            raise SystemExit(1)
    print(f"saved to {save_key(name, value)}")


def cmd_search(args) -> None:
    cat = _catalog()
    hits = cat.search(" ".join(args.query), record_type=args.record_type)
    columns = ["variable", "label", "record_type", "n_countries", "n_samples", "group_label"]
    _print(hits[[c for c in columns if c in hits.columns]], args.limit or None, args.csv)


def cmd_info(args) -> None:
    cat = _catalog()
    row = cat.variable(args.variable)
    print(f"{row['variable']}  [{row['record_type']}]  {row['label']}")
    print(f"group:  {row.get('group_label')}")
    print(f"url:    {row.get('url')}")
    if isinstance(row.get("description"), str):
        print(f"\n{row['description'][:800]}")
    avail = cat.availability([row["variable"]])
    print(f"\navailable in {len(avail)} samples across {avail['country'].nunique()} countries:\n")
    per_country = (
        avail.groupby("country")["year"]
        .agg(lambda s: ", ".join(str(y) for y in sorted(set(s.dropna()))))
        .reset_index()
    )
    _print(per_country, args.limit or None, args.csv)


def cmd_coverage(args) -> None:
    cat = _catalog()
    if args.optional:
        usable = cat.samples_for(args.variables, args.optional, **_filters(args))
        df = (
            usable.groupby(["country", "iso3"], dropna=False, as_index=False)
            .agg(
                n_samples=("sample_id", "size"),
                years=("year", lambda s: ", ".join(str(y) for y in sorted(set(s.dropna())))),
                avg_extras=("n_optional_present", "mean"),
            )
            .sort_values(["n_samples", "country"], ascending=[False, True])
            .reset_index(drop=True)
        )
        print(f"# must have:     {', '.join(cat.resolve_variables(args.variables))}")
        print(f"# nice to have:  {', '.join(cat.resolve_variables(args.optional))}\n")
    else:
        df = cat.coverage(args.variables, how=args.require)
        print(
            f"# samples carrying {args.require} of: "
            f"{', '.join(cat.resolve_variables(args.variables))}\n"
        )
    _print(df, args.limit or None, args.csv)


def cmd_samples(args) -> None:
    cat = _catalog()
    if args.optional:
        df = cat.samples_for(args.variables, args.optional, **_filters(args))
    else:
        df = cat.samples_with(args.variables, how=args.require, **_filters(args))
    if args.ids_only:
        print(" ".join(df["sample_id"]))
        return
    columns = ["sample_id", "country", "iso3", "year", "kind", "subsample",
               "n_variables_present", "n_optional_present", "optional_missing"]
    _print(df[[c for c in columns if c in df.columns]], args.limit or None, args.csv)


def cmd_codes(args) -> None:
    from .http import Fetcher
    from .scrape.frequencies import fetch_frequencies

    cat = _catalog()
    row = cat.variable(args.variable)
    df = fetch_frequencies(Fetcher(), row["variable"], refresh=args.refresh)
    if df.empty:
        print(f"IPUMS publishes no case counts for {row['variable']}")
        return

    if args.sample:
        wanted = {s.strip().lower() for s in args.sample}
        unknown = wanted - set(df["sample_id"])
        if unknown:
            print(f"# not available for: {', '.join(sorted(unknown))}", file=sys.stderr)
        df = df[df["sample_id"].isin(wanted)]
    if args.nonzero:
        df = df[df["count"] > 0]

    print(f"# {row['variable']}: {row['label']}")
    print(f"# {df['sample_id'].nunique()} sample(s), {df['code'].nunique()} categories\n")
    df = df.sort_values(["sample_id", "count"], ascending=[True, False])
    _print(df[["sample_id", "code", "label", "count", "share"]], args.limit or None, args.csv)


def cmd_matrix(args) -> None:
    cat = _catalog()
    _print(cat.matrix(args.variables).reset_index(), args.limit or None, args.csv)


def cmd_vars_in(args) -> None:
    cat = _catalog()
    df = cat.variables_in(args.samples)
    _print(df[["variable", "label", "record_type", "group_label"]], args.limit or None, args.csv)


def cmd_plan(args) -> None:
    cat = _catalog()
    definition = build_extract(
        cat,
        variables=args.variables,
        optional=args.optional,
        countries=args.country,
        year_min=args.year_min,
        year_max=args.year_max,
        kind=args.kind,
        require=args.require,
        description=args.description,
        data_format=args.format,
        hierarchical=args.hierarchical,
    )
    problems = definition.validate(cat, optional=args.optional)
    payload = definition.to_json()
    print(
        f"# {len(payload['samples'])} samples x {len(payload['variables'])} variables",
        file=sys.stderr,
    )
    for problem in problems:
        print(f"# warning: {problem}", file=sys.stderr)

    if args.curl:
        print(definition.to_curl())
    elif args.output:
        path = definition.save(args.output)
        print(f"wrote {path}", file=sys.stderr)
    else:
        print(json.dumps(payload, indent=2))


def cmd_submit(args) -> None:
    from .api import IpumsClient

    definition = ExtractDefinition.from_json(args.request)
    if not args.no_validate:
        for problem in definition.validate(_catalog()):
            print(f"warning: {problem}", file=sys.stderr)

    client = IpumsClient()
    result = client.submit(definition)
    number = result.get("number")
    print(f"extract {number}: {result.get('status')}")
    if args.wait:
        info = client.wait(number, poll_seconds=args.poll)
        print(f"extract {number}: {info.get('status')}")
        for path in client.download(number, which=args.which):
            print(path)


def cmd_status(args) -> None:
    from .api import IpumsClient

    client = IpumsClient()
    if args.number is None:
        rows = [
            {
                "number": e.get("number"),
                "status": e.get("status"),
                "description": (e.get("extractDefinition") or {}).get("description"),
            }
            for e in client.list_extracts(limit=args.limit or 25)
        ]
        _print(pd.DataFrame(rows), None, args.csv)
        return
    info = client.status(args.number)
    print(json.dumps(info, indent=2) if args.json else f"extract {args.number}: {info.get('status')}")


def cmd_download(args) -> None:
    from .api import IpumsClient

    client = IpumsClient()
    if args.wait:
        client.wait(args.number, poll_seconds=args.poll)
    for path in client.download(args.number, dest=args.dest, which=args.which, overwrite=args.overwrite):
        print(path)


# ------------------------------------------------------------------- parsing


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--optional",
        nargs="+",
        default=[],
        metavar="VAR",
        help="nice-to-have variables: included where they exist, never rule a sample out",
    )
    parser.add_argument("--country", action="append", help="country name or ISO code (repeatable)")
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    parser.add_argument("--kind", choices=["census", "LFS"])
    parser.add_argument(
        "--require",
        choices=["all", "any"],
        default="all",
        help="samples must carry all (default) or any of the variables",
    )


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=50, help="rows to print; 0 for all")
    parser.add_argument("--csv", action="store_true", help="emit CSV on stdout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipumsi", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("refresh", help="rebuild the catalog by scraping the IPUMS website")
    p.add_argument("--refresh", action="store_true", help="bypass the on-disk page cache")
    p.add_argument("--no-cache", action="store_true", help="do not write a page cache")
    p.add_argument("--delay", type=float, default=None, help="seconds between requests")
    p.add_argument("--limit-variables", type=int, default=None, help="for smoke tests")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("key", help="manage the IPUMS and Anthropic API keys")
    sub_key = p.add_subparsers(dest="key_command", required=True)
    kp = sub_key.add_parser("list", help="show which keys are set and where they came from")
    kp.add_argument("--csv", action="store_true")
    kp.set_defaults(func=cmd_key, csv=False)
    kp = sub_key.add_parser("set", help="save a key for this user")
    kp.add_argument("name", help="IPUMS_API_KEY or ANTHROPIC_API_KEY")
    kp.add_argument("value", nargs="?", help="omit to be prompted without echo")
    kp.add_argument("--no-check", action="store_true", help="skip the live API check")
    kp.set_defaults(func=cmd_key, csv=False)
    kp = sub_key.add_parser("check", help="verify a key against the live API")
    kp.add_argument("name")
    kp.set_defaults(func=cmd_key, csv=False)
    kp = sub_key.add_parser("forget", help="delete a saved key")
    kp.add_argument("name")
    kp.set_defaults(func=cmd_key, csv=False)

    p = sub.add_parser("search", help="search variables by mnemonic, label or description")
    p.add_argument("query", nargs="+")
    p.add_argument("--record-type", choices=["P", "H"])
    _add_output(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("info", help="show one variable and where it is available")
    p.add_argument("variable")
    _add_output(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("coverage", help="country-level coverage for a variable set")
    p.add_argument("variables", nargs="+")
    _add_filters(p)
    _add_output(p)
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("samples", help="samples carrying a variable set")
    p.add_argument("variables", nargs="+")
    p.add_argument("--ids-only", action="store_true", help="print just the sample IDs")
    _add_filters(p)
    _add_output(p)
    p.set_defaults(func=cmd_samples)

    p = sub.add_parser("codes", help="case counts per category for one variable")
    p.add_argument("variable")
    p.add_argument("--sample", nargs="+", help="restrict to these sample IDs")
    p.add_argument("--nonzero", action="store_true", help="hide categories with no cases")
    p.add_argument("--refresh", action="store_true", help="bypass the page cache")
    _add_output(p)
    p.set_defaults(func=cmd_codes)

    p = sub.add_parser("matrix", help="sample x variable availability matrix")
    p.add_argument("variables", nargs="+")
    _add_output(p)
    p.set_defaults(func=cmd_matrix)

    p = sub.add_parser("vars-in", help="variables available in every given sample")
    p.add_argument("samples", nargs="+")
    _add_output(p)
    p.set_defaults(func=cmd_vars_in)

    p = sub.add_parser("plan", help="build an extract request from a variable set")
    p.add_argument("variables", nargs="+")
    p.add_argument("-o", "--output", help="write the request JSON here")
    p.add_argument("--curl", action="store_true", help="print a curl command instead")
    p.add_argument("--description")
    p.add_argument("--format", default="csv",
                   choices=["csv", "fixed_width", "stata", "spss", "sas9"])
    p.add_argument("--hierarchical", action="store_true")
    _add_filters(p)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("submit", help="submit a request JSON to the IPUMS API")
    p.add_argument("request")
    p.add_argument("--wait", action="store_true", help="poll until done, then download")
    p.add_argument("--poll", type=float, default=60.0, help="seconds between polls")
    p.add_argument("--which", nargs="+", default=["data", "ddiCodebook"])
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("status", help="check an extract, or list recent ones")
    p.add_argument("number", nargs="?", type=int)
    p.add_argument("--json", action="store_true")
    _add_output(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("download", help="download a completed extract")
    p.add_argument("number", type=int)
    p.add_argument("--dest")
    p.add_argument("--which", nargs="+", default=["data", "ddiCodebook"])
    p.add_argument("--wait", action="store_true")
    p.add_argument("--poll", type=float, default=60.0)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_download)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if getattr(args, "limit", None) == 0:
        args.limit = None
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
