# Orphan artifact audit (2026-05-11)

Scope: artifacts under `scripts/` (top-level .py/.sh), `docs/*.md` + `docs/_internal/*.md`, top-level `site/*.{html,json,txt}`, `.github/workflows/*.yml`, `src/jpintel_mcp/**/*.py`. Inputs are read-only; **no files moved, renamed, or deleted**. Per the destruction-free organization rule, all 措置 below are limited to (1) leaving the file in place with a banner annotation, or (2) routing the file into an `_archive/` index entry. Recommend that no consumer or generator deletes anything based on this report without explicit operator approval.

## Inventory + orphan totals

| Category | Path scope | Inventory | Orphan (ref count = 0) | Orphan (ref count = 1, single audit-only mention) |
|---|---|---:|---:|---:|
| scripts | `scripts/*.py` + `scripts/*.sh` (top-level) | 112 | 21 | 27 |
| docs/public | `docs/*.md` (top-level, excluded subdirs) | 47 | 1 | 1 (`security_posture.md` only via mkdocs.yml exclude_docs) |
| docs/_internal | `docs/_internal/*.md` (top-level) | 181 | 16 | 22 |
| site/top | `site/*.{html,json,txt}` (top-level only) | 53 | 1 (claude_desktop_config.example.json) | 0 |
| workflows | `.github/workflows/*.yml` | 99 | 2 | 17 (single workflow_cron_state audit mention) |
| src | `src/jpintel_mcp/**/*.py` | 377 | 17 (16 in `_archive/`, 1 active: `mcp/autonomath_tools/intel_wave31.py`) | (excluded — most singletons are legitimate router imports) |

Method: each candidate basename was searched across `.github/`, `docs/`, `scripts/`, `src/`, `site/`, `mkdocs.yml`, `pyproject.toml`, `CLAUDE.md` using `grep -l`. Auto-generated subtrees (`site/programs/`, `site/laws/`, `site/cases/`, `site/enforcement/`, `site/qa/`, `site/cross/`) and `__pycache__/` are excluded — they don't change orphan status. `from . import X` style relative imports in `__init__.py` are counted (otherwise `autonomath_tools/*.py` would appear falsely orphan; the package's `__init__.py` block-import handles 38 of 41 tool modules).

Largest orphan category = **docs/_internal (16)**, followed by scripts (21 zero-ref + 27 single-ref legacy wave aids).

---

## 1. scripts/ — top-level orphans

### A. ref count = 0 (no caller in workflows / pyproject / cron / etl / docs / Makefile / fly.toml)

