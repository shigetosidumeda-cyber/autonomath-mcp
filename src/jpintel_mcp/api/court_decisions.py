"""REST handlers for court_decisions (裁判所判例検索 / hanrei_jp).

Backed by migration 016's `court_decisions` + `court_decisions_fts` +
`enforcement_decision_refs` tables. Supersets the legacy 012 `case_law`
catalog. Primary source is www.courts.go.jp hanrei_jp — D1 Law / Westlaw
Japan / LEX/DB aggregators are banned at ingest (license + 再配布 blocks).

# CHAIN: laws ←(related_law_ids_json)── court_decisions ←(enforcement_decision_refs)──
#        enforcement_cases. This router is how callers trace:
#        "our client may have triggered 補助金適正化法 第22条 — which
#        Supreme Court rulings interpret that article, and which
#        enforcement actions cite those rulings?"
# WHEN NOT: do not use /court-decisions for 会計検査院 reports themselves —
#        those live on /v1/enforcement-cases. Use /court-decisions only
#        for 判決 / 決定 / 命令 issued by a court. The /by-statute endpoint
#        is for statute→ruling chaining, not reverse.

Scope boundary — read-only. Decision rows are curated externally (via
scripts/ingest/ingest_court_decisions.py) and never mutated here.

FTS workaround: same trigram tokenizer gotcha as programs_fts / laws_fts —
we reuse the `_build_fts_match` phrase-quote builder from api/programs.py
so 2+ character kanji compounds (e.g. `税額控除`, `補助金適正化`) match
contiguously, never as independent trigram hits.
"""
import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.programs import (
    KANA_EXPANSIONS,
    _build_fts_match,
)
from jpintel_mcp.models import (
    CourtDecision,
    CourtDecisionByStatuteRequest,
    CourtDecisionSearchResponse,
    CourtLevel,
    DecisionType,
)

router = APIRouter(prefix="/v1/court-decisions", tags=["court-decisions"])


