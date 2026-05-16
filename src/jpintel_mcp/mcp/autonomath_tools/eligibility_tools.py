"""eligibility_tools — MCP wrappers for the R8 dynamic eligibility check.

Mirrors :mod:`jpintel_mcp.api.eligibility_check` so an MCP-only customer
agent can answer the same question without going through HTTP.

Two tools are exposed::

  dynamic_eligibility_check_am(houjin_bangou, industry_jsic=None,
                               exclude_history_years=5,
                               program_id_hint=None)
  → blocked / borderline / eligible verdicts for every program in
    jpintel.db (or the hinted subset) given the houjin's 行政処分
    history within the look-back window.

  program_eligibility_for_houjin_am(program_id, houjin_bangou,
                                    exclude_history_years=5)
  → single (program, houjin) verdict + reasons + enforcement hits.

Pure SQLite; no LLM. Both gated behind ``AUTONOMATH_ELIGIBILITY_CHECK_ENABLED``
(default ON) on top of the global ``AUTONOMATH_ENABLED`` env-gate so the
operator can flip them off without redeploy.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.api.eligibility_check import (
    _DEFAULT_HISTORY_YEARS,
    _MAX_HISTORY_YEARS,
    _cutoff_iso,
    _fetch_blocking_rules,
    _fetch_candidate_programs,
    _fetch_enforcement_hits,
    _normalize_houjin_bangou,
    _open_autonomath_ro,
    _walk_eligibility,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.eligibility_check")

_ENABLED = (
    get_flag("JPCITE_ELIGIBILITY_CHECK_ENABLED", "AUTONOMATH_ELIGIBILITY_CHECK_ENABLED", "1") == "1"
)

_DISCLAIMER = (
    "Dynamic eligibility check is a deterministic join of public 行政処分 records "
    "and exclusion rules. Coverage is bounded by published 一次資料 and is not "
    "legal clearance. 最終的な受給可否は所管官庁の公募要領 + 税理士法 §52 / 行政書士法 §1 "
    "に基づく専門家確認を経てください。"
)


def _open_jpintel_ro() -> sqlite3.Connection | None:
    path = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", str(settings.db_path))
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only=ON")
    return conn


def _verdicts_to_dict(verdicts: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "program_id": v.program_id,
            "program_name": v.program_name,
            "verdict": v.verdict,
            "rule_ids": v.rule_ids,
            "reasons": v.reasons,
        }
        for v in verdicts
    ]


def _hits_to_dict(hits: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "enforcement_id": h.enforcement_id,
            "enforcement_kind": h.enforcement_kind,
            "issuing_authority": h.issuing_authority,
            "issuance_date": h.issuance_date,
            "exclusion_start": h.exclusion_start,
            "exclusion_end": h.exclusion_end,
            "reason_summary": h.reason_summary,
            "severity_bucket": h.severity_bucket,
            "source_url": h.source_url,
        }
        for h in hits
    ]


def _dynamic_check_impl(
    *,
    houjin_bangou: str,
    industry_jsic: str | None,
    exclude_history_years: int,
    program_id_hint: list[str] | None,
) -> dict[str, Any]:
    houjin = _normalize_houjin_bangou(houjin_bangou)
    if houjin is None:
        return make_error(
            code="out_of_range",
            message="houjin_bangou must contain exactly 13 digits.",
            hint="T-prefix and hyphens are stripped; ensure 13 numeric digits remain.",
            field="houjin_bangou",
        )
    if not (1 <= exclude_history_years <= _MAX_HISTORY_YEARS):
        return make_error(
            code="out_of_range",
            message=(
                f"exclude_history_years must be in [1, {_MAX_HISTORY_YEARS}] "
                f"(received {exclude_history_years})."
            ),
            field="exclude_history_years",
        )

    cutoff = _cutoff_iso(exclude_history_years)
    am_conn = _open_autonomath_ro()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="am_enforcement_detail unavailable on this volume.",
            hint="Check AUTONOMATH_DB_PATH and that the volume is mounted.",
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

    jp_conn = _open_jpintel_ro()
    if jp_conn is None:
        return make_error(
            code="db_unavailable",
            message="jpintel.db unavailable on this volume.",
            hint="Check JPINTEL_DB_PATH and that the volume is mounted.",
        )
    try:
        candidates = _fetch_candidate_programs(
            jp_conn,
            industry_jsic=industry_jsic,
            program_id_hint=program_id_hint,
        )
        rules = _fetch_blocking_rules(jp_conn)
    finally:
        with contextlib.suppress(Exception):
            jp_conn.close()

    blocked, borderline, eligible = _walk_eligibility(
        candidates=candidates,
        rules=rules,
        enforcement_hits=hits,
    )

    return {
        "houjin_bangou": houjin,
        "industry_jsic": industry_jsic,
        "exclude_history_years": exclude_history_years,
        "enforcement_hits": _hits_to_dict(hits),
        "blocked_programs": _verdicts_to_dict(blocked),
        "borderline_programs": _verdicts_to_dict(borderline),
        "eligible_programs": _verdicts_to_dict(eligible),
        "checked_program_count": len(candidates),
        "checked_rule_count": len(rules),
        "_disclaimer": _DISCLAIMER,
    }


def _single_program_impl(
    *,
    program_id: str,
    houjin_bangou: str,
    exclude_history_years: int,
) -> dict[str, Any]:
    houjin = _normalize_houjin_bangou(houjin_bangou)
    if houjin is None:
        return make_error(
            code="out_of_range",
            message="houjin_bangou must contain exactly 13 digits.",
            field="houjin_bangou",
        )
    if not (1 <= exclude_history_years <= _MAX_HISTORY_YEARS):
        return make_error(
            code="out_of_range",
            message=(
                f"exclude_history_years must be in [1, {_MAX_HISTORY_YEARS}] "
                f"(received {exclude_history_years})."
            ),
            field="exclude_history_years",
        )

    jp_conn = _open_jpintel_ro()
    if jp_conn is None:
        return make_error(
            code="db_unavailable",
            message="jpintel.db unavailable on this volume.",
        )
    try:
        prog_row = jp_conn.execute(
            "SELECT unified_id, primary_name FROM programs WHERE unified_id = ?",
            (program_id,),
        ).fetchone()
        if prog_row is None:
            return make_error(
                code="no_matching_records",
                message=f"program not found: {program_id}",
                hint="Verify program_id via search_programs / list_open_programs.",
                field="program_id",
            )
        rules = _fetch_blocking_rules(jp_conn)
    finally:
        with contextlib.suppress(Exception):
            jp_conn.close()

    cutoff = _cutoff_iso(exclude_history_years)
    am_conn = _open_autonomath_ro()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="am_enforcement_detail unavailable on this volume.",
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

    return {
        "houjin_bangou": houjin,
        "program_id": verdict.program_id,
        "program_name": verdict.program_name,
        "verdict": verdict.verdict,
        "rule_ids": verdict.rule_ids,
        "reasons": verdict.reasons,
        "enforcement_hits": _hits_to_dict(hits),
        "_disclaimer": _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def dynamic_eligibility_check_am(
        houjin_bangou: Annotated[
            str,
            Field(
                description=(
                    "13-digit 法人番号. T-prefix / hyphens accepted; the tool "
                    "normalises to bare 13-digit form. Sole proprietors are "
                    "outside scope (法人番号 を持たないため)."
                ),
                min_length=13,
                max_length=32,
            ),
        ],
        industry_jsic: Annotated[
            str | None,
            Field(
                description=(
                    "Optional JSIC major letter (A..T) used to narrow program "
                    "candidates before the rule walk. Omit to consider every "
                    "program in jpintel.db."
                ),
                min_length=1,
                max_length=2,
            ),
        ] = None,
        exclude_history_years: Annotated[
            int,
            Field(
                ge=1,
                le=_MAX_HISTORY_YEARS,
                description=(
                    "Look-back window in years. Default 5 mirrors most "
                    "公募要領 (過去5年に補助金の不正受給等がない者…)."
                ),
            ),
        ] = _DEFAULT_HISTORY_YEARS,
        program_id_hint: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional pre-filter on programs.unified_id — useful when "
                    "the consultant already knows the candidate set. Max 200."
                ),
                max_length=200,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[ELIGIBILITY-DYNAMIC-AM] Joins one houjin's 行政処分 history (am_enforcement_detail) with exclusion_rules to triage every program in jpintel.db into blocked / borderline / eligible verdicts. NO LLM. Returns `_disclaimer`. Verify primary source (公募要領) before applying.

        WHAT:
          1. SELECT * FROM am_enforcement_detail WHERE houjin_bangou = ?
             AND issuance_date >= today - exclude_history_years.
          2. Bucket each hit by enforcement_kind:
             * blocking  = subsidy_exclude / grant_refund / license_revoke
             * warning   = contract_suspend / business_improvement / fine
             * informational = investigation / other
          3. SELECT exclusion_rules WHERE kind IN (exclude / absolute /
             prerequisite / entity_scope_restriction).
          4. For every candidate program (jpintel.db, optional industry_jsic +
             program_id_hint filters), match against rules whose program_a /
             program_b / program_b_group references it. If the houjin has
             ≥1 blocking hit and the rule is exclude/absolute/scope → blocked.
             Warning hits + critical-severity rule → borderline. Otherwise
             eligible.

        WHEN:
          - 「弊社 (法人番号 1234567890123) は今 申請可能な 補助金 list が欲しい」
          - 補助金 consultant の pre-screen (受任前 due diligence)
          - 中小企業 が 自社 eligibility を 一括 評価

        WHEN NOT:
          - 個別の program × 法人 だけを問う → program_eligibility_for_houjin_am
          - 公募要領 解釈そのもの (記述抽出は search_programs / get_program_abstract)
          - 反社チェック / 信用情報 — am_enforcement_detail は 公表 行政処分 のみ

        RETURNS:
          {
            houjin_bangou, industry_jsic, exclude_history_years,
            enforcement_hits: [...],
            blocked_programs: [...],
            borderline_programs: [...],
            eligible_programs: [...],
            checked_program_count, checked_rule_count,
            _disclaimer: str,
          }

        Errors return the canonical error envelope (db_unavailable /
        invalid_argument / out_of_range).
        """

        try:
            return _dynamic_check_impl(
                houjin_bangou=houjin_bangou,
                industry_jsic=industry_jsic,
                exclude_history_years=exclude_history_years,
                program_id_hint=list(program_id_hint) if program_id_hint else None,
            )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            logger.exception("dynamic_eligibility_check_am query failed")
            return make_error(
                code="db_unavailable",
                message=str(exc),
                hint="autonomath.db / jpintel.db unreachable; retry shortly.",
            )

    @mcp.tool(annotations=_READ_ONLY)
    def program_eligibility_for_houjin_am(
        program_id: Annotated[
            str,
            Field(
                description=(
                    "programs.unified_id. Discover via search_programs / list_open_programs."
                ),
                min_length=4,
                max_length=64,
            ),
        ],
        houjin_bangou: Annotated[
            str,
            Field(
                description=("13-digit 法人番号. T-prefix / hyphens accepted."),
                min_length=13,
                max_length=32,
            ),
        ],
        exclude_history_years: Annotated[
            int,
            Field(
                ge=1,
                le=_MAX_HISTORY_YEARS,
                description="Look-back window in years (default 5).",
            ),
        ] = _DEFAULT_HISTORY_YEARS,
    ) -> dict[str, Any]:
        """[ELIGIBILITY-PAIR-AM] Resolves eligibility for one (program, 法人) pair by joining am_enforcement_detail with exclusion_rules. NO LLM. Returns `_disclaimer`. Verify primary source.

        Same algorithm as dynamic_eligibility_check_am, scoped to a single
        program. Use this when the caller already has a program_id (e.g. from
        search_programs) and wants the deterministic verdict for one
        prospect.

        Errors: program_id unknown → no_matching_records; missing volume →
        db_unavailable; bad inputs → invalid_argument / out_of_range.
        """

        try:
            return _single_program_impl(
                program_id=program_id,
                houjin_bangou=houjin_bangou,
                exclude_history_years=exclude_history_years,
            )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            logger.exception("program_eligibility_for_houjin_am query failed")
            return make_error(
                code="db_unavailable",
                message=str(exc),
                hint="autonomath.db / jpintel.db unreachable; retry shortly.",
            )


__all__ = [
    "_dynamic_check_impl",
    "_single_program_impl",
]
