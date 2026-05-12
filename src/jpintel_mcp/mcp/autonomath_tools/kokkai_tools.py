"""kokkai_tools — DEEP-39 国会会議録 + 審議会議事録 MCP tool surface (2 tools).

Two new tools that surface the DEEP-39 corpus to the customer LLM:

  * ``search_kokkai_utterance(law_keyword, date_range)``
      — kokkai_utterance を keyword + 期間 filter, top 20 row + 3-axis
        citation (source_url + retrieved_at + sha256) + ``_disclaimer``.
        Surfaces 国会答弁 引用 for §52 / §47条の2 / §72 / §3 sensitive
        cohorts (§52 = 税理士法、 §47条の2 = 公認会計士法、 §72 = 弁護士法、
        §3 = 司法書士法). DEEP-26 reverse-proxy SEO uses these envelopes
        to render「§52 国会答弁 引用」 niche pages.

  * ``search_shingikai_minutes(council, agenda_keyword)``
      — shingikai_minutes を council + 議題 keyword filter, top 10 row
        + citation envelope.

Both tools:

  * LLM call = 0. Pure SQLite over autonomath.db.
  * Single ¥3/req billing event per call (the wrapper runs N internal
    queries but bills as 1 metered request).
  * ``_disclaimer`` envelope on both — both surfaces are §52/§47条の2/§72
    sensitive (legislative quotes can be cherry-picked into 助言-shaped
    advice, so the disclaimer fence is mandatory).
  * ``corpus_snapshot_id`` + ``corpus_checksum`` from snapshot_helper for
    auditor reproducibility.
  * ``_next_calls`` compounding hints to drive the customer LLM toward
    related tools (search_by_law / track_amendment_lineage_am).

Migration dependency: wave24_185_kokkai_utterance.sql (3 tables).
Cron dependency: scripts/cron/ingest_kokkai_weekly.py +
                 scripts/cron/ingest_shingikai_weekly.py.
"""

from __future__ import annotations

import datetime
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

