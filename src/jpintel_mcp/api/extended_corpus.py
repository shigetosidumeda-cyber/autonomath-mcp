"""REST handlers for the Wave 32 extended corpus (Axis 1d+1e+1f).

Three primary-source corpora landed via migrations 228/229/230:

  * ``am_court_decisions_extended`` (mig 228) — 裁判所 hanrei_jp + NDL OAI
    extension to the existing 016 `court_decisions` (jpintel.db, 2,065).
  * ``am_industry_guidelines`` (mig 229) — 10 省庁 業種ガイドライン corpus
    keyed by JSIC major (19 majors A-T).
  * ``am_nta_tsutatsu_extended`` (mig 230) — 通達 section-level breakdown
    + full body, extending nta_tsutatsu_index (103).

# CHAIN: programs ←(related_program_ids)── court_decisions ←(related_law_ids)──
#        laws → tsutatsu sections → industry_guidelines (by JSIC).
# WHEN NOT: do not use this router for 国税庁 公表裁決事例 — those live on
#        the existing /v1/nta endpoints backed by 103 nta_saiketsu.

NO LLM. SQLite over autonomath.db. Each row is primary-source-cited (PDL
v1.0 / gov_standard). 1 req = 1 billable unit (¥3 metered).

Mounted under ``AnonIpLimitDep`` like other read surfaces — anonymous
3/day per IP, authenticated metered.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/v1", tags=["extended-corpus"])


_AUTONOMATH_DB: Path | None = None


def _autonomath_db_path() -> Path:
    global _AUTONOMATH_DB
    if _AUTONOMATH_DB is not None:
        return _AUTONOMATH_DB
    # Production: /data/autonomath.db. Dev: repo-root autonomath.db.
    candidate = Path("/data/autonomath.db")
    if candidate.exists() and candidate.stat().st_size > 0:
        _AUTONOMATH_DB = candidate
        return candidate
    repo_root = Path(__file__).resolve().parents[3]
    fallback = repo_root / "autonomath.db"
    _AUTONOMATH_DB = fallback
    return fallback


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_autonomath_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except json.JSONDecodeError:
        pass
    return []


# --------------------------------------------------------------------------
# /v1/court/decisions/extended
# --------------------------------------------------------------------------


@router.get(
    "/court/decisions/extended",
    summary="Search extended court decisions corpus",
    description=(
        "Returns paginated court decisions from the Wave 32 extended corpus "
        "(`am_court_decisions_extended`, migration 228). Filter by `level` "
        "(supreme/high/district/summary/family) and `case_type` "
        "(tax/admin/corporate/ip/labor/civil/criminal/other)."
    ),
)
def court_decisions_extended(
    level: Annotated[
        str | None,
        Query(description="Court level filter", pattern="^(supreme|high|district|summary|family)$"),
    ] = None,
    case_type: Annotated[
        str | None,
        Query(
            description="Case-type bucket",
            pattern="^(tax|admin|corporate|ip|labor|civil|criminal|other)$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if level:
        where.append("court_level = ?")
        params.append(level)
    if case_type:
        where.append("case_type = ?")
        params.append(case_type)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with _connect() as conn:
        try:
            count_row = conn.execute(
                f"SELECT COUNT(*) AS n FROM am_court_decisions_extended {where_sql}",
                params,
            ).fetchone()
            total = int(count_row["n"]) if count_row else 0
            rows = conn.execute(
                f"""
                SELECT unified_id, case_number, court, court_level, case_type,
                       case_name, decision_date, decision_type, subject_area,
                       related_law_ids_json, related_program_ids_json,
                       key_ruling, full_text_url, source_url, source, license
                FROM am_court_decisions_extended
                {where_sql}
                ORDER BY decision_date DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # Table missing (migration not yet applied on this image).
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"extended court corpus not initialized: {exc}",
            ) from exc

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "unified_id": r["unified_id"],
                "case_number": r["case_number"],
                "court": r["court"],
                "court_level": r["court_level"],
                "case_type": r["case_type"],
                "case_name": r["case_name"],
                "decision_date": r["decision_date"],
                "decision_type": r["decision_type"],
                "subject_area": r["subject_area"],
                "related_law_ids": _parse_json_list(r["related_law_ids_json"]),
                "related_program_ids": _parse_json_list(r["related_program_ids_json"]),
                "key_ruling": r["key_ruling"],
                "full_text_url": r["full_text_url"],
                "source_url": r["source_url"],
                "source": r["source"],
                "license": r["license"],
            }
            for r in rows
        ],
        "_disclaimer": (
            "Court-decision excerpts are retrieval-only citations from primary "
            "government sources (courts.go.jp / NDL). Not legal advice "
            "(弁護士法 §72). Always consult counsel before acting."
        ),
    }


# --------------------------------------------------------------------------
# /v1/industry/guidelines
# --------------------------------------------------------------------------


