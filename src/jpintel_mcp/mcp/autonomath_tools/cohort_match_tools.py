"""cohort_match_tools — R8 cohort matcher (採択事例 × 業種 × 規模 × 地域).

Single MCP tool ``case_cohort_match_am`` (and a parallel REST endpoint
``POST /v1/cases/cohort_match`` wired in ``api/case_cohort_match.py``)
that answers the central jpcite question:

    「私と同業同規模同地域の採択企業はどの制度に通ったか?」

Input is a coarse 4-axis cohort filter — JSIC industry prefix, employee
range, revenue range, prefecture — and the response bundles:

  * top N matching case_studies rows (jpintel.db, 2,286 採択事例)
  * top N matching jpi_adoption_records rows (autonomath.db, 201,845
    V4-absorbed METI/MAFF 採択結果)
  * a per-program rollup: program_used / appearance_count /
    average_amount_yen / cohort_share / case_ids
  * a summary band: total_cases, distinct_programs, mean / median amount

The tool stitches across the two SQLite files **without** ATTACH DATABASE
— each side is opened read-only via the existing connection helpers and
the results are merged in Python. We never JOIN across files.

Sparsity caveats are surfaced in the response (`sparsity_notes`) so a
caller never confuses "0 amount rows" with "0 cohort matches" — only
~1.9% of `case_studies.total_subsidy_received_yen` is populated and
0% of `jpi_adoption_records.amount_granted_yen` carries a value (V4
absorbed records are name-only).

NO LLM. Single ¥3/req billing unit. §52 / §47条の2 / 行政書士法 §1
disclaimer envelope on every result — output is information retrieval,
not 申請代理 / 税務助言 / 経営判断.
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import statistics
from collections import defaultdict
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.cohort_match")

_ENABLED = get_flag("JPCITE_COHORT_MATCH_ENABLED", "AUTONOMATH_COHORT_MATCH_ENABLED", "1") == "1"


_DISCLAIMER_COHORT_MATCH = (
    "本 response は jpintel case_studies + autonomath jpi_adoption_records 一次資料の "
    "cohort-fence aggregation で、税務助言 (税理士法 §52)・監査調書 (公認会計士法 §47条の2)・"
    "申請代理 (行政書士法 §1)・経営判断 (中小企業診断士の経営助言) の代替ではありません。"
    "業種 (JSIC) / 規模 / 地域 のマッチングは公表データに基づく heuristic であり、"
    "個別案件の採択可否を保証するものではありません。各 program の適合可否は申請要領を "
    "一次資料 (source_url) で必ずご確認ください。"
)


def _open_jpintel_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only via file URI.

    Tests inject ``JPINTEL_DB_PATH`` to a tmp seeded fixture; production
    boots with ``data/jpintel.db``. Soft-fail returns a make_error envelope
    when the file is missing — callers (REST + MCP) propagate as-is.
    """
    db_path = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_case_studies", "search_acceptance_stats_am"],
        )


def _open_autonomath_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only. Soft-fail to error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_case_studies"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_case_studies"],
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _validate_range(
    raw: list[int] | tuple[int, int] | None,
    *,
    field: str,
    minimum: int = 0,
) -> tuple[int | None, int | None, dict[str, Any] | None]:
    """Validate a [low, high] range; either bound may be None to skip.

    Returns (low, high, error_envelope_or_None). Range is rejected when
    explicit low > high. Callers swap the order rather than guess.
    """
    if raw is None:
        return None, None, None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return (
            None,
            None,
            make_error(
                code="invalid_enum",
                message=f"{field} must be a 2-element [low, high] range, got {raw!r}.",
                field=field,
            ),
        )
    low, high = raw[0], raw[1]
    if low is not None and (not isinstance(low, int) or low < minimum):
        return (
            None,
            None,
            make_error(
                code="out_of_range",
                message=f"{field}[0] must be >= {minimum}, got {low!r}.",
                field=field,
            ),
        )
    if high is not None and (not isinstance(high, int) or high < minimum):
        return (
            None,
            None,
            make_error(
                code="out_of_range",
                message=f"{field}[1] must be >= {minimum}, got {high!r}.",
                field=field,
            ),
        )
    if low is not None and high is not None and low > high:
        return (
            None,
            None,
            make_error(
                code="out_of_range",
                message=f"{field} low ({low}) > high ({high}).",
                field=field,
            ),
        )
    return low, high, None


