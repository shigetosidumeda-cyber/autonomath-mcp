"""REST surface for the per-program narrative cache (Wave 24 → REST).

Mirrors :func:`jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half.
get_program_narrative` on the wire so a customer agent that uses HTTP
(no MCP transport) can read the same pre-computed narrative the MCP
tool returns.

Why a dedicated REST route
--------------------------
Wave 24 shipped the narrative cache as MCP-only. The W29-9 customer
agent e2e flow (``tests/test_customer_e2e.py``) exercises::

    GET /v1/programs/search                         → candidates
    GET /v1/programs/{id}/eligibility_predicate
    GET /v1/programs/{id}/narrative                 ← THIS ROUTE
    POST /v1/evidence/packets/batch
    GET /v1/audit/proof/{epid}

Step 4 was MCP-only after Wave 24, which broke HTTP-only customer
agents. We expose the same SELECT here so the chain walks end-to-end.

Source of truth (in lookup order):
  1. ``am_program_narrative_full`` (W20 fast-path, migration wave24_149)
     — pre-rendered ONE coherent prose body + 反駁 bank, keyed by
     program_id PRIMARY KEY. Consulted FIRST when the caller asks for
     the default surface (lang='ja', section='all').
  2. ``am_program_narrative`` (migration wave24_136 + wave24_141)
     — 4-section per-language rows (overview / eligibility /
     application_flow / pitfalls). Used as the fall-back when the W20
     cache misses, when section≠'all', or when lang='en'.

Returned envelope carries the standard
``_disclaimer + corpus_snapshot_id + audit_seal`` trio so the e2e step
7 (envelope shape audit) is satisfied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.narrative")

router = APIRouter(prefix="/v1/programs", tags=["narrative"])


_NARRATIVE_SECTIONS = ("overview", "eligibility", "application_flow", "pitfalls")
_SectionLiteral = Literal["all", "overview", "eligibility", "application_flow", "pitfalls"]
_LangLiteral = Literal["ja", "en"]


# Pre-computed narrative is corpus-derived prose; fence it from being
# read as 税理士法 §52 advice. Mirrors the MCP-side disclaimer surface.
_NARRATIVE_DISCLAIMER = (
    "本 narrative は jpcite が公開資料 (公募要領・通達・国税庁 Q&A 等) を整理した解説で、"
    "税理士法 §52 に基づく個別具体的な税務判断・申請書作成代行ではありません。"
    "最終的な受給可否・申請書面は primary source (source_url) と税理士・行政書士の確認を"
    "必ず行ってください。 jpcite は generation accuracy について保証しません。"
)


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


def _open_autonomath_ro() -> sqlite3.Connection:
    """Read-only autonomath.db connection (mirrors eligibility_predicate.py)."""
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _fetch_full_cache(am_conn: sqlite3.Connection, program_id: str) -> dict[str, Any] | None:
    """Return W20 full-narrative cache row for program_id or None."""
    if not _table_exists(am_conn, "am_program_narrative_full"):
        return None
    try:
        row = am_conn.execute(
            """
            SELECT narrative_md, counter_arguments_md, generated_at,
                   model_used, content_hash,
                   source_program_corpus_snapshot_id
              FROM am_program_narrative_full
             WHERE program_id = ?
            """,
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None or not row["narrative_md"]:
        return None
    return {
        "narrative_md": row["narrative_md"],
        "counter_arguments_md": row["counter_arguments_md"],
        "generated_at": row["generated_at"],
        "model_used": row["model_used"],
        "content_hash": row["content_hash"],
        "source_program_corpus_snapshot_id": row["source_program_corpus_snapshot_id"],
    }


def _fetch_section_rows(
    am_conn: sqlite3.Connection,
    program_id: str,
    *,
    lang: str,
    section: str,
) -> list[dict[str, Any]]:
    """Return per-section narrative rows or [] when table missing / no rows."""
    if not _table_exists(am_conn, "am_program_narrative"):
        return []
    try:
        if section == "all":
            placeholders = ",".join("?" for _ in _NARRATIVE_SECTIONS)
            rows = am_conn.execute(
                f"""
                SELECT section, lang, body_text, content_hash,
                       is_active, generated_at, source_url_json,
                       model_id, literal_quote_check_passed
                  FROM am_program_narrative
                 WHERE program_id = ?
                   AND lang = ?
                   AND section IN ({placeholders})
                   AND COALESCE(is_active, 1) = 1
                 ORDER BY CASE section
                            WHEN 'overview' THEN 0
                            WHEN 'eligibility' THEN 1
                            WHEN 'application_flow' THEN 2
                            WHEN 'pitfalls' THEN 3
                            ELSE 99
                          END
                """,
                (program_id, lang, *_NARRATIVE_SECTIONS),
            ).fetchall()
        else:
            rows = am_conn.execute(
                """
                SELECT section, lang, body_text, content_hash,
                       is_active, generated_at, source_url_json,
                       model_id, literal_quote_check_passed
                  FROM am_program_narrative
                 WHERE program_id = ?
                   AND lang = ?
                   AND section = ?
                   AND COALESCE(is_active, 1) = 1
                """,
                (program_id, lang, section),
            ).fetchall()
    except sqlite3.Error as exc:
        _log.exception("am_program_narrative query failed: %s", exc)
        return []

    return [
        {
            "section": r["section"],
            "lang": r["lang"],
            "body_text": r["body_text"] or "",
            "content_hash": r["content_hash"],
            "is_active": (bool(r["is_active"]) if r["is_active"] is not None else True),
            "source_url_json": _safe_json_loads(r["source_url_json"]),
            "generated_at": r["generated_at"],
            "model_id": r["model_id"],
            "literal_quote_check_passed": (
                bool(r["literal_quote_check_passed"])
                if r["literal_quote_check_passed"] is not None
                else False
            ),
        }
        for r in rows
    ]


@router.get(
    "/{program_id}/narrative",
    summary="Per-program pre-computed narrative (cache hit + section fallback)",
    description=(
        "Returns the pre-computed narrative for a program from the "
        "autonomath narrative cache. Lookup order:\n\n"
        "1. `am_program_narrative_full` (W20 fast-path) — one coherent "
        "   ja prose body + 反駁 bank, returned as `narrative_full`.\n"
        "2. `am_program_narrative` (4-section corpus) — used when the "
        "   W20 cache misses, when `section ≠ 'all'`, or when `lang='en'`.\n\n"
        "**section** = `all | overview | eligibility | application_flow | pitfalls`.\n\n"
        "**lang** = `ja | en`.\n\n"
        "Mirrors the MCP tool ``get_program_narrative`` (Wave 24)."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Narrative envelope + `_disclaimer` + `corpus_snapshot_id` "
                "+ `audit_seal` (paid keys only). May contain "
                "`narrative_full` (W20 cache hit) or `results` (4-section "
                "fall-back) — at least one of the two paths is always "
                "consulted."
            ),
        },
        404: {
            "description": ("No narrative cached for this program_id."),
        },
    },
)
def get_narrative(
    program_id: Annotated[
        str,
        PathParam(
            description=(
                "jpi_programs.unified_id (例: 'UNI-75690a3d74'). Discover via /v1/programs/search."
            ),
            min_length=4,
            max_length=64,
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    section: Annotated[
        _SectionLiteral,
        Query(
            description=(
                "Which section to return. 'all' returns up to 4 rows "
                "(overview / eligibility / application_flow / pitfalls)."
            ),
        ),
    ] = "all",
    lang: Annotated[
        _LangLiteral,
        Query(description="Body language. 'ja' is the default corpus."),
    ] = "ja",
) -> JSONResponse:
    """Return the narrative envelope for ``program_id``."""

    am_conn = _open_autonomath_ro()
    cache_hit = False
    cache_source: str | None = None
    full_cache: dict[str, Any] | None = None
    section_rows: list[dict[str, Any]] = []
    try:
        # W20 fast-path: only consulted on the default surface.
        if lang == "ja" and section == "all":
            full_cache = _fetch_full_cache(am_conn, program_id)
            if full_cache is not None:
                cache_hit = True
                cache_source = "am_program_narrative_full"

        # Always also try the 4-section corpus when the full cache missed
        # OR when the caller asked for a single section / English body.
        if full_cache is None:
            section_rows = _fetch_section_rows(am_conn, program_id, lang=lang, section=section)
            if section_rows:
                cache_source = "am_program_narrative"
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    if full_cache is None and not section_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no narrative cached for program_id={program_id!r} "
                f"(section={section!r}, lang={lang!r}). Either the id is "
                "unknown or no narrative has been generated yet."
            ),
        )

    body: dict[str, Any] = {
        "program_id": program_id,
        "section": section,
        "lang": lang,
        "results": section_rows,
        "total": len(section_rows),
        "limit": 4 if section == "all" else 1,
        "offset": 0,
        "_cache_hit": cache_hit,
        "_cache_source": cache_source,
        "_disclaimer": _NARRATIVE_DISCLAIMER,
    }
    if full_cache is not None:
        body["narrative_full"] = full_cache

    # Standard envelope trio: corpus_snapshot_id + audit_seal.
    attach_corpus_snapshot(body, conn)
    log_usage(conn, ctx, "programs.narrative", strict_metering=True)
    attach_seal_to_body(
        body,
        endpoint="programs.narrative",
        request_params={
            "program_id": program_id,
            "section": section,
            "lang": lang,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    headers = dict(snapshot_headers(conn))
    # Surface a coarse cache hint so the e2e (and prod observability)
    # can attribute hit / miss without parsing the body.
    headers["x-cache"] = "hit" if cache_hit else "miss"
    return JSONResponse(content=body, headers=headers)


__all__ = ["router"]
