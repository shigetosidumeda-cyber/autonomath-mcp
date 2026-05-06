# Repo Hygiene Triage 2026-05-06

Generated: 2026-05-06 JST

Scope: non-destructive repository triage, debug prioritization, and handoff control. This file intentionally does not move, delete, revert, or normalize any existing worktree changes.

## 1. Current verdict

The repository is dirty, but the dirt is mostly explainable as parallel implementation lanes plus generated distribution artifacts. The correct first action is not bulk cleanup. The correct first action is to freeze ownership boundaries, keep production-side effects off, and land only small, verified fixes by lane.

Current local snapshot:

| metric | count |
| --- | ---: |
| `git status --short` entries | 757 |
| modified tracked files | 244 |
| deleted tracked files | 1 |
| untracked non-ignored files | 512 |
| modified tracked file paths from `git diff --name-only` | 244 |

Top dirty directories:

| area | entries | reading |
| --- | ---: | --- |
| `scripts/` | 225 | migrations, cron, manifest, ETL, distribution tooling |
| `docs/` | 147 | launch docs, SOT docs, market/value research |
| `tests/` | 125 | feature and safety tests from multiple lanes |
| `src/` | 91 | API, billing, MCP, citation, artifact implementation |
| `site/` | 67 | generated/static publish surfaces |
| `tools/` | 29 | offline inbox and CLI research handoff |
| `sdk/` | 24 | SDK package and release surfaces |
| `.github/` | 18 | workflow/deploy/release automation |

## 2. Hard rule for cleanup

Until each lane owner is explicit, do not run:

- `git reset --hard`
- `git checkout -- ...`
- `git clean -fd`
- bulk deletion of `site/`, `docs/`, `sdk/`, `tools/offline/_inbox/`, databases, or generated manifests
- production commands such as `fly deploy`, `fly secrets set`, live ingestion without `--dry-run`, or migration apply against production

Safe cleanup is limited to documentation, classification, static validation, and narrow patches that are tied to one lane and verified.

## 3. Active lanes

| lane | status | owner boundary | immediate action |
| --- | --- | --- | --- |
| M00 implementation | Codex local green for M00-D P0 and company public artifact audit-seal contract | `_m00_implementation/*`, billing safety, distribution parity, company folder, proof/evidence/audit surfaces | avoid broad edits; deploy still gated by deploy packet |
| M01 gBiz | local contract tests improved, live use still blocked | gBiz cron scripts, gBiz migrations, monthly workflow, gBiz docs | no secret/deploy/live ingest until app/secret/target_db boundaries are fixed |
| distribution/generated | static/runtime/tool-count checks pass at 139 tools | OpenAPI JSON, MCP manifests, `site/*.json`, generated docs surfaces | freeze regeneration; DA-01 140-tool packet is separate |
| tests/safety | mixed ownership | rate limit, Stripe webhook, customer cap, distribution parity, gBiz dry-run | run targeted safe tests only |
| docs/SOT | drift present | `DIRECTORY.md`, `docs/_internal/INDEX*.md`, `CLAUDE.md`, `SYNTHESIS_2026_05_06.md` | create reconciliation index before editing older docs |
| SDK/release | release-sensitive | `sdk/*`, package locks, VSIX/tarball outputs | verify release scripts before deleting any artifacts |
| offline inbox | research asset | `tools/offline/_inbox/*` | preserve; summarize only |

## 4. Source-of-truth drift

There is no single clean SOT right now. The following claims conflict:

| topic | conflicting surfaces |
| --- | --- |
| product/tool count | docs index references older counts; directory/index/synthesis mention different versions and tool totals |
| current execution plan | old sections still point to M01 next action, while the newer synthesis section makes M00 gating primary |
| app/brand naming | `jpcite`, `AutonoMath`, `autonomath-api`, and `jpintel_mcp` appear in separate deployment and source surfaces |
| inbox contract | older docs describe two CLI streams, while `value_growth_dual` is now a third effective stream |
| secret location | `SECRETS_REGISTRY.md`, legal compliance docs, workflow draft, and local `.env.local` describe different operational boundaries |

Working SOT for the next implementation loop:

1. `docs/_internal/CURRENT_SOT_2026-05-06.md` is the current pointer layer.
2. `tools/offline/_inbox/value_growth_dual/SYNTHESIS_2026_05_06.md` sections 8.19 and 9 define execution control.
3. `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md` defines repository hygiene and debug order.
4. Existing older indexes are historical until reconciled.

## 5. Debug findings

### P0: secret hygiene

The gBiz token is present locally in an ignored env file and should not be copied into docs, logs, shell history, or chat. The scan did not find that token literal in tracked or untracked repository docs/workflows checked during this triage.

Ignored staging material appears to contain Stripe webhook secret-like values. Because ignored files can still leak through manual sharing, treat those values as rotation candidates and either delete the staging copy or replace with inert placeholders after confirming it is not needed.

