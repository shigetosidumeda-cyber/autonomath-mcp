"""REST handlers for am_law_tsutatsu_all (migration 253) + am_law_guideline
(migration 254). Read-only.

Endpoints:
  GET /v1/laws/tsutatsu_all/search
  GET /v1/laws/tsutatsu_all/{tsutatsu_id}
  GET /v1/laws/tsutatsu_all/agencies
  GET /v1/laws/guideline/search
  GET /v1/laws/guideline/{guideline_id}
  GET /v1/laws/guideline/issuers

NO LLM call. No aggregator URLs surfaced.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/laws", tags=["laws-tsutatsu-guideline"])


def _autonomath_db_path() -> Path:
    path = os.environ.get("AUTONOMATH_DB_PATH")
    if path:
        return Path(path)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "autonomath.db"


def _connect() -> sqlite3.Connection:
    path = _autonomath_db_path()
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "autonomath_db_unavailable", "path": str(path)},
        )
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _row_to_tsutatsu(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tsutatsu_id": row["tsutatsu_id"],
        "agency_id": row["agency_id"],
        "agency_name": row["agency_name"],
        "tsutatsu_number": row["tsutatsu_number"],
        "title": row["title"],
        "body_excerpt": row["body_excerpt"],
        "issued_date": row["issued_date"],
        "last_revised": row["last_revised"],
        "industry_jsic_major": row["industry_jsic_major"],
        "applicable_law_id": row["applicable_law_id"],
        "document_type": row["document_type"],
        "source_url": row["source_url"],
        "full_text_url": row["full_text_url"],
        "pdf_url": row["pdf_url"],
        "license": row["license"],
    }


def _row_to_guideline(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "guideline_id": row["guideline_id"],
        "issuer_type": row["issuer_type"],
        "issuer_org": row["issuer_org"],
        "issuer_agency_id": row["issuer_agency_id"],
        "title": row["title"],
        "short_title": row["short_title"],
        "body_excerpt": row["body_excerpt"],
        "industry_jsic_major": row["industry_jsic_major"],
        "industry_jsic_minor": row["industry_jsic_minor"],
        "industry_jsic_label": row["industry_jsic_label"],
        "target_audience": row["target_audience"],
        "compliance_status": row["compliance_status"],
        "issued_date": row["issued_date"],
        "last_revised": row["last_revised"],
        "document_type": row["document_type"],
        "source_url": row["source_url"],
        "full_text_url": row["full_text_url"],
        "pdf_url": row["pdf_url"],
        "license": row["license"],
    }


@router.get("/tsutatsu_all/search", summary="Search 通達 across 15 ministries")
def search_tsutatsu_all(
    q: str | None = Query(None),
    agency_id: str | None = Query(None),
    industry_jsic_major: str | None = Query(None),
    issued_after: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    conn = _connect()
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "rowid IN (SELECT rowid FROM am_law_tsutatsu_all_fts WHERE am_law_tsutatsu_all_fts MATCH ?)"
        )
        params.append(q)
    if agency_id:
        where.append("agency_id = ?")
        params.append(agency_id)
    if industry_jsic_major:
        where.append("industry_jsic_major = ?")
        params.append(industry_jsic_major)
    if issued_after:
        where.append("issued_date >= ?")
        params.append(issued_after)
    sql = "SELECT * FROM am_law_tsutatsu_all"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY issued_date DESC NULLS LAST, tsutatsu_id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "253_law_tsutatsu_all",
                "reason": str(exc),
            },
        )
    count_sql = "SELECT COUNT(*) AS c FROM am_law_tsutatsu_all"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = conn.execute(count_sql, params[:-2]).fetchone()["c"]
    conn.close()
    return JSONResponse(
        {
            "ok": True,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "results": [_row_to_tsutatsu(r) for r in rows],
        }
    )


@router.get("/tsutatsu_all/agencies", summary="List agencies + tsutatsu counts")
def list_tsutatsu_agencies() -> JSONResponse:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM v_tsutatsu_all_agency_density").fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "253_law_tsutatsu_all",
                "reason": str(exc),
            },
        )
    conn.close()
    return JSONResponse({"ok": True, "agencies": [dict(r) for r in rows]})


@router.get("/tsutatsu_all/{tsutatsu_id}", summary="Get full body of single 通達")
def get_tsutatsu_detail(tsutatsu_id: str) -> JSONResponse:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM am_law_tsutatsu_all WHERE tsutatsu_id = ?",
            (tsutatsu_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "253_law_tsutatsu_all",
                "reason": str(exc),
            },
        )
    conn.close()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "tsutatsu_not_found", "tsutatsu_id": tsutatsu_id},
        )
    out = _row_to_tsutatsu(row)
    out["body_text"] = row["body_text"]
    out["content_hash"] = row["content_hash"]
    out["ingested_at"] = row["ingested_at"]
    out["last_verified"] = row["last_verified"]
    return JSONResponse({"ok": True, "tsutatsu": out})


@router.get("/guideline/search", summary="Search 業種ガイドライン")
def search_guideline(
    q: str | None = Query(None),
    issuer_type: str | None = Query(None),
    issuer_org: str | None = Query(None),
    industry_jsic_major: str | None = Query(None),
    compliance_status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    conn = _connect()
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "rowid IN (SELECT rowid FROM am_law_guideline_fts WHERE am_law_guideline_fts MATCH ?)"
        )
        params.append(q)
    if issuer_type:
        where.append("issuer_type = ?")
        params.append(issuer_type)
    if issuer_org:
        where.append("issuer_org = ?")
        params.append(issuer_org)
    if industry_jsic_major:
        where.append("industry_jsic_major = ?")
        params.append(industry_jsic_major)
    if compliance_status:
        where.append("compliance_status = ?")
        params.append(compliance_status)
    sql = "SELECT * FROM am_law_guideline"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY issued_date DESC NULLS LAST, guideline_id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "254_law_guideline",
                "reason": str(exc),
            },
        )
    count_sql = "SELECT COUNT(*) AS c FROM am_law_guideline"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = conn.execute(count_sql, params[:-2]).fetchone()["c"]
    conn.close()
    return JSONResponse(
        {
            "ok": True,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "results": [_row_to_guideline(r) for r in rows],
        }
    )


@router.get("/guideline/issuers", summary="List guideline issuers + counts")
def list_guideline_issuers() -> JSONResponse:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT issuer_type, issuer_org, COUNT(*) AS guideline_count
               FROM am_law_guideline GROUP BY issuer_type, issuer_org
               ORDER BY guideline_count DESC""",
        ).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "254_law_guideline",
                "reason": str(exc),
            },
        )
    conn.close()
    return JSONResponse({"ok": True, "issuers": [dict(r) for r in rows]})


@router.get("/guideline/{guideline_id}", summary="Get full body of single guideline")
def get_guideline_detail(guideline_id: str) -> JSONResponse:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM am_law_guideline WHERE guideline_id = ?",
            (guideline_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "schema_pending_migration",
                "migration": "254_law_guideline",
                "reason": str(exc),
            },
        )
    conn.close()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "guideline_not_found", "guideline_id": guideline_id},
        )
    out = _row_to_guideline(row)
    out["body_text"] = row["body_text"]
    out["content_hash"] = row["content_hash"]
    out["related_law_ids_json"] = row["related_law_ids_json"]
    out["ingested_at"] = row["ingested_at"]
    out["last_verified"] = row["last_verified"]
    return JSONResponse({"ok": True, "guideline": out})
