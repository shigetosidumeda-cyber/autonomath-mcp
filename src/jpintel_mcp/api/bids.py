"""REST handlers for bids (入札 public procurement catalog).

Backed by migration 017's `bids` + `bids_fts` tables. Primary sources:
GEPS 政府電子調達 (p-portal.go.jp, CC-BY 4.0), self-gov top-7 JV flows
(neighboring 都道府県 *.lg.jp), and ministry-direct procurement pages
under *.go.jp. Aggregators (NJSS 等) are never a primary source — the
ingest layer enforces lineage discipline via scripts/ingest/check_lineage.py;
this handler only reads what lineage-gated ingest has already written.

# CHAIN: programs ─(program_id_hint soft-FK)→ bids
#        houjin_master ─(procuring_houjin_bangou / winner_houjin_bangou
#        soft-FK)→ bids
# WHEN NOT: do not use /bids/search to resolve "this 補助金の公募" — that
#        belongs on /v1/programs/search. /bids is for after-the-fact
#        procurement notices + 落札結果, not funded-program discovery.

Scope boundary — read-only. Bid rows are curated externally (via
scripts/ingest/ingest_bids.py) and never mutated here.

FTS workaround: same trigram tokenizer gotcha as programs_fts / laws_fts /
court_decisions_fts. We reuse the `_build_fts_match` phrase-quote builder
from api/programs.py so 2+ character kanji compounds (e.g. `道路工事`,
`ソフトウェア開発`) match contiguously, never as independent trigram hits.
Handlers must pass raw user queries through `_build_fts_match` — do not
concatenate them into the MATCH expression by hand.
"""
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.programs import _build_fts_match

router = APIRouter(prefix="/v1/bids", tags=["bids"])


BidKind = Literal["open", "selective", "negotiated", "kobo_subsidy"]


class BidOut(BaseModel):
    """Single 入札 row. Columns map 1:1 onto 017_bids.sql's `bids` table."""

    model_config = ConfigDict(extra="forbid")

    unified_id: str = Field(..., description="BID-<10 lowercase hex>")
    bid_title: str = Field(
        ..., description="Bid title (案件名) — short headline as published by the procuring entity."
    )
    bid_kind: BidKind = Field(
        ...,
        description=(
            "Bid procedure kind. open = 一般競争 (open competitive); "
            "selective = 指名競争 (selective tender); "
            "negotiated = 随意契約 (negotiated contract); "
            "kobo_subsidy = 公募型補助 (subsidy-style open call)."
        ),
    )
    procuring_entity: str = Field(
        ..., description="Procuring entity name (発注機関名) — ministry / agency / 自治体 issuing the tender."
    )
    procuring_houjin_bangou: str | None = Field(
        default=None,
        description=(
            "13-digit 法人番号 of the procuring entity (soft ref to houjin_master)."
        ),
    )
    ministry: str | None = Field(
        default=None,
        description="Ministry / agency in charge (所管府省) — e.g. 農林水産省, 経済産業省.",
    )
    prefecture: str | None = Field(
        default=None,
        description="Prefecture (都道府県) — full-suffix kanji form, e.g. 東京都. NULL for nationwide bids.",
    )
    program_id_hint: str | None = Field(
        default=None,
        description=(
            "Soft reference to programs.unified_id when this bid is the procurement "
            "arm of a funded 補助事業."
        ),
    )
    announcement_date: str | None = Field(
        default=None,
        description="Announcement date / 公告日 (ISO 8601 YYYY-MM-DD).",
    )
    question_deadline: str | None = Field(
        default=None,
        description="Question-submission deadline / 質問受付期限 (ISO 8601 YYYY-MM-DD).",
    )
    bid_deadline: str | None = Field(
        default=None,
        description="Bid-submission deadline / 入札書提出期限 (ISO 8601 YYYY-MM-DD).",
    )
    decision_date: str | None = Field(
        default=None,
        description="Award-decision date / 落札決定日 (ISO 8601 YYYY-MM-DD).",
    )
    budget_ceiling_yen: int | None = Field(
        default=None,
        description=(
            "Budget ceiling / contract cap (予定価格 / 契約限度額) in JPY, "
            "tax-inclusive when disclosed by the procuring entity."
        ),
    )
    awarded_amount_yen: int | None = Field(
        default=None,
        description=(
            "Awarded amount (落札金額) in JPY, tax-inclusive when disclosed."
        ),
    )
    winner_name: str | None = Field(
        default=None,
        description="Winning bidder name (落札者名) — as published by the procuring entity.",
    )
    winner_houjin_bangou: str | None = Field(
        default=None,
        description="13-digit 法人番号 of the winning bidder (soft ref to houjin_master).",
    )
    participant_count: int | None = Field(
        default=None,
        description="Number of participating bidders (入札参加者数).",
    )
    bid_description: str | None = Field(
        default=None,
        description="Procurement scope / specification summary (調達概要 / 仕様要旨).",
    )
    eligibility_conditions: str | None = Field(
        default=None,
        description=(
            "Participation eligibility conditions (参加資格要件) — "
            "grade rating / location / past-performance requirements."
        ),
    )
    classification_code: str | None = Field(
        default=None, description="'役務' | '物品' | '工事' (or finer JGS code)"
    )
    source_url: str = Field(..., description="primary source (GEPS / ministry / *.lg.jp)")
    source_excerpt: str | None = Field(
        default=None, description="relevant passage for audit"
    )
    source_checksum: str | None = Field(
        default=None, description="optional SHA-256 of raw fetch body"
    )
    confidence: float = Field(..., description="0..1 lineage confidence")
    fetched_at: str = Field(..., description="ISO 8601 UTC of last successful fetch")
    updated_at: str = Field(..., description="ISO 8601 UTC of last row write")


class BidsSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    results: list[BidOut]


def _row_to_bid(row: sqlite3.Row) -> BidOut:
    return BidOut(
        unified_id=row["unified_id"],
        bid_title=row["bid_title"],
        bid_kind=row["bid_kind"],
        procuring_entity=row["procuring_entity"],
        procuring_houjin_bangou=row["procuring_houjin_bangou"],
        ministry=row["ministry"],
        prefecture=row["prefecture"],
        program_id_hint=row["program_id_hint"],
        announcement_date=row["announcement_date"],
        question_deadline=row["question_deadline"],
        bid_deadline=row["bid_deadline"],
        decision_date=row["decision_date"],
        budget_ceiling_yen=row["budget_ceiling_yen"],
        awarded_amount_yen=row["awarded_amount_yen"],
        winner_name=row["winner_name"],
        winner_houjin_bangou=row["winner_houjin_bangou"],
        participant_count=row["participant_count"],
        bid_description=row["bid_description"],
        eligibility_conditions=row["eligibility_conditions"],
        classification_code=row["classification_code"],
        source_url=row["source_url"],
        source_excerpt=row["source_excerpt"],
        source_checksum=row["source_checksum"],
        confidence=row["confidence"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
    )


_HOUJIN_BANGOU_PATTERN = r"^\d{13}$"


@router.get(
    "/search",
    response_model=BidsSearchResponse,
    summary="Search Japanese government bids (入札案件)",
    description=(
        "Search 362 入札案件 (government procurement bids) sourced from "
        "GEPS (政府電子調達) + ministry / 自治体 procurement portals. "
        "Filter by `bid_kind` (open / selective / negotiated / "
        "kobo_subsidy), 発注機関 法人番号, 落札者 法人番号, programs.unified_id "
        "hint, awarded_amount band, deadline window.\n\n"
        "**When to use:** caller asks 'who won the 国土交通省 2025 IT "
        "procurement?' or 'are there still-open 物品調達 in 関東 with "
        "award ceiling > 1億?'. Pair with `/v1/am/enforcement` to "
        "screen winners for 入札参加資格停止.\n\n"
        "**FTS quirk:** terms < 3 chars will not match (trigram "
        "tokenizer limitation); use the structured filters instead "
        "or longer phrases. When `q` is omitted, results sort by "
        "most recently published first."
    ),
    responses={
        200: {
            "description": "Paginated bids.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "unified_id": "BID-cf1aff5eb7",
                                "bid_title": "農林水産省永年勤続者表彰用銀杯等の製造（単価契約）",
                                "bid_kind": "open",
                                "procuring_entity": "農林水産省",
                                "procuring_houjin_bangou": None,
                                "ministry": "農林水産省",
                                "prefecture": None,
                                "program_id_hint": None,
                                "announcement_date": "2026-04-14",
                                "question_deadline": None,
                                "bid_deadline": "2026-04-27",
                                "decision_date": None,
                                "budget_ceiling_yen": None,
                                "awarded_amount_yen": None,
                                "winner_name": None,
                                "winner_houjin_bangou": None,
                                "participant_count": None,
                                "bid_description": None,
                                "eligibility_conditions": None,
                                "classification_code": "物品の製造",
                                "source_url": "https://www.maff.go.jp/j/supply/nyusatu/buppin_ekimu/sonota1/index.html",
                                "source_excerpt": None,
                                "source_checksum": None,
                                "confidence": 0.92,
                                "fetched_at": "2026-04-25T04:06:20Z",
                                "updated_at": "2026-04-25T04:06:20Z",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def search_bids(
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search across bid_title + bid_description + "
                "procuring_entity + winner_name (FTS5 with quoted-phrase "
                "workaround for 2+ character kanji compounds). Terms "
                "shorter than 3 characters will not match — trigram "
                "tokenizer limitation; use a longer phrase or the "
                "structured filters instead."
            ),
            max_length=200,
        ),
    ] = None,
    bid_kind: Annotated[
        BidKind | None,
        Query(
            description=(
                "Filter by bid_kind. One of: open | selective | "
                "negotiated | kobo_subsidy."
            ),
        ),
    ] = None,
    procuring_houjin_bangou: Annotated[
        str | None,
        Query(
            description="Exact 13-digit 法人番号 of the procuring entity.",
            pattern=_HOUJIN_BANGOU_PATTERN,
        ),
    ] = None,
    winner_houjin_bangou: Annotated[
        str | None,
        Query(
            description="Exact 13-digit 法人番号 of the落札者.",
            pattern=_HOUJIN_BANGOU_PATTERN,
        ),
    ] = None,
    program_id_hint: Annotated[
        str | None,
        Query(
            description=(
                "Exact programs.unified_id (UNI-* / TAX-* / LAW-* etc.) — "
                "returns bids linked to that program via ingest matchers."
            ),
            max_length=64,
        ),
    ] = None,
    min_amount: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Inclusive lower bound on awarded_amount_yen (JPY). "
                "Rows with NULL awarded_amount_yen are excluded from the "
                "filtered set when this is set."
            ),
        ),
    ] = None,
    max_amount: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Inclusive upper bound on awarded_amount_yen (JPY). "
                "Rows with NULL awarded_amount_yen are excluded from the "
                "filtered set when this is set."
            ),
        ),
    ] = None,
    deadline_after: Annotated[
        str | None,
        Query(
            description=(
                "ISO date (YYYY-MM-DD) — inclusive lower bound on "
                "bid_deadline. Useful for 'still-open' queries."
            ),
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BidsSearchResponse:
    """Search bids (入札案件). FTS match when `q` is given, else most recently
    published first."""

    where: list[str] = []
    params: list = []
    join_fts = False

    if q:
        q_clean = q.strip()
        if q_clean:
            # Trigram tokenizer silently returns zero hits for terms < 3 chars.
            # No kana expansion table here (bids vocabulary is project-name
            # heavy, not category-heavy), so a short query just falls through
            # to a LIKE fallback across the FTS-indexed columns.
            if len(q_clean) >= 3:
                join_fts = True
                params.append(_build_fts_match(q_clean))
            else:
                like = f"%{q_clean}%"
                where.append(
                    "(bid_title LIKE ? "
                    "OR COALESCE(bid_description,'') LIKE ? "
                    "OR procuring_entity LIKE ? "
                    "OR COALESCE(winner_name,'') LIKE ?)"
                )
                params.extend([like, like, like, like])

    if bid_kind:
        where.append("bid_kind = ?")
        params.append(bid_kind)
    if procuring_houjin_bangou:
        where.append("procuring_houjin_bangou = ?")
        params.append(procuring_houjin_bangou)
    if winner_houjin_bangou:
        where.append("winner_houjin_bangou = ?")
        params.append(winner_houjin_bangou)
    if program_id_hint:
        where.append("program_id_hint = ?")
        params.append(program_id_hint)
    if min_amount is not None:
        where.append("awarded_amount_yen IS NOT NULL AND awarded_amount_yen >= ?")
        params.append(min_amount)
    if max_amount is not None:
        where.append("awarded_amount_yen IS NOT NULL AND awarded_amount_yen <= ?")
        params.append(max_amount)
    if deadline_after:
        where.append("bid_deadline IS NOT NULL AND bid_deadline >= ?")
        params.append(deadline_after)

    if join_fts:
        base_from = "bids_fts JOIN bids USING(unified_id)"
        where_clause = "bids_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
    else:
        base_from = "bids"
        where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}"
    (total,) = conn.execute(count_sql, params).fetchone()

    # Ordering:
    #   - FTS path: bids_fts.rank (bm25) first so exact phrase hits rise,
    #     then most-recent announcement, then unified_id for determinism.
    #   - Non-FTS path: published_at proxy = announcement_date DESC, falling
    #     back to bid_deadline then updated_at so rows that skip an
    #     announcement_date (随意契約 etc.) still sort sensibly.
    if join_fts:
        order_sql = (
            "ORDER BY bids_fts.rank, "
            "COALESCE(bids.announcement_date, bids.bid_deadline, bids.updated_at) DESC, "
            "bids.unified_id"
        )
    else:
        order_sql = (
            "ORDER BY "
            "COALESCE(bids.announcement_date, bids.bid_deadline, bids.updated_at) DESC, "
            "bids.unified_id"
        )

    select_sql = (
        f"SELECT bids.* FROM {base_from} WHERE {where_clause} "
        f"{order_sql} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    log_usage(
        conn,
        ctx,
        "bids.search",
        params={
            "q": q,
            "bid_kind": bid_kind,
            "procuring_houjin_bangou": procuring_houjin_bangou,
            "winner_houjin_bangou": winner_houjin_bangou,
            "program_id_hint": program_id_hint,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "deadline_after": deadline_after,
        },
    )

    return BidsSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_bid(r) for r in rows],
    )


@router.get("/{unified_id}", response_model=BidOut)
def get_bid(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return a single 入札案件 by BID-<10 hex> unified_id.

    Audit trail (会計士 work-paper, added 2026-04-29): the response includes
    `corpus_snapshot_id` + `corpus_checksum` so an auditor citing this 入札
    in a work-paper can reproduce the lookup later and detect whether the
    corpus mutated. See docs/audit_trail.md.
    """
    row = conn.execute(
        "SELECT * FROM bids WHERE unified_id = ?", (unified_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"bid not found: {unified_id}"
        )

    log_usage(conn, ctx, "bids.get", params={"unified_id": unified_id})
    body = _row_to_bid(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
