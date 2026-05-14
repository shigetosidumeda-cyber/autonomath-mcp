# Directory Map (jpcite repo)

Post-launch canonical layout. Read this in 2 minutes before touching the tree.

## Brand state

- **User-facing brand**: **jpcite** (apex `jpcite.com`, API `api.jpcite.com`). Legacy brands `zeimu-kaikei.ai` and `autonomath.ai` still resolve via 301 redirect for SEO carry-over.
- **Operator entity**: **Bookyou株式会社** (適格請求書発行事業者番号 T8010001213708), 代表 梅田茂利, info@bookyou.net.
- **Product / package name**: **jpcite** is the user-facing product. `autonomath-mcp` package slug and `autonomath-api` / `autonomath-mcp` console script slugs are legacy technical names retained for compatibility. Fly app is `autonomath-api`.
- **Source import path**: **`src/jpintel_mcp/`** is the legacy package import path and is intentionally kept. Do **NOT** rename to `autonomath_mcp` — every consumer's `from jpintel_mcp...` import would break. The directory name is invisible to users; only the PyPI distribution name matters externally.
- The "jpintel" string must NOT appear in user-facing copy (Intel trademark collision). Internal file paths and import statements are fine.

## Top-level layout

| Dir / file | Purpose | Status / ownership |
|---|---|---|
| `src/jpintel_mcp/` | Live API + MCP + ingest + billing source | **live API code** |
| `tests/` | Unit + integration + e2e (181 `test_*.py`) | live |
| `scripts/` | Ops utilities, cron, ingest, migrations | live |
| `scripts/migrations/` | Numbered SQL migration files (001-119) | **immutable history — never edit applied migrations** |
| `scripts/cron/` | Recurring jobs (44 scripts) | live |
| `scripts/etl/` | One-off bulk ETL (translate, harvest, repromote) | live |
| `scripts/ingest/` | Ministry / corpus ingest scripts (~65 files) | live |
| `scripts/_archive/` | Executed one-shots kept for reference | archive |
| `data/` | Production-attached SQLite + JSON drops | live (do **not** commit DBs — `*.db` gitignored) |
| `docs/` | Customer-facing MkDocs source | live |
| `docs/_internal/` | Operator-only runbooks + plans | operator-only |
| `site/` | Cloudflare Pages static site (HTML + SSG output) | live |
| `sdk/` | Python + TypeScript SDKs + plugins (freee / MF / kintone / slack / email / excel / google-sheets) | live |
| `dist/` | Build artifacts: wheels, sdist, mcpb; canonical release manifests/static distribution surfaces are v0.4.0 | build-output |
| `dxt/` | DXT bundle assets (`manifest.json`, icon) | live |
| `overrides/` | MkDocs theme partials | live |
| `monitoring/` | Sentry rules + SLA targets + uptime metrics + SEO metrics | live |
| `analytics/` | JSONL baselines (geo, confidence, npm) | live |
| `badges/` | README SVG status badges | live |
| `examples/` | SDK integration sample code (Python + TypeScript) | live |
| `evals/` | Eval harness gold sets (`gold.yaml`) | live |
| `loadtest/` | k6 scenarios (`programs_search.js`, `webhook_stripe.js`) | live |
| `benchmarks/` | RAG benchmark inputs (`japanese_subsidy_rag/`) | live |
| `content/` | Pre-launch press / Zenn drafts | live (low-traffic) |
| `research/` | Strategy + design docs + outreach + research loops | research-only |
| `research/loops/runs/20260430/` | **OTHER CLI's running research loop output** | **DO NOT TOUCH during loop runs** |
| `tools/offline/` | Operator-only utilities (LLM imports allowed here) | **operator-only, isolated from production tree** |
| `analysis_wave18/` | OTHER CLI research output drop (audits, KPI snapshots) | **DO NOT TOUCH** |
| `analysis_value/` | Internal value-canon strategy notes | research-only |
| `autonomath_staging/` | **Pre-launch staging snapshot, gitignored** | archive (filesystem-only, not in git) |
| `.github/` | CI/CD workflows (~50 YAMLs) | live |

## Hygiene Rules

The layout above is the source-of-truth map. The working tree also contains
local runtime data, generated artifacts, and operator research output. Treat
these as different lanes before reviewing or deploying.

