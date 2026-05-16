#!/usr/bin/env python3
"""Register Glue Catalog tables for all packet outcomes + 3 packet sources.

Creates one EXTERNAL TABLE per S3 prefix under
``s3://jpcite-credit-993693061769-202605-derived/`` so Athena can run
cross-source / cross-join queries on the populated derived corpus.

Each row corresponds to one JSON document under the prefix; the table
schema deliberately uses minimal STRING / DOUBLE / BIGINT columns plus
a generic ``data`` JSON column so the regression-resistant downstream
queries can ``json_extract(...)`` on any nested field without re-running
this script. Tables that hold nested arrays (``records`` /
``top_houjin`` / ``metrics``) keep them as ``STRING`` JSON blobs to
side-step JSON-vs-Parquet schema drift.

Tables registered:

- ``packet_houjin_360``         — ``houjin_360/`` (86,849 JSON)
- ``packet_acceptance_probability`` — ``acceptance_probability/`` (225,600 JSON)
- ``packet_program_lineage``    — ``program_lineage/`` (11,601 JSON, uploading)
- 16 Wave 53 outcome tables ``packet_<outcome_kind>`` for each prefix

All tables share the JsonSerDe ``org.openx.data.jsonserde.JsonSerDe``
with ``ignore.malformed.json = true`` and ``case.insensitive = false``.

Idempotent: ``CREATE EXTERNAL TABLE IF NOT EXISTS`` only. Re-running
the script is a no-op for already-registered tables.

Reads AWS_PROFILE=bookyou-recovery / REGION=ap-northeast-1 by default.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import boto3

DATABASE = "jpcite_credit_2026_05"
WORKGROUP = "jpcite-credit-2026-05"
BUCKET = "jpcite-credit-993693061769-202605-derived"
RESULT_S3 = f"s3://{BUCKET}/athena-results/"
PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

# Table registry: (table_name, prefix, columns) — columns is a list of
# (column_name, athena_type). Columns are flat top-level fields commonly
# present in the JSON; nested structures live in raw_json STRING below.
PACKET_TABLES: list[tuple[str, str, list[tuple[str, str]]]] = [
    # 3 packet sources (the high-row-count tier).
    (
        "packet_houjin_360",
        "houjin_360/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),  # JSON struct kept as string
            ("coverage", "string"),
            ("sources", "string"),
            ("records", "string"),
            ("sections", "string"),
        ],
    ),
    (
        "packet_acceptance_probability",
        "acceptance_probability/",
        [
            ("package_kind", "string"),
            ("probability_estimate", "double"),
            ("n_sample", "bigint"),
            ("n_eligible_programs", "bigint"),
            ("freshest_announced_at", "string"),
            ("cohort_definition", "string"),
            ("confidence_interval", "string"),
            ("disclaimer", "string"),
            ("known_gaps", "string"),
            ("adjacency_suggestions", "string"),
            ("header", "string"),
        ],
    ),
    (
        "packet_program_lineage",
        "program_lineage/",
        [
            ("package_kind", "string"),
            ("athena_workgroup", "string"),
            ("header", "string"),
            ("program", "string"),
            ("legal_basis_chain", "string"),
            ("notice_chain", "string"),
            ("saiketsu_chain", "string"),
            ("precedent_chain", "string"),
            ("amendment_timeline", "string"),
            ("coverage_score", "string"),
            ("chain_counts", "string"),
            ("billing_unit", "bigint"),
            ("disclaimer", "string"),
        ],
    ),
    # 16 Wave 53 outcome tables.
    (
        "packet_application_strategy_v1",
        "application_strategy_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("strategy", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_bid_opportunity_matching_v1",
        "bid_opportunity_matching_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("metrics", "string"),
            ("matches", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_cohort_program_recommendation_v1",
        "cohort_program_recommendation_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("recommendations", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_company_public_baseline_v1",
        "company_public_baseline_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("coverage", "string"),
            ("sources", "string"),
            ("records", "string"),
        ],
    ),
    (
        "packet_enforcement_industry_heatmap_v1",
        "enforcement_industry_heatmap_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("metrics", "string"),
            ("top_houjin", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_invoice_houjin_cross_check_v1",
        "invoice_houjin_cross_check_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("nta_invoice", "string"),
            ("gbiz_master", "string"),
            ("mismatch", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_invoice_registrant_public_check_v1",
        "invoice_registrant_public_check_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("nta_status", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_kanpou_gazette_watch_v1",
        "kanpou_gazette_watch_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("entries", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_local_government_subsidy_aggregator_v1",
        "local_government_subsidy_aggregator_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("programs", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_permit_renewal_calendar_v1",
        "permit_renewal_calendar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("schedule", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_program_law_amendment_impact_v1",
        "program_law_amendment_impact_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("amendment_chain", "string"),
            ("impacted_programs", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_regulatory_change_radar_v1",
        "regulatory_change_radar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("signals", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_subsidy_application_timeline_v1",
        "subsidy_application_timeline_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("rounds", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_succession_program_matching_v1",
        "succession_program_matching_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("matches", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_tax_treaty_japan_inbound_v1",
        "tax_treaty_japan_inbound_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("treaty_summary", "string"),
            ("withholding", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_vendor_due_diligence_v1",
        "vendor_due_diligence_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("dd_checks", "string"),
            ("score", "string"),
            ("sources", "string"),
        ],
    ),
    # Wave 53.3 — 10 cross-source deep analysis tables (2026-05-16).
    (
        "packet_patent_corp_360_v1",
        "patent_corp_360_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("patent_signals", "string"),
            ("patent_cap_programs", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_environmental_compliance_radar_v1",
        "environmental_compliance_radar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("env_enforcements", "string"),
            ("gx_program_adoptions", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_statistical_cohort_proxy_v1",
        "statistical_cohort_proxy_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("cohort_stats", "string"),
            ("industry_stat_refs", "string"),
            ("top_houjin", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_diet_question_program_link_v1",
        "diet_question_program_link_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("program_name", "string"),
            ("program_source_url", "string"),
            ("policy_origin_facts", "string"),
            ("amendment_diffs", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_edinet_finance_program_match_v1",
        "edinet_finance_program_match_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("adoption_rows", "string"),
            ("tax_rulesets", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_trademark_brand_protection_v1",
        "trademark_brand_protection_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("trademark_adoption_rows", "string"),
            ("trademark_program_caps", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_statistics_market_size_v1",
        "statistics_market_size_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("industry_stat_refs", "string"),
            ("market_cell", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_cross_administrative_timeline_v1",
        "cross_administrative_timeline_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("events", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_public_procurement_trend_v1",
        "public_procurement_trend_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("cell_stats", "string"),
            ("top_winners", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_regulation_impact_simulator_v1",
        "regulation_impact_simulator_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("amendment", "string"),
            ("impacted_houjin", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    # Wave 54 — 10 cross-source packet tables (2026-05-16).
    (
        "packet_patent_environmental_link_v1",
        "patent_environmental_link_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("patent_adoptions", "string"),
            ("env_signals", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_diet_question_amendment_correlate_v1",
        "diet_question_amendment_correlate_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("program_name", "string"),
            ("diet_policy_origin_facts", "string"),
            ("related_shitsugi", "string"),
            ("amendment_diffs", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_edinet_program_subsidy_compounding_v1",
        "edinet_program_subsidy_compounding_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("houjin_summary", "string"),
            ("edinet_anchor_aliases", "string"),
            ("subsidy_adoption_breakdown", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_kanpou_program_event_link_v1",
        "kanpou_program_event_link_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("program_name", "string"),
            ("kanpou_relevant_events", "string"),
            ("all_other_events", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_kfs_saiketsu_industry_radar_v1",
        "kfs_saiketsu_industry_radar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("tax_type", "string"),
            ("industry_buckets", "string"),
            ("saiketsu_sample", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_municipal_budget_match_v1",
        "municipal_budget_match_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("prefecture", "string"),
            ("top_municipalities", "string"),
            ("top_programs", "string"),
            ("total_adoptions", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_trademark_industry_density_v1",
        "trademark_industry_density_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("jsic_major", "string"),
            ("jsic_name_ja", "string"),
            ("trademark_adoptions", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_environmental_disposal_radar_v1",
        "environmental_disposal_radar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("issuing_authority", "string"),
            ("disposal_enforcements", "string"),
            ("municipality_actions", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_regulatory_change_industry_impact_v1",
        "regulatory_change_industry_impact_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("jsic_major", "string"),
            ("jsic_name_ja", "string"),
            ("industry_program_amendments", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
    (
        "packet_gbiz_invoice_dispatch_match_v1",
        "gbiz_invoice_dispatch_match_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("cohort_definition", "string"),
            ("invoice_registrant", "string"),
            ("houjin_master_match", "string"),
            ("adoption_history", "string"),
            ("enforcement_history", "string"),
            ("metrics", "string"),
            ("known_gaps", "string"),
            ("sources", "string"),
            ("disclaimer", "string"),
            ("jpcite_cost_jpy", "string"),
            ("request_time_llm_call_performed", "string"),
        ],
    ),
]


# JPCIR header columns shared by every Wave 56-58 packet (super-set).
# JsonSerDe `ignore.malformed.json = true` + missing-field semantics let us
# use a unified kitchen-sink schema where each generator only fills the
# subset it cares about; absent fields are returned as NULL by Athena.
_WAVE_56_58_COLUMNS: list[tuple[str, str]] = [
    # JPCIR header
    ("object_id", "string"),
    ("object_type", "string"),
    ("package_id", "string"),
    ("package_kind", "string"),
    ("created_at", "string"),
    ("generated_at", "string"),
    ("producer", "string"),
    ("schema_version", "string"),
    ("subject", "string"),
    ("cohort_definition", "string"),
    ("metrics", "string"),
    ("known_gaps", "string"),
    ("sources", "string"),
    ("disclaimer", "string"),
    ("jpcite_cost_jpy", "string"),
    ("request_time_llm_call_performed", "string"),
    # Wave 56 (time-series) body fields
    ("entity_id", "string"),
    ("amendment_history", "string"),
    ("snapshot_periods", "string"),
    ("prefecture", "string"),
    ("monthly_distribution", "string"),
    ("peak_month", "string"),
    ("peak_count", "string"),
    ("total_cases", "string"),
    ("jsic_major", "string"),
    ("fiscal_years", "string"),
    ("total_count", "string"),
    ("total_amount_yen", "string"),
    ("tax_category", "string"),
    ("phase_changes", "string"),
    ("monthly_registrations", "string"),
    ("active_total", "string"),
    ("revoked_total", "string"),
    ("quarter", "string"),
    ("field_top", "string"),
    ("total_diffs", "string"),
    ("program_entity_id", "string"),
    ("recent_rounds", "string"),
    ("open_month_distribution", "string"),
    ("predicted_open_month_mode", "string"),
    ("ministry", "string"),
    ("total_bids", "string"),
    ("adoption_event_monthly", "string"),
    ("application_close_monthly", "string"),
    ("adoption_total", "string"),
    ("application_close_total", "string"),
    ("scope", "string"),
    ("bursts", "string"),
    ("monthly_mean", "string"),
    # Wave 57 (geographic) body fields
    ("registrant_kind_distribution", "string"),
    ("total_registrants", "string"),
    ("active_registrants", "string"),
    ("municipality_propensity", "string"),
    ("top_prefecture", "string"),
    ("top_adoptions", "string"),
    ("arbitrage_candidates", "string"),
    ("municipality_top", "string"),
    ("municipality_program_total", "string"),
    ("subject_area", "string"),
    ("court_distribution", "string"),
    ("total_decisions", "string"),
    ("env_programs", "string"),
    ("env_decisions", "string"),
    ("env_enforcement", "string"),
    ("compliance_score", "string"),
    ("tier_distribution", "string"),
    ("authority_distribution", "string"),
    ("total_programs", "string"),
    ("industry_match", "string"),
    ("enforcement_kind_distribution", "string"),
    ("rural_municipalities", "string"),
    ("rural_municipality_total", "string"),
    ("municipalities_with_coverage", "string"),
    # Wave 58 (relationship) body fields
    ("overlap_groups", "string"),
    ("entity_name", "string"),
    ("entity_role", "string"),
    ("bid_history", "string"),
    ("certification_id", "string"),
    ("certification_name", "string"),
    ("linked_houjin", "string"),
    ("employment_programs", "string"),
    ("houjin_bangou", "string"),
    ("chain", "string"),
    ("total_adoptions", "string"),
    ("first_event_date", "string"),
    ("latest_event_date", "string"),
    ("name_prefix", "string"),
    ("linked_entities", "string"),
    ("group_size_total", "string"),
    ("support_organizations", "string"),
    ("top_industry_link", "string"),
    ("permits", "string"),
    ("company_name", "string"),
    ("adoption_link", "string"),
    ("bid_link", "string"),
    ("vendor_name", "string"),
    ("payment_history", "string"),
    ("unique_procurer_count", "string"),
]

# (table_name, prefix) pairs for the 30 Wave 56-58 packet types — all
# reuse the shared `_WAVE_56_58_COLUMNS` super-set schema above.
_WAVE_56_58_TABLES: list[tuple[str, str]] = [
    # Wave 56 — time-series (commit fe657f0c6).
    ("packet_program_amendment_timeline_v2", "program_amendment_timeline_v2/"),
    ("packet_enforcement_seasonal_trend_v1", "enforcement_seasonal_trend_v1/"),
    ("packet_adoption_fiscal_cycle_v1", "adoption_fiscal_cycle_v1/"),
    ("packet_tax_ruleset_phase_change_v1", "tax_ruleset_phase_change_v1/"),
    ("packet_invoice_registration_velocity_v1", "invoice_registration_velocity_v1/"),
    ("packet_regulatory_q_over_q_diff_v1", "regulatory_q_over_q_diff_v1/"),
    (
        "packet_subsidy_application_window_predict_v1",
        "subsidy_application_window_predict_v1/",
    ),
    ("packet_bid_announcement_seasonality_v1", "bid_announcement_seasonality_v1/"),
    ("packet_succession_event_pulse_v1", "succession_event_pulse_v1/"),
    ("packet_kanpou_event_burst_v1", "kanpou_event_burst_v1/"),
    # Wave 57 — geographic (commit f5aeb3168).
    ("packet_city_jct_density_v1", "city_jct_density_v1/"),
    ("packet_city_size_subsidy_propensity_v1", "city_size_subsidy_propensity_v1/"),
    ("packet_cross_prefecture_arbitrage_v1", "cross_prefecture_arbitrage_v1/"),
    (
        "packet_municipality_subsidy_inventory_v1",
        "municipality_subsidy_inventory_v1/",
    ),
    (
        "packet_prefecture_court_decision_focus_v1",
        "prefecture_court_decision_focus_v1/",
    ),
    (
        "packet_prefecture_environmental_compliance_v1",
        "prefecture_environmental_compliance_v1/",
    ),
    ("packet_prefecture_program_heatmap_v1", "prefecture_program_heatmap_v1/"),
    ("packet_region_industry_match_v1", "region_industry_match_v1/"),
    ("packet_regional_enforcement_density_v1", "regional_enforcement_density_v1/"),
    ("packet_rural_subsidy_coverage_v1", "rural_subsidy_coverage_v1/"),
    # Wave 58 — relationship (commit 54bafe53d).
    ("packet_board_member_overlap_v1", "board_member_overlap_v1/"),
    ("packet_business_partner_360_v1", "business_partner_360_v1/"),
    ("packet_certification_houjin_link_v1", "certification_houjin_link_v1/"),
    (
        "packet_employment_program_eligibility_v1",
        "employment_program_eligibility_v1/",
    ),
    ("packet_founding_succession_chain_v1", "founding_succession_chain_v1/"),
    ("packet_houjin_parent_subsidiary_v1", "houjin_parent_subsidiary_v1/"),
    ("packet_industry_association_link_v1", "industry_association_link_v1/"),
    ("packet_license_houjin_jurisdiction_v1", "license_houjin_jurisdiction_v1/"),
    ("packet_public_listed_program_link_v1", "public_listed_program_link_v1/"),
    ("packet_vendor_payment_history_match_v1", "vendor_payment_history_match_v1/"),
]

# Append Wave 56-58 entries with the shared super-set column list.
for _name, _prefix in _WAVE_56_58_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 62 — sectoral cross packets (catalog 112 → 122). All 10 share the
# jsic_major industry cohort with a generic "<sector>_programs" payload +
# enforcement_distribution_n + candidate_pool_size. Reuse the same shared
# super-set columns; specific arrays land in raw_json.
_WAVE_62_TABLES: list[tuple[str, str]] = [
    ("packet_healthcare_compliance_subsidy_v1", "healthcare_compliance_subsidy_v1/"),
    ("packet_agriculture_program_intensity_v1", "agriculture_program_intensity_v1/"),
    ("packet_transport_logistics_grants_v1", "transport_logistics_grants_v1/"),
    ("packet_energy_efficiency_subsidy_v1", "energy_efficiency_subsidy_v1/"),
    ("packet_construction_public_works_v1", "construction_public_works_v1/"),
    ("packet_manufacturing_dx_grants_v1", "manufacturing_dx_grants_v1/"),
    ("packet_retail_inbound_subsidy_v1", "retail_inbound_subsidy_v1/"),
    ("packet_education_research_grants_v1", "education_research_grants_v1/"),
    ("packet_finance_fintech_regulation_v1", "finance_fintech_regulation_v1/"),
    ("packet_non_profit_program_overlay_v1", "non_profit_program_overlay_v1/"),
]

for _name, _prefix in _WAVE_62_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 65 — financial markets cross packets (catalog 142 → 152). All 10
# share the jsic_major industry cohort with descriptive adoption_n + optional
# amount_total_yen proxy. Reuse the shared super-set columns; specific
# fields land in raw_json.
_WAVE_65_TABLES: list[tuple[str, str]] = [
    ("packet_listed_company_disclosure_pulse_v1", "listed_company_disclosure_pulse_v1/"),
    ("packet_ipo_pipeline_signal_v1", "ipo_pipeline_signal_v1/"),
    ("packet_bond_issuance_pattern_v1", "bond_issuance_pattern_v1/"),
    ("packet_dividend_policy_stability_v1", "dividend_policy_stability_v1/"),
    ("packet_shareholder_return_intensity_v1", "shareholder_return_intensity_v1/"),
    ("packet_capital_raising_history_v1", "capital_raising_history_v1/"),
    ("packet_executive_compensation_disclosure_v1", "executive_compensation_disclosure_v1/"),
    ("packet_audit_firm_rotation_v1", "audit_firm_rotation_v1/"),
    ("packet_tax_haven_subsidiary_v1", "tax_haven_subsidiary_v1/"),
    ("packet_fpd_etf_holdings_v1", "fpd_etf_holdings_v1/"),
]

for _name, _prefix in _WAVE_65_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 63 — governance / compliance / ESG cross packets (catalog 132 → 142).
# All 10 share the jsic_major industry cohort with topic-specific compliance
# / governance proxy aggregations (board diversity / insider trading / RPT /
# ISO certification / antimonopoly / consumer protection / environmental
# disclosure / labor dispute / product recall / regulatory audit outcomes).
# Reuse the shared super-set columns; topic-specific arrays land in raw_json.
_WAVE_63_TABLES: list[tuple[str, str]] = [
    ("packet_board_diversity_signal_v1", "board_diversity_signal_v1/"),
    ("packet_insider_trading_disclosure_v1", "insider_trading_disclosure_v1/"),
    ("packet_related_party_transaction_v1", "related_party_transaction_v1/"),
    ("packet_iso_certification_overlap_v1", "iso_certification_overlap_v1/"),
    (
        "packet_antimonopoly_violation_intensity_v1",
        "antimonopoly_violation_intensity_v1/",
    ),
    (
        "packet_consumer_protection_compliance_v1",
        "consumer_protection_compliance_v1/",
    ),
    ("packet_environmental_disclosure_v1", "environmental_disclosure_v1/"),
    ("packet_labor_dispute_event_rate_v1", "labor_dispute_event_rate_v1/"),
    ("packet_product_recall_intensity_v1", "product_recall_intensity_v1/"),
    ("packet_regulatory_audit_outcomes_v1", "regulatory_audit_outcomes_v1/"),
]

for _name, _prefix in _WAVE_63_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 64 — international / cross-border packets (catalog 142 → 152). Mix of
# country (am_tax_treaty / jurisdiction) and jsic_major industry cohorts:
# 5 country (FDI / DTT impact / bilateral trade / FDI security review /
# international arbitration venue) + 5 industry (import/export license /
# WTO subsidy compliance / EU GDPR overlap / US export control overlap /
# cross-border data transfer). Reuse the shared super-set columns;
# topic-specific arrays land in raw_json.
_WAVE_64_TABLES: list[tuple[str, str]] = [
    ("packet_foreign_direct_investment_v1", "foreign_direct_investment_v1/"),
    ("packet_double_tax_treaty_impact_v1", "double_tax_treaty_impact_v1/"),
    ("packet_import_export_license_v1", "import_export_license_v1/"),
    ("packet_wto_subsidy_compliance_v1", "wto_subsidy_compliance_v1/"),
    ("packet_eu_gdpr_overlap_v1", "eu_gdpr_overlap_v1/"),
    ("packet_us_export_control_overlap_v1", "us_export_control_overlap_v1/"),
    ("packet_bilateral_trade_program_v1", "bilateral_trade_program_v1/"),
    ("packet_fdi_security_review_v1", "fdi_security_review_v1/"),
    ("packet_cross_border_data_transfer_v1", "cross_border_data_transfer_v1/"),
    (
        "packet_international_arbitration_venue_v1",
        "international_arbitration_venue_v1/",
    ),
]

for _name, _prefix in _WAVE_64_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 60 — cross-industry macro packets (catalog 92 → 102). All 10 share
# the jsic_major industry cohort with topic-specific macro proxy
# aggregations (lifecycle stage / carbon reporting / competitor uptake /
# DX subsidy chain / export program match / green investment eligibility /
# industry compliance index / KPI funding correlation / patent subsidy
# intersection / subsidy ROI estimate). Reuse the shared super-set columns;
# topic-specific arrays land in raw_json.
_WAVE_60_TABLES: list[tuple[str, str]] = [
    ("packet_business_lifecycle_stage_v1", "business_lifecycle_stage_v1/"),
    ("packet_carbon_reporting_compliance_v1", "carbon_reporting_compliance_v1/"),
    ("packet_competitor_subsidy_uptake_v1", "competitor_subsidy_uptake_v1/"),
    (
        "packet_digital_transformation_subsidy_chain_v1",
        "digital_transformation_subsidy_chain_v1/",
    ),
    ("packet_export_program_match_v1", "export_program_match_v1/"),
    ("packet_green_investment_eligibility_v1", "green_investment_eligibility_v1/"),
    ("packet_industry_compliance_index_v1", "industry_compliance_index_v1/"),
    ("packet_kpi_funding_correlation_v1", "kpi_funding_correlation_v1/"),
    ("packet_patent_subsidy_intersection_v1", "patent_subsidy_intersection_v1/"),
    ("packet_subsidy_roi_estimate_v1", "subsidy_roi_estimate_v1/"),
]

for _name, _prefix in _WAVE_60_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 61 — financial / monetary cross packets (catalog 102 → 112). All 10
# share the jsic_major industry cohort with financing-topic proxy
# aggregations (angel tax uptake / cash runway estimate / cross-border
# remittance / debt subsidy stack / funding-to-revenue ratio / invoice
# payment velocity / M&A event signals / payroll subsidy intensity /
# revenue volatility subsidy offset / trade finance eligibility).
_WAVE_61_TABLES: list[tuple[str, str]] = [
    ("packet_angel_tax_uptake_v1", "angel_tax_uptake_v1/"),
    ("packet_cash_runway_estimate_v1", "cash_runway_estimate_v1/"),
    ("packet_cross_border_remittance_v1", "cross_border_remittance_v1/"),
    ("packet_debt_subsidy_stack_v1", "debt_subsidy_stack_v1/"),
    ("packet_funding_to_revenue_ratio_v1", "funding_to_revenue_ratio_v1/"),
    ("packet_invoice_payment_velocity_v1", "invoice_payment_velocity_v1/"),
    ("packet_m_a_event_signals_v1", "m_a_event_signals_v1/"),
    ("packet_payroll_subsidy_intensity_v1", "payroll_subsidy_intensity_v1/"),
    (
        "packet_revenue_volatility_subsidy_offset_v1",
        "revenue_volatility_subsidy_offset_v1/",
    ),
    ("packet_trade_finance_eligibility_v1", "trade_finance_eligibility_v1/"),
]

for _name, _prefix in _WAVE_61_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 68 — supply chain cross packets (catalog 152 → 162). All 10 share the
# jsic_major industry cohort with descriptive adoption_n + optional
# amount_total_yen proxy covering vendor concentration / logistics partner /
# inventory turnover / supplier credit rating / import dependency / JIT /
# commodity exposure / secondary supplier resilience / trade credit terms /
# contract manufacturing intensity. Reuse the shared super-set columns;
# topic-specific fields land in raw_json.
_WAVE_68_TABLES: list[tuple[str, str]] = [
    ("packet_vendor_concentration_risk_v1", "vendor_concentration_risk_v1/"),
    ("packet_logistics_partner_360_v1", "logistics_partner_360_v1/"),
    ("packet_inventory_turnover_pattern_v1", "inventory_turnover_pattern_v1/"),
    (
        "packet_supplier_credit_rating_match_v1",
        "supplier_credit_rating_match_v1/",
    ),
    ("packet_import_dependency_country_v1", "import_dependency_country_v1/"),
    ("packet_just_in_time_intensity_v1", "just_in_time_intensity_v1/"),
    ("packet_commodity_price_exposure_v1", "commodity_price_exposure_v1/"),
    (
        "packet_secondary_supplier_resilience_v1",
        "secondary_supplier_resilience_v1/",
    ),
    ("packet_trade_credit_terms_v1", "trade_credit_terms_v1/"),
    (
        "packet_contract_manufacturing_intensity_v1",
        "contract_manufacturing_intensity_v1/",
    ),
]

for _name, _prefix in _WAVE_68_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 66 — personal data / PII compliance cross packets (catalog 152 → 162).
# All 10 share the jsic_major industry cohort with adoption_n proxy + topic-
# specific 個情法 disclaimer + 2 PPC / e-Gov sources. Reuse the shared super-
# set columns; subject_kind = jsic_major.
_WAVE_66_TABLES: list[tuple[str, str]] = [
    (
        "packet_pii_classification_compliance_v1",
        "pii_classification_compliance_v1/",
    ),
    ("packet_data_breach_event_history_v1", "data_breach_event_history_v1/"),
    (
        "packet_opt_out_mechanism_disclosure_v1",
        "opt_out_mechanism_disclosure_v1/",
    ),
    ("packet_third_party_data_transfer_v1", "third_party_data_transfer_v1/"),
    (
        "packet_anonymization_method_disclosure_v1",
        "anonymization_method_disclosure_v1/",
    ),
    (
        "packet_mandatory_breach_notice_sla_v1",
        "mandatory_breach_notice_sla_v1/",
    ),
    ("packet_consent_collection_record_v1", "consent_collection_record_v1/"),
    ("packet_data_retention_policy_v1", "data_retention_policy_v1/"),
    ("packet_cross_border_pii_transfer_v1", "cross_border_pii_transfer_v1/"),
    ("packet_sensitive_data_handling_v1", "sensitive_data_handling_v1/"),
]

for _name, _prefix in _WAVE_66_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 67 — technical infrastructure cross packets (catalog 162 → 172). All 10
# share the jsic_major industry cohort with descriptive adoption_n covering
# system outage incident log / cybersecurity certification / cloud dependency
# disclosure / OSS license compliance / API uptime SLA / data center location
# / DR capability / third-party audit / DevOps maturity / automation
# intensity. Reuse the shared super-set columns; topic-specific fields land
# in raw_json.
_WAVE_67_TABLES: list[tuple[str, str]] = [
    (
        "packet_system_outage_incident_log_v1",
        "system_outage_incident_log_v1/",
    ),
    (
        "packet_cybersecurity_certification_v1",
        "cybersecurity_certification_v1/",
    ),
    (
        "packet_cloud_dependency_disclosure_v1",
        "cloud_dependency_disclosure_v1/",
    ),
    (
        "packet_open_source_license_compliance_v1",
        "open_source_license_compliance_v1/",
    ),
    (
        "packet_api_uptime_sla_obligation_v1",
        "api_uptime_sla_obligation_v1/",
    ),
    ("packet_data_center_location_v1", "data_center_location_v1/"),
    (
        "packet_disaster_recovery_capability_v1",
        "disaster_recovery_capability_v1/",
    ),
    (
        "packet_third_party_audit_certification_v1",
        "third_party_audit_certification_v1/",
    ),
    ("packet_devops_maturity_signal_v1", "devops_maturity_signal_v1/"),
    (
        "packet_automation_intensity_index_v1",
        "automation_intensity_index_v1/",
    ),
]

for _name, _prefix in _WAVE_67_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 72 — ML/AI compliance cross packets (catalog 192 → 202). All 10 share
# the jsic_major industry cohort with descriptive adoption_n proxy covering
# AI governance disclosure / algorithmic decision transparency / bias audit
# disclosure / AI model lineage / training data provenance / automated
# decision dispute rate / explainability compliance / deepfake disclosure
# obligation / AI safety certification / AI regulatory horizon scan. Reuse
# the shared super-set columns; topic-specific fields land in raw_json.
_WAVE_72_TABLES: list[tuple[str, str]] = [
    ("packet_ai_governance_disclosure_v1", "ai_governance_disclosure_v1/"),
    (
        "packet_algorithmic_decision_transparency_v1",
        "algorithmic_decision_transparency_v1/",
    ),
    ("packet_bias_audit_disclosure_v1", "bias_audit_disclosure_v1/"),
    ("packet_ai_model_lineage_v1", "ai_model_lineage_v1/"),
    ("packet_training_data_provenance_v1", "training_data_provenance_v1/"),
    (
        "packet_automated_decision_dispute_rate_v1",
        "automated_decision_dispute_rate_v1/",
    ),
    ("packet_explainability_compliance_v1", "explainability_compliance_v1/"),
    (
        "packet_deepfake_disclosure_obligation_v1",
        "deepfake_disclosure_obligation_v1/",
    ),
    ("packet_ai_safety_certification_v1", "ai_safety_certification_v1/"),
    (
        "packet_ai_regulatory_horizon_scan_v1",
        "ai_regulatory_horizon_scan_v1/",
    ),
]

for _name, _prefix in _WAVE_72_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 73 — climate finance cross packets (catalog 212 → 222). All 10 share
# the jsic_major industry cohort with descriptive adoption_n + optional
# amount_total_yen proxy covering climate transition plan / Scope 3 emissions
# disclosure / transition finance eligibility / green bond issuance / climate
# alignment target / sustainability-linked loan / carbon credit inventory /
# TCFD disclosure completeness / just transition program / physical climate
# risk geography. Reuse the shared super-set columns; topic-specific fields
# land in raw_json.
_WAVE_73_TABLES: list[tuple[str, str]] = [
    ("packet_climate_transition_plan_v1", "climate_transition_plan_v1/"),
    (
        "packet_scope3_emissions_disclosure_v1",
        "scope3_emissions_disclosure_v1/",
    ),
    (
        "packet_transition_finance_eligibility_v1",
        "transition_finance_eligibility_v1/",
    ),
    ("packet_green_bond_issuance_v1", "green_bond_issuance_v1/"),
    ("packet_climate_alignment_target_v1", "climate_alignment_target_v1/"),
    (
        "packet_sustainability_linked_loan_v1",
        "sustainability_linked_loan_v1/",
    ),
    ("packet_carbon_credit_inventory_v1", "carbon_credit_inventory_v1/"),
    (
        "packet_tcfd_disclosure_completeness_v1",
        "tcfd_disclosure_completeness_v1/",
    ),
    ("packet_just_transition_program_v1", "just_transition_program_v1/"),
    (
        "packet_physical_climate_risk_geo_v1",
        "physical_climate_risk_geo_v1/",
    ),
]

for _name, _prefix in _WAVE_73_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 74 — fintech / digital assets cross packets (catalog 222 → 232). All 10
# share the jsic_major industry cohort with descriptive adoption_n proxy
# covering Fintech license inventory / crypto asset disclosure / 資金決済法
# compliance / stablecoin issuer signal / DeFi platform disclosure / 中央銀行
# デジタル通貨 (デジタル円) pilot / Fintech regulatory sandbox participation
# / API banking compliance / mobile payment intensity / fraud alert
# disclosure. Reuse the shared super-set columns; topic-specific fields land
# in raw_json.
_WAVE_74_TABLES: list[tuple[str, str]] = [
    ("packet_fintech_license_inventory_v1", "fintech_license_inventory_v1/"),
    ("packet_crypto_asset_disclosure_v1", "crypto_asset_disclosure_v1/"),
    (
        "packet_payment_service_act_compliance_v1",
        "payment_service_act_compliance_v1/",
    ),
    ("packet_stablecoin_issuer_signal_v1", "stablecoin_issuer_signal_v1/"),
    ("packet_defi_platform_disclosure_v1", "defi_platform_disclosure_v1/"),
    ("packet_digital_yen_pilot_v1", "digital_yen_pilot_v1/"),
    (
        "packet_fintech_sandbox_participation_v1",
        "fintech_sandbox_participation_v1/",
    ),
    ("packet_api_banking_compliance_v1", "api_banking_compliance_v1/"),
    ("packet_mobile_payment_intensity_v1", "mobile_payment_intensity_v1/"),
    ("packet_fraud_alert_disclosure_v1", "fraud_alert_disclosure_v1/"),
]

for _name, _prefix in _WAVE_74_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 70 — industry x geographic intersection houjin universal key packets
# (catalog 192 -> 202). All 10 share the **houjin** subject cohort with
# (houjin_bangou, industry_jsic_medium, prefecture or municipality) intersection
# carrying houjin_bangou as universal key. Fixes the canonical moat hole where
# prefecture cohort and industry cohort packets carried no shared key (Wave 67
# Q12+Q14 EMPTY intersection). subject_kind = houjin.
_WAVE_70_TABLES: list[tuple[str, str]] = [
    (
        "packet_industry_x_prefecture_houjin_v1",
        "industry_x_prefecture_houjin_v1/",
    ),
    (
        "packet_prefecture_x_industry_density_v1",
        "prefecture_x_industry_density_v1/",
    ),
    (
        "packet_regional_industry_subsidy_match_v1",
        "regional_industry_subsidy_match_v1/",
    ),
    (
        "packet_municipality_industry_directory_v1",
        "municipality_industry_directory_v1/",
    ),
    (
        "packet_prefecture_industry_court_overlay_v1",
        "prefecture_industry_court_overlay_v1/",
    ),
    (
        "packet_regional_industry_violation_density_v1",
        "regional_industry_violation_density_v1/",
    ),
    (
        "packet_city_industry_diversification_v1",
        "city_industry_diversification_v1/",
    ),
    (
        "packet_prefecture_industry_inbound_v1",
        "prefecture_industry_inbound_v1/",
    ),
    (
        "packet_regional_industry_export_intensity_v1",
        "regional_industry_export_intensity_v1/",
    ),
    (
        "packet_municipality_industry_cluster_v1",
        "municipality_industry_cluster_v1/",
    ),
]

for _name, _prefix in _WAVE_70_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 69 — entity_360 cross-source houjin-cohort packets (catalog 182 -> 192).
# All 10 share the **houjin** subject cohort with houjin_bangou as canonical
# universal key. Each axis (summary / compliance / subsidy / court / invoice /
# certification / succession / partner / temporal / risk) bundles a single
# cohort packet per houjin, so AI agents only need 1 fetch instead of 6+
# separate registry calls. Reuse the shared super-set columns; axis-specific
# fields land in raw_json. subject_kind = houjin.
_WAVE_69_TABLES: list[tuple[str, str]] = [
    ("packet_entity_360_summary_v1", "entity_360_summary_v1/"),
    ("packet_entity_compliance_360_v1", "entity_compliance_360_v1/"),
    ("packet_entity_subsidy_360_v1", "entity_subsidy_360_v1/"),
    ("packet_entity_court_360_v1", "entity_court_360_v1/"),
    ("packet_entity_invoice_360_v1", "entity_invoice_360_v1/"),
    ("packet_entity_certification_360_v1", "entity_certification_360_v1/"),
    ("packet_entity_succession_360_v1", "entity_succession_360_v1/"),
    ("packet_entity_partner_360_v1", "entity_partner_360_v1/"),
    ("packet_entity_temporal_pulse_v1", "entity_temporal_pulse_v1/"),
    ("packet_entity_risk_360_v1", "entity_risk_360_v1/"),
]

for _name, _prefix in _WAVE_69_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 75 — employment / labor cross packets (catalog 232 → 242). All 10 share
# the jsic_major industry cohort with descriptive adoption_n proxy covering
# workforce demographic signal / HR subsidy uptake / labor standard violation
# / overtime intensity disclosure / paid leave compliance / D&I program
# participation / foreign worker program / internship intensity / executive
# succession planning / wage gap disclosure. Each carries 2 一次 sources
# (厚労省 / 内閣府 男女共同参画局 / 出入国在留管理庁 / OTIT / 文科省 / 経産省
# / 中小企業庁 / 中小機構) + topic-specific disclaimer (労基法、女性活躍
# 推進法、障害者雇用促進法、入管法、技能実習法、経営承継円滑化法、社労士
# 法、行政書士法 等)。Reuse the shared super-set columns; topic-specific
# fields land in raw_json.
_WAVE_75_TABLES: list[tuple[str, str]] = [
    (
        "packet_workforce_demographic_signal_v1",
        "workforce_demographic_signal_v1/",
    ),
    ("packet_hr_subsidy_uptake_v1", "hr_subsidy_uptake_v1/"),
    ("packet_labor_standard_violation_v1", "labor_standard_violation_v1/"),
    (
        "packet_overtime_intensity_disclosure_v1",
        "overtime_intensity_disclosure_v1/",
    ),
    ("packet_paid_leave_compliance_v1", "paid_leave_compliance_v1/"),
    (
        "packet_diversity_inclusion_program_v1",
        "diversity_inclusion_program_v1/",
    ),
    ("packet_foreign_worker_program_v1", "foreign_worker_program_v1/"),
    (
        "packet_internship_program_intensity_v1",
        "internship_program_intensity_v1/",
    ),
    (
        "packet_executive_succession_planning_v1",
        "executive_succession_planning_v1/",
    ),
    ("packet_wage_gap_disclosure_v1", "wage_gap_disclosure_v1/"),
]

for _name, _prefix in _WAVE_75_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 76 — startup / scaleup signal cross packets (catalog 242 → 252). All 10
# share the jsic_major industry cohort with descriptive adoption_n proxy
# covering unicorn potential signal / VC funding milestone pulse / J-Startup
# certification / deeptech subsidy intensity / university spinout signal /
# angel investor overlap / incubator program participation / research grant
# chain / IP creation velocity / growth metric disclosure. Reuse the shared
# super-set columns; topic-specific fields land in raw_json.
_WAVE_76_TABLES: list[tuple[str, str]] = [
    ("packet_unicorn_potential_signal_v1", "unicorn_potential_signal_v1/"),
    ("packet_vc_funding_milestone_pulse_v1", "vc_funding_milestone_pulse_v1/"),
    ("packet_j_startup_certification_v1", "j_startup_certification_v1/"),
    ("packet_deeptech_subsidy_intensity_v1", "deeptech_subsidy_intensity_v1/"),
    ("packet_university_spinout_signal_v1", "university_spinout_signal_v1/"),
    ("packet_angel_investor_overlap_v1", "angel_investor_overlap_v1/"),
    (
        "packet_incubator_program_participation_v1",
        "incubator_program_participation_v1/",
    ),
    ("packet_research_grant_chain_v1", "research_grant_chain_v1/"),
    ("packet_ip_creation_velocity_v1", "ip_creation_velocity_v1/"),
    ("packet_growth_metric_disclosure_v1", "growth_metric_disclosure_v1/"),
]

for _name, _prefix in _WAVE_76_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 77 corporate lifecycle event packet tables (10 generators, 2026-05-16). All
# share the jsic_major industry cohort with descriptive adoption_n proxy covering
# establishment pulse / dissolution signal / merger event pulse / demerger split
# signal / bankruptcy risk proxy / rehabilitation petition history / liquidation
# program match / subsidiary creation pulse / headquarters relocation / business
# transfer signal. Reuse the shared super-set columns; topic-specific fields land
# in raw_json.
_WAVE_77_TABLES: list[tuple[str, str]] = [
    ("packet_establishment_pulse_v1", "establishment_pulse_v1/"),
    ("packet_dissolution_signal_v1", "dissolution_signal_v1/"),
    ("packet_merger_event_pulse_v1", "merger_event_pulse_v1/"),
    ("packet_demerger_split_signal_v1", "demerger_split_signal_v1/"),
    ("packet_bankruptcy_risk_proxy_v1", "bankruptcy_risk_proxy_v1/"),
    (
        "packet_rehabilitation_petition_history_v1",
        "rehabilitation_petition_history_v1/",
    ),
    ("packet_liquidation_program_match_v1", "liquidation_program_match_v1/"),
    ("packet_subsidiary_creation_pulse_v1", "subsidiary_creation_pulse_v1/"),
    ("packet_headquarters_relocation_v1", "headquarters_relocation_v1/"),
    ("packet_business_transfer_signal_v1", "business_transfer_signal_v1/"),
]

for _name, _prefix in _WAVE_77_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 78 license / permit cross packet tables (10 generators, 2026-05-16). All
# share the jsic_major industry cohort with descriptive adoption_n proxy covering
# construction license overlay (建設業法 §3, 28業種) / medical facility license
# (医療法 §7) / food business permit (食品衛生法 §55, 32業種) / education
# authority license (学校教育法 §4 / 私立学校法 §30) / transport passenger
# license (道路運送法 §3) / alcohol retail license (酒税法 §9) / financial
# business license (金商法 §29 / 銀行法 §4 / 貸金業法 §3 / 資金決済法 §37) /
# environmental facility permit (大気汚染防止法 §6 / 水質汚濁防止法 §5 /
# 環境影響評価法 §3) / waste disposal permit (廃棄物処理法 §7, §14) / real
# estate broker license (宅建業法 §3). Reuse the shared super-set columns;
# topic-specific fields land in raw_json.
_WAVE_78_TABLES: list[tuple[str, str]] = [
    (
        "packet_construction_license_overlay_v1",
        "construction_license_overlay_v1/",
    ),
    ("packet_medical_facility_license_v1", "medical_facility_license_v1/"),
    ("packet_food_business_permit_v1", "food_business_permit_v1/"),
    (
        "packet_education_authority_license_v1",
        "education_authority_license_v1/",
    ),
    (
        "packet_transport_passenger_license_v1",
        "transport_passenger_license_v1/",
    ),
    ("packet_alcohol_retail_license_v1", "alcohol_retail_license_v1/"),
    (
        "packet_financial_business_license_v1",
        "financial_business_license_v1/",
    ),
    (
        "packet_environmental_facility_permit_v1",
        "environmental_facility_permit_v1/",
    ),
    ("packet_waste_disposal_permit_v1", "waste_disposal_permit_v1/"),
    (
        "packet_real_estate_broker_license_v1",
        "real_estate_broker_license_v1/",
    ),
]

for _name, _prefix in _WAVE_78_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 79 export / import trade compliance cross packet tables (10 generators,
# 2026-05-16). All share the jsic_major industry cohort with descriptive
# adoption_n proxy covering tariff classification match (HS code) / export
# control regulation (経産省 安管令) / origin certification intensity
# (EPA/FTA) / customs violation history / dual-use item disclosure / strategic
# goods signal / EU CBAM exposure / US Iran sanction compliance (OFAC) / WTO
# agreement eligibility (GPA/SCM) / trade remedy petition history (AD/SG/CVD).
# Reuse the shared super-set columns; topic-specific fields land in raw_json.
_WAVE_79_TABLES: list[tuple[str, str]] = [
    (
        "packet_tariff_classification_match_v1",
        "tariff_classification_match_v1/",
    ),
    ("packet_export_control_regulation_v1", "export_control_regulation_v1/"),
    (
        "packet_origin_certification_intensity_v1",
        "origin_certification_intensity_v1/",
    ),
    ("packet_customs_violation_history_v1", "customs_violation_history_v1/"),
    ("packet_dual_use_item_disclosure_v1", "dual_use_item_disclosure_v1/"),
    ("packet_strategic_goods_signal_v1", "strategic_goods_signal_v1/"),
    (
        "packet_eu_carbon_border_adjustment_v1",
        "eu_carbon_border_adjustment_v1/",
    ),
    (
        "packet_us_iran_sanction_compliance_v1",
        "us_iran_sanction_compliance_v1/",
    ),
    ("packet_wto_agreement_eligibility_v1", "wto_agreement_eligibility_v1/"),
    (
        "packet_trade_remedy_petition_history_v1",
        "trade_remedy_petition_history_v1/",
    ),
]

for _name, _prefix in _WAVE_79_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 80 supply chain risk cross packet tables (10 generators, 2026-05-16). All
# share the jsic_major industry cohort with descriptive adoption_n proxy
# covering single-source dependency signal / commodity concentration risk /
# geographic supplier concentration / supplier subsidy inheritance / logistics
# disruption resilience / supplier certification overlap / supplier lifecycle
# risk / payment term volatility / upstream violation proxy / just-in-time
# failure proxy. Reuse the shared super-set columns; topic-specific fields land
# in raw_json.
_WAVE_80_TABLES: list[tuple[str, str]] = [
    (
        "packet_single_source_dependency_signal_v1",
        "single_source_dependency_signal_v1/",
    ),
    (
        "packet_commodity_concentration_risk_v1",
        "commodity_concentration_risk_v1/",
    ),
    (
        "packet_geographic_supplier_concentration_v1",
        "geographic_supplier_concentration_v1/",
    ),
    (
        "packet_supplier_subsidy_inheritance_v1",
        "supplier_subsidy_inheritance_v1/",
    ),
    (
        "packet_logistics_disruption_resilience_v1",
        "logistics_disruption_resilience_v1/",
    ),
    (
        "packet_supplier_certification_overlap_v1",
        "supplier_certification_overlap_v1/",
    ),
    ("packet_supplier_lifecycle_risk_v1", "supplier_lifecycle_risk_v1/"),
    ("packet_payment_term_volatility_v1", "payment_term_volatility_v1/"),
    ("packet_upstream_violation_proxy_v1", "upstream_violation_proxy_v1/"),
    (
        "packet_just_in_time_failure_proxy_v1",
        "just_in_time_failure_proxy_v1/",
    ),
]

for _name, _prefix in _WAVE_80_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 81 ESG materiality cross packet tables (10 generators, 2026-05-16). All
# share the jsic_major industry cohort with descriptive adoption_n proxy covering
# Scope 1+2 disclosure completeness (環境省 / 経産省 GHG 報告) / biodiversity
# disclosure (TNFD / 30by30 OECM) / water stewardship signal (環境省 水質 /
# AWS Alliance for Water Stewardship) / human rights due diligence (UNGPs /
# OECD MNE / 経産省 人権 DD 指針) / community engagement intensity (内閣府
# まち・ひと・しごと創生 / 商工会議所) / circular economy signal (資源有効
# 利用促進法 / 容リ法 / EU ESPR) / product safety recall intensity (消安法 /
# 食品衛生法 / NITE) / animal welfare disclosure (WOAH / 農水省 AW 指針 /
# 3Rs) / modern slavery compliance (UK MSA §54 / US UFLPA / EU FLR / 技能実習)
# / conflict mineral disclosure (3TG + Cobalt / Dodd-Frank §1502 / EU CMR /
# RMI CMRT). Reuse the shared super-set columns; topic-specific fields land in
# raw_json.
_WAVE_81_TABLES: list[tuple[str, str]] = [
    (
        "packet_scope1_2_disclosure_completeness_v1",
        "scope1_2_disclosure_completeness_v1/",
    ),
    ("packet_biodiversity_disclosure_v1", "biodiversity_disclosure_v1/"),
    ("packet_water_stewardship_signal_v1", "water_stewardship_signal_v1/"),
    ("packet_human_rights_due_diligence_v1", "human_rights_due_diligence_v1/"),
    (
        "packet_community_engagement_intensity_v1",
        "community_engagement_intensity_v1/",
    ),
    ("packet_circular_economy_signal_v1", "circular_economy_signal_v1/"),
    (
        "packet_product_safety_recall_intensity_v1",
        "product_safety_recall_intensity_v1/",
    ),
    ("packet_animal_welfare_disclosure_v1", "animal_welfare_disclosure_v1/"),
    ("packet_modern_slavery_compliance_v1", "modern_slavery_compliance_v1/"),
    ("packet_conflict_mineral_disclosure_v1", "conflict_mineral_disclosure_v1/"),
]

for _name, _prefix in _WAVE_81_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 82 IP / innovation cross packet tables (10 generators, 2026-05-16). All
# share the jsic_major industry cohort with descriptive adoption_n proxy
# covering 特許出願 velocity / 商標登録 intensity / R&D 補助金 chain (NEDO /
# JST / AMED / 経産省 GX / ものづくり) / 発明者 overlap network / 特許訴訟
# history / Standard Essential Patent (SEP / FRAND) / Open Innovation signal
# (CVC / OSS) / 産学連携 intensity / IP 収益化 pattern (ライセンス / 担保 /
# 特許プール) / IP ポートフォリオ品質 (維持率 / forward citation / Patent
# Strength Index)。Reuse the shared super-set columns; topic-specific fields
# land in raw_json.
_WAVE_82_TABLES: list[tuple[str, str]] = [
    ("packet_patent_filing_velocity_v1", "patent_filing_velocity_v1/"),
    (
        "packet_trademark_registration_intensity_v1",
        "trademark_registration_intensity_v1/",
    ),
    ("packet_rd_subsidy_chain_v1", "rd_subsidy_chain_v1/"),
    ("packet_inventor_overlap_network_v1", "inventor_overlap_network_v1/"),
    ("packet_patent_litigation_history_v1", "patent_litigation_history_v1/"),
    ("packet_standard_essential_patent_v1", "standard_essential_patent_v1/"),
    ("packet_open_innovation_signal_v1", "open_innovation_signal_v1/"),
    (
        "packet_academic_collaboration_intensity_v1",
        "academic_collaboration_intensity_v1/",
    ),
    ("packet_ip_monetization_pattern_v1", "ip_monetization_pattern_v1/"),
    ("packet_ip_portfolio_quality_v1", "ip_portfolio_quality_v1/"),
]

for _name, _prefix in _WAVE_82_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 83 climate physical risk cross packet tables (10 generators, 2026-05-16).
# All share the jsic_major industry cohort with descriptive adoption_n proxy
# covering 浸水想定区域 exposure (国交省 水管理・国土保全局 / 重ねるハザード
# マップ) / 地震 hazard overlay (NIED J-SHIS + 地震本部) / 台風経路 frequency
# (気象庁 台風 + 気候適応) / 熱ストレス 経済影響 (環境省 WBGT + 厚労省 熱中症
# + JWA) / 渇水 水供給 risk (水資源機構 + 国交省 水管理) / 沿岸 内水 inundation
# signal (港湾局 + 国交省 海岸) / 土砂 災害 (砂防部 + 産総研 地質調査総合) /
# 火山 zone overlay (気象庁 火山 + 内閣府防災) / 津波 zone exposure (気象庁
# 津波 + 内閣府防災) / 林野 火災 risk proxy (林野庁 + 消防庁 + A-PLAT 気候適応)。
# Reuse the shared super-set columns; topic-specific fields land in raw_json.
_WAVE_83_TABLES: list[tuple[str, str]] = [
    ("packet_flood_zone_exposure_v1", "flood_zone_exposure_v1/"),
    ("packet_earthquake_hazard_overlay_v1", "earthquake_hazard_overlay_v1/"),
    ("packet_typhoon_path_frequency_v1", "typhoon_path_frequency_v1/"),
    ("packet_heat_stress_economic_impact_v1", "heat_stress_economic_impact_v1/"),
    ("packet_drought_water_supply_risk_v1", "drought_water_supply_risk_v1/"),
    ("packet_coastal_inundation_signal_v1", "coastal_inundation_signal_v1/"),
    ("packet_landslide_geotechnical_risk_v1", "landslide_geotechnical_risk_v1/"),
    ("packet_volcanic_zone_overlay_v1", "volcanic_zone_overlay_v1/"),
    ("packet_tsunami_zone_exposure_v1", "tsunami_zone_exposure_v1/"),
    ("packet_wildfire_risk_proxy_v1", "wildfire_risk_proxy_v1/"),
]

for _name, _prefix in _WAVE_83_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 84 demographics / population cross packet tables (10 generators,
# 2026-05-16). All share the jsic_major industry cohort with descriptive
# adoption_n proxy covering 人口減少地域 × 事業所立地 / 高齢化進行 proxy
# (65歳以上比率) / 若年労働者集中 (15-34歳 + 新卒採用 intensity) / 人口
# 流入 signal (転入超過 + UIJターン + 関係人口) / 過疎人口密度 (DID 比率
# + 中山間地域) / 性別労働 balance (女性管理職比率 + 育休取得率 + 男女
# 賃金格差) / 外国人居住密度 (在留外国人 + 技能実習 + 特定技能) / 子供
# 人口 overlay (0-14歳 + 出生率 + 保育所整備率) / 世帯所得地理 (中央値
# + ジニ係数 + 相対貧困率 + 生活保護率) / 学歴達成 地理 (大卒比率 +
# STEM 修了率 + リカレント教育)。Reuse the shared super-set columns;
# topic-specific fields land in raw_json.
_WAVE_84_TABLES: list[tuple[str, str]] = [
    ("packet_population_decline_zone_v1", "population_decline_zone_v1/"),
    ("packet_aging_population_proxy_v1", "aging_population_proxy_v1/"),
    (
        "packet_young_worker_concentration_v1",
        "young_worker_concentration_v1/",
    ),
    ("packet_migration_inflow_signal_v1", "migration_inflow_signal_v1/"),
    ("packet_rural_population_density_v1", "rural_population_density_v1/"),
    ("packet_gender_workforce_balance_v1", "gender_workforce_balance_v1/"),
    ("packet_foreign_resident_density_v1", "foreign_resident_density_v1/"),
    ("packet_child_population_overlay_v1", "child_population_overlay_v1/"),
    (
        "packet_household_income_geography_v1",
        "household_income_geography_v1/",
    ),
    ("packet_education_attainment_geo_v1", "education_attainment_geo_v1/"),
]

for _name, _prefix in _WAVE_84_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 85 cybersecurity event cross packet tables (10 generators, 2026-05-16).
# All share the jsic_major industry cohort with descriptive adoption_n proxy
# covering データ漏洩 event log (個情委 報告 / 本人通知 / 行政処分) /
# ランサムウェア incident signal (BCP 復旧 / 身代金支払方針 / JPCERT 連携) /
# サプライチェーン攻撃 vector (vendor compromise / SBOM / signed-build) /
# 内部脅威 proxy (不正持出し / 退職者アクセス / 特権 ID 濫用 / 営業秘密) /
# ゼロデイ脆弱性 signal (patch lag / CVE / EoL / KEV) / フィッシング 標的化
# (BEC / brand impersonation / DMARC・SPF・DKIM) / クラウド設定ミス incident
# (S3 公開 bucket / IAM 過剰権限 / SG 0.0.0.0/0 / KMS / CSPM / ISMAP) /
# 第三者経由 propagation (委託先漏えい / SaaS vendor 侵害 / 監査権) /
# セキュリティ認証 intensity (ISMS / ISO 27001 / SOC 2 / PCI DSS / FISC /
# プライバシーマーク / ISMAP) / インシデント対応 maturity (CSIRT / playbook
# / tabletop 演習 / MTTD・MTTR / フォレンジック)。Reuse the shared super-set
# columns; topic-specific fields land in raw_json.
_WAVE_85_TABLES: list[tuple[str, str]] = [
    ("packet_data_breach_event_log_v1", "data_breach_event_log_v1/"),
    (
        "packet_ransomware_incident_signal_v1",
        "ransomware_incident_signal_v1/",
    ),
    (
        "packet_supply_chain_attack_vector_v1",
        "supply_chain_attack_vector_v1/",
    ),
    ("packet_insider_threat_proxy_v1", "insider_threat_proxy_v1/"),
    ("packet_zero_day_exposure_signal_v1", "zero_day_exposure_signal_v1/"),
    (
        "packet_phishing_campaign_intensity_v1",
        "phishing_campaign_intensity_v1/",
    ),
    ("packet_cloud_misconfig_incident_v1", "cloud_misconfig_incident_v1/"),
    (
        "packet_third_party_breach_propagation_v1",
        "third_party_breach_propagation_v1/",
    ),
    (
        "packet_sec_certification_intensity_v1",
        "sec_certification_intensity_v1/",
    ),
    ("packet_incident_response_maturity_v1", "incident_response_maturity_v1/"),
]

for _name, _prefix in _WAVE_85_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 86 social media / digital presence cross packet tables (10 generators,
# 2026-05-17). All share the jsic_major industry cohort with descriptive
# adoption_n proxy covering 公式 corporate website signal (特商法表記 / プライ
# バシーポリシー / cookie consent / SSL 適合) / SNS account inventory (X /
# LinkedIn / Instagram / verified / ステマ告示遵守) / content publication
# velocity (オウンドメディア / プレスリリース / 業法広告基準) / influencer
# partnership (タイアップ / #PR 表記 / アフィリエイト開示) / digital marketing
# spend proxy (検索広告 / SEO / SNS 広告 / ROAS / Ad fraud / DSP・SSP 透明性)
# / review sentiment (口コミ件数 / やらせ review / 削除申立 / 名誉毀損) /
# employer brand (採用 site / OpenWork / Indeed / 職業安定法) / IR intensity
# (決算説明会 / TCFD / SS・CGコード / フェアディスクロージャー) / press
# release pulse (PR TIMES / 適時開示) / community forum engagement (Slack /
# Discord / Qiita / Zenn / GitHub Discussions / OSS ライセンス遵守)。Reuse
# the shared super-set columns; topic-specific fields land in raw_json.
_WAVE_86_TABLES: list[tuple[str, str]] = [
    ("packet_corporate_website_signal_v1", "corporate_website_signal_v1/"),
    (
        "packet_social_media_account_inventory_v1",
        "social_media_account_inventory_v1/",
    ),
    (
        "packet_content_publication_velocity_v1",
        "content_publication_velocity_v1/",
    ),
    (
        "packet_influencer_partnership_signal_v1",
        "influencer_partnership_signal_v1/",
    ),
    (
        "packet_digital_marketing_spend_proxy_v1",
        "digital_marketing_spend_proxy_v1/",
    ),
    ("packet_review_sentiment_aggregate_v1", "review_sentiment_aggregate_v1/"),
    ("packet_employer_brand_signal_v1", "employer_brand_signal_v1/"),
    (
        "packet_investor_relations_intensity_v1",
        "investor_relations_intensity_v1/",
    ),
    ("packet_press_release_pulse_v1", "press_release_pulse_v1/"),
    ("packet_community_forum_engagement_v1", "community_forum_engagement_v1/"),
]

for _name, _prefix in _WAVE_86_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


# Wave 88 corporate activism / political donation cross packet tables (10
# generators, 2026-05-17). All share the jsic_major industry cohort with
# descriptive adoption_n proxy covering 政治献金 record (政治資金規正法 報告
# 書 / 政党支部 / 政治団体 寄附 / 内部統制) / ロビー活動 intensity (議員陳情 /
# 業界団体 通じた要望 / パブコメ参加 / 議連活動) / 業界団体 加入 (経団連 /
# 日商 / 同友会 / 業界別団体 / 協同組合) / 独禁法 settlement history (排除措
# 置命令 / 課徴金納付命令 / 確約計画 / リニエンシー / 私訴和解) / 企業政治活
# 動 signal (政策提言 / 意見広告 / 役員 公職就任 / OB 政策秘書 / 議連 個社派
# 遣) / 政府委員会 seat (各府省 審議会 / 検討会 / 研究会 業界代表 / 学識委員)
# / 公共政策 advocacy (パブコメ提出 / ホワイトペーパー / 政策提言レポート /
# 自主規制 ガイドライン提案) / 規制関与 intensity (規制官庁 ヒアリング / 当局
# 会合 / 規制サンドボックス / 事前協議 / RIA 参画) / Think tank 提携 (シンク
# タンク 共同研究 / 寄附講座 / 産学連携 政策研究 / 政策提言シンクタンク 会員)
# / Media relations pattern (記者会見 頻度 / プレスリリース量 / 業界メディア
# 寄稿 / IR 取材対応 / 危機管理広報)。Reuse the shared super-set columns;
# topic-specific fields land in raw_json.
_WAVE_88_TABLES: list[tuple[str, str]] = [
    ("packet_political_donation_record_v1", "political_donation_record_v1/"),
    ("packet_lobby_activity_intensity_v1", "lobby_activity_intensity_v1/"),
    (
        "packet_trade_association_membership_v1",
        "trade_association_membership_v1/",
    ),
    (
        "packet_anti_trust_settlement_history_v1",
        "anti_trust_settlement_history_v1/",
    ),
    (
        "packet_corporate_political_activity_signal_v1",
        "corporate_political_activity_signal_v1/",
    ),
    ("packet_government_committee_seat_v1", "government_committee_seat_v1/"),
    ("packet_public_policy_advocacy_v1", "public_policy_advocacy_v1/"),
    (
        "packet_regulatory_engagement_intensity_v1",
        "regulatory_engagement_intensity_v1/",
    ),
    ("packet_think_tank_partnership_v1", "think_tank_partnership_v1/"),
    ("packet_media_relations_pattern_v1", "media_relations_pattern_v1/"),
]

for _name, _prefix in _WAVE_88_TABLES:
    PACKET_TABLES.append((_name, _prefix, _WAVE_56_58_COLUMNS))


def render_ddl(table: str, prefix: str, columns: list[tuple[str, str]]) -> str:
    """Render a single ``CREATE EXTERNAL TABLE IF NOT EXISTS`` for a packet table."""
    col_block = ",\n  ".join(f"{name} {sql_type}" for name, sql_type in columns)
    location = f"s3://{BUCKET}/{prefix}"
    return f"""CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.{table} (
  {col_block}
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
  'ignore.malformed.json' = 'true',
  'case.insensitive' = 'false'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION '{location}'
TBLPROPERTIES (
  'classification' = 'json',
  'project' = 'jpcite',
  'credit_run' = '2026-05',
  'auto_stop' = '2026-05-29',
  'contract' = 'jpcir.packet.v1'
)"""


def run_athena_ddl(athena: Any, ddl: str) -> str:
    """Submit a DDL via Athena and block until SUCCEEDED / FAILED."""
    resp = athena.start_query_execution(
        QueryString=ddl,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": RESULT_S3},
    )
    qid: str = resp["QueryExecutionId"]
    for _ in range(60):
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = status["State"]
        if state == "SUCCEEDED":
            return qid
        if state in {"FAILED", "CANCELLED"}:
            reason = status.get("StateChangeReason", "")
            raise RuntimeError(f"DDL FAILED ({qid}): {reason}\nSQL=\n{ddl[:400]}")
        time.sleep(1)
    raise RuntimeError(f"DDL timeout ({qid})")


def main() -> None:
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    athena = session.client("athena")
    glue = session.client("glue")

    summary: list[dict[str, Any]] = []
    for table, prefix, cols in PACKET_TABLES:
        ddl = render_ddl(table, prefix, cols)
        try:
            qid = run_athena_ddl(athena, ddl)
            # Sanity: confirm in Glue catalog.
            glue.get_table(DatabaseName=DATABASE, Name=table)
            summary.append({"table": table, "prefix": prefix, "exec_id": qid, "state": "OK"})
            print(f"[ok] {table:48s}  {prefix:42s}  exec={qid}", flush=True)
        except Exception as e:  # noqa: BLE001
            summary.append(
                {"table": table, "prefix": prefix, "state": "FAIL", "error": str(e)[:200]}
            )
            print(f"[fail] {table:48s}  {prefix:42s}  err={str(e)[:160]}", flush=True)

    out_path = "out/glue_packet_table_register.json"
    os.makedirs("out", exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump({"database": DATABASE, "tables": summary}, fh, indent=2)
    print(
        f"[summary] wrote {out_path}  total={len(summary)}  ok={sum(1 for s in summary if s['state'] == 'OK')}"
    )


if __name__ == "__main__":
    main()
    sys.exit(0)
