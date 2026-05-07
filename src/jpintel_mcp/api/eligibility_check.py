"""Dynamic eligibility check linking 行政処分 history to exclusion rules.

R8 (2026-05-07) capability — joins two existing corpora that until now lived
on separate surfaces:

  * ``am_enforcement_detail`` (autonomath.db, 22,258 rows; the row a 法人 lands
    on when it earned a public 行政処分 such as 補助金 exclusion / 業務改善命令 /
    指名停止 / 課徴金 etc.)
  * ``exclusion_rules`` (jpintel.db, 181 rows; the rule book governing how a
    program excludes / requires another program or status).

Existing surfaces stop short of the customer's real question::

    "私 (法人 1234567890123) が過去 5 年に受けた 行政処分 を踏まえて、
     今 申請可能な 補助金 list は?"

The discrete searches require the caller to walk
enforcement → manually map enforcement_kind to exclusion semantics → re-query
programs. This module collapses that fan-out into one POST + one GET pair.

NOTE — read-only / no-LLM. The endpoint never mutates either DB and never
calls a language model. The mapping enforcement_kind → blocking_severity is
encoded as a static rule table in this module (review-able in code review,
matches our LLM-free promise).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.eligibility_check")

router = APIRouter(prefix="/v1/eligibility", tags=["eligibility-check"])

# Severity buckets per ``enforcement_kind``. Drives the program triage:
#   * "blocking": within window → program is *blocked* if any exclusion rule
#                 references the recipient as ineligible.
#   * "warning":  carries reputational risk, surfaces as borderline only.
#   * "informational": logged for the report but does not gate eligibility.
#
# Rationale (per kind, locked 2026-05-07):
#   subsidy_exclude  ┐ direct 補助金 ineligibility (clean-room blocker)
#   grant_refund     ┤
#   license_revoke   ┘
#   contract_suspend - 入札 停止 — affects bid-side surfaces only
#   business_improvement, fine: regulatory but doesn't auto-bar 補助金
#   investigation, other: provisional / unclassified
_BLOCKING_KINDS = frozenset({"subsidy_exclude", "grant_refund", "license_revoke"})
_WARNING_KINDS = frozenset({"contract_suspend", "business_improvement", "fine"})
_INFORMATIONAL_KINDS = frozenset({"investigation", "other"})

_DEFAULT_HISTORY_YEARS = 5
_MAX_HISTORY_YEARS = 20

_DISCLAIMER = (
    "Dynamic eligibility check is a deterministic join of public 行政処分 records "
    "and exclusion rules. Coverage is bounded by published 一次資料 and is not "
    "legal clearance. 最終的な受給可否は所管官庁の公募要領 + 税理士法 §52 / 行政書士法 §1 "
    "に基づく専門家確認を経てください。"
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DynamicCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    houjin_bangou: str = Field(
        ...,
        description=(
            "13-digit 法人番号. T-prefix and hyphens accepted; the handler "
            "normalises to the bare 13-digit form. Sole proprietors should "
            "use the dedicated GET surface — this endpoint requires a 法人."
        ),
        min_length=13,
        max_length=32,
    )
    industry_jsic: str | None = Field(
        default=None,
        description=(
            "Optional JSIC major letter (A..T) used to narrow program "
            "candidates before the rule walk. When omitted, every program "
            "in jpintel.db is considered."
        ),
        min_length=1,
        max_length=2,
    )
    exclude_history_years: int = Field(
        default=_DEFAULT_HISTORY_YEARS,
        ge=1,
        le=_MAX_HISTORY_YEARS,
        description=(
            "Look-back window in years. Default 5 mirrors most 補助金 公募要領 "
            "(過去5年に補助金の不正受給等がない者…)."
        ),
    )
    program_id_hint: list[str] | None = Field(
        default=None,
        description=(
            "Optional pre-filter on programs.unified_id. When present, the "
            "rule walk only enumerates these programs — useful when the "
            "consultant already knows the candidate set."
        ),
        max_length=200,
    )


class EnforcementHit(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enforcement_id: int
    enforcement_kind: str | None
    issuing_authority: str | None
    issuance_date: str
    exclusion_start: str | None
    exclusion_end: str | None
    reason_summary: str | None
    severity_bucket: Literal["blocking", "warning", "informational"]
    source_url: str | None


class ProgramVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    program_id: str
    program_name: str | None
    verdict: Literal["blocked", "borderline", "eligible"]
    rule_ids: list[str]
    reasons: list[str]


class DynamicCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    houjin_bangou: str
    industry_jsic: str | None
    exclude_history_years: int
    enforcement_hits: list[EnforcementHit]
    blocked_programs: list[ProgramVerdict]
    borderline_programs: list[ProgramVerdict]
    eligible_programs: list[ProgramVerdict]
    checked_program_count: int
    checked_rule_count: int
    disclaimer: str = Field(
        default=_DISCLAIMER, alias="_disclaimer", serialization_alias="_disclaimer"
    )


class SingleProgramVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    houjin_bangou: str
    program_id: str
    program_name: str | None
    verdict: Literal["blocked", "borderline", "eligible"]
    rule_ids: list[str]
    reasons: list[str]
    enforcement_hits: list[EnforcementHit]
    disclaimer: str = Field(
        default=_DISCLAIMER, alias="_disclaimer", serialization_alias="_disclaimer"
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _normalize_houjin_bangou(raw: str) -> str | None:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 13:
        return None
    return digits


def _autonomath_db_path() -> str:
    return os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Read-only autonomath.db handle. Returns None when the volume is missing.

    Mirrors the helper in api/eligibility_predicate.py so we share the same
    pin-one-connection-per-request invariant.
    """
    path = _autonomath_db_path()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _classify(kind: str | None) -> Literal["blocking", "warning", "informational"]:
    if not kind:
        return "informational"
    if kind in _BLOCKING_KINDS:
        return "blocking"
    if kind in _WARNING_KINDS:
        return "warning"
    return "informational"


