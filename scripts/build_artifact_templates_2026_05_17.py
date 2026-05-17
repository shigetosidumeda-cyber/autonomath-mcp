#!/usr/bin/env python3
"""Generate 50 artifact template YAML files (5 士業 × 10 種類).

Lane N1 — 実務成果物テンプレート bank construction.

Output:
    data/artifact_templates/{segment}/{artifact_type}.yaml

Each YAML file carries:
  - metadata (authority, sensitive_act, scaffold_only, requires_professional_review)
  - sections[] (skeleton structure)
  - placeholders[] (typed, with mcp_query_spec)
  - mcp_query_bindings (placeholder -> MCP tool + args)

The templates are **scaffolds** — they cite authority and structure
correctly, but they MUST be reviewed by the corresponding 士業 before
submission. The mcp_query_bindings reference EXISTING jpcite MCP tools.

NO LLM calls anywhere; this script is pure file emission.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "data" / "artifact_templates"


# ---------------------------------------------------------------------------
# Shared placeholder shapes that bind to existing jpcite MCP tools.
# ---------------------------------------------------------------------------
#
# These MCP tools are confirmed to exist (verified against
# src/jpintel_mcp/mcp/autonomath_tools/):
#   - get_houjin_360_am          (corporate_layer_tools.py)
#   - search_invoice_by_houjin_partial (corporate_layer_tools.py)
#   - get_am_tax_rule            (tax_rule_tool.py)
#   - get_law_article_am         (autonomath_wrappers.py)
#   - search_programs            (jpintel.db side, programs)
#   - get_annotations            (annotation_tools.py)
#   - search_acceptance_stats_am (tools.py)
#   - list_open_programs         (tools.py)
#   - check_funding_stack_am     (funding_stack_tools.py)
#   - enum_values_am             (tools.py)
#   - get_provenance             (annotation_tools.py)
#
# Placeholders that have no corresponding MCP source (e.g. raw user input
# like 申請日 / 担当者氏名) carry mcp_query_spec = null and rely on the
# agent / caller filling them from the session profile.


def _ph(
    key: str,
    type_: str,
    required: bool = True,
    source: str = "session",
    mcp_query_spec: dict[str, Any] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Build a placeholder spec."""
    return {
        "key": key,
        "type": type_,
        "required": required,
        "source": source,
        "mcp_query_spec": mcp_query_spec,
        "description": description,
    }


