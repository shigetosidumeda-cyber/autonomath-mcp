# Outcome → Packet → Athena Crosswalk

**Schema version**: `jpcite.outcome_packet_athena_crosswalk.v1`  
**Generated**: `2026-05-16T20:30:00+09:00`  
**Machine-readable artifact**: `site/.well-known/jpcite-outcome-packet-crosswalk.json`

This document maps every purchasable outcome to its backing packet, S3 path, Glue table,
and Athena query template. AI agents use this artifact to resolve _"what am I buying and
where does it live"_ before issuing a `/v1/cost/preview` or paid call.

## Summary

- **Total outcomes**: 152
- **WIRED** (packet generator + Glue table both registered): **69**
- **PENDING** (gap — see classification below): **63**

### Gap classification

- **10 outcomes**: packet generator exists (Wave 53-58 landings) but Glue Data Catalog has not been crawled against the new prefixes yet (was 40 — Wave 56-58 30 tables flipped to WIRED on 2026-05-16 after Athena `COUNT(*)` smoke verified all 30 tables have rows present). Flip remaining 10 to WIRED after `aws glue start-crawler --name jpcite_credit_derived_crawler` completes.
- **13 outcomes**: control or meta surfaces (e.g. `agent_routing_decision`, `cost_preview`, `source_receipt_ledger`, `evidence_answer`) that intentionally do not have a packet-table backing — they are routed through `/v1/*` endpoints with on-the-fly composition.

### Live Glue catalog reconciliation (`aws glue get-tables --database-name jpcite_credit_2026_05 --region ap-northeast-1 --profile bookyou-recovery`, 2026-05-16)

Live Glue has 70+ tables: 69 `packet_*` (matches WIRED count above 1:1) + 4 auxiliary (`claim_refs`, `known_gaps`, `object_manifest`, `source_receipts`). The auxiliary tables back receipt-verifiable envelopes (`source_receipts` join) and gap reporting (`known_gaps`) — they are not outcome-bound. See `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json` for the upstream source-family map.

## AWS Constants

- **S3 derived bucket**: `jpcite-credit-993693061769-202605-derived`
- **Glue database**: `jpcite_credit_2026_05`
- **Glue region**: `ap-northeast-1`
- **Athena workgroup**: `jpcite-credit-canary`

## Crosswalk table

