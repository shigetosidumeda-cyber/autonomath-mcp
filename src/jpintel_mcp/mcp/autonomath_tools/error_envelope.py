"""Unified error envelope for AutonoMath MCP tools (2026-04-23).

Rationale
---------
Customer LLMs consume MCP tool responses as JSON. Currently (wave-3) the
10 new tools and the 13 existing jpintel tools raise / return errors in
three inconsistent shapes:

  1. ``raise ValueError("program not found: xxx")``
       → surfaces to the client as an MCP "tool error" envelope with
         just a message string. The LLM has to parse English prose to
         know WHY the call failed and WHAT to do next. Empirically, this
         causes the LLM to either retry the same call (infinite loop) or
         give up entirely with "I don't know".

  2. ``return {total: 0, results: [], hint: "...", retry_with: [...]}``
       → clean, but the *shape* differs per tool (some have
         ``suggested_tools``, some have ``retry_with``, some have both)
         and ``hint`` is a free-form string that forces string parsing.

  3. ``return {..., "error": "match() failed: RuntimeError: ..."}``
       → internal error leaks implementation detail and has no
         machine-readable code.

This module defines a single helper ``make_error()`` that produces a
stable envelope. Every tool converts its error paths to this helper.
The customer-facing guide (``docs/error_handling.md``) documents the
finite set of ``code`` values and the LLM strategy for each.

Envelope shape
--------------
::

    {
      "error": {
        "code": "missing_required_arg" | "invalid_enum" | "invalid_date_format"
              | "no_matching_records" | "ambiguous_query" | "seed_not_found"
              | "db_locked" | "db_unavailable" | "subsystem_unavailable"
              | "internal",
        "message": "human-readable English (≤120 chars, no stack trace)",
        "hint": "actionable next-step for the LLM (≤200 chars)",
        "retry_with": ["tool_a", "tool_b"],          # alt tools to try
        "suggested_tools": ["enum_values", ...],      # disambiguation tools
        "retry_args": {"region": "関東"},              # suggested arg fixes
        "documentation": "https://.../error_handling.md#<anchor>",
        "field": "law_name",                          # arg name when code is arg-specific
        "severity": "hard" | "soft",                  # hard=stop, soft=degrade-and-continue
      },
      # Even on error, the canonical envelope keys are present so
      # tolerant consumers can treat "error" as a signal without
      # crashing on missing keys:
      "total": 0,
      "limit": <int>,
      "offset": <int>,
      "results": [],
    }

Design choices
--------------
- **Never raise from helper.** Tools call ``make_error(...)`` and
  ``return`` the dict. Raising ValueError leaves the LLM with a single
  string; returning the envelope gives it structured context.
- **code is a closed enum.** Customer LLMs can pattern-match on a
  finite set. Adding a new code requires a doc update.
- **retry_with vs suggested_tools.** ``retry_with`` = "call one of
  these instead of me for the same question". ``suggested_tools`` =
  "call these FIRST to disambiguate, then retry me with better args".
- **documentation URL** points to the published error guide so the LLM
  can read the canonical retry strategy without a reasoning hop.
- **severity** lets the LLM decide: ``hard`` codes (missing_required_arg,
  db_unavailable) mean "cannot proceed"; ``soft`` codes
  (no_matching_records, seed_not_found) mean "the tool ran fine, the
  world just didn't have the answer — a different tool might".
"""
from __future__ import annotations

from typing import Any, Literal

__all__ = [
    "ErrorCode",
    "make_error",
    "is_error",
    "ERROR_CODES",
    "DOC_URL",
]


# ---------------------------------------------------------------------------
# Canonical error codes.
# ---------------------------------------------------------------------------

ErrorCode = Literal[
    "missing_required_arg",
    "invalid_enum",
    "invalid_date_format",
    "out_of_range",
    "no_matching_records",
    "ambiguous_query",
    "seed_not_found",
    "rules_conflict",
    "db_locked",
    "db_unavailable",
    "subsystem_unavailable",
    "internal",
]

