"""REST handlers for case_studies (採択事例 / success stories).

Backed by migration 011's `case_studies` table. 2,286 rows as of
2026-04-23, aggregated from Jグランツ 採択結果, mirasapo 事業事例,
and prefectural 事例集. Consumers use this to prove "a business like
mine has actually received this grant" before applying, and to
triangulate on program-recipient pairings that the programs table
alone doesn't capture.

Scope: read-only. Curation is done externally by
scripts/ingest_external_data.py — this router is a thin query surface.
"""
import json
import re
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
from jpintel_mcp.api.programs import _build_fts_match
from jpintel_mcp.api.vocab import (
    _normalize_industry_jsic,
    _normalize_prefecture,
)
from jpintel_mcp.models import CaseStudy, CaseStudySearchResponse

router = APIRouter(prefix="/v1/case-studies", tags=["case-studies"])


_RE_PURE_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")


def _is_short_ascii(s: str) -> bool:
    """Short pure-ASCII acronym-style query (e.g. 'DX', 'IT', 'AI', 'GX').

    These never tokenize on FTS5's trigram (min 3 codepoints), so FTS MATCH
    always returns 0; the LIKE fallback is the only way to reach them.
    """
    return bool(s) and len(s) < 3 and _RE_PURE_ASCII_WORD.fullmatch(s) is not None


def _build_case_studies_fts_match(raw_query: str) -> str:
    """Compose an FTS5 MATCH expression for case_studies_fts.

    2026-04-29: delegates to ``api.programs._build_fts_match`` — the
    canonical builder. Previously this file had its own minimal copy
    that lacked the ``_tokenize_query`` extraction (user-quoted phrase
    handling, FTS5-special char stripping). Sharing the builder keeps
    case_studies + programs in lockstep on the trigram-overlap fix
    (CLAUDE.md "Common gotchas" — 税額控除 vs ふるさと納税).

    KANA_EXPANSIONS is harmless on the 2.3k case_studies corpus —
    the OR'd kanji target is just absent from the FTS index for those
    expansions, costing nothing.
    """
    return _build_fts_match(raw_query)


def _json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed if x is not None]


def _json_any(raw: Any) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_case_study(row: sqlite3.Row) -> CaseStudy:
    sole = row["is_sole_proprietor"]
    is_sole: bool | None = None if sole is None else bool(sole)

    return CaseStudy(
        case_id=row["case_id"],
        company_name=row["company_name"],
        houjin_bangou=row["houjin_bangou"],
        is_sole_proprietor=is_sole,
        prefecture=row["prefecture"],
        municipality=row["municipality"],
        industry_jsic=row["industry_jsic"],
        industry_name=row["industry_name"],
        employees=row["employees"],
        founded_year=row["founded_year"],
        capital_yen=row["capital_yen"],
        case_title=row["case_title"],
        case_summary=row["case_summary"],
        programs_used=_json_list(row["programs_used_json"]),
        total_subsidy_received_yen=row["total_subsidy_received_yen"],
        outcomes=_json_any(row["outcomes_json"]),
        patterns=_json_any(row["patterns_json"]),
        publication_date=row["publication_date"],
        source_url=row["source_url"],
        source_excerpt=row["source_excerpt"],
        fetched_at=row["fetched_at"],
        confidence=row["confidence"],
    )


