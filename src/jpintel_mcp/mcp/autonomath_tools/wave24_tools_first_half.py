"""wave24_tools_first_half — Chapter 10.7 new MCP tools #97-#108 (12 tools).

First-half landing of the 24-tool Wave 24 batch (MASTER_PLAN_v1 §10.7).
Tools land in two files (this file = #97-#108, sibling file = #109-#120).

Tools shipped here
------------------

  recommend_programs_for_houjin   (#97)  — am_recommended_programs TOP-N + reason_json
  find_combinable_programs        (#98)  — am_program_combinations, visibility='public' default
  get_program_calendar_12mo       (#99)  — am_program_calendar_12mo
  forecast_enforcement_risk       (#100) — am_enforcement_industry_risk
  find_similar_case_studies       (#101) — am_case_study_similarity
  get_houjin_360_snapshot_history (#102) — am_houjin_360_snapshot, 12mo trend + delta
  get_tax_amendment_cycle         (#103) — am_tax_amendment_history + cycle_stats
  infer_invoice_buyer_seller      (#104) — am_invoice_buyer_seller_graph
  match_programs_by_capital       (#105) — am_capital_band_program_match (capital→band)
  get_program_adoption_stats      (#106) — am_program_adoption_stats
  get_program_narrative           (#107) — am_program_narrative (section='all' OR single)
  predict_rd_tax_credit           (#108) — am_houjin_360_snapshot + am_tax_amendment_history

Hard constraints (memory feedback_no_operator_llm_api)
------------------------------------------------------

  * Tool body never imports anthropic / openai / google.generativeai.
  * Tool body never calls an LLM API. SELECT only.
  * Pre-computed narratives originate from the operator-side Claude Code
    subagent batch (§10.6) and land in `am_program_narrative` via cron;
    here we read them back, never generate them.

Migration table-presence is best-effort
---------------------------------------

The 14 wave24_* migrations (126-139) are landed by a sibling agent
(W1-14). When a target table is missing in a fresh dev DB, every tool
returns the canonical empty envelope (`results=[], total=0,
_billing_unit=N, _next_calls=[]`) instead of raising — the customer LLM
gets a "no data" signal rather than a 500.

Sensitive-tool disclaimer flow
------------------------------

Eleven of the twelve tools sit in the §52 / §72 / §1 / 信用情報法 /
個人情報保護法 / 景表法 fence (per §L1 mapping). The disclaimer string
itself lives in `envelope_wrapper.SENSITIVE_TOOLS` (already pre-registered
by the parallel W1-10 agent), so the response decorator auto-injects
`_disclaimer` once the tool name flows through `with_envelope`. The
twelve-tool registration block at the bottom of this file uses the
canonical `@mcp.tool(annotations=_READ_ONLY)` decorator; the
auto-disclaimer pickup happens at the envelope-wrap layer registered
by `mcp/server.py`.

NO LLM call inside any tool — pure SQLite + Python over autonomath.db.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.db.id_translator import normalize_program_id
from jpintel_mcp.ingest.plain_japanese_dict import replace_plain_japanese
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error as _raw_make_error
from .snapshot_helper import attach_corpus_snapshot


def make_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """make_error wrapper that always attaches the corpus_snapshot pair.

    W3-13 finding (2026-05-04): every customer-facing response —
    including error envelopes — must carry the auditor reproducibility
    pair. We wrap make_error here so every error-path return picks it
    up without having to touch every call site individually.
    """
    return attach_corpus_snapshot(_raw_make_error(*args, **kwargs))


def _finalize(body: dict[str, Any]) -> dict[str, Any]:
    """Attach corpus_snapshot pair to the impl response body. Idempotent."""
    return attach_corpus_snapshot(body)


logger = logging.getLogger("jpintel.mcp.autonomath.wave24a")

# Env-gated registration (default on). Flip to "0" for one-flag rollback
# if a regression surfaces post-launch.
_ENABLED = os.environ.get("AUTONOMATH_WAVE24_FIRST_HALF_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _normalize_houjin(value: str | None) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix)."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _is_valid_houjin(value: str) -> bool:
    """13-digit numeric check after `_normalize_houjin`."""
    return bool(value) and value.isdigit() and len(value) == 13


def _to_unified(program_id: str) -> str:
    """Translate any ``program_id`` form to ``UNI-...`` for wave24 tables.

    All wave24 substrate tables (``am_program_combinations``,
    ``am_program_calendar_12mo``, ``am_program_documents`` etc.) key on
    ``program_unified_id`` per their migrations. The customer LLM may
    pass either ``UNI-...`` (jpi_programs.unified_id) or ``program:...``
    (am_entities.canonical_id) depending on which earlier ``_next_calls``
    it walked through. Normalize once here so the SQL hits the right
    column regardless. Falls back to the original input on translation
    miss — matches current behavior, just no longer empty-result-silent
    when the agent passes a canonical id.
    """
    uni, _can = normalize_program_id(program_id)
    return uni or program_id


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db (read-only), returning either a conn or err envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return True iff `name` exists as a table or view in the open DB.

    Used for graceful degradation — when a wave24 migration has not yet
    landed in a fresh dev DB, the tool returns an empty envelope instead
    of raising `no such table`.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True iff `table` has a column named `column`.

    Mirrors the helper in `wave24_tools_second_half.py` so this file can
    safe-gate optional columns (e.g. `am_compat_matrix.visibility` added
    by migration wave24_107) without raising on legacy DBs that have not
    applied the migration yet.
    """
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)
    except sqlite3.Error:
        return False


