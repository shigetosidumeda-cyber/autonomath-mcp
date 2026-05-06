# Repo Cleanup Loop Report

- date: `2026-05-06`
- scope: non-destructive repository organization
- rule: no deletes, no moves, no reverting user work
- outputs:
  - `docs/_internal/repo_hygiene_inventory_latest.md`
  - `docs/_internal/repo_dirty_lanes_latest.md`
  - `docs/_internal/repo_value_assets_latest.md`
  - `docs/_internal/mcp_manifest_deep_diff_latest.md`
  - `docs/_internal/migration_inventory_latest.md`
  - `docs/_internal/value_productization_queue_2026-05-06.md`
  - `docs/_internal/repo_organization_assessment_2026-05-06.md`
  - `docs/_internal/generated_artifacts_map_2026-05-06.md`
  - `scripts/MANIFEST.md`
  - `site/README.md`

## Verdict

The repository now has a clear organization contract, but the remaining dirty
tree should be treated as release review material, not trash. The biggest
cleanup win is lane separation:

1. Ignore local runtime data and raw operator output.
2. Keep source, migrations, tests, workflows, SDK distribution, and generated
   public artifacts visible.
3. Review those visible changes by lane before deployment.

## What Changed

- Added repository hygiene ignore rules for local SQLite files, virtualenvs,
  backup builds, temporary directories, operator inbox/outbox output, WARC-like
  captures, binary PDF captures, and generated audience subdirectories.
- Tightened `.dockerignore` so production images do not accidentally include
  root databases, local data dumps, research artifacts, offline runs, SDK
  workspaces, benchmarks, analytics, monitoring drafts, or build backups.
- Added a top-level organization assessment and generated artifact map under
  `docs/_internal/`.
- Added `scripts/MANIFEST.md` to make script placement explicit.
- Added `site/README.md` to distinguish hand-authored public files from
  generated or mirrored site artifacts.
- Updated `tools/offline/README.md` to reflect its current role as the
  operator-only prompt, batch, ingest, and raw run boundary.
- Added `scripts/ops/repo_hygiene_inventory.py` for top-level size and lane
  inventory.
- Added `scripts/ops/repo_dirty_lane_report.py` for dirty-tree review lanes.
- Added `scripts/ops/repo_value_asset_report.py` for productizable asset
  discovery.
- Added `scripts/ops/mcp_manifest_deep_diff.py` for DXT vs registry MCP
  description drift.
- Added `scripts/ops/migration_inventory.py` for SQL migration family,
  rollback, target DB, and danger-marker inventory.
- Added boundary README files for `docs/_internal/`, `benchmarks/`,
  `monitoring/`, `.github/workflows/`, and `scripts/migrations/`.

## Current Inventory

Latest `repo_hygiene_inventory` result:

- modified entries: `218`
- deleted entries: `1`
- untracked entries: `458`
- largest local item: `autonomath.db` at `11.5GB`
- largest mixed review roots: `tools`, `sdk`, `site`, `docs`, `scripts`,
  `tests`

Latest `repo_dirty_lane_report` result:

| lane | entries | action |
|---|---:|---|
| runtime_code | 81 | review with API/MCP tests |
| billing_auth_security | 10 | review first before deployment |
| migrations | 129 | verify numbering and rollback pairing |
| cron_etl_ops | 51 | require dry-run and DB/write target clarity |
| tests | 111 | bind to feature lanes and CI gates |
| workflows | 14 | review permissions, concurrency, production writes |
| generated_public_site | 64 | regenerate and compare with source |
| openapi_distribution | 6 | keep OpenAPI mirrors in sync |
| sdk_distribution | 55 | verify package/version/manifest parity |
| public_docs | 70 | human copy review |
| internal_docs | 63 | keep operator-only and out of public site |
| operator_offline | 29 | commit prompts/runners, ignore raw outputs |
| benchmarks_monitoring | 28 | keep configs and compact summaries |
| data_or_local_seed | 1 | avoid DB/raw data commits |
| root_release_files | 10 | review as release metadata |
| misc_review | 25 | classify before merge |

Latest `repo_value_asset_report` result:

- value asset entries: `911`
- `ai_first_hop_distribution`: `253`
- `customer_output_surfaces`: `40`
- `data_foundation`: `368`
- `trust_quality_proof`: `56`
- `operator_research_to_product`: `25`
- `public_conversion_copy`: `161`
- `internal_sensitive_only`: `8`

Latest `mcp_manifest_deep_diff` result:

- DXT tools: `139`
- registry tools: `139`
- hard drift: `false`
- description mismatches: `52`
- DXT resources: `28`
- registry resources: `0`

Latest `migration_inventory` result:

