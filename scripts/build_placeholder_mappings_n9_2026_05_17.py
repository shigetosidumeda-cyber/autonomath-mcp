#!/usr/bin/env python3
"""Lane N9 — generate data/placeholder_mappings.json (~207 entries).

Idempotent: re-running overwrites the existing file. Designed to be run
after a fresh checkout / PC restart that wiped the untracked
data/placeholder_mappings.json file.

The JSON file is the canonical source-of-truth for
``am_placeholder_mapping`` rows. The companion script
``scripts/cron/load_placeholder_mappings_2026_05_17.py`` bulk-loads
this JSON into the autonomath.db table.

NO LLM. Pure Python generator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "placeholder_mappings.json"


def m(
    name: str,
    tool: str,
    args: str = "{}",
    out: str = "$",
    fallback: Any = None,
    kind: str = "text",
    desc: str = "",
    sensitive: int = 0,
    license_: str = "jpcite-scaffold-cc0",
) -> dict[str, Any]:
    return {
        "placeholder_name": name,
        "mcp_tool_name": tool,
        "args_template": args,
        "output_path": out,
        "fallback_value": fallback,
        "value_kind": kind,
        "description": desc,
        "is_sensitive": sensitive,
        "license": license_,
    }


# ---------------------------------------------------------------------------
# Mapping bank
# ---------------------------------------------------------------------------


def _mappings() -> list[dict[str, Any]]:  # noqa: PLR0915
    # ruff: noqa: N806 — terse uppercase locals are intentional, this is a
    # data builder where SQL-style identifiers are easier to scan than
    # snake_case `hj_args` / `prg_args` / etc.
    HJ = '{"houjin_bangou": "{houjin_bangou}"}'  # noqa: N806
    PRG = '{"program_id": "{program_id}"}'  # noqa: N806
    LAW = '{"law_id": "{law_id}"}'  # noqa: N806
    LAWA = '{"law_id": "{law_id}", "article": "{article_number}"}'  # noqa: N806
    AS_OF = '{"window_months": 12, "as_of": "{current_date}"}'  # noqa: N806
    out: list[dict[str, Any]] = []

    # 1. Houjin / corporate identity (16)
    out += [
        m(
            "{{HOUJIN_BANGOU}}",
            "context",
            "{}",
            "houjin_bangou",
            desc="13桁 法人番号",
            kind="text",
            license_="jpcite-scaffold-cc0",
        ),
        m(
            "{{HOUJIN_NAME}}",
            "get_houjin_360_am",
            HJ,
            "houjin.name",
            "(法人名未取得)",
            "text",
            "国税庁登録法人名",
            license_="pdl_v1.0",
        ),
        m(
            "{{HOUJIN_NAME_KANA}}",
            "get_houjin_360_am",
            HJ,
            "houjin.name_kana",
            None,
            "text",
            "法人名フリガナ",
            license_="pdl_v1.0",
        ),
        m(
            "{{HOUJIN_NAME_EN}}",
            "get_houjin_360_am",
            HJ,
            "houjin.name_en",
            None,
            "text",
            "法人名英語",
            license_="pdl_v1.0",
        ),
        m(
            "{{REGISTERED_ADDRESS}}",
            "get_houjin_360_am",
            HJ,
            "houjin.registered_address",
            "(本店所在地未取得)",
            "text",
            "登記本店所在地",
            license_="pdl_v1.0",
        ),
        m(
            "{{PREFECTURE}}",
            "get_houjin_360_am",
            HJ,
            "houjin.prefecture",
            None,
            "text",
            "本店所在 都道府県",
            license_="pdl_v1.0",
        ),
        m(
            "{{MUNICIPALITY}}",
            "get_houjin_360_am",
            HJ,
            "houjin.municipality",
            None,
            "text",
            "本店所在 市区町村",
            license_="pdl_v1.0",
        ),
        m(
            "{{POSTAL_CODE}}",
            "get_houjin_360_am",
            HJ,
            "houjin.postal_code",
            None,
            "text",
            "本店郵便番号",
            license_="pdl_v1.0",
        ),
        m(
            "{{REPRESENTATIVE_NAME}}",
            "get_houjin_360_am",
            HJ,
            "houjin.representative_name",
            None,
            "text",
            "代表者氏名",
            license_="pdl_v1.0",
        ),
        m(
            "{{REPRESENTATIVE_TITLE}}",
            "get_houjin_360_am",
            HJ,
            "houjin.representative_title",
            "代表取締役",
            "text",
            "代表者役職",
            license_="pdl_v1.0",
        ),
        m(
            "{{ESTABLISHED_DATE}}",
            "get_houjin_360_am",
            HJ,
            "houjin.established_date",
            None,
            "date",
            "設立年月日",
            license_="pdl_v1.0",
        ),
        m(
            "{{CAPITAL_YEN}}",
            "get_houjin_360_am",
            HJ,
            "houjin.capital_yen",
            None,
            "yen",
            "資本金 (円)",
            license_="pdl_v1.0",
        ),
        m(
            "{{EMPLOYEE_COUNT}}",
            "get_houjin_360_am",
            HJ,
            "houjin.employee_count",
            None,
            "integer",
            "従業員数",
            license_="pdl_v1.0",
        ),
        m(
            "{{INDUSTRY_JSIC_MAJOR}}",
            "get_houjin_360_am",
            HJ,
            "houjin.industry_jsic_major",
            None,
            "enum",
            "JSIC大分類",
            license_="pdl_v1.0",
        ),
        m(
            "{{INDUSTRY_JSIC_NAME}}",
            "get_houjin_360_am",
            HJ,
            "houjin.industry_jsic_name",
            None,
            "text",
            "JSIC大分類 日本語",
            license_="pdl_v1.0",
        ),
        m(
            "{{REVENUE_YEN}}",
            "get_houjin_360_am",
            HJ,
            "houjin.revenue_yen",
            None,
            "yen",
            "売上高 (円)",
            license_="pdl_v1.0",
        ),
        m(
            "{{REVENUE_BAND}}",
            "get_houjin_360_am",
            HJ,
            "houjin.revenue_band",
            None,
            "enum",
            "売上 band",
            license_="pdl_v1.0",
        ),
    ]

    # 2. Invoice registrant (4)
    out += [
        m(
            "{{INVOICE_REGISTRANT_T}}",
            "search_invoice_registrants",
            HJ,
            "registrant.t_number",
            "(未登録)",
            "text",
            "適格事業者番号 T+13桁",
            license_="pdl_v1.0",
        ),
        m(
            "{{INVOICE_REGISTRATION_DATE}}",
            "search_invoice_registrants",
            HJ,
            "registrant.registration_date",
            None,
            "date",
            "登録日",
            license_="pdl_v1.0",
        ),
        m(
            "{{INVOICE_STATUS}}",
            "search_invoice_registrants",
            HJ,
            "registrant.status",
            "未登録",
            "enum",
            "登録状態",
            license_="pdl_v1.0",
        ),
        m(
            "{{INVOICE_REVOCATION_DATE}}",
            "search_invoice_registrants",
            HJ,
            "registrant.revocation_date",
            None,
            "date",
            "取消日",
            license_="pdl_v1.0",
        ),
    ]

    # 3. Program (17)
    out += [
        m("{{PROGRAM_ID}}", "context", "{}", "program_id", None, "text", "program unified_id"),
        m(
            "{{PROGRAM_NAME}}",
            "program_full_context",
            PRG,
            "program.name",
            None,
            "text",
            "制度名称",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_KIND}}",
            "program_full_context",
            PRG,
            "program.program_kind",
            None,
            "enum",
            "制度種別",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_AUTHORITY}}",
            "program_full_context",
            PRG,
            "program.authority",
            None,
            "text",
            "所管省庁",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_TIER}}",
            "program_full_context",
            PRG,
            "program.tier",
            None,
            "enum",
            "tier S/A/B/C",
        ),
        m(
            "{{PROGRAM_SOURCE_URL}}",
            "program_full_context",
            PRG,
            "program.source_url",
            None,
            "url",
            "一次出典 URL",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_SUMMARY}}",
            "program_full_context",
            PRG,
            "program.summary",
            None,
            "text",
            "制度サマリ",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_AMOUNT_MAX}}",
            "program_full_context",
            PRG,
            "program.amount_max_yen",
            None,
            "yen",
            "上限金額",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_AMOUNT_RATE}}",
            "program_full_context",
            PRG,
            "program.subsidy_rate",
            None,
            "percentage",
            "補助率",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_DEADLINE}}",
            "program_full_context",
            PRG,
            "program.application_deadline",
            None,
            "date",
            "申請締切",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_APPLICATION_OPEN}}",
            "program_full_context",
            PRG,
            "program.application_open_date",
            None,
            "date",
            "申請開始",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_TARGET_TYPES}}",
            "program_full_context",
            PRG,
            "program.target_types_json",
            "[]",
            "list",
            "対象事業者",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_TARGET_PREFECTURE}}",
            "program_full_context",
            PRG,
            "program.target_prefecture",
            "全国",
            "text",
            "対象都道府県",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_ELIGIBILITY_CHAIN}}",
            "apply_eligibility_chain_am",
            '{"program_id": "{program_id}", "business_profile": "{business_profile}"}',
            "$",
            None,
            "json",
            "eligibility chain",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_REQUIRED_DOCUMENTS}}",
            "bundle_application_kit",
            '{"program_id": "{program_id}", "client_id": "{client_id}"}',
            "kit.required_documents",
            "[]",
            "list",
            "必要書類",
            license_="gov_standard",
        ),
        m(
            "{{PROGRAM_LIFECYCLE_STATUS}}",
            "program_lifecycle",
            PRG,
            "status",
            "unknown",
            "enum",
            "制度 lifecycle",
        ),
        m(
            "{{PROGRAM_PREREQUISITE_CHAIN}}",
            "prerequisite_chain",
            PRG,
            "chain",
            "[]",
            "json",
            "前提 chain",
            license_="gov_standard",
        ),
    ]

    # 4. Law / article (7)
    out += [
        m("{{LAW_ID}}", "context", "{}", "law_id", None, "text", "法令ID"),
        m(
            "{{LAW_NAME}}",
            "get_law_article_am",
            LAW,
            "law.name",
            None,
            "text",
            "法令名",
            license_="cc_by_4.0",
        ),
        m(
            "{{LAW_NUMBER}}",
            "get_law_article_am",
            LAW,
            "law.law_number",
            None,
            "text",
            "法令番号",
            license_="cc_by_4.0",
        ),
        m(
            "{{LEGAL_BASIS_ARTICLE}}",
            "get_law_article_am",
            LAWA,
            "article.body",
            None,
            "text",
            "条文本文",
            license_="cc_by_4.0",
        ),
        m("{{ARTICLE_NUMBER}}", "context", "{}", "article_number", None, "text", "条文番号"),
        m(
            "{{ARTICLE_TITLE}}",
            "get_law_article_am",
            LAWA,
            "article.title",
            None,
            "text",
            "条文見出し",
            license_="cc_by_4.0",
        ),
        m(
            "{{ARTICLE_EFFECTIVE_DATE}}",
            "get_law_article_am",
            LAWA,
            "article.effective_from",
            None,
            "date",
            "施行日",
            license_="cc_by_4.0",
        ),
    ]

    # 5. Tax rule (9)
    out += [
        m("{{TAX_RULE_ID}}", "context", "{}", "tax_rule_id", None, "text", "TAX-* ID", sensitive=1),
        m(
            "{{TAX_RULE_NAME}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.name",
            None,
            "text",
            "税制名称",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_AUTHORITY}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.authority",
            "国税庁",
            "text",
            "所管",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_RATE}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.credit_rate",
            None,
            "percentage",
            "税額控除率",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_AMOUNT_MAX}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.amount_max_yen",
            None,
            "yen",
            "上限額",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_SUNSET_DATE}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.sunset_date",
            None,
            "date",
            "sunset",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_NOTICE_URL}}",
            "get_am_tax_rule",
            '{"ruleset_id": "{tax_rule_id}"}',
            "rule.source_url",
            None,
            "url",
            "一次 URL",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_TSUTATSU_CITE}}",
            "cite_tsutatsu",
            '{"ruleset_id": "{tax_rule_id}"}',
            "tsutatsu",
            "[]",
            "json",
            "通達 引用",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TAX_RULE_APPLICABLE}}",
            "evaluate_tax_applicability",
            '{"target_ruleset_ids": ["{tax_rule_id}"], "business_profile": "{business_profile}"}',
            "applicable[0]",
            None,
            "boolean",
            "適用可否",
            sensitive=1,
            license_="gov_standard",
        ),
    ]

    # 6. Enforcement (5)
    out += [
        m(
            "{{ENFORCEMENT_COUNT}}",
            "check_enforcement_am",
            HJ,
            "enforcements.length",
            "0",
            "integer",
            "行政処分件数",
            license_="gov_standard",
        ),
        m(
            "{{ENFORCEMENT_LATEST_DATE}}",
            "check_enforcement_am",
            HJ,
            "enforcements[0].decision_date",
            None,
            "date",
            "直近 処分日",
            license_="gov_standard",
        ),
        m(
            "{{ENFORCEMENT_LATEST_KIND}}",
            "check_enforcement_am",
            HJ,
            "enforcements[0].kind",
            None,
            "enum",
            "直近 種別",
            license_="gov_standard",
        ),
        m(
            "{{ENFORCEMENT_LATEST_AMOUNT}}",
            "check_enforcement_am",
            HJ,
            "enforcements[0].amount_yen",
            None,
            "yen",
            "直近 金額",
            license_="gov_standard",
        ),
        m(
            "{{ENFORCEMENT_AUTHORITY}}",
            "check_enforcement_am",
            HJ,
            "enforcements[0].authority",
            None,
            "text",
            "処分庁",
            license_="gov_standard",
        ),
    ]

    # 7. Court decision (5)
    out += [
        m("{{COURT_DECISION_ID}}", "context", "{}", "court_decision_id", None, "text", "判例 ID"),
        m(
            "{{COURT_NAME}}",
            "search_acceptance_stats_am",
            '{"id": "{court_decision_id}"}',
            "decision.court_name",
            None,
            "text",
            "裁判所名",
            license_="public_domain",
        ),
        m(
            "{{COURT_DECISION_DATE}}",
            "search_acceptance_stats_am",
            '{"id": "{court_decision_id}"}',
            "decision.decision_date",
            None,
            "date",
            "判決年月日",
            license_="public_domain",
        ),
        m(
            "{{COURT_CASE_NUMBER}}",
            "search_acceptance_stats_am",
            '{"id": "{court_decision_id}"}',
            "decision.case_number",
            None,
            "text",
            "事件番号",
            license_="public_domain",
        ),
        m(
            "{{COURT_DECISION_SUMMARY}}",
            "search_acceptance_stats_am",
            '{"id": "{court_decision_id}"}',
            "decision.summary",
            None,
            "text",
            "判決要旨",
            license_="public_domain",
        ),
    ]

    # 8. Audit (6)
    out += [
        m(
            "{{AUDIT_PERIOD}}",
            "context",
            "{}",
            "audit_period",
            None,
            "text",
            "監査期間",
            sensitive=1,
        ),
        m(
            "{{AUDIT_FIRM_ID}}",
            "context",
            "{}",
            "audit_firm_id",
            None,
            "text",
            "監査法人 ID",
            sensitive=1,
        ),
        m(
            "{{AUDIT_PARTNER_NAME}}",
            "context",
            "{}",
            "audit_partner_name",
            None,
            "text",
            "監査責任パートナー",
            sensitive=1,
        ),
        m(
            "{{AUDIT_OPINION_TYPE}}",
            "context",
            "{}",
            "audit_opinion_type",
            "draft",
            "enum",
            "意見種別",
            sensitive=1,
        ),
        m(
            "{{AUDIT_SEAL_PACK_ID}}",
            "compose_audit_workpaper",
            '{"client_id": "{client_id}", "audit_period": "{audit_period}"}',
            "audit_seal_pack_id",
            None,
            "text",
            "audit_seal pack ID",
            sensitive=1,
        ),
        m(
            "{{WORKPAPER_PDF_URL}}",
            "compose_audit_workpaper",
            '{"client_id": "{client_id}", "audit_period": "{audit_period}"}',
            "workpaper_pdf_url",
            None,
            "url",
            "監査調書 PDF URL",
            sensitive=1,
        ),
    ]

    # 9. Client / fiscal (10)
    out += [
        m("{{CLIENT_ID}}", "context", "{}", "client_id", None, "text", "顧問先 ID"),
        m(
            "{{CLIENT_PROFILE_ID}}",
            "context",
            "{}",
            "client_profile_id",
            None,
            "text",
            "client_profiles 行 ID",
        ),
        m("{{FISCAL_YEAR}}", "context", "{}", "fiscal_year", None, "text", "事業年度 YYYY"),
        m("{{FISCAL_YEAR_END}}", "context", "{}", "fiscal_year_end", None, "date", "事業年度末"),
        m(
            "{{FISCAL_YEAR_MONTH}}",
            "context",
            "{}",
            "fiscal_year_month",
            None,
            "text",
            "対象月 YYYY-MM",
        ),
        m("{{TAX_YEAR}}", "context", "{}", "tax_year", None, "text", "税務年度"),
        m(
            "{{CURRENT_DATE}}",
            "computed",
            '{"compute": "today_iso"}',
            "$",
            None,
            "date",
            "現在日付 JST",
        ),
        m(
            "{{CURRENT_FISCAL_YEAR}}",
            "computed",
            '{"compute": "current_fiscal_year_jp"}',
            "$",
            None,
            "text",
            "現在 和暦事業年度",
        ),
        m(
            "{{CURRENT_WAREKI}}",
            "computed",
            '{"compute": "current_wareki"}',
            "$",
            None,
            "wareki",
            "現在 和暦",
        ),
        m(
            "{{CURRENT_TIMESTAMP}}",
            "computed",
            '{"compute": "now_iso"}',
            "$",
            None,
            "text",
            "現在時刻 JST ISO",
        ),
    ]

    # 10. Amendment lineage (3)
    out += [
        m(
            "{{AMENDMENT_DIFF_COUNT}}",
            "track_amendment_lineage_am",
            AS_OF,
            "amendments.length",
            "0",
            "integer",
            "直近12ヶ月 改正件数",
            license_="cc_by_4.0",
        ),
        m(
            "{{AMENDMENT_LATEST_DATE}}",
            "track_amendment_lineage_am",
            AS_OF,
            "amendments[0].effective_date",
            None,
            "date",
            "直近 施行日",
            license_="cc_by_4.0",
        ),
        m(
            "{{AMENDMENT_LATEST_SUMMARY}}",
            "track_amendment_lineage_am",
            AS_OF,
            "amendments[0].summary",
            None,
            "text",
            "直近 サマリ",
            license_="cc_by_4.0",
        ),
    ]

    # 11. Sunset (3)
    out += [
        m(
            "{{SUNSET_ALERT_COUNT}}",
            "list_tax_sunset_alerts",
            '{"as_of": "{current_date}", "window_months": 12}',
            "alerts.length",
            "0",
            "integer",
            "12ヶ月 sunset件数",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{SUNSET_NEXT_DATE}}",
            "list_tax_sunset_alerts",
            '{"as_of": "{current_date}", "window_months": 12}',
            "alerts[0].sunset_date",
            None,
            "date",
            "直近 sunset",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{SUNSET_NEXT_RULE}}",
            "list_tax_sunset_alerts",
            '{"as_of": "{current_date}", "window_months": 12}',
            "alerts[0].rule_name",
            None,
            "text",
            "sunset対象 rule",
            sensitive=1,
            license_="gov_standard",
        ),
    ]

    # 12. Adoption / similar cases (4)
    out += [
        m(
            "{{ADOPTION_COUNT}}",
            "search_acceptance_stats_am",
            PRG,
            "total_adopted",
            "0",
            "integer",
            "採択件数",
            license_="gov_standard",
        ),
        m(
            "{{ADOPTION_RATE}}",
            "search_acceptance_stats_am",
            PRG,
            "adoption_rate",
            None,
            "percentage",
            "採択率",
            license_="gov_standard",
        ),
        m(
            "{{ADOPTION_LATEST_DATE}}",
            "search_acceptance_stats_am",
            PRG,
            "latest_adoption_date",
            None,
            "date",
            "直近採択公表日",
            license_="gov_standard",
        ),
        m(
            "{{SIMILAR_CASES_TOP3}}",
            "similar_cases",
            '{"jsic_major": "{industry_jsic_major}", "prefecture": "{prefecture}", "limit": 3}',
            "cases",
            "[]",
            "json",
            "類似事例 top 3",
            license_="gov_standard",
        ),
    ]

    # 13. Exclusion / compatibility (3)
    out += [
        m(
            "{{EXCLUSION_COUNT}}",
            "check_exclusions",
            '{"program_ids": ["{program_id}"]}',
            "exclusions.length",
            "0",
            "integer",
            "排他ヒット数",
        ),
        m(
            "{{EXCLUSION_DETAIL}}",
            "check_exclusions",
            '{"program_ids": ["{program_id}"]}',
            "exclusions[0].detail",
            None,
            "text",
            "直近 排他 詳細",
        ),
        m(
            "{{COMPATIBILITY_SCORE}}",
            "program_compatibility_pair_am",
            '{"program_a": "{program_id}", "program_b": "{paired_program_id}"}',
            "score",
            None,
            "percentage",
            "互換性 score",
        ),
    ]

    # 14. Jurisdiction (3)
    out += [
        m(
            "{{JURISDICTION_HOUMU}}",
            "cross_check_jurisdiction",
            HJ,
            "houmu_kyoku",
            None,
            "text",
            "管轄 法務局",
            license_="pdl_v1.0",
        ),
        m(
            "{{JURISDICTION_ZEIMU}}",
            "cross_check_jurisdiction",
            HJ,
            "zeimu_sho",
            None,
            "text",
            "管轄 税務署",
            license_="pdl_v1.0",
        ),
        m(
            "{{JURISDICTION_DISCREPANCY}}",
            "cross_check_jurisdiction",
            HJ,
            "discrepancies",
            "[]",
            "list",
            "管轄不一致",
            license_="pdl_v1.0",
        ),
    ]

    # 15. Loan (4)
    out += [
        m(
            "{{LOAN_PRODUCT_NAME}}",
            "search_loans_am",
            '{"keyword": "{loan_keyword}"}',
            "loans[0].name",
            None,
            "text",
            "融資商品名",
            license_="gov_standard",
        ),
        m(
            "{{LOAN_INTEREST_RATE}}",
            "search_loans_am",
            '{"keyword": "{loan_keyword}"}',
            "loans[0].interest_rate",
            None,
            "percentage",
            "利率",
            license_="gov_standard",
        ),
        m(
            "{{LOAN_COLLATERAL_TYPE}}",
            "search_loans_am",
            '{"keyword": "{loan_keyword}"}',
            "loans[0].collateral_type",
            None,
            "enum",
            "担保種別",
            license_="gov_standard",
        ),
        m(
            "{{LOAN_AMOUNT_MAX}}",
            "search_loans_am",
            '{"keyword": "{loan_keyword}"}',
            "loans[0].amount_max_yen",
            None,
            "yen",
            "融資上限",
            license_="gov_standard",
        ),
    ]

    # 16. Deadline (3)
    out += [
        m(
            "{{DEADLINE_NEXT}}",
            "deadline_calendar",
            '{"anchor_date": "{current_date}"}',
            "deadlines[0].date",
            None,
            "date",
            "直近 deadline",
        ),
        m(
            "{{DEADLINE_NEXT_LABEL}}",
            "deadline_calendar",
            '{"anchor_date": "{current_date}"}',
            "deadlines[0].label",
            None,
            "text",
            "直近 label",
        ),
        m(
            "{{DEADLINE_ALL_JSON}}",
            "deadline_calendar",
            '{"anchor_date": "{current_date}"}',
            "deadlines",
            "[]",
            "json",
            "全 deadline list",
        ),
    ]

    # 17. Treaty / foreign capital (6)
    out += [
        m(
            "{{TREATY_COUNTRY}}",
            "context",
            "{}",
            "treaty_country",
            None,
            "text",
            "条約相手国",
            sensitive=1,
        ),
        m(
            "{{TREATY_DIVIDEND_RATE}}",
            "get_tax_treaty",
            '{"country": "{treaty_country}"}',
            "treaty.dividend_rate",
            None,
            "percentage",
            "配当税率",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TREATY_INTEREST_RATE}}",
            "get_tax_treaty",
            '{"country": "{treaty_country}"}',
            "treaty.interest_rate",
            None,
            "percentage",
            "利子税率",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{TREATY_ROYALTY_RATE}}",
            "get_tax_treaty",
            '{"country": "{treaty_country}"}',
            "treaty.royalty_rate",
            None,
            "percentage",
            "使用料税率",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{FOREIGN_CAPITAL_RATIO}}",
            "check_foreign_capital_eligibility",
            HJ,
            "foreign_capital_ratio",
            "0",
            "percentage",
            "外資比率",
            sensitive=1,
            license_="pdl_v1.0",
        ),
        m(
            "{{FOREIGN_CAPITAL_ELIGIBLE}}",
            "check_foreign_capital_eligibility",
            HJ,
            "eligible",
            "false",
            "boolean",
            "外資要件適合",
            sensitive=1,
            license_="pdl_v1.0",
        ),
    ]

    # 18. DD questions (3)
    out += [
        m(
            "{{DD_QUESTION_COUNT}}",
            "match_due_diligence_questions",
            '{"industry_jsic": "{industry_jsic_major}"}',
            "questions.length",
            "0",
            "integer",
            "DD件数",
            sensitive=1,
        ),
        m(
            "{{DD_QUESTION_LIST}}",
            "match_due_diligence_questions",
            '{"industry_jsic": "{industry_jsic_major}"}',
            "questions",
            "[]",
            "json",
            "DD全件",
            sensitive=1,
        ),
        m(
            "{{DD_TOP_SEVERITY}}",
            "match_due_diligence_questions",
            '{"industry_jsic": "{industry_jsic_major}"}',
            "questions[0].severity",
            None,
            "enum",
            "最重要 severity",
            sensitive=1,
        ),
    ]

    # 19. Corpus / health (3)
    out += [
        m(
            "{{CORPUS_SNAPSHOT_ID}}",
            "deep_health_am",
            "{}",
            "corpus_snapshot_id",
            None,
            "text",
            "corpus snapshot ID",
        ),
        m(
            "{{CORPUS_CHECKSUM}}",
            "deep_health_am",
            "{}",
            "corpus_checksum",
            None,
            "text",
            "corpus checksum",
        ),
        m("{{API_VERSION}}", "deep_health_am", "{}", "api_version", "v0.5.0", "text", "API 版"),
    ]

    # 20. Provenance (4)
    out += [
        m(
            "{{PROVENANCE_SOURCE_URL}}",
            "get_provenance",
            '{"entity_ids": ["{entity_id}"]}',
            "provenance[0].source_url",
            None,
            "url",
            "出典 URL",
        ),
        m(
            "{{PROVENANCE_FETCHED_AT}}",
            "get_provenance",
            '{"entity_ids": ["{entity_id}"]}',
            "provenance[0].fetched_at",
            None,
            "date",
            "出典 取得日",
        ),
        m(
            "{{PROVENANCE_LICENSE}}",
            "get_provenance",
            '{"entity_ids": ["{entity_id}"]}',
            "provenance[0].license",
            None,
            "enum",
            "出典 license",
        ),
        m(
            "{{PROVENANCE_AUTHORITY}}",
            "get_provenance",
            '{"entity_ids": ["{entity_id}"]}',
            "provenance[0].authority",
            None,
            "text",
            "出典 authority",
        ),
    ]

    # 21. Kit / scaffold (3)
    out += [
        m(
            "{{KIT_COVER_LETTER}}",
            "bundle_application_kit",
            '{"program_id": "{program_id}", "client_id": "{client_id}"}',
            "kit.cover_letter_scaffold",
            None,
            "text",
            "cover letter scaffold",
        ),
        m(
            "{{KIT_CHECKLIST}}",
            "bundle_application_kit",
            '{"program_id": "{program_id}", "client_id": "{client_id}"}',
            "kit.required_documents_checklist",
            "[]",
            "list",
            "必要書類",
            license_="gov_standard",
        ),
        m(
            "{{KIT_SIMILAR_CASES}}",
            "bundle_application_kit",
            '{"program_id": "{program_id}", "client_id": "{client_id}"}',
            "kit.similar_accepted_cases",
            "[]",
            "list",
            "類似採択事例",
            license_="gov_standard",
        ),
    ]

    # 22. Kessan briefing (2)
    out += [
        m(
            "{{KESSAN_BRIEFING_SUMMARY}}",
            "prepare_kessan_briefing",
            '{"client_id": "{client_id}", "fiscal_period": "{fiscal_year_month}"}',
            "briefing.summary",
            None,
            "text",
            "決算 briefing",
            sensitive=1,
        ),
        m(
            "{{KESSAN_AMENDMENT_DIFF}}",
            "prepare_kessan_briefing",
            '{"client_id": "{client_id}", "fiscal_period": "{fiscal_year_month}"}',
            "briefing.amendment_diff",
            "[]",
            "json",
            "改正 diff",
            sensitive=1,
        ),
    ]

    # 23. Route (4)
    out += [
        m(
            "{{ROUTE_RECOMMENDED}}",
            "jpcite_route",
            '{"intent": "{intent}"}',
            "recommended_tool",
            None,
            "text",
            "推奨 route tool",
        ),
        m(
            "{{ROUTE_PRICE_JPY}}",
            "jpcite_route",
            '{"intent": "{intent}"}',
            "estimated_price_jpy",
            "300",
            "yen",
            "推定 price",
        ),
        m(
            "{{ROUTE_PACKET_ID}}",
            "jpcite_route",
            '{"intent": "{intent}"}',
            "packet_id",
            None,
            "text",
            "packet ID",
        ),
        m(
            "{{ROUTE_SOURCE_DATASETS}}",
            "jpcite_route",
            '{"intent": "{intent}"}',
            "source_datasets",
            "[]",
            "list",
            "source datasets",
        ),
    ]

    # 24. Houjin 360 panel (2)
    out += [
        m(
            "{{HOUJIN_360_PANEL_URL}}",
            "get_houjin_360_am",
            HJ,
            "panel_url",
            None,
            "url",
            "panel URL",
        ),
        m(
            "{{HOUJIN_360_SCORE}}",
            "get_houjin_360_am",
            HJ,
            "score.total",
            None,
            "integer",
            "score 0-100",
        ),
    ]

    # 25. Search (3)
    out += [
        m("{{SEARCH_KEYWORD}}", "context", "{}", "search_keyword", None, "text", "検索 keyword"),
        m(
            "{{SEARCH_RESULTS_TOTAL}}",
            "search_programs",
            '{"keyword": "{search_keyword}"}',
            "total",
            "0",
            "integer",
            "検索 hits",
        ),
        m(
            "{{SEARCH_RESULTS_TOP3}}",
            "search_programs",
            '{"keyword": "{search_keyword}", "limit": 3}',
            "results",
            "[]",
            "json",
            "top 3",
        ),
    ]

    # 26. SIB scaffold (2 - sensitive)
    out += [
        m(
            "{{SIB_CONTRACT_NUMBER}}",
            "computed",
            '{"compute": "sib_unsupported"}',
            "$",
            "(社労士法 §27 のため scaffold のみ)",
            "text",
            "SIB契約番号 scaffold-only",
            sensitive=1,
        ),
        m(
            "{{SIB_CONTRACT_DATE}}",
            "computed",
            '{"compute": "sib_unsupported"}',
            "$",
            "(社労士確認後手書き)",
            "text",
            "SIB契約日 scaffold-only",
            sensitive=1,
        ),
    ]

    # 27. License / certification (4)
    out += [
        m("{{LICENSE_TYPE}}", "context", "{}", "license_type", None, "text", "許認可種別"),
        m(
            "{{LICENSE_EXPIRY_DATE}}",
            "context",
            "{}",
            "license_expiry_date",
            None,
            "date",
            "有効期限",
        ),
        m(
            "{{LICENSE_AUTHORITY}}",
            "search_certifications",
            '{"keyword": "{license_type}"}',
            "results[0].authority",
            None,
            "text",
            "所管庁",
            license_="gov_standard",
        ),
        m(
            "{{LICENSE_RENEWAL_FEE}}",
            "search_certifications",
            '{"keyword": "{license_type}"}',
            "results[0].renewal_fee_yen",
            None,
            "yen",
            "更新手数料",
            license_="gov_standard",
        ),
    ]

    # 28. Contract (3)
    out += [
        m("{{CONTRACT_TYPE}}", "context", "{}", "contract_type", None, "enum", "契約種別"),
        m(
            "{{CONTRACT_PARTIES}}",
            "context",
            "{}",
            "parties_houjin_bangou",
            "[]",
            "list",
            "当事者法人番号",
        ),
        m(
            "{{FORBIDDEN_CLAUSES_LIST}}",
            "rule_engine_check",
            '{"contract_type": "{contract_type}"}',
            "clauses",
            "[]",
            "json",
            "禁止条項 alerts",
            sensitive=1,
        ),
    ]

    # 29. Corporate setup (5)
    out += [
        m("{{NEW_COMPANY_NAME}}", "context", "{}", "new_company_name", None, "text", "新会社名"),
        m(
            "{{BUSINESS_PURPOSE}}",
            "context",
            "{}",
            "business_purpose",
            "[]",
            "list",
            "定款 事業目的",
        ),
        m(
            "{{FOUNDER_PROFILE_JSON}}",
            "context",
            "{}",
            "founder_profile",
            None,
            "json",
            "発起人 profile",
        ),
        m("{{CAPITAL_YEN_NEW}}", "context", "{}", "capital_yen", "1000000", "yen", "新会社 資本金"),
        m(
            "{{NAME_COLLISION_COUNT}}",
            "search_invoice_registrants",
            '{"company_name_keyword": "{new_company_name}"}',
            "total",
            "0",
            "integer",
            "同名既存法人",
            license_="pdl_v1.0",
        ),
    ]

    # 30. Director change (4)
    out += [
        m("{{DIRECTOR_CHANGE_TYPE}}", "context", "{}", "change_type", None, "enum", "役員変更種別"),
        m(
            "{{DIRECTOR_EFFECTIVE_DATE}}",
            "context",
            "{}",
            "effective_date",
            None,
            "date",
            "効力発生日",
        ),
        m(
            "{{DIRECTOR_NAME_NEW}}",
            "context",
            "{}",
            "new_director_profile.name",
            None,
            "text",
            "新役員氏名",
        ),
        m(
            "{{DIRECTOR_DEADLINE_2WEEK}}",
            "deadline_calendar",
            '{"anchor_date": "{effective_date}", "window_days": 14}',
            "deadlines[0].date",
            None,
            "date",
            "2週間期限",
        ),
    ]

    # 31. Real estate (4)
    out += [
        m(
            "{{PROPERTY_ADDRESS}}",
            "context",
            "{}",
            "property_address",
            None,
            "text",
            "不動産所在地",
        ),
        m("{{SALE_PRICE_YEN}}", "context", "{}", "sale_price_yen", None, "yen", "売買価格"),
        m(
            "{{REGISTRATION_TAX_YEN}}",
            "get_am_tax_rule",
            '{"keyword": "登録免許税"}',
            "rule.computed_amount_yen",
            None,
            "yen",
            "登録免許税概算",
            sensitive=1,
            license_="gov_standard",
        ),
        m(
            "{{ACQUISITION_TAX_YEN}}",
            "get_am_tax_rule",
            '{"keyword": "不動産取得税"}',
            "rule.computed_amount_yen",
            None,
            "yen",
            "不動産取得税概算",
            sensitive=1,
            license_="gov_standard",
        ),
    ]

    # 32. Watch list (2)
    out += [
        m(
            "{{WATCH_LIST_ID}}",
            "list_houjin_watch",
            '{"client_org_id": "{client_org_id}"}',
            "watch_lists[0].id",
            None,
            "text",
            "watch list ID",
        ),
        m(
            "{{WATCH_LIST_COUNT}}",
            "list_houjin_watch",
            '{"client_org_id": "{client_org_id}"}',
            "total",
            "0",
            "integer",
            "watch 対象数",
        ),
    ]

    # 33. API key / wallet (5)
    out += [
        m("{{API_KEY_PARENT_ID}}", "context", "{}", "parent_api_key", None, "text", "親 API key"),
        m(
            "{{API_KEY_CHILD_ID}}",
            "provision_child_api_key",
            '{"client_org_id": "{client_org_id}", "parent_api_key": "{parent_api_key}"}',
            "child_api_key_id",
            None,
            "text",
            "子 API key",
        ),
        m(
            "{{API_KEY_QUOTA_REMAINING}}",
            "get_usage_status",
            "{}",
            "remaining_quota",
            "0",
            "integer",
            "残 quota",
        ),
        m(
            "{{WALLET_ID}}",
            "create_credit_wallet",
            '{"client_org_id": "{client_org_id}"}',
            "wallet_id",
            None,
            "text",
            "wallet ID",
        ),
        m(
            "{{WALLET_BALANCE_YEN}}",
            "create_credit_wallet",
            '{"client_org_id": "{client_org_id}"}',
            "balance_jpy",
            "0",
            "yen",
            "wallet 残高",
        ),
    ]

    # 34. Recipe metadata (4)
    out += [
        m("{{RECIPE_NAME}}", "context", "{}", "recipe_name", None, "text", "recipe 名"),
        m(
            "{{RECIPE_STEPS_TOTAL}}",
            "get_recipe",
            '{"recipe_name": "{recipe_name}"}',
            "steps.length",
            "0",
            "integer",
            "step 数",
        ),
        m(
            "{{RECIPE_COST_JPY}}",
            "get_recipe",
            '{"recipe_name": "{recipe_name}"}',
            "cost_estimate_jpy",
            None,
            "yen",
            "推定 cost",
        ),
        m(
            "{{RECIPE_DURATION_SEC}}",
            "get_recipe",
            '{"recipe_name": "{recipe_name}"}',
            "expected_duration_seconds",
            None,
            "integer",
            "推定秒",
        ),
    ]

    # 35. Static / examples (2)
    out += [
        m(
            "{{STATIC_TAXONOMY_LIST}}",
            "list_static_resources_am",
            "{}",
            "resources",
            "[]",
            "list",
            "静的 taxonomy",
        ),
        m(
            "{{EXAMPLE_PROFILES_LIST}}",
            "list_example_profiles_am",
            "{}",
            "profiles",
            "[]",
            "list",
            "example profile",
        ),
    ]

    # 36. Federated (1)
    out += [
        m(
            "{{FEDERATED_PARTNER_LIST}}",
            "recommend_partner_for_gap",
            '{"capability_gap": "{capability_gap}"}',
            "partners",
            "[]",
            "json",
            "partner 推奨",
        ),
    ]

    # 37. Kokkai / Shingikai / Pubcomment (4)
    out += [
        m(
            "{{KOKKAI_UTTERANCE_LATEST}}",
            "search_kokkai_utterance",
            '{"keyword": "{policy_keyword}", "limit": 1}',
            "results[0].text",
            None,
            "text",
            "国会発言",
            license_="public_domain",
        ),
        m(
            "{{SHINGIKAI_MINUTES_LATEST}}",
            "search_shingikai_minutes",
            '{"keyword": "{policy_keyword}", "limit": 1}',
            "results[0].text",
            None,
            "text",
            "審議会議事録",
            license_="public_domain",
        ),
        m(
            "{{PUBCOMMENT_STATUS}}",
            "get_pubcomment_status",
            '{"keyword": "{policy_keyword}"}',
            "status",
            None,
            "enum",
            "パブコメ status",
            license_="cc_by_4.0",
        ),
        m(
            "{{PUBCOMMENT_DEADLINE}}",
            "get_pubcomment_status",
            '{"keyword": "{policy_keyword}"}',
            "deadline_date",
            None,
            "date",
            "パブコメ deadline",
            license_="cc_by_4.0",
        ),
    ]

    # 38. Municipality (1)
    out += [
        m(
            "{{MUNICIPALITY_SUBSIDY_TOP1}}",
            "search_municipality_subsidies",
            '{"prefecture": "{prefecture}", "municipality": "{municipality}"}',
            "results[0].name",
            None,
            "text",
            "自治体補助金 top 1",
            license_="gov_standard",
        ),
    ]

    # 39. NTA corpus (2)
    out += [
        m(
            "{{SAIKETSU_LATEST_DOCKET}}",
            "find_saiketsu",
            '{"keyword": "{search_keyword}", "limit": 1}',
            "results[0].docket",
            None,
            "text",
            "裁決 docket",
            sensitive=1,
            license_="public_domain",
        ),
        m(
            "{{SHITSUGI_LATEST}}",
            "find_shitsugi",
            '{"keyword": "{search_keyword}", "limit": 1}',
            "results[0].q",
            None,
            "text",
            "国税庁質疑応答",
            sensitive=1,
            license_="gov_standard",
        ),
    ]

    # 40. URLs (3)
    out += [
        m(
            "{{LLMS_TXT_URL}}",
            "computed",
            '{"compute": "llms_txt_url"}',
            "$",
            "https://jpcite.com/llms.txt",
            "url",
            "llms.txt URL",
        ),
        m(
            "{{OPENAPI_URL}}",
            "computed",
            '{"compute": "openapi_url"}',
            "$",
            "https://jpcite.com/docs/openapi/v1.json",
            "url",
            "OpenAPI URL",
        ),
        m(
            "{{MCP_ENDPOINT_URL}}",
            "computed",
            '{"compute": "mcp_endpoint_url"}',
            "$",
            "https://mcp.jpcite.com",
            "url",
            "MCP endpoint",
        ),
    ]

    # 41. Operator identity (3)
    out += [
        m(
            "{{COVENANT_AUTHORITY}}",
            "computed",
            '{"compute": "covenant_authority"}',
            "$",
            "Bookyou株式会社 (T8010001213708)",
            "text",
            "operator id",
        ),
        m(
            "{{OPERATOR_NAME}}",
            "computed",
            '{"compute": "operator_name"}',
            "$",
            "Bookyou株式会社",
            "text",
            "operator 法人名",
        ),
        m(
            "{{OPERATOR_INVOICE_T}}",
            "computed",
            '{"compute": "operator_invoice_t"}',
            "$",
            "T8010001213708",
            "text",
            "operator T番号",
        ),
    ]

    # 42. Disclaimer (6 - all sensitive)
    out += [
        m(
            "{{DISCLAIMER_TAX}}",
            "computed",
            '{"compute": "disclaimer_tax"}',
            "$",
            "§52 (税理士法) 候補リスト/参考資料のみ。最終判定は税理士。",
            "text",
            "§52 disclaimer",
            sensitive=1,
        ),
        m(
            "{{DISCLAIMER_AUDIT}}",
            "computed",
            '{"compute": "disclaimer_audit"}',
            "$",
            "§47条の2 (公認会計士法) 監査意見表明は会計士独占。本資料は調書補助。",
            "text",
            "§47条の2 disclaimer",
            sensitive=1,
        ),
        m(
            "{{DISCLAIMER_GYOUSEI}}",
            "computed",
            '{"compute": "disclaimer_gyousei"}',
            "$",
            "§1 (行政書士法) 申請書面作成は独占業務。本資料は scaffold + 一次 URL のみ。",
            "text",
            "§1 disclaimer",
            sensitive=1,
        ),
        m(
            "{{DISCLAIMER_SHIHOSHOSHI}}",
            "computed",
            '{"compute": "disclaimer_shihoshoshi"}',
            "$",
            "§3 (司法書士法) 登記申請書面は司法書士独占。本資料は scaffold + 一次 URL のみ。",
            "text",
            "§3 disclaimer",
            sensitive=1,
        ),
        m(
            "{{DISCLAIMER_BENGOSHI}}",
            "computed",
            '{"compute": "disclaimer_bengoshi"}',
            "$",
            "§72 (弁護士法) 紛争性ある契約は弁護士業務。本資料は非紛争 + 一次 URL のみ。",
            "text",
            "§72 disclaimer",
            sensitive=1,
        ),
        m(
            "{{DISCLAIMER_SHAROUSHI}}",
            "computed",
            '{"compute": "disclaimer_sharoushi"}',
            "$",
            "§27 (社労士法) 労働社会保険諸法令書類作成は社労士独占。本資料は scaffold のみ。",
            "text",
            "社労士法 §27 disclaimer",
            sensitive=1,
        ),
    ]

    # 43. Cohort / region (5)
    out += [
        m(
            "{{COHORT_AVG_REVENUE_YEN}}",
            "benchmark_cohort_average_am",
            '{"jsic_major": "{industry_jsic_major}", "size_band": "{revenue_band}", "prefecture": "{prefecture}"}',
            "cohort.avg_revenue_yen",
            None,
            "yen",
            "同cohort 平均売上",
            license_="gov_standard",
        ),
        m(
            "{{COHORT_AVG_EMPLOYEES}}",
            "benchmark_cohort_average_am",
            '{"jsic_major": "{industry_jsic_major}", "size_band": "{revenue_band}", "prefecture": "{prefecture}"}',
            "cohort.avg_employees",
            None,
            "integer",
            "同cohort 平均従業員",
            license_="gov_standard",
        ),
        m(
            "{{COHORT_TOP10_OUTLIER}}",
            "benchmark_cohort_average_am",
            '{"jsic_major": "{industry_jsic_major}", "size_band": "{revenue_band}", "prefecture": "{prefecture}"}',
            "cohort.top10_outlier",
            "[]",
            "json",
            "top 10% outlier",
            license_="gov_standard",
        ),
        m("{{REGION_CODE}}", "context", "{}", "region_code", None, "text", "am_region.code 5桁"),
        m(
            "{{REGION_NAME_JA}}",
            "programs_by_region_am",
            '{"code": "{region_code}"}',
            "region.name_ja",
            None,
            "text",
            "region 日本語名",
            license_="gov_standard",
        ),
    ]

    # 44. Bids / kessan_review_flag / policy upstream (5)
    out += [
        m(
            "{{BIDS_LATEST_TITLE}}",
            "search_programs",
            '{"keyword": "入札", "limit": 1}',
            "results[0].name",
            None,
            "text",
            "直近入札 title",
            license_="gov_standard",
        ),
        m(
            "{{BIDS_LATEST_DEADLINE}}",
            "search_programs",
            '{"keyword": "入札", "limit": 1}',
            "results[0].application_deadline",
            None,
            "date",
            "直近入札 締切",
            license_="gov_standard",
        ),
        m(
            "{{KESSAN_REVIEW_FLAG}}",
            "computed",
            '{"compute": "kessan_review_required"}',
            "$",
            "review_required",
            "enum",
            "always review_required",
            sensitive=1,
        ),
        m(
            "{{POLICY_UPSTREAM_TIMELINE}}",
            "policy_upstream_timeline",
            '{"keyword": "{policy_keyword}"}',
            "timeline",
            "[]",
            "json",
            "上流 signal timeline",
            license_="public_domain",
        ),
        m(
            "{{POLICY_UPSTREAM_WATCH}}",
            "policy_upstream_watch",
            '{"keyword": "{policy_keyword}"}',
            "signals",
            "[]",
            "json",
            "上流 watch",
            license_="public_domain",
        ),
    ]

    # 45. Succession (1)
    out += [
        m(
            "{{SUCCESSION_PLAYBOOK}}",
            "succession_playbook_am",
            HJ,
            "playbook",
            None,
            "json",
            "事業承継 playbook",
            sensitive=1,
        ),
    ]

    # 46. Evidence packet (2)
    out += [
        m(
            "{{EVIDENCE_PACKET_ID}}",
            "get_evidence_packet",
            '{"entity_id": "{entity_id}"}',
            "packet.id",
            None,
            "text",
            "evidence packet ID",
        ),
        m(
            "{{EVIDENCE_PACKET_SHA}}",
            "get_evidence_packet",
            '{"entity_id": "{entity_id}"}',
            "packet.sha256",
            None,
            "text",
            "evidence sha256",
        ),
    ]

    # 47. Tax chain (1)
    out += [
        m(
            "{{TAX_CHAIN_FULL}}",
            "tax_rule_full_chain",
            '{"rule_id": "{tax_rule_id}"}',
            "chain",
            "[]",
            "json",
            "tax 全 chain",
            sensitive=1,
            license_="gov_standard",
        ),
    ]

    # 48. Fact signature (2)
    out += [
        m(
            "{{FACT_SIGNATURE_HEX}}",
            "fact_signature_verify_am",
            '{"fact_id": "{fact_id}"}',
            "signature.hex",
            None,
            "text",
            "Ed25519 signature",
        ),
        m(
            "{{FACT_VERIFY_RESULT}}",
            "fact_signature_verify_am",
            '{"fact_id": "{fact_id}"}',
            "verified",
            "false",
            "boolean",
            "fact 検証結果",
        ),
    ]

    # 49. Shihoshoshi DD (1)
    out += [
        m(
            "{{SHIHOSHOSHI_DD_PACK}}",
            "shihoshoshi_dd_pack_am",
            HJ,
            "pack",
            None,
            "json",
            "司法書士 DD pack",
            sensitive=1,
        ),
    ]

    # 50. Invoice risk (2)
    out += [
        m(
            "{{INVOICE_RISK_SCORE}}",
            "invoice_risk_lookup",
            HJ,
            "risk_score",
            None,
            "integer",
            "invoice risk 0-100",
            sensitive=1,
            license_="pdl_v1.0",
        ),
        m(
            "{{INVOICE_TAX_CREDIT_ELIGIBLE}}",
            "invoice_risk_lookup",
            HJ,
            "tax_credit_eligible",
            "false",
            "boolean",
            "仕入税額控除 適格",
            sensitive=1,
            license_="pdl_v1.0",
        ),
    ]

    return out


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    mappings = _mappings()
    payload = {
        "_metadata": {
            "lane": "N9",
            "wave": "wave24_206",
            "version": "v1",
            "generated_at": "2026-05-17",
            "license": "jpcite-scaffold-cc0",
            "description": (
                "Canonical 1:1 binding from placeholder_name -> (mcp_tool_name, "
                "args_template, output_path). Companion to lane N1 (am_artifact_templates) "
                "and N8 (data/recipes/). NO LLM resolution."
            ),
            "total_entries": len(mappings),
            "value_kinds": [
                "text",
                "yen",
                "date",
                "boolean",
                "list",
                "json",
                "enum",
                "wareki",
                "integer",
                "percentage",
                "url",
            ],
        },
        "mappings": mappings,
    }
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(mappings)} placeholder mappings to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