def _fetch_case_studies_cohort(
    industry_jsic: str | None,
    employee_low: int | None,
    employee_high: int | None,
    revenue_low: int | None,
    revenue_high: int | None,
    prefecture: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull case_studies rows matching the 4-axis cohort filter."""
    conn_or_err = _open_jpintel_ro()
    if isinstance(conn_or_err, dict):
        return []
    conn = conn_or_err

    where: list[str] = []
    params: list[Any] = []

    if industry_jsic:
        where.append("industry_jsic LIKE ?")
        params.append(f"{industry_jsic}%")

    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)

    if employee_low is not None:
        where.append("(employees IS NULL OR employees >= ?)")
        params.append(employee_low)
    if employee_high is not None:
        where.append("(employees IS NULL OR employees <= ?)")
        params.append(employee_high)

    if revenue_low is not None:
        where.append("(capital_yen IS NULL OR capital_yen >= ?)")
        params.append(revenue_low)
    if revenue_high is not None:
        where.append("(capital_yen IS NULL OR capital_yen <= ?)")
        params.append(revenue_high)

    where_sql = " AND ".join(where) if where else "1=1"

    sql = (  # nosec B608
        "SELECT case_id, company_name, houjin_bangou, prefecture, municipality, "
        "       industry_jsic, industry_name, employees, capital_yen, founded_year, "
        "       case_title, case_summary, programs_used_json, "
        "       total_subsidy_received_yen, publication_date, source_url, confidence "
        "  FROM case_studies "
        f" WHERE {where_sql} "
        " ORDER BY publication_date DESC, case_id "
        " LIMIT ? "
    )
    params.append(int(limit))

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("cohort_match case_studies fetch failed: %s", exc)
        rows = []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            programs_used = json.loads(r["programs_used_json"] or "[]")
            if not isinstance(programs_used, list):
                programs_used = []
        except (json.JSONDecodeError, TypeError):
            programs_used = []
        out.append(
            {
                "case_id": r["case_id"],
                "company_name": r["company_name"],
                "houjin_bangou": r["houjin_bangou"],
                "prefecture": r["prefecture"],
                "municipality": r["municipality"],
                "industry_jsic": r["industry_jsic"],
                "industry_name": r["industry_name"],
                "employees": r["employees"],
                "capital_yen": r["capital_yen"],
                "founded_year": r["founded_year"],
                "case_title": r["case_title"],
                "case_summary": r["case_summary"],
                "programs_used": [str(p) for p in programs_used if p is not None],
                "total_subsidy_received_yen": r["total_subsidy_received_yen"],
                "publication_date": r["publication_date"],
                "source_url": r["source_url"],
                "confidence": r["confidence"],
            }
        )
    return out


def _fetch_adoption_records_cohort(
    industry_jsic: str | None,
    prefecture: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull jpi_adoption_records rows matching the cohort filter (2 axes only)."""
    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return []
    conn = conn_or_err

    where: list[str] = []
    params: list[Any] = []

    if industry_jsic:
        where.append("industry_jsic_medium LIKE ?")
        params.append(f"{industry_jsic}%")

    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)

    where_sql = " AND ".join(where) if where else "1=1"

    sql = (  # nosec B608
        "SELECT id, houjin_bangou, program_id, program_id_hint, program_name_raw, "
        "       company_name_raw, round_label, round_number, announced_at, "
        "       prefecture, municipality, project_title, industry_raw, "
        "       industry_jsic_medium, amount_granted_yen, amount_project_total_yen, "
        "       source_url, fetched_at, confidence "
        "  FROM jpi_adoption_records "
        f" WHERE {where_sql} "
        " ORDER BY announced_at DESC, id "
        " LIMIT ? "
    )
    params.append(int(limit))

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("cohort_match adoption_records fetch failed: %s", exc)
        rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "adoption_id": r["id"],
                "houjin_bangou": r["houjin_bangou"],
                "program_id": r["program_id"],
                "program_id_hint": r["program_id_hint"],
                "program_name_raw": r["program_name_raw"],
                "company_name_raw": r["company_name_raw"],
                "round_label": r["round_label"],
                "round_number": r["round_number"],
                "announced_at": r["announced_at"],
                "prefecture": r["prefecture"],
                "municipality": r["municipality"],
                "project_title": r["project_title"],
                "industry_raw": r["industry_raw"],
                "industry_jsic_medium": r["industry_jsic_medium"],
                "amount_granted_yen": r["amount_granted_yen"],
                "amount_project_total_yen": r["amount_project_total_yen"],
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
                "confidence": r["confidence"],
            }
        )
    return out


