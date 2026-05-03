"""REST handlers for laws (e-Gov 法令 catalog).

Backed by migration 015's `laws` + `laws_fts` + `program_law_refs` tables.
Exposes ~3,400 rows of 憲法 / 法律 / 政令 / 勅令 / 府省令 / 規則 / 告示 /
ガイドライン harvested from e-Gov 法令 API V2 (CC-BY 4.0). Primary
surface for "what is the 根拠法 of this 補助金" and "which programs cite
this statute" lookups.

# CHAIN: programs ─(program_law_refs)→ laws ─(related_law_ids_json)→
#        court_decisions. This router is the 中間ハブ. /search finds laws;
#        /{unified_id}/related-programs walks the reverse edge.
# WHEN NOT: do not use /laws/search to resolve a free-text "税制" query —
#        that belongs on /v1/programs/search with funding_purpose=tax.
#        /laws is for statute-level look-ups only, not benefit discovery.

Scope boundary — this router is read-only. Law rows are curated externally
(via scripts/ingest/ingest_laws.py) and never mutated here.

FTS workaround: the trigram tokenizer gives single-kanji overlap false
positives. For 2+ character kanji queries we reuse the phrase-quote
builder from api/programs.py (`_build_fts_match`) so e.g. `税額控除`
matches only rows where those tokens appear contiguously, never rows
that merely mention 税 + 控除 independently.
"""
import json
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)
from jpintel_mcp.api.programs import (
    KANA_EXPANSIONS,
    _build_fts_match,
)
from jpintel_mcp.models import (
    Law,
    LawSearchResponse,
    LawType,
    RelatedProgramRef,
    RelatedProgramsResponse,
)

router = APIRouter(prefix="/v1/laws", tags=["laws"])


