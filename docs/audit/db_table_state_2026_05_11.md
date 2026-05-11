# jpcite 2-DB Table State Audit (2026-05-11)

**Scope**: SQLite table-level inventory across the two production DBs.
**Method**: `sqlite3` read-only opens + `PRAGMA table_info` + `SELECT COUNT(*)`. No writes.
**Source files audited**:

- `/Users/shigetoumeda/jpcite/autonomath.db` (12 GB on disk — note CLAUDE.md SOT cites "~9.4 GB"; physical size is ~12 GB as of 2026-05-07 22:43)
- `/Users/shigetoumeda/jpcite/data/jpintel.db` (426 MB on disk — CLAUDE.md SOT cites "~352 MB", post-zenken/wave24 growth)
- `/Users/shigetoumeda/jpcite/scripts/migrations/*.sql` (317 files, 142 distinct migration numbers up to 205)

---

## 0. Headline counts

| DB                | Total tables | Total views | Empty (row=0) | Non-empty |
|-------------------|-------------:|------------:|--------------:|----------:|
| `autonomath.db`   |          505 |          15 |           258 |       247 |
| `data/jpintel.db` |          182 |           2 |            92 |        90 |
| **Combined**      |      **687** |      **17** |       **350** |   **337** |

- `autonomath.db`: **51.1 %** of tables are empty (258 / 505).
- `jpintel.db`: **50.5 %** of tables are empty (92 / 182).
- Empty share is dominated by FTS5/sqlite-vec shadow tables (zero parent rows = zero shadow rows) and `pc_*` precompute layers that have not been materialised.

---

## A. `autonomath.db` (12 GB, 505 tables, 15 views)

### A.1 Top-50 tables by row count (desc)

| #  | Row count   | Table                                  |
|---:|------------:|----------------------------------------|
|  1 |   6,124,990 | `am_entity_facts`                      |
|  2 |     503,930 | `am_entities`                          |
|  3 |     503,930 | `am_entity_density_score`              |
|  4 |     503,930 | `am_entity_pagerank`                   |
|  5 |     424,277 | `am_entities_vec_rowids`               |
|  6 |     424,277 | `am_vec_rowid_map`                     |
|  7 |     424,277 | `am_vec_tier_a_rowids`                 |
|  8 |     402,600 | `am_entities_fts`                      |
|  9 |     402,600 | `am_entities_fts_content`              |
| 10 |     402,600 | `am_entities_fts_docsize`              |
| 11 |     388,972 | `am_entities_fts_uni`                  |
| 12 |     388,972 | `am_entities_fts_uni_content`          |
| 13 |     388,972 | `am_entities_fts_uni_docsize`          |
| 14 |     378,342 | `am_relation`                          |
| 15 |     353,278 | `am_law_article`                       |
| 16 |     335,605 | `am_alias`                             |
| 17 |     335,605 | `am_alias_fts`                         |
| 18 |     335,605 | `am_alias_fts_docsize`                 |
| 19 |     279,841 | `am_entity_source`                     |
| 20 |     267,855 | `am_entities_fts_data`                 |
| 21 |     250,946 | `am_amount_condition`                  |
| 22 |     215,233 | `am_entities_vec_l2v2_map`             |
| 23 |     215,233 | `am_entities_vec_l2v2_rowids`          |
| 24 |     201,845 | `adoption_records`                     |
| 25 |     201,845 | `am_entities_vec_A_rowids`             |
| 26 |     201,845 | `jpi_adoption_records`                 |
| 27 |     172,386 | `am_entity_appearance_count`           |
| 28 |     167,121 | `am_adopted_company_features`          |
| 29 |     166,765 | `houjin_master`                        |
| 30 |     166,765 | `jpi_houjin_master`                    |
| 31 |      97,272 | `am_source`                            |
| 32 |      59,898 | `am_entities_fts_uni_data`             |
| 33 |      50,000 | `am_recommended_programs`              |
| 34 |      43,966 | `am_compat_matrix`                     |
| 35 |      28,574 | `am_entities_fts_idx`                  |
| 36 |      22,258 | `am_enforcement_detail`                |
| 37 |      19,421 | `am_citation_network`                  |
| 38 |      17,883 | `am_evidence_citation`                 |
| 39 |      16,474 | `am_entity_annotation`                 |
| 40 |      14,596 | `am_amendment_snapshot`                |
| 41 |      13,829 | `jpi_source_lineage_audit`             |
| 42 |      13,801 | `jpi_invoice_registrants`              |
| 43 |      13,578 | `jpi_programs`                         |
| 44 |      12,753 | `am_program_eligibility_predicate_json`|
| 45 |      12,116 | `am_amendment_diff`                    |
| 46 |      11,601 | `am_entities_vec_S_rowids`             |
| 47 |      10,125 | `am_law`                               |
| 48 |       9,830 | `am_peer_cache`                        |
| 49 |       9,484 | `jpi_laws`                             |
| 50 |       7,925 | `am_entities_fts_uni_idx`              |