@router.get(
    "/industry/guidelines",
    summary="List sector guidelines by JSIC industry + ministry",
    description=(
        "Returns guideline documents from the Wave 32 industry corpus "
        "(`am_industry_guidelines`, migration 229). Filter by `industry` "
        "(JSIC major code A-T) and `ministry` "
        "(env/maff/mhlw/meti/mlit/mext/mof/mic/moj/mod/other)."
    ),
)
def industry_guidelines(
    industry: Annotated[
        str | None,
        Query(description="JSIC major code", pattern="^[A-T]$"),
    ] = None,
    ministry: Annotated[
        str | None,
        Query(
            description="Ministry code",
            pattern="^(env|maff|mhlw|meti|mlit|mext|mof|mic|moj|mod|other)$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if industry:
        where.append("industry_jsic_major = ?")
        params.append(industry)
    if ministry:
        where.append("ministry = ?")
        params.append(ministry)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with _connect() as conn:
        try:
            count_row = conn.execute(
                f"SELECT COUNT(*) AS n FROM am_industry_guidelines {where_sql}",
                params,
            ).fetchone()
            total = int(count_row["n"]) if count_row else 0
            rows = conn.execute(
                f"""
                SELECT guideline_id, ministry, industry_jsic_major,
                       industry_jsic_label, title, body, full_text_url,
                       pdf_url, issued_date, last_revised, document_type,
                       source_url, license
                FROM am_industry_guidelines
                {where_sql}
                ORDER BY last_revised DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"industry guidelines corpus not initialized: {exc}",
            ) from exc

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "guideline_id": r["guideline_id"],
                "ministry": r["ministry"],
                "industry_jsic_major": r["industry_jsic_major"],
                "industry_jsic_label": r["industry_jsic_label"],
                "title": r["title"],
                "body": r["body"],
                "full_text_url": r["full_text_url"],
                "pdf_url": r["pdf_url"],
                "issued_date": r["issued_date"],
                "last_revised": r["last_revised"],
                "document_type": r["document_type"],
                "source_url": r["source_url"],
                "license": r["license"],
            }
            for r in rows
        ],
        "_disclaimer": (
            "Industry guideline excerpts are retrieval-only citations from "
            "primary ministry sources. Operators must verify the latest revision "
            "at the ministry website before applying."
        ),
    }


# --------------------------------------------------------------------------
# /v1/nta/tsutatsu/{tsutatsu_id}/sections
# --------------------------------------------------------------------------


@router.get(
    "/nta/tsutatsu/{tsutatsu_id}/sections",
    summary="Return section-level breakdown of an NTA tsutatsu",
    description=(
        "Returns the section list for a given tsutatsu code (e.g. `法基通-9-2-3`)"
        " from the Wave 32 extended corpus (`am_nta_tsutatsu_extended`, "
        "migration 230). Includes `body_text` (full section body) and "
        "`applicable_tax_law_id` cross-reference where derivable."
    ),
)
def nta_tsutatsu_sections(tsutatsu_id: str) -> dict[str, Any]:
    # tsutatsu_id is the parent_code (e.g. '法基通-9-2-3'). Validate cheaply.
    if not tsutatsu_id or len(tsutatsu_id) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid tsutatsu_id",
        )

    with _connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT section_id, parent_code, law_canonical_id,
                       applicable_tax_law_id, article_number, section_number,
                       title, body_text, cross_references_json, source_url,
                       last_amended, ingested_at
                FROM am_nta_tsutatsu_extended
                WHERE parent_code = ?
                ORDER BY article_number ASC, section_number ASC, id ASC
                """,
                (tsutatsu_id,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"tsutatsu corpus not initialized: {exc}",
            ) from exc

    if not rows:
        # Soft-empty: tsutatsu may exist in 103 index but not yet in extended.
        return {
            "tsutatsu_id": tsutatsu_id,
            "total": 0,
            "sections": [],
            "_disclaimer": (
                "Section breakdown not yet ingested for this tsutatsu. Refer "
                "to the NTA 通達 page directly at https://www.nta.go.jp/law/tsutatsu/."
            ),
        }

    return {
        "tsutatsu_id": tsutatsu_id,
        "total": len(rows),
        "sections": [
            {
                "section_id": r["section_id"],
                "parent_code": r["parent_code"],
                "law_canonical_id": r["law_canonical_id"],
                "applicable_tax_law_id": r["applicable_tax_law_id"],
                "article_number": r["article_number"],
                "section_number": r["section_number"],
                "title": r["title"],
                "body_text": r["body_text"],
                "cross_references": _parse_json_list(r["cross_references_json"]),
                "source_url": r["source_url"],
                "last_amended": r["last_amended"],
                "ingested_at": r["ingested_at"],
            }
            for r in rows
        ],
        "_disclaimer": (
            "NTA tsutatsu excerpts are retrieval-only citations. Not tax "
            "advice (税理士法 §52). Consult a 税理士 before relying on "
            "these for filing positions."
        ),
    }
