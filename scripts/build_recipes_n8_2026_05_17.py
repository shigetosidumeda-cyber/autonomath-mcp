#!/usr/bin/env python3
"""Lane N8 — generate 15 recipe YAML files under data/recipes/.

Idempotent: re-running overwrites the existing 15 yaml files. Designed to
be invoked after a fresh checkout / PC restart that wiped the untracked
data/recipes/ directory.

5 segments × 3 scenarios = 15 recipes:

  - 税理士 (tax): monthly_closing / year_end_adjustment / corporate_filing
  - 会計士 (audit): workpaper_compile / internal_control / consolidation
  - 行政書士 (gyousei): subsidy_application_draft / license_renewal /
    contract_compliance_check
  - 司法書士 (shihoshoshi): corporate_setup_registration /
    director_change_registration / real_estate_transfer
  - AX エンジニア / FDE (ax_fde): client_onboarding /
    domain_expertise_transfer / compliance_dashboard

NO LLM. Pure Python generator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = REPO_ROOT / "data" / "recipes"


def _emit_yaml(recipe: dict[str, Any]) -> str:
    """Emit a recipe dict as the YAML-subset shape moat_n8 expects.

    The shape is deliberately strict: top-level scalar keys, list-of-dict
    for ``steps``, 2-space indent for nested blocks. JSON braces are
    avoided in favour of YAML indentation so the moat_n8 parser handles
    every file.
    """
    lines: list[str] = []
    for k, v in recipe.items():
        if isinstance(v, list) and k == "steps":
            lines.append(f"{k}:")
            for step in v:
                first = True
                for sk, sv in step.items():
                    if first:
                        lines.append(f"  - {sk}: {_fmt(sv)}")
                        first = False
                    else:
                        if isinstance(sv, dict):
                            lines.append(f"    {sk}:")
                            for kk, vv in sv.items():
                                lines.append(f"      {kk}: {_fmt(vv)}")
                        else:
                            lines.append(f"    {sk}: {_fmt(sv)}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_fmt(item)}")
        elif isinstance(v, dict):
            lines.append(f"{k}:")
            for kk, vv in v.items():
                if isinstance(vv, list):
                    lines.append(f"  {kk}:")
                    for item in vv:
                        lines.append(f"    - {_fmt(item)}")
                else:
                    lines.append(f"  {kk}: {_fmt(vv)}")
        else:
            lines.append(f"{k}: {_fmt(v)}")
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    s = str(value)
    # Quote if value contains ':' or starts with special chars; else bare.
    if any(
        ch in s for ch in (":", "#", "@", "&", "*", "!", "%", "?", "|", ">", "<")
    ) or s.startswith(("-", "[", "{")):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _step(
    n: int,
    tool_name: str,
    purpose: str,
    args: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step": n,
        "tool_name": tool_name,
        "purpose": purpose,
        "args": args or {},
        "expected_output_schema": schema or {"results": "array"},
    }


# ---------------------------------------------------------------------------
# Recipe definitions (15 total)
# ---------------------------------------------------------------------------


def _r_tax_monthly_closing() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_tax_monthly_closing",
        "segment": "tax",
        "title": "月次決算 jpcite call sequence (税理士)",
        "disclaimer": "§52 (税理士法) — 候補リスト/参考資料のみ提供。最終的な月次決算判定は税理士が責任を負う。",
        "preconditions": [
            "client_id",
            "houjin_bangou",
            "fiscal_year_month (YYYY-MM)",
            "target_ruleset_ids (optional)",
            "business_profile",
        ],
        "expected_duration_seconds": 60,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 39,
        "billable_units": 13,
        "output_artifact": {
            "type": "monthly_closing_packet",
            "format": "json",
            "fields": [
                "applied_tax_rules",
                "amendment_diff_in_window",
                "exclusion_warnings",
                "cross_check_jurisdiction",
                "audit_seal_pack_id",
                "evidence_packet",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "vocabulary canonicalize"),
            _step(2, "search_tax_incentives", "適用候補 surface"),
            _step(3, "evaluate_tax_applicability", "rule x profile bulk 判定"),
            _step(4, "track_amendment_lineage_am", "当月までの改正/通達 diff"),
            _step(5, "prepare_kessan_briefing", "月次 briefing"),
            _step(6, "check_exclusions", "排他 / 併給"),
            _step(7, "cross_check_jurisdiction", "登記/適格/採択 整合性"),
            _step(8, "search_invoice_registrants", "適格事業者 status"),
            _step(9, "list_tax_sunset_alerts", "sunset alerts"),
            _step(10, "compose_audit_workpaper", "workpaper PDF + audit_seal"),
            _step(11, "jpcite_route", "outcome route"),
            _step(12, "get_provenance", "出典 + license"),
            _step(13, "deep_health_am", "snapshot pin"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_tax_year_end_adjustment() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_tax_year_end_adjustment",
        "segment": "tax",
        "title": "年末調整一括処理 jpcite call sequence (税理士)",
        "disclaimer": "§52 (税理士法) — 年末調整事務の補助のみ。最終判定は税理士。",
        "preconditions": [
            "client_id",
            "tax_year (YYYY)",
            "profile_ids (顧問先 client_profiles 配列)",
        ],
        "expected_duration_seconds": 90,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 42,
        "billable_units": 14,
        "output_artifact": {
            "type": "year_end_adjustment_packet",
            "format": "json",
            "fields": [
                "applicable_tax_rules",
                "amendment_diff_yoy",
                "sunset_alerts",
                "fan_out_saved_searches",
                "workpaper_pdf_url",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "tax_rule_kind closed-set"),
            _step(2, "list_tax_sunset_alerts", "当年末 cliff"),
            _step(3, "search_tax_incentives", "年末調整 候補"),
            _step(4, "get_am_tax_rule", "rule 詳細"),
            _step(5, "track_amendment_lineage_am", "YoY 改正"),
            _step(6, "bundle_application_kit", "扶養控除等 scaffold"),
            _step(7, "prepare_kessan_briefing", "確定申告 briefing"),
            _step(8, "compose_audit_workpaper", "顧問先別 PDF"),
            _step(9, "dispatch_audit_seal_webhook", "audit_seal 配信"),
            _step(10, "get_provenance", "出典"),
            _step(11, "check_exclusions", "控除併用可否"),
            _step(12, "jpcite_route", "outcome route"),
            _step(13, "deep_health_am", "snapshot pin"),
            _step(14, "jpcite_preview_cost", "予算試算"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_tax_corporate_filing() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_tax_corporate_filing",
        "segment": "tax",
        "title": "法人税申告書作成 jpcite call sequence (税理士)",
        "disclaimer": "§52 (税理士法) — 申告書作成は税理士の独占業務。本レシピは参考資料のみ。",
        "preconditions": [
            "client_id",
            "houjin_bangou",
            "fiscal_year_end (YYYY-MM-DD)",
            "business_profile",
        ],
        "expected_duration_seconds": 120,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 54,
        "billable_units": 18,
        "output_artifact": {
            "type": "corporate_filing_evidence_packet",
            "format": "json",
            "fields": [
                "applied_tax_rules",
                "rd_credit_eligibility",
                "loss_carryforward_window",
                "exclusion_matrix",
                "workpaper_pdf_url",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "closed-set"),
            _step(2, "search_tax_incentives", "適用候補"),
            _step(3, "get_am_tax_rule", "rule 詳細"),
            _step(4, "evaluate_tax_applicability", "bulk 判定"),
            _step(5, "search_acceptance_stats_am", "同業種 採択率"),
            _step(6, "track_amendment_lineage_am", "YoY 改正"),
            _step(7, "list_tax_sunset_alerts", "FY 内 sunset"),
            _step(8, "search_loans_am", "融資/特例"),
            _step(9, "check_enforcement_am", "行政処分 履歴"),
            _step(10, "cross_check_jurisdiction", "整合性"),
            _step(11, "check_exclusions", "排他"),
            _step(12, "prepare_kessan_briefing", "確定申告 briefing"),
            _step(13, "compose_audit_workpaper", "workpaper PDF"),
            _step(14, "bundle_application_kit", "添付 scaffold"),
            _step(15, "get_provenance", "出典"),
            _step(16, "jpcite_route", "outcome route"),
            _step(17, "deep_health_am", "snapshot pin"),
            _step(18, "jpcite_execute_packet", "route 実行"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_audit_workpaper_compile() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_audit_workpaper_compile",
        "segment": "audit",
        "title": "監査調書編纂 jpcite call sequence (公認会計士)",
        "disclaimer": "§47条の2 (公認会計士法) — 監査意見表明は会計士の独占業務。本レシピは調書補助のみ。",
        "preconditions": [
            "audit_firm_id",
            "client_id",
            "houjin_bangou",
            "audit_period (YYYY or YYYY-Q1..Q4)",
        ],
        "expected_duration_seconds": 90,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 42,
        "billable_units": 14,
        "output_artifact": {
            "type": "audit_workpaper_pdf",
            "format": "pdf+json",
            "fields": [
                "workpaper_pdf_url",
                "audit_seal_pack_id",
                "corpus_snapshot_id",
                "corpus_checksum",
                "provenance_chain",
            ],
        },
        "steps": [
            _step(1, "deep_health_am", "snapshot pin"),
            _step(2, "enum_values_am", "vocab"),
            _step(3, "search_tax_incentives", "適用候補"),
            _step(4, "get_am_tax_rule", "rule 詳細"),
            _step(5, "evaluate_tax_applicability", "profile x rule"),
            _step(6, "track_amendment_lineage_am", "期間中 改正"),
            _step(7, "cross_check_jurisdiction", "整合性"),
            _step(8, "check_enforcement_am", "履歴"),
            _step(9, "match_due_diligence_questions", "DD 質問 deck"),
            _step(10, "get_provenance", "出典"),
            _step(11, "check_exclusions", "排他"),
            _step(12, "compose_audit_workpaper", "調書 PDF"),
            _step(13, "dispatch_audit_seal_webhook", "audit_seal 配信"),
            _step(14, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_audit_internal_control() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_audit_internal_control",
        "segment": "audit",
        "title": "内部統制評価 jpcite call sequence (公認会計士)",
        "disclaimer": "§47条の2 (公認会計士法) + 金商法 J-SOX — IT/業務 統制評価補助のみ。",
        "preconditions": [
            "audit_firm_id",
            "client_id",
            "houjin_bangou",
            "audit_period",
        ],
        "expected_duration_seconds": 90,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 36,
        "billable_units": 12,
        "output_artifact": {
            "type": "internal_control_evaluation_packet",
            "format": "json",
            "fields": [
                "control_deficiencies",
                "dd_question_deck",
                "enforcement_history",
                "jurisdiction_discrepancies",
                "workpaper_pdf_url",
            ],
        },
        "steps": [
            _step(1, "deep_health_am", "snapshot pin"),
            _step(2, "match_due_diligence_questions", "DD 統制軸"),
            _step(3, "check_enforcement_am", "履歴"),
            _step(4, "cross_check_jurisdiction", "整合性"),
            _step(5, "search_invoice_registrants", "適格 status"),
            _step(6, "search_acceptance_stats_am", "ベンチマーク"),
            _step(7, "track_amendment_lineage_am", "金商法/会社法 改正"),
            _step(8, "forecast_program_renewal", "renewal cadence"),
            _step(9, "get_provenance", "出典"),
            _step(10, "compose_audit_workpaper", "統制評価 workpaper"),
            _step(11, "dispatch_audit_seal_webhook", "audit_seal 配信"),
            _step(12, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_audit_consolidation() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_audit_consolidation",
        "segment": "audit",
        "title": "連結手続書 jpcite call sequence (公認会計士)",
        "disclaimer": "§47条の2 (公認会計士法) — 連結監査意見表明は会計士独占。",
        "preconditions": [
            "audit_firm_id",
            "parent_houjin_bangou",
            "subsidiary_houjin_bangou (array)",
            "audit_period",
            "consolidation_scope",
        ],
        "expected_duration_seconds": 120,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 54,
        "billable_units": 18,
        "output_artifact": {
            "type": "consolidation_evidence_packet",
            "format": "json",
            "fields": [
                "subsidiary_360_panel",
                "tax_treaty_matrix",
                "foreign_capital_eligibility",
                "inter_company_transactions_review",
                "workpaper_pdf_url",
            ],
        },
        "steps": [
            _step(1, "deep_health_am", "snapshot pin"),
            _step(2, "get_houjin_360_am", "親法人 360"),
            _step(3, "get_houjin_360_am", "子法人 360"),
            _step(4, "cross_check_jurisdiction", "親子 jurisdiction"),
            _step(5, "check_enforcement_am", "親子 履歴"),
            _step(6, "get_tax_treaty", "treaty matrix"),
            _step(7, "check_foreign_capital_eligibility", "外資要件"),
            _step(8, "get_law_article_am", "会計基準/J-SOX 引用"),
            _step(9, "track_amendment_lineage_am", "連結会計 改正"),
            _step(10, "search_acceptance_stats_am", "ベンチマーク"),
            _step(11, "match_due_diligence_questions", "DD 連結軸"),
            _step(12, "check_exclusions", "親子 排他"),
            _step(13, "prepare_kessan_briefing", "連結決算 briefing"),
            _step(14, "get_provenance", "出典"),
            _step(15, "compose_audit_workpaper", "連結調書 PDF"),
            _step(16, "dispatch_audit_seal_webhook", "audit_seal 配信"),
            _step(17, "jpcite_route", "outcome route"),
            _step(18, "jpcite_preview_cost", "cost preview"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_subsidy_application_draft() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_subsidy_application_draft",
        "segment": "gyousei",
        "title": "補助金申請書 draft jpcite call sequence (行政書士)",
        "disclaimer": "§1 (行政書士法) — 申請書面作成は行政書士の独占業務。本レシピは scaffold + 一次 URL のみ。",
        "preconditions": [
            "client_id",
            "houjin_bangou",
            "target_program_id (or keyword)",
            "applicant_profile",
        ],
        "expected_duration_seconds": 75,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 39,
        "billable_units": 13,
        "output_artifact": {
            "type": "application_kit_scaffold",
            "format": "json",
            "fields": [
                "program_metadata",
                "cover_letter_scaffold",
                "required_documents_checklist",
                "similar_accepted_cases",
                "exclusion_warnings",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "closed-set"),
            _step(2, "search_programs", "候補 FTS5"),
            _step(3, "program_full_context", "詳細 + 法令 + 通達"),
            _step(4, "program_lifecycle", "active period"),
            _step(5, "prerequisite_chain", "前提 chain"),
            _step(6, "similar_cases", "採択事例"),
            _step(7, "rule_engine_check", "eligibility"),
            _step(8, "check_exclusions", "併給"),
            _step(9, "bundle_application_kit", "scaffold + checklist"),
            _step(10, "check_enforcement_am", "履歴 chip"),
            _step(11, "deadline_calendar", "申請期限"),
            _step(12, "get_provenance", "出典"),
            _step(13, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_license_renewal() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_license_renewal",
        "segment": "gyousei",
        "title": "許認可更新 jpcite call sequence (行政書士)",
        "disclaimer": "§1 (行政書士法) — 許認可申請書面作成 独占業務。",
        "preconditions": [
            "client_id",
            "houjin_bangou",
            "license_type",
            "license_expiry_date",
            "jurisdiction",
        ],
        "expected_duration_seconds": 60,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 33,
        "billable_units": 11,
        "output_artifact": {
            "type": "license_renewal_kit",
            "format": "json",
            "fields": [
                "license_metadata",
                "required_documents_checklist",
                "deadline_calendar",
                "enforcement_history",
                "cross_jurisdiction_warnings",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "license_type closed-set"),
            _step(2, "search_certifications", "該当 認証/許認可"),
            _step(3, "program_full_context", "更新要件 詳細"),
            _step(4, "prerequisite_chain", "更新 前提 chain"),
            _step(5, "check_enforcement_am", "履歴 chip"),
            _step(6, "cross_check_jurisdiction", "jurisdiction"),
            _step(7, "bundle_application_kit", "更新 scaffold"),
            _step(8, "deadline_calendar", "更新期限"),
            _step(9, "track_amendment_lineage_am", "業法 改正"),
            _step(10, "get_provenance", "出典"),
            _step(11, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_contract_compliance_check() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_contract_compliance_check",
        "segment": "gyousei",
        "title": "契約 compliance check jpcite call sequence (行政書士)",
        "disclaimer": "§72 (弁護士法) / §1 (行政書士法) — 紛争性ある契約は弁護士業務。",
        "preconditions": [
            "client_id",
            "contract_type",
            "parties_houjin_bangou (array)",
            "jurisdiction",
        ],
        "expected_duration_seconds": 60,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 33,
        "billable_units": 11,
        "output_artifact": {
            "type": "compliance_check_packet",
            "format": "json",
            "fields": [
                "applicable_laws",
                "forbidden_clauses_alerts",
                "similar_court_decisions",
                "enforcement_history_panel",
                "cross_jurisdiction_warnings",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "contract_type closed-set"),
            _step(2, "search_by_law", "該当 law surface"),
            _step(3, "get_law_article_am", "条文"),
            _step(4, "search_acceptance_stats_am", "類似事例"),
            _step(5, "track_amendment_lineage_am", "法改正"),
            _step(6, "check_enforcement_am", "履歴 chip"),
            _step(7, "search_invoice_registrants", "適格 status"),
            _step(8, "cross_check_jurisdiction", "jurisdiction"),
            _step(9, "rule_engine_check", "禁止条項 detect"),
            _step(10, "get_provenance", "出典"),
            _step(11, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_corporate_setup_registration() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_corporate_setup_registration",
        "segment": "shihoshoshi",
        "title": "会社設立登記一式 jpcite call sequence (司法書士)",
        "disclaimer": "§3 (司法書士法) — 登記申請書面 独占業務。",
        "preconditions": [
            "founder_profile",
            "new_company_name",
            "business_purpose (array)",
            "prefecture",
            "capital_yen",
        ],
        "expected_duration_seconds": 90,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 39,
        "billable_units": 13,
        "output_artifact": {
            "type": "corporate_setup_kit",
            "format": "json",
            "fields": [
                "applicable_laws",
                "required_documents",
                "similar_company_names_check",
                "applicable_subsidies_post_setup",
                "tax_registration_calendar",
            ],
        },
        "steps": [
            _step(1, "enum_values_am", "target_type"),
            _step(2, "get_law_article_am", "会社法 §25-§103"),
            _step(3, "get_law_article_am", "商業登記法 §17-§24"),
            _step(4, "search_certifications", "設立後 補助金"),
            _step(5, "similar_cases", "設立後 採択事例"),
            _step(6, "search_invoice_registrants", "同名 chip"),
            _step(7, "check_enforcement_am", "代表者 履歴"),
            _step(8, "prerequisite_chain", "設立 前提 chain"),
            _step(9, "bundle_application_kit", "scaffold"),
            _step(10, "deadline_calendar", "設立後 calendar"),
            _step(11, "track_amendment_lineage_am", "会社法 改正"),
            _step(12, "get_provenance", "出典"),
            _step(13, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_director_change_registration() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_director_change_registration",
        "segment": "shihoshoshi",
        "title": "役員変更登記 jpcite call sequence (司法書士)",
        "disclaimer": "§3 (司法書士法) — 登記申請 独占業務。",
        "preconditions": [
            "houjin_bangou",
            "change_type",
            "effective_date",
            "new_director_profile",
        ],
        "expected_duration_seconds": 45,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 27,
        "billable_units": 9,
        "output_artifact": {
            "type": "director_change_kit",
            "format": "json",
            "fields": [
                "applicable_law_articles",
                "required_documents_checklist",
                "deadline_alert",
                "similar_houjin_360_view",
                "enforcement_chip_on_new_director",
            ],
        },
        "steps": [
            _step(1, "get_law_article_am", "会社法 §329-§341"),
            _step(2, "get_law_article_am", "商業登記法 §54"),
            _step(3, "get_houjin_360_am", "法人 360"),
            _step(4, "check_enforcement_am", "新役員 履歴"),
            _step(5, "cross_check_jurisdiction", "法務局 jurisdiction"),
            _step(6, "bundle_application_kit", "変更登記 scaffold"),
            _step(7, "deadline_calendar", "2週間以内"),
            _step(8, "track_amendment_lineage_am", "会社法 改正"),
            _step(9, "get_provenance", "出典"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_real_estate_transfer() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_real_estate_transfer",
        "segment": "shihoshoshi",
        "title": "不動産売買登記 jpcite call sequence (司法書士)",
        "disclaimer": "§3 (司法書士法) — 登記申請 独占業務。紛争性ある場合 §72 弁護士業務。",
        "preconditions": [
            "seller_profile",
            "buyer_profile",
            "property_address",
            "sale_price_yen",
            "contract_date",
        ],
        "expected_duration_seconds": 60,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 33,
        "billable_units": 11,
        "output_artifact": {
            "type": "real_estate_transfer_kit",
            "format": "json",
            "fields": [
                "applicable_law_articles",
                "required_documents_checklist",
                "tax_calendar",
                "similar_recent_court_decisions",
                "cross_check_houjin_360",
            ],
        },
        "steps": [
            _step(1, "get_law_article_am", "不動産登記法 §16-§30"),
            _step(2, "get_law_article_am", "民法 §555-§585"),
            _step(3, "search_acceptance_stats_am", "類似 判例"),
            _step(4, "get_houjin_360_am", "法人当事者 360"),
            _step(5, "check_enforcement_am", "履歴 chip"),
            _step(6, "search_tax_incentives", "登録免許税 軽減"),
            _step(7, "get_am_tax_rule", "不動産取得税"),
            _step(8, "bundle_application_kit", "所有権移転登記 scaffold"),
            _step(9, "deadline_calendar", "税務 calendar"),
            _step(10, "track_amendment_lineage_am", "不登法/民法 改正"),
            _step(11, "get_provenance", "出典"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_client_onboarding() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_client_onboarding",
        "segment": "ax_fde",
        "title": "Client onboarding 統合 (AX エンジニア / FDE)",
        "disclaimer": "¥3/req metered。AX エンジニアは 5 分で integration 完了。",
        "preconditions": [
            "client_org_id",
            "target_segment",
            "desired_outcome_slugs (array)",
            "mcp_client_runtime",
        ],
        "expected_duration_seconds": 60,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 27,
        "billable_units": 9,
        "output_artifact": {
            "type": "onboarding_handoff_packet",
            "format": "json",
            "fields": [
                "configured_mcp_endpoint_url",
                "api_key_parent_child_pair",
                "recommended_recipes_subset",
                "billing_wallet_initial_state",
                "smoke_test_evidence",
            ],
        },
        "steps": [
            _step(1, "deep_health_am", "pre-flight"),
            _step(2, "list_recipes", "segment 別 recipe"),
            _step(3, "get_recipe", "各 outcome の recipe"),
            _step(4, "jpcite_preview_cost", "予算試算"),
            _step(5, "get_usage_status", "親 quota"),
            _step(6, "provision_child_api_key", "顧客 sub-key"),
            _step(7, "create_credit_wallet", "前払い wallet"),
            _step(8, "list_static_resources_am", "静的 taxonomy"),
            _step(9, "list_example_profiles_am", "example profile"),
            _step(10, "jpcite_route", "outcome ごと route"),
            _step(11, "deep_health_am", "post-wire smoke"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_domain_expertise_transfer() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_domain_expertise_transfer",
        "segment": "ax_fde",
        "title": "Domain expertise transfer to client agent (AX / FDE)",
        "disclaimer": "¥3/req metered。jpcite Evidence/Recipe を client agent に転送。",
        "preconditions": [
            "client_agent_runtime",
            "target_segment",
            "desired_skills (array)",
        ],
        "expected_duration_seconds": 75,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 30,
        "billable_units": 10,
        "output_artifact": {
            "type": "skill_transfer_handoff",
            "format": "json",
            "fields": [
                "configured_recipes",
                "composable_tool_recommendations",
                "llms_txt_subset_export",
                "openapi_agent_subset",
                "federated_mcp_recommendations",
            ],
        },
        "steps": [
            _step(1, "list_recipes", "segment 全 recipe"),
            _step(2, "get_recipe", "各 skill ごと recipe"),
            _step(3, "list_static_resources_am", "静的 taxonomy"),
            _step(4, "list_example_profiles_am", "example profile"),
            _step(5, "deep_health_am", "snapshot pin"),
            _step(6, "get_provenance", "出典 chain"),
            _step(7, "jpcite_route", "route 推奨"),
            _step(8, "jpcite_preview_cost", "cost preview"),
            _step(9, "resolve_placeholder", "テンプレート placeholder 解決"),
            _step(10, "get_artifact_template", "scaffold 取得"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


def _r_compliance_dashboard() -> dict[str, Any]:
    return {
        "recipe_name": "recipe_compliance_dashboard",
        "segment": "ax_fde",
        "title": "Compliance dashboard 統合 (AX エンジニア / FDE)",
        "disclaimer": "¥3/req metered。多顧客 compliance kpi を 1 dashboard に集約。",
        "preconditions": [
            "client_org_id",
            "tracked_houjin_bangou_list",
            "kpi_axes",
            "refresh_cadence",
        ],
        "expected_duration_seconds": 90,
        "parallel_calls_supported": True,
        "cost_estimate_jpy": 60,
        "billable_units": 20,
        "output_artifact": {
            "type": "compliance_dashboard_packet",
            "format": "json",
            "fields": [
                "enforcement_panel",
                "invoice_compliance_panel",
                "amendment_diff_panel",
                "sunset_alerts_panel",
                "cross_jurisdiction_warnings",
                "houjin_360_summary",
                "corpus_snapshot_id",
            ],
        },
        "steps": [
            _step(1, "deep_health_am", "snapshot pin"),
            _step(2, "check_enforcement_am", "全顧問先 行政処分"),
            _step(3, "search_invoice_registrants", "適格 status batch"),
            _step(4, "track_amendment_lineage_am", "直近 改正"),
            _step(5, "list_tax_sunset_alerts", "sunset / cliff"),
            _step(6, "cross_check_jurisdiction", "整合性"),
            _step(7, "get_houjin_360_am", "法人 360 batch"),
            _step(8, "forecast_program_renewal", "renewal cadence"),
            _step(9, "dispatch_audit_seal_webhook", "webhook 配信"),
            _step(10, "get_provenance", "出典 chain"),
            _step(11, "jpcite_preview_cost", "cost preview"),
            _step(12, "jpcite_route", "outcome route"),
        ],
        "no_llm_required": True,
        "mypy_strict_safe": True,
    }


_RECIPES = (
    _r_tax_monthly_closing,
    _r_tax_year_end_adjustment,
    _r_tax_corporate_filing,
    _r_audit_workpaper_compile,
    _r_audit_internal_control,
    _r_audit_consolidation,
    _r_subsidy_application_draft,
    _r_license_renewal,
    _r_contract_compliance_check,
    _r_corporate_setup_registration,
    _r_director_change_registration,
    _r_real_estate_transfer,
    _r_client_onboarding,
    _r_domain_expertise_transfer,
    _r_compliance_dashboard,
)


def main() -> int:
    RECIPE_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for builder in _RECIPES:
        recipe = builder()
        path = RECIPE_DIR / f"{recipe['recipe_name']}.yaml"
        path.write_text(_emit_yaml(recipe), encoding="utf-8")
        written += 1
    print(f"wrote {written} recipes to {RECIPE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