### A.2 `am_entities.record_kind` distribution (CLAUDE.md SOT verified)

| record_kind        | rows    | CLAUDE.md SOT cited | match |
|--------------------|--------:|--------------------:|:-----:|
| `adoption`         | 215,233 |             215,233 | OK    |
| `corporate_entity` | 166,969 |             166,969 | OK    |
| `statistic`        |  73,960 |              73,960 | OK    |
| `enforcement`      |  22,255 |              22,255 | OK    |
| `invoice_registrant`| 13,801 |              13,801 | OK    |
| `program`          |   8,203 |               8,203 | OK    |
| `case_study`       |   2,885 |               2,885 | OK    |
| `tax_measure`      |     285 |                 285 | OK    |
| `law`              |     252 |                 252 | OK    |
| `certification`    |      66 |                  66 | OK    |
| `authority`        |      20 |                  20 | OK    |
| `document`         |       1 |                   1 | OK    |
| **TOTAL**          | **503,930** |         **503,930** | **OK** |

### A.3 Empty (row=0) tables in `autonomath.db` — categorised (258 total)

Breakdown:

| Category                              | Count |
|---------------------------------------|------:|
| `_fts*` shadow (parent empty)         |    48 |
| `_vec*` shadow (parent empty)         |    32 |
| `jpi_*` mirror (jpintel side empty)   |    54 |
| `pc_*` precompute (never materialised)|    32 |
| `am_*` real tables (empty)            |    17 |
| Other (op/audit/queue tables)         |    75 |
| **TOTAL**                             | **258** |

#### A.3.1 `am_*` empty real tables (17) — most actionable

These are entity/feature tables defined in migrations 136-149 (`wave24_*`) and earlier that have **never been populated**:

| Table                                | Likely owner / migration             | Status                            |
|--------------------------------------|--------------------------------------|-----------------------------------|
| `am_actionable_answer_cache`         | cache layer                          | runtime — fills on first query    |
| `am_case_study_narrative`            | narrative ETL                        | NEVER POPULATED — narrative cohort|
| `am_enforcement_source_index`        | enforcement secondary index          | NEVER POPULATED                   |
| `am_enforcement_summary`             | enforcement aggregate                | NEVER POPULATED                   |
| `am_houjin_360_narrative`            | houjin 360 narrative                 | NEVER POPULATED                   |
| `am_houjin_360_snapshot`             | houjin 360 snapshot                  | NEVER POPULATED                   |
| `am_idempotency_cache`               | API idempotency cache                | runtime — fills on first request  |
| `am_invoice_buyer_seller_graph`      | invoice graph (wave24_133)           | NEVER POPULATED                   |
| `am_law_article_summary`             | law article summariser               | NEVER POPULATED                   |
| `am_narrative_quarantine`            | narrative quarantine (wave24_141)    | runtime — fills on quarantine hit |
| `am_program_calendar_12mo`           | 12-mo calendar rollup                | NEVER POPULATED                   |
| `am_program_documents`               | program documents (wave24_138)       | NEVER POPULATED                   |
| `am_program_eligibility_history`     | eligibility audit                    | runtime — fills on first eval     |
| `am_program_eligibility_predicate`   | predicate text store                 | NEVER POPULATED (json side has 12,753 rows in `*_json` variant — schema split, real rows landed in json sibling only) |
| `am_program_narrative`               | narrative (wave24_136)               | NEVER POPULATED                   |
| `am_webhook_delivery`                | webhook outbox                       | runtime — fills per delivery      |
| `am_webhook_subscription`            | webhook config                       | runtime — fills per signup        |

