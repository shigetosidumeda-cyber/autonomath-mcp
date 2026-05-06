"""Universal response envelope primitives — `_next_calls`, `_license_summary`.

Three primitives that lift ARPU across every search endpoint:

  1. `_next_calls`: per-row deterministic follow-up suggestions. An LLM
     agent that hits search and gets back N rows can chain straight into
     2-3 follow-ups (get-by-id, trace, find_cases) without inventing tool
     names from scratch. Higher chain depth → more billed requests.

  2. `_license_summary`: tally of `am_source.license` values across the
     returned rows. Lets a redistribution-conscious caller (e.g. an
     enterprise downstream packaging our data into a SaaS) confirm the
     entire response is on a green-list license before shipping.

  3. `?license=` query filter: comma-separated whitelist
     (`pdl_v1.0,cc_by_4.0,public_domain`) that drops rows whose source
     domain maps to a non-listed license. Pairs with the summary above.

The license map is sourced from `autonomath.db.am_source` (1,447 distinct
domains as of 2026-04-29). This module loads the (domain → license)
dict at first use and caches it process-locally — `am_source` mutates at
ingest cadence (daily at most) so we recompute on a 5-minute TTL to
absorb cron-loaded new sources without a process restart.

Honesty: when a source_url's domain is absent from the lookup, the row
is tagged `unknown` rather than dropped or guessed. `?license=unknown`
explicitly opts into the gray zone; the default whitelist excludes it.

Failure mode: `am_source` access can fail (autonomath.db absent in
unit-test fixtures, lock contention). We degrade to an empty mapping —
all rows are then `unknown` and a `?license=` filter behaves like a
pass-through. Never raises.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from jpintel_mcp.config import settings

# Process-local cache for the (domain → license) mapping. 5-minute TTL.
_LICENSE_MAP_CACHE: dict[str, str] | None = None
_LICENSE_MAP_EXPIRY: float = 0.0
_LICENSE_MAP_TTL = 300.0  # seconds

# Canonical license enum (matches am_source CHECK constraint, migration 049).
_VALID_LICENSES: frozenset[str] = frozenset(
    {
        "pdl_v1.0",
        "cc_by_4.0",
        "gov_standard_v2.0",
        "public_domain",
        "proprietary",
        "unknown",
    }
)


def _load_license_map() -> dict[str, str]:
    """Return (domain → license) dict, loaded from autonomath.db.am_source.

    Cached for `_LICENSE_MAP_TTL` seconds. Soft-fails: returns empty dict
    on any sqlite error (test fixtures lack autonomath.db, ingest has a
    rare race during table rebuild, etc.).
    """
    global _LICENSE_MAP_CACHE, _LICENSE_MAP_EXPIRY
    now = time.monotonic()
    if _LICENSE_MAP_CACHE is not None and _LICENSE_MAP_EXPIRY > now:
        return _LICENSE_MAP_CACHE
    mapping: dict[str, str] = {}
    try:
        # Connect read-only — license lookup never writes. Avoids a
        # writer-lock conflict with concurrent ingest.
        am_path = settings.autonomath_db_path
        conn = sqlite3.connect(f"file:{am_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT domain, license FROM am_source "
                "WHERE domain IS NOT NULL AND domain != '' "
                "  AND license IS NOT NULL"
            ).fetchall()
            for domain, license_val in rows:
                if not domain or not license_val:
                    continue
                # First-write-wins: 1447/1448 domains have unique license,
                # 1 has 2 (the empty-string domain we already filtered).
                # Subsequent rows for the same domain are ignored.
                if domain not in mapping:
                    mapping[domain] = license_val
        finally:
            conn.close()
    except sqlite3.Error:
        # Test fixture / autonomath.db absent / WAL recovery lag. Honest
        # empty mapping → every row is `unknown`. Better than raising.
        return {}
    _LICENSE_MAP_CACHE = mapping
    _LICENSE_MAP_EXPIRY = now + _LICENSE_MAP_TTL
    return mapping


def _domain_of(url: str | None) -> str | None:
    """Return the netloc (sans port) of a URL, or None on parse failure.

    `urlparse('https://www.nta.go.jp/foo')` → 'www.nta.go.jp'.
    Empty / non-string input → None.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host or None


def license_for_url(url: str | None) -> str:
    """Return the canonical license string for a row's `source_url`.

    Returns `'unknown'` when the URL is absent, malformed, or its domain
    isn't in the am_source mapping.
    """
    domain = _domain_of(url)
    if domain is None:
        return "unknown"
    mapping = _load_license_map()
    return mapping.get(domain, "unknown")


def parse_license_filter(license_param: str | None) -> set[str] | None:
    """Parse a comma-separated `?license=` query value into a validated set.

    Returns None when `license_param` is None / empty (= no filter).
    Unknown enum values are silently dropped — better to under-filter than
    to 422 a string we can't understand. An all-invalid input collapses
    to None as well.
    """
    if not license_param:
        return None
    raw = [v.strip() for v in license_param.split(",") if v.strip()]
    if not raw:
        return None
    cleaned = {v for v in raw if v in _VALID_LICENSES}
    return cleaned or None