logger = logging.getLogger("jpintel.mcp.autonomath.kokkai")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = get_flag("JPCITE_KOKKAI_ENABLED", "AUTONOMATH_KOKKAI_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Disclaimers — §52 / §47条の2 / §72 / §3 fence on legislative quote surfaces.
# ---------------------------------------------------------------------------

_DISCLAIMER_KOKKAI = (
    "本 response は kokkai_utterance (国会会議録 一次資料) の keyword filter "
    "結果で、税務助言 (税理士法 §52) ・公認会計士業務 (公認会計士法 §47条の2) ・"
    "法律事務 (弁護士法 §72) ・登記申請 (司法書士法 §3) ・行政書士業務 "
    "(行政書士法 §1) の代替ではありません。引用は答弁時点の発言であり、 "
    "改正により現在の取扱が変更されている可能性があります。 確定判断は資格を "
    "有する士業へご相談ください。"
)

_DISCLAIMER_SHINGIKAI = (
    "本 response は shingikai_minutes (各省 審議会 議事録) の keyword filter "
    "結果で、税務助言 (税理士法 §52) ・公認会計士業務 (公認会計士法 §47条の2) ・"
    "法律事務 (弁護士法 §72) の代替ではありません。引用は審議会段階の議論であり、"
    "答申・法案・施行までに内容が変更される可能性があります。 確定判断は "
    "資格を有する士業へご相談ください。"
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
            hint="Ensure autonomath.db is present and migration wave24_185 has applied.",
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# 1) search_kokkai_utterance
# ---------------------------------------------------------------------------


def _search_kokkai_utterance_impl(
    law_keyword: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Pure SQL kokkai_utterance search by keyword + date range.

    Returns top ``limit`` rows ordered by date DESC. Each result carries
    source_url + retrieved_at + sha256 (3-axis citation).
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

    # Build WHERE clause defensively.
    clauses: list[str] = ["body LIKE ?"]
    params: list[Any] = [f"%{keyword}%"]
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    where = " AND ".join(clauses)
    sql = (  # nosec B608
        "SELECT id, session_no, house, committee, date, speaker, "
        "       speaker_role, body, source_url, retrieved_at, sha256 "
        "  FROM kokkai_utterance "
        f" WHERE {where} "
        " ORDER BY date DESC "
        " LIMIT ? "
    )
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("kokkai_utterance search failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"kokkai_utterance query failed: {exc}",
            hint="Confirm migration wave24_185 has applied.",
        )

    results: list[dict[str, Any]] = []
    for r in rows:
        # Cap each body at 4 KB for transport. Full text remains in DB
        # for the customer to fetch via source_url for reproducibility.
        body_excerpt = (r["body"] or "")[:4000]
        results.append(
            {
                "speech_id": r["id"],
                "session_no": r["session_no"],
                "house": r["house"],
                "committee": r["committee"],
                "date": r["date"],
                "speaker": r["speaker"],
                "speaker_role": r["speaker_role"],
                "body_excerpt": body_excerpt,
                "source_url": r["source_url"],
                "retrieved_at": r["retrieved_at"],
                "sha256": r["sha256"],
            }
        )

    body: dict[str, Any] = {
        "law_keyword": keyword,
        "date_range": {"from": date_from, "to": date_to},
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "as_of_jst": _today_iso(),
        "_disclaimer": _DISCLAIMER_KOKKAI,
        "_next_calls": [
            {
                "tool": "search_by_law",
                "args": {"law_name": keyword},
                "rationale": "改正前の答弁から改正後の条文 + tax_rulesets / programs に compound",
            },
            {
                "tool": "search_shingikai_minutes",
                "args": {"council": "税制調査会", "agenda_keyword": keyword},
                "rationale": "国会答弁 → 審議会議事 で lead time 6-18ヶ月 horizon を埋める",
            },
        ],
        "_billing_unit": 1,
    }
    return attach_corpus_snapshot_with_conn(conn, body)


def _search_shingikai_minutes_impl(
    council: str,
    agenda_keyword: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Pure SQL shingikai_minutes search by council + agenda keyword.

    ``agenda_keyword`` is optional — when omitted, returns the latest
    ``limit`` minutes for the council ordered by date DESC.
    """
    if not isinstance(council, str) or not council.strip():
        return make_error(
            code="missing_required_arg",
            message="council must be a non-empty string (e.g. '税制調査会')",
            field="council",
        )
    council = council.strip()
    limit = max(1, min(int(limit), 50))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    clauses: list[str] = ["council LIKE ?"]
    params: list[Any] = [f"%{council}%"]
    if agenda_keyword and isinstance(agenda_keyword, str) and agenda_keyword.strip():
        kw = agenda_keyword.strip()
        clauses.append("(agenda LIKE ? OR body_text LIKE ?)")
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")
    where = " AND ".join(clauses)
    sql = (  # nosec B608
        "SELECT id, ministry, council, date, agenda, body_text, "
        "       pdf_url, retrieved_at, sha256 "
        "  FROM shingikai_minutes "
        f" WHERE {where} "
        " ORDER BY date DESC "
        " LIMIT ? "
    )
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("shingikai_minutes search failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"shingikai_minutes query failed: {exc}",
            hint="Confirm migration wave24_185 has applied.",
        )

    results: list[dict[str, Any]] = []
    for r in rows:
        body_excerpt = (r["body_text"] or "")[:6000]
        results.append(
            {
                "minutes_id": r["id"],
                "ministry": r["ministry"],
                "council": r["council"],
                "date": r["date"],
                "agenda": r["agenda"],
                "body_excerpt": body_excerpt,
                "pdf_url": r["pdf_url"],
                "retrieved_at": r["retrieved_at"],
                "sha256": r["sha256"],
            }
        )

    body: dict[str, Any] = {
        "council": council,
        "agenda_keyword": agenda_keyword,
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "as_of_jst": _today_iso(),
        "_disclaimer": _DISCLAIMER_SHINGIKAI,
        "_next_calls": [
            {
                "tool": "search_kokkai_utterance",
                "args": {"law_keyword": agenda_keyword or council},
                "rationale": "審議会議事 → 国会答弁 で 改正前段階の言及を full-stack で追跡",
            },
            {
                "tool": "track_amendment_lineage_am",
                "args": {"law_name": agenda_keyword or council},
                "rationale": "審議会段階 → 改正後 diff まで lineage を 1-call で展開",
            },
        ],
        "_billing_unit": 1,
    }
    return attach_corpus_snapshot_with_conn(conn, body)


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_KOKKAI_ENABLED + global enable.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def search_kokkai_utterance(
        law_keyword: Annotated[
            str,
            Field(
                description=(
                    "業法 keyword (e.g. '税理士法' / '適格請求書' / 'AI規制'). "
                    "Substring match against kokkai_utterance.body."
                ),
                min_length=1,
                max_length=120,
            ),
        ],
        date_from: Annotated[
            str | None,
            Field(
                default=None,
                description="ISO YYYY-MM-DD lower bound (inclusive). Optional.",
            ),
        ] = None,
        date_to: Annotated[
            str | None,
            Field(
                default=None,
                description="ISO YYYY-MM-DD upper bound (inclusive). Optional.",
            ),
        ] = None,
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
        """[KOKKAI] DEEP-39 国会会議録 keyword + date filter. Returns top rows with 3-axis citation (source_url + retrieved_at + sha256). Sensitive (§52 / §47条の2 / §72 / §3) — disclaimer envelope mandatory. NO LLM, single ¥3/req billing."""
        return _search_kokkai_utterance_impl(
            law_keyword=law_keyword,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def search_shingikai_minutes(
        council: Annotated[
            str,
            Field(
                description=(
                    "Council name substring (e.g. '税制調査会' / '規制改革推進会議' / '法制審議会')."
                ),
                min_length=1,
                max_length=120,
            ),
        ],
        agenda_keyword: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional 議題 keyword to AND-filter against agenda + body_text. "
                    "Omit for the latest minutes of the council."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                default=10,
                description="Max rows (1..50, default 10).",
                ge=1,
                le=50,
            ),
        ] = 10,
    ) -> dict[str, Any]:
        """[SHINGIKAI] DEEP-39 審議会 議事録 keyword filter. Returns top rows with 3-axis citation. Sensitive (§52 / §47条の2 / §72) — disclaimer envelope mandatory. NO LLM, single ¥3/req billing."""
        return _search_shingikai_minutes_impl(
            council=council,
            agenda_keyword=agenda_keyword,
            limit=limit,
        )


__all__ = [
    "_search_kokkai_utterance_impl",
    "_search_shingikai_minutes_impl",
]