def _fetch_enforcement_hits(
    am_conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    cutoff_iso: str,
) -> list[EnforcementHit]:
    """Pull every am_enforcement_detail row for the houjin since cutoff."""

    sql = """
        SELECT enforcement_id,
               enforcement_kind,
               issuing_authority,
               issuance_date,
               exclusion_start,
               exclusion_end,
               reason_summary,
               source_url
          FROM am_enforcement_detail
         WHERE houjin_bangou = ?
           AND issuance_date >= ?
         ORDER BY issuance_date DESC
    """
    try:
        rows = am_conn.execute(sql, (houjin_bangou, cutoff_iso)).fetchall()
    except sqlite3.OperationalError as exc:
        _log.warning("am_enforcement_detail unavailable: %s", exc)
        return []
    return [
        EnforcementHit(
            enforcement_id=int(r["enforcement_id"]),
            enforcement_kind=r["enforcement_kind"],
            issuing_authority=r["issuing_authority"],
            issuance_date=r["issuance_date"],
            exclusion_start=r["exclusion_start"],
            exclusion_end=r["exclusion_end"],
            reason_summary=r["reason_summary"],
            severity_bucket=_classify(r["enforcement_kind"]),
            source_url=r["source_url"],
        )
        for r in rows
    ]


def _fetch_candidate_programs(
    conn: sqlite3.Connection,
    *,
    industry_jsic: str | None,
    program_id_hint: list[str] | None,
) -> list[tuple[str, str | None]]:
    """Return (unified_id, primary_name) tuples for the candidate set.

    The set is intentionally bounded — the dynamic check is a per-houjin
    triage, not a corpus dump. We cap at 5,000 rows so the rule walk stays
    O(programs * rules) within sub-second budgets.
    """

    where = ["excluded = 0"]
    params: list[Any] = []
    if industry_jsic:
        where.append("UPPER(jsic_major) = UPPER(?)")
        params.append(industry_jsic)
    if program_id_hint:
        placeholders = ",".join("?" * len(program_id_hint))
        where.append(f"unified_id IN ({placeholders})")
        params.extend(program_id_hint)

    where_sql = " AND ".join(where) if where else "1=1"
    sql = (
        f"SELECT unified_id, primary_name FROM programs "
        f"WHERE {where_sql} "
        f"ORDER BY tier IS NULL, tier, unified_id "
        f"LIMIT 5000"
    )
    rows = conn.execute(sql, params).fetchall()
    return [(r["unified_id"], r["primary_name"]) for r in rows]


