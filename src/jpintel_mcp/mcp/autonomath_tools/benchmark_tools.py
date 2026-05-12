"""benchmark_tools — R8 industry-benchmark surface (cohort average + outliers).

Two implementation entrypoints + one MCP tool:

* ``benchmark_cohort_average_impl(industry_jsic, size_band, prefecture)`` —
  computes the 業種 (JSIC 大分類) × 規模 (small / medium / large) × 地域 (都道府県)
  cohort 平均: 平均採択額 / 採択件数 / hit数 (制度数) / outlier 法人 (top 10%
  by amount). Backed by jpi_adoption_records (autonomath.db) joined with
  case_studies (jpintel.db) so a single cohort response covers both V4
  absorbed METI/MAFF 採択結果 (201,845 rows, 0% with amount) and the
  curated case_studies side (2,286 rows, ~1.9% with amount).

* ``benchmark_me_vs_industry_impl(*, key_hash, conn, industry_jsic,
  size_band, prefecture)`` — pulls the caller's recent usage_events (from
  jpintel.db, scoped to the caller's parent/child key tree per migration
  086) and frames it against the same cohort average. Returns the
  caller's hit_count + reach_pct against the cohort's distinct programs
  + a ``leakage_programs`` list = cohort程式 minus me's programs (= 取り
  こぼし候補). NO PII leak — the caller only ever sees their own
  ``usage_events`` rows.

Both impls are pure SQLite + Python; NO LLM call; single ¥3/req billing.
The §52 / §47条の2 / §1 disclaimer envelope is attached on every body so
LLM consumers cannot mistake this for 申請代理 / 税務助言 / 経営判断.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import sqlite3
import statistics
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.benchmark")

_ENABLED = get_flag("JPCITE_BENCHMARK_ENABLED", "AUTONOMATH_BENCHMARK_ENABLED", "1") == "1"


_DISCLAIMER_BENCHMARK = (
    "本 benchmark は jpintel case_studies + autonomath jpi_adoption_records "
    "の cohort 集計で、税務助言 (税理士法 §52)・監査調書 (公認会計士法 §47条の2)・"
    "申請代理 (行政書士法 §1)・経営判断 (中小企業診断士の経営助言) の代替では"
    "ありません。jpi_adoption_records.amount_granted_yen は 0% / 201,845 行のみ"
    "値を保持しており、平均採択額は case_studies 側の 4 行 (~0.18%) のみが寄与"
    "します。outlier (top 10%) は populated 行のみ ranking。各 program の適合"
    "可否は申請要領を一次資料 (source_url) で必ずご確認ください。"
)


# ---------------------------------------------------------------------------
# Size band → (capital_yen low, high) heuristic.
#
# Aligns with the 中小企業基本法 §2 boundaries (製造業 = 資本金3億円超 = 大企業)
# but stays JSIC-neutral so a single mapping works across A–T. The cohort
# matcher uses capital_yen as a revenue proxy (case_studies has no explicit
# revenue column); revenue_yen would also fit if it existed.
#
#   small   ≤ 50M ¥ capital  (typical 中小企業)
#   medium  50M–300M ¥        (上位 中堅)
#   large   > 300M ¥           (大企業)
# ---------------------------------------------------------------------------
_SIZE_BAND_BOUNDS: dict[str, tuple[int | None, int | None]] = {
    "small": (None, 50_000_000),
    "medium": (50_000_000, 300_000_000),
    "large": (300_000_000, None),
    "all": (None, None),
}


_SPARSITY_NOTES_BENCHMARK = [
    "jpi_adoption_records.amount_granted_yen is currently 0/201,845 populated. "
    "V4 absorption captured 採択企業 + program identity but not 交付額; the "
    "cohort 平均採択額 is therefore driven by case_studies.total_subsidy_received_yen "
    "(~1.9% / 4 of 2,286 populated). Treat the average as a directional indicator, "
    "not a settlement.",
    "case_studies revenue_yen is approximated via capital_yen (no explicit "
    "revenue column). size_band='small' ≤ ¥50M / 'medium' ≤ ¥300M / 'large' > ¥300M "
    "track the 中小企業基本法 §2 製造業 boundary.",
    "industry_jsic uses prefix match. 'D' covers 建設業 大分類; 'E29' filters down to "
    "中分類 食料品製造業. jpi_adoption_records carries 中分類 as `industry_jsic_medium`; "
    "case_studies carries mixed-grain `industry_jsic` (1-letter or 4-digit). Both are "
    "reachable through the same prefix LIKE.",
    "outlier_top_decile is the top 10% of cohort 法人 by populated 交付額. The list is "
    "sparse when only case_studies contributes amount values; rows without amount are "
    "omitted from outlier ranking but still counted in cohort_size.",
]


# R8 BUGHUNT (2026-05-07): canonical data_quality envelope for adoption-records-backed
# endpoints. Discloses upstream substrate caveats audited live against
# autonomath.db on 2026-05-07. Numbers are static-snapshot; re-probe before
# launch if the substrate is rebuilt.
_DATA_QUALITY_BENCHMARK: dict[str, Any] = {
    "substrate": "jpi_adoption_records (201,845) + case_studies (2,286)",
    "adoption_records_total": 201_845,
    "case_studies_total": 2_286,
    "amount_granted_yen_populated": 0,
    "case_studies_amount_populated": 4,
    "orphan_houjin_in_adoption_records": 357,
    "license_unknown_pct": 0.83,
    "license_unknown_count": 805,
    "caveat": (
        "jpi_adoption_records.amount_granted_yen is 0% populated; cohort 平均採択額 "
        "leans on 4/2,286 case_studies rows. 357 distinct houjin_bangou in "
        "jpi_adoption_records do not yet present in houjin_master (gBiz delta "
        "self-heal pending). 805 / 97,272 am_source rows carry license='unknown'. "
        "Treat aggregates as directional, not authoritative."
    ),
}


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _open_jpintel_ro(db_path: str | None = None) -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only via file URI. Mirror cohort_match_tools."""
    path = db_path or get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
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
            retry_with=["case_cohort_match_am", "search_acceptance_stats_am"],
        )