| # | Outcome ID | Display | Status | Cost band | ¥ | Generator | Glue table | Est rows |
|---|---|---|---|---|---|---|---|---|
| 1 | `agent_routing_decision` | Agent routing decision | **PENDING** | free | ¥0 | `—` | `—` | — |
| 2 | `cost_preview` | Cost preview before purchase | **PENDING** | free | ¥0 | `—` | `—` | — |
| 3 | `company_public_baseline` | Company public baseline | **WIRED** | light | ¥300 | `generate_company_public_baseline_packets.py` | `packet_company_public_baseline_v1` | — |
| 4 | `invoice_registrant_public_check` | Invoice registrant public check | **WIRED** | light | ¥300 | `generate_invoice_registrant_public_check_packets.py` | `packet_invoice_registrant_public_check_v1` | — |
| 5 | `application_strategy` | Subsidy and grant candidate pack | **WIRED** | heavy | ¥900 | `generate_application_strategy_packets.py` | `packet_application_strategy_v1` | — |
| 6 | `regulation_change_watch` | Law and regulation change watch | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 7 | `local_government_permit_obligation_map` | Local government permit and obligation map | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 8 | `court_enforcement_citation_pack` | Court and enforcement citation pack | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 9 | `public_statistics_market_context` | Public statistics market context | **PENDING** | light | ¥300 | `—` | `—` | — |
| 10 | `client_monthly_review` | Client monthly public watchlist | **PENDING** | heavy | ¥900 | `—` | `—` | — |
| 11 | `csv_overlay_public_check` | Accounting CSV public counterparty check | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 12 | `cashbook_csv_subsidy_fit_screen` | Cashbook CSV subsidy fit screen | **PENDING** | heavy | ¥900 | `—` | `—` | — |
| 13 | `source_receipt_ledger` | Source receipt ledger | **PENDING** | light | ¥300 | `—` | `—` | — |
| 14 | `evidence_answer` | Evidence answer citation pack | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 15 | `foreign_investor_japan_public_entry_brief` | Foreign investor Japan public entry brief | **PENDING** | heavy | ¥900 | `—` | `—` | — |
| 16 | `healthcare_regulatory_public_check` | Healthcare regulatory public check | **PENDING** | mid | ¥600 | `—` | `—` | — |
| 17 | `houjin_360_full_packet` | Houjin 360 full packet | **WIRED** | heavy | ¥900 | `generate_houjin_360_packets.py` | `packet_houjin_360` | 166,969 |
| 18 | `program_lineage_packet` | Program lineage packet | **WIRED** | mid | ¥600 | `generate_program_lineage_packets.py` | `packet_program_lineage` | 11,601 |
| 19 | `acceptance_probability_cohort_packet` | Acceptance probability cohort packet | **WIRED** | heavy | ¥900 | `generate_acceptance_probability_packets.py` | `packet_acceptance_probability` | 225,000 |
| 20 | `enforcement_industry_heatmap_packet` | Enforcement industry heatmap packet | **WIRED** | mid | ¥600 | `generate_regional_enforcement_density_packets.py` | `packet_enforcement_industry_heatmap_v1` | — |
| 21 | `invoice_houjin_cross_check_packet` | Invoice and houjin cross-check packet | **WIRED** | light | ¥300 | `—` | `packet_invoice_houjin_cross_check_v1` | — |
| 22 | `program_law_amendment_impact_packet` | Program and law amendment impact packet | **WIRED** | heavy | ¥900 | `generate_program_law_amendment_impact_packets.py` | `packet_program_law_amendment_impact_v1` | — |
| 23 | `cohort_program_recommendation_packet` | Cohort program recommendation packet | **WIRED** | heavy | ¥900 | `generate_cohort_program_recommendation_packets.py` | `packet_cohort_program_recommendation_v1` | — |
| 24 | `vendor_due_diligence_packet` | Vendor due diligence packet | **WIRED** | heavy | ¥900 | `—` | `packet_vendor_due_diligence_v1` | — |
| 25 | `succession_program_matching_packet` | Succession program matching packet | **WIRED** | mid | ¥600 | `generate_succession_program_matching_packets.py` | `packet_succession_program_matching_v1` | — |
| 26 | `regulatory_change_radar_packet` | Regulatory change radar packet | **WIRED** | mid | ¥600 | `—` | `packet_regulatory_change_radar_v1` | — |
| 27 | `tax_treaty_japan_inbound_packet` | Tax treaty Japan inbound packet | **WIRED** | mid | ¥600 | `generate_tax_treaty_japan_inbound_packets.py` | `packet_tax_treaty_japan_inbound_v1` | — |
| 28 | `subsidy_application_timeline_packet` | Subsidy application timeline packet | **WIRED** | light | ¥300 | `—` | `packet_subsidy_application_timeline_v1` | — |
| 29 | `bid_opportunity_matching_packet` | Bid opportunity matching packet | **WIRED** | mid | ¥600 | `generate_bid_opportunity_matching_packets.py` | `packet_bid_opportunity_matching_v1` | — |
| 30 | `permit_renewal_calendar_packet` | Permit renewal calendar packet | **WIRED** | light | ¥300 | `generate_permit_renewal_calendar_packets.py` | `packet_permit_renewal_calendar_v1` | — |
| 31 | `local_government_subsidy_aggregator_packet` | Local government subsidy aggregator packet | **WIRED** | mid | ¥600 | `generate_local_government_subsidy_aggregator_packets.py` | `packet_local_government_subsidy_aggregator_v1` | — |
| 32 | `kanpou_gazette_watch_packet` | Kanpou gazette watch packet | **WIRED** | light | ¥300 | `generate_kanpou_gazette_watch_packets.py` | `packet_kanpou_gazette_watch_v1` | — |
| 33 | `patent_corp_360_packet` | Patent corp 360 packet | **WIRED** | light | ¥300 | `generate_patent_corp_360_packets.py` | `packet_patent_corp_360_v1` | — |
| 34 | `environmental_compliance_radar_packet` | Environmental compliance radar packet | **WIRED** | mid | ¥600 | `generate_environmental_compliance_radar_packets.py` | `packet_environmental_compliance_radar_v1` | — |
| 35 | `statistical_cohort_proxy_packet` | Statistical cohort proxy packet | **WIRED** | light | ¥300 | `generate_statistical_cohort_proxy_packets.py` | `packet_statistical_cohort_proxy_v1` | — |
| 36 | `diet_question_program_link_packet` | Diet question program lineage packet | **WIRED** | mid | ¥600 | `generate_diet_question_program_link_packets.py` | `packet_diet_question_program_link_v1` | — |
| 37 | `edinet_finance_program_match_packet` | EDINET finance program match packet | **WIRED** | mid | ¥600 | `generate_edinet_finance_program_match_packets.py` | `packet_edinet_finance_program_match_v1` | — |
| 38 | `trademark_brand_protection_packet` | Trademark brand protection 360 packet | **WIRED** | light | ¥300 | `generate_trademark_brand_protection_packets.py` | `packet_trademark_brand_protection_v1` | — |
| 39 | `statistics_market_size_packet` | Statistics market size packet | **WIRED** | light | ¥300 | `generate_statistics_market_size_packets.py` | `packet_statistics_market_size_v1` | — |
| 40 | `cross_administrative_timeline_packet` | Cross administrative timeline packet | **WIRED** | mid | ¥600 | `generate_cross_administrative_timeline_packets.py` | `packet_cross_administrative_timeline_v1` | — |
| 41 | `public_procurement_trend_packet` | Public procurement trend packet | **WIRED** | mid | ¥600 | `generate_public_procurement_trend_packets.py` | `packet_public_procurement_trend_v1` | — |
| 42 | `regulation_impact_simulator_packet` | Regulation impact simulator packet | **WIRED** | mid | ¥600 | `generate_regulation_impact_simulator_packets.py` | `packet_regulation_impact_simulator_v1` | — |
| 43 | `patent_environmental_link_packet` | Patent × environmental link packet | **WIRED** | mid | ¥600 | `generate_patent_environmental_link_packets.py` | `packet_patent_environmental_link_v1` | — |
| 44 | `diet_question_amendment_correlate_packet` | Diet question × amendment correlate packet | **WIRED** | mid | ¥600 | `generate_diet_question_amendment_correlate_packets.py` | `packet_diet_question_amendment_correlate_v1` | — |
| 45 | `edinet_program_subsidy_compounding_packet` | EDINET × program subsidy compounding packet | **WIRED** | heavy | ¥900 | `generate_edinet_program_subsidy_compounding_packets.py` | `packet_edinet_program_subsidy_compounding_v1` | — |
| 46 | `kanpou_program_event_link_packet` | 官報 × program event link packet | **WIRED** | light | ¥300 | `generate_kanpou_program_event_link_packets.py` | `packet_kanpou_program_event_link_v1` | — |
| 47 | `kfs_saiketsu_industry_radar_packet` | 国税不服審判所 × 業種 radar packet | **WIRED** | mid | ¥600 | `generate_kfs_saiketsu_industry_radar_packets.py` | `packet_kfs_saiketsu_industry_radar_v1` | — |
| 48 | `municipal_budget_match_packet` | 47都道府県 × 補助金 budget match packet | **WIRED** | mid | ¥600 | `generate_municipal_budget_match_packets.py` | `packet_municipal_budget_match_v1` | — |
| 49 | `trademark_industry_density_packet` | 商標 × 業種 density packet | **WIRED** | light | ¥300 | `generate_trademark_industry_density_packets.py` | `packet_trademark_industry_density_v1` | — |
| 50 | `environmental_disposal_radar_packet` | 廃棄物処理 × 行政処分 radar packet | **WIRED** | mid | ¥600 | `generate_environmental_disposal_radar_packets.py` | `packet_environmental_disposal_radar_v1` | — |
| 51 | `regulatory_change_industry_impact_packet` | 法令改正 × 業種影響 packet | **WIRED** | mid | ¥600 | `generate_regulatory_change_industry_impact_packets.py` | `packet_regulatory_change_industry_impact_v1` | — |
| 52 | `gbiz_invoice_dispatch_match_packet` | gBizINFO × インボイス × 取引パターン packet | **WIRED** | mid | ¥600 | `generate_gbiz_invoice_dispatch_match_packets.py` | `packet_gbiz_invoice_dispatch_match_v1` | — |
| 53 | `gov_spending_efficiency_packet` | 政府支出 効率 (補助金 × EDINET × 業種) packet | **PENDING** | mid | ¥600 | `generate_gov_spending_efficiency_packets.py` | `—` | — |
| 54 | `regulatory_cluster_radar_packet` | 規制クラスタ レーダー (処分 × 改正 × 業種) packet | **PENDING** | mid | ¥600 | `generate_regulatory_cluster_radar_packets.py` | `—` | — |
| 55 | `succession_match_3axis_packet` | 事業承継 3軸マッチ (候補 × 類似度 × 地域) packet | **PENDING** | heavy | ¥900 | `generate_succession_match_3axis_packets.py` | `—` | — |
| 56 | `inbound_tax_treaty_compliance_packet` | 外資 税務条約 コンプライアンス (法人 × 条約 × インボイス) packet | **PENDING** | heavy | ¥900 | `generate_inbound_tax_treaty_compliance_packets.py` | `—` | — |
| 57 | `patent_subsidy_correlation_packet` | 特許 × 補助金 相関 (J14 × J05 × 業種) packet | **PENDING** | mid | ¥600 | `generate_patent_subsidy_correlation_packets.py` | `—` | — |
| 58 | `municipal_tax_subsidy_cohort_packet` | 地方税 × 自治体補助金 × 産業 cohort packet | **PENDING** | mid | ¥600 | `generate_municipal_tax_subsidy_cohort_packets.py` | `—` | — |
| 59 | `regulatory_amendment_industry_radar_packet` | 法令改正 × 業種影響 (snapshot cliffs) radar packet | **PENDING** | mid | ¥600 | `generate_regulatory_amendment_industry_radar_packets.py` | `—` | — |
| 60 | `bid_subsidy_substitution_packet` | 入札 × 補助金 代替性 (発注機関 × 制度) packet | **PENDING** | mid | ¥600 | `generate_bid_subsidy_substitution_packets.py` | `—` | — |
| 61 | `administrative_disposition_recovery_packet` | 行政処分 後 復活率 (採択履歴 × 処分庁) packet | **PENDING** | mid | ¥600 | `generate_administrative_disposition_recovery_packets.py` | `—` | — |
| 62 | `environmental_certification_match_packet` | 環境認証 × 補助金 × 制度 マッチ packet | **PENDING** | mid | ¥600 | `generate_environmental_certification_match_packets.py` | `—` | — |
| 63 | `program_amendment_timeline_v2_packet` | 制度改正履歴 + 影響期間 v2 packet | **WIRED** | mid | ¥600 | `generate_program_amendment_timeline_v2_packets.py` | `packet_program_amendment_timeline_v2` | 5000 |
| 64 | `enforcement_seasonal_trend_packet` | 行政処分 月別季節性 packet | **WIRED** | mid | ¥600 | `generate_enforcement_seasonal_trend_packets.py` | `packet_enforcement_seasonal_trend_v1` | 47 |
| 65 | `adoption_fiscal_cycle_packet` | 採択事例 fiscal year cycle packet | **WIRED** | mid | ¥600 | `generate_adoption_fiscal_cycle_packets.py` | `packet_adoption_fiscal_cycle_v1` | 17 |
| 66 | `tax_ruleset_phase_change_packet` | 税制 段階変更 timeline packet | **WIRED** | mid | ¥600 | `generate_tax_ruleset_phase_change_packets.py` | `packet_tax_ruleset_phase_change_v1` | 3 |
| 67 | `invoice_registration_velocity_packet` | インボイス登録 速度トレンド packet | **WIRED** | mid | ¥600 | `generate_invoice_registration_velocity_packets.py` | `packet_invoice_registration_velocity_v1` | 47 |
| 68 | `regulatory_q_over_q_diff_packet` | 法令改正 Q-over-Q 差分 packet | **WIRED** | mid | ¥600 | `generate_regulatory_q_over_q_diff_packets.py` | `packet_regulatory_q_over_q_diff_v1` | 1 |
| 69 | `subsidy_application_window_predict_packet` | 申請期間 forecast packet | **WIRED** | mid | ¥600 | `generate_subsidy_application_window_predict_packets.py` | `packet_subsidy_application_window_predict_v1` | 928 |
| 70 | `bid_announcement_seasonality_packet` | 入札公告 季節性 packet | **WIRED** | mid | ¥600 | `generate_bid_announcement_seasonality_packets.py` | `packet_bid_announcement_seasonality_v1` | 1 |
| 71 | `succession_event_pulse_packet` | 事業承継 events pulse packet | **WIRED** | mid | ¥600 | `generate_succession_event_pulse_packets.py` | `packet_succession_event_pulse_v1` | 55 |
| 72 | `kanpou_event_burst_packet` | 官報 event burst detector packet | **WIRED** | mid | ¥600 | `generate_kanpou_event_burst_packets.py` | `packet_kanpou_event_burst_v1` | 1 |
| 73 | `prefecture_program_heatmap_packet` | 47都道府県 × 制度 密度 heatmap packet | **WIRED** | mid | ¥600 | `generate_prefecture_program_heatmap_packets.py` | `packet_prefecture_program_heatmap_v1` | 48 |
| 74 | `municipality_subsidy_inventory_packet` | 政令市 補助金 inventory packet | **WIRED** | mid | ¥600 | `generate_municipality_subsidy_inventory_packets.py` | `packet_municipality_subsidy_inventory_v1` | 47 |
| 75 | `region_industry_match_packet` | 地域 × 業種 適合 matcher packet | **WIRED** | mid | ¥600 | `generate_region_industry_match_packets.py` | `packet_region_industry_match_v1` | 50 |
| 76 | `cross_prefecture_arbitrage_packet` | 都道府県間 制度 arbitrage packet | **WIRED** | mid | ¥600 | `generate_cross_prefecture_arbitrage_packets.py` | `packet_cross_prefecture_arbitrage_v1` | 17 |
| 77 | `city_size_subsidy_propensity_packet` | 自治体規模 × 補助金率 packet | **WIRED** | mid | ¥600 | `generate_city_size_subsidy_propensity_packets.py` | `packet_city_size_subsidy_propensity_v1` | 51 |
| 78 | `regional_enforcement_density_packet` | 地域別 行政処分 密度 packet | **WIRED** | mid | ¥600 | `generate_regional_enforcement_density_packets.py` | `packet_regional_enforcement_density_v1` | 47 |
| 79 | `prefecture_court_decision_focus_packet` | 都道府県別 判例 focus packet | **WIRED** | mid | ¥600 | `generate_prefecture_court_decision_focus_packets.py` | `packet_prefecture_court_decision_focus_v1` | 5 |
| 80 | `city_jct_density_packet` | 市区町村 適格事業者密度 packet | **WIRED** | mid | ¥600 | `generate_city_jct_density_packets.py` | `packet_city_jct_density_v1` | 47 |
| 81 | `rural_subsidy_coverage_packet` | 過疎地域補助金 coverage packet | **WIRED** | mid | ¥600 | `generate_rural_subsidy_coverage_packets.py` | `packet_rural_subsidy_coverage_v1` | 47 |
| 82 | `prefecture_environmental_compliance_packet` | 都道府県 環境compliance score packet | **WIRED** | mid | ¥600 | `generate_prefecture_environmental_compliance_packets.py` | `packet_prefecture_environmental_compliance_v1` | 45 |
| 83 | `houjin_parent_subsidiary_packet` | 法人 親子関係 cross-ref packet | **WIRED** | mid | ¥600 | `generate_houjin_parent_subsidiary_packets.py` | `packet_houjin_parent_subsidiary_v1` | 2918 |
| 84 | `business_partner_360_packet` | 取引先 360 (双方向 due diligence) packet | **WIRED** | mid | ¥600 | `generate_business_partner_360_packets.py` | `packet_business_partner_360_v1` | 1 |
| 85 | `board_member_overlap_packet` | 役員 兼任 network packet | **WIRED** | mid | ¥600 | `generate_board_member_overlap_packets.py` | `packet_board_member_overlap_v1` | 49 |
| 86 | `founding_succession_chain_packet` | 設立 → 後継 chain packet | **WIRED** | mid | ¥600 | `generate_founding_succession_chain_packets.py` | `packet_founding_succession_chain_v1` | 1005 |
| 87 | `certification_houjin_link_packet` | 認証 × 法人 (ISO/JIS/GMP) packet | **WIRED** | mid | ¥600 | `generate_certification_houjin_link_packets.py` | `packet_certification_houjin_link_v1` | 3 |
| 88 | `license_houjin_jurisdiction_packet` | 許認可 × 法人 × 管轄 packet | **WIRED** | mid | ¥600 | `generate_license_houjin_jurisdiction_packets.py` | `packet_license_houjin_jurisdiction_v1` | 5 |
| 89 | `employment_program_eligibility_packet` | 雇用 × 制度適格 packet | **WIRED** | mid | ¥600 | `generate_employment_program_eligibility_packets.py` | `packet_employment_program_eligibility_v1` | 47 |
| 90 | `vendor_payment_history_match_packet` | 取引先 支払履歴 match (公開部分) packet | **WIRED** | mid | ¥600 | `generate_vendor_payment_history_match_packets.py` | `packet_vendor_payment_history_match_v1` | 1 |
| 91 | `industry_association_link_packet` | 業界団体 × 法人 link packet | **WIRED** | mid | ¥600 | `generate_industry_association_link_packets.py` | `packet_industry_association_link_v1` | 50 |
| 92 | `public_listed_program_link_packet` | 上場法人 × 公開制度 link packet | **WIRED** | mid | ¥600 | `generate_public_listed_program_link_packets.py` | `packet_public_listed_program_link_v1` | 191 |