- migration files: `239`
- forward files: `174`
- rollback files: `64`
- rollback pairs: `64`
- orphan rollbacks: `0`
- forward missing rollback: `110`
- duplicate forward numeric prefixes: `4`
- target DB unmarked files: `50`
- files with dangerous SQL markers: `69`

## Agent Audit Synthesis

### Docs And Site

- `docs/_internal/SECRETS_REGISTRY.md` must never be treated as public
  content without inspection.
- OpenAPI JSON, public counts, sitemap, benchmark results, MCP manifests, and
  `.mcpb` files are generated or distribution artifacts. They should land with
  generator commands and version rationale.
- `site/` mixes hand-authored HTML and generated output. Use `site/README.md`
  as the boundary.
- `docs/runbook/` needs a public-vs-operator decision. When unsure, keep
  sensitive runbooks in `docs/_internal/`.
- `docs/_internal/README.md` now fixes the operator-only boundary. Public
  promotion should happen by creating a new redacted public doc, not by exposing
  internal files directly.

### Scripts And Migrations

- `scripts/migrations/` contains two numbering styles: numeric `146-176` and
  `wave24_*`. The next cleanup should establish an applied-order manifest
  before any production migration batch.
- `scripts/migrations/README.md` and `migration_inventory_latest.md` now make
  the non-destructive review model explicit: lexical runner order, target DB,
  rollback pairs, manual/draft files, duplicate forward prefixes, and dangerous
  SQL markers.
- Cron jobs and ETL scripts are mostly in the right directories, but DB-write
  and external-send jobs need docstrings with dry-run behavior, target DB,
  network side effects, and safe rerun status.
- Dangerous operators include Cloudflare mutation, existing-user notification,
  Merkle anchoring, bulk calendar/recommendation rebuilds, and rollback SQL.

### Runtime And Tests

- The biggest review risk is `src/jpintel_mcp/api/main.py`, because many
  routers and public/paywalled boundaries change together.
- Billing, credit pack, Turnstile/APPI, audit seal rotation, idempotency,
  cost-cap, and origin enforcement should be reviewed before normal runtime
  value features.
- Tests are extensive but should be grouped by lane: billing/security,
  runtime routes, MCP registration, output envelope, production smoke, and
  slow DB-dependent checks.
- Strongest product surfaces: `artifacts`, `intel_*` composite endpoints,
  evidence batch, funding stack, eligibility predicates, company DD, citation
  pack, regulatory context, and practitioner-ready packs. These turn jpcite
  from search into deliverables a BPO, tax advisor, M&A team, finance team, or
  AI developer can reuse.
- `application_strategy_pack` is now explicitly marked in the agent OpenAPI
  subset as a priority first-hop for public support strategy. The guidance
  tells AI clients when to call it, what fields to preserve, and which claims
  not to make.
- Treat Wave32-like REST/MCP files as value candidates, not public facts, until
  router registration, MCP import/registration, OpenAPI export, SDK types,
  manifest sync, billing behavior, and legal disclaimers are verified.
- For paid/batch endpoints, `Idempotency-Key`, `X-Cost-Cap-JPY`, usage events,
  and Stripe meter behavior must be part of the release gate.

### SDK And Distribution

- Distribution manifest drift check currently passes.
- OpenAPI mirrors and MCP manifest mirrors are synchronized, but version
  numbers across repo, SDKs, DXT, and package artifacts need explicit release
  rationale.
- The MCP/DXT/SDK distribution layer is a major value asset. `mcp-server*.json`,
  `server.json`, `smithery.yaml`, `dxt/manifest.json`, `.mcpb`, `sdk/agents`,
  and partner SDKs can make jpcite the first hop for AI agents.
- Manifest file equality is not enough. DXT and full MCP tool names match, but
  tool descriptions and counts can drift. Add a future guard that compares
  descriptions, counts, pricing language, and version language.
- `mcp_manifest_deep_diff_latest.md` confirms no hard tool-name drift, but 52
  tool descriptions differ. This is a value issue, not just hygiene: agent
  routing depends on those descriptions.
- `sdk/typescript/autonomath-sdk-0.2.0.tgz` is deleted in the dirty tree. It
  looks like an old package artifact, but do not remove it without publish or
  rollback intent review.
- New browser and VS Code extension directories should be treated as new
  distribution surfaces, not noise.
- Normalize SDK naming before publishing more examples. The repo currently has
  multiple package-name surfaces; agent snippets must install the same package
  name that is actually published.

### Data, Offline, Benchmarks, Monitoring

- `tools/offline/_inbox/` is raw execution output and should stay ignored.
- Commit repeatable prompts, runners, configs, and compact benchmark summaries.
  Ignore raw captures, large logs, local DBs, generated JSONL, and cache
  directories.
- `monitoring/*.yaml` and `monitoring/*.json` are config-like and should be
  versioned when they define production or launch gates.
