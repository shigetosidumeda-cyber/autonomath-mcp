# W28 Payload Audit (2026-05-05)

Response-size audit of all 182 `docs/openapi/v1.json` endpoints, run against
local uvicorn (`.venv/bin/uvicorn jpintel_mcp.api.main:app --port 8088`,
`ANON_RATE_LIMIT_ENABLED=false`, `RATE_LIMIT_BURST_DISABLED=1`,
`PER_IP_ENDPOINT_LIMIT_DISABLED=1`). Each endpoint was called with the
minimum query/body required by its OpenAPI parameters; auth-gated and
strict-validation paths return 401/403/422/404 envelopes (counted as
"skipped" for size purposes). One `timeout` (`/v1/stats/data_quality`,
exceeded 15s) is also skipped.

**Status mix**: 200=61, 422=72, 404=14, 401=29, 503=2, 400=2, 403=1,
timeout=1. The user/me/integrations cluster (29 × 401) and validation-only
POSTs (72 × 422) emit the standard ~500-1.5KB error envelope; their wire
shape is already minimal and not a target.

**OK-only sample (n=61)**: total 603,676 B, mean 9,896 B, p50 1,513 B, p95
32,321 B. **Top 10 = 67.1% of all OK bytes** — payload weight is heavily
concentrated in the search list endpoints.

Current opt-in optimisations (W26):
- `?compact=true` envelope (`api/_compact_envelope.py`): module landed
  2026-05-05, **0 routes wired** as opt-in callers yet.
- `?fields=` partial response (`api/_field_filter.py`): wired on **5 route
  declarations** across 4 files — `evidence.py` (×2 packet routes),
  `programs.py` (`/search` + `/{unified_id}`), `autonomath.py` (36-協定
  POST). Search list endpoints below mostly do **not** carry it yet.

## Top 10 — recommended treatment

| rank | size B | endpoint | shape | recommend |
|---:|---:|:---|:---|:---|
| 1 | 119,388 | `GET /v1/exclusions/rules` | flat list of 181 dicts (depth 4, 365 array nodes), no envelope | **partial** — add `?fields=rule_id,kind,program_a,program_b,severity` (drops `description` + `source_notes` + `extra` block, ≈ -70% bytes); also add `?limit/offset` paging — currently returns the whole table in one shot |
| 2 | 57,480 | `GET /v1/loan-programs/search` | `{total,limit,offset,results[20]}` × 21 columns/row incl. `target_conditions`, `source_excerpt` | **partial** — `?fields=results.id,program_name,provider,amount_max_yen,interest_rate_base_annual` saves the long text columns, expect ≈ -60% |
| 3 | 40,815 | `GET /v1/case-studies/search` | `{total,limit,offset,results[20]}` × 21 cols, large `case_summary` + `source_excerpt` per row | **partial** — `?fields=results.case_id,company_name,case_title,programs_used,prefecture` covers list-page UX, ≈ -55% |
| 4 | 32,321 | `GET /v1/tax_rulesets/search` | nested `eligibility_conditions_json` (depth 8) + `_disclaimer` per envelope | **partial + compact** — `?fields=` to drop `eligibility_conditions_json` + `calculation_formula` from list view (lift to `/{unified_id}`); `?compact=true` to dedupe the boilerplate `_disclaimer` into a top-level reference |
| 5 | 30,974 | `GET /v1/invoice_registrants/search` | 50/page × 16 cols, repeats `attribution{}` block | **partial** — `?fields=results.invoice_registration_number,normalized_name,prefecture,registered_date,revoked_date` is the typical lookup shape, ≈ -65% |
| 6 | 28,947 | `GET /v1/am/programs/active_v2` | 50/page × ~25 fields incl. amendment_snapshot bookkeeping | **partial** — `?fields=results.unified_id,primary_name,authority_canonical,prefecture,application_close_date,is_application_open_now`; the `amendment_*` + `effective_*` columns are detail-page material |
| 7 | 24,879 | `GET /v1/am/audit-log` | 50 diff rows + `_meta{honest_note,rss,license_metadata,creator}` envelope | **compact** — `_meta` + `_disclaimer`-style boilerplate is a perfect compact-envelope target (replace with id ref); diff rows already lean |
| 8 | 24,831 | `GET /v1/bids/search` | 20/page × 23 cols, long `bid_description` + `eligibility_conditions` per row | **partial** — `?fields=results.unified_id,bid_title,procuring_entity,bid_deadline,awarded_amount_yen,winner_name`, ≈ -60% |
| 9 | 23,285 | `GET /v1/enforcement-cases/search` | 20/page × 22 cols incl. `reason_excerpt` + `legal_basis` text | **partial** — `?fields=results.case_id,event_type,recipient_name,amount_improper_grant_yen,occurred_fiscal_years,prefecture` |
| 10 | 22,350 | `GET /v1/programs/search` | already supports `?fields=` — current default returns 20/page with full Program (incl. `a_to_j_coverage`, `application_window`, `aliases`, `crop_categories`, etc.) | **already wired** — verify the `fields=minimal/standard` slice presets actually trim to ≤ 5KB; may also want `?compact=true` once the envelope opts in |

