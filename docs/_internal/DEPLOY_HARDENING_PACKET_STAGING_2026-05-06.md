# Deploy Hardening Packet Staging 2026-05-06

Status: NO-GO.

This is a local packetization runbook only. It is not a production mutation
plan, not an approval packet, and not evidence that deploy is allowed. The
current deploy state remains NO-GO until the operator has separately reviewed
the dirty lanes, ACK requirements, migration boundaries, secrets posture, and
final gate output.

Do not run production deploy, production migration, production secret mutation,
live ingest, or production API mutation while following this document.

## Operator Intent

Use this staging packet to make one reviewable "deploy hardening core" from the
current mixed worktree. The packet should be small enough that the operator can
answer:

- which files are in scope;
- which risks are intentionally covered;
- which tests prove the hardening behavior;
- which changed files are deliberately excluded into other packets;
- which commands are examples only and require explicit operator execution.

## Current NO-GO Reasons

Treat the repo as NO-GO because:

- the worktree is broad and mixed;
- `dirty_tree` is still a deploy gate failure until the final reviewed packet is
  clean or explicitly acknowledged;
- `operator_ack` is not provided by this staging document;
- migration auto-apply, target DB ownership, and rollback/reconciliation must be
  reviewed before any production write path;
- live gBiz ingest and production secrets require separate operator approval;
- workflow target tracking and workflow write targets must be verified before a
  release path is used.

## Latest Implementation Delta

Preserve these current implementation changes in the deploy-hardening review:

- `scripts/ops/release_readiness.py` no longer blocks on distribution manifest
  metadata or generated distribution counts. Release readiness is scoped to
  workflow target sync/tracking, release format gating, deploy/entrypoint
  preflight alignment, WAF docs, the read-only preflight script, and its own
  tests. Distribution manifest/count review stays in the separate distribution
  companion packet.
- `src/jpintel_mcp/api/openapi_agent.py` now treats artifact routes as optional.
  Agent first-hop guidance for `createCompanyPublicBaseline` is emitted only
  when `/v1/artifacts/company_public_baseline` exists; if the artifact backend
  is absent, the agent OpenAPI projection omits artifact paths and the
  `x-jpcite-first-hop-policy` block instead of advertising unavailable optional
  artifacts.
- `src/jpintel_mcp/api/artifacts.py` now pins deterministic artifact endpoints
  to `response_model=ArtifactResponse` with
  `response_model_exclude_unset=True`, including the company-public artifact
  routes. This keeps the generated OpenAPI contract anchored to the artifact
  envelope instead of ad hoc dict inference, and exposes explicit
  `ArtifactResponse` fields for artifact metadata, sections/sources,
  structured `known_gaps`, `source_receipts`, billing metadata, agent routing,
  `audit_seal`, and `_seal_unavailable`.
- Artifact `known_gaps` are normalized to a structured schema:
  `gap_id`, `severity`, `message`, `message_ja`, `section`, and
  `source_fields`. Legacy string gaps are preserved by converting them into
  review-severity records instead of dropping them.
- Agent-facing billing metadata now describes compatibility billing in
  pair-count units. `/v1/funding_stack/check` and
  `/v1/artifacts/compatibility_table` both advertise `pair_count` billing, and
  artifact response metadata exposes `quantity`, `result_count`, and
  `pair_count` consistently for usage/cap reconciliation.
- Evidence Packet paid-output paths now use strict delivery gating for metering
  and audit seals. `evidence_batch` / `evidence.packet.batch`,
  `evidence.packet.get`, and `evidence.packet.query` must call usage logging
  with `strict_metering=True`; JSON paid-output paths that issue audit seals
  must also use `strict_audit_seal=True` before the response is delivered.
- Paid artifact final metering-cap rejection now fails closed before delivery:
  `503 billing_cap_final_check_failed` must leave both `usage_events` and
  `audit_seals` unchanged.
- Evidence Packet final metering-cap rejection now has the same fail-closed
  property: `503 billing_cap_final_check_failed` for `evidence.packet.batch`,
  `evidence.packet.get`, or `evidence.packet.query` must leave both
  `usage_events` and `audit_seals` unchanged.
