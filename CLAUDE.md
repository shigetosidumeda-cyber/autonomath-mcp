# CLAUDE.md

Guidance for Claude Code sessions working in this repository. Read this before making changes.

> 2026-05-06 SOT note: volatile counts in this file are architecture snapshots. For current execution order, dirty-tree handling, and re-probe requirements, read `docs/_internal/CURRENT_SOT_2026-05-06.md` and `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md` before changing manifests, generated artifacts, deploy workflows, or public copy.

## Overview

jpcite is a Japanese public-program database exposed as both a REST API and an MCP server, backed by SQLite FTS5. Coverage (production state, 2026-05-01 post Wave 23 + Section A 部分完了; **honest counts** post phantom-moat audit): **11,684 searchable programs** (補助金・融資・税制・認定, tier S=114 / A=1,340 / B=4,186 / C=6,044 — searchable counts; full table = 14,472, tier X quarantine = 2,788) + 2,286 採択事例 + 108 融資 (担保・個人保証人・第三者保証人 三軸分解) + 1,185 行政処分 + **154 laws full-text indexed + 9,484 law catalog stubs** (e-Gov CC-BY; full-text load incremental — name resolver covers all 9,484, body text only 154; **weekly cron `incremental-law-load` bumped 100→300/run on 2026-04-29 → ~7.5 month saturation, was ~22 months**; **migration 090 added `law_articles.body_en`** for e-Gov 英訳 + foreign FDI cohort) + 50 tax_rulesets (35 → 50 on 2026-04-29 via migration 083; ZERO-coverage 研究開発税制 措置法42-4 + IT導入補助金 会計処理 backfilled per 会計士 walk) + 2,065 court_decisions + 362 bids + 13,801 invoice_registrants (PDL v1.0 delta; **monthly 4M-row zenken bulk wired 2026-04-29 via `nta-bulk-monthly` workflow + `scripts/cron/ingest_nta_invoice_bulk.py`**, first full load lands 1st-of-month 03:00 JST → ~4M rows / ~920 MB DB growth) + 181 exclusion / prerequisite rules (125 exclude + 17 prerequisite + 15 absolute + 24 other) + **8 am_tax_treaty rows** (migration 091, 国際課税 cohort surface; schema seeds ~80 countries, only 8 hand-curated rows live as of 2026-04-29). **v0.3.2 absorbs V4 + Phase A into autonomath.db** (8.29 GB unified primary DB — physically merged with jpintel.db via migration 032; V4 migrations 046–049 + 5 ingest scripts; Phase A 7 tools + 8 static taxonomies + 5 example profiles + 36協定 template): **503,930 entities** + 6.12M facts + 177,381 relations + 335,605 aliases + 28,201 am_law_article rows + 22,258 am_enforcement_detail rows + am_amount_condition (250,946 rows on disk; majority are template-default ¥500K/¥2M values from a broken ETL pass — data quality re-validation in progress, do not surface aggregate count externally) + am_compat_matrix (43,966 rows; 4,300 sourced pairs + heuristic inferences flagged status='unknown') + am_amendment_snapshot (14,596 captures, of which ~2,500 carry content hash and 144 carry definitive effective_from dates — eligibility_hash never changes between v1/v2, time-series only firm on the 144 dated rows) + am_amendment_diff (0 rows — populates from cron post-launch) + 78 jpi_* mirrored tables across tax measures, certifications, laws, authorities, adoptions, enforcements, loans, mutual insurance, regions. MCP exposes **139 tools** at default gates (`tools/list` runtime count; verify with `len(await mcp.list_tools())` before bumping manifests). **3 additional tools are gated off pending fix** (smoke test 2026-04-29 found them 100% broken): `query_at_snapshot` (no migration 067 → AUTONOMATH_SNAPSHOT_ENABLED), `intent_of` + `reason_answer` (reasoning package missing → AUTONOMATH_REASONING_ENABLED). `related_programs` was un-gated 2026-04-29 (am_relation walk live, smoke test passing). Flipping fix-gate flags changes the runtime surface; always verify with `len(await mcp.list_tools())` before bumping a manifest.

> Note: legacy strings of `11,547 programs`, `416,375 entities`, `424,054 entities`, `55 tools`, `59 tools`, and `v0.2.0 baseline` may still appear in some downstream `docs/`, `site/`, and launch-asset files — those reflect pre-v15 / pre-V4 / pre-Phase-A snapshots and are retained as historical-state markers. Authoritative current numbers are above and are now reflected in `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json` (manifest-bump CLI bumped to v0.3.0 on 2026-04-25; v0.3.1 on 2026-04-29 carried Wave 30 §52 disclaimer hardening across 11 sensitive-tool branches + brand rename + dead URL fix + homepage CRO + phantom-moat copy fix + 4 broken-tool gates + 3 new disclaimer settings + tool_count 72→68→69 after `related_programs` un-gate; **v0.3.2 on 2026-04-30** carries jpcite brand rename across user-facing surfaces + Section A partial completion: A4 done [`am_source.content_hash` NULL 281→0], A5 partial [`last_verified` 1→94, target 95,000], A6 done [`am_entity_facts.source_id` 0→81,787, target 80,000 met], D9 done [`programs.aliases_json` non-empty 82→9,996 across S/A/B/C], B13 partial [prefecture 欠損 9,509→6,011, municipality 欠損 11,377→11,350], E1 done [`license_review_queue.csv` 1,425 行], C1/C2/C3/C4 done).