def _open_autonomath_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only. Soft-fail to error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            retry_with=["case_cohort_match_am"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["case_cohort_match_am"],
        )


def _normalize_size_band(raw: str | None) -> str:
    if raw is None:
        return "all"
    norm = str(raw).strip().lower()
    if norm in _SIZE_BAND_BOUNDS:
        return norm
    return "all"


def _capital_filter(
    size_band: str,
) -> tuple[list[str], list[Any]]:
    """Return SQL fragments + params for the size_band capital_yen band."""
    low, high = _SIZE_BAND_BOUNDS.get(size_band, (None, None))
    where: list[str] = []
    params: list[Any] = []
    if low is not None:
        where.append("(capital_yen IS NULL OR capital_yen >= ?)")
        params.append(low)
    if high is not None:
        where.append("(capital_yen IS NULL OR capital_yen <= ?)")
        params.append(high)
    return where, params


def _fetch_case_studies_for_cohort(
    industry_jsic: str | None,
    size_band: str,
    prefecture: str | None,
) -> list[dict[str, Any]]:
    """Pull case_studies rows for the cohort. Returns [] on db error."""
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
    cap_where, cap_params = _capital_filter(size_band)
    where.extend(cap_where)
    params.extend(cap_params)

    where_sql = " AND ".join(where) if where else "1=1"
    sql = (  # nosec B608
        "SELECT case_id, company_name, houjin_bangou, prefecture, "
        "       industry_jsic, employees, capital_yen, "
        "       programs_used_json, total_subsidy_received_yen, "
        "       publication_date, source_url "
        "  FROM case_studies "
        f" WHERE {where_sql} "
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("benchmark case_studies fetch failed: %s", exc)
        rows = []
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            programs = json.loads(r["programs_used_json"] or "[]")
            if not isinstance(programs, list):
                programs = []
        except (json.JSONDecodeError, TypeError):
            programs = []
        out.append(
            {
                "case_id": r["case_id"],
                "company_name": r["company_name"],
                "houjin_bangou": r["houjin_bangou"],
                "prefecture": r["prefecture"],
                "industry_jsic": r["industry_jsic"],
                "employees": r["employees"],
                "capital_yen": r["capital_yen"],
                "programs": [str(p) for p in programs if p],
                "amount_yen": r["total_subsidy_received_yen"],
                "publication_date": r["publication_date"],
                "source_url": r["source_url"],
            }
        )
    return out


def _fetch_adoption_records_for_cohort(
    industry_jsic: str | None,
    prefecture: str | None,
) -> list[dict[str, Any]]:
    """Pull jpi_adoption_records rows for the cohort. Returns [] on error."""
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
        "SELECT id, houjin_bangou, program_id, program_id_hint, "
        "       program_name_raw, company_name_raw, prefecture, "
        "       industry_jsic_medium, amount_granted_yen, "
        "       announced_at, source_url "
        "  FROM jpi_adoption_records "
        f" WHERE {where_sql} "
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("benchmark adoption_records fetch failed: %s", exc)
        rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        program_label = r["program_name_raw"] or r["program_id_hint"] or ""
        out.append(
            {
                "adoption_id": r["id"],
                "houjin_bangou": r["houjin_bangou"],
                "company_name": r["company_name_raw"],
                "prefecture": r["prefecture"],
                "industry_jsic_medium": r["industry_jsic_medium"],
                "program": str(program_label).strip() if program_label else "",
                "amount_yen": r["amount_granted_yen"],
                "announced_at": r["announced_at"],
                "source_url": r["source_url"],
            }
        )
    return out


def _accept_rate(case_count: int, adoption_count: int) -> float | None:
    """Soft accept-rate proxy.

    case_studies + jpi_adoption_records are both 採択 (i.e. positive)
    rows; we have no ministry-published applicant-count denominator on
    this cohort. We still return a directional ratio = adoption_count /
    (case_count + adoption_count) so the response carries a single number
    LLM consumers can compare across cohorts. The sparsity_notes call out
    that this is NOT a real 採択率.
    """
    total = case_count + adoption_count
    if total == 0:
        return None
    return round(adoption_count / total, 4)


def _outlier_top_decile(
    case_studies: list[dict[str, Any]],
    adoption_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the top 10% rows by amount_yen across both sides.

    Outlier ranking is amount-driven: rows missing amount are skipped
    silently (and called out in sparsity_notes). When fewer than 10
    rows have amount, every populated row is returned (ceiling at 1
    so the response is never empty when at least one amount exists).
    """
    rows: list[dict[str, Any]] = []
    for cs in case_studies:
        if cs.get("amount_yen") is not None and cs["amount_yen"] > 0:
            rows.append(
                {
                    "kind": "case_study",
                    "case_id": cs.get("case_id"),
                    "company_name": cs.get("company_name"),
                    "houjin_bangou": cs.get("houjin_bangou"),
                    "prefecture": cs.get("prefecture"),
                    "industry_jsic": cs.get("industry_jsic"),
                    "amount_yen": int(cs["amount_yen"]),
                    "programs": cs.get("programs", []),
                    "source_url": cs.get("source_url"),
                }
            )
    for ar in adoption_records:
        if ar.get("amount_yen") is not None and ar["amount_yen"] > 0:
            rows.append(
                {
                    "kind": "adoption_record",
                    "adoption_id": ar.get("adoption_id"),
                    "company_name": ar.get("company_name"),
                    "houjin_bangou": ar.get("houjin_bangou"),
                    "prefecture": ar.get("prefecture"),
                    "industry_jsic_medium": ar.get("industry_jsic_medium"),
                    "amount_yen": int(ar["amount_yen"]),
                    "program": ar.get("program"),
                    "source_url": ar.get("source_url"),
                }
            )
    rows.sort(key=lambda r: r["amount_yen"], reverse=True)
    take = max(1, len(rows) // 10) if rows else 0
    return rows[:take]


def _summary_amount_stats(
    case_studies: list[dict[str, Any]],
    adoption_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute amount-level cohort statistics."""
    amounts: list[int] = []
    for cs in case_studies:
        a = cs.get("amount_yen")
        if a is not None and a > 0:
            amounts.append(int(a))
    for ar in adoption_records:
        a = ar.get("amount_yen")
        if a is not None and a > 0:
            amounts.append(int(a))
    if not amounts:
        return {
            "amount_yen_with_value": 0,
            "amount_yen_mean": None,
            "amount_yen_median": None,
            "amount_yen_min": None,
            "amount_yen_max": None,
            "amount_yen_total": 0,
        }
    return {
        "amount_yen_with_value": len(amounts),
        "amount_yen_mean": int(round(statistics.fmean(amounts))),
        "amount_yen_median": int(statistics.median(amounts)),
        "amount_yen_min": min(amounts),
        "amount_yen_max": max(amounts),
        "amount_yen_total": sum(amounts),
    }


def _distinct_programs(
    case_studies: list[dict[str, Any]],
    adoption_records: list[dict[str, Any]],
) -> list[str]:
    """Sorted list of distinct program labels in the cohort."""
    labels: set[str] = set()
    for cs in case_studies:
        for p in cs.get("programs", []):
            if p:
                labels.add(p.strip())
    for ar in adoption_records:
        p = ar.get("program") or ""
        if p:
            labels.add(p.strip())
    return sorted(labels)


def benchmark_cohort_average_impl(
    industry_jsic: str | None = None,
    size_band: str | None = None,
    prefecture: str | None = None,
) -> dict[str, Any]:
    """Compute the 業種 × 規模 × 地域 cohort average + outlier list."""
    industry_norm = industry_jsic.strip() if industry_jsic else None
    pref_norm = prefecture.strip() if prefecture else None
    size_norm = _normalize_size_band(size_band)

    case_studies = _fetch_case_studies_for_cohort(industry_norm, size_norm, pref_norm)
    adoption_records = _fetch_adoption_records_for_cohort(industry_norm, pref_norm)
    cohort_size = len(case_studies) + len(adoption_records)

    distinct_programs = _distinct_programs(case_studies, adoption_records)
    summary_amount = _summary_amount_stats(case_studies, adoption_records)
    outliers = _outlier_top_decile(case_studies, adoption_records)
    accept_rate_proxy = _accept_rate(len(case_studies), len(adoption_records))

    next_calls: list[dict[str, Any]] = []
    if industry_norm:
        next_calls.append(
            {
                "tool": "case_cohort_match_am",
                "args": {
                    "industry_jsic": industry_norm,
                    "prefecture": pref_norm,
                    "limit": 50,
                },
                "rationale": (
                    "Pull the full cohort row-set with per-row metadata once you "
                    "have an industry baseline; benchmark_cohort_average aggregates, "
                    "case_cohort_match_am lists."
                ),
                "compound_mult": 1.5,
            }
        )
    if distinct_programs:
        top_program = distinct_programs[0]
        next_calls.append(
            {
                "tool": "search_acceptance_stats_am",
                "args": {"program_name": top_program},
                "rationale": (
                    "Pair the cohort's program list with per-program 採択率 so the "
                    "directional accept_rate_proxy can be replaced with a real one."
                ),
                "compound_mult": 1.4,
            }
        )

    body: dict[str, Any] = {
        "input": {
            "industry_jsic": industry_norm,
            "size_band": size_norm,
            "prefecture": pref_norm,
        },
        "cohort_size": cohort_size,
        "case_study_count": len(case_studies),
        "adoption_record_count": len(adoption_records),
        "distinct_programs": distinct_programs,
        "distinct_program_count": len(distinct_programs),
        "accept_rate_proxy": accept_rate_proxy,
        "amount_summary": summary_amount,
        "outlier_top_decile": outliers,
        "axes_applied": {
            "industry_jsic": industry_norm,
            "size_band": size_norm,
            "size_band_capital_yen": list(_SIZE_BAND_BOUNDS.get(size_norm, (None, None))),
            "prefecture": pref_norm,
            "case_studies_axes": [
                "industry_jsic",
                "size_band(capital_yen)",
                "prefecture",
            ],
            "adoption_records_axes": ["industry_jsic_medium", "prefecture"],
        },
        "sparsity_notes": list(_SPARSITY_NOTES_BENCHMARK),
        "data_quality": dict(_DATA_QUALITY_BENCHMARK),
        "as_of_jst": _today_iso(),
        "_disclaimer": _DISCLAIMER_BENCHMARK,
        "_next_calls": next_calls,
        "_billing_unit": 1,
    }
    attach_corpus_snapshot(body)
    return body


# ---------------------------------------------------------------------------
# Me vs industry — the personal lens.
#
# The caller's recent usage is already in jpintel.db ``usage_events``
# scoped to api_keys.key_hash (and parent_key_id tree per migration 086).
# The endpoint pulls the caller's last 90 days of endpoint hits, treats
# every search-for-program endpoint as a "program touch", and frames the
# touched-set against the cohort's distinct programs:
#
#   reach_pct = caller_touched / cohort_distinct_programs
#   leakage   = cohort_distinct_programs minus caller_touched
#
# The leakage list is the value: it surfaces 取りこぼし制度 (programs the
# cohort uses but the caller has not touched yet). Per CLAUDE.md the
# caller's own usage_events is the only PII surface; we never leak other
# customers' usage.
# ---------------------------------------------------------------------------


# Endpoints that count as "program touches" — every short_name that
# materially returns a program-shaped row.
_PROGRAM_TOUCH_ENDPOINTS: frozenset[str] = frozenset(
    {
        "programs.search",
        "programs.get",
        "programs.prescreen",
        "case_studies.search",
        "case_studies.get",
        "case_cohort_match",
        "search_acceptance_stats_am",
        "search_tax_incentives",
        "search_certifications",
        "list_open_programs",
        "search_by_law",
        "active_programs_at",
    }
)


def _resolve_tree_key_hashes(conn: sqlite3.Connection, key_hash: str) -> list[str]:
    """Return [key_hash] + sibling key_hashes when migration 086 columns exist.

    Mirrors ``api/me.py::_resolve_tree_key_hashes`` so a parent caller
    sees aggregate touches across the whole tree (consistent with how
    /v1/me/usage already aggregates).
    """
    try:
        row = conn.execute(
            "SELECT id, parent_key_id FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
    except sqlite3.OperationalError:
        return [key_hash]
    if row is None:
        return [key_hash]
    row_keys = row.keys() if hasattr(row, "keys") else []
    if "id" not in row_keys:
        return [key_hash]
    pk = row["parent_key_id"] if "parent_key_id" in row_keys else None
    root = pk if pk is not None else row["id"]
    if root is None:
        return [key_hash]
    rows = conn.execute(
        "SELECT key_hash FROM api_keys WHERE id = ? OR parent_key_id = ?",
        (root, root),
    ).fetchall()
    hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in rows]
    if key_hash not in hashes:
        hashes.append(key_hash)
    return hashes


def _fetch_caller_endpoint_hits(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    days: int,
) -> dict[str, int]:
    """Return {endpoint_short_name: hit_count} over the last `days` days."""
    days = max(1, min(days, 365))
    cutoff = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat()
    tree_hashes = _resolve_tree_key_hashes(conn, key_hash)
    if not tree_hashes:
        return {}
    placeholders = ",".join("?" * len(tree_hashes))
    sql = (  # nosec B608 — placeholders only
        "SELECT endpoint, COUNT(*) AS n "
        "  FROM usage_events "
        f" WHERE key_hash IN ({placeholders}) AND ts >= ? "
        " GROUP BY endpoint"
    )
    try:
        rows = conn.execute(sql, (*tree_hashes, cutoff)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("benchmark caller hits fetch failed: %s", exc)
        return {}
    return {r["endpoint"]: int(r["n"]) for r in rows}


def benchmark_me_vs_industry_impl(
    *,
    conn: sqlite3.Connection,
    key_hash: str,
    industry_jsic: str | None = None,
    size_band: str | None = None,
    prefecture: str | None = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """Compose the caller-versus-industry framing.

    ``conn`` is the request-scoped jpintel.db connection (carries
    ``usage_events`` and ``api_keys``). ``key_hash`` is the caller's
    HMAC, already resolved by ``deps.require_key`` upstream. The cohort
    side is computed via ``benchmark_cohort_average_impl`` so the two
    lenses share corpus-snapshot identity.
    """
    cohort = benchmark_cohort_average_impl(
        industry_jsic=industry_jsic,
        size_band=size_band,
        prefecture=prefecture,
    )

    endpoint_hits = _fetch_caller_endpoint_hits(conn, key_hash=key_hash, days=window_days)
    program_touches_by_endpoint = {
        ep: n for ep, n in endpoint_hits.items() if ep in _PROGRAM_TOUCH_ENDPOINTS
    }
    total_program_touches = sum(program_touches_by_endpoint.values())

    cohort_programs = list(cohort.get("distinct_programs") or [])
    # The caller's hit set is endpoint-level, not program-level — we do
    # NOT have a per-program touch column on usage_events (params_digest
    # is hashed; raw program_id is intentionally not stored). We surface
    # this honestly: ``my_program_touches_known=False`` so a downstream
    # LLM cannot mistake total_program_touches for "touched N distinct
    # programs". The leakage list defaults to the full cohort so the
    # caller can rank by gap immediately.
    leakage_programs = cohort_programs
    reach_pct = 0.0 if cohort_programs else None

    next_calls: list[dict[str, Any]] = list(cohort.get("_next_calls") or [])
    if leakage_programs:
        next_calls.insert(
            0,
            {
                "tool": "search_acceptance_stats_am",
                "args": {"program_name": leakage_programs[0]},
                "rationale": (
                    "First leakage candidate — cohort uses this program but the "
                    "caller has not yet hit any program-touch endpoint with it."
                ),
                "compound_mult": 1.6,
            },
        )

    body: dict[str, Any] = {
        "input": {
            "industry_jsic": cohort["input"]["industry_jsic"],
            "size_band": cohort["input"]["size_band"],
            "prefecture": cohort["input"]["prefecture"],
            "window_days": max(1, min(window_days, 365)),
        },
        "cohort": {
            "cohort_size": cohort["cohort_size"],
            "distinct_programs": cohort_programs,
            "distinct_program_count": cohort["distinct_program_count"],
            "amount_summary": cohort["amount_summary"],
            "accept_rate_proxy": cohort["accept_rate_proxy"],
            "outlier_top_decile_count": len(cohort["outlier_top_decile"]),
        },
        "me": {
            "total_program_touches": total_program_touches,
            "endpoint_hits": program_touches_by_endpoint,
            "my_program_touches_known": False,
            "reach_pct": reach_pct,
        },
        "leakage_programs": leakage_programs,
        "leakage_program_count": len(leakage_programs),
        "axes_applied": cohort["axes_applied"],
        "sparsity_notes": [
            *cohort["sparsity_notes"],
            (
                "usage_events does not store the program_id surfaced by a search "
                "call; the caller's program_touches is endpoint-level only "
                "(`my_program_touches_known=False`). leakage_programs therefore "
                "lists the full cohort distinct-program set as a precaution."
            ),
        ],
        "data_quality": dict(_DATA_QUALITY_BENCHMARK),
        "as_of_jst": cohort["as_of_jst"],
        "_disclaimer": _DISCLAIMER_BENCHMARK,
        "_next_calls": next_calls,
        "_billing_unit": 1,
    }
    if "corpus_snapshot_id" in cohort:
        body["corpus_snapshot_id"] = cohort["corpus_snapshot_id"]
    if "corpus_checksum" in cohort:
        body["corpus_checksum"] = cohort["corpus_checksum"]
    return body


# ---------------------------------------------------------------------------
# MCP tool registration. The user-versus-industry lens is intentionally
# REST-only (it needs an authenticated request scope to see the caller's
# usage_events); the cohort-average lens is a pure function over public
# corpora and surfaces as an MCP tool.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def benchmark_cohort_average_am(
        industry_jsic: Annotated[
            str | None,
            Field(
                description=(
                    "JSIC industry code prefix (e.g. 'D' for 建設業, 'E29' for "
                    "中分類 食料品製造業). Prefix-matches both jpintel "
                    "case_studies.industry_jsic and autonomath "
                    "jpi_adoption_records.industry_jsic_medium. None spans all 37 "
                    "majors."
                ),
            ),
        ] = None,
        size_band: Annotated[
            str | None,
            Field(
                description=(
                    "Size band — 'small' (capital ≤ ¥50M) / 'medium' (¥50M–¥300M) / "
                    "'large' (> ¥300M) / 'all'. NULL-tolerant: rows missing "
                    "capital_yen still pass when other axes match."
                ),
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                description=(
                    "都道府県 exact match (e.g. '東京都', '群馬県'). Filters both "
                    "sides. None spans nationwide."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[BENCHMARK] 業種 (JSIC) × 規模 × 地域 平均採択額 / 採択件数 / hit数 (制度数) / outlier 法人 (top 10%) over case_studies + jpi_adoption_records. Single ¥3/req. NO LLM. §52 / §47条の2 / §1 sensitive — directional benchmark, not 採択保証 / 経営助言."""
        return benchmark_cohort_average_impl(
            industry_jsic=industry_jsic,
            size_band=size_band,
            prefecture=prefecture,
        )


__all__ = [
    "_DISCLAIMER_BENCHMARK",
    "_PROGRAM_TOUCH_ENDPOINTS",
    "_SIZE_BAND_BOUNDS",
    "benchmark_cohort_average_impl",
    "benchmark_me_vs_industry_impl",
]