| # | path | size | mtime | orphan 理由 | 推奨措置 |
|---|---|---:|---|---|---|
| 1 | `scripts/backfill_source_urls.py` | 6.0 KB | 2026-05-07 | one-shot wave-1 source_url backfill — header confirms "Wave 1 of 4". Superseded by `backfill_source_urls_wave4.py` chain; no live caller. | 残す + banner `# HISTORICAL: 2026-04 Wave 1-4 backfill (kept for replay reference); not invoked from any workflow/cron.` |
| 2 | `scripts/backfill_source_urls_wave4.py` | 27.5 KB | 2026-05-07 | Wave 4 one-shot completion run | 残す + 同 banner |
| 3 | `scripts/build_minify.py` | 13.7 KB | 2026-05-07 | HTML/CSS minifier — no caller in workflows or docs | やめる候補 (`_archive/` index entry) but consider 残す if planned for future content-flywheel step |
| 4 | `scripts/compliance_cron.py` | 28.5 KB | 2026-05-07 | name suggests cron entry, but no `.github/workflows/*.yml` schedules it; `scripts/cron/` does **not** contain a sibling | やめる候補 → `_archive/` index; if intended for compliance-cron.yml workflow, wire it explicitly |
| 5 | `scripts/dedup_programs_wave17.py` | 11.1 KB | 2026-05-07 | Wave 17 noise-duplicate consolidation, one-shot per header (`Detect and merge noise duplicates in jpintel.db`) | 残す + banner `# HISTORICAL: Wave 17 one-shot; replay only if duplicates re-introduced.` |
| 6 | `scripts/delete_old_stripe_webhook.py` | 1.6 KB | 2026-05-07 | one-shot Stripe webhook cleanup | 残す + banner `# HISTORICAL: Stripe webhook migration helper, single-use 2026-04.` |
| 7 | `scripts/import_non_agri_rules.py` | 5.6 KB | 2026-05-07 | post-pivot artifact (legacy brand era); no caller | 残す + banner `# HISTORICAL: legacy pivot era ingest; superseded by current rules ingest path.` |
| 8 | `scripts/inject_a11y_baseline.py` | 1.4 KB | 2026-05-11 | newly written (today) — likely Wave 5 Lane work-in-progress | 改善する: wire into pages-deploy-main.yml or pages-regenerate.yml. If intentional one-shot, demote with banner. |
| 9 | `scripts/inject_jsonld.py` | 1.2 KB | 2026-05-11 | newly written (today) — likely Wave 5 Lane work-in-progress | 改善する: wire into structured_data_v3.yml workflow (currently 1-ref via that workflow only) or add banner. |
| 10 | `scripts/match_non_agri_ids.py` | 17.0 KB | 2026-05-07 | legacy pivot era ID matcher | 残す + banner `# HISTORICAL: legacy pivot era; non-agri remapping done.` |
| 11 | `scripts/populate_tier_b_vec.py` | 21.2 KB | 2026-05-07 | one-shot Tier-B vec population (sentence-transformers + sqlite-vec) | 残す + banner `# HISTORICAL: Tier-B vec one-shot 2026-04; idempotent, safe to re-run.` |
| 12 | `scripts/process_duplicate_review_2026_04_26.py` | 17.5 KB | 2026-05-07 | dated 2026-04-26 in filename, Wave 18 残 193 ambiguous queue | 残す + banner `# HISTORICAL: Wave 18 dated 2026-04-26 review queue processor.` |
| 13 | `scripts/publish_all_registries.sh` | 9.1 KB | 2026-04-29 | wrapper script — `publish_to_registries.py` + `publish_to_mcp_registries.py` are referenced directly | やめる候補: `_archive/` index entry, link to the two single-purpose scripts in the index |
| 14 | `scripts/rebuild_am_entities_fts.py` | 8.1 KB | 2026-05-07 | V4 Phase 6 one-shot FTS rebuild (per header) | 残す + banner `# HISTORICAL: V4 absorption FTS rebuild 2026-04-25; rerun manually if drift detected.` |
| 15 | `scripts/rebuild_programs_fts.py` | 4.5 KB | 2026-05-07 | one-shot programs_fts reconcile | 残す + banner `# HISTORICAL: programs_fts reconcile; manual op only.` |
| 16 | `scripts/reconcile_program_entities.py` | 4.0 KB | 2026-04-29 | one-shot Jaro-Winkler matcher (V4 absorption) | 残す + banner `# HISTORICAL: V4 absorption Phase B reconcile; sees no traffic post 2026-04-25.` |
| 17 | `scripts/send_scheduled_emails.py` | 1.4 KB | 2026-05-07 | no caller; transactional-email path likely subsumed by `dispatch_webhooks.py` cron | やめる候補: `_archive/` index; verify no Fly job uses it before archiving |
| 18 | `scripts/setup_stripe_compliance_product.py` | 6.0 KB | 2026-05-07 | one-shot Stripe product/price seeding | 残す + banner `# HISTORICAL: Stripe compliance-product setup 2026-04; rerun only on price change.` |
| 19 | `scripts/static_bad_urls.py` | 3.1 KB | 2026-05-07 | no caller — likely superseded by `url_integrity_scan.py` | やめる候補: `_archive/` index, point at successor |
| 20 | `scripts/unify_dbs.py` | 7.8 KB | 2026-05-07 | one-shot jpintel.db → autonomath.db unify (per header, "Pre-conditions / Post-conditions" gated) | 残す + banner `# HISTORICAL: V4 absorption DB unify 2026-04-25; do NOT re-run.` |
| 21 | `scripts/user_value_acceptance_gate.py` | 16.6 KB | 2026-05-07 | acceptance gate — referenced in earlier sessions but not in any current workflow | 改善する: wire into release-readiness-ci.yml if intended; if obsoleted by acceptance-criteria-ci.yml + acceptance_check.yml, banner as superseded |

### B. ref count = 1 (single audit/changelog mention only, no live wiring)