- **Operator**: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708), 代表 梅田茂利, info@bookyou.net
- **Product**: jpcite (PyPI package: `autonomath-mcp` — legacy distribution name retained; user-facing brand is jpcite)
- **Launch target**: 2026-05-06 on Fly.io Tokyo + Cloudflare Pages + Stripe metered billing
- **Business model**: ¥3/request fully metered (税込 ¥3.30), anonymous tier gets 3 req/day free per IP (JST 翌日 00:00 リセット), 100% organic acquisition, solo + zero-touch operations

## Wave 23 changelog (2026-04-29 industry packs)

3 new MCP tools shipped at the cohort revenue model's "Industry packs" pillar (cohort #8). Tool count 86 → **89**. New file: `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py` (gated by `AUTONOMATH_INDUSTRY_PACKS_ENABLED`, default ON). NO migration needed — `am_industry_jsic` (50 rows) already covers JSIC majors A-T; the wrappers filter `programs` by JSIC major + name keyword union and pull citations from `nta_saiketsu` + `nta_tsutatsu_index` (migration 103, ~140 saiketsu / 3,221 tsutatsu).

- **`pack_construction`** (JSIC D): top 10 programs (建設・建築・住宅・耐震・改修・空き家・工事・下請 fence) + up to 5 国税不服審判所 裁決事例 (法人税・消費税) + up to 3 通達 references (法基通・消基通). 1 req ¥3, NO LLM, §52/§47条の2 sensitive.
- **`pack_manufacturing`** (JSIC E): top 10 programs (ものづくり・製造・設備投資・省エネ・GX・脱炭素・事業再構築・IT導入・DX 等) + up to 5 saiketsu (法人税・所得税) + up to 3 通達 (法基通). Same envelope contract.
- **`pack_real_estate`** (JSIC K): top 10 programs (不動産・空き家・住宅・賃貸・改修・流通 等) + up to 5 saiketsu (所得税・相続税・法人税) + up to 3 通達 (所基通・相基通). Same envelope contract.

**Landing pages**: `site/audiences/{construction,manufacturing,real_estate}.html` (static HTML, no JS fetch — programs rendered server-side from corpus snapshot). Surfaces 8 sample programs each with first-party `source_url` links.