def _empty_envelope(
    *,
    billing_unit: int = 1,
    limit: int = 20,
    offset: int = 0,
    next_calls: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical empty envelope (graceful degradation when table absent).

    Mirrors the keys that `error_envelope.make_error` and the regular
    success path emit so consumers never key-miss on `_billing_unit`,
    `_next_calls`, `total`, etc.
    """
    body: dict[str, Any] = {
        "total": 0,
        "limit": max(1, min(500, int(limit))),
        "offset": max(0, int(offset)),
        "results": [],
        "_billing_unit": int(billing_unit),
        "_next_calls": list(next_calls or []),
    }
    if extra:
        for k, v in extra.items():
            body.setdefault(k, v)
    return attach_corpus_snapshot(body)


def _capital_band_for_yen(capital_yen: int) -> str:
    """Map a JPY capital amount to a canonical band id matching
    `am_capital_band_program_match.capital_band` (#105 helper).

    Band labels MUST stay in sync with the CHECK constraint in
    `scripts/migrations/wave24_134_am_capital_band_program_match.sql`:
        under_1m / 1m_to_3m / 3m_to_5m / 5m_to_10m /
        10m_to_50m / 50m_to_100m / 100m_to_300m /
        300m_to_1b / 1b_plus
    Any drift here causes silent zero-row joins on the production
    `am_capital_band_program_match` table.
    """
    n = int(capital_yen or 0)
    if n < 0:
        return "unknown"
    if n < 1_000_000:
        return "under_1m"
    if n < 3_000_000:
        return "1m_to_3m"
    if n < 5_000_000:
        return "3m_to_5m"
    if n < 10_000_000:
        return "5m_to_10m"
    if n < 50_000_000:
        return "10m_to_50m"
    if n < 100_000_000:
        return "50m_to_100m"
    if n < 300_000_000:
        return "100m_to_300m"
    if n < 1_000_000_000:
        return "300m_to_1b"
    return "1b_plus"


def _safe_json_loads(blob: Any) -> Any:
    """Best-effort JSON decode. Returns the original value on failure."""
    if blob is None or blob == "":
        return None
    if isinstance(blob, (dict, list)):
        return blob
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return blob


def _delta_from_prev(curr: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
    """Compute a shallow per-key delta between `curr` and `prev`.

    Used by `get_houjin_360_snapshot_history` (#102) to surface the
    month-over-month diff without forcing the customer LLM to do JSON
    diffing on its own.
    """
    if not prev:
        return {"is_first": True, "changed_keys": []}
    changed: list[dict[str, Any]] = []
    for key in sorted(set(curr.keys()) | set(prev.keys())):
        if key.startswith("_") or key in {"snapshot_month", "houjin_bangou"}:
            continue
        a, b = prev.get(key), curr.get(key)
        if a != b:
            changed.append({"key": key, "prev": a, "curr": b})
    return {"is_first": False, "changed_keys": changed}


# ---------------------------------------------------------------------------
# #97 recommend_programs_for_houjin
# ---------------------------------------------------------------------------


def _recommend_programs_for_houjin_impl(
    houjin_bangou: str,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """SELECT TOP-N from `am_recommended_programs` for a 法人.

    The reason payload is stored as JSON in `reason_json`; we decode it
    here so the customer LLM does not have to.
    """
    if not houjin_bangou:
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not _is_valid_houjin(hb):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    limit = max(1, min(int(limit or 10), 50))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_calendar_12mo",
            "args": {"program_id": "<results[0].program_id>"},
            "rationale": "12 ヶ月カレンダーで直近の開期を確認。",
            "estimated_units": 1,
        },
        {
            "tool": "score_application_probability",
            "args": {
                "program_id": "<results[0].program_id>",
                "houjin_bangou": hb,
            },
            "rationale": "TOP 候補について採択者類似度スコアを取得。",
            "estimated_units": 2,
        },
    ]

    if not _table_exists(conn, "am_recommended_programs"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_recommended_programs (migration wave24_126) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    try:
        # Total for pagination echo.
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_recommended_programs WHERE houjin_bangou = ?",
            (hb,),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0

        rows = conn.execute(
            """
            SELECT program_unified_id AS program_id, score, rank, reason_json,
                   computed_at
              FROM am_recommended_programs
             WHERE houjin_bangou = ?
             ORDER BY rank ASC, score DESC
             LIMIT ? OFFSET ?
            """,
            (hb, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_recommended_programs query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_recommended_programs query failed: {exc}",
        )

    results = [
        {
            "program_id": r["program_id"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "rank": int(r["rank"]) if r["rank"] is not None else None,
            "reason": _safe_json_loads(r["reason_json"]),
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "houjin_bangou": hb,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #98 find_combinable_programs
# ---------------------------------------------------------------------------


def _find_combinable_programs_impl(
    program_id: str,
    visibility: str = "public",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the partner-program list from `am_program_combinations`.

    The CHECK constraint on the table is `program_a < program_b`, so we
    issue a UNION matching either side and rewrite to "partner_program_id".
    `visibility='public'` is the default (per §10.6.4 finding (c) — only
    sourced rows surface to public callers).
    """
    if not program_id:
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    program_id = _to_unified(program_id)
    if visibility not in ("public", "internal", "all"):
        return make_error(
            code="invalid_enum",
            message=f"visibility must be one of public/internal/all (got {visibility!r}).",
            field="visibility",
        )
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_complementary_subsidies",
            "args": {"program_id": program_id},
            "rationale": "時系列カバー軸の補完候補を別 query で取得。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_program_combinations"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "program_id": program_id,
                "visibility": visibility,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_program_combinations (migration wave24_127) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    # Schema (migration wave24_127): am_program_combinations carries
    #   program_a_unified_id, program_b_unified_id, combinable (0/1/2),
    #   confidence ('high'|'medium'|'low'), reason, source_url, source_kind,
    #   computed_at. There is NO `visibility` and NO `evidence_json` column
    #   on this table — visibility is an `am_compat_matrix` concept (added
    #   by migration wave24_107). When the caller asks for a visibility
    #   filter we attempt to join through `am_compat_matrix` if its
    #   visibility column is present; otherwise we degrade to the legacy
    #   sourced/heuristic split (`inferred_only=0 AND source_url IS NOT NULL`
    #   for 'public', the inverse for 'internal').
    #
    # Caveat the caller about how the filter was applied so the surface is
    # honest about whether the requested visibility ladder was real.
    visibility_basis = "no_filter"
    visibility_clause_a = ""
    visibility_clause_b = ""
    visibility_params: tuple[Any, ...] = ()
    has_compat = _table_exists(conn, "am_compat_matrix")
    has_visibility = has_compat and _column_exists(conn, "am_compat_matrix", "visibility")
    has_inferred_only = has_compat and _column_exists(conn, "am_compat_matrix", "inferred_only")
    has_compat_source_url = has_compat and _column_exists(conn, "am_compat_matrix", "source_url")
    has_program_a_uni = has_compat and _column_exists(
        conn, "am_compat_matrix", "program_a_unified_id"
    )
    has_program_b_uni = has_compat and _column_exists(
        conn, "am_compat_matrix", "program_b_unified_id"
    )
    can_join_compat = (
        has_compat
        and has_program_a_uni
        and has_program_b_uni
        and (has_visibility or (has_inferred_only and has_compat_source_url))
    )

    if visibility != "all" and can_join_compat:
        if has_visibility:
            visibility_basis = "compat_matrix.visibility"
            visibility_clause_a = (
                " AND EXISTS (SELECT 1 FROM am_compat_matrix m "
                "WHERE m.program_a_unified_id = c.program_a_unified_id "
                "AND m.program_b_unified_id = c.program_b_unified_id "
                "AND m.visibility = ?)"
            )
            visibility_clause_b = (
                " AND EXISTS (SELECT 1 FROM am_compat_matrix m "
                "WHERE m.program_a_unified_id = c.program_a_unified_id "
                "AND m.program_b_unified_id = c.program_b_unified_id "
                "AND m.visibility = ?)"
            )
            visibility_params = (visibility,)
        else:
            # Legacy fallback: 'public' = sourced (inferred_only=0 AND
            # source_url present), 'internal' = its complement.
            visibility_basis = "compat_matrix.inferred_only_fallback"
            if visibility == "public":
                fallback_pred = (
                    "m.inferred_only = 0 AND m.source_url IS NOT NULL AND m.source_url != ''"
                )
            else:  # 'internal'
                fallback_pred = "(m.inferred_only = 1 OR m.source_url IS NULL OR m.source_url = '')"
            visibility_clause_a = (
                f" AND EXISTS (SELECT 1 FROM am_compat_matrix m "
                f"WHERE m.program_a_unified_id = c.program_a_unified_id "
                f"AND m.program_b_unified_id = c.program_b_unified_id "
                f"AND {fallback_pred})"
            )
            visibility_clause_b = visibility_clause_a
            visibility_params = ()
    elif visibility != "all":
        # `am_compat_matrix` join not possible — be honest in the caveat
        # rather than silently dropping rows. We still filter by source_url
        # presence directly on `am_program_combinations` as the closest
        # available proxy for 'public'.
        visibility_basis = "program_combinations.source_url_fallback"
        if visibility == "public":
            visibility_clause_a = " AND c.source_url IS NOT NULL AND c.source_url != ''"
        else:
            visibility_clause_a = " AND (c.source_url IS NULL OR c.source_url = '')"
        visibility_clause_b = visibility_clause_a
        visibility_params = ()

    sql = f"""
        SELECT partner_program_id, combinable, confidence, reason,
               source_url, source_kind, computed_at
          FROM (
            SELECT c.program_b_unified_id AS partner_program_id,
                   c.combinable, c.confidence, c.reason,
                   c.source_url, c.source_kind, c.computed_at
              FROM am_program_combinations c
             WHERE c.program_a_unified_id = ?{visibility_clause_a}
            UNION ALL
            SELECT c.program_a_unified_id AS partner_program_id,
                   c.combinable, c.confidence, c.reason,
                   c.source_url, c.source_kind, c.computed_at
              FROM am_program_combinations c
             WHERE c.program_b_unified_id = ?{visibility_clause_b}
          )
         ORDER BY CASE confidence
                    WHEN 'high'   THEN 0
                    WHEN 'medium' THEN 1
                    WHEN 'low'    THEN 2
                    ELSE 3
                  END,
                  partner_program_id
         LIMIT ? OFFSET ?
    """
    count_sql = f"""
        SELECT COUNT(*) AS n FROM (
          SELECT 1 FROM am_program_combinations c
           WHERE c.program_a_unified_id = ?{visibility_clause_a}
          UNION ALL
          SELECT 1 FROM am_program_combinations c
           WHERE c.program_b_unified_id = ?{visibility_clause_b}
        )
    """

    try:
        total_row = conn.execute(
            count_sql,
            (program_id, *visibility_params, program_id, *visibility_params),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            sql,
            (
                program_id,
                *visibility_params,
                program_id,
                *visibility_params,
                limit,
                offset,
            ),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_program_combinations query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_program_combinations query failed: {exc}",
        )

    results = [
        {
            "partner_program_id": r["partner_program_id"],
            "combinable": bool(r["combinable"]) if r["combinable"] is not None else None,
            "confidence": r["confidence"],
            "reason": r["reason"],
            "source_url": r["source_url"],
            "source_kind": r["source_kind"],
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "program_id": program_id,
            "visibility": visibility,
            "visibility_basis": visibility_basis,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #99 get_program_calendar_12mo
# ---------------------------------------------------------------------------


def _get_program_calendar_12mo_impl(
    program_id: str,
    limit: int = 12,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the 12-month calendar (`am_program_calendar_12mo`) for a program."""
    if not program_id:
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    program_id = _to_unified(program_id)
    limit = max(1, min(int(limit or 12), 24))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_adoption_stats",
            "args": {"program_id": program_id},
            "rationale": "開期確認 → 採択統計でレース性を読む。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_program_calendar_12mo"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "program_id": program_id,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_program_calendar_12mo (migration wave24_128) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_program_calendar_12mo WHERE program_unified_id = ?",
            (program_id,),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            """
            SELECT month_start AS month, is_open, deadline, round_id_json,
                   notes, computed_at
              FROM am_program_calendar_12mo
             WHERE program_unified_id = ?
             ORDER BY month_start ASC
             LIMIT ? OFFSET ?
            """,
            (program_id, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_program_calendar_12mo query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_program_calendar_12mo query failed: {exc}",
        )

    # `am_program_calendar_12mo` stores `round_id_json` (JSON list of
    # `am_application_round.round_id`). The tool docstring promises a
    # human-readable `round_label`, so we resolve ids → labels via a
    # bounded follow-up SELECT (graceful when am_application_round is
    # absent or rounds were pruned).
    has_app_round = _table_exists(conn, "am_application_round")
    results: list[dict[str, Any]] = []
    for r in rows:
        round_ids = _safe_json_loads(r["round_id_json"]) or []
        round_label: str | None = None
        if has_app_round and isinstance(round_ids, list) and round_ids:
            try:
                placeholders = ",".join("?" for _ in round_ids)
                label_rows = conn.execute(
                    f"SELECT round_label FROM am_application_round "
                    f"WHERE round_id IN ({placeholders})",
                    tuple(round_ids),
                ).fetchall()
                labels = [lr["round_label"] for lr in label_rows if lr["round_label"]]
                if labels:
                    round_label = " / ".join(labels)
            except sqlite3.Error:
                round_label = None
        results.append(
            {
                "month": r["month"],
                "is_open": bool(r["is_open"]) if r["is_open"] is not None else None,
                "deadline": r["deadline"],
                "round_label": round_label,
                "round_ids": round_ids if isinstance(round_ids, list) else [],
                "notes": r["notes"],
                "computed_at": r["computed_at"],
            }
        )

    return _finalize(
        {
            "program_id": program_id,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #100 forecast_enforcement_risk
# ---------------------------------------------------------------------------


def _forecast_enforcement_risk_impl(
    jsic_major: str | None = None,
    region_code: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Cross-reference (jsic × region) against `am_enforcement_industry_risk`.

    Either or both filters may be supplied; absence means wildcard.
    """
    if not jsic_major and not region_code:
        return make_error(
            code="missing_required_arg",
            message="At least one of jsic_major or region_code is required.",
            field="jsic_major",
            hint="Pass jsic_major (e.g. 'D') and/or region_code (5-digit JIS X 0401).",
        )
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_adopted_companies_by_program",
            "args": {"program_id": "<inferred>"},
            "rationale": "高リスク sector の同業他社を採択履歴から横展開。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_enforcement_industry_risk"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "jsic_major": jsic_major,
                "region_code": region_code,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_enforcement_industry_risk (migration wave24_129) "
                        "not yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    where_clauses: list[str] = []
    params: list[Any] = []
    if jsic_major:
        where_clauses.append("jsic_major = ?")
        params.append(str(jsic_major).strip().upper()[:1])
    if region_code:
        where_clauses.append("region_code = ?")
        params.append(str(region_code).strip())
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Schema (migration wave24_129):
    #   jsic_major, jsic_middle, region_code, risk_category,
    #   incident_count, total_amount_yen, percentile_in_industry,
    #   trend_3yr_json, source_snapshot_id, computed_at
    # Response payload exposes these columns directly — historical aliases
    # were dropped because the underlying table never carried them.
    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM am_enforcement_industry_risk WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT jsic_major, jsic_middle, region_code, risk_category,
                   incident_count, total_amount_yen, percentile_in_industry,
                   trend_3yr_json, source_snapshot_id, computed_at
              FROM am_enforcement_industry_risk
             WHERE {where_sql}
             ORDER BY percentile_in_industry DESC,
                      incident_count DESC
             LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_enforcement_industry_risk query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_enforcement_industry_risk query failed: {exc}",
        )

    results = [
        {
            "jsic_major": r["jsic_major"],
            "jsic_middle": r["jsic_middle"],
            "region_code": r["region_code"],
            "risk_category": r["risk_category"],
            "incident_count": r["incident_count"],
            "total_amount_yen": r["total_amount_yen"],
            "percentile_in_industry": r["percentile_in_industry"],
            "trend_3yr": _safe_json_loads(r["trend_3yr_json"]),
            "source_snapshot_id": r["source_snapshot_id"],
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "jsic_major": jsic_major,
            "region_code": region_code,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #101 find_similar_case_studies
# ---------------------------------------------------------------------------


def _find_similar_case_studies_impl(
    case_id: int | str,
    limit: int = 5,
    offset: int = 0,
) -> dict[str, Any]:
    """Return up to N similar cases from `am_case_study_similarity`.

    PK on the table is `(case_a, case_b)`; we UNION-ALL both directions.
    """
    if case_id is None or case_id == "":
        return make_error(
            code="missing_required_arg",
            message="case_id is required.",
            field="case_id",
        )
    try:
        cid: int | str = int(case_id)
    except (TypeError, ValueError):
        cid = str(case_id)
    limit = max(1, min(int(limit or 5), 50))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_adopted_companies_by_program",
            "args": {"program_id": "<results[0].program_id_b>"},
            "rationale": "似た採択事例の同 program 採択企業 list を引く。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_case_study_similarity"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "case_id": cid,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_case_study_similarity (migration wave24_130) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    sql = """
        SELECT partner_case_id, similarity, shared_features_json,
               computed_at
          FROM (
            SELECT case_b AS partner_case_id, similarity,
                   shared_features_json, computed_at
              FROM am_case_study_similarity
             WHERE case_a = ?
            UNION ALL
            SELECT case_a AS partner_case_id, similarity,
                   shared_features_json, computed_at
              FROM am_case_study_similarity
             WHERE case_b = ?
          )
         ORDER BY similarity DESC, partner_case_id
         LIMIT ? OFFSET ?
    """
    count_sql = """
        SELECT COUNT(*) AS n FROM (
          SELECT 1 FROM am_case_study_similarity WHERE case_a = ?
          UNION ALL
          SELECT 1 FROM am_case_study_similarity WHERE case_b = ?
        )
    """

    try:
        total_row = conn.execute(count_sql, (cid, cid)).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(sql, (cid, cid, limit, offset)).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_case_study_similarity query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_case_study_similarity query failed: {exc}",
        )

    results = [
        {
            "case_id": r["partner_case_id"],
            "similarity": r["similarity"],
            "shared_features": _safe_json_loads(r["shared_features_json"]),
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "case_id": cid,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #102 get_houjin_360_snapshot_history
# ---------------------------------------------------------------------------


def _get_houjin_360_snapshot_history_impl(
    houjin_bangou: str,
    months: int = 12,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the last N monthly snapshots from `am_houjin_360_snapshot`.

    Each row's `delta_from_prev` is computed in Python by JSON-diffing the
    `payload_json` against the previous month — keeps the SQL slim and
    keeps the diff format under our control.
    """
    if not houjin_bangou:
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not _is_valid_houjin(hb):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if not isinstance(months, int) or months < 1 or months > 36:
        return make_error(
            code="out_of_range",
            message=f"months must be 1..36 (got {months!r}).",
            field="months",
        )
    months = int(months)
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_compliance_risk_score",
            "args": {"houjin_bangou": hb},
            "rationale": "trend で抜け落ちる単月コンプラ score を別 query で確認。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_houjin_360_snapshot"):
        return _empty_envelope(
            billing_unit=1,
            limit=months,
            offset=offset,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "months": months,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_houjin_360_snapshot (migration wave24_131) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_houjin_360_snapshot WHERE houjin_bangou = ?",
            (hb,),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        # Pull oldest→newest so the JSON-diff iteration walks forward;
        # we reverse for the response so latest sits at index 0.
        rows = conn.execute(
            """
            SELECT snapshot_month, payload_json, computed_at
              FROM am_houjin_360_snapshot
             WHERE houjin_bangou = ?
             ORDER BY snapshot_month ASC
             LIMIT ? OFFSET ?
            """,
            (hb, months, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_houjin_360_snapshot query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_houjin_360_snapshot query failed: {exc}",
        )

    decoded: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for r in rows:
        snap = _safe_json_loads(r["payload_json"])
        snap_dict = snap if isinstance(snap, dict) else {"raw": snap}
        delta = _delta_from_prev(snap_dict, prev)
        decoded.append(
            {
                "snapshot_month": r["snapshot_month"],
                "snapshot": snap_dict,
                "delta_from_prev": delta,
                "computed_at": r["computed_at"],
            }
        )
        prev = snap_dict

    # Newest first for the consumer response.
    decoded.reverse()

    return _finalize(
        {
            "houjin_bangou": hb,
            "months": months,
            "results": decoded,
            "total": total,
            "limit": months,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #103 get_tax_amendment_cycle
# ---------------------------------------------------------------------------


def _get_tax_amendment_cycle_impl(
    tax_ruleset_id: int | str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the amendment history + cycle stats for a tax ruleset.

    `cycle_stats` is computed in Python from the gap (in days) between
    consecutive `effective_from` dates so the customer LLM does not need
    to do the calendar arithmetic.
    """
    if tax_ruleset_id is None or tax_ruleset_id == "":
        return make_error(
            code="missing_required_arg",
            message="tax_ruleset_id is required.",
            field="tax_ruleset_id",
        )
    try:
        rsid: int | str = int(tax_ruleset_id)
    except (TypeError, ValueError):
        rsid = str(tax_ruleset_id)
    limit = max(1, min(int(limit or 20), 200))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "simulate_tax_change_impact",
            "args": {"tax_ruleset_id": rsid},
            "rationale": "改正サイクル把握 → 影響額試算へ。",
            "estimated_units": 2,
        },
    ]

    if not _table_exists(conn, "am_tax_amendment_history"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "tax_ruleset_id": rsid,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_tax_amendment_history (migration wave24_132) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_tax_amendment_history WHERE tax_ruleset_id = ?",
            (rsid,),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            """
            SELECT amendment_id, effective_from, change_kind,
                   summary_ja, source_url, computed_at
              FROM am_tax_amendment_history
             WHERE tax_ruleset_id = ?
             ORDER BY effective_from ASC
             LIMIT ? OFFSET ?
            """,
            (rsid, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_tax_amendment_history query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_tax_amendment_history query failed: {exc}",
        )

    results: list[dict[str, Any]] = []
    gaps_days: list[int] = []
    prev_date: datetime.date | None = None
    for r in rows:
        eff = r["effective_from"]
        eff_date: datetime.date | None = None
        if isinstance(eff, str) and eff:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                try:
                    eff_date = datetime.datetime.strptime(eff[:10], fmt).date()
                    break
                except ValueError:
                    continue
        gap_days: int | None = None
        if eff_date and prev_date:
            gap_days = (eff_date - prev_date).days
            if gap_days >= 0:
                gaps_days.append(gap_days)
        results.append(
            {
                "amendment_id": r["amendment_id"],
                "effective_from": eff,
                "change_kind": r["change_kind"],
                "summary_ja": r["summary_ja"],
                "source_url": r["source_url"],
                "gap_from_prev_days": gap_days,
                "computed_at": r["computed_at"],
            }
        )
        if eff_date:
            prev_date = eff_date

    cycle_stats: dict[str, Any] = {
        "n_amendments": len(results),
        "n_gaps_observed": len(gaps_days),
    }
    if gaps_days:
        cycle_stats.update(
            {
                "min_gap_days": min(gaps_days),
                "max_gap_days": max(gaps_days),
                "mean_gap_days": round(sum(gaps_days) / len(gaps_days), 1),
                "median_gap_days": sorted(gaps_days)[len(gaps_days) // 2],
            }
        )

    return _finalize(
        {
            "tax_ruleset_id": rsid,
            "results": results,
            "cycle_stats": cycle_stats,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #104 infer_invoice_buyer_seller
# ---------------------------------------------------------------------------


def _infer_invoice_buyer_seller_impl(
    houjin_bangou: str,
    direction: str = "both",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return inferred trading partners from `am_invoice_buyer_seller_graph`.

    The CHECK on the table is `seller != buyer`. `direction` may be
    'seller' (= the input is selling), 'buyer' (= the input is buying),
    or 'both'.
    """
    if not houjin_bangou:
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not _is_valid_houjin(hb):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if direction not in ("seller", "buyer", "both"):
        return make_error(
            code="invalid_enum",
            message=f"direction must be one of seller/buyer/both (got {direction!r}).",
            field="direction",
        )
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_houjin_360_snapshot_history",
            "args": {"houjin_bangou": "<results[0].partner_houjin>"},
            "rationale": "推測取引相手を 360 view で確認。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_invoice_buyer_seller_graph"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "direction": direction,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_invoice_buyer_seller_graph (migration wave24_133) "
                        "not yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    union_blocks: list[str] = []
    params_count: list[Any] = []
    params_select: list[Any] = []

    if direction in ("seller", "both"):
        # input is seller -> partner is buyer
        union_blocks.append(
            "SELECT buyer_houjin_bangou AS partner_houjin, 'buyer' AS partner_role, "
            "evidence_kind, confidence, source_url_json AS evidence_json, computed_at "
            "FROM am_invoice_buyer_seller_graph WHERE seller_houjin_bangou = ?"
        )
        params_count.append(hb)
        params_select.append(hb)
    if direction in ("buyer", "both"):
        # input is buyer -> partner is seller
        union_blocks.append(
            "SELECT seller_houjin_bangou AS partner_houjin, 'seller' AS partner_role, "
            "evidence_kind, confidence, source_url_json AS evidence_json, computed_at "
            "FROM am_invoice_buyer_seller_graph WHERE buyer_houjin_bangou = ?"
        )
        params_count.append(hb)
        params_select.append(hb)

    union_sql = " UNION ALL ".join(union_blocks)

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM ({union_sql})",
            tuple(params_count),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT partner_houjin, partner_role, evidence_kind,
                   confidence, evidence_json, computed_at
              FROM ({union_sql})
             ORDER BY confidence DESC, partner_houjin
             LIMIT ? OFFSET ?
            """,
            (*params_select, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_invoice_buyer_seller_graph query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_invoice_buyer_seller_graph query failed: {exc}",
        )

    # Schema (migration wave24_133): seller_houjin_bangou / buyer_houjin_bangou
    # / confidence / confidence_band / inferred_industry / evidence_kind
    # / evidence_count / source_url_json (JSON list of citations) / first_seen_at
    # / last_seen_at / computed_at. The SELECT aliases source_url_json AS
    # evidence_json so the row mapping below pulls a decoded JSON list of
    # citation URLs, NOT a single string.
    results = [
        {
            "partner_houjin": r["partner_houjin"],
            "partner_role": r["partner_role"],
            "evidence_kind": r["evidence_kind"],
            "confidence": r["confidence"],
            "evidence_urls": _safe_json_loads(r["evidence_json"]),
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "houjin_bangou": hb,
            "direction": direction,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #105 match_programs_by_capital
# ---------------------------------------------------------------------------


def _match_programs_by_capital_impl(
    capital_yen: int,
    jsic_major: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Map capital_yen → band → SELECT from `am_capital_band_program_match`."""
    if capital_yen is None:
        return make_error(
            code="missing_required_arg",
            message="capital_yen is required (integer JPY, ≥ 0).",
            field="capital_yen",
        )
    try:
        cyen = int(capital_yen)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_enum",
            message=f"capital_yen must be an integer (got {capital_yen!r}).",
            field="capital_yen",
        )
    if cyen < 0 or cyen > 100_000_000_000_000:  # ¥100 兆 sanity cap
        return make_error(
            code="out_of_range",
            message=f"capital_yen out of range (got {cyen}).",
            field="capital_yen",
        )
    band = _capital_band_for_yen(cyen)
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_adoption_stats",
            "args": {"program_id": "<results[0].program_id>"},
            "rationale": "band 一致 program について採択統計を確認。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_capital_band_program_match"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "capital_yen": cyen,
                "capital_band": band,
                "jsic_major": jsic_major,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_capital_band_program_match (migration wave24_134) "
                        "not yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    # `am_capital_band_program_match` (migration wave24_134) does NOT
    # carry `jsic_major` and stores amounts as `avg_amount_man_yen`
    # (万円). Earlier versions of this tool SELECTed `jsic_major` /
    # `avg_amount_yen` and 100 % crashed with `no such column`. We
    # gate the optional `jsic_major` filter via _column_exists so a
    # future schema bump (e.g. adding `jsic_major`) re-activates it
    # without code changes, and we expose the 万円 amount as
    # `avg_amount_yen` (× 10_000) for caller stability.
    has_jsic = _column_exists(conn, "am_capital_band_program_match", "jsic_major")
    where_clauses = ["capital_band = ?"]
    params: list[Any] = [band]
    jsic_filter_dropped = False
    if jsic_major:
        if has_jsic:
            where_clauses.append("jsic_major = ?")
            params.append(str(jsic_major).strip().upper()[:1])
        else:
            jsic_filter_dropped = True
    where_sql = " AND ".join(where_clauses)
    select_jsic = "jsic_major" if has_jsic else "NULL AS jsic_major"

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM am_capital_band_program_match WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT program_unified_id AS program_id, {select_jsic}, capital_band,
                   adoption_count, adoption_rate,
                   avg_amount_man_yen,
                   percentile_in_band, sample_size, computed_at
              FROM am_capital_band_program_match
             WHERE {where_sql}
             ORDER BY adoption_rate DESC, adoption_count DESC
             LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_capital_band_program_match query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_capital_band_program_match query failed: {exc}",
        )

    results = []
    for r in rows:
        man_yen = r["avg_amount_man_yen"]
        avg_amount_yen = int(round(float(man_yen) * 10_000)) if man_yen is not None else None
        results.append(
            {
                "program_id": r["program_id"],
                "jsic_major": r["jsic_major"],
                "capital_band": r["capital_band"],
                "adoption_count": r["adoption_count"],
                "adoption_rate": r["adoption_rate"],
                "avg_amount_man_yen": man_yen,
                "avg_amount_yen": avg_amount_yen,
                "percentile_in_band": r["percentile_in_band"],
                "sample_size": r["sample_size"],
                "computed_at": r["computed_at"],
            }
        )

    payload: dict[str, Any] = {
        "capital_yen": cyen,
        "capital_band": band,
        "jsic_major": jsic_major,
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
        "_billing_unit": 1,
        "_next_calls": next_calls,
    }
    if jsic_filter_dropped:
        payload["data_quality"] = {
            "jsic_filter_applied": False,
            "caveat": (
                "am_capital_band_program_match has no jsic_major column "
                "in this DB; jsic_major filter ignored."
            ),
        }
    return _finalize(payload)


# ---------------------------------------------------------------------------
# #106 get_program_adoption_stats
# ---------------------------------------------------------------------------


def _get_program_adoption_stats_impl(
    program_id: str,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Return per-FY adoption stats for a program.

    `industry_distribution` is JSON-decoded so the customer LLM can read
    it directly.
    """
    if not program_id:
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    program_id = _to_unified(program_id)
    limit = max(1, min(int(limit or 10), 50))
    offset = max(0, int(offset or 0))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_adopted_companies_by_program",
            "args": {"program_id": program_id},
            "rationale": "統計の裏付けに採択企業 list を引く。",
            "estimated_units": 1,
        },
    ]

    if not _table_exists(conn, "am_program_adoption_stats"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "program_id": program_id,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_program_adoption_stats (migration wave24_135) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_program_adoption_stats WHERE program_unified_id = ?",
            (program_id,),
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            """
            SELECT fiscal_year, adoption_count, application_count,
                   success_rate, avg_amount_yen, total_amount_yen,
                   industry_distribution_json, region_distribution_json,
                   computed_at
              FROM am_program_adoption_stats
             WHERE program_unified_id = ?
             ORDER BY fiscal_year DESC
             LIMIT ? OFFSET ?
            """,
            (program_id, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_program_adoption_stats query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_program_adoption_stats query failed: {exc}",
        )

    results = [
        {
            "fiscal_year": r["fiscal_year"],
            "adoption_count": r["adoption_count"],
            "application_count": r["application_count"],
            "success_rate": r["success_rate"],
            "avg_amount_yen": r["avg_amount_yen"],
            "total_amount_yen": r["total_amount_yen"],
            "industry_distribution": _safe_json_loads(r["industry_distribution_json"]),
            "region_distribution": _safe_json_loads(r["region_distribution_json"]),
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]

    return _finalize(
        {
            "program_id": program_id,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #107 get_program_narrative
# ---------------------------------------------------------------------------

_NARRATIVE_SECTIONS = ("overview", "eligibility", "application_flow", "pitfalls")


def _get_program_narrative_impl(
    program_id: str,
    section: str = "all",
    lang: str = "ja",
    reading_level: Literal["standard", "plain"] = "standard",
) -> dict[str, Any]:
    """Return the pre-computed narrative for a program.

    `section='all'` returns up to 4 rows (overview / eligibility /
    application_flow / pitfalls); a specific section returns a single
    row. Pre-generation lives in the operator-side Claude Code subagent
    batch (§10.6) — this tool only SELECTs.

    `reading_level='plain'` (W3-12 UC7 LINE 中小企業向け) post-processes
    `body_text` through a rule-based 平易日本語 dictionary
    (`ingest.plain_japanese_dict`). NO LLM call — pure str.replace per
    `feedback_no_operator_llm_api`. The chosen level is echoed back as
    `_reading_level` on the envelope for client introspection.
    """
    if not program_id:
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    if section not in (*_NARRATIVE_SECTIONS, "all"):
        return make_error(
            code="invalid_enum",
            message=(
                f"section must be one of "
                f"{'/'.join((*_NARRATIVE_SECTIONS, 'all'))} (got {section!r})."
            ),
            field="section",
        )
    if lang not in ("ja", "en"):
        return make_error(
            code="invalid_enum",
            message=f"lang must be one of ja/en (got {lang!r}).",
            field="lang",
        )
    if reading_level not in ("standard", "plain"):
        return make_error(
            code="invalid_enum",
            message=(f"reading_level must be one of standard/plain (got {reading_level!r})."),
            field="reading_level",
        )
    # Plain-Japanese substitution dict targets ja text only — applying
    # it to en bodies would be a no-op at best and a corruption at
    # worst. Reject the combination explicitly.
    if reading_level == "plain" and lang != "ja":
        return make_error(
            code="invalid_enum",
            message=(
                f"reading_level='plain' is only supported with lang='ja' (got lang={lang!r})."
            ),
            field="reading_level",
        )
    program_id = _to_unified(program_id)

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_application_documents",
            "args": {"program_id": program_id},
            "rationale": "解説 → 必要書類 list へ。",
            "estimated_units": 1,
        },
    ]

    # ------------------------------------------------------------------
    # W20 fast-path: am_program_narrative_full (migration wave24_149).
    # Pre-rendered ONE coherent prose body + 反駁 bank, keyed
    # program_id PRIMARY KEY. We consult this cache FIRST when the
    # caller asks for the default surface (lang='ja', section='all',
    # reading_level='standard'). 'plain' reading level + 'en' lang +
    # specific-section requests bypass the W20 cache and fall through
    # to the existing 4-section path. See migration 149 header for the
    # schema-split rationale.
    # ------------------------------------------------------------------
    if (
        lang == "ja"
        and section == "all"
        and reading_level == "standard"
        and _table_exists(conn, "am_program_narrative_full")
    ):
        try:
            cache_row = conn.execute(
                """
                SELECT narrative_md, counter_arguments_md, generated_at,
                       model_used, content_hash,
                       source_program_corpus_snapshot_id
                  FROM am_program_narrative_full
                 WHERE program_id = ?
                """,
                (program_id,),
            ).fetchone()
        except sqlite3.Error:
            cache_row = None
        if cache_row and cache_row["narrative_md"]:
            return _finalize(
                {
                    "program_id": program_id,
                    "section": section,
                    "lang": lang,
                    "reading_level": reading_level,
                    "narrative_full": {
                        "narrative_md": cache_row["narrative_md"],
                        "counter_arguments_md": cache_row["counter_arguments_md"],
                        "generated_at": cache_row["generated_at"],
                        "model_used": cache_row["model_used"],
                        "content_hash": cache_row["content_hash"],
                        "source_program_corpus_snapshot_id": cache_row[
                            "source_program_corpus_snapshot_id"
                        ],
                    },
                    # Keep the legacy `results` array shape so existing
                    # clients that iterate it don't break — empty list when
                    # the W20 cache is the only surface, and the four-
                    # section path (below) is bypassed.
                    "results": [],
                    "total": 0,
                    "limit": 4,
                    "offset": 0,
                    "_billing_unit": 1,
                    "_cache_hit": True,
                    "_cache_source": "am_program_narrative_full",
                    "_reading_level": reading_level,
                    "_next_calls": next_calls,
                }
            )

    if not _table_exists(conn, "am_program_narrative"):
        return _empty_envelope(
            billing_unit=1,
            limit=4 if section == "all" else 1,
            offset=0,
            next_calls=next_calls,
            extra={
                "program_id": program_id,
                "section": section,
                "lang": lang,
                "reading_level": reading_level,
                "_reading_level": reading_level,
                "data_quality": {
                    "table_present": False,
                    "caveat": (
                        "am_program_narrative (migration wave24_136) not "
                        "yet applied; degrading to empty envelope."
                    ),
                },
            },
        )

    # Schema (wave24_136 + wave24_141 ALTER):
    #   body_text / source_url_json / generated_at / model_id /
    #   literal_quote_check_passed / is_active / quarantine_id / content_hash.
    # `content_md` / `computed_at` / `source_url` columns do NOT exist —
    # earlier draft of this impl referenced them and 100%-broke the tool
    # (`db_unavailable: no such column: content_md`). See W3-12 launch
    # blocker (UC3/UC4/UC7).
    try:
        if section == "all":
            placeholders = ",".join("?" for _ in _NARRATIVE_SECTIONS)
            rows = conn.execute(
                f"""
                SELECT section, lang, body_text, content_hash,
                       is_active, generated_at, source_url_json,
                       model_id, literal_quote_check_passed
                  FROM am_program_narrative
                 WHERE program_id = ?
                   AND lang = ?
                   AND section IN ({placeholders})
                   AND COALESCE(is_active, 1) = 1
                 ORDER BY CASE section
                            WHEN 'overview' THEN 0
                            WHEN 'eligibility' THEN 1
                            WHEN 'application_flow' THEN 2
                            WHEN 'pitfalls' THEN 3
                            ELSE 99
                          END
                """,
                (program_id, lang, *_NARRATIVE_SECTIONS),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT section, lang, body_text, content_hash,
                       is_active, generated_at, source_url_json,
                       model_id, literal_quote_check_passed
                  FROM am_program_narrative
                 WHERE program_id = ?
                   AND lang = ?
                   AND section = ?
                   AND COALESCE(is_active, 1) = 1
                """,
                (program_id, lang, section),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("am_program_narrative query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_program_narrative query failed: {exc}",
        )

    def _format_body(raw: str | None) -> str:
        # Rule-based 平易日本語 substitution (jpcite service-side LLM
        # call禁止 — `feedback_no_operator_llm_api`). 'standard' is the
        # untouched corpus body.
        if reading_level == "plain":
            return replace_plain_japanese(raw)
        return raw or ""

    results = [
        {
            "section": r["section"],
            "lang": r["lang"],
            "body_text": _format_body(r["body_text"]),
            "content_hash": r["content_hash"],
            "is_active": bool(r["is_active"]) if r["is_active"] is not None else True,
            "source_url_json": _safe_json_loads(r["source_url_json"]),
            "generated_at": r["generated_at"],
            "model_id": r["model_id"],
            "literal_quote_check_passed": bool(r["literal_quote_check_passed"])
            if r["literal_quote_check_passed"] is not None
            else False,
        }
        for r in rows
    ]

    return _finalize(
        {
            "program_id": program_id,
            "section": section,
            "lang": lang,
            "reading_level": reading_level,
            "results": results,
            "total": len(results),
            "limit": 4 if section == "all" else 1,
            "offset": 0,
            "_billing_unit": 1,
            "_reading_level": reading_level,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #108 predict_rd_tax_credit
# ---------------------------------------------------------------------------


def _predict_rd_tax_credit_impl(
    houjin_bangou: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """JOIN `am_houjin_360_snapshot` × `am_tax_amendment_history` for 措置法 §42-4.

    Pure Python computation:
      * pull the latest snapshot for the houjin in the requested FY
      * pull the latest amendment for the §42-4 ruleset preceding the FY
      * compute estimated credit = `rd_expense_yen` × `headline_rate`
      * return a heuristic envelope with caveats; this is NOT 税務助言
    """
    if not houjin_bangou:
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not _is_valid_houjin(hb):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if fiscal_year is None:
        # Default to JST fiscal year of "today" (April-March).
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
        fy = today.year if today.month >= 4 else today.year - 1
    else:
        try:
            fy = int(fiscal_year)
        except (TypeError, ValueError):
            return make_error(
                code="invalid_enum",
                message=f"fiscal_year must be an integer (got {fiscal_year!r}).",
                field="fiscal_year",
            )
        if fy < 2000 or fy > 2100:
            return make_error(
                code="out_of_range",
                message=f"fiscal_year out of range 2000..2100 (got {fy}).",
                field="fiscal_year",
            )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_tax_amendment_cycle",
            "args": {"tax_ruleset_id": "<resolved>"},
            "rationale": "計算前提 ruleset の改正サイクルを照合。",
            "estimated_units": 1,
        },
    ]

    snapshot_present = _table_exists(conn, "am_houjin_360_snapshot")
    amendment_present = _table_exists(conn, "am_tax_amendment_history")

    if not snapshot_present and not amendment_present:
        return _empty_envelope(
            billing_unit=2,
            limit=1,
            offset=0,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "fiscal_year": fy,
                "data_quality": {
                    "snapshot_table_present": snapshot_present,
                    "amendment_table_present": amendment_present,
                    "caveat": (
                        "am_houjin_360_snapshot + am_tax_amendment_history "
                        "(migrations wave24_131 / wave24_132) not yet applied;"
                        " degrading to empty envelope."
                    ),
                },
            },
        )

    # ------------------------------------------------------------------
    # 1) Pull the latest snapshot in or before the FY (Mar of FY+1).
    # ------------------------------------------------------------------
    fy_end_month = f"{fy + 1:04d}-03"
    rd_expense_yen: float | None = None
    snapshot_month: str | None = None
    snapshot_payload: dict[str, Any] | None = None
    if snapshot_present:
        try:
            row = conn.execute(
                """
                SELECT snapshot_month, payload_json
                  FROM am_houjin_360_snapshot
                 WHERE houjin_bangou = ?
                   AND snapshot_month <= ?
                 ORDER BY snapshot_month DESC
                 LIMIT 1
                """,
                (hb, fy_end_month),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            snapshot_month = row["snapshot_month"]
            snap = _safe_json_loads(row["payload_json"])
            if isinstance(snap, dict):
                snapshot_payload = snap
                # Try several common key names.
                for key in ("rd_expense_yen", "research_expense_yen", "rd_expense"):
                    val = snap.get(key)
                    if isinstance(val, (int, float)):
                        rd_expense_yen = float(val)
                        break

    # ------------------------------------------------------------------
    # 2) Pull the latest amendment for tax_ruleset_id matching §42-4.
    # ------------------------------------------------------------------
    headline_rate: float | None = None
    amendment_id: int | str | None = None
    amendment_effective_from: str | None = None
    ruleset_resolved: int | str | None = None
    if amendment_present:
        try:
            # Resolve ruleset id by name match against jpi_tax_rulesets when
            # available; otherwise leave None and pull the latest history row
            # carrying a 措置法 §42-4 mention in summary_ja.
            if _table_exists(conn, "jpi_tax_rulesets"):
                rs_row = conn.execute(
                    """
                    SELECT id
                      FROM jpi_tax_rulesets
                     WHERE name LIKE '%42-4%'
                        OR name LIKE '%研究開発税制%'
                        OR short_name LIKE '%R&D%'
                     ORDER BY id ASC
                     LIMIT 1
                    """,
                ).fetchone()
                if rs_row:
                    ruleset_resolved = rs_row["id"]
            am_row = None
            if ruleset_resolved is not None:
                am_row = conn.execute(
                    """
                    SELECT amendment_id, effective_from, headline_rate, summary_ja
                      FROM am_tax_amendment_history
                     WHERE tax_ruleset_id = ?
                       AND effective_from <= ?
                     ORDER BY effective_from DESC
                     LIMIT 1
                    """,
                    (ruleset_resolved, f"{fy + 1:04d}-03-31"),
                ).fetchone()
            if am_row is None:
                am_row = conn.execute(
                    """
                    SELECT amendment_id, effective_from, headline_rate, summary_ja
                      FROM am_tax_amendment_history
                     WHERE (summary_ja LIKE '%42-4%'
                            OR summary_ja LIKE '%研究開発税制%')
                       AND effective_from <= ?
                     ORDER BY effective_from DESC
                     LIMIT 1
                    """,
                    (f"{fy + 1:04d}-03-31",),
                ).fetchone()
        except sqlite3.Error:
            am_row = None
        if am_row:
            amendment_id = am_row["amendment_id"]
            amendment_effective_from = am_row["effective_from"]
            try:
                headline_rate = (
                    float(am_row["headline_rate"]) if am_row["headline_rate"] is not None else None
                )
            except (TypeError, ValueError):
                headline_rate = None

    # ------------------------------------------------------------------
    # 3) Compute estimated credit.
    # ------------------------------------------------------------------
    estimated_credit_yen: float | None = None
    if rd_expense_yen is not None and headline_rate is not None:
        estimated_credit_yen = round(rd_expense_yen * headline_rate, 0)

    return _finalize(
        {
            "houjin_bangou": hb,
            "fiscal_year": fy,
            "results": [
                {
                    "estimated_credit_yen": estimated_credit_yen,
                    "rd_expense_yen": rd_expense_yen,
                    "headline_rate": headline_rate,
                    "snapshot_month": snapshot_month,
                    "amendment_id": amendment_id,
                    "amendment_effective_from": amendment_effective_from,
                    "ruleset_resolved_id": ruleset_resolved,
                }
            ],
            "total": 1 if estimated_credit_yen is not None else 0,
            "limit": 1,
            "offset": 0,
            "data_quality": {
                "snapshot_present": snapshot_present and snapshot_payload is not None,
                "amendment_present": amendment_present and headline_rate is not None,
                "caveat": (
                    "Heuristic estimate from rd_expense_yen × headline_rate "
                    "only — does NOT account for incremental / volume-based "
                    "split, group-relief, carry-forward, or the 14% cap. "
                    "税理士法 §52 — not 税務助言."
                ),
            },
            "_billing_unit": 2,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_WAVE24_FIRST_HALF_ENABLED +
# the global AUTONOMATH_ENABLED. Each docstring is ≤ 400 chars per the
# Wave 21/22 convention.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def recommend_programs_for_houjin(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="TOP-N to return (1..50). Default 10."),
        ] = 10,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#97] TOP-N recommended programs for a 法人 from am_recommended_programs (pre-computed via §10.3 ETL). Returns score + rank + decoded reason JSON. SENSITIVE — §52 / §72 fence; the LLM should treat the score as guidance, not a 採択 forecast."""
        return _recommend_programs_for_houjin_impl(
            houjin_bangou=houjin_bangou,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_combinable_programs(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        visibility: Annotated[
            str,
            Field(description="One of public/internal/all (default 'public')."),
        ] = "public",
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Page size (1..100). Default 20."),
        ] = 20,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#98] Combinable-program list from am_program_combinations. Both directions UNIONed under the (program_a < program_b) CHECK. visibility='public' (default) surfaces only sourced rows; 'internal' adds heuristic. SENSITIVE — §52/§1 fence — combinability is heuristic, not a promise."""
        return _find_combinable_programs_impl(
            program_id=program_id,
            visibility=visibility,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_calendar_12mo(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=24, description="Months returned (1..24). Default 12."),
        ] = 12,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#99] 12-month per-program calendar from am_program_calendar_12mo (pre-computed). Returns is_open + deadline + round_label per month. NOT sensitive — calendar facts. Use after recommend_programs_for_houjin or search_programs to time the application."""
        return _get_program_calendar_12mo_impl(
            program_id=program_id,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def forecast_enforcement_risk(
        jsic_major: Annotated[
            str | None,
            Field(
                description="JSIC major letter (A..T). One of jsic_major / region_code required."
            ),
        ] = None,
        region_code: Annotated[
            str | None,
            Field(description="5-digit JIS X 0401 / 0402 region code. Optional."),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Page size (1..100). Default 20."),
        ] = 20,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#100] enforcement × JSIC × region 横展開 risk from am_enforcement_industry_risk. propagation_probability is a 5-year statistical forecast, not a legal opinion. SENSITIVE — 弁護士法 §72 / 社労士法 §27. The customer LLM must surface the disclaimer envelope."""
        return _forecast_enforcement_risk_impl(
            jsic_major=jsic_major,
            region_code=region_code,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_similar_case_studies(
        case_id: Annotated[
            str,
            Field(description="Source case_id (採択事例 PK)."),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Number of similar cases to return (1..50). Default 5."),
        ] = 5,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#101] Top-N similar 採択事例 from am_case_study_similarity (pre-computed pairwise feature similarity, PK case_a < case_b — UNIONed both directions). NOT sensitive — facts about past adoptions, not advice. Use to find 'companies like mine' before drafting an application."""
        return _find_similar_case_studies_impl(
            case_id=case_id,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_houjin_360_snapshot_history(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        months: Annotated[
            int,
            Field(ge=1, le=36, description="Trailing months to return (1..36). Default 12."),
        ] = 12,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#102] Past N monthly snapshots (latest first) from am_houjin_360_snapshot, with per-row delta_from_prev computed by JSON diff in Python. SENSITIVE — 信用情報法 / 個人情報保護法 fence. NOT a credit / 反社 substitute; the LLM must surface the disclaimer envelope."""
        return _get_houjin_360_snapshot_history_impl(
            houjin_bangou=houjin_bangou,
            months=months,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_tax_amendment_cycle(
        tax_ruleset_id: Annotated[
            str,
            Field(description="Target tax_ruleset_id (integer or canonical-id string)."),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=200, description="Amendments returned (1..200). Default 20."),
        ] = 20,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#103] Per-ruleset amendment history from am_tax_amendment_history + cycle_stats (min/max/mean/median gap days, computed in Python). SENSITIVE — 税理士法 §52. The cycle is a past-tense pattern; future amendments are not guaranteed. Disclaimer auto-injected."""
        return _get_tax_amendment_cycle_impl(
            tax_ruleset_id=tax_ruleset_id,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def infer_invoice_buyer_seller(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        direction: Annotated[
            str,
            Field(description="One of seller/buyer/both (default 'both')."),
        ] = "both",
        limit: Annotated[
            int,
            Field(ge=1, le=500, description="Page size (1..500). Default 50."),
        ] = 50,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#104] Inferred trading partners from am_invoice_buyer_seller_graph. CHECK seller != buyer. direction filters which side the input plays. SENSITIVE — 信用情報法 / 個人情報保護法. Inferences are heuristic; not a substitute for credit checks."""
        return _infer_invoice_buyer_seller_impl(
            houjin_bangou=houjin_bangou,
            direction=direction,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def match_programs_by_capital(
        capital_yen: Annotated[
            int,
            Field(ge=0, description="Capital amount in JPY (≥ 0). Maps to a canonical band."),
        ],
        jsic_major: Annotated[
            str | None,
            Field(description="Optional JSIC major letter (A..T) for cross-filter."),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Page size (1..100). Default 20."),
        ] = 20,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#105] capital_yen → canonical band (lt_1m / 1m_10m / ... / gte_5b) → SELECT from am_capital_band_program_match. Optional jsic_major narrows. NOT sensitive — adoption stats by band are facts. Pair with score_application_probability for full read."""
        return _match_programs_by_capital_impl(
            capital_yen=capital_yen,
            jsic_major=jsic_major,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_adoption_stats(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Fiscal years to return (1..50). Default 10."),
        ] = 10,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset. Default 0."),
        ] = 0,
    ) -> dict[str, Any]:
        """[WAVE24-#106] Per-FY adoption stats (count / rate / avg amount / industry & region distribution JSON-decoded) from am_program_adoption_stats. NOT sensitive — facts. Pair with find_adopted_companies_by_program for the underlying corpus."""
        return _get_program_adoption_stats_impl(
            program_id=program_id,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_narrative(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        section: Annotated[
            str,
            Field(
                description="One of overview/eligibility/application_flow/pitfalls/all. Default 'all'."
            ),
        ] = "all",
        lang: Annotated[
            str,
            Field(description="One of ja/en. Default 'ja'."),
        ] = "ja",
        reading_level: Annotated[
            Literal["standard", "plain"],
            Field(
                description="'standard' = corpus untouched; 'plain' applies a rule-based 平易日本語 dictionary (LINE 中小企業向け, lang='ja' only). Default 'standard'."
            ),
        ] = "standard",
    ) -> dict[str, Any]:
        """[WAVE24-#107] Pre-computed program narrative from am_program_narrative (operator-side Claude Code subagent batch §10.6 — NOT generated here). section='all' returns up to 4 rows; specific section returns 1. reading_level='plain' post-processes body_text via rule-based dict (jpcite LLM call禁止). SENSITIVE — 行政書士法 §1 + LLM 由来明示 — not 申請代理."""
        return _get_program_narrative_impl(
            program_id=program_id,
            section=section,
            lang=lang,
            reading_level=reading_level,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def predict_rd_tax_credit(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        fiscal_year: Annotated[
            int | None,
            Field(description="Target FY (April-March). Default = current FY."),
        ] = None,
    ) -> dict[str, Any]:
        """[WAVE24-#108] 措置法 §42-4 R&D tax credit estimate from am_houjin_360_snapshot (rd_expense_yen) × am_tax_amendment_history (headline_rate). Pure Python multiplication. billing_unit=2 (compound). SENSITIVE — 税理士法 §52. Heuristic — does NOT model incremental / volume split / 14% cap."""
        return _predict_rd_tax_credit_impl(
            houjin_bangou=houjin_bangou,
            fiscal_year=fiscal_year,
        )

    # ----- Registration export for the W1-18 server.py wiring -------------
    WAVE24_TOOLS_FIRST_HALF: list[Any] = [
        recommend_programs_for_houjin,
        find_combinable_programs,
        get_program_calendar_12mo,
        forecast_enforcement_risk,
        find_similar_case_studies,
        get_houjin_360_snapshot_history,
        get_tax_amendment_cycle,
        infer_invoice_buyer_seller,
        match_programs_by_capital,
        get_program_adoption_stats,
        get_program_narrative,
        predict_rd_tax_credit,
    ]
else:
    # When the gate is off (or autonomath_enabled is False) the MCP
    # decorator never runs, so the public symbols above don't exist.
    # Export a stable empty list so import-time `from … import
    # WAVE24_TOOLS_FIRST_HALF` still works in the server.py wiring path.
    WAVE24_TOOLS_FIRST_HALF: list[Any] = []  # type: ignore[no-redef]


__all__ = [
    "WAVE24_TOOLS_FIRST_HALF",
    # Pure-impl helpers (importable for unit tests / fallback REST routes).
    "_recommend_programs_for_houjin_impl",
    "_find_combinable_programs_impl",
    "_get_program_calendar_12mo_impl",
    "_forecast_enforcement_risk_impl",
    "_find_similar_case_studies_impl",
    "_get_houjin_360_snapshot_history_impl",
    "_get_tax_amendment_cycle_impl",
    "_infer_invoice_buyer_seller_impl",
    "_match_programs_by_capital_impl",
    "_get_program_adoption_stats_impl",
    "_get_program_narrative_impl",
    "_predict_rd_tax_credit_impl",
    "_capital_band_for_yen",
]


# Silence unused-import warnings for `hashlib` (kept for parity with the
# sibling wave22_tools.py snapshot helpers; the second-half file may
# reuse it for corpus_checksum).
_ = hashlib