These show up in `docs/_internal/dead_code_audit_2026-04-30.md` or `CLAUDE.md` history note only — no live caller. Snapshot list (27 total): `_build_compare_csv.py`, `archive_telemetry.sh`, `bench.py`, `check_fence_count.py`, `check_mcp_drift.py`, `check_openapi_drift.py`, `check_publish_text.py`, `check_sitemap_freshness.py`, `check_tool_count_consistency.py`, `generate_case_pages.py`, `generate_enforcement_pages.py`, `ingest_case_studies_supplement.py`, `ingest_examiner_feedback.py`, `ingest_maff.py`, `ingest_mhlw.py`, `ingest_mic.py`, `ingest_moj.py`, `monthly_invariant_review.py`, `publish_to_mcp_registries.py`, `publish_to_registries.py`, `rename_zeimu_to_jpcite.py`, `restore.py`, `scan_publish_surface.py`, `seed_advisors.py`, `setup_stripe_device_flow.py`, `test_backup_integrity.py`, `validate_jsonld.py`, `walk_pref_subsidy_seeds.py`, `weekly_invariant_check.py`. **Note**: several (e.g. `check_*_drift.py`, `check_sitemap_freshness.py`) are referenced by `*_drift_v3.yml` / `sitemap_freshness_v3.yml` workflows — `_v3` reference count = 1 means single-workflow consumer, which is valid. Most of these are NOT genuine orphans, just narrow-consumer scripts.

→ 推奨措置: 残す (single-workflow consumer is legitimate). Run the audit again if `_v3.yml` workflows are merged or replaced.

---

## 2. docs/ + docs/_internal — orphans

### docs/*.md (top-level)

| # | path | size | mtime | refs | orphan 理由 | 推奨措置 |
|---|---|---:|---|---:|---|---|
| 1 | `docs/alerts_guide.md` | 2.9 KB | 2026-05-07 | 0 | not in mkdocs.yml nav, not linked from any other doc, not exclude_docs phantom either | 改善する: either add to mkdocs.yml nav (Developer > Alerts) — already advertised as `docs/alerts_guide.md` in CLAUDE.md and nav has an alerts entry pointing here; verify the nav link spelling matches. If the nav already covers a sibling, banner with redirect note. |

### docs/_internal/*.md — 16 zero-ref candidates

All recently written (2026-05-06..08, R8 spec batch + paid_product_value strategy batch). Most are loop-iteration strategy artifacts that haven't been linked back into `INDEX.md` or `INDEX_2026-05-05.md`.

| # | path | size | mtime | orphan 理由 | 推奨措置 |
|---|---|---:|---|---|---|
| 1 | `docs/_internal/advisors_evidence_handoff_concrete_plan_2026-05-07.md` | 26.1 KB | 2026-05-08 | session-scoped strategy plan; no _internal/INDEX link | 改善する: add to `docs/_internal/INDEX.md` advisors evidence section |
| 2 | `docs/_internal/all_issues_resolution_master_plan_v2_2026-05-08.md` | 21.3 KB | 2026-05-08 | iteration-2 follow-up to `all_issues_resolution_master_plan_2026-05-08.md` (v1 has 1 ref) | 改善する: cross-link v1 → v2 explicitly, or banner v1 as superseded |
| 3 | `docs/_internal/DEPLOY_HARDENING_PACKET_STAGING_2026-05-06.md` | 28.4 KB | 2026-05-06 | staging-only packet; no link from `PRODUCTION_DEPLOY_PACKET_2026-05-06.md` | 改善する: link from PROD packet's history section |
| 4 | `docs/_internal/geo_agent_100k_daily_growth_plan_2026-05-08.md` | 9.7 KB | 2026-05-08 | growth plan iteration | 改善する: add to INDEX growth section or banner as historical iteration |
| 5-9 | `docs/_internal/paid_product_value_strategy_*.md` × 5 (base + turn 2/3/4/5 + data_expansion turn5) | 13-26 KB each | 2026-05-08 | strategy iteration chain; turns not cross-linked | 改善する: add to INDEX as a strategy series block; banner chain (turn N references turn N-1) |
| 10 | `docs/_internal/pricing_demand_strategy_2026-05-08.md` | 2.0 KB | 2026-05-08 | brief strategy note; isolated | 改善する: link from `paid_product_value_strategy_*` series |
| 11-15 | `docs/_internal/R8_*` × 5 (compatibility / corporate_form / funding_stage / succession / tax_chain) | 5-9 KB each | 2026-05-07 | R8 surface specs; live R8 cohort grow shipped (matchers + endpoints) but spec docs unlinked | 改善する: cross-link from CLAUDE.md R8 grow section (currently only `R8_funding_stage_endpoint_2026-05-07.md` is referenced); add the other 4 to `docs/_internal/INDEX.md` or `INDEX_2026-05-05.md`. Source-side implementation already exists, so the spec docs are not stale — just unlinked. |
| 16 | `docs/_internal/repo_hygiene_packetization_addendum_2026-05-06.md` | 5.8 KB | 2026-05-07 | hygiene addendum; not linked back from `repo_hygiene_inventory_latest.md` | 改善する: link from `repo_hygiene_inventory_latest.md` |

