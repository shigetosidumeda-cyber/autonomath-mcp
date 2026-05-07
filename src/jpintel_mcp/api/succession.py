"""REST handlers for /v1/succession/* — M&A / 事業承継 制度 matcher.

Surfaces the 事業承継 chain (経営承継円滑化法 + 事業承継税制 +
事業承継・引継ぎ補助金 + M&A補助金 + 都道府県融資 + 政策金融公庫融資) for
中小企業 considering 後継者問題 / M&A. Pure SQLite + Python, NO LLM.

Two endpoints:

    POST /v1/succession/match
        body  = SuccessionMatchRequest (scenario, current_revenue,
                employee_count, owner_age)
        reply = SuccessionMatchResponse — applicable 制度 (税制 + 補助金 +
                法令支援) + scenario-tailored 適用条件 + recommendations.

    GET  /v1/succession/playbook
        reply = SuccessionPlaybookResponse — standard 事業承継 playbook
                (税理士 + M&A仲介 + 認定支援機関 + timeline + checkpoints).

Pricing
-------

¥3/req metered (1 unit per call). Anonymous tier shares the 3/日 per-IP
cap via AnonIpLimitDep on the router mount in api/main.py.

§52 envelope — every 2xx body carries a ``_disclaimer`` envelope key
explicitly fencing the response to 一般情報提供 (税理士法 §52, 弁護士法
§72, 中小企業診断士 ≠ 弁護士・税理士). Recommendations are checklist
material; final filings (相続税 / 贈与税 / 認定申請) require qualified
専門家 supervision.

Read-only. Reads from data/jpintel.db (programs + laws). Never opens a
write connection.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import sqlite3

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._envelope import StandardResponse, wants_envelope_v2
from jpintel_mcp.api._error_envelope import safe_request_id
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.succession")

router = APIRouter(prefix="/v1/succession", tags=["succession"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Disclaimer copy fences the response into 一般情報提供 territory only.
# 税理士法 §52 (税務助言の制限), 弁護士法 §72 (法律事務取扱の制限),
# 中小企業診断士 自体は資格として個別税務 / 法律相談を行えない、を統合した
# checklist-only 文言。
_DISCLAIMER = (
    "本情報は事業承継に関する一般的な制度紹介であり、個別具体的な税務助言・"
    "法的助言ではありません (税理士法 §52 / 弁護士法 §72)。相続税・贈与税の"
    "申告、経営承継円滑化法に基づく認定申請、M&A契約 等の最終判断は、必ず"
    "税理士・公認会計士・弁護士・認定経営革新等支援機関 等の有資格者に"
    "ご相談ください。本サービスは公的機関 (中小企業庁・国税庁・経済産業省・"
    "都道府県・日本政策金融公庫 等) が公表する制度情報を検索・整理して"
    "提供するものです。"
)

# Scenario enum (closed). Picking the scenario first lets us tailor the
# 制度 chain — child_inherit (親族内) leans on 事業承継税制 + 経営承継
# 円滑化法 認定、m_and_a (第三者承継) on M&A補助金 + 引継ぎ補助金、
# employee_buy_out (役員・従業員承継 / EBO) sits in between.
_SCENARIOS: dict[str, dict[str, Any]] = {
    "child_inherit": {
        "label_ja": "親族内承継 (子・親族への承継)",
        "primary_levers": [
            "事業承継税制 (法人版特例措置)",
            "事業承継税制 (個人版)",
            "経営承継円滑化法 (遺留分特例 / 金融支援)",
            "事業承継・引継ぎ補助金 (経営革新枠)",
        ],
        "key_keywords": ["事業承継", "承継", "後継"],
    },
    "m_and_a": {
        "label_ja": "第三者承継 (M&A・事業譲渡)",
        "primary_levers": [
            "事業承継・引継ぎ補助金 (M&A枠 / 専門家活用枠)",
            "経営承継円滑化法 (M&A 認定支援)",
            "中小企業基盤整備機構 事業承継・引継ぎ支援センター",
            "中小M&A推進計画 (中小企業庁)",
        ],
        "key_keywords": ["M&A", "承継", "引継ぎ", "事業譲渡"],
    },
    "employee_buy_out": {
        "label_ja": "役員・従業員承継 (EBO / MBO)",
        "primary_levers": [
            "事業承継・引継ぎ補助金 (経営革新枠)",
            "経営承継円滑化法 (金融支援 — 株式取得資金)",
            "日本政策金融公庫 事業承継・集約・活性化支援資金",
        ],
        "key_keywords": ["事業承継", "承継", "MBO", "EBO"],
    },
}

# 経営承継円滑化法 + 関連法令 (e-Gov 検索キー)。programs テーブルへの
# JOIN は law_short_title でなく law_title 部分一致 (LIKE) を使う。
_RELATED_LAW_TITLES = (
    "中小企業における経営の承継の円滑化に関する法律",
    "中小企業における経営の承継の円滑化に関する法律施行令",
    "中小企業における経営の承継の円滑化に関する法律施行規則",
    "相続税法",
)

# 中小企業 size fence. 事業承継税制 等は中小企業者 (中小企業基本法 §2)
# の枠内のみ適用。資本金 / 従業員数 の業種別表は明細書から省略するが、
# 一般的な売上 / 従業員数 の上下限を closed integer cap として扱い、
# それを越える場合は 'large_enterprise' フラグを立てて 適格性 判定
# から外す。
_LARGE_ENTERPRISE_REVENUE_THRESHOLD = 5_000_000_000  # ¥50億 以上で大企業寄り
_LARGE_ENTERPRISE_EMPLOYEE_THRESHOLD = 300  # 300名 以上で大企業寄り

# Cap on the number of programs returned in a match. 5 件で上位の制度
# を提示し、深掘りは search_programs / get_program で取得する想定。
_MAX_PROGRAMS = 8

# Owner age threshold for 早期承継 advisory. 70 歳以上は政府の 70 万人
# 後継者不在問題 の対象層、リスク高 cohort として強調する。
_OWNER_AGE_HIGH_RISK = 70


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SuccessionMatchRequest(BaseModel):
    """POST body for /v1/succession/match.

    Closed-vocab `scenario` + 3 numeric 中小企業 dimensions.
    """

    model_config = ConfigDict(frozen=True)

    scenario: Annotated[
        str,
        Field(
            description=(
                "承継 scenario. 'child_inherit'=親族内承継, "
                "'m_and_a'=第三者 (M&A・事業譲渡), "
                "'employee_buy_out'=役員・従業員 (EBO/MBO)."
            ),
            pattern=r"^(child_inherit|m_and_a|employee_buy_out)$",
        ),
    ]
    current_revenue: Annotated[
        int,
        Field(
            description=(
                "Current annual revenue in JPY (税抜・概算)。"
                "中小企業判定 (中小企業基本法 §2) に使う粗い目安。"
            ),
            ge=0,
            le=10_000_000_000_000,
        ),
    ]
    employee_count: Annotated[
        int,
        Field(
            description=(
                "Full-time-equivalent employee count。"
                "中小企業者該当性 (業種別 300名/100名/50名) のおおまかな閾値判定に使う。"
            ),
            ge=0,
            le=1_000_000,
        ),
    ]
    owner_age: Annotated[
        int,
        Field(
            description=("代表取締役 (現オーナー) の年齢。70歳以上は早期承継 advisory が立つ。"),
            ge=18,
            le=120,
        ),
    ]


class ProgramMatch(BaseModel):
    """One matched 制度 row."""

    model_config = ConfigDict(frozen=True)

    unified_id: str
    name: str
    program_kind: str | None
    authority_level: str | None
    authority_name: str | None
    prefecture: str | None
    tier: str | None
    amount_max_man_yen: float | None
    source_url: str | None


class LegalSupport(BaseModel):
    """One related 法令 row (経営承継円滑化法 等)."""

    model_config = ConfigDict(frozen=True)

    unified_id: str
    law_title: str
    law_short_title: str | None
    ministry: str | None
    full_text_url: str | None
    source_url: str


class TaxLever(BaseModel):
    """A 税制 lever (curated; not pulled from DB)."""

    model_config = ConfigDict(frozen=True)

    name: str
    summary: str
    primary_source_url: str
    applicability_note: str


class SuccessionMatchResponse(BaseModel):
    """Body of /v1/succession/match (200)."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    scenario_label_ja: str
    cohort_summary: dict[str, Any]
    is_chusho_kigyo: bool
    early_succession_advised: bool
    primary_levers: list[str]
    programs: list[ProgramMatch]
    tax_levers: list[TaxLever]
    legal_support: list[LegalSupport]
    next_steps: list[str]
    provenance: dict[str, Any]
    disclaimer: str = Field(default="", alias="_disclaimer")


