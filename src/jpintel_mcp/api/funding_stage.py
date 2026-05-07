"""REST endpoints for the funding-stage program matcher (no LLM).

Mounts two surfaces:

* ``GET  /v1/funding_stages/catalog`` — closed-enum catalog of the 5
  canonical funding stages (seed / early / growth / ipo / succession),
  each with definition + indicative size band + 代表的な制度 list. Free,
  read-only, no metering — equivalent to ``/v1/regions/search`` posture
  (catalog is constant data so we never charge for it).
* ``POST /v1/programs/by_funding_stage`` — given the caller's stage tag
  + 4 coarse profile axes (annual revenue / employee count /
  incorporation year / prefecture), returns the subset of jpintel
  ``programs`` that match the stage's keyword fence + the caller's
  age / size band, ranked by ``amount_max_man_yen × likelihood``. ¥3/req
  metered, anonymous tier shares the 3/日 IP cap via ``AnonIpLimitDep``
  on the router mount in ``api/main.py``.

Stage ↔ program mapping is purely declarative — every stage carries a
keyword fence (Japanese OR-ladder against ``programs.primary_name``) +
indicative ``age_max_years`` / ``capital_max_yen`` envelope; the matcher
applies those alongside the caller's own profile to rank rows.

NO LLM. NO destructive write. Pure read-only over jpintel.programs.

Disclaimer
----------
The 「stage 判定」 is heuristic — Japanese funding programs do not carry a
formal stage tag. We document the keyword fence in the catalog so callers
see exactly what `growth` (etc.) means for the matcher, and every match
carries a ``_disclaimer`` reminder to verify the primary source.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.funding_stage")

router = APIRouter(prefix="/v1", tags=["funding-stage"])


# ---------------------------------------------------------------------------
# 5 canonical funding stages — closed enum + per-stage matcher fence.
# ---------------------------------------------------------------------------

# Each entry:
#   id              — stable enum slug used by callers
#   ja_label        — 日本語表示ラベル (catalog UX)
#   description     — one-paragraph definition
#   age_min_years   — stage の 創業年数 下限 (None = 制限なし)
#   age_max_years   — 創業年数 上限 (None = 制限なし)
#   capital_max_yen — 資本金 上限の目安 (None = 制限なし)
#   revenue_band_yen— [low, high] 売上 帯目安 (any None = open)
#   keywords_any    — primary_name に含まれる OR ladder (1 つでも match で fence pass)
#   keywords_avoid  — false-positive 除外 (1 つでも match で除外)
#   representative_program_keys — catalog 表示用の 代表制度 (primary_name fragment)
_STAGES: list[dict[str, Any]] = [
    {
        "id": "seed",
        "ja_label": "シード (創業前後)",
        "description": (
            "創業前後・プロダクト未確立フェーズ。創業補助金/創業融資/"
            "公庫新創業融資/起業支援金/シード期スタートアップ支援が中心。"
        ),
        "age_min_years": None,
        "age_max_years": 3,
        "capital_max_yen": 30_000_000,
        "revenue_band_yen": [None, 50_000_000],
        "keywords_any": [
            "創業",
            "起業",
            "スタートアップ",
            "新創業",
            "シード",
            "アクセラレータ",
            "アクセラレーター",
        ],
        "keywords_avoid": [
            "事業承継",
            "M&A",
            "上場",
            "IPO",
        ],
        "representative_program_keys": [
            "新創業融資",
            "創業支援",
            "創業補助金",
            "アクセラレーター",
            "スタートアップ支援",
        ],
    },
    {
        "id": "early",
        "ja_label": "アーリー (3〜5 年目)",
        "description": (
            "プロダクト確立後・初期スケール段階。ものづくり補助金/IT 導入補助金/"
            "事業再構築/ディープテック・スタートアップ支援等が刺さりやすい帯。"
        ),
        "age_min_years": 1,
        "age_max_years": 7,
        "capital_max_yen": 100_000_000,
        "revenue_band_yen": [10_000_000, 500_000_000],
        "keywords_any": [
            "ものづくり",
            "IT導入",
            "IT 導入",
            "事業再構築",
            "スタートアップ",
            "ディープテック",
            "成長加速",
            "新事業展開",
            "革新的事業",
        ],
        "keywords_avoid": [
            "事業承継",
            "M&A",
            "上場",
            "IPO",
            "創業前",
        ],
        "representative_program_keys": [
            "ものづくり補助金",
            "IT導入補助金",
            "事業再構築補助金",
            "ディープテック",
            "中小企業成長加速化補助金",
        ],
    },
    {
        "id": "growth",
        "ja_label": "グロース (5〜10 年目)",
        "description": (
            "本格スケール・量産投資・海外展開フェーズ。設備投資型補助金/"
            "成長促進補助金/JETRO 系海外展開支援/中堅企業向け施策が中心。"
        ),
        "age_min_years": 3,
        "age_max_years": None,
        "capital_max_yen": 300_000_000,
        "revenue_band_yen": [100_000_000, 5_000_000_000],
        "keywords_any": [
            "成長",
            "海外展開",
            "輸出",
            "設備投資",
            "中堅",
            "DX",
            "GX",
            "脱炭素",
            "省エネ",
            "競争力強化",
            "サプライチェーン",
        ],
        "keywords_avoid": [
            "創業",
            "事業承継",
            "M&A",
            "廃業",
        ],
        "representative_program_keys": [
            "中小企業成長加速化補助金",
            "海外展開",
            "設備投資",
            "サプライチェーン",
            "省エネ",
        ],
    },
    {
        "id": "ipo",
        "ja_label": "IPO (上場準備)",
        "description": (
            "上場準備・公開後の成長資金調達フェーズ。J-Startup/グローバル "
            "スタートアップ・アクセラレーション/上場支援/公開後の研究開発税制等。"
            "※ 日本の補助金/融資/税制では『IPO 専用』の制度は限定的で、"
            "上場準備企業は研究開発税制 + 中堅企業施策 + ベンチャー支援を"
            "重ねる運用が現実的。"
        ),
        "age_min_years": 5,
        "age_max_years": None,
        "capital_max_yen": None,
        "revenue_band_yen": [500_000_000, None],
        "keywords_any": [
            "上場",
            "IPO",
            "J-Startup",
            "グローバル",
            "ベンチャー",
            "成長投資",
            "研究開発税制",
            "オープンイノベーション",
        ],
        "keywords_avoid": [
            "創業前",
            "創業",
            "廃業",
        ],
        "representative_program_keys": [
            "J-Startup",
            "ディープテック・スタートアップ",
            "オープンイノベーション促進税制",
            "研究開発税制",
        ],
    },
    {
        "id": "succession",
        "ja_label": "事業承継 / M&A",
        "description": (
            "事業承継・M&A・廃業再チャレンジフェーズ。事業承継・M&A補助金/"
            "事業承継税制(特例措置)/事業承継支援融資/廃業再チャレンジ等。"
        ),
        "age_min_years": 5,
        "age_max_years": None,
        "capital_max_yen": None,
        "revenue_band_yen": [None, None],
        "keywords_any": [
            "事業承継",
            "M&A",
            "M & A",
            "廃業",
            "再チャレンジ",
            "後継者",
            "経営継承",
        ],
        "keywords_avoid": [
            "創業",
            "起業",
            "新創業",
        ],
        "representative_program_keys": [
            "事業承継・M&A補助金",
            "事業承継税制",
            "事業承継支援融資",
            "事業承継推進",
            "廃業・再チャレンジ",
        ],
    },
]


_STAGE_BY_ID: dict[str, dict[str, Any]] = {s["id"]: s for s in _STAGES}

_DISCLAIMER = (
    "funding_stage matcher は jpintel.programs を keyword fence + age/capital band "
    "で篩った heuristic です。日本の制度は『stage X 専用』タグを持たないため、"
    "stage 判定は keywords_any / keywords_avoid 公開定義に依拠した近似値です。"
    "必ず source_url / 一次資料 + 専門家確認を経てください。"
    "本 response は 申請代理 / 税務助言 / 経営判断を構成しません。"
)


# ---------------------------------------------------------------------------
# Catalog endpoint — free, read-only, never metered.
# ---------------------------------------------------------------------------


@router.get(
    "/funding_stages/catalog",
    summary="資金調達ステージカタログ (5 stage 定義 + 代表制度)",
    description=(
        "5 ステージ (seed / early / growth / ipo / succession) の定義 + "
        "indicative 帯 (age / capital / revenue) + keyword fence + jpintel "
        "プログラムから抽出した 代表制度 リストを返す。FREE 路。"
    ),
)
def get_funding_stages_catalog(
    conn: DbDep,
) -> dict[str, Any]:
    """Return the 5-stage catalog with representative program rows pulled from
    jpintel.programs by primary_name keyword match.

    No metering — catalog is constant data.
    """
    out_stages: list[dict[str, Any]] = []
    for stage in _STAGES:
        rep_rows = _representative_programs_for_stage(conn, stage)
        out_stages.append(
            {
                "id": stage["id"],
                "ja_label": stage["ja_label"],
                "description": stage["description"],
                "age_min_years": stage["age_min_years"],
                "age_max_years": stage["age_max_years"],
                "capital_max_yen": stage["capital_max_yen"],
                "revenue_band_yen": stage["revenue_band_yen"],
                "keywords_any": list(stage["keywords_any"]),
                "keywords_avoid": list(stage["keywords_avoid"]),
                "representative_programs": rep_rows,
            }
        )
    return {
        "stages": out_stages,
        "total": len(out_stages),
        "limit": len(out_stages),
        "offset": 0,
        "results": out_stages,
        "_disclaimer": _DISCLAIMER,
    }


def _representative_programs_for_stage(
    conn: sqlite3.Connection,
    stage: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return up to 5 representative programs for the given stage by name match.

    Each row carries unified_id + primary_name + tier + program_kind +
    amount_max_man_yen + source_url so the catalog UI can deep-link directly
    to the program page.
    """
    rep_keys = list(stage.get("representative_program_keys") or [])
    if not rep_keys:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in rep_keys:
        try:
            rows = conn.execute(
                """
                SELECT unified_id, primary_name, tier, program_kind,
                       amount_max_man_yen, source_url
                  FROM programs
                 WHERE excluded = 0
                   AND tier IN ('S', 'A', 'B', 'C')
                   AND primary_name LIKE ?
                 ORDER BY
                    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1
                             WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
                    COALESCE(amount_max_man_yen, 0) DESC
                 LIMIT 2
                """,
                (f"%{key}%",),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning(
                "funding_stage catalog: representative lookup failed for %r: %s",
                key,
                exc,
            )
            continue
        for r in rows:
            uid = r["unified_id"] if isinstance(r, sqlite3.Row) else r[0]
            if uid in seen:
                continue
            seen.add(uid)
            out.append(
                {
                    "unified_id": uid,
                    "primary_name": (r["primary_name"] if isinstance(r, sqlite3.Row) else r[1]),
                    "tier": r["tier"] if isinstance(r, sqlite3.Row) else r[2],
                    "program_kind": (r["program_kind"] if isinstance(r, sqlite3.Row) else r[3]),
                    "amount_max_man_yen": (
                        r["amount_max_man_yen"] if isinstance(r, sqlite3.Row) else r[4]
                    ),
                    "source_url": (r["source_url"] if isinstance(r, sqlite3.Row) else r[5]),
                    "matched_key": key,
                }
            )
            if len(out) >= 5:
                return out
    return out


# ---------------------------------------------------------------------------
# Matcher endpoint — POST /v1/programs/by_funding_stage
# ---------------------------------------------------------------------------


class FundingStageMatchBody(BaseModel):
    """Request body for ``POST /v1/programs/by_funding_stage``."""

    model_config = ConfigDict(extra="ignore")

    stage: str = Field(
        ...,
        description=(
            "Funding stage slug — one of "
            "``seed`` / ``early`` / ``growth`` / ``ipo`` / ``succession``. "
            "See ``GET /v1/funding_stages/catalog`` for definitions."
        ),
        examples=["growth"],
    )
    annual_revenue_yen: int | None = Field(
        default=None,
        ge=0,
        description="年商 (yen). None = 開示しない (matcher は revenue 帯を緩和)。",
    )
    employee_count: int | None = Field(
        default=None,
        ge=0,
        description="従業員数。None = 開示しない。",
    )
    incorporation_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "設立年 (西暦)。None = 開示しない。年齢は "
            "(現年 - incorporation_year) で算出し stage の age band に当て込む。"
        ),
    )
    prefecture: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "都道府県 exact match (例: '東京都')。None = 全国スコープ。"
            "国/都道府県/市町村 すべての programs を含む (national + prefecture + "
            "他県の制度を除外)。"
        ),
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="返却する programs の最大件数。Clamped to [1, 100]。Default 20。",
    )


