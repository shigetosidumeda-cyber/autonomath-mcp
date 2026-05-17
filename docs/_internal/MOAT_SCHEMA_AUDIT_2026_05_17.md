# MOAT Schema Audit — wave24_* migrations (2026-05-17)

Read-only audit of the `wave24_*.sql` migration set against the live
`autonomath.db` (14 GB, repo root) and `data/jpintel.db` (427 MB). Run with
PRAGMA `table_list` + `foreign_key_list` only — no `quick_check` /
`integrity_check` on the 14 GB DB (memory `feedback_no_quick_check_on_huge_sqlite`).

Companion to D2 design audit. Counts in §Overview / Wave 50 sections of
`CLAUDE.md` remain authoritative for product framing; this doc captures the
state of the wave24 schema layer only.

## 1. Migration inventory

- Forward migrations: **75** (`scripts/migrations/wave24_*.sql`, excluding
  `*_rollback.sql`).
- Rollback companions: **72**.
- Rollback companions missing (3):
  - `wave24_058_production_gate_status.sql` (jpintel, additive CREATE TABLE)
  - `wave24_182_contributor_trust.sql` (autonomath, 2 CREATE TABLE)
  - `wave24_201_am_houjin_program_portfolio.sql` (autonomath, 1 CREATE TABLE)
- `target_db` headers (`-- target_db: …` on line 1):
  - autonomath: **64**
  - jpintel: **11**
- Header presence is 75/75 — no untyped migrations.

## 2. Live drift report (autonomath.db, 14 GB at repo root)

`autonomath.db` total `am_*` tables: **342**. `am_alias` row count:
**433,057** (up from 335,605 baseline in §Overview).

`schema_migrations` bookkeeping table records **132** total migration ids,
of which **8** are `wave24_*`:

```
wave24_105_audit_seal_key_version.sql
wave24_106_amendment_snapshot_rebuild.sql
wave24_107_am_compat_matrix_visibility.sql
wave24_108_programs_source_verified_at.sql
wave24_109_am_amount_condition_is_authoritative.sql
wave24_153_am_entity_appearance_count.sql
wave24_204_am_amendment_alert_impact.sql
wave24_205_am_segment_view.sql
```

### 2.1 autonomath forward (64 files)

Per-file primary-table existence in `autonomath.db`:

- **APPLIED (table present)**: 23
- **MISSING (table absent)**: 34
- **ALTER / VIEW / secondary-table only (no detectable primary CREATE TABLE
  pattern; verified safe)**: 7

APPLIED (23): `am_5hop_graph`, `am_adopted_company_features`,
`am_amendment_alert_impact`, `am_artifact_templates`,
`am_case_extracted_facts`, `am_citation_network`,
`am_data_quality_snapshot`, `am_entity_appearance_count`,
`am_geo_industry_density`, `am_houjin_360_snapshot`,
`am_houjin_program_portfolio`, `am_invoice_buyer_seller_graph`,
`am_legal_reasoning_chain`, `am_narrative_quarantine`,
`am_program_calendar_12mo`, `am_program_documents`,
`am_program_eligibility_history`, `am_program_eligibility_predicate`,
`am_program_narrative`, `am_program_narrative_full`,
`am_recommended_programs`, `am_segment_view`, `am_window_directory`.

MISSING (34, primary CREATE TABLE not yet executed against live DB):