class PlaybookStep(BaseModel):
    """One step in the standard succession playbook."""

    model_config = ConfigDict(frozen=True)

    step_no: int
    label_ja: str
    advisor_kind: str
    horizon: str
    deliverables: list[str]
    primary_sources: list[str]


class SuccessionPlaybookResponse(BaseModel):
    """Body of /v1/succession/playbook (200)."""

    model_config = ConfigDict(frozen=True)

    overview_ja: str
    typical_horizon_years: str
    advisor_chain: list[str]
    steps: list[PlaybookStep]
    cliff_dates: list[dict[str, str]]
    primary_sources: list[dict[str, str]]
    disclaimer: str = Field(default="", alias="_disclaimer")


# ---------------------------------------------------------------------------
# Curated 税制 levers — pinned to 中小企業庁 / 国税庁 primary sources
# ---------------------------------------------------------------------------


_TAX_LEVERS_BY_SCENARIO: dict[str, list[dict[str, str]]] = {
    "child_inherit": [
        {
            "name": "事業承継税制 (法人版特例措置)",
            "summary": (
                "後継者が先代経営者から非上場株式を相続・贈与で取得した場合、"
                "一定要件下で 相続税・贈与税 の 100% 納税猶予・免除。特例措置は"
                "事前に特例承継計画の提出が必要。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html"
            ),
            "applicability_note": (
                "中小企業者 (中小企業基本法) かつ非上場の 株式会社・特例有限会社。"
                "都道府県知事の認定が必要。"
            ),
        },
        {
            "name": "事業承継税制 (個人版)",
            "summary": (
                "個人事業者が事業用資産を後継者に相続・贈与で承継した場合、"
                "一定要件下で 相続税・贈与税 の納税猶予。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/zaimu/shoukei/kojinjigyou_shoukei.html"
            ),
            "applicability_note": "青色申告かつ個人版承継計画の提出が必要。",
        },
        {
            "name": "相続時精算課税制度",
            "summary": (
                "60歳以上の親から18歳以上の子・孫への贈与で、累計2,500万円までを"
                "贈与時非課税 → 相続時に精算する制度。事業承継の事前対策として併用。"
            ),
            "primary_source_url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/sozoku/4103.htm",
            "applicability_note": "暦年課税との選択制 (一度選択したら撤回不可)。",
        },
    ],
    "m_and_a": [
        {
            "name": "中小企業の経営資源集約化に資する税制",
            "summary": (
                "M&A実施後の簿外債務リスク等に備えるための準備金積立を損金算入。"
                "中小企業経営強化税制 D類型と組み合わせる場合あり。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/keiei/kyoka/2021/210624kyoka.html"
            ),
            "applicability_note": ("経営力向上計画の認定が前提。70%以上の株式取得 等の要件あり。"),
        },
        {
            "name": "登録免許税・不動産取得税 軽減措置 (経営承継円滑化法)",
            "summary": (
                "経営承継円滑化法 認定下での合併・事業譲渡に伴う 登録免許税・不動産取得税 の軽減。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html"
            ),
            "applicability_note": "都道府県知事の経営力向上計画認定が必要。",
        },
    ],
    "employee_buy_out": [
        {
            "name": "事業承継税制 (役員・従業員承継 への適用)",
            "summary": (
                "親族外の役員・従業員への株式承継についても、特例承継計画を提出"
                "した上で 相続税・贈与税 の納税猶予が利用可能。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html"
            ),
            "applicability_note": ("親族内承継と同じく特例承継計画提出 + 都道府県知事認定が必要。"),
        },
        {
            "name": "中小企業経営強化税制 D類型 (経営資源集約化設備)",
            "summary": (
                "経営力向上計画の認定下で取得した設備の特別償却 / 税額控除。"
                "EBO/MBO 後の生産性向上投資に併用可能。"
            ),
            "primary_source_url": (
                "https://www.chusho.meti.go.jp/keiei/kyoka/2021/210624kyoka.html"
            ),
            "applicability_note": "経営力向上計画 認定 + 工業会証明書 等が必要。",
        },
    ],
}


