"""Real Estate V5 — 5 MCP tool stubs (P6-F W4 prep).

Each tool returns a uniform ``not_implemented_until_T+200d`` envelope.
The shape matches the existing AutonoMath tools (paginated: total /
results / data_as_of / filter_applied; one-shot: status / data_as_of
/ filter_applied) so downstream LLMs and the integration tests don't
have to special-case the preview phase.

Design discipline
-----------------
* docstrings already document the **intended** WHAT / WHEN / WHEN NOT
  / RETURNS, so partners reading the OpenAPI export at T+150d see the
  contract that will ship at T+200d. The body just short-circuits.
* every stub is annotated ``@mcp.tool(annotations=_READ_ONLY)`` and
  accepts the **final** parameter list — wiring real SQL later is a
  body-only edit. No signature changes after T+200d.
* import is module-level (no lazy import) because registration is the
  whole point of the file. Circular-import safety is guaranteed by
  ``server.py`` deferring the ``import jpintel_mcp.mcp.real_estate_tools``
  to the bottom of the module after ``mcp = FastMCP(...)``.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

_NOT_IMPLEMENTED_STATUS = "not_implemented_until_T+200d"
_LAUNCH_TARGET = "2026-11-22"  # T+200d from 2026-04-25 scaffolding


def _stub_envelope(
    *,
    paginated: bool,
    filter_applied: dict[str, Any],
) -> dict[str, Any]:
    """Build the canonical preview envelope for a Real Estate V5 stub.

    Both shapes carry ``status`` + ``launch_target`` + ``data_as_of``
    + ``filter_applied`` so LLM clients see a stable, machine-readable
    "not ready yet" signal instead of an empty result that looks like
    a no-match.
    """
    today = datetime.date.today().isoformat()
    base: dict[str, Any] = {
        "status": _NOT_IMPLEMENTED_STATUS,
        "launch_target": _LAUNCH_TARGET,
        "data_as_of": today,
        "filter_applied": filter_applied,
        "hint": (
            "Real Estate V5 (migration 042) ships at T+200d "
            f"(target {_LAUNCH_TARGET}). For now, fall back to "
            "search_programs / search_loan_programs / search_enforcement_cases "
            "with prefecture + property keyword filters."
        ),
    }
    if paginated:
        base["total"] = 0
        base["results"] = []
    return base


# ---------------------------------------------------------------------------
# 1. search_real_estate_programs — FTS5 + program_kind + law_basis filter
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def search_real_estate_programs(
    q: Annotated[
        str | None,
        Field(
            description="自由文検索 (FTS5)。建築基準法 / 都市計画法 / 借地借家法 関連 program に絞る前段。"
        ),
    ] = None,
    program_kind: Annotated[
        str | None,
        Field(
            description="program_kind enum: subsidy / tax_incentive / loan / certification / zoning。"
        ),
    ] = None,
    law_basis: Annotated[
        str | None,
        Field(
            description="根拠法名 (例: 建築基準法 / 都市計画法 / 不動産登記法 / 借地借家法 / 建物区分所有法)。"
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Field(description="都道府県 (例: '東京都')。national / 都道府県 / 市町村 横断検索。"),
    ] = None,
    property_type_target: Annotated[
        str | None,
        Field(description="対象 property type (商業 / 住宅 / 工場 / 農地 / 林地 等)。"),
    ] = None,
    tier: Annotated[
        str | None,
        Field(
            description="tier enum: S / A / B / C (X excluded)。default 全 tier (excluded=0 のみ)。"
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="最大返却件数 (default 20)。")] = 20,
    offset: Annotated[int, Field(ge=0, description="ページング offset (default 0)。")] = 0,
) -> dict[str, Any]:
    """[REAL-ESTATE] 建築基準法 / 都市計画法 / 借地借家法 関連 program 検索 — FTS5 + program_kind + law_basis filter。

    WHAT (T+200d 後): ``real_estate_programs`` (migration 042) を
    FTS5 + program_kind + law_basis + prefecture + property_type_target
    で絞り込んで paginated 返却。

    WHEN:
      - 「東京都の耐震改修補助は?」(prefecture + program_kind=subsidy)
      - 「建築基準法に紐づく税制優遇」(law_basis + program_kind=tax_incentive)
      - 「商業ビル向けの認定制度を一覧」(property_type_target + program_kind=certification)

    WHEN NOT:
      - 用途地域 / 防火地域 詳細 → get_zoning_overlay
      - 不動産業者の処分歴 → search_real_estate_compliance
      - 1-shot DD レポート → dd_property_am

    RETURNS (envelope):
      {
        status: "not_implemented_until_T+200d",
        launch_target: "2026-11-22",
        total: int, results: [...],     # paginated
        data_as_of: str, filter_applied: {...}, hint: str
      }

    PREVIEW PHASE: 本 stub は launch_target 前は ``total=0`` の preview
    envelope を返す。本実装は migration 042 (real_estate_programs +
    zoning_overlays) を活用し T+200d 直前に SQL 化する。
    """
    return _stub_envelope(
        paginated=True,
        filter_applied={
            "q": q,
            "program_kind": program_kind,
            "law_basis": law_basis,
            "prefecture": prefecture,
            "property_type_target": property_type_target,
            "tier": tier,
            "limit": limit,
            "offset": offset,
        },
    )


# ---------------------------------------------------------------------------
# 2. get_zoning_overlay — (prefecture, city, district) lookup
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def get_zoning_overlay(
    prefecture: Annotated[
        str,
        Field(description="都道府県 (必須、例: '東京都' / '神奈川県')。"),
    ],
    city: Annotated[
        str,
        Field(description="市区町村 (必須、例: '千代田区' / '横浜市西区')。"),
    ],
    district: Annotated[
        str | None,
        Field(description="町丁目 / 字 (任意、例: '丸の内一丁目')。null で市区町村全域。"),
    ] = None,
    zoning_type: Annotated[
        str | None,
        Field(
            description=(
                "zoning_type enum: 用途地域 / 防火地域 / 準防火地域 / "
                "高度地区 / 景観地区 / 特別用途地区 / その他。"
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """[REAL-ESTATE] 用途地域 / 防火地域 / 高度地区 詳細 lookup — (prefecture, city, district) で zoning_overlays から取得。

    WHAT (T+200d 後): ``zoning_overlays`` (migration 042) から
    (prefecture, city, district) に該当する overlay を全 zoning_type
    分まとめて返す。``restrictions_json`` (建蔽率 / 容積率 /
    高さ制限 / 日影規制) はパース済み dict として展開。

    WHEN:
      - 「丸の内一丁目の用途地域は?」
      - 「横浜市西区の防火指定」
      - 「千代田区の高度地区 m 上限」

    WHEN NOT:
      - 建蔽率 / 容積率 vs 計画建物 → cross_check_zoning
      - 補助金 / 認定検索 → search_real_estate_programs
      - 全国まとめ → 該当する一覧 API は提供しない (zoning は spatial、bulk 配信は license 別件)

    RETURNS (envelope):
      {
        status: "not_implemented_until_T+200d",
        launch_target: "2026-11-22",
        data_as_of: str,
        filter_applied: {prefecture, city, district, zoning_type},
        hint: str
      }

    PREVIEW PHASE: stub は launch_target 前は overlay を返さない。
    本実装は migration 042 + W3 ingest 完了後に SQL 化する。
    """
    return _stub_envelope(
        paginated=False,
        filter_applied={
            "prefecture": prefecture,
            "city": city,
            "district": district,
            "zoning_type": zoning_type,
        },
    )


# ---------------------------------------------------------------------------
# 3. search_real_estate_compliance — 建設業法 + 宅建業法 + 借地借家法 横断
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def search_real_estate_compliance(
    q: Annotated[
        str | None,
        Field(description="自由文検索 (FTS5)。法人名 / 違反内容 / 処分種別 等。"),
    ] = None,
    law_basis: Annotated[
        str | None,
        Field(description="根拠法 (建設業法 / 宅地建物取引業法 / 借地借家法 / 建築士法 等)。"),
    ] = None,
    prefecture: Annotated[
        str | None,
        Field(description="処分庁所在 都道府県 (例: '大阪府')。"),
    ] = None,
    corporate_number: Annotated[
        str | None,
        Field(
            description="法人番号 (13桁) で被処分業者を絞り込み。null で全業者。",
            min_length=13,
            max_length=13,
        ),
    ] = None,
    days_back: Annotated[
        int,
        Field(ge=1, le=3650, description="今日から N 日前までの処分のみ (default 1825 = 5年)。"),
    ] = 1825,
    limit: Annotated[int, Field(ge=1, le=100, description="最大返却件数 (default 20)。")] = 20,
    offset: Annotated[int, Field(ge=0, description="ページング offset (default 0)。")] = 0,
) -> dict[str, Any]:
    """[REAL-ESTATE] 建設業法 + 宅建業法 + 借地借家法 横断 compliance 検索 — 行政処分歴・指導歴。

    WHAT (T+200d 後): ``enforcement_cases`` (jpintel.db) +
    ``real_estate_programs`` (migration 042) を JOIN し、不動産系
    根拠法 (建設業法 / 宅建業法 / 借地借家法 / 建築士法 等) に
    紐づく行政処分を paginated 返却。法人番号 (13桁) でも検索可能。

    WHEN:
      - 「過去 5 年で建設業法違反の関東勢を一覧」
      - 「法人番号 9XXX の宅建業者の処分歴」
      - 「借地借家法トラブルの判例近傍」(× 訴訟は court_decisions)

    WHEN NOT:
      - 民事判例 → search_court_decisions (existing)
      - 補助金検索 → search_real_estate_programs
      - 不動産 DD pack → dd_property_am

    RETURNS (envelope): paginated (total / results / filter_applied / hint)。
    PREVIEW PHASE: stub は launch_target 前は ``total=0`` を返す。
    """
    return _stub_envelope(
        paginated=True,
        filter_applied={
            "q": q,
            "law_basis": law_basis,
            "prefecture": prefecture,
            "corporate_number": corporate_number,
            "days_back": days_back,
            "limit": limit,
            "offset": offset,
        },
    )


# ---------------------------------------------------------------------------
# 4. dd_property_am — 不動産 DD (zoning + 補助 + 法令 + 処分歴) 1-shot
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def dd_property_am(
    prefecture: Annotated[
        str,
        Field(description="物件所在 都道府県 (必須)。"),
    ],
    city: Annotated[
        str,
        Field(description="物件所在 市区町村 (必須)。"),
    ],
    district: Annotated[
        str | None,
        Field(description="町丁目 (任意)。null で市区町村全域 zoning を集約。"),
    ] = None,
    owner_corporate_number: Annotated[
        str | None,
        Field(
            description="所有者 法人番号 (13桁) — 行政処分歴を同梱する場合に指定。",
            min_length=13,
            max_length=13,
        ),
    ] = None,
    property_type: Annotated[
        str | None,
        Field(description="property_type_target enum (商業 / 住宅 / 工場 / 農地 / 林地 等)。"),
    ] = None,
) -> dict[str, Any]:
    """[REAL-ESTATE] 不動産 due diligence — 所有者法人番号 → 行政処分歴 + zoning + 補助金 + 法令 を 1 call で。

    WHAT (T+200d 後): 1 つの物件 (prefecture, city, district) について
    以下を 1 envelope で返す:
      - zoning_overlays 全 type (用途地域 / 防火地域 / 高度地区 etc.)
      - 適用可能性のある real_estate_programs (補助金 / 税制優遇 / 認定)
      - 関連 laws (建築基準法 / 都市計画法 / 借地借家法 等の代表条文)
      - 所有者法人番号 → 行政処分歴 (建設業法 / 宅建業法)
      - 国税庁適格事業者登録 status

    WHEN:
      - 物件 acquisition の DD (買収前 1-shot scan)
      - 仲介業者の事前確認
      - 不動産 SaaS API consumer の summary endpoint

    WHEN NOT:
      - 個別 zoning だけ → get_zoning_overlay (lighter)
      - 個別 program 検索 → search_real_estate_programs
      - 投資利回り試算 → 推論は顧客側 (我々は事実 API のみ)

    RETURNS (one-shot envelope):
      {
        status: "not_implemented_until_T+200d",
        launch_target: "2026-11-22",
        data_as_of: str,
        filter_applied: {prefecture, city, district, owner_corporate_number, property_type},
        hint: str
      }

    PREVIEW PHASE: stub は launch_target 前は status 通知のみ。
    本実装は migration 042 + autonomath.db owner DD path 確定後。
    """
    return _stub_envelope(
        paginated=False,
        filter_applied={
            "prefecture": prefecture,
            "city": city,
            "district": district,
            "owner_corporate_number": owner_corporate_number,
            "property_type": property_type,
        },
    )


# ---------------------------------------------------------------------------
# 5. cross_check_zoning — 建蔽率 / 容積率 vs 計画建物 verification
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def cross_check_zoning(
    prefecture: Annotated[
        str,
        Field(description="都道府県 (必須)。"),
    ],
    city: Annotated[
        str,
        Field(description="市区町村 (必須)。"),
    ],
    district: Annotated[
        str | None,
        Field(description="町丁目 (任意)。null で市区町村集約 (overlay 包含 union)。"),
    ] = None,
    planned_kenpei_pct: Annotated[
        float | None,
        Field(ge=0, le=100, description="計画建物の建蔽率 (%) — overlay 上限と比較。"),
    ] = None,
    planned_yoseki_pct: Annotated[
        float | None,
        Field(ge=0, le=2000, description="計画建物の容積率 (%) — overlay 上限と比較。"),
    ] = None,
    planned_height_m: Annotated[
        float | None,
        Field(ge=0, le=600, description="計画建物の高さ (m) — 高度地区上限と比較。"),
    ] = None,
) -> dict[str, Any]:
    """[REAL-ESTATE] 建蔽率 / 容積率 / 高さ vs 計画建物 verification — 複数 overlay を 1 call で重ね合わせ。

    WHAT (T+200d 後): (prefecture, city, district) の zoning_overlays
    全 type を取り出し、``planned_kenpei_pct`` / ``planned_yoseki_pct``
    / ``planned_height_m`` に対する pass / fail を overlay ごとに
    判定。``restrictions_json`` を 1 envelope に union して fail 理由を
    一覧化する。

    WHEN:
      - 「計画建物 建蔽率 70%、容積率 400%、高さ 31m は通る?」
      - 設計事務所の事前 sanity check
      - 不動産 SaaS の plan-feasibility endpoint

    WHEN NOT:
      - overlay 単独閲覧 → get_zoning_overlay (lighter, no plan params)
      - 補助金検索 → search_real_estate_programs
      - 確認申請の代行 → 士業独占。我々は scope 外

    RETURNS (one-shot envelope):
      {
        status: "not_implemented_until_T+200d",
        launch_target: "2026-11-22",
        data_as_of: str,
        filter_applied: {prefecture, city, district, planned_kenpei_pct,
                         planned_yoseki_pct, planned_height_m},
        hint: str
      }

    PREVIEW PHASE: stub は launch_target 前は判定を返さない。
    本実装は migration 042 + W3 ingest (1,000 overlay rows) 完了後。
    """
    return _stub_envelope(
        paginated=False,
        filter_applied={
            "prefecture": prefecture,
            "city": city,
            "district": district,
            "planned_kenpei_pct": planned_kenpei_pct,
            "planned_yoseki_pct": planned_yoseki_pct,
            "planned_height_m": planned_height_m,
        },
    )