def _build_program_rollup(
    case_studies: list[dict[str, Any]],
    adoption_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate the cohort by program — the central matcher value."""
    rollup: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label_candidates": defaultdict(int),
            "case_study_count": 0,
            "adoption_record_count": 0,
            "amount_samples": [],
            "example_case_ids": [],
        }
    )
    total_rows = 0

    for cs in case_studies:
        for prog in cs.get("programs_used", []):
            if not prog or not isinstance(prog, str):
                continue
            key = prog.strip().casefold()
            if not key:
                continue
            slot = rollup[key]
            slot["label_candidates"][prog.strip()] += 1
            slot["case_study_count"] += 1
            amt = cs.get("total_subsidy_received_yen")
            if amt is not None and amt > 0:
                slot["amount_samples"].append(int(amt))
            cid = cs.get("case_id")
            if cid and len(slot["example_case_ids"]) < 3:
                slot["example_case_ids"].append(cid)
            total_rows += 1

    for ar in adoption_records:
        prog_label = ar.get("program_name_raw") or ar.get("program_id_hint") or ""
        if not prog_label:
            continue
        key = str(prog_label).strip().casefold()
        if not key:
            continue
        slot = rollup[key]
        slot["label_candidates"][str(prog_label).strip()] += 1
        slot["adoption_record_count"] += 1
        amt = ar.get("amount_granted_yen")
        if amt is not None and amt > 0:
            slot["amount_samples"].append(int(amt))
        total_rows += 1

    out: list[dict[str, Any]] = []
    for slot in rollup.values():
        label_candidates = slot["label_candidates"]
        canonical_label = max(label_candidates.items(), key=lambda kv: (kv[1], kv[0]))[0]
        appearance_count = slot["case_study_count"] + slot["adoption_record_count"]
        amount_samples = slot["amount_samples"]
        avg_amount = (
            int(round(sum(amount_samples) / len(amount_samples))) if amount_samples else None
        )
        cohort_share = (appearance_count / total_rows) if total_rows else 0.0
        out.append(
            {
                "program_label": canonical_label,
                "appearance_count": appearance_count,
                "case_study_count": slot["case_study_count"],
                "adoption_record_count": slot["adoption_record_count"],
                "avg_amount_yen": avg_amount,
                "cohort_share": round(cohort_share, 4),
                "example_case_ids": list(slot["example_case_ids"]),
            }
        )
    out.sort(key=lambda r: (-r["appearance_count"], r["program_label"]))
    return out


def _build_summary(
    case_studies: list[dict[str, Any]],
    adoption_records: list[dict[str, Any]],
    program_rollup: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute cohort-level summary numbers (cheap, zero LLM)."""
    amounts: list[int] = []
    for cs in case_studies:
        a = cs.get("total_subsidy_received_yen")
        if a is not None and a > 0:
            amounts.append(int(a))
    for ar in adoption_records:
        a = ar.get("amount_granted_yen")
        if a is not None and a > 0:
            amounts.append(int(a))

    if amounts:
        mean_yen: int | None = int(round(statistics.fmean(amounts)))
        median_yen: int | None = int(statistics.median(amounts))
        min_yen: int | None = min(amounts)
        max_yen: int | None = max(amounts)
    else:
        mean_yen = median_yen = min_yen = max_yen = None

    return {
        "case_study_count": len(case_studies),
        "adoption_record_count": len(adoption_records),
        "total_cohort_rows": len(case_studies) + len(adoption_records),
        "distinct_programs": len(program_rollup),
        "amount_yen_with_value": len(amounts),
        "amount_yen_mean": mean_yen,
        "amount_yen_median": median_yen,
        "amount_yen_min": min_yen,
        "amount_yen_max": max_yen,
    }


_SPARSITY_NOTES = [
    "case_studies.total_subsidy_received_yen is populated on ~1.9% of "
    "rows (4 / 2,286 — ministries publish 採択 without 交付額). "
    "Most matched cases will show null for amount.",
    "jpi_adoption_records.amount_granted_yen is currently 0/201,845 "
    "populated. V4 absorption captured 採択企業 + program identity but "
    "not 交付額; size filtering on this side is by JSIC + prefecture only.",
    "case_studies revenue_yen is approximated via capital_yen because "
    "case_studies has no explicit revenue column. Rows missing capital_yen "
    "are kept (NULL-tolerant filter) rather than silently dropped.",
    "industry_jsic prefix match: 'A' matches every JSIC code starting "
    "with A (大分類); 'E29' matches the 中分類 食料品製造業. Mixed-grain "
    "case_studies (some 1-letter, some 4-digit) are both reachable.",
]


# R8 BUGHUNT (2026-05-07): canonical data_quality envelope. Same upstream
# substrate as benchmark_tools — values audited live on autonomath.db
# 2026-05-07. Re-probe on substrate rebuild.
_DATA_QUALITY_COHORT: dict[str, Any] = {
    "substrate": "jpi_adoption_records (201,845) + case_studies (2,286)",
    "adoption_records_total": 201_845,
    "case_studies_total": 2_286,
    "amount_granted_yen_populated": 0,
    "case_studies_amount_populated": 4,
    "orphan_houjin_in_adoption_records": 357,
    "license_unknown_pct": 0.83,
    "license_unknown_count": 805,
    "caveat": (
        "amount_granted_yen 0% populated (jpi_adoption_records side); 357 "
        "houjin_bangou orphans pending gBiz delta self-heal; 805 / 97,272 "
        "am_source rows still license='unknown'. Aggregates are directional, "
        "not authoritative."
    ),
}


def case_cohort_match_impl(
    industry_jsic: str | None = None,
    employee_count_range: list[int] | tuple[int, int] | None = None,
    revenue_yen_range: list[int] | tuple[int, int] | None = None,
    prefecture: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Implementation entry — composes the cohort-match response envelope."""
    limit = max(1, min(100, int(limit)))

    emp_low, emp_high, emp_err = _validate_range(
        list(employee_count_range) if employee_count_range is not None else None,
        field="employee_count_range",
    )
    if emp_err is not None:
        return emp_err

    rev_low, rev_high, rev_err = _validate_range(
        list(revenue_yen_range) if revenue_yen_range is not None else None,
        field="revenue_yen_range",
    )
    if rev_err is not None:
        return rev_err

    industry_jsic_norm = industry_jsic.strip() if industry_jsic else None
    prefecture_norm = prefecture.strip() if prefecture else None

    case_studies = _fetch_case_studies_cohort(
        industry_jsic=industry_jsic_norm,
        employee_low=emp_low,
        employee_high=emp_high,
        revenue_low=rev_low,
        revenue_high=rev_high,
        prefecture=prefecture_norm,
        limit=limit,
    )
    adoption_records = _fetch_adoption_records_cohort(
        industry_jsic=industry_jsic_norm,
        prefecture=prefecture_norm,
        limit=limit,
    )
    program_rollup = _build_program_rollup(case_studies, adoption_records)
    summary = _build_summary(case_studies, adoption_records, program_rollup)

    next_calls: list[dict[str, Any]] = []
    if program_rollup:
        top_program = program_rollup[0]["program_label"]
        next_calls.append(
            {
                "tool": "search_case_studies",
                "args": {"q": top_program, "limit": 50},
                "rationale": (
                    f"Top-cohort program is {top_program!r}; fetch the full "
                    "case_studies set (with summary text) for prior-art reading."
                ),
                "compound_mult": 1.5,
            }
        )
        next_calls.append(
            {
                "tool": "search_acceptance_stats_am",
                "args": {"program_name": top_program},
                "rationale": (
                    "Pair the cohort's most common program with its 採択率 "
                    "history to size the realistic application odds."
                ),
                "compound_mult": 1.4,
            }
        )
    if industry_jsic_norm:
        next_calls.append(
            {
                "tool": "search_programs",
                "args": {
                    "industry_jsic": industry_jsic_norm,
                    "prefecture": prefecture_norm,
                    "limit": 30,
                },
                "rationale": (
                    "Browse the full eligible program list for the same "
                    "industry × prefecture cohort, beyond the 採択 history."
                ),
                "compound_mult": 1.3,
            }
        )

    axes_applied = {
        "industry_jsic": industry_jsic_norm,
        "employee_count_range": [emp_low, emp_high]
        if (emp_low is not None or emp_high is not None)
        else None,
        "revenue_yen_range": [rev_low, rev_high]
        if (rev_low is not None or rev_high is not None)
        else None,
        "prefecture": prefecture_norm,
        "case_studies_axes": ["industry_jsic", "employee", "revenue_proxy", "prefecture"],
        "adoption_records_axes": ["industry_jsic_medium", "prefecture"],
    }

    flat_results: list[dict[str, Any]] = []
    for cs in case_studies:
        flat_results.append({"kind": "case_study", **cs})
    for ar in adoption_records:
        flat_results.append({"kind": "adoption_record", **ar})

    body: dict[str, Any] = {
        "input": {
            "industry_jsic": industry_jsic_norm,
            "employee_count_range": [emp_low, emp_high]
            if (emp_low is not None or emp_high is not None)
            else None,
            "revenue_yen_range": [rev_low, rev_high]
            if (rev_low is not None or rev_high is not None)
            else None,
            "prefecture": prefecture_norm,
            "limit": limit,
        },
        "results": flat_results,
        "total": len(flat_results),
        "limit": limit,
        "offset": 0,
        "matched_case_studies": case_studies,
        "matched_adoption_records": adoption_records,
        "program_rollup": program_rollup,
        "summary": summary,
        "axes_applied": axes_applied,
        "sparsity_notes": list(_SPARSITY_NOTES),
        "data_quality": dict(_DATA_QUALITY_COHORT),
        "as_of_jst": _today_iso(),
        "_disclaimer": _DISCLAIMER_COHORT_MATCH,
        "_next_calls": next_calls,
        "_billing_unit": 1,
    }
    attach_corpus_snapshot(body)
    return body


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def case_cohort_match_am(
        industry_jsic: Annotated[
            str | None,
            Field(
                description=(
                    "JSIC industry code prefix (e.g. 'A' for 農林水産業 大分類, "
                    "'E29' for 食料品製造業 中分類). Prefix-matches both jpintel "
                    "case_studies.industry_jsic and autonomath "
                    "jpi_adoption_records.industry_jsic_medium. None spans all."
                ),
            ),
        ] = None,
        employee_count_range: Annotated[
            list[int] | None,
            Field(
                description=(
                    "[low, high] inclusive employee-count band. Either bound may be "
                    "None to leave it open. Filters case_studies.employees only — "
                    "jpi_adoption_records does not carry employee count."
                ),
                min_length=2,
                max_length=2,
            ),
        ] = None,
        revenue_yen_range: Annotated[
            list[int] | None,
            Field(
                description=(
                    "[low, high] yen revenue band. Approximated via capital_yen on "
                    "case_studies (no explicit revenue column). NULL-tolerant — "
                    "rows missing capital_yen still pass when other axes match."
                ),
                min_length=2,
                max_length=2,
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                description=(
                    "都道府県 exact match (e.g. '東京都', '群馬県'). Filters "
                    "both sides. None spans nationwide."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Max rows per side. Clamped [1,100]. Default 20."),
        ] = 20,
    ) -> dict[str, Any]:
        """[COHORT-MATCH] 同業 (JSIC) × 同規模 (employees + revenue) × 同地域 (prefecture) cohort matcher: pulls case_studies (jpintel.db, 2,286) + jpi_adoption_records (autonomath.db, 201,845) + per-program rollup (appearance_count / avg_amount / cohort_share). Single ¥3/req. NO LLM. §52 / §47条の2 / §1 sensitive — information retrieval, not 申請代理."""
        return case_cohort_match_impl(
            industry_jsic=industry_jsic,
            employee_count_range=employee_count_range,
            revenue_yen_range=revenue_yen_range,
            prefecture=prefecture,
            limit=limit,
        )


if __name__ == "__main__":  # pragma: no cover
    import pprint

    res = case_cohort_match_impl(
        industry_jsic="E",
        employee_count_range=[10, 100],
        revenue_yen_range=[100_000_000, 1_000_000_000],
        prefecture="東京都",
        limit=5,
    )
    pprint.pprint(
        {
            "summary": res.get("summary"),
            "first_case": (res.get("matched_case_studies") or [{}])[0].get("case_id"),
            "first_adoption": (res.get("matched_adoption_records") or [{}])[0].get("adoption_id"),
            "top_program": (res.get("program_rollup") or [{}])[0].get("program_label"),
            "next_calls": len(res.get("_next_calls") or []),
        }
    )
