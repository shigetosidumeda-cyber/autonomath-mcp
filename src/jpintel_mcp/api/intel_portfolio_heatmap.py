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
_VERIFIED_AMOUNT_TIERS = {"verified", "authoritative"}
_AMOUNT_POLICY = (
    "am_amount_condition values are included only when quality_tier is "
    "verified/authoritative or is_authoritative=1; template_default rows are omitted."
)
_AMOUNT_TOTAL_LIMITATION = (
    "total_amount_max_yen and total_verified_amount_max_yen aggregate only "
    "verified/authoritative am_amount_condition values. program_amount_hint, "
    "template_default, and unverified amount rows are excluded from totals."
)
_COMPATIBILITY_ADVISORY_CAVEAT = (
    "Compatibility is an advisory matrix signal, not a legal/tax ruling. "
    "inferred_only rows are heuristic; confirm expense overlap, Subsidy "
    "Appropriateness Act Article 17, and program-specific exceptions in primary sources."
)


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
) -> tuple[dict[str, int | None], dict[str, dict[str, Any]], int, list[str]]:
    amounts: dict[str, int | None] = dict.fromkeys(program_ids)
    meta: dict[str, dict[str, Any]] = {
        pid: {
            "source": "none",
            "quality_tier": None,
            "is_authoritative": None,
            "template_default": None,
            "limitation": "no verified/authoritative amount condition available",
        }
        for pid in program_ids
    }
    omitted_count = 0
    quality_gaps: list[str] = []
    if not _table_exists(conn, "am_amount_condition"):
        _missing(missing, "am_amount_condition")
        return amounts, meta, omitted_count, quality_gaps
    cols = _columns(conn, "am_amount_condition")
    pid_col = _first_existing(cols, ("program_id", "unified_id", "entity_id", "program_entity_id"))
    amount_col = _first_existing(
        cols, ("amount_max_yen", "max_amount_yen", "amount_yen", "fixed_yen", "numeric_value")
    )
    if not pid_col or not amount_col:
        return amounts, meta, omitted_count, quality_gaps

    identifiers = list(program_ids)
    if pid_col == "entity_id":
        identifiers.extend(f"program:{pid}" for pid in program_ids)
    placeholders = ",".join(["?"] * len(identifiers))
    quality_col = _first_existing(cols, ("quality_tier", "quality_flag"))
    authoritative_col = _first_existing(cols, ("is_authoritative", "authoritative"))
    template_col = _first_existing(cols, ("template_default", "is_template_default"))
    if not quality_col and not authoritative_col:
        quality_gaps.append(
            "am_amount_condition quality metadata unavailable; condition amounts omitted"
        )
        for pid in program_ids:
            meta[pid]["limitation"] = (
                "amount condition omitted because quality metadata is unavailable"
            )
        try:
            omitted_row = conn.execute(
                f"SELECT COUNT(*) FROM am_amount_condition WHERE {pid_col} IN ({placeholders})",
                identifiers,
            ).fetchone()
            omitted_count = int(omitted_row[0] or 0) if omitted_row else 0
        except sqlite3.Error as exc:
            logger.warning("amount condition omission count failed: %s", exc)
        return amounts, meta, omitted_count, quality_gaps

    quality_expr = f"LOWER(COALESCE({quality_col}, ''))" if quality_col else "''"
    authoritative_expr = f"COALESCE({authoritative_col}, 0)" if authoritative_col else "0"
    template_expr = f"COALESCE({template_col}, 0)" if template_col else "0"
    trusted_clauses: list[str] = []
    if quality_col:
        trusted_clauses.append(f"{quality_expr} IN ({','.join(['?'] * len(_VERIFIED_AMOUNT_TIERS))})")
    if authoritative_col:
        trusted_clauses.append(f"{authoritative_expr} = 1")
    trusted_sql = "(" + " OR ".join(trusted_clauses) + ")" if trusted_clauses else "1=1"
    if template_col:
        trusted_sql = f"{trusted_sql} AND {template_expr} = 0"
    trusted_params = sorted(_VERIFIED_AMOUNT_TIERS) if quality_col else []
    select_cols = [
        f"{pid_col} AS pid",
        f"{amount_col} AS amount",
        f"{quality_col} AS quality_tier" if quality_col else "NULL AS quality_tier",
        f"{authoritative_col} AS is_authoritative"
        if authoritative_col
        else "NULL AS is_authoritative",
        f"{template_col} AS template_default" if template_col else "NULL AS template_default",
    ]
    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM am_amount_condition "
            f"WHERE {pid_col} IN ({placeholders}) AND {trusted_sql}",
            [*identifiers, *trusted_params],
        ).fetchall()
        omitted_row = conn.execute(
            f"SELECT COUNT(*) FROM am_amount_condition "
            f"WHERE {pid_col} IN ({placeholders}) AND NOT ({trusted_sql})",
            [*identifiers, *trusted_params],
        ).fetchone()
        omitted_count = int(omitted_row[0] or 0) if omitted_row else 0
    except sqlite3.Error as exc:
        logger.warning("amount condition query failed: %s", exc)
        return amounts, meta, omitted_count, quality_gaps
    for row in rows:
        pid = str(row["pid"] or "")
        if pid.startswith("program:"):
            pid = pid.removeprefix("program:")
        if pid not in amounts or row["amount"] is None:
            continue
        amount = int(float(row["amount"]))
        if amounts[pid] is None or amount > int(amounts[pid] or 0):
            is_authoritative = row["is_authoritative"]
            template_default = row["template_default"]
            amounts[pid] = amount
            meta[pid] = {
                "source": "am_amount_condition",
                "quality_tier": row["quality_tier"],
                "is_authoritative": bool(is_authoritative)
                if is_authoritative is not None
                else None,
                "template_default": bool(template_default)
                if template_default is not None
                else None,
                "limitation": None,
            }
    if omitted_count:
        quality_gaps.append(
            f"am_amount_condition omitted {omitted_count} unverified/template-default amount row(s)"
        )
    return amounts, meta, omitted_count, quality_gaps


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _compatibility_advisory_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    inferred_only = _bool_or_none(row.get("inferred_only")) if row else None
    source_url = row.get("source_url") if row else None
    confidence = row.get("confidence") if row else None
    if row is None:
        advisory_quality = "no_matrix_row_advisory"
    elif inferred_only is True:
        advisory_quality = "heuristic_advisory"
    elif source_url:
        advisory_quality = "sourced_advisory"
    else:
        advisory_quality = "matrix_advisory"
    return {
        "quality": advisory_quality,
        "advisory_quality": advisory_quality,
        "caveat": _COMPATIBILITY_ADVISORY_CAVEAT,
        "inferred_only": inferred_only,
        "confidence": confidence,
        "source_url": source_url,
        "source_url_present": bool(source_url),
    }