def _row_to_law(row: sqlite3.Row) -> Law:
    subj_raw = row["subject_areas_json"]
    subject_areas: list[str] = []
    if subj_raw:
        try:
            parsed = json.loads(subj_raw)
            if isinstance(parsed, list):
                subject_areas = [str(x) for x in parsed]
        except json.JSONDecodeError:
            subject_areas = []

    return Law(
        unified_id=row["unified_id"],
        law_number=row["law_number"],
        law_title=row["law_title"],
        law_short_title=row["law_short_title"],
        law_type=row["law_type"],
        ministry=row["ministry"],
        promulgated_date=row["promulgated_date"],
        enforced_date=row["enforced_date"],
        last_amended_date=row["last_amended_date"],
        revision_status=row["revision_status"],
        superseded_by_law_id=row["superseded_by_law_id"],
        article_count=row["article_count"],
        full_text_url=row["full_text_url"],
        summary=row["summary"],
        subject_areas=subject_areas,
        source_url=row["source_url"],
        source_checksum=row["source_checksum"],
        confidence=row["confidence"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "/search",
    response_model=LawSearchResponse,
    summary="Search Japanese laws (法令): 憲法 / 法律 / 政令 / 省令 / 告示",
    description=(
        "Search the e-Gov 法令 catalog (9,484 rows + still loading) "
        "across `law_title + law_short_title + law_number + summary`. "
        "Filter by `law_type` (constitution / act / cabinet_order / "
        "imperial_order / ministerial_ordinance / rule / notice / "
        "guideline), 所管府省 (`ministry`), revision_status, and "
        "promulgated / enforced date windows.\n\n"
        "**License:** e-Gov 法令データ is **CC-BY 4.0** (attribution "
        "required, redistribution permitted with attribution). The "
        "`source_url` on each row points to the canonical e-Gov 法令検索 "
        "permalink — relay it.\n\n"
        "**Search note:** Japanese legal phrases are normalized. For very "
        "short terms, structured filters or longer phrases are more reliable.\n\n"
        "Pair with `GET /v1/laws/{unified_id}/related-programs` to "
        "trace which 補助金 cite a given statute as authority / "
        "eligibility / exclusion / penalty."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Paginated laws (e-Gov 法令 catalog, CC-BY 4.0).",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "unified_id": "LAW-jp-shotokuzeiho",
                                "law_number": "昭和四十年法律第三十三号",
                                "law_title": "所得税法",
                                "law_short_title": "所得税法",
                                "law_type": "act",
                                "ministry": "財務省",
                                "promulgated_date": "1965-03-31",
                                "enforced_date": "1965-04-01",
                                "last_amended_date": "2025-03-31",
                                "revision_status": "current",
                                "article_count": 245,
                                "full_text_url": "https://laws.e-gov.go.jp/law/340AC0000000033",
                                "subject_areas": ["税法", "所得税"],
                                "source_url": "https://laws.e-gov.go.jp/law/340AC0000000033",
                                "fetched_at": "2026-04-20T05:14:33Z",
                                "confidence": 1.0,
                            }
                        ],
                    }
                }
            },
        },
    },
)
def search_laws(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search across law_title + law_short_title + "
                "law_number + summary. Japanese phrases are normalized; "
                "very short terms use fallback matching."
            ),
            max_length=200,
        ),
    ] = None,
    law_type: Annotated[
        LawType | None,
        Query(
            description=(
                "Filter by law_type. One of: constitution | act | "
                "cabinet_order | imperial_order | ministerial_ordinance | "
                "rule | notice | guideline."
            ),
        ),
    ] = None,
    ministry: Annotated[
        str | None,
        Query(
            description="Filter by 所管府省 (exact match).",
            max_length=120,
        ),
    ] = None,
    currently_effective_only: Annotated[
        bool,
        Query(
            description=(
                "When true (default), only `revision_status='current'` rows "
                "are returned. Flip to false to include 'superseded' rows."
            ),
        ),
    ] = True,
    include_repealed: Annotated[
        bool,
        Query(
            description=(
                "When false (default), `revision_status='repealed'` rows are "
                "excluded. Flip to true for historical research."
            ),
        ),
    ] = False,
    promulgated_from: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive lower bound on promulgated_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    promulgated_to: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive upper bound on promulgated_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    enforced_from: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive lower bound on enforced_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    enforced_to: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive upper bound on enforced_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LawSearchResponse:
    """Search laws (statutes, ordinances, ministerial rules)."""
    _t0 = time.perf_counter()

    where: list[str] = []
    params: list[Any] = []
    join_fts = False

    if q:
        q_clean = q.strip()
        # Mirror the programs.py FTS-vs-LIKE decision: if any expansion
        # term is shorter than 3 characters, FTS5 trigram will silently
        # miss it, so fall through to LIKE. This is the only honest path.
        search_terms: list[str] = [q_clean]
        if q_clean in KANA_EXPANSIONS:
            search_terms.extend(KANA_EXPANSIONS[q_clean])
        shortest = min(len(t) for t in search_terms)
        if shortest >= 3:
            join_fts = True
            params.append(_build_fts_match(q_clean))
        else:
            like_clauses: list[str] = []
            for t in search_terms:
                like_clauses.append(
                    "(law_title LIKE ? "
                    "OR COALESCE(law_short_title,'') LIKE ? "
                    "OR law_number LIKE ? "
                    "OR COALESCE(summary,'') LIKE ?)"
                )
                like = f"%{t}%"
                params.extend([like, like, like, like])
            where.append("(" + " OR ".join(like_clauses) + ")")

    if law_type:
        where.append("law_type = ?")
        params.append(law_type)
    if ministry:
        where.append("ministry = ?")
        params.append(ministry)
    if currently_effective_only:
        where.append("revision_status = 'current'")
    if not include_repealed:
        where.append("revision_status != 'repealed'")
    if promulgated_from:
        where.append("promulgated_date >= ?")
        params.append(promulgated_from)
    if promulgated_to:
        where.append("promulgated_date <= ?")
        params.append(promulgated_to)
    if enforced_from:
        where.append("enforced_date >= ?")
        params.append(enforced_from)
    if enforced_to:
        where.append("enforced_date <= ?")
        params.append(enforced_to)

    if join_fts:
        base_from = "laws_fts JOIN laws USING(unified_id)"
        where_clause = "laws_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
    else:
        base_from = "laws"
        where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}"
    (total,) = conn.execute(count_sql, params).fetchone()

    # Ordering: prefer current -> superseded -> repealed, then most-recent
    # enforcement first (actionable laws surface first). Add laws_fts.rank
    # as the FTS path tiebreaker so exact-phrase hits rise.
    rev_order = (
        "CASE revision_status "
        "WHEN 'current' THEN 0 WHEN 'superseded' THEN 1 "
        "WHEN 'repealed' THEN 2 ELSE 3 END"
    )
    order_parts: list[str] = [rev_order]
    if join_fts:
        order_parts.append("laws_fts.rank")
    order_parts.extend(
        [
            "COALESCE(enforced_date, promulgated_date, '') DESC",
            "unified_id",
        ]
    )
    order_sql = "ORDER BY " + ", ".join(order_parts)

    select_sql = (
        f"SELECT laws.* FROM {base_from} WHERE {where_clause} "
        f"{order_sql} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "laws.search",
        params={
            "q": q,
            "law_type": law_type,
            "ministry": ministry,
            "currently_effective_only": currently_effective_only,
            "include_repealed": include_repealed,
            "promulgated_from": promulgated_from,
            "promulgated_to": promulgated_to,
            "enforced_from": enforced_from,
            "enforced_to": enforced_to,
        },
        latency_ms=_latency_ms,
        result_count=total,
    )

    if total == 0 and q is not None:
        _q_clean_for_log = q.strip()
        if len(_q_clean_for_log) > 1:
            log_empty_search(
                conn,
                query=_q_clean_for_log,
                endpoint="search_laws",
                filters={
                    "law_type": law_type,
                    "ministry": ministry,
                    "currently_effective_only": currently_effective_only,
                    "include_repealed": include_repealed,
                    "promulgated_from": promulgated_from,
                    "promulgated_to": promulgated_to,
                    "enforced_from": enforced_from,
                    "enforced_to": enforced_to,
                },
                ip=request.client.host if request.client else None,
            )

    return LawSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_law(r) for r in rows],
    )


