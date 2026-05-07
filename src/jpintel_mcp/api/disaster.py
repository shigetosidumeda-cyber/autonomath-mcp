"""REST handlers for 自然災害 × 復興制度 surface.

Backed by the existing `programs` corpus (jpintel.db) — there is no dedicated
`am_disaster*` table at this snapshot. The endpoints below project the corpus
through three lenses:

1. ``GET /v1/disaster/active_programs`` — programs whose `primary_name` matches
   the disaster / 被災 / 復興 / 被災者 / セーフティネット fence and whose
   `valid_from` falls in the last 12 months. This is the "発災後すぐ surface"
   path: a 都道府県 LP team or 中小企業 owner asks "今 利用できる 災害特例 は?"
   and gets back a primary-source-cited list within one round-trip.

2. ``POST /v1/disaster/match`` — body carries (`prefecture` JIS X 0401 code,
   `disaster_type` enum, `incident_date`). The handler returns the union of
   matching subsidies + loans + tax特例 for that prefecture, ranked tier first.

3. ``GET /v1/disaster/catalog`` — past 5 years (configurable via `years`)
   災害指定 history derived from `primary_name` regex (令和N年 + disaster
   keyword) plus the related programs each event triggered. Pure read, used
   for retrospective comparison ("過去 5 年 の 能登 / 山形 / 静岡 災害特例").

Constraints honored:
    - LLM 0 (no anthropic / openai / google.generativeai imports).
    - Pre-commit clean (ruff + ruff-format + bandit).
    - Primary-source `source_url` echoed on every row (no aggregator fence).
    - 3-axis security_required filter on loans bubbles up unchanged so callers
      can stack "無担保・無保証 災害融資 only" via /v1/disaster/match.

Scope: read-only. No persistence; the catalog timeline is computed on demand
because the underlying data is too thin (≈260 disaster rows) to warrant a
materialised cache.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import sqlite3

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)

router = APIRouter(prefix="/v1/disaster", tags=["disaster"])


# ---------------------------------------------------------------------------
# Disaster taxonomy.
# ---------------------------------------------------------------------------
# `disaster_type` is a closed enum so callers can't smuggle free-text into
# the keyword fence. Each value carries the JP keywords that surface in
# `primary_name` for that disaster type. The mapping is intentionally
# inclusive — a 令和7年8月豪雨 row mentions both 豪雨 and 水害, so a caller
# asking for `flood` must catch both. Same for 地震 / 震災.
#
# Sentinel `unknown` is omitted intentionally — disaster surface only fires
# when the caller knows what happened (発災後 surfacing).

DisasterType = Literal[
    "flood",
    "earthquake",
    "typhoon",
    "fire",
    "snow",
    "landslide",
    "tsunami",
    "volcanic",
    "any",
]

_DISASTER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "flood": ("豪雨", "水害", "浸水", "大雨", "洪水"),
    "earthquake": ("地震", "震災", "能登半島", "熊本地震"),
    "typhoon": ("台風",),
    "fire": ("火災", "山火事"),
    "snow": ("豪雪", "大雪", "雪害"),
    "landslide": ("土砂", "地すべり"),
    "tsunami": ("津波",),
    "volcanic": ("噴火", "火山"),
    # The catch-all keyword set used when `disaster_type=any` or when the
    # endpoint simply wants every disaster row regardless of the specific
    # cause.
    "any": (
        "災害",
        "被災",
        "復興",
        "復旧",
        "豪雨",
        "水害",
        "浸水",
        "地震",
        "震災",
        "台風",
        "豪雪",
        "大雪",
        "雪害",
        "土砂",
        "津波",
        "噴火",
        "セーフティネット",
    ),
}


# JIS X 0401 prefecture code → JP name. Mirrors api/intel._PREFECTURE_CODE_TO_NAME
# (intentionally duplicated here so this module has no cycle with intel.py).
_PREFECTURE_CODE_TO_NAME: dict[str, str] = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "05": "秋田県",
    "06": "山形県",
    "07": "福島県",
    "08": "茨城県",
    "09": "栃木県",
    "10": "群馬県",
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
    "15": "新潟県",
    "16": "富山県",
    "17": "石川県",
    "18": "福井県",
    "19": "山梨県",
    "20": "長野県",
    "21": "岐阜県",
    "22": "静岡県",
    "23": "愛知県",
    "24": "三重県",
    "25": "滋賀県",
    "26": "京都府",
    "27": "大阪府",
    "28": "兵庫県",
    "29": "奈良県",
    "30": "和歌山県",
    "31": "鳥取県",
    "32": "島根県",
    "33": "岡山県",
    "34": "広島県",
    "35": "山口県",
    "36": "徳島県",
    "37": "香川県",
    "38": "愛媛県",
    "39": "高知県",
    "40": "福岡県",
    "41": "佐賀県",
    "42": "長崎県",
    "43": "熊本県",
    "44": "大分県",
    "45": "宮崎県",
    "46": "鹿児島県",
    "47": "沖縄県",
}


# 令和N年 → 西暦N. Used only for the catalog regex below; kept inline
# because the supported range is tight (R1=2019..R10=2028).
_REIWA_TO_YEAR: dict[str, int] = {f"令和{n}年": 2018 + n for n in range(1, 12)}

# Catalog row title regex. Matches strings like 「令和6年能登半島地震」
# or 「令和5年7月豪雨」 inside `primary_name`. The first capture is the
# 令和N年 token; the second is the disaster phrase.
_DISASTER_TITLE_RE = re.compile(
    r"(令和[1-9０-９]+年)(?:[0-9０-９]+月)?\s*([^\s（）()]{0,30}?(?:豪雨|地震|台風|大雪|豪雪|火災|噴火|津波|水害|大雨))",
)


# ---------------------------------------------------------------------------
# Pydantic response models.
# ---------------------------------------------------------------------------


class DisasterProgramRef(BaseModel):
    """One disaster-related program row, projected for surface use."""

    unified_id: str
    primary_name: str
    prefecture: str | None = None
    program_kind: str | None = None
    tier: str | None = None
    authority_level: str | None = None
    authority_name: str | None = None
    amount_max_man_yen: float | None = None
    official_url: str | None = None
    source_url: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    matched_disaster_types: list[str] = Field(default_factory=list)


class DisasterActiveProgramsResponse(BaseModel):
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): populate_by_name=True so the route
    # can pass disclaimer=... via the Python-attribute name (the "_disclaimer"
    # alias has a leading underscore which Python forbids as a kwarg).
    model_config = ConfigDict(populate_by_name=True)

    total: int
    window_months: int
    as_of: str
    results: list[DisasterProgramRef]
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 災害特例 surface — 税理士法 §52 /
    # 行政書士法 §1 / 中小企業診断士 fence. serialization_alias mirrors
    # api/eligibility_check.py so FastAPI emits "_disclaimer".
    disclaimer: str = Field(
        default_factory=lambda: _DISCLAIMER_DISASTER,
        alias="_disclaimer",
        serialization_alias="_disclaimer",
    )


class DisasterMatchRequest(BaseModel):
    """Body for ``POST /v1/disaster/match``.

    `prefecture` is JIS X 0401 (two-digit, 01–47); `disaster_type` is closed
    enum; `incident_date` ISO-8601 (date-only YYYY-MM-DD or full timestamp).
    """

    prefecture: Annotated[
        str,
        Field(
            min_length=2,
            max_length=2,
            description="JIS X 0401 two-digit prefecture code (01–47).",
        ),
    ]
    disaster_type: DisasterType
    incident_date: Annotated[
        str,
        Field(
            min_length=8,
            max_length=32,
            description=("ISO-8601 — 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SSZ'."),
        ),
    ]
    limit: Annotated[int, Field(ge=1, le=100)] = 30


class DisasterMatchBucket(BaseModel):
    program_kind: str
    count: int
    items: list[DisasterProgramRef]


class DisasterMatchResponse(BaseModel):
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): populate_by_name=True so the route
    # can pass disclaimer=... via the Python-attribute name.
    model_config = ConfigDict(populate_by_name=True)

    prefecture: str
    prefecture_code: str
    disaster_type: str
    incident_date: str
    total: int
    buckets: list[DisasterMatchBucket]
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 災害特例 surface — 税理士法 §52 /
    # 行政書士法 §1 / 中小企業診断士 fence.
    disclaimer: str = Field(
        default_factory=lambda: _DISCLAIMER_DISASTER,
        alias="_disclaimer",
        serialization_alias="_disclaimer",
    )


class DisasterEvent(BaseModel):
    """One disaster identified from program-name regex parsing."""

    label: str
    year: int
    era_label: str
    disaster_keyword: str
    inferred_type: str
    program_count: int
    sample_programs: list[DisasterProgramRef]


class DisasterCatalogResponse(BaseModel):
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): populate_by_name=True so the route
    # can pass disclaimer=... via the Python-attribute name.
    model_config = ConfigDict(populate_by_name=True)

    years: int
    as_of: str
    total_events: int
    events: list[DisasterEvent]
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 災害特例 surface — 税理士法 §52 /
    # 行政書士法 §1 / 中小企業診断士 fence.
    disclaimer: str = Field(
        default_factory=lambda: _DISCLAIMER_DISASTER,
        alias="_disclaimer",
        serialization_alias="_disclaimer",
    )


# ---------------------------------------------------------------------------
# R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 業法 fence — 災害特例 surface 全 endpoint で
# 補助金・融資・税特例 を列挙するため、税理士法 §52 (税務代理) ・行政書士法 §1 (申請代理) ・
# 中小企業診断士の経営助言の代替ではないことを明示する。/v1/disaster/active_programs +
# /v1/disaster/match + /v1/disaster/catalog の 3 endpoint で missing 検出 → fix。
# ---------------------------------------------------------------------------
_DISCLAIMER_DISASTER = (
    "本 disaster surface は 災害特例 として programs corpus (jpintel.db) の "
    "primary_name keyword fence で抽出した 補助金 / 融資 / 税特例 / "
    "セーフティネット保証 の機械的列挙であり、税理士法 §52 (税務代理) ・"
    "行政書士法 §1 (申請代理) ・中小企業診断士の経営助言の代替ではない。"
    "個別案件の適用可否は各 source_url の一次情報 (中小企業庁・国税庁・"
    "都道府県・日本政策金融公庫 等) を必ずご確認ください。"
)


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _row_get(row: sqlite3.Row, key: str) -> Any:
    """Return ``row[key]`` if present, else ``None``.

    ``sqlite3.Row`` does not implement ``__contains__`` over keys (it
    iterates VALUES), so the canonical "is column present" test is
    ``key in row.keys()``. We wrap that here so call sites stay clean.
    """
    return row[key] if key in row.keys() else None  # noqa: SIM118 — see docstring


def _row_to_ref(row: sqlite3.Row, matched_types: list[str]) -> DisasterProgramRef:
    """Project a `programs` row onto the disaster surface schema."""
    return DisasterProgramRef(
        unified_id=row["unified_id"],
        primary_name=row["primary_name"],
        prefecture=_row_get(row, "prefecture"),
        program_kind=_row_get(row, "program_kind"),
        tier=_row_get(row, "tier"),
        authority_level=_row_get(row, "authority_level"),
        authority_name=_row_get(row, "authority_name"),
        amount_max_man_yen=_row_get(row, "amount_max_man_yen"),
        official_url=_row_get(row, "official_url"),
        source_url=_row_get(row, "source_url"),
        valid_from=_row_get(row, "valid_from"),
        valid_until=_row_get(row, "valid_until"),
        matched_disaster_types=matched_types,
    )


def _classify_row_disaster_types(name: str) -> list[str]:
    """Return every `DisasterType` enum whose keyword bag intersects `name`.

    `any` is excluded so the projected `matched_disaster_types[]` carries
    only specific disaster categories (callers can re-derive `any` if they
    want it).
    """
    matched: list[str] = []
    for dtype, kws in _DISASTER_KEYWORDS.items():
        if dtype == "any":
            continue
        if any(kw in name for kw in kws):
            matched.append(dtype)
    return matched


def _disaster_keyword_clause(disaster_type: str) -> tuple[str, list[str]]:
    """Return a SQL OR-fragment + parameters for a primary_name keyword fence.

    The fence is `(primary_name LIKE '%kw1%' OR ... OR primary_name LIKE '%kwN%')`.
    Empty keyword bags (should not happen — every enum has ≥1) degrade to a
    benign `0` so the caller's outer WHERE remains valid.
    """
    kws = _DISASTER_KEYWORDS.get(disaster_type, ())
    if not kws:
        return "0", []
    fragments = ["primary_name LIKE ?" for _ in kws]
    return "(" + " OR ".join(fragments) + ")", [f"%{kw}%" for kw in kws]


def _validate_iso_date(s: str) -> str:
    """Return `s` if it parses as ISO-8601, raise 422 otherwise."""
    s = s.strip()
    candidates = (s, s + "T00:00:00+00:00", s.replace("Z", "+00:00"))
    for c in candidates:
        try:
            datetime.fromisoformat(c)
            return s
        except ValueError:
            continue
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        f"incident_date must be ISO-8601 (YYYY-MM-DD or full timestamp), got {s!r}",
    )


# ---------------------------------------------------------------------------
# GET /v1/disaster/active_programs
# ---------------------------------------------------------------------------


@router.get(
    "/active_programs",
    response_model=DisasterActiveProgramsResponse,
    summary="List 災害特例 / 復興制度 surfaced in the last N months",
    description=(
        "Surface disaster-recovery programs that the corpus saw a `valid_from` "
        "update for in the last `window_months` (default 12). Use this "
        "endpoint as the **発災後 immediate-surface** path: a prefecture LP "
        "team can call it within minutes of 災害指定 and get back the union "
        "of (subsidy + loan + tax特例 + セーフティネット保証) rows that "
        "now apply.\n\n"
        "Uses primary-source `source_url` from `programs` directly — never "
        "aggregators. Rows where `tier='X'` (quarantined) are excluded."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": ("List of active disaster programs surfaced in the rolling window."),
        },
    },
)
def list_active_disaster_programs(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    window_months: Annotated[
        int,
        Query(
            ge=1,
            le=60,
            description=("Look-back window in months (default 12, max 60)."),
        ),
    ] = 12,
    prefecture: Annotated[
        str | None,
        Query(
            max_length=20,
            description=(
                "JP prefecture name (e.g. '石川県') — substring match. Pass "
                "`全国` for nationwide-only programs. Omit for all."
            ),
        ),
    ] = None,
    disaster_type: Annotated[
        DisasterType | None,
        Query(
            description=("Filter by disaster category. Omit / `any` for all disaster rows."),
        ),
    ] = None,
    program_kind: Annotated[
        str | None,
        Query(
            max_length=40,
            description=("subsidy | loan | grant | tax_deduction | support | …"),
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DisasterActiveProgramsResponse:
    """Return active disaster programs in the last `window_months`."""
    _t0 = time.perf_counter()
    cutoff = (datetime.now(UTC) - timedelta(days=30 * window_months)).isoformat()

    dtype_for_clause = disaster_type or "any"
    fence_sql, fence_params = _disaster_keyword_clause(dtype_for_clause)

    where: list[str] = [
        "excluded = 0",
        "(tier IS NULL OR tier <> 'X')",
        fence_sql,
        # Either the row's valid_from is recent enough OR valid_from is NULL
        # (legacy rows) — NULL rows are kept because the dataset has many
        # post-bulk-rewrite rows with NULL valid_from but recent corpus
        # ingestion. The cutoff still excludes anything obviously stale.
        "(valid_from IS NULL OR valid_from >= ?)",
    ]
    params: list[Any] = [*fence_params, cutoff]

    if prefecture:
        where.append("(COALESCE(prefecture, '') = ? OR COALESCE(prefecture, '') = '全国')")
        params.append(prefecture)
    if program_kind:
        where.append("program_kind = ?")
        params.append(program_kind)

    where_sql = " AND ".join(where)

    (total,) = conn.execute(f"SELECT COUNT(*) FROM programs WHERE {where_sql}", params).fetchone()

    rows = conn.execute(
        f"""SELECT * FROM programs
            WHERE {where_sql}
            ORDER BY
                CASE tier
                    WHEN 'S' THEN 0
                    WHEN 'A' THEN 1
                    WHEN 'B' THEN 2
                    WHEN 'C' THEN 3
                    ELSE 9
                END,
                COALESCE(amount_max_man_yen, 0) DESC,
                primary_name
            LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()

    refs: list[DisasterProgramRef] = []
    for row in rows:
        matched = _classify_row_disaster_types(row["primary_name"] or "")
        refs.append(_row_to_ref(row, matched))

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "disaster.active_programs",
        latency_ms=_latency_ms,
        result_count=total,
        strict_metering=True,
    )

    if total == 0:
        log_empty_search(
            conn,
            query=(disaster_type or "any") + ":" + (prefecture or ""),
            endpoint="list_active_disaster_programs",
            filters={
                "window_months": window_months,
                "prefecture": prefecture,
                "disaster_type": disaster_type,
                "program_kind": program_kind,
            },
            ip=request.client.host if request.client else None,
        )

    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): the model's `disclaimer` field
    # default_factory pulls _DISCLAIMER_DISASTER at construction so the
    # envelope is emitted on every 200 — no kwarg needed (the `_disclaimer`
    # alias has a leading underscore that Python forbids as a kwarg name).
    return DisasterActiveProgramsResponse(
        total=total,
        window_months=window_months,
        as_of=datetime.now(UTC).isoformat(),
        results=refs,
    )