| Lane | Examples | Rule |
|---|---|---|
| Runtime source | `src/`, production-safe `scripts/`, `entrypoint.sh`, `Dockerfile` | Review with tests and deploy impact |
| Migrations | `scripts/migrations/` | Immutable once applied; add new migration instead of editing old ones |
| Public source | `docs/`, hand-authored `site/*.html`, `README.md` | Review as user-facing copy/docs |
| Generated public artifacts | `docs/openapi/*.json`, `site/openapi*.json`, `site/docs/`, generated SEO/sitemap/llms-full | Regenerate from source; do not hand-edit |
| Runtime/local data | root `*.db`, `*.sqlite`, WAL/SHM files | Local or volume data, not source |
| Operator research | `tools/offline/_inbox/`, `analysis_wave18/`, `docs/_internal/` drafts | Promote only distilled, reviewed outputs |
| Build/archive output | `dist/`, `dist.bak*/`, package tarballs | Keep out of normal review unless publishing |

Generated artifact details live in
`docs/_internal/generated_artifacts_map_2026-05-06.md`. A machine-generated
repo inventory and dirty-tree lane report can be written with:

```bash
uv run python scripts/ops/repo_hygiene_inventory.py
uv run python scripts/ops/repo_dirty_lane_report.py
uv run python scripts/ops/repo_value_asset_report.py
uv run python scripts/ops/mcp_manifest_deep_diff.py
uv run python scripts/ops/migration_inventory.py
```

Before production deploy, inspect the dirty tree by lane. Do not mix runtime
code, generated site/OpenAPI output, SDK packaging, operator research, and
DB/migration changes in one review unless that is the explicit release bundle.

## Top-level files

| File | Purpose |
|---|---|
| `README.md` | Public project README |
| `CLAUDE.md` | Agent guidance (architecture, gotchas, what-not-to-do) |
| `CHANGELOG.md` | Release notes |
| `DIRECTORY.md` | **This file** |
| `JPCITE_SETUP.md` | jpcite domain rebrand setup notes |
| `LAUNCH_CONVERGENCE_2026-05-06.md` | Launch convergence doc |
| `HANDOFF_2026-04-25.md` | V4 + Phase A absorption handoff |
| `AUTONOMATH_DB_MANIFEST.md` | Unified `autonomath.db` table inventory |
| `pyproject.toml` | Python project (PyPI `autonomath-mcp`, console scripts) |
| `server.json` | MCP registry manifest (version must match `pyproject.toml`) |
| `mcp-server.json` | MCP catalog submission manifest |
| `mkdocs.yml` | Docs site config |
| `smithery.yaml` | Smithery registry submission |
| `fly.toml` | Fly.io Tokyo deploy (app `autonomath-api`) |
| `Dockerfile` + `entrypoint.sh` | Production image + boot-time `autonomath.db` self-heal migrations |
| `cloudflare-rules.yaml` | Cloudflare Pages headers/rules source |
| `uv.lock` | Python deps lock |
| `.env.example` | Env-var template |
| `.pre-commit-config.yaml` / `.gitleaks.toml` / `.bandit.yaml` / `.yamllint.yaml` | Static checks |

## `src/jpintel_mcp/` substructure

```
src/jpintel_mcp/
  api/           FastAPI REST app, mounted at /v1/*
  mcp/           FastMCP stdio server (runtime-derived tool count; do not hard-code stale counts)
    autonomath_tools/    50 autonomath-gated tools (composition, NTA, Wave 21-23)
    healthcare_tools/    healthcare gate (off by default)
    real_estate_tools/   real-estate gate (off by default)
  services/      Cross-feature business logic (citation_verifier, cross_source, evidence_packet, funding_stack_checker, token_compression)
  ingest/        Canonical ingest (tier scoring) — distinct from scripts/ingest/
  db/            SQLite session + base schema
  billing/       Stripe metered billing (keys, stripe_usage, stripe_edge_cases)
  email/         Postmark transactional + onboarding + scheduler + unsubscribe + compliance_templates
  models/        Pydantic models (consolidated 2026-04-25 with premium_response.py)
  cache/         L4 cache helpers
  security/      pii_redact, headers, rate-limit
  observability/ Sentry, telemetry, metrics
  i18n/          Translation helpers
  ingest/        (canonical tier scorer)
  line/          LINE Bot endpoints
  loops/         Self-improve loop substrate (operator-only triggers)
  self_improve/  Self-improvement orchestrator + scoring
  templates/     Jinja templates for rendered surfaces
  utils/         Shared utilities (wareki, jp_money, jp_constants, etc.)
  analytics/     usage event sinks
  config.py      Pydantic settings (single source of truth for env vars)
  _archive/      Pre-launch dead branches kept for reference
```

Console-script entry points (declared in `pyproject.toml`):

- `autonomath-api` → `jpintel_mcp.api.main:run`
- `autonomath-mcp` → `jpintel_mcp.mcp.server:run`

## `scripts/` substructure