def _compatibility_row_advisory(pid: str, pairs: list[dict[str, Any]], status: str) -> dict[str, Any]:
    related = [p for p in pairs if pid in {p["program_a"], p["program_b"]}]
    qualities = {str(p.get("advisory_quality") or p.get("quality") or "") for p in related}
    if status == "single_program":
        advisory_quality = "single_program_advisory"
    elif not related:
        advisory_quality = "unknown_advisory"
    elif "heuristic_advisory" in qualities or "no_matrix_row_advisory" in qualities:
        advisory_quality = "mixed_advisory"
    elif "matrix_advisory" in qualities:
        advisory_quality = "matrix_advisory"
    else:
        advisory_quality = "sourced_advisory"
    return {
        "quality": advisory_quality,
        "advisory_quality": advisory_quality,
        "caveat": _COMPATIBILITY_ADVISORY_CAVEAT,
    }


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
    inferred_col = _first_existing(cols, ("inferred_only", "is_inferred"))
    confidence_col = _first_existing(cols, ("confidence", "score"))
    source_url_col = _first_existing(cols, ("source_url", "evidence_url"))
    rationale_col = _first_existing(cols, ("rationale_short", "conditions_text", "rationale"))
    if not a_col or not b_col or not status_col:
        return per_program, pairs_out
    pair_lookup = {
        tuple(sorted(pair)): {
            "status": "unknown",
            **_compatibility_advisory_fields(None),
            "rationale": None,
        }
        for pair in combinations(program_ids, 2)
    }
    select_cols = [f"{status_col} AS status"]
    for alias, col in (
        ("inferred_only", inferred_col),
        ("confidence", confidence_col),
        ("source_url", source_url_col),
        ("rationale", rationale_col),
    ):
        select_cols.append(f"{col} AS {alias}" if col else f"NULL AS {alias}")
    try:
        for a, b in pair_lookup:
            row = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM am_compat_matrix "
                f"WHERE (({a_col}=? AND {b_col}=?) OR ({a_col}=? AND {b_col}=?)) LIMIT 1",
                (a, b, b, a),
            ).fetchone()
            if row:
                row_data = dict(row)
                pair_lookup[(a, b)] = {
                    "status": str(row["status"] or "unknown"),
                    **_compatibility_advisory_fields(row_data),
                    "rationale": row_data.get("rationale"),
                }
    except sqlite3.Error as exc:
        logger.warning("compat query failed: %s", exc)
    for (a, b), detail in pair_lookup.items():
        pairs_out.append({"program_a": a, "program_b": b, **detail})
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
        amount_meta = {
            pid: {
                "source": "none",
                "quality_tier": None,
                "is_authoritative": None,
                "template_default": None,
                "limitation": "autonomath.db unavailable; amount condition quality unknown",
            }
            for pid in program_ids
        }
        omitted_amount_count = 0
        amount_quality_gaps: list[str] = []
        timing = {pid: {"next_deadline": None, "window_status": "unknown"} for pid in program_ids}
        compatibility, pairs = (dict.fromkeys(program_ids, "unknown"), [])  # type: ignore[var-annotated]
    else:
        programs = _fetch_programs(conn, program_ids, missing)
        amounts, amount_meta, omitted_amount_count, amount_quality_gaps = _amount_by_program(
            conn, program_ids, missing
        )
        timing = _timing_by_program(conn, program_ids, missing)
        compatibility, pairs = _compatibility(conn, program_ids, missing)
    known_gaps.extend(amount_quality_gaps)

    rows: list[dict[str, Any]] = []
    for pid in program_ids:
        prog = programs.get(pid, {"program_id": pid})
        verified_amount = amounts.get(pid)
        amount = verified_amount
        amount_hint = prog.get("amount_hint")
        row_amount_meta = dict(amount_meta.get(pid) or {})
        if amount is None and amount_hint is not None:
            raw_amount = float(amount_hint)
            amount = int(raw_amount * 10_000) if raw_amount < 1_000_000 else int(raw_amount)
            row_amount_meta = {
                "source": "program_amount_hint",
                "quality_tier": None,
                "is_authoritative": None,
                "template_default": None,
                "limitation": (
                    "program-level amount hint; no verified/authoritative "
                    "am_amount_condition value was available"
                ),
            }
        row_timing = timing.get(pid, {"next_deadline": None, "window_status": "unknown"})
        compat = compatibility.get(pid, "unknown")
        risk = _risk_score(prog.get("tier"), compat, row_timing, amount)
        counts_toward_total = row_amount_meta.get("source") == "am_amount_condition"
        rows.append(
            {
                "program_id": pid,
                "name": prog.get("name"),
                "risk": {"score": risk, "label": _label(risk), "tier": prog.get("tier")},
                "amount": {
                    "max_yen": amount,
                    "verified_max_yen": verified_amount,
                    "counts_toward_total": counts_toward_total,
                    "band": "unknown"
                    if amount is None
                    else ("large" if amount >= 10_000_000 else "standard"),
                    "quality": row_amount_meta,
                },
                "timing": row_timing,
                "compatibility": {
                    "status": compat,
                    **_compatibility_row_advisory(pid, pairs, compat),
                },
            }
        )

    if not program_ids:
        known_gaps.append("no program_ids supplied or resolved from houjin_id")
    for table in sorted(set(missing)):
        known_gaps.append(f"{table} unavailable; related heatmap axis is partial")
    high_count = sum(1 for r in rows if r["risk"]["label"] == "high")
    total_verified_amount = sum(
        r["amount"]["verified_max_yen"] or 0
        for r in rows
        if r["amount"].get("counts_toward_total")
    )
    summary = {
        "program_count": len(rows),
        "high_risk_count": high_count,
        "total_amount_max_yen": total_verified_amount,
        "total_verified_amount_max_yen": total_verified_amount,
        "amount_total_limitation": _AMOUNT_TOTAL_LIMITATION,
        "compatibility_pairs": len(pairs),
        "missing_axis_count": len(set(missing)),
        "verified_amount_count": sum(
            1
            for r in rows
            if ((r.get("amount") or {}).get("quality") or {}).get("source")
            == "am_amount_condition"
        ),
        "omitted_amount_condition_count": omitted_amount_count,
    }
    return {
        "houjin_id": normalized,
        "heatmap_rows": rows,
        "compatibility_pairs": pairs,
        "summary": summary,
        "known_gaps": known_gaps,
        "data_quality": {
            "missing_tables": sorted(set(missing)),
            "amount_policy": _AMOUNT_POLICY,
            "amount_total_limitation": _AMOUNT_TOTAL_LIMITATION,
            "omitted_amount_condition_count": omitted_amount_count,
            "compatibility_caveat": _COMPATIBILITY_ADVISORY_CAVEAT,
        },
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
