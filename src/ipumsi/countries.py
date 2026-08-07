"""IPUMS sample-prefix -> ISO 3166 mapping.

IPUMS International sample IDs start with a two-letter country prefix that is
ISO 3166-1 alpha-2 with one exception (``uk`` rather than ``gb``). The alpha-3
codes below are what the World Bank indicator API expects, so this table is the
hinge between the IPUMS catalog and external country-level covariates.
"""

from __future__ import annotations

# prefix -> ISO 3166-1 alpha-3
ISO3: dict[str, str] = {
    "am": "ARM", "ar": "ARG", "at": "AUT", "bd": "BGD", "bf": "BFA",
    "bj": "BEN", "bo": "BOL", "br": "BRA", "bw": "BWA", "by": "BLR",
    "ca": "CAN", "ch": "CHE", "ci": "CIV", "cl": "CHL", "cm": "CMR",
    "cn": "CHN", "co": "COL", "cr": "CRI", "cu": "CUB", "de": "DEU",
    "dk": "DNK", "do": "DOM", "ec": "ECU", "eg": "EGY", "es": "ESP",
    "et": "ETH", "fi": "FIN", "fj": "FJI", "fr": "FRA", "gh": "GHA",
    "gn": "GIN", "gr": "GRC", "gt": "GTM", "hn": "HND", "ht": "HTI",
    "hu": "HUN", "id": "IDN", "ie": "IRL", "il": "ISR", "in": "IND",
    "iq": "IRQ", "ir": "IRN", "is": "ISL", "it": "ITA", "jm": "JAM",
    "jo": "JOR", "ke": "KEN", "kg": "KGZ", "kh": "KHM", "la": "LAO",
    "lc": "LCA", "lr": "LBR", "ls": "LSO", "ma": "MAR", "ml": "MLI",
    "mm": "MMR", "mn": "MNG", "mu": "MUS", "mw": "MWI", "mx": "MEX",
    "my": "MYS", "mz": "MOZ", "ng": "NGA", "ni": "NIC", "nl": "NLD",
    "no": "NOR", "np": "NPL", "pa": "PAN", "pe": "PER", "pg": "PNG",
    "ph": "PHL", "pk": "PAK", "pl": "POL", "pr": "PRI", "ps": "PSE",
    "pt": "PRT", "py": "PRY", "ro": "ROU", "ru": "RUS", "rw": "RWA",
    "sd": "SDN", "se": "SWE", "si": "SVN", "sk": "SVK", "sl": "SLE",
    "sn": "SEN", "sr": "SUR", "ss": "SSD", "sv": "SLV", "tg": "TGO",
    "th": "THA", "tr": "TUR", "tt": "TTO", "tz": "TZA", "ua": "UKR",
    "ug": "UGA", "uk": "GBR", "us": "USA", "uy": "URY", "ve": "VEN",
    "vn": "VNM", "za": "ZAF", "zm": "ZMB", "zw": "ZWE",
}

# prefix -> ISO 3166-1 alpha-2 (identical except for the UK)
ISO2: dict[str, str] = {p: ("GB" if p == "uk" else p.upper()) for p in ISO3}

# The sample-ID table and the variable pages do not always spell a country the
# same way. Everything is normalised to the variable pages' spelling, which is
# the one a user is likely to type. Keys are lower-cased.
COUNTRY_ALIASES: dict[str, str] = {
    "dominican rep": "Dominican Republic",
}


def normalize_country(name: str) -> str:
    if not isinstance(name, str):
        return name
    stripped = name.strip()
    return COUNTRY_ALIASES.get(stripped.lower(), stripped)


def iso3(prefix: str) -> str | None:
    return ISO3.get(prefix.lower())


def iso2(prefix: str) -> str | None:
    return ISO2.get(prefix.lower())