```
scripts/
  migrations/        SQL migrations 001-119 (gaps at 004/006/025-036/040/084/093-095/100 = numbering reservations)
                     IMMUTABLE — once applied, never edit; add a new file instead
  cron/              44 scripts: backups, digests, NTA bulk, law full-text, RSS, billing, webhooks, alerts, KPIs
  etl/               Bulk one-off transforms: batch_translate_corpus.py (in tools/offline/), harvest_implicit_relations.py, repromote_amount_conditions.py
  ingest/            Ministry / corpus ingest (~65 files: enforcement_*, court_decisions_*, bids_*, etc.)
  audits/            Spot-audit markdown drops
  lib/               Shared script helpers
  registry_submissions/  Per-registry submission JSONs
  seeds/             (empty stub)
  sync/              External sync helpers (gbiz, kintone)
  _archive/          Executed one-shot scripts (fix_uni_*, fix_url_*, apply_prefecture_*)
  + ~80 top-level *.py utilities (generate_*, refresh_*, ingest_*, bench_*, publish_*)
```

## `site/` substructure (Cloudflare Pages)

```
site/
  index.html, pricing.html, dashboard.html, tos.html, privacy.html, tokushoho.html, ...   landing + legal
  _templates/        SSG Jinja templates: program.html, prefecture.html, industry_program.html, qa.html, news_post.html, cross.html, prefecture_index.html
  audiences/         9 segment landing pages: smb, dev, vc, tax-advisor, subsidy-consultant, admin-scrivener, construction, manufacturing, real_estate
  compare/           Compare-vs-X pages (11 competitors)
  cross/             47 prefecture cross-link hubs (one dir per pref)
  en/                English mirror (32 pages)
  industries/        JSIC industry hubs (A, B, C, D, E, E-sme, F, G, H, I)
  prefectures/       47 prefecture index pages
  programs/          1,418 per-program SEO pages (generated)
  structured/        1,415 JSON-LD per-program structured-data files
  qa/                Q&A hubs
  news/              News index
  blog/              Blog posts (markdown + rendered)
  press/             Press kit (about, contact, fact-sheet, founders)
  integrations/      Per-client setup pages (claude-desktop, cursor, gemini, chatgpt, ...)
  widget/            Embed widget assets
  status/            Status page
  admin/             Operator-only admin pages
  dashboard/         Customer dashboard (split files dashboard.js / dashboard_v2.js)
  downloads/         Public download artifacts
  security/          security.txt + security policy
  static/            Static helpers
  assets/            CSS, JS, fonts, OG images, prompts, BRAND.md
  _data/             SSG input data (curl_examples.json)
  docs/              MkDocs build output (gitignored)
  _redirects, _headers, llms.txt, llms-full.txt, robots.txt, sitemap*.xml   Cloudflare + LLM crawl manifests
```

## `docs/` (MkDocs source)

```
docs/
  index.md, getting-started.md, api-reference.md, mcp-tools.md, faq.md, pricing.md, ...   public docs
  api-reference/          response_envelope.md (per-endpoint)
  blog/                   Launch-week posts
  runbook/                (currently empty — operator runbooks live in _internal/)
  openapi/                v1.json (regenerate via scripts/export_openapi.py)
  sdks/                   SDK docs
  launch/, launch_assets/ Launch-day collateral
  partnerships/           Partner-facing docs
  compliance/             Compliance summaries
  canonical/              Canonical reference docs
  integrations/           Integration recipes
  ux/                     UX walks
  stylesheets/            MkDocs theming
  assets/                 Public images
  _internal/              **OPERATOR ONLY** — runbooks, deploy logs, incident SOPs, customer-dev notes, succession docs (~80 files)
    _archive/             value_maximization_plan_no_llm_api.md (single file)
    archive/launch_2026-04-23/   pre-launch decision docs
    mcp_registry_submissions/    Per-registry submission docs
    templates/                   Operator email/document templates
```

## `tests/`

```
tests/
  test_*.py            Top-level unit + integration (181 test files)
  api/                 API-suite-specific tests
  mcp/                 MCP server tests
  e2e/                 Playwright e2e (slow — needs `pytest tests/e2e` + Chromium)
  smoke/               Boot/health smoke
  bench/               Bench harness tests
  eval/                Eval scaffolding
  format_consistency/  Cross-tool envelope contract enforcement
  models/              Pydantic model tests
  sdk/                 SDK parity (Python ↔ TypeScript)
  templates/           Site template render tests
  utils/               Shared test helpers
```

Slow / flaky suites: `tests/e2e/` (Playwright, needs `[e2e]` extras + Chromium), `tests/bench/` (DB-warm timing).

