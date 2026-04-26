# CLAUDE.md

Guidance for Claude Code sessions working in this repository. Read this before making changes.

## Overview

AutonoMath is a Japanese public-program database exposed as both a REST API and an MCP server, backed by SQLite FTS5. Coverage (production state, 2026-04-26 post Wave 20 dedup): **10,790 searchable programs** (補助金・融資・税制・認定, tier S=114 / A=1,340 / B=3,292 / C=6,044 — searchable counts; full table incl. tier X quarantine = 13,578, tier X = 1,923 broken down as external_info_entry 875 / no_amount_data 561 / placeholder_url 205 / dedup_ambiguous_resolved 175 / legacy_year_budget 60 / aggregator_only 33 / dead_source_url 8 / unknown_target 6) + 2,286 採択事例 + 108 融資 (担保・個人保証人・第三者保証人 三軸分解) + 1,185 行政処分 + 9,484 laws (e-Gov CC-BY, 継続ロード中) + 35 tax_rulesets + 2,065 court_decisions + 362 bids + 13,801 invoice_registrants (PDL v1.0 delta) + 181 exclusion / prerequisite rules (125 exclude + 17 prerequisite + 15 absolute + 24 other). **v0.3.0 absorbs V4 + Phase A into autonomath.db** (8.29 GB unified primary DB — physically merged with jpintel.db via migration 032; V4 migrations 046–049 + 5 ingest scripts; Phase A 7 tools + 8 static taxonomies + 5 example profiles + 36協定 template): **503,930 entities** + 6.12M facts + 23,805 relations + 335,605 aliases + 28,048 am_law_article rows + 22,258 am_enforcement_detail rows + 35,713 am_amount_condition rows + 78 jpi_* mirrored tables across tax measures, certifications, laws, authorities, adoptions, enforcements, loans, mutual insurance, regions. MCP exposes **72 tools** at default gates (`tools/list` runtime count, AUTONOMATH_ENABLED=1, 36協定 + healthcare + real_estate gated off): 39 jpintel + 33 autonomath. Composition revealed by 2026-04-26 audit: prior `66` literal was stale — `graph_traverse`, `unified_lifecycle_calendar`, `program_lifecycle`, `program_abstract_structured`, `prerequisite_chain`, `rule_engine_check`, `query_at_snapshot`, plus the new `get_usage_status` (jpintel-side quota probe) had drifted from the manifest count. Always verify with `len(mcp._tool_manager.list_tools())` before bumping a manifest.

> Note: legacy strings of `11,547 programs`, `416,375 entities`, `424,054 entities`, `55 tools`, `59 tools`, and `v0.2.0 baseline` may still appear in some downstream `docs/`, `site/`, and launch-asset files — those reflect pre-v15 / pre-V4 / pre-Phase-A snapshots and are retained as historical-state markers. Authoritative current numbers are above and are now reflected in `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json` (all bumped to v0.3.0 by the manifest-bump CLI on 2026-04-25).

- **Operator**: Bookyou株式会社 (法人番号 T8010001213708), 代表 梅田茂利, info@bookyou.net
- **Product**: AutonoMath (PyPI package: `autonomath-mcp`)
- **Launch target**: 2026-05-06 on Fly.io Tokyo + Cloudflare Pages + Stripe metered billing
- **Business model**: ¥3/request fully metered (税込 ¥3.30), anonymous tier gets 50/month free (JST 月初 00:00 リセット), 100% organic acquisition, solo + zero-touch operations

## Architecture

Package is named `autonomath-mcp` on PyPI but the source directory is `src/jpintel_mcp/` (legacy name, do **not** rename — entry points and imports depend on it).

```
src/jpintel_mcp/
  api/      FastAPI REST, mounted at /v1/*
  mcp/      FastMCP stdio server (72 tools at default gates, protocol 2025-06-18: 39 core + 33 autonomath [V1 + 4 V4 universal + Phase A + lifecycle/abstract/prerequisite/graph_traverse/snapshot/rule_engine], gated by AUTONOMATH_ENABLED)
  ingest/   Data ingestion + canonical tier scoring
  db/       SQLite migrations + query helpers
  billing/  Stripe metered billing integration
  email/    Transactional email
```

