"""Turn a research pitch into a variable selection, using Claude.

The catalog is the hard part of this problem and it is already solved: 1,709
variables with labels, groups and real availability. What Claude adds is the
mapping from "I want to relate GDP per capita to the migration rate of
low-income individuals" to the handful of mnemonics that actually encode it.

So the model gets the whole catalog as a cached system prompt and is constrained
to a JSON schema; every mnemonic it returns is then checked against the catalog
before it reaches the UI. A hallucinated variable name is dropped and reported,
never silently selected.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_INTRO = """\
You help economists plan IPUMS International data extracts.

IPUMS International harmonises census and labour-force microdata across ~100
countries. The user describes a research question; you choose the harmonised
variables that would answer it.

The complete variable catalog follows, one per line, as:

    MNEMONIC <tab> RECORD_TYPE <tab> GROUP <tab> LABEL

RECORD_TYPE is P (person) or H (household).

Rules:
- Only ever return mnemonics that appear verbatim in the catalog below. Never
  invent one, and never return a variable from IPUMS USA or another collection.
- Split your picks into two tiers. "Must have" variables define the analysis:
  a country-year without all of them is unusable, so every extra must-have
  shrinks the sample. "Nice to have" variables add controls or robustness where
  they happen to exist, and never disqualify a sample.
- Be disciplined about the must-have tier. It is the single biggest determinant
  of how much data the user ends up with — prefer moving a variable to
  nice-to-have over cutting the panel in half for it.
- Always include the technical variables an analysis needs to be weighted and
  identified (person or household weights, geography, year) as must-haves when
  the question calls for them.
- Where several variables encode the same concept with different coverage (for
  example several income measures, or migration measured at 1, 5 or 10 year
  horizons), say so in your reasoning and pick the one that best matches the
  question rather than all of them.
- Set country and year filters only when the question actually implies them.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "must_have": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variable": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["variable", "reason"],
                "additionalProperties": False,
            },
        },
        "nice_to_have": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variable": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["variable", "reason"],
                "additionalProperties": False,
            },
        },
        "countries": {
            "type": "array",
            "items": {"type": "string"},
        },
        "year_min": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "year_max": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "strategy": {"type": "string"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "must_have", "nice_to_have", "countries", "year_min", "year_max",
        "strategy", "caveats",
    ],
    "additionalProperties": False,
}


class MissingAnthropicKey(RuntimeError):
    pass


class AssistantError(RuntimeError):
    pass


@dataclass
class Pick:
    variable: str
    reason: str
    label: str = ""


@dataclass
class Suggestion:
    must_have: list[Pick] = field(default_factory=list)
    nice_to_have: list[Pick] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    year_min: int | None = None
    year_max: int | None = None
    strategy: str = ""
    caveats: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def anthropic_key(explicit: str | None = None) -> str:
    """Resolve the Anthropic API key. Same search order as the IPUMS key."""
    if explicit:
        return explicit.strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()

    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value and not value.startswith("your_"):
                    return value

    keyfile = Path.home() / ".anthropic_api_key"
    if keyfile.exists() and keyfile.read_text(encoding="utf-8").strip():
        return keyfile.read_text(encoding="utf-8").strip()

    raise MissingAnthropicKey(
        "No Anthropic API key found. Set ANTHROPIC_API_KEY, add it to .env, or "
        "write it to ~/.anthropic_api_key. Keys: https://console.anthropic.com/"
    )


def catalog_prompt(catalog) -> str:
    """Serialise the catalog deterministically so the prompt cache actually hits."""
    variables = catalog.variables.sort_values("variable")
    lines = [
        f"{row.variable}\t{row.record_type}\t{row.group_label}\t{row.label}"
        for row in variables.itertuples()
    ]
    countries = ", ".join(sorted(catalog.samples["country"].dropna().unique()))
    years = catalog.samples["year"].dropna()
    return (
        f"{SYSTEM_INTRO}\n"
        f"Samples span {int(years.min())}-{int(years.max())} across these countries "
        f"(use these exact names in `countries`):\n{countries}\n\n"
        f"=== VARIABLE CATALOG ({len(lines)} variables) ===\n" + "\n".join(lines)
    )


def _client(key: str | None = None):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise AssistantError(
            "The `anthropic` package is not installed. Install it with "
            '`pip install -e ".[assistant]"`.'
        ) from exc
    return anthropic.Anthropic(api_key=anthropic_key(key))


def suggest_variables(
    catalog,
    pitch: str,
    api_key: str | None = None,
    model: str = MODEL,
) -> Suggestion:
    """Ask Claude which variables answer ``pitch``, validated against the catalog."""
    if not pitch.strip():
        raise ValueError("describe the project first")

    client = _client(api_key)
    system = [
        {
            "type": "text",
            "text": catalog_prompt(catalog),
            # The catalog is ~40k tokens and identical on every call; caching it
            # makes the second and later questions roughly a tenth of the price.
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages = [{"role": "user", "content": pitch.strip()}]
    request = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }

    # Claude Opus 5 can decline a request outright; server-side fallbacks re-run
    # it on another model in the same call rather than handing back a refusal.
    try:
        response = client.beta.messages.create(
            betas=[FALLBACK_BETA], fallbacks="default", **request
        )
    except Exception as exc:  # noqa: BLE001 - beta may be unavailable on this key
        log.info("server-side fallbacks unavailable (%s); retrying without", exc)
        response = client.messages.create(**request)

    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise AssistantError(
            f"Claude declined this request{f' ({category})' if category else ''}. "
            "Try rephrasing the project description."
        )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise AssistantError(f"No text in the response (stop_reason={response.stop_reason!r})")

    return _build(json.loads(text), catalog, response)


def _build(payload: dict, catalog, response) -> Suggestion:
    known = set(catalog.variables["variable"])
    labels = dict(zip(catalog.variables["variable"], catalog.variables["label"].fillna("")))
    dropped: list[str] = []
    seen: set[str] = set()

    def picks(items) -> list[Pick]:
        out = []
        for item in items or []:
            name = str(item.get("variable", "")).strip().upper()
            if name not in known:
                dropped.append(name)
                continue
            if name in seen:  # must-have wins over nice-to-have
                continue
            seen.add(name)
            out.append(Pick(name, str(item.get("reason", "")).strip(), labels.get(name, "")))
        return out

    must = picks(payload.get("must_have"))
    nice = picks(payload.get("nice_to_have"))

    known_countries = set(catalog.samples["country"].dropna())
    countries = [c for c in (payload.get("countries") or []) if c in known_countries]

    usage = getattr(response, "usage", None)
    return Suggestion(
        must_have=must,
        nice_to_have=nice,
        countries=countries,
        year_min=payload.get("year_min"),
        year_max=payload.get("year_max"),
        strategy=str(payload.get("strategy", "")).strip(),
        caveats=[str(c).strip() for c in (payload.get("caveats") or []) if str(c).strip()],
        dropped=dropped,
        usage={
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        } if usage else {},
    )