def _row_to_decision(row: sqlite3.Row) -> CourtDecision:
    law_ids_raw = row["related_law_ids_json"]
    related_law_ids: list[str] = []
    if law_ids_raw:
        try:
            parsed = json.loads(law_ids_raw)
            if isinstance(parsed, list):
                related_law_ids = [str(x) for x in parsed]
        except json.JSONDecodeError:
            related_law_ids = []

    return CourtDecision(
        unified_id=row["unified_id"],
        case_name=row["case_name"],
        case_number=row["case_number"],
        court=row["court"],
        court_level=row["court_level"],
        decision_date=row["decision_date"],
        decision_type=row["decision_type"],
        subject_area=row["subject_area"],
        related_law_ids=related_law_ids,
        key_ruling=row["key_ruling"],
        parties_involved=row["parties_involved"],
        impact_on_business=row["impact_on_business"],
        precedent_weight=row["precedent_weight"],
        full_text_url=row["full_text_url"],
        pdf_url=row["pdf_url"],
        source_url=row["source_url"],
        source_excerpt=row["source_excerpt"],
        source_checksum=row["source_checksum"],
        confidence=row["confidence"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "/search",
    response_model=CourtDecisionSearchResponse,
    summary="Search Japanese court decisions (判決 / 決定 / 命令)",
    description=(
        "Search 2,065 court decisions (判例) sourced from courts.go.jp "
        "判例検索 across `case_name + subject_area + key_ruling + "
        "impact_on_business`. Filter by 裁判所名 / `court_level` "
        "(supreme / high / district / summary / family) / "
        "`decision_type` (判決 / 決定 / 命令) / `subject_area` "
        "(租税 / 行政 / 補助金適正化法 / etc.) / decided_from/to date "
        "window / `references_law_id` (cites this LAW-* unified_id).\n\n"
        "**Precedent weight:** each row carries `precedent_weight` in "
        "`{binding, persuasive, informational}`. binding = 最高裁 or "
        "大法廷; persuasive = 高裁 / 地裁 leading case; "
        "informational = case reference. LLM agents should surface "
        "`precedent_weight` when relaying — a 地裁 ruling is not the "
        "same as 最高裁 binding precedent.\n\n"
        "For statute-citation crawls (which decisions cite this law?), "
        "prefer `POST /v1/court-decisions/by-statute`."
    ),
    responses={
        200: {
            "description": "Paginated court decisions.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "unified_id": "HAN-5954003266",
                                "case_name": "所得税更正処分取消等請求事件",
                                "case_number": "平成30(行ヒ)422",
                                "court": "最高裁判所第三小法廷",
                                "court_level": "supreme",
                                "decision_date": "2020-03-24",
                                "decision_type": "判決",
                                "subject_area": "租税",
                                "precedent_weight": "binding",
                                "key_ruling": "国税通則法24条所定の更正処分の取消…",
                                "full_text_url": "https://www.courts.go.jp/app/hanrei_jp/detail2?id=89311",
                                "source_url": "https://www.courts.go.jp/...",
                                "fetched_at": "2026-04-20T05:14:33Z",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def search_court_decisions(
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search across case_name + subject_area + "
                "key_ruling + impact_on_business (FTS5 with quoted-phrase "
                "workaround for 2+ character kanji compounds)."
            ),
            max_length=200,
        ),
    ] = None,
    court: Annotated[
        str | None,
        Query(
            description="Filter by 裁判所名 (exact match, e.g. '最高裁判所第三小法廷').",
            max_length=160,
        ),
    ] = None,
    court_level: Annotated[
        CourtLevel | None,
        Query(
            description=(
                "Filter by court tier. One of: supreme | high | district | "
                "summary | family."
            ),
        ),
    ] = None,
    decision_type: Annotated[
        DecisionType | None,
        Query(
            description="Filter by decision shape. One of: 判決 | 決定 | 命令.",
        ),
    ] = None,
    subject_area: Annotated[
        str | None,
        Query(
            description=(
                "Filter by 分野 (substring LIKE — the column is free-text "
                "and varies by 判例集, so exact-match is too brittle)."
            ),
            max_length=120,
        ),
    ] = None,
    references_law_id: Annotated[
        str | None,
        Query(
            description=(
                "Filter rows whose `related_law_ids_json` contains this "
                "LAW-<10 hex> unified_id. JSON-array substring LIKE — "
                "accurate because unified_ids are fixed-width and have a "
                "distinctive `LAW-` prefix."
            ),
            pattern=r"^LAW-[0-9a-f]{10}$",
        ),
    ] = None,
    decided_from: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive lower bound on decision_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    decided_to: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive upper bound on decision_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CourtDecisionSearchResponse:
    """Search court decisions (判決 / 決定 / 命令)."""

    where: list[str] = []
    params: list[Any] = []
    join_fts = False

    if q:
        q_clean = q.strip()
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
                    "(case_name LIKE ? "
                    "OR COALESCE(subject_area,'') LIKE ? "
                    "OR COALESCE(key_ruling,'') LIKE ? "
                    "OR COALESCE(impact_on_business,'') LIKE ?)"
                )
                like = f"%{t}%"
                params.extend([like, like, like, like])
            where.append("(" + " OR ".join(like_clauses) + ")")

    if court:
        where.append("court = ?")
        params.append(court)
    if court_level:
        where.append("court_level = ?")
        params.append(court_level)
    if decision_type:
        where.append("decision_type = ?")
        params.append(decision_type)
    if subject_area:
        where.append("COALESCE(subject_area,'') LIKE ?")
        params.append(f"%{subject_area}%")
    if references_law_id:
        # related_law_ids_json is a JSON array of LAW-<10 hex> strings.
        # The `"LAW-..."` quoted form anchors the match to the array element
        # boundary — a fixed-width prefix can't collide with an unrelated
        # substring elsewhere in the blob.
        where.append("COALESCE(related_law_ids_json,'') LIKE ?")
        params.append(f'%"{references_law_id}"%')
    if decided_from:
        where.append("decision_date >= ?")
        params.append(decided_from)
    if decided_to:
        where.append("decision_date <= ?")
        params.append(decided_to)

    if join_fts:
        base_from = "court_decisions_fts JOIN court_decisions USING(unified_id)"
        where_clause = "court_decisions_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
    else:
        base_from = "court_decisions"
        where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}"
    (total,) = conn.execute(count_sql, params).fetchone()

    # Ordering: binding > persuasive > informational (先例価値),
    # then supreme > high > district > summary > family (裁判所階層),
    # then most recent decision first.
    weight_order = (
        "CASE precedent_weight "
        "WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 "
        "WHEN 'informational' THEN 2 ELSE 3 END"
    )
    level_order = (
        "CASE court_level "
        "WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 "
        "WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
    )
    order_parts: list[str] = [weight_order, level_order]
    if join_fts:
        order_parts.append("court_decisions_fts.rank")
    order_parts.extend(
        [
            "COALESCE(decision_date, '') DESC",
            "unified_id",
        ]
    )
    order_sql = "ORDER BY " + ", ".join(order_parts)

    select_sql = (
        f"SELECT court_decisions.* FROM {base_from} "
        f"WHERE {where_clause} {order_sql} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    log_usage(
        conn,
        ctx,
        "court_decisions.search",
        params={
            "q": q,
            "court": court,
            "court_level": court_level,
            "decision_type": decision_type,
            "subject_area": subject_area,
            "references_law_id": references_law_id,
            "decided_from": decided_from,
            "decided_to": decided_to,
        },
    )

    return CourtDecisionSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_decision(r) for r in rows],
    )