- **Database**: two separate SQLite files, no ATTACH / cross-DB JOIN.
  - `data/jpintel.db` (316 MB live as of 2026-04-25, FTS5 trigram). Core tables: `programs`, `api_keys`, `exclusion_rules`, `subscribers`, `case_studies`, `loan_programs`, `enforcement_cases`. Expansion tables (schema pre-built 2026-04-24): `laws` (9,484 rows, 継続ロード中), `tax_rulesets` (35 rows live), `court_decisions` (2,065 rows live), `bids` (362 rows live), `invoice_registrants` (13,801 rows delta-only; PDL v1.0 attribution live, full 4M-row monthly bulk pending), plus join tables `program_law_refs`, `enforcement_decision_refs`.
  - `autonomath.db` (8.29 GB at **repo root** — note that `data/autonomath.db` is a 0-byte placeholder; production code reads from the root path, **unified primary DB** as of 2026-04-25 17:25 — migration 032 merged jpintel.db tables in as `jpi_*`). Entity-fact EAV schema: `am_entities` (424,054 rows across 12 record_kinds: adoption 215k / corporate_entity 87,093 (houjin 87,076 + nintei_shien 17 — 認定経営革新等支援機関の銀行) / statistic 74k / enforcement 22k / invoice_registrant 13.8k / program 8.2k / case_study 2.9k / tax_measure 285 / law 252 / certification 66 / authority 20 / document 1), `am_entity_facts` (5.26M rows), `am_relation` (23,805 edges, 15 canonical relation types), `am_alias` (335,605 rows), `am_authority`, `am_region` (1,966 rows, all 5-digit codes), `am_tax_rule`, `am_subsidy_rule`, `am_application_round` (1,256 rows; 54 future / 17 within 60d), `am_loan_product`, `am_insurance_mutual`, `am_enforcement_detail` (22,258 rows; 6,455 with houjin_bangou; grant_refund 1,498 / subsidy_exclude 476 / fine 26 carry amount_yen), `am_amendment_snapshot` (14,596 rows — eligibility_hash never changes between v1/v2, time-series is fake), `am_amount_condition` (35,713 rows; 27,233 = adoption granted), `am_industry_jsic` (35 rows — JSIC major+partial medium only), `am_target_profile` (43 rows), `am_law_article` (28,048 rows), plus FTS5 (`am_entities_fts` trigram + `am_entities_fts_uni` unicode61) and sqlite-vec tables (`am_entities_vec` + 5 tiered vec indexes). 78 mirrored `jpi_*` tables (424,417 rows total). Cross-domain views: `entity_id_map` (6,339 jpi↔am mappings), `v_program_full` (13,578 jpi / 6,261 mapped = 46.1%), `v_houjin_360`, `v_readiness_input`. AUTONOMATH_ENABLED gate retained for legacy paths.
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

- **¥3/req metered only** (税込 ¥3.30). No tier SKUs, no seat fees, no annual minimums. Any code or UI that introduces "Free tier" / `tier-badge` / "Starter plan" / "Pro plan" is a regression. The only free path is the anonymous 50/month rate limit (IP-based, JST 月初 00:00 リセット).
- **100% organic acquisition.** No paid ads, no sales calls, no cold outreach. Zero-touch ops means no DPA/MSA negotiation, no Slack Connect, no phone support, no onboarding calls.
- **Solo ops.** No delegation, no CS team. Every feature must be fully self-service.
- **Data hygiene.** Every `programs` row must cite a primary source (government ministry, prefecture, 日本政策金融公庫, etc.). Aggregators like noukaweb, hojyokin-portal, biz.stayway are **banned** from `source_url` — past incidents created 詐欺 risk.
- **Trademark.** The name "jpintel" collides with Intel (著名商標衝突濃厚). Do **not** revive the jpintel brand in user-facing copy. The product is **AutonoMath**; the operator is **Bookyou株式会社**. This distinction matters — do not conflate.

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

- `ruff check src/ tests/ scripts/` passes
- `.venv/bin/pytest` passes (full suite, including integration)
- `mypy src/` passes (best effort — treat new errors as red)
- OpenAPI spec regenerated: `.venv/bin/python scripts/export_openapi.py > docs/openapi/v1.json`
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

