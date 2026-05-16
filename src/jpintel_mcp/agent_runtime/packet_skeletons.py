"""Deterministic P0 outcome packet skeleton examples.

These examples are intentionally static: they describe the public packet shape
without fetching sources, running LLM calls, or exposing tenant-private facts.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID
from jpintel_mcp.agent_runtime.source_receipts import (
    known_gap,
    public_claim,
    source_receipt,
)

BILLING_CONTRACT_ID = f"{CAPSULE_ID}:accepted-artifact-pricing"
NO_HIT_SEMANTICS = "no_hit_not_absence"

P0_PACKET_SKELETON_IDS = (
    "company_public_baseline",
    "invoice_registrant_public_check",
    "application_strategy",
    "regulation_change_watch",
    "local_government_permit_obligation_map",
    "court_enforcement_citation_pack",
    "public_statistics_market_context",
    "client_monthly_review",
    "csv_overlay_public_check",
    "cashbook_csv_subsidy_fit_screen",
    "source_receipt_ledger",
    "evidence_answer",
    "foreign_investor_japan_public_entry_brief",
    "healthcare_regulatory_public_check",
)

P0_PACKET_SKELETON_DEFERRED_REASONS: dict[str, str] = {}
PUBLIC_RELEASE_KEY_RENAMES = {
    "raw_csv_retained": "csv_input_retained",
    "raw_csv_logged": "csv_input_logged",
    "raw_csv_sent_to_aws": "csv_input_sent_to_aws",
    "raw_row_values_included": "csv_row_values_included",
    "raw_value_retained": "private_value_retained",
}


def _claim(
    claim_id: str,
    text: str,
    receipt_ids: tuple[str, ...],
    *,
    visibility: str = "public",
    support_state: str = "supported",
) -> dict[str, Any]:
    return public_claim(
        claim_id,
        text,
        receipt_ids,
        visibility=visibility,
        support_state=support_state,
    )


def _receipt(
    receipt_id: str,
    source_family_id: str,
    source_url: str,
    *,
    support_state: str = "direct",
) -> dict[str, str]:
    return source_receipt(
        receipt_id,
        source_family_id,
        source_url,
        support_state=support_state,
    )


def _gap(gap_id: str, gap_type: str, explanation: str) -> dict[str, str]:
    return known_gap(gap_id, gap_type, explanation)


def _private_csv_overlay(derived_fact_type: str) -> dict[str, Any]:
    return {
        "tenant_scope": "tenant_private",
        "redaction_policy": "hash_only_private_facts",
        "raw_csv_retained": False,
        "raw_csv_logged": False,
        "raw_csv_sent_to_aws": False,
        "public_surface_export_allowed": False,
        "source_receipt_compatible": False,
        "private_fact_examples": [
            {
                "record_id": "private_fact_hash_only",
                "derived_fact_type": derived_fact_type,
                "value_fingerprint_hash": "sha256:example-private-fingerprint",
                "public_claim_support": False,
                "source_receipt_compatible": False,
                "raw_value_retained": False,
            }
        ],
    }


def _base_skeleton(
    outcome_contract_id: str,
    display_name: str,
    packet_ids: tuple[str, ...],
    claims: list[dict[str, Any]],
    source_receipts: list[dict[str, str]],
    known_gaps: list[dict[str, str]],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skeleton: dict[str, Any] = {
        "schema_version": "jpcite.packet_skeleton.p0.v1",
        "capsule_id": CAPSULE_ID,
        "outcome_contract_id": outcome_contract_id,
        "display_name": display_name,
        "packet_ids": list(packet_ids),
        "billing_contract_id": BILLING_CONTRACT_ID,
        "claims": claims,
        "source_receipts": source_receipts,
        "known_gaps": known_gaps,
        "no_hit_semantics": {
            "rule": NO_HIT_SEMANTICS,
            "absence_claim_enabled": False,
            "wording": "No hit is reported as an observed search result only, not as proof of absence.",
        },
    }
    if extra:
        skeleton.update(extra)
    return skeleton


def _build_packet_skeletons() -> dict[str, dict[str, Any]]:
    company_receipts = [
        _receipt("sr_company_gbizinfo", "gBizINFO", "https://info.gbiz.go.jp/"),
        _receipt("sr_company_nta_invoice", "nta_invoice", "https://www.invoice-kohyo.nta.go.jp/"),
        _receipt("sr_company_edinet", "edinet", "https://disclosure2.edinet-fsa.go.jp/"),
    ]
    invoice_receipts = [
        _receipt(
            "sr_invoice_nta_invoice",
            "nta_invoice",
            "https://www.invoice-kohyo.nta.go.jp/",
        ),
    ]
    application_receipts = [
        _receipt("sr_app_program", "jgrants", "https://www.jgrants-portal.go.jp/"),
        _receipt("sr_app_guideline", "sme_agency", "https://www.chusho.meti.go.jp/"),
        _receipt("sr_app_local_notice", "local_government_notice", "metadata:local-notice"),
    ]
    regulation_receipts = [
        _receipt("sr_reg_current", "egov_law", "https://elaws.e-gov.go.jp/"),
        _receipt("sr_reg_meti_notice", "meti_notice", "https://www.meti.go.jp/"),
        _receipt("sr_reg_mhlw_notice", "mhlw_notice", "https://www.mhlw.go.jp/"),
    ]
    local_government_receipts = [
        _receipt("sr_local_notice", "local_government_notice", "metadata:local-notice"),
        _receipt("sr_local_national_law", "egov_law", "https://elaws.e-gov.go.jp/"),
    ]
    court_receipts = [
        _receipt("sr_court_decision", "courts_jp", "https://www.courts.go.jp/"),
        _receipt("sr_court_meti_enforcement", "meti_enforcement", "https://www.meti.go.jp/"),
        _receipt("sr_court_maff_enforcement", "maff_enforcement", "https://www.maff.go.jp/"),
    ]
    statistics_receipts = [
        _receipt("sr_stats_estat", "estat", "https://www.e-stat.go.jp/"),
        _receipt(
            "sr_stats_prefecture",
            "prefecture_statistics",
            "metadata:prefecture-statistics",
        ),
    ]
    monthly_review_receipts = [
        _receipt("sr_monthly_company", "gBizINFO", "https://info.gbiz.go.jp/"),
        _receipt("sr_monthly_invoice", "nta_invoice", "https://www.invoice-kohyo.nta.go.jp/"),
        _receipt("sr_monthly_program", "jgrants", "https://www.jgrants-portal.go.jp/"),
        _receipt("sr_monthly_law_change", "egov_law", "https://elaws.e-gov.go.jp/"),
    ]
    csv_public_receipts = [
        _receipt("sr_csv_public_invoice", "nta_invoice", "https://www.invoice-kohyo.nta.go.jp/"),
        _receipt("sr_csv_public_gbizinfo", "gBizINFO", "https://info.gbiz.go.jp/"),
    ]
    cashbook_receipts = [
        _receipt("sr_cashbook_program", "jgrants", "https://www.jgrants-portal.go.jp/"),
        _receipt("sr_cashbook_guideline", "sme_agency", "https://www.chusho.meti.go.jp/"),
    ]
    ledger_receipts = [
        _receipt("sr_ledger_receipt_graph", "source_receipt_ledger", "metadata:receipt-graph"),
        _receipt("sr_ledger_gbizinfo", "gBizINFO", "https://info.gbiz.go.jp/"),
        _receipt("sr_ledger_egov_law", "egov_law", "https://elaws.e-gov.go.jp/"),
        _receipt(
            "sr_ledger_registry_gap",
            "commercial_registry",
            "metadata:registry-gap",
            support_state="gap",
        ),
    ]
    evidence_receipts = [
        _receipt("sr_evidence_primary", "egov_law", "https://elaws.e-gov.go.jp/"),
        _receipt("sr_evidence_notice", "official_notice", "metadata:official-notice"),
        _receipt("sr_evidence_receipt_graph", "source_receipt_ledger", "metadata:receipt-graph"),
    ]
    foreign_investor_receipts = [
        _receipt("sr_foreign_edinet", "edinet", "https://disclosure2.edinet-fsa.go.jp/"),
        _receipt("sr_foreign_law", "egov_law", "https://elaws.e-gov.go.jp/"),
        _receipt("sr_foreign_meti_notice", "meti_notice", "https://www.meti.go.jp/"),
    ]
    healthcare_receipts = [
        _receipt("sr_healthcare_mhlw_notice", "mhlw_notice", "https://www.mhlw.go.jp/"),
        _receipt("sr_healthcare_law", "egov_law", "https://elaws.e-gov.go.jp/"),
        _receipt(
            "sr_healthcare_local_notice",
            "local_government_notice",
            "metadata:local-notice",
        ),
    ]

    return {
        "company_public_baseline": _base_skeleton(
            "company_public_baseline",
            "Company public baseline packet",
            ("company_profile", "source_receipts", "known_gaps"),
            [
                _claim(
                    "claim_company_name",
                    "Public-source company name placeholder.",
                    ("sr_company_gbizinfo",),
                ),
                _claim(
                    "claim_invoice_status",
                    "Public invoice registration status placeholder.",
                    ("sr_company_nta_invoice",),
                ),
            ],
            company_receipts,
            [
                _gap(
                    "gap_registry_currentness",
                    "freshness",
                    "Registry freshness is not asserted by this skeleton.",
                )
            ],
        ),
        "invoice_registrant_public_check": _base_skeleton(
            "invoice_registrant_public_check",
            "Invoice registrant public check packet",
            ("invoice_registration_status", "source_receipts", "known_gaps"),
            [
                _claim(
                    "claim_invoice_registration_status",
                    "Qualified invoice registration status placeholder.",
                    ("sr_invoice_nta_invoice",),
                ),
            ],
            invoice_receipts,
            [
                _gap(
                    "gap_invoice_no_hit_boundary",
                    "no_hit_boundary",
                    "No matching registry row is a no-hit observation, not proof of non-registration.",
                )
            ],
            extra={
                "invoice_registration_status": {
                    "match_state": "placeholder_observed_or_no_hit",
                    "absence_claim_enabled": False,
                    "receipt_id": "sr_invoice_nta_invoice",
                }
            },
        ),
        "application_strategy": _base_skeleton(
            "application_strategy",
            "Application strategy packet",
            (
                "normalized_applicant_profile",
                "ranked_candidates",
                "fit_signals",
                "questions_for_professional",
                "known_gaps",
            ),
            [
                _claim(
                    "claim_candidate_program",
                    "Program candidate placeholder; not an application eligibility verdict.",
                    ("sr_app_program",),
                ),
                _claim(
                    "claim_guideline_requirement",
                    "Guideline requirement placeholder for professional review.",
                    ("sr_app_guideline",),
                ),
                _claim(
                    "claim_local_program_context",
                    "Local program notice placeholder.",
                    ("sr_app_local_notice",),
                ),
            ],
            application_receipts,
            [
                _gap(
                    "gap_private_input_unverified",
                    "input_boundary",
                    "Applicant profile facts are minimized and not independently verified.",
                ),
                _gap(
                    "gap_compatibility_unknown",
                    "professional_review",
                    "Same-expense and stacking compatibility require source-specific review.",
                ),
            ],
            extra={
                "quality": {
                    "human_review_required": True,
                    "human_review_reasons": [
                        "application_strategy_boundary",
                        "professional_interpretation_required",
                    ],
                },
                "strategy_sections": {
                    "normalized_applicant_profile": {
                        "location": "prefecture_or_municipality_placeholder",
                        "industry": "industry_placeholder",
                        "investment_plan": "minimized_profile_placeholder",
                    },
                    "ranked_candidates": [
                        {
                            "candidate_id": "candidate_program_placeholder",
                            "receipt_ids": ["sr_app_program", "sr_app_guideline"],
                            "recommendation_state": "candidate_for_review",
                            "not_a_verdict": True,
                        }
                    ],
                    "questions_for_professional": [
                        "Confirm deadline, required documents, same-expense restrictions, and applicant-specific exclusions."
                    ],
                    "do_not_claim": [
                        "grant_award",
                        "application_eligibility_verdict",
                        "tax_advice",
                    ],
                },
            },
        ),
        "regulation_change_watch": _base_skeleton(
            "regulation_change_watch",
            "Regulation and policy change watch packet",
            ("change_diff", "affected_workflows", "source_receipts"),
            [
                _claim(
                    "claim_current_rule",
                    "Current regulation text placeholder.",
                    ("sr_reg_current",),
                ),
                _claim("claim_meti_notice", "METI notice placeholder.", ("sr_reg_meti_notice",)),
                _claim("claim_mhlw_notice", "MHLW notice placeholder.", ("sr_reg_mhlw_notice",)),
            ],
            regulation_receipts,
            [
                _gap(
                    "gap_effective_date_confirmation",
                    "freshness",
                    "Effective date confirmation remains a known gap until sourced.",
                )
            ],
            extra={
                "change_diff": {
                    "before": "Prior rule placeholder.",
                    "after": "Current rule placeholder.",
                    "affected_workflows": ["compliance_calendar", "customer_notice_review"],
                }
            },
        ),
        "local_government_permit_obligation_map": _base_skeleton(
            "local_government_permit_obligation_map",
            "Local government permit and obligation map packet",
            ("jurisdiction_profile", "permit_obligations", "source_receipts", "known_gaps"),
            [
                _claim(
                    "claim_local_notice_rule",
                    "Local permit notice placeholder.",
                    ("sr_local_notice",),
                ),
                _claim(
                    "claim_national_rule_baseline",
                    "National rule baseline placeholder.",
                    ("sr_local_national_law",),
                ),
            ],
            local_government_receipts,
            [
                _gap(
                    "gap_municipality_scope",
                    "coverage",
                    "Municipality coverage depends on the selected jurisdiction and cached notices.",
                ),
                _gap(
                    "gap_permit_advice_boundary",
                    "professional_review",
                    "Permit obligations are a sourced map, not legal advice or filing instructions.",
                ),
            ],
            extra={
                "permit_obligations": [
                    {
                        "obligation_id": "local_permit_placeholder",
                        "jurisdiction": "municipality_placeholder",
                        "receipt_ids": ["sr_local_notice", "sr_local_national_law"],
                        "review_state": "candidate_for_review",
                    }
                ]
            },
        ),
        "court_enforcement_citation_pack": _base_skeleton(
            "court_enforcement_citation_pack",
            "Court and enforcement citation pack",
            ("court_citations", "enforcement_notices", "claim_refs", "known_gaps"),
            [
                _claim(
                    "claim_court_citation",
                    "Published decision citation placeholder.",
                    ("sr_court_decision",),
                ),
                _claim(
                    "claim_meti_enforcement_notice",
                    "METI enforcement notice placeholder.",
                    ("sr_court_meti_enforcement",),
                ),
                _claim(
                    "claim_maff_enforcement_notice",
                    "MAFF enforcement notice placeholder.",
                    ("sr_court_maff_enforcement",),
                ),
            ],
            court_receipts,
            [
                _gap(
                    "gap_case_law_completeness",
                    "coverage",
                    "Published decisions are not asserted to be a complete case-law corpus.",
                ),
                _gap(
                    "gap_outcome_interpretation",
                    "professional_review",
                    "Citation context requires human review before legal interpretation.",
                ),
            ],
            extra={
                "court_citations": [
                    {
                        "citation_id": "published_decision_placeholder",
                        "receipt_id": "sr_court_decision",
                        "not_full_case_law_search": True,
                    }
                ],
                "enforcement_notices": [
                    {
                        "notice_id": "meti_notice_placeholder",
                        "receipt_id": "sr_court_meti_enforcement",
                    },
                    {
                        "notice_id": "maff_notice_placeholder",
                        "receipt_id": "sr_court_maff_enforcement",
                    },
                ],
            },
        ),
        "public_statistics_market_context": _base_skeleton(
            "public_statistics_market_context",
            "Public statistics market context packet",
            ("statistics_snapshot", "market_context", "source_receipts", "known_gaps"),
            [
                _claim(
                    "claim_estat_snapshot", "National statistics placeholder.", ("sr_stats_estat",)
                ),
                _claim(
                    "claim_prefecture_statistics",
                    "Prefecture statistics placeholder.",
                    ("sr_stats_prefecture",),
                ),
            ],
            statistics_receipts,
            [
                _gap(
                    "gap_statistical_granularity",
                    "coverage",
                    "Statistics may not match the requested geography, industry, or time period.",
                ),
                _gap(
                    "gap_market_inference_boundary",
                    "interpretation_boundary",
                    "Market context is descriptive and not a forecast or investment recommendation.",
                ),
            ],
            extra={
                "statistics_snapshot": {
                    "geography": "prefecture_or_national_placeholder",
                    "period": "published_period_placeholder",
                    "receipt_ids": ["sr_stats_estat", "sr_stats_prefecture"],
                },
                "market_context": {
                    "interpretation_state": "descriptive_public_statistics_only",
                    "forecast_claim_enabled": False,
                },
            },
        ),
        "client_monthly_review": _base_skeleton(
            "client_monthly_review",
            "Client monthly review packet",
            (
                "client_priority_queue",
                "this_month_watch_items",
                "deadline_risks",
                "questions_for_client",
                "office_tasks",
            ),
            [
                _claim(
                    "claim_client_identity",
                    "Client public identity placeholder.",
                    ("sr_monthly_company",),
                ),
                _claim(
                    "claim_program_watch_item",
                    "This-month program watch item placeholder.",
                    ("sr_monthly_program",),
                ),
                _claim(
                    "claim_policy_change_note",
                    "Policy or system-change note placeholder.",
                    ("sr_monthly_law_change",),
                ),
                _claim(
                    "claim_invoice_watch",
                    "Invoice registry watch placeholder.",
                    ("sr_monthly_invoice",),
                ),
            ],
            monthly_review_receipts,
            [
                _gap(
                    "gap_private_client_notes_minimized",
                    "privacy_boundary",
                    "Private client notes are minimized and not exported as public claims.",
                ),
                _gap(
                    "gap_current_month_freshness",
                    "freshness",
                    "Current-month watch items require live source refresh before final client communication.",
                ),
            ],
            extra={
                "quality": {
                    "human_review_required": True,
                    "human_review_reasons": [
                        "accounting_adjacent_review",
                        "client_communication_review",
                    ],
                },
                "monthly_review": {
                    "review_month": "2026-05",
                    "client_priority_queue": [
                        {
                            "client_ref": "client_subject_placeholder",
                            "priority_reason": "deadline_or_change_watch_placeholder",
                            "receipt_ids": ["sr_monthly_company", "sr_monthly_program"],
                        }
                    ],
                    "copy_paste_client_messages": [
                        {
                            "message_id": "client_question_prompt",
                            "text": "Please confirm the planned expense timing and whether the same expense is used for another program.",
                            "requires_human_review": True,
                        }
                    ],
                    "office_tasks": [
                        {
                            "task_id": "source_refresh_before_send",
                            "owner_role": "advisor",
                            "source_receipt_ids": [
                                "sr_monthly_program",
                                "sr_monthly_law_change",
                            ],
                        }
                    ],
                },
            },
        ),
        "csv_overlay_public_check": _base_skeleton(
            "csv_overlay_public_check",
            "Private CSV overlay with public-source checks",
            ("csv_summary", "public_checks", "redacted_findings"),
            [
                _claim(
                    "claim_public_invoice_check",
                    "Public invoice check placeholder.",
                    ("sr_csv_public_invoice",),
                ),
                _claim(
                    "claim_public_company_check",
                    "Public company check placeholder.",
                    ("sr_csv_public_gbizinfo",),
                ),
            ],
            csv_public_receipts,
            [
                _gap(
                    "gap_private_fact_non_public",
                    "privacy_boundary",
                    "Tenant-private CSV facts are not public claims or source receipts.",
                )
            ],
            extra={
                "private_overlay": _private_csv_overlay("counterparty_match_candidate"),
                "csv_summary": {
                    "tenant_scope": "tenant_private",
                    "export_state": "redacted_summary_only",
                    "raw_row_values_included": False,
                },
                "public_checks": [
                    {
                        "check_id": "invoice_registry_public_check",
                        "receipt_id": "sr_csv_public_invoice",
                    },
                    {
                        "check_id": "company_public_profile_check",
                        "receipt_id": "sr_csv_public_gbizinfo",
                    },
                ],
                "redacted_findings": [
                    {
                        "finding_id": "counterparty_public_match_placeholder",
                        "private_fact_ref": "private_fact_hash_only",
                        "public_receipt_ids": ["sr_csv_public_invoice", "sr_csv_public_gbizinfo"],
                    }
                ],
            },
        ),
        "cashbook_csv_subsidy_fit_screen": _base_skeleton(
            "cashbook_csv_subsidy_fit_screen",
            "Cashbook CSV subsidy fit screen packet",
            (
                "cashbook_summary",
                "program_fit_signals",
                "questions_for_professional",
                "known_gaps",
            ),
            [
                _claim(
                    "claim_cashbook_program",
                    "Program listing placeholder.",
                    ("sr_cashbook_program",),
                ),
                _claim(
                    "claim_cashbook_expense_rule",
                    "Eligible expense rule placeholder.",
                    ("sr_cashbook_guideline",),
                ),
            ],
            cashbook_receipts,
            [
                _gap(
                    "gap_cashbook_private_facts_non_public",
                    "privacy_boundary",
                    "Tenant-private cashbook facts are redacted and cannot create public receipts.",
                ),
                _gap(
                    "gap_cashbook_fit_not_eligibility",
                    "professional_review",
                    "Fit signals are not an eligibility verdict or grant award prediction.",
                ),
            ],
            extra={
                "private_overlay": _private_csv_overlay("cashbook_program_fit_signal"),
                "cashbook_summary": {
                    "tenant_scope": "tenant_private",
                    "export_state": "redacted_summary_only",
                    "raw_row_values_included": False,
                },
                "program_fit_signals": [
                    {
                        "signal_id": "expense_timing_candidate_placeholder",
                        "private_fact_ref": "private_fact_hash_only",
                        "public_receipt_ids": ["sr_cashbook_program", "sr_cashbook_guideline"],
                        "not_a_verdict": True,
                    }
                ],
                "questions_for_professional": [
                    "Confirm eligible expense category, timing, deadline, and stacking restrictions."
                ],
            },
        ),
        "source_receipt_ledger": _base_skeleton(
            "source_receipt_ledger",
            "Source receipt ledger",
            ("receipt_ledger", "claim_graph", "coverage_gaps"),
            [
                _claim(
                    "claim_receipt_inventory",
                    "Receipt graph inventory placeholder.",
                    ("sr_ledger_receipt_graph",),
                ),
                _claim(
                    "claim_registry_receipt",
                    "Registry receipt placeholder.",
                    ("sr_ledger_gbizinfo",),
                ),
                _claim("claim_law_receipt", "Law receipt placeholder.", ("sr_ledger_egov_law",)),
                _claim(
                    "claim_registry_gap",
                    "Registry coverage gap placeholder.",
                    ("sr_ledger_registry_gap",),
                    support_state="gap",
                ),
            ],
            ledger_receipts,
            [
                _gap(
                    "gap_commercial_registry_receipt",
                    "source_access",
                    "Commercial registry receipt is represented only as a gap.",
                )
            ],
            extra={
                "claim_graph": [
                    {
                        "claim_id": "claim_receipt_inventory",
                        "depends_on_receipt_ids": ["sr_ledger_receipt_graph"],
                    },
                    {
                        "claim_id": "claim_registry_receipt",
                        "depends_on_receipt_ids": ["sr_ledger_gbizinfo"],
                    },
                    {
                        "claim_id": "claim_law_receipt",
                        "depends_on_receipt_ids": ["sr_ledger_egov_law"],
                    },
                    {
                        "claim_id": "claim_registry_gap",
                        "depends_on_receipt_ids": ["sr_ledger_registry_gap"],
                    },
                ]
            },
        ),
        "evidence_answer": _base_skeleton(
            "evidence_answer",
            "Evidence-grounded answer packet",
            ("answer", "claim_refs", "no_hit_lease", "known_gaps"),
            [
                _claim(
                    "claim_answer_core",
                    "Answer claim placeholder tied to official evidence.",
                    ("sr_evidence_primary",),
                ),
                _claim(
                    "claim_notice_context",
                    "Context claim placeholder from an official notice.",
                    ("sr_evidence_notice",),
                ),
                _claim(
                    "claim_receipt_context",
                    "Receipt graph context placeholder.",
                    ("sr_evidence_receipt_graph",),
                ),
            ],
            evidence_receipts,
            [
                _gap(
                    "gap_nonofficial_commentary",
                    "coverage",
                    "Non-official commentary is outside this P0 skeleton.",
                )
            ],
            extra={
                "answer": {
                    "text": "Deterministic answer placeholder; claims carry receipt references."
                }
            },
        ),
        "foreign_investor_japan_public_entry_brief": _base_skeleton(
            "foreign_investor_japan_public_entry_brief",
            "Foreign investor Japan public entry brief packet",
            ("entry_brief", "disclosure_context", "regulatory_baseline", "known_gaps"),
            [
                _claim(
                    "claim_foreign_disclosure_context",
                    "Disclosure context placeholder.",
                    ("sr_foreign_edinet",),
                ),
                _claim(
                    "claim_foreign_legal_baseline",
                    "Legal baseline placeholder.",
                    ("sr_foreign_law",),
                ),
                _claim(
                    "claim_foreign_policy_notice",
                    "Policy notice placeholder.",
                    ("sr_foreign_meti_notice",),
                ),
            ],
            foreign_investor_receipts,
            [
                _gap(
                    "gap_foreign_investment_advice_boundary",
                    "professional_review",
                    "Entry brief is public-source context, not investment, tax, or legal advice.",
                ),
                _gap(
                    "gap_entity_specific_filings",
                    "input_boundary",
                    "Entity-specific filings require the user's selected entity and source refresh.",
                ),
            ],
            extra={
                "entry_brief": {
                    "jurisdiction": "japan_placeholder",
                    "receipt_ids": [
                        "sr_foreign_edinet",
                        "sr_foreign_law",
                        "sr_foreign_meti_notice",
                    ],
                    "advice_claim_enabled": False,
                }
            },
        ),
        "healthcare_regulatory_public_check": _base_skeleton(
            "healthcare_regulatory_public_check",
            "Healthcare regulatory public check packet",
            (
                "healthcare_notice_check",
                "regulatory_baseline",
                "local_requirements",
                "known_gaps",
            ),
            [
                _claim(
                    "claim_healthcare_notice",
                    "Healthcare notice placeholder.",
                    ("sr_healthcare_mhlw_notice",),
                ),
                _claim(
                    "claim_healthcare_law",
                    "Statutory baseline placeholder.",
                    ("sr_healthcare_law",),
                ),
                _claim(
                    "claim_healthcare_local_requirement",
                    "Local requirement placeholder.",
                    ("sr_healthcare_local_notice",),
                ),
            ],
            healthcare_receipts,
            [
                _gap(
                    "gap_healthcare_facility_specificity",
                    "input_boundary",
                    "Facility type and local jurisdiction determine which requirements apply.",
                ),
                _gap(
                    "gap_healthcare_professional_review",
                    "professional_review",
                    "Healthcare regulatory checks require qualified human review before action.",
                ),
            ],
            extra={
                "healthcare_notice_check": {
                    "notice_state": "public_notice_placeholder",
                    "receipt_id": "sr_healthcare_mhlw_notice",
                },
                "regulatory_baseline": {
                    "receipt_id": "sr_healthcare_law",
                    "professional_review_required": True,
                },
                "local_requirements": [
                    {
                        "requirement_id": "local_healthcare_requirement_placeholder",
                        "receipt_id": "sr_healthcare_local_notice",
                        "jurisdiction": "municipality_placeholder",
                    }
                ],
            },
        ),
    }


def build_packet_skeleton_catalog() -> dict[str, dict[str, Any]]:
    """Return deterministic P0 skeleton examples keyed by outcome contract id."""

    return deepcopy(_build_packet_skeletons())


def build_public_packet_skeleton_catalog_shape() -> dict[str, Any]:
    """Return public release-safe skeleton examples.

    Internal tests keep the raw CSV boundary flag names because they mirror the
    runtime privacy contract. The public release artifact uses neutral key names
    so generated discovery surfaces cannot be mistaken for provider CSV data.
    """

    return {
        "schema_version": "jpcite.packet_skeleton_catalog.p0.v1",
        "capsule_id": CAPSULE_ID,
        "catalog_kind": "public_static_shape_examples",
        "paid_packet_body_materialized": False,
        "request_time_llm_dependency": False,
        "live_network_dependency": False,
        "live_aws_dependency": False,
        "real_csv_runtime_enabled": False,
        "no_hit_semantics": NO_HIT_SEMANTICS,
        "skeletons": _rename_public_release_keys(build_packet_skeleton_catalog()),
    }


def get_packet_skeleton(outcome_contract_id: str) -> dict[str, Any]:
    """Return one deterministic P0 skeleton example."""

    skeletons = _build_packet_skeletons()
    try:
        return deepcopy(skeletons[outcome_contract_id])
    except KeyError as exc:
        raise ValueError(f"unknown P0 packet skeleton: {outcome_contract_id}") from exc


def _rename_public_release_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            PUBLIC_RELEASE_KEY_RENAMES.get(key, key): _rename_public_release_keys(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_rename_public_release_keys(item) for item in value]
    return value