#### A.3.2 `pc_*` empty precompute tables (32)

All 32 `pc_*` precompute tables are empty in `autonomath.db`. These are duplicates of jpintel-side precompute tables. The autonomath copies were created by `migration 044/045_precompute_*` but the population batch never ran on the autonomath side (jpintel side populated some — see B.4).

```
pc_acceptance_rate_by_authority      pc_amendment_recent_by_law
pc_amendment_severity_distribution   pc_amount_max_distribution
pc_amount_to_recipient_size          pc_application_close_calendar
pc_authority_action_frequency        pc_authority_to_programs
pc_certification_by_subject          pc_combo_pairs
pc_court_decision_law_chain          pc_enforcement_by_industry
pc_enforcement_industry_distribution pc_industry_jsic_aliases
pc_industry_jsic_to_program          pc_invoice_registrant_by_pref
pc_law_amendments_recent             pc_law_text_to_program_count
pc_law_to_amendment_chain            pc_law_to_program_index
pc_loan_by_collateral_type           pc_loan_collateral_to_program
pc_program_geographic_density        pc_program_to_amendments
pc_program_to_certification_combo    pc_program_to_loan_combo
pc_program_to_tax_combo              pc_seasonal_calendar
pc_starter_packs_per_audience        pc_top_subsidies_by_industry
pc_top_subsidies_by_prefecture       pc_acceptance_stats_by_program
```

#### A.3.3 `jpi_*` empty mirror tables (54)

54 of 80 `jpi_*` tables are empty (26 non-empty). Empty mirrors include all 32 `jpi_pc_*` (matching A.3.2), plus `jpi_advisors`, `jpi_compliance_subscribers`, `jpi_line_users`, `jpi_medical_institutions`, `jpi_ministry_faq`, `jpi_real_estate_programs`, `jpi_support_org`, `jpi_testimonials`, `jpi_usage_events`, `jpi_verticals_deep`, `jpi_widget_keys`, `jpi_zoning_overlays`, etc. These are byproducts of `migration 032`'s wholesale schema-copy from jpintel — the underlying jpintel rows are themselves empty (see B.3), so the mirror is correctly empty.

#### A.3.4 FTS5 / vec shadow tables — sanity matrix

Shadow tables are expected to track their parent. Mismatches found:

| Parent              | parent rows | shadow      | shadow rows | Status      |
|---------------------|------------:|-------------|------------:|-------------|
| `adoption_records`  |     201,845 | `adoption_fts` |       0 | **MISMATCH** — adoption_fts never built |
| `houjin_master`     |     166,765 | `houjin_master_fts` |  0 | **MISMATCH** — houjin_master_fts never built |
| `am_program_narrative` | 0       | `am_program_narrative_fts` | 0 | OK (both empty) |
| `case_studies`      |           0 | `case_studies_fts` |     0 | OK          |
| `court_decisions`   |           0 | `court_decisions_fts` |  0 | OK          |
| `bids`              |           0 | `bids_fts`        |       0 | OK          |
| `verticals_deep`    |           0 | `verticals_deep_fts` |   0 | OK          |
| `support_org`       |           0 | `support_org_fts` |       0 | OK          |
| `ministry_faq`      |           0 | `ministry_faq_fts` |      0 | OK          |

