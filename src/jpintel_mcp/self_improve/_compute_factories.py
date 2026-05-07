"""Compute factories injected into Loop H (cache warming).

Loop H (`loop_h_cache_warming.run`) takes a `compute_factories` kwarg shaped
as ``{l4_tool_name: callable(params)->dict}``. The orchestrator wires the
factories through this module so the loop body stays decoupled from the
FastAPI app graph (no circular imports, unit tests can stub freely).

What each factory does:

    * Re-computes the body for ONE L4 cache key, given the canonical params
      blob recovered from `l4_query_cache.params_json`.
    * Opens its own short-lived sqlite3 connection so the orchestrator
      doesn't have to thread one through.
    * Returns a JSON-serialisable dict (the same shape the route handler
      would have produced — `_l4_get_or_compute_safe`'s "compute" closure).

Why factories live HERE (not in the API routers): the route handlers'
compute closures (`_do_search`, `_do_get`) close over per-request state
(`conn`, `ctx`, `request`, FastAPI Query objects). We can't call them from
cron without a request context. Instead we re-derive the same response by
calling the underlying pure helpers (`_build_search_response`,
`_row_to_program_detail`, `tools.search_tax_incentives`) with params
plucked from the cached `params_json`.

Constraints (CONSTITUTION 13.2 + `feedback_autonomath_no_api_use`):
    * No Anthropic / Claude / OpenAI / Gemini / SDK imports — pure Python +
      SQLite + the existing app-internal pure helpers.
    * No `log_usage` call here — warming is internal cron and MUST NOT
      increment `usage_events` (would double-bill or zero-bill, see the
      docstring on `loop_h_cache_warming`).
    * Defensive: if a helper raises, we swallow into None — the loop's
      `_warm_one` already treats unserializable / None-returning computes
      as a skip. A noisy crash would take the whole orchestrator down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Tool names — must match the constants in the live route handlers.
# Drift here means the warmer writes to a different cache_key partition than
# the route reads from, so the warming silently does nothing.
# ---------------------------------------------------------------------------
TOOL_PROGRAMS_SEARCH = "api.programs.search"
TOOL_PROGRAMS_GET = "api.programs.get"
TOOL_AM_TAX_INCENTIVES = "api.am.tax_incentives"


# Whitelist of params that `_build_search_response` accepts. Cached
# `l4_query_cache.params_json` rows include extras (`ctx_tier`, `as_of_date`)
# that the helper does not take as kwargs — `as_of_date` is converted to
# `as_of_iso` and `ctx_tier` is irrelevant to the SQL build (it only gates
# `fields=full` upstream). Keep this in sync with `_build_search_response`'s
# signature in api/programs.py:1235.
_SEARCH_PASSTHROUGH_KEYS = (
    "q",
    "tier",
    "prefecture",
    "authority_level",
    "funding_purpose",
    "target_type",
    "amount_min",
    "amount_max",
    "include_excluded",
    "limit",
    "offset",
    "fields",
    "include_advisors",
)


def _programs_search_factory(params: dict[str, Any]) -> dict[str, Any] | None:
    """Re-compute the /v1/programs/search body from cached params.

    Mirrors `api/programs.py::search_programs`'s `_do_search` closure but
    opens its own connection. Returns the raw response dict on success,
    None on any error (loop's `_warm_one` treats None as a skip).
    """
    # Lazy imports — keep the orchestrator import light + avoid pulling
    # the FastAPI app graph at module load (circular-import insurance).
    try:
        from jpintel_mcp.api.programs import _build_search_response
        from jpintel_mcp.db.session import connect
    except ImportError:
        return None

    kwargs: dict[str, Any] = {k: params.get(k) for k in _SEARCH_PASSTHROUGH_KEYS}
    # Defaults — params_json ALWAYS carries these because the route always
    # populated them, but be defensive against schema drift.
    kwargs.setdefault("include_excluded", False)
    kwargs.setdefault("limit", 20)
    kwargs.setdefault("offset", 0)
    kwargs.setdefault("fields", "default")
    kwargs.setdefault("include_advisors", False)
    kwargs["as_of_iso"] = params.get("as_of_date")

    conn = connect()
    try:
        return _build_search_response(conn=conn, **kwargs)
    except Exception:  # noqa: BLE001
        # Loop H must not crash the orchestrator on a single bad row.
        return None
    finally:
        conn.close()


def _programs_get_factory(params: dict[str, Any]) -> dict[str, Any] | None:
    """Re-compute the /v1/programs/{unified_id} body from cached params.

    Mirrors `api/programs.py::get_program`'s `_do_get` closure. Single-row
    SELECT + `_row_to_program_detail` rebuild. None on error / not-found.
    """
    try:
        from jpintel_mcp.api.programs import _row_to_program_detail
        from jpintel_mcp.db.session import connect
    except ImportError:
        return None

    unified_id = params.get("unified_id")
    fields = params.get("fields", "default")
    if not unified_id:
        return None

    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?",
            (unified_id,),
        ).fetchone()
        if row is None:
            return None
        # tier-X quarantine — same posture as the live route handler. A
        # warming pass that materialised quarantined rows would silently
        # poison the cache.
        if (row["tier"] or "X") == "X":
            return None
        return _row_to_program_detail(row, fields)
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


# Whitelist of params that `tools.search_tax_incentives` accepts. The cache
# row's params include `ctx_tier` (cache-poisoning guard) which the tool
# function itself does not take. Keep in sync with the function signature in
# mcp/autonomath_tools/tools.py:421.
_TAX_INCENTIVES_PASSTHROUGH_KEYS = (
    "query",
    "authority",
    "industry",
    "target_year",
    "target_entity",
    "natural_query",
    "limit",
    "offset",
    "lang",
    "foreign_capital_eligibility",
)


def _am_tax_incentives_factory(params: dict[str, Any]) -> dict[str, Any] | None:
    """Re-compute the /v1/am/tax_incentives body from cached params.

    Mirrors `api/autonomath.py::rest_search_tax_incentives`'s `_do_search`.
    Note: the live route applies `_apply_envelope` AFTER the L4 cache get
    so the envelope hints (status / explanation / suggestions) stay current.
    The cached body therefore stores the RAW tool result, not the enveloped
    response — same posture here.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools import tools
    except ImportError:
        return None

    kwargs: dict[str, Any] = {k: params.get(k) for k in _TAX_INCENTIVES_PASSTHROUGH_KEYS}
    kwargs.setdefault("limit", 20)
    kwargs.setdefault("offset", 0)

    try:
        # `_safe_tool` decoration in tools.py already returns an error
        # envelope on DB faults rather than raising — but be defensive
        # anyway so a tool refactor cannot crash the orchestrator.
        return cast("dict[str, Any]", tools.search_tax_incentives(**kwargs))
    except Exception:  # noqa: BLE001
        return None


def build_compute_factories() -> dict[str, Callable[[dict[str, Any]], Any]]:
    """Construct the `{l4_tool_name: callable}` map injected into Loop H.

    Keys MUST match the L4 tool-name constants in the route handlers
    (`api.programs.search`, `api.programs.get`, `api.am.tax_incentives`)
    AND the `_ENDPOINT_TO_L4_TOOL` map in `loop_h_cache_warming.py`.

    Returns:
        Three-entry dict — one factory per L4-wired endpoint. Add new
        entries here as more endpoints get L4-wrapped (track the constants
        in api/programs.py + api/autonomath.py + the `_ENDPOINT_TO_L4_TOOL`
        map in loop_h_cache_warming.py).
    """
    return {
        TOOL_PROGRAMS_SEARCH: _programs_search_factory,
        TOOL_PROGRAMS_GET: _programs_get_factory,
        TOOL_AM_TAX_INCENTIVES: _am_tax_incentives_factory,
    }
