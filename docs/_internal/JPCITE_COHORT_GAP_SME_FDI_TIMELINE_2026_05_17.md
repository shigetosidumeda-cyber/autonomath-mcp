# jpcite Cohort Gap — SME × FDI × Timeline (G6/G7/G8) — 2026-05-17

Audit of three cohort surfaces (中小経営者 / 国際・英訳 / 時系列) against the
live `autonomath.db` SOT. READ-ONLY, `[lane:solo]`. No LLM. No aggregator.

## Baseline counts (verified `autonomath.db` 2026-05-17)

| Surface | Asset | Count | Cohort |
| --- | --- | --- | --- |
| Programs | `jpi_programs` (all) / `program_kind='subsidy'` | 13,578 / 5,864 | G6 |
| Loans | `jpi_loan_programs` | 108 | G6 |
| Tax | `am_tax_rule` (credit/exemption/reduction/...) | 145 | G6 |
| Cases | `jpi_case_studies` (summary≥100 chars) | 2,286 (1,039) | G6 |
| Adoption | `jpi_adoption_records` | 201,845 | G6 |
| Templates | `am_artifact_templates` (5 segment × 10) | 50 | G6 |
| Accept trend | `am_acceptance_trend` | 69 | G6 |
| Monthly adopt | `am_adoption_trend_monthly` | 473 | G6 |
| Industry JSIC | `am_industry_jsic` | 37 | G6 |
| Geo×industry | `am_geo_industry_density` | 1,034 | G6 |
| Law articles | `am_law_article` (`body_en` non-null) | 353,278 (**1**) | G7 |
| Tax treaty | `am_tax_treaty` | 33 / ~80 target | G7 |
| Amendment diff | `am_amendment_diff` (2026-04-30〜2026-05-12) | 16,116 | G8 |
| Amendment snapshot | `am_amendment_snapshot` (version_seq 1-2) | 14,596 | G8 |
| Monthly snapshot log | `am_monthly_snapshot_log` (2023-06〜2026-05) | 36 mo × 4 tbl = 144 | G8 |
| Entity monthly snap | `am_entity_monthly_snapshot` | **0** | G8 |

---

## G6 — 中小経営者 (SME owners): top 10 gaps

| # | Gap | Current | Target | ETL plan |
| --- | --- | --- | --- | --- |
| G6-01 | 採択 vivid narrative | `am_program_narrative` = 0 / `am_case_study_narrative` = 0 | 2,286 case_studies × structured narrative (problem/solution/outcome/¥) | `scripts/etl/extract_case_narrative_2026_05_17.py` — regex+template extractor over `jpi_case_studies.case_summary` (1,039 rows ≥100 chars), patterns_json / outcomes_json already populated (2,238 / 1,520). Pure deterministic, no LLM. |
| G6-02 | 経営計画 templates | `am_artifact_templates` segments = {会計士, 司法書士, 社労士, 税理士, 行政書士} — 中小経営者 segment **missing** | Add `segment='chuusho_keieisha'` × 10 artifact_type | New migration `wave24_207_keiei_keikaku_templates.sql` — 10 scaffolds (jigyo_keikaku, shikin_keikaku, jinji_keikaku, hanro_kaitaku, jigyou_shoukei, BCP, monodukuri_keikaku, IT_donyu_keikaku, jigyou_saikouchiku_keikaku, keiei_kakushin_keikaku). `is_scaffold_only=1`, `uses_llm=0`. |
| G6-03 | 業界動向 narrative | `industry_journal_mention`=0 / `industry_stats`=0 / `am_enforcement_industry_risk`=0 | 37 JSIC major × monthly trend + 採択 density | Re-use `am_acceptance_trend` (69) + `am_adoption_trend_monthly` (473) + `am_geo_industry_density` (1,034) to populate `industry_stats` deterministic aggregator. |
| G6-04 | 補助金 deadline calendar | `application_window_json` exists but not surfaced as cohort view | Per-month application window roll-up | View `v_sme_program_calendar` over `jpi_programs.application_window_json` (already used by N2 ETL). |
| G6-05 | 経営者 segment ID column | No `segment` lookup on `jpi_houjin_master` for chuusho_keieisha | Tag SME-eligible houjin via 中小企業基本法 cutoff (capital / employee_count) | `scripts/etl/tag_sme_houjin_2026_05_17.py` — pure threshold rule (法 第2条) over `am_entity_monthly_snapshot.capital_yen` + `.employee_count` once populated (see G8-04). |
| G6-06 | 融資 narrative depth | 108 loan rows, `target_conditions` text exists, no extracted structure | 108 × {collateral, guarantor, rate_floor, eligibility_clauses} parsed | Idempotent regex parser over `target_conditions` + `security_notes`; 3 enum columns already exist (`collateral_required`, `personal_guarantor_required`, `third_party_guarantor_required`) — backfill them. |
| G6-07 | 税制優遇 combinable matrix | `am_tax_rule.combinable_with` JSON exists, no pre-computed pair view | 145 × 145 incompatibility matrix | Materialised view `v_am_tax_rule_combinability` (deterministic SET intersection). |
| G6-08 | 採択率 vintage drift | `am_acceptance_trend` records only `trend ∈ {up, stable}`, no per-cohort | Per-prefecture × industry × 上位10 program | Aggregator over `jpi_adoption_records` (201K) JOIN `jpi_programs.jsic_major` (already assigned). |
| G6-09 | 経営承継 / IT導入 / monodukuri sub-cohort | All collapsed into single `program_kind='subsidy'` | Top-tier program tags (P_MAJOR=5) for SME | Tag column `is_sme_flagship` populated from `aliases_json` regex on the 5 flagship names (ものづくり / IT導入 / 事業再構築 / 持続化 / 事業承継). |
| G6-10 | 採択 PDF excerpt → text | `jpi_case_studies.source_excerpt` populated but not normalised | NFKC + whitespace dedupe → searchable | One-shot SQL `UPDATE`, no fetch. |

