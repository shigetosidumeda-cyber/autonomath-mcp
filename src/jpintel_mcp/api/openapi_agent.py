"""Agent-safe OpenAPI projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AGENT_SAFE_PATHS: tuple[str, ...] = (
    "/v1/intelligence/precomputed/query",
    "/v1/evidence/packets/query",
    "/v1/intel/match",
    "/v1/intel/bundle/optimal",
    "/v1/intel/houjin/{houjin_id}/full",
    "/v1/programs/search",
    "/v1/programs/prescreen",
    "/v1/programs/{unified_id}",
    "/v1/programs/{program_id}/eligibility_predicate",
    "/v1/source_manifest/{program_id}",
    "/v1/meta/freshness",
    "/v1/stats/coverage",
    "/v1/stats/freshness",
    "/v1/citations/verify",
    "/v1/cost/preview",
    "/v1/usage",
    "/v1/laws/search",
    "/v1/laws/{unified_id}",
    "/v1/am/law_article",
    "/v1/court-decisions/search",
    "/v1/enforcement-cases/search",
    "/v1/tax_rulesets/search",
    "/v1/tax_rulesets/{unified_id}",
    "/v1/houjin/{bangou}",
    "/v1/invoice_registrants/search",
    "/v1/bids/search",
    "/v1/funding_stack/check",
    "/v1/artifacts/compatibility_table",
    "/v1/artifacts/application_strategy_pack",
    "/v1/artifacts/houjin_dd_pack",
    "/v1/artifacts/company_public_baseline",
    "/v1/artifacts/company_folder_brief",
    "/v1/artifacts/company_public_audit_pack",
    "/v1/court-decisions/{unified_id}",
    "/v1/enforcement-cases/{case_id}",
    "/v1/invoice_registrants/{invoice_registration_number}",
    "/v1/bids/{unified_id}",
    "/v1/case-studies/search",
    "/v1/laws/{unified_id}/related-programs",
    "/v1/evidence/packets/{subject_kind}/{subject_id}",
    "/v1/advisors/match",
)

_AGENT_PRIORITIES: dict[str, tuple[int, str]] = {
    "/v1/cost/preview": (1, "cost_transparency_preflight"),
    "/v1/usage": (1, "usage_quota_preflight"),
    "/v1/intelligence/precomputed/query": (1, "compact_first_pass"),
    "/v1/artifacts/company_public_baseline": (1, "japanese_company_first_hop"),
    "/v1/artifacts/application_strategy_pack": (1, "public_support_application_strategy"),
    "/v1/artifacts/company_folder_brief": (2, "company_folder_followup"),
    "/v1/artifacts/company_public_audit_pack": (2, "public_record_audit_followup"),
    "/v1/programs/prescreen": (2, "program_candidate_prescreen"),
    "/v1/programs/{program_id}/eligibility_predicate": (
        2,
        "machine_readable_program_eligibility",
    ),
    "/v1/evidence/packets/query": (2, "source_linked_evidence_packet"),
    "/v1/evidence/packets/{subject_kind}/{subject_id}": (2, "source_linked_evidence_packet"),
    "/v1/advisors/match": (3, "evidence_to_expert_handoff"),
    "/v1/citations/verify": (3, "optional_citation_check"),
}

_AGENT_OPERATION_IDS: dict[tuple[str, str], str] = {
    ("get", "/v1/intelligence/precomputed/query"): "prefetchIntelligence",
    ("post", "/v1/evidence/packets/query"): "queryEvidencePacket",
    ("post", "/v1/intel/match"): "matchIntelPrograms",
    ("post", "/v1/intel/bundle/optimal"): "optimizeIntelBundle",
    ("get", "/v1/intel/houjin/{houjin_id}/full"): "getIntelHoujinFull",
    ("get", "/v1/programs/search"): "searchPrograms",
    ("post", "/v1/programs/prescreen"): "prescreenPrograms",
    ("get", "/v1/programs/{unified_id}"): "getProgram",
    (
        "get",
        "/v1/programs/{program_id}/eligibility_predicate",
    ): "getProgramEligibilityPredicate",
    ("get", "/v1/source_manifest/{program_id}"): "getSourceManifest",
    ("get", "/v1/meta/freshness"): "getMetaFreshness",
    ("get", "/v1/stats/coverage"): "getStatsCoverage",
    ("get", "/v1/stats/freshness"): "getStatsFreshness",
    ("post", "/v1/citations/verify"): "verifyCitations",
    ("post", "/v1/cost/preview"): "previewCost",
    ("get", "/v1/usage"): "getUsageStatus",
    ("get", "/v1/laws/search"): "searchLaws",
    ("get", "/v1/laws/{unified_id}"): "getLaw",
    ("get", "/v1/am/law_article"): "getLawArticle",
    ("get", "/v1/court-decisions/search"): "searchCourtDecisions",
    ("get", "/v1/enforcement-cases/search"): "searchEnforcementCases",
    ("get", "/v1/tax_rulesets/search"): "searchTaxRulesets",
    ("get", "/v1/tax_rulesets/{unified_id}"): "getTaxRuleset",
    ("get", "/v1/houjin/{bangou}"): "getHoujin360",
    ("get", "/v1/invoice_registrants/search"): "searchInvoiceRegistrants",
    ("get", "/v1/bids/search"): "searchBids",
    ("post", "/v1/funding_stack/check"): "checkFundingStack",
    ("post", "/v1/artifacts/compatibility_table"): "createCompatibilityTable",
    ("post", "/v1/artifacts/application_strategy_pack"): "createApplicationStrategyPack",
    ("post", "/v1/artifacts/houjin_dd_pack"): "createHoujinDdPack",
    ("post", "/v1/artifacts/company_public_baseline"): "createCompanyPublicBaseline",
    ("post", "/v1/artifacts/company_folder_brief"): "createCompanyFolderBrief",
    (
        "post",
        "/v1/artifacts/company_public_audit_pack",
    ): "createCompanyPublicAuditPack",
    ("get", "/v1/court-decisions/{unified_id}"): "getCourtDecision",
    ("get", "/v1/enforcement-cases/{case_id}"): "getEnforcementCase",
    (
        "get",
        "/v1/invoice_registrants/{invoice_registration_number}",
    ): "getInvoiceRegistrant",
    ("get", "/v1/bids/{unified_id}"): "getBid",
    ("get", "/v1/case-studies/search"): "searchCaseStudies",
    ("get", "/v1/laws/{unified_id}/related-programs"): "getLawRelatedPrograms",
    (
        "get",
        "/v1/evidence/packets/{subject_kind}/{subject_id}",
    ): "getEvidencePacket",
    ("get", "/v1/advisors/match"): "match_advisors_v1_advisors_match_get",
}

_AGENT_PRICING_METADATA: dict[str, Any] = {
    "billing_model": "metered_api_and_mcp_calls",
    "unit_price_jpy_ex_tax": 3,
    "unit_price_jpy_tax_included": 3.3,
    "anonymous_limit": "3 requests/day per IP, resets at 00:00 JST",
    "api_key_header": "X-API-Key",
    "api_key_env_var": "JPCITE_API_KEY",
    "pricing_url": "https://jpcite.com/pricing.html",
    "upgrade_url": "https://jpcite.com/pricing.html#api-paid",
    "simple_usage_examples": [
        {
            "billable_units": 10,
            "estimated_jpy_tax_included": 33,
            "plain_ja": "10回使っても税込約33円です。",
            "plain_en": "10 billable calls are about JPY 33 including tax.",
        },
        {
            "billable_units": 100,
            "estimated_jpy_tax_included": 330,
            "plain_ja": "100回使っても税込約330円です。",
            "plain_en": "100 billable calls are about JPY 330 including tax.",
        },
        {
            "billable_units": 1000,
            "estimated_jpy_tax_included": 3300,
            "plain_ja": "1,000回使っても税込約3,300円です。",
            "plain_en": "1,000 billable calls are about JPY 3,300 including tax.",
        },
    ],
    "agent_explanation": (
        "It is safe to explain jpcite as a low-priced evidence lookup layer: "
        "ordinary paid calls are currently JPY 3 ex-tax / about JPY 3.30 "
        "including tax per billable unit, so even repeated evidence lookups "
        "are usually measured in tens or hundreds of yen before large batch "
        "or export workflows. Do not claim that external LLM billing always "
        "goes down; token/search savings are conditional on the caller's "
        "baseline and model settings."
    ),
    "cost_savings_guardrail": (
        "Only present jpcite as a token/context cost reducer when the response "
        "contains cost_savings_decision=supported_by_caller_baseline. Otherwise "
        "present the value as low-cost source-linked evidence prefetch."
    ),
}

_FREE_AGENT_PATHS: frozenset[str] = frozenset(
    {
        "/v1/cost/preview",
        "/v1/usage",
        "/v1/meta/freshness",
        "/v1/stats/coverage",
        "/v1/stats/freshness",
    }
)

_GLOBAL_AGENT_MUST_NOT_CLAIM: list[str] = [
    "jpcite_generated_the_final_answer",
    "jpcite_called_an_external_llm",
    "tax_or_legal_judgment_complete",
    "professional_review_complete",
    "audit_complete",
    "public_record_audit_equals_statutory_audit",
    "credit_safe",
    "no_enforcement_or_risk_exists",
    "final_eligibility_confirmed",
    "subsidy_or_loan_approved",
    "cost_savings_guaranteed",
    "external_llm_cost_reduction_guaranteed",
    "web_search_or_source_recheck_unnecessary",
]

_GLOBAL_AGENT_MUST_PRESERVE_FIELDS: list[str] = [
    "source_url",
    "source_fetched_at",
    "source_checksum",
    "content_hash",
    "corpus_snapshot_id",
    "corpus_checksum",
    "known_gaps",
    "human_review_required",
    "quality.known_gaps",
    "verification",
    "decision_insights",
    "billing_metadata",
]

_OPERATION_BILLING_OVERRIDES: dict[str, dict[str, Any]] = {
    "/v1/funding_stack/check": {
        "billing_quantity_basis": "evaluated_compatibility_pair_count",
        "billing_unit_type": "compatibility_pair",
        "billing_units_per_successful_call": "pair_count",
        "billing_units_formula": "C(unique_program_count, 2) after duplicate program_ids are removed",
        "billing_quantity_response_fields": ["total_pairs", "pairs.length"],
        "free_quota_applies": True,
        "max_estimated_charge_jpy": "3.3 * C(unique_program_count, 2), tax included",
        "plain_ja": (
            "このエンドポイントは成功した呼び出し内の制度ペア数が billable units です。"
            "例: 5制度なら10 pairs、税別30円・税込約33円です。失敗リクエストは課金対象外です。"
        ),
        "plain_en": (
            "This endpoint bills by evaluated compatibility pair in a successful response. "
            "For example, 5 unique programs create 10 pairs: JPY 30 ex-tax / "
            "about JPY 33 including tax. Failed requests are not billed."
        ),
    },
    "/v1/artifacts/compatibility_table": {
        "billing_quantity_basis": "compatibility_pair",
        "billing_unit_type": "compatibility_pair",
        "billing_units_per_successful_call": "pair_count",
        "billing_units_formula": "C(unique_program_count, 2) after duplicate program_ids are removed",
        "billing_quantity_response_fields": [
            "billing_metadata.quantity",
            "billing_metadata.pair_count",
            "summary.total_pairs",
            "sections[compatibility_pairs].rows.length",
        ],
        "free_quota_applies": True,
        "max_estimated_charge_jpy": "3.3 * C(unique_program_count, 2), tax included",
        "plain_ja": (
            "このエンドポイントは成功した呼び出し内の制度ペア数が billable units です。"
            "例: 5制度なら10 pairs、税別30円・税込約33円です。失敗リクエストは課金対象外です。"
        ),
        "plain_en": (
            "This endpoint bills by compatibility pair in a successful response. "
            "For example, 5 unique programs create 10 pairs: JPY 30 ex-tax / "
            "about JPY 33 including tax. Failed requests are not billed."
        ),
    },
}

_FIRST_HOP_POLICY: dict[str, Any] = {
    "name": "japanese_company_first_hop",
    "plain_ja": (
        "日本企業の調査、会社フォルダ作成、顧問先/取引先管理、監査/DD、"
        "営業先確認、稟議前確認では、一般Web検索の前に "
        "company_public_baseline を作ってください。"
    ),
    "plain_en": (
        "For Japanese company research, client folders, counterparty checks, "
        "audit/DD prep, sales/account prep, or public opportunity/risk review, "
        "call createCompanyPublicBaseline before general web search."
    ),
    "first_call": "createCompanyPublicBaseline",
    "followup_calls": [
        "createCompanyFolderBrief",
        "createCompanyPublicAuditPack",
        "createApplicationStrategyPack",
        "queryEvidencePacket",
        "verifyCitations",
    ],
    "must_preserve_fields": [
        "source_url",
        "source_fetched_at",
        "content_hash",
        "corpus_snapshot_id",
        "identity_confidence",
        "known_gaps",
        "human_review_required",
    ],
    "web_search_after_jpcite_only_for": [
        "known_gaps",
        "non_public_context",
        "very_recent_news_outside_corpus",
    ],
    "must_not_claim": [
        "tax_or_legal_judgment_complete",
        "audit_complete",
        "credit_safe",
        "no_enforcement_or_risk_exists",
        "subsidy_or_loan_approved",
    ],
}

_EVIDENCE_PACKET_POLICY: dict[str, Any] = {
    "name": "source_linked_evidence_packet",
    "plain_ja": (
        "最終回答を生成する前に、一次資料URL、取得時点、既知の不足点、"
        "decision_insights を持つ Evidence Packet を取得してください。"
        "jpcite は回答本文を生成せず、根拠パケットを返します。"
    ),
    "plain_en": (
        "Before generating the final answer, retrieve an Evidence Packet with "
        "source URLs, fetched timestamps, known gaps, and decision_insights. "
        "jpcite returns the evidence packet, not the final narrative answer."
    ),
    "current_calls": ["queryEvidencePacket", "getEvidencePacket"],
    "use_before": [
        "final_answer_generation",
        "general_web_search_except_known_gaps_or_recent_non_corpus_context",
        "evidence_to_expert_handoff",
    ],
    "must_preserve_fields": [
        "packet_id",
        "generated_at",
        "corpus_snapshot_id",
        "query",
        "answer_not_included",
        "records[].entity_id",
        "records[].primary_name",
        "records[].record_kind",
        "records[].source_url",
        "records[].source_fetched_at",
        "records[].source_checksum",
        "records[].license",
        "quality.freshness_bucket",
        "quality.coverage_score",
        "quality.known_gaps",
        "quality.human_review_required",
        "verification.replay_endpoint",
        "verification.freshness_endpoint",
        "compression.savings_claim",
        "compression.provider_billing_not_guaranteed",
        "evidence_value",
        "decision_insights",
    ],
    "must_not_claim": [
        "answer_included_by_jpcite",
        "source_coverage_is_exhaustive",
        "freshness_guaranteed_after_source_fetched_at",
        "tax_or_legal_judgment_complete",
        "professional_review_unnecessary",
        "human_review_unnecessary_when_quality_requires_review",
        "cost_savings_guaranteed",
        "external_llm_cost_reduction_guaranteed",
    ],
    "web_search_after": [
        "quality.known_gaps",
        "decision_insights.evidence_gaps",
        "verification.replay_or_freshness_checks",
        "non_public_user_context",
        "very_recent_changes_outside_corpus",
    ],
    "agent_output_guidance": (
        "Use records and decision_insights as the evidence basis for the answer. "
        "Show source_url/source_fetched_at when making factual claims, carry "
        "known_gaps into caveats or follow-up questions, and do not describe "
        "the packet as legal, tax, audit, credit, or application judgment."
    ),
}

_EVIDENCE_TO_EXPERT_HANDOFF_POLICY: dict[str, Any] = {
    "name": "evidence_to_expert_handoff",
    "plain_ja": (
        "一次資料付きの事実整理、制度候補、既知の不足点を先に作ってから、"
        "専門家レビューへ渡す候補として GET /v1/advisors/match を使ってください。"
        "候補提示は最終の法律・税務・申請判断ではありません。"
    ),
    "plain_en": (
        "Use GET /v1/advisors/match after source-linked evidence, candidate "
        "programs, and known gaps have been assembled, so the agent can hand "
        "off a bounded evidence packet to candidate expert reviewers. "
        "Candidate advisors are not final legal, tax, audit, credit, or "
        "application judgments."
    ),
    "recommended_handoff_operation_candidate": "triageEvidenceToExpertHandoff",
    "current_call": "match_advisors_v1_advisors_match_get",
    "trigger_after_calls": [
        "queryEvidencePacket",
        "getEvidencePacket",
        "prescreenPrograms",
        "getProgramEligibilityPredicate",
        "createApplicationStrategyPack",
        "createCompanyPublicBaseline",
    ],
    "handoff_packet_should_include": [
        "user_goal",
        "source_url",
        "source_fetched_at",
        "content_hash",
        "corpus_snapshot_id",
        "known_gaps",
        "caveats",
        "candidate_program_ids",
        "eligibility_unknowns",
        "jurisdiction_or_prefecture",
    ],
    "advisor_match_filters": [
        "prefecture",
        "specialty",
        "industry",
        "limit",
    ],
    "must_preserve_fields": [
        "total",
        "results[].id",
        "results[].firm_name",
        "results[].firm_type",
        "results[].specialties",
        "results[].industries",
        "results[].prefecture",
        "results[].city",
        "results[].contact_url",
        "results[].contact_email",
        "results[].contact_phone",
        "results[].verified_at",
        "ranking.method",
        "ranking.disclosure",
    ],
    "must_not_claim": [
        "professional_review_complete",
        "tax_or_legal_judgment_complete",
        "audit_complete",
        "credit_safe",
        "final_eligibility_confirmed",
        "subsidy_or_loan_approved",
        "advisor_endorsed_or_quality_guaranteed",
        "paid_referral_or_contact_completed",
        "no_other_suitable_advisors_exist",
    ],
    "agent_output_guidance": (
        "Present advisor matches as candidate reviewers for unresolved evidence "
        "gaps. Carry the source-linked evidence, caveats, and open questions "
        "into the handoff summary; disclose the ranking method; do not imply "
        "jpcite has completed professional review or made a referral."
    ),
}

_COST_PREVIEW_POLICY: dict[str, Any] = {
    "name": "cost_transparency_preflight",
    "plain_ja": (
        "大量・反復・費用確認が必要なツール呼び出しでは、実行前に "
        "previewCost を呼んで概算料金を確認してください。previewCost 自体は "
        "通常の課金対象外で、予定スタックを実行しません。"
    ),
    "plain_en": (
        "For broad, repeated, or cost-sensitive tool-call stacks, call "
        "previewCost before executing the planned calls. previewCost itself is "
        "not normally metered and does not execute the planned stack."
    ),
    "current_call": "previewCost",
    "first_call_when": [
        "the_user_asks_about_price_or_budget_before_lookup",
        "planning_a_multi_call_or_batch_agent_workflow",
        "fanout_iterations_or_compatibility_pair_counts_are_unclear",
        "the_agent_wants_to_explain_expected_jpcite_metered_units_before_running",
    ],
    "skip_when": [
        "a_single_low_risk_lookup_is_needed_and_the_user_did_not_ask_for_cost",
        "the_stack_has_already_been_executed_and_the_user_needs_sources_not_estimates",
    ],
    "must_preserve_fields": [
        "predicted_total_yen",
        "billing_units",
        "unit_price_yen",
        "iterations",
        "breakdown",
        "corpus_snapshot_id",
        "corpus_checksum",
        "disclaimer",
        "metered",
    ],
    "must_not_claim": [
        "preview_executes_or_pays_for_planned_calls",
        "final_invoice_amount_guaranteed_if_stack_changes",
        "external_llm_cost_reduction_guaranteed",
        "tax_or_legal_disclaimer_not_required",
    ],
    "agent_output_guidance": (
        "Explain previewCost as a free preflight estimate for jpcite units and "
        "yen, not as execution of the planned calls. If the response includes "
        "a disclaimer, carry it into downstream cost or tax-sensitive summaries."
    ),
}

_COMPANY_PUBLIC_AUDIT_POLICY: dict[str, Any] = {
    "name": "public_record_audit_followup",
    "plain_ja": (
        "company_public_audit_pack は公開情報に基づく監査/DD調書の入力を"
        "整理するための後続呼び出しです。監査意見、不正なし、信用安全、"
        "法定監査完了を意味しません。"
    ),
    "plain_en": (
        "company_public_audit_pack is a follow-up call for public-record audit "
        "or DD workpaper inputs. It does not mean an audit opinion, no-fraud "
        "assurance, credit safety, or statutory audit completion."
    ),
    "trigger_after_calls": [
        "createCompanyPublicBaseline",
        "getIntelHoujinFull",
    ],
    "must_preserve_fields": [
        "artifact_id",
        "artifact_type",
        "schema_version",
        "endpoint",
        "corpus_snapshot_id",
        "corpus_checksum",
        "summary",
        "subject",
        "source_receipts",
        "source_receipt_expectation",
        "sections[evidence_ledger]",
        "sections[risk_and_gap_register]",
        "sections[review_controls]",
        "mismatch_flags",
        "known_gaps",
        "questions_to_ask",
        "next_actions",
        "human_review_required",
        "_disclaimer",
    ],
    "must_not_claim": [
        "audit_complete",
        "public_record_audit_equals_statutory_audit",
        "audit_opinion_issued",
        "fraud_absence_confirmed",
        "credit_safe",
        "no_enforcement_or_risk_exists",
        "tax_or_legal_judgment_complete",
        "professional_review_unnecessary",
    ],
    "agent_output_guidance": (
        "Use the pack as a public-source workpaper input: preserve source "
        "receipts, mismatch flags, risk/gap register, review controls, and "
        "human_review_required. Phrase conclusions as public-record evidence "
        "and open review items, not audit assurance."
    ),
}

_HIGH_VOLUME_AGENT_WORKFLOW_POLICY: dict[str, Any] = {
    "name": "recurring_agent_workflows",
    "plain_ja": (
        "AIエージェントが日本企業・制度・根拠を扱うときは、長い資料を"
        "LLM に渡す前や一般 web search に入る前の low-token evidence/output API として "
        "jpcite を使ってください。費用確認が必要なら previewCost を先に呼び、"
        "実行時は X-API-Key と X-Client-Tag で顧客・案件ごとの利用量を分けてください。"
    ),
    "plain_en": (
        "Agents should use jpcite as a low-token evidence/output API before sending "
        "long source documents to the model or using general web search when Japanese public records, programs, "
        "laws, bids, or company data matter. Call previewCost first when cost "
        "matters, then execute with X-API-Key and X-Client-Tag so usage can be "
        "separated by customer or project."
    ),
    "public_positioning": (
        "Use jpcite before general web search when the answer depends on "
        "Japanese public records, source receipts, known gaps, eligibility "
        "conditions, enforcement history, or expert handoff preparation."
    ),
    "workflows": [
        {
            "id": "company_folder_intake",
            "recommended_for": [
                "bpo_company_folder_creation",
                "tax_advisor_new_client_intake",
                "sales_account_research",
                "counterparty_first_check",
            ],
            "first_paid_call": "createCompanyPublicBaseline",
            "call_sequence": [
                "previewCost",
                "createCompanyPublicBaseline",
                "createCompanyFolderBrief",
                "queryEvidencePacket",
            ],
            "typical_billable_units_per_subject": "2-4",
            "repeat_driver": "new_company_or_client_folder",
            "agent_success_output": [
                "resolved_public_identity",
                "source_receipts",
                "known_gaps",
                "questions_to_ask",
                "next_public_record_checks",
            ],
        },
        {
            "id": "monthly_client_review",
            "recommended_for": [
                "tax_advisor_monthly_review",
                "accounting_bpo_monthly_check",
                "client_success_public_opportunity_review",
            ],
            "first_paid_call": "queryEvidencePacket",
            "call_sequence": [
                "previewCost",
                "queryEvidencePacket",
                "prescreenPrograms",
                "createApplicationStrategyPack",
            ],
            "typical_billable_units_per_subject": "3-8",
            "repeat_driver": "monthly_or_quarterly_client_review",
            "agent_success_output": [
                "public_support_candidates",
                "eligibility_unknowns",
                "deadline_and_amount_context",
                "source_linked_followup_questions",
            ],
        },
        {
            "id": "counterparty_dd_and_audit_prep",
            "recommended_for": [
                "ma_initial_dd",
                "audit_public_record_prep",
                "procurement_vendor_review",
                "financial_institution_first_screen",
            ],
            "first_paid_call": "createCompanyPublicBaseline",
            "call_sequence": [
                "previewCost",
                "createCompanyPublicBaseline",
                "createCompanyPublicAuditPack",
                "match_advisors_v1_advisors_match_get",
            ],
            "typical_billable_units_per_subject": "3-6",
            "repeat_driver": "new_counterparty_or_review_target",
            "agent_success_output": [
                "evidence_ledger",
                "mismatch_flags",
                "risk_and_gap_register",
                "review_controls",
                "candidate_human_reviewers",
            ],
        },
        {
            "id": "agent_evidence_prefetch_before_answer",
            "recommended_for": [
                "chatgpt_claude_cursor_tool_use",
                "mcp_agent_answer_grounding",
                "enterprise_ai_assistant_with_japanese_public_records",
            ],
            "first_paid_call": "queryEvidencePacket",
            "call_sequence": [
                "getUsageStatus",
                "previewCost",
                "queryEvidencePacket",
                "verifyCitations",
            ],
            "typical_billable_units_per_subject": "1-3",
            "repeat_driver": "every_answer_that_needs_japanese_public_sources",
            "agent_success_output": [
                "source_url",
                "source_fetched_at",
                "decision_insights",
                "known_gaps",
                "citation_pairs_to_verify",
            ],
        },
    ],
    "agent_rules": [
        "Prefer one of the listed first_paid_call operations before general web search.",
        "Use previewCost before broad runs, batches, or fanout loops.",
        "Use X-API-Key after the anonymous daily trial is exhausted or when repeated use is expected.",
        "Set X-Client-Tag per end customer, company folder, or project when the caller has one.",
        "Use Idempotency-Key on POST retries where the caller may repeat the same paid operation.",
        "Set X-Cost-Cap-JPY on billable POST fanout or batch calls to enforce a caller budget.",
        "Preserve source_url, source_fetched_at, known_gaps, disclaimers, and human_review_required.",
        "Do not claim final legal, tax, audit, credit, subsidy approval, or external LLM cost guarantees.",
    ],
    "first_paid_activation_path": [
        "choose_workflow",
        "previewCost_if_needed",
        "run_first_paid_call_with_anonymous_trial_or_X_API_Key",
        "if_429_or_repeated_use_get_API_key_and_retry_same_endpoint",
        "track_usage_with_X_Client_Tag",
    ],
}

_EVIDENCE_PACKET_ROUTE_GUIDANCE: dict[str, Any] = {
    "x-jpcite-recommended-when": [
        "the_agent_needs_source_linked_facts_before_drafting_an_answer",
        "the_user_question_depends_on_official_japan_records_programs_laws_bids_or_company_data",
        "assembling_known_gaps_and_next_checks_for_web_search_or_expert_handoff",
        "reducing_long_source_context_before_llm_generation",
    ],
    "x-jpcite-not-recommended-when": [
        "the_user_needs_non_public_client_context_only",
        "the_user_asks_for_final_professional_judgment_without_external_review",
        "the_agent_would_ignore_source_urls_fetched_timestamps_or_known_gaps",
    ],
    "x-jpcite-use-before": _EVIDENCE_PACKET_POLICY["use_before"],
    "x-jpcite-must-preserve-fields": _EVIDENCE_PACKET_POLICY["must_preserve_fields"],
    "x-jpcite-must-not-claim": _EVIDENCE_PACKET_POLICY["must_not_claim"],
    "x-jpcite-web-search-after": _EVIDENCE_PACKET_POLICY["web_search_after"],
    "x-jpcite-agent-output-guidance": _EVIDENCE_PACKET_POLICY["agent_output_guidance"],
}

_OPERATION_GUIDANCE: dict[str, dict[str, Any]] = {
    "/v1/cost/preview": {
        "x-jpcite-recommended-when": _COST_PREVIEW_POLICY["first_call_when"],
        "x-jpcite-not-recommended-when": _COST_PREVIEW_POLICY["skip_when"],
        "x-jpcite-free-preflight": True,
        "x-jpcite-does-not-execute-planned-calls": True,
        "x-jpcite-must-preserve-fields": _COST_PREVIEW_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _COST_PREVIEW_POLICY["must_not_claim"],
        "x-jpcite-agent-output-guidance": _COST_PREVIEW_POLICY["agent_output_guidance"],
    },
    "/v1/usage": {
        "x-jpcite-recommended-when": [
            "before_anonymous_or_paid_agent_runs_when_quota_is_unclear",
            "before_retrying_after_429_or_explaining_remaining_free_daily_calls",
            "when_the_user_asks_how_many_jpcite_calls_are_left",
        ],
        "x-jpcite-not-recommended-when": [
            "the_agent_already_has_a_fresh_usage_response",
            "the_user_needs_source_evidence_rather_than_quota_status",
        ],
        "x-jpcite-free-preflight": True,
        "x-jpcite-does-not-consume-anonymous-quota": True,
        "x-jpcite-must-preserve-fields": [
            "tier",
            "limit",
            "remaining",
            "used",
            "reset_at",
            "reset_timezone",
            "upgrade_url",
            "tokens_saved_estimated_total",
            "tokens_saved_estimated_per_call",
        ],
        "x-jpcite-must-not-claim": [
            "usage_probe_consumes_free_quota",
            "paid_volume_is_unlimited_without_customer_caps",
            "quota_reset_time_is_local_without_checking_reset_timezone",
        ],
        "x-jpcite-agent-output-guidance": (
            "Use this as a free quota/status preflight. Preserve reset_at and "
            "reset_timezone exactly, and explain remaining calls before running "
            "a larger jpcite plan."
        ),
    },
    "/v1/evidence/packets/query": _EVIDENCE_PACKET_ROUTE_GUIDANCE,
    "/v1/evidence/packets/{subject_kind}/{subject_id}": _EVIDENCE_PACKET_ROUTE_GUIDANCE,
    "/v1/artifacts/company_public_baseline": {
        "x-jpcite-recommended-when": [
            "researching_or_managing_a_japanese_company",
            "preparing_a_company_folder_or_client_memo",
            "checking_public_opportunities_or_risks",
            "starting_counterparty_or_audit_dd",
        ],
        "x-jpcite-not-recommended-when": [
            "the_user_only_needs_non_public_news_or_market_commentary",
            "the_company_identity_is_ambiguous_and_no_houjin_number_or_address_is_available",
            "the_user_asks_for_final_legal_tax_audit_credit_or_application_judgment",
        ],
        "x-jpcite-must-preserve-fields": _FIRST_HOP_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _FIRST_HOP_POLICY["must_not_claim"],
        "x-jpcite-web-search-after": _FIRST_HOP_POLICY["web_search_after_jpcite_only_for"],
    },
    "/v1/artifacts/application_strategy_pack": {
        "x-jpcite-recommended-when": [
            "preparing_subsidy_loan_or_tax_incentive_options",
            "turning_a_business_profile_into_candidate_public_support_programs",
            "checking_amount_fit_exclusions_required_documents_and_next_questions",
            "supporting_bpo_tax_advisor_or_subsidy_consultant_first_meeting",
        ],
        "x-jpcite-not-recommended-when": [
            "the_user_asks_for_final_application_approval_or_adoption_probability_guarantee",
            "the_business_profile_is_missing_basic_location_or_activity_context",
            "the_user_needs_private_financials_contracts_or_non_public_company_context_only",
            "the_user_asks_for_final_legal_tax_or_administrative_scrivener_judgment",
        ],
        "x-jpcite-must-preserve-fields": _FIRST_HOP_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _FIRST_HOP_POLICY["must_not_claim"],
        "x-jpcite-web-search-after": _FIRST_HOP_POLICY["web_search_after_jpcite_only_for"],
    },
    "/v1/programs/prescreen": {
        "x-jpcite-recommended-when": [
            "turning_company_or_project_profile_into_ranked_public_support_candidates",
            "reducing_keyword_guessing_before_program_search_or_general_web_search",
            "choosing_program_ids_before_application_strategy_pack_or_eligibility_predicate",
        ],
        "x-jpcite-not-recommended-when": [
            "the_user_needs_final_application_eligibility_or_adoption_probability",
            "the_user_has_no_profile_axis_beyond_a_free_text_question",
            "the_user_needs_private_financials_contracts_or_unpublished_context_only",
        ],
        "x-jpcite-must-preserve-fields": [
            "unified_id",
            "fit_score",
            "match_reasons",
            "caveats",
            "source_url",
            "profile_echo",
        ],
        "x-jpcite-must-not-claim": [
            "final_eligibility_confirmed",
            "subsidy_or_loan_approved",
            "adoption_probability_guaranteed",
            "professional_review_unnecessary",
        ],
        "x-jpcite-web-search-after": [
            "known_or_visible_caveats",
            "non_public_context",
            "very_recent_program_changes_outside_corpus",
        ],
    },
    "/v1/programs/{program_id}/eligibility_predicate": {
        "x-jpcite-recommended-when": [
            "the_caller_already_has_a_program_id_and_needs_machine_readable_conditions",
            "checking_which_profile_axes_need_human_or_customer_confirmation",
            "building_rule_based_prescreen_or_exclusion_explanations_before_drafting",
        ],
        "x-jpcite-not-recommended-when": [
            "the_user_needs_a_program_list_but_has_no_program_id",
            "the_user_asks_for_final_legal_tax_or_application_judgment",
            "the_user_interprets_missing_predicate_axes_as_no_constraint",
        ],
        "x-jpcite-must-preserve-fields": [
            "program_id",
            "predicate_json",
            "axes",
            "source_url",
            "source_fetched_at",
            "last_checked_at",
        ],
        "x-jpcite-must-not-claim": [
            "missing_axis_means_no_requirement",
            "final_eligibility_confirmed",
            "subsidy_or_loan_approved",
            "professional_review_unnecessary",
        ],
        "x-jpcite-web-search-after": [
            "missing_predicate_axes",
            "source_recency_gaps",
            "non_public_company_or_project_context",
        ],
    },
    "/v1/artifacts/company_folder_brief": {
        "x-jpcite-recommended-when": [
            "turning_company_public_baseline_into_a_crm_or_client_folder_note",
            "preparing_questions_to_ask_a_client_or_counterparty",
        ],
        "x-jpcite-must-preserve-fields": _FIRST_HOP_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _FIRST_HOP_POLICY["must_not_claim"],
        "x-jpcite-web-search-after": _FIRST_HOP_POLICY["web_search_after_jpcite_only_for"],
    },
    "/v1/artifacts/company_public_audit_pack": {
        "x-jpcite-recommended-when": [
            "preparing_public_record_audit_or_dd_workpaper_inputs",
            "preserving_scope_known_gaps_and_source_receipts_for_review",
            "turning_company_public_baseline_into_a_review_control_packet",
        ],
        "x-jpcite-not-recommended-when": [
            "the_company_identity_has_not_been_resolved_to_public_records",
            "the_user_needs_statutory_audit_assurance_or_an_audit_opinion",
            "the_user_needs_private_ledger_contract_or_bank_data_only",
        ],
        "x-jpcite-trigger-after-calls": _COMPANY_PUBLIC_AUDIT_POLICY["trigger_after_calls"],
        "x-jpcite-public-record-scope": True,
        "x-jpcite-must-preserve-fields": _COMPANY_PUBLIC_AUDIT_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _COMPANY_PUBLIC_AUDIT_POLICY["must_not_claim"],
        "x-jpcite-web-search-after": _FIRST_HOP_POLICY["web_search_after_jpcite_only_for"],
        "x-jpcite-agent-output-guidance": _COMPANY_PUBLIC_AUDIT_POLICY["agent_output_guidance"],
    },
    "/v1/advisors/match": {
        "x-jpcite-recommended-when": [
            "handing_source_linked_evidence_to_a_human_expert_reviewer",
            "the_user_asks_who_can_review_tax_legal_application_or_financing_next_steps",
            "known_gaps_or_eligibility_unknowns_require_professional_confirmation",
            "a_program_company_or_law_evidence_packet_needs_prefecture_or_specialty_fit",
        ],
        "x-jpcite-not-recommended-when": [
            "the_agent_has_not_collected_source_linked_facts_or_known_gaps_yet",
            "the_user_needs_the_agent_to_make_final_legal_tax_audit_credit_or_application_judgment",
            "the_user_only_needs_general_background_with_no_japan_advisor_handoff",
            "the_next_action_is_tracking_a_click_or_reporting_a_conversion",
        ],
        "x-jpcite-handoff-role": "evidence_to_expert_handoff",
        "x-jpcite-handoff-policy": "triageEvidenceToExpertHandoff",
        "x-jpcite-trigger-after-calls": _EVIDENCE_TO_EXPERT_HANDOFF_POLICY["trigger_after_calls"],
        "x-jpcite-handoff-packet-should-include": _EVIDENCE_TO_EXPERT_HANDOFF_POLICY[
            "handoff_packet_should_include"
        ],
        "x-jpcite-must-preserve-fields": _EVIDENCE_TO_EXPERT_HANDOFF_POLICY["must_preserve_fields"],
        "x-jpcite-must-not-claim": _EVIDENCE_TO_EXPERT_HANDOFF_POLICY["must_not_claim"],
        "x-jpcite-web-search-after": [
            "advisor_identity_or_credential_confirmation",
            "known_gaps_not_covered_by_jpcite_sources",
            "non_public_client_context",
            "very_recent_status_changes_outside_corpus",
        ],
        "x-jpcite-agent-output-guidance": _EVIDENCE_TO_EXPERT_HANDOFF_POLICY[
            "agent_output_guidance"
        ],
    },
}


def _collect_schema_refs(node: Any, refs: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_schema_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_refs(item, refs)


def _prune_components(schema: dict[str, Any]) -> None:
    components = schema.get("components")
    if not isinstance(components, dict):
        return
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return

    needed: set[str] = set()
    _collect_schema_refs(schema.get("paths") or {}, needed)
    expanded: set[str] = set()
    while needed - expanded:
        name = (needed - expanded).pop()
        expanded.add(name)
        component = schemas.get(name)
        if component is not None:
            _collect_schema_refs(component, needed)
    components["schemas"] = {
        name: deepcopy(schemas[name]) for name in sorted(expanded) if name in schemas
    }
    if not components["schemas"]:
        components.pop("schemas", None)


def _build_agent_call_order_policy(paths: dict[str, Any]) -> dict[str, Any]:
    available = set(paths)
    first_call_order: list[dict[str, Any]] = []

    def add_step(
        *,
        path: str,
        call: str,
        when: list[str],
        purpose: str,
        alternate_calls: list[str] | None = None,
        skip_when: list[str] | None = None,
    ) -> None:
        if path not in available:
            return
        step: dict[str, Any] = {
            "step": len(first_call_order) + 1,
            "call": call,
            "path": path,
            "when": when,
            "purpose": purpose,
        }
        if alternate_calls:
            step["alternate_calls"] = alternate_calls
        if skip_when:
            step["skip_when"] = skip_when
        first_call_order.append(step)

    add_step(
        path="/v1/cost/preview",
        call="previewCost",
        when=_COST_PREVIEW_POLICY["first_call_when"],
        skip_when=_COST_PREVIEW_POLICY["skip_when"],
        purpose="free_preflight_for_planned_metered_jpcite_calls",
    )
    add_step(
        path="/v1/artifacts/company_public_baseline",
        call="createCompanyPublicBaseline",
        when=[
            "japanese_company_research_client_folder_counterparty_audit_dd_or_sales_prep",
            "before_general_web_search_for_public_company_facts",
        ],
        purpose="resolve_public_company_identity_sources_known_gaps_and_review_flags",
    )

    evidence_alternates: list[str] = []
    if "/v1/evidence/packets/{subject_kind}/{subject_id}" in available:
        evidence_alternates.append("getEvidencePacket")
    add_step(
        path="/v1/evidence/packets/query",
        call="queryEvidencePacket",
        alternate_calls=evidence_alternates or None,
        when=[
            "the_agent_needs_source_linked_facts_before_answer_generation",
            "the_agent_needs_known_gaps_or_decision_insights_for_next_steps",
        ],
        purpose="assemble_source_linked_records_quality_known_gaps_and_decision_insights",
    )
    if (
        "/v1/evidence/packets/query" not in available
        and "/v1/evidence/packets/{subject_kind}/{subject_id}" in available
    ):
        add_step(
            path="/v1/evidence/packets/{subject_kind}/{subject_id}",
            call="getEvidencePacket",
            when=[
                "the_agent_has_a_program_id_or_houjin_number_and_needs_one_subject_packet",
                "the_agent_needs_known_gaps_or_decision_insights_for_next_steps",
            ],
            purpose="assemble_one_subject_source_linked_packet",
        )

    support_alternates: list[str] = []
    if "/v1/programs/{program_id}/eligibility_predicate" in available:
        support_alternates.append("getProgramEligibilityPredicate")
    if "/v1/artifacts/application_strategy_pack" in available:
        support_alternates.append("createApplicationStrategyPack")
    add_step(
        path="/v1/programs/prescreen",
        call="prescreenPrograms",
        alternate_calls=support_alternates or None,
        when=[
            "the_user_needs_candidate_subsidy_loan_or_tax_incentive_programs",
            "the_agent_has_company_or_project_profile_axes_to_screen",
        ],
        purpose="rank_candidate_public_support_programs_without_final_eligibility_claims",
    )

    add_step(
        path="/v1/artifacts/company_public_audit_pack",
        call="createCompanyPublicAuditPack",
        when=[
            "public_record_audit_or_dd_workpaper_inputs_are_needed",
            "source_receipts_mismatch_flags_and_review_controls_must_be_preserved",
        ],
        purpose="prepare_public_source_evidence_ledger_risk_gap_register_and_review_controls",
    )
    add_step(
        path="/v1/advisors/match",
        call="match_advisors_v1_advisors_match_get",
        when=_EVIDENCE_TO_EXPERT_HANDOFF_POLICY["trigger_after_calls"],
        purpose="handoff_bounded_evidence_packet_to_candidate_human_expert_reviewers",
    )
    add_step(
        path="/v1/citations/verify",
        call="verifyCitations",
        when=[
            "the_agent_needs_to_check_citation_pairs_before_final_output",
            "the_answer_will_quote_or_rely_on_specific_source_urls",
        ],
        purpose="optional_citation_check_before_final_answer",
    )

    return {
        "name": "agent_first_call_order",
        "plain_ja": (
            "AIエージェントは、費用確認が必要なら previewCost、"
            "日本企業の公開調査なら company_public_baseline、回答生成前は "
            "Evidence Packet、監査/DDは company_public_audit_pack、"
            "専門家レビュー候補は最後に GET /v1/advisors/match の順で使ってください。"
        ),
        "plain_en": (
            "Agents should use previewCost first for cost-sensitive plans, "
            "company_public_baseline first for Japanese public-company work, "
            "Evidence Packets before answer generation, company_public_audit_pack "
            "for audit/DD workpaper inputs, and GET /v1/advisors/match only "
            "after the bounded evidence packet is assembled."
        ),
        "first_call_order": first_call_order,
        "global_must_preserve_fields": _GLOBAL_AGENT_MUST_PRESERVE_FIELDS,
        "global_must_not_claim": _GLOBAL_AGENT_MUST_NOT_CLAIM,
        "web_search_position": (
            "Use general web search after jpcite for known_gaps, non-public "
            "context supplied by the user, or very recent changes outside the corpus."
        ),
    }


_SAFE_PAID_HEADER_PARAMETERS: dict[str, dict[str, Any]] = {
    "X-Client-Tag": {
        "name": "X-Client-Tag",
        "in": "header",
        "required": False,
        "schema": {
            "type": "string",
            "pattern": "^[A-Za-z0-9_-]{1,32}$",
            "maxLength": 32,
        },
        "description": (
            "Optional paid-usage attribution tag for the end customer, company "
            "folder, or project. Stored on usage events when a valid API key is used."
        ),
    },
    "Idempotency-Key": {
        "name": "Idempotency-Key",
        "in": "header",
        "required": False,
        "schema": {"type": "string", "minLength": 8, "maxLength": 128},
        "description": (
            "Optional retry key for POST operations. Use the same value when "
            "retrying the same paid operation so duplicate retries can be replayed safely."
        ),
    },
    "X-Cost-Cap-JPY": {
        "name": "X-Cost-Cap-JPY",
        "in": "header",
        "required": False,
        "schema": {"type": "integer", "minimum": 0},
        "description": (
            "Optional maximum JPY budget for this call. Use with previewCost "
            "before broad, batch, or fanout runs."
        ),
    },
}


def _ensure_header_parameter(operation: dict[str, Any], name: str) -> None:
    params = operation.setdefault("parameters", [])
    if not isinstance(params, list):
        return
    wanted = name.lower()
    for param in params:
        if not isinstance(param, dict):
            continue
        if param.get("in") == "header" and str(param.get("name", "")).lower() == wanted:
            return
    params.append(deepcopy(_SAFE_PAID_HEADER_PARAMETERS[name]))


def _attach_safe_paid_execution_guidance(operation: dict[str, Any], *, is_post: bool) -> None:
    _ensure_header_parameter(operation, "X-Client-Tag")
    if is_post:
        _ensure_header_parameter(operation, "Idempotency-Key")
        _ensure_header_parameter(operation, "X-Cost-Cap-JPY")
    operation["x-jpcite-safe-paid-execution"] = {
        "preflight_sequence": ["getUsageStatus", "previewCost"],
        "headers": {
            "X-API-Key": (
                "Use for repeated or paid volume. Configure GPT Actions as "
                "API Key > Custom header name X-API-Key."
            ),
            "X-Client-Tag": "Set per customer, company folder, or project for usage attribution.",
            "Idempotency-Key": "Use on POST retries for the same paid operation.",
            "X-Cost-Cap-JPY": "Use on billable POST fanout or batch calls to enforce caller budget.",
        },
        "paid_continuation": (
            "After anonymous quota is exhausted or repeated use is expected, "
            "retry the same endpoint with X-API-Key, "
            "and keep X-Client-Tag stable for the customer/project."
        ),
    }


def _drop_unavailable_operation_refs(node: Any, unavailable_calls: set[str]) -> Any:
    if not unavailable_calls:
        return node
    if isinstance(node, list):
        return [
            _drop_unavailable_operation_refs(item, unavailable_calls)
            for item in node
            if not (isinstance(item, str) and item in unavailable_calls)
        ]
    if isinstance(node, dict):
        return {
            key: _drop_unavailable_operation_refs(value, unavailable_calls)
            for key, value in node.items()
        }
    return node


def build_agent_openapi_schema(full_schema: dict[str, Any]) -> dict[str, Any]:
    """Return a reduced OpenAPI schema for LLM action importers."""
    schema = deepcopy(full_schema)
    all_paths = schema.get("paths") or {}
    schema["paths"] = {
        path: deepcopy(all_paths[path]) for path in AGENT_SAFE_PATHS if path in all_paths
    }
    company_first_hop_available = "/v1/artifacts/company_public_baseline" in schema["paths"]
    advisor_match_available = "/v1/advisors/match" in schema["paths"]
    evidence_packet_available = any(
        path in schema["paths"]
        for path in (
            "/v1/evidence/packets/query",
            "/v1/evidence/packets/{subject_kind}/{subject_id}",
        )
    )
    cost_preview_available = "/v1/cost/preview" in schema["paths"]
    unavailable_calls: set[str] = {
        operation_id
        for (_method, path), operation_id in _AGENT_OPERATION_IDS.items()
        if path not in schema["paths"]
    }
    schema["security"] = []
    info = schema.setdefault("info", {})
    info["title"] = "jpcite Agent Evidence API"
    info.pop("contact", None)
    description = (
        "Agent-safe OpenAPI subset for evidence prefetch before answer "
        "generation. jpcite returns source-linked facts, source_url, "
        "fetched timestamps, known gaps, and compatibility rules; it does not "
        "call external LLM APIs and does not generate final legal/tax advice. "
    )
    if company_first_hop_available:
        description += (
            "For Japanese company research, client folders, counterparty checks, "
            "audit/DD prep, sales/account prep, or public opportunity/risk review, "
            "call createCompanyPublicBaseline before general web search, then use "
            "web search only for known_gaps, non-public context, or very recent "
            "news outside the corpus. "
        )
    if evidence_packet_available:
        description += (
            "Before final answer generation, use queryEvidencePacket or "
            "getEvidencePacket to collect source-linked records, decision_insights, "
            "and known gaps. "
        )
    if cost_preview_available:
        description += (
            "For broad, repeated, or cost-sensitive call stacks, call previewCost "
            "first; it is a free estimate and does not execute planned calls. "
        )
    if advisor_match_available:
        description += (
            "For Evidence-to-Expert Handoff, call match_advisors_v1_advisors_match_get "
            "after source-linked evidence, caveats, and known gaps are assembled; "
            "present advisor matches as candidate reviewers, not final professional "
            "judgment or completed referral. "
        )
    description += (
        "Optional token/context fields compare caller-supplied input-context "
        "baselines. This spec excludes billing, webhook, OAuth, account-management, "
        "and administrative endpoints. Anonymous callers can evaluate within the "
        "published daily limit unless an operation marks X-API-Key as required; "
        "callers that need higher volume send X-API-Key."
    )
    info["description"] = description
    info["x-jpcite-pricing"] = deepcopy(_AGENT_PRICING_METADATA)
    info["x-jpcite-agent-call-order-policy"] = _drop_unavailable_operation_refs(
        _build_agent_call_order_policy(schema["paths"]),
        unavailable_calls,
    )
    if company_first_hop_available or evidence_packet_available:
        info["x-jpcite-recurring-agent-workflow-policy"] = _drop_unavailable_operation_refs(
            deepcopy(_HIGH_VOLUME_AGENT_WORKFLOW_POLICY),
            unavailable_calls,
        )
    else:
        info.pop("x-jpcite-recurring-agent-workflow-policy", None)
    info["x-jpcite-global-must-not-claim"] = deepcopy(_GLOBAL_AGENT_MUST_NOT_CLAIM)
    if evidence_packet_available:
        evidence_policy = deepcopy(_EVIDENCE_PACKET_POLICY)
        current_calls: list[str] = []
        if "/v1/evidence/packets/query" in schema["paths"]:
            current_calls.append("queryEvidencePacket")
        if "/v1/evidence/packets/{subject_kind}/{subject_id}" in schema["paths"]:
            current_calls.append("getEvidencePacket")
        evidence_policy["current_calls"] = current_calls
        info["x-jpcite-evidence-packet-policy"] = evidence_policy
    else:
        info.pop("x-jpcite-evidence-packet-policy", None)
    if cost_preview_available:
        info["x-jpcite-cost-preview-policy"] = deepcopy(_COST_PREVIEW_POLICY)
    else:
        info.pop("x-jpcite-cost-preview-policy", None)
    if company_first_hop_available:
        info["x-jpcite-first-hop-policy"] = _drop_unavailable_operation_refs(
            deepcopy(_FIRST_HOP_POLICY),
            unavailable_calls,
        )
    else:
        info.pop("x-jpcite-first-hop-policy", None)
    if advisor_match_available:
        info["x-jpcite-evidence-to-expert-handoff-policy"] = _drop_unavailable_operation_refs(
            deepcopy(_EVIDENCE_TO_EXPERT_HANDOFF_POLICY),
            unavailable_calls,
        )
    else:
        info.pop("x-jpcite-evidence-to-expert-handoff-policy", None)
    for path, path_item in schema["paths"].items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
                "trace",
            }:
                continue
            if not isinstance(operation, dict):
                continue
            auth_required = path == "/v1/citations/verify"
            operation_id = _AGENT_OPERATION_IDS.get((method.lower(), path))
            if operation_id:
                operation["operationId"] = operation_id
            operation["security"] = (
                [{"ApiKeyAuth": []}] if auth_required else [{"ApiKeyAuth": []}, {}]
            )
            operation["x-jpcite-agent-safe"] = True
            operation["x-jpcite-auth"] = (
                "required_x_api_key" if auth_required else "optional_x_api_key_for_paid_volume"
            )
            _ensure_header_parameter(operation, "X-Client-Tag")
            if path in _FREE_AGENT_PATHS:
                operation["x-jpcite-billing"] = {
                    "billable": False,
                    "billing_units": 0,
                    "plain_ja": "このエンドポイントは料金確認・透明性確認用で、通常の課金対象外です。",
                    "plain_en": (
                        "This endpoint is for cost preview or transparency checks "
                        "and is not normally metered."
                    ),
                }
            else:
                billing_metadata = {
                    "billable": True,
                    "billing_quantity_basis": "successful_call",
                    "billing_unit_type": "api_call",
                    "billing_units_formula": "1 unit per successful HTTP response",
                    "billing_units_per_successful_call": 1,
                    "free_quota_applies": True,
                    "unit_price_jpy_ex_tax": 3,
                    "unit_price_jpy_tax_included": 3.3,
                    "max_estimated_charge_jpy": "3.3 per successful call, tax included",
                    "plain_ja": (
                        "通常の有料利用では成功した1呼び出しあたり1 unit、"
                        "税別3円・税込約3.30円です。失敗リクエストは課金対象外です。"
                    ),
                    "plain_en": (
                        "In ordinary paid use, a successful call is 1 unit: "
                        "JPY 3 ex-tax / about JPY 3.30 including tax. Failed "
                        "requests are not billed."
                    ),
                }
                billing_metadata.update(deepcopy(_OPERATION_BILLING_OVERRIDES.get(path, {})))
                operation["x-jpcite-billing"] = billing_metadata
                _attach_safe_paid_execution_guidance(
                    operation,
                    is_post=method.lower() == "post",
                )
            responses = operation.get("responses")
            if isinstance(responses, dict):
                auth_response = responses.get("401")
                if isinstance(auth_response, dict):
                    if auth_required:
                        auth_response["description"] = "Authentication required. Send X-API-Key."
                    else:
                        auth_response["description"] = (
                            "Invalid authentication — returned only when an API "
                            "key is supplied but invalid. Anonymous callers may "
                            "use the published daily limit; quota exhaustion "
                            "returns 429."
                        )
            priority = _AGENT_PRIORITIES.get(path)
            if priority:
                operation["x-jpcite-agent-priority"] = priority[0]
                operation["x-jpcite-route-purpose"] = priority[1]
            guidance = _OPERATION_GUIDANCE.get(path)
            if guidance:
                operation.update(
                    _drop_unavailable_operation_refs(
                        deepcopy(guidance),
                        unavailable_calls,
                    )
                )
            operation.setdefault("tags", ["agent-evidence"])
    _prune_components(schema)
    return schema


__all__ = ["AGENT_SAFE_PATHS", "build_agent_openapi_schema"]