- `benchmarks/README.md` and `monitoring/README.md` now separate public proof,
  internal regression, SLO design, and not-yet-applied monitoring artifacts.
- Strongest value discovery: `company_public_baseline` should become the
  first-hop company evidence layer. From a corporation number or company name,
  it can combine identity, invoice status, programs, adoption history, public
  risk signals, known gaps, and next questions into one reusable brief.
- Strongest proof asset: `tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl`
  defines what real BPO, tax, accounting, administrative-scrivener, M&A,
  finance, AI developer, municipality, and FDI users should receive. Treat it
  as product acceptance criteria, not just tests.
- Strongest benchmark assets: `benchmarks/jcrb_v1/`, `benchmarks/composite_vs_naive/`,
  and `benchmarks/sims/zeirishi_1month_report.md`. Use them conservatively as
  proof of citation workflow and verification-time reduction, not unsupported
  broad claims.
- Data foundation with immediate customer value: `programs` / `jpi_programs`,
  `am_amount_condition`, `am_law_article`, `adoption_records` /
  `jpi_adoption_records`, `houjin_master`, `nta_tsutatsu_index`, `nta_saiketsu`,
  `am_recommended_programs`, `am_amendment_diff`, `court_decisions`,
  `case_studies`, and `enforcement_cases`.
- Do not use empty or thin derived tables as public proof yet:
  `am_program_calendar_12mo`, `am_actionable_answer_cache`,
  `am_program_eligibility_predicate`, `source_document`, `extracted_fact`,
  `corpus_snapshot`, `audit_merkle_anchor`, and `cron_runs` were reported as
  empty or not yet suitable as public evidence.
- Productization priority is now captured in
  `docs/_internal/value_productization_queue_2026-05-06.md`: start with
  `application_strategy_pack`, then `company_public_baseline` /
  `houjin_dd_pack`, then `company_public_audit_pack`, then agent-first
  distribution, then public proof pages.

### Root, Docker, CI

- `.dockerignore` now blocks the major context hazards: local DBs, data dumps,
  virtualenvs, offline runs, SDK workspaces, site build output, and research
  artifacts.
- `Dockerfile` still copies `scripts/`, so experiments should not be placed in
  deployable script directories.
- `workflow_dispatch` deploy can bypass normal CI-success sequencing. Manual
  deploy should be reserved for already-tested SHAs.
- Production-write workflows should have least privilege, concurrency, and
  secret-missing behavior reviewed one by one.
- `.github/workflows/README.md` now fixes workflow review lanes, especially
  `prod-db-write`, `repo-write`, `deploy-publish`, and backup behavior.

## Operating Rule From Here

Use these commands before release review:

```bash
uv run python scripts/ops/repo_hygiene_inventory.py
uv run python scripts/ops/repo_dirty_lane_report.py
uv run python scripts/ops/repo_value_asset_report.py
uv run python scripts/ops/mcp_manifest_deep_diff.py
uv run python scripts/ops/migration_inventory.py
uv run ruff check scripts/ops/repo_hygiene_inventory.py scripts/ops/repo_dirty_lane_report.py scripts/ops/repo_value_asset_report.py scripts/ops/mcp_manifest_deep_diff.py scripts/ops/migration_inventory.py tests/test_repo_hygiene_inventory.py tests/test_repo_dirty_lane_report.py tests/test_repo_value_asset_report.py tests/test_mcp_manifest_deep_diff.py tests/test_migration_inventory.py
uv run pytest tests/test_repo_hygiene_inventory.py tests/test_repo_dirty_lane_report.py tests/test_repo_value_asset_report.py tests/test_mcp_manifest_deep_diff.py tests/test_migration_inventory.py -q
```

Recommended review order:

1. `billing_auth_security`
2. `runtime_code`
3. `migrations`
4. `workflows`
5. `cron_etl_ops`
6. `tests`
7. `openapi_distribution`
8. `sdk_distribution`
9. `generated_public_site`
10. `public_docs`
11. `internal_docs`
12. `operator_offline`

The repo is cleaner now because the remaining work is named. The next
improvement loop should not delete files; it should turn each lane into a
separate reviewed release bundle.

## Follow-up Implementation Applied

- Added agent-safe OpenAPI guidance for `application_strategy_pack`,
  `programs.prescreen`, and `programs/{program_id}/eligibility_predicate`.
  Static agent specs were regenerated.
- Added migration inventory preflight fail flags while keeping the default
  report-only workflow non-destructive.
- Closed two billing/security P0s from review: strict metering for evidence
  batch, and production Turnstile boot gate for APPI intake.
- Strengthened public audit-seal verification by binding `seal_id` and
  `corpus_snapshot_id` into the HMAC.
- Strengthened JCRB public proof posture by separating unvalidated seed examples
  from verified leaderboard rows and validating submission shape before publish.