# ---------------------------------------------------------------------------
# Cliff dates (legislative sunset / scheduled changes)
# ---------------------------------------------------------------------------


_CLIFF_DATES: list[dict[str, str]] = [
    {
        "date": "2026-03-31",
        "label_ja": "事業承継税制 特例承継計画 提出期限",
        "note": "提出が無い場合、特例措置 (100%猶予) は使えなくなる。",
    },
    {
        "date": "2027-12-31",
        "label_ja": "事業承継税制 特例措置 適用期限",
        "note": (
            "2027/12/31 までに 相続・贈与 を完了させる必要がある "
            "(ただし国会審議による延長の可能性あり、最新の中小企業庁告示を確認)。"
        ),
    },
]


# ---------------------------------------------------------------------------
# Standard advisor chain & playbook (curated)
# ---------------------------------------------------------------------------


_PLAYBOOK_STEPS: list[dict[str, Any]] = [
    {
        "step_no": 1,
        "label_ja": "現状把握 (株主構成・財務・組織)",
        "advisor_kind": "認定経営革新等支援機関 (税理士・会計士)",
        "horizon": "1〜3 ヶ月",
        "deliverables": [
            "株主名簿 / 持株比率",
            "直近3期の決算書・税務申告書",
            "事業承継診断書 (中小企業庁ひな形)",
        ],
        "primary_sources": [
            "https://www.chusho.meti.go.jp/zaimu/shoukei/2017/170719shoukei.html",
        ],
    },
    {
        "step_no": 2,
        "label_ja": "承継方針の決定 (親族内 / 第三者 / 役員従業員)",
        "advisor_kind": "認定経営革新等支援機関 + 弁護士",
        "horizon": "1〜2 ヶ月",
        "deliverables": [
            "承継方針書",
            "後継者候補リスト",
            "M&A候補リスト (該当時)",
        ],
        "primary_sources": [
            "https://www.chusho.meti.go.jp/zaimu/shoukei/2022/220404shoukei.html",
        ],
    },
    {
        "step_no": 3,
        "label_ja": "経営承継円滑化法 認定申請 + 特例承継計画提出",
        "advisor_kind": "税理士 + 都道府県中小企業担当部署",
        "horizon": "提出期限まで (2026-03-31 が現行 cliff)",
        "deliverables": [
            "特例承継計画 (中小企業庁ひな形)",
            "都道府県知事 認定申請書",
        ],
        "primary_sources": [
            "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html",
            "https://laws.e-gov.go.jp/law/420AC0000000033",
        ],
    },
    {
        "step_no": 4,
        "label_ja": "M&A仲介・FA選定 (M&Aルート時)",
        "advisor_kind": "登録M&A支援機関 (中小企業庁 登録制度)",
        "horizon": "3〜6 ヶ月",
        "deliverables": [
            "FA契約書 / 仲介契約書",
            "ノンネームシート / IM (Information Memorandum)",
        ],
        "primary_sources": [
            "https://www.chusho.meti.go.jp/zaimu/shoukei/2021/210430shoukei.html",
            "https://ma-shienkikan.go.jp/",
        ],
    },
    {
        "step_no": 5,
        "label_ja": "事業承継・引継ぎ補助金 申請 (該当枠)",
        "advisor_kind": "認定経営革新等支援機関",
        "horizon": "公募回ごと",
        "deliverables": [
            "事業承継・引継ぎ補助金 交付申請書",
            "事業計画書",
        ],
        "primary_sources": [
            "https://www.shokei-hojo.jp/",
        ],
    },
    {
        "step_no": 6,
        "label_ja": "株式・事業譲渡 / 相続・贈与 実行",
        "advisor_kind": "弁護士 + 税理士 + 司法書士",
        "horizon": "2〜4 ヶ月",
        "deliverables": [
            "株式譲渡契約書 / 事業譲渡契約書 / 贈与契約書",
            "相続税・贈与税 申告書 (申告期限内)",
            "登記申請書 (該当時)",
        ],
        "primary_sources": [
            "https://www.nta.go.jp/taxes/shiraberu/taxanswer/sozoku/4103.htm",
        ],
    },
    {
        "step_no": 7,
        "label_ja": "PMI (Post Merger Integration) / 承継後統合",
        "advisor_kind": "認定経営革新等支援機関",
        "horizon": "6〜18 ヶ月",
        "deliverables": [
            "PMI計画書 (中小企業庁 PMIガイドライン準拠)",
            "経営力向上計画 認定 (税制併用時)",
        ],
        "primary_sources": [
            "https://www.chusho.meti.go.jp/zaimu/shoukei/2022/220317shoukei.html",
        ],
    },
]