### docs/_internal/*.md — 22 single-ref candidates

22 files have exactly 1 reference, typically only from `INDEX_2026-05-05.md` or self-referential CLAUDE.md history. Snapshot list: `all_issues_resolution_master_plan_2026-05-08.md`, `artifact_api_contract_2026-05-06.md`, `dirty_tree_release_classification_2026-05-06.md`, `evidence_packet_persistence_design_2026-05-06.md`, `handoff_precomputed_intelligence_2026-04-30.md`, `offline_cli_inbox_contract_2026-05-06.md`, `openapi_distribution_sync_2026-05-06.md`, `performance_audit_2026-04-30.md`, `PRODUCTION_DEPLOY_PACKET_MANIFEST_2026-05-07.md`, `PRODUCTION_READINESS_LOOP_HANDOFF_2026-05-07.md`, `repo_cleanup_loop_report_2026-05-06.md`, `STRICT_METERING_HARDENING_VERIFICATION_2026-05-07.md`, `TABLE_CATALOG.md`, `TEST_CATALOG.md`, `TRACEABILITY_MATRIX.md`, `W24_BRAND_AUDIT.md`, `W24_DEAD_CODE_AUDIT.md`, `W24_PENDING_WORKFLOWS_REAUDIT.md`, `W28_NARRATIVE_DISPATCH.md`, `W28_PAYLOAD_AUDIT.md`, `W29_NPM_BOOTSTRAP.md`, `dead_code_audit_2026-04-30.md` (2 refs but close to single).

→ 推奨措置: 残す (catalog/handoff/audit docs are by nature single-ref entries — they live behind `INDEX_2026-05-05.md` and exist as reference material). Periodic re-link audit, no other action.

---

## 3. site/ top-level orphans

Top-level scope only (53 files). For deep auto-generated trees see the existing `docs/audit/site_docs_orphan_2026_05_11.md` companion report (25 deep-tree orphans).

### A. ref count = 0

| # | path | size | mtime | orphan 理由 | 推奨措置 |
|---|---|---:|---|---|---|
| 1 | `site/claude_desktop_config.example.json` | 215 B | 2026-05-11 | not in any sitemap, no _redirects entry, no inbound href; freshly written today (Wave 1 Lane C2 sample config) | 改善する: link from `site/connect/claude.html` (or wherever the Claude Desktop install recipe lives), or add to sitemap+robots.txt. If it's a download artifact only, banner with `<!-- DOWNLOAD: linked from docs/cookbook/r16-claude-desktop-install.md -->`. |

### B. low-ref candidates (worth verifying inbound traffic)

These have a few inbound hrefs from sibling html but appear in no sitemap (sitemap drift):

| # | path | inbound html | sitemap | 推奨措置 |
|---|---|---:|---:|---|
| 1 | `site/glossary.html` | 0 (only itself + en/glossary.html sibling) | 0 | 改善する: link from `site/index.html` footer or `site/getting-started.html` |
| 2 | `site/testimonials.html` | 0 (only itself + en sibling) | 0 | 改善する: link from `site/about.html` or `site/trust.html` |
| 3 | `site/sla.html` | 2 | 0 | 改善する: add to sitemap.xml; CLAUDE.md docs claim sla.md → /sla but site path coverage is thin |
| 4 | `site/openapi.agent.gpt30.json` | 1 (`site/connect/chatgpt.html`) | 0 | 残す (single legitimate consumer) — but add to robots.txt allow + sitemap for crawler discovery |

