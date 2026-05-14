"""POST /v1/intel/diff — composite entity-comparison endpoint (M&A due diligence).

Single-call envelope that runs a structured diff between two entities of
compatible kinds (program × program, houjin × houjin, law × law). The
customer LLM hands us ``{a: {type, id}, b: {type, id}, depth}`` and we
return:

* ``shared_attrs``     — fields where both sides carry the same value.
* ``unique_to_a``      — fields populated on A but missing/null on B.
* ``unique_to_b``      — fields populated on B but missing/null on A.
* ``conflict_points``  — fields populated on BOTH sides with DIVERGENT
  values + a short ``reason`` (data-source / namespace / kind axis).

Cross-source axes used to derive the diff:

* ``programs`` / ``houjin_master`` / ``am_law_article`` — primary attrs.
* ``am_5hop_graph`` — 1..depth-hop neighbourhood diff (depth ∈ {1, 2, 3}).
* ``am_program_eligibility_predicate`` — predicate-set diff for
  program × program comparisons (capital_max / employee_max / region_in
  etc.).
* ``am_id_bridge`` — cross-namespace id resolution so callers can pass
  jpintel UNI-* canonical ids OR autonomath-side ``program:`` /
  ``certification:`` / ``loan:`` ids interchangeably.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python set
  arithmetic.
* The diff is purely descriptive ("A has X, B doesn't"). It does NOT
  emit recommendations. Auditor + M&A consumers wrap it themselves with
  their own due-diligence framework — same posture as the other
  ``/v1/intel/*`` composites.

Graceful degradation
--------------------
When a downstream table is missing in a fresh dev DB (e.g. the wave24
materialised views never populated), the corresponding axis silently
returns the empty list and ``data_quality.missing_tables`` accumulates
the table name — the customer LLM gets a partial-but-honest envelope
rather than a 500.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_diff")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


_DIFF_DISCLAIMER = (
    "本 /v1/intel/diff の出力は jpcite corpus に対する **記述的 (descriptive) "
    "差分** であり、M&A デューデリジェンス・与信判断・採択可能性予測などの最終"
    "判断を代替するものではありません。conflict_points は同一フィールドに対する "
    "**データソースまたは namespace の不一致** を機械的に検出した結果であり、"
    "「どちらが正しいか」は判定していません。確定判断 (税理士法 §52 / 弁護士法 §72 "
    "/ 行政書士法 §1の2 / 司法書士法 §3 / 公認会計士法 §47条の2) は資格を有する士業へ。"
)


# Allowed entity kinds. ``law`` and ``program`` are accepted as aliases that
# map onto the same downstream axis (programs/laws live in jpintel.db,
# houjin_master in jpintel.db, am_law_article + am_5hop_graph in
# autonomath.db).
EntityKind = Literal["program", "houjin", "law"]


class EntityRef(BaseModel):
    """One side of the diff."""

    type: EntityKind = Field(
        ...,
        description=(
            "Entity kind. ``program`` matches jpintel.db ``programs``; "
            "``houjin`` matches jpintel.db ``houjin_master`` (13-digit 法人番号); "
            "``law`` matches autonomath.db ``am_law_article`` keyed by "
            "law_canonical_id."
        ),
    )
    id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Canonical identifier for the entity. Programs accept "
            "UNI-* / program:* / certification:* (resolved via am_id_bridge); "
            "houjin accepts the 13-digit NTA 法人番号 (T-prefix stripped); "
            "law accepts a law_canonical_id (e.g. 'law:houjinzeiho')."
        ),
    )


class IntelDiffRequest(BaseModel):
    """POST body for /v1/intel/diff."""

    a: EntityRef = Field(..., description="Left side of the diff.")
    b: EntityRef = Field(..., description="Right side of the diff.")
    depth: int = Field(
        2,
        ge=1,
        le=3,
        description=(
            "Neighbourhood depth (1..3) for the am_5hop_graph axis. "
            "Higher depth surfaces more shared / unique edges but the "
            "row count grows ~O(degree^depth). 2 is the right default."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _normalize_houjin(value: str) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix)."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _resolve_am_id(am_conn: sqlite3.Connection | None, raw_id: str) -> list[str]:
    """Return a list of candidate canonical ids (raw_id first, then bridges).

    Used by the am_5hop_graph axis so that callers passing a jpintel
    UNI-* id and callers passing an autonomath-side ``program:*`` id
    both resolve to the same neighbourhood. Missing am_id_bridge degrades
    to ``[raw_id]`` so the call still succeeds.
    """
    candidates: list[str] = [raw_id]
    if am_conn is None or not raw_id:
        return candidates
    if not _table_exists(am_conn, "am_id_bridge"):
        return candidates
    try:
        rows = am_conn.execute(
            "SELECT id_b FROM am_id_bridge WHERE id_a = ? "
            "UNION SELECT id_a FROM am_id_bridge WHERE id_b = ?",
            (raw_id, raw_id),
        ).fetchall()
    except sqlite3.Error:
        return candidates
    for r in rows:
        cand = r[0] if not isinstance(r, sqlite3.Row) else r["id_b"]
        if isinstance(cand, str) and cand and cand not in candidates:
            candidates.append(cand)
    return candidates


# ---------------------------------------------------------------------------
# Per-kind primary attribute fetchers
# ---------------------------------------------------------------------------


def _fetch_program_attrs(
    conn: sqlite3.Connection,
    pid: str,
    *,
    missing_tables: list[str],
) -> dict[str, Any] | None:
    """Pull canonical program attributes from jpintel.db ``programs``."""
    if not _table_exists(conn, "programs"):
        missing_tables.append("programs")
        return None
    try:
        row = conn.execute(
            "SELECT unified_id, primary_name, tier, prefecture, "
            "       authority_level, authority_name, program_kind, "
            "       amount_max_man_yen, amount_min_man_yen, subsidy_rate "
            "  FROM programs WHERE unified_id = ? LIMIT 1",
            (pid,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("programs lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return dict(row)


def _fetch_houjin_attrs(
    conn: sqlite3.Connection,
    hb: str,
    *,
    missing_tables: list[str],
) -> dict[str, Any] | None:
    """Pull canonical 法人 attributes from jpintel.db ``houjin_master``."""
    if not _table_exists(conn, "houjin_master"):
        missing_tables.append("houjin_master")
        return None
    try:
        row = conn.execute(
            "SELECT houjin_bangou, normalized_name, prefecture, "
            "       municipality, corporation_type, established_date, "
            "       close_date, total_adoptions, total_received_yen "
            "  FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
            (hb,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("houjin_master lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return dict(row)


def _fetch_law_attrs(
    am_conn: sqlite3.Connection | None,
    lid: str,
    *,
    missing_tables: list[str],
) -> dict[str, Any] | None:
    """Pull canonical law-article attributes from autonomath.db ``am_law_article``.

    Aggregates per-article rows under one law_canonical_id into a single
    summary record (article_count + earliest effective_from + latest
    last_amended) so the diff has a meaningful row to compare on the law
    axis without having to fan out per article.
    """
    if am_conn is None:
        missing_tables.append("am_law_article")
        return None
    if not _table_exists(am_conn, "am_law_article"):
        missing_tables.append("am_law_article")
        return None
    try:
        row = am_conn.execute(
            "SELECT law_canonical_id, "
            "       COUNT(*) AS article_count, "
            "       MIN(effective_from) AS earliest_effective_from, "
            "       MAX(last_amended) AS latest_last_amended, "
            "       MIN(source_url) AS sample_source_url "
            "  FROM am_law_article WHERE law_canonical_id = ? "
            " GROUP BY law_canonical_id LIMIT 1",
            (lid,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_law_article lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return dict(row)


def _fetch_primary_attrs(
    *,
    kind: str,
    raw_id: str,
    conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    missing_tables: list[str],
) -> dict[str, Any] | None:
    if kind == "program":
        return _fetch_program_attrs(conn, raw_id, missing_tables=missing_tables)
    if kind == "houjin":
        return _fetch_houjin_attrs(conn, _normalize_houjin(raw_id), missing_tables=missing_tables)
    if kind == "law":
        return _fetch_law_attrs(am_conn, raw_id, missing_tables=missing_tables)
    return None


# ---------------------------------------------------------------------------
# Cross-axis diff helpers (graph + predicate)
# ---------------------------------------------------------------------------


def _fetch_5hop_neighbours(
    am_conn: sqlite3.Connection | None,
    seed_ids: list[str],
    *,
    depth: int,
    missing_tables: list[str],
) -> set[str]:
    """Return the set of end_entity_id within `depth` hops of any seed.

    Pure SELECT against the wave24 materialised graph; no recursive CTE.
    Empty set when the table is missing or no seed has any neighbour.
    """
    if am_conn is None or not seed_ids:
        return set()
    if not _table_exists(am_conn, "am_5hop_graph"):
        missing_tables.append("am_5hop_graph")
        return set()
    placeholders = ",".join("?" * len(seed_ids))
    try:
        rows = am_conn.execute(
            f"SELECT DISTINCT end_entity_id FROM am_5hop_graph "
            f"WHERE start_entity_id IN ({placeholders}) AND hop <= ?",  # noqa: S608
            (*seed_ids, int(depth)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_5hop_graph fan-out failed: %s", exc)
        return set()
    out: set[str] = set()
    for r in rows:
        val = r[0] if not isinstance(r, sqlite3.Row) else r["end_entity_id"]
        if isinstance(val, str) and val:
            out.add(val)
    return out


def _fetch_predicate_set(
    am_conn: sqlite3.Connection | None,
    program_id: str,
    *,
    missing_tables: list[str],
) -> dict[tuple[str, str], Any]:
    """Return ``{(predicate_kind, operator): value_repr}`` for the program.

    Used only for program × program diffs. value_repr collapses
    value_text / value_num / value_json into a single comparable tuple
    so set-difference + conflict detection work without per-kind logic.
    """
    if am_conn is None or not program_id:
        return {}
    if not _table_exists(am_conn, "am_program_eligibility_predicate"):
        missing_tables.append("am_program_eligibility_predicate")
        return {}
    try:
        rows = am_conn.execute(
            "SELECT predicate_kind, operator, value_text, value_num, value_json "
            "  FROM am_program_eligibility_predicate "
            " WHERE program_unified_id = ?",
            (program_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_eligibility_predicate fetch failed: %s", exc)
        return {}
    out: dict[tuple[str, str], Any] = {}
    for r in rows:
        kind = r["predicate_kind"] if isinstance(r, sqlite3.Row) else r[0]
        op = r["operator"] if isinstance(r, sqlite3.Row) else r[1]
        v_text = r["value_text"] if isinstance(r, sqlite3.Row) else r[2]
        v_num = r["value_num"] if isinstance(r, sqlite3.Row) else r[3]
        v_json = r["value_json"] if isinstance(r, sqlite3.Row) else r[4]
        # Coerce to a single comparable representation. Prefer numeric
        # over text over JSON when multiple are present (matches the
        # CHECK constraint: predicates carry exactly one value column).
        if v_num is not None:
            value: Any = float(v_num)
        elif v_text is not None:
            value = str(v_text)
        elif v_json is not None:
            value = v_json
        else:
            value = None
        out[(str(kind), str(op))] = value
    return out


def _to_jsonable(value: Any) -> Any:
    """Coerce a row value into a JSON-safe scalar (no bytes, no Row)."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        with contextlib.suppress(Exception):
            return value.decode("utf-8", "replace")
        return repr(value)
    return str(value)