def _fetch_blocking_rules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Pull exclusion_rules of kinds that gate eligibility outright."""

    return conn.execute(
        "SELECT rule_id, kind, severity, program_a, program_b, program_b_group_json, "
        "       description, source_urls_json, source_notes, "
        "       program_a_uid, program_b_uid "
        "  FROM exclusion_rules "
        " WHERE kind IN ('exclude','absolute','prerequisite','entity_scope_restriction')"
    ).fetchall()


def _rule_targets(row: sqlite3.Row) -> set[str]:
    """Programs / status keys a rule is anchored to (both name + uid forms)."""

    keys: set[str] = set()
    for col in ("program_a", "program_b", "program_a_uid", "program_b_uid"):
        try:
            v = row[col]
        except (IndexError, KeyError):
            v = None
        if v:
            keys.add(str(v))
    raw = row["program_b_group_json"]
    if raw:
        try:
            import json as _json

            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                keys.update(str(x) for x in parsed if x)
        except Exception:  # noqa: BLE001
            pass
    return keys


def _walk_eligibility(
    *,
    candidates: list[tuple[str, str | None]],
    rules: list[sqlite3.Row],
    enforcement_hits: list[EnforcementHit],
) -> tuple[list[ProgramVerdict], list[ProgramVerdict], list[ProgramVerdict]]:
    """Triage the candidate set against the rule set + enforcement hits."""

    blocking_count = sum(1 for h in enforcement_hits if h.severity_bucket == "blocking")
    warning_count = sum(1 for h in enforcement_hits if h.severity_bucket == "warning")
    has_blocking = blocking_count > 0
    has_warning = warning_count > 0

    # Pre-build name→uid lookup so a rule referencing primary_name can match a
    # candidate whose key is unified_id (and vice-versa).
    name_to_uid: dict[str, str] = {pid: pid for pid, _ in candidates}
    for pid, name in candidates:
        if name:
            name_to_uid[name] = pid

    blocked: list[ProgramVerdict] = []
    borderline: list[ProgramVerdict] = []
    eligible: list[ProgramVerdict] = []

    for unified_id, primary_name in candidates:
        keys = {unified_id}
        if primary_name:
            keys.add(primary_name)

        matched_rule_ids: list[str] = []
        reasons: list[str] = []
        for rule in rules:
            targets = _rule_targets(rule)
            if not targets & keys:
                continue
            kind = (rule["kind"] or "").lower()
            severity = (rule["severity"] or "").lower()
            description = rule["description"] or ""
            if has_blocking and kind in {"exclude", "absolute", "entity_scope_restriction"}:
                matched_rule_ids.append(rule["rule_id"])
                reasons.append(
                    f"rule={rule['rule_id']} kind={kind} severity={severity}: {description}"
                )
            elif has_warning and severity == "critical":
                matched_rule_ids.append(rule["rule_id"])
                reasons.append(
                    f"rule={rule['rule_id']} kind={kind} severity={severity}: "
                    f"warning-grade enforcement on file — manual review."
                )

        verdict_obj = ProgramVerdict(
            program_id=unified_id,
            program_name=primary_name,
            verdict="eligible",
            rule_ids=[],
            reasons=[],
        )
        if matched_rule_ids and has_blocking:
            blocked.append(
                ProgramVerdict(
                    program_id=unified_id,
                    program_name=primary_name,
                    verdict="blocked",
                    rule_ids=matched_rule_ids,
                    reasons=reasons,
                )
            )
        elif matched_rule_ids and has_warning:
            borderline.append(
                ProgramVerdict(
                    program_id=unified_id,
                    program_name=primary_name,
                    verdict="borderline",
                    rule_ids=matched_rule_ids,
                    reasons=reasons,
                )
            )
        elif has_blocking:
            # No rule matched this program but the houjin still has blocking
            # history — surface as borderline to force documentation.
            borderline.append(
                ProgramVerdict(
                    program_id=unified_id,
                    program_name=primary_name,
                    verdict="borderline",
                    rule_ids=[],
                    reasons=[
                        "houjin has blocking enforcement history within the "
                        "look-back window; verify program-side 公募要領 "
                        "exclusion clauses manually."
                    ],
                )
            )
        else:
            eligible.append(verdict_obj)

    return blocked, borderline, eligible


def _cutoff_iso(years: int) -> str:
    today = _dt.date.today()
    try:
        cutoff = today.replace(year=today.year - years)
    except ValueError:
        # Feb-29 corner case
        cutoff = today.replace(month=2, day=28, year=today.year - years)
    return cutoff.isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/dynamic_check",
    response_model=DynamicCheckResponse,
    summary="Dynamic eligibility check joining 行政処分 history with exclusion rules",
    responses={
        **COMMON_ERROR_RESPONSES,
        503: {
            "model": ErrorEnvelope,
            "description": (
                "autonomath.db (am_enforcement_detail) unavailable on this "
                "deployment — eligibility verdict cannot be produced."
            ),
        },
    },
)
def dynamic_check(
    payload: DynamicCheckRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Triage every program in jpintel.db against this 法人's 行政処分 history."""

    houjin = _normalize_houjin_bangou(payload.houjin_bangou)
    if houjin is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "houjin_bangou must contain exactly 13 digits",
        )
    cutoff = _cutoff_iso(payload.exclude_history_years)

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "am_enforcement_detail corpus unavailable",
        )
    try:
        hits = _fetch_enforcement_hits(
            am_conn,
            houjin_bangou=houjin,
            cutoff_iso=cutoff,
        )
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    candidates = _fetch_candidate_programs(
        conn,
        industry_jsic=payload.industry_jsic,
        program_id_hint=payload.program_id_hint,
    )
    rules = _fetch_blocking_rules(conn)
    blocked, borderline, eligible = _walk_eligibility(
        candidates=candidates,
        rules=rules,
        enforcement_hits=hits,
    )

    log_usage(
        conn,
        ctx,
        "eligibility.dynamic_check",
        params={
            "houjin_bangou": houjin,
            "industry_jsic": payload.industry_jsic,
            "exclude_history_years": payload.exclude_history_years,
            "candidate_count": len(candidates),
            "rule_count": len(rules),
            "hit_count": len(hits),
        },
        result_count=len(blocked) + len(borderline) + len(eligible),
        strict_metering=True,
    )

    body = DynamicCheckResponse(
        houjin_bangou=houjin,
        industry_jsic=payload.industry_jsic,
        exclude_history_years=payload.exclude_history_years,
        enforcement_hits=hits,
        blocked_programs=blocked,
        borderline_programs=borderline,
        eligible_programs=eligible,
        checked_program_count=len(candidates),
        checked_rule_count=len(rules),
    ).model_dump(mode="json", by_alias=True)
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.get(
    "/programs/{program_id}/eligibility_for/{houjin_bangou}",
    response_model=SingleProgramVerdict,
    summary="Single-program eligibility for one 法人 (deterministic verdict)",
    responses={
        **COMMON_ERROR_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": "program_id unknown — verify via /v1/programs/search.",
        },
        503: {
            "model": ErrorEnvelope,
            "description": "am_enforcement_detail corpus unavailable.",
        },
    },
)
def eligibility_for(
    program_id: Annotated[
        str,
        PathParam(
            description="programs.unified_id — discoverable via /v1/programs/search.",
            min_length=4,
            max_length=64,
        ),
    ],
    houjin_bangou: Annotated[
        str,
        PathParam(
            description="13-digit 法人番号. T-prefix / hyphens accepted.",
            min_length=13,
            max_length=32,
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    exclude_history_years: int = _DEFAULT_HISTORY_YEARS,
) -> JSONResponse:
    """Resolve eligibility for one (program, 法人) pair."""

    houjin = _normalize_houjin_bangou(houjin_bangou)
    if houjin is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "houjin_bangou must contain exactly 13 digits",
        )
    if exclude_history_years < 1 or exclude_history_years > _MAX_HISTORY_YEARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"exclude_history_years must be in [1, {_MAX_HISTORY_YEARS}]",
        )

    prog_row = conn.execute(
        "SELECT unified_id, primary_name FROM programs WHERE unified_id = ?",
        (program_id,),
    ).fetchone()
    if prog_row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"program not found: {program_id}",
        )

    cutoff = _cutoff_iso(exclude_history_years)
    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "am_enforcement_detail corpus unavailable",
        )
    try:
        hits = _fetch_enforcement_hits(
            am_conn,
            houjin_bangou=houjin,
            cutoff_iso=cutoff,
        )
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    rules = _fetch_blocking_rules(conn)
    blocked, borderline, eligible = _walk_eligibility(
        candidates=[(prog_row["unified_id"], prog_row["primary_name"])],
        rules=rules,
        enforcement_hits=hits,
    )

    if blocked:
        verdict = blocked[0]
    elif borderline:
        verdict = borderline[0]
    else:
        verdict = eligible[0]

    log_usage(
        conn,
        ctx,
        "eligibility.for_pair",
        params={
            "program_id": program_id,
            "houjin_bangou": houjin,
            "exclude_history_years": exclude_history_years,
        },
        strict_metering=True,
    )

    body = SingleProgramVerdict(
        houjin_bangou=houjin,
        program_id=verdict.program_id,
        program_name=verdict.program_name,
        verdict=verdict.verdict,
        rule_ids=verdict.rule_ids,
        reasons=verdict.reasons,
        enforcement_hits=hits,
    ).model_dump(mode="json", by_alias=True)
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


__all__ = ["router"]