@router.get(
    "/search",
    response_model=CaseStudySearchResponse,
    summary="Search 採択事例 (awarded grant case studies)",
    description=(
        "Browse 2,286 採択事例 (real awarded grants) — searchable across "
        "`company_name + case_title + case_summary + source_excerpt` "
        "via FTS5 trigram + filterable by 都道府県 / industry_jsic / "
        "法人番号 / `program_used` / 補助金額 band / 従業員数 band.\n\n"
        "**Use cases:** prior-art research ('which companies received "
        "ものづくり補助金 in 群馬?'), benchmark sizing ('what's the typical "
        "amount for 製造業 + 100 employees?'), or co-applicant discovery.\n\n"
        "**Sparsity caveats:**\n"
        "- only ~19% of rows carry 法人番号 (427 / 2,286) — most 採択 "
        "announcements publish 社名 only. Prefer `q=<company_name>` "
        "for substring search when 法人番号 is unknown.\n"
        "- only <1% (4 / 2,286) carry an `amount_received_man_yen` value "
        "— ministries publish 採択 without 交付額. Filtering on "
        "`min_subsidy_yen` / `max_subsidy_yen` silently drops ~99% of "
        "matches; avoid unless the user explicitly asked for an amount band."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Paginated case_studies. Search via FTS5 trigram on company_name + case_title + summary.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "case_id": "CS-meti-jizokuka-2024-00123",
                                "company_name": "株式会社ヤマダ製作所",
                                "case_title": "持続化補助金で新規販路開拓に成功",
                                "case_summary": "EC サイト構築費 200 万円補助で売上 1.4 倍。",
                                "prefecture": "群馬県",
                                "industry_jsic": "29",
                                "houjin_bangou": "1234567890123",
                                "program_used": "小規模事業者持続化補助金",
                                "amount_received_man_yen": 150,
                                "fiscal_year": 2024,
                                "source_url": "https://www.jizokukahojokin.info/case/123",
                                "fetched_at": "2026-04-20T05:14:33Z",
                                "confidence": 0.92,
                            }
                        ],
                    }
                }
            },
        },
    },
)
def search_case_studies(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search over company_name + case_title + "
                "case_summary + source_excerpt. Backed by FTS5 trigram "
                "(case_studies_fts) for queries of length >= 2; falls back "
                "to LIKE for single-char or 0-result short-ASCII queries."
            ),
            max_length=200,
        ),
    ] = None,
    prefecture: Annotated[str | None, Query(max_length=80)] = None,
    industry_jsic: Annotated[
        str | None,
        Query(
            description="JSIC industry code prefix (e.g. 'A' for 農林水産業, '05' for 食料品製造業).",
            max_length=10,
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Query(
            max_length=13,
            description=(
                "13-digit 法人番号 exact match. NOTE: only ~19% of case studies carry 法人番号 "
                "(427 / 2,286 rows) — most 採択 announcements publish 社名 only. "
                "Prefer `q=<company_name>` for substring search when the 法人番号 is unknown."
            ),
        ),
    ] = None,
    program_used: Annotated[
        str | None,
        Query(
            description=(
                "Match rows whose programs_used_json list contains this program "
                "name or unified_id substring."
            ),
            max_length=200,
        ),
    ] = None,
    min_subsidy_yen: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Lower bound on total_subsidy_received_yen (JPY). "
                "WARNING: only 4 / 2,286 rows (<1%) carry an amount — ministries publish 採択 without 交付額. "
                "Filtering here silently drops ~99% of matches."
            ),
        ),
    ] = None,
    max_subsidy_yen: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Upper bound on total_subsidy_received_yen (JPY). "
                "Same <1% sparsity as min_subsidy_yen — avoid unless the user explicitly asked for a ceiling."
            ),
        ),
    ] = None,
    min_employees: Annotated[int | None, Query(ge=0)] = None,
    max_employees: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CaseStudySearchResponse:
    """Search 採択事例 case studies."""

    _t0 = time.perf_counter()
    where: list[str] = []
    params: list[Any] = []
    use_fts = False
    fts_match_param: str | None = None
    q_clean: str | None = None

    if q:
        q_clean = q.strip()
        # Path selection (see migration 057_case_studies_fts.sql + slow-query
        # audit a889d3a849074d765, 2026-04-25):
        #   * len >= 2          → FTS5 MATCH (was ~120ms P95 LIKE; ~3-7ms FTS).
        #     2-char queries usually return 0 because the trigram tokenizer
        #     emits 3-grams only, but we still attempt FTS so the OR-quote /
        #     phrase semantics are consistent. The 0-result fallback below
        #     handles those cases.
        #   * len < 2           → straight LIKE (single-char queries cannot
        #     ride the trigram index at all).
        if len(q_clean) >= 2:
            use_fts = True
            fts_match_param = _build_case_studies_fts_match(q_clean)
        else:
            like = f"%{q_clean}%"
            where.append(
                "(COALESCE(case_studies.company_name,'') LIKE ? "
                "OR COALESCE(case_studies.case_title,'') LIKE ? "
                "OR COALESCE(case_studies.case_summary,'') LIKE ? "
                "OR COALESCE(case_studies.source_excerpt,'') LIKE ?)"
            )
            params.extend([like, like, like, like])
    prefecture = _normalize_prefecture(prefecture)
    if prefecture:
        where.append("case_studies.prefecture = ?")
        params.append(prefecture)
    industry_jsic = _normalize_industry_jsic(industry_jsic)
    if industry_jsic:
        where.append("case_studies.industry_jsic LIKE ?")
        params.append(f"{industry_jsic}%")
    if houjin_bangou:
        where.append("case_studies.houjin_bangou = ?")
        params.append(houjin_bangou)
    if program_used:
        # programs_used_json stores a JSON list; substring match is good
        # enough for both unified_id hits and raw program-name hits.
        where.append("case_studies.programs_used_json LIKE ?")
        params.append(f"%{program_used}%")
    if min_subsidy_yen is not None:
        where.append("case_studies.total_subsidy_received_yen >= ?")
        params.append(min_subsidy_yen)
    if max_subsidy_yen is not None:
        where.append("case_studies.total_subsidy_received_yen <= ?")
        params.append(max_subsidy_yen)
    if min_employees is not None:
        where.append("case_studies.employees >= ?")
        params.append(min_employees)
    if max_employees is not None:
        where.append("case_studies.employees <= ?")
        params.append(max_employees)

    extra_where_sql = " AND ".join(where) if where else ""

    def _execute(use_fts_path: bool) -> tuple[int, list[sqlite3.Row]]:
        """Run COUNT + SELECT for either the FTS or LIKE path.

        Pulled into a closure so we can re-run with the LIKE path when an
        FTS attempt returns 0 results AND the original query is a short
        ASCII acronym (those never match a trigram index — the only way
        they reach is the LIKE substring scan).

        Index alignment: ORDER BY publication_date DESC, case_id matches
        idx_case_studies_pubdate exactly. The previous COALESCE(...,'')
        wrapper defeated that index — dropped here. SQLite sorts NULL last
        for DESC by default, which preserves prior behavior on the only
        test that walks the order list (test_search_orders_by_publication_date_desc
        skips None pairs).
        """
        local_params: list[Any] = []
        if use_fts_path:
            assert fts_match_param is not None
            base_from = "case_studies_fts JOIN case_studies USING(case_id)"
            match_clause = "case_studies_fts MATCH ?"
            local_params.append(fts_match_param)
            if extra_where_sql:
                where_clause = match_clause + " AND " + extra_where_sql
            else:
                where_clause = match_clause
        else:
            base_from = "case_studies"
            where_clause = extra_where_sql or "1=1"

        local_params.extend(params)

        (total_count,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}",
            local_params,
        ).fetchone()

        result_rows = conn.execute(
            f"""SELECT case_studies.* FROM {base_from}
                WHERE {where_clause}
                ORDER BY case_studies.publication_date DESC, case_studies.case_id
                LIMIT ? OFFSET ?""",
            [*local_params, limit, offset],
        ).fetchall()
        return total_count, result_rows

    total, rows = _execute(use_fts)

    # 0-result fallback: short ASCII acronyms ('DX', 'IT', 'AI', 'GX') cannot
    # tokenize against an FTS5 trigram index (min 3 codepoints), so the FTS
    # path always returns 0 for them. Re-run via LIKE so the substring hit
    # in case_title / case_summary still surfaces. Bounded — runs at most
    # once per request, only when q is genuinely short ASCII.
    if use_fts and total == 0 and q_clean is not None and _is_short_ascii(q_clean):
        like = f"%{q_clean}%"
        fallback_where = list(where)
        fallback_params: list[Any] = []
        fallback_where.insert(
            0,
            "(COALESCE(case_studies.company_name,'') LIKE ? "
            "OR COALESCE(case_studies.case_title,'') LIKE ? "
            "OR COALESCE(case_studies.case_summary,'') LIKE ? "
            "OR COALESCE(case_studies.source_excerpt,'') LIKE ?)",
        )
        fallback_params.extend([like, like, like, like])
        fallback_params.extend(params)
        fallback_where_sql = " AND ".join(fallback_where) if fallback_where else "1=1"
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM case_studies WHERE {fallback_where_sql}",
            fallback_params,
        ).fetchone()
        rows = conn.execute(
            f"""SELECT case_studies.* FROM case_studies
                WHERE {fallback_where_sql}
                ORDER BY case_studies.publication_date DESC, case_studies.case_id
                LIMIT ? OFFSET ?""",
            [*fallback_params, limit, offset],
        ).fetchall()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "case_studies.search",
        latency_ms=_latency_ms,
        result_count=total,
    )

    if total == 0 and q is not None:
        _q_clean_for_log = q.strip()
        if len(_q_clean_for_log) > 1:
            log_empty_search(
                conn,
                query=_q_clean_for_log,
                endpoint="search_case_studies",
                filters={
                    "prefecture": prefecture,
                    "industry_jsic": industry_jsic,
                    "houjin_bangou": houjin_bangou,
                    "program_used": program_used,
                    "min_subsidy_yen": min_subsidy_yen,
                    "max_subsidy_yen": max_subsidy_yen,
                    "min_employees": min_employees,
                    "max_employees": max_employees,
                },
                ip=request.client.host if request.client else None,
            )

    return CaseStudySearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_case_study(r) for r in rows],
    )