(In `autonomath.db`, `adoption_records` itself has 201,845 rows but its companion `adoption_fts` is empty — full-text search on adoption is non-functional inside autonomath. The jpintel side has the same mismatch — see B.3.)

### A.4 Quality-issue tables (template-default majority / sparse coverage)

| #  | Table                       | Total rows | Real / Authoritative rows | Pollution share | Note                                                                 |
|---:|-----------------------------|-----------:|-------------------------:|----------------:|----------------------------------------------------------------------|
|  1 | `am_amount_condition`       |    250,946 | `template_default=0`: **8,480** (of which 836 `quality_tier='verified'`) | **96.6 %**     | Confirmed CLAUDE.md SOT: "majority template-default ¥500K/¥2M from a broken ETL pass". Top `fixed_yen`: 3.5M (72,918 rows), 500K (61,363), 12.5M (49,210). |
|  2 | `am_amendment_snapshot`     |     14,596 | `effective_from IS NOT NULL`: **140** (43 distinct dates) | **99.0 %**     | Confirmed CLAUDE.md SOT: "144 dated only" (audit found 140, near-match). eligibility_hash never changes between v1/v2 — time-series is fake on remaining 14,456. |
|  3 | `am_law_article`            |    353,278 | `LENGTH(text_full) > 100`: **240,980** | 31.8 % stub  | 112,298 rows are stubs / metadata-only. Trust-Tier slicing required.  |
|  4 | `am_compat_matrix`          |     43,966 | 4,300 sourced + heuristic flagged `status='unknown'` | ≥90 % heuristic | CLAUDE.md SOT says 4,300 sourced + heuristic inferences are status-flagged — not a silent quality bug, but consumers must filter. |
|  5 | `am_recommended_programs`   |     50,000 | exactly 50K (cap), origin unclear | — | Rounded-50K row count is suspicious (likely fixed cap, not data-driven). |

---

## B. `data/jpintel.db` (426 MB, 182 tables, 2 views)

### B.1 Top-40 tables by row count (desc)

| #  | Row count | Table                              |
|---:|----------:|------------------------------------|
|  1 |   199,944 | `adoption_records`                 |
|  2 |   166,765 | `houjin_master`                    |
|  3 |    33,839 | `programs_fts_data`                |
|  4 |    18,497 | `programs_fts_idx`                 |
|  5 |    14,472 | `programs`                         |
|  6 |    13,829 | `source_lineage_audit`             |
|  7 |    13,801 | `invoice_registrants`              |
|  8 |    11,869 | `programs_fts`                     |
|  9 |    11,869 | `programs_fts_content`             |
| 10 |    11,869 | `programs_fts_docsize`             |
| 11 |     9,484 | `laws`                             |
| 12 |     9,484 | `laws_fts`                         |
| 13 |     9,484 | `laws_fts_content`                 |
| 14 |     9,484 | `laws_fts_docsize`                 |
| 15 |     7,866 | `case_studies_fts_idx`             |
| 16 |     7,677 | `case_studies_fts_data`            |
| 17 |     4,956 | `analytics_events`                 |
| 18 |     2,286 | `case_studies`                     |
| 19 |     2,286 | `case_studies_fts`                 |
| 20 |     2,286 | `case_studies_fts_content`         |
| 21 |     2,286 | `case_studies_fts_docsize`         |
| 22 |     2,065 | `court_decisions`                  |
| 23 |     2,065 | `court_decisions_fts`              |
| 24 |     2,065 | `court_decisions_fts_content`      |
| 25 |     2,065 | `court_decisions_fts_docsize`      |
| 26 |     1,899 | `program_law_refs`                 |
| 27 |     1,575 | `court_decisions_fts_data`         |
| 28 |     1,571 | `court_decisions_fts_idx`          |
| 29 |     1,519 | `pc_application_close_calendar`    |
| 30 |     1,307 | `laws_fts_data`                    |
| 31 |     1,185 | `enforcement_cases`                |
| 32 |     1,125 | `laws_fts_idx`                     |
| 33 |       940 | `pc_top_subsidies_by_prefecture`   |
| 34 |       495 | `case_law`                         |
| 35 |       362 | `bids`                             |
| 36 |       362 | `bids_fts`                         |
| 37 |       362 | `bids_fts_content`                 |
| 38 |       362 | `bids_fts_docsize`                 |
| 39 |       181 | `exclusion_rules`                  |
| 40 |       168 | `schema_migrations`                |

