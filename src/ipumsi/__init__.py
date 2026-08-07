"""ipumsi -- make the IPUMS International catalog queryable, and drive the extract API from it.

IPUMS publishes no metadata API for its microdata collections, so this package
scrapes the public browse pages into a small tidy catalog (samples, variables,
and which variables exist in which samples) and then uses that catalog to build
and submit extract requests.

    from ipumsi import Catalog, build_extract
    cat = Catalog.load()
    cat.coverage(["GEOMIG1_P", "INCTOT"])
    req = build_extract(cat, ["GEOMIG1_P", "INCTOT"], year_min=1990)
"""

from .catalog import Catalog, load
from .extract import ExtractDefinition, VariableSpec, build_extract

__version__ = "0.1.0"
__all__ = ["Catalog", "load", "ExtractDefinition", "VariableSpec", "build_extract"]
