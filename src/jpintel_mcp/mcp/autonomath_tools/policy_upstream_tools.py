"""policy_upstream_tools — DEEP-46 政策 上流 signal 統合 surface (2 tools).

The `kokkai_tools` (DEEP-39), `pubcomment_tools` (DEEP-45) and the
`am_amendment_diff` chain (DEEP-22) each surface ONE upstream signal
in isolation:

  * 国会会議録    — lead time 6-18 ヶ月, noisy
  * 審議会議事録  — lead time 9-18 ヶ月, noisy
  * パブコメ      — lead time 30-60 日, certain (公示期間 法定)
  * 法案・改正    — lead time 0 ヶ月, ground truth

The customer LLM today has to make 3 separate tool calls (search_kokkai
+ search_shingikai + get_pubcomment_status), then reconcile timestamps,
then ALSO check `programs` for already-shipped 制度 — a 4-call walk per
keyword. Watching N keywords = 4N calls.

This module collapses the 4 surfaces into 2 compounding tools so a
caller watches an entire keyword set or a single topic with one ¥3/req.

  * ``policy_upstream_watch(keywords, watch_period_days)``
      — 1..20 keywords, 1..365 day window. Returns per-keyword rollup of
        kokkai count + shingikai count + ongoing-pubcomment count + the
        most recent evidence URL on each axis. Drives "what should I be
        watching this week" digests.

  * ``policy_upstream_timeline(topic, limit)``
      — single keyword, returns 国会 → 審議会 → パブコメ → 法案 → 制度
        timeline events sorted by date ASC. Each event carries
        ``stage`` (one of ``kokkai`` / ``shingikai`` / ``pubcomment`` /
        ``law_amendment`` / ``program_launch``) + 3-axis citation.
        Drives "lead time chain for X" reports.

Both tools:

  * LLM call = 0. Pure SQLite over autonomath.db (kokkai_utterance +
    shingikai_minutes + pubcomment_announcement + jpi_programs +
    am_amendment_diff). 1 single ¥3/req billing event per call.
  * ``_disclaimer`` envelope on both — surfaces 答弁・議事・改正案 + 制度,
    so §52 / §47条の2 / §72 / §1 sensitive cohorts are all covered.
  * ``corpus_snapshot_id`` + ``corpus_checksum`` for auditor reproducibility.
  * ``_next_calls`` compounding hints driving the customer LLM toward
    the deeper, single-axis tools (search_kokkai_utterance /
    search_shingikai_minutes / get_pubcomment_status / search_by_law).
  * Underscore-prefixed parameters are internal — REST surface filters
    them via ``_filter_kwargs_for_tool`` (W2-9 M-1 hardening).

Migration dependency: wave24_185 (kokkai/shingikai) +
                      wave24_192 (pubcomment) +
                      autonomath spine (jpi_programs / am_amendment_diff).
NO new migration — pure read composition.
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot_with_conn

logger = logging.getLogger("jpintel.mcp.autonomath.policy_upstream")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = (
    get_flag("JPCITE_POLICY_UPSTREAM_ENABLED", "AUTONOMATH_POLICY_UPSTREAM_ENABLED", "1") == "1"
)


# ---------------------------------------------------------------------------
# Disclaimer — §52 / §47条の2 / §72 / §1 fence on every cross-stage rollup.
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "本 response は kokkai_utterance (国会会議録) ・ shingikai_minutes "
    "(審議会議事録) ・ pubcomment_announcement (e-Gov パブコメ) ・ "
    "am_amendment_diff (改正後 diff) ・ jpi_programs (制度カタログ) を "
    "横断的に統合した keyword filter 結果で、税務助言 (税理士法 §52) ・ "
    "公認会計士業務 (公認会計士法 §47条の2) ・ 法律事務 (弁護士法 §72) ・ "
    "行政書士業務 (行政書士法 §1) の代替ではありません。引用は答弁・議事・"
    "公示・改正の 各時点の 一次資料 で、 成立・施行までに内容が変更される "
    "可能性があります。 確定判断は 資格を 有する士業へご相談ください。"
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only, returning either a conn or error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present and migrations wave24_185 + wave24_192 have applied.",
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    """Best-effort table presence check — graceful-skip a missing optional table."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Per-keyword axis collectors. Each returns (count, latest_date, latest_url).
# ---------------------------------------------------------------------------


