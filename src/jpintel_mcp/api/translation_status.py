"""Wave 41 Agent I — GET /v1/translation/status

Public transparency endpoint that surfaces multilingual coverage statistics
for the 4 languages (en / zh / ko / ja-baseline) across:

  - `am_law` body_{en,zh,ko}
  - `am_law_article` body_{en,zh,ko}
  - `programs.title_en` / `programs.summary_en`
  - `am_law_translation_review_queue` pending counts

Anti-詐欺 signal: users can see exactly what fraction of the corpus is
machine-fetched primary-source translation vs. still in the manual review
queue. We never auto-translate, so coverage growth is honest.

Route:
    GET /v1/translation/status
        ?lang=en|zh|ko|all         (default all)

Response shape:
    {
      "languages": {
        "en": {
          "laws": {"total": int, "filled": int, "coverage_pct": float},
          "articles": {"total": int, "filled": int, "coverage_pct": float},
          "programs": {"total": int, "filled": int, "coverage_pct": float},
          "review_queue_pending": int,
          "last_refreshed_at": "<ISO8601>" | null
        },
        "zh": { ... },
        "ko": { ... }
      },
      "generated_at": "<ISO8601>",
      "disclaimer": "<licensing/coverage note>"
    }
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v1/translation", tags=["translation", "transparency"])

_DISCLAIMER = (
    "Multilingual coverage is sourced exclusively from primary government "
    "publications (japaneselawtranslation.go.jp CC-BY 4.0, ministry English "
    "sub-paths, JETRO zh-cn/zh-tw/kr public-domain mirrors). NEVER "
    "auto-translated by an LLM. Missing rows surface in the manual review "
    "queue at /status/translation_review_queue. Coverage figures honest as "
    "of `generated_at`."
)


def _autonomath_db_path() -> Path:
    env = os.environ.get("AUTONOMATH_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _jpintel_db_path() -> Path:
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "jpintel.db"


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _open(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _scalar(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> int:
    try:
        row = conn.execute(sql, args).fetchone()
        if row is None:
            return 0
        v = row[0]
        return int(v) if v is not None else 0
    except sqlite3.Error:
        return 0


def _last_refresh(conn: sqlite3.Connection, target_lang: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT MAX(finished_at) FROM am_law_translation_refresh_log "
            "WHERE target_lang = ? AND finished_at IS NOT NULL",
            (target_lang,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.Error:
        return None
    return None


def _coverage_pct(filled: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(filled / total * 100, 2)


def _law_stats(conn: sqlite3.Connection, lang: str) -> dict[str, Any]:
    total_laws = _scalar(conn, "SELECT COUNT(*) FROM am_law")
    filled_laws = _scalar(conn, f"SELECT COUNT(*) FROM am_law WHERE body_{lang} IS NOT NULL")
    total_articles = _scalar(conn, "SELECT COUNT(*) FROM am_law_article")
    filled_articles = _scalar(
        conn,
        f"SELECT COUNT(*) FROM am_law_article WHERE body_{lang} IS NOT NULL",
    )
    pending = _scalar(
        conn,
        "SELECT COUNT(*) FROM am_law_translation_review_queue "
        "WHERE target_lang = ? AND (operator_decision IS NULL OR operator_decision = 'pending')",
        (lang,),
    )
    return {
        "laws": {
            "total": total_laws,
            "filled": filled_laws,
            "coverage_pct": _coverage_pct(filled_laws, total_laws),
        },
        "articles": {
            "total": total_articles,
            "filled": filled_articles,
            "coverage_pct": _coverage_pct(filled_articles, total_articles),
        },
        "review_queue_pending": pending,
        "last_refreshed_at": _last_refresh(conn, lang),
    }


def _program_stats(conn: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None:
        return {"total": 0, "filled": 0, "coverage_pct": 0.0}
    try:
        total = _scalar(
            conn,
            "SELECT COUNT(*) FROM programs "
            "WHERE COALESCE(excluded,0)=0 AND tier IN ('S','A','B','C')",
        )
        filled = _scalar(
            conn,
            "SELECT COUNT(*) FROM programs "
            "WHERE COALESCE(excluded,0)=0 AND tier IN ('S','A','B','C') "
            "  AND title_en IS NOT NULL AND summary_en IS NOT NULL",
        )
    except sqlite3.Error:
        return {"total": 0, "filled": 0, "coverage_pct": 0.0}
    return {
        "total": total,
        "filled": filled,
        "coverage_pct": _coverage_pct(filled, total),
    }


@router.get("/status")
def translation_status(
    lang: str = Query(default="all", pattern="^(en|zh|ko|all)$"),
) -> dict[str, Any]:
    """Return coverage statistics for one or all of en/zh/ko."""
    am_conn = _open(_autonomath_db_path())
    jp_conn = _open(_jpintel_db_path())
    if am_conn is None and jp_conn is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "translation_corpus_unavailable",
                "hint": "autonomath.db + jpintel.db both unreachable",
            },
        )
    target_langs = ["en", "zh", "ko"] if lang == "all" else [lang]
    out: dict[str, Any] = {"languages": {}}
    for tl in target_langs:
        entry: dict[str, Any] = {
            "laws": {"total": 0, "filled": 0, "coverage_pct": 0.0},
            "articles": {"total": 0, "filled": 0, "coverage_pct": 0.0},
            "programs": {"total": 0, "filled": 0, "coverage_pct": 0.0},
            "review_queue_pending": 0,
            "last_refreshed_at": None,
        }
        if am_conn is not None:
            entry.update(_law_stats(am_conn, tl))
        if tl == "en":
            entry["programs"] = _program_stats(jp_conn)
        out["languages"][tl] = entry
    if am_conn is not None:
        am_conn.close()
    if jp_conn is not None:
        jp_conn.close()
    out["generated_at"] = _utcnow_iso()
    out["disclaimer"] = _DISCLAIMER
    return out