## Athena query templates

Every WIRED entry has a parameterized Athena query template under the
`athena_query_template` field in the JSON artifact. The canonical form is:

```sql
SELECT * FROM "jpcite_credit_2026_05"."<glue_table>"
WHERE subject_id_hint = ?
LIMIT 100;
```

Cross-table joins always go through `source_receipts` (Glue table) so claims remain receipt-verifiable.
Example for a receipt-anchored query:

```sql
SELECT p.*, sr.source_url, sr.fetched_at
FROM "jpcite_credit_2026_05"."packet_houjin_360" p
JOIN "jpcite_credit_2026_05"."source_receipts" sr
  ON p.source_receipt_id = sr.receipt_id
WHERE p.subject_id_hint = ?
LIMIT 100;
```

## Agent discovery pattern

AI agents should fetch the JSON artifact (`site/.well-known/jpcite-outcome-packet-crosswalk.json`) and:

1. Resolve a user-intent string to an `outcome_id` via the public catalog (`/.well-known/jpcite-outcome-catalog.json`).
2. Look up the matching crosswalk entry in this artifact.
3. If `status == WIRED`: issue a `/v1/cost/preview` against `preview_endpoint`, then either
   (a) call the outcome's billable endpoint, or
   (b) query Athena directly via the `athena_query_template` if the caller has direct AWS access.
4. If `status == PENDING`: do **not** assume the table exists. Either choose a WIRED alternative or wait for the next Glue crawler pass.

## Source documents

- **outcome_catalog**: `site/.well-known/jpcite-outcome-catalog.json`
- **outcome_contract_catalog**: `site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json`
- **outcome_source_crosswalk**: `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json`
- **packet_generators_dir**: `scripts/aws_credit_ops/`
- **glue_database**: `jpcite_credit_2026_05`
- **glue_region**: `ap-northeast-1`

## Honesty notes

- Counts are **architecture-snapshot**, not runtime probe. Re-run `scripts/check_distribution_manifest_drift.py` after Glue crawler refresh to reconcile.
- `estimated_rows` is **honest unknown** (`—`) for the 41 packet-generator-exists-but-Glue-pending outcomes — those numbers fill in after the next ETL crawler pass.
- `agent_routing_decision` and `cost_preview` are **deliberately** non-billable, no-packet control surfaces; do not mark them as PENDING bugs.

_Last updated: 2026-05-16T20:30:00+09:00_