@router.get(
    "/{case_id}",
    response_model=CaseStudy,
    summary="Get a single 採択事例 case study by case_id",
    description=(
        "Look up one 採択事例 by stable `case_id` (e.g. "
        "`CS-meti-jizokuka-2024-00123`). Returns full case_title, "
        "case_summary, programs_used, amount_received (when published), "
        "outcomes (KPI lift, headcount change), patterns (intervention "
        "category), and source lineage.\n\n"
        "Discovery flow: call `GET /v1/case-studies/search` first, then "
        "follow up on each `case_id` here for the long-form outcome "
        "narrative."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Single case study row.",
            "content": {
                "application/json": {
                    "example": {
                        "case_id": "CS-meti-jizokuka-2024-00123",
                        "company_name": "株式会社ヤマダ製作所",
                        "case_title": "持続化補助金で新規販路開拓に成功",
                        "case_summary": "EC サイト構築費 200 万円補助で売上 1.4 倍。",
                        "prefecture": "群馬県",
                        "industry_jsic": "29",
                        "houjin_bangou": "1234567890123",
                        "employee_count": 8,
                        "programs_used": ["小規模事業者持続化補助金"],
                        "amount_received_man_yen": 150,
                        "fiscal_year": 2024,
                        "outcomes": {"sales_yoy_pct": 40, "new_channels": 2},
                        "patterns": ["EC構築", "販路開拓"],
                        "publication_date": "2024-12-15",
                        "source_url": "https://www.jizokukahojokin.info/case/123",
                        "source_excerpt": "EC化により…",
                        "fetched_at": "2026-04-20T05:14:33Z",
                        "confidence": 0.92,
                    }
                }
            },
        },
        404: {
            "model": ErrorEnvelope,
            "description": "case study not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_case_study(
    case_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Single case study lookup by `case_id`.

    Audit trail (会計士 work-paper, added 2026-04-29): the response includes
    `corpus_snapshot_id` + `corpus_checksum` so an auditor citing this 採択事例
    in a work-paper can reproduce the lookup later and detect whether the
    corpus mutated. See docs/audit_trail.md.
    """
    row = conn.execute(
        "SELECT * FROM case_studies WHERE case_id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"case study not found: {case_id}")

    log_usage(conn, ctx, "case_studies.get")
    body = _row_to_case_study(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
