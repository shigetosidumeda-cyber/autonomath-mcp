"""POST /v1/intel/portfolio_heatmap — deterministic program portfolio heatmap."""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from itertools import combinations
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_portfolio_heatmap")

router = APIRouter(prefix="/v1/intel", tags=["intel"])

_DISCLAIMER = (
    "本 portfolio_heatmap は programs / adoption / amount / calendar / compat "
    "substrate を機械的に集計した rules-based 表であり、採択可能性・併用可否・"
    "税務/法務判断の保証ではありません。申請・併用・会計処理の確定判断は"
    "一次資料と資格を有する専門家で確認してください。"
)

_RISK_POINTS = {"S": 10, "A": 20, "B": 35, "C": 50, "D": 65, "X": 90}


class PortfolioHeatmapRequest(BaseModel):
    program_ids: list[str] | None = Field(None, min_length=1, max_length=25)
    houjin_id: str | None = Field(None, min_length=13, max_length=14)
    horizon_months: int = Field(12, ge=1, le=36)


def _normalize_houjin(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[\s\-,　]", "", str(raw).strip().lstrip("Tt"))
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _missing(missing_tables: list[str], table: str) -> None:
    if table not in missing_tables:
        missing_tables.append(table)


def _first_existing(cols: set[str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in cols:
            return name
    return None


def _open_autonomath() -> sqlite3.Connection | None:
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    try:
        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("autonomath unavailable for portfolio_heatmap: %s", exc)
        return None


def _dedupe_program_ids(program_ids: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in program_ids or []:
        pid = str(raw).strip()
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def _program_ids_for_houjin(
    conn: sqlite3.Connection,
    houjin_id: str,
    missing_tables: list[str],
    limit: int = 25,
) -> list[str]:
    if not _table_exists(conn, "jpi_adoption_records"):
        _missing(missing_tables, "jpi_adoption_records")
        return []
    cols = _columns(conn, "jpi_adoption_records")
    pid_col = _first_existing(cols, ("program_id", "program_id_hint"))
    if not pid_col:
        return []
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {pid_col} AS pid FROM jpi_adoption_records "
            "WHERE houjin_bangou=? AND pid IS NOT NULL ORDER BY pid ASC LIMIT ?",
            (houjin_id, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("houjin program lookup failed: %s", exc)
        return []
    return [str(r["pid"]) for r in rows if r["pid"]]


def _fetch_programs(
    conn: sqlite3.Connection,
    program_ids: list[str],
    missing_tables: list[str],
) -> dict[str, dict[str, Any]]:
    if not program_ids:
        return {}
    table = "jpi_programs" if _table_exists(conn, "jpi_programs") else None
    if table is None and _table_exists(conn, "programs"):
        table = "programs"
    if table is None:
        _missing(missing_tables, "jpi_programs")
        return {
            pid: {"program_id": pid, "name": None, "tier": None, "program_kind": None}
            for pid in program_ids
        }

    cols = _columns(conn, table)
    id_col = _first_existing(cols, ("unified_id", "program_id"))
    name_col = _first_existing(cols, ("primary_name", "name"))
    tier_col = _first_existing(cols, ("tier", "trust_tier"))
    kind_col = _first_existing(cols, ("program_kind", "kind"))
    amount_col = _first_existing(cols, ("amount_max_man_yen", "max_amount_yen", "amount_max_yen"))
    if not id_col:
        return {}
    placeholders = ",".join(["?"] * len(program_ids))
    select_cols = [f"{id_col} AS program_id"]
    for alias, col in (
        ("name", name_col),
        ("tier", tier_col),
        ("program_kind", kind_col),
        ("amount_hint", amount_col),
    ):
        select_cols.append(f"{col} AS {alias}" if col else f"NULL AS {alias}")
    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {table} WHERE {id_col} IN ({placeholders})",
            program_ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("program lookup failed: %s", exc)
        rows = []
    out = {
        pid: {
            "program_id": pid,
            "name": None,
            "tier": None,
            "program_kind": None,
            "amount_hint": None,
        }
        for pid in program_ids
    }
    for row in rows:
        out[str(row["program_id"])] = dict(row)
    return out


def _amount_by_program(
    conn: sqlite3.Connection, program_ids: list[str], missing: list[str]
) -> dict[str, int | None]:
    amounts: dict[str, int | None] = dict.fromkeys(program_ids)
    if not _table_exists(conn, "am_amount_condition"):
        _missing(missing, "am_amount_condition")
        return amounts
    cols = _columns(conn, "am_amount_condition")
    pid_col = _first_existing(cols, ("program_id", "unified_id"))
    amount_col = _first_existing(cols, ("amount_max_yen", "max_amount_yen", "amount_yen"))
    if not pid_col or not amount_col:
        return amounts
    placeholders = ",".join(["?"] * len(program_ids))
    try:
        rows = conn.execute(
            f"SELECT {pid_col} AS pid, MAX({amount_col}) AS amount "
            f"FROM am_amount_condition WHERE {pid_col} IN ({placeholders}) GROUP BY {pid_col}",
            program_ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("amount condition query failed: %s", exc)
        return amounts
    for row in rows:
        amounts[str(row["pid"])] = int(row["amount"]) if row["amount"] is not None else None
    return amounts


def _timing_by_program(
    conn: sqlite3.Connection, program_ids: list[str], missing: list[str]
) -> dict[str, dict[str, Any]]:
    timing = {pid: {"next_deadline": None, "window_status": "unknown"} for pid in program_ids}
    if not _table_exists(conn, "am_program_calendar_12mo"):
        _missing(missing, "am_program_calendar_12mo")
        return timing
    cols = _columns(conn, "am_program_calendar_12mo")
    pid_col = _first_existing(cols, ("program_id", "unified_id"))
    deadline_col = _first_existing(cols, ("deadline_date", "application_deadline", "date"))
    status_col = _first_existing(cols, ("window_status", "status"))
    if not pid_col:
        return timing
    deadline_expr = f"MIN({deadline_col})" if deadline_col else "NULL"
    status_expr = f"MIN({status_col})" if status_col else "'unknown'"
    placeholders = ",".join(["?"] * len(program_ids))
    try:
        rows = conn.execute(
            f"SELECT {pid_col} AS pid, {deadline_expr} AS deadline, {status_expr} AS status "
            f"FROM am_program_calendar_12mo WHERE {pid_col} IN ({placeholders}) GROUP BY {pid_col}",
            program_ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("calendar query failed: %s", exc)
        return timing
    for row in rows:
        timing[str(row["pid"])] = {
            "next_deadline": row["deadline"],
            "window_status": row["status"] or "unknown",
        }
    return timing


def _compatibility(
    conn: sqlite3.Connection,
    program_ids: list[str],
    missing: list[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    per_program = dict.fromkeys(program_ids, "unknown")
    pairs_out: list[dict[str, Any]] = []
    if len(program_ids) < 2:
        for pid in program_ids:
            per_program[pid] = "single_program"
        return per_program, pairs_out
    if not _table_exists(conn, "am_compat_matrix"):
        _missing(missing, "am_compat_matrix")
        return per_program, pairs_out

    cols = _columns(conn, "am_compat_matrix")
    a_col = _first_existing(cols, ("program_a_id", "program_a"))
    b_col = _first_existing(cols, ("program_b_id", "program_b"))
    status_col = _first_existing(cols, ("compat_status", "status", "compat_matrix_says"))
    if not a_col or not b_col or not status_col:
        return per_program, pairs_out
    pair_lookup = {tuple(sorted(pair)): "unknown" for pair in combinations(program_ids, 2)}
    try:
        for a, b in pair_lookup:
            row = conn.execute(
                f"SELECT {status_col} AS status FROM am_compat_matrix "
                f"WHERE (({a_col}=? AND {b_col}=?) OR ({a_col}=? AND {b_col}=?)) LIMIT 1",
                (a, b, b, a),
            ).fetchone()
            if row:
                pair_lookup[(a, b)] = str(row["status"] or "unknown")
    except sqlite3.Error as exc:
        logger.warning("compat query failed: %s", exc)
    for (a, b), status in pair_lookup.items():
        pairs_out.append({"program_a": a, "program_b": b, "status": status})
    for pid in program_ids:
        statuses = [p["status"] for p in pairs_out if pid in {p["program_a"], p["program_b"]}]
        if any(s == "incompatible" for s in statuses):
            per_program[pid] = "incompatible"
        elif any(s in {"case_by_case", "requires_review"} for s in statuses):
            per_program[pid] = "requires_review"
        elif statuses and all(s == "compatible" for s in statuses):
            per_program[pid] = "compatible"
    return per_program, pairs_out


def _risk_score(
    tier: str | None, compatibility: str, timing: dict[str, Any], amount_yen: int | None
) -> int:
    score = _RISK_POINTS.get(str(tier or "").upper(), 45)
    if compatibility == "incompatible":
        score += 35
    elif compatibility in {"requires_review", "unknown"}:
        score += 15
    if timing.get("window_status") in {"closed", "expired"}:
        score += 20
    if amount_yen is None:
        score += 10
    return max(0, min(100, score))


def _label(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _build_envelope(
    conn: sqlite3.Connection | None, payload: PortfolioHeatmapRequest
) -> dict[str, Any]:
    missing: list[str] = []
    known_gaps: list[str] = []
    normalized = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    program_ids = _dedupe_program_ids(payload.program_ids)

    if conn is None:
        missing.append("autonomath.db")
        known_gaps.append("autonomath.db unavailable; no portfolio substrate loaded")
    elif not program_ids and normalized:
        program_ids = _program_ids_for_houjin(conn, normalized, missing)

    if conn is None:
        programs = {
            pid: {"program_id": pid, "name": None, "tier": None, "program_kind": None}
            for pid in program_ids
        }
        amounts = dict.fromkeys(program_ids)
        timing = {pid: {"next_deadline": None, "window_status": "unknown"} for pid in program_ids}
        compatibility, pairs = (dict.fromkeys(program_ids, "unknown"), [])  # type: ignore[var-annotated]
    else:
        programs = _fetch_programs(conn, program_ids, missing)
        amounts = _amount_by_program(conn, program_ids, missing)
        timing = _timing_by_program(conn, program_ids, missing)
        compatibility, pairs = _compatibility(conn, program_ids, missing)

    rows: list[dict[str, Any]] = []
    for pid in program_ids:
        prog = programs.get(pid, {"program_id": pid})
        amount = amounts.get(pid)
        amount_hint = prog.get("amount_hint")
        if amount is None and amount_hint is not None:
            raw_amount = float(amount_hint)
            amount = int(raw_amount * 10_000) if raw_amount < 1_000_000 else int(raw_amount)
        row_timing = timing.get(pid, {"next_deadline": None, "window_status": "unknown"})
        compat = compatibility.get(pid, "unknown")
        risk = _risk_score(prog.get("tier"), compat, row_timing, amount)
        rows.append(
            {
                "program_id": pid,
                "name": prog.get("name"),
                "risk": {"score": risk, "label": _label(risk), "tier": prog.get("tier")},
                "amount": {
                    "max_yen": amount,
                    "band": "unknown"
                    if amount is None
                    else ("large" if amount >= 10_000_000 else "standard"),
                },
                "timing": row_timing,
                "compatibility": {"status": compat},
            }
        )

    if not program_ids:
        known_gaps.append("no program_ids supplied or resolved from houjin_id")
    for table in sorted(set(missing)):
        known_gaps.append(f"{table} unavailable; related heatmap axis is partial")
    high_count = sum(1 for r in rows if r["risk"]["label"] == "high")
    total_amount = sum(r["amount"]["max_yen"] or 0 for r in rows)
    summary = {
        "program_count": len(rows),
        "high_risk_count": high_count,
        "total_amount_max_yen": total_amount,
        "compatibility_pairs": len(pairs),
        "missing_axis_count": len(set(missing)),
    }
    return {
        "houjin_id": normalized,
        "heatmap_rows": rows,
        "compatibility_pairs": pairs,
        "summary": summary,
        "known_gaps": known_gaps,
        "data_quality": {"missing_tables": sorted(set(missing))},
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


@router.post(
    "/portfolio_heatmap",
    summary="Program portfolio heatmap across risk / amount / timing / compatibility (NO LLM)",
)
def post_portfolio_heatmap(
    payload: Annotated[PortfolioHeatmapRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()
    if not payload.program_ids and not payload.houjin_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_required_field",
                "field": "program_ids|houjin_id",
                "message": "supply program_ids or houjin_id",
            },
        )
    normalized = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    if payload.houjin_id and normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": "houjin_id must be 13 digits, with or without T prefix",
            },
        )

    body = _build_envelope(_open_autonomath(), payload)
    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)
    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.portfolio_heatmap",
        latency_ms=latency_ms,
        result_count=len(body.get("heatmap_rows") or []),
        strict_metering=True,
        params={
            "program_count": len(payload.program_ids or []),
            "houjin_id_present": bool(payload.houjin_id),
        },
    )
    attach_seal_to_body(
        body,
        endpoint="intel.portfolio_heatmap",
        request_params={
            "program_ids": _dedupe_program_ids(payload.program_ids),
            "houjin_id": normalized,
            "horizon_months": payload.horizon_months,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