## What NOT to do

- Never mock the database in integration tests — a past incident had mocked tests pass while a production migration failed.
- Never reintroduce tier-based pricing UI, feature gates labeled "Pro", or seat counters.
- Never silently refetch `source_url` and rewrite `source_fetched_at` without actually having performed the fetch — the column's semantics must stay honest.
- Never rename `src/jpintel_mcp/` to `src/autonomath_mcp/` — the PyPI package name is `autonomath-mcp`, but the import path is the legacy `jpintel_mcp` and changing it will break every consumer.
- Never commit `data/jpintel.db.bak.*` or `.wrangler/` or `.venv/` — if any slip through, add them to `.gitignore`.
- Never push with `--no-verify` or `--no-gpg-sign`. Fix the hook failure.
- Never revive the "jpintel" brand in user-facing surfaces (site copy, README headlines, marketing). Internal file paths are fine; user-visible strings are not.

## Key files

- `pyproject.toml` — distribution + console-script config (`autonomath-api`, `autonomath-mcp`)
- `server.json` — MCP registry manifest (version must match `pyproject.toml`)
- `src/jpintel_mcp/api/main.py` — FastAPI app + middleware wiring
- `src/jpintel_mcp/api/programs.py` — search logic + FTS tokenizer workaround
- `src/jpintel_mcp/mcp/server.py` — FastMCP entry point, 72 tools total at default gates:
  - **39 prod tools** backed by jpintel.db (programs + case_studies + loan_programs + enforcement + `get_usage_status` quota probe + 7 one-shot discovery tools [smb_starter_pack / subsidy_combo_finder / deadline_calendar / dd_profile_am / similar_cases / regulatory_prep_pack / subsidy_roadmap_3yr] + expansion: laws [9,484 rows, 継続ロード中] / tax_rulesets [35 rows] / court_decisions [0 rows, schema ready] / bids [0 rows, schema ready] / invoice_registrants [13,801 rows delta, full bulk pending] + cross-dataset glue)
  - **33 autonomath tools** backed by autonomath.db, registered at `server.py:4220` via `if settings.autonomath_enabled: from jpintel_mcp.mcp import autonomath_tools`. Package `src/jpintel_mcp/mcp/autonomath_tools/` exports: `search_tax_incentives`, `search_certifications`, `list_open_programs`, `enum_values_am`, `search_by_law`, `active_programs_at`, `related_programs`, `search_acceptance_stats_am`, `intent_of`, `reason_answer` (tools.py), `get_am_tax_rule` (tax_rule_tool.py), `search_gx_programs_am`, `search_loans_am`, `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am` (autonomath_wrappers.py), `list_tax_sunset_alerts`, V4 universal (`get_annotations`, `validate`, `get_provenance`, `get_provenance_for_fact`), Phase A (`list_static_resources_am`, `get_static_resource_am`, `list_example_profiles_am`, `get_example_profile_am`, `deep_health_am`), and additional tools (`graph_traverse`, `unified_lifecycle_calendar`, `program_lifecycle`, `program_abstract_structured`, `prerequisite_chain`, `rule_engine_check`, `query_at_snapshot`). `render_36_kyotei_am` + `get_36_kyotei_metadata_am` are gated behind `AUTONOMATH_36_KYOTEI_ENABLED` (default off — would push count to 74).
- `src/jpintel_mcp/api/autonomath.py` — REST router for 16 autonomath tools at `/v1/am/*`. **Intentionally NOT mounted in main.py** — deferred to post-launch per parallel-CLI merge plan. File on disk; activate via single-line `app.include_router(autonomath_router, dependencies=[AnonIpLimitDep])`.
- `src/jpintel_mcp/billing/` — Stripe metered billing
- `site/_templates/program.html` — per-program SEO page template
- `scripts/generate_program_pages.py` — static page generator
- `scripts/refresh_sources.py` — nightly URL liveness scan
- `scripts/export_openapi.py` — regenerates `docs/openapi/v1.json`
- `fly.toml` — Fly.io Tokyo deployment
- `mkdocs.yml` — docs site config
- `DIRECTORY.md` — detailed directory map (keep in sync when restructuring)
