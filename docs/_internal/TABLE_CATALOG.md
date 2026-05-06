# JPCite SQLite Table Catalog

- Snapshot: 2026-05-05 17:06:45 JST
- Generated: 2026-05-05 17:22:10
- DBs: `data/jpintel.db` (~423 MB) + `autonomath.db` (~11.0 GB at repo root)
- Sources: `sqlite_master`, `scripts/migrations/*.sql`, `src/jpintel_mcp/{mcp,api}/**.py`
- Counts column legend: `<rows>` for tables, `**[empty]**` for 0 rows, `(virtual; ~N rowids)` for vec0 virtuals (count via `_rowids` shadow table).
- `MCP/API` column = number of `.py` files in `src/jpintel_mcp/mcp/` and `src/jpintel_mcp/api/` containing `FROM/JOIN/INTO/UPDATE <table>`.

## Totals

- jpintel.db: 181 tables + 2 views, total rows ≈ **580,441**
- autonomath.db: 450 tables + 13 views, total rows ≈ **15,523,258** (excl. vec0)

---

## 1. `data/jpintel.db` (jpintel-mcp public-facing slim DB)

### 1.1. Wave 0-1 (foundation) — 32 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `adoption_records` | 199,944 | id, houjin_bangou, program_id_hint, program_name_raw, company_name_raw (+14) | 014_business_intelligence_layer.sql | 0/0 |
| `advisor_referrals` | **[empty]** | id, referral_token, advisor_id, source_query_hash, source_program_id (+9) | 024_advisors.sql | 0/1 |
| `advisors` | **[empty]** | id, houjin_bangou, firm_name, firm_name_kana, firm_type (+21) | 024_advisors.sql | 0/1 |
| `anon_rate_limit` | 140 | ip_hash, date, call_count, first_seen, last_seen | 007_anon_rate_limit.sql | 0/3 |
| `bids` | 362 | unified_id, bid_title, bid_kind, procuring_entity, procuring_houjin_bangou (+23) | 017_bids.sql | 1/2 |
| `case_law` | 495 | id, case_name, court, decision_date, case_number (+10) | 012_case_law.sql | 0/0 |
| `case_studies` | 2,286 | case_id, company_name, houjin_bangou, is_sole_proprietor, prefecture (+19) | 011_external_data_tables.sql | 2/1 |
| `compliance_notification_log` | **[empty]** | id, subscriber_id, sent_at, subject, changes_json (+2) | 020_compliance_subscribers.sql | 0/0 |
| `compliance_subscribers` | **[empty]** | id, email, houjin_bangou, industry_codes_json, areas_of_interest_json (+14) | 020_compliance_subscribers.sql | 0/2 |
| `court_decisions` | 2,065 | unified_id, case_name, case_number, court, court_level (+18) | 016_court_decisions.sql | 2/3 |
| `device_codes` | 4 | device_code, user_code, status, client_fingerprint, scope (+12) | 023_device_codes.sql | 0/2 |
| `email_schedule` | **[empty]** | id, api_key_id, email, kind, send_at (+5) | 008_email_schedule.sql | 0/1 |
| `enforcement_cases` | 1,185 | case_id, event_type, program_name_hint, recipient_name, recipient_kind (+23) | 011_external_data_tables.sql | 1/2 |
| `enforcement_decision_refs` | **[empty]** | enforcement_case_id, decision_unified_id, ref_kind, source_url, fetched_at | 016_court_decisions.sql | 1/0 |
| `feedback` | 11 | id, key_hash, customer_id, tier, message (+5) | 003_feedback.sql | 0/1 |
| `houjin_master` | 166,765 | houjin_bangou, normalized_name, alternative_names_json, address_normalized, prefecture (+15) | 014_business_intelligence_layer.sql | 0/0 |
| `industry_program_density` | **[empty]** | id, jsic_code_medium, prefecture, program_id, peer_count (+7) | 014_business_intelligence_layer.sql | 0/0 |
| `industry_stats` | **[empty]** | id, statistic_source, statistic_year, jsic_code_large, jsic_name_large (+16) | 014_business_intelligence_layer.sql | 0/0 |
| `invoice_registrants` | 13,801 | invoice_registration_number, houjin_bangou, normalized_name, address_normalized, prefecture (+11) | 019_invoice_registrants.sql | 1/3 |
| `laws` | 9,484 | unified_id, law_number, law_title, law_short_title, law_type (+17) | 015_laws.sql | 1/4 |
| `line_users` | **[empty]** | line_user_id, display_name, picture_url, language, added_at (+9) | 021_line_users.sql | 0/1 |
| `loan_programs` | 108 | id, program_name, provider, loan_type, amount_max_yen (+17) | 011_external_data_tables.sql | 1/1 |
| `ministry_faq` | **[empty]** | id, program_name_hint, ministry, category, question (+5) | 014_business_intelligence_layer.sql | 0/0 |
| `new_program_candidates` | 102 | id, candidate_name, mentioned_in, ministry, budget_yen (+7) | 011_external_data_tables.sql | 0/0 |
| `program_documents` | 132 | id, program_name, form_name, form_type, form_format (+9) | 011_external_data_tables.sql | 0/0 |
| `program_law_refs` | 1,059 | program_unified_id, law_unified_id, ref_kind, article_citation, source_url (+2) | 015_laws.sql | 1/2 |
| `source_lineage_audit` | 13,829 | id, table_name, row_key, source_url, source_domain (+5) | 014_business_intelligence_layer.sql | 0/0 |
| `subscribers` | 14 | id, email, source, created_at, unsubscribed_at | 002_subscribers.sql | 0/3 |
| `support_org` | **[empty]** | org_id, org_type, org_name, houjin_bangou, prefecture (+10) | 014_business_intelligence_layer.sql | 0/0 |
| `tax_rulesets` | 50 | unified_id, ruleset_name, tax_category, ruleset_kind, effective_from (+17) | 018_tax_rulesets.sql | 1/2 |
| `verticals_deep` | **[empty]** | id, vertical_code, vertical_label, wave_number, record_type (+11) | 014_business_intelligence_layer.sql | 0/0 |
| `widget_keys` | **[empty]** | key_id, owner_email, label, allowed_origins_json, stripe_customer_id (+11) | 022_widget_keys.sql | 0/1 |

