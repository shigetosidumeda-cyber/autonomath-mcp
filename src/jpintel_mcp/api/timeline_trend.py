"""Timeline trend + upcoming rounds endpoints (R8 — 2026-05-07).

Three endpoints answering the cohort question central to consultant /
audit / 顧問 fan-out: "for THIS制度 (or 業種×地域) over the past N years,
how did 採択 trend, and when is the next 募集 closing?".

  * GET /v1/programs/{program_id}/timeline
        Per-program annual rollup over jpi_adoption_records (201,845 rows)
        + am_application_round (1,256 rows, 422 open / 493 upcoming).
        Returns adoption_count / distinct_houjin / total_amount /
        avg_amount per year + next_round + (倍率 = applicants/adopted)
        proxy reconstructed from round counts.

  * GET /v1/cases/timeline_trend?industry=&prefecture=&years=5
        業種 (JSIC prefix) × 地域 (prefecture) × 時間 (year) trend.
        Annual buckets: adoption_count / distinct_program_count /
        total_amount + per-axis trend_flag (increasing / stable /
        decreasing) computed via least-squares slope on adoption_count.

  * GET /v1/me/upcoming_rounds_for_my_profile
        For the calling API key's client_profiles fan-out: every round
        closing in the next 60 days that matches at least one profile's
        JSIC×prefecture×target_types overlap. Authenticated only —
        anonymous rejected with 401.

Contract:
  * **NO LLM call** anywhere in this module — pure SQLite + Python.
  * **Cross-DB walk** without ATTACH: open autonomath.db read-only
    via the existing helper, join in Python on jpi_unified_id.
  * **¥3 / call** flat per endpoint regardless of result count.
  * **§52 / §47条の2 / §1 disclaimer envelope** on the two sensitive
    surfaces (timeline + cases trend); upcoming-rounds carries §1 only
    (申請代理 fence) since it is pure schedule data.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM API import on this module.
* Pure read of autonomath.db + jpintel.db.
* Graceful degradation — when an autonomath table is absent on a
  fresh dev DB, the corresponding stream is empty and the missing
  table name is added to ``data_quality.missing_tables`` rather than
  500ing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("jpintel.api.timeline_trend")


router = APIRouter(tags=["timeline-trend"])


# Disclaimer text — same fence as intel_timeline so envelope-grep stays
# coherent across the timeline cohort.
_DISCLAIMER_TIMELINE = (
    "本 timeline / trend は jpi_adoption_records (201,845 行) + "
    "am_application_round (1,256 行) + jpintel programs (11,601 行) の機械的集計であり、"
    "税理士法 §52 (税務代理) ・公認会計士法 §47条の2 (監査) ・行政書士法 §1 (申請代理) ・"
    "中小企業診断士の経営助言の代替ではない。trend_flag は採択件数の最小二乗回帰の符号 "
    "(slope > 0.5 ⇒ increasing, < -0.5 ⇒ decreasing, それ以外 ⇒ stable) であり、"
    "LLM 推論は含まれない。倍率は (applicants / adopted) の proxy 推定で、"
    "正式な公募倍率は各制度の決定通知を一次資料で確認すること。"
)

_DISCLAIMER_UPCOMING = (
    "本 list は am_application_round.application_close_date が今日 (JST) から "
    "+60 日以内の round を顧問先 profile (client_profiles) と JSIC × 都道府県 × "
    "target_types で機械照合した結果であり、行政書士法 §1 (申請代理) の代替ではない。"
    "個別案件の応募可否は申請要領一次資料を必ずご確認ください。"
)

# ---------------------------------------------------------------------------
# Helpers — autonomath open + graceful table_exists
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db read-only — None on missing/empty file.

    Mirrors intel_timeline._open_autonomath_ro: tests inject
    AUTONOMATH_DB_PATH; production resolves via settings.
    """
    try:
        from jpintel_mcp.config import settings

        p = settings.autonomath_db_path
        if not p.exists() or p.stat().st_size == 0:
            return None
        uri = f"file:{p}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except (sqlite3.Error, AttributeError, OSError) as exc:
        logger.warning("autonomath open failed: %s", exc)
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _today_jst() -> date:
    return (datetime.now(UTC) + timedelta(hours=9)).date()