@router.get(
    "/{unified_id}",
    response_model=CourtDecision,
    summary="Get a single court decision by unified_id (HAN-*)",
    description=(
        "Look up one 判例 by stable `unified_id` (`HAN-<10 hex>`). "
        "Returns 事件名, 事件番号, 裁判所, 言渡日, 判決種別, 分野, "
        "主要判示事項 (`key_ruling`), 実務影響 (`impact_on_business`), "
        "`precedent_weight`, courts.go.jp permalink, and `pdf_url` "
        "(全文 PDF mirror).\n\n"
        "Discovery flow: call `GET /v1/court-decisions/search` first, "
        "then follow up on each `unified_id` here for the full key "
        "ruling text + practical impact summary."
    ),
    responses={
        200: {
            "description": "Single court decision row.",
            "content": {
                "application/json": {
                    "example": {
                        "unified_id": "HAN-5954003266",
                        "case_name": "所得税更正処分取消等請求事件",
                        "case_number": "平成30(行ヒ)422",
                        "court": "最高裁判所第三小法廷",
                        "court_level": "supreme",
                        "decision_date": "2020-03-24",
                        "decision_type": "判決",
                        "subject_area": "租税",
                        "precedent_weight": "binding",
                        "key_ruling": "更正処分の理由付記の…",
                        "impact_on_business": "国税不服審判の段階で…",
                        "full_text_url": "https://www.courts.go.jp/app/hanrei_jp/detail2?id=89311",
                        "pdf_url": "https://www.courts.go.jp/app/files/hanrei_jp/311/089311_hanrei.pdf",
                        "source_url": "https://www.courts.go.jp/app/hanrei_jp/detail2?id=89311",
                        "source_excerpt": "…(裁判所サイトより抜粋)",
                        "confidence": 0.9,
                        "fetched_at": "2026-04-20T05:14:33Z",
                    }
                }
            },
        }
    },
)
def get_court_decision(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return a single court decision with full source lineage.

    Audit trail (会計士 work-paper, added 2026-04-29): the response includes
    `corpus_snapshot_id` (ISO-8601 of latest am_amendment_diff detection or
    MAX(fetched_at) fallback) and `corpus_checksum` (sha256:<16hex>) so an
    auditor citing this 判例 in a work-paper can reproduce the lookup later
    and detect whether the corpus mutated. See docs/audit_trail.md.
    """
    row = conn.execute(
        "SELECT * FROM court_decisions WHERE unified_id = ?",
        (unified_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"court decision not found: {unified_id}",
        )

    log_usage(
        conn, ctx, "court_decisions.get", params={"unified_id": unified_id}
    )
    body = _row_to_decision(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.post("/by-statute", response_model=CourtDecisionSearchResponse)
def decisions_by_statute(
    payload: CourtDecisionByStatuteRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> CourtDecisionSearchResponse:
    """Return court decisions citing a given LAW-<10 hex> statute.

    TRACE endpoint: resolves the statute→ruling edge via
    `related_law_ids_json`. When `article_citation` is supplied, we
    additionally require the article string to appear in `key_ruling` or
    `source_excerpt` — the ingest does not yet write a structured
    (law_id, article) map, so this is a honest contains-check, not a
    false-precision exact join. Callers should treat `article_citation`
    narrowing as best-effort.
    """

    law_id = payload.law_id.strip()
    if not law_id.startswith("LAW-") or len(law_id) != 14:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"law_id must match LAW-<10 hex>, got {law_id!r}",
        )

    # Existence check — a missing law returns 404 rather than an empty
    # list, so callers notice malformed ids instead of treating "zero
    # hits" as "no jurisprudence".
    law_row = conn.execute(
        "SELECT unified_id FROM laws WHERE unified_id = ?", (law_id,)
    ).fetchone()
    if law_row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"law not found: {law_id}"
        )

    where: list[str] = ['COALESCE(related_law_ids_json,\'\') LIKE ?']
    params: list[Any] = [f'%"{law_id}"%']

    if payload.article_citation:
        article = payload.article_citation.strip()
        where.append(
            "(COALESCE(key_ruling,'') LIKE ? "
            "OR COALESCE(source_excerpt,'') LIKE ?)"
        )
        like_article = f"%{article}%"
        params.extend([like_article, like_article])

    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM court_decisions WHERE {where_sql}", params
    ).fetchone()

    weight_order = (
        "CASE precedent_weight "
        "WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 "
        "WHEN 'informational' THEN 2 ELSE 3 END"
    )
    level_order = (
        "CASE court_level "
        "WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 "
        "WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
    )

    rows = conn.execute(
        f"""SELECT * FROM court_decisions
            WHERE {where_sql}
            ORDER BY
                {weight_order},
                {level_order},
                COALESCE(decision_date, '') DESC,
                unified_id
            LIMIT ? OFFSET ?""",
        [*params, payload.limit, payload.offset],
    ).fetchall()

    log_usage(
        conn,
        ctx,
        "court_decisions.by_statute",
        params={
            "law_id": law_id,
            "article_citation": payload.article_citation,
        },
    )

    return CourtDecisionSearchResponse(
        total=total,
        limit=payload.limit,
        offset=payload.offset,
        results=[_row_to_decision(r) for r in rows],
    )