---

## G7 — 国際 / 英訳 (FDI / inbound): top 5 gaps

| # | Gap | Current | Target | ETL plan |
| --- | --- | --- | --- | --- |
| G7-01 | `am_law_article.body_en` ほぼ空 | 1 / 353,278 (0.0003%) | JLT (日本法令外国語訳) covers ~870 laws → walk + match → ~80K article rows | `scripts/etl/ingest_egov_law_translation.py` **already exists** — runner just hasn't been scheduled. Add to `scripts/cron/poll_egov_amendment_daily.py` weekly slot. CC-BY 4.0, no LLM. |
| G7-02 | `am_tax_treaty` 33 / ~80 country pair | 33 rows (AE, AU, BE, BR, CA, CH, CN, DE, DK, ES, …) | ~80 (MOF lists ~78 bilateral DTA) | `scripts/etl/ingest_mof_tax_treaty.py` **already exists** — re-run with extended ISO list. Backfill migration `125_tax_treaty_backfill_30_countries.sql` already loaded 30; need second pass for the remaining ~15. |
| G7-03 | Treaty `pe_days_threshold` 5 / 33 | Only 5 rows have PE day-count | 33 — every DTA defines PE | Re-parse MOF PDFs with stricter regex (`第5条 恒久的施設`) — pure pypdf, no LLM. |
| G7-04 | 海外法人 vs JP 制度 mapping | None — no cross-reference table | `am_program_fdi_eligibility` linking 13,578 programs × `requires_jp_houjin` flag | New migration + deterministic rule over `target_types_json` (look for `houjin` / `gaishikei` / `kokunai`) — pure SQL. |
| G7-05 | IFRS ↔ JGAAP mapping | None | 50 IFRS standards × JGAAP article cross-walk | Lower priority — schema-only stub `am_accounting_standard_xref` (manual seed from ASBJ public table, gov_standard license). Defer ETL beyond v0.4. |

**Translation review queue infrastructure already exists** (`am_law_translation_progress`, `am_law_translation_review_queue`, both empty). Wiring is the gap, not the schema.

---

## G8 — 時系列 (Dim Q time machine): top 5 gaps

| # | Gap | Current | Target | ETL plan |
| --- | --- | --- | --- | --- |
| G8-01 | Amendment diff history < 13 days | `detected_at` 2026-04-30 〜 2026-05-12 (16,116 rows, 2 months) | 5 years rolling | `scripts/etl/backfill_amendment_diff_from_snapshots.py` **already exists** — synthesise diff rows from any pair of `am_amendment_snapshot` versions where `version_seq=1→2` differs. Will yield ~7,298 entity-pairs of historical diff. |
| G8-02 | Snapshot version_seq only 1-2 | Max version_seq = 2 (per entity) | Up to ~60 (5 years × 12 mo) | `scripts/etl/generate_dim_q_sample_snapshots.py` **exists** — extend to walk wayback / e-Gov 法令履歴 API for true historical body. Throttled 1 req/sec, gov_standard. |
| G8-03 | `am_monthly_snapshot_log` partial table coverage | 36 mo × **4** tables (amendment_snapshot, program_history, law_jorei, cross_source_agreement); 3 are 0-row | 36 mo × ~12 critical tables (programs, loans, tax_rule, treaty, case_studies, adoption, narrative, ...) | Extend `_SNAPSHOT_TABLES` in `scripts/etl/build_monthly_snapshot.py`. Pure SHA256 digest, no fetch. |
| G8-04 | `am_entity_monthly_snapshot` = 0 | Schema exists, no rows | One row per active houjin per month (capital_yen, employee_count, status_active) | Pure SELECT INTO from `jpi_houjin_master` + `houjin_change_history` (already populated). Required also by G6-05. |
| G8-05 | Counterfactual "as_of" 関数 missing | `am_monthly_snapshot_log` records digests but no SQL view picks the right snapshot row for arbitrary `as_of_date` | View `v_am_program_as_of` etc. picking max(version_seq) where observed_at ≤ as_of | Migration `wave24_208_time_machine_views.sql` — pure SQL views, no ETL. |

---

## Cross-cohort observations

1. **Schemas already exist for nearly every gap.** The bottleneck is ETL scheduling and runner wiring, not migrations. Six of the top 20 gaps are "existing script that needs to be cron-scheduled" rather than new build.
2. **No LLM is required for any of the 20 gaps.** Every fix is deterministic (regex / SQL aggregator / public PDF parse / schema seed).
3. **G6-01 (採択 vivid narrative) is the single highest-leverage fix** — 2,286 cases × narrative extraction unblocks both Dim K (predictive) and Dim O (verified knowledge graph) downstream.
4. **G7-01 + G7-02 share infra** — both ingesters are already written, both gated only on operator-explicit kick-off (no LLM, no API key).
5. **G8 monthly snapshot retention already proves "5-year window"** — 36 monthly digests confirm the pattern works; gap is widening table coverage, not building the spine.

## Commit

This audit is read-only documentation. Compute scripts (e.g.
`scripts/etl/extract_case_narrative_2026_05_17.py`) are scoped for
follow-up landings, NOT in this commit.