# ---------------------------------------------------------------------------
# Diff core
# ---------------------------------------------------------------------------


def _diff_attr_dicts(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Pure dict-diff: shared / unique_to_a / unique_to_b / conflicts.

    A field is "unique to A" iff A has a non-null value AND B's value is
    null/missing. A "conflict" is a field present and non-null on BOTH
    sides whose values differ. "Shared" fields agree on both sides.
    """
    shared: list[dict[str, Any]] = []
    unique_a: list[dict[str, Any]] = []
    unique_b: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    a = a or {}
    b = b or {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va = _to_jsonable(a.get(k))
        vb = _to_jsonable(b.get(k))
        a_present = va not in (None, "", [], {})
        b_present = vb not in (None, "", [], {})
        if a_present and b_present:
            if va == vb:
                shared.append({"field": k, "value": va})
            else:
                conflicts.append(
                    {
                        "field": k,
                        "a_value": va,
                        "b_value": vb,
                        "reason": "value_mismatch",
                    }
                )
        elif a_present:
            unique_a.append({"field": k, "value": va})
        elif b_present:
            unique_b.append({"field": k, "value": vb})
    return shared, unique_a, unique_b, conflicts


def _diff_neighbour_sets(
    *,
    a_set: set[str],
    b_set: set[str],
    depth: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Set-diff over the am_5hop_graph neighbourhoods."""
    shared = sorted(a_set & b_set)
    unique_a = sorted(a_set - b_set)
    unique_b = sorted(b_set - a_set)
    field = f"am_5hop_graph.depth_{depth}_neighbours"
    return (
        [{"field": field, "value": v} for v in shared],
        [{"field": field, "value": v} for v in unique_a],
        [{"field": field, "value": v} for v in unique_b],
    )


def _diff_predicate_sets(
    a_pred: dict[tuple[str, str], Any],
    b_pred: dict[tuple[str, str], Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Diff two program eligibility predicate sets."""
    shared: list[dict[str, Any]] = []
    unique_a: list[dict[str, Any]] = []
    unique_b: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    keys = sorted(set(a_pred.keys()) | set(b_pred.keys()))
    for k in keys:
        kind, op = k
        field = f"predicate.{kind}.{op}"
        va = a_pred.get(k)
        vb = b_pred.get(k)
        in_a = k in a_pred
        in_b = k in b_pred
        if in_a and in_b:
            if va == vb:
                shared.append({"field": field, "value": va})
            else:
                conflicts.append(
                    {
                        "field": field,
                        "a_value": va,
                        "b_value": vb,
                        "reason": "predicate_value_mismatch",
                    }
                )
        elif in_a:
            unique_a.append({"field": field, "value": va})
        else:
            unique_b.append({"field": field, "value": vb})
    return shared, unique_a, unique_b, conflicts


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/diff",
    summary="Composite entity diff (M&A DD) — shared / unique / conflicts in 1 call",
    description=(
        "Structured diff between two entities of compatible kinds (program "
        "× program, houjin × houjin, law × law). Returns shared_attrs, "
        "unique_to_a, unique_to_b, and conflict_points joined across "
        "primary tables (programs / houjin_master / am_law_article), the "
        "am_5hop_graph 1..depth-hop neighbourhood, am_program_eligibility_"
        "predicate (program × program only), and am_id_bridge for "
        "cross-namespace id resolution.\n\n"
        "**Pricing:** ¥3 per call (`_billing_unit: 1`).\n\n"
        "**No LLM.** Pure SQLite + Python set arithmetic. Output is "
        "descriptive, not prescriptive — final M&A / 与信 / 採択判断 must "
        "go through qualified 士業."
    ),
    responses={
        200: {"description": "Composite diff envelope."},
        404: {"description": "Either entity could not be resolved in any axis."},
        422: {"description": "Incompatible entity kinds (a.type != b.type)."},
    },
)
def post_intel_diff(
    payload: Annotated[IntelDiffRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    if payload.a.type != payload.b.type:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "incompatible_entity_kinds",
                "message": (
                    f"a.type ({payload.a.type!r}) and b.type "
                    f"({payload.b.type!r}) must match for a meaningful diff."
                ),
            },
        )

    kind = payload.a.type
    a_id = payload.a.id.strip()
    b_id = payload.b.id.strip()
    if not a_id or not b_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "empty_entity_id",
                "message": "a.id and b.id must be non-empty after trim.",
            },
        )
    if a_id == b_id and kind != "houjin":
        # Houjin can legitimately diff against itself (sanity check
        # against gBizINFO drift). For programs / laws the same canonical
        # id collapses the diff to all-shared which is rarely useful but
        # not an error — pass through.
        pass

    # Open autonomath.db RO. Lazy import + best-effort: a missing volume
    # degrades the wave24 axes but the primary attrs from jpintel.db
    # still answer.
    am_conn: sqlite3.Connection | None = None
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        try:
            am_conn = connect_autonomath()
        except (FileNotFoundError, sqlite3.Error) as exc:
            logger.info("intel.diff degrading without autonomath.db: %s", exc)
            am_conn = None
    except ImportError:
        am_conn = None

    missing_tables: list[str] = []

    # Primary attrs from the canonical tables.
    a_attrs = _fetch_primary_attrs(
        kind=kind,
        raw_id=a_id,
        conn=conn,
        am_conn=am_conn,
        missing_tables=missing_tables,
    )
    b_attrs = _fetch_primary_attrs(
        kind=kind,
        raw_id=b_id,
        conn=conn,
        am_conn=am_conn,
        missing_tables=missing_tables,
    )
    if a_attrs is None and b_attrs is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "both_entities_unresolved",
                "message": (
                    f"Neither {a_id!r} nor {b_id!r} resolved against "
                    f"the {kind!r} axis (canonical table missing or both "
                    f"ids unknown)."
                ),
                "missing_tables": missing_tables,
            },
        )

    # Wave24 graph neighbourhoods (cross-source via am_id_bridge).
    a_seeds = _resolve_am_id(am_conn, a_id)
    b_seeds = _resolve_am_id(am_conn, b_id)
    a_nbrs = _fetch_5hop_neighbours(
        am_conn, a_seeds, depth=payload.depth, missing_tables=missing_tables
    )
    b_nbrs = _fetch_5hop_neighbours(
        am_conn, b_seeds, depth=payload.depth, missing_tables=missing_tables
    )

    # Eligibility predicate set (program × program only).
    a_pred: dict[tuple[str, str], Any] = {}
    b_pred: dict[tuple[str, str], Any] = {}
    if kind == "program":
        a_pred = _fetch_predicate_set(am_conn, a_id, missing_tables=missing_tables)
        b_pred = _fetch_predicate_set(am_conn, b_id, missing_tables=missing_tables)

    # Compose per-axis diffs.
    s_attr, ua_attr, ub_attr, c_attr = _diff_attr_dicts(a_attrs, b_attrs)
    s_nbr, ua_nbr, ub_nbr = _diff_neighbour_sets(a_set=a_nbrs, b_set=b_nbrs, depth=payload.depth)
    if kind == "program":
        s_pred, ua_pred, ub_pred, c_pred = _diff_predicate_sets(a_pred, b_pred)
    else:
        s_pred, ua_pred, ub_pred, c_pred = [], [], [], []

    shared_attrs = s_attr + s_nbr + s_pred
    unique_to_a = ua_attr + ua_nbr + ua_pred
    unique_to_b = ub_attr + ub_nbr + ub_pred
    conflict_points = c_attr + c_pred

    # Close the autonomath connection (per-thread pool — safe).
    if am_conn is not None:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    body: dict[str, Any] = {
        "a": {"type": kind, "id": a_id, "resolved": a_attrs is not None},
        "b": {"type": kind, "id": b_id, "resolved": b_attrs is not None},
        "depth": payload.depth,
        "shared_attrs": shared_attrs,
        "unique_to_a": unique_to_a,
        "unique_to_b": unique_to_b,
        "conflict_points": conflict_points,
        "data_quality": {
            "missing_tables": sorted(set(missing_tables)),
            "a_neighbour_count": len(a_nbrs),
            "b_neighbour_count": len(b_nbrs),
            "a_predicate_count": len(a_pred),
            "b_predicate_count": len(b_pred),
            "axes": [
                "primary_attrs",
                "am_5hop_graph",
                "am_program_eligibility_predicate" if kind == "program" else None,
                "am_id_bridge",
            ],
        },
        "_disclaimer": _DIFF_DISCLAIMER,
        "_billing_unit": 1,
    }
    # axes list contains a None for non-program kinds — strip it for cleanliness.
    body["data_quality"]["axes"] = [x for x in body["data_quality"]["axes"] if x is not None]

    # corpus_snapshot_id + checksum (auditor reproducibility).
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.diff",
        latency_ms=latency_ms,
        result_count=(
            len(shared_attrs) + len(unique_to_a) + len(unique_to_b) + len(conflict_points)
        ),
        params={
            "kind": kind,
            "depth": payload.depth,
            "a_id_present": bool(a_id),
            "b_id_present": bool(b_id),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.diff",
        request_params={
            "a_type": kind,
            "a_id": a_id,
            "b_type": kind,
            "b_id": b_id,
            "depth": payload.depth,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    # Defensive: a downstream JSON encoder might choke on tuple keys we
    # accidentally let through. Round-trip via json.dumps to coerce.
    return JSONResponse(content=json.loads(json.dumps(body, default=str)))


__all__ = ["router"]