def filter_rows_by_license(
    rows: list[Any], license_set: set[str] | None, *, url_attr: str = "source_url"
) -> list[Any]:
    """Filter `rows` to those whose source_url license is in `license_set`.

    Each row may be a dict, a sqlite3.Row, or a Pydantic model — we look
    up `source_url` via attribute / item access. Rows without an
    accessible source_url are tagged `unknown`.
    """
    if license_set is None:
        return rows

    def _src(r: Any) -> str | None:
        if isinstance(r, dict):
            return r.get(url_attr)
        try:
            return getattr(r, url_attr, None)
        except AttributeError:
            return None

    return [r for r in rows if license_for_url(_src(r)) in license_set]


def license_summary(rows: Iterable[Any], *, url_attr: str = "source_url") -> dict[str, int]:
    """Build a `{license: count}` rollup over the returned rows.

    Always includes every license that actually appears (zero-count
    licenses are omitted). `unknown` shows up explicitly when present so
    callers see how much of the response is gray-zone.
    """
    counts: dict[str, int] = {}

    def _src(r: Any) -> str | None:
        if isinstance(r, dict):
            return r.get(url_attr)
        try:
            return getattr(r, url_attr, None)
        except AttributeError:
            return None

    for r in rows:
        lic = license_for_url(_src(r))
        counts[lic] = counts.get(lic, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# `_next_calls` — deterministic per-row follow-up suggestions.
# ---------------------------------------------------------------------------
#
# Design rules:
#   1. Suggestions reference foreign keys that are populated on the row;
#      never speculate on chains the row doesn't actually announce.
#   2. Tool names are MCP-canonical (matches `mcp/server.py` registrations).
#   3. Limit 2-3 per row to keep response payloads bounded.
#
# Per CLAUDE.md "phantom moat audit" guidance: only emit a suggestion when
# the row actually carries the foreign key. A search row with a NULL
# `programs_used_json` does NOT get a `find_cases_by_program` suggestion.


def _row_attr(row: Any, key: str) -> Any:
    """Read `row[key]` whether row is a dict, sqlite3.Row, or pydantic model."""
    if isinstance(row, dict):
        return row.get(key)
    if isinstance(row, sqlite3.Row):
        try:
            return row[key]
        except (IndexError, KeyError):
            return None
    return getattr(row, key, None)


def _has_value(v: Any) -> bool:
    """Truthy except treat empty list/dict/str as 'no value'."""
    if v is None:
        return False
    if isinstance(v, (list, dict, str)):
        return bool(v)
    return True


def next_calls_for_program(row: Any) -> list[dict[str, Any]]:
    """Suggest 2-3 follow-up calls for a programs.search row.

    Always: get_program(unified_id).
    Conditional: trace_program_to_law (if program references laws via
    enriched/source_mentions) and find_cases_by_program (if the row hints
    case_studies coverage — we don't pre-join, so this is best-effort).
    """
    uid = _row_attr(row, "unified_id")
    if not uid:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_program", "args": {"unified_id": uid}},
    ]
    # programs rows that reference laws carry program_law_refs in the DB.
    # We don't load that join into the search row, but the source_mentions /
    # enriched JSON usually carries 法令 keywords; the cheapest fast-rule is
    # "always offer trace_program_to_law on UNI-* rows since program_law_refs
    # may carry edges even without enriched populated". The MCP tool itself
    # returns an empty edge set when nothing matches (no quota burn), so the
    # suggestion is honest.
    calls.append({"tool": "trace_program_to_law", "args": {"unified_id": uid}})
    # find_cases_by_program — only emit when we have any signal that case_studies
    # rows mention this program. The honest filter: presence of at least one
    # of (primary_name, aliases) on the row, which is universally true for
    # programs.search results, but the case_studies table is sparse. We
    # add this only when an explicit hint exists in row['program_kind']
    # being 'subsidy' (the only kind cited in 採択事例 today). Anything
    # else (loan / tax / certification) skips the case-study suggestion.
    program_kind = _row_attr(row, "program_kind")
    if program_kind == "subsidy":
        calls.append({"tool": "find_cases_by_program", "args": {"program_id": uid}})
    return calls


def next_calls_for_law(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for laws.search rows."""
    uid = _row_attr(row, "unified_id")
    if not uid:
        return []
    return [
        {"tool": "get_law", "args": {"unified_id": uid}},
        {"tool": "list_programs_by_law", "args": {"law_id": uid}},
        {"tool": "search_court_decisions", "args": {"references_law_id": uid}},
    ]


def next_calls_for_court_decision(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for court_decisions.search rows."""
    uid = _row_attr(row, "unified_id")
    if not uid:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_court_decision", "args": {"unified_id": uid}},
    ]
    # If row carries related_law_ids, suggest the first as a chaining hint.
    related = _row_attr(row, "related_law_ids")
    if isinstance(related, list) and related:
        first_law = related[0]
        if isinstance(first_law, str) and first_law.startswith("LAW-"):
            calls.append({"tool": "get_law", "args": {"unified_id": first_law}})
    return calls