def _binding(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build an MCP query binding spec."""
    return {"tool": tool, "args": args}


# ---------------------------------------------------------------------------
# Common placeholders used across many templates.
# ---------------------------------------------------------------------------

PH_COMPANY_NAME = _ph(
    "COMPANY_NAME",
    "string",
    source="mcp",
    mcp_query_spec=_binding(
        "get_houjin_360_am",
        {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "name"},
    ),
    description="法人名 (houjin_bangou から resolve)",
)

PH_HOUJIN_BANGOU = _ph(
    "HOUJIN_BANGOU",
    "string",
    source="session",
    description="法人番号 (13 桁)",
)

PH_REPRESENTATIVE = _ph(
    "REPRESENTATIVE",
    "string",
    source="mcp",
    mcp_query_spec=_binding(
        "get_houjin_360_am",
        {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "representative"},
    ),
    description="代表者氏名",
)

PH_ADDRESS = _ph(
    "ADDRESS",
    "string",
    source="mcp",
    mcp_query_spec=_binding(
        "get_houjin_360_am",
        {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "address"},
    ),
    description="本店所在地",
)

PH_FISCAL_YEAR = _ph(
    "FISCAL_YEAR", "string", source="session", description="会計年度 (例: 2026-04-01〜2027-03-31)"
)
PH_AGREEMENT_DATE = _ph("AGREEMENT_DATE", "date", source="session", description="作成日")


# =============================================================================
# 税理士 10 templates
# =============================================================================

ZEIRISHI = [
    {
        "artifact_type": "gessji_shiwake",
        "artifact_name_ja": "月次仕訳",
        "authority": "法人税法 §22 + 会社法 §432",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 月次仕訳帳", "対象月: {{TARGET_MONTH}}"],
            },
            {"id": "journal", "title": "仕訳明細", "paragraphs": ["勘定科目 / 借方 / 貸方 / 摘要"]},
            {
                "id": "footer",
                "title": "署名欄",
                "paragraphs": ["作成: {{PREPARER_NAME}} / 確認: 税理士 {{ZEIRISHI_NAME}}"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("TARGET_MONTH", "string", description="対象月 (YYYY-MM)"),
            _ph("PREPARER_NAME", "string", description="作成者氏名"),
            _ph("ZEIRISHI_NAME", "string", description="担当税理士氏名"),
        ],
    },
    {
        "artifact_type": "nenmatsu_chosei",
        "artifact_name_ja": "年末調整書",
        "authority": "所得税法 §190 + 同 §194-198",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 給与所得者の年末調整"],
            },
            {
                "id": "employee_info",
                "title": "従業員情報",
                "paragraphs": ["氏名 / マイナンバー / 扶養 / 保険料控除"],
            },
            {
                "id": "tax_calc",
                "title": "税額計算",
                "paragraphs": ["年税額 - 既徴収税額 = 差引調整額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("ANNUAL_INCOME", "money_yen", description="年間給与"),
            _ph(
                "LEGAL_BASIS_INCOME_TAX_190",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "所得税法", "article": "190"}
                ),
                description="所得税法 §190 条文",
            ),
        ],
    },
    {
        "artifact_type": "houjinzei_shinkoku",
        "artifact_name_ja": "法人税申告書",
        "authority": "法人税法 §74 + 別表",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "cover",
                "title": "別表1",
                "paragraphs": ["{{COMPANY_NAME}} / 法人番号 {{HOUJIN_BANGOU}} / {{FISCAL_YEAR}}"],
            },
            {
                "id": "betsu4",
                "title": "別表4 (所得計算)",
                "paragraphs": ["当期純利益 + 加算 - 減算 = 課税所得"],
            },
            {
                "id": "betsu5",
                "title": "別表5 (利益積立金)",
                "paragraphs": ["期首 + 当期増 - 当期減 = 期末"],
            },
            {"id": "tax_calc", "title": "税額計算", "paragraphs": ["課税所得 × 税率 = 法人税額"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_REPRESENTATIVE,
            PH_FISCAL_YEAR,
            _ph("TAXABLE_INCOME", "money_yen", description="課税所得金額"),
            _ph(
                "TAX_RULE_HOJINZEI",
                "rule_ref",
                source="mcp",
                mcp_query_spec=_binding("get_am_tax_rule", {"rule_id": "houjinzei_main_rate"}),
                description="法人税本則税率",
            ),
        ],
    },
    {
        "artifact_type": "shouhizei_shinkoku",
        "artifact_name_ja": "消費税申告書",
        "authority": "消費税法 §45",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "cover",
                "title": "申告書第一表",
                "paragraphs": ["{{COMPANY_NAME}} / {{FISCAL_YEAR}}"],
            },
            {
                "id": "calc",
                "title": "課税標準額計算",
                "paragraphs": ["課税売上 × 税率 - 仕入税額控除"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph("TAXABLE_SALES", "money_yen", description="課税売上高"),
            _ph(
                "INVOICE_REGISTRATION_NO",
                "string",
                source="mcp",
                mcp_query_spec=_binding(
                    "search_invoice_by_houjin_partial",
                    {"houjin_bangou": "{{HOUJIN_BANGOU}}"},
                ),
                description="適格請求書発行事業者登録番号",
            ),
            _ph(
                "TAX_RULE_SHOUHIZEI",
                "rule_ref",
                source="mcp",
                mcp_query_spec=_binding("get_am_tax_rule", {"rule_id": "shouhizei_standard_rate"}),
                description="消費税標準税率",
            ),
        ],
    },
    {
        "artifact_type": "gensen_choushuubo",
        "artifact_name_ja": "源泉徴収簿",
        "authority": "所得税法 §183 + 同施行規則 §76",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 給与所得・退職所得に対する源泉徴収簿"],
            },
            {
                "id": "monthly",
                "title": "月別明細",
                "paragraphs": ["支給日 / 総支給額 / 社保料 / 課税対象 / 源泉税額"],
            },
            {"id": "annual", "title": "年計", "paragraphs": ["年税額 / 還付・追徴額"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("EMPLOYEE_MYNUMBER", "string", description="マイナンバー (12桁、要保護)"),
            _ph("FISCAL_YEAR", "string", description="対象年"),
        ],
    },
    {
        "artifact_type": "kyuyo_keisan",
        "artifact_name_ja": "給与計算",
        "authority": "労基法 §24 + 所得税法 §183",
        "sensitive_act": "税理士法 §52 + 社労士法 §27",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} {{PAY_PERIOD}} 給与明細"],
            },
            {
                "id": "earnings",
                "title": "支給",
                "paragraphs": ["基本給 / 残業手当 / 通勤費 / その他手当"],
            },
            {
                "id": "deductions",
                "title": "控除",
                "paragraphs": ["健康保険 / 厚生年金 / 雇用保険 / 所得税 / 住民税"],
            },
            {"id": "net", "title": "差引支給額", "paragraphs": ["総支給 - 総控除 = 差引支給"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("PAY_PERIOD", "string", description="給与計算期間 (YYYY-MM)"),
            _ph("GROSS_PAY", "money_yen", description="総支給額"),
            _ph(
                "SHAKAI_HOKEN_RATE",
                "rule_ref",
                source="mcp",
                mcp_query_spec=_binding("get_am_tax_rule", {"rule_id": "shakai_hoken_rates"}),
                description="社会保険料率",
            ),
        ],
    },
    {
        "artifact_type": "shoukyaku_shisan_shinkoku",
        "artifact_name_ja": "償却資産申告書",
        "authority": "地方税法 §383",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "cover",
                "title": "申告書",
                "paragraphs": ["{{COMPANY_NAME}} / 法人番号 {{HOUJIN_BANGOU}} / 賦課期日 1/1"],
            },
            {
                "id": "asset_list",
                "title": "資産明細",
                "paragraphs": ["取得年月 / 取得価額 / 耐用年数 / 評価額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_ADDRESS,
            _ph("MUNICIPALITY", "string", description="提出先 (市町村)"),
            _ph("ASSESSMENT_YEAR", "string", description="賦課年度 (YYYY)"),
        ],
    },
    {
        "artifact_type": "inshi_zei_shinkoku",
        "artifact_name_ja": "印紙税申告書",
        "authority": "印紙税法 §11 + 別表第一",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "cover",
                "title": "印紙税納税申告書 (書式表示用)",
                "paragraphs": ["{{COMPANY_NAME}}"],
            },
            {
                "id": "document_list",
                "title": "課税文書明細",
                "paragraphs": ["文書種類 / 金額 / 通数 / 税額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("DOCUMENT_TYPE", "enum", description="課税文書の種類 (1号〜20号)"),
            _ph("CONTRACT_AMOUNT", "money_yen", description="契約金額"),
            _ph(
                "INSHI_TAX_TABLE",
                "rule_ref",
                source="mcp",
                mcp_query_spec=_binding("get_am_tax_rule", {"rule_id": "inshi_zei_table_1"}),
                description="印紙税法 別表第一",
            ),
        ],
    },
    {
        "artifact_type": "kifukin_koujo_shoumei",
        "artifact_name_ja": "寄附金控除証明書",
        "authority": "所得税法 §78 + 措置法 §41の18の2",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "header",
                "title": "証明書ヘッダ",
                "paragraphs": ["{{ISSUER_NAME}} 寄附金受領証明書"],
            },
            {"id": "donor_info", "title": "寄附者情報", "paragraphs": ["氏名 / 住所"]},
            {
                "id": "donation",
                "title": "寄附内容",
                "paragraphs": ["寄附年月日 / 寄附金額 / 寄附目的"],
            },
        ],
        "placeholders": [
            _ph("ISSUER_NAME", "string", description="発行団体名"),
            _ph("DONOR_NAME", "string", description="寄附者氏名"),
            _ph("DONATION_AMOUNT", "money_yen", description="寄附金額"),
            _ph("DONATION_DATE", "date", description="寄附年月日"),
            _ph(
                "LEGAL_BASIS_INCOME_TAX_78",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "所得税法", "article": "78"}
                ),
                description="所得税法 §78 条文",
            ),
        ],
    },
    {
        "artifact_type": "kaihaigyou_todoke",
        "artifact_name_ja": "個人事業 開廃業届出書",
        "authority": "所得税法 §229",
        "sensitive_act": "税理士法 §52",
        "sections": [
            {
                "id": "header",
                "title": "個人事業の開業・廃業等届出書",
                "paragraphs": ["提出先: {{TAX_OFFICE}}"],
            },
            {"id": "person", "title": "届出者情報", "paragraphs": ["氏名 / 住所 / マイナンバー"]},
            {"id": "business", "title": "事業内容", "paragraphs": ["業種 / 屋号 / 開業日"]},
        ],
        "placeholders": [
            _ph("PERSON_NAME", "string", description="届出者氏名"),
            _ph("ADDRESS", "string", description="住所"),
            _ph("TAX_OFFICE", "string", description="所轄税務署名"),
            _ph("BUSINESS_TYPE", "string", description="業種"),
            _ph("OPENING_DATE", "date", description="開業 (or 廃業) 年月日"),
        ],
    },
]


# =============================================================================
# 会計士 10 templates
# =============================================================================

KAIKEISHI = [
    {
        "artifact_type": "kansa_chosho",
        "artifact_name_ja": "監査調書",
        "authority": "公認会計士法 §2 + 監査基準 第三 実施基準",
        "sensitive_act": "公認会計士法 §47条の2 + §1",
        "sections": [
            {
                "id": "header",
                "title": "監査調書ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} {{FISCAL_YEAR}} 監査調書"],
            },
            {"id": "scope", "title": "監査範囲", "paragraphs": ["対象勘定科目 / 監査手続"]},
            {"id": "findings", "title": "発見事項", "paragraphs": ["手続 / 結果 / 結論"]},
            {
                "id": "signoff",
                "title": "署名",
                "paragraphs": ["担当: {{CPA_NAME}} / 関与社員: {{PARTNER_NAME}}"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph("CPA_NAME", "string", description="担当公認会計士氏名"),
            _ph("PARTNER_NAME", "string", description="関与社員氏名"),
        ],
    },
    {
        "artifact_type": "naibu_tousei_houkoku",
        "artifact_name_ja": "内部統制報告書",
        "authority": "金商法 §24の4の4 + 内部統制府令",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 内部統制報告書 ({{FISCAL_YEAR}})"],
            },
            {
                "id": "scope",
                "title": "評価範囲",
                "paragraphs": ["全社統制 / 業務プロセス統制 / IT 統制"],
            },
            {
                "id": "conclusion",
                "title": "結論",
                "paragraphs": ["有効である / 開示すべき重要な不備あり"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_REPRESENTATIVE,
            PH_FISCAL_YEAR,
            _ph("ASSESSMENT_RESULT", "enum", description="有効 / 開示すべき重要な不備あり"),
        ],
    },
    {
        "artifact_type": "kansa_iken",
        "artifact_name_ja": "監査意見書",
        "authority": "金商法 §193の2 + 監査基準",
        "sensitive_act": "公認会計士法 §47条の2 + §1",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["独立監査人の監査報告書"]},
            {
                "id": "opinion",
                "title": "監査意見",
                "paragraphs": ["無限定適正 / 限定付適正 / 不適正 / 意見不表明"],
            },
            {"id": "basis", "title": "監査意見の根拠", "paragraphs": ["監査基準に準拠"]},
            {"id": "responsibility", "title": "経営者・監査役・監査人の責任", "paragraphs": [""]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph(
                "OPINION_TYPE", "enum", description="無限定適正 / 限定付適正 / 不適正 / 意見不表明"
            ),
            _ph("CPA_FIRM_NAME", "string", description="監査法人名"),
            _ph("RESPONSIBLE_PARTNER", "string", description="代表社員 公認会計士"),
        ],
    },
    {
        "artifact_type": "tanaoroshi_hyouka",
        "artifact_name_ja": "棚卸資産評価",
        "authority": "企業会計基準第9号 棚卸資産の評価に関する会計基準",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 棚卸資産評価明細"],
            },
            {
                "id": "method",
                "title": "評価方法",
                "paragraphs": ["原価法 (個別法 / 先入先出 / 移動平均 / 売価還元) + 低価法"],
            },
            {
                "id": "detail",
                "title": "明細",
                "paragraphs": ["品目 / 数量 / 取得原価 / 正味売却価額 / 評価額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph(
                "INVENTORY_METHOD",
                "enum",
                description="評価方法 (個別 / 先入先出 / 移動平均 / 売価還元)",
            ),
        ],
    },
    {
        "artifact_type": "taishoku_kyufu_keisan",
        "artifact_name_ja": "退職給付計算書",
        "authority": "企業会計基準第26号 退職給付に関する会計基準",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 退職給付債務計算書 ({{FISCAL_YEAR}})"],
            },
            {
                "id": "assumptions",
                "title": "数理計算上の仮定",
                "paragraphs": ["割引率 / 退職率 / 昇給率"],
            },
            {
                "id": "obligation",
                "title": "退職給付債務",
                "paragraphs": ["期首 + 勤務費用 + 利息費用 - 給付支払額 = 期末"],
            },
            {
                "id": "asset",
                "title": "年金資産",
                "paragraphs": ["期首 + 期待運用収益 + 拠出 - 給付 = 期末"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph("DISCOUNT_RATE", "decimal", description="割引率 (年率%)"),
        ],
    },
    {
        "artifact_type": "lease_torihiki",
        "artifact_name_ja": "リース取引",
        "authority": "企業会計基準第13号 リース取引に関する会計基準",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} リース資産・債務明細"],
            },
            {
                "id": "classification",
                "title": "分類",
                "paragraphs": ["ファイナンス / オペレーティング判定"],
            },
            {
                "id": "schedule",
                "title": "支払スケジュール",
                "paragraphs": ["期 / 元本 / 利息 / 残高"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("LEASE_SUBJECT", "string", description="リース物件"),
            _ph("LEASE_TERM_MONTHS", "integer", description="リース期間 (月)"),
            _ph("MONTHLY_PAYMENT", "money_yen", description="月額リース料"),
        ],
    },
    {
        "artifact_type": "kinyu_shouhin_hyouka",
        "artifact_name_ja": "金融商品評価",
        "authority": "企業会計基準第10号 金融商品に関する会計基準",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 金融商品時価評価明細"],
            },
            {
                "id": "classification",
                "title": "分類",
                "paragraphs": ["売買目的有価証券 / 満期保有 / その他有価証券"],
            },
            {
                "id": "valuation",
                "title": "評価",
                "paragraphs": ["銘柄 / 取得原価 / 期末時価 / 評価差額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_FISCAL_YEAR,
            _ph("INSTRUMENT_TYPE", "enum", description="売買目的 / 満期保有 / その他"),
        ],
    },
    {
        "artifact_type": "renketsu_tetsuduki",
        "artifact_name_ja": "連結手続書",
        "authority": "連結財務諸表規則 + 企業会計基準第22号",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} 連結手続書 ({{FISCAL_YEAR}})"],
            },
            {
                "id": "scope",
                "title": "連結範囲",
                "paragraphs": ["親会社 / 子会社 / 関連会社 (持分法)"],
            },
            {
                "id": "elimination",
                "title": "連結消去仕訳",
                "paragraphs": ["投資と資本の相殺 / 債権債務消去 / 内部利益消去"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_FISCAL_YEAR,
            _ph("SUBSIDIARY_COUNT", "integer", description="連結子会社数"),
        ],
    },
    {
        "artifact_type": "segment_jouhou",
        "artifact_name_ja": "セグメント情報",
        "authority": "企業会計基準第17号 セグメント情報等の開示",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["{{COMPANY_NAME}} セグメント情報 ({{FISCAL_YEAR}})"],
            },
            {
                "id": "segments",
                "title": "報告セグメント",
                "paragraphs": ["セグメント名 / 売上高 / 利益 / 資産"],
            },
            {
                "id": "reconciliation",
                "title": "調整額",
                "paragraphs": ["セグメント合計 → 連結 P/L への調整"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_FISCAL_YEAR,
            _ph("SEGMENT_NAMES", "array_string", description="報告セグメント名一覧"),
        ],
    },
    {
        "artifact_type": "kaikei_houshin_chuuki",
        "artifact_name_ja": "会計方針注記",
        "authority": "会社法 §435 + 計算書類規則 §103",
        "sensitive_act": "公認会計士法 §47条の2",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["重要な会計方針"]},
            {
                "id": "policies",
                "title": "方針",
                "paragraphs": ["有価証券 / 棚卸資産 / 固定資産 / 引当金 / 収益認識"],
            },
            {
                "id": "changes",
                "title": "会計方針の変更",
                "paragraphs": ["変更内容 / 理由 / 影響額"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_FISCAL_YEAR,
            _ph("POLICY_CHANGES_THIS_YEAR", "boolean", description="当期に方針変更があるか"),
        ],
    },
]


# =============================================================================
# 行政書士 10 templates
# =============================================================================

GYOUSEI = [
    {
        "artifact_type": "hojokin_shinsei",
        "artifact_name_ja": "補助金申請書",
        "authority": "補助金等適正化法 §5 + 各補助金実施要領",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {
                "id": "cover",
                "title": "申請書表紙",
                "paragraphs": ["{{PROGRAM_NAME}} 補助金交付申請書"],
            },
            {
                "id": "applicant",
                "title": "申請者情報",
                "paragraphs": ["法人名 / 法人番号 / 代表者 / 住所"],
            },
            {"id": "project", "title": "事業計画", "paragraphs": ["目的 / 内容 / 期間 / 経費明細"]},
            {"id": "budget", "title": "経費明細", "paragraphs": ["費目 / 金額 / 補助対象有無"]},
            {"id": "signoff", "title": "誓約", "paragraphs": ["反社チェック / 二重申請なし"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_REPRESENTATIVE,
            PH_ADDRESS,
            _ph(
                "PROGRAM_NAME",
                "string",
                source="mcp",
                mcp_query_spec=_binding("search_programs", {"q": "{{KEYWORD}}", "limit": 1}),
                description="補助金名",
            ),
            _ph(
                "PROGRAM_ID",
                "string",
                source="mcp",
                mcp_query_spec=_binding("search_programs", {"q": "{{KEYWORD}}", "limit": 1}),
                description="補助金プログラム ID (jpcite)",
            ),
            _ph("REQUESTED_AMOUNT", "money_yen", description="申請額"),
            _ph(
                "FUNDING_STACK_CHECK",
                "validation",
                source="mcp",
                mcp_query_spec=_binding(
                    "check_funding_stack_am",
                    {"program_ids": ["{{PROGRAM_ID}}"], "houjin_bangou": "{{HOUJIN_BANGOU}}"},
                ),
                description="二重申請 / 併用可否チェック",
            ),
        ],
    },
    {
        "artifact_type": "kyoninka_shinsei",
        "artifact_name_ja": "許認可申請書",
        "authority": "各業法 (建設業法 / 古物営業法 / 食品衛生法 等)",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {"id": "cover", "title": "申請書表紙", "paragraphs": ["{{LICENSE_TYPE}} 許可申請書"]},
            {"id": "applicant", "title": "申請者情報", "paragraphs": ["法人 / 個人 区分 / 所在地"]},
            {
                "id": "qualifications",
                "title": "資格要件",
                "paragraphs": ["欠格事由 / 専任者 / 財産的基礎"],
            },
            {
                "id": "attachments",
                "title": "添付書類",
                "paragraphs": ["定款 / 登記事項証明書 / 納税証明書"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_REPRESENTATIVE,
            _ph("LICENSE_TYPE", "string", description="許認可種別"),
            _ph("LICENSE_AUTHORITY", "string", description="許可権者 (都道府県知事 / 大臣 等)"),
        ],
    },
    {
        "artifact_type": "gyoumu_itaku_keiyaku",
        "artifact_name_ja": "業務委託契約書",
        "authority": "民法 §632 (請負) + §643 (委任)",
        "sensitive_act": "行政書士法 §1 (権利義務に関する書類作成)",
        "sections": [
            {
                "id": "preamble",
                "title": "前文",
                "paragraphs": ["{{PARTY_A}} (以下「甲」) と {{PARTY_B}} (以下「乙」)"],
            },
            {"id": "scope", "title": "業務内容", "paragraphs": ["委託業務の範囲 / 成果物"]},
            {"id": "consideration", "title": "報酬", "paragraphs": ["金額 / 支払方法 / 支払期日"]},
            {
                "id": "term",
                "title": "期間 / 解除",
                "paragraphs": ["契約期間 / 中途解約 / 損害賠償"],
            },
            {
                "id": "confidentiality",
                "title": "秘密保持",
                "paragraphs": ["秘密情報の範囲 / 存続期間"],
            },
            {"id": "jurisdiction", "title": "管轄", "paragraphs": ["合意管轄裁判所"]},
        ],
        "placeholders": [
            _ph("PARTY_A", "string", description="委託者 (甲) 名称"),
            _ph("PARTY_B", "string", description="受託者 (乙) 名称"),
            _ph("SCOPE_OF_WORK", "string", description="業務内容"),
            _ph("FEE_AMOUNT", "money_yen", description="委託料"),
            _ph("CONTRACT_START", "date", description="契約開始日"),
            _ph("CONTRACT_END", "date", description="契約終了日"),
        ],
    },
    {
        "artifact_type": "gyoumu_teikei_keiyaku",
        "artifact_name_ja": "業務提携契約書",
        "authority": "民法 + 独禁法 §3 (不当な拘束条件付取引の禁止)",
        "sensitive_act": "行政書士法 §1",
        "sections": [
            {
                "id": "preamble",
                "title": "前文",
                "paragraphs": ["{{PARTY_A}} と {{PARTY_B}} の業務提携契約"],
            },
            {"id": "purpose", "title": "目的", "paragraphs": ["提携の目的・対象事業"]},
            {"id": "roles", "title": "役割分担", "paragraphs": ["甲の役割 / 乙の役割"]},
            {"id": "revenue", "title": "収益配分", "paragraphs": ["配分比率 / 計算方法"]},
            {"id": "term", "title": "期間 / 解約", "paragraphs": ["有効期間 / 解約予告"]},
        ],
        "placeholders": [
            _ph("PARTY_A", "string", description="甲 法人名"),
            _ph("PARTY_B", "string", description="乙 法人名"),
            _ph("PARTNERSHIP_PURPOSE", "string", description="提携目的"),
            _ph("REVENUE_SPLIT", "string", description="収益配分 (例: 甲50/乙50)"),
        ],
    },
    {
        "artifact_type": "naiyo_shoumei",
        "artifact_name_ja": "内容証明",
        "authority": "郵便法 §48 + 民法 §97 (意思表示の到達)",
        "sensitive_act": "行政書士法 §1 (権利義務又は事実証明)",
        "sections": [
            {
                "id": "header",
                "title": "差出人・受取人",
                "paragraphs": ["差出人: {{SENDER_NAME}} / 受取人: {{RECIPIENT_NAME}}"],
            },
            {"id": "body", "title": "本文", "paragraphs": ["事実関係 / 請求内容 / 期限"]},
            {"id": "demand", "title": "請求事項", "paragraphs": ["支払額 / 履行内容 / 期日"]},
        ],
        "placeholders": [
            _ph("SENDER_NAME", "string", description="差出人氏名"),
            _ph("SENDER_ADDRESS", "string", description="差出人住所"),
            _ph("RECIPIENT_NAME", "string", description="受取人氏名"),
            _ph("RECIPIENT_ADDRESS", "string", description="受取人住所"),
            _ph("CLAIM_DESCRIPTION", "string", description="請求の概要"),
            _ph("CLAIM_AMOUNT", "money_yen", required=False, description="請求金額 (該当時)"),
            _ph("DEADLINE_DATE", "date", description="履行期限"),
        ],
    },
    {
        "artifact_type": "eigyo_kyoka_shinsei",
        "artifact_name_ja": "営業許可申請書",
        "authority": "食品衛生法 §55 + 同施行規則",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {"id": "applicant", "title": "申請者情報", "paragraphs": ["申請者 / 営業所所在地"]},
            {
                "id": "facility",
                "title": "施設情報",
                "paragraphs": ["業種 / 構造設備 / 食品衛生責任者"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("BUSINESS_CATEGORY", "string", description="営業種類 (飲食店営業 / 食肉販売業 等)"),
            _ph("FACILITY_ADDRESS", "string", description="営業所所在地"),
            _ph("HEALTH_MANAGER_NAME", "string", description="食品衛生責任者氏名"),
        ],
    },
    {
        "artifact_type": "kobutsu_shou_shinsei",
        "artifact_name_ja": "古物商許可申請書",
        "authority": "古物営業法 §3",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {"id": "applicant", "title": "申請者情報", "paragraphs": ["氏名 / 住所 / 法人代表者"]},
            {"id": "business", "title": "営業内容", "paragraphs": ["取扱品目 / 営業所"]},
            {"id": "manager", "title": "管理者", "paragraphs": ["管理者氏名 / 住所"]},
        ],
        "placeholders": [
            _ph("APPLICANT_NAME", "string", description="申請者氏名 / 法人名"),
            _ph("OFFICE_ADDRESS", "string", description="営業所所在地"),
            _ph("CATEGORIES", "array_string", description="取扱品目 (13 区分から選択)"),
            _ph("POLICE_STATION", "string", description="所轄警察署"),
        ],
    },
    {
        "artifact_type": "kensetsu_kyoka_shinsei",
        "artifact_name_ja": "建設業許可申請書",
        "authority": "建設業法 §3 + 同施行規則 §2",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {"id": "applicant", "title": "申請者", "paragraphs": ["商号 / 主たる営業所"]},
            {"id": "type", "title": "許可業種", "paragraphs": ["29 業種から選択"]},
            {
                "id": "requirements",
                "title": "要件",
                "paragraphs": ["経営業務管理責任者 / 専任技術者 / 財産的基礎"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            PH_REPRESENTATIVE,
            _ph("LICENSE_CATEGORY", "string", description="許可業種 (土木一式 / 建築一式 等)"),
            _ph("LICENSE_LEVEL", "enum", description="一般 / 特定"),
            _ph("AUTHORITY_LEVEL", "enum", description="知事許可 / 大臣許可"),
        ],
    },
    {
        "artifact_type": "sanpai_kyoka_shinsei",
        "artifact_name_ja": "産廃業許可申請書",
        "authority": "廃棄物処理法 §14",
        "sensitive_act": "行政書士法 §1 + §19",
        "sections": [
            {"id": "applicant", "title": "申請者", "paragraphs": ["法人 / 個人"]},
            {"id": "scope", "title": "事業範囲", "paragraphs": ["収集運搬 / 中間処理 / 最終処分"]},
            {
                "id": "waste_types",
                "title": "取扱廃棄物",
                "paragraphs": ["産業廃棄物 20 種類から選択"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("BUSINESS_SCOPE", "enum", description="収集運搬 / 中間処理 / 最終処分"),
            _ph("WASTE_TYPES", "array_string", description="取扱産廃種類"),
        ],
    },
    {
        "artifact_type": "nyukan_zairyu_shikaku",
        "artifact_name_ja": "入管・在留資格申請書",
        "authority": "出入国管理及び難民認定法 §7 + §20",
        "sensitive_act": "行政書士法 §1 + 申請取次資格",
        "sections": [
            {
                "id": "applicant",
                "title": "申請者",
                "paragraphs": ["氏名 / 国籍 / 生年月日 / 性別 / パスポート"],
            },
            {"id": "status", "title": "在留資格", "paragraphs": ["申請区分 / 在留資格種別 / 期間"]},
            {"id": "sponsor", "title": "受入機関", "paragraphs": ["所属先 / 役職 / 業務内容"]},
        ],
        "placeholders": [
            _ph("APPLICANT_NAME", "string", description="申請者氏名 (ローマ字)"),
            _ph("NATIONALITY", "string", description="国籍"),
            _ph("PASSPORT_NO", "string", description="パスポート番号"),
            _ph("RESIDENCE_STATUS", "enum", description="在留資格 (技術・人文知識・国際業務 等)"),
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
        ],
    },
]


# =============================================================================
# 司法書士 10 templates
# =============================================================================

SHIHOU = [
    {
        "artifact_type": "kaisha_setsuritsu_touki",
        "artifact_name_ja": "会社設立登記申請書",
        "authority": "商業登記法 §47 + 会社法 §911",
        "sensitive_act": "司法書士法 §3 + §73",
        "sections": [
            {"id": "header", "title": "申請書表紙", "paragraphs": ["株式会社設立登記申請書"]},
            {"id": "company", "title": "会社情報", "paragraphs": ["商号 / 本店 / 目的 / 資本金"]},
            {"id": "officers", "title": "役員", "paragraphs": ["取締役 / 代表取締役 / 監査役"]},
            {
                "id": "attachments",
                "title": "添付書類",
                "paragraphs": ["定款 / 出資払込証明 / 印鑑証明"],
            },
        ],
        "placeholders": [
            _ph("COMPANY_NAME", "string", description="商号"),
            _ph("HEADQUARTER_ADDRESS", "string", description="本店所在地"),
            _ph("CAPITAL_AMOUNT", "money_yen", description="資本金"),
            _ph("PURPOSE_OF_BUSINESS", "array_string", description="事業目的"),
            _ph("REPRESENTATIVE_NAME", "string", description="代表取締役氏名"),
        ],
    },
    {
        "artifact_type": "yakuin_henko_touki",
        "artifact_name_ja": "役員変更登記申請書",
        "authority": "商業登記法 §54 + 会社法 §915",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["役員変更登記申請書"]},
            {"id": "current", "title": "変更前", "paragraphs": ["現役員"]},
            {"id": "new", "title": "変更後", "paragraphs": ["新役員 / 就任承諾書 / 印鑑証明"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("CHANGE_DATE", "date", description="変更年月日"),
            _ph("RETIRING_OFFICER", "string", required=False, description="退任役員氏名"),
            _ph("APPOINTING_OFFICER", "string", required=False, description="就任役員氏名"),
        ],
    },
    {
        "artifact_type": "shougou_henko_touki",
        "artifact_name_ja": "商号変更登記申請書",
        "authority": "商業登記法 §54 + 会社法 §915",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["商号変更登記申請書"]},
            {"id": "old", "title": "変更前商号", "paragraphs": ["{{OLD_NAME}}"]},
            {"id": "new", "title": "変更後商号", "paragraphs": ["{{NEW_NAME}}"]},
            {"id": "resolution", "title": "決議", "paragraphs": ["株主総会議事録 / 定款変更"]},
        ],
        "placeholders": [
            PH_HOUJIN_BANGOU,
            _ph("OLD_NAME", "string", description="変更前商号"),
            _ph("NEW_NAME", "string", description="変更後商号"),
            _ph("RESOLUTION_DATE", "date", description="株主総会決議日"),
        ],
    },
    {
        "artifact_type": "honten_iten_touki",
        "artifact_name_ja": "本店移転登記申請書",
        "authority": "商業登記法 §51-53 + 会社法 §915",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["本店移転登記申請書"]},
            {"id": "old", "title": "旧本店", "paragraphs": ["{{OLD_ADDRESS}}"]},
            {"id": "new", "title": "新本店", "paragraphs": ["{{NEW_ADDRESS}}"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("OLD_ADDRESS", "string", description="移転前本店所在地"),
            _ph("NEW_ADDRESS", "string", description="移転後本店所在地"),
            _ph("MOVE_DATE", "date", description="移転年月日"),
        ],
    },
    {
        "artifact_type": "fudosan_baibai_touki",
        "artifact_name_ja": "不動産売買登記申請書",
        "authority": "不動産登記法 §60 + 民法 §177",
        "sensitive_act": "司法書士法 §3 + §73",
        "sections": [
            {"id": "header", "title": "申請書表紙", "paragraphs": ["所有権移転登記申請書"]},
            {"id": "property", "title": "不動産表示", "paragraphs": ["所在 / 地番 / 地目 / 地積"]},
            {
                "id": "parties",
                "title": "当事者",
                "paragraphs": ["売主 (登記義務者) / 買主 (登記権利者)"],
            },
            {"id": "cause", "title": "登記原因", "paragraphs": ["売買 / 年月日"]},
        ],
        "placeholders": [
            _ph("SELLER_NAME", "string", description="売主氏名 / 法人名"),
            _ph("BUYER_NAME", "string", description="買主氏名 / 法人名"),
            _ph("PROPERTY_LOCATION", "string", description="不動産所在"),
            _ph("LOT_NUMBER", "string", description="地番 / 家屋番号"),
            _ph("SALE_DATE", "date", description="売買年月日"),
            _ph("PURCHASE_PRICE", "money_yen", description="売買代金"),
        ],
    },
    {
        "artifact_type": "teitouken_settei_touki",
        "artifact_name_ja": "抵当権設定登記申請書",
        "authority": "不動産登記法 §60 + 民法 §369",
        "sensitive_act": "司法書士法 §3 + §73",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["抵当権設定登記申請書"]},
            {"id": "property", "title": "物件表示", "paragraphs": [""]},
            {
                "id": "obligation",
                "title": "債権の内容",
                "paragraphs": ["債権額 / 利息 / 損害金 / 債務者"],
            },
            {"id": "parties", "title": "抵当権者・設定者", "paragraphs": [""]},
        ],
        "placeholders": [
            _ph("MORTGAGEE", "string", description="抵当権者 (金融機関等)"),
            _ph("MORTGAGOR", "string", description="抵当権設定者"),
            _ph("DEBTOR", "string", description="債務者"),
            _ph("PROPERTY_LOCATION", "string", description="物件所在"),
            _ph("CLAIM_AMOUNT", "money_yen", description="債権額"),
            _ph("INTEREST_RATE", "decimal", description="利息 (年率%)"),
        ],
    },
    {
        "artifact_type": "souzoku_touki",
        "artifact_name_ja": "相続登記申請書",
        "authority": "不動産登記法 §63 + 民法 §882-",
        "sensitive_act": "司法書士法 §3 + §73",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["所有権移転登記申請書 (相続)"]},
            {
                "id": "decedent",
                "title": "被相続人",
                "paragraphs": ["氏名 / 死亡年月日 / 最後の住所"],
            },
            {"id": "heirs", "title": "相続人", "paragraphs": ["相続人氏名 / 持分"]},
            {"id": "property", "title": "不動産", "paragraphs": [""]},
            {
                "id": "attachments",
                "title": "添付",
                "paragraphs": ["戸籍謄本 / 遺産分割協議書 / 印鑑証明"],
            },
        ],
        "placeholders": [
            _ph("DECEDENT_NAME", "string", description="被相続人氏名"),
            _ph("DEATH_DATE", "date", description="死亡年月日"),
            _ph("HEIRS", "array_string", description="相続人氏名一覧"),
            _ph("PROPERTY_LOCATION", "string", description="相続不動産所在"),
            _ph("INHERITANCE_TYPE", "enum", description="法定相続 / 遺産分割 / 遺言"),
        ],
    },
    {
        "artifact_type": "houjin_kaisan_touki",
        "artifact_name_ja": "法人解散登記申請書",
        "authority": "商業登記法 §71-77 + 会社法 §926",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["解散及び清算人選任登記申請書"]},
            {
                "id": "cause",
                "title": "解散事由",
                "paragraphs": ["株主総会決議 / 存続期間満了 / 合併 / 破産"],
            },
            {"id": "liquidator", "title": "清算人", "paragraphs": ["氏名 / 住所"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("DISSOLUTION_CAUSE", "enum", description="解散事由"),
            _ph("DISSOLUTION_DATE", "date", description="解散年月日"),
            _ph("LIQUIDATOR_NAME", "string", description="清算人氏名"),
        ],
    },
    {
        "artifact_type": "shougyo_touki_misc",
        "artifact_name_ja": "商業登記",
        "authority": "商業登記法 §1 + 会社法 §911-933",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["商業登記申請書"]},
            {"id": "subject", "title": "登記事項", "paragraphs": ["対象事項の変更 / 追加 / 削除"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph(
                "REGISTRATION_SUBJECT", "string", description="登記事項 (例: 目的変更 / 資本金変更)"
            ),
            _ph("EFFECTIVE_DATE", "date", description="効力発生日"),
        ],
    },
    {
        "artifact_type": "shurui_kabushiki_touki",
        "artifact_name_ja": "種類株式発行登記",
        "authority": "商業登記法 §54 + 会社法 §108 + §911",
        "sensitive_act": "司法書士法 §3",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["種類株式発行登記申請書"]},
            {
                "id": "share_class",
                "title": "種類",
                "paragraphs": ["普通株式 / 優先株式 / 劣後株式 / 議決権制限株式 等"],
            },
            {
                "id": "terms",
                "title": "内容",
                "paragraphs": ["配当優先 / 残余財産 / 議決権 / 譲渡制限"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_HOUJIN_BANGOU,
            _ph("SHARE_CLASS_NAME", "string", description="種類株式名"),
            _ph("PREFERENCE_TYPE", "enum", description="優先内容 (配当 / 残余 / 議決権制限 等)"),
            _ph("ISSUE_AMOUNT", "integer", description="発行株式数"),
        ],
    },
]


# =============================================================================
# 社労士 10 templates
# =============================================================================

SHAROUSHI = [
    {
        "artifact_type": "shuugyou_kisoku",
        "artifact_name_ja": "就業規則",
        "authority": "労基法 §89",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "general", "title": "総則", "paragraphs": ["目的 / 適用範囲"]},
            {"id": "hiring", "title": "採用・異動", "paragraphs": ["採用基準 / 試用期間 / 配転"]},
            {
                "id": "work_hours",
                "title": "労働時間・休憩・休日",
                "paragraphs": ["所定労働時間 / 休憩 / 休日"],
            },
            {"id": "leave", "title": "休暇", "paragraphs": ["年次有給休暇 / 特別休暇"]},
            {"id": "wages", "title": "賃金", "paragraphs": ["賃金規程に委任"]},
            {"id": "retirement", "title": "退職・解雇", "paragraphs": ["退職事由 / 解雇事由"]},
            {"id": "safety", "title": "安全衛生", "paragraphs": ["災害補償 / 安全衛生"]},
            {"id": "discipline", "title": "表彰・懲戒", "paragraphs": ["表彰 / 懲戒事由 / 種類"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_ADDRESS,
            _ph("EFFECTIVE_DATE", "date", description="施行日"),
            _ph("WORKING_HOURS_DAILY", "decimal", description="所定労働時間 (時間/日)"),
            _ph("ANNUAL_LEAVE_DAYS", "integer", description="年次有給休暇 (日数)"),
            _ph(
                "LEGAL_BASIS_LABOR_89",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "労働基準法", "article": "89"}
                ),
                description="労基法 §89 (作成義務)",
            ),
        ],
    },
    {
        "artifact_type": "sanroku_kyoutei",
        "artifact_name_ja": "36協定書",
        "authority": "労基法 §36",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {
                "id": "header",
                "title": "ヘッダ",
                "paragraphs": ["時間外労働・休日労働に関する協定届"],
            },
            {"id": "parties", "title": "当事者", "paragraphs": ["使用者 / 労働者代表"]},
            {
                "id": "overtime",
                "title": "時間外労働",
                "paragraphs": ["業務種類 / 労働者数 / 延長時間 (1日/月/年)"],
            },
            {
                "id": "holiday_work",
                "title": "休日労働",
                "paragraphs": ["業務種類 / 休日日数 / 始業終業時刻"],
            },
            {
                "id": "special_clause",
                "title": "特別条項",
                "paragraphs": ["臨時的な特別の事情 / 上限"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_REPRESENTATIVE,
            _ph("EMPLOYEE_REP_NAME", "string", description="労働者代表氏名"),
            _ph("AGREEMENT_PERIOD_START", "date", description="協定開始日"),
            _ph("AGREEMENT_PERIOD_END", "date", description="協定終了日"),
            _ph("MAX_OVERTIME_MONTHLY", "decimal", description="月延長時間上限 (h)"),
            _ph("MAX_OVERTIME_ANNUAL", "decimal", description="年延長時間上限 (h)"),
            _ph(
                "LEGAL_BASIS_LABOR_36",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "労働基準法", "article": "36"}
                ),
                description="労基法 §36 条文",
            ),
        ],
    },
    {
        "artifact_type": "koyou_keiyaku",
        "artifact_name_ja": "雇用契約書",
        "authority": "労基法 §15 + 労働契約法 §4",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {
                "id": "preamble",
                "title": "前文",
                "paragraphs": ["{{COMPANY_NAME}} と {{EMPLOYEE_NAME}}"],
            },
            {"id": "duties", "title": "業務内容・就業場所", "paragraphs": [""]},
            {"id": "term", "title": "契約期間", "paragraphs": ["期間の定め有無 / 更新基準"]},
            {"id": "hours", "title": "始業・終業・休憩", "paragraphs": [""]},
            {
                "id": "wages",
                "title": "賃金",
                "paragraphs": ["基本給 / 諸手当 / 締日 / 支払日 / 方法"],
            },
            {"id": "retirement", "title": "退職", "paragraphs": ["定年 / 自己都合 / 解雇事由"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_REPRESENTATIVE,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("EMPLOYMENT_TYPE", "enum", description="正社員 / 契約社員 / パート / アルバイト"),
            _ph("CONTRACT_START", "date", description="雇用開始日"),
            _ph("CONTRACT_END", "date", required=False, description="雇用終了日 (期間定有の場合)"),
            _ph("BASE_SALARY", "money_yen", description="基本給"),
        ],
    },
    {
        "artifact_type": "chingin_kitei",
        "artifact_name_ja": "賃金規程",
        "authority": "労基法 §89",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "general", "title": "総則", "paragraphs": ["目的 / 適用範囲"]},
            {"id": "structure", "title": "賃金体系", "paragraphs": ["基本給 / 諸手当 / 賞与"]},
            {"id": "calc", "title": "計算方法", "paragraphs": ["時間外 / 休日 / 深夜割増"]},
            {"id": "payment", "title": "支払", "paragraphs": ["締日 / 支払日 / 支払方法"]},
            {"id": "deduction", "title": "控除", "paragraphs": ["社保 / 税 / 労組費"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("EFFECTIVE_DATE", "date", description="施行日"),
            _ph("WAGE_CALC_PERIOD", "string", description="賃金計算期間"),
            _ph("PAYDAY", "string", description="支払日 (例: 当月25日)"),
            _ph(
                "OVERTIME_PREMIUM_RATE",
                "rule_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "労働基準法", "article": "37"}
                ),
                description="労基法 §37 割増率",
            ),
        ],
    },
    {
        "artifact_type": "taishokukin_kitei",
        "artifact_name_ja": "退職金規程",
        "authority": "労基法 §89 (相対的記載事項)",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "general", "title": "総則", "paragraphs": ["目的 / 適用範囲"]},
            {"id": "eligibility", "title": "支給要件", "paragraphs": ["勤続年数 / 退職事由"]},
            {"id": "calc", "title": "算定方法", "paragraphs": ["基本給 × 支給率 × 退職事由係数"]},
            {"id": "payment", "title": "支給", "paragraphs": ["支給時期 / 方法"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("MIN_YEARS_OF_SERVICE", "integer", description="支給最低勤続年数"),
            _ph("CALC_FORMULA", "string", description="算定式の記述"),
        ],
    },
    {
        "artifact_type": "ikuji_kaigo_kyugyou",
        "artifact_name_ja": "育児・介護休業規程",
        "authority": "育児・介護休業法 §5-21 + 労基法 §65",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "childcare", "title": "育児休業", "paragraphs": ["対象労働者 / 期間 / 申出"]},
            {
                "id": "childcare_short",
                "title": "育児短時間勤務",
                "paragraphs": ["3歳未満子 / 6時間勤務"],
            },
            {"id": "nursing", "title": "介護休業", "paragraphs": ["対象家族 / 通算93日 / 3回まで"]},
            {"id": "nursing_short", "title": "介護短時間勤務", "paragraphs": [""]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("EFFECTIVE_DATE", "date", description="施行日"),
            _ph(
                "LEGAL_BASIS_CHILDCARE",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "育児・介護休業法", "article": "5"}
                ),
                description="育児・介護休業法 §5",
            ),
        ],
    },
    {
        "artifact_type": "anzen_eisei_kitei",
        "artifact_name_ja": "安全衛生規程",
        "authority": "労働安全衛生法 §3 + §59 + §66",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "general", "title": "総則", "paragraphs": ["目的 / 安全衛生管理体制"]},
            {
                "id": "education",
                "title": "安全衛生教育",
                "paragraphs": ["雇入れ時教育 / 危険有害業務教育"],
            },
            {
                "id": "health_check",
                "title": "健康診断",
                "paragraphs": ["雇入れ時 / 定期 / 特殊健診"],
            },
            {
                "id": "harassment",
                "title": "ハラスメント防止",
                "paragraphs": ["パワハラ / セクハラ / マタハラ"],
            },
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            _ph("SAFETY_OFFICER_NAME", "string", description="安全衛生推進者氏名"),
            _ph("EFFECTIVE_DATE", "date", description="施行日"),
        ],
    },
    {
        "artifact_type": "kyuyo_kaitei_tsuchi",
        "artifact_name_ja": "給与改定通知書",
        "authority": "労基法 §15 + 労働契約法 §8",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["給与改定通知書"]},
            {"id": "addressee", "title": "宛名", "paragraphs": ["{{EMPLOYEE_NAME}} 殿"]},
            {"id": "content", "title": "改定内容", "paragraphs": ["改定前 / 改定後 / 改定理由"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_REPRESENTATIVE,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("OLD_SALARY", "money_yen", description="改定前給与"),
            _ph("NEW_SALARY", "money_yen", description="改定後給与"),
            _ph("REVISION_DATE", "date", description="改定発効日"),
            _ph("REVISION_REASON", "string", description="改定理由"),
        ],
    },
    {
        "artifact_type": "kaiko_yokoku_tsuchi",
        "artifact_name_ja": "解雇予告通知書",
        "authority": "労基法 §20",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["解雇予告通知書"]},
            {"id": "addressee", "title": "宛名", "paragraphs": ["{{EMPLOYEE_NAME}} 殿"]},
            {"id": "notice", "title": "予告", "paragraphs": ["解雇予定日 / 解雇事由"]},
            {"id": "compensation", "title": "予告手当", "paragraphs": ["30日に満たない期間の手当"]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_REPRESENTATIVE,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("NOTICE_DATE", "date", description="通知日"),
            _ph("DISMISSAL_DATE", "date", description="解雇予定日 (30日以上後)"),
            _ph("DISMISSAL_REASON", "string", description="解雇事由"),
            _ph(
                "LEGAL_BASIS_LABOR_20",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "労働基準法", "article": "20"}
                ),
                description="労基法 §20 (解雇予告)",
            ),
        ],
    },
    {
        "artifact_type": "roudou_jouken_tsuchi",
        "artifact_name_ja": "労働条件通知書",
        "authority": "労基法 §15 + 同施行規則 §5",
        "sensitive_act": "社労士法 §27",
        "sections": [
            {"id": "header", "title": "ヘッダ", "paragraphs": ["労働条件通知書"]},
            {"id": "addressee", "title": "宛名", "paragraphs": ["{{EMPLOYEE_NAME}} 殿"]},
            {"id": "contract", "title": "契約期間", "paragraphs": ["期間の定め有無 / 更新の有無"]},
            {"id": "place", "title": "就業場所・業務", "paragraphs": [""]},
            {"id": "hours", "title": "始業終業時刻・休憩・休日", "paragraphs": [""]},
            {"id": "wages", "title": "賃金", "paragraphs": ["基本給 / 諸手当 / 締切日 / 支払日"]},
            {"id": "termination", "title": "退職・解雇", "paragraphs": [""]},
        ],
        "placeholders": [
            PH_COMPANY_NAME,
            PH_REPRESENTATIVE,
            _ph("EMPLOYEE_NAME", "string", description="従業員氏名"),
            _ph("CONTRACT_START", "date", description="雇用開始日"),
            _ph("WORK_LOCATION", "string", description="就業場所"),
            _ph("WORK_DUTIES", "string", description="従事する業務"),
            _ph("BASE_SALARY", "money_yen", description="基本給"),
            _ph(
                "LEGAL_BASIS_LABOR_15",
                "law_ref",
                source="mcp",
                mcp_query_spec=_binding(
                    "get_law_article_am", {"law_id": "労働基準法", "article": "15"}
                ),
                description="労基法 §15 (労働条件明示)",
            ),
        ],
    },
]


# =============================================================================
# Build + Emit
# =============================================================================

SEGMENTS = {
    "zeirishi": ("税理士", ZEIRISHI),
    "kaikeishi": ("会計士", KAIKEISHI),
    "gyousei": ("行政書士", GYOUSEI),
    "shihou": ("司法書士", SHIHOU),
    "sharoushi": ("社労士", SHAROUSHI),
}


def build_template(segment_label: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Compose the final YAML-shaped dict for one artifact template."""
    placeholders = spec["placeholders"]
    bindings = {}
    for p in placeholders:
        if p.get("mcp_query_spec"):
            bindings[p["key"]] = p["mcp_query_spec"]
    return {
        "segment": segment_label,
        "artifact_type": spec["artifact_type"],
        "artifact_name_ja": spec["artifact_name_ja"],
        "version": "v1",
        "authority": spec["authority"],
        "sensitive_act": spec["sensitive_act"],
        "is_scaffold_only": True,
        "requires_professional_review": True,
        "uses_llm": False,
        "quality_grade": "draft",
        "license": "jpcite-scaffold-cc0",
        "sections": spec["sections"],
        "placeholders": placeholders,
        "mcp_query_bindings": bindings,
        "disclaimer": (
            f"このテンプレートは scaffold です。{spec['authority']} に基づく成果物として "
            f"{spec['sensitive_act']} 有資格者の確認・署名なく提出してはなりません。"
        ),
    }


def emit_yaml(path: Path, data: dict[str, Any]) -> None:
    """Emit as YAML-flavored JSON. We use JSON-as-YAML for fidelity + no dep."""
    # JSON is a strict subset of YAML 1.2, so the .yaml file is valid YAML
    # and round-trips through yaml.safe_load() without ambiguity.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    total = 0
    for seg_key, (seg_label, specs) in SEGMENTS.items():
        assert len(specs) == 10, f"{seg_key} must define exactly 10 templates (got {len(specs)})"
        for spec in specs:
            data = build_template(seg_label, spec)
            out_path = OUT_ROOT / seg_key / f"{spec['artifact_type']}.yaml"
            emit_yaml(out_path, data)
            total += 1
    print(f"emitted {total} artifact template YAML files under {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