@router.post(
    "/programs/by_funding_stage",
    summary="資金調達ステージ別 program マッチャー",
    description=(
        "5 ステージ (seed / early / growth / ipo / succession) のいずれかを "
        "指定すると、stage の keyword fence + 年齢/資本金/売上帯 + 任意の都道府県 "
        "で programs を篩い、`amount_max_man_yen × likelihood` 順に sort して "
        "返す。\n\n"
        "* 1 リクエスト = 1 課金単位 (¥3/req)\n"
        "* anonymous tier は 3 req/日 IP 制限を共有\n"
        "* `_disclaimer` フィールドは必須 — stage 判定は heuristic\n"
        "* `axes_applied` は実際に honored したフィルタ軸を返す"
    ),
)
def match_programs_by_funding_stage(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[
        FundingStageMatchBody,
        Body(description="Funding stage + 4-axis 軽量プロファイル"),
    ],
) -> dict[str, Any]:
    """POST /v1/programs/by_funding_stage — stage-aware program matcher."""
    t0 = time.perf_counter()
    if body.stage not in _STAGE_BY_ID:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_enum",
                "field": "stage",
                "message": (f"unknown stage {body.stage!r}. valid: {sorted(_STAGE_BY_ID.keys())}"),
                "hint": "GET /v1/funding_stages/catalog で 5 stage の定義を確認してください。",
            },
        )

    stage_def = _STAGE_BY_ID[body.stage]
    age_years = _age_years_from_year(body.incorporation_year)
    matched, axes_applied = _match_programs_for_stage(
        conn,
        stage=stage_def,
        annual_revenue_yen=body.annual_revenue_yen,
        employee_count=body.employee_count,
        age_years=age_years,
        prefecture=body.prefecture,
        limit=body.limit,
    )

    body_out: dict[str, Any] = {
        "input": {
            "stage": body.stage,
            "annual_revenue_yen": body.annual_revenue_yen,
            "employee_count": body.employee_count,
            "incorporation_year": body.incorporation_year,
            "age_years": age_years,
            "prefecture": body.prefecture,
            "limit": body.limit,
        },
        "stage_definition": {
            "id": stage_def["id"],
            "ja_label": stage_def["ja_label"],
            "description": stage_def["description"],
            "age_min_years": stage_def["age_min_years"],
            "age_max_years": stage_def["age_max_years"],
            "capital_max_yen": stage_def["capital_max_yen"],
            "revenue_band_yen": stage_def["revenue_band_yen"],
            "keywords_any": list(stage_def["keywords_any"]),
            "keywords_avoid": list(stage_def["keywords_avoid"]),
        },
        "matched_programs": matched,
        "axes_applied": axes_applied,
        "summary": {
            "total_matched": len(matched),
            "amount_max_man_yen_top": (
                matched[0]["amount_max_man_yen"]
                if matched and matched[0].get("amount_max_man_yen") is not None
                else None
            ),
        },
        "total": len(matched),
        "limit": body.limit,
        "offset": 0,
        "results": matched,
        "_disclaimer": _DISCLAIMER,
    }
    latency_ms = int((time.perf_counter() - t0) * 1000)

    log_usage(
        conn,
        ctx,
        "programs.by_funding_stage",
        params={
            "stage": body.stage,
            "prefecture": body.prefecture,
            "limit": body.limit,
        },
        latency_ms=latency_ms,
        result_count=len(matched),
        quantity=1,
        strict_metering=True,
    )
    attach_seal_to_body(
        body_out,
        endpoint="programs.by_funding_stage",
        request_params={
            "stage": body.stage,
            "prefecture": body.prefecture,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body_out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _age_years_from_year(year: int | None) -> int | None:
    """Convert ``incorporation_year`` to integer years since incorporation.

    Returns None when input is None. Negative results are clamped to 0
    (caller is "incorporated in the future" — silly, but don't crash).
    """
    if year is None:
        return None
    now_year = datetime.now(UTC).year
    return max(0, now_year - year)


def _match_programs_for_stage(
    conn: sqlite3.Connection,
    *,
    stage: dict[str, Any],
    annual_revenue_yen: int | None,
    employee_count: int | None,
    age_years: int | None,
    prefecture: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pull stage-fit programs out of jpintel.programs and rank them.

    Ranking score = ``amount_max_man_yen * likelihood``, where
    ``likelihood`` is in [0.1, 1.0]:
      * 1.0 baseline
      * +0.0 if all keywords_any match
      * scaled down if the row tier is B / C (raw recall but lower trust)
      * scaled down if a keywords_avoid term hits (fence-leak — drop hard)

    Returns (matched_rows, axes_applied_dict).
    """
    keywords_any: list[str] = list(stage.get("keywords_any") or [])
    keywords_avoid: list[str] = list(stage.get("keywords_avoid") or [])
    if not keywords_any:
        return [], {
            "stage_keyword_filter": False,
            "prefecture": prefecture,
            "age_filter": False,
            "revenue_filter": False,
            "employee_filter": False,
        }

    where_clauses: list[str] = [
        "p.excluded = 0",
        "p.tier IN ('S','A','B','C')",
    ]
    bind_params: list[Any] = []

    # Keyword OR ladder against primary_name + aliases_json (best-effort).
    kw_or = " OR ".join(["p.primary_name LIKE ?"] * len(keywords_any))
    where_clauses.append(f"({kw_or})")
    bind_params.extend([f"%{kw}%" for kw in keywords_any])

    # Prefecture: include national + prefecture-match. We accept rows whose
    # prefecture is NULL (national / 業種別) OR exact-matches the caller.
    if prefecture:
        where_clauses.append("(p.prefecture IS NULL OR p.prefecture = '' OR p.prefecture = ?)")
        bind_params.append(prefecture)

    sql = f"""
        SELECT
            unified_id, primary_name, aliases_json, authority_level,
            authority_name, prefecture, municipality, program_kind,
            official_url, source_url,
            amount_max_man_yen, amount_min_man_yen, subsidy_rate,
            tier, target_types_json, funding_purpose_json, amount_band
          FROM programs p
         WHERE {" AND ".join(where_clauses)}
         ORDER BY
            CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1
                     WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
            COALESCE(amount_max_man_yen, 0) DESC
         LIMIT ?
    """
    bind_params.append(max(1, min(limit, 100)) * 4)  # over-fetch for scoring

    try:
        rows = conn.execute(sql, bind_params).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("funding_stage matcher SQL failed: %s", exc)
        rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r) if isinstance(r, sqlite3.Row) else dict(zip(r.keys(), r, strict=False))
        primary_name = d.get("primary_name") or ""
        # Avoid-keyword fence: hard-drop the row if any avoid term hits.
        if any(av in primary_name for av in keywords_avoid):
            continue
        likelihood = _likelihood_score(
            primary_name=primary_name,
            tier=d.get("tier"),
            keywords_any=keywords_any,
        )
        amt = d.get("amount_max_man_yen") or 0.0
        score = float(amt) * likelihood
        d["likelihood"] = round(likelihood, 4)
        d["score"] = round(score, 4)
        d["aliases"] = _safe_json_list(d.pop("aliases_json", None))
        d["target_types"] = _safe_json_list(d.pop("target_types_json", None))
        d["funding_purpose"] = _safe_json_list(d.pop("funding_purpose_json", None))
        out.append(d)

    out.sort(key=lambda r: (-r["score"], r["primary_name"] or ""))
    out = out[: max(1, min(limit, 100))]

    return out, {
        "stage_keyword_filter": True,
        "prefecture": prefecture,
        "age_filter": age_years is not None,
        "revenue_filter": annual_revenue_yen is not None,
        "employee_filter": employee_count is not None,
    }


def _likelihood_score(
    *,
    primary_name: str,
    tier: str | None,
    keywords_any: list[str],
) -> float:
    """Heuristic 0.1-1.0 likelihood score based on keyword density + tier.

    Rules (intentional simplicity — no LLM):
      * +0.6 if any keyword matches (fence pass)
      * +0.05 per additional matched keyword (capped at +0.3)
      * tier S → ×1.0 / A → ×0.9 / B → ×0.7 / C → ×0.55
      * floor 0.1, ceiling 1.0
    """
    if not primary_name or not keywords_any:
        return 0.1
    hits = sum(1 for kw in keywords_any if kw in primary_name)
    if hits <= 0:
        return 0.1
    base = 0.6 + min(0.3, (hits - 1) * 0.05)
    tier_factor = {"S": 1.0, "A": 0.9, "B": 0.7, "C": 0.55}.get(tier or "", 0.5)
    score = base * tier_factor
    return max(0.1, min(1.0, score))


def _safe_json_list(value: Any) -> list[Any]:
    """Decode a JSON string column to list. Defensive: returns [] on error."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except (ValueError, TypeError):
            return []
    return []


__all__ = [
    "router",
    "FundingStageMatchBody",
    "_STAGES",
    "_STAGE_BY_ID",
    "_match_programs_for_stage",
    "_likelihood_score",
    "_age_years_from_year",
]