def _kokkai_axis(
    conn: sqlite3.Connection,
    keyword: str,
    window_from: str,
) -> tuple[int, str | None, str | None]:
    if not _has_table(conn, "kokkai_utterance"):
        return 0, None, None
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(date) AS d "  # nosec B608
            "  FROM kokkai_utterance "
            " WHERE body LIKE ? AND date >= ?",
            (f"%{keyword}%", window_from),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("kokkai axis failed: %s", exc)
        return 0, None, None
    count = int(row["n"]) if row and row["n"] is not None else 0
    latest_date = row["d"] if row and row["d"] else None
    if not count or not latest_date:
        return count, latest_date, None
    try:
        url_row = conn.execute(
            "SELECT source_url FROM kokkai_utterance "  # nosec B608
            "WHERE body LIKE ? AND date = ? "
            "ORDER BY id LIMIT 1",
            (f"%{keyword}%", latest_date),
        ).fetchone()
    except sqlite3.Error:
        url_row = None
    return count, latest_date, (url_row["source_url"] if url_row else None)


def _shingikai_axis(
    conn: sqlite3.Connection,
    keyword: str,
    window_from: str,
) -> tuple[int, str | None, str | None]:
    if not _has_table(conn, "shingikai_minutes"):
        return 0, None, None
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(date) AS d "  # nosec B608
            "  FROM shingikai_minutes "
            " WHERE (agenda LIKE ? OR body_text LIKE ?) AND date >= ?",
            (f"%{keyword}%", f"%{keyword}%", window_from),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("shingikai axis failed: %s", exc)
        return 0, None, None
    count = int(row["n"]) if row and row["n"] is not None else 0
    latest_date = row["d"] if row and row["d"] else None
    if not count or not latest_date:
        return count, latest_date, None
    try:
        url_row = conn.execute(
            "SELECT pdf_url FROM shingikai_minutes "  # nosec B608
            "WHERE (agenda LIKE ? OR body_text LIKE ?) AND date = ? "
            "ORDER BY id LIMIT 1",
            (f"%{keyword}%", f"%{keyword}%", latest_date),
        ).fetchone()
    except sqlite3.Error:
        url_row = None
    return count, latest_date, (url_row["pdf_url"] if url_row else None)