- Public audit-seal verification keeps a legacy fallback: lookup by `seal_id`
  first, then by legacy `call_id` for pre-`seal_id` rows or schemas.
- Full and agent OpenAPI specs were regenerated from the runtime schema, and
  the targeted OpenAPI/export/agent/artifact response-model tests are green.
- The latest local gate snapshot remains NO-GO only for the known review
  blockers: production GO gate is `3 pass / 2 fail / 5`, with only
  `dirty_tree` and `operator_ack` red; aggregate pre-deploy is
  `2 pass / 1 fail / 3`, with only
  `release_readiness.workflow_targets_git_tracked` red; `release_readiness` is
  `8/1/9`, with only `workflow_targets_git_tracked` red.

## Latest Handoff Reconciliation

Read the latest value-growth handoff as planning/spec input, not as deploy
permission. The current execution SOT remains
`docs/_internal/CURRENT_SOT_2026-05-06.md`,
`docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md`, and
`docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md`.

Important reconciliation rules:

- `tools/offline/_inbox/value_growth_dual/HANDOFF_2026_05_06.md` contains
  operator action examples such as Fly secret mutation, live smoke, production
  migration apply, deploy/restart, and GitHub secret registration. Those
  examples are not part of this staging packet and must not be executed by an
  automated agent.
- Active Fly command targets are `autonomath-api`, not historical
  `jpcite-api` command contexts. Any handoff command that still names
  `jpcite-api` is stale for production command execution.
- M00-D billing/security and company public artifact behavior have local green
  evidence, including customer cap fail-closed, Stripe webhook tolerance,
  credit-pack idempotency, audit-seal persistence, paid-key usage logging, and
  source-receipt quality checks. This is local evidence only; it does not clear
  `dirty_tree`, `operator_ack`, migration ownership, secret placement, or live
  ingest blockers.
- M00-A distribution parity is locally green at 139 MCP tools, 269 runtime
  routes, and 227 REST OpenAPI paths. Generated OpenAPI, MCP, DXT, site JSON,
  and SDK release surfaces stay frozen unless cut as one reviewed distribution
  companion packet.
- M01 gBiz contracts are locally improved, but live gBiz ingest remains NO-GO
  until Fly app naming, secret-name placement, and production migration
  boundaries are reviewed in the final deploy packet.

## Packet Boundary Summary

Use three packets, not one broad packet:

| packet | purpose | deploy relationship |
| --- | --- | --- |
| core deploy-hardening packet | deploy gate, boot migration guard, ACK shape, secrets-name registry, migration target inventory, focused deploy-safety tests | must be reviewed before any production deploy path |
| distribution companion packet | generated OpenAPI/MCP/DXT/site JSON/SDK mirrors, manifest counts, DA-01 139-to-140 tool changes, first-hop discovery surfaces | must stay frozen until core and M01/M00 contracts settle; regenerate and review together |
| artifact backend packet | paid artifact handlers, source receipts, audit-seal persistence, usage metering, company-folder/product aliases such as `client_company_folder_v1` | may depend on core safety and distribution mirrors, but should not be bundled into deploy-gate mechanics unless a specific fail-closed property is under review |

## Core Packet Candidate Files

Candidate means "review together". It does not mean "stage now" or "commit now".
The operator should remove any file whose diff is not part of deploy hardening.

