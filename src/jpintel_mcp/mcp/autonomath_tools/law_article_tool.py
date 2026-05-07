#!/usr/bin/env python3
"""Wave 13 Agent #3 — law article MCP tool.

Exposes two functions to AutonoMath customer LLMs:

  get_law_article(law_name_or_canonical_id, article_number)
      Exact lookup. Accepts canonical_id ('law:sozei-tokubetsu') or
      canonical/short name ('租税特別措置法' / '措置法').
      Returns: {found, law, article_number, article_number_sort, title,
                text_summary, text_full, effective_from, effective_until,
                last_amended, source_url, source_fetched_at}

  search_law_articles(law_name, keyword, limit=20)
      Keyword search against title || text_summary for articles under the
      given law.  Returns list of envelopes.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from .error_envelope import make_error

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))


def _resolve_law(con: sqlite3.Connection, needle: str) -> dict[str, Any] | None:
    """Resolve a law name or canonical_id to {canonical_id, canonical_name}."""
    if not needle:
        return None
    needle = needle.strip()

    # canonical_id direct hit
    if needle.startswith("law:"):
        row = con.execute(
            "SELECT canonical_id, canonical_name FROM am_law WHERE canonical_id = ?",
            (needle,),
        ).fetchone()
        if row:
            return {"canonical_id": row[0], "canonical_name": row[1]}
        return None

    # Exact canonical_name or short_name
    row = con.execute(
        """
        SELECT canonical_id, canonical_name FROM am_law
         WHERE canonical_name = ? OR short_name = ?
         LIMIT 1
        """,
        (needle, needle),
    ).fetchone()
    if row:
        return {"canonical_id": row[0], "canonical_name": row[1]}

    # LIKE fallback
    row = con.execute(
        """
        SELECT canonical_id, canonical_name FROM am_law
         WHERE canonical_name LIKE ? OR short_name LIKE ?
         ORDER BY LENGTH(canonical_name) ASC
         LIMIT 1
        """,
        (f"%{needle}%", f"%{needle}%"),
    ).fetchone()
    if row:
        return {"canonical_id": row[0], "canonical_name": row[1]}
    return None


def _normalize_article_number(raw: str) -> list[str]:
    """Return a list of candidate article_number strings to try in order.

    Accepts:  '第41条の19', '41条の19', '41の19', '41-19', '41.19', '41'
    Canonical form in DB is '第N条' or '第N条のM' or '第N条のMのL'.
    """
    if not raw:
        return []
    raw = str(raw).strip()
    candidates = [raw]

    # If already starts with '第' and contains '条', treat as canonical form.
    if raw.startswith("第") and "条" in raw:
        return candidates

    # Handle digit-only forms.
    body = raw
    if body.startswith("第"):
        body = body[1:]

    # Canonical form insertion: parse N[sep]M[sep]L and produce 第N条のMのL.
    # Accept separators: . - _ の ／ /
    for sep in [".", "-", "_", "／", "/"]:
        body = body.replace(sep, "の")

    if "条" in body:
        # Something like '41条の19' — just prepend 第.
        candidates.append("第" + body)
    else:
        # Something like '41の19' → 第41条の19. Insert 条 after first の-split.
        parts = body.split("の")
        if len(parts) == 1:
            # Just a number.
            candidates.append("第" + parts[0] + "条")
        else:
            head, *rest = parts
            candidates.append("第" + head + "条" + "".join("の" + p for p in rest))
        # Also try naive append (第41の19条) in case schema differs.
        candidates.append("第" + body + "条")

    # Also try just prepending 第 if raw already had 条.
    if "条" in raw and not raw.startswith("第"):
        candidates.append("第" + raw)
    return list(dict.fromkeys(candidates))  # dedupe preserve order


def _envelope_article(row: sqlite3.Row, law: dict[str, Any]) -> dict[str, Any]:
    return {
        "found": True,
        "law": {
            "canonical_id": law["canonical_id"],
            "canonical_name": law["canonical_name"],
        },
        "article_id": row["article_id"],
        "article_number": row["article_number"],
        "article_number_sort": row["article_number_sort"],
        "title": row["title"],
        "text_summary": row["text_summary"],
        "text_full": row["text_full"],
        "effective_from": row["effective_from"],
        "effective_until": row["effective_until"],
        "last_amended": row["last_amended"],
        "source_url": row["source_url"],
        "source_fetched_at": row["source_fetched_at"],
    }


def _missing_arg_envelope(field: str, law_needle: str, article_number: str | None) -> dict[str, Any]:
    """Hard-error envelope for empty required args. Preserves queried metadata."""
    err = make_error(
        code="missing_required_arg",
        message=f"{field} is required.",
        hint=f"Pass a non-empty {field}.",
        retry_with=["search_laws", "get_law"],
        field=field,
        extra={
            "queried": {
                "law_name_or_canonical_id": law_needle,
                "article_number": article_number,
            },
        },
    )
    return {
        "found": False,
        "law": {"canonical_id": None, "canonical_name": None},
        "article_number": article_number,
        "title": None,
        "text_summary": None,
        "source_url": None,
        "error": err["error"],
    }


def _no_match_envelope(
    code: str,
    message: str,
    *,
    law_needle: str,
    article_number: str | None,
    law_canonical_id: str | None = None,
    law_canonical_name: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """Soft-error envelope for valid query / no rows. ``code`` is one of
    ``seed_not_found`` (law not found) or ``no_matching_records`` (article
    missing under a resolved law)."""
    err = make_error(
        code=code,  # type: ignore[arg-type]
        message=message,
        hint=(
            "Verify the law name via search_laws / get_law, then retry. "
            "Article numbers must include 第N条 or be normalizable (41の19 / 41-19)."
        ),
        retry_with=["search_laws", "get_law"],
        suggested_tools=["search_laws"],
        field=field,
        extra={
            "queried": {
                "law_name_or_canonical_id": law_needle,
                "article_number": article_number,
            },
        },
    )
    return {
        "found": False,
        "law": {
            "canonical_id": law_canonical_id,
            "canonical_name": law_canonical_name,
        },
        "article_number": article_number,
        "title": None,
        "text_summary": None,
        "source_url": None,
        "error": err["error"],
    }


def get_law_article(law_name_or_canonical_id: str, article_number: str) -> dict[str, Any]:
    """Exact article lookup."""
    if not law_name_or_canonical_id:
        return _missing_arg_envelope(
            "law_name_or_canonical_id",
            "",
            article_number,
        )
    if not article_number:
        return _missing_arg_envelope(
            "article_number",
            law_name_or_canonical_id,
            None,
        )

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        law = _resolve_law(con, law_name_or_canonical_id)
        if not law:
            return _no_match_envelope(
                "seed_not_found",
                f"law not found: {law_name_or_canonical_id!r}",
                law_needle=law_name_or_canonical_id,
                article_number=article_number,
                field="law_name_or_canonical_id",
            )

        for cand in _normalize_article_number(article_number):
            row = con.execute(
                """
                SELECT article_id, article_number, article_number_sort, title,
                       text_summary, text_full, effective_from, effective_until,
                       last_amended, source_url, source_fetched_at
                  FROM am_law_article
                 WHERE law_canonical_id = ? AND article_number = ?
                 LIMIT 1
                """,
                (law["canonical_id"], cand),
            ).fetchone()
            if row:
                return _envelope_article(row, law)

        return _no_match_envelope(
            "no_matching_records",
            f"article {article_number!r} not found in {law['canonical_name']}",
            law_needle=law_name_or_canonical_id,
            article_number=article_number,
            law_canonical_id=law["canonical_id"],
            law_canonical_name=law["canonical_name"],
            field="article_number",
        )
    finally:
        con.close()


def search_law_articles(
    law_name: str,
    keyword: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Keyword search within a single law."""
    if not law_name:
        return {"found": False, "reason": "law_name is required", "results": []}

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        law = _resolve_law(con, law_name)
        if not law:
            return {
                "found": False,
                "reason": "law_not_found",
                "law": {"queried": law_name},
                "results": [],
            }

        params: list[Any] = [law["canonical_id"]]
        where = "law_canonical_id = ?"
        if keyword:
            where += " AND (title LIKE ? OR text_summary LIKE ?)"
            kw = f"%{keyword}%"
            params += [kw, kw]

        rows = con.execute(
            f"""
            SELECT article_id, article_number, article_number_sort, title,
                   text_summary, effective_from, last_amended, source_url
              FROM am_law_article
             WHERE {where}
             ORDER BY article_number_sort ASC
             LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

        results = [
            {
                "article_id": r["article_id"],
                "article_number": r["article_number"],
                "article_number_sort": r["article_number_sort"],
                "title": r["title"],
                "text_summary": r["text_summary"],
                "effective_from": r["effective_from"],
                "last_amended": r["last_amended"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]
        return {
            "found": bool(results),
            "law": {
                "canonical_id": law["canonical_id"],
                "canonical_name": law["canonical_name"],
            },
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }
    finally:
        con.close()


if __name__ == "__main__":
    import json

    # Quick smoke test when invoked directly.
    print(
        json.dumps(
            get_law_article("租税特別措置法", "第41条の19"),
            ensure_ascii=False,
            indent=2,
        )
    )
    print(
        json.dumps(
            search_law_articles("中小企業等経営強化法", "経営力向上"),
            ensure_ascii=False,
            indent=2,
        )
    )