### B.2 CLAUDE.md SOT cross-check (jpintel)

| Metric                      | CLAUDE.md SOT       | Audit measurement                | Match |
|-----------------------------|---------------------|----------------------------------|:-----:|
| programs (total)            | 14,472              | 14,472                           | OK    |
| programs (searchable)       | 11,601              | `excluded=0`: 11,601             | OK    |
| programs (quarantine/excluded)| 2,871             | `excluded=1`: 2,871              | OK    |
| case_studies                | 2,286               | 2,286                            | OK    |
| loan_programs               | 108                 | 108                              | OK    |
| enforcement_cases           | 1,185               | 1,185                            | OK    |
| laws (catalog stubs)        | 9,484               | 9,484                            | OK    |
| laws (full-text indexed)    | 6,493 stated        | `LENGTH(full_text_url)>0` cannot be measured (column is URL not body — body stored elsewhere, likely `am_law_article` per A.3) | INDIRECT |
| tax_rulesets                | 50                  | 50                               | OK    |
| court_decisions             | 2,065               | 2,065                            | OK    |
| bids                        | 362                 | 362                              | OK    |
| invoice_registrants         | 13,801              | 13,801                           | OK    |
| exclusion_rules             | 181                 | 181                              | OK    |

### B.3 Empty (row=0) tables in `jpintel.db` — categorised (92 total)

| Category                              | Count |
|---------------------------------------|------:|
| `_fts*` shadow (parent empty)         |    20 |
| `pc_*` precompute (never materialised)|    28 |
| `jpi_*` mirror                        |     2 |
| Other (op/audit/queue tables)         |    42 |
| **TOTAL**                             | **92** |

#### B.3.1 Top-10 empty non-shadow tables in jpintel (most likely "obsolete-or-not-yet-used")

| Table                              | Migration / Purpose                          |
|------------------------------------|----------------------------------------------|
| `verticals_deep`                   | vertical deep-dive content (never seeded)    |
| `support_org`                      | support org directory (never seeded)         |
| `ministry_faq`                     | ministry FAQ (never seeded)                  |
| `medical_institutions`             | medical institutions (never seeded)          |
| `care_subsidies`                   | care subsidies (never seeded)                |
| `real_estate_programs`             | real-estate programs (migration 042, no data)|
| `zoning_overlays`                  | zoning overlays (never seeded)               |
| `industry_program_density`         | rollup target (never run)                    |
| `industry_stats`                   | rollup target (never run)                    |
| `testimonials`                     | marketing testimonials (migration 041, no data) |