| path | why it belongs in the core candidate set |
| --- | --- |
| `.github/workflows/deploy.yml` | production deploy hard gate wiring and operator ACK enforcement |
| `entrypoint.sh` | boot-time migration behavior and fail-closed runtime semantics |
| `scripts/migrations/autonomath_boot_manifest.txt` | manifest-gated boot migration allowlist |
| `scripts/ops/production_deploy_go_gate.py` | final GO/NO-GO gate and dirty-lane fingerprint source |
| `scripts/ops/pre_deploy_verify.py` | aggregate local pre-deploy verification runner |
| `scripts/ops/release_readiness.py` | workflow target and release readiness gate |
| `scripts/ops/migration_inventory.py` | migration target DB and danger classification support |
| `scripts/ops/preflight_production_improvement.py` | production-improvement DB preflight guard |
| `scripts/ops/perf_smoke.py` | local smoke/perf verification support |
| `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md` | current NO-GO evidence and blocker table |
| `docs/_internal/operator_deploy_ack_addendum_2026-05-06.md` | ACK shape and operator-only handoff |
| `docs/_internal/SECRETS_REGISTRY.md` | secret-name source of truth without values |
| `docs/_internal/release_readiness_2026-05-06.md` | release readiness evidence note |
| `docs/_internal/waf_deploy_gate_prepare_2026-05-06.md` | WAF/deploy gate preparation notes |
| `docs/_internal/DEPLOY_HARDENING_PACKET_STAGING_2026-05-06.md` | this local staging runbook |
| `tests/test_production_deploy_go_gate.py` | gate behavior coverage |
| `tests/test_pre_deploy_verify.py` | pre-deploy verification coverage |
| `tests/test_release_readiness.py` | release readiness and workflow target coverage |
| `tests/test_boot_gate.py` | production boot gate coverage |
| `tests/test_entrypoint_vec0_boot_gate.py` | entrypoint boot behavior coverage |
| `tests/test_no_default_secrets_in_prod.py` | production default-secret guard coverage |
| `tests/test_appi_turnstile.py` | APPI Turnstile fail-closed coverage |
| `tests/test_appi_deletion_turnstile.py` | APPI deletion Turnstile coverage |
| `tests/test_gbiz_ingest_workflow.py` | gBiz workflow static contract coverage |
| `tests/test_migration_inventory.py` | migration inventory and target DB coverage |
| `tests/test_production_improvement_preflight.py` | production-improvement preflight coverage |

Optional only if the diff is strictly hardening-related:

- `src/jpintel_mcp/api/_audit_seal.py`
- `src/jpintel_mcp/api/anon_limit.py`
- `src/jpintel_mcp/api/appi_deletion.py`
- `src/jpintel_mcp/api/appi_disclosure.py`
- `src/jpintel_mcp/api/billing.py`
- `src/jpintel_mcp/api/line_webhook.py`
- `src/jpintel_mcp/api/middleware/cost_cap.py`
- `src/jpintel_mcp/api/middleware/idempotency.py`
- `src/jpintel_mcp/api/middleware/origin_enforcement.py`
- `src/jpintel_mcp/api/audit_proof.py`

If any optional runtime file is included, the packet must name the exact
security property being hardened: fail-closed behavior, idempotency, cost cap,
origin enforcement, APPI/Turnstile, audit seal persistence, webhook safety, or
anonymous rate limiting.

## Distribution Companion Packet

Keep this packet separate from the core deploy-hardening packet. It should be
cut only after the runtime source-of-truth is settled and the operator intends
to refresh the public/AI-facing distribution surfaces together.

Candidate companion surfaces:

- generated OpenAPI: `docs/openapi/*.json`, `site/openapi*.json`, and
  `site/docs/openapi/*.json`;
- MCP and registry manifests: `mcp-server*.json`, `server.json`,
  `smithery.yaml`, `dxt/manifest.json`, and distribution manifest metadata;
- SDK/package mirrors: `sdk/**`, package lockfiles, package tarballs, DXT/MCPB
  outputs, and browser/IDE extension surfaces;
- LLM/site discovery mirrors: `site/llms*.txt`, `.well-known` files,
  public-count snapshots, and generated site JSON;
- DA-01 eligibility predicate registration if the operator intentionally moves
  from 139 to 140 tools.

Rules:

- Do not hand-edit generated OpenAPI or manifest mirrors. Change the runtime
  source or generator, regenerate, then review the generated diff as one bundle.
- Do not mix a 139-to-140 tool-count change into the core deploy-hardening
  packet. It requires manifest, docs, DXT, site JSON, and count review together.