def _pubcomment_axis(
    conn: sqlite3.Connection,
    keyword: str,
    today: str,
    window_from: str,
) -> tuple[int, int, str | None, str | None]:
    """Returns (ongoing, recent_total, latest_announce_date, latest_url).

    Ongoing = comment_deadline >= today. Recent total = within window_from
    inclusive (catches recently-closed cases the watcher should still see).
    """
    if not _has_table(conn, "pubcomment_announcement"):
        return 0, 0, None, None
    try:
        row = conn.execute(
            "SELECT "  # nosec B608
            "  SUM(CASE WHEN comment_deadline >= ? THEN 1 ELSE 0 END) AS ongoing, "
            "  COUNT(*) AS recent_total, "
            "  MAX(announcement_date) AS d "
            "  FROM pubcomment_announcement "
            " WHERE (target_law LIKE ? OR summary_text LIKE ?) "
            "   AND announcement_date >= ?",
            (today, f"%{keyword}%", f"%{keyword}%", window_from),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("pubcomment axis failed: %s", exc)
        return 0, 0, None, None
    ongoing = int(row["ongoing"]) if row and row["ongoing"] is not None else 0
    recent_total = int(row["recent_total"]) if row and row["recent_total"] is not None else 0
    latest_date = row["d"] if row and row["d"] else None
    if not recent_total or not latest_date:
        return ongoing, recent_total, latest_date, None
    try:
        url_row = conn.execute(
            "SELECT full_text_url FROM pubcomment_announcement "  # nosec B608
            "WHERE (target_law LIKE ? OR summary_text LIKE ?) "
            "  AND announcement_date = ? "
            "ORDER BY id LIMIT 1",
            (f"%{keyword}%", f"%{keyword}%", latest_date),
        ).fetchone()
    except sqlite3.Error:
        url_row = None
    return ongoing, recent_total, latest_date, (url_row["full_text_url"] if url_row else None)


def _amendment_axis(
    conn: sqlite3.Connection,
    keyword: str,
    window_from: str,
) -> tuple[int, str | None]:
    """Best-effort am_amendment_diff probe — graceful when the table is absent.

    am_amendment_diff schema (CLAUDE.md §V4 + migration 049): diff_id /
    entity_id / field_name / prev_value / new_value / detected_at /
    source_url. We match keyword on entity_id + the cheap (field_name,
    new_value) string axes — broad enough to catch programs / laws /
    tax_rulesets renamed to mention the keyword without overfitting.
    """
    if not _has_table(conn, "am_amendment_diff"):
        return 0, None
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(detected_at) AS d "  # nosec B608
            "  FROM am_amendment_diff "
            " WHERE (entity_id LIKE ? OR field_name LIKE ? OR new_value LIKE ?) "
            "   AND detected_at >= ?",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", window_from),
        ).fetchone()
        count = int(row["n"]) if row and row["n"] is not None else 0
        latest = row["d"] if row and row["d"] else None
        return count, latest
    except sqlite3.Error:
        # Schema drift / missing column — graceful zero, not an error.
        return 0, None


def _program_axis(conn: sqlite3.Connection, keyword: str) -> int:
    """Count of jpi_programs rows whose name matches keyword (any non-quarantined tier).

    Uses ``primary_name`` (the canonical jpcite jpi_programs name column).
    The ``aliases_json`` LIKE clause catches the common case where a
    program is registered under one display name but the upstream
    keyword (e.g. '事業承継') appears only in an alias.
    """
    if not _has_table(conn, "jpi_programs"):
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jpi_programs "  # nosec B608
            "WHERE (primary_name LIKE ? OR aliases_json LIKE ?) "
            "  AND tier IN ('S','A','B','C')",
            (f"%{keyword}%", f"%{keyword}%"),
        ).fetchone()
        return int(row["n"]) if row and row["n"] is not None else 0
    except sqlite3.Error:
        return 0


# ---------------------------------------------------------------------------
# 1) policy_upstream_watch
# ---------------------------------------------------------------------------