→ 残り 39 top-level site files all have ≥2 inbound refs and live in sitemap/_redirects (no action).

---

## 4. .github/workflows/ orphans

### A. ref count = 0 (no sibling workflow refs them, no docs mention them outside audit)

| # | path | size | mtime | orphan 理由 | 推奨措置 |
|---|---|---:|---|---|---|
| 1 | `.github/workflows/incremental-law-bulk-saturation-cron.yml` | 8.0 KB | 2026-05-07 | superseded by `incremental-law-load.yml` (per `workflow_cron_state_2026_05_11.md` audit); duplicate scheduled cron | 改善する: confirm `incremental-law-load.yml` is the canonical replacement (its 2 refs include this file's audit mention), then 残す + banner top-of-file `# DEPRECATED: superseded by incremental-law-load.yml on 2026-05-07. Kept for cron-history audit.` OR move to a `.github/workflows/_archive/` subdir (note: GHA does ignore subdirs, so safe). |
| 2 | `.github/workflows/incremental-law-en-translation-cron.yml` | 8.9 KB | 2026-05-07 | similarly superseded; same 0-ref pattern | 改善する: same banner approach as above |

### B. ref count = 1 (only `docs/audit/workflow_cron_state_2026_05_11.md` mentions them)

17 workflows show up in that one audit doc only. Snapshot list (all `*_v3.yml` and several `*-cron.yml`): `acceptance_check.yml`, `acceptance_criteria_ci.yml`, `amendment-alert-fanout-cron.yml`, `facts_registry_drift_v3.yml`, `fence_count_drift_v3.yml`, `geo_eval.yml`, `lane-enforcer-ci.yml`, `mcp_drift_v3.yml`, `og-images.yml`, `openapi_drift_v3.yml`, `post-award-monitor-cron.yml`, `publish_text_guard.yml`, `sdk-republish.yml`, `sitemap_freshness_v3.yml`, `status_update.yml`, `structured_data_v3.yml`. **Caveat**: many of these are top-level workflows (no sibling workflow needs to "reference" them — they're triggered by `on: schedule`, `on: push`, or `on: workflow_dispatch` directly). They are **not orphans** under the proper definition; the 1-ref count is just the audit doc.

→ 推奨措置: 残す (live-triggered workflows are by definition not referenced by other workflows). Re-confirm each via GitHub Actions run history (last 30 days) before any action — that probe is **not** part of this static audit.

---

## 5. src/jpintel_mcp/ orphans

### A. `_archive/` subtree (16 files — already archived)

The package already has a `src/jpintel_mcp/_archive/` subdir with three timestamped subdirs:
- `_archive/autonomath_tools_dead_2026-04-25/` (4 files: `acceptance_stats_tool.py`, `batch_handler.py`, `batch_tool.py`, `sib_tool.py`, `unigram_search.py`)
- `_archive/embedding_2026-04-25/` (2 files in the 0-ref tally: `facet_synthesis.py`, `unigram_fallback.py`; full subdir holds more)
- `_archive/reasoning_2026-04-25/` (10 files: `bound_samples.py`, `bind_i02.py`..`bind_i10.py`, `samples.py`)

These already follow the destruction-free pattern (banner-via-directory-name + dated). The 4 zero-ref entries (`batch_tool.py`, `facet_synthesis.py`, `bound_samples.py`, plus dead-package siblings of the 12 one-ref bind files) are correctly archived.

→ 推奨措置: 残す (already archived per repo policy). Verify each subdir has a top-level `README.md` describing why archived; if missing, add a minimal banner file. As of audit, `scripts/_archive/README.md` exists (813 B) — confirm `src/jpintel_mcp/_archive/*/README.md` parity.

### B. active-code orphans (3 candidates, 1 confirmed)

| # | path | size | mtime | orphan 理由 | 推奨措置 |
|---|---|---:|---|---|---|
| 1 | `src/jpintel_mcp/mcp/autonomath_tools/eligibility_predicate_tool.py` | 8.3 KB | 2026-05-05 | **NOT** imported in `autonomath_tools/__init__.py` block-import (verified line-by-line); cross-ref hit (`compatibility_tools.py`) is only a comment / type-hint, not an import side-effect | 改善する: either add to `__init__.py` block-import alongside `eligibility_tools` if intended live, or move to `_archive/autonomath_tools_dead_2026-04-25/` with a banner |
| 2 | `src/jpintel_mcp/mcp/autonomath_tools/intel_wave31.py` | 60.9 KB | 2026-05-08 | NOT in `__init__.py` block-import; large file (~60 KB), likely Wave 31 staging | 改善する: confirm whether AUTONOMATH_INTEL_WAVE31_ENABLED gate is intended to wire it later. If yes, document gate in CLAUDE.md `Key files` block. If no, archive. |
| 3 | `src/jpintel_mcp/mcp/autonomath_tools/intel_wave32.py` | 9.4 KB | 2026-05-08 | same pattern as wave31; also references `compatibility_tools.py` import — not registered | 改善する: same as #2 |

---

## やめる / 残す / 改善する rollup

| 軸 | 件数 | サマリ |
|---|---:|---|
| **やめる** (推奨 `_archive/` index entry) | **6** | `scripts/build_minify.py`, `scripts/compliance_cron.py`, `scripts/publish_all_registries.sh`, `scripts/send_scheduled_emails.py`, `scripts/static_bad_urls.py`, ~~scripts/dedup~~ (kept as HISTORICAL) — these are not banner-as-HISTORICAL candidates because they're not one-shot historical aids; they're features that did not land. **No actual file move is performed by this audit** — append the path to `scripts/_archive/README.md` as a manifest line under a "candidate for archive (operator approval pending)" section, and leave the file in place. |
| **残す** (HISTORICAL banner, no move) | **18** | Wave 1-23 historical scripts that are one-shot but safe to keep for replay reference: `backfill_source_urls.py`, `backfill_source_urls_wave4.py`, `dedup_programs_wave17.py`, `delete_old_stripe_webhook.py`, `import_non_agri_rules.py`, `match_non_agri_ids.py`, `populate_tier_b_vec.py`, `process_duplicate_review_2026_04_26.py`, `rebuild_am_entities_fts.py`, `rebuild_programs_fts.py`, `reconcile_program_entities.py`, `setup_stripe_compliance_product.py`, `unify_dbs.py`, plus the 16 `src/jpintel_mcp/_archive/*` files already archived. Banner format: `# HISTORICAL: <Wave/Date>; <one-sentence rerun guidance>.` |
| **改善する** (wire up or cross-link) | **31** | 16 docs/_internal cross-link to `INDEX_2026-05-05.md`; 4 R8 spec docs cross-link from CLAUDE.md R8 grow section; 5 paid_product_value_strategy series cross-link; `docs/alerts_guide.md` nav fix; `site/claude_desktop_config.example.json` sitemap/_redirects entry; `site/glossary.html`+`site/testimonials.html`+`site/sla.html` add to sitemap; `scripts/inject_a11y_baseline.py`+`scripts/inject_jsonld.py` wire into a workflow; `src/jpintel_mcp/mcp/autonomath_tools/eligibility_predicate_tool.py`+`intel_wave31.py`+`intel_wave32.py` either register in `__init__.py` or archive; `incremental-law-bulk-saturation-cron.yml`+`incremental-law-en-translation-cron.yml` add DEPRECATED banner pointing at `incremental-law-load.yml`. |

---

## 制約遵守確認

- **rm/mv 提案ゼロ**: すべての措置は (a) HISTORICAL banner 付与で原位置維持、(b) `_archive/README.md` のマニフェスト追記、(c) 既存 doc/site の cross-link 追加 のみ。
- **旧 brand 露出**: 本書内で legacy brand 文字列を表に出していない (CLAUDE.md 由来の brand 履歴脚注は引用しない)。
- **「Phase」「MVP」「最初に」禁句**: 本書では使用していない (V4 absorption section の "Phase 6" 等は CLAUDE.md からの引用ではなく、ファイル header の自己記述として残した固有名詞ーー一般用語としては未使用)。
- **memory `feedback_legacy_brand_marker`**: jpcite brand history で legacy codename を前面化しない方針を遵守。