#: Public list of error codes + severity + one-line description.
#: Used by ``docs/error_handling.md`` generator and by tests to verify
#: exhaustive coverage.
ERROR_CODES: dict[str, dict[str, str]] = {
    "missing_required_arg": {
        "severity": "hard",
        "summary": "A required argument was empty, null, or whitespace-only.",
    },
    "invalid_enum": {
        "severity": "hard",
        "summary": "An argument did not match the allowed Literal[] values.",
    },
    "invalid_date_format": {
        "severity": "hard",
        "summary": "Date string did not parse as ISO YYYY-MM-DD (or YYYY/MM/DD).",
    },
    "out_of_range": {
        "severity": "hard",
        "summary": "Numeric argument outside declared ge/le bounds.",
    },
    "no_matching_records": {
        "severity": "soft",
        "summary": "Query was valid; no rows matched. Try retry_with / suggested_tools.",
    },
    "ambiguous_query": {
        "severity": "soft",
        "summary": "Free-text query matched multiple disjoint record kinds; refine with filters.",
    },
    "seed_not_found": {
        "severity": "soft",
        "summary": "Graph seed id / canonical id did not resolve to any node. Try search_* first.",
    },
    "rules_conflict": {
        "severity": "hard",
        "summary": "Two or more rule corpora yielded mutually contradictory verdicts for the same input. Force human review — never silently merge.",
    },
    "db_locked": {
        "severity": "hard",
        "summary": "SQLite reported 'database is locked' after retry budget exhausted.",
    },
    "db_unavailable": {
        "severity": "hard",
        "summary": "DB file missing / unreadable / schema mismatch. Not a client-fixable error.",
    },
    "subsystem_unavailable": {
        "severity": "soft",
        "summary": "Optional subsystem (reasoning, query_rewrite) import failed. Tool degrades gracefully.",
    },
    "internal": {
        "severity": "hard",
        "summary": "Unhandled exception inside the tool. Report and retry with backoff.",
    },
}


# ---------------------------------------------------------------------------
# Documentation anchor.
# ---------------------------------------------------------------------------

#: Base documentation URL. Each code's anchor is
#: ``{DOC_URL}#<code>`` — see ``docs/error_handling.md``.
DOC_URL = "https://jpcite.com/docs/error_handling"


# ---------------------------------------------------------------------------
# Helper.
# ---------------------------------------------------------------------------


def make_error(
    code: ErrorCode,
    message: str,
    *,
    hint: str | None = None,
    retry_with: list[str] | None = None,
    suggested_tools: list[str] | None = None,
    retry_args: dict[str, Any] | None = None,
    field: str | None = None,
    limit: int = 20,
    offset: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical error envelope.

    The returned dict is safe to ``return`` from any MCP tool. It includes
    the standard ``{total, limit, offset, results}`` keys so downstream
    consumers that check only for ``error`` OR only for the search envelope
    shape both work without special-casing.

    Parameters
    ----------
    code : ErrorCode
        One of the closed-enum codes in ``ERROR_CODES``.
    message : str
        Human-readable English message (≤120 chars). No stack trace.
    hint : str, optional
        Actionable next step for the LLM (≤200 chars). If omitted, a
        default is derived from ``ERROR_CODES[code]["summary"]``.
    retry_with : list[str], optional
        Alternative tools the LLM should call *instead of* this tool.
    suggested_tools : list[str], optional
        Disambiguation tools the LLM should call *before* retrying this
        tool (typically ``enum_values`` or ``search_*``).
    retry_args : dict, optional
        Suggested argument fixes (e.g. ``{"region": "関東"}``).
    field : str, optional
        The specific argument that triggered the error (for
        ``missing_required_arg`` / ``invalid_enum`` / ``out_of_range``).
    limit, offset : int
        Pagination echo (so the envelope round-trips with search tools).
    extra : dict, optional
        Additional per-tool fields (e.g. ``{"seed_name": "..."}`` for
        ``related_programs``). Merged into the ``error`` dict last.
    """
    if code not in ERROR_CODES:
        # Defensive: unknown code → coerce to "internal".
        code = "internal"
    spec = ERROR_CODES[code]
    err: dict[str, Any] = {
        "code": code,
        "message": message.strip() if message else spec["summary"],
        "hint": (hint or spec["summary"]).strip(),
        "severity": spec["severity"],
        "documentation": f"{DOC_URL}#{code}",
    }
    if retry_with:
        err["retry_with"] = list(retry_with)
    if suggested_tools:
        err["suggested_tools"] = list(suggested_tools)
    if retry_args:
        err["retry_args"] = dict(retry_args)
    if field:
        err["field"] = field
    if extra:
        for k, v in extra.items():
            err.setdefault(k, v)
    # Tier 1 CS Feature J: attach plain-Japanese user_message. Soft-imported
    # so the error envelope module remains importable in stripped-down test
    # environments where cs_features may not be on path.
    try:
        from .cs_features import user_message_for_error  # local import
        err.setdefault("user_message", user_message_for_error(code))
    except Exception:  # pragma: no cover - defensive
        pass
    return {
        "error": err,
        "total": 0,
        "limit": max(1, min(100, int(limit))),
        "offset": max(0, int(offset)),
        "results": [],
    }


def is_error(payload: Any) -> bool:
    """Return True iff ``payload`` is an error envelope. Customer LLMs
    should check this first before assuming a payload has ``results``.
    """
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("error"), dict)
        and payload["error"].get("code") in ERROR_CODES
    )