@router.get(
    "/{unified_id}",
    response_model=Law,
    summary="Get a single law (法令) by unified_id (LAW-*)",
    description=(
        "Look up one 法令 by stable `unified_id` (`LAW-<10 hex>`). "
        "Returns 法令番号 (e.g. 昭和四十年法律第三十三号), 正式名称, "
        "略称, 所管府省, 公布日 / 施行日 / 改正日, 条文数, 2-3 line "
        "abstract (`summary`), `subject_areas` tags (subsidy_clawback "
        "/ tax_credit / etc.), and `full_text_url` (e-Gov 法令検索 "
        "permalink for humans).\n\n"
        "**License:** e-Gov 法令データ is CC-BY 4.0 (cc_by_4.0). "
        "Relay `source_url` + attribution.\n\n"
        "Pair with `GET /v1/laws/{unified_id}/related-programs` to "
        "trace which programs cite this law."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Single law row.",
            "content": {
                "application/json": {
                    "example": {
                        "unified_id": "LAW-64c08d2649",
                        "law_number": "昭和四十年法律第三十三号",
                        "law_title": "所得税法",
                        "law_short_title": "所得税法",
                        "law_type": "act",
                        "ministry": "財務省",
                        "promulgated_date": "1965-03-31",
                        "enforced_date": "2026-04-01",
                        "last_amended_date": "2026-03-31",
                        "revision_status": "current",
                        "article_count": 245,
                        "full_text_url": "https://laws.e-gov.go.jp/law/340AC0000000033",
                        "summary": "所得に対する税の課税標準・税額等を定める。",
                        "subject_areas": ["税法", "所得税"],
                        "source_url": "https://laws.e-gov.go.jp/law/340AC0000000033",
                        "fetched_at": "2026-04-20T05:14:33Z",
                        "confidence": 1.0,
                    }
                }
            },
        },
        404: {
            "model": ErrorEnvelope,
            "description": "law not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_law(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return a single law including summary, article_count, and lineage.

    The response includes `corpus_snapshot_id` + `corpus_checksum` so callers
    can reproduce the lookup later and detect whether the corpus changed.
    """
    row = conn.execute(
        "SELECT * FROM laws WHERE unified_id = ?", (unified_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"law not found: {unified_id}"
        )

    log_usage(conn, ctx, "laws.get", params={"unified_id": unified_id})
    body = _row_to_law(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.get(
    "/{unified_id}/related-programs",
    response_model=RelatedProgramsResponse,
    responses={
        **COMMON_ERROR_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": "law not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_related_programs(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
    ref_kind: Annotated[
        str | None,
        Query(
            description=(
                "Filter by citation kind. One of: authority | eligibility | "
                "exclusion | reference | penalty. Omit to return all kinds."
            ),
            max_length=20,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelatedProgramsResponse:
    """Reverse lookup: which programs cite this law via program_law_refs."""

    # Verify the law exists first — surfaces a 404 instead of an empty list
    # when the caller has the wrong unified_id (honest semantics).
    law_row = conn.execute(
        "SELECT unified_id FROM laws WHERE unified_id = ?", (unified_id,)
    ).fetchone()
    if law_row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"law not found: {unified_id}"
        )

    allowed_kinds = {
        "authority",
        "eligibility",
        "exclusion",
        "reference",
        "penalty",
    }
    if ref_kind is not None and ref_kind not in allowed_kinds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"ref_kind must be one of {sorted(allowed_kinds)}, got {ref_kind!r}",
        )

    where: list[str] = ["plr.law_unified_id = ?"]
    params: list[Any] = [unified_id]
    if ref_kind is not None:
        where.append("plr.ref_kind = ?")
        params.append(ref_kind)
    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM program_law_refs plr WHERE {where_sql}",
        params,
    ).fetchone()

    rows = conn.execute(
        f"""SELECT plr.program_unified_id AS program_unified_id,
                   plr.ref_kind           AS ref_kind,
                   plr.article_citation   AS article_citation,
                   plr.source_url         AS source_url,
                   plr.fetched_at         AS fetched_at,
                   plr.confidence         AS confidence,
                   p.primary_name         AS program_name
             FROM program_law_refs plr
             LEFT JOIN programs p ON p.unified_id = plr.program_unified_id
             WHERE {where_sql}
             ORDER BY
                 CASE plr.ref_kind
                     WHEN 'authority'   THEN 0
                     WHEN 'eligibility' THEN 1
                     WHEN 'exclusion'   THEN 2
                     WHEN 'penalty'     THEN 3
                     WHEN 'reference'   THEN 4
                     ELSE 5 END,
                 plr.program_unified_id
             LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()

    results = [
        RelatedProgramRef(
            program_unified_id=r["program_unified_id"],
            ref_kind=r["ref_kind"],
            article_citation=r["article_citation"],
            program_name=r["program_name"],
            source_url=r["source_url"],
            fetched_at=r["fetched_at"],
            confidence=r["confidence"],
        )
        for r in rows
    ]

    log_usage(
        conn,
        ctx,
        "laws.related_programs",
        params={"unified_id": unified_id, "ref_kind": ref_kind},
    )

    return RelatedProgramsResponse(
        law_unified_id=unified_id,
        total=total,
        limit=limit,
        offset=offset,
        results=results,
    )