- If distribution static/runtime checks pass before regeneration, treat that as
  freeze evidence, not permission to refresh release artifacts.
- Do not re-add distribution manifest checks to `release_readiness`; generated
  manifest/count assertions belong to this companion packet, not the core
  release-readiness gate.

## Artifact Backend Packet

Treat artifact backend work as a product/runtime packet unless it is directly
hardening a fail-closed production property.

Candidate artifact backend material:

- paid artifact endpoints and handlers under `src/jpintel_mcp/api/artifacts*`;
- `company_public_baseline`, `company_folder_brief`,
  `company_public_audit_pack`, and future `client_company_folder_v1` aliases;
- audit-seal persistence, source receipts, usage-event metering, idempotency,
  and billing/cap interactions that determine whether paid output may be
  delivered;
- tests covering artifact contracts, usage logging, source-receipt gaps, and
  audit-seal failure behavior.

Current staging rule: paid artifacts must fail closed when audit-seal
persistence fails. Metered artifact endpoints should return
`503 audit_seal_persist_failed`, with no artifact body and no `usage_events`
write. Do not bypass this to `_seal_unavailable` for paid artifacts.

Current final-cap rule: paid artifact final metering-cap failures must return
`503 billing_cap_final_check_failed` before writing either `usage_events` or
`audit_seals`. Do not deliver an unmetered artifact body after the final cap
check rejects the charge.

Current response-contract rule: deterministic artifact routes must keep the
explicit `response_model=ArtifactResponse` and
`response_model_exclude_unset=True` declarations. Do not remove this pin while
refreshing generated OpenAPI or agent surfaces.

Current `known_gaps` rule: artifact responses must keep structured gap records
with `gap_id`, `severity`, `message`, `message_ja`, `section`, and
`source_fields`. Existing string gaps may be accepted only through the
normalizer, which converts them into review records.

Current billing-metadata rule: compatibility artifacts bill by actual
compatibility pair count, not by one request or one artifact envelope. Agent
billing metadata and artifact `billing_metadata` must continue to expose
`pair_count` as the billable unit basis.

Current audit-seal compatibility rule: public seal verification must keep the
legacy `call_id` fallback for old rows while preferring `seal_id` for new
rows.

Current Evidence Packet metering rule: paid `evidence_batch` /
`evidence.packet.batch`, `evidence.packet.get`, and `evidence.packet.query`
responses must be delivered only after strict metering succeeds. Paid JSON
responses that expose `audit_seal` must also require strict audit-seal
persistence before delivery; do not return a paid evidence packet with an
unmetered body or a missing required seal.

Current Evidence Packet final-cap rule: final metering-cap failures must return
`503 billing_cap_final_check_failed` before writing either `usage_events` or
`audit_seals`. This rule is covered for batch, single packet GET, and packet
query paths.

The next value packet may expose existing `company_folder_brief` as
`client_company_folder_v1`, but only after M00-D/M01/deploy gates remain green
and the route/OpenAPI/distribution packet is intentionally cut.

OpenAPI agent guidance must keep these artifacts optional: when artifact routes
are not mounted, the agent-safe OpenAPI must not include artifact paths or
first-hop instructions that name artifact operations.

## Split Into Separate Packets

Keep these groups out of the core deploy hardening packet unless the operator
explicitly approves a broader scope:

| separate packet | examples | reason to split |
| --- | --- | --- |
| migration/data-layer packet | `scripts/migrations/*.sql`, rollback SQL, `docs/_internal/migration_inventory_latest.md` | requires target DB, apply order, rollback, and destructive-marker review |
| live ingest and ETL packet | `scripts/cron/**`, `scripts/etl/**`, gBiz refresh jobs | can call external APIs or write production DBs when enabled |
| scheduled workflow packet | new hourly/daily/monthly workflows beyond `deploy.yml` | needs permissions, concurrency, secrets, write targets, and rollback review |
| generated distribution packet | `docs/openapi/*.json`, `site/openapi*.json`, MCP manifests, DXT, SDK mirrors | should be regenerated from source and compared as one bundle |
| public site and launch packet | `site/**`, `docs/launch/**`, `docs/launch_assets/**`, blog and pricing copy | generated/public claims must be reviewed separately from deploy gates |
| SDK/package packet | `sdk/**`, package lockfiles, package artifacts, browser/IDE extensions | versioning and package registry risk are separate from production deploy hardening |
| artifact backend packet | `src/jpintel_mcp/api/artifacts*`, company public packs, source receipts, usage-event metering, audit-seal paid-output behavior | product deliverable and billing/audit contract review; include in core only for a named fail-closed hardening property |
| broad runtime feature packet | `src/jpintel_mcp/api/intel_*`, narrative, calculator, evidence batch | product feature review and API compatibility are broader than deploy hardening |
| offline/operator research packet | `tools/offline/**`, inbox outputs, marketplace applications, raw batch outputs | local outputs need redaction and reproducibility review before source control |
| benchmark/monitoring packet | `benchmarks/**`, SLO configs, generated reports | keep compact summaries separate from raw runs |
| internal-docs archive packet | handoffs, plans, legal notes, historical packets | useful operator memory, but not release-critical code |

## Operator-Only Actions

The following action families may appear in handoffs or examples, but they are
operator-only and outside this staging packet:

- creating or modifying the final deploy ACK file;
- setting, unsetting, rotating, or inspecting production secret values;
- registering GitHub Actions secrets;
- running live gBiz smoke or monthly ingest;
- applying migrations to production DB files or production Postgres;
- changing Fly machines, restarting the Fly app, or deploying a new image;
- enabling scheduled workflows that write to production services;
- staging, committing, tagging, pushing, publishing packages, or submitting
  registry updates.

Automated agents may prepare documentation, run local read-only/static checks,
and produce candidate file lists. They must not perform the operator-only
actions above unless the operator gives a separate, explicit instruction.

## Local Packetization Flow

1. Re-snapshot the worktree:

```bash
git status --short
git status --porcelain=v1 -- .github/workflows/deploy.yml entrypoint.sh scripts/ops scripts/migrations/autonomath_boot_manifest.txt docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md docs/_internal/operator_deploy_ack_addendum_2026-05-06.md docs/_internal/SECRETS_REGISTRY.md docs/_internal/release_readiness_2026-05-06.md docs/_internal/waf_deploy_gate_prepare_2026-05-06.md tests/test_production_deploy_go_gate.py tests/test_pre_deploy_verify.py tests/test_release_readiness.py tests/test_boot_gate.py tests/test_entrypoint_vec0_boot_gate.py tests/test_no_default_secrets_in_prod.py tests/test_appi_turnstile.py tests/test_appi_deletion_turnstile.py tests/test_gbiz_ingest_workflow.py tests/test_migration_inventory.py tests/test_production_improvement_preflight.py
```

2. Review diffs for only the candidate files:

```bash
git diff -- .github/workflows/deploy.yml entrypoint.sh scripts/ops scripts/migrations/autonomath_boot_manifest.txt docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md docs/_internal/operator_deploy_ack_addendum_2026-05-06.md docs/_internal/SECRETS_REGISTRY.md docs/_internal/release_readiness_2026-05-06.md docs/_internal/waf_deploy_gate_prepare_2026-05-06.md tests/test_production_deploy_go_gate.py tests/test_pre_deploy_verify.py tests/test_release_readiness.py tests/test_boot_gate.py tests/test_entrypoint_vec0_boot_gate.py tests/test_no_default_secrets_in_prod.py tests/test_appi_turnstile.py tests/test_appi_deletion_turnstile.py tests/test_gbiz_ingest_workflow.py tests/test_migration_inventory.py tests/test_production_improvement_preflight.py
```

3. Operator-only staging example:

