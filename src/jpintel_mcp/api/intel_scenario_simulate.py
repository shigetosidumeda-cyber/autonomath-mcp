"""POST /v1/intel/scenario/simulate — deterministic grant scenario simulator.

This endpoint gives customer LLMs a single rules-based "what changes if..."
surface for houjin/program funding scenarios. It never calls an LLM, never
writes to SQLite, and treats missing autonomath substrate as a data-quality
gap rather than a server error.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._compact_envelope import to_compact, wants_compact

logger = logging.getLogger("jpintel.api.intel_scenario_simulate")

router = APIRouter(prefix="/v1/intel", tags=["intel"])

_MAX_PROGRAMS = 25
_DEFAULT_PROBABILITY = 0.35

_DISCLAIMER = (
    "本 scenario/simulate response は programs / jpi_programs / "
    "am_recommended_programs / jpi_adoption_records / am_funding_stack_empirical "
    "等の公開・事前計算 substrate を rules-based に集計した試算であり、"
    "採択保証、補助金額の確約、税務・法律・行政手続代理の助言ではありません。"
    "最終判断は一次資料および税理士法 §52・行政書士法 §1・弁護士法 §72 の "
    "有資格者確認に従ってください。"
)


class ScenarioNumbers(BaseModel):
    requested_amount_yen: Annotated[
        int | None,
        Field(default=None, ge=0, description="Target requested amount in yen."),
    ] = None
    capex_yen: Annotated[
        int | None,
        Field(default=None, ge=0, description="Planned eligible expenditure in yen."),
    ] = None
    subsidy_rate: Annotated[
        float | None,
        Field(default=None, ge=0.0, le=1.0, description="Assumed subsidy rate, 0.0..1.0."),
    ] = None
    probability_adjustment_pct: Annotated[
        float,
        Field(
            default=0.0,
            ge=-100.0,
            le=100.0,
            description="Additive probability delta in percentage points.",
        ),
    ] = 0.0
    deadline_days_delta: Annotated[
        int,
        Field(
            default=0,
            ge=-365,
            le=365,
            description="Positive means more days before deadline; negative means less.",
        ),
    ] = 0
    additional_program_ids: Annotated[
        list[str],
        Field(default_factory=list, max_length=_MAX_PROGRAMS),
    ]
    remove_program_ids: Annotated[
        list[str],
        Field(default_factory=list, max_length=_MAX_PROGRAMS),
    ]
    enforce_conflict_penalty: bool = True


class ScenarioSimulateRequest(BaseModel):
    houjin_id: Annotated[
        str | None,
        Field(default=None, description="13-digit 法人番号, with or without T prefix."),
    ] = None
    program_ids: Annotated[
        list[str],
        Field(default_factory=list, max_length=_MAX_PROGRAMS),
    ]
    scenario: ScenarioNumbers = Field(default_factory=ScenarioNumbers)


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    try:
        from jpintel_mcp.config import settings

        return Path(str(settings.autonomath_db_path))
    except (AttributeError, ImportError):
        return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    p = _autonomath_db_path()
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except sqlite3.Error as exc:
        logger.warning("scenario simulator could not open autonomath.db: %s", exc)
        return None


def _normalize_houjin(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s if s.isdigit() and len(s) == 13 else None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _first_table(conn: sqlite3.Connection, names: tuple[str, ...]) -> str | None:
    for name in names:
        if _table_exists(conn, name):
            return name
    return None


def _program_id_col(cols: set[str]) -> str | None:
    for col in ("program_unified_id", "unified_id", "program_id", "id"):
        if col in cols:
            return col
    return None


def _money_from_man_yen(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value) * 10_000))
    except (TypeError, ValueError):
        return None


def _fetch_houjin_profile(
    conn: sqlite3.Connection | None,
    houjin_id: str | None,
    known_gaps: list[str],
) -> dict[str, Any] | None:
    if conn is None or not houjin_id:
        return None
    if not _table_exists(conn, "houjin_master"):
        known_gaps.append("missing_table:houjin_master")
        return None
    cols = _columns(conn, "houjin_master")
    if "houjin_bangou" not in cols:
        known_gaps.append("missing_column:houjin_master.houjin_bangou")
        return None
    select_cols = [
        c
        for c in (
            "normalized_name",
            "name",
            "prefecture",
            "municipality",
            "jsic_major",
            "capital_yen",
            "employee_count",
        )
        if c in cols
    ]
    try:
        row = conn.execute(
            f"SELECT houjin_bangou{',' if select_cols else ''}{','.join(select_cols)} "
            "FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        known_gaps.append(f"query_failed:houjin_master:{exc.__class__.__name__}")
        return None
    return dict(row) if row else None


def _fetch_adopted_program_ids(
    conn: sqlite3.Connection | None,
    houjin_id: str | None,
    known_gaps: list[str],
) -> list[str]:
    if conn is None or not houjin_id:
        return []
    if not _table_exists(conn, "jpi_adoption_records"):
        known_gaps.append("missing_table:jpi_adoption_records")
        return []
    cols = _columns(conn, "jpi_adoption_records")
    id_col = _program_id_col(cols)
    if "houjin_bangou" not in cols or id_col is None:
        known_gaps.append("missing_column:jpi_adoption_records.houjin_bangou_or_program_id")
        return []
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {id_col} AS program_id FROM jpi_adoption_records "
            f"WHERE houjin_bangou = ? AND {id_col} IS NOT NULL LIMIT ?",
            (houjin_id, _MAX_PROGRAMS),
        ).fetchall()
    except sqlite3.Error as exc:
        known_gaps.append(f"query_failed:jpi_adoption_records:{exc.__class__.__name__}")
        return []
    return [str(r["program_id"]) for r in rows if r["program_id"]]


def _fetch_recommended_scores(
    conn: sqlite3.Connection | None,
    houjin_id: str | None,
    known_gaps: list[str],
) -> dict[str, float]:
    if conn is None or not houjin_id:
        return {}
    if not _table_exists(conn, "am_recommended_programs"):
        known_gaps.append("missing_table:am_recommended_programs")
        return {}
    cols = _columns(conn, "am_recommended_programs")
    if not {"houjin_bangou", "program_unified_id"}.issubset(cols):
        known_gaps.append(
            "missing_column:am_recommended_programs.houjin_bangou_or_program_unified_id"
        )
        return {}
    score_expr = "score" if "score" in cols else "NULL"
    try:
        rows = conn.execute(
            f"SELECT program_unified_id, {score_expr} AS score FROM am_recommended_programs "
            "WHERE houjin_bangou = ? LIMIT ?",
            (houjin_id, _MAX_PROGRAMS),
        ).fetchall()
    except sqlite3.Error as exc:
        known_gaps.append(f"query_failed:am_recommended_programs:{exc.__class__.__name__}")
        return {}
    scores: dict[str, float] = {}
    for row in rows:
        try:
            scores[str(row["program_unified_id"])] = max(0.0, min(1.0, float(row["score"])))
        except (TypeError, ValueError):
            scores[str(row["program_unified_id"])] = _DEFAULT_PROBABILITY
    return scores


def _fetch_programs(
    conn: sqlite3.Connection | None,
    program_ids: list[str],
    known_gaps: list[str],
) -> list[dict[str, Any]]:
    if conn is None or not program_ids:
        return []
    table = _first_table(conn, ("jpi_programs", "programs"))
    if table is None:
        known_gaps.append("missing_table:jpi_programs_or_programs")
        return []
    cols = _columns(conn, table)
    id_col = _program_id_col(cols)
    if id_col is None:
        known_gaps.append(f"missing_column:{table}.program_id")
        return []
    placeholders = ",".join("?" for _ in program_ids)
    select_parts = [f"{id_col} AS program_id"]
    for source, alias in (
        ("primary_name", "name"),
        ("name", "name"),
        ("program_kind", "program_kind"),
        ("prefecture", "prefecture"),
        ("amount_max_man_yen", "amount_max_man_yen"),
        ("amount_min_man_yen", "amount_min_man_yen"),
    ):
        if source in cols:
            select_parts.append(f"{source} AS {alias}")
    try:
        rows = conn.execute(
            f"SELECT {','.join(select_parts)} FROM {table} WHERE {id_col} IN ({placeholders})",
            tuple(program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        known_gaps.append(f"query_failed:{table}:{exc.__class__.__name__}")
        return []

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        pid = str(item["program_id"])
        seen.add(pid)
        item["amount_max_yen"] = _money_from_man_yen(item.get("amount_max_man_yen"))
        item["amount_min_yen"] = _money_from_man_yen(item.get("amount_min_man_yen"))
        out.append(item)
    missing = [pid for pid in program_ids if pid not in seen]
    if missing:
        known_gaps.append(f"program_not_found:{','.join(missing[:5])}")
    return out


def _fetch_conflicts(
    conn: sqlite3.Connection | None,
    program_ids: list[str],
    known_gaps: list[str],
) -> list[tuple[str, str]]:
    if conn is None or len(program_ids) < 2:
        return []
    if not _table_exists(conn, "am_funding_stack_empirical"):
        known_gaps.append("missing_table:am_funding_stack_empirical")
        return []
    cols = _columns(conn, "am_funding_stack_empirical")
    required = {"program_a_id", "program_b_id", "conflict_flag"}
    if not required.issubset(cols):
        known_gaps.append("missing_column:am_funding_stack_empirical.conflict_shape")
        return []
    id_set = set(program_ids)
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = conn.execute(
            "SELECT program_a_id, program_b_id FROM am_funding_stack_empirical "
            f"WHERE conflict_flag = 1 AND program_a_id IN ({placeholders}) AND program_b_id IN ({placeholders})",
            tuple(program_ids) + tuple(program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        known_gaps.append(f"query_failed:am_funding_stack_empirical:{exc.__class__.__name__}")
        return []
    return [
        (str(r["program_a_id"]), str(r["program_b_id"]))
        for r in rows
        if r["program_a_id"] in id_set and r["program_b_id"] in id_set
    ]


def _estimate_amount(
    programs: list[dict[str, Any]], scenario: ScenarioNumbers | None = None
) -> int:
    if scenario and scenario.capex_yen is not None and scenario.subsidy_rate is not None:
        amount = int(round(scenario.capex_yen * scenario.subsidy_rate))
        if scenario.requested_amount_yen is not None:
            amount = min(amount, scenario.requested_amount_yen)
        return max(0, amount)
    if scenario and scenario.requested_amount_yen is not None:
        return scenario.requested_amount_yen
    return sum(int(p.get("amount_max_yen") or 0) for p in programs)


def _average_probability(
    program_ids: list[str], scores: dict[str, float], adjustment_pct: float = 0.0
) -> float:
    if not program_ids:
        base = _DEFAULT_PROBABILITY
    else:
        values = [scores.get(pid, _DEFAULT_PROBABILITY) for pid in program_ids]
        base = sum(values) / len(values)
    return round(max(0.0, min(1.0, base + adjustment_pct / 100.0)), 4)


def _build_block(
    *,
    program_ids: list[str],
    programs: list[dict[str, Any]],
    scores: dict[str, float],
    conflicts: list[tuple[str, str]],
    scenario: ScenarioNumbers | None = None,
) -> dict[str, Any]:
    probability = _average_probability(
        program_ids,
        scores,
        scenario.probability_adjustment_pct if scenario else 0.0,
    )
    estimated_amount = _estimate_amount(programs, scenario)
    if scenario and scenario.enforce_conflict_penalty and conflicts:
        probability = round(max(0.0, probability - min(0.25, 0.05 * len(conflicts))), 4)
    return {
        "program_count": len(program_ids),
        "matched_program_count": len(programs),
        "estimated_amount_yen": estimated_amount,
        "average_probability": probability,
        "expected_value_yen": int(round(estimated_amount * probability)),
        "conflict_count": len(conflicts),
    }


def _risk_notes(
    *,
    baseline: dict[str, Any],
    after: dict[str, Any],
    conflicts: list[tuple[str, str]],
    scenario: ScenarioNumbers,
    known_gaps: list[str],
) -> list[str]:
    notes: list[str] = []
    if conflicts:
        notes.append(f"{len(conflicts)} hard funding-stack conflict pair(s) were detected.")
    if scenario.deadline_days_delta < 0:
        notes.append(
            "Deadline compression lowers execution margin; verify current application window."
        )
    if (
        scenario.requested_amount_yen
        and baseline["estimated_amount_yen"]
        and scenario.requested_amount_yen > baseline["estimated_amount_yen"]
    ):
        notes.append("Requested amount exceeds the currently known program maximum rollup.")
    if after["average_probability"] < 0.25:
        notes.append("Average probability is low under this deterministic score baseline.")
    if known_gaps:
        notes.append(
            "Sparse substrate: treat numeric output as incomplete until known_gaps are resolved."
        )
    if not notes:
        notes.append("No deterministic conflict or amount-cap warning was triggered.")
    return notes


def _simulate(payload: ScenarioSimulateRequest) -> dict[str, Any]:
    known_gaps: list[str] = []
    normalized = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    if payload.houjin_id and normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": "houjin_id must be 13 digits, with or without T prefix.",
            },
        )
    if not normalized and not payload.program_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_scenario_anchor",
                "field": "houjin_id|program_ids",
                "message": "Either houjin_id or at least one program_ids entry must be supplied.",
            },
        )

    conn = _open_autonomath_ro()
    if conn is None:
        known_gaps.append("autonomath_db_unavailable")

    try:
        houjin_profile = _fetch_houjin_profile(conn, normalized, known_gaps)
        adopted = _fetch_adopted_program_ids(conn, normalized, known_gaps)
        requested_ids = list(dict.fromkeys([*payload.program_ids, *adopted]))[:_MAX_PROGRAMS]
        after_ids = [
            pid for pid in requested_ids if pid not in set(payload.scenario.remove_program_ids)
        ]
        after_ids = list(dict.fromkeys([*after_ids, *payload.scenario.additional_program_ids]))[
            :_MAX_PROGRAMS
        ]

        scores = _fetch_recommended_scores(conn, normalized, known_gaps)
        baseline_programs = _fetch_programs(conn, requested_ids, known_gaps)
        after_programs = _fetch_programs(conn, after_ids, known_gaps)
        baseline_conflicts = _fetch_conflicts(conn, requested_ids, known_gaps)
        after_conflicts = _fetch_conflicts(conn, after_ids, known_gaps)
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    baseline = _build_block(
        program_ids=requested_ids,
        programs=baseline_programs,
        scores=scores,
        conflicts=baseline_conflicts,
    )
    after = _build_block(
        program_ids=after_ids,
        programs=after_programs,
        scores=scores,
        conflicts=after_conflicts,
        scenario=payload.scenario,
    )
    delta = {
        "estimated_amount_yen": after["estimated_amount_yen"] - baseline["estimated_amount_yen"],
        "average_probability": round(
            after["average_probability"] - baseline["average_probability"], 4
        ),
        "expected_value_yen": after["expected_value_yen"] - baseline["expected_value_yen"],
        "conflict_count": after["conflict_count"] - baseline["conflict_count"],
    }

    body: dict[str, Any] = {
        "input": {
            "houjin_id": normalized,
            "program_ids": requested_ids,
            "scenario": payload.scenario.model_dump(),
        },
        "houjin_profile": houjin_profile,
        "baseline": baseline,
        "after": after,
        "delta": delta,
        "risk_notes": _risk_notes(
            baseline=baseline,
            after=after,
            conflicts=after_conflicts,
            scenario=payload.scenario,
            known_gaps=known_gaps,
        ),
        "known_gaps": sorted(set(known_gaps)),
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


@router.post(
    "/scenario/simulate",
    summary="Deterministic funding scenario simulation (NO LLM)",
    description=(
        "Simulates baseline vs after funding scenario metrics for a houjin and/or "
        "program set. The route is pure SQLite + Python, read-only, deterministic, "
        "and degrades to known_gaps on sparse DB substrate."
    ),
)
def post_intel_scenario_simulate(
    payload: Annotated[ScenarioSimulateRequest, Body(...)],
    request: Request,
) -> JSONResponse:
    _t0 = time.perf_counter()
    body = _simulate(payload)
    body["latency_ms"] = int((time.perf_counter() - _t0) * 1000)
    if request is not None and wants_compact(request):
        body = to_compact(body)
    return JSONResponse(content=body)


__all__ = ["router"]