Action:

- Update `docs/_internal/SECRETS_REGISTRY.md` as the SOT for secret names and storage boundaries.
- Do not paste secret values into markdown handoffs.
- Use environment variable names only, not literal tokens.

### P0: M01 gBiz is not deploy-ready

The handoff sequence says Fly secret, smoke, migration, then deploy/restart. That sequence should remain blocked until these local mismatches are fixed:

| issue | current finding | likely effect |
| --- | --- | --- |
| Fly app name | active Fly command docs now target `autonomath-api`; historical/product text may still say `jpcite-api` | keep command-level grep guard clean before deploy |
| CLI flags | local test confirms workflow aliases are accepted | keep as regression gate |
| rate limiter API | local test confirms legacy `get` wrapper and 429 fail-fast | keep as regression gate |
| SQL schema | local test confirms migration/cron insert column contract | keep as regression gate |
| attribution | helper now emits legal required keys; cron raw JSON stores inner `_attribution`; corporate mirror stores `source_url` / `upstream_source` / `attribution_json`; `/v1/houjin/{bangou}` now returns gBiz `_attribution`, `_disclaimer_gbiz`, and v2 citation locally | keep as regression gate before live publication |
| subsidy table | script writes `jpi_adoption_records`; repo has `adoption_records` pattern | insert target may be missing |
| workflow branch/log path | branch and update-log assumptions drift from local repo | CI false failure or no-op |

Action:

- First make all M01 scripts pass `--help`.
- Then run dry-run against a temp DB, not production.
- Then run one corporation smoke with local dev DB only.
- Only after that revisit Fly/GitHub secrets and deploy.

### P0: M00-D safety gate local status

| issue | finding | action |
| --- | --- | --- |
| customer cap | fail-closed focused tests are green locally | keep as deploy gate |
| Stripe webhook tolerance | locked to `tolerance=300` across billing/compliance/widget/advisors callsites; focused tests green | keep stubs/tests aligned with explicit kwarg |
| audit proof/evidence | audit seal now returns `audit_seal` only after persist confirmation; fail path returns `_seal_unavailable` | keep generated public artifacts frozen until proof surfaces are regenerated as one lane |
| credit pack | Stripe idempotency key, stale reserved recovery, and non-ACK unfinished webhook path are covered; focused tests green | apply jpintel-target migration only through deploy packet |

This local green status is not a production deploy authorization by itself. It only means the M00-D P0 blockers are no longer the first known red tests in this workspace snapshot.

### P1: generated surfaces

The distribution manifest drift check currently passes:

```text
[check_distribution_manifest_drift] OK - distribution manifest matches static surfaces.
```

That is a good sign, but it does not mean regeneration is safe. Generated surfaces should remain frozen until:

- M00-D passes
- M01 schema and CLI contracts are fixed
- OpenAPI/MCP/site manifests are regenerated from one command path
- generated output diffs are reviewed as a single release lane

### P1: tracked vs ignored artifacts

Likely tracked release surfaces:

- `docs/openapi/agent.json`
- `docs/openapi/v1.json`
- `site/openapi.agent.json`
- `site/mcp-server.json`
- `site/server.json`
- SDK lockfiles

Likely ignored or deletion-candidate generated outputs, pending confirmation:

- SDK package tarballs / VSIX outputs
- local DB/WAL/SHM files
- `node_modules`
- Python caches
- local virtualenvs
- large offline inbox snapshots that are no longer referenced by handoff docs

Do not delete these in bulk. First check whether release scripts or docs reference them.

## 6. Safe validation commands

Safe commands already run in this triage:

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from pathlib import Path
paths = [
    'scripts/cron/ingest_gbiz_corporate_v2.py',
    'scripts/cron/ingest_gbiz_subsidy_v2.py',
    'scripts/cron/ingest_gbiz_certification_v2.py',
    'scripts/cron/ingest_gbiz_procurement_v2.py',
    'scripts/cron/ingest_gbiz_commendation_v2.py',
    'src/jpcite/api/_gbiz_rate_limiter.py',
    'scripts/check_distribution_manifest_drift.py',
]
for path in paths:
    compile(Path(path).read_text(), path, 'exec')
