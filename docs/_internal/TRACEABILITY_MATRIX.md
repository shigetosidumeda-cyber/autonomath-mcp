# jpcite Traceability Matrix (REST <-> MCP <-> DB)

Generated 2026-05-05. Read-only audit (no migration / source mutation).

Sources: `docs/openapi/v1.json` (174 paths), MCP `tools/list` (100 active at default gates), `scripts/migrations/*.sql` (171 CREATE TABLE).

Coverage method: AST scan of decorator-bound function body + 1-hop in-file helpers + 1-hop import-transitive table refs (whole-file SQL fallback). Wave24 routes annotated `delegates_to_tool`. Section B includes 45 gated-off / unmounted tool definitions for completeness; `active=Y` flags membership in the runtime 100.

## Summary

- REST endpoints (in openapi v1): **165**
- MCP tools (active at default gates): **100** of 145 defined
- Tables (CREATE TABLE in non-rollback migrations): **171**
- Orphan tables (no REST/MCP code path): **86** (50%)
- REST auth distribution: {'anon': 105, 'anon-limited': 53, 'paid': 7}

## Section A. REST endpoint -> tables (R/W)

Auth: `paid` = `current_me` / `require_metered_api_key` (API key required); `apikey` = `require_key` only; `admin` = `require_admin`; `anon-limited` = router-level `AnonIpLimitDep` (3 req/day IP); `anon` = no gate.