```bash
git add .github/workflows/deploy.yml entrypoint.sh scripts/ops/production_deploy_go_gate.py scripts/ops/pre_deploy_verify.py scripts/ops/release_readiness.py scripts/ops/migration_inventory.py scripts/ops/preflight_production_improvement.py scripts/ops/perf_smoke.py scripts/migrations/autonomath_boot_manifest.txt docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md docs/_internal/operator_deploy_ack_addendum_2026-05-06.md docs/_internal/SECRETS_REGISTRY.md docs/_internal/release_readiness_2026-05-06.md docs/_internal/waf_deploy_gate_prepare_2026-05-06.md docs/_internal/DEPLOY_HARDENING_PACKET_STAGING_2026-05-06.md tests/test_production_deploy_go_gate.py tests/test_pre_deploy_verify.py tests/test_release_readiness.py tests/test_boot_gate.py tests/test_entrypoint_vec0_boot_gate.py tests/test_no_default_secrets_in_prod.py tests/test_appi_turnstile.py tests/test_appi_deletion_turnstile.py tests/test_gbiz_ingest_workflow.py tests/test_migration_inventory.py tests/test_production_improvement_preflight.py
```

4. Operator-only commit example:

```bash
git commit -m "stage deploy hardening packet"
```

The examples above are not instructions for Codex or an automated agent to
execute. The operator must explicitly choose and run any staging or commit
command.

## Production-Prohibited Commands

Do not run these commands or command families from this staging packet. This
ban includes historical handoff commands, command variants, aliases, and
equivalent write paths.

- `fly deploy`
- `fly deploy -a <legacy-app-name>`
- `fly deploy -a autonomath-api`
- `flyctl deploy`
- `flyctl deploy -a <legacy-app-name>`
- `flyctl deploy -a autonomath-api`
- `flyctl ssh console -a <legacy-app-name> -C "<mutation command>"`
- `flyctl ssh console -a autonomath-api -C "<mutation command>"`
- `flyctl ssh console ... sqlite3 /data/autonomath.db ...`
- `flyctl secrets set ...`
- `flyctl secrets unset ...`
- `fly secrets set ...`
- `fly secrets unset ...`
- `flyctl machine update ...`
- `flyctl apps restart autonomath-api`
- `flyctl apps restart <legacy-app-name>`
- `fly machine restart ...`
- `uv run python scripts/migrate.py --db <production-db> ...`
- `sqlite3 /data/autonomath.db "<DDL or DML>"`
- `sqlite3 /Users/shigetoumeda/jpcite/autonomath.db < scripts/migrations/<production-intended>.sql`
- `psql "$DATABASE_URL" -c "<DDL or DML>"`
- `gh secret set ...`
- `gh workflow enable ...`
- `gh workflow run gbiz-ingest-monthly.yml ...`
- `GBIZINFO_API_TOKEN=... uv run python scripts/cron/ingest_gbiz_*.py`
- `.venv/bin/python scripts/cron/ingest_gbiz_*.py` without `--dry-run` against a production-capable DB
- `curl -X POST https://api.jpcite.com/...`
- `curl -X PUT https://api.jpcite.com/...`
- `curl -X PATCH https://api.jpcite.com/...`
- `curl -X DELETE https://api.jpcite.com/...`
- `git add ...`
- `git commit ...`
- `git tag ...`
- `git push ...`
- `npm publish ...`
- `twine upload ...`
- `stripe ... --live`

Read-only local checks are allowed. Production writes, production restarts,
production deploys, live third-party ingest, and secret mutations are forbidden
until a separate final deploy packet is GO.

## Latest Verification Snapshot

Current local evidence from the 2026-05-06 deploy packet, to be refreshed in
the final packet before any GO decision:

| check | latest local result |
| --- | --- |
| focused integration suite | 138 passed across gBiz, GO gate, boot gate, paid artifacts, agent billing metadata, release/CI workflow checks, and pre-deploy checks |
| targeted billing/payment safety suite | 57 passed, including pair-count billing metadata and usage/cap reconciliation |
| agent OpenAPI billing metadata suite | 4 passed, including `pair_count` billing for funding-stack and compatibility artifact operations |
| artifact response_model contract suite | passed, covering generated OpenAPI `ArtifactResponse` refs for deterministic artifact endpoints |
| artifact known_gaps schema suite | passed, covering structured `gap_id`/`severity`/`message`/`section`/`source_fields` records |
| paid artifact final cap failure suite | passed, covering `billing_cap_final_check_failed` with no new `usage_events` or `audit_seals` |
| Evidence Packet targeted suite | 90 passed, including `evidence_batch` / `evidence.packet.batch`, `evidence.packet.get`, and `evidence.packet.query` strict metering + strict audit-seal coverage |
| Evidence Packet final cap failure suite | passed, covering `billing_cap_final_check_failed` with no new `usage_events` or `audit_seals` for batch, GET, and query paid-output paths |
| audit-seal legacy verify fallback | passed, covering `seal_id` lookup with legacy `call_id` fallback |
| OpenAPI full/agent regeneration | passed, full and agent specs regenerated from runtime schema with targeted export/agent/response-model checks green |
| M00-D billing/security focused suite | 69 passed |
| credit pack focused suite | 19 passed |
| billing webhook regression suite | 20 passed |
| gBiz attribution/field/compact/ingest contract suite | 33 passed |
| gBiz monthly workflow static contract | 5 passed |
| company public artifacts usage + audit-seal suite | 19 passed, including `company_public_audit_pack.source_receipts` quality gate |
| distribution static/runtime/tool-count checks | OK at 139 tools / 269 routes / 227 OpenAPI paths |
| aggregate pre-deploy verify actual run | NO-GO: `2 pass / 1 fail`; failure is `release_readiness.workflow_targets_git_tracked` |
| production GO/NO-GO gate actual run | NO-GO: `3 pass / 2 fail / 5`; failures are `dirty_tree` and `operator_ack` |
| CI/release readiness | NO-GO: `release_readiness 8/1/9`; failure is `workflow_targets_git_tracked` |

This snapshot is evidence for review, not deploy authorization. Any edit to a
dirty file changes the dirty-tree content hash. Rerun the gate after all edits
are complete and copy only the final machine output into an out-of-repo ACK if
the operator chooses the reviewed dirty-tree path.

## Verification After Packetization

Run these after the operator has selected the local packet contents. They do not
deploy, mutate production, set secrets, or apply migrations.

```bash
git diff --check -- .github/workflows/deploy.yml entrypoint.sh scripts/ops scripts/migrations/autonomath_boot_manifest.txt docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md docs/_internal/operator_deploy_ack_addendum_2026-05-06.md docs/_internal/SECRETS_REGISTRY.md docs/_internal/release_readiness_2026-05-06.md docs/_internal/waf_deploy_gate_prepare_2026-05-06.md docs/_internal/DEPLOY_HARDENING_PACKET_STAGING_2026-05-06.md tests/test_production_deploy_go_gate.py tests/test_pre_deploy_verify.py tests/test_release_readiness.py tests/test_boot_gate.py tests/test_entrypoint_vec0_boot_gate.py tests/test_no_default_secrets_in_prod.py tests/test_appi_turnstile.py tests/test_appi_deletion_turnstile.py tests/test_gbiz_ingest_workflow.py tests/test_migration_inventory.py tests/test_production_improvement_preflight.py
uv run python scripts/ops/release_readiness.py --warn-only
uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db --warn-only
uv run python scripts/ops/production_deploy_go_gate.py --warn-only
uv run pytest tests/test_production_deploy_go_gate.py tests/test_pre_deploy_verify.py tests/test_release_readiness.py tests/test_boot_gate.py tests/test_entrypoint_vec0_boot_gate.py tests/test_no_default_secrets_in_prod.py tests/test_appi_turnstile.py tests/test_appi_deletion_turnstile.py tests/test_gbiz_ingest_workflow.py tests/test_migration_inventory.py tests/test_production_improvement_preflight.py
```

Expected result for this staging phase: commands may still report NO-GO because
the tree is dirty and the operator ACK is absent. That is acceptable for local
packetization. A GO decision requires a separate final deploy packet and fresh
gate output.