_PLAYBOOK_PRIMARY_SOURCES: list[dict[str, str]] = [
    {
        "name": "中小企業庁 事業承継ポータル",
        "url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
    },
    {
        "name": "事業承継税制 (法人版特例措置)",
        "url": "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html",
    },
    {
        "name": "経営承継円滑化法 (e-Gov)",
        "url": "https://laws.e-gov.go.jp/law/420AC0000000033",
    },
    {
        "name": "事業承継・引継ぎ補助金",
        "url": "https://www.shokei-hojo.jp/",
    },
    {
        "name": "中小企業庁 M&A支援機関 登録制度",
        "url": "https://ma-shienkikan.go.jp/",
    },
    {
        "name": "国税庁 相続税・贈与税 タックスアンサー",
        "url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/sozoku/",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mark_envelope_v2_served(request: Request) -> None:
    """Tell EnvelopeAdapterMiddleware that this route emitted the v2 shape."""
    with contextlib.suppress(Exception):
        request.state.envelope_v2_served = True


def _classify_chusho(revenue_jpy: int, employee_count: int) -> bool:
    """Rough 中小企業者該当性 — coarse threshold so the response can flag
    'this entity may exceed 中小企業 cap' without claiming a definitive
    legal classification.

    The 中小企業基本法 §2 actual table varies by industry (製造業 等
    300名 / ¥3億, 卸売業 100名 / ¥1億, 小売業 50名 / ¥5千万, サービス
    100名 / ¥5千万). We treat anything above the 製造業 ceiling as a
    'large_enterprise' candidate and surface a hint rather than gate.
    """
    if revenue_jpy >= _LARGE_ENTERPRISE_REVENUE_THRESHOLD:
        return False
    return employee_count < _LARGE_ENTERPRISE_EMPLOYEE_THRESHOLD


def _query_succession_programs(
    conn: sqlite3.Connection,
    keywords: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Return up to `limit` succession-related programs whose primary_name
    matches any of the supplied keywords. Quarantined / excluded rows are
    filtered out. Tier S / A rows surface first.
    """

    if not keywords:
        return []

    # Build a parameterised LIKE union. Each keyword becomes one OR branch.
    like_clauses = " OR ".join(["primary_name LIKE ?"] * len(keywords))
    like_params = [f"%{kw}%" for kw in keywords]

    # Detect optional `audit_quarantined` column. Migration 167 added it on
    # the production jpintel.db, but the seeded test fixture and pre-167
    # snapshots don't carry it. We probe once and fall through gracefully so
    # both surfaces work without a hard schema dependency.
    has_audit_quarantined = bool(
        conn.execute(
            "SELECT 1 FROM pragma_table_info('programs') WHERE name = 'audit_quarantined'"
        ).fetchone()
    )
    audit_clause = " AND audit_quarantined = 0" if has_audit_quarantined else ""

    sql = f"""
        SELECT unified_id, primary_name, program_kind, authority_level,
               authority_name, prefecture, tier, amount_max_man_yen, source_url
          FROM programs
         WHERE excluded = 0{audit_clause}
           AND tier IN ('S', 'A', 'B', 'C')
           AND ({like_clauses})
         ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1
                            WHEN 'B' THEN 2 WHEN 'C' THEN 3 END,
                  COALESCE(amount_max_man_yen, 0) DESC,
                  primary_name
         LIMIT ?
    """
    rows = conn.execute(sql, (*like_params, int(limit))).fetchall()
    return [
        {
            "unified_id": r["unified_id"],
            "name": r["primary_name"],
            "program_kind": r["program_kind"],
            "authority_level": r["authority_level"],
            "authority_name": r["authority_name"],
            "prefecture": r["prefecture"],
            "tier": r["tier"],
            "amount_max_man_yen": r["amount_max_man_yen"],
            "source_url": r["source_url"],
        }
        for r in rows
    ]


def _query_related_laws(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return the 4 fixed succession-related laws (経営承継円滑化法 + 関連)."""

    out: list[dict[str, Any]] = []
    for title in _RELATED_LAW_TITLES:
        row = conn.execute(
            """SELECT unified_id, law_title, law_short_title, ministry,
                      full_text_url, source_url
                 FROM laws
                WHERE law_title = ?
                LIMIT 1""",
            (title,),
        ).fetchone()
        if row is None:
            continue
        out.append(
            {
                "unified_id": row["unified_id"],
                "law_title": row["law_title"],
                "law_short_title": row["law_short_title"],
                "ministry": row["ministry"],
                "full_text_url": row["full_text_url"],
                "source_url": row["source_url"],
            }
        )
    return out


def _build_next_steps(
    *,
    scenario: str,
    is_chusho: bool,
    early_advised: bool,
    program_count: int,
) -> list[str]:
    """Compose the per-call advisory checklist."""
    steps: list[str] = []

    if not is_chusho:
        steps.append(
            "売上 / 従業員数 が中小企業基本法 §2 の上限を超えている可能性が"
            "高いため、事業承継税制 等の中小企業者向け施策の適用要件を"
            "再確認してください。"
        )

    if early_advised:
        steps.append(
            "代表者年齢が 70 歳以上です。事業承継税制の特例措置 cliff "
            "(2026-03-31 計画提出 / 2027-12-31 適用期限) が迫っているため、"
            "早期に都道府県の事業承継・引継ぎ支援センターへ相談してください。"
        )

    if scenario == "child_inherit":
        steps.append(
            "親族内承継: 特例承継計画 (中小企業庁ひな形) の提出を最優先。"
            "提出後に贈与・相続を実行する流れが推奨です。"
        )
    elif scenario == "m_and_a":
        steps.append(
            "第三者承継 (M&A): 中小企業庁登録 M&A支援機関の選定 + 事業承継・"
            "引継ぎ補助金 (M&A枠) の公募回 確認 が初動です。"
        )
    elif scenario == "employee_buy_out":
        steps.append(
            "役員・従業員承継 (EBO/MBO): 株式取得資金の調達 (政策金融公庫 "
            "事業承継・集約・活性化支援資金 等) と特例承継計画 提出を並行進行。"
        )

    if program_count == 0:
        steps.append(
            "現スナップショットでマッチする補助金・融資が 0 件です。"
            "都道府県の事業承継・引継ぎ支援センター に直接相談し、"
            "公募回 / 自治体独自施策 を確認してください。"
        )

    steps.append(
        "本サービスは情報提供のみです。実際の申告・認定申請は、認定経営"
        "革新等支援機関 (税理士・公認会計士 等) 監修のもとで実施してください。"
    )
    return steps


# ---------------------------------------------------------------------------
# POST /v1/succession/match
# ---------------------------------------------------------------------------


@router.post(
    "/match",
    response_model=SuccessionMatchResponse,
    summary="M&A / 事業承継 制度マッチ (no LLM)",
    description=(
        "scenario (親族内 / 第三者M&A / 役員従業員) + 売上 / 従業員数 / "
        "代表者年齢 から、適用候補となる 補助金・税制・法令支援 を"
        "deterministic に列挙する。1 unit = 1 call (¥3 / 税込 ¥3.30)。"
        "Anonymous tier shares 3/日 per-IP cap.\n\n"
        "**§52 envelope:** every 2xx body carries `_disclaimer` — 一般"
        "情報提供 only, 個別税務助言・法律相談ではない。最終判断は"
        "税理士・弁護士・認定経営革新等支援機関 を経由のこと。"
    ),
)
def match_succession(
    payload: SuccessionMatchRequest,
    conn: DbDep,
    ctx: ApiContextDep,
    request: Request,
) -> JSONResponse:
    """Return scenario-tailored 制度 chain + advisory checklist."""

    _t0 = time.perf_counter()

    scenario = payload.scenario
    spec = _SCENARIOS[scenario]

    is_chusho = _classify_chusho(payload.current_revenue, payload.employee_count)
    early_advised = payload.owner_age >= _OWNER_AGE_HIGH_RISK

    programs = _query_succession_programs(conn, list(spec["key_keywords"]), _MAX_PROGRAMS)
    laws = _query_related_laws(conn)
    tax_levers = _TAX_LEVERS_BY_SCENARIO.get(scenario, [])
    next_steps = _build_next_steps(
        scenario=scenario,
        is_chusho=is_chusho,
        early_advised=early_advised,
        program_count=len(programs),
    )

    body: dict[str, Any] = {
        "scenario": scenario,
        "scenario_label_ja": spec["label_ja"],
        "cohort_summary": {
            "current_revenue_jpy": payload.current_revenue,
            "employee_count": payload.employee_count,
            "owner_age": payload.owner_age,
        },
        "is_chusho_kigyo": is_chusho,
        "early_succession_advised": early_advised,
        "primary_levers": list(spec["primary_levers"]),
        "programs": programs,
        "tax_levers": tax_levers,
        "legal_support": laws,
        "next_steps": next_steps,
        "provenance": {
            "data_origin": ("中小企業庁 + 国税庁 + e-Gov + 都道府県 + 日本政策金融公庫"),
            "program_corpus_size": len(programs),
            "law_corpus_size": len(laws),
            "tax_lever_count": len(tax_levers),
            "primary_source_root": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
        },
        "_disclaimer": _DISCLAIMER,
    }

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "succession.match",
        latency_ms=_latency_ms,
        params={
            "scenario": scenario,
            "owner_age_band": "70+" if early_advised else "<70",
            "is_chusho": is_chusho,
        },
        result_count=len(programs),
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="succession.match",
        request_params={
            "scenario": scenario,
            "current_revenue": payload.current_revenue,
            "employee_count": payload.employee_count,
            "owner_age": payload.owner_age,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_envelope_v2(request):
        _mark_envelope_v2_served(request)
        env = StandardResponse.sparse(
            [body],
            request_id=safe_request_id(request),
            citations=[
                {
                    "source_url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
                    "publisher": "中小企業庁",
                    "title": "事業承継ポータル",
                    "verification_status": "unknown",
                    "verification_basis": "local_catalog",
                    "live_verified_at_request": False,
                }
            ],
            query_echo={
                "normalized_input": {
                    "scenario": scenario,
                    "current_revenue": payload.current_revenue,
                    "employee_count": payload.employee_count,
                    "owner_age": payload.owner_age,
                },
                "applied_filters": {"scenario": scenario},
                "unparsed_terms": [],
            },
            latency_ms=_latency_ms,
            billable_units=1,
            client_tag=getattr(request.state, "client_tag", None),
        )
        return JSONResponse(
            content=env.to_wire(),
            headers={"X-Envelope-Version": "v2"},
        )

    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# GET /v1/succession/playbook
# ---------------------------------------------------------------------------


@router.get(
    "/playbook",
    response_model=SuccessionPlaybookResponse,
    summary="標準 事業承継 playbook (no LLM)",
    description=(
        "事業承継の標準フロー (税理士 → 認定支援機関 → M&A仲介 → 弁護士 → "
        "司法書士 等) を 7 step で返す。¥3/req metered (1 unit)。"
        "scenario によらない一般的 playbook で、scenario 別の制度マッチは "
        "POST /v1/succession/match を併用してください。\n\n"
        "**§52 envelope:** every 2xx body carries `_disclaimer`."
    ),
)
def get_succession_playbook(
    conn: DbDep,
    ctx: ApiContextDep,
    request: Request,
) -> JSONResponse:
    """Return the curated 7-step succession playbook + cliff dates."""

    _t0 = time.perf_counter()

    body: dict[str, Any] = {
        "overview_ja": (
            "中小企業の事業承継は (1) 現状把握 → (2) 承継方針決定 → "
            "(3) 経営承継円滑化法 認定 → (4) M&A仲介 / 後継者選定 → "
            "(5) 補助金申請 → (6) 株式・資産移転実行 → (7) PMI の 7 段階で"
            "標準化されています (中小企業庁 事業承継ガイドライン準拠)。"
        ),
        "typical_horizon_years": "5〜10 年 (早期着手推奨、法人は 7 年中央値)",
        "advisor_chain": [
            "認定経営革新等支援機関 (税理士・公認会計士)",
            "弁護士",
            "司法書士",
            "登録 M&A支援機関 (該当時)",
            "都道府県 事業承継・引継ぎ支援センター",
        ],
        "steps": _PLAYBOOK_STEPS,
        "cliff_dates": _CLIFF_DATES,
        "primary_sources": _PLAYBOOK_PRIMARY_SOURCES,
        "_disclaimer": _DISCLAIMER,
    }

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "succession.playbook",
        latency_ms=_latency_ms,
        params={"playbook": "standard"},
        result_count=len(_PLAYBOOK_STEPS),
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="succession.playbook",
        request_params={"playbook": "standard"},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_envelope_v2(request):
        _mark_envelope_v2_served(request)
        env = StandardResponse.sparse(
            [body],
            request_id=safe_request_id(request),
            citations=[
                {
                    "source_url": src["url"],
                    "publisher": "中小企業庁 / 国税庁 / e-Gov",
                    "title": src["name"],
                    "verification_status": "unknown",
                    "verification_basis": "local_catalog",
                    "live_verified_at_request": False,
                }
                for src in _PLAYBOOK_PRIMARY_SOURCES
            ],
            query_echo={
                "normalized_input": {},
                "applied_filters": {},
                "unparsed_terms": [],
            },
            latency_ms=_latency_ms,
            billable_units=1,
            client_tag=getattr(request.state, "client_tag", None),
        )
        return JSONResponse(
            content=env.to_wire(),
            headers={"X-Envelope-Version": "v2"},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body,
    )


__all__ = [
    "router",
    "SuccessionMatchRequest",
    "SuccessionMatchResponse",
    "SuccessionPlaybookResponse",
    "PlaybookStep",
    "ProgramMatch",
    "TaxLever",
    "LegalSupport",
]