print('in_memory_compile_ok')
PY
.venv/bin/python scripts/check_distribution_manifest_drift.py
```

Results:

- whitespace check: pass
- in-memory compile for 7 selected Python files: pass
- distribution manifest drift: pass

Safe next commands:

```bash
.venv/bin/python -m ruff check --no-cache scripts src tests
.venv/bin/python -m ruff format --check scripts src tests
.venv/bin/python scripts/cron/ingest_gbiz_corporate_v2.py --help
.venv/bin/python scripts/cron/ingest_gbiz_subsidy_v2.py --help
.venv/bin/python scripts/cron/ingest_gbiz_certification_v2.py --help
.venv/bin/python scripts/cron/ingest_gbiz_procurement_v2.py --help
.venv/bin/python scripts/cron/ingest_gbiz_commendation_v2.py --help
```

Use temp DB paths for any ingestion test:

```bash
tmp_db="$(mktemp -t jpcite-gbiz.XXXXXX.sqlite)"
.venv/bin/python scripts/cron/ingest_gbiz_corporate_v2.py --dry-run --db-path "$tmp_db" --houjin-bangou 8010001213708
```

## 7. Non-destructive cleanup sequence

### Phase 0: freeze risky effects

Owner: current operator

- keep production deploy paused
- keep Fly secret and migration apply paused
- keep bulk clean/delete paused
- mark `_m00_implementation/*` as reserved by the other CLI

Exit condition:

- this triage file exists
- all agents' findings are summarized
- no production command has run

### Phase 1: SOT reconciliation

Owner: docs/SOT lane

- create a compact current SOT index
- mark older index files as historical without deleting them
- normalize app names in docs only after deciding whether Fly target is `autonomath-api` or `jpcite-api`
- update secrets registry with names and locations, not values

Exit condition:

- one doc says which plan controls execution
- no contradictory next action remains unlabelled as historical

### Phase 2: M01 local contract repair

Owner: gBiz lane

- align argparse names used by workflow and scripts
- replace `_gbiz.get(...)` calls with the actual exported rate-limited API
- align SQL table columns and INSERT statements
- fix `jpi_adoption_records` target or add an explicit compatibility table
- add one temp-DB smoke test that does not need network

Exit condition:

- all M01 cron scripts pass `--help`
- temp DB dry-run reaches the API boundary cleanly
- migration applies to sqlite memory or temp DB without schema mismatch

### Phase 3: M00-D safety gate

Owner: other CLI unless handed back

- decide Stripe webhook tolerance policy
- make customer cap fail closed
- verify audit proof/evidence packet contract

Exit condition:

- targeted billing/security tests pass
- no public generated artifact depends on an unsettled proof contract

### Phase 4: generated release surface regeneration

Owner: release/distribution lane

- run one canonical regeneration command
- run manifest drift check
- review generated JSON/site/OpenAPI diffs as a group

Exit condition:

- generated diffs are explainable
- manifest drift check passes after regeneration

### Phase 5: SDK and docs release cleanup

Owner: SDK/docs lane

- confirm package artifacts are either tracked releases or ignored build outputs
- add scoped ignore rules only for disposable outputs
- update public docs after product/tool count SOT is settled

Exit condition:

- no accidental release artifact deletion
- public docs match current manifest/tool count

## 8. Value opportunities found during cleanup

The cleanup process exposed assets that can become product value, not just engineering debt:

| asset | value opportunity |
| --- | --- |
| M01 gBiz mirror | company-folder baseline: official corporate facts, subsidies, certifications, procurement, commendations |
| distribution manifest | AI-facing trust layer: models can discover exactly which tools exist and what each tool returns |
| offline research inbox | paid-output design library: persona recipes, industry packs, benchmarks, and evidence templates |
| SOT reconciliation | operational credibility: fewer contradictory claims in docs and AI-facing surfaces |
| safety gates | paid-user trust: billing caps, webhook tolerance, audit proof, and citation attribution become reasons to use jpcite as the public-data layer |

The biggest product direction remains: make jpcite the cheapest and fastest first stop for AI agents that need public Japanese corporate, regulatory, program, and professional-service context. The repo cleanup should therefore prioritize reliable company-folder output and AI-readable manifests before broad marketing edits.

## 9. Next work packet

Recommended next packet for the current operator:

1. Patch M01 local contract mismatches only, with no production side effects.
2. Add or run temp-DB tests for gBiz script/schema compatibility.
3. Produce a SOT reconciliation doc that names the current execution plan and labels older plans historical.
4. Wait for the other CLI's M00-D safety results before touching billing, webhook, audit proof, or generated release surfaces.
5. After M00-D passes, regenerate and review distribution artifacts as one bundle.

Recommended next packet for the external CLI:

1. Finish M00-D customer cap and Stripe webhook policy.
2. Report exact changed files and tests.
3. Avoid M01 gBiz cron, migration, and workflow files unless explicitly handed over.

## 10. Final cleanup standard

The repository is considered clean enough for daily production improvement when all of these are true:

- `git status` changes are grouped by lane and each lane has an owner
- no untracked file is ambiguous between release artifact and disposable output
- one execution SOT exists for the current day
- production deploy commands are separated from local debug commands
- generated artifacts are regenerated from one path and pass drift checks
- secret names are documented, but no secret values are present in docs or handoffs
- targeted safety tests pass for billing, rate limits, webhook tolerance, and ingestion dry-runs