def _policy_upstream_watch_impl(
    keywords: list[str],
    watch_period_days: int = 90,
) -> dict[str, Any]:
    """Cross-axis upstream signal rollup over kokkai + shingikai + pubcomment.

    Returns one row per keyword: total mentions on each axis within the
    ``watch_period_days`` window + the most-recent evidence URL on each
    axis. Empty rows are still rendered so the customer LLM can drive a
    "no signal yet" digest line.
    """
    if not isinstance(keywords, list) or not keywords:
        return make_error(
            code="missing_required_arg",
            message="keywords must be a non-empty list of 1..20 strings",
            field="keywords",
        )
    cleaned: list[str] = []
    for kw in keywords:
        if not isinstance(kw, str):
            continue
        s = kw.strip()
        if s:
            cleaned.append(s)
    cleaned = list(dict.fromkeys(cleaned))[:20]
    if not cleaned:
        return make_error(
            code="missing_required_arg",
            message="keywords list contained no non-empty strings",
            field="keywords",
        )
    try:
        wpd = int(watch_period_days)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_input",
            message="watch_period_days must be an integer",
            field="watch_period_days",
        )
    wpd = max(1, min(wpd, 365))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    today = _today_iso()
    window_from = (datetime.date.fromisoformat(today) - datetime.timedelta(days=wpd)).isoformat()

    rows: list[dict[str, Any]] = []
    total_signals = 0
    for kw in cleaned:
        kk_count, kk_date, kk_url = _kokkai_axis(conn, kw, window_from)
        sh_count, sh_date, sh_url = _shingikai_axis(conn, kw, window_from)
        pc_ongoing, pc_total, pc_date, pc_url = _pubcomment_axis(conn, kw, today, window_from)
        am_count, am_date = _amendment_axis(conn, kw, window_from)
        prog_count = _program_axis(conn, kw)
        signal_strength = kk_count + sh_count + pc_total + am_count
        total_signals += signal_strength
        rows.append(
            {
                "keyword": kw,
                "signal_strength": signal_strength,
                "kokkai": {
                    "count": kk_count,
                    "latest_date": kk_date,
                    "latest_source_url": kk_url,
                },
                "shingikai": {
                    "count": sh_count,
                    "latest_date": sh_date,
                    "latest_pdf_url": sh_url,
                },
                "pubcomment": {
                    "ongoing": pc_ongoing,
                    "recent_total": pc_total,
                    "latest_date": pc_date,
                    "latest_full_text_url": pc_url,
                },
                "amendment": {
                    "count": am_count,
                    "latest_detected_at": am_date,
                },
                "programs_already_live": prog_count,
            }
        )

    # Stable order: by signal_strength DESC, then by keyword ASC.
    rows.sort(key=lambda r: (-int(r["signal_strength"]), str(r["keyword"])))

    body: dict[str, Any] = {
        "keywords": cleaned,
        "watch_period_days": wpd,
        "window_from": window_from,
        "as_of_jst": today,
        "results": rows,
        "total": len(rows),
        "total_signals": total_signals,
        "limit": len(rows),
        "offset": 0,
        "_disclaimer": _DISCLAIMER,
        "_next_calls": [
            {
                "tool": "search_kokkai_utterance",
                "args": {"law_keyword": cleaned[0], "limit": 20},
                "rationale": "国会答弁 詳細を 1 keyword で深掘り (lead time 6-18 ヶ月 horizon)",
            },
            {
                "tool": "get_pubcomment_status",
                "args": {"law_keyword": cleaned[0], "limit": 20},
                "rationale": "ongoing 公示中 案件の summary + 締切 を確認 (lead time 30-60 日 horizon)",
            },
            {
                "tool": "policy_upstream_timeline",
                "args": {"topic": cleaned[0], "limit": 50},
                "rationale": "1 keyword に絞って 国会 → 審議会 → パブコメ → 法案 → 制度 chain を時系列展開",
            },
        ],
        "_billing_unit": 1,
    }
    return attach_corpus_snapshot_with_conn(conn, body)


# ---------------------------------------------------------------------------
# 2) policy_upstream_timeline
# ---------------------------------------------------------------------------


