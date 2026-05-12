"""pubcomment_tools — DEEP-45 e-Gov パブコメ 公示 MCP tool surface (1 tool).

One new tool that surfaces the DEEP-45 corpus to the customer LLM:

  * ``get_pubcomment_status(law_keyword)``
      — pubcomment_announcement を target_law LIKE keyword で filter,
        現在公示中 (comment_deadline >= today) の案件 + 直近 90 日終了
        案件 を 上位 20 row 返す. 各 row は (id / ministry / target_law /
        announcement_date / comment_deadline / summary_text 抜粋 / full_text_url
        / sha256 / cohort_impact) + ``_disclaimer`` envelope.

DEEP-45 lead time 30-60 日 / 確実性最高 (政令・省令 改正案 30 日, 法律案 60 日
の 公示期間 法定). DEEP-39 国会会議録 (6-18 ヶ月, noisy) と 審議会議事録
(9-18 ヶ月) の 上流 detect が出した signal の 確認 surface として 機能.

Constraints:

  * LLM call = 0. Pure SQLite over autonomath.db.
  * Single ¥3/req billing event per call.
  * ``_disclaimer`` envelope on §52/§47条の2/§72/§1 sensitive 4 cohort hit.
  * ``corpus_snapshot_id`` + ``corpus_checksum`` from snapshot_helper for
    auditor reproducibility.
  * ``_next_calls`` compounding hints to drive the customer LLM toward
    related tools (search_kokkai_utterance / search_by_law).

Migration dependency: wave24_192_pubcomment_announcement.sql (1 table).
Cron dependency: scripts/cron/ingest_egov_pubcomment_daily.py.
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

logger = logging.getLogger("jpintel.mcp.autonomath.pubcomment")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = get_flag("JPCITE_PUBCOMMENT_ENABLED", "AUTONOMATH_PUBCOMMENT_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Disclaimer — §52 / §47条の2 / §72 / §1 fence on 改正案 surface.
# ---------------------------------------------------------------------------

_DISCLAIMER_PUBCOMMENT = (
    "本 response は pubcomment_announcement (e-Gov パブコメ 公示) の keyword "
    "filter 結果で、税務助言 (税理士法 §52) ・公認会計士業務 (公認会計士法 "
    "§47条の2) ・法律事務 (弁護士法 §72) ・行政書士業務 (行政書士法 §1) "
    "の代替ではありません。掲載案件は意見募集中 / 締切後の改正案であり、 "
    "成立・施行までに内容が変更される可能性があります。 確定判断は資格を "
    "有する士業へご相談ください。"
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
            hint="Ensure autonomath.db is present and migration wave24_192 has applied.",
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# get_pubcomment_status
# ---------------------------------------------------------------------------


def _get_pubcomment_status_impl(
    law_keyword: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Pure SQL pubcomment_announcement filter by target_law LIKE keyword.

    Returns 公示中 (comment_deadline >= today) + 直近 90 日終了 の 案件,
    sorted by announcement_date DESC. Each result carries 3-axis citation
    (full_text_url + retrieved_at + sha256) + cohort_impact JSON.
    """
    if not isinstance(law_keyword, str) or not law_keyword.strip():
        return make_error(
            code="missing_required_arg",
            message="law_keyword must be a non-empty string",
            field="law_keyword",
        )
    keyword = law_keyword.strip()
    limit = max(1, min(int(limit), 100))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    today = _today_iso()
    # 90-day catch-up lower bound.
    today_dt = datetime.date.fromisoformat(today)
    lower = (today_dt - datetime.timedelta(days=90)).isoformat()

    sql = (  # nosec B608
        "SELECT id, ministry, target_law, announcement_date, comment_deadline, "
        "       summary_text, full_text_url, retrieved_at, sha256, "
        "       jpcite_relevant, jpcite_cohort_impact "
        "  FROM pubcomment_announcement "
        " WHERE (target_law LIKE ? OR summary_text LIKE ?) "
        "   AND (comment_deadline >= ? OR comment_deadline >= ?) "
        " ORDER BY announcement_date DESC "
        " LIMIT ? "
    )
    params: list[Any] = [
        f"%{keyword}%",
        f"%{keyword}%",
        today,
        lower,
        limit,
    ]

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("pubcomment_announcement search failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"pubcomment_announcement query failed: {exc}",
            hint="Confirm migration wave24_192 has applied.",
        )

    results: list[dict[str, Any]] = []
    sensitive_cohort_hit = False
    for r in rows:
        cohort_impact: dict[str, Any] | None = None
        raw_impact = r["jpcite_cohort_impact"]
        if raw_impact:
            try:
                cohort_impact = json.loads(raw_impact)
            except (ValueError, TypeError):
                cohort_impact = None
        if cohort_impact and cohort_impact.get("cohort_impact"):
            sensitive_cohort_hit = True
        # Cap summary at 1500 char for transport. Full text remains in DB
        # for the customer to fetch via full_text_url.
        summary_excerpt = (r["summary_text"] or "")[:1500]
        # Ongoing if deadline >= today.
        is_ongoing = (r["comment_deadline"] or "") >= today
        results.append(
            {
                "id": r["id"],
                "ministry": r["ministry"],
                "target_law": r["target_law"],
                "announcement_date": r["announcement_date"],
                "comment_deadline": r["comment_deadline"],
                "summary_excerpt": summary_excerpt,
                "full_text_url": r["full_text_url"],
                "retrieved_at": r["retrieved_at"],
                "sha256": r["sha256"],
                "jpcite_relevant": bool(r["jpcite_relevant"]),
                "cohort_impact": cohort_impact,
                "is_ongoing": is_ongoing,
            }
        )

    body: dict[str, Any] = {
        "law_keyword": keyword,
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "as_of_jst": today,
        "_disclaimer": _DISCLAIMER_PUBCOMMENT
        if sensitive_cohort_hit or results
        else _DISCLAIMER_PUBCOMMENT,
        "_next_calls": [
            {
                "tool": "search_kokkai_utterance",
                "args": {"law_keyword": keyword},
                "rationale": "改正案 公示 → 国会答弁 で lead time 6-18 ヶ月 horizon を埋める",
            },
            {
                "tool": "search_by_law",
                "args": {"law_name": keyword},
                "rationale": "改正案 公示 → 改正後 条文 + tax_rulesets / programs に compound",
            },
        ],
        "_billing_unit": 1,
    }
    return attach_corpus_snapshot_with_conn(conn, body)


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_PUBCOMMENT_ENABLED + global enable.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def get_pubcomment_status(
        law_keyword: Annotated[
            str,
            Field(
                description=(
                    "業法 keyword (e.g. '税理士法' / '適格請求書' / "
                    "'個人情報保護法'). Substring match against "
                    "pubcomment_announcement.target_law and summary_text."
                ),
                min_length=1,
                max_length=120,
            ),
        ],
        limit: Annotated[
            int,
            Field(
                default=20,
                description="Max rows (1..100, default 20).",
                ge=1,
                le=100,
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """[PUBCOMMENT] DEEP-45 e-Gov パブコメ 公示 follow. Returns 公示中 + 直近 90 日終了 案件 with 3-axis citation (full_text_url + retrieved_at + sha256) + cohort_impact rollup. Lead time 30-60 日, sensitive (§52 / §47条の2 / §72 / §1) — disclaimer envelope mandatory. NO LLM, single ¥3/req billing."""
        return _get_pubcomment_status_impl(
            law_keyword=law_keyword,
            limit=limit,
        )


__all__ = [
    "_get_pubcomment_status_impl",
]