## `research/`

```
research/
  data_expansion_design.md     ~407 KB canonical design doc
  competitive_landscape.md, content_calendar.md, data_quality_report.md, jgrants_ingest_plan.md,
  launch_content.md, legal_disclaimer.md, mcp_rest_parity.md, observability.md, ...   strategy + research notes
  blog_drafts/                 unpublished drafts
  outreach/                    templates_2026-04-30.md (only file)
  loops/                       OTHER CLI's research loop driver
    research_collection_loop.py
    RUN_LOG.md
    runs/20260430/             ACTIVE — written by OTHER CLI, do not touch
  observability_stubs/         pre-launch UX experiment stubs (dormant)
  a11y_before_after/           dormant 2026-04-23 a11y screenshot drop
  _archive/pre_launch_decisions/   archived launch-prep decisions
  non_agri_*.json / .md        non-agri ingest exclusion mapping artifacts
```

## `tools/offline/`

Operator-only tools. **This directory is permitted to import LLM SDKs (`anthropic`, `openai`, etc.).** It is excluded from `tests/test_no_llm_in_production.py`. Production code under `src/`, `scripts/cron/`, `scripts/etl/`, `tests/` must NOT import LLM SDKs (CI guard).

```
tools/offline/
  INFO_COLLECTOR_*.md          repeatable external information-collection prompts
  run_*_batch.py               local batch precompute / ingest runners
  ingest_* / extract_*         offline ETL helpers
  _runner_common.py            shared offline runner helpers
  _inbox/ _outbox/ _done/      ignored raw run outputs and handoff artifacts
  README.md                    rules of the road
```

## `analysis_wave18/`

OTHER CLI's research output drop. ~200 markdown audits + benchmarks + scoring artifacts (Wave 18 — Wave 30 series). Recently active: `customer_demand_audit_2026-04-30.md`, `distribution_drift_2026-04-30.md`, `kpi_state_2026-04-30.md`, etc. **Do not touch during loop runs.**

## `data/` (DB + bulk artifacts)