### 1.2. Wave 2-5 (BI/health/RE) — 40 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `alert_subscriptions` | 1 | id, api_key_hash, filter_type, filter_value, min_severity (+6) | 038_alert_subscriptions.sql | 0/2 |
| `care_subsidies` | **[empty]** | canonical_id, program_name, authority, authority_level, prefecture (+11) | 039_healthcare_schema.sql | 1/0 |
| `jpi_pc_program_health` | **[empty]** | program_id, quality_score, warning_count_recent, critical_count_recent, last_validated_at (+1) | 048_pc_program_health.sql | 1/0 |
| `l4_query_cache` | 61 | cache_key, tool_name, params_json, result_json, hit_count (+3) | 043_l4_cache.sql | 0/0 |
| `medical_institutions` | **[empty]** | canonical_id, institution_type, name, name_kana, prefecture (+12) | 039_healthcare_schema.sql | 1/0 |
| `pc_acceptance_rate_by_authority` | **[empty]** | authority_id, fiscal_year, applied_count, accepted_count, acceptance_rate (+2) | 045_precompute_more.sql | 0/0 |
| `pc_acceptance_stats_by_program` | **[empty]** | program_id, fiscal_year, round_label, applied_count, accepted_count (+2) | 044_precompute_tables.sql | 0/0 |
| `pc_amendment_recent_by_law` | **[empty]** | law_id, amendment_id, severity, effective_date, summary (+1) | 045_precompute_more.sql | 0/0 |
| `pc_amendment_severity_distribution` | **[empty]** | severity, month_yyyymm, amendment_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_amount_max_distribution` | **[empty]** | bucket, program_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_amount_to_recipient_size` | **[empty]** | amount_bucket, smb_size_class, recipient_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_application_close_calendar` | **[empty]** | month_of_year, program_id, close_date, days_until, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_authority_action_frequency` | **[empty]** | authority_id, month_yyyymm, action_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_authority_to_programs` | **[empty]** | authority_id, program_id, role, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_certification_by_subject` | **[empty]** | subject_code, rank, certification_id, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_combo_pairs` | **[empty]** | program_a, program_b, compat_kind, rationale, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_court_decision_law_chain` | **[empty]** | court_id, law_id, decision_id, relation_kind, decided_at (+1) | 045_precompute_more.sql | 0/0 |
| `pc_enforcement_by_industry` | **[empty]** | industry_jsic, enforcement_id, severity, observed_at, headline (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_enforcement_industry_distribution` | **[empty]** | industry_jsic, severity, five_year_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_industry_jsic_aliases` | **[empty]** | alias_text, industry_jsic, confidence, source, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_industry_jsic_to_program` | **[empty]** | industry_jsic, rank, program_id, relevance_score, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_invoice_registrant_by_pref` | **[empty]** | prefecture_code, registrant_count, last_seen_at, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_law_amendments_recent` | **[empty]** | amendment_id, law_id, severity, effective_date, observed_at (+2) | 044_precompute_tables.sql | 0/0 |
| `pc_law_text_to_program_count` | **[empty]** | law_id, program_count, last_cited_at, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_law_to_amendment_chain` | **[empty]** | law_id, amendment_id, parent_amendment_id, position, effective_date (+1) | 045_precompute_more.sql | 0/0 |
| `pc_law_to_program_index` | **[empty]** | law_id, program_id, citation_kind, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_loan_by_collateral_type` | **[empty]** | collateral_type, rank, loan_program_id, cap_amount_yen, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_loan_collateral_to_program` | **[empty]** | collateral_type, program_id, rank, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_geographic_density` | **[empty]** | prefecture_code, tier, program_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_amendments` | **[empty]** | program_id, amendment_id, severity, observed_at, summary (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_program_to_certification_combo` | **[empty]** | program_id, certification_id, requirement_kind, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_loan_combo` | **[empty]** | program_id, loan_program_id, compat_kind, rationale, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_tax_combo` | **[empty]** | program_id, tax_ruleset_id, applicability, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_seasonal_calendar` | **[empty]** | month_of_year, program_id, deadline_date, deadline_kind, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_starter_packs_per_audience` | **[empty]** | audience, rank, program_id, note, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_top_subsidies_by_industry` | **[empty]** | industry_jsic, rank, program_id, relevance_score, cached_payload (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_top_subsidies_by_prefecture` | **[empty]** | prefecture_code, rank, program_id, relevance_score, cached_payload (+1) | 044_precompute_tables.sql | 0/0 |
| `real_estate_programs` | **[empty]** | canonical_id, program_kind, name, authority, authority_level (+12) | 042_real_estate_schema.sql | 0/0 |
| `testimonials` | **[empty]** | id, api_key_hash, audience, text, name (+4) | 041_testimonials.sql | 0/1 |
| `zoning_overlays` | **[empty]** | canonical_id, prefecture, city, district, zoning_type (+5) | 042_real_estate_schema.sql | 0/0 |

### 1.3. Wave 6-10 (precompute/audit) — 9 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `advisory_locks` | **[empty]** | key, holder, acquired_at, ttl_s, expires_at | 063_advisory_locks.sql | 0/1 |
| `appi_deletion_requests` | **[empty]** | request_id, requester_email, requester_legal_name, target_houjin_bangou, target_data_categories (+7) | 068_appi_deletion_requests.sql | 0/1 |
| `appi_disclosure_requests` | **[empty]** | request_id, requester_email, requester_legal_name, target_houjin_bangou, identity_verification_method (+4) | 066_appi_disclosure_requests.sql | 0/1 |
| `audit_log` | 108 | id, ts, event_type, key_hash, key_hash_new (+4) | 058_audit_log.sql | 0/1 |
| `bg_task_queue` | 3 | id, kind, payload_json, status, attempts (+6) | 060_bg_task_queue.sql | 0/2 |
| `empty_search_log` | 37 | id, query, endpoint, filters_json, ip_hash (+1) | 062_empty_search_log.sql | 0/1 |
| `jpi_exclusion_rules_pre052_snapshot` | **[empty]** | rule_id, program_a, program_b, snapshot_at | 065_compat_matrix_uni_id_backfill.sql | 0/0 |
| `postmark_webhook_events` | **[empty]** | message_id, event_type, received_at, processed_at | 059_postmark_webhook_events.sql | 0/1 |
| `stripe_webhook_events` | 14 | event_id, event_type, livemode, received_at, processed_at | 053_stripe_webhook_events.sql | 0/2 |

### 1.4. Wave 11-15 (auth/webhooks/treaty) — 11 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_idempotency_cache` | 1 | cache_key, response_blob, expires_at, created_at | 087_idempotency_cache.sql | 0/2 |
| `audit_seals` | **[empty]** | call_id, api_key_hash, ts, endpoint, query_hash (+8) | 089_audit_seal_table.sql | 0/2 |
| `customer_watches` | **[empty]** | id, api_key_hash, watch_kind, target_id, registered_at (+6) | 088_houjin_watch.sql | 0/1 |
| `customer_webhooks` | **[empty]** | id, api_key_hash, url, event_types_json, secret_hmac (+7) | 080_customer_webhooks.sql | 0/1 |
| `email_unsubscribes` | **[empty]** | email, unsubscribed_at, reason | 072_email_unsubscribes.sql | 0/0 |
| `exclusion_reason_codes` | 15 | code, description, created_at | 074_tier_x_exclusion_reason_classify.sql | 0/0 |
| `refund_requests` | 2 | request_id, customer_id, amount_yen, reason, status (+2) | 071_stripe_edge_cases.sql | 0/0 |
| `saved_searches` | **[empty]** | id, api_key_hash, name, query_json, frequency (+11) | 079_saved_searches.sql | 1/3 |
| `stripe_tax_cache` | **[empty]** | customer_id, rate_bps, jurisdiction, tax_amount_yen, cached_at | 071_stripe_edge_cases.sql | 0/0 |
| `trial_signups` | 1 | email, email_normalized, token_hash, created_at, created_ip_hash (+2) | 076_trial_signup.sql | 0/1 |
| `webhook_deliveries` | **[empty]** | id, webhook_id, event_type, event_id, payload_json (+5) | 080_customer_webhooks.sql | 0/1 |

### 1.5. Wave 16-20 (NTA/integrations) — 8 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `client_profiles` | **[empty]** | profile_id, api_key_hash, name_label, jsic_major, prefecture (+6) | 096_client_profiles.sql | 0/3 |
| `course_subscriptions` | **[empty]** | id, api_key_id, email, course_slug, started_at (+5) | 099_recurring_engagement.sql | 0/1 |
| `cron_runs` | 26 | id, cron_name, started_at, finished_at, status (+6) | 102_cron_runs_heartbeat.sql | 0/1 |
| `customer_intentions` | **[empty]** | id, api_key_hash, profile_id, program_id, awarded_at (+4) | 098_program_post_award_calendar.sql | 0/0 |
| `integration_accounts` | **[empty]** | id, api_key_hash, provider, encrypted_blob, display_handle (+3) | 105_integrations.sql | 0/1 |
| `integration_sync_log` | **[empty]** | id, api_key_hash, provider, idempotency_key, saved_search_id (+4) | 105_integrations.sql | 0/2 |
| `line_message_log` | **[empty]** | log_id, event_id, line_user_id, event_type, direction (+8) | 106_line_message_log.sql | 0/1 |
| `program_post_award_calendar` | **[empty]** | id, program_id, milestone_kind, days_after_award, kind_label (+2) | 098_program_post_award_calendar.sql | 0/0 |

### 1.6. Wave 21-22 — 4 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `alias_candidates_queue` | **[empty]** | id, candidate_alias, canonical_term, match_score, empty_query_count (+5) | 112_alias_candidates_queue.sql | 0/0 |
| `analytics_events` | 1,380 | id, ts, method, path, status (+11) | 111_analytics_events.sql | 0/2 |
| `citation_verification` | **[empty]** | id, entity_id, source_url, verification_status, matched_form (+3) | 126_citation_verification.sql | 0/1 |
| `funnel_events` | 13 | id, ts, event_name, page, properties_json (+8) | 123_funnel_events.sql | 0/2 |

### 1.9. no-migration — 9 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `_aggregator_purge_2026_04_25` | 21 | unified_id, primary_name, aliases_json, authority_level, authority_name (+29) | - | 0/0 |
| `api_keys` | 2 | key_hash, customer_id, tier, stripe_subscription_id, created_at (+16) | - | 1/13 |
| `exclusion_rules` | 181 | rule_id, kind, severity, program_a, program_b (+9) | - | 1/3 |
| `meta` | 4 | key, value, updated_at | - | 1/1 |
| `programs` | 14,472 | unified_id, primary_name, aliases_json, authority_level, authority_name (+46) | - | 5/15 |
| `schema_migrations` | 118 | id, checksum, applied_at | - | 0/0 |
| `source_failures` | 13 | id, unified_id, source_url, status_code, checked_at (+1) | - | 0/0 |
| `source_redirects` | **[empty]** | id, unified_id, orig_url, final_url, detected_at | - | 0/0 |
| `usage_events` | **[empty]** | id, key_hash, endpoint, ts, status (+9) | - | 1/15 |

### 1.10. FTS shadow — 66 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `adoption_fts` | **[empty]** | record_id, project_title, industry_raw, company_name_raw, program_name_raw | 014_business_intelligence_layer.sql | 0/0 |
| `adoption_fts_config` | 1 | k, v | - | 0/0 |
| `adoption_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `adoption_fts_data` | 2 | id, block | - | 0/0 |
| `adoption_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `adoption_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `bids_fts` | 362 | unified_id, bid_title, bid_description, procuring_entity, winner_name | 017_bids.sql | 0/0 |
| `bids_fts_config` | 1 | k, v | - | 0/0 |
| `bids_fts_content` | 362 | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `bids_fts_data` | 108 | id, block | - | 0/0 |
| `bids_fts_docsize` | 362 | id, sz | - | 0/0 |
| `bids_fts_idx` | 106 | segid, term, pgno | - | 0/0 |
| `case_studies_fts` | 2,286 | case_id, company_name, case_title, case_summary, source_excerpt | 057_case_studies_fts.sql | 0/0 |
| `case_studies_fts_config` | 1 | k, v | - | 0/0 |
| `case_studies_fts_content` | 2,286 | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `case_studies_fts_data` | 7,677 | id, block | - | 0/0 |
| `case_studies_fts_docsize` | 2,286 | id, sz | - | 0/0 |
| `case_studies_fts_idx` | 7,866 | segid, term, pgno | - | 0/0 |
| `court_decisions_fts` | 2,065 | unified_id, case_name, subject_area, key_ruling, impact_on_business | 016_court_decisions.sql | 0/0 |
| `court_decisions_fts_config` | 1 | k, v | - | 0/0 |
| `court_decisions_fts_content` | 2,065 | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `court_decisions_fts_data` | 1,575 | id, block | - | 0/0 |
| `court_decisions_fts_docsize` | 2,065 | id, sz | - | 0/0 |
| `court_decisions_fts_idx` | 1,571 | segid, term, pgno | - | 0/0 |
| `houjin_master_fts` | **[empty]** | houjin_bangou, normalized_name, alternative_names, address | 014_business_intelligence_layer.sql | 0/0 |
| `houjin_master_fts_config` | 1 | k, v | - | 0/0 |
| `houjin_master_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `houjin_master_fts_data` | 2 | id, block | - | 0/0 |
| `houjin_master_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `houjin_master_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `laws_fts` | 9,484 | unified_id, law_title, law_short_title, law_number, summary | 015_laws.sql | 0/0 |
| `laws_fts_config` | 1 | k, v | - | 0/0 |
| `laws_fts_content` | 9,484 | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `laws_fts_data` | 1,307 | id, block | - | 0/0 |
| `laws_fts_docsize` | 9,484 | id, sz | - | 0/0 |
| `laws_fts_idx` | 1,125 | segid, term, pgno | - | 0/0 |
| `ministry_faq_fts` | **[empty]** | faq_id, question, answer, category | 014_business_intelligence_layer.sql | 0/0 |
| `ministry_faq_fts_config` | 1 | k, v | - | 0/0 |
| `ministry_faq_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `ministry_faq_fts_data` | 2 | id, block | - | 0/0 |
| `ministry_faq_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `ministry_faq_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `programs_fts` | 11,869 | unified_id, primary_name, aliases, enriched_text | - | 0/0 |
| `programs_fts_config` | 1 | k, v | - | 0/0 |
| `programs_fts_content` | 11,869 | id, c0, c1, c2, c3 | - | 0/0 |
| `programs_fts_data` | 33,839 | id, block | - | 0/0 |
| `programs_fts_docsize` | 11,869 | id, sz | - | 0/0 |
| `programs_fts_idx` | 18,497 | segid, term, pgno | - | 0/0 |
| `support_org_fts` | **[empty]** | org_id, org_name, services, specialties | 014_business_intelligence_layer.sql | 0/0 |
| `support_org_fts_config` | 1 | k, v | - | 0/0 |
| `support_org_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `support_org_fts_data` | 2 | id, block | - | 0/0 |
| `support_org_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `support_org_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `tax_rulesets_fts` | 50 | unified_id, ruleset_name, eligibility_conditions, calculation_formula | 018_tax_rulesets.sql | 0/0 |
| `tax_rulesets_fts_config` | 1 | k, v | - | 0/0 |
| `tax_rulesets_fts_content` | 50 | id, c0, c1, c2, c3 | - | 0/0 |
| `tax_rulesets_fts_data` | 47 | id, block | - | 0/0 |
| `tax_rulesets_fts_docsize` | 50 | id, sz | - | 0/0 |
| `tax_rulesets_fts_idx` | 45 | segid, term, pgno | - | 0/0 |
| `verticals_deep_fts` | **[empty]** | vertical_id, vertical_label, record_title, record_summary | 014_business_intelligence_layer.sql | 0/0 |
| `verticals_deep_fts_config` | 1 | k, v | - | 0/0 |
| `verticals_deep_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `verticals_deep_fts_data` | 2 | id, block | - | 0/0 |
| `verticals_deep_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `verticals_deep_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |

### 1.X. Views

| View | Rows | Migration |
|---|---:|---|
| `am_unified_rule` | ERR_OperationalError | 064_unified_rule_view.sql |
| `case_law_v2` | 2,065 | 016_court_decisions.sql |

---

## 2. `autonomath.db` (full operator/ETL working DB, 9.4 GB)

### 2.1. Foundation tables (shared schema with jpintel) — 107 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `adoption_records` | **[empty]** | id, houjin_bangou, program_id_hint, program_name_raw, company_name_raw (+14) | 014_business_intelligence_layer.sql | 0/0 |
| `advisor_referrals` | **[empty]** | id, referral_token, advisor_id, source_query_hash, source_program_id (+9) | 024_advisors.sql | 0/1 |
| `advisors` | **[empty]** | id, houjin_bangou, firm_name, firm_name_kana, firm_type (+21) | 024_advisors.sql | 0/1 |
| `advisory_locks` | **[empty]** | key, holder, acquired_at, ttl_s, expires_at | 063_advisory_locks.sql | 0/1 |
| `alert_subscriptions` | **[empty]** | id, api_key_hash, filter_type, filter_value, min_severity (+6) | 038_alert_subscriptions.sql | 0/2 |
| `analytics_events` | **[empty]** | id, ts, method, path, status (+5) | 111_analytics_events.sql | 0/2 |
| `anon_rate_limit` | **[empty]** | ip_hash, date, call_count, first_seen, last_seen | 007_anon_rate_limit.sql | 0/3 |
| `api_key_rotations` | **[empty]** | rotation_id, old_key_hash, new_key_hash, reason, rotated_at (+3) | - | 0/0 |
| `api_keys` | **[empty]** | key_hash, key_prefix, created_at, disabled_at, disabled_reason (+17) | - | 1/13 |
| `appi_deletion_requests` | **[empty]** | request_id, requester_email, requester_legal_name, target_houjin_bangou, target_data_categories (+7) | 068_appi_deletion_requests.sql | 0/1 |
| `appi_disclosure_requests` | **[empty]** | request_id, requester_email, requester_legal_name, target_houjin_bangou, identity_verification_method (+4) | 066_appi_disclosure_requests.sql | 0/1 |
| `audit_log` | **[empty]** | id, ts, event_type, key_hash, key_hash_new (+4) | 058_audit_log.sql | 0/1 |
| `audit_log_section52` | 1 | id, sampled_at, tool, request_hash, response_hash (+3) | 101_trust_infrastructure.sql | 0/1 |
| `audit_merkle_anchor` | **[empty]** | daily_date, row_count, merkle_root, ots_proof, github_commit_sha (+2) | 146_audit_merkle_anchor.sql | 0/1 |
| `audit_merkle_leaves` | **[empty]** | daily_date, leaf_index, evidence_packet_id, leaf_hash | 146_audit_merkle_anchor.sql | 0/1 |
| `bg_task_queue` | **[empty]** | id, kind, payload_json, status, attempts (+6) | 060_bg_task_queue.sql | 0/2 |
| `bids` | **[empty]** | unified_id, bid_title, bid_kind, procuring_entity, procuring_houjin_bangou (+21) | 017_bids.sql | 1/2 |
| `care_subsidies` | **[empty]** | canonical_id, program_name, authority, authority_level, prefecture (+11) | 039_healthcare_schema.sql | 1/0 |
| `case_law` | **[empty]** | id, case_name, court, decision_date, case_number (+10) | 012_case_law.sql | 0/0 |
| `case_studies` | **[empty]** | case_id, company_name, houjin_bangou, is_sole_proprietor, prefecture (+17) | 011_external_data_tables.sql | 2/1 |
| `compliance_notification_log` | **[empty]** | id, subscriber_id, sent_at, subject, changes_json (+2) | 020_compliance_subscribers.sql | 0/0 |
| `compliance_subscribers` | **[empty]** | id, email, houjin_bangou, industry_codes_json, areas_of_interest_json (+14) | 020_compliance_subscribers.sql | 0/2 |
| `correction_log` | 1 | id, detected_at, dataset, entity_id, field_name (+7) | 101_trust_infrastructure.sql | 0/1 |
| `correction_submissions` | **[empty]** | id, submitted_at, entity_id, field, claimed_correct_value (+9) | 101_trust_infrastructure.sql | 0/1 |
| `court_decisions` | **[empty]** | unified_id, case_name, case_number, court, court_level (+16) | 016_court_decisions.sql | 2/3 |
| `cron_runs` | **[empty]** | id, cron_name, started_at, finished_at, status (+6) | 102_cron_runs_heartbeat.sql | 0/1 |
| `cross_source_baseline_state` | 1 | id, baseline_run_at, baseline_completed | 107_cross_source_baseline_state.sql | 0/0 |
| `dd_question_templates` | 60 | question_id, question_ja, question_category, industry_jsic_major, program_kind (+6) | 104_wave22_dd_question_templates.sql | 1/0 |
| `dead_url_alerts` | **[empty]** | id, detected_at, dataset, entity_id, dead_url (+4) | 101_trust_infrastructure.sql | 0/0 |
| `device_codes` | **[empty]** | device_code, user_code, status, client_fingerprint, scope (+12) | 023_device_codes.sql | 0/2 |
| `email_schedule` | **[empty]** | id, api_key_id, email, kind, send_at (+5) | 008_email_schedule.sql | 0/1 |
| `email_unsubscribes` | **[empty]** | email, unsubscribed_at, reason | 072_email_unsubscribes.sql | 0/0 |
| `empty_search_log` | **[empty]** | id, query, endpoint, filters_json, ip_hash (+1) | 062_empty_search_log.sql | 0/1 |
| `enforcement_cases` | **[empty]** | case_id, event_type, program_name_hint, recipient_name, recipient_kind (+21) | 011_external_data_tables.sql | 1/2 |
| `enforcement_decision_refs` | **[empty]** | enforcement_case_id, decision_unified_id, ref_kind, source_url, fetched_at | 016_court_decisions.sql | 1/0 |
| `entity_id_map` | 6,339 | jpi_unified_id, am_canonical_id, match_method, confidence, matched_at | - | 1/5 |
| `exclusion_reason_codes` | 10 | code, description, created_at | 074_tier_x_exclusion_reason_classify.sql | 0/0 |
| `exclusion_rules` | **[empty]** | rule_id, kind, severity, program_a, program_b (+9) | - | 1/3 |
| `feedback` | **[empty]** | id, key_hash, customer_id, tier, message (+5) | 003_feedback.sql | 0/1 |
| `funnel_events` | **[empty]** | id, ts, event_name, page, properties_json (+8) | 123_funnel_events.sql | 0/2 |
| `houjin_master` | **[empty]** | houjin_bangou, normalized_name, alternative_names_json, address_normalized, prefecture (+15) | 014_business_intelligence_layer.sql | 0/0 |
| `industry_program_density` | **[empty]** | id, jsic_code_medium, prefecture, program_id, peer_count (+7) | 014_business_intelligence_layer.sql | 0/0 |
| `industry_stats` | **[empty]** | id, statistic_source, statistic_year, jsic_code_large, jsic_name_large (+16) | 014_business_intelligence_layer.sql | 0/0 |
| `invoice_registrants` | **[empty]** | invoice_registration_number, houjin_bangou, normalized_name, address_normalized, prefecture (+11) | 019_invoice_registrants.sql | 1/3 |
| `l4_query_cache` | **[empty]** | cache_key, tool_name, params_json, result_json, hit_count (+3) | 043_l4_cache.sql | 0/0 |
| `laws` | **[empty]** | unified_id, law_number, law_title, law_short_title, law_type (+15) | 015_laws.sql | 1/4 |
| `line_message_log` | **[empty]** | log_id, event_id, line_user_id, event_type, direction (+8) | 106_line_message_log.sql | 0/1 |
| `line_users` | **[empty]** | line_user_id, display_name, picture_url, language, added_at (+9) | 021_line_users.sql | 0/1 |
| `loan_programs` | **[empty]** | id, program_name, provider, loan_type, amount_max_yen (+15) | 011_external_data_tables.sql | 1/1 |
| `medical_institutions` | **[empty]** | canonical_id, institution_type, name, name_kana, prefecture (+12) | 039_healthcare_schema.sql | 1/0 |
| `meta` | **[empty]** | key, value, updated_at | - | 1/1 |
| `ministry_faq` | **[empty]** | id, program_name_hint, ministry, category, question (+5) | 014_business_intelligence_layer.sql | 0/0 |
| `new_program_candidates` | **[empty]** | id, candidate_name, mentioned_in, ministry, budget_yen (+7) | 011_external_data_tables.sql | 0/0 |
| `pc_acceptance_rate_by_authority` | **[empty]** | authority_id, fiscal_year, applied_count, accepted_count, acceptance_rate (+2) | 045_precompute_more.sql | 0/0 |
| `pc_acceptance_stats_by_program` | **[empty]** | program_id, fiscal_year, round_label, applied_count, accepted_count (+2) | 044_precompute_tables.sql | 0/0 |
| `pc_amendment_recent_by_law` | **[empty]** | law_id, amendment_id, severity, effective_date, summary (+1) | 045_precompute_more.sql | 0/0 |
| `pc_amendment_severity_distribution` | **[empty]** | severity, month_yyyymm, amendment_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_amount_max_distribution` | **[empty]** | bucket, program_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_amount_to_recipient_size` | **[empty]** | amount_bucket, smb_size_class, recipient_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_application_close_calendar` | **[empty]** | month_of_year, program_id, close_date, days_until, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_authority_action_frequency` | **[empty]** | authority_id, month_yyyymm, action_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_authority_to_programs` | **[empty]** | authority_id, program_id, role, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_certification_by_subject` | **[empty]** | subject_code, rank, certification_id, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_combo_pairs` | **[empty]** | program_a, program_b, compat_kind, rationale, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_court_decision_law_chain` | **[empty]** | court_id, law_id, decision_id, relation_kind, decided_at (+1) | 045_precompute_more.sql | 0/0 |
| `pc_enforcement_by_industry` | **[empty]** | industry_jsic, enforcement_id, severity, observed_at, headline (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_enforcement_industry_distribution` | **[empty]** | industry_jsic, severity, five_year_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_industry_jsic_aliases` | **[empty]** | alias_text, industry_jsic, confidence, source, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_industry_jsic_to_program` | **[empty]** | industry_jsic, rank, program_id, relevance_score, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_invoice_registrant_by_pref` | **[empty]** | prefecture_code, registrant_count, last_seen_at, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_law_amendments_recent` | **[empty]** | amendment_id, law_id, severity, effective_date, observed_at (+2) | 044_precompute_tables.sql | 0/0 |
| `pc_law_text_to_program_count` | **[empty]** | law_id, program_count, last_cited_at, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_law_to_amendment_chain` | **[empty]** | law_id, amendment_id, parent_amendment_id, position, effective_date (+1) | 045_precompute_more.sql | 0/0 |
| `pc_law_to_program_index` | **[empty]** | law_id, program_id, citation_kind, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_loan_by_collateral_type` | **[empty]** | collateral_type, rank, loan_program_id, cap_amount_yen, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_loan_collateral_to_program` | **[empty]** | collateral_type, program_id, rank, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_geographic_density` | **[empty]** | prefecture_code, tier, program_count, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_amendments` | **[empty]** | program_id, amendment_id, severity, observed_at, summary (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_program_to_certification_combo` | **[empty]** | program_id, certification_id, requirement_kind, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_loan_combo` | **[empty]** | program_id, loan_program_id, compat_kind, rationale, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_program_to_tax_combo` | **[empty]** | program_id, tax_ruleset_id, applicability, refreshed_at | 045_precompute_more.sql | 0/0 |
| `pc_seasonal_calendar` | **[empty]** | month_of_year, program_id, deadline_date, deadline_kind, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_starter_packs_per_audience` | **[empty]** | audience, rank, program_id, note, refreshed_at | 044_precompute_tables.sql | 0/0 |
| `pc_top_subsidies_by_industry` | **[empty]** | industry_jsic, rank, program_id, relevance_score, cached_payload (+1) | 044_precompute_tables.sql | 0/0 |
| `pc_top_subsidies_by_prefecture` | **[empty]** | prefecture_code, rank, program_id, relevance_score, cached_payload (+1) | 044_precompute_tables.sql | 0/0 |
| `postmark_webhook_events` | **[empty]** | message_id, event_type, received_at, processed_at | 059_postmark_webhook_events.sql | 0/1 |
| `program_documents` | **[empty]** | id, program_name, form_name, form_type, form_format (+9) | 011_external_data_tables.sql | 0/0 |
| `program_law_refs` | **[empty]** | program_unified_id, law_unified_id, ref_kind, article_citation, source_url (+2) | 015_laws.sql | 1/2 |
| `programs` | **[empty]** | unified_id, primary_name, aliases_json, authority_level, authority_name (+30) | - | 5/15 |
| `quality_metrics_daily` | **[empty]** | id, computed_at, computed_for_date, dataset, precision_estimate (+7) | 101_trust_infrastructure.sql | 0/0 |
| `query_log_v2` | **[empty]** | id, ts, tool, status_code, duration_ms (+4) | - | 0/1 |
| `real_estate_programs` | **[empty]** | canonical_id, program_kind, name, authority, authority_level (+12) | 042_real_estate_schema.sql | 0/0 |
| `refund_requests` | **[empty]** | request_id, customer_id, amount_yen, reason, status (+2) | 071_stripe_edge_cases.sql | 0/0 |
| `reproducibility_snapshots` | **[empty]** | snapshot_id, captured_at, api_version, row_counts_json, on_disk (+3) | 101_trust_infrastructure.sql | 0/0 |
| `schema_migrations` | 124 | id, checksum, applied_at | - | 0/0 |
| `source_lineage_audit` | **[empty]** | id, table_name, row_key, source_url, source_domain (+5) | 014_business_intelligence_layer.sql | 0/0 |
| `stripe_tax_cache` | **[empty]** | customer_id, rate_bps, jurisdiction, tax_amount_yen, cached_at | 071_stripe_edge_cases.sql | 0/0 |
| `stripe_webhook_events` | **[empty]** | event_id, event_type, livemode, received_at, processed_at | 053_stripe_webhook_events.sql | 0/2 |
| `subscribers` | **[empty]** | id, email, source, created_at, unsubscribed_at | 002_subscribers.sql | 0/3 |
| `support_org` | **[empty]** | org_id, org_type, org_name, houjin_bangou, prefecture (+10) | 014_business_intelligence_layer.sql | 0/0 |
| `tax_rulesets` | **[empty]** | unified_id, ruleset_name, tax_category, ruleset_kind, effective_from (+15) | 018_tax_rulesets.sql | 1/2 |
| `testimonials` | **[empty]** | id, api_key_hash, audience, text, name (+4) | 041_testimonials.sql | 0/1 |
| `trial_signups` | **[empty]** | email, email_normalized, token_hash, created_at, created_ip_hash (+2) | 076_trial_signup.sql | 0/1 |
| `usage_events` | **[empty]** | id, key_hash, endpoint, ts, status (+7) | - | 1/15 |
| `verticals_deep` | **[empty]** | id, vertical_code, vertical_label, wave_number, record_type (+11) | 014_business_intelligence_layer.sql | 0/0 |
| `widget_keys` | **[empty]** | key_id, owner_email, label, allowed_origins_json, stripe_customer_id (+11) | 022_widget_keys.sql | 0/1 |
| `zoning_overlays` | **[empty]** | canonical_id, prefecture, city, district, zoning_type (+5) | 042_real_estate_schema.sql | 0/0 |

### 2.3. AutonoMath canonical (`am_*`) — Wave 2-5 (BI/health/RE) — 4 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_annotation_kind` | 6 | kind, description, default_visibility | 046_annotation_layer.sql | 0/0 |
| `am_entity_annotation` | 16,474 | annotation_id, entity_id, kind, severity, text_ja (+10) | 046_annotation_layer.sql | 1/1 |
| `am_validation_result` | 54 | result_id, rule_id, entity_id, applicant_hash, passed (+2) | 047_validation_layer.sql | 1/0 |
| `am_validation_rule` | 6 | rule_id, applies_to, scope, predicate_kind, predicate_ref (+8) | 047_validation_layer.sql | 1/1 |

### 2.4. AutonoMath canonical (`am_*`) — Wave 11-15 (auth/webhooks/treaty) — 2 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_amendment_diff` | 7,819 | diff_id, entity_id, field_name, prev_value, new_value (+4) | 075_am_amendment_diff.sql | 3/4 |
| `am_idempotency_cache` | **[empty]** | cache_key, response_blob, expires_at, created_at | 087_idempotency_cache.sql | 0/2 |

### 2.5. AutonoMath canonical (`am_*`) — Wave 16-20 (NTA/integrations) — 1 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_tax_treaty` | 33 | treaty_id, country_iso, country_name_ja, country_name_en, treaty_kind (+15) | 091_tax_treaty.sql | 1/0 |

### 2.6. AutonoMath canonical (`am_*`) — Wave 23 (am_*) — 8 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_adoption_trend_monthly` | 473 | year_month, jsic_major, adoption_count, distinct_houjin_count, distinct_program_count (+2) | 160_am_adoption_trend_monthly.sql | 0/0 |
| `am_enforcement_anomaly` | 1,034 | prefecture_code, jsic_major, enforcement_count, z_score, anomaly_flag (+2) | 161_am_enforcement_anomaly.sql | 0/0 |
| `am_entity_density_score` | 503,930 | entity_id, record_kind, verification_count, edge_count, fact_count (+6) | 158_am_entity_density_score.sql | 1/1 |
| `am_entity_pagerank` | 503,930 | entity_id, pagerank_score, pagerank_rank, in_degree, out_degree (+1) | 162_am_entity_pagerank.sql | 0/0 |
| `am_funding_stack_empirical` | 15 | program_a_id, program_b_id, co_adoption_count, mean_days_between, compat_matrix_says (+2) | 156_am_funding_stack_empirical.sql | 0/1 |
| `am_geo_industry_density` | 1,034 | prefecture_code, jsic_major, program_count, program_tier_S, program_tier_A (+6) | 155_am_geo_industry_density.sql,wave24_155_am_geo_industry_density.sql | 0/0 |
| `am_id_bridge` | 6,350 | id_a, id_b, bridge_kind, confidence, created_at | 159_am_id_bridge.sql | 0/0 |
| `am_temporal_correlation` | 166 | amendment_id, amendment_effective_at, law_canonical_id, program_id, adoption_count_pre30d (+5) | 154_am_temporal_correlation.sql | 0/0 |

### 2.7. AutonoMath canonical (`am_*`) — no-migration — 73 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `am_acceptance_stat` | 522 | program_entity_id, round_label, application_date, applied_count, accepted_count (+4) | - | 0/0 |
| `am_acceptance_trend` | 69 | program_entity_id, primary_name, rounds_count, rate_min, rate_max (+11) | - | 0/0 |
| `am_alias` | 335,605 | id, entity_table, canonical_id, alias, alias_kind (+2) | - | 1/0 |
| `am_amendment_snapshot` | 14,596 | snapshot_id, entity_id, version_seq, observed_at, effective_from (+11) | - | 4/0 |
| `am_amount_condition` | 250,946 | id, entity_id, condition_label, base_rate_num, base_rate_denom (+21) | - | 0/0 |
| `am_application_round` | 1,256 | round_id, program_entity_id, round_label, round_seq, application_open_date (+7) | - | 5/1 |
| `am_application_steps` | 700 | program_entity_id, step_no, step_title, step_description, prerequisites_json (+4) | - | 2/0 |
| `am_authority` | 585 | canonical_id, canonical_name, canonical_en, level, parent_id (+4) | - | 0/0 |
| `am_case_law` | 50 | case_id, case_number, court_name, decision_date, case_kind (+7) | - | 0/0 |
| `am_combo_calculator` | 56 | combo_id, combo_name, members_json, scenario_business_type, invest_amount_yen (+12) | - | 1/0 |
| `am_compat_matrix` | 43,966 | program_a_id, program_b_id, compat_status, combined_max_yen, conditions_text (+7) | - | 4/1 |
| `am_deadline_cascade` | 3,606 | cascade_id, source_program_id, source_round_label, source_close_date, alt_rank (+7) | - | 0/0 |
| `am_eligibility_tree` | 1,000 | program_entity_id, question_no, question_text, question_kind, yes_path_action (+4) | - | 0/0 |
| `am_enforcement_detail` | 22,258 | enforcement_id, entity_id, houjin_bangou, target_name, enforcement_kind (+10) | - | 4/2 |
| `am_entities` | 503,930 | canonical_id, record_kind, source_topic, source_record_index, primary_name (+12) | - | 15/7 |
| `am_entities_fts_uni` | 388,972 | canonical_id, record_kind, primary_name, raw_json | - | 0/0 |
| `am_entities_fts_uni_config` | 1 | k, v | - | 0/0 |
| `am_entities_fts_uni_content` | 388,972 | id, c0, c1, c2, c3 | - | 0/0 |
| `am_entities_fts_uni_data` | 59,898 | id, block | - | 0/0 |
| `am_entities_fts_uni_docsize` | 388,972 | id, sz | - | 0/0 |
| `am_entities_fts_uni_idx` | 7,925 | segid, term, pgno | - | 0/0 |
| `am_entity_facts` | 6,124,990 | id, entity_id, field_name, field_value_text, field_value_json (+9) | - | 1/5 |
| `am_entity_source` | 279,841 | entity_id, source_id, role, source_field, promoted_at | - | 1/2 |
| `am_entity_tag` | 5,821 | tag_id, entity_id, tag_category, tag_name, derive_method (+2) | - | 0/0 |
| `am_evidence_citation` | 17,883 | entity_id, intent_id, citation_no, text_short, text_long (+7) | - | 0/0 |
| `am_faq` | 100 | faq_id, category, question_text, answer_short, answer_full (+4) | - | 0/0 |
| `am_hallucination_guard` | 504 | guard_id, fake_term, fake_kind, status, similar_canonical_id (+5) | - | 0/0 |
| `am_industry_jsic` | 37 | jsic_code, jsic_level, jsic_name_ja, jsic_name_en, parent_code (+1) | - | 2/0 |
| `am_insurance_mutual` | 31 | canonical_id, primary_name, provider_entity_id, plan_kind, premium_min_yen (+8) | - | 2/0 |
| `am_intent_skeleton` | 50 | intent_id, variant_id, skeleton_text, required_slots, optional_slots (+5) | - | 0/0 |
| `am_law` | 10,125 | canonical_id, canonical_name, short_name, law_number, category (+12) | - | 3/0 |
| `am_law_article` | 204,188 | article_id, law_canonical_id, article_number, article_number_sort, title (+12) | - | 5/0 |
| `am_law_reference` | 5,523 | id, entity_id, law_canonical_id, law_name_raw, article (+7) | - | 0/0 |
| `am_loan_product` | 45 | canonical_id, primary_name, lender_entity_id, loan_program_kind, limit_yen (+13) | - | 3/0 |
| `am_peer_cache` | 9,830 | region_code, peer_code, rank, similarity, reason (+1) | - | 0/0 |
| `am_prerequisite_bundle` | 795 | bundle_id, program_entity_id, prerequisite_kind, prerequisite_name, required_or_optional (+6) | - | 3/0 |
| `am_profile_match` | 3,840 | profile_hash, industry_jsic, company_size, prefecture_code, purpose (+5) | - | 0/0 |
| `am_program_comparison` | 54 | compare_set_id, set_name, members_json, comparison_table, decision_tree_text (+3) | - | 0/0 |
| `am_program_summary` | 5,627 | entity_id, primary_name, summary_50, summary_200, summary_800 (+5) | - | 1/0 |
| `am_query_facet_dict` | 1,081 | facet_id, facet_kind, pattern_text, pattern_kind, facet_value (+3) | - | 0/0 |
| `am_region` | 1,966 | region_code, region_level, name_ja, name_en, name_kana (+10) | - | 1/0 |
| `am_relation` | 378,342 | id, source_entity_id, target_entity_id, target_raw, relation_type (+6) | - | 2/1 |
| `am_relation_facts` | 199 | id, source_entity_id, target_entity_id, target_raw, relation_type (+4) | - | 0/0 |
| `am_sib_contract` | 35 | canonical_id, contract_name, contract_type, implementing_body, implementing_authority (+11) | - | 0/0 |
| `am_source` | 97,272 | id, source_url, source_type, domain, is_pdf (+6) | - | 1/8 |
| `am_subsidy_rule` | 44 | subsidy_rule_id, program_entity_id, rule_type, base_rate_pct, cap_yen (+13) | - | 1/0 |
| `am_system_prompt` | 20 | prompt_id, persona, language, prompt_text, recommended_tools (+4) | - | 0/0 |
| `am_target_profile` | 43 | canonical_id, human_label, entity_class, sme_bucket, capital_max_yen (+10) | - | 0/0 |
| `am_tax_rule` | 145 | tax_measure_entity_id, rule_type, base_rate_pct, cap_yen, eligibility_cond_json (+9) | - | 4/0 |
| `am_tax_rule_narrative` | 145 | tax_rule_id, tax_measure_entity_id, rule_type, narrative_short, narrative_full (+5) | - | 0/0 |
| `am_user_query_seed` | 100 | query_id, query_text, language, intent_id, expected_tools (+7) | - | 0/0 |
| `am_vec_tier_a_chunks` | 415 | chunk_id, size, validity, rowids | - | 0/0 |
| `am_vec_tier_a_info` | 4 | key, value | - | 0/0 |
| `am_vec_tier_a_rowids` | 424,277 | rowid, id, chunk_id, chunk_offset | - | 0/0 |
| `am_vec_tier_a_vector_chunks00` | 415 | rowid, vectors | - | 0/0 |
| `am_vec_tier_b_dealbreakers_chunks` | **[empty]** | chunk_id, size, validity, rowids | - | 0/0 |
| `am_vec_tier_b_dealbreakers_info` | 4 | key, value | - | 0/0 |
| `am_vec_tier_b_dealbreakers_rowids` | **[empty]** | rowid, id, chunk_id, chunk_offset | - | 0/0 |
| `am_vec_tier_b_dealbreakers_vector_chunks00` | **[empty]** | rowid, vectors | - | 0/0 |
| `am_vec_tier_b_eligibility_chunks` | **[empty]** | chunk_id, size, validity, rowids | - | 0/0 |
| `am_vec_tier_b_eligibility_info` | 4 | key, value | - | 0/0 |
| `am_vec_tier_b_eligibility_rowids` | **[empty]** | rowid, id, chunk_id, chunk_offset | - | 0/0 |
| `am_vec_tier_b_eligibility_vector_chunks00` | **[empty]** | rowid, vectors | - | 0/0 |
| `am_vec_tier_b_exclusions_chunks` | **[empty]** | chunk_id, size, validity, rowids | - | 0/0 |
| `am_vec_tier_b_exclusions_info` | 4 | key, value | - | 0/0 |
| `am_vec_tier_b_exclusions_rowids` | **[empty]** | rowid, id, chunk_id, chunk_offset | - | 0/0 |
| `am_vec_tier_b_exclusions_vector_chunks00` | **[empty]** | rowid, vectors | - | 0/0 |
| `am_vec_tier_b_obligations_chunks` | **[empty]** | chunk_id, size, validity, rowids | - | 0/0 |
| `am_vec_tier_b_obligations_info` | 4 | key, value | - | 0/0 |
| `am_vec_tier_b_obligations_rowids` | **[empty]** | rowid, id, chunk_id, chunk_offset | - | 0/0 |
| `am_vec_tier_b_obligations_vector_chunks00` | **[empty]** | rowid, vectors | - | 0/0 |
| `am_webhook_delivery` | **[empty]** | delivery_id, subscription_id, event_type, event_id, payload_json (+7) | - | 0/0 |
| `am_webhook_subscription` | **[empty]** | subscription_id, api_key_hash, event_types_json, target_url, secret_hmac (+5) | - | 0/0 |

### 2.8. Wave 22+23 materialised views (`mat_*`) — 3 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `mat_active_program_summary` | 1 | active_programs, adoptions, enforcements, distinct_prefectures, distinct_authorities (+1) | - | 0/0 |
| `mat_entity_count_by_kind` | 17 | record_kind, canonical_status, n, refreshed_at | - | 0/0 |
| `mat_tax_rule_effective_now` | 125 | tax_measure_entity_id, rule_type, base_rate_pct, cap_yen, eligibility_cond_json (+10) | - | 0/0 |

### 2.9. NTA corpus (`nta_*`, Wave 20) — 4 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `nta_bunsho_kaitou` | 278 | id, slug, category, response_date, request_summary (+4) | 103_nta_corpus.sql | 1/1 |
| `nta_saiketsu` | 137 | id, volume_no, case_no, decision_date, fiscal_period (+7) | 103_nta_corpus.sql | 2/0 |
| `nta_shitsugi` | 286 | id, slug, category, question, answer (+4) | 103_nta_corpus.sql | 1/1 |
| `nta_tsutatsu_index` | 3,223 | id, code, law_canonical_id, article_number, title (+5) | 103_nta_corpus.sql | 2/1 |

### 2.10. `jpi_*` mirror snapshot (post-W18 split, see migration 110) — 80 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `jpi__aggregator_purge_2026_04_25` | 21 | unified_id, primary_name, aliases_json, authority_level, authority_name (+29) | - | 0/0 |
| `jpi_adoption_records` | 201,845 | id, houjin_bangou, program_id_hint, program_name_raw, company_name_raw (+17) | - | 3/1 |
| `jpi_advisor_referrals` | **[empty]** | id, referral_token, advisor_id, source_query_hash, source_program_id (+9) | - | 0/0 |
| `jpi_advisors` | **[empty]** | id, houjin_bangou, firm_name, firm_name_kana, firm_type (+21) | - | 0/0 |
| `jpi_alert_subscriptions` | 1 | id, api_key_hash, filter_type, filter_value, min_severity (+6) | - | 0/0 |
| `jpi_anon_rate_limit` | 5 | ip_hash, date, call_count, first_seen, last_seen | - | 0/0 |
| `jpi_api_keys` | 2 | key_hash, customer_id, tier, stripe_subscription_id, created_at (+3) | - | 0/0 |
| `jpi_bids` | 362 | unified_id, bid_title, bid_kind, procuring_entity, procuring_houjin_bangou (+21) | - | 0/0 |
| `jpi_care_subsidies` | **[empty]** | canonical_id, program_name, authority, authority_level, prefecture (+11) | - | 0/0 |
| `jpi_case_law` | 495 | id, case_name, court, decision_date, case_number (+10) | - | 0/0 |
| `jpi_case_studies` | 2,286 | case_id, company_name, houjin_bangou, is_sole_proprietor, prefecture (+17) | - | 0/0 |
| `jpi_compliance_notification_log` | **[empty]** | id, subscriber_id, sent_at, subject, changes_json (+2) | - | 0/0 |
| `jpi_compliance_subscribers` | **[empty]** | id, email, houjin_bangou, industry_codes_json, areas_of_interest_json (+14) | - | 0/0 |
| `jpi_court_decisions` | 2,065 | unified_id, case_name, case_number, court, court_level (+16) | - | 0/0 |
| `jpi_device_codes` | **[empty]** | device_code, user_code, status, client_fingerprint, scope (+12) | - | 0/0 |
| `jpi_email_schedule` | **[empty]** | id, api_key_id, email, kind, send_at (+5) | - | 0/0 |
| `jpi_enforcement_cases` | 1,185 | case_id, event_type, program_name_hint, recipient_name, recipient_kind (+21) | - | 0/0 |
| `jpi_enforcement_decision_refs` | **[empty]** | enforcement_case_id, decision_unified_id, ref_kind, source_url, fetched_at | - | 0/0 |
| `jpi_exclusion_rules` | 181 | rule_id, kind, severity, program_a, program_b (+7) | - | 2/0 |
| `jpi_exclusion_rules_pre052_snapshot` | 179 | rule_id, program_a, program_b, snapshot_at | 065_compat_matrix_uni_id_backfill.sql | 0/0 |
| `jpi_feedback` | 1 | id, key_hash, customer_id, tier, message (+6) | - | 0/0 |
| `jpi_houjin_master` | 166,765 | houjin_bangou, normalized_name, alternative_names_json, address_normalized, prefecture (+10) | - | 3/0 |
| `jpi_industry_program_density` | **[empty]** | id, jsic_code_medium, prefecture, program_id, peer_count (+7) | - | 0/0 |
| `jpi_invoice_registrants` | 13,801 | invoice_registration_number, houjin_bangou, normalized_name, address_normalized, prefecture (+11) | - | 2/1 |
| `jpi_l4_query_cache` | **[empty]** | cache_key, tool_name, params_json, result_json, hit_count (+3) | - | 0/0 |
| `jpi_laws` | 9,484 | unified_id, law_number, law_title, law_short_title, law_type (+15) | - | 0/0 |
| `jpi_line_users` | **[empty]** | line_user_id, display_name, picture_url, language, added_at (+9) | - | 0/0 |
| `jpi_loan_programs` | 108 | id, program_name, provider, loan_type, amount_max_yen (+15) | - | 0/0 |
| `jpi_medical_institutions` | **[empty]** | canonical_id, institution_type, name, name_kana, prefecture (+12) | - | 0/0 |
| `jpi_meta` | 4 | key, value, updated_at | - | 0/0 |
| `jpi_ministry_faq` | **[empty]** | id, program_name_hint, ministry, category, question (+5) | - | 0/0 |
| `jpi_new_program_candidates` | 102 | id, candidate_name, mentioned_in, ministry, budget_yen (+7) | - | 0/0 |
| `jpi_pc_acceptance_rate_by_authority` | **[empty]** | authority_id, fiscal_year, applied_count, accepted_count, acceptance_rate (+2) | - | 0/0 |
| `jpi_pc_amendment_recent_by_law` | **[empty]** | law_id, amendment_id, severity, effective_date, summary (+1) | - | 0/0 |
| `jpi_pc_amendment_severity_distribution` | **[empty]** | severity, month_yyyymm, amendment_count, refreshed_at | - | 0/0 |
| `jpi_pc_amount_max_distribution` | **[empty]** | bucket, program_count, refreshed_at | - | 0/0 |
| `jpi_pc_amount_to_recipient_size` | **[empty]** | amount_bucket, smb_size_class, recipient_count, refreshed_at | - | 0/0 |
| `jpi_pc_application_close_calendar` | **[empty]** | month_of_year, program_id, close_date, days_until, refreshed_at | - | 0/0 |
| `jpi_pc_authority_action_frequency` | **[empty]** | authority_id, month_yyyymm, action_count, refreshed_at | - | 0/0 |
| `jpi_pc_authority_to_programs` | **[empty]** | authority_id, program_id, role, refreshed_at | - | 0/0 |
| `jpi_pc_certification_by_subject` | **[empty]** | subject_code, rank, certification_id, refreshed_at | - | 0/0 |
| `jpi_pc_combo_pairs` | **[empty]** | program_a, program_b, compat_kind, rationale, refreshed_at | - | 0/0 |
| `jpi_pc_court_decision_law_chain` | **[empty]** | court_id, law_id, decision_id, relation_kind, decided_at (+1) | - | 0/0 |
| `jpi_pc_enforcement_by_industry` | **[empty]** | industry_jsic, enforcement_id, severity, observed_at, headline (+1) | - | 0/0 |
| `jpi_pc_enforcement_industry_distribution` | **[empty]** | industry_jsic, severity, five_year_count, refreshed_at | - | 0/0 |
| `jpi_pc_industry_jsic_aliases` | **[empty]** | alias_text, industry_jsic, confidence, source, refreshed_at | - | 0/0 |
| `jpi_pc_industry_jsic_to_program` | **[empty]** | industry_jsic, rank, program_id, relevance_score, refreshed_at | - | 0/0 |
| `jpi_pc_invoice_registrant_by_pref` | **[empty]** | prefecture_code, registrant_count, last_seen_at, refreshed_at | - | 0/0 |
| `jpi_pc_law_amendments_recent` | **[empty]** | amendment_id, law_id, severity, effective_date, observed_at (+2) | - | 0/0 |
| `jpi_pc_law_text_to_program_count` | **[empty]** | law_id, program_count, last_cited_at, refreshed_at | - | 0/0 |
| `jpi_pc_law_to_amendment_chain` | **[empty]** | law_id, amendment_id, parent_amendment_id, position, effective_date (+1) | - | 0/0 |
| `jpi_pc_law_to_program_index` | **[empty]** | law_id, program_id, citation_kind, refreshed_at | - | 0/0 |
| `jpi_pc_loan_by_collateral_type` | **[empty]** | collateral_type, rank, loan_program_id, cap_amount_yen, refreshed_at | - | 0/0 |
| `jpi_pc_loan_collateral_to_program` | **[empty]** | collateral_type, program_id, rank, refreshed_at | - | 0/0 |
| `jpi_pc_program_geographic_density` | **[empty]** | prefecture_code, tier, program_count, refreshed_at | - | 0/0 |
| `jpi_pc_program_health` | 66 | program_id, quality_score, warning_count_recent, critical_count_recent, last_validated_at (+1) | 048_pc_program_health.sql | 1/0 |
| `jpi_pc_program_to_amendments` | **[empty]** | program_id, amendment_id, severity, observed_at, summary (+1) | - | 0/0 |
| `jpi_pc_program_to_certification_combo` | **[empty]** | program_id, certification_id, requirement_kind, refreshed_at | - | 0/0 |
| `jpi_pc_program_to_loan_combo` | **[empty]** | program_id, loan_program_id, compat_kind, rationale, refreshed_at | - | 0/0 |
| `jpi_pc_program_to_tax_combo` | **[empty]** | program_id, tax_ruleset_id, applicability, refreshed_at | - | 0/0 |
| `jpi_pc_seasonal_calendar` | **[empty]** | month_of_year, program_id, deadline_date, deadline_kind, refreshed_at | - | 0/0 |
| `jpi_pc_starter_packs_per_audience` | **[empty]** | audience, rank, program_id, note, refreshed_at | - | 0/0 |
| `jpi_pc_top_subsidies_by_industry` | **[empty]** | industry_jsic, rank, program_id, relevance_score, cached_payload (+1) | - | 0/0 |
| `jpi_pc_top_subsidies_by_prefecture` | **[empty]** | prefecture_code, rank, program_id, relevance_score, cached_payload (+1) | - | 0/0 |
| `jpi_program_documents` | 132 | id, program_name, form_name, form_type, form_format (+9) | - | 1/0 |
| `jpi_program_law_refs` | **[empty]** | program_unified_id, law_unified_id, ref_kind, article_citation, source_url (+2) | - | 0/0 |
| `jpi_programs` | 13,578 | unified_id, primary_name, aliases_json, authority_level, authority_name (+30) | - | 2/3 |
| `jpi_real_estate_programs` | **[empty]** | canonical_id, program_kind, name, authority, authority_level (+12) | - | 0/0 |
| `jpi_schema_migrations` | 30 | id, checksum, applied_at | - | 0/0 |
| `jpi_source_failures` | **[empty]** | id, unified_id, source_url, status_code, checked_at (+1) | - | 0/0 |
| `jpi_source_lineage_audit` | 13,829 | id, table_name, row_key, source_url, source_domain (+5) | - | 0/0 |
| `jpi_source_redirects` | **[empty]** | id, unified_id, orig_url, final_url, detected_at | - | 0/0 |
| `jpi_subscribers` | 1 | id, email, source, created_at, unsubscribed_at | - | 0/0 |
| `jpi_support_org` | **[empty]** | org_id, org_type, org_name, houjin_bangou, prefecture (+10) | - | 0/0 |
| `jpi_tax_rulesets` | 35 | unified_id, ruleset_name, tax_category, ruleset_kind, effective_from (+15) | - | 2/0 |
| `jpi_testimonials` | **[empty]** | id, api_key_hash, audience, text, name (+4) | - | 0/0 |
| `jpi_usage_events` | **[empty]** | id, key_hash, endpoint, ts, status (+2) | - | 0/0 |
| `jpi_verticals_deep` | **[empty]** | id, vertical_code, vertical_label, wave_number, record_type (+11) | - | 0/0 |
| `jpi_widget_keys` | **[empty]** | key_id, owner_email, label, allowed_origins_json, stripe_customer_id (+11) | - | 0/0 |
| `jpi_zoning_overlays` | **[empty]** | canonical_id, prefecture, city, district, zoning_type (+5) | - | 0/0 |

### 2.11. FTS5 shadow tables — 98 tables

| Table | Rows | Main columns | Migration | MCP/API refs |
|---|---:|---|---|---:|
| `adoption_fts` | **[empty]** | record_id, project_title, industry_raw, company_name_raw, program_name_raw | 014_business_intelligence_layer.sql | 0/0 |
| `adoption_fts_config` | 1 | k, v | - | 0/0 |
| `adoption_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `adoption_fts_data` | 2 | id, block | - | 0/0 |
| `adoption_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `adoption_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `am_alias_fts` | 335,605 | alias, alias_kind, canonical_id | - | 0/0 |
| `am_alias_fts_config` | 1 | k, v | - | 0/0 |
| `am_alias_fts_data` | 4,284 | id, block | - | 0/0 |
| `am_alias_fts_docsize` | 335,605 | id, sz | - | 0/0 |
| `am_alias_fts_idx` | 3,868 | segid, term, pgno | - | 0/0 |
| `am_entities_fts` | 402,600 | canonical_id, record_kind, primary_name, raw_json | - | 1/0 |
| `am_entities_fts_config` | 1 | k, v | - | 0/0 |
| `am_entities_fts_content` | 402,600 | id, c0, c1, c2, c3 | - | 0/0 |
| `am_entities_fts_data` | 267,855 | id, block | - | 0/0 |
| `am_entities_fts_docsize` | 402,600 | id, sz | - | 0/0 |
| `am_entities_fts_idx` | 28,574 | segid, term, pgno | - | 0/0 |
| `am_program_narrative_fts` | **[empty]** | body_text, narrative_id | wave24_136_am_program_narrative.sql | 0/0 |
| `am_program_narrative_fts_config` | 1 | k, v | - | 0/0 |
| `am_program_narrative_fts_content` | **[empty]** | id, c0, c1 | - | 0/0 |
| `am_program_narrative_fts_data` | 2 | id, block | - | 0/0 |
| `am_program_narrative_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `am_program_narrative_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `bids_fts` | **[empty]** | unified_id, bid_title, bid_description, procuring_entity, winner_name | 017_bids.sql | 0/0 |
| `bids_fts_config` | 1 | k, v | - | 0/0 |
| `bids_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `bids_fts_data` | 2 | id, block | - | 0/0 |
| `bids_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `bids_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `case_studies_fts` | **[empty]** | case_id, company_name, case_title, case_summary, source_excerpt | 057_case_studies_fts.sql | 0/0 |
| `case_studies_fts_config` | 1 | k, v | - | 0/0 |
| `case_studies_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `case_studies_fts_data` | 2 | id, block | - | 0/0 |
| `case_studies_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `case_studies_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `court_decisions_fts` | **[empty]** | unified_id, case_name, subject_area, key_ruling, impact_on_business | 016_court_decisions.sql | 0/0 |
| `court_decisions_fts_config` | 1 | k, v | - | 0/0 |
| `court_decisions_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `court_decisions_fts_data` | 2 | id, block | - | 0/0 |
| `court_decisions_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `court_decisions_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `houjin_master_fts` | **[empty]** | houjin_bangou, normalized_name, alternative_names, address | 014_business_intelligence_layer.sql | 0/0 |
| `houjin_master_fts_config` | 1 | k, v | - | 0/0 |
| `houjin_master_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `houjin_master_fts_data` | 2 | id, block | - | 0/0 |
| `houjin_master_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `houjin_master_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `laws_fts` | **[empty]** | unified_id, law_title, law_short_title, law_number, summary | 015_laws.sql | 0/0 |
| `laws_fts_config` | 1 | k, v | - | 0/0 |
| `laws_fts_content` | **[empty]** | id, c0, c1, c2, c3 (+1) | - | 0/0 |
| `laws_fts_data` | 2 | id, block | - | 0/0 |
| `laws_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `laws_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `ministry_faq_fts` | **[empty]** | faq_id, question, answer, category | 014_business_intelligence_layer.sql | 0/0 |
| `ministry_faq_fts_config` | 1 | k, v | - | 0/0 |
| `ministry_faq_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `ministry_faq_fts_data` | 2 | id, block | - | 0/0 |
| `ministry_faq_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `ministry_faq_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `nta_bunsho_kaitou_fts` | 278 | request_summary, answer | 103_nta_corpus.sql | 1/0 |
| `nta_bunsho_kaitou_fts_config` | 1 | k, v | - | 0/0 |
| `nta_bunsho_kaitou_fts_data` | 277 | id, block | - | 0/0 |
| `nta_bunsho_kaitou_fts_docsize` | 278 | id, sz | - | 0/0 |
| `nta_bunsho_kaitou_fts_idx` | 274 | segid, term, pgno | - | 0/0 |
| `nta_saiketsu_fts` | 137 | title, decision_summary, fulltext | 103_nta_corpus.sql | 1/0 |
| `nta_saiketsu_fts_config` | 1 | k, v | - | 0/0 |
| `nta_saiketsu_fts_data` | 1,923 | id, block | - | 0/0 |
| `nta_saiketsu_fts_docsize` | 137 | id, sz | - | 0/0 |
| `nta_saiketsu_fts_idx` | 1,913 | segid, term, pgno | - | 0/0 |
| `nta_shitsugi_fts` | 286 | question, answer, related_law | 103_nta_corpus.sql | 1/0 |
| `nta_shitsugi_fts_config` | 1 | k, v | - | 0/0 |
| `nta_shitsugi_fts_data` | 266 | id, block | - | 0/0 |
| `nta_shitsugi_fts_docsize` | 286 | id, sz | - | 0/0 |
| `nta_shitsugi_fts_idx` | 409 | segid, term, pgno | - | 0/0 |
| `programs_fts` | **[empty]** | unified_id, primary_name, aliases, enriched_text | - | 0/0 |
| `programs_fts_config` | 1 | k, v | - | 0/0 |
| `programs_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `programs_fts_data` | 2 | id, block | - | 0/0 |
| `programs_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `programs_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `support_org_fts` | **[empty]** | org_id, org_name, services, specialties | 014_business_intelligence_layer.sql | 0/0 |
| `support_org_fts_config` | 1 | k, v | - | 0/0 |
| `support_org_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `support_org_fts_data` | 2 | id, block | - | 0/0 |
| `support_org_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `support_org_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `tax_rulesets_fts` | **[empty]** | unified_id, ruleset_name, eligibility_conditions, calculation_formula | 018_tax_rulesets.sql | 0/0 |
| `tax_rulesets_fts_config` | 1 | k, v | - | 0/0 |
| `tax_rulesets_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `tax_rulesets_fts_data` | 2 | id, block | - | 0/0 |
| `tax_rulesets_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `tax_rulesets_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |
| `verticals_deep_fts` | **[empty]** | vertical_id, vertical_label, record_title, record_summary | 014_business_intelligence_layer.sql | 0/0 |
| `verticals_deep_fts_config` | 1 | k, v | - | 0/0 |
| `verticals_deep_fts_content` | **[empty]** | id, c0, c1, c2, c3 | - | 0/0 |
| `verticals_deep_fts_data` | 2 | id, block | - | 0/0 |
| `verticals_deep_fts_docsize` | **[empty]** | id, sz | - | 0/0 |
| `verticals_deep_fts_idx` | **[empty]** | segid, term, pgno | - | 0/0 |

### 2.12. Views — 13 views

| View | Rows | Migration |
|---|---:|---|
| `am_entities_extended` | 503,930 | - |
| `am_entities_fts_compat` | 402,600 | - |
| `am_uncertainty_view` | 6,124,990 | 069_uncertainty_view.sql |
| `am_unified_rule` | 44,398 | 064_unified_rule_view.sql |
| `case_law_v2` | **[empty]** | 016_court_decisions.sql |
| `programs_active_at_v2` | 5,955 | 070_programs_active_at_v2.sql |
| `v_am_program_required_predicates` | **[empty]** | wave24_137_am_program_eligibility_predicate.sql |
| `v_am_relation_all` | 378,541 | - |
| `v_dd_question_template_summary` | 7 | 104_wave22_dd_question_templates.sql |
| `v_houjin_360` | 166,765 | - |
| `v_houjin_appearances` | 172,386 | wave24_153_am_entity_appearance_count.sql |
| `v_program_complete` | 8,203 | - |
| `v_program_full` | 13,578 | - |

### 2.13. Special: `vec0` virtual tables (sqlite-vec)

These are extension-backed virtual tables that error on `SELECT COUNT(*)` when sqlite-vec is not loaded. Row count inferred from the `_rowids` shadow table.

| Virtual table | Rowids | Underlying tier | Migration |
|---|---:|---|---|
| `am_entities_vec` | 424,277 | all entities, single space | - |
| `am_entities_vec_A` | 201,845 | Authority space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_C` | 2,286 | Case study space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_J` | 2,065 | Judicial / court space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_K` | 137 | Knowledge / FAQ space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_L` | 7,360 | Law space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_S` | 11,601 | Subsidy/program space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_T` | 1,984 | Tax-rule space | 147_am_entities_vec_tables.sql |
| `am_entities_vec_l2v2` | 215,233 | L2-normalised v2 embeddings | - |
| `am_vec_tier_a` | 424,277 | Tier-A canonical | - |
| `am_vec_tier_b_dealbreakers` | 0 | Tier-B dealbreakers | - |
| `am_vec_tier_b_eligibility` | 0 | Tier-B eligibility | - |
| `am_vec_tier_b_exclusions` | 0 | Tier-B exclusions | - |
| `am_vec_tier_b_obligations` | 0 | Tier-B obligations | - |

Plus shadow tables (38 total: `_chunks`, `_info`, `_rowids`, `_vector_chunks00`, `_map`):

<details><summary>Full vec shadow-table list</summary>

| Shadow table | Rows |
|---|---:|
| `am_entities_vec_A_chunks` | 198 |
| `am_entities_vec_A_info` | 4 |
| `am_entities_vec_A_rowids` | 201,845 |
| `am_entities_vec_A_vector_chunks00` | 198 |
| `am_entities_vec_C_chunks` | 3 |
| `am_entities_vec_C_info` | 4 |
| `am_entities_vec_C_rowids` | 2,286 |
| `am_entities_vec_C_vector_chunks00` | 3 |
| `am_entities_vec_J_chunks` | 3 |
| `am_entities_vec_J_info` | 4 |
| `am_entities_vec_J_rowids` | 2,065 |
| `am_entities_vec_J_vector_chunks00` | 3 |
| `am_entities_vec_K_chunks` | 1 |
| `am_entities_vec_K_info` | 4 |
| `am_entities_vec_K_rowids` | 137 |
| `am_entities_vec_K_vector_chunks00` | 1 |
| `am_entities_vec_L_chunks` | 8 |
| `am_entities_vec_L_info` | 4 |
| `am_entities_vec_L_rowids` | 7,360 |
| `am_entities_vec_L_vector_chunks00` | 8 |
| `am_entities_vec_S_chunks` | 12 |
| `am_entities_vec_S_info` | 4 |
| `am_entities_vec_S_rowids` | 11,601 |
| `am_entities_vec_S_vector_chunks00` | 12 |
| `am_entities_vec_T_chunks` | 2 |
| `am_entities_vec_T_info` | 4 |
| `am_entities_vec_T_rowids` | 1,984 |
| `am_entities_vec_T_vector_chunks00` | 2 |
| `am_entities_vec_chunks` | 415 |
| `am_entities_vec_info` | 4 |
| `am_entities_vec_l2v2_chunks` | 211 |
| `am_entities_vec_l2v2_info` | 4 |
| `am_entities_vec_l2v2_map` | 215,233 |
| `am_entities_vec_l2v2_rowids` | 215,233 |
| `am_entities_vec_l2v2_vector_chunks00` | 211 |
| `am_entities_vec_rowids` | 424,277 |
| `am_entities_vec_vector_chunks00` | 415 |
| `am_vec_rowid_map` | 424,277 |

</details>

---

## Notes

- Tables marked **[empty]** have 0 rows at snapshot time; many are precompute (`pc_*`) sinks awaiting the next batch refresh.
- Vec0 virtual tables show `ERR_VEC0` on `COUNT(*)` because the `sqlite-vec` extension is not loaded into stock `sqlite3`. The `_rowids` shadow gives the embedded vector count.
- `jpi_*` tables in autonomath.db are post-Wave-18 read-only mirror snapshots written by migration 110 (cross-pollution split).
- Wave grouping is heuristic — based on migration number ranges (24=foundation, 25-50=BI/health/RE, 51-70=audit, 71-90=auth/treaty, 91-110=NTA/integration, 111-130=W21-22, 131-165=W23, wave24_*=W24).
- Read-only run; no rows mutated.