# ---------------------------------------------------------------------------
# POST /v1/disaster/match
# ---------------------------------------------------------------------------


@router.post(
    "/match",
    response_model=DisasterMatchResponse,
    summary="Match disaster-relief programs by (prefecture, disaster_type, date)",
    description=(
        "Given a disaster instance — JIS X 0401 prefecture code + disaster "
        "type + incident date — return every applicable program from the "
        "corpus, bucketed by `program_kind` (subsidy / loan / grant / "
        "tax_deduction / support / certification / 等). Each bucket is "
        "tier-sorted (S→A→B→C) so the highest-trust rows surface first.\n\n"
        "Use this endpoint when the caller already knows the disaster facts "
        "and wants a one-shot 'what can my client apply for' answer. For an "
        "open browse use `/v1/disaster/active_programs` instead."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": ("Disaster-match buckets keyed on program_kind, tier-sorted."),
        },
    },
)
def match_disaster_programs(
    payload: DisasterMatchRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> DisasterMatchResponse:
    """Match disaster-relief programs against a (prefecture, type, date) tuple."""
    _t0 = time.perf_counter()

    pref_name = _PREFECTURE_CODE_TO_NAME.get(payload.prefecture)
    if not pref_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            (f"prefecture must be a JIS X 0401 two-digit code 01–47, got {payload.prefecture!r}"),
        )

    incident_iso = _validate_iso_date(payload.incident_date)

    fence_sql, fence_params = _disaster_keyword_clause(payload.disaster_type)
    where: list[str] = [
        "excluded = 0",
        "(tier IS NULL OR tier <> 'X')",
        fence_sql,
        # Match prefecture-scoped rows OR nationwide rows (`全国`) so a 石川県
        # caller still sees 公庫 / セーフティネット 4号 etc.
        "(COALESCE(prefecture, '') = ? OR COALESCE(prefecture, '') IN ('全国', ''))",
    ]
    params: list[Any] = [*fence_params, pref_name]

    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""SELECT * FROM programs
            WHERE {where_sql}
            ORDER BY
                CASE tier
                    WHEN 'S' THEN 0
                    WHEN 'A' THEN 1
                    WHEN 'B' THEN 2
                    WHEN 'C' THEN 3
                    ELSE 9
                END,
                COALESCE(amount_max_man_yen, 0) DESC,
                primary_name
            LIMIT ?""",
        [*params, payload.limit],
    ).fetchall()

    buckets: dict[str, list[DisasterProgramRef]] = {}
    for row in rows:
        kind = row["program_kind"] or "unspecified"
        matched = _classify_row_disaster_types(row["primary_name"] or "")
        # Ensure the requested type is in the matched list even when the
        # row only carries a generic 災害 keyword.
        if payload.disaster_type != "any" and payload.disaster_type not in matched:
            matched = [*matched, payload.disaster_type]
        buckets.setdefault(kind, []).append(_row_to_ref(row, matched))

    bucket_models = [
        DisasterMatchBucket(program_kind=k, count=len(v), items=v)
        for k, v in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    total = sum(b.count for b in bucket_models)

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "disaster.match",
        latency_ms=_latency_ms,
        result_count=total,
        strict_metering=True,
    )

    if total == 0:
        log_empty_search(
            conn,
            query=f"{payload.prefecture}:{payload.disaster_type}",
            endpoint="match_disaster_programs",
            filters={
                "prefecture_code": payload.prefecture,
                "disaster_type": payload.disaster_type,
                "incident_date": incident_iso,
            },
            ip=request.client.host if request.client else None,
        )

    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): default_factory binds
    # _DISCLAIMER_DISASTER at construction; no kwarg needed.
    return DisasterMatchResponse(
        prefecture=pref_name,
        prefecture_code=payload.prefecture,
        disaster_type=payload.disaster_type,
        incident_date=incident_iso,
        total=total,
        buckets=bucket_models,
    )


# ---------------------------------------------------------------------------
# GET /v1/disaster/catalog
# ---------------------------------------------------------------------------


@router.get(
    "/catalog",
    response_model=DisasterCatalogResponse,
    summary="災害指定 history (last N years) + related programs",
    description=(
        "Walk `programs.primary_name` for 「令和N年…豪雨」 / 「令和N年…地震」 "
        "/ 「令和N年…台風」 patterns and return one event row per detected "
        "disaster, with up to 5 sample programs per event. Useful for a "
        "retrospective 'what disasters happened the last 5 years and which "
        "制度 did they unlock' walkthrough — e.g. 能登半島地震 / 山形豪雨 / "
        "熊本豪雨 / 令和2年7月豪雨.\n\n"
        "Year detection is best-effort: the regex understands 令和N年, "
        "optionally 月, then a disaster keyword. Pre-令和 years (Heisei "
        "30 / 平成) are not surfaced — those are out of scope for the "
        "5-year rolling 'recent disasters' window."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Disaster events + sample programs.",
        },
    },
)
def disaster_catalog(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    years: Annotated[
        int,
        Query(
            ge=1,
            le=10,
            description="Look-back horizon in years (default 5, max 10).",
        ),
    ] = 5,
    sample_per_event: Annotated[int, Query(ge=1, le=20)] = 5,
) -> JSONResponse:
    """Compute disaster events + sample programs over a rolling year window."""
    _t0 = time.perf_counter()
    now = datetime.now(UTC)
    min_year = now.year - years

    # Pull every row that mentions a 令和 token + any disaster keyword.
    # A bounded 5,000 row scan is safe — full 災害 universe is ≈260 rows.
    rows = conn.execute(
        """SELECT unified_id, primary_name, prefecture, program_kind, tier,
                  authority_level, authority_name, amount_max_man_yen,
                  official_url, source_url, valid_from, valid_until
           FROM programs
           WHERE excluded = 0
             AND (tier IS NULL OR tier <> 'X')
             AND primary_name LIKE '%令和%'
             AND (
                primary_name LIKE '%豪雨%'
                OR primary_name LIKE '%地震%'
                OR primary_name LIKE '%台風%'
                OR primary_name LIKE '%大雪%'
                OR primary_name LIKE '%豪雪%'
                OR primary_name LIKE '%火災%'
                OR primary_name LIKE '%津波%'
                OR primary_name LIKE '%水害%'
                OR primary_name LIKE '%大雨%'
             )
           LIMIT 5000"""
    ).fetchall()

    # event_key: (era_label, year, disaster_keyword) → list[DisasterProgramRef]
    events: dict[tuple[str, int, str], list[DisasterProgramRef]] = {}
    for row in rows:
        name = row["primary_name"] or ""
        m = _DISASTER_TITLE_RE.search(name)
        if not m:
            continue
        era_token = m.group(1)
        # Translate full-width digits to half so 令和６年 also lands.
        era_normalised = era_token.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        year = _REIWA_TO_YEAR.get(era_normalised)
        if year is None or year < min_year:
            continue
        keyword = m.group(2)
        # Reduce keyword to its disaster suffix (e.g. "能登半島地震" → "地震").
        for suffix in (
            "豪雨",
            "地震",
            "台風",
            "大雪",
            "豪雪",
            "火災",
            "津波",
            "水害",
            "大雨",
            "噴火",
        ):
            if keyword.endswith(suffix):
                keyword = suffix
                break
        key = (era_normalised, year, keyword)
        bucket = events.setdefault(key, [])
        if len(bucket) < sample_per_event:
            matched = _classify_row_disaster_types(name)
            bucket.append(_row_to_ref(row, matched))

    # Build the response, sorted year DESC then keyword.
    inferred_for: dict[str, str] = {
        "豪雨": "flood",
        "水害": "flood",
        "大雨": "flood",
        "地震": "earthquake",
        "台風": "typhoon",
        "大雪": "snow",
        "豪雪": "snow",
        "火災": "fire",
        "津波": "tsunami",
        "噴火": "volcanic",
    }
    event_models: list[DisasterEvent] = []
    # Recompute total counts per event (the sample bucket is capped at
    # sample_per_event but the headline count must reflect the full match).
    counts: dict[tuple[str, int, str], int] = {}
    for row in rows:
        name = row["primary_name"] or ""
        m = _DISASTER_TITLE_RE.search(name)
        if not m:
            continue
        era_token = m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        year = _REIWA_TO_YEAR.get(era_token)
        if year is None or year < min_year:
            continue
        keyword = m.group(2)
        for suffix in (
            "豪雨",
            "地震",
            "台風",
            "大雪",
            "豪雪",
            "火災",
            "津波",
            "水害",
            "大雨",
            "噴火",
        ):
            if keyword.endswith(suffix):
                keyword = suffix
                break
        counts[(era_token, year, keyword)] = counts.get((era_token, year, keyword), 0) + 1

    for key, samples in events.items():
        era_label, year, keyword = key
        label = f"{era_label}{keyword}"
        event_models.append(
            DisasterEvent(
                label=label,
                year=year,
                era_label=era_label,
                disaster_keyword=keyword,
                inferred_type=inferred_for.get(keyword, "any"),
                program_count=counts.get(key, len(samples)),
                sample_programs=samples,
            )
        )
    event_models.sort(key=lambda e: (-e.year, e.disaster_keyword, e.era_label))

    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): default_factory binds
    # _DISCLAIMER_DISASTER at construction; no kwarg needed.
    body_model = DisasterCatalogResponse(
        years=years,
        as_of=now.isoformat(),
        total_events=len(event_models),
        events=event_models,
    )

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "disaster.catalog",
        latency_ms=_latency_ms,
        result_count=len(event_models),
        strict_metering=True,
    )

    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): by_alias=True so the
    # _disclaimer envelope key emits as "_disclaimer" (not "disclaimer").
    body = body_model.model_dump(mode="json", by_alias=True)
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