| File | Purpose | Notes |
|---|---|---|
| `data/jpintel.db` | jpintel hot path (~360 MB) | live; FTS5 trigram + unicode61 |
| `autonomath.db` (**at repo root, NOT under data/**) | Unified primary DB (~9.4 GB) | live; production code reads from this path; **`data/autonomath.db` is a 0-byte placeholder** |
| `data/autonomath.db` | 0-byte placeholder | DO NOT use as the live DB — read from repo-root path |
| `jpintel.db` (at repo root) | small staging copy (~20 KB) | CI / local-dev shadow |
| `autonomath_invoice_mirror.db` (at root) | NTA invoice corpus mirror (~42 MB) | live |
| `graph.sqlite` (at root) | Graph cache (~18 MB) | live |
| `autonomath.db.bak.*`, `autonomath.db.pre_*` | Backup snapshots (multi-GB each) | gitignored; rotate manually |
| `data/snapshots/` | OTHER CLI shard outputs (am_diff_20260430_shard*.json) | **DO NOT TOUCH** |
| `data/structured_facts/research_20260430/` | OTHER CLI structured-fact outputs | **DO NOT TOUCH** |
| `data/autonomath/`, `data/autonomath_static/` | Static taxonomies + example profiles seeded into MCP | live |
| `data/ingest_logs/`, `data/ingest_*.log` | Ingest run logs | rotate-only |
| `data/duplicate_review_*.jsonl` | Duplicate-review queue + decisions | live |
| `data/hallucination_guard.yaml` | Hallucination guard ruleset | live |
| `data/sample_saved_searches.json` | Wave 23 saved-search seeds | live |

`*.db` is gitignored via wildcard — confirmed via `git check-ignore` for `autonomath.db`, `data/autonomath.db`, `data/jpintel.db`, `jpintel.db`. Production code reads `autonomath.db` from the **repo-root path**, attached to a Fly volume in production. The repo-root location is intentional.

## Production infrastructure entry points

| Surface | URL / target |
|---|---|
| Production API | `https://api.jpcite.com` (also `api.autonomath.ai` redirect, `api.zeimu-kaikei.ai` legacy) |
| Marketing site | `https://jpcite.com` (Cloudflare Pages) |
| Fly.io app | `autonomath-api` (region nrt) |
| Fly SSH | `flyctl ssh console -a autonomath-api` |
| Fly logs | `flyctl logs -a autonomath-api` |
| Deploy | `flyctl deploy -a autonomath-api --remote-only` |
| MCP stdio (local) | `.venv/bin/autonomath-mcp` |
| MCP registry | `mcp publish server.json` (see `scripts/mcp_registries.md`) |
| PyPI | package `autonomath-mcp` |

## Drift fixed in this revision

DIRECTORY.md prior version referenced legacy state. This revision:

- Renamed brand context to **jpcite** (apex / website / API). Legacy references to `autonomath.ai` URLs preserved only where they remain live (Fly app name, redirect targets).
- Added `research/loops/`, `research/outreach/` (new since prior version).
- Added `analysis_wave18/`, `tools/offline/`, `monitoring/`, `analytics/`, `badges/` to top-level table.
- Added `dxt/`, `dist/`, `benchmarks/`, `content/`, `evals/`, `examples/`, `loadtest/`, `analysis_value/`, `autonomath_staging/`.
- Documented `scripts/cron/` (44 scripts), `scripts/etl/`, `scripts/ingest/` (~65 files), `scripts/_archive/`, `scripts/audits/`, `scripts/lib/`, `scripts/registry_submissions/`.
- Documented `src/jpintel_mcp/` 18+ subdirs (was 5 in prior version).
- Documented full `site/` SSG layout including `audiences/`, `cross/`, `en/`, `industries/`, `prefectures/`, `programs/` (1,418 pages), `structured/` (1,415 JSON-LD), `_templates/`, `_data/`, etc.
- Documented `docs/_internal/_archive/` and `docs/_internal/archive/launch_2026-04-23/` (separate paths).
- Clarified the `data/autonomath.db` 0-byte placeholder vs `autonomath.db` at repo root (production hot path) — was a footgun in the prior version.
- Removed reference to `data_expansion_design.md` "9,775 行" — the file is now ~407 KB but exact line count not re-verified; left as approximate.

**Drift count**: ~14 dirs added, ~6 paths re-described (db locations, brand strings, sdk subdirs, scripts/cron expansion), 0 dirs claimed-but-missing.

## Dead path candidates (REPORT — do NOT delete)

Dirs with no `from <dir>...` import / no `<dir>/` reference in `src/`, `scripts/`, `tests/`, `docs/` (excluding doc-only mentions in `CLAUDE.md`, manifests, README).

| Path | Last touched | Inbound refs | Recommendation |
|---|---|---:|---|
| `autonomath_staging/` | 2026-04-25 | 2 (doc-only: 1 comment in `scripts/migrations/052_perf_indexes.sql`, 1 in `tests/sdk/test_python_parity.py` doctring) | gitignored; safe to leave on disk; consider moving to `~/Archive/` if reclaiming the ~MBs |
| `analysis_value/` | 2026-04-25 | 1 (doc-only: `scripts/distribution_manifest.yml` comment) | move to `_archive/` if no longer used in strategy review |
| `research/observability_stubs/` | 2026-04-22 | 0 | move to `research/_archive/` |
| `research/a11y_before_after/` | 2026-04-23 | 0 | move to `research/_archive/` (one-shot screenshot bundle) |
| `research/_archive/pre_launch_decisions/` | 2026-04-23 | 0 | already archive — leave |
| `scripts/seeds/` | 2026-04-24 | 0 | empty stub; remove or document if reserved |
| `scripts/_archive/` | 2026-04-29 | (intentional archive) | leave |
| `docs/_internal/archive/launch_2026-04-23/` | 2026-04-23 | (intentional archive) | leave |
| `docs/_internal/_archive/` | 2026-04-30 | (intentional archive) | leave |
| `benchmarks/` | 2026-04-26 | 0 | review usage; if benchmark harness moved to `tools/offline/`, archive contents |
| `content/` | 2026-04-24 | 15 (mostly self-referential markdown) | live press/Zenn drafts — keep |
| `loadtest/` | 2026-04-25 | 1 (`docs` reference) | live k6 scenarios — keep |

**Dead path candidate count**: 4 strict candidates (no inbound refs, mtime stable): `research/observability_stubs/`, `research/a11y_before_after/`, `scripts/seeds/`, `benchmarks/`. 2 doc-only-referenced candidates (`autonomath_staging/`, `analysis_value/`). Caveat: with launch on 2026-05-06, the entire repo is "young" — nothing breaks the 90-day mtime threshold yet. Re-run this audit in ~2 months for a real pruning pass.

## Key startup reads (for new agent sessions)

1. `CLAUDE.md` — full architecture, gotchas, what-not-to-do (~7 min read)
2. This file — directory navigation (~2 min)
3. `research/data_expansion_design.md` — canonical design (skim TL;DR + Anti-patterns, ~5 min)
4. `pyproject.toml` + `server.json` — current version, console scripts, manifest (~30 sec)