| migration | expected primary table |
|---|---|
| wave24_110_am_entities_vec_v2 | am_entities_vec_v2_metadata (+ vec virtual) |
| wave24_111_am_entity_monthly_snapshot | am_entity_monthly_snapshot |
| wave24_112_am_region_extension | am_region_program_density |
| wave24_127_am_program_combinations | am_program_combinations |
| wave24_129_am_enforcement_industry_risk | am_enforcement_industry_risk |
| wave24_130_am_case_study_similarity | am_case_study_similarity |
| wave24_132_am_tax_amendment_history | am_tax_amendment_history |
| wave24_134_am_capital_band_program_match | am_capital_band_program_match |
| wave24_135_am_program_adoption_stats | am_program_adoption_stats |
| wave24_139_am_region_program_density | am_region_program_density |
| wave24_140_am_narrative_extracted_entities | am_narrative_extracted_entities |
| wave24_142_am_narrative_customer_reports | am_narrative_customer_reports |
| wave24_148_am_credit_pack_purchase | am_credit_pack_purchase |
| wave24_164_gbiz_v2_mirror_tables | gbiz_corp_activity (+ 7 mirrors) |
| wave24_168_entity_resolution_bridge_v2 | entity_resolution_bridge_v2 |
| wave24_170_source_catalog | source_catalog |
| wave24_171_source_freshness_ledger | source_freshness_ledger |
| wave24_172_cross_source_signal_layer | cross_source_signal_layer |
| wave24_173_invoice_status_history | invoice_status_history |
| wave24_174_enforcement_permit_event_layer | enforcement_permit_event_layer |
| wave24_175_public_funding_ledger | public_funding_ledger |
| wave24_176_edinet_filing_signal_layer | edinet_filing_signal_layer |
| wave24_177_regulatory_citation_graph | reg_node (+ reg_edge) |
| wave24_178_document_requirement_layer | document_requirement_layer |
| wave24_181_verify_log | verify_log |
| wave24_182_contributor_trust | contributor_trust |
| wave24_183_citation_log | citation_log |
| wave24_184_contribution_queue | contribution_queue |
| wave24_185_kokkai_utterance | kokkai_utterance |
| wave24_186_industry_journal_mention | industry_journal_mention |
| wave24_187_brand_mention | brand_mention |
| wave24_189_citation_sample | citation_sample |
| wave24_192_pubcomment_announcement | pubcomment_announcement |
| wave24_198_am_relation_predicted | am_relation_predicted |

ALTER / VIEW / secondary-only (7, expected to pass without table creation):
`wave24_107_am_compat_matrix_visibility`,
`wave24_109_am_amount_condition_is_authoritative`,
`wave24_113b_jpi_programs_jsic`,
`wave24_113c_autonomath_houjin_master_jsic`,
`wave24_144_narrative_quality_kpi_view`,
`wave24_180_time_machine_index`,
`wave24_193_fix_am_region_fk`.

### 2.2 jpintel forward (11 files)

Files with primary CREATE TABLE (8):

| migration | expected table | live status |
|---|---|---|
| wave24_058_production_gate_status | production_gate_status | APPLIED |
| wave24_105_audit_seal_key_version | audit_seal_keys | APPLIED |
| wave24_143_customer_webhooks_test_hits | customer_webhooks_test_hits | APPLIED |
| wave24_166_credit_pack_reservation | credit_pack_reservation | MISSING |
| wave24_188_evolution_dashboard_snapshot | evolution_dashboard_snapshot | MISSING |
| wave24_190_restore_drill_log | restore_drill_log | MISSING |
| wave24_191_municipality_subsidy | municipality_subsidy | MISSING |
| wave24_194_amendment_alert_subscriptions | amendment_alert_subscriptions | MISSING |

ALTER / column-add only (3, no primary CREATE TABLE): `wave24_108_*`,
`wave24_110a_tier_c_cleanup`, `wave24_113a_programs_jsic`.

## 3. Apply-order / schema conflict audit

- `target_db` markers are consistent (64 autonomath / 11 jpintel) — no
  header drift.
- All 75 forward migrations begin with `-- target_db: …` so the
  `entrypoint.sh §4` `head -1 grep "target_db: autonomath"` rule classifies
  them correctly.
- Object-name reuse across files:
  - `am_region_program_density` appears in **wave24_112** AND
    **wave24_139** — both use `CREATE TABLE IF NOT EXISTS` (idempotent;
    no schema-redefinition conflict).
  - `entity_resolution_bridge_v2` / `v_entity_resolution_public` —
    duplicate hit was a false positive (each appears once as DDL inside
    `wave24_168`; the second hit was a doc-comment reference).
  - No re-declaration with conflicting columns detected across the set.