**Common pattern**: 8 of the 10 are paged search lists where the per-row
schema includes 1-3 long-text columns (`source_excerpt`, `description`,
`bid_description`, `case_summary`, `eligibility_conditions_json`) intended
for the detail page, not the list view. A single shared `fields=list`
preset across these endpoints would cut top-10 traffic ≈ 55-65%.

## Adoption recommendation (audit-only — apply in a separate wave)

1. **Wire `?fields=` on the 8 unwired search endpoints** (rows 1-9 minus
   #10 which already has it): `loan-programs/search`,
   `case-studies/search`, `tax_rulesets/search`,
   `invoice_registrants/search`, `am/programs/active_v2`, `am/audit-log`,
   `bids/search`, `enforcement-cases/search`. Reuses
   `apply_fields_filter()` already in tree — no new module needed.
2. **Wire `?compact=true` on `/v1/am/audit-log`** (high `_meta` + per-row
   field-name redundancy) and `/v1/tax_rulesets/search` (`_disclaimer`
   boilerplate). These are the two endpoints whose envelope ratio is
   highest relative to row payload.
3. **Defensive**: `/v1/exclusions/rules` is the single biggest blast radius
   (120KB, no paging) — add `?limit/offset` before `?fields=`. Currently
   the entire 181-row table goes over the wire on every call.
4. **Out of scope for compact/partial**: error envelopes (already minimal),
   `/v1/intelligence/precomputed/query`, `/v1/calendar/deadlines`, and the
   `/v1/am/pack_*` cohort packs are precomputed snapshots whose envelope
   is content, not boilerplate.

## Full size table (n=182, sorted: 200 by size desc, then non-200)

The full per-endpoint table is preserved at
`tmp_audit_w28.json` (raw measurements) and reproduced below.

<details>
<summary>Full table (click to expand)</summary>

| size B | status | depth | arr_max | arr_count | ms | method | path |
|---:|---:|---:|---:|---:|---:|:---|:---|
| 119388 | 200 | 4 | 181 | 365 | 105 | GET | /v1/exclusions/rules |
| 57480 | 200 | 3 | 20 | 1 | 56 | GET | /v1/loan-programs/search |
| 40815 | 200 | 4 | 20 | 53 | 59 | GET | /v1/case-studies/search |
| 32321 | 200 | 8 | 20 | 45 | 159 | GET | /v1/tax_rulesets/search |
| 30974 | 200 | 3 | 50 | 1 | 190 | GET | /v1/invoice_registrants/search |
| 28947 | 200 | 3 | 50 | 2 | 744 | GET | /v1/am/programs/active_v2 |
| 24879 | 200 | 3 | 50 | 1 | 375 | GET | /v1/am/audit-log |
| 24831 | 200 | 3 | 20 | 1 | 81 | GET | /v1/bids/search |
| 23285 | 200 | 4 | 20 | 21 | 79 | GET | /v1/enforcement-cases/search |
| 22350 | 200 | 4 | 20 | 101 | 1732 | GET | /v1/programs/search |
| 19781 | 200 | 4 | 20 | 21 | 302 | GET | /v1/laws/search |
| 17264 | 200 | 3 | 20 | 1 | 1526 | GET | /v1/enforcement-cases/details/search |
| 15048 | 200 | 4 | 20 | 21 | 159 | GET | /v1/court-decisions/search |
| 14669 | 200 | 4 | 10 | 5 | 418 | GET | /v1/am/pack_real_estate |
| 13932 | 200 | 3 | 20 | 2 | 598 | GET | /v1/am/acceptance_stats |
| 11556 | 200 | 5 | 15 | 47 | 977 | GET | /v1/am/gx_programs |
| 10995 | 200 | 4 | 10 | 5 | 466 | GET | /v1/am/pack_manufacturing |
| 10092 | 200 | 4 | 10 | 5 | 1993 | GET | /v1/am/pack_construction |
| 9820 | 200 | 3 | 30 | 1 | 1741 | GET | /v1/calendar/deadlines |
| 9167 | 200 | 3 | 20 | 2 | 377 | GET | /v1/am/active_at |
| 8021 | 200 | 3 | 20 | 3 | 599 | GET | /v1/am/by_law |
| 7415 | 200 | 5 | 10 | 12 | 71 | GET | /v1/am/mutual_plans |
| 7256 | 200 | 5 | 10 | 3 | 173 | GET | /v1/am/loans |
| 5767 | 200 | 3 | 20 | 2 | 169 | GET | /v1/am/certifications |
| 4606 | 200 | 3 | 20 | 2 | 235 | GET | /v1/am/tax_incentives |
| 4203 | 200 | 4 | 10 | 22 | 1369 | POST | /v1/programs/prescreen |
| 3606 | 200 | 3 | 5 | 9 | 2621 | GET | /v1/intelligence/precomputed/query |
| 2081 | 200 | 3 | 9 | 1 | 6008 | GET | /v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code} |
| 1705 | 200 | 3 | 9 | 1 | 204 | GET | /v1/am/data-freshness |
| 1528 | 200 | 3 | 30 | 1 | 223 | GET | /v1/stats/usage |
| 1513 | 200 | 3 | 2 | 3 | 233 | GET | /v1/am/law_article |
| 1469 | 200 | 3 | 1 | 4 | 26 | GET | /v1/am/tax_rule |
| 1462 | 200 | 3 | 1 | 2 | 758 | GET | /v1/am/open_programs |
| 1372 | 200 | 3 | 3 | 9 | 7619 | GET | /v1/am/related/{program_id} |
| 1306 | 200 | 3 | 8 | 2 | 69 | GET | /v1/am/static |
| 1133 | 200 | 3 | 4 | 3 | 72 | GET | /v1/am/annotations/{entity_id} |
| 1107 | 200 | 3 | 0 | 0 | 1340 | GET | /v1/stats/freshness |
| 1091 | 200 | 2 | 0 | 0 | 1866 | GET | /v1/meta |
| 1028 | 200 | 0 | 0 | 0 | 70 | GET | /v1/corrections/feed |
| 1023 | 200 | 3 | 3 | 3 | 44 | GET | /v1/am/provenance/{entity_id} |
| 907 | 200 | 3 | 1 | 4 | 52 | GET | /v1/am/enforcement |
| 854 | 200 | 3 | 0 | 0 | 2663 | GET | /v1/am/health/deep |
| 737 | 200 | 3 | 5 | 2 | 42 | GET | /v1/am/example_profiles |
| 716 | 200 | 3 | 0 | 5 | 536 | GET | /v1/discover/related/{entity_id} |
| 643 | 200 | 3 | 5 | 1 | 379 | GET | /v1/health/data |
| 635 | 200 | 3 | 9 | 1 | 489 | GET | /v1/staleness |
| 558 | 200 | 3 | 1 | 1 | 136 | GET | /v1/corrections |
| 318 | 200 | 3 | 1 | 1 | 107 | GET | /v1/trust/section52 |
| 308 | 200 | 1 | 0 | 0 | 80 | GET | /v1/usage |
| 269 | 200 | 2 | 0 | 1 | 241 | GET | /v1/advisors/match |
| 243 | 200 | 1 | 0 | 0 | 309 | GET | /v1/stats/coverage |
| 241 | 200 | 1 | 0 | 0 | 72 | POST | /v1/device/authorize |
| 238 | 200 | 1 | 0 | 0 | 106 | POST | /v1/integrations/slack |
| 230 | 200 | 2 | 0 | 1 | 5935 | GET | /v1/stats/confidence |
| 199 | 200 | 2 | 0 | 0 | 38 | GET | /v1/health/sla |
| 140 | 200 | 1 | 0 | 0 | 151 | GET | /v1/ping |
| 58 | 200 | 0 | 0 | 0 | 502 | GET | /v1/integrations/excel |
| 42 | 200 | 1 | 0 | 0 | 72 | GET | /v1/meta/corpus_snapshot |
| 21 | 200 | 2 | 0 | 1 | 62 | GET | /v1/testimonials |
| 18 | 200 | 1 | 0 | 0 | 59 | GET | /readyz |
| 15 | 200 | 1 | 0 | 0 | 97 | GET | /healthz |
| skip | timeout |  |  |  | 15000 | GET | /v1/stats/data_quality |
| 2172 | 422 |  |  |  | 32 | POST | /v1/advisors/signup |
| 1658 | 422 |  |  |  | 50 | GET | /v1/am/enums/{enum_name} |
| 1585 | 422 |  |  |  | 204 | POST | /v1/privacy/deletion_request |
| 1496 | 422 |  |  |  | 84 | POST | /v1/corrections |
| 1470 | 422 |  |  |  | 53 | POST | /v1/widget/signup |
| 1341 | 422 |  |  |  | 120 | POST | /v1/privacy/disclosure_request |
| 1290 | 422 |  |  |  | 36 | POST | /v1/audit/workpaper |
| 1287 | 422 |  |  |  | 38 | POST | /v1/audit/batch_evaluate |
| 1275 | 422 |  |  |  | 46 | POST | /v1/billing/refund_request |
| 1259 | 422 |  |  |  | 51 | POST | /v1/integrations/kintone/connect |
| 1248 | 422 |  |  |  | 35 | POST | /v1/me/saved_searches |
| 1203 | 422 |  |  |  | 29 | POST | /v1/me/saved_searches/{saved_id}/sheet |
| 1072 | 422 |  |  |  | 28 | POST | /v1/device/complete |
| 1057 | 422 |  |  |  | 54 | POST | /v1/me/recurring/slack |
| 1051 | 422 |  |  |  | 44 | POST | /v1/compliance/subscribe |
| 1045 | 422 |  |  |  | 41 | POST | /v1/billing/checkout |
| 1043 | 422 |  |  |  | 46 | POST | /v1/me/courses |
| 1041 | 422 |  |  |  | 45 | POST | /v1/am/dd_export |
| 1041 | 422 |  |  |  | 3923 | POST | /v1/device/token |
| 1035 | 422 |  |  |  | 41 | POST | /v1/me/watches |
| 1026 | 422 |  |  |  | 23 | POST | /v1/me/testimonials |
| 1026 | 422 |  |  |  | 21 | POST | /v1/me/webhooks |
| 1012 | 422 |  |  |  | 28 | GET | /v1/advisors/{advisor_id}/dashboard-data |
| 1012 | 422 |  |  |  | 32 | POST | /v1/advisors/verify-houjin/{advisor_id} |
| 991 | 422 |  |  |  | 29 | DELETE | /v1/me/testimonials/{testimonial_id} |
| 991 | 422 |  |  |  | 44 | GET | /v1/me/saved_searches/{saved_id}/results.xlsx |
| 989 | 422 |  |  |  | 34 | DELETE | /v1/me/client_profiles/{profile_id} |
| 987 | 422 |  |  |  | 16 | GET | /v1/me/webhooks/{webhook_id}/deliveries |
| 986 | 422 |  |  |  | 49 | GET | /v1/me/recurring/quarterly/{year}/{quarter} |
| 986 | 422 |  |  |  | 41 | GET | /v1/me/saved_searches/{saved_id}/results |
| 983 | 422 |  |  |  | 39 | DELETE | /v1/me/alerts/subscriptions/{sub_id} |
| 982 | 422 |  |  |  | 26 | POST | /v1/me/webhooks/{webhook_id}/test |
| 981 | 422 |  |  |  | 35 | DELETE | /v1/me/saved_searches/{saved_id} |
| 980 | 422 |  |  |  | 35 | PATCH | /v1/me/saved_searches/{saved_id} |
| 979 | 422 |  |  |  | 28 | DELETE | /v1/me/webhooks/{webhook_id} |
| 974 | 422 |  |  |  | 50 | DELETE | /v1/me/watches/{watch_id} |
| 974 | 422 |  |  |  | 25 | GET | /v1/am/provenance/fact/{fact_id} |
| 972 | 422 |  |  |  | 29 | GET | /v1/loan-programs/{loan_id} |
| 971 | 422 |  |  |  | 52 | GET | /v1/audit/cite_chain/{ruleset_id} |
| 965 | 422 |  |  |  | 94 | GET | /v1/subscribers/unsubscribe |
| 960 | 422 |  |  |  | 46 | POST | /v1/email/unsubscribe |
| 959 | 422 |  |  |  | 44 | GET | /v1/email/unsubscribe |
| 955 | 422 |  |  |  | 30 | GET | /v1/signup/verify |
| 953 | 422 |  |  |  | 31 | GET | /v1/houjin/{bangou} |
| 840 | 422 |  |  |  | 52 | POST | /v1/integrations/kintone/sync |
| 840 | 422 |  |  |  | 45 | POST | /v1/me/recurring/email_course/start |
| 839 | 422 |  |  |  | 77 | POST | /v1/advisors/report-conversion |
| 838 | 422 |  |  |  | 97 | POST | /v1/tax_rulesets/evaluate |
| 837 | 422 |  |  |  | 43 | POST | /v1/compliance/stripe-checkout |
| 831 | 422 |  |  |  | 34 | POST | /v1/billing/keys/from-checkout |
| 828 | 422 |  |  |  | 63 | POST | /v1/am/validate |
| 827 | 422 |  |  |  | 38 | POST | /v1/evidence/packets/query |
| 827 | 422 |  |  |  | 43 | POST | /v1/me/client_profiles/bulk_import |
| 826 | 422 |  |  |  | 25 | POST | /v1/funding_stack/check |
| 826 | 422 |  |  |  | 71 | POST | /v1/me/alerts/subscribe |
| 825 | 422 |  |  |  | 364 | POST | /v1/cost/preview |
| 824 | 422 |  |  |  | 111 | POST | /v1/am/dd_batch |
| 823 | 422 |  |  |  | 132 | POST | /v1/court-decisions/by-statute |
| 823 | 422 |  |  |  | 38 | POST | /v1/exclusions/check |
| 821 | 422 |  |  |  | 26 | POST | /v1/me/clients/bulk_evaluate |
| 821 | 422 |  |  |  | 85 | POST | /v1/programs/batch |
| 819 | 422 |  |  |  | 28 | POST | /v1/advisors/track |
| 819 | 422 |  |  |  | 45 | POST | /v1/billing/portal |
| 819 | 422 |  |  |  | 70 | POST | /v1/citations/verify |
| 815 | 422 |  |  |  | 52 | POST | /v1/integrations/kintone |
| 807 | 422 |  |  |  | 38 | POST | /v1/feedback |
| 806 | 422 |  |  |  | 28 | POST | /v1/session |
| 806 | 422 |  |  |  | 807 | POST | /v1/subscribers |
| 801 | 422 |  |  |  | 36 | POST | /v1/signup |
| 664 | 400 |  |  |  | 29 | GET | /v1/compliance/verify/{verification_token} |
| 664 | 400 |  |  |  | 55 | POST | /v1/compliance/unsubscribe/{unsubscribe_token} |
| 656 | 404 |  |  |  | 48 | GET | /v1/am/static/{resource_id} |
| 647 | 401 |  |  |  | 34 | GET | /v1/calendar/deadlines.ics |
| 642 | 404 |  |  |  | 28 | GET | /v1/court-decisions/{unified_id} |
| 629 | 401 |  |  |  | 39 | GET | /v1/audit/snapshot_attestation |
| 628 | 404 |  |  |  | 95 | GET | /v1/case-studies/{case_id} |
| 626 | 404 |  |  |  | 40 | GET | /v1/laws/{unified_id}/related-programs |
| 621 | 404 |  |  |  | 26 | GET | /v1/enforcement-cases/{case_id} |
| 618 | 404 |  |  |  | 60 | GET | /v1/am/programs/{program_id}/sources |
| 613 | 401 |  |  |  | 39 | GET | /v1/me/alerts/subscriptions |
| 610 | 404 |  |  |  | 27 | GET | /v1/cross_source/{entity_id} |
| 609 | 404 |  |  |  | 28 | GET | /v1/bids/{unified_id} |
| 609 | 404 |  |  |  | 23 | GET | /v1/laws/{unified_id} |
| 607 | 404 |  |  |  | 50 | GET | /v1/programs/{unified_id} |
| 605 | 404 |  |  |  | 33 | GET | /v1/am/example_profiles/{profile_id} |
| 605 | 401 |  |  |  | 42 | GET | /v1/me/client_profiles |
| 603 | 401 |  |  |  | 43 | DELETE | /v1/me/courses/{course_slug} |
| 603 | 401 |  |  |  | 31 | GET | /v1/me/saved_searches |
| 602 | 401 |  |  |  | 161 | GET | /v1/widget/enum_values |
| 602 | 401 |  |  |  | 60 | GET | /v1/widget/search |
| 599 | 401 |  |  |  | 28 | GET | /v1/me/courses |
| 599 | 401 |  |  |  | 47 | POST | /v1/me/cap |
| 598 | 503 |  |  |  | 66 | GET | /v1/meta/freshness |
| 595 | 401 |  |  |  | 52 | GET | /v1/me/billing_history |
| 595 | 401 |  |  |  | 58 | GET | /v1/me/dashboard |
| 595 | 401 |  |  |  | 36 | GET | /v1/me/tool_recommendation |
| 595 | 401 |  |  |  | 31 | GET | /v1/me/usage_by_tool |
| 591 | 401 |  |  |  | 31 | GET | /v1/me/webhooks |
| 589 | 401 |  |  |  | 36 | GET | /v1/me/watches |
| 586 | 403 |  |  |  | 22 | POST | /v1/session/logout |
| 585 | 401 |  |  |  | 40 | GET | /v1/billing/client_tag_breakdown |
| 571 | 401 |  |  |  | 22 | POST | /v1/integrations/google/start |
| 553 | 503 |  |  |  | 80 | GET | /v1/widget/{key_id}/usage |
| 529 | 401 |  |  |  | 38 | DELETE | /v1/me/keys/children/{child_id} |
| 529 | 401 |  |  |  | 59 | GET | /v1/me |
| 529 | 401 |  |  |  | 47 | GET | /v1/me/keys/children |
| 529 | 401 |  |  |  | 49 | GET | /v1/me/usage |
| 529 | 401 |  |  |  | 41 | GET | /v1/me/usage.csv |
| 529 | 401 |  |  |  | 47 | POST | /v1/me/billing-portal |
| 529 | 401 |  |  |  | 32 | POST | /v1/me/keys/children |
| 529 | 401 |  |  |  | 48 | POST | /v1/me/rotate-key |
| 509 | 401 |  |  |  | 30 | DELETE | /v1/integrations/google |
| 509 | 401 |  |  |  | 29 | GET | /v1/integrations/google/status |
| 509 | 401 |  |  |  | 50 | POST | /v1/integrations/email/connect |
| 309 | 404 |  |  |  | 167 | GET | /v1/source_manifest/{program_id} |
| 201 | 404 |  |  |  | 38 | GET | /v1/audit/seals/{seal_id} |
| 198 | 404 |  |  |  | 159 | GET | /v1/evidence/packets/{subject_kind}/{subject_id} |
| 70 | 422 |  |  |  | 49 | GET | /v1/tax_rulesets/{unified_id} |
| 64 | 422 |  |  |  | 33 | GET | /v1/invoice_registrants/{invoice_registration_number} |
| 54 | 422 |  |  |  | 31 | GET | /v1/am/group_graph |

</details>