| auth | endpoint | router file | tables |
| --- | --- | --- | --- |
| anon | `/healthz` | `src/jpintel_mcp/api/meta.py` | R: anon_rate_limit, audit_seals / W: anon_rate_limit, empty_search_log |
| anon | `/readyz` | `src/jpintel_mcp/api/main.py` | R: advisor_referrals, advisors, alert_subscriptions, am_5hop_graph, am_amendment_diff, am_entity_density_score, am_funding_stack_empirical, am_idempotency_cache, analytics_events, anon_rate_limit, audit_log_section52, audit_seals, bids, case_studies, client_profiles, compliance_subscribers, correction_log, correction_submissions, course_subscriptions, court_decisions, cron_runs, customer_watches, customer_webhooks, device_codes, email_schedule, enforcement_cases, feedback, funnel_events, integration_sync_log, invoice_registrants, laws, line_message_log, line_users, loan_programs, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, program_law_refs, saved_searches, stripe_tax_cache, stripe_webhook_events, tax_rulesets, testimonials, trial_signups, webhook_deliveries, widget_keys / W: advisor_referrals, advisors, alert_subscriptions, am_idempotency_cache, anon_rate_limit, appi_deletion_requests, appi_disclosure_requests, bg_task_queue, citation_verification, client_profiles, compliance_subscribers, correction_submissions, course_subscriptions, customer_watches, customer_webhooks, device_codes, feedback, funnel_events, integration_sync_log, line_users, postmark_webhook_events, refund_requests, saved_searches, stripe_tax_cache, stripe_webhook_events, subscribers, testimonials, trial_signups, widget_keys |
| anon | `/v1/advisors/match` | `src/jpintel_mcp/api/advisors.py` | R: advisors |
| anon | `/v1/advisors/report-conversion` | `src/jpintel_mcp/api/advisors.py` | R: advisor_referrals, advisors / W: advisor_referrals, advisors |
| anon | `/v1/advisors/signup` | `src/jpintel_mcp/api/advisors.py` | R: advisors / W: advisors |
| anon | `/v1/advisors/track` | `src/jpintel_mcp/api/advisors.py` | R: advisors / W: advisor_referrals |
| anon | `/v1/advisors/verify-houjin/{advisor_id}` | `src/jpintel_mcp/api/advisors.py` | R: advisors, invoice_registrants / W: advisors |
| anon | `/v1/advisors/{advisor_id}/dashboard-data` | `src/jpintel_mcp/api/advisors.py` | R: advisor_referrals, advisors |
| anon | `/v1/am/acceptance_stats` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/active_at` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/annotations/{entity_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon-limited | `/v1/am/audit-log` | `src/jpintel_mcp/api/audit_log.py` | R: am_amendment_diff |
| anon | `/v1/am/by_law` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/certifications` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/data-freshness` | `src/jpintel_mcp/api/transparency.py` | (no direct table refs) |
| anon | `/v1/am/dd_batch` | `src/jpintel_mcp/api/ma_dd.py` | R: am_amendment_diff, bids, enforcement_cases, invoice_registrants |
| anon | `/v1/am/dd_export` | `src/jpintel_mcp/api/ma_dd.py` | R: am_amendment_diff, bids, enforcement_cases, invoice_registrants |
| anon | `/v1/am/enforcement` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/enums/{enum_name}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/example_profiles` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/example_profiles/{profile_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/group_graph` | `src/jpintel_mcp/api/ma_dd.py` | R: am_amendment_diff, audit_seals / W: empty_search_log |
| anon | `/v1/am/gx_programs` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/health/deep` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/law_article` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/loans` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/mutual_plans` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/open_programs` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/pack_construction` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/pack_manufacturing` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/pack_real_estate` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/programs/active_v2` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/programs/{program_id}/sources` | `src/jpintel_mcp/api/transparency.py` | (no direct table refs) |
| anon | `/v1/am/provenance/fact/{fact_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/provenance/{entity_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/related/{program_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/static` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/static/{resource_id}` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/tax_incentives` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/tax_rule` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/am/validate` | `src/jpintel_mcp/api/autonomath.py` | R: am_entity_annotation, am_validation_rule, l4_query_cache / W: empty_search_log, l4_query_cache |
| anon-limited | `/v1/audit/batch_evaluate` | `src/jpintel_mcp/api/audit.py` | R: tax_rulesets |
| anon-limited | `/v1/audit/cite_chain/{ruleset_id}` | `src/jpintel_mcp/api/audit.py` | R: tax_rulesets |
| anon-limited | `/v1/audit/seals/{seal_id}` | `src/jpintel_mcp/api/audit.py` | R: am_amendment_diff, am_idempotency_cache, audit_seals, court_decisions, laws, tax_rulesets / W: am_idempotency_cache, empty_search_log |
| anon-limited | `/v1/audit/snapshot_attestation` | `src/jpintel_mcp/api/audit.py` | R: am_amendment_diff |
| anon-limited | `/v1/audit/workpaper` | `src/jpintel_mcp/api/audit.py` | R: tax_rulesets |
| anon-limited | `/v1/bids/search` | `src/jpintel_mcp/api/bids.py` | R: bids |
| anon-limited | `/v1/bids/{unified_id}` | `src/jpintel_mcp/api/bids.py` | R: bids |
| anon | `/v1/billing/checkout` | `src/jpintel_mcp/api/billing.py` | R: device_codes |
| anon | `/v1/billing/client_tag_breakdown` | `src/jpintel_mcp/api/billing_breakdown.py` | W: empty_search_log |
| anon | `/v1/billing/keys/from-checkout` | `src/jpintel_mcp/api/billing.py` | W: bg_task_queue |
| anon | `/v1/billing/portal` | `src/jpintel_mcp/api/billing.py` | R: advisory_locks, bg_task_queue, stripe_tax_cache / W: advisory_locks, audit_log, bg_task_queue, empty_search_log, refund_requests, stripe_tax_cache |
| anon-limited | `/v1/calendar/deadlines` | `src/jpintel_mcp/api/calendar.py` | W: empty_search_log |
| anon-limited | `/v1/calendar/deadlines.ics` | `src/jpintel_mcp/api/calendar.py` | W: empty_search_log |
| anon-limited | `/v1/case-studies/search` | `src/jpintel_mcp/api/case_studies.py` | R: case_studies |
| anon-limited | `/v1/case-studies/{case_id}` | `src/jpintel_mcp/api/case_studies.py` | R: case_studies |
| anon-limited | `/v1/citations/verify` | `src/jpintel_mcp/api/citations.py` | W: citation_verification |
| anon | `/v1/compliance/stripe-checkout` | `src/jpintel_mcp/api/compliance.py` | R: compliance_subscribers |
| anon | `/v1/compliance/subscribe` | `src/jpintel_mcp/api/compliance.py` | R: compliance_subscribers / W: compliance_subscribers |
| anon | `/v1/compliance/unsubscribe/{unsubscribe_token}` | `src/jpintel_mcp/api/compliance.py` | R: compliance_subscribers / W: compliance_subscribers |
| anon | `/v1/compliance/verify/{verification_token}` | `src/jpintel_mcp/api/compliance.py` | R: compliance_subscribers / W: compliance_subscribers |
| anon | `/v1/corrections` | `src/jpintel_mcp/api/trust.py` | R: correction_submissions / W: correction_submissions |
| anon | `/v1/corrections/feed` | `src/jpintel_mcp/api/trust.py` | R: correction_log |
| anon | `/v1/cost/preview` | `src/jpintel_mcp/api/cost.py` | R: am_amendment_diff / W: empty_search_log |
| anon-limited | `/v1/court-decisions/by-statute` | `src/jpintel_mcp/api/court_decisions.py` | R: court_decisions, laws |
| anon-limited | `/v1/court-decisions/search` | `src/jpintel_mcp/api/court_decisions.py` | R: court_decisions |
| anon-limited | `/v1/court-decisions/{unified_id}` | `src/jpintel_mcp/api/court_decisions.py` | R: court_decisions |
| anon | `/v1/cross_source/{entity_id}` | `src/jpintel_mcp/api/trust.py` | (no direct table refs) |
| anon | `/v1/device/authorize` | `src/jpintel_mcp/api/device_flow.py` | W: device_codes |
| anon | `/v1/device/complete` | `src/jpintel_mcp/api/device_flow.py` | R: device_codes / W: device_codes |
| anon | `/v1/device/token` | `src/jpintel_mcp/api/device_flow.py` | R: device_codes / W: device_codes |
| anon-limited | `/v1/discover/related/{entity_id}` | `src/jpintel_mcp/api/discover.py` | R: audit_seals / W: empty_search_log |
| anon | `/v1/email/unsubscribe` | `src/jpintel_mcp/api/email_unsubscribe.py` | W: compliance_subscribers, subscribers |
| anon-limited | `/v1/enforcement-cases/details/search` | `src/jpintel_mcp/api/enforcement.py` | R: am_amendment_diff / W: empty_search_log |
| anon-limited | `/v1/enforcement-cases/search` | `src/jpintel_mcp/api/enforcement.py` | R: enforcement_cases |
| anon-limited | `/v1/enforcement-cases/{case_id}` | `src/jpintel_mcp/api/enforcement.py` | R: enforcement_cases |
| anon-limited | `/v1/evidence/packets/query` | `src/jpintel_mcp/api/evidence.py` | R: am_amendment_diff, audit_seals, citation_verification / W: empty_search_log |
| anon-limited | `/v1/evidence/packets/{subject_kind}/{subject_id}` | `src/jpintel_mcp/api/evidence.py` | R: am_amendment_diff, audit_seals, citation_verification / W: empty_search_log |
| anon-limited | `/v1/exclusions/check` | `src/jpintel_mcp/api/exclusions.py` | W: empty_search_log |
| anon-limited | `/v1/exclusions/rules` | `src/jpintel_mcp/api/exclusions.py` | W: empty_search_log |
| anon | `/v1/feedback` | `src/jpintel_mcp/api/anon_limit.py` | (no direct table refs) |
| anon-limited | `/v1/funding_stack/check` | `src/jpintel_mcp/api/funding_stack.py` | R: audit_seals / W: empty_search_log |
| anon | `/v1/health/data` | `src/jpintel_mcp/api/meta.py` | R: anon_rate_limit, audit_seals / W: anon_rate_limit, empty_search_log |
| anon | `/v1/health/sla` | `src/jpintel_mcp/api/trust.py` | (no direct table refs) |
| anon-limited | `/v1/houjin/{bangou}` | `src/jpintel_mcp/api/houjin.py` | R: audit_seals / W: empty_search_log |
| anon-limited | `/v1/integrations/email/connect` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/excel` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/google` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/google/start` | `src/jpintel_mcp/api/integrations.py` | W: integration_sync_log |
| anon-limited | `/v1/integrations/google/status` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/kintone` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/kintone/connect` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/integrations/kintone/sync` | `src/jpintel_mcp/api/integrations.py` | R: saved_searches / W: integration_sync_log |
| anon-limited | `/v1/integrations/slack` | `src/jpintel_mcp/api/integrations.py` | R: court_decisions, integration_accounts, integration_sync_log, laws, tax_rulesets / W: empty_search_log, integration_accounts, integration_sync_log |
| anon-limited | `/v1/intelligence/precomputed/query` | `src/jpintel_mcp/api/intelligence.py` | R: am_amendment_diff, audit_seals, citation_verification / W: empty_search_log |
| anon-limited | `/v1/invoice_registrants/search` | `src/jpintel_mcp/api/invoice_registrants.py` | R: invoice_registrants |
| anon-limited | `/v1/invoice_registrants/{invoice_registration_number}` | `src/jpintel_mcp/api/invoice_registrants.py` | R: invoice_registrants |
| anon-limited | `/v1/laws/search` | `src/jpintel_mcp/api/laws.py` | R: laws |
| anon-limited | `/v1/laws/{unified_id}` | `src/jpintel_mcp/api/laws.py` | R: laws |
| anon-limited | `/v1/laws/{unified_id}/related-programs` | `src/jpintel_mcp/api/laws.py` | R: laws, program_law_refs |
| anon-limited | `/v1/loan-programs/search` | `src/jpintel_mcp/api/loan_programs.py` | R: loan_programs |
| anon-limited | `/v1/loan-programs/{loan_id}` | `src/jpintel_mcp/api/loan_programs.py` | R: loan_programs |
| paid | `/v1/me` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/me/alerts/subscribe` | `src/jpintel_mcp/api/alerts.py` | R: alert_subscriptions / W: alert_subscriptions |
| anon | `/v1/me/alerts/subscriptions` | `src/jpintel_mcp/api/alerts.py` | R: alert_subscriptions |
| anon | `/v1/me/alerts/subscriptions/{sub_id}` | `src/jpintel_mcp/api/alerts.py` | R: alert_subscriptions / W: alert_subscriptions |
| paid | `/v1/me/billing-portal` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/me/billing_history` | `src/jpintel_mcp/api/dashboard.py` | W: empty_search_log |
| anon | `/v1/me/cap` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/me/client_profiles/bulk_import` | `src/jpintel_mcp/api/client_profiles.py` | R: client_profiles / W: client_profiles |
| anon | `/v1/me/client_profiles/{profile_id}` | `src/jpintel_mcp/api/client_profiles.py` | R: client_profiles / W: client_profiles |
| anon | `/v1/me/clients/bulk_evaluate` | `src/jpintel_mcp/api/bulk_evaluate.py` | R: am_idempotency_cache / W: am_idempotency_cache |
| anon | `/v1/me/courses/{course_slug}` | `src/jpintel_mcp/api/courses.py` | R: course_subscriptions / W: course_subscriptions |
| anon | `/v1/me/dashboard` | `src/jpintel_mcp/api/dashboard.py` | W: empty_search_log |
| paid | `/v1/me/keys/children` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| paid | `/v1/me/keys/children/{child_id}` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/me/recurring/email_course/start` | `src/jpintel_mcp/api/recurring_quarterly.py` | R: course_subscriptions / W: course_subscriptions, empty_search_log |
| anon | `/v1/me/recurring/quarterly/{year}/{quarter}` | `src/jpintel_mcp/api/recurring_quarterly.py` | R: client_profiles |
| anon | `/v1/me/recurring/slack` | `src/jpintel_mcp/api/recurring_quarterly.py` | R: saved_searches / W: saved_searches |
| paid | `/v1/me/rotate-key` | `src/jpintel_mcp/api/me.py` | R: email_schedule / W: alert_subscriptions |
| anon | `/v1/me/saved_searches/{saved_id}` | `src/jpintel_mcp/api/saved_searches.py` | R: saved_searches / W: saved_searches |
| anon | `/v1/me/saved_searches/{saved_id}/results` | `src/jpintel_mcp/api/saved_searches.py` | R: saved_searches |
| anon | `/v1/me/saved_searches/{saved_id}/results.xlsx` | `src/jpintel_mcp/api/saved_searches.py` | R: saved_searches |
| anon | `/v1/me/saved_searches/{saved_id}/sheet` | `src/jpintel_mcp/api/saved_searches.py` | R: saved_searches / W: saved_searches |
| anon | `/v1/me/tool_recommendation` | `src/jpintel_mcp/api/dashboard.py` | W: empty_search_log |
| paid | `/v1/me/usage` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| paid | `/v1/me/usage.csv` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/me/usage_by_tool` | `src/jpintel_mcp/api/dashboard.py` | W: empty_search_log |
| anon | `/v1/me/webhooks/{webhook_id}` | `src/jpintel_mcp/api/customer_webhooks.py` | R: customer_webhooks / W: customer_webhooks |
| anon | `/v1/me/webhooks/{webhook_id}/deliveries` | `src/jpintel_mcp/api/customer_webhooks.py` | R: customer_webhooks, webhook_deliveries |
| anon | `/v1/me/webhooks/{webhook_id}/test` | `src/jpintel_mcp/api/customer_webhooks.py` | R: customer_webhooks |
| anon-limited | `/v1/meta` | `src/jpintel_mcp/api/meta.py` | R: anon_rate_limit, audit_seals / W: anon_rate_limit, empty_search_log |
| anon | `/v1/meta/corpus_snapshot` | `src/jpintel_mcp/api/meta.py` | R: anon_rate_limit, audit_seals / W: anon_rate_limit, empty_search_log |
| anon | `/v1/meta/freshness` | `src/jpintel_mcp/api/meta_freshness.py` | (no direct table refs) |
| anon-limited | `/v1/ping` | `src/jpintel_mcp/api/meta.py` | R: anon_rate_limit, audit_seals / W: anon_rate_limit, empty_search_log |
| anon | `/v1/privacy/deletion_request` | `src/jpintel_mcp/api/appi_deletion.py` | W: appi_deletion_requests |
| anon | `/v1/privacy/disclosure_request` | `src/jpintel_mcp/api/appi_disclosure.py` | W: appi_disclosure_requests |
| anon-limited | `/v1/programs/batch` | `src/jpintel_mcp/api/programs.py` | R: advisor_referrals, advisors, am_amendment_diff, invoice_registrants, l4_query_cache / W: advisor_referrals, advisors, empty_search_log, l4_query_cache |
| anon-limited | `/v1/programs/prescreen` | `src/jpintel_mcp/api/prescreen.py` | W: empty_search_log |
| anon-limited | `/v1/programs/search` | `src/jpintel_mcp/api/programs.py` | R: advisor_referrals, advisors, am_amendment_diff, invoice_registrants, l4_query_cache / W: advisor_referrals, advisors, empty_search_log, l4_query_cache |
| anon-limited | `/v1/programs/{unified_id}` | `src/jpintel_mcp/api/programs.py` | R: advisor_referrals, advisors, am_amendment_diff, invoice_registrants, l4_query_cache / W: advisor_referrals, advisors, empty_search_log, l4_query_cache |
| anon | `/v1/session` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/session/logout` | `src/jpintel_mcp/api/me.py` | R: bg_task_queue / W: audit_log, bg_task_queue, empty_search_log |
| anon | `/v1/signup` | `src/jpintel_mcp/api/signup.py` | R: trial_signups / W: trial_signups |
| anon | `/v1/signup/verify` | `src/jpintel_mcp/api/signup.py` | R: trial_signups / W: trial_signups |
| anon-limited | `/v1/source_manifest/{program_id}` | `src/jpintel_mcp/api/source_manifest.py` | W: empty_search_log |
| anon | `/v1/staleness` | `src/jpintel_mcp/api/trust.py` | (no direct table refs) |
| anon | `/v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code}` | `src/jpintel_mcp/api/stats.py` | R: l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/stats/confidence` | `src/jpintel_mcp/api/confidence.py` | W: empty_search_log |
| anon | `/v1/stats/coverage` | `src/jpintel_mcp/api/stats.py` | R: l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/stats/data_quality` | `src/jpintel_mcp/api/stats.py` | R: l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/stats/freshness` | `src/jpintel_mcp/api/stats.py` | R: l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/stats/usage` | `src/jpintel_mcp/api/stats.py` | R: l4_query_cache / W: empty_search_log, l4_query_cache |
| anon | `/v1/subscribers` | `src/jpintel_mcp/api/anon_limit.py` | (no direct table refs) |
| anon | `/v1/subscribers/unsubscribe` | `src/jpintel_mcp/api/subscribers.py` | W: subscribers |
| anon-limited | `/v1/tax_rulesets/evaluate` | `src/jpintel_mcp/api/tax_rulesets.py` | R: tax_rulesets |
| anon-limited | `/v1/tax_rulesets/search` | `src/jpintel_mcp/api/tax_rulesets.py` | R: tax_rulesets |
| anon-limited | `/v1/tax_rulesets/{unified_id}` | `src/jpintel_mcp/api/tax_rulesets.py` | R: tax_rulesets |
| anon | `/v1/testimonials` | `src/jpintel_mcp/api/anon_limit.py` | (no direct table refs) |
| anon | `/v1/trust/section52` | `src/jpintel_mcp/api/trust.py` | R: audit_log_section52 |
| anon | `/v1/usage` | `src/jpintel_mcp/api/usage.py` | R: anon_rate_limit |
| anon | `/v1/widget/enum_values` | `src/jpintel_mcp/api/widget_auth.py` | W: widget_keys |
| anon | `/v1/widget/search` | `src/jpintel_mcp/api/widget_auth.py` | W: widget_keys |
| anon | `/v1/widget/signup` | `src/jpintel_mcp/api/widget_auth.py` | R: device_codes, stripe_webhook_events / W: bg_task_queue, empty_search_log, stripe_webhook_events |
| anon | `/v1/widget/{key_id}/usage` | `src/jpintel_mcp/api/widget_auth.py` | R: widget_keys |

## Section B. MCP tool -> tables (R/W)

Active = present in `mcp.list_tools()` runtime (100). Gated-off = decorator present but excluded by env-flag (36協定 / healthcare / real_estate / fix-gates).

| active | tool | defining file | tables |
| --- | --- | --- | --- |
| Y | `active_programs_at` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `apply_eligibility_chain_am` | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `audit_batch_evaluate` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| Y | `batch_get_programs` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `bid_eligible_for_profile` | `src/jpintel_mcp/mcp/server.py` | R: bids |
| Y | `bundle_application_kit` | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `check_drug_approval` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `check_enforcement_am` | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `check_exclusions` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| gated | `check_foreign_capital_eligibility` | `src/jpintel_mcp/mcp/autonomath_tools/english_wedge.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `check_funding_stack_am` | `src/jpintel_mcp/mcp/autonomath_tools/funding_stack_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `cite_tsutatsu` | `src/jpintel_mcp/mcp/autonomath_tools/nta_corpus_tools.py` | R: nta_tsutatsu_index |
| Y | `combined_compliance_check` | `src/jpintel_mcp/mcp/server.py` | R: bids, tax_rulesets |
| Y | `compose_audit_workpaper` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| Y | `cross_check_jurisdiction` | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `cross_check_zoning` | `src/jpintel_mcp/mcp/real_estate_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `dd_medical_institution_am` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `dd_profile_am` | `src/jpintel_mcp/mcp/server.py` | R: invoice_registrants |
| gated | `dd_property_am` | `src/jpintel_mcp/mcp/real_estate_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `deadline_calendar` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `deep_health_am` | `src/jpintel_mcp/mcp/autonomath_tools/health_tool.py` | R: am_entity_annotation, am_validation_rule, bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `discover_related` | `src/jpintel_mcp/mcp/autonomath_tools/discover.py` | R: am_5hop_graph, am_entity_density_score, am_funding_stack_empirical, bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `enum_values` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `enum_values_am` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `evaluate_tax_applicability` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| gated | `find_adopted_companies_by_program` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `find_bunsho_kaitou` | `src/jpintel_mcp/mcp/autonomath_tools/nta_corpus_tools.py` | R: nta_bunsho_kaitou |
| Y | `find_cases_by_law` | `src/jpintel_mcp/mcp/server.py` | R: court_decisions, enforcement_cases, enforcement_decision_refs, laws |
| gated | `find_combinable_programs` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_program_combinations |
| Y | `find_complementary_programs_am` | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `find_complementary_subsidies` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_program_calendar_12mo, am_program_combinations |
| gated | `find_emerging_programs` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `find_fdi_friendly_subsidies` | `src/jpintel_mcp/mcp/autonomath_tools/english_wedge.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `find_precedents_by_statute` | `src/jpintel_mcp/mcp/server.py` | R: court_decisions, laws |
| gated | `find_programs_by_jsic` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `find_saiketsu` | `src/jpintel_mcp/mcp/autonomath_tools/nta_corpus_tools.py` | R: nta_saiketsu |
| Y | `find_shitsugi` | `src/jpintel_mcp/mcp/autonomath_tools/nta_corpus_tools.py` | R: nta_shitsugi |
| gated | `find_similar_case_studies` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_case_study_similarity |
| gated | `forecast_enforcement_risk` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_enforcement_industry_risk |
| Y | `forecast_program_renewal` | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_36_kyotei_metadata_am` | `src/jpintel_mcp/mcp/autonomath_tools/template_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_am_tax_rule` | `src/jpintel_mcp/mcp/autonomath_tools/tax_rule_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_annotations` | `src/jpintel_mcp/mcp/autonomath_tools/annotation_tools.py` | R: am_entity_annotation |
| Y | `get_bid` | `src/jpintel_mcp/mcp/server.py` | R: bids |
| Y | `get_case_study` | `src/jpintel_mcp/mcp/server.py` | R: case_studies |
| gated | `get_compliance_risk_score` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_houjin_360_snapshot |
| Y | `get_court_decision` | `src/jpintel_mcp/mcp/server.py` | R: court_decisions |
| Y | `get_enforcement_case` | `src/jpintel_mcp/mcp/server.py` | R: enforcement_cases |
| Y | `get_evidence_packet` | `src/jpintel_mcp/mcp/autonomath_tools/evidence_packet_tools.py` | R: am_amendment_diff, bids, case_studies, citation_verification, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_evidence_packet_batch` | `src/jpintel_mcp/mcp/autonomath_tools/evidence_batch.py` | R: am_amendment_diff, bids, case_studies, citation_verification, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_example_profile_am` | `src/jpintel_mcp/mcp/autonomath_tools/static_resources_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_houjin_360_am` | `src/jpintel_mcp/mcp/autonomath_tools/corporate_layer_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_houjin_360_snapshot_history` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_houjin_360_snapshot |
| gated | `get_houjin_subsidy_history` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_industry_program_density` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_region_program_density |
| Y | `get_law` | `src/jpintel_mcp/mcp/server.py` | R: laws |
| Y | `get_law_article_am` | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_law_article_en` | `src/jpintel_mcp/mcp/autonomath_tools/english_wedge.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_loan_program` | `src/jpintel_mcp/mcp/server.py` | R: loan_programs |
| gated | `get_medical_institution` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: medical_institutions |
| Y | `get_meta` | `src/jpintel_mcp/mcp/server.py` | R: case_studies, enforcement_cases, loan_programs |
| Y | `get_program` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| gated | `get_program_adoption_stats` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_program_adoption_stats |
| gated | `get_program_application_documents` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_program_documents |
| gated | `get_program_calendar_12mo` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_program_calendar_12mo |
| gated | `get_program_keyword_analysis` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_program_narrative |
| gated | `get_program_narrative` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_program_narrative, am_program_narrative_full |
| gated | `get_program_renewal_probability` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_amendment_diff |
| Y | `get_provenance` | `src/jpintel_mcp/mcp/autonomath_tools/provenance_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_provenance_for_fact` | `src/jpintel_mcp/mcp/autonomath_tools/provenance_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_source_manifest` | `src/jpintel_mcp/mcp/autonomath_tools/source_manifest_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `get_static_resource_am` | `src/jpintel_mcp/mcp/autonomath_tools/static_resources_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `get_tax_amendment_cycle` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_tax_amendment_history |
| Y | `get_tax_rule` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| gated | `get_tax_treaty` | `src/jpintel_mcp/mcp/autonomath_tools/english_wedge.py` | R: am_tax_treaty |
| Y | `get_usage_status` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| gated | `get_zoning_overlay` | `src/jpintel_mcp/mcp/real_estate_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `graph_traverse` | `src/jpintel_mcp/mcp/autonomath_tools/graph_traverse_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `infer_invoice_buyer_seller` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_invoice_buyer_seller_graph |
| gated | `intent_of` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `list_edinet_disclosures` | `src/jpintel_mcp/mcp/autonomath_tools/corporate_layer_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `list_example_profiles_am` | `src/jpintel_mcp/mcp/autonomath_tools/static_resources_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `list_exclusion_rules` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `list_law_revisions` | `src/jpintel_mcp/mcp/server.py` | R: laws |
| Y | `list_open_programs` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `list_static_resources_am` | `src/jpintel_mcp/mcp/autonomath_tools/static_resources_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `list_tax_sunset_alerts` | `src/jpintel_mcp/mcp/autonomath_tools/sunset_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `match_due_diligence_questions` | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | R: dd_question_templates |
| gated | `match_programs_by_capital` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_capital_band_program_match |
| Y | `pack_construction` | `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `pack_manufacturing` | `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `pack_real_estate` | `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `predict_rd_tax_credit` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_houjin_360_snapshot, am_tax_amendment_history |
| Y | `prepare_kessan_briefing` | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | R: am_amendment_diff, saved_searches |
| Y | `prerequisite_chain` | `src/jpintel_mcp/mcp/autonomath_tools/prerequisite_chain_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `prescreen_programs` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `program_abstract_structured` | `src/jpintel_mcp/mcp/autonomath_tools/multilingual_abstract_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `program_active_periods_am` | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `program_lifecycle` | `src/jpintel_mcp/mcp/autonomath_tools/lifecycle_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `reason_answer` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `recommend_programs_for_houjin` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` | R: am_recommended_programs |
| Y | `recommend_similar_case` | `src/jpintel_mcp/mcp/autonomath_tools/recommend_similar.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `recommend_similar_court_decision` | `src/jpintel_mcp/mcp/autonomath_tools/recommend_similar.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `recommend_similar_program` | `src/jpintel_mcp/mcp/autonomath_tools/recommend_similar.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `regulatory_prep_pack` | `src/jpintel_mcp/mcp/server.py` | R: enforcement_cases, laws, tax_rulesets |
| Y | `related_programs` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `render_36_kyotei_am` | `src/jpintel_mcp/mcp/autonomath_tools/template_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `resolve_citation_chain` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| Y | `rule_engine_check` | `src/jpintel_mcp/mcp/autonomath_tools/rule_engine_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `score_application_probability` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_capital_band_program_match, am_program_adoption_stats, am_recommended_programs |
| Y | `search_acceptance_stats_am` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_bids` | `src/jpintel_mcp/mcp/server.py` | R: bids |
| Y | `search_by_law` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `search_care_subsidies` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: care_subsidies |
| Y | `search_case_studies` | `src/jpintel_mcp/mcp/server.py` | R: case_studies |
| Y | `search_certifications` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_court_decisions` | `src/jpintel_mcp/mcp/server.py` | R: court_decisions |
| Y | `search_enforcement_cases` | `src/jpintel_mcp/mcp/server.py` | R: enforcement_cases |
| Y | `search_gx_programs_am` | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `search_healthcare_compliance` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: medical_institutions |
| gated | `search_healthcare_programs` | `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_invoice_by_houjin_partial` | `src/jpintel_mcp/mcp/autonomath_tools/corporate_layer_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_invoice_registrants` | `src/jpintel_mcp/mcp/server.py` | R: invoice_registrants |
| Y | `search_laws` | `src/jpintel_mcp/mcp/server.py` | R: laws |
| gated | `search_laws_en` | `src/jpintel_mcp/mcp/autonomath_tools/english_wedge.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_loan_programs` | `src/jpintel_mcp/mcp/server.py` | R: loan_programs |
| Y | `search_loans_am` | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_mutual_plans_am` | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, jpi_pc_program_health, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_programs` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| gated | `search_real_estate_compliance` | `src/jpintel_mcp/mcp/real_estate_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `search_real_estate_programs` | `src/jpintel_mcp/mcp/real_estate_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_tax_incentives` | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `search_tax_rules` | `src/jpintel_mcp/mcp/server.py` | R: tax_rulesets |
| Y | `similar_cases` | `src/jpintel_mcp/mcp/server.py` | R: case_studies |
| Y | `simulate_application_am` | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| gated | `simulate_tax_change_impact` | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` | R: am_houjin_360_snapshot, am_tax_amendment_history |
| Y | `smb_starter_pack` | `src/jpintel_mcp/mcp/server.py` | R: enforcement_cases, loan_programs, tax_rulesets |
| Y | `subsidy_combo_finder` | `src/jpintel_mcp/mcp/server.py` | R: loan_programs, tax_rulesets |
| Y | `subsidy_roadmap_3yr` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `trace_program_to_law` | `src/jpintel_mcp/mcp/server.py` | R: laws, program_law_refs |
| Y | `track_amendment_lineage_am` | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `unified_lifecycle_calendar` | `src/jpintel_mcp/mcp/autonomath_tools/lifecycle_calendar_tool.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `upcoming_deadlines` | `src/jpintel_mcp/mcp/server.py` | R: am_amendment_diff, audit_seals, court_decisions, jpi_pc_program_health, laws, nta_bunsho_kaitou, nta_shitsugi, nta_tsutatsu_index, tax_rulesets / W: empty_search_log |
| Y | `validate` | `src/jpintel_mcp/mcp/autonomath_tools/validation_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |
| Y | `verify_citations` | `src/jpintel_mcp/mcp/autonomath_tools/citations_tools.py` | R: bids, case_studies, court_decisions, enforcement_cases, enforcement_decision_refs, invoice_registrants, laws, loan_programs, program_law_refs, tax_rulesets |

## Section C. Table -> endpoints + tools (reverse index)

Each row = table | first migration | endpoint consumers (`[R|W] path`) | tool consumers (`[R|W] tool`).

| table | first migration | REST consumers | MCP tool consumers |
| --- | --- | --- | --- |
| `adoption_records` | `014_business_intelligence_layer.sql` | - | - |
| `advisor_referrals` | `024_advisors.sql` | [R] `/readyz`<br>[R] `/v1/advisors/report-conversion`<br>[R] `/v1/advisors/{advisor_id}/dashboard-data`<br>[R] `/v1/programs/batch`<br>[R] `/v1/programs/search`<br>[R] `/v1/programs/{unified_id}`<br>[W] `/readyz`<br>[W] `/v1/advisors/report-conversion`<br>[W] `/v1/advisors/track`<br>[W] `/v1/programs/batch`<br>[W] `/v1/programs/search`<br>[W] `/v1/programs/{unified_id}` | - |
| `advisors` | `024_advisors.sql` | [R] `/readyz`<br>[R] `/v1/advisors/match`<br>[R] `/v1/advisors/report-conversion`<br>[R] `/v1/advisors/signup`<br>[R] `/v1/advisors/track`<br>[R] `/v1/advisors/verify-houjin/{advisor_id}`<br>[R] `/v1/advisors/{advisor_id}/dashboard-data`<br>[R] `/v1/programs/batch`<br>[R] `/v1/programs/search`<br>[R] `/v1/programs/{unified_id}`<br>[W] `/readyz`<br>[W] `/v1/advisors/report-conversion`<br>[W] `/v1/advisors/signup`<br>[W] `/v1/advisors/stripe-connect-webhook`<br>[W] `/v1/advisors/verify-houjin/{advisor_id}`<br>[W] `/v1/programs/batch`<br>[W] `/v1/programs/search`<br>[W] `/v1/programs/{unified_id}` | - |
| `advisory_locks` | `063_advisory_locks.sql` | [R] `/v1/billing/portal`<br>[W] `/v1/billing/portal` | - |
| `alert_subscriptions` | `038_alert_subscriptions.sql` | [R] `/readyz`<br>[R] `/v1/me/alerts/subscribe`<br>[R] `/v1/me/alerts/subscriptions`<br>[R] `/v1/me/alerts/subscriptions/{sub_id}`<br>[W] `/readyz`<br>[W] `/v1/me/alerts/subscribe`<br>[W] `/v1/me/alerts/subscriptions/{sub_id}`<br>[W] `/v1/me/rotate-key` | - |
| `alias_candidates_queue` | `112_alias_candidates_queue.sql` | - | - |
| `am_5hop_graph` | `wave24_152_am_5hop_graph.sql` | [R] `/readyz` | [R] `discover_related` |
| `am_adopted_company_features` | `wave24_157_am_adopted_company_features.sql` | - | - |
| `am_adoption_trend_monthly` | `160_am_adoption_trend_monthly.sql` | - | - |
| `am_amendment_diff` | `075_am_amendment_diff.sql` | [R] `/readyz`<br>[R] `/v1/am/audit-log`<br>[R] `/v1/am/dd_batch`<br>[R] `/v1/am/dd_export`<br>[R] `/v1/am/group_graph`<br>[R] `/v1/am/programs/{program_id}/renewal_change_forecast`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/audit/snapshot_attestation`<br>[R] `/v1/cost/preview`<br>[R] `/v1/enforcement-cases/details/search`<br>[R] `/v1/evidence/packets/batch`<br>[R] `/v1/evidence/packets/query`<br>[R] `/v1/evidence/packets/{subject_kind}/{subject_id}`<br>[R] `/v1/intelligence/precomputed/query`<br>[R] `/v1/programs/batch`<br>[R] `/v1/programs/search`<br>[R] `/v1/programs/{unified_id}` | [R] `batch_get_programs`<br>[R] `check_exclusions`<br>[R] `deadline_calendar`<br>[R] `enum_values`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_program`<br>[R] `get_program_renewal_probability`<br>[R] `get_usage_status`<br>[R] `list_exclusion_rules`<br>[R] `prepare_kessan_briefing`<br>[R] `prescreen_programs`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `am_annotation_kind` | `046_annotation_layer.sql` | - | - |
| `am_capital_band_program_match` | `wave24_134_am_capital_band_program_match.sql` | [R] `/v1/am/match/capital`<br>[R] `/v1/am/programs/{program_id}/houjin/{houjin_bangou}/similarity_score` | [R] `match_programs_by_capital`<br>[R] `score_application_probability` |
| `am_case_study_narrative` | `wave24_141_am_narrative_quarantine.sql` | - | - |
| `am_case_study_similarity` | `wave24_130_am_case_study_similarity.sql` | [R] `/v1/am/case_studies/similar/{case_id}` | [R] `find_similar_case_studies` |
| `am_citation_network` | `wave24_163_am_citation_network.sql` | - | - |
| `am_credit_pack_purchase` | `wave24_148_am_credit_pack_purchase.sql` | - | - |
| `am_data_quality_snapshot` | `wave24_145_am_data_quality_snapshot.sql` | - | - |
| `am_enforcement_anomaly` | `161_am_enforcement_anomaly.sql` | - | - |
| `am_enforcement_industry_risk` | `wave24_129_am_enforcement_industry_risk.sql` | [R] `/v1/am/enforcement_risk` | [R] `forecast_enforcement_risk` |
| `am_enforcement_summary` | `wave24_141_am_narrative_quarantine.sql` | - | - |
| `am_entities_vec_v2_metadata` | `wave24_110_am_entities_vec_v2.sql` | - | - |
| `am_entity_annotation` | `046_annotation_layer.sql` | [R] `/v1/am/acceptance_stats`<br>[R] `/v1/am/active_at`<br>[R] `/v1/am/annotations/{entity_id}`<br>[R] `/v1/am/by_law`<br>[R] `/v1/am/certifications`<br>[R] `/v1/am/enforcement`<br>[R] `/v1/am/enums/{enum_name}`<br>[R] `/v1/am/example_profiles`<br>[R] `/v1/am/example_profiles/{profile_id}`<br>[R] `/v1/am/gx_programs`<br>[R] `/v1/am/health/deep`<br>[R] `/v1/am/intent`<br>[R] `/v1/am/law_article`<br>[R] `/v1/am/loans`<br>[R] `/v1/am/mutual_plans`<br>[R] `/v1/am/open_programs`<br>[R] `/v1/am/pack_construction`<br>[R] `/v1/am/pack_manufacturing`<br>[R] `/v1/am/pack_real_estate`<br>[R] `/v1/am/programs/active_v2`<br>[R] `/v1/am/provenance/fact/{fact_id}`<br>[R] `/v1/am/provenance/{entity_id}`<br>[R] `/v1/am/reason`<br>[R] `/v1/am/related/{program_id}`<br>[R] `/v1/am/static`<br>[R] `/v1/am/static/{resource_id}`<br>[R] `/v1/am/tax_incentives`<br>[R] `/v1/am/tax_rule`<br>[R] `/v1/am/templates/saburoku_kyotei`<br>[R] `/v1/am/templates/saburoku_kyotei/metadata`<br>[R] `/v1/am/validate` | [R] `deep_health_am`<br>[R] `get_annotations` |
| `am_entity_appearance_count` | `wave24_153_am_entity_appearance_count.sql` | - | - |
| `am_entity_density_score` | `158_am_entity_density_score.sql` | [R] `/readyz` | [R] `discover_related` |
| `am_entity_monthly_snapshot` | `wave24_111_am_entity_monthly_snapshot.sql` | - | - |
| `am_entity_pagerank` | `162_am_entity_pagerank.sql` | - | - |
| `am_funding_stack_empirical` | `156_am_funding_stack_empirical.sql` | [R] `/readyz` | [R] `discover_related` |
| `am_geo_industry_density` | `155_am_geo_industry_density.sql` | - | - |
| `am_houjin_360_narrative` | `wave24_141_am_narrative_quarantine.sql` | - | - |
| `am_houjin_360_snapshot` | `wave24_131_am_houjin_360_snapshot.sql` | [R] `/v1/am/houjin/{houjin_bangou}/compliance_risk`<br>[R] `/v1/am/houjin/{houjin_bangou}/rd_tax_credit`<br>[R] `/v1/am/houjin/{houjin_bangou}/tax_change_impact` | [R] `get_compliance_risk_score`<br>[R] `get_houjin_360_snapshot_history`<br>[R] `predict_rd_tax_credit`<br>[R] `simulate_tax_change_impact` |
| `am_id_bridge` | `159_am_id_bridge.sql` | - | - |
| `am_idempotency_cache` | `087_idempotency_cache.sql` | [R] `/readyz`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/me/clients/bulk_evaluate`<br>[W] `/readyz`<br>[W] `/v1/audit/seals/{seal_id}`<br>[W] `/v1/me/clients/bulk_evaluate` | - |
| `am_invoice_buyer_seller_graph` | `wave24_133_am_invoice_buyer_seller_graph.sql` | [R] `/v1/am/houjin/{houjin_bangou}/invoice_graph` | [R] `infer_invoice_buyer_seller` |
| `am_law_article_summary` | `wave24_141_am_narrative_quarantine.sql` | - | - |
| `am_narrative_customer_reports` | `wave24_142_am_narrative_customer_reports.sql` | [R] `/v1/narrative/{narrative_id}/report`<br>[W] `/v1/narrative/{narrative_id}/report` | - |
| `am_narrative_extracted_entities` | `wave24_140_am_narrative_extracted_entities.sql` | - | - |
| `am_narrative_quarantine` | `wave24_141_am_narrative_quarantine.sql` | [W] `/v1/narrative/{narrative_id}/report` | - |
| `am_narrative_serve_log` | `wave24_142_am_narrative_customer_reports.sql` | - | - |
| `am_program_adoption_stats` | `wave24_135_am_program_adoption_stats.sql` | [R] `/v1/am/programs/{program_id}/adoption_stats`<br>[R] `/v1/am/programs/{program_id}/houjin/{houjin_bangou}/similarity_score` | [R] `get_program_adoption_stats`<br>[R] `score_application_probability` |
| `am_program_calendar_12mo` | `wave24_128_am_program_calendar_12mo.sql` | [R] `/v1/am/programs/{program_id}/complementary` | [R] `find_complementary_subsidies`<br>[R] `get_program_calendar_12mo` |
| `am_program_combinations` | `wave24_127_am_program_combinations.sql` | [R] `/v1/am/combinations/{program_id}`<br>[R] `/v1/am/programs/{program_id}/complementary` | [R] `find_combinable_programs`<br>[R] `find_complementary_subsidies` |
| `am_program_documents` | `wave24_138_am_program_documents.sql` | [R] `/v1/am/programs/{program_id}/documents` | [R] `get_program_application_documents` |
| `am_program_eligibility_history` | `wave24_106_amendment_snapshot_rebuild.sql` | - | - |
| `am_program_eligibility_predicate` | `wave24_137_am_program_eligibility_predicate.sql` | - | - |
| `am_program_narrative` | `wave24_136_am_program_narrative.sql` | [R] `/v1/am/programs/{program_id}/keywords`<br>[R] `/v1/am/programs/{program_id}/narrative` | [R] `get_program_keyword_analysis`<br>[R] `get_program_narrative` |
| `am_program_narrative_full` | `wave24_149_am_program_narrative_full.sql` | [R] `/v1/am/programs/{program_id}/narrative` | [R] `get_program_narrative` |
| `am_recommended_programs` | `wave24_126_am_recommended_programs.sql` | [R] `/v1/am/programs/{program_id}/houjin/{houjin_bangou}/similarity_score`<br>[R] `/v1/am/recommend` | [R] `recommend_programs_for_houjin`<br>[R] `score_application_probability` |
| `am_region_program_density` | `wave24_112_am_region_extension.sql` | [R] `/v1/am/density/{jsic_major}` | [R] `get_industry_program_density` |
| `am_region_program_density_breakdown` | `wave24_139_am_region_program_density.sql` | - | - |
| `am_tax_amendment_history` | `wave24_132_am_tax_amendment_history.sql` | [R] `/v1/am/houjin/{houjin_bangou}/rd_tax_credit`<br>[R] `/v1/am/houjin/{houjin_bangou}/tax_change_impact`<br>[R] `/v1/am/tax/{tax_ruleset_id}/amendment_cycle` | [R] `get_tax_amendment_cycle`<br>[R] `predict_rd_tax_credit`<br>[R] `simulate_tax_change_impact` |
| `am_tax_treaty` | `091_tax_treaty.sql` | [R] `/v1/en/fdi_subsidies`<br>[R] `/v1/en/foreign_capital_eligibility`<br>[R] `/v1/en/laws/search`<br>[R] `/v1/en/laws/{law_id}/articles/{article_no}`<br>[R] `/v1/en/tax_treaty/{country_a}` | [R] `get_tax_treaty` |
| `am_temporal_correlation` | `154_am_temporal_correlation.sql` | - | - |
| `am_validation_result` | `047_validation_layer.sql` | - | - |
| `am_validation_rule` | `047_validation_layer.sql` | [R] `/v1/am/acceptance_stats`<br>[R] `/v1/am/active_at`<br>[R] `/v1/am/annotations/{entity_id}`<br>[R] `/v1/am/by_law`<br>[R] `/v1/am/certifications`<br>[R] `/v1/am/enforcement`<br>[R] `/v1/am/enums/{enum_name}`<br>[R] `/v1/am/example_profiles`<br>[R] `/v1/am/example_profiles/{profile_id}`<br>[R] `/v1/am/gx_programs`<br>[R] `/v1/am/health/deep`<br>[R] `/v1/am/intent`<br>[R] `/v1/am/law_article`<br>[R] `/v1/am/loans`<br>[R] `/v1/am/mutual_plans`<br>[R] `/v1/am/open_programs`<br>[R] `/v1/am/pack_construction`<br>[R] `/v1/am/pack_manufacturing`<br>[R] `/v1/am/pack_real_estate`<br>[R] `/v1/am/programs/active_v2`<br>[R] `/v1/am/provenance/fact/{fact_id}`<br>[R] `/v1/am/provenance/{entity_id}`<br>[R] `/v1/am/reason`<br>[R] `/v1/am/related/{program_id}`<br>[R] `/v1/am/static`<br>[R] `/v1/am/static/{resource_id}`<br>[R] `/v1/am/tax_incentives`<br>[R] `/v1/am/tax_rule`<br>[R] `/v1/am/templates/saburoku_kyotei`<br>[R] `/v1/am/templates/saburoku_kyotei/metadata`<br>[R] `/v1/am/validate` | [R] `deep_health_am` |
| `analytics_events` | `111_analytics_events.sql` | [R] `/readyz`<br>[R] `/v1/admin/analytics_split`<br>[R] `/v1/admin/kpi` | - |
| `anon_rate_limit` | `007_anon_rate_limit.sql` | [R] `/healthz`<br>[R] `/meta`<br>[R] `/readyz`<br>[R] `/v1/health/data`<br>[R] `/v1/meta`<br>[R] `/v1/meta/corpus_snapshot`<br>[R] `/v1/ping`<br>[R] `/v1/stats/funnel`<br>[R] `/v1/usage`<br>[W] `/healthz`<br>[W] `/meta`<br>[W] `/readyz`<br>[W] `/v1/health/data`<br>[W] `/v1/meta`<br>[W] `/v1/meta/corpus_snapshot`<br>[W] `/v1/ping` | - |
| `api_keys_v2` | `052_api_keys_subscription_status.sql` | - | - |
| `appi_deletion_requests` | `068_appi_deletion_requests.sql` | [W] `/readyz`<br>[W] `/v1/privacy/deletion_request` | - |
| `appi_disclosure_requests` | `066_appi_disclosure_requests.sql` | [W] `/readyz`<br>[W] `/v1/privacy/disclosure_request` | - |
| `audit_log` | `058_audit_log.sql` | [W] `/v1/billing/portal`<br>[W] `/v1/me`<br>[W] `/v1/me/billing-portal`<br>[W] `/v1/me/cap`<br>[W] `/v1/me/keys/children`<br>[W] `/v1/me/keys/children/{child_id}`<br>[W] `/v1/me/usage`<br>[W] `/v1/me/usage.csv`<br>[W] `/v1/session`<br>[W] `/v1/session/logout` | - |
| `audit_log_section52` | `101_trust_infrastructure.sql` | [R] `/readyz`<br>[R] `/v1/trust/section52` | - |
| `audit_merkle_anchor` | `146_audit_merkle_anchor.sql` | [R] `/v1/audit/proof/{evidence_packet_id}` | - |
| `audit_merkle_leaves` | `146_audit_merkle_anchor.sql` | [R] `/v1/audit/proof/{evidence_packet_id}` | - |
| `audit_seal_keys` | `wave24_105_audit_seal_key_version.sql` | - | - |
| `audit_seals` | `089_audit_seal_table.sql` | [R] `/healthz`<br>[R] `/meta`<br>[R] `/readyz`<br>[R] `/v1/am/group_graph`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/discover/related/{entity_id}`<br>[R] `/v1/evidence/packets/batch`<br>[R] `/v1/evidence/packets/query`<br>[R] `/v1/evidence/packets/{subject_kind}/{subject_id}`<br>[R] `/v1/funding_stack/check`<br>[R] `/v1/health/data`<br>[R] `/v1/houjin/{bangou}`<br>[R] `/v1/intelligence/precomputed/query`<br>[R] `/v1/meta`<br>[R] `/v1/meta/corpus_snapshot`<br>[R] `/v1/ping` | [R] `batch_get_programs`<br>[R] `check_exclusions`<br>[R] `deadline_calendar`<br>[R] `enum_values`<br>[R] `get_program`<br>[R] `get_usage_status`<br>[R] `list_exclusion_rules`<br>[R] `prescreen_programs`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `bg_task_queue` | `060_bg_task_queue.sql` | [R] `/v1/billing/portal`<br>[R] `/v1/me`<br>[R] `/v1/me/billing-portal`<br>[R] `/v1/me/cap`<br>[R] `/v1/me/keys/children`<br>[R] `/v1/me/keys/children/{child_id}`<br>[R] `/v1/me/usage`<br>[R] `/v1/me/usage.csv`<br>[R] `/v1/session`<br>[R] `/v1/session/logout`<br>[W] `/readyz`<br>[W] `/v1/billing/keys/from-checkout`<br>[W] `/v1/billing/portal`<br>[W] `/v1/me`<br>[W] `/v1/me/billing-portal`<br>[W] `/v1/me/cap`<br>[W] `/v1/me/keys/children`<br>[W] `/v1/me/keys/children/{child_id}`<br>[W] `/v1/me/usage`<br>[W] `/v1/me/usage.csv`<br>[W] `/v1/session`<br>[W] `/v1/session/logout`<br>[W] `/v1/widget/signup` | - |
| `bids` | `017_bids.sql` | [R] `/readyz`<br>[R] `/v1/am/dd_batch`<br>[R] `/v1/am/dd_export`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/bids/search`<br>[R] `/v1/bids/{unified_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bid_eligible_for_profile`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `combined_compliance_check`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_bid`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_bids`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `care_subsidies` | `039_healthcare_schema.sql` | - | [R] `search_care_subsidies` |
| `case_law` | `012_case_law.sql` | - | - |
| `case_studies` | `011_external_data_tables.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/case-studies/search`<br>[R] `/v1/case-studies/{case_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_case_study`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_meta`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_case_studies`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `similar_cases`<br>[R] `simulate_application_am`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `citation_verification` | `126_citation_verification.sql` | [R] `/v1/evidence/packets/batch`<br>[R] `/v1/evidence/packets/query`<br>[R] `/v1/evidence/packets/{subject_kind}/{subject_id}`<br>[R] `/v1/intelligence/precomputed/query`<br>[W] `/readyz`<br>[W] `/v1/citations/verify` | [R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch` |
| `client_profiles` | `096_client_profiles.sql` | [R] `/readyz`<br>[R] `/v1/me/client_profiles/bulk_import`<br>[R] `/v1/me/client_profiles/{profile_id}`<br>[R] `/v1/me/recurring/quarterly/{year}/{quarter}`<br>[W] `/readyz`<br>[W] `/v1/me/client_profiles/bulk_import`<br>[W] `/v1/me/client_profiles/{profile_id}` | - |
| `compliance_notification_log` | `020_compliance_subscribers.sql` | - | - |
| `compliance_subscribers` | `020_compliance_subscribers.sql` | [R] `/readyz`<br>[R] `/v1/compliance/stripe-checkout`<br>[R] `/v1/compliance/stripe-webhook`<br>[R] `/v1/compliance/subscribe`<br>[R] `/v1/compliance/unsubscribe/{unsubscribe_token}`<br>[R] `/v1/compliance/verify/{verification_token}`<br>[W] `/readyz`<br>[W] `/v1/compliance/stripe-webhook`<br>[W] `/v1/compliance/subscribe`<br>[W] `/v1/compliance/unsubscribe/{unsubscribe_token}`<br>[W] `/v1/compliance/verify/{verification_token}`<br>[W] `/v1/email/unsubscribe` | - |
| `correction_log` | `101_trust_infrastructure.sql` | [R] `/readyz`<br>[R] `/v1/corrections/feed` | - |
| `correction_submissions` | `101_trust_infrastructure.sql` | [R] `/readyz`<br>[R] `/v1/corrections`<br>[W] `/readyz`<br>[W] `/v1/corrections` | - |
| `course_subscriptions` | `099_recurring_engagement.sql` | [R] `/readyz`<br>[R] `/v1/me/courses/{course_slug}`<br>[R] `/v1/me/recurring/email_course/start`<br>[W] `/readyz`<br>[W] `/v1/me/courses/{course_slug}`<br>[W] `/v1/me/recurring/email_course/start` | - |
| `court_decisions` | `016_court_decisions.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/court-decisions/by-statute`<br>[R] `/v1/court-decisions/search`<br>[R] `/v1/court-decisions/{unified_id}`<br>[R] `/v1/integrations/email/connect`<br>[R] `/v1/integrations/email/inbound`<br>[R] `/v1/integrations/excel`<br>[R] `/v1/integrations/google`<br>[R] `/v1/integrations/google/status`<br>[R] `/v1/integrations/kintone`<br>[R] `/v1/integrations/kintone/connect`<br>[R] `/v1/integrations/sheets`<br>[R] `/v1/integrations/slack`<br>[R] `/v1/integrations/slack/webhook` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `batch_get_programs`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_exclusions`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deadline_calendar`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_cases_by_law`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_precedents_by_statute`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_court_decision`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_program`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_usage_status`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_exclusion_rules`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `prescreen_programs`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_court_decisions`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_programs`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `subsidy_roadmap_3yr`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `upcoming_deadlines`<br>[R] `validate`<br>[R] `verify_citations` |
| `cron_runs` | `102_cron_runs_heartbeat.sql` | [R] `/readyz`<br>[R] `/v1/admin/cron_runs`<br>[R] `/v1/admin/kpi` | - |
| `cross_source_baseline_state` | `107_cross_source_baseline_state.sql` | - | - |
| `customer_intentions` | `098_program_post_award_calendar.sql` | - | - |
| `customer_watches` | `088_houjin_watch.sql` | [R] `/readyz`<br>[W] `/readyz` | - |
| `customer_webhooks` | `080_customer_webhooks.sql` | [R] `/readyz`<br>[R] `/v1/me/webhooks/{webhook_id}`<br>[R] `/v1/me/webhooks/{webhook_id}/deliveries`<br>[R] `/v1/me/webhooks/{webhook_id}/test`<br>[W] `/readyz`<br>[W] `/v1/me/webhooks/{webhook_id}` | - |
| `customer_webhooks_test_hits` | `wave24_143_customer_webhooks_test_hits.sql` | - | - |
| `dd_question_templates` | `104_wave22_dd_question_templates.sql` | - | [R] `match_due_diligence_questions` |
| `dead_url_alerts` | `101_trust_infrastructure.sql` | - | - |
| `device_codes` | `023_device_codes.sql` | [R] `/readyz`<br>[R] `/v1/billing/checkout`<br>[R] `/v1/device/complete`<br>[R] `/v1/device/token`<br>[R] `/v1/widget/signup`<br>[W] `/readyz`<br>[W] `/v1/device/authorize`<br>[W] `/v1/device/complete`<br>[W] `/v1/device/token` | - |
| `email_schedule` | `008_email_schedule.sql` | [R] `/readyz`<br>[R] `/v1/me/rotate-key` | - |
| `email_schedule_new` | `010_email_schedule_day0_day1.sql` | - | - |
| `email_unsubscribes` | `072_email_unsubscribes.sql` | - | - |
| `empty_search_log` | `062_empty_search_log.sql` | [W] `/healthz`<br>[W] `/meta`<br>[W] `/v1/admin/cohort`<br>[W] `/v1/admin/funnel`<br>[W] `/v1/admin/kill_switch_status`<br>[W] `/v1/admin/kpi`<br>[W] `/v1/admin/top-errors`<br>[W] `/v1/am/acceptance_stats`<br>[W] `/v1/am/active_at`<br>[W] `/v1/am/annotations/{entity_id}`<br>[W] `/v1/am/by_law`<br>[W] `/v1/am/certifications`<br>[W] `/v1/am/enforcement`<br>[W] `/v1/am/enums/{enum_name}`<br>[W] `/v1/am/example_profiles`<br>[W] `/v1/am/example_profiles/{profile_id}`<br>[W] `/v1/am/group_graph`<br>[W] `/v1/am/gx_programs`<br>[W] `/v1/am/health/deep`<br>[W] `/v1/am/intent`<br>[W] `/v1/am/law_article`<br>[W] `/v1/am/loans`<br>[W] `/v1/am/mutual_plans`<br>[W] `/v1/am/open_programs`<br>[W] `/v1/am/pack_construction`<br>[W] `/v1/am/pack_manufacturing`<br>[W] `/v1/am/pack_real_estate`<br>[W] `/v1/am/programs/active_v2`<br>[W] `/v1/am/provenance/fact/{fact_id}`<br>[W] `/v1/am/provenance/{entity_id}`<br>[W] `/v1/am/reason`<br>[W] `/v1/am/related/{program_id}`<br>[W] `/v1/am/static`<br>[W] `/v1/am/static/{resource_id}`<br>[W] `/v1/am/tax_incentives`<br>[W] `/v1/am/tax_rule`<br>[W] `/v1/am/templates/saburoku_kyotei`<br>[W] `/v1/am/templates/saburoku_kyotei/metadata`<br>[W] `/v1/am/validate`<br>[W] `/v1/audit/seals/{seal_id}`<br>[W] `/v1/billing/client_tag_breakdown`<br>[W] `/v1/billing/portal`<br>[W] `/v1/calendar/deadlines`<br>[W] `/v1/calendar/deadlines.ics`<br>[W] `/v1/cost/preview`<br>[W] `/v1/discover/related/{entity_id}`<br>[W] `/v1/en/fdi_subsidies`<br>[W] `/v1/en/foreign_capital_eligibility`<br>[W] `/v1/en/laws/search`<br>[W] `/v1/en/laws/{law_id}/articles/{article_no}`<br>[W] `/v1/en/tax_treaty/{country_a}`<br>[W] `/v1/enforcement-cases/details/search`<br>[W] `/v1/evidence/packets/batch`<br>[W] `/v1/evidence/packets/query`<br>[W] `/v1/evidence/packets/{subject_kind}/{subject_id}`<br>[W] `/v1/exclusions/check`<br>[W] `/v1/exclusions/rules`<br>[W] `/v1/funding_stack/check`<br>[W] `/v1/health/data`<br>[W] `/v1/houjin/{bangou}`<br>[W] `/v1/integrations/email/connect`<br>[W] `/v1/integrations/email/inbound`<br>[W] `/v1/integrations/excel`<br>[W] `/v1/integrations/google`<br>[W] `/v1/integrations/google/status`<br>[W] `/v1/integrations/kintone`<br>[W] `/v1/integrations/kintone/connect`<br>[W] `/v1/integrations/sheets`<br>[W] `/v1/integrations/slack`<br>[W] `/v1/integrations/slack/webhook`<br>[W] `/v1/intelligence/precomputed/query`<br>[W] `/v1/me`<br>[W] `/v1/me/billing-portal`<br>[W] `/v1/me/billing_history`<br>[W] `/v1/me/cap`<br>[W] `/v1/me/dashboard`<br>[W] `/v1/me/keys/children`<br>[W] `/v1/me/keys/children/{child_id}`<br>[W] `/v1/me/recurring/email_course/start`<br>[W] `/v1/me/tool_recommendation`<br>[W] `/v1/me/usage`<br>[W] `/v1/me/usage.csv`<br>[W] `/v1/me/usage_by_tool`<br>[W] `/v1/meta`<br>[W] `/v1/meta/corpus_snapshot`<br>[W] `/v1/ping`<br>[W] `/v1/programs/batch`<br>[W] `/v1/programs/prescreen`<br>[W] `/v1/programs/search`<br>[W] `/v1/programs/{unified_id}`<br>[W] `/v1/session`<br>[W] `/v1/session/logout`<br>[W] `/v1/source_manifest/{program_id}`<br>[W] `/v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code}`<br>[W] `/v1/stats/confidence`<br>[W] `/v1/stats/coverage`<br>[W] `/v1/stats/data_quality`<br>[W] `/v1/stats/freshness`<br>[W] `/v1/stats/usage`<br>[W] `/v1/widget/signup` | [W] `batch_get_programs`<br>[W] `check_exclusions`<br>[W] `deadline_calendar`<br>[W] `enum_values`<br>[W] `get_program`<br>[W] `get_usage_status`<br>[W] `list_exclusion_rules`<br>[W] `prescreen_programs`<br>[W] `search_programs`<br>[W] `subsidy_roadmap_3yr`<br>[W] `upcoming_deadlines` |
| `enforcement_cases` | `011_external_data_tables.sql` | [R] `/readyz`<br>[R] `/v1/am/dd_batch`<br>[R] `/v1/am/dd_export`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/enforcement-cases/search`<br>[R] `/v1/enforcement-cases/{case_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_cases_by_law`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_enforcement_case`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_meta`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `regulatory_prep_pack`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_enforcement_cases`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `smb_starter_pack`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `enforcement_decision_refs` | `016_court_decisions.sql` | [R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_cases_by_law`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `exclusion_reason_codes` | `074_tier_x_exclusion_reason_classify.sql` | - | - |
| `feedback` | `003_feedback.sql` | [R] `/readyz`<br>[W] `/readyz` | - |
| `funnel_events` | `123_funnel_events.sql` | [R] `/readyz`<br>[R] `/v1/admin/analytics_split`<br>[R] `/v1/admin/kpi`<br>[W] `/readyz`<br>[W] `/v1/funnel/event` | - |
| `handles` | `087_idempotency_cache.sql` | - | - |
| `houjin_master` | `014_business_intelligence_layer.sql` | - | - |
| `industry_program_density` | `014_business_intelligence_layer.sql` | - | - |
| `industry_stats` | `014_business_intelligence_layer.sql` | - | - |
| `integration_accounts` | `105_integrations.sql` | [R] `/v1/integrations/email/connect`<br>[R] `/v1/integrations/email/inbound`<br>[R] `/v1/integrations/excel`<br>[R] `/v1/integrations/google`<br>[R] `/v1/integrations/google/status`<br>[R] `/v1/integrations/kintone`<br>[R] `/v1/integrations/kintone/connect`<br>[R] `/v1/integrations/sheets`<br>[R] `/v1/integrations/slack`<br>[R] `/v1/integrations/slack/webhook`<br>[W] `/v1/integrations/email/connect`<br>[W] `/v1/integrations/email/inbound`<br>[W] `/v1/integrations/excel`<br>[W] `/v1/integrations/google`<br>[W] `/v1/integrations/google/status`<br>[W] `/v1/integrations/kintone`<br>[W] `/v1/integrations/kintone/connect`<br>[W] `/v1/integrations/sheets`<br>[W] `/v1/integrations/slack`<br>[W] `/v1/integrations/slack/webhook` | - |
| `integration_sync_log` | `105_integrations.sql` | [R] `/readyz`<br>[R] `/v1/integrations/email/connect`<br>[R] `/v1/integrations/email/inbound`<br>[R] `/v1/integrations/excel`<br>[R] `/v1/integrations/google`<br>[R] `/v1/integrations/google/callback`<br>[R] `/v1/integrations/google/status`<br>[R] `/v1/integrations/kintone`<br>[R] `/v1/integrations/kintone/connect`<br>[R] `/v1/integrations/sheets`<br>[R] `/v1/integrations/slack`<br>[R] `/v1/integrations/slack/webhook`<br>[W] `/readyz`<br>[W] `/v1/integrations/email/connect`<br>[W] `/v1/integrations/email/inbound`<br>[W] `/v1/integrations/excel`<br>[W] `/v1/integrations/google`<br>[W] `/v1/integrations/google/callback`<br>[W] `/v1/integrations/google/start`<br>[W] `/v1/integrations/google/status`<br>[W] `/v1/integrations/kintone`<br>[W] `/v1/integrations/kintone/connect`<br>[W] `/v1/integrations/kintone/sync`<br>[W] `/v1/integrations/sheets`<br>[W] `/v1/integrations/slack`<br>[W] `/v1/integrations/slack/webhook` | - |
| `invoice_registrants` | `019_invoice_registrants.sql` | [R] `/readyz`<br>[R] `/v1/advisors/verify-houjin/{advisor_id}`<br>[R] `/v1/am/dd_batch`<br>[R] `/v1/am/dd_export`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/invoice_registrants/search`<br>[R] `/v1/invoice_registrants/{invoice_registration_number}`<br>[R] `/v1/programs/batch`<br>[R] `/v1/programs/search`<br>[R] `/v1/programs/{unified_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_profile_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_invoice_registrants`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `jpi_exclusion_rules_pre052_snapshot` | `065_compat_matrix_uni_id_backfill.sql` | - | - |
| `jpi_pc_program_health` | `048_pc_program_health.sql` | - | [R] `batch_get_programs`<br>[R] `check_enforcement_am`<br>[R] `check_exclusions`<br>[R] `deadline_calendar`<br>[R] `deep_health_am`<br>[R] `enum_values`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_example_profile_am`<br>[R] `get_law_article_am`<br>[R] `get_program`<br>[R] `get_static_resource_am`<br>[R] `get_usage_status`<br>[R] `list_example_profiles_am`<br>[R] `list_exclusion_rules`<br>[R] `list_static_resources_am`<br>[R] `prescreen_programs`<br>[R] `render_36_kyotei_am`<br>[R] `search_gx_programs_am`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `l4_query_cache` | `043_l4_cache.sql` | [R] `/v1/am/acceptance_stats`<br>[R] `/v1/am/active_at`<br>[R] `/v1/am/annotations/{entity_id}`<br>[R] `/v1/am/by_law`<br>[R] `/v1/am/certifications`<br>[R] `/v1/am/enforcement`<br>[R] `/v1/am/enums/{enum_name}`<br>[R] `/v1/am/example_profiles`<br>[R] `/v1/am/example_profiles/{profile_id}`<br>[R] `/v1/am/gx_programs`<br>[R] `/v1/am/health/deep`<br>[R] `/v1/am/intent`<br>[R] `/v1/am/law_article`<br>[R] `/v1/am/loans`<br>[R] `/v1/am/mutual_plans`<br>[R] `/v1/am/open_programs`<br>[R] `/v1/am/pack_construction`<br>[R] `/v1/am/pack_manufacturing`<br>[R] `/v1/am/pack_real_estate`<br>[R] `/v1/am/programs/active_v2`<br>[R] `/v1/am/provenance/fact/{fact_id}`<br>[R] `/v1/am/provenance/{entity_id}`<br>[R] `/v1/am/reason`<br>[R] `/v1/am/related/{program_id}`<br>[R] `/v1/am/static`<br>[R] `/v1/am/static/{resource_id}`<br>[R] `/v1/am/tax_incentives`<br>[R] `/v1/am/tax_rule`<br>[R] `/v1/am/templates/saburoku_kyotei`<br>[R] `/v1/am/templates/saburoku_kyotei/metadata`<br>[R] `/v1/am/validate`<br>[R] `/v1/programs/batch`<br>[R] `/v1/programs/search`<br>[R] `/v1/programs/{unified_id}`<br>[R] `/v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code}`<br>[R] `/v1/stats/coverage`<br>[R] `/v1/stats/data_quality`<br>[R] `/v1/stats/freshness`<br>[R] `/v1/stats/usage`<br>[W] `/v1/am/acceptance_stats`<br>[W] `/v1/am/active_at`<br>[W] `/v1/am/annotations/{entity_id}`<br>[W] `/v1/am/by_law`<br>[W] `/v1/am/certifications`<br>[W] `/v1/am/enforcement`<br>[W] `/v1/am/enums/{enum_name}`<br>[W] `/v1/am/example_profiles`<br>[W] `/v1/am/example_profiles/{profile_id}`<br>[W] `/v1/am/gx_programs`<br>[W] `/v1/am/health/deep`<br>[W] `/v1/am/intent`<br>[W] `/v1/am/law_article`<br>[W] `/v1/am/loans`<br>[W] `/v1/am/mutual_plans`<br>[W] `/v1/am/open_programs`<br>[W] `/v1/am/pack_construction`<br>[W] `/v1/am/pack_manufacturing`<br>[W] `/v1/am/pack_real_estate`<br>[W] `/v1/am/programs/active_v2`<br>[W] `/v1/am/provenance/fact/{fact_id}`<br>[W] `/v1/am/provenance/{entity_id}`<br>[W] `/v1/am/reason`<br>[W] `/v1/am/related/{program_id}`<br>[W] `/v1/am/static`<br>[W] `/v1/am/static/{resource_id}`<br>[W] `/v1/am/tax_incentives`<br>[W] `/v1/am/tax_rule`<br>[W] `/v1/am/templates/saburoku_kyotei`<br>[W] `/v1/am/templates/saburoku_kyotei/metadata`<br>[W] `/v1/am/validate`<br>[W] `/v1/programs/batch`<br>[W] `/v1/programs/search`<br>[W] `/v1/programs/{unified_id}`<br>[W] `/v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code}`<br>[W] `/v1/stats/coverage`<br>[W] `/v1/stats/data_quality`<br>[W] `/v1/stats/freshness`<br>[W] `/v1/stats/usage` | - |
| `laws` | `015_laws.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/court-decisions/by-statute`<br>[R] `/v1/integrations/email/connect`<br>[R] `/v1/integrations/email/inbound`<br>[R] `/v1/integrations/excel`<br>[R] `/v1/integrations/google`<br>[R] `/v1/integrations/google/status`<br>[R] `/v1/integrations/kintone`<br>[R] `/v1/integrations/kintone/connect`<br>[R] `/v1/integrations/sheets`<br>[R] `/v1/integrations/slack`<br>[R] `/v1/integrations/slack/webhook`<br>[R] `/v1/laws/search`<br>[R] `/v1/laws/{unified_id}`<br>[R] `/v1/laws/{unified_id}/related-programs` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `batch_get_programs`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_exclusions`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deadline_calendar`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_cases_by_law`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_precedents_by_statute`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_program`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_usage_status`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_exclusion_rules`<br>[R] `list_law_revisions`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `prescreen_programs`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `regulatory_prep_pack`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_programs`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `subsidy_roadmap_3yr`<br>[R] `trace_program_to_law`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `upcoming_deadlines`<br>[R] `validate`<br>[R] `verify_citations` |
| `line_message_log` | `106_line_message_log.sql` | [R] `/readyz`<br>[R] `/v1/integrations/line/webhook` | - |
| `line_users` | `021_line_users.sql` | [R] `/readyz`<br>[R] `/v1/integrations/line/webhook`<br>[W] `/readyz`<br>[W] `/v1/integrations/line/webhook` | - |
| `loan_programs` | `011_external_data_tables.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/loan-programs/search`<br>[R] `/v1/loan-programs/{loan_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_loan_program`<br>[R] `get_meta`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loan_programs`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `smb_starter_pack`<br>[R] `subsidy_combo_finder`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `medical_institutions` | `039_healthcare_schema.sql` | - | [R] `get_medical_institution`<br>[R] `search_healthcare_compliance` |
| `ministry_faq` | `014_business_intelligence_layer.sql` | - | - |
| `new_program_candidates` | `011_external_data_tables.sql` | - | - |
| `nta_bunsho_kaitou` | `103_nta_corpus.sql` | [R] `/readyz` | [R] `batch_get_programs`<br>[R] `check_exclusions`<br>[R] `deadline_calendar`<br>[R] `enum_values`<br>[R] `find_bunsho_kaitou`<br>[R] `get_program`<br>[R] `get_usage_status`<br>[R] `list_exclusion_rules`<br>[R] `prescreen_programs`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `nta_saiketsu` | `103_nta_corpus.sql` | - | [R] `find_saiketsu` |
| `nta_shitsugi` | `103_nta_corpus.sql` | [R] `/readyz` | [R] `batch_get_programs`<br>[R] `check_exclusions`<br>[R] `deadline_calendar`<br>[R] `enum_values`<br>[R] `find_shitsugi`<br>[R] `get_program`<br>[R] `get_usage_status`<br>[R] `list_exclusion_rules`<br>[R] `prescreen_programs`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `nta_tsutatsu_index` | `103_nta_corpus.sql` | [R] `/readyz` | [R] `batch_get_programs`<br>[R] `check_exclusions`<br>[R] `cite_tsutatsu`<br>[R] `deadline_calendar`<br>[R] `enum_values`<br>[R] `get_program`<br>[R] `get_usage_status`<br>[R] `list_exclusion_rules`<br>[R] `prescreen_programs`<br>[R] `search_programs`<br>[R] `subsidy_roadmap_3yr`<br>[R] `upcoming_deadlines` |
| `pc_acceptance_rate_by_authority` | `045_precompute_more.sql` | - | - |
| `pc_acceptance_stats_by_program` | `044_precompute_tables.sql` | - | - |
| `pc_amendment_recent_by_law` | `045_precompute_more.sql` | - | - |
| `pc_amendment_severity_distribution` | `045_precompute_more.sql` | - | - |
| `pc_amount_max_distribution` | `045_precompute_more.sql` | - | - |
| `pc_amount_to_recipient_size` | `045_precompute_more.sql` | - | - |
| `pc_application_close_calendar` | `045_precompute_more.sql` | - | - |
| `pc_authority_action_frequency` | `045_precompute_more.sql` | - | - |
| `pc_authority_to_programs` | `044_precompute_tables.sql` | - | - |
| `pc_certification_by_subject` | `044_precompute_tables.sql` | - | - |
| `pc_combo_pairs` | `044_precompute_tables.sql` | - | - |
| `pc_court_decision_law_chain` | `045_precompute_more.sql` | - | - |
| `pc_enforcement_by_industry` | `044_precompute_tables.sql` | - | - |
| `pc_enforcement_industry_distribution` | `045_precompute_more.sql` | - | - |
| `pc_industry_jsic_aliases` | `044_precompute_tables.sql` | - | - |
| `pc_industry_jsic_to_program` | `045_precompute_more.sql` | - | - |
| `pc_invoice_registrant_by_pref` | `045_precompute_more.sql` | - | - |
| `pc_law_amendments_recent` | `044_precompute_tables.sql` | - | - |
| `pc_law_text_to_program_count` | `045_precompute_more.sql` | - | - |
| `pc_law_to_amendment_chain` | `045_precompute_more.sql` | - | - |
| `pc_law_to_program_index` | `044_precompute_tables.sql` | - | - |
| `pc_loan_by_collateral_type` | `044_precompute_tables.sql` | - | - |
| `pc_loan_collateral_to_program` | `045_precompute_more.sql` | - | - |
| `pc_program_geographic_density` | `045_precompute_more.sql` | - | - |
| `pc_program_to_amendments` | `044_precompute_tables.sql` | - | - |
| `pc_program_to_certification_combo` | `045_precompute_more.sql` | - | - |
| `pc_program_to_loan_combo` | `045_precompute_more.sql` | - | - |
| `pc_program_to_tax_combo` | `045_precompute_more.sql` | - | - |
| `pc_seasonal_calendar` | `044_precompute_tables.sql` | - | - |
| `pc_starter_packs_per_audience` | `044_precompute_tables.sql` | - | - |
| `pc_top_subsidies_by_industry` | `044_precompute_tables.sql` | - | - |
| `pc_top_subsidies_by_prefecture` | `044_precompute_tables.sql` | - | - |
| `postmark_webhook_events` | `059_postmark_webhook_events.sql` | [W] `/readyz`<br>[W] `/v1/email/webhook` | - |
| `program_documents` | `011_external_data_tables.sql` | - | - |
| `program_law_refs` | `015_laws.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/laws/{unified_id}/related-programs` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values_am`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `simulate_application_am`<br>[R] `trace_program_to_law`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `validate`<br>[R] `verify_citations` |
| `program_post_award_calendar` | `098_program_post_award_calendar.sql` | - | - |
| `quality_metrics_daily` | `101_trust_infrastructure.sql` | - | - |
| `real_estate_programs` | `042_real_estate_schema.sql` | - | - |
| `refund_requests` | `071_stripe_edge_cases.sql` | [W] `/readyz`<br>[W] `/v1/billing/portal` | - |
| `reproducibility_snapshots` | `101_trust_infrastructure.sql` | - | - |
| `saved_searches` | `079_saved_searches.sql` | [R] `/readyz`<br>[R] `/v1/integrations/kintone/sync`<br>[R] `/v1/me/recurring/slack`<br>[R] `/v1/me/saved_searches/{saved_id}`<br>[R] `/v1/me/saved_searches/{saved_id}/results`<br>[R] `/v1/me/saved_searches/{saved_id}/results.xlsx`<br>[R] `/v1/me/saved_searches/{saved_id}/sheet`<br>[W] `/readyz`<br>[W] `/v1/me/recurring/slack`<br>[W] `/v1/me/saved_searches/{saved_id}`<br>[W] `/v1/me/saved_searches/{saved_id}/sheet` | [R] `prepare_kessan_briefing` |
| `source_lineage_audit` | `014_business_intelligence_layer.sql` | - | - |
| `statements` | `wave24_112_am_region_extension.sql` | - | - |
| `stripe_tax_cache` | `071_stripe_edge_cases.sql` | [R] `/readyz`<br>[R] `/v1/billing/portal`<br>[W] `/readyz`<br>[W] `/v1/billing/portal` | - |
| `stripe_webhook_events` | `053_stripe_webhook_events.sql` | [R] `/readyz`<br>[R] `/v1/billing/webhook`<br>[R] `/v1/widget/signup`<br>[R] `/v1/widget/stripe-webhook`<br>[W] `/readyz`<br>[W] `/v1/billing/webhook`<br>[W] `/v1/widget/signup`<br>[W] `/v1/widget/stripe-webhook` | - |
| `subscribers` | `002_subscribers.sql` | [W] `/readyz`<br>[W] `/v1/email/unsubscribe`<br>[W] `/v1/email/webhook`<br>[W] `/v1/subscribers/unsubscribe` | - |
| `support_org` | `014_business_intelligence_layer.sql` | - | - |
| `tax_rulesets` | `018_tax_rulesets.sql` | [R] `/readyz`<br>[R] `/v1/am/houjin/{houjin_bangou}/subsidy_history`<br>[R] `/v1/am/programs/by_jsic/{jsic_code}`<br>[R] `/v1/am/programs/emerging`<br>[R] `/v1/am/programs/{program_id}/adopted_companies`<br>[R] `/v1/audit/batch_evaluate`<br>[R] `/v1/audit/cite_chain/{ruleset_id}`<br>[R] `/v1/audit/seals/{seal_id}`<br>[R] `/v1/audit/workpaper`<br>[R] `/v1/integrations/email/connect`<br>[R] `/v1/integrations/email/inbound`<br>[R] `/v1/integrations/excel`<br>[R] `/v1/integrations/google`<br>[R] `/v1/integrations/google/status`<br>[R] `/v1/integrations/kintone`<br>[R] `/v1/integrations/kintone/connect`<br>[R] `/v1/integrations/sheets`<br>[R] `/v1/integrations/slack`<br>[R] `/v1/integrations/slack/webhook`<br>[R] `/v1/tax_rulesets/evaluate`<br>[R] `/v1/tax_rulesets/search`<br>[R] `/v1/tax_rulesets/{unified_id}` | [R] `active_programs_at`<br>[R] `apply_eligibility_chain_am`<br>[R] `audit_batch_evaluate`<br>[R] `batch_get_programs`<br>[R] `bundle_application_kit`<br>[R] `check_drug_approval`<br>[R] `check_enforcement_am`<br>[R] `check_exclusions`<br>[R] `check_foreign_capital_eligibility`<br>[R] `check_funding_stack_am`<br>[R] `combined_compliance_check`<br>[R] `compose_audit_workpaper`<br>[R] `cross_check_jurisdiction`<br>[R] `cross_check_zoning`<br>[R] `dd_medical_institution_am`<br>[R] `dd_property_am`<br>[R] `deadline_calendar`<br>[R] `deep_health_am`<br>[R] `discover_related`<br>[R] `enum_values`<br>[R] `enum_values_am`<br>[R] `evaluate_tax_applicability`<br>[R] `find_adopted_companies_by_program`<br>[R] `find_complementary_programs_am`<br>[R] `find_emerging_programs`<br>[R] `find_fdi_friendly_subsidies`<br>[R] `find_programs_by_jsic`<br>[R] `forecast_program_renewal`<br>[R] `get_36_kyotei_metadata_am`<br>[R] `get_am_tax_rule`<br>[R] `get_evidence_packet`<br>[R] `get_evidence_packet_batch`<br>[R] `get_example_profile_am`<br>[R] `get_houjin_360_am`<br>[R] `get_houjin_subsidy_history`<br>[R] `get_law_article_am`<br>[R] `get_law_article_en`<br>[R] `get_program`<br>[R] `get_provenance`<br>[R] `get_provenance_for_fact`<br>[R] `get_source_manifest`<br>[R] `get_static_resource_am`<br>[R] `get_tax_rule`<br>[R] `get_usage_status`<br>[R] `get_zoning_overlay`<br>[R] `graph_traverse`<br>[R] `intent_of`<br>[R] `list_edinet_disclosures`<br>[R] `list_example_profiles_am`<br>[R] `list_exclusion_rules`<br>[R] `list_open_programs`<br>[R] `list_static_resources_am`<br>[R] `list_tax_sunset_alerts`<br>[R] `pack_construction`<br>[R] `pack_manufacturing`<br>[R] `pack_real_estate`<br>[R] `prerequisite_chain`<br>[R] `prescreen_programs`<br>[R] `program_abstract_structured`<br>[R] `program_active_periods_am`<br>[R] `program_lifecycle`<br>[R] `reason_answer`<br>[R] `recommend_similar_case`<br>[R] `recommend_similar_court_decision`<br>[R] `recommend_similar_program`<br>[R] `regulatory_prep_pack`<br>[R] `related_programs`<br>[R] `render_36_kyotei_am`<br>[R] `resolve_citation_chain`<br>[R] `rule_engine_check`<br>[R] `search_acceptance_stats_am`<br>[R] `search_by_law`<br>[R] `search_certifications`<br>[R] `search_gx_programs_am`<br>[R] `search_healthcare_programs`<br>[R] `search_invoice_by_houjin_partial`<br>[R] `search_laws_en`<br>[R] `search_loans_am`<br>[R] `search_mutual_plans_am`<br>[R] `search_programs`<br>[R] `search_real_estate_compliance`<br>[R] `search_real_estate_programs`<br>[R] `search_tax_incentives`<br>[R] `search_tax_rules`<br>[R] `simulate_application_am`<br>[R] `smb_starter_pack`<br>[R] `subsidy_combo_finder`<br>[R] `subsidy_roadmap_3yr`<br>[R] `track_amendment_lineage_am`<br>[R] `unified_lifecycle_calendar`<br>[R] `upcoming_deadlines`<br>[R] `validate`<br>[R] `verify_citations` |
| `testimonials` | `041_testimonials.sql` | [R] `/readyz`<br>[W] `/readyz` | - |
| `trial_signups` | `076_trial_signup.sql` | [R] `/readyz`<br>[R] `/v1/signup`<br>[R] `/v1/signup/verify`<br>[W] `/readyz`<br>[W] `/v1/signup`<br>[W] `/v1/signup/verify` | - |
| `verticals_deep` | `014_business_intelligence_layer.sql` | - | - |
| `webhook_deliveries` | `080_customer_webhooks.sql` | [R] `/readyz`<br>[R] `/v1/me/webhooks/{webhook_id}/deliveries` | - |
| `widget_keys` | `022_widget_keys.sql` | [R] `/readyz`<br>[R] `/v1/widget/stripe-webhook`<br>[R] `/v1/widget/{key_id}/usage`<br>[W] `/readyz`<br>[W] `/v1/widget/enum_values`<br>[W] `/v1/widget/search`<br>[W] `/v1/widget/stripe-webhook` | - |
| `zoning_overlays` | `042_real_estate_schema.sql` | - | - |

## Section D. Orphan tables (no REST/MCP code path)

Total orphans: **86** of 171. Likely categories: precompute targets (`pc_*`) refreshed by `scripts/cron/precompute_refresh.py` and surfaced via aggregate views; ETL staging (`alias_candidates_queue`, `am_data_quality_snapshot`); future-cohort schemas not yet wired (`am_program_eligibility_predicate`, `am_temporal_correlation`); audit infrastructure consumed by middleware not by named routes (`audit_seal_keys`, `audit_merkle_*`).

| table | migration |
| --- | --- |
| `adoption_records` | `014_business_intelligence_layer.sql` |
| `alias_candidates_queue` | `112_alias_candidates_queue.sql` |
| `am_adopted_company_features` | `wave24_157_am_adopted_company_features.sql` |
| `am_adoption_trend_monthly` | `160_am_adoption_trend_monthly.sql` |
| `am_annotation_kind` | `046_annotation_layer.sql` |
| `am_case_study_narrative` | `wave24_141_am_narrative_quarantine.sql` |
| `am_citation_network` | `wave24_163_am_citation_network.sql` |
| `am_credit_pack_purchase` | `wave24_148_am_credit_pack_purchase.sql` |
| `am_data_quality_snapshot` | `wave24_145_am_data_quality_snapshot.sql` |
| `am_enforcement_anomaly` | `161_am_enforcement_anomaly.sql` |
| `am_enforcement_summary` | `wave24_141_am_narrative_quarantine.sql` |
| `am_entities_vec_v2_metadata` | `wave24_110_am_entities_vec_v2.sql` |
| `am_entity_appearance_count` | `wave24_153_am_entity_appearance_count.sql` |
| `am_entity_monthly_snapshot` | `wave24_111_am_entity_monthly_snapshot.sql` |
| `am_entity_pagerank` | `162_am_entity_pagerank.sql` |
| `am_geo_industry_density` | `155_am_geo_industry_density.sql` |
| `am_houjin_360_narrative` | `wave24_141_am_narrative_quarantine.sql` |
| `am_id_bridge` | `159_am_id_bridge.sql` |
| `am_law_article_summary` | `wave24_141_am_narrative_quarantine.sql` |
| `am_narrative_extracted_entities` | `wave24_140_am_narrative_extracted_entities.sql` |
| `am_narrative_serve_log` | `wave24_142_am_narrative_customer_reports.sql` |
| `am_program_eligibility_history` | `wave24_106_amendment_snapshot_rebuild.sql` |
| `am_program_eligibility_predicate` | `wave24_137_am_program_eligibility_predicate.sql` |
| `am_region_program_density_breakdown` | `wave24_139_am_region_program_density.sql` |
| `am_temporal_correlation` | `154_am_temporal_correlation.sql` |
| `am_validation_result` | `047_validation_layer.sql` |
| `api_keys_v2` | `052_api_keys_subscription_status.sql` |
| `audit_seal_keys` | `wave24_105_audit_seal_key_version.sql` |
| `case_law` | `012_case_law.sql` |
| `compliance_notification_log` | `020_compliance_subscribers.sql` |
| `cross_source_baseline_state` | `107_cross_source_baseline_state.sql` |
| `customer_intentions` | `098_program_post_award_calendar.sql` |
| `customer_webhooks_test_hits` | `wave24_143_customer_webhooks_test_hits.sql` |
| `dead_url_alerts` | `101_trust_infrastructure.sql` |
| `email_schedule_new` | `010_email_schedule_day0_day1.sql` |
| `email_unsubscribes` | `072_email_unsubscribes.sql` |
| `exclusion_reason_codes` | `074_tier_x_exclusion_reason_classify.sql` |
| `handles` | `087_idempotency_cache.sql` |
| `houjin_master` | `014_business_intelligence_layer.sql` |
| `industry_program_density` | `014_business_intelligence_layer.sql` |
| `industry_stats` | `014_business_intelligence_layer.sql` |
| `jpi_exclusion_rules_pre052_snapshot` | `065_compat_matrix_uni_id_backfill.sql` |
| `ministry_faq` | `014_business_intelligence_layer.sql` |
| `new_program_candidates` | `011_external_data_tables.sql` |
| `pc_acceptance_rate_by_authority` | `045_precompute_more.sql` |
| `pc_acceptance_stats_by_program` | `044_precompute_tables.sql` |
| `pc_amendment_recent_by_law` | `045_precompute_more.sql` |
| `pc_amendment_severity_distribution` | `045_precompute_more.sql` |
| `pc_amount_max_distribution` | `045_precompute_more.sql` |
| `pc_amount_to_recipient_size` | `045_precompute_more.sql` |
| `pc_application_close_calendar` | `045_precompute_more.sql` |
| `pc_authority_action_frequency` | `045_precompute_more.sql` |
| `pc_authority_to_programs` | `044_precompute_tables.sql` |
| `pc_certification_by_subject` | `044_precompute_tables.sql` |
| `pc_combo_pairs` | `044_precompute_tables.sql` |
| `pc_court_decision_law_chain` | `045_precompute_more.sql` |
| `pc_enforcement_by_industry` | `044_precompute_tables.sql` |
| `pc_enforcement_industry_distribution` | `045_precompute_more.sql` |
| `pc_industry_jsic_aliases` | `044_precompute_tables.sql` |
| `pc_industry_jsic_to_program` | `045_precompute_more.sql` |
| `pc_invoice_registrant_by_pref` | `045_precompute_more.sql` |
| `pc_law_amendments_recent` | `044_precompute_tables.sql` |
| `pc_law_text_to_program_count` | `045_precompute_more.sql` |
| `pc_law_to_amendment_chain` | `045_precompute_more.sql` |
| `pc_law_to_program_index` | `044_precompute_tables.sql` |
| `pc_loan_by_collateral_type` | `044_precompute_tables.sql` |
| `pc_loan_collateral_to_program` | `045_precompute_more.sql` |
| `pc_program_geographic_density` | `045_precompute_more.sql` |
| `pc_program_to_amendments` | `044_precompute_tables.sql` |
| `pc_program_to_certification_combo` | `045_precompute_more.sql` |
| `pc_program_to_loan_combo` | `045_precompute_more.sql` |
| `pc_program_to_tax_combo` | `045_precompute_more.sql` |
| `pc_seasonal_calendar` | `044_precompute_tables.sql` |
| `pc_starter_packs_per_audience` | `044_precompute_tables.sql` |
| `pc_top_subsidies_by_industry` | `044_precompute_tables.sql` |
| `pc_top_subsidies_by_prefecture` | `044_precompute_tables.sql` |
| `program_documents` | `011_external_data_tables.sql` |
| `program_post_award_calendar` | `098_program_post_award_calendar.sql` |
| `quality_metrics_daily` | `101_trust_infrastructure.sql` |
| `real_estate_programs` | `042_real_estate_schema.sql` |
| `reproducibility_snapshots` | `101_trust_infrastructure.sql` |
| `source_lineage_audit` | `014_business_intelligence_layer.sql` |
| `statements` | `wave24_112_am_region_extension.sql` |
| `support_org` | `014_business_intelligence_layer.sql` |
| `verticals_deep` | `014_business_intelligence_layer.sql` |
| `zoning_overlays` | `042_real_estate_schema.sql` |

## Appendix. Audit gaps

- openapi paths NOT scanned for tables: **9** (router-file lookup failed).
  - `/v1/me/webhooks`
  - `/v1/billing/refund_request`
  - `/v1/me/watches/{watch_id}`
  - `/v1/me/testimonials`
  - `/v1/me/client_profiles`
  - `/v1/me/testimonials/{testimonial_id}`
  - `/v1/me/watches`
  - `/v1/me/saved_searches`
  - `/v1/me/courses`

- Endpoints with NO detected table touch (9; likely external service, signed payload only, or helper-deep behind multiple module hops):
  - `/v1/am/data-freshness` -> `src/jpintel_mcp/api/transparency.py`
  - `/v1/am/programs/{program_id}/sources` -> `src/jpintel_mcp/api/transparency.py`
  - `/v1/cross_source/{entity_id}` -> `src/jpintel_mcp/api/trust.py`
  - `/v1/feedback` -> `src/jpintel_mcp/api/anon_limit.py`
  - `/v1/health/sla` -> `src/jpintel_mcp/api/trust.py`
  - `/v1/meta/freshness` -> `src/jpintel_mcp/api/meta_freshness.py`
  - `/v1/staleness` -> `src/jpintel_mcp/api/trust.py`
  - `/v1/subscribers` -> `src/jpintel_mcp/api/anon_limit.py`
  - `/v1/testimonials` -> `src/jpintel_mcp/api/anon_limit.py`
