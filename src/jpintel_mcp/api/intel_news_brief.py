"""POST /v1/intel/news_brief -- local-facts news brief.

No web fetch and no LLM call. The endpoint only reshapes already-ingested
facts and their source metadata into a compact brief.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api import deps as api_deps

# DbDep MUST be imported at module-load time, not under TYPE_CHECKING:
# `from __future__ import annotations` lifts the route handler's `conn:
# DbDep` annotation into a string forward-reference. FastAPI resolves
# annotations at route registration; if the symbol isn't real, it falls
# back to treating `conn` as a normal Query parameter and every request
# 422s with `{"loc":["query","conn"],"msg":"Field required"}`.
DbDep = api_deps.DbDep

router = APIRouter(prefix="/v1/intel", tags=["intel"])


_CHANGE_TERMS = (
    "change",
    "changed",
    "update",
    "updated",
    "revision",
    "amendment",
    "recent",
    "改正",
    "変更",
    "更新",
    "改定",
    "開始",
    "終了",
    "締切",
    "公募",
)
_ENFORCEMENT_TERMS = (
    "enforcement",
    "violation",
    "penalty",
    "sanction",
    "revocation",
    "行政処分",
    "処分",
    "不正",
    "違反",
    "取消",
    "返還",
)


class NewsBriefRequest(BaseModel):
    program: str | None = Field(None, max_length=200)
    law: str | None = Field(None, max_length=200)
    houjin: str | None = Field(None, max_length=32)
    industry: str | None = Field(None, max_length=100)
    max_items: int = Field(5, ge=1, le=20)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _normalize_houjin(value: str | None) -> str | None:
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _source_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_url": row.get("source_url"),
        "fetched_at": row.get("fetched_at"),
        "field_name": row.get("field_name"),
    }


def _fact_summary(row: dict[str, Any]) -> str:
    value = (
        _text(row.get("field_value_text"))
        or _text(row.get("field_value_numeric"))
        or _text(row.get("field_value_json"))
        or _text(row.get("value"))
        or ""
    )
    field = _text(row.get("field_name")) or "fact"
    return f"{field}: {value}" if value else field


def _fetch_fact_rows(
    conn: sqlite3.Connection, payload: NewsBriefRequest, known_gaps: list[str]
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "am_entity_facts"):
        known_gaps.append("am_entity_facts table is not available")
        return []

    cols = _columns(conn, "am_entity_facts")
    select = {
        "entity_id": "entity_id" if "entity_id" in cols else "NULL",
        "field_name": "field_name" if "field_name" in cols else "NULL",
        "field_value_text": "field_value_text" if "field_value_text" in cols else "NULL",
        "field_value_numeric": ("field_value_numeric" if "field_value_numeric" in cols else "NULL"),
        "field_value_json": "field_value_json" if "field_value_json" in cols else "NULL",
        "source_url": "source_url" if "source_url" in cols else "NULL",
        "fetched_at": (
            "fetched_at"
            if "fetched_at" in cols
            else ("created_at" if "created_at" in cols else "NULL")
        ),
    }

    clauses: list[str] = []
    params: list[Any] = []
    searchable = [
        col
        for col in ("entity_id", "field_name", "field_value_text", "field_value_json", "source_url")
        if col in cols
    ]
    for _label, value in (
        ("program", payload.program),
        ("law", payload.law),
        ("industry", payload.industry),
    ):
        if not value or not searchable:
            continue
        term = f"%{value.strip()}%"
        clauses.append("(" + " OR ".join(f"{col} LIKE ?" for col in searchable) + ")")
        params.extend([term] * len(searchable))

    houjin = _normalize_houjin(payload.houjin)
    if houjin and searchable:
        candidates = [houjin, f"houjin:{houjin}"]
        clauses.append(
            "("
            + " OR ".join(f"{col} IN ({','.join('?' for _ in candidates)})" for col in searchable)
            + ")"
        )
        params.extend(candidates * len(searchable))

    if not clauses:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_query",
                "message": "one of program, law, houjin, or industry is required",
            },
        )

    sql = (
        "SELECT "
        + ", ".join(f"{expr} AS {alias}" for alias, expr in select.items())
        + " FROM am_entity_facts WHERE "
        + " OR ".join(clauses)
        + " ORDER BY fetched_at DESC NULLS LAST LIMIT ?"
    )
    params.append(int(payload.max_items) * 6)
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        known_gaps.append(f"am_entity_facts query failed: {exc}")
        return []


def _dedupe_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("source_url")
        if not url or url in seen:
            continue
        seen.add(str(url))
        links.append({"url": url, "fetched_at": row.get("fetched_at")})
    return links


@router.post(
    "/news_brief",
    summary="Recent local-facts news brief for program/law/houjin/industry",
)
def post_news_brief(
    payload: Annotated[NewsBriefRequest, Body(...)],
    conn: DbDep,
) -> dict[str, Any]:
    known_gaps: list[str] = []
    rows = _fetch_fact_rows(conn, payload, known_gaps)

    recent_changes: list[dict[str, Any]] = []
    enforcement_mentions: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            _text(row.get(k)) or "" for k in ("field_name", "field_value_text", "field_value_json")
        )
        item = {"summary": _fact_summary(row), "source": _source_item(row)}
        if _contains_any(haystack, _ENFORCEMENT_TERMS):
            enforcement_mentions.append(item)
        elif _contains_any(haystack, _CHANGE_TERMS):
            recent_changes.append(item)

    if not rows:
        known_gaps.append("no matching local facts found for the supplied query")
    elif not recent_changes and not enforcement_mentions:
        known_gaps.append("matching facts exist, but none are tagged as changes or enforcement")

    fetched_values = [str(row["fetched_at"]) for row in rows if row.get("fetched_at")]
    as_of = max(fetched_values) if fetched_values else datetime.now(UTC).isoformat()

    return {
        "query": payload.model_dump(exclude_none=True),
        "recent_changes": recent_changes[: payload.max_items],
        "enforcement_mentions": enforcement_mentions[: payload.max_items],
        "source_links": _dedupe_links(rows)[: payload.max_items],
        "as_of": as_of,
        "known_gaps": list(dict.fromkeys(known_gaps)),
    }


__all__ = ["router"]