def next_calls_for_case_study(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for case_studies.search rows."""
    case_id = _row_attr(row, "case_id")
    if not case_id:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_case_study", "args": {"case_id": case_id}},
    ]
    programs_used = _row_attr(row, "programs_used")
    if isinstance(programs_used, list) and programs_used:
        first = programs_used[0]
        if isinstance(first, str) and first.startswith("UNI-"):
            calls.append({"tool": "get_program", "args": {"unified_id": first}})
    houjin = _row_attr(row, "houjin_bangou")
    if isinstance(houjin, str) and len(houjin) == 13 and houjin.isdigit():
        calls.append(
            {
                "tool": "check_enforcement_am",
                "args": {"houjin_bangou": houjin},
            }
        )
    return calls


def next_calls_for_bid(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for bids.search rows."""
    uid = _row_attr(row, "unified_id")
    if not uid:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_bid", "args": {"unified_id": uid}},
    ]
    program_id_hint = _row_attr(row, "program_id_hint")
    if isinstance(program_id_hint, str) and program_id_hint.startswith("UNI-"):
        calls.append({"tool": "get_program", "args": {"unified_id": program_id_hint}})
    winner_houjin = _row_attr(row, "winner_houjin_bangou")
    if isinstance(winner_houjin, str) and len(winner_houjin) == 13 and winner_houjin.isdigit():
        calls.append(
            {
                "tool": "check_enforcement_am",
                "args": {"houjin_bangou": winner_houjin},
            }
        )
    return calls


def next_calls_for_invoice_registrant(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for invoice_registrants.search rows."""
    reg_no = _row_attr(row, "invoice_registration_number")
    if not reg_no:
        return []
    calls: list[dict[str, Any]] = [
        {
            "tool": "get_invoice_registrant",
            "args": {"invoice_registration_number": reg_no},
        }
    ]
    houjin = _row_attr(row, "houjin_bangou")
    if isinstance(houjin, str) and len(houjin) == 13 and houjin.isdigit():
        calls.append(
            {
                "tool": "check_enforcement_am",
                "args": {"houjin_bangou": houjin},
            }
        )
    return calls


def next_calls_for_loan(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for loan_programs.search rows."""
    loan_id = _row_attr(row, "id")
    if loan_id is None:
        return []
    return [
        {"tool": "get_loan_program", "args": {"id": loan_id}},
    ]


def next_calls_for_tax_ruleset(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for tax_rulesets.search rows."""
    uid = _row_attr(row, "unified_id")
    if not uid:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_tax_ruleset", "args": {"unified_id": uid}},
        {"tool": "evaluate_tax_rulesets", "args": {"target_ruleset_ids": [uid]}},
    ]
    related = _row_attr(row, "related_law_ids")
    if isinstance(related, list) and related:
        first_law = related[0]
        if isinstance(first_law, str) and first_law.startswith("LAW-"):
            calls.append({"tool": "get_law", "args": {"unified_id": first_law}})
    return calls


def next_calls_for_enforcement(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for enforcement_cases.search rows."""
    case_id = _row_attr(row, "case_id")
    if not case_id:
        return []
    calls: list[dict[str, Any]] = [
        {"tool": "get_enforcement_case", "args": {"case_id": case_id}},
    ]
    houjin = _row_attr(row, "recipient_houjin_bangou")
    if isinstance(houjin, str) and len(houjin) == 13 and houjin.isdigit():
        calls.append(
            {
                "tool": "check_enforcement_am",
                "args": {"houjin_bangou": houjin},
            }
        )
    return calls


def next_calls_for_am_entity(row: Any) -> list[dict[str, Any]]:
    """Suggest follow-ups for autonomath am_entity-shaped search rows
    (search_tax_incentives, search_certifications, search_loans_am, etc.)."""
    eid = _row_attr(row, "entity_id") or _row_attr(row, "canonical_id")
    if not eid:
        return []
    return [
        {"tool": "get_provenance", "args": {"entity_id": eid}},
        {"tool": "get_annotations", "args": {"entity_id": eid}},
    ]


# ---------------------------------------------------------------------------
# Public top-level helper: build (next_calls, license_summary) for a result
# list and return ready-to-merge envelope keys.
# ---------------------------------------------------------------------------


def build_envelope_extras(
    rows: list[Any],
    *,
    next_calls_fn: Any | None = None,
    url_attr: str = "source_url",
) -> dict[str, Any]:
    """Return a dict with `_next_calls` + `_license_summary` ready to merge
    onto a search response body.

    `_next_calls` is a flat list — N rows × 2-3 suggestions each. Caller
    can split per-row downstream if needed; we keep the envelope flat so
    the agent doesn't need to re-traverse the results array.

    `_license_summary` is a dict {license: count} over the visible rows.
    """
    extras: dict[str, Any] = {
        "_license_summary": license_summary(rows, url_attr=url_attr),
    }
    if next_calls_fn is not None:
        flat: list[dict[str, Any]] = []
        for row in rows:
            try:
                flat.extend(next_calls_fn(row))
            except Exception:  # noqa: BLE001
                # Per-row failure must not poison the whole response.
                continue
        extras["_next_calls"] = flat
    return extras