**Saved-search seeds**: `data/sample_saved_searches.json` (9 saved searches × frequency='weekly' — schema CHECK forbids 'monthly', so the spec's monthly cadence runs on the closest available weekly cron via `run_saved_searches.py`). 3 per industry, channel_format='email' default.

**Tests**: `tests/test_industry_packs.py` — 10 tests, all passing. One happy-path per industry asserts ≥5 programs + ≥1 通達 reference; manufacturing + real_estate also assert ≥1 saiketsu citation. Construction saiketsu set is honestly-thin (only 1 法人税 row matches construction keywords across 137 saiketsu rows) — test does NOT gate on it.

**Honest gap**: NTA saiketsu corpus is small (137 rows) — the construction cohort yields 0-1 citations on 法人税/消費税 axis. Not a code defect, just thin upstream data; will compound naturally as `nta_saiketsu` ingest matures.

## Wave 21-22 changelog (2026-04-29)

17 parallel agents landed migrations **085-101** (gaps at 084/093/094/095/100 are intentional — number reservations during agent merge). Tool count 69 → **74** (further evolved post Wave 23 to 89 — see Overview). Routes 141 → **194** (post Wave 23 cron + courses + client_profiles wiring). New cron + workflow surface area below.

- **085** `usage_events.client_tag` — X-Client-Tag header for 顧問先 attribution (税理士 fan-out cohort).
- **086** `api_keys` parent/child — sub-API-key SaaS B2B fan-out (one parent key issues child keys per 顧問先).
- **087** `idempotency_cache` — cost-cap + idempotency middleware backing table.
- **088** `houjin_watch` — corp watch list + webhook trigger (M&A pillar; real-time amendment surface).
- **089** `audit_seal` — 税理士 monthly audit-seal pack (`api/_audit_seal.py` is the implementation).
- **090** `law_articles.body_en` — 英訳 e-Gov column (foreign FDI cohort enabler).
- **091** `am_tax_treaty` — international tax treaty table (国際課税 cohort); schema seeds ~80 countries, 8 rows hand-curated as of 2026-04-29.
- **092** `foreign_capital_eligibility` — flag column for 外資系 eligibility filtering.
- **096** `client_profiles` — 税理士 顧問先 master table; router file `api/client_profiles.py` wired in `main.py:1649` under `/v1/me/client_profiles` (4 paths live in production openapi, verified 2026-05-04).
- **097** `saved_searches.profile_ids` — per-client fan-out column on saved_searches.
- **098** `program_post_award_calendar` — 採択後 monitoring calendar (post-award engagement).
- **099** `recurring_engagement` — Slack digest + email course + quarterly PDF substrate; route surface in `api/courses.py` wired in `main.py:1657` under `/v1/me/courses` (2 paths live in production openapi, verified 2026-05-04). Quarterly PDF + Slack webhook live via `recurring_quarterly` router at `main.py:1664`.
- **101** `trust_infrastructure` (target_db: autonomath) — SLA, corrections, cross-source agreement, stale-data tracking.

**New cron scripts** (`scripts/cron/`): `backup_autonomath.py`, `backup_jpintel.py`, `dispatch_webhooks.py`, `expire_trials.py`, `run_saved_searches.py`, `send_daily_kpi_digest.py`, `ingest_nta_invoice_bulk.py`, `incremental_law_fulltext.py`, `index_now_ping.py`, `predictive_billing_alert.py`, `regenerate_audit_log_rss.py`, `r2_backup.sh`.

**New GitHub Actions** (`.github/workflows/`): `analytics-cron.yml`, `incremental-law-load.yml`, `index-now-cron.yml`, `ministry-ingest-monthly.yml`, `nta-bulk-monthly.yml`, `saved-searches-cron.yml`, `trial-expire-cron.yml`, `weekly-backup-autonomath.yml`, `competitive-watch.yml`, `tls-check.yml`, `self-improve-weekly.yml`.

**New top-level directories**: `monitoring/` (sentry rules + SLA + uptime metrics), `badges/` (5 SVGs for README), `analytics/` (jsonl baselines), `scripts/etl/` (`batch_translate_corpus.py`, `harvest_implicit_relations.py`, `repromote_amount_conditions.py`).

**SDK plugin surface**: `sdk/freee-plugin/`, `sdk/mf-plugin/` (full Fly app with oauth_callback + proxy_endpoints), `sdk/integrations/{email,excel,google-sheets,kintone,slack}/`.

**Wave 21 tools confirmed live** (5, autonomath gate, AUTONOMATH_COMPOSITION_ENABLED on by default — see `autonomath_tools/composition_tools.py`): `apply_eligibility_chain_am`, `find_complementary_programs_am`, `simulate_application_am`, `track_amendment_lineage_am`, `program_active_periods_am`.

**Wave 22 composition tools (live, 2026-04-29 — `autonomath_tools/wave22_tools.py`, AUTONOMATH_WAVE22_ENABLED on by default):** 5 new MCP tools that compound call-density on top of Wave 21 (74 → **79** at default gates; verified via `len(mcp._tool_manager.list_tools())`). Each tool emits `_next_calls` (compound multiplier), `corpus_snapshot_id` + `corpus_checksum` (auditor reproducibility), and a `_disclaimer` envelope on the four §52 / §72 / §1 sensitive surfaces. NO LLM call inside the tools — pure SQLite + Python.
  - `match_due_diligence_questions` — DD question deck (30-60) tailored to industry × portfolio × 与信 risk by joining `dd_question_templates` (60 rows, migration 104) with houjin / adoption / enforcement / invoice corpora. Sensitive (§52 / §72 — checklist, not advice).
  - `prepare_kessan_briefing` — 月次 / 四半期 summary of program-eligibility changes since last 決算 by joining `am_amendment_diff` + `jpi_tax_rulesets` within the FY window. Sensitive (§52 — 決算 territory).
  - `forecast_program_renewal` — Probability + window of program renewal in next FY based on historical `am_application_round` cadence + `am_amendment_snapshot` density. 4-signal weighted average (frequency / recency / pipeline / snapshot). NOT sensitive — statistical, no disclaimer.
  - `cross_check_jurisdiction` — Registered (法務局) vs invoice (NTA) vs operational (採択) jurisdiction breakdown for 税理士 onboarding. Detects 不一致 across `houjin_master` / `invoice_registrants` / `adoption_records`. Sensitive (§52 / §72 / 司法書士法 §3).
  - `bundle_application_kit` — Complete kit assembly: program metadata + cover letter scaffold + 必要書類 checklist + similar 採択例. Pure file assembly, NO DOCX generation. Sensitive (行政書士法 §1 — scaffold + 一次 URL only, no 申請書面 creation).

**Migration 104** (`scripts/migrations/104_wave22_dd_question_templates.sql`, target_db: autonomath, idempotent): adds `dd_question_templates` (60 seeded questions across 7 categories: credit / enforcement / invoice_compliance / industry_specific / lifecycle / tax / governance) + `v_dd_question_template_summary` view. Indexed on (industry_jsic_major, severity_weight DESC) for the matcher hot path.

**Wave 22 migration substrate (2026-04-22..29 — separate from this Wave 22 MCP tools landing)**: tables in migrations 088 / 089 / 090 / 091 / 092 / 096..099 / 101 (houjin_watch / audit_seal / tax_treaty / foreign_capital_eligibility / client_profiles / program_post_award_calendar / recurring_engagement / trust_infrastructure) — REST-only surfaces or pending wiring; the 5 Wave 22 MCP tools above are an additive layer over the 8.29 GB unified DB and do not depend on these wires.

## Cohort revenue model (8 cohorts, locked 2026-04-29)

Strategy convergence after phantom-moat audit. **Y1 ¥36-96M / Y3 ¥120-600M ARR ceiling.** Each cohort has a dedicated capture surface (migration / cron / route) — listed below for traceability.

1. **M&A** — `houjin_watch` (mig 088) + `dispatch_webhooks.py` cron. Real-time corp amendment surface, webhook delivery to deal-side ops.
2. **税理士 (kaikei pack)** — `audit_seal` (mig 089) + `api/_audit_seal.py` + `regenerate_audit_log_rss.py`. Monthly audit-seal pack PDF + RSS, per 顧問先 fan-out via `api_keys` parent/child (mig 086) and `client_profiles` (mig 096).
3. **会計士** — overlaps with 税理士 surface; differentiated by `tax_rulesets` v2 (50 rows post mig 083) covering 研究開発税制 + IT導入会計処理.
4. **Foreign FDI** — `law_articles.body_en` (mig 090) + `am_tax_treaty` (mig 091, schema seeds ~80 countries, 8 rows live) + `foreign_capital_eligibility` (mig 092). 英訳 corpus via `batch_translate_corpus.py` ETL.
5. **補助金 consultant** — `client_profiles` (mig 096) + `saved_searches.profile_ids` (mig 097) + `run_saved_searches.py` cron. Sub-API-key fan-out so consultant runs N顧問先 saved searches as one cron.
6. **中小企業 LINE** — line_users + widget_keys (migs 021/022 already shipped). Light-weight conversational surface; no Wave 21-22 additions.
7. **信金商工会 organic** — programs S/A tier coverage + `competitive-watch.yml` workflow + organic SEO via `index_now_ping.py`. No paid acquisition.
8. **Industry packs** — healthcare + real_estate + GX gates (existing), plus `program_post_award_calendar` (mig 098) for 採択後 vertical monitoring.

**Engagement multiplier** across all 8: `recurring_engagement` (mig 099) + `courses.py` (Slack digest / email course / quarterly PDF) + `trust_infrastructure` (mig 101, SLA + corrections + cross-source) — these are horizontal substrate, not cohort-specific.

## Architecture

Package is named `autonomath-mcp` on PyPI but the source directory is `src/jpintel_mcp/` (legacy name, do **not** rename — entry points and imports depend on it).

```
src/jpintel_mcp/
  api/      FastAPI REST, mounted at /v1/*
  mcp/      FastMCP stdio server (139 tools at default gates, protocol 2025-06-18; verify with len(await mcp.list_tools()) before bumping manifests)
  ingest/   Data ingestion + canonical tier scoring
  db/       SQLite migrations + query helpers
  billing/  Stripe metered billing integration
  email/    Transactional email
```

- **Database**: two separate SQLite files, no ATTACH / cross-DB JOIN.
  - `data/jpintel.db` (~352 MB live as of 2026-04-29, FTS5 trigram). Core tables: `programs` (11,684 searchable / 14,472 total), `api_keys`, `exclusion_rules` (181 rows), `subscribers`, `case_studies` (2,286 rows), `loan_programs` (108 rows), `enforcement_cases` (1,185 rows). Expansion tables: `laws` (9,484 rows, 継続ロード中), `tax_rulesets` (50 rows live), `court_decisions` (2,065 rows live), `bids` (362 rows live), `invoice_registrants` (13,801 rows delta-only at this snapshot; PDL v1.0 attribution live; **monthly 4M-row zenken bulk automation wired 2026-04-29** — `.github/workflows/nta-bulk-monthly.yml` + `scripts/cron/ingest_nta_invoice_bulk.py`, first full load 1st-of-month 03:00 JST, +migration 081 covering indexes for houjin/prefecture rollups), plus join tables `program_law_refs`, `enforcement_decision_refs`.
  - `autonomath.db` (~9.4 GB at **repo root** — note that `data/autonomath.db` is a 0-byte placeholder; production code reads from the root path, **unified primary DB** as of 2026-04-25 17:25 — migration 032 merged jpintel.db tables in as `jpi_*`). Entity-fact EAV schema: `am_entities` (**503,930 rows** across 12 record_kinds: adoption 215,233 / corporate_entity 166,969 / statistic 73,960 / enforcement 22,255 / invoice_registrant 13,801 / program 8,203 / case_study 2,885 / tax_measure 285 / law 252 / certification 66 / authority 20 / document 1), `am_entity_facts` (6.12M rows), `am_relation` (177,381 edges, 15 canonical relation types), `am_alias` (335,605 rows), `am_authority`, `am_region` (1,966 rows, all 5-digit codes), `am_tax_rule`, `am_subsidy_rule`, `am_application_round` (1,256 rows; 54 future / 17 within 60d), `am_loan_product`, `am_insurance_mutual`, `am_enforcement_detail` (22,258 rows; 6,455 with houjin_bangou; grant_refund 1,498 / subsidy_exclude 476 / fine 26 carry amount_yen), `am_amendment_snapshot` (14,596 rows — eligibility_hash never changes between v1/v2, time-series is fake), `am_amount_condition` (250,946 rows; majority template-default — re-validation in progress), `am_industry_jsic` (50 rows — JSIC major+partial medium only), `am_target_profile` (43 rows), `am_law_article` (28,201 rows), plus FTS5 (`am_entities_fts` trigram + `am_entities_fts_uni` unicode61) and sqlite-vec tables (`am_entities_vec` + 5 tiered vec indexes). 78 mirrored `jpi_*` tables. Cross-domain views: `entity_id_map`, `v_program_full`, `v_houjin_360`, `v_readiness_input`. AUTONOMATH_ENABLED gate retained for legacy paths.
- **Static site**: `site/` — hand-written HTML, generated program pages, deployed to Cloudflare Pages.
- **Docs**: `docs/*.md` built via mkdocs, served at `/docs`.
- **Console scripts** (from `pyproject.toml`):
  - `autonomath-api` → `jpintel_mcp.api.main:run`
  - `autonomath-mcp` → `jpintel_mcp.mcp.server:run`

## V4 absorption (complete 2026-04-25)

Absorption from `~/Autonomath/` landed via migrations 046–049 + 5 ingest scripts + 4 universal endpoints. Signaling doc: `docs/_internal/COORDINATION_2026-04-25.md`.

- **Tables added** (migrations applied): `am_entity_annotation` + `am_annotation_kind` (046, 16,474 annotation rows), `am_validation_rule` + `am_validation_result` (047, 6 generic predicates registered), `jpi_pc_program_health` (048, 66 programs). Migration 049 added three columns: `am_source.license` (97,270 / 97,272 filled, 805 unknown), `am_entity_facts.source_id` (NULL backfill pending), `jpi_feedback.entity_canonical_id` (forward-only).
- **Ingest landed** (`scripts/ingest_*.py` + `scripts/port_validation_rules.py` + `scripts/fill_license.py`): examiner_feedback (3,109 / 8,189 program-resolved → 16,474 annotations; 5,080 unresolved are non-program category names like "GX関連補助金"), gbiz (79,876 new corporate_entity rows + 861,137 new corp.* facts spanning 21 new field_names), case_studies supplement (1,901 NEW into `jpi_adoption_records`, 6,959 already-present), license bulk fill (NTA→pdl_v1.0 87k, gov_standard 7k, public_domain 953, JST→proprietary 617, e-Gov→cc_by_4.0 186).
- **Endpoints**: 4 universal tools wired into `autonomath_router` (which **is** mounted at `api/main.py:557`, contrary to legacy stale comment). REST + MCP both live: `GET /v1/am/annotations/{entity_id}`, `POST /v1/am/validate`, `GET /v1/am/provenance/{entity_id}`, `GET /v1/am/provenance/fact/{fact_id}`. New files: `mcp/autonomath_tools/{annotation,validation,provenance}_tools.py`, `api/_validation_predicates.py`.
- **Precompute**: `scripts/cron/precompute_refresh.py` REFRESHERS dict gained `jpi_pc_program_health` (33rd target, autonomath-DB branch). Invocation: `--only jpi_pc_program_health`.

Post-V4 counts: `am_entities` 424,054 → **503,930**; `am_entities` corporate_entity 87,093 → **166,969**; `am_entity_facts` 5.26M → **6.12M**; `jpi_adoption_records` 199,944 → **201,845**. Tool count 55 → **59** → **66** (4 universal: annotations + validate + provenance entity + provenance fact; +7 Phase A absorption). Manifests bumped to **v0.3.0** on 2026-04-25 (`pyproject.toml` / `server.json` / `mcp-server.json` / `dxt/manifest.json` / `smithery.yaml`); `dist/` carries v0.3.0 sdist + wheel + regenerated `.mcpb` alongside the v0.2.0 baseline artifacts. Live PyPI / npm publish deferred to post-launch +24h grace per launch CLI plan.

Pending follow-ups (deferred, non-blocking): FTS+vec rebuild for new annotation text + 21 new corp.* facts (~2.2h read-only); `am_entity_facts.source_id` backfill from existing `am_entity_source` rollup.

### Phase A absorption (complete 2026-04-25)

- **7 new tools**: `list_static_resources_am`, `get_static_resource_am`, `list_example_profiles_am`, `get_example_profile_am`, `render_36_kyotei_am`, `get_36_kyotei_metadata_am`, `deep_health_am`.
- **8 static taxonomies + 5 example profiles** in `data/autonomath_static/`.
- **4 utility modules**: `wareki.py`, `jp_money.py`, `jp_constants.py`, `templates/saburoku_kyotei.py`.
- **1 new model module**: `models/premium_response.py` (PremiumResponse, ProvenanceBadge, AdoptionScore, AuditLogEntry).
- **1 new health endpoint**: `/v1/am/health/deep` (mounted on `health_router`, no AnonIpLimitDep).
- **REST**: 7 new routes under `/v1/am/static`, `/v1/am/example_profiles`, `/v1/am/templates/saburoku_kyotei`, `/v1/am/health/deep`.
- **Models package consolidated**: legacy `models.py` (444 lines) merged into `models/__init__.py` to coexist with `premium_response.py`.
- **36協定 launch gate**: `render_36_kyotei_am` + `get_36_kyotei_metadata_am` are gated behind `AUTONOMATH_36_KYOTEI_ENABLED` (default `False`). 36協定 is a 労基法 §36 + 社労士法 regulated obligation; incorrect generation can expose the operator to legal liability and brand damage. The gate keeps both tools out of `mcp.list_tools()` until the operator completes a legal review (社労士 supervision arrangement + customer-facing disclaimer alignment). Even when enabled, every render response carries a `_disclaimer` field declaring the output a draft requiring 社労士 confirmation. See `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md`.

## Non-negotiable constraints

- **¥3/req metered only** (税込 ¥3.30). No tier SKUs, no seat fees, no annual minimums. Any code or UI that introduces "Free tier" / `tier-badge` / "Starter plan" / "Pro plan" is a regression. The only free path is the anonymous 3 req/day rate limit (IP-based, JST 翌日 00:00 リセット).
- **100% organic acquisition.** No paid ads, no sales calls, no cold outreach. Zero-touch ops means no DPA/MSA negotiation, no Slack Connect, no phone support, no onboarding calls.
- **Solo ops.** No delegation, no CS team. Every feature must be fully self-service.
- **Data hygiene.** Every `programs` row must cite a primary source (government ministry, prefecture, 日本政策金融公庫, etc.). Aggregators like noukaweb, hojyokin-portal, biz.stayway are **banned** from `source_url` — past incidents created 詐欺 risk.
- **Trademark.** The name "jpintel" collides with Intel (著名商標衝突濃厚). Do **not** revive the jpintel brand in user-facing copy. The product is **jpcite** (renamed from AutonoMath on 2026-04-30); the operator is **Bookyou株式会社**. This distinction matters — do not conflate.

## Key commands

```bash
# Install (dev + site extras; use .venv/bin/* below)
pip install -e ".[dev,site]"
playwright install chromium   # only needed for e2e suite

# Run API locally
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080

# Run MCP server (stdio)
.venv/bin/autonomath-mcp

# Regenerate per-program SEO pages
.venv/bin/python scripts/generate_program_pages.py

# Nightly source URL liveness scan (filter by tier)
.venv/bin/python scripts/refresh_sources.py --tier S,A

# Tests
.venv/bin/pytest              # unit + integration
.venv/bin/pytest tests/e2e/   # Playwright e2e (needs [e2e] extras)

# DB inspection
sqlite3 data/jpintel.db "SELECT tier, COUNT(*) FROM programs WHERE excluded=0 GROUP BY tier;"
```

## Quality gates (before deploying)

- CI lint target passes: `uv run ruff check scripts/generate_cross_hub_pages.py scripts/generate_geo_program_pages.py scripts/generate_industry_hub_pages.py scripts/generate_industry_program_pages.py scripts/generate_prefecture_pages.py scripts/generate_program_pages.py scripts/regen_llms_full.py scripts/regen_llms_full_en.py scripts/etl/generate_program_rss_feeds.py`
- `.venv/bin/pytest` passes (full suite, including integration)
- `mypy src/` passes (best effort — treat new errors as red)
- OpenAPI spec regenerated: `.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json`
- Static site builds cleanly: `mkdocs build --strict`

Pre-commit hooks are configured in `.pre-commit-config.yaml` — do not bypass with `--no-verify`.

## Release checklist

1. Bump version in both `pyproject.toml` and `server.json` (they must match).
2. Update `CHANGELOG.md`.
3. Tag and push: `git tag v0.x.y && git push --tags`.
4. PyPI: `python -m build && twine upload dist/*` (requires `PYPI_TOKEN`).
5. MCP registry: `mcp publish server.json` — see `scripts/mcp_registries.md` for the list of registries.
6. Cloudflare Pages auto-deploys from `main`; Fly.io deploy via `fly deploy` (see `fly.toml`).

## Common gotchas

- **FTS5 trigram tokenizer** causes false single-kanji overlap matches. Example: searching `税額控除` also hits rows mentioning only `ふるさと納税` because both contain `税`. Use phrase queries (`"税額控除"` with quotes) for 2+ character kanji compounds. See `src/jpintel_mcp/api/programs.py` for the current workaround.
- **`tier='X'` is the quarantine tier.** All search paths must exclude it. `generate_program_pages.py` filters `tier IN ('S','A','B','C')` — keep that filter.
- **`source_fetched_at` is a uniform sentinel** across rows that were bulk-rewritten. Render it as **"出典取得"** (when we last fetched), never as **"最終更新"** (which would imply we verified currency). Semantic honesty matters under 景表法 / 消費者契約法.
- **Use `pykakasi`, not `cutlet`** for Hepburn slug generation. `cutlet` pulls in `mojimoji` which fails to compile on macOS Rosetta.
- **Rate limit reset timezones differ.** Anonymous quota resets at JST midnight; authenticated API-key quota resets at UTC midnight. Dashboard and docs copy must not claim both are UTC.
- **Stripe checkout pitfall.** Do **not** pass `consent_collection={"terms_of_service": "required"}` — this causes a 500 in live mode. Use `custom_text.submit.message` for the ToS link instead.
- **DB backups live alongside the DB.** Files like `data/jpintel.db.bak-*` and `data/jpintel.db.bak.*` are backups — never commit them. Verify `.gitignore` covers them before `git add data/`.
- **CORS allowlist must include jpcite.com apex AND www.** `JPINTEL_CORS_ORIGINS` (Fly secret + `config.py` default) must list `https://jpcite.com`, `https://www.jpcite.com`, `https://api.jpcite.com` at minimum (plus the legacy `zeimu-kaikei.ai` apex+www and `autonomath.ai` apex+www until those brands are fully retired). `OriginEnforcementMiddleware` 403s any unlisted origin **before** the route handler runs — every browser-side feature (prescreen UI, saved searches, customer webhooks dashboard, audit log) breaks simultaneously if the apex or www variant is missing. 2026-04-29 launch persona walk caught this: secret was set to the autonomath.ai brand only, all browser POSTs returned 403 `origin_not_allowed`. See `docs/runbook/cors_setup.md` for verify + add-origin procedure.
- **Autonomath-target migrations land via `entrypoint.sh`, not `release_command`.** `fly.toml`'s `release_command = "python scripts/migrate.py"` is intentionally commented out — `migrate.py` does not filter by `target_db` and would corrupt `autonomath.db` by creating jpintel-default tables (`programs`, `api_keys`) that schema_guard then rejects as FORBIDDEN. Instead, `entrypoint.sh` §4 auto-discovers every `scripts/migrations/*.sql` whose first line is `-- target_db: autonomath` and applies it idempotently to `$AUTONOMATH_DB_PATH` on each boot. **When adding a new autonomath-target migration:** (1) make the very first line `-- target_db: autonomath`, (2) use only `CREATE * IF NOT EXISTS` / idempotent DML so re-runs on every boot are safe, (3) name rollback companions `*_rollback.sql` so the entrypoint loop excludes them, (4) verify with `grep -l "target_db: autonomath" scripts/migrations/` that the file is picked up. Expected boot log line: `autonomath self-heal migrations: applied=N skipped=M`. **Do NOT** re-enable `release_command` to "fix" this — 87 migrations × 8.29 GB autonomath.db hangs the Fly release machine, and `migrate.py` still lacks `target_db` filtering.

## What NOT to do

- Never mock the database in integration tests — a past incident had mocked tests pass while a production migration failed.
- Never reintroduce tier-based pricing UI, feature gates labeled "Pro", or seat counters.
- Never silently refetch `source_url` and rewrite `source_fetched_at` without actually having performed the fetch — the column's semantics must stay honest.
- Never rename `src/jpintel_mcp/` to `src/autonomath_mcp/` — the PyPI package name is `autonomath-mcp`, but the import path is the legacy `jpintel_mcp` and changing it will break every consumer.
- Never commit `data/jpintel.db.bak.*` or `.wrangler/` or `.venv/` — if any slip through, add them to `.gitignore`.
- Never push with `--no-verify` or `--no-gpg-sign`. Fix the hook failure.
- Never revive the "jpintel" brand in user-facing surfaces (site copy, README headlines, marketing). Internal file paths are fine; user-visible strings are not.
- Never put LLM API imports (`anthropic`, `openai`, `google.generativeai`, `claude_agent_sdk`) anywhere under `src/`, `scripts/cron/`, `scripts/etl/`, or `tests/`. Operator-only offline tools that need an LLM go in `tools/offline/`. The CI guard `tests/test_no_llm_in_production.py` enforces this — never weaken it. Same rule applies to LLM API-key env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`) on real code lines.

## Key files

- `pyproject.toml` — distribution + console-script config (`autonomath-api`, `autonomath-mcp`)
- `server.json` — MCP registry manifest (version must match `pyproject.toml`)
- `src/jpintel_mcp/api/main.py` — FastAPI app + middleware wiring
- `src/jpintel_mcp/api/programs.py` — search logic + FTS tokenizer workaround
- `src/jpintel_mcp/mcp/server.py` — FastMCP entry point, 139 tools total at default gates:
  - **39 prod tools** backed by jpintel.db (programs + case_studies + loan_programs + enforcement + `get_usage_status` quota probe + 7 one-shot discovery tools [smb_starter_pack / subsidy_combo_finder / deadline_calendar / dd_profile_am / similar_cases / regulatory_prep_pack / subsidy_roadmap_3yr] + expansion: laws [9,484 rows, 継続ロード中] / tax_rulesets [50 rows] / court_decisions [0 rows, schema ready] / bids [0 rows, schema ready] / invoice_registrants [13,801 rows delta, monthly 4M-row bulk cron wired 2026-04-29] + cross-dataset glue)
  - **50 autonomath tools** backed by autonomath.db at default gates (52 total when remaining broken-tool gates flipped ON; +2 if 36協定 gate flipped), registered at `server.py:4220` via `if settings.autonomath_enabled: from jpintel_mcp.mcp import autonomath_tools`. Package `src/jpintel_mcp/mcp/autonomath_tools/` exports: `search_tax_incentives`, `search_certifications`, `list_open_programs`, `enum_values_am`, `search_by_law`, `active_programs_at`, `search_acceptance_stats_am` (tools.py), `get_am_tax_rule` (tax_rule_tool.py), `search_gx_programs_am`, `search_loans_am`, `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am` (autonomath_wrappers.py), `list_tax_sunset_alerts`, V4 universal (`get_annotations`, `validate`, `get_provenance`, `get_provenance_for_fact`), Phase A (`list_static_resources_am`, `get_static_resource_am`, `list_example_profiles_am`, `get_example_profile_am`, `deep_health_am`), additional tools (`graph_traverse`, `unified_lifecycle_calendar`, `program_lifecycle`, `program_abstract_structured`, `prerequisite_chain`, `rule_engine_check`, `related_programs`), and **Wave 21 composition tools** (`apply_eligibility_chain_am`, `find_complementary_programs_am`, `simulate_application_am`, `track_amendment_lineage_am`, `program_active_periods_am` — `composition_tools.py`, AUTONOMATH_COMPOSITION_ENABLED gate, default ON). **Gated off pending fix (smoke test 2026-04-29 broken)**: `query_at_snapshot` (`AUTONOMATH_SNAPSHOT_ENABLED`, migration 067 missing), `intent_of` + `reason_answer` (`AUTONOMATH_REASONING_ENABLED`, reasoning package missing). `related_programs` was un-gated 2026-04-29. `render_36_kyotei_am` + `get_36_kyotei_metadata_am` are gated behind `AUTONOMATH_36_KYOTEI_ENABLED` (default off — would push count to 76).
- `src/jpintel_mcp/api/autonomath.py` — REST router for autonomath tools at `/v1/am/*`. **Mounted in `main.py` at line 987** (`app.include_router(autonomath_router, dependencies=[AnonIpLimitDep])`). Surfaces `am/annotations`, `am/validate`, `am/provenance`, plus Phase A static/example/template routes.
- `src/jpintel_mcp/billing/` — Stripe metered billing
- `site/_templates/program.html` — per-program SEO page template
- `scripts/generate_program_pages.py` — static page generator
- `scripts/refresh_sources.py` — nightly URL liveness scan
- `scripts/export_openapi.py` — regenerates `docs/openapi/v1.json`
- `fly.toml` — Fly.io Tokyo deployment
- `mkdocs.yml` — docs site config
- `DIRECTORY.md` — detailed directory map (keep in sync when restructuring)