- DML risk surfaces:
  - ALTER TABLE present in 10 files (mostly add-column, all idempotent
    via `entrypoint.sh` duplicate-column tolerance): 105, 106, 107, 108,
    109, 112, 113a, 113b, 113c, 141.
  - DROP statements present in 3 files: 144 (DROP VIEW IF EXISTS, view
    rebuild), 153 (DROP VIEW IF EXISTS), 193 (FK fix — DROP+CREATE TABLE,
    advertised as `fix_am_region_fk`).
  - No DROP TABLE on shared substrate detected outside the 193 region-FK
    fix.

## 4. Index / FK / constraint audit (sample of new tables)

Inspected DDL via `sqlite_master` for the 10 newly-landed wave24 tables in
this audit's scope:

- `am_artifact_templates` — PK `template_id` AUTOINCREMENT, UNIQUE
  `(segment, artifact_type, version)`, 3 indexes (`segment`, `type`,
  `segment_type`). CHECK constraints on `is_scaffold_only`,
  `requires_professional_review`, `uses_llm`. No FK (segment / authority /
  sensitive_act stored as plain TEXT).
- `am_houjin_program_portfolio` — PK `id` AUTOINCREMENT, UNIQUE
  `(houjin_bangou, program_id, method)`, 5 indexes (houjin, program,
  houjin_priority, houjin_unapplied, deadline). **Soft FK** to
  `jpi_houjin_master.houjin_bangou` and `jpi_programs.unified_id`
  documented in comments but not enforced — consistent with the broader
  `am_*` / `jpi_*` table convention of TEXT soft references.
- `am_legal_reasoning_chain` — PK `chain_id` with shape CHECK (`LRC-`
  prefix + length 14), tax_category CHECK enum (7 values), confidence
  CHECK 0..1. 3 indexes (category, computed, topic). No FK.
- `am_window_directory` — PK `window_id`, jurisdiction_kind CHECK enum
  (12 values), license CHECK enum (5 values), UNIQUE
  `(jurisdiction_kind, name, postal_address)`. 5 indexes. No FK.
- `am_amendment_alert_impact` — PK `alert_id` AUTOINCREMENT,
  houjin_bangou length=13 CHECK, impact_score 0..100 CHECK. 4 indexes
  (houjin, pending, score, dedupe-UNIQUE). No FK (`amendment_diff_id`
  soft ref to `am_amendment_diff`).
- `am_segment_view` — PK `segment_key`, 5 indexes (band, jsic, pref,
  rank). Denormalized program/judgment/tsutatsu arrays as JSON TEXT.
- `am_case_extracted_facts` — PK `case_id`, source_kind / extraction_method
  CHECK enums, confidence CHECK 0..1. 3 indexes
  (amount_pref, case, jsic_year).
- `am_figure_embeddings` — PK `figure_id`, UNIQUE `(pdf_sha256, page_no,
  figure_idx)`, 3 indexes (kind, pdf, source_doc). BLOB embedding column
  + f32 little-endian.
- `am_citation_judge_law` — PK `id` AUTOINCREMENT, 4 indexes (article,
  court, law, score), UNIQUE `(court_unified_id, article_id,
  inference_run_id, method)` via `ux_am_citation_jl_caim`. **The only
  real FK in the surveyed batch**: `FOREIGN KEY (article_id) REFERENCES
  am_law_article(article_id) ON DELETE CASCADE`.
- `am_relation_predicted` — table file present (wave24_198) but **NOT
  applied to live DB** (see §2.1 MISSING list).

`am_alias` substrate: live 433,057 rows (≈+97K vs the 335,605 baseline
in §Overview), no conflict with the new tables — no migration in the
wave24 set rewrites `am_alias`.

## 5. Production / deploy-time apply status

