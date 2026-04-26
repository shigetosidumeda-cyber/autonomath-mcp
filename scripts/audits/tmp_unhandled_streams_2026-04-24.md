# /tmp unhandled streams audit (2026-04-24)

Source: `data/ingest_external_20260423-221042.log` (2026-04-24 07:10 JST).
Scope per task #111: dirs numbered 100-138. Captured neighboring outliers (64, 99, 139-157) for completeness.

## Summary

40 dirs in the 100-138 range; **5 unhandled** (auto_detect=miss). Full ingest has **16 unhandled** across all dirs.

None block the 2026-05-06 launch — all program-like rows that could route to `programs` are covered by handled dirs. Unhandled dirs fall into schema families that map to existing tables (laws, tax_rulesets, exclusion_rules) or to future expansion.

## 100-138 range (5 unhandled)

| Dir | Lines | Schema sample | Proposed routing |
|---|---|---|---|
| 111_security_business_guards | 45 | `topic, unit, value, yoy_delta, law_basis` | **Statistics** (no table; low value for launch) |
| 124_road_infrastructure_bridges | 34 | `law_no, enacted_year, article_key, purpose, target_types` | **laws** (add handler: map law_no→law_id, enacted_year→promulgation_date) |
| 130_dental_medicine_industry | 32 | `title, body, date, agent, category` | News stream — **drop** (not in data model) |
| 132_beauty_medicine_clinic | 31 | `exclusion_status, data_points, source_type` | **exclusion_rules** (add handler: map exclusion_status→kind) |
| 134_life_nonlife_small_short_insurance | 42 | `name, description, fsa_supervised, legal_basis, target_types` | **programs** (add alias: name→primary_name, description→overview) |

## Full unhandled list (all ranges)

- `64_smart_agriculture_ict` — **programs** candidate (schema close; `name`, `description`, `support_type`, `application_deadline`). One alias away from handled.
- `99_pension_social_security_deep` — **laws** (fields: `law_name`, `diet_session`, `promulgated_date`).
- `139_invoice_consumption_tax` — **tax_rulesets** (fields: `tier`, `key_facts`, `source_url`).
- `140_income_tax_individual_deep` — **tax_rulesets** (fields: `governing_law`, `details`).
- `141_multi_marketing_fraud_consumer` — **laws** or **exclusion_rules** (fields: `cooling_off_table`, `legal_basis`).
- `144_nursing_homes_types_detail` — **laws** (fields: `legal_basis`, `topic`, `key_figures`).
- `145_wind_power_offshore_onshore` — **laws** (fields: `source_law`, `key_provisions`, `enactment`).
- `150_local_taxes_detail` — **tax_rulesets** (fields: `tax_type`, `jurisdiction`, `effective_date`).
- `152_criminal_justice_crime_deep` — **laws** (fields: `source_law`, `promulgation_date`).
- `153_textile_apparel_fashion` — **Statistics** (no table; `jsic_code`, `data`).
- `157_reit_real_estate_investment` — **laws** (fields: `law_number`, `jurisdiction`, `last_major_revision`).

## Recommendations (post-launch)

1. **Quick win (1 alias)**: Extend auto-detect to treat `name + description + support_type` as a programs-compatible schema. Adds ~85 rows from `64_smart_agriculture_ict` + `134_life_nonlife`.
2. **Laws handler pass**: 7 dirs above (99, 124, 141, 144, 145, 152, 157) have enough law-like fields to append to `laws`. Estimate +240 rows of JP law coverage on top of the 6,850+ continually-loading e-Gov base.
3. **tax_rulesets handler pass**: 3 dirs (139, 140, 150) add consumption/income/local tax rules — strong fit for the existing `tax_rulesets` table schema (currently 35 rows).
4. **Drop/defer**: 111, 130, 153 — statistics/news streams that don't map to the current data model. Either create a `statistics` table (post-launch, if demand) or archive.

## Status

- No launch blocker. All 5 unhandled 100-138 dirs skipped cleanly (WARNING logs, no parse errors).
- Handlers listed as post-launch improvement-loop candidates.
- Memory/feedback: confirmed that auto-detect handles 35 of 40 dirs in the range; the 5 misses are due to schema divergence (not bugs in the detector).