def _policy_upstream_timeline_impl(
    topic: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Single-topic chain across 国会 / 審議会 / パブコメ / 改正 / 制度.

    Each event carries: ``stage`` (literal axis name), ``date`` (ISO),
    ``title`` (committee / council / target_law / entity), ``source_url``
    + ``retrieved_at`` + ``sha256`` (3-axis citation when available).

    Sort: ASC by date so the customer LLM reads the chain forward in time.
    ``limit`` caps the merged event list (NOT the per-axis raw rows).
    """
    if not isinstance(topic, str) or not topic.strip():
        return make_error(
            code="missing_required_arg",
            message="topic must be a non-empty string",
            field="topic",
        )
    topic_clean = topic.strip()
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_input",
            message="limit must be an integer",
            field="limit",
        )
    lim = max(1, min(lim, 200))
    # Per-axis sub-cap so a single noisy axis cannot starve the others.
    per_axis_cap = max(5, min(lim, 80))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    events: list[dict[str, Any]] = []
    today = _today_iso()
    pattern = f"%{topic_clean}%"

    # Stage 1 — 国会
    if _has_table(conn, "kokkai_utterance"):
        try:
            kk_rows = conn.execute(
                "SELECT id, date, committee, speaker, source_url, "  # nosec B608
                "       retrieved_at, sha256 "
                "  FROM kokkai_utterance "
                " WHERE body LIKE ? "
                " ORDER BY date DESC LIMIT ?",
                (pattern, per_axis_cap),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("timeline kokkai failed: %s", exc)
            kk_rows = []
        for r in kk_rows:
            events.append(
                {
                    "stage": "kokkai",
                    "date": r["date"],
                    "title": (
                        f"{r['committee']} / {r['speaker']}"
                        if r["committee"] and r["speaker"]
                        else (r["committee"] or r["speaker"] or "国会発言")
                    ),
                    "ref_id": r["id"],
                    "source_url": r["source_url"],
                    "retrieved_at": r["retrieved_at"],
                    "sha256": r["sha256"],
                    "lead_time_horizon_months": "6-18",
                }
            )

    # Stage 2 — 審議会
    if _has_table(conn, "shingikai_minutes"):
        try:
            sh_rows = conn.execute(
                "SELECT id, ministry, council, date, agenda, pdf_url, "  # nosec B608
                "       retrieved_at, sha256 "
                "  FROM shingikai_minutes "
                " WHERE agenda LIKE ? OR body_text LIKE ? "
                " ORDER BY date DESC LIMIT ?",
                (pattern, pattern, per_axis_cap),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("timeline shingikai failed: %s", exc)
            sh_rows = []
        for r in sh_rows:
            events.append(
                {
                    "stage": "shingikai",
                    "date": r["date"],
                    "title": (
                        f"{r['ministry']} {r['council']}"
                        if r["ministry"] and r["council"]
                        else (r["council"] or r["ministry"] or "審議会")
                    ),
                    "agenda": r["agenda"],
                    "ref_id": r["id"],
                    "source_url": r["pdf_url"],
                    "retrieved_at": r["retrieved_at"],
                    "sha256": r["sha256"],
                    "lead_time_horizon_months": "9-18",
                }
            )

    # Stage 3 — パブコメ
    if _has_table(conn, "pubcomment_announcement"):
        try:
            pc_rows = conn.execute(
                "SELECT id, ministry, target_law, announcement_date, "  # nosec B608
                "       comment_deadline, full_text_url, retrieved_at, sha256, "
                "       jpcite_cohort_impact "
                "  FROM pubcomment_announcement "
                " WHERE target_law LIKE ? OR summary_text LIKE ? "
                " ORDER BY announcement_date DESC LIMIT ?",
                (pattern, pattern, per_axis_cap),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("timeline pubcomment failed: %s", exc)
            pc_rows = []
        for r in pc_rows:
            cohort_impact: dict[str, Any] | None = None
            raw_impact = r["jpcite_cohort_impact"]
            if raw_impact:
                try:
                    cohort_impact = json.loads(raw_impact)
                except (ValueError, TypeError):
                    cohort_impact = None
            events.append(
                {
                    "stage": "pubcomment",
                    "date": r["announcement_date"],
                    "title": (
                        f"{r['ministry']} / {r['target_law']}"
                        if r["ministry"] and r["target_law"]
                        else (r["target_law"] or r["ministry"] or "パブコメ")
                    ),
                    "comment_deadline": r["comment_deadline"],
                    "is_ongoing": (r["comment_deadline"] or "") >= today,
                    "ref_id": r["id"],
                    "source_url": r["full_text_url"],
                    "retrieved_at": r["retrieved_at"],
                    "sha256": r["sha256"],
                    "cohort_impact": cohort_impact,
                    "lead_time_horizon_months": "1-2",
                }
            )

    # Stage 4 — 改正 (best-effort, schema drift tolerant). am_amendment_diff
    # carries entity_id / field_name / prev_value / new_value / detected_at
    # / source_url (cron-live since 2026-05-02 per CLAUDE.md). We surface
    # the diff as `field_name: prev → new` so the customer LLM gets a
    # one-line human-readable summary without re-deriving it.
    if _has_table(conn, "am_amendment_diff"):
        try:
            am_rows = conn.execute(
                "SELECT entity_id, field_name, prev_value, new_value, "  # nosec B608
                "       detected_at, source_url "
                "  FROM am_amendment_diff "
                " WHERE entity_id LIKE ? OR field_name LIKE ? OR new_value LIKE ? "
                " ORDER BY detected_at DESC LIMIT ?",
                (pattern, pattern, pattern, per_axis_cap),
            ).fetchall()
        except sqlite3.Error:
            am_rows = []
        for r in am_rows:
            detected = r["detected_at"]
            ev_date: str | None = None
            if isinstance(detected, str) and len(detected) >= 10:
                ev_date = detected[:10]
            prev_v = r["prev_value"] or ""
            new_v = r["new_value"] or ""
            field_n = r["field_name"] or ""
            # Cap each side to keep transport small.
            diff_summary = (
                f"{field_n}: {prev_v[:200]} → {new_v[:200]}"
                if field_n
                else f"{prev_v[:200]} → {new_v[:200]}"
            )
            events.append(
                {
                    "stage": "law_amendment",
                    "date": ev_date,
                    "title": r["entity_id"],
                    "diff_summary": diff_summary,
                    "field_name": field_n,
                    "ref_id": r["entity_id"],
                    "source_url": r["source_url"],
                    "retrieved_at": detected,
                    "sha256": None,
                    "lead_time_horizon_months": "0",
                }
            )

    # Stage 5 — 制度 (jpi_programs). Uses canonical jpi_programs columns
    # (primary_name + aliases_json + source_fetched_at). Quarantine tier
    # 'X' is excluded — same posture as the static SEO page generator.
    if _has_table(conn, "jpi_programs"):
        try:
            pg_rows = conn.execute(
                "SELECT unified_id, primary_name, aliases_json, source_url, "  # nosec B608
                "       source_fetched_at, tier "
                "  FROM jpi_programs "
                " WHERE (primary_name LIKE ? OR aliases_json LIKE ?) "
                "   AND tier IN ('S','A','B','C') "
                " ORDER BY source_fetched_at DESC LIMIT ?",
                (pattern, pattern, per_axis_cap),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("timeline jpi_programs failed: %s", exc)
            pg_rows = []
        for r in pg_rows:
            sf = r["source_fetched_at"]
            pg_ev_date: str | None = None
            if isinstance(sf, str) and len(sf) >= 10:
                pg_ev_date = sf[:10]
            events.append(
                {
                    "stage": "program_launch",
                    "date": pg_ev_date,
                    "title": r["primary_name"],
                    "tier": r["tier"],
                    "ref_id": r["unified_id"],
                    "source_url": r["source_url"],
                    "retrieved_at": sf,
                    "sha256": None,
                    "lead_time_horizon_months": "0",
                }
            )

    # Sort ASC; events without a date sink to the bottom.
    def _sort_key(ev: dict[str, Any]) -> tuple[int, str]:
        d = ev.get("date") or ""
        return (0 if d else 1, str(d))

    events.sort(key=_sort_key)
    if len(events) > lim:
        # Keep the most recent ``lim`` events when we exceed the cap (chop
        # from the head, since events are ASC). Preserve ASC order.
        events = events[-lim:]

    stage_counts: dict[str, int] = {
        "kokkai": 0,
        "shingikai": 0,
        "pubcomment": 0,
        "law_amendment": 0,
        "program_launch": 0,
    }
    for ev in events:
        s = str(ev.get("stage") or "")
        if s in stage_counts:
            stage_counts[s] += 1

    body: dict[str, Any] = {
        "topic": topic_clean,
        "results": events,
        "total": len(events),
        "stage_counts": stage_counts,
        "limit": lim,
        "offset": 0,
        "as_of_jst": today,
        "_disclaimer": _DISCLAIMER,
        "_next_calls": [
            {
                "tool": "search_kokkai_utterance",
                "args": {"law_keyword": topic_clean, "limit": 20},
                "rationale": "国会段階 (lead time 6-18 ヶ月) の発言全文を取得",
            },
            {
                "tool": "search_shingikai_minutes",
                "args": {"council": "税制調査会", "agenda_keyword": topic_clean},
                "rationale": "審議会段階 (lead time 9-18 ヶ月) の議事抜粋を取得",
            },
            {
                "tool": "get_pubcomment_status",
                "args": {"law_keyword": topic_clean, "limit": 20},
                "rationale": "公示段階 (lead time 30-60 日) の改正案 summary + 締切",
            },
            {
                "tool": "search_by_law",
                "args": {"law_name": topic_clean},
                "rationale": "改正 / 制度段階で 条文 + tax_rulesets / programs に compound",
            },
        ],
        "_billing_unit": 1,
    }
    return attach_corpus_snapshot_with_conn(conn, body)


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_POLICY_UPSTREAM_ENABLED + global enable.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def policy_upstream_watch(
        keywords: Annotated[
            list[str],
            Field(
                description=(
                    "1..20 業法 / 制度 keyword (e.g. ['DX','GX','事業承継']). "
                    "Substring match against kokkai_utterance.body / "
                    "shingikai_minutes.{agenda,body_text} / "
                    "pubcomment_announcement.{target_law,summary_text} / "
                    "am_amendment_diff."
                ),
                min_length=1,
                max_length=20,
            ),
        ],
        watch_period_days: Annotated[
            int,
            Field(
                default=90,
                description="Window length in days (1..365, default 90).",
                ge=1,
                le=365,
            ),
        ] = 90,
    ) -> dict[str, Any]:
        """[POLICY_UPSTREAM] DEEP-46 cross-axis upstream signal rollup. Per keyword: kokkai count + shingikai count + ongoing-pubcomment count + most-recent evidence URL on each axis. Drives "what should I be watching this week" digests for any keyword set in 1 ¥3 call. NO LLM, single ¥3/req billing. §52/§47条の2/§72/§1 envelope mandatory."""
        return _policy_upstream_watch_impl(
            keywords=keywords,
            watch_period_days=watch_period_days,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def policy_upstream_timeline(
        topic: Annotated[
            str,
            Field(
                description=(
                    "Single 業法 / 制度 keyword (e.g. '事業承継' / '適格請求書' / "
                    "'AI規制'). Returns 国会 → 審議会 → パブコメ → 改正 → 制度 "
                    "chain in chronological order."
                ),
                min_length=1,
                max_length=120,
            ),
        ],
        limit: Annotated[
            int,
            Field(
                default=50,
                description="Max merged events (1..200, default 50).",
                ge=1,
                le=200,
            ),
        ] = 50,
    ) -> dict[str, Any]:
        """[POLICY_UPSTREAM] DEEP-46 single-topic timeline across 5 stages (kokkai → shingikai → pubcomment → law_amendment → program_launch). Each event carries 3-axis citation (source_url + retrieved_at + sha256) + lead_time_horizon_months. NO LLM, single ¥3/req billing. §52/§47条の2/§72/§1 envelope mandatory."""
        return _policy_upstream_timeline_impl(
            topic=topic,
            limit=limit,
        )


__all__ = [
    "_policy_upstream_watch_impl",
    "_policy_upstream_timeline_impl",
]