# ---------------------------------------------------------------------------
# Trend stats — least-squares slope sign on the year-buckets
# ---------------------------------------------------------------------------


def _trend_flag(values: list[int]) -> str:
    """Compute trend flag from a year-ordered series.

    Returns 'increasing' / 'stable' / 'decreasing' based on the sign of
    the least-squares slope, normalised by the series mean to make the
    threshold scale-independent. Empty / single-point series yield 'n/a'.
    """
    n = len(values)
    if n < 2:
        return "n/a"
    mean_v = sum(values) / n
    if mean_v <= 0:
        return "n/a"
    # x = 0..n-1, y = values
    x_mean = (n - 1) / 2.0
    num = sum((i - x_mean) * (v - mean_v) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den <= 0:
        return "stable"
    slope = num / den
    # Normalise by mean so a 5%/year drift counts as 'stable'.
    norm = slope / mean_v
    if norm > 0.05:
        return "increasing"
    if norm < -0.05:
        return "decreasing"
    return "stable"


# ---------------------------------------------------------------------------
# Program-side timeline (per-program adoption + next_round)
# ---------------------------------------------------------------------------


def _resolve_program_aliases(
    am_conn: sqlite3.Connection, program_id: str
) -> set[str]:
    """Return the set of equivalent canonical_ids the autonomath side knows.

    Walks entity_id_map both directions. Always includes program_id.
    """
    ids: set[str] = {program_id}
    if not _table_exists(am_conn, "entity_id_map"):
        return ids
    try:
        rows = am_conn.execute(
            "SELECT jpi_unified_id, am_canonical_id FROM entity_id_map "
            "WHERE jpi_unified_id = ? OR am_canonical_id = ?",
            (program_id, program_id),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("entity_id_map lookup failed: %s", exc)
        return ids
    for r in rows:
        jpi = r["jpi_unified_id"] if isinstance(r, sqlite3.Row) else r[0]
        am = r["am_canonical_id"] if isinstance(r, sqlite3.Row) else r[1]
        if jpi:
            ids.add(jpi)
        if am:
            ids.add(am)
    return ids


def _program_year_buckets(
    am_conn: sqlite3.Connection,
    program_ids: set[str],
    years: int,
    today: date,
    missing: list[str],
) -> list[dict[str, Any]]:
    """Per-year adoption rollup for the given program canonical ids.

    Reads jpi_adoption_records.announced_at (substr 1..4 = YYYY) +
    amount_granted_yen + houjin_bangou. Returns one bucket per year
    in the [today.year - years + 1, today.year] window. Missing years
    are present with zero counts so the customer never has to fill gaps.
    """
    if not _table_exists(am_conn, "jpi_adoption_records"):
        missing.append("jpi_adoption_records")
        return []
    if not program_ids:
        return []
    placeholders = ",".join("?" for _ in program_ids)
    start_year = today.year - years + 1
    try:
        rows = am_conn.execute(
            f"SELECT substr(announced_at, 1, 4) AS yyyy, "
            f"       COUNT(*) AS adoption_count, "
            f"       COUNT(DISTINCT houjin_bangou) AS distinct_houjin, "
            f"       SUM(COALESCE(amount_granted_yen, 0)) AS total_amount_yen, "
            f"       AVG(NULLIF(amount_granted_yen, 0)) AS avg_amount_yen "
            f"  FROM jpi_adoption_records "
            f" WHERE program_id IN ({placeholders}) "
            f"   AND announced_at IS NOT NULL "
            f"   AND substr(announced_at, 1, 4) GLOB '[0-9][0-9][0-9][0-9]' "
            f"   AND CAST(substr(announced_at, 1, 4) AS INTEGER) >= ? "
            f"   AND CAST(substr(announced_at, 1, 4) AS INTEGER) <= ? "
            f" GROUP BY yyyy ORDER BY yyyy ASC",
            (*program_ids, start_year, today.year),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("adoption rollup failed: %s", exc)
        return []
    by_year: dict[int, dict[str, Any]] = {}
    for r in rows:
        try:
            yr = int(r["yyyy"])
        except (TypeError, ValueError):
            continue
        avg = r["avg_amount_yen"]
        by_year[yr] = {
            "year": yr,
            "adoption_count": int(r["adoption_count"] or 0),
            "distinct_houjin_count": int(r["distinct_houjin"] or 0),
            "total_amount_yen": int(r["total_amount_yen"] or 0),
            "avg_amount_yen": int(avg) if avg is not None else None,
        }
    out: list[dict[str, Any]] = []
    for yr in range(start_year, today.year + 1):
        if yr in by_year:
            out.append(by_year[yr])
        else:
            out.append(
                {
                    "year": yr,
                    "adoption_count": 0,
                    "distinct_houjin_count": 0,
                    "total_amount_yen": 0,
                    "avg_amount_yen": None,
                }
            )
    return out


def _program_next_round(
    am_conn: sqlite3.Connection,
    program_ids: set[str],
    today_iso: str,
    missing: list[str],
) -> dict[str, Any] | None:
    if not _table_exists(am_conn, "am_application_round"):
        missing.append("am_application_round")
        return None
    if not program_ids:
        return None
    placeholders = ",".join("?" for _ in program_ids)
    try:
        row = am_conn.execute(
            f"SELECT round_id, program_entity_id, round_label, "
            f"       application_open_date, application_close_date, "
            f"       status, source_url "
            f"  FROM am_application_round "
            f" WHERE program_entity_id IN ({placeholders}) "
            f"   AND application_close_date IS NOT NULL "
            f"   AND application_close_date >= ? "
            f"   AND COALESCE(status,'open') != 'closed' "
            f" ORDER BY application_close_date ASC LIMIT 1",
            (*program_ids, today_iso),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("next_round lookup failed: %s", exc)
        return None
    if row is None:
        return None
    close_iso = row["application_close_date"]
    days_remaining: int | None = None
    try:
        close_d = date.fromisoformat(close_iso[:10])
        days_remaining = (close_d - date.fromisoformat(today_iso)).days
    except (ValueError, TypeError):
        pass
    return {
        "round_id": row["round_id"],
        "round_label": row["round_label"],
        "application_open_date": row["application_open_date"],
        "application_close_date": close_iso,
        "days_remaining": days_remaining,
        "status": row["status"],
        "source_url": row["source_url"],
    }


def _program_round_history(
    am_conn: sqlite3.Connection,
    program_ids: set[str],
    years: int,
    today: date,
    missing: list[str],
) -> list[dict[str, Any]]:
    """Past-round count per year — used to estimate 倍率 proxy."""
    if not _table_exists(am_conn, "am_application_round"):
        # Already added by next_round path if missing — dedupe.
        if "am_application_round" not in missing:
            missing.append("am_application_round")
        return []
    if not program_ids:
        return []
    placeholders = ",".join("?" for _ in program_ids)
    start_year = today.year - years + 1
    try:
        rows = am_conn.execute(
            f"SELECT substr(application_close_date, 1, 4) AS yyyy, "
            f"       COUNT(*) AS round_count "
            f"  FROM am_application_round "
            f" WHERE program_entity_id IN ({placeholders}) "
            f"   AND application_close_date IS NOT NULL "
            f"   AND CAST(substr(application_close_date, 1, 4) AS INTEGER) >= ? "
            f"   AND CAST(substr(application_close_date, 1, 4) AS INTEGER) <= ? "
            f" GROUP BY yyyy ORDER BY yyyy ASC",
            (*program_ids, start_year, today.year),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("round_history lookup failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            yr = int(r["yyyy"])
        except (TypeError, ValueError):
            continue
        out.append({"year": yr, "round_count": int(r["round_count"] or 0)})
    return out


def _build_program_timeline(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    years: int,
) -> dict[str, Any]:
    """Pure assembly of per-program timeline body."""
    today = _today_jst()
    today_iso = today.isoformat()
    missing: list[str] = []
    program_name: str | None = None

    # jpintel-side primary_name resolution.
    try:
        row = conn.execute(
            "SELECT primary_name FROM programs WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
        if row and row["primary_name"]:
            program_name = str(row["primary_name"])
    except sqlite3.Error:
        program_name = None

    am_conn = _open_autonomath_ro()
    yearly: list[dict[str, Any]] = []
    next_round: dict[str, Any] | None = None
    round_history: list[dict[str, Any]] = []
    program_ids: set[str] = {program_id}

    try:
        if am_conn is None:
            missing.append("autonomath_db")
        else:
            program_ids = _resolve_program_aliases(am_conn, program_id)
            yearly = _program_year_buckets(
                am_conn,
                program_ids,
                years=years,
                today=today,
                missing=missing,
            )
            next_round = _program_next_round(
                am_conn,
                program_ids,
                today_iso=today_iso,
                missing=missing,
            )
            round_history = _program_round_history(
                am_conn,
                program_ids,
                years=years,
                today=today,
                missing=missing,
            )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    # Trend flag — based on adoption_count over yearly buckets.
    counts = [b["adoption_count"] for b in yearly]
    trend_flag = _trend_flag(counts)

    # 倍率 proxy: when round_history has multiple-round years AND adoption
    # count exists, mean(adoption_per_round) gives a cheap "competition
    # density" signal. Honest about it being a proxy in the disclaimer.
    rounds_by_year = {r["year"]: r["round_count"] for r in round_history}
    competition_proxy: list[dict[str, Any]] = []
    for b in yearly:
        rc = rounds_by_year.get(b["year"], 0)
        if rc > 0 and b["adoption_count"] > 0:
            competition_proxy.append(
                {
                    "year": b["year"],
                    "rounds": rc,
                    "adoption_count": b["adoption_count"],
                    "adoption_per_round": round(b["adoption_count"] / rc, 2),
                }
            )

    summary_stats = {
        "total_adoption_count": sum(b["adoption_count"] for b in yearly),
        "total_distinct_houjin": sum(b["distinct_houjin_count"] for b in yearly),
        "total_amount_yen": sum(b["total_amount_yen"] for b in yearly),
        "years_with_data": sum(1 for b in yearly if b["adoption_count"] > 0),
        "trend_flag": trend_flag,
    }

    body: dict[str, Any] = {
        "program_id": program_id,
        "program_name": program_name or program_id,
        "years": years,
        "as_of": today_iso,
        "yearly": yearly,
        "next_round": next_round,
        "round_history": round_history,
        "competition_proxy": competition_proxy,
        "summary_stats": summary_stats,
        "data_quality": {
            "missing_tables": missing,
            "year_count": len(yearly),
            "resolved_aliases": len(program_ids),
        },
        "_disclaimer": _DISCLAIMER_TIMELINE,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Cases timeline trend (industry × prefecture × time)
# ---------------------------------------------------------------------------


def _cases_year_buckets(
    am_conn: sqlite3.Connection,
    *,
    industry: str | None,
    prefecture: str | None,
    years: int,
    today: date,
    missing: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(am_conn, "jpi_adoption_records"):
        missing.append("jpi_adoption_records")
        return []
    where: list[str] = [
        "announced_at IS NOT NULL",
        "substr(announced_at, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'",
        "CAST(substr(announced_at, 1, 4) AS INTEGER) >= ?",
        "CAST(substr(announced_at, 1, 4) AS INTEGER) <= ?",
    ]
    start_year = today.year - years + 1
    params: list[Any] = [start_year, today.year]
    if industry:
        # JSIC prefix match: 'E' covers E29, E30, etc.
        where.append("industry_jsic_medium LIKE ? ")
        params.append(f"{industry}%")
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)

    try:
        rows = am_conn.execute(
            "SELECT substr(announced_at, 1, 4) AS yyyy, "
            "       COUNT(*) AS adoption_count, "
            "       COUNT(DISTINCT houjin_bangou) AS distinct_houjin, "
            "       COUNT(DISTINCT program_id) AS distinct_program_count, "
            "       SUM(COALESCE(amount_granted_yen, 0)) AS total_amount_yen "
            "  FROM jpi_adoption_records "
            " WHERE " + " AND ".join(where) + " "
            "GROUP BY yyyy ORDER BY yyyy ASC",
            params,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("cases trend rollup failed: %s", exc)
        return []
    by_year: dict[int, dict[str, Any]] = {}
    for r in rows:
        try:
            yr = int(r["yyyy"])
        except (TypeError, ValueError):
            continue
        by_year[yr] = {
            "year": yr,
            "adoption_count": int(r["adoption_count"] or 0),
            "distinct_houjin_count": int(r["distinct_houjin"] or 0),
            "distinct_program_count": int(r["distinct_program_count"] or 0),
            "total_amount_yen": int(r["total_amount_yen"] or 0),
        }
    out: list[dict[str, Any]] = []
    for yr in range(start_year, today.year + 1):
        if yr in by_year:
            out.append(by_year[yr])
        else:
            out.append(
                {
                    "year": yr,
                    "adoption_count": 0,
                    "distinct_houjin_count": 0,
                    "distinct_program_count": 0,
                    "total_amount_yen": 0,
                }
            )
    return out


def _build_cases_trend(
    *, industry: str | None, prefecture: str | None, years: int
) -> dict[str, Any]:
    today = _today_jst()
    today_iso = today.isoformat()
    missing: list[str] = []
    yearly: list[dict[str, Any]] = []
    am_conn = _open_autonomath_ro()
    try:
        if am_conn is None:
            missing.append("autonomath_db")
        else:
            yearly = _cases_year_buckets(
                am_conn,
                industry=industry,
                prefecture=prefecture,
                years=years,
                today=today,
                missing=missing,
            )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    counts = [b["adoption_count"] for b in yearly]
    trend_flag = _trend_flag(counts)
    summary_stats = {
        "total_adoption_count": sum(b["adoption_count"] for b in yearly),
        "total_distinct_houjin": sum(b["distinct_houjin_count"] for b in yearly),
        "total_distinct_program_count": sum(
            b["distinct_program_count"] for b in yearly
        ),
        "total_amount_yen": sum(b["total_amount_yen"] for b in yearly),
        "years_with_data": sum(1 for b in yearly if b["adoption_count"] > 0),
        "trend_flag": trend_flag,
    }
    body: dict[str, Any] = {
        "industry": industry,
        "prefecture": prefecture,
        "years": years,
        "as_of": today_iso,
        "yearly": yearly,
        "summary_stats": summary_stats,
        "data_quality": {
            "missing_tables": missing,
            "year_count": len(yearly),
        },
        "_disclaimer": _DISCLAIMER_TIMELINE,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Upcoming rounds for the calling key's client_profiles
# ---------------------------------------------------------------------------


def _fetch_profiles(
    conn: sqlite3.Connection, key_hash: str
) -> list[dict[str, Any]]:
    """Pull the calling key's client_profiles. Empty list = no profiles."""
    try:
        rows = conn.execute(
            "SELECT profile_id, name_label, jsic_major, prefecture, "
            "       target_types_json, last_active_program_ids_json "
            "  FROM client_profiles WHERE api_key_hash = ?",
            (key_hash,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("client_profiles fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        target_types: list[str] = []
        try:
            tt = json.loads(r["target_types_json"] or "[]")
            if isinstance(tt, list):
                target_types = [str(x) for x in tt]
        except (json.JSONDecodeError, TypeError):
            target_types = []
        last_active: list[str] = []
        try:
            la = json.loads(r["last_active_program_ids_json"] or "[]")
            if isinstance(la, list):
                last_active = [str(x) for x in la]
        except (json.JSONDecodeError, TypeError):
            last_active = []
        out.append(
            {
                "profile_id": int(r["profile_id"]),
                "name_label": r["name_label"],
                "jsic_major": r["jsic_major"],
                "prefecture": r["prefecture"],
                "target_types": target_types,
                "last_active_program_ids": last_active,
            }
        )
    return out


def _fetch_upcoming_rounds(
    am_conn: sqlite3.Connection, today_iso: str, horizon_iso: str
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    rounds_sql = (
        "SELECT round_id, program_entity_id, round_label, "
        "       application_open_date, application_close_date, "
        "       status, source_url "
        "FROM am_application_round "
        "WHERE application_close_date IS NOT NULL "
        "  AND application_close_date >= ? "
        "  AND application_close_date <= ? "
        "  AND COALESCE(status, 'open') != 'closed' "
        "ORDER BY application_close_date ASC, round_id ASC"
    )
    try:
        rounds = [
            dict(r)
            for r in am_conn.execute(rounds_sql, (today_iso, horizon_iso)).fetchall()
        ]
    except sqlite3.Error as exc:
        logger.warning("upcoming rounds fetch failed: %s", exc)
        return [], {}
    am_to_jpi: dict[str, list[str]] = {}
    if _table_exists(am_conn, "entity_id_map"):
        try:
            for r in am_conn.execute(
                "SELECT jpi_unified_id, am_canonical_id FROM entity_id_map"
            ).fetchall():
                am_to_jpi.setdefault(r["am_canonical_id"], []).append(
                    r["jpi_unified_id"]
                )
        except sqlite3.Error as exc:
            logger.warning("entity_id_map dump failed: %s", exc)
    return rounds, am_to_jpi


def _hydrate_programs(
    conn: sqlite3.Connection, unified_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    ids = list(set(unified_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = conn.execute(
            f"SELECT unified_id, primary_name, tier, authority_level, "
            f"       prefecture, target_types_json, official_url "
            f"  FROM programs "
            f" WHERE excluded = 0 AND COALESCE(tier,'X') != 'X' "
            f"   AND unified_id IN ({placeholders})",
            ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("programs hydrate failed: %s", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        target_types: list[str] = []
        try:
            tt = json.loads(r["target_types_json"] or "[]")
            if isinstance(tt, list):
                target_types = [str(x) for x in tt]
        except (json.JSONDecodeError, TypeError):
            target_types = []
        out[r["unified_id"]] = {
            "unified_id": r["unified_id"],
            "primary_name": r["primary_name"],
            "tier": r["tier"],
            "authority_level": r["authority_level"],
            "prefecture": r["prefecture"],
            "target_types": target_types,
            "official_url": r["official_url"],
        }
    return out


def _profile_match(
    profile: dict[str, Any],
    program: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return (matches, [reason_codes]). At least one axis must align.

    Reason codes:
      * `jsic_major_match` — JSIC prefix overlap (kept loose since
        programs.target_types_json is the primary industry signal here;
        only emit when prefecture matches).
      * `prefecture_match` — equal prefecture OR program is national-fallback.
      * `target_types_overlap` — any overlap between profile target_types
        and program target_types.
      * `last_active_program` — the program is in the profile's
        last_active_program_ids list (highest-affinity signal).
    """
    reasons: list[str] = []
    pp = profile.get("prefecture")
    prog_pref = program.get("prefecture")
    pref_match = False
    if pp and prog_pref and pp == prog_pref:
        pref_match = True
    elif prog_pref is None or program.get("authority_level") in {"national", "国"}:
        # Program is nationwide — counts as a soft prefecture match for
        # any profile that explicitly set its prefecture.
        pref_match = bool(pp)
    if pref_match:
        reasons.append("prefecture_match")

    profile_targets = set(profile.get("target_types") or [])
    program_targets = set(program.get("target_types") or [])
    if profile_targets and program_targets and profile_targets & program_targets:
        reasons.append("target_types_overlap")

    last_active = set(profile.get("last_active_program_ids") or [])
    if program["unified_id"] in last_active:
        reasons.append("last_active_program")

    # JSIC overlap is a low-priority signal — it only fires when at least
    # one stronger axis already matched. Honest about being a soft signal.
    if profile.get("jsic_major") and pref_match:
        reasons.append("jsic_major_match")

    matches = bool(reasons)
    return matches, reasons


def _build_upcoming_rounds_for_profile(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    horizon_days: int,
) -> dict[str, Any]:
    today = _today_jst()
    horizon = today + timedelta(days=horizon_days)
    today_iso = today.isoformat()
    horizon_iso = horizon.isoformat()
    missing: list[str] = []

    profiles = _fetch_profiles(conn, key_hash)
    if not profiles:
        return {
            "as_of": today_iso,
            "horizon_days": horizon_days,
            "horizon_iso": horizon_iso,
            "profile_count": 0,
            "matches": [],
            "summary_stats": {
                "total_matches": 0,
                "total_unique_rounds": 0,
                "profiles_with_match": 0,
            },
            "data_quality": {
                "missing_tables": ["client_profiles_for_key"],
                "no_profiles": True,
            },
            "_disclaimer": _DISCLAIMER_UPCOMING,
            "_billing_unit": 1,
        }

    am_conn = _open_autonomath_ro()
    rounds: list[dict[str, Any]] = []
    am_to_jpi: dict[str, list[str]] = {}
    try:
        if am_conn is None:
            missing.append("autonomath_db")
        else:
            if not _table_exists(am_conn, "am_application_round"):
                missing.append("am_application_round")
            else:
                rounds, am_to_jpi = _fetch_upcoming_rounds(
                    am_conn, today_iso, horizon_iso
                )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    # All candidate jpi unified_ids the rounds could surface.
    candidate_ids: set[str] = set()
    for r in rounds:
        for jpi in am_to_jpi.get(r["program_entity_id"], []):
            candidate_ids.add(jpi)
    programs = _hydrate_programs(conn, candidate_ids)

    # For each round, expand into one match per (profile, jpi) pair when
    # _profile_match returns True. dedupe per (profile_id, round_id).
    matches: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    profiles_with_match: set[int] = set()
    unique_rounds: set[int] = set()

    for r in rounds:
        rid = int(r["round_id"])
        close_iso = r["application_close_date"]
        try:
            close_d = date.fromisoformat(close_iso[:10])
            days_remaining = (close_d - today).days
        except (ValueError, TypeError):
            days_remaining = None
        for jpi in am_to_jpi.get(r["program_entity_id"], []):
            prog = programs.get(jpi)
            if prog is None:
                continue
            for prof in profiles:
                ok, reasons = _profile_match(prof, prog)
                if not ok:
                    continue
                key = (prof["profile_id"], rid)
                if key in seen:
                    continue
                seen.add(key)
                profiles_with_match.add(prof["profile_id"])
                unique_rounds.add(rid)
                matches.append(
                    {
                        "profile_id": prof["profile_id"],
                        "profile_name_label": prof["name_label"],
                        "round_id": rid,
                        "round_label": r["round_label"],
                        "program_unified_id": prog["unified_id"],
                        "program_primary_name": prog["primary_name"],
                        "program_tier": prog["tier"],
                        "application_open_date": r["application_open_date"],
                        "application_close_date": close_iso,
                        "days_remaining": days_remaining,
                        "status": r["status"],
                        "source_url": r["source_url"] or prog["official_url"],
                        "match_reasons": reasons,
                    }
                )

    # Stable sort: closest-deadline first, then profile_id.
    matches.sort(
        key=lambda m: (
            m["application_close_date"] or "9999-12-31",
            m["profile_id"],
            m["round_id"],
        )
    )

    body: dict[str, Any] = {
        "as_of": today_iso,
        "horizon_days": horizon_days,
        "horizon_iso": horizon_iso,
        "profile_count": len(profiles),
        "matches": matches,
        "summary_stats": {
            "total_matches": len(matches),
            "total_unique_rounds": len(unique_rounds),
            "profiles_with_match": len(profiles_with_match),
        },
        "data_quality": {
            "missing_tables": missing,
            "rounds_in_horizon": len(rounds),
        },
        "_disclaimer": _DISCLAIMER_UPCOMING,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/v1/programs/{program_id}/timeline",
    summary="Per-program annual adoption + next-round timeline",
    description=(
        "Annual rollup over jpi_adoption_records (201,845 rows) joined to "
        "am_application_round (1,256 rows) for the given program. Returns "
        "yearly adoption_count / distinct_houjin / total_amount + "
        "next_round (closest open/upcoming round) + competition_proxy "
        "(adoption_per_round). NO LLM. ¥3 / call. §52 / §47条の2 / §1 fence."
    ),
)
def get_program_timeline(
    program_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=200,
            description=(
                "Program canonical id. Accepts either jpintel `UNI-...` or "
                "autonomath `program:...` form; entity_id_map bridges both."
            ),
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    years: Annotated[
        int,
        Query(
            ge=1,
            le=20,
            description=(
                "Number of past years (inclusive of current year) to roll up. "
                "Default 5. Bounded [1, 20]."
            ),
        ),
    ] = 5,
) -> JSONResponse:
    _t0 = time.perf_counter()
    pid = program_id.strip()
    if not pid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "program_id",
                "message": "program_id must be non-empty.",
            },
        )

    body = _build_program_timeline(conn, program_id=pid, years=years)
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.timeline",
        latency_ms=latency_ms,
        result_count=len(body.get("yearly") or []),
        params={"program_id": pid, "years": years},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.timeline",
        request_params={"program_id": pid, "years": years},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    if wants_compact(request):
        body = to_compact(body)
    return JSONResponse(content=body)


@router.get(
    "/v1/cases/timeline_trend",
    summary="業種 × 地域 × 時間 — annual adoption trend across cohorts",
    description=(
        "Year-bucketed rollup of jpi_adoption_records under "
        "(industry [JSIC prefix] × prefecture × past N years) with "
        "trend_flag (increasing / stable / decreasing) computed via "
        "least-squares slope on adoption_count. NO LLM. ¥3 / call. "
        "§52 / §47条の2 / §1 fence."
    ),
)
def get_cases_timeline_trend(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    industry: Annotated[
        str | None,
        Query(
            description=(
                "JSIC prefix (e.g. 'E' for 製造業, 'E29' for 食料品製造業). "
                "Prefix-matches industry_jsic_medium. None = all industries."
            ),
            max_length=8,
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "都道府県 exact match (e.g. '東京都', '大阪府'). None = nationwide."
            ),
            max_length=20,
        ),
    ] = None,
    years: Annotated[
        int,
        Query(
            ge=1,
            le=20,
            description=(
                "Number of past years (inclusive of current year). Default 5. "
                "Bounded [1, 20]."
            ),
        ),
    ] = 5,
) -> JSONResponse:
    _t0 = time.perf_counter()

    body = _build_cases_trend(
        industry=industry,
        prefecture=prefecture,
        years=years,
    )
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "cases.timeline_trend",
        latency_ms=latency_ms,
        result_count=len(body.get("yearly") or []),
        params={
            "industry": industry,
            "prefecture": prefecture,
            "years": years,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="cases.timeline_trend",
        request_params={
            "industry": industry,
            "prefecture": prefecture,
            "years": years,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    if wants_compact(request):
        body = to_compact(body)
    return JSONResponse(content=body)


@router.get(
    "/v1/me/upcoming_rounds_for_my_profile",
    summary="Upcoming rounds matching the calling key's client_profiles",
    description=(
        "Returns every am_application_round closing within the next "
        "horizon_days (default 60) that matches at least one of the calling "
        "API key's client_profiles via JSIC × prefecture × target_types × "
        "last_active_program overlap. Authenticated only — anon = 401. "
        "NO LLM. ¥3 / call. 行政書士法 §1 fence."
    ),
)
def get_upcoming_rounds_for_my_profile(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    horizon_days: Annotated[
        int,
        Query(
            ge=1,
            le=180,
            description=(
                "Lookahead window in days (JST). Default 60. Bounded [1, 180]."
            ),
        ),
    ] = 60,
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "auth_required",
                "message": (
                    "upcoming_rounds_for_my_profile requires an authenticated "
                    "API key (X-API-Key)."
                ),
            },
        )

    _t0 = time.perf_counter()
    body = _build_upcoming_rounds_for_profile(
        conn,
        key_hash=ctx.key_hash,
        horizon_days=horizon_days,
    )
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "me.upcoming_rounds_for_my_profile",
        latency_ms=latency_ms,
        result_count=len(body.get("matches") or []),
        params={"horizon_days": horizon_days},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="me.upcoming_rounds_for_my_profile",
        request_params={"horizon_days": horizon_days},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    if wants_compact(request):
        body = to_compact(body)
    return JSONResponse(content=body)


__all__ = ["router"]
