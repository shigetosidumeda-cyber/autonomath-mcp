"""A5 — 会社設立一式 Pack (¥800 / req, 司法書士 segment).

One MCP call assembles the canonical 会社設立 scaffold bundle for a
prospective houjin by composing 6 scaffold documents + 3 statutory
filing windows + 50+ canonical {{...}} placeholders:

  1. ``teikan_draft`` — 定款 draft (会社法 §27 / §28 / §30 必要的記載事項).
  2. ``setsuritsu_touki_shinsei_sho`` — 設立登記申請書 scaffold (司法書士).
  3. ``inkan_todoke_sho`` — 印鑑届出書 (法務局).
  4. ``houjin_setsuritsu_todoke_sho`` — 法人設立届出書 (税理士 supervision).
  5. ``kyuyo_shiharai_jimusho_todoke_sho`` — 給与支払事務所等の開設届出書.
  6. ``shakai_hoken_shinki_tekiyou_todoke`` — 健康保険・厚生年金 新規適用届
     (社労士 supervision).

Output is a flat list of 6 scaffold artifacts + 3 filing windows
+ a placeholder catalog. NO LLM — pure dict composition. No DB fan-out
is required because 会社設立 is a deterministic scaffold pack: the
4-tier inputs (法人格 / 代表者 / 出資額 / 業種 / 本店所在地) drive every
section template directly.

Hard constraints
----------------

* §52 / §47条の2 / §72 / §1 / §3 + 社労士法 + 商業登記法 + 会社法
  disclaimer envelope on every response.
* Scaffold-only — every artifact requires the cited 士業 supervision
  before submission. 公証人による 定款認証 (株式会社) は別途必要.
* No DB I/O — pack composition is deterministic on inputs.
* ``_billing_unit = 267`` so the host MCP server bills
  ``267 × ¥3 = ¥801 ≈ ¥800`` (A5 Tier D band, ¥100..¥1000).

Tool
----

* ``product_kaisha_setsuritsu_pack(entity_type, representative_name,
  representative_address, capital_yen, business_purpose,
  head_office_prefecture, head_office_city, jsic_major)`` — single
  bundle composition. Returns the 6 scaffolds + 3 windows + 50+
  placeholders ready for upstream agent fill via N9 placeholder bank.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ..moat_lane_tools._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.products.a5_kaisha_setsuritsu")

_PRODUCT_ID = "A5"
_SCHEMA_VERSION = "products.a5.v1"
_UPSTREAM_MODULE = "jpintel_mcp.mcp.products.product_a5_kaisha_setsuritsu"
_SEGMENT = "司法書士"

# A5 sells at ¥800 / call; the ¥3 metered ledger maps that to 267 units
# (ceil(800/3) = 267 → 267 * ¥3 = ¥801, +¥1 rounding floor of ¥800).
_BILLING_UNITS = 267
_TIER_LETTER = "D"  # F4 pricing_v2.PricingTier.D

_ENTITY_TYPES: tuple[str, ...] = (
    "株式会社",
    "合同会社",
    "一般社団法人",
    "NPO法人",
)

_A5_DISCLAIMER_SUFFIX = (
    "本 pack は corpus snapshot ベースの scaffold 文書集合体で、定款認証 / "
    "設立登記 / 税務署届出 / 年金事務所届出 を含む一切の法定手続きを完了 "
    "させる効力を持ちません。公証人役場での 定款認証 (株式会社) / 法務局 "
    "での設立登記申請 (司法書士独占 §3) / 税務署届出書面の作成 (税理士 "
    "supervision §52) / 年金事務所届出 (社労士 supervision) は必ず該当 "
    "士業 supervision の下で primary source を確認のうえ実施してください。"
)


# ---------------------------------------------------------------------------
# Scaffold catalogs (pure Python, deterministic on entity_type)
# ---------------------------------------------------------------------------


def _teikan_sections(entity_type: str) -> tuple[str, ...]:
    """Return 定款 必要的記載事項 (会社法 §27) section order."""
    is_kabushiki = entity_type == "株式会社"
    is_npo = entity_type == "NPO法人"
    return (
        "第1章 総則",
        "第1条 (商号)",
        "第2条 (目的)",
        "第3条 (本店所在地)",
        "第4条 (公告方法)",
        "第2章 株式 / 出資" if not is_npo else "第2章 会員",
        "第5条 (発行可能株式総数)" if is_kabushiki else "第5条 (出資 / 会員資格)",
        "第6条 (株式の譲渡制限)" if is_kabushiki else "第6条 (会員の権利)",
        "第3章 株主総会 / 社員総会",
        "第7条 (招集)",
        "第8条 (議決権)",
        "第4章 役員",
        "第9条 (取締役)" if is_kabushiki else "第9条 (業務執行)",
        "第10条 (代表取締役)" if is_kabushiki else "第10条 (代表者)",
        "第5章 計算",
        "第11条 (事業年度)",
        "第12条 (剰余金の処分)" if not is_npo else "第12条 (剰余金不分配)",
        "第6章 附則",
        "第13条 (設立に際して出資される財産)",
        "第14条 (最初の事業年度)",
        "第15条 (設立時取締役 / 設立時社員)",
    )


def _setsuritsu_touki_sections(entity_type: str) -> tuple[str, ...]:
    """Return 設立登記申請書 sections (商業登記法 §47, 法務局 hand-off)."""
    is_kabushiki = entity_type == "株式会社"
    is_npo = entity_type == "NPO法人"
    return (
        "申請書 (商号 / 本店 / 登記の事由 / 登記すべき事項)",
        "添付書面 — 定款" if not is_npo else "添付書面 — 寄附行為",
        "添付書面 — 払込証明書" if is_kabushiki else "添付書面 — 出資金領収書",
        "添付書面 — 設立時代表取締役選定書" if is_kabushiki else "添付書面 — 代表者選定書",
        "添付書面 — 印鑑届出書",
        "添付書面 — 印鑑証明書 (代表者)",
        "添付書面 — 本人確認証明書 (取締役 / 代表者)",
        "登録免許税 領収証書貼付欄",
    )


def _inkan_todoke_sections() -> tuple[str, ...]:
    return (
        "商号 (本店所在地)",
        "代表者 氏名 / 生年月日 / 住所",
        "届出印 押印欄",
        "代表者 個人印 押印欄",
        "印鑑カード交付申請有無",
    )


def _houjin_setsuritsu_todoke_sections() -> tuple[str, ...]:
    return (
        "提出先税務署名",
        "法人名 / 法人番号 (未取得欄)",
        "本店所在地",
        "代表者 氏名 / 住所",
        "事業年度",
        "設立年月日",
        "事業の目的 (定款写し添付)",
        "資本金又は出資金の額",
        "支店 / 出張所 / 工場等",
        "添付書面チェック (定款写し / 設立趣意書 / 登記事項証明書)",
    )


def _kyuyo_shiharai_jimusho_sections() -> tuple[str, ...]:
    return (
        "提出先税務署名",
        "事務所名称",
        "事務所所在地",
        "開設年月日",
        "給与支払の状況 (常時雇用人員 / 給与支払期日)",
        "源泉所得税の納期の特例の承認 有無",
    )


def _shakai_hoken_shinki_sections() -> tuple[str, ...]:
    return (
        "事業所名称 / 所在地",
        "事業主氏名 / 住所",
        "事業の種類",
        "適用年月日",
        "被保険者数",
        "健康保険組合加入有無",
        "添付書面チェック (登記事項証明書 / 法人番号指定通知書 / 賃貸借契約書)",
    )


# ---------------------------------------------------------------------------
# Placeholder catalog (50+ N9-style canonical tokens)
# ---------------------------------------------------------------------------


_PLACEHOLDERS: tuple[str, ...] = (
    # 商号 / 法人格
    "{{SHOUGOU}}",
    "{{HOUJIN_KAKU}}",
    "{{HOUJIN_KAKU_LATIN}}",
    "{{KAISHA_HOUJIN_BANGOU_PLACEHOLDER}}",
    # 本店所在地
    "{{HONTEN_PREFECTURE}}",
    "{{HONTEN_CITY}}",
    "{{HONTEN_BANCHI}}",
    "{{HONTEN_BUILDING}}",
    "{{HONTEN_POSTAL_CODE}}",
    # 代表者
    "{{DAIHYOUSHA_NAME}}",
    "{{DAIHYOUSHA_NAME_KANA}}",
    "{{DAIHYOUSHA_BIRTH}}",
    "{{DAIHYOUSHA_ADDRESS}}",
    "{{DAIHYOUSHA_INKAN}}",
    # 出資 / 資本金
    "{{CAPITAL_YEN}}",
    "{{CAPITAL_YEN_KANJI}}",
    "{{CAPITAL_PAYMENT_BANK}}",
    "{{CAPITAL_PAYMENT_DATE}}",
    "{{HAKKO_KABUSHIKI_SUU}}",
    "{{HATSUKO_KABUSHIKI_SUU_ICHIRI}}",
    # 事業目的
    "{{JIGYOU_MOKUTEKI_1}}",
    "{{JIGYOU_MOKUTEKI_2}}",
    "{{JIGYOU_MOKUTEKI_3}}",
    "{{JIGYOU_MOKUTEKI_OTHER}}",
    # 役員
    "{{TORISHIMARIYAKU_1}}",
    "{{TORISHIMARIYAKU_2}}",
    "{{KANSAYAKU_1}}",
    "{{SETSURITSUJI_TORISHIMARIYAKU}}",
    "{{NINKI_NENSUU}}",
    # 事業年度
    "{{JIGYOU_NENDO_START}}",
    "{{JIGYOU_NENDO_END}}",
    "{{KESSAN_TSUKI}}",
    # 設立日
    "{{SETSURITSU_DATE}}",
    "{{SETSURITSU_DATE_WAREKI}}",
    # 公告
    "{{KOUKOKU_METHOD}}",
    "{{KOUKOKU_NEWSPAPER}}",
    # 公証人
    "{{KOUSHOUNIN_OFFICE_NAME}}",
    "{{KOUSHOUNIN_ADDRESS}}",
    "{{NINSHOU_DATE_PLACEHOLDER}}",
    # 印鑑
    "{{KAISHA_DAIHYOU_INKAN_IMPRINT}}",
    "{{KAISHA_GINKOU_INKAN_IMPRINT}}",
    # 登録免許税
    "{{TOUROKU_MENKYO_ZEI}}",
    "{{TOUROKU_MENKYO_ZEI_RYOSHU_BANGOU}}",
    # 税務署
    "{{ZEIMUSHO_NAME}}",
    "{{ZEIMUSHO_KANKATSU_KU}}",
    "{{GENZEN_TOKUREI_SHINSEI}}",
    # 年金事務所
    "{{NENKIN_JIMUSHO_NAME}}",
    "{{HOKEN_TEKIYOU_DATE}}",
    "{{HIHOKENSHA_SUU}}",
    "{{KENKOU_HOKEN_KUMIAI}}",
    # 設立後 補助金 hint
    "{{POST_SETSURITSU_SUBSIDY_HINT}}",
    "{{POST_SETSURITSU_TAX_INCENTIVE_HINT}}",
    # 監督 士業
    "{{SUPERVISING_SHIHOUSHOSHI}}",
    "{{SUPERVISING_ZEIRISHI}}",
    "{{SUPERVISING_SHAROUSHI}}",
)


# ---------------------------------------------------------------------------
# Filing window math
# ---------------------------------------------------------------------------


def _filing_windows(setsuritsu_date: _dt.date) -> list[dict[str, Any]]:
    """Compute three statutory windows from the planned 設立日."""

    def iso(d: _dt.date) -> str:
        return d.isoformat()

    return [
        {
            "authority": "法務局",
            "document_name": "設立登記申請書",
            "statutory_basis": "商業登記法 §47 / 会社法 §911 (設立日 + 14日以内)",
            "window_open": iso(setsuritsu_date),
            "window_close": iso(setsuritsu_date + _dt.timedelta(days=14)),
            "days_from_setsuritsu": 14,
        },
        {
            "authority": "税務署",
            "document_name": "法人設立届出書 + 給与支払事務所等の開設届出書",
            "statutory_basis": "法人税法 §148 (設立日 + 2ヶ月以内) / 所得税法 §230",
            "window_open": iso(setsuritsu_date),
            "window_close": iso(setsuritsu_date + _dt.timedelta(days=60)),
            "days_from_setsuritsu": 60,
        },
        {
            "authority": "年金事務所",
            "document_name": "健康保険・厚生年金保険 新規適用届",
            "statutory_basis": "健康保険法 §48 / 厚生年金保険法 §27 (採用日 + 5日以内)",
            "window_open": iso(setsuritsu_date),
            "window_close": iso(setsuritsu_date + _dt.timedelta(days=5)),
            "days_from_setsuritsu": 5,
        },
    ]


# ---------------------------------------------------------------------------
# Scaffold composition
# ---------------------------------------------------------------------------


def _compose_scaffolds(entity_type: str) -> list[dict[str, Any]]:
    """Compose the 6 scaffold documents for the given entity_type."""
    return [
        {
            "artifact_type": "teikan_draft",
            "artifact_name_ja": "定款 (draft)",
            "document_kind": "teikan",
            "sections": list(_teikan_sections(entity_type)),
            "placeholders": [
                p
                for p in _PLACEHOLDERS
                if any(
                    n in p
                    for n in (
                        "SHOUGOU",
                        "HONTEN",
                        "DAIHYOUSHA",
                        "CAPITAL",
                        "JIGYOU_MOKUTEKI",
                        "JIGYOU_NENDO",
                        "TORISHIMARIYAKU",
                        "KANSAYAKU",
                        "KESSAN_TSUKI",
                        "KOUKOKU",
                        "SETSURITSU_DATE",
                        "NINKI_NENSUU",
                        "HAKKO_KABUSHIKI_SUU",
                    )
                )
            ],
            "statutory_basis": [
                "会社法 §27 (必要的記載事項)",
                "会社法 §28 (変態設立事項)",
                "会社法 §30 (定款の認証)",
            ],
            "supervising_shigyo": "司法書士 / 公証人",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
        {
            "artifact_type": "setsuritsu_touki_shinsei_sho",
            "artifact_name_ja": "設立登記申請書",
            "document_kind": "touki",
            "sections": list(_setsuritsu_touki_sections(entity_type)),
            "placeholders": [
                "{{SHOUGOU}}",
                "{{HONTEN_PREFECTURE}}",
                "{{HONTEN_CITY}}",
                "{{HONTEN_BANCHI}}",
                "{{DAIHYOUSHA_NAME}}",
                "{{DAIHYOUSHA_ADDRESS}}",
                "{{CAPITAL_YEN}}",
                "{{HAKKO_KABUSHIKI_SUU}}",
                "{{SETSURITSU_DATE}}",
                "{{TOUROKU_MENKYO_ZEI}}",
                "{{TOUROKU_MENKYO_ZEI_RYOSHU_BANGOU}}",
                "{{SUPERVISING_SHIHOUSHOSHI}}",
            ],
            "statutory_basis": [
                "商業登記法 §47 (登記申請の方式)",
                "会社法 §911 (株式会社の設立の登記)",
                "登録免許税法 別表第1",
            ],
            "supervising_shigyo": "司法書士",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
        {
            "artifact_type": "inkan_todoke_sho",
            "artifact_name_ja": "印鑑届出書",
            "document_kind": "todoke",
            "sections": list(_inkan_todoke_sections()),
            "placeholders": [
                "{{SHOUGOU}}",
                "{{HONTEN_PREFECTURE}}",
                "{{HONTEN_CITY}}",
                "{{DAIHYOUSHA_NAME}}",
                "{{DAIHYOUSHA_BIRTH}}",
                "{{DAIHYOUSHA_ADDRESS}}",
                "{{KAISHA_DAIHYOU_INKAN_IMPRINT}}",
                "{{DAIHYOUSHA_INKAN}}",
                "{{SUPERVISING_SHIHOUSHOSHI}}",
            ],
            "statutory_basis": [
                "商業登記規則 §9 (印鑑提出)",
                "商業登記法 §20",
            ],
            "supervising_shigyo": "司法書士",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
        {
            "artifact_type": "houjin_setsuritsu_todoke_sho",
            "artifact_name_ja": "法人設立届出書",
            "document_kind": "todoke",
            "sections": list(_houjin_setsuritsu_todoke_sections()),
            "placeholders": [
                "{{ZEIMUSHO_NAME}}",
                "{{SHOUGOU}}",
                "{{HONTEN_PREFECTURE}}",
                "{{HONTEN_CITY}}",
                "{{DAIHYOUSHA_NAME}}",
                "{{DAIHYOUSHA_ADDRESS}}",
                "{{CAPITAL_YEN}}",
                "{{JIGYOU_NENDO_START}}",
                "{{JIGYOU_NENDO_END}}",
                "{{KESSAN_TSUKI}}",
                "{{SETSURITSU_DATE}}",
                "{{JIGYOU_MOKUTEKI_1}}",
                "{{SUPERVISING_ZEIRISHI}}",
            ],
            "statutory_basis": [
                "法人税法 §148 (設立届出)",
                "国税通則法 §117",
            ],
            "supervising_shigyo": "税理士",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
        {
            "artifact_type": "kyuyo_shiharai_jimusho_todoke_sho",
            "artifact_name_ja": "給与支払事務所等の開設届出書",
            "document_kind": "todoke",
            "sections": list(_kyuyo_shiharai_jimusho_sections()),
            "placeholders": [
                "{{ZEIMUSHO_NAME}}",
                "{{SHOUGOU}}",
                "{{HONTEN_PREFECTURE}}",
                "{{HONTEN_CITY}}",
                "{{SETSURITSU_DATE}}",
                "{{GENZEN_TOKUREI_SHINSEI}}",
                "{{SUPERVISING_ZEIRISHI}}",
            ],
            "statutory_basis": ["所得税法 §230 (給与支払事務所等の届出)"],
            "supervising_shigyo": "税理士",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
        {
            "artifact_type": "shakai_hoken_shinki_tekiyou_todoke",
            "artifact_name_ja": "健康保険・厚生年金保険 新規適用届",
            "document_kind": "shinki",
            "sections": list(_shakai_hoken_shinki_sections()),
            "placeholders": [
                "{{NENKIN_JIMUSHO_NAME}}",
                "{{SHOUGOU}}",
                "{{HONTEN_PREFECTURE}}",
                "{{HONTEN_CITY}}",
                "{{DAIHYOUSHA_NAME}}",
                "{{DAIHYOUSHA_ADDRESS}}",
                "{{JIGYOU_MOKUTEKI_1}}",
                "{{HOKEN_TEKIYOU_DATE}}",
                "{{HIHOKENSHA_SUU}}",
                "{{KENKOU_HOKEN_KUMIAI}}",
                "{{SUPERVISING_SHAROUSHI}}",
            ],
            "statutory_basis": [
                "健康保険法 §48 (新規適用届)",
                "厚生年金保険法 §27",
            ],
            "supervising_shigyo": "社労士",
            "is_scaffold_only": True,
            "requires_professional_review": True,
        },
    ]


def _agent_next_actions(entity_type: str) -> list[dict[str, Any]]:
    return [
        {
            "step": "fill 50+ placeholders via N9 placeholder bank",
            "items": ["SHOUGOU", "DAIHYOUSHA_NAME", "CAPITAL_YEN", "..."],
            "rationale": (
                "Each scaffold carries unresolved {{...}} placeholders. "
                "Iterate via the N9 placeholder mapping bank "
                "(`resolve_placeholder`) before 司法書士 review."
            ),
        },
        {
            "step": "公証人 認証 of 定款 draft" if entity_type == "株式会社" else "定款 内部確定",
            "items": ["teikan_draft"],
            "rationale": (
                "株式会社 requires 公証人 認証 per 会社法 §30; 合同会社 / "
                "一般社団 / NPO can finalise 定款 internally."
            ),
        },
        {
            "step": "engage 司法書士 + 税理士 + 社労士",
            "items": [
                "setsuritsu_touki_shinsei_sho",
                "houjin_setsuritsu_todoke_sho",
                "shakai_hoken_shinki_tekiyou_todoke",
            ],
            "rationale": (
                "設立登記 (司法書士 §3 独占) / 法人設立届 (税理士 §52 監修) / "
                "新規適用届 (社労士 監修) を 3 士業 で並行進行する。"
            ),
        },
    ]


def _empty_envelope(
    *, primary_input: dict[str, Any], rationale: str, status: str = "empty"
) -> dict[str, Any]:
    return {
        "tool_name": "product_kaisha_setsuritsu_pack",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "bundle": [],
        "aggregate": {
            "artifact_count": 0,
            "completed_artifact_count": 0,
            "total_placeholders": 0,
            "statutory_fence": [],
        },
        "filing_windows": [],
        "placeholders": [],
        "agent_next_actions": [],
        "billing": {
            "unit": _BILLING_UNITS,
            "yen": _BILLING_UNITS * 3,
            "product_id": _PRODUCT_ID,
            "tier": _TIER_LETTER,
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a5_kaisha_setsuritsu",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["N1", "N4", "N9"],
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": f"{DISCLAIMER}\n{_A5_DISCLAIMER_SUFFIX}",
        "_related_shihou": [_SEGMENT, "税理士", "社労士"],
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["N1", "N4", "N9"],
            "observed_at": today_iso_utc(),
        },
    }


@mcp.tool(annotations=_READ_ONLY)
def product_kaisha_setsuritsu_pack(
    entity_type: Annotated[
        str,
        Field(
            description=("法人格. One of 株式会社 / 合同会社 / 一般社団法人 / NPO法人."),
        ),
    ],
    representative_name: Annotated[
        str,
        Field(min_length=1, max_length=64, description="代表者 氏名."),
    ],
    representative_address: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description="代表者 住所 (defaulted to 本店所在地 if same).",
        ),
    ],
    capital_yen: Annotated[
        int,
        Field(
            ge=1,
            le=10_000_000_000,
            description=("出資額 (¥). 会社法 §27 一円会社 OK; defensive ceiling at ¥10B."),
        ),
    ],
    business_purpose: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=20,
            description="事業目的. 1-20 free-text strings.",
        ),
    ],
    head_office_prefecture: Annotated[
        str,
        Field(min_length=2, max_length=8, description="本店所在地 都道府県 (e.g. 東京都)."),
    ],
    head_office_city: Annotated[
        str,
        Field(min_length=1, max_length=64, description="本店所在地 市区町村."),
    ],
    jsic_major: Annotated[
        str | None,
        Field(
            default=None,
            min_length=1,
            max_length=1,
            description=("JSIC 大分類 (A..T). Optional; drives 設立後 補助金検索 hint."),
        ),
    ] = None,
    setsuritsu_date_iso: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Planned 設立日 (ISO 8601 YYYY-MM-DD). Defaults to today. "
                "Used to compute the three statutory filing windows."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1/§3/社労士法/会社法/商業登記法]
    A5 - 会社設立一式 Pack (¥800 / req, Tier D).

    Composes the canonical 会社設立 6-scaffold bundle:
    定款 draft + 設立登記申請書 + 印鑑届出書 + 法人設立届出書 +
    給与支払事務所届出書 + 健康保険・厚生年金 新規適用届. Each scaffold
    is deterministic on the 8 inputs and ends with the cited 士業
    supervision requirement. Plus 3 statutory filing windows (法務局 +
    税務署 + 年金事務所) and 50+ canonical {{...}} placeholders for
    upstream N9 placeholder bank resolution.

    Output is scaffold-only — 定款認証 (公証人) / 設立登記 (司法書士) /
    法人設立届出書 提出 (税理士) / 新規適用届 (社労士) は out of scope;
    1 billable call counts as 267 units (267 × ¥3 = ¥801 ≈ ¥800,
    Tier D ¥100..¥1000 band). NO LLM inference — pure dict composition.
    """
    primary_input: dict[str, Any] = {
        "entity_type": entity_type,
        "representative_name": representative_name,
        "representative_address": representative_address,
        "capital_yen": capital_yen,
        "business_purpose": list(business_purpose),
        "head_office_prefecture": head_office_prefecture,
        "head_office_city": head_office_city,
        "jsic_major": jsic_major,
        "setsuritsu_date_iso": setsuritsu_date_iso,
    }

    if entity_type not in _ENTITY_TYPES:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=(
                f"entity_type={entity_type!r} not in {list(_ENTITY_TYPES)}. "
                "Valid: 株式会社 / 合同会社 / 一般社団法人 / NPO法人."
            ),
            status="invalid_argument",
        )

    cleaned_purpose = [p.strip() for p in business_purpose if p and p.strip()]
    if not cleaned_purpose:
        return _empty_envelope(
            primary_input=primary_input,
            rationale="business_purpose must contain at least one non-empty entry.",
            status="invalid_argument",
        )

    # Resolve setsuritsu_date (defaults to today UTC).
    try:
        if setsuritsu_date_iso:
            setsuritsu_date = _dt.date.fromisoformat(setsuritsu_date_iso)
        else:
            setsuritsu_date = _dt.datetime.now(_dt.UTC).date()
    except ValueError as exc:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"setsuritsu_date_iso parse error: {exc}",
            status="invalid_argument",
        )

    bundle = _compose_scaffolds(entity_type)
    windows = _filing_windows(setsuritsu_date)
    next_actions = _agent_next_actions(entity_type)

    statutory_fence = sorted(
        {
            "司法書士法 §3",
            "税理士法 §52",
            "公認会計士法 §47条の2",
            "弁護士法 §72",
            "行政書士法 §1",
            "社労士法",
            "会社法 §27",
            "会社法 §911",
            "商業登記法 §47",
            "法人税法 §148",
            "所得税法 §230",
            "健康保険法 §48",
            "厚生年金保険法 §27",
        }
    )

    aggregate = {
        "artifact_count": len(bundle),
        "completed_artifact_count": 0,  # scaffolds — none "completed" until 士業 review
        "total_placeholders": len(_PLACEHOLDERS),
        "statutory_fence": statutory_fence,
    }

    citations = []
    for scaffold in bundle:
        for basis in scaffold.get("statutory_basis", [])[:1]:
            citations.append(
                {
                    "kind": "statutory_basis",
                    "text": basis,
                    "artifact_type": scaffold["artifact_type"],
                }
            )

    return {
        "tool_name": "product_kaisha_setsuritsu_pack",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "entity_type": entity_type,
            "setsuritsu_date": setsuritsu_date.isoformat(),
            "summary": {
                "artifact_count": aggregate["artifact_count"],
                "filing_window_count": len(windows),
                "placeholder_count": len(_PLACEHOLDERS),
                "supervising_shigyo": sorted(
                    {scaffold["supervising_shigyo"] for scaffold in bundle}
                ),
            },
        },
        "bundle": bundle,
        "aggregate": aggregate,
        "filing_windows": windows,
        "placeholders": list(_PLACEHOLDERS),
        "agent_next_actions": next_actions,
        "billing": {
            "unit": _BILLING_UNITS,
            "yen": _BILLING_UNITS * 3,
            "product_id": _PRODUCT_ID,
            "tier": _TIER_LETTER,
        },
        "results": bundle,
        "total": len(bundle),
        "limit": len(bundle),
        "offset": 0,
        "citations": citations[:10],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a5_kaisha_setsuritsu",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["N1", "N4", "N9"],
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": f"{DISCLAIMER}\n{_A5_DISCLAIMER_SUFFIX}",
        "_related_shihou": [_SEGMENT, "税理士", "社労士"],
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["N1", "N4", "N9"],
            "observed_at": today_iso_utc(),
        },
    }


__all__ = [
    "product_kaisha_setsuritsu_pack",
]