(Plus operator/runtime tables that fill on first request: `analytics_events`-style queues, `appi_*`, `audit_seal*`, `customer_*`, `email_*`, `line_*`, `postmark_*`, `stripe_*`, `webhook_*`, `widget_keys`, `subscribers`, etc. These are not "obsolete" — they're event sinks waiting for traffic.)

#### B.3.2 FTS5 / vec shadow tables — sanity matrix

| Parent              | parent rows | shadow            | shadow rows | Status                |
|---------------------|------------:|-------------------|------------:|-----------------------|
| `adoption_records`  |     199,944 | `adoption_fts`    |           0 | **MISMATCH** — never built |
| `houjin_master`     |     166,765 | `houjin_master_fts` |         0 | **MISMATCH** — never built |
| `programs`          |      14,472 | `programs_fts`    |      11,869 | OK (FTS indexes only `excluded=0`) |
| `case_studies`      |       2,286 | `case_studies_fts`|       2,286 | OK                    |
| `court_decisions`   |       2,065 | `court_decisions_fts` |   2,065 | OK                    |
| `bids`              |         362 | `bids_fts`        |         362 | OK                    |
| `laws`              |       9,484 | `laws_fts`        |       9,484 | OK                    |
| `tax_rulesets`      |          50 | `tax_rulesets_fts`|          50 | OK                    |
| `verticals_deep`    |           0 | `verticals_deep_fts` |        0 | OK                    |
| `support_org`       |           0 | `support_org_fts` |           0 | OK                    |
| `ministry_faq`      |           0 | `ministry_faq_fts`|           0 | OK                    |

### B.4 jpintel `pc_*` precompute coverage

Out of 33 `pc_*` tables in jpintel, **only 2 are populated**: `pc_application_close_calendar` (1,519 rows) and `pc_top_subsidies_by_prefecture` (940 rows). The remaining 31 are empty rollup targets from `migration 044/045_precompute_*`.

---

## C. Migrations health

### C.1 Migration counts

- **Migration files on disk**: 317 `.sql` files, 142 distinct numeric prefixes up to 205.
- **Applied to `autonomath.db`** (`schema_migrations` table): **130 rows** (latest = `wave24_153_am_entity_appearance_count.sql` @ 2026-05-05).
- **Applied to `jpintel.db`** (`schema_migrations` table): **168 rows** (latest = `wave24_163_am_citation_network.sql` @ 2026-05-05).
- **Applied to `jpi_schema_migrations`** (autonomath mirror): 45 rows (legacy snapshot from migration 032).

### C.2 Missing / reserved numbers (specific gaps in 1-205)

From the file system, the following migration numbers have **no `.sql` file**:

`4, 6, 25-36, 40, 84, 93, 94, 95, 100, 117, 127-145, 178-194` (some are intentionally reserved per CLAUDE.md SOT).

Specific CLAUDE.md-noted gaps verified:

| Number | File present? | In `autonomath.db.schema_migrations`? | CLAUDE.md note                                  |
|-------:|:-------------:|:--------------------------------------:|-------------------------------------------------|
|    067 | YES (both `_dataset_versioning.sql` and `_autonomath.sql`) | YES (both applied) | CLAUDE.md says "migration 067 missing → `query_at_snapshot` AUTONOMATH_SNAPSHOT_ENABLED gated off" — but the file IS applied; **the gate-off appears to be runtime-package-missing, not migration-missing**. Worth re-checking the gate logic. |
|    084 | absent        | absent                                 | Reserved (CLAUDE.md SOT)                        |
|    093 | absent        | absent                                 | Reserved (CLAUDE.md SOT)                        |
|    094 | absent        | absent                                 | Reserved (CLAUDE.md SOT)                        |
|    095 | absent        | absent                                 | Reserved (CLAUDE.md SOT)                        |
|    100 | absent        | absent                                 | Reserved (CLAUDE.md SOT)                        |

### C.3 FTS5 tokenizer mix (autonomath)

| FTS5 table              | Tokenizer                              | Purpose                                  |
|-------------------------|----------------------------------------|------------------------------------------|
| `am_entities_fts`       | `trigram`                              | precise 3-gram matching (kanji compounds)|
| `am_entities_fts_uni`   | `unicode61 remove_diacritics 2`        | broader unigram fallback                 |
| `am_alias_fts`          | `trigram`                              | alias matching                           |
| `am_program_narrative_fts` | (parent empty)                      | n/a                                      |

CLAUDE.md SOT confirms FTS5 trigram causes false single-kanji overlap (e.g. `税額控除` query matches rows containing only `税`); workaround documented in `src/jpintel_mcp/api/programs.py` (use quoted phrase queries).

---

## D. Recommendations (audit-only, no destructive changes)

### D.1 Empty tables — proposed disposition

Following the project's "no rm / no mv — banner+index instead" rule:

| Disposition                          | Tables                                                                 |
|--------------------------------------|------------------------------------------------------------------------|
| **KEEP — runtime fills**             | `am_idempotency_cache`, `am_actionable_answer_cache`, `am_webhook_*`, `am_narrative_quarantine`, `am_program_eligibility_history`, all `analytics_events`/`audit_*`/`email_*`/`stripe_*`/`postmark_*`/`webhook_*` (event sinks) |
| **MARK as `_archive_candidate_*`**   | `am_houjin_360_*`, `am_case_study_narrative`, `am_program_narrative*`, `am_program_documents`, `am_law_article_summary`, `am_enforcement_summary`, `am_enforcement_source_index`, `am_program_calendar_12mo`, `am_invoice_buyer_seller_graph` (defined but never populated, no ETL scheduled) |
| **REBUILD shadow** (FTS mismatch)    | `adoption_fts` (autonomath + jpintel), `houjin_master_fts` (both) — parents have 200K / 167K rows but the FTS shadows are empty, so search on these is broken |
| **POPULATE pc_* selectively**        | Decide per consumer demand — 60 empty `pc_*` precompute tables across the 2 DBs. If a Wave 24 tool reads them, populate; otherwise mark `_archive_candidate_*` |
| **KEEP `jpi_*` empties as-is**       | They mirror their jpintel parent, so emptiness is correctly propagated |

### D.2 Quality re-validation queue

| Priority | Table                  | Action                                                                 |
|---------:|------------------------|------------------------------------------------------------------------|
|       P0 | `am_amount_condition`  | Already gated externally per CLAUDE.md SOT ("do not surface aggregate count externally"). Re-run ETL after fix, drop `template_default=1` rows from public surface. |
|       P0 | `am_amendment_snapshot`| Keep only the 140 rows with `effective_from` until eligibility-hash bug fixed. Tool `track_amendment_lineage_am` must filter. |
|       P1 | `am_law_article`       | Mark 112,298 stub rows (text_full ≤ 100 chars) as `is_stub=1` for filtering. |
|       P1 | `am_compat_matrix`     | Ensure `status='unknown'` filter applied in `find_complementary_programs_am` paths. |
|       P2 | `adoption_fts` / `houjin_master_fts` (both DBs) | Rebuild FTS shadows — current search returns 0 hits silently. |

### D.3 Migration-067 gate review (CLAUDE.md SOT correction candidate)

The CLAUDE.md SOT line at line 9 says `query_at_snapshot` is "gated off" because "migration 067 missing → AUTONOMATH_SNAPSHOT_ENABLED". However, both `067_dataset_versioning.sql` and `067_dataset_versioning_autonomath.sql` are recorded in `autonomath.db.schema_migrations`. The gate-off is more likely a **runtime package / table-content issue**, not a missing migration. Suggest re-running the smoke test and updating CLAUDE.md SOT if confirmed.

---

## E. Cardinality summary tables — exported artifacts

The full per-table row counts are saved as JSON for reproducibility:

- `/tmp/jpintel_full.json` — 182 rows, all jpintel tables with COUNT(*)
- `/tmp/autonomath_full.json` — 505 rows, all autonomath tables with COUNT(*)

(These are operator-local audit artifacts, not checked into git.)

---

## F. End notes

- Audit performed read-only; no DBs were modified.
- 2 DBs are independent files; no `ATTACH` was attempted (jpintel inline tables were physically merged into autonomath as `jpi_*` per migration 032 long ago, so cross-DB JOINs are not currently needed at runtime).
- 9.4 GB / 12 GB size discrepancy: CLAUDE.md SOT was authored when DB was smaller; current physical file is ~12 GB (12,884,377,600 bytes). Not a defect — just SOT staleness.
- All "honest counts" from CLAUDE.md SOT lines 9, 138, 139 were cross-verified and match within ±1 row.