`entrypoint.sh §4` runs autonomath-target migrations in `manifest` mode by
default (`AUTONOMATH_BOOT_MIGRATION_MODE=manifest`, fallback chain
`jpcite_boot_manifest.txt` → `autonomath_boot_manifest.txt`). The two
manifest files are **byte-identical** (`diff` empty).

Crucial finding: **0 of the 64 autonomath-target wave24_* migrations are
listed in the boot manifest**. `grep -E '^wave24_'` on
`jpcite_boot_manifest.txt` returns no matches.

Implication: production `autonomath.db` self-heal on Fly boot will skip
all wave24 autonomath migrations regardless of whether the SQL file is
committed. The 23 currently-APPLIED tables on the local 14 GB DB are
present either via offline `sqlite3 < migration.sql` execution or via
upstream R2 snapshot rollover — not via boot-time self-heal.

For the 34 MISSING tables to land in production, either:

1. Add the relevant filenames to `jpcite_boot_manifest.txt` AND
   `autonomath_boot_manifest.txt` (both, byte-identical), or
2. Apply offline + ship the resulting DB via the R2 snapshot path, or
3. Run a one-shot `sqlite3 $AUTONOMATH_DB_PATH < migration.sql` against
   the live volume.

`fly.toml` `release_command` is intentionally commented out (see
`CLAUDE.md` "Common gotchas") — re-enabling it is NOT a fix; the proper
path is the manifest.

## 6. Drift summary

| dimension | count |
|---|---|
| forward migrations (total) | 75 |
| rollback companions present | 72 |
| rollback companions missing | 3 (058 / 182 / 201) |
| autonomath target | 64 |
| autonomath APPLIED locally | 23 |
| autonomath MISSING locally | 34 |
| autonomath ALTER/VIEW-only (no primary CREATE TABLE) | 7 |
| jpintel target | 11 |
| jpintel APPLIED locally | 3 |
| jpintel MISSING locally | 5 |
| jpintel ALTER/column-only | 3 |
| schema_migrations bookkeeping rows for wave24_* | 8 |
| production-ready (in boot manifest) | 0 |
| header consistency (`-- target_db:`) | 75/75 |
| header conflict / re-declaration | 0 (only idempotent CREATE IF NOT EXISTS overlap on `am_region_program_density`) |

## 7. Recommendations (non-binding observations)

1. Decide whether the 34 + 5 = **39 MISSING** wave24 forward migrations
   should land in production. If yes, add to `jpcite_boot_manifest.txt`
   (kept byte-identical to `autonomath_boot_manifest.txt`) and verify
   each is pure-additive (`CREATE … IF NOT EXISTS`).
2. Add rollback companions for the 3 missing files (058 / 182 / 201) to
   match the convention of the other 72.
3. Consider populating `schema_migrations` bookkeeping for the 23
   already-APPLIED but unrecorded migrations so future boot self-heal
   loops do not re-apply them.
4. The single duplicated `am_region_program_density` CREATE in
   wave24_112 + wave24_139 is benign (idempotent), but rename or merge
   to keep file-to-table mapping 1:1 for future audits.

## 8. Method (reproducibility)

```bash
# Inventory
ls /Users/shigetoumeda/jpcite/scripts/migrations/wave24_*.sql | grep -v rollback | wc -l
# Header consistency
for f in scripts/migrations/wave24_*.sql; do
  case "$f" in *_rollback.sql) continue;; esac
  head -1 "$f"
done | sort | uniq -c
# Live table existence (single batch query against 14 GB DB)
sqlite3 autonomath.db "SELECT name FROM sqlite_master WHERE type='table' AND name IN (…);"
# Bookkeeping
sqlite3 autonomath.db "SELECT id FROM schema_migrations WHERE id LIKE 'wave24_%';"
```

Audit produced 2026-05-17 against repo HEAD `37518c215798aa23e428c605dea40d79a23a51a0`.
[lane:solo]
