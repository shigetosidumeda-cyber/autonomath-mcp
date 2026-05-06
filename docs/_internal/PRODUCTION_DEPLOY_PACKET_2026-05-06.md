# Production Deploy Packet 2026-05-06

Status: NO-GO.

This packet records the current deploy gate after the Codex implementation loop on 2026-05-06 JST. It is a local verification summary only; no production deploy, secret mutation, live gBiz ingest, or production migration apply has been executed.

## Latest Deploy Gate Addendum

`deploy.yml` now requires `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` and runs both `pre_deploy_verify` and `production_deploy_go_gate` as hard gates before `flyctl deploy`.

`entrypoint.sh` autonomath boot migration is now default manifest-gated with `AUTONOMATH_BOOT_MIGRATION_MODE=manifest`; production boot must not bulk-apply unreviewed migrations outside the reviewed manifest path.

Remaining machine-detected gate failures may be `workflow_targets_git_tracked`, `dirty_tree`, and `operator_ack`. That list is not the operator-review NO-GO table and does not clear any human-reviewed blockers below.

`PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` is the operator ACK body, not a secret value. It must contain all 8 required acknowledgement booleans set to `true`, and the ACK body must not be committed, generated, or stored inside this repo.

## Local Verification Checks

| lane | result |
| --- | --- |
| latest focused integration suite | 135 passed (`gBiz`, GO gate, boot gate, paid artifacts, release/CI workflow checks, pre-deploy checks) |
| M00-D billing/security focused suite | 69 passed |
| credit pack focused suite | 19 passed |
| billing webhook regression suite | 20 passed |
| gBiz attribution/field/compact/ingest contract suite | 33 passed; includes corporate mirror `attribution_json`, corporate delta mixed-key extraction, residual-family UPSERT refresh, preflight-before-fetch, per-houjin source URL attribution, and rollback on partial writes |
| gBiz monthly workflow static contract | 5 passed; locks workflow_dispatch mode, 5 delta families, Fly SSH `/data/autonomath.db`, log paths, failure-only notifications, and GitHub secret refs |
| houjin public-response gBiz attribution + v2 citation suite | included in 32 passed focused envelope run |
| company public artifacts usage + audit-seal suite | 19 passed; includes `company_public_audit_pack.source_receipts` quality gate |
| distribution static/runtime/tool-count checks | OK at 139 tools / 269 routes / 227 OpenAPI paths |
| migration `wave24_166_credit_pack_reservation.sql` + rollback syntax | sqlite `:memory:` OK |
| migration target/danger gate | dirty/new forward migrations must declare `target_db`; destructive forward SQL is blocked except FTS delete triggers and view refreshes with same-file recreate |
| migration `007_anon_rate_limit.sql` target | marked `-- target_db: jpintel`; sqlite `:memory:` syntax OK |
| production improvement preflight + perf smoke | local production-improvement preflight passed; latest perf smoke passed with `/healthz` ~80 ms, `/v1/programs/search` ~423 ms, `/v1/meta` ~84 ms |
| aggregate pre-deploy verify actual run | NO-GO: `2 pass / 1 fail`; failure is `release_readiness.workflow_targets_git_tracked`, not a live-service mutation |
| production_deploy_go_gate unit tests | 20 passed; the gate itself is read-only, performs no network calls, reads no secret values, and applies no migrations |
| production GO/NO-GO gate actual run | NO-GO: `3 pass / 2 fail / 5`; failures remain `dirty_tree` and `operator_ack` |
| APPI production boot/helper gate | focused suite included in 59 passed; app lifespan now calls the production secret gate before `init_db()`, and the APPI prod/production helper path is covered |
| CI/release readiness | NO-GO in current dirty worktree: `9 pass / 1 fail / 10`; target sync and Ruff format gate pass, but `workflow_targets_git_tracked` fails because 23 workflow lint/test targets are still untracked |
| gBiz corporate pagination/savepoint/facts refresh | current implementation handles corporate `page` / `totalPage` pagination, uses per-houjin savepoint rollback, and refreshes corporate facts before freshness is claimed |
| gBiz family pagination ownership | subsidy/certification/commendation/procurement now also use `page` / `totalPage`, `force_refresh=True`, preflight DB/schema before live fetch, per-houjin source URL attribution, and UPSERT/update semantics instead of stale `INSERT OR IGNORE` |
| gBiz corporate blocker closure | local evidence now covers schema preflight before fetch, dry-run preflight, canonical env gating, and delta `update_log` success-count reporting; focused/broader suites recorded `38 passed`, `43 passed`, and `141 passed` |

## NO-GO Blockers

| blocker | current state | required before deploy |
| --- | --- | --- |
| Fly app name | Active operation docs now use `autonomath-api` for Fly command targets; historical/product mentions remain | keep the command-context grep guard clean for legacy Fly app aliases before deploy |
| production secrets | Secret names must be confirmed on `autonomath-api`; gBiz token is not a live-deploy precondition until approved and placed intentionally | verify required secret names only; never paste values into docs/logs/chat |
| APPI Turnstile state | production boot now fails closed when APPI intake/deletion is enabled without `CLOUDFLARE_TURNSTILE_SECRET`; current Fly secret list snapshot does not show that name | either confirm APPI is intentionally disabled through `AUTONOMATH_APPI_ENABLED=0` / `false`, or place/verify the Turnstile secret name before deploy |
| local Fly deploy / Docker build context | current local `fly deploy` is NO-GO: `Dockerfile` uses `COPY src/scripts`, but deploy-time script and migration behavior depends on what is actually present in the Fly build context | do not run local `fly deploy` until Docker build context contents are reviewed and the image is proven to contain only the intended runtime scripts |
| migration auto-apply path | `entrypoint.sh` degraded semantics and `scripts/migrations` auto-apply behavior can turn image contents into production DB mutations at boot | disable or explicitly packet-review auto-apply before deploy; degraded startup must not mask skipped or failed migration review |
| target DB boundaries | `entrypoint.sh` and migration inventory still show mixed `autonomath` / `jpintel` ownership risk | mark/review target DB for deploy packet migrations; do not bulk-apply unreviewed migrations |
| migration top risks | default `AUTONOMATH_BOOT_MIGRATION_MODE=manifest` with the empty manifest auto-applies 0 `autonomath` migrations at boot; non-empty manifest entries or `discover` mode would become production DB mutations | split by target DB and approve exact files/runners before any image boot or manual migration apply; do not enable non-empty manifest or `discover` without operator approval |
| R2 bootstrap | missing DB background bootstrap is allowed and is not a foreground deploy blocker; an existing DB SHA mismatch is a different condition | existing DB SHA mismatch is foreground repair when `AUTONOMATH_DB_URL` is set, and fail-closed when URL/download/hash validation is unavailable |
| rollback plan | `credit_pack_reservation` rollback is destructive because it deletes idempotency evidence | require pre-rollback reconciliation SQL and Stripe balance-transaction review before any rollback |
| tier C cleanup | tier C cleanup remains unsafe in the current dirty packet because generated/site/sdk/offline-inbox surfaces are broad and mixed | no bulk cleanup until deploy lanes are reviewed and separated from production release blockers |
| live gBiz ingest | gBiz ingest code may be deployed only if live monthly ingest is disabled or explicitly approved with `GBIZINFO_API_TOKEN` placed on the Fly machine | do not run live gBiz ingest from GitHub/Fly until app, secret, and migration gates are reviewed |
| workflow target tracking | release readiness now detects 23 workflow lint/test targets that exist locally but are not tracked by git | commit the workflow targets with the workflow changes, or remove them from workflow target lists before any release/deploy path |
| dirty tree | current worktree is intentionally broad and mixed; release packet must be lane-reviewed before deploy | run `production_deploy_go_gate.py`; deploy only with clean tree or a reviewed dirty-lane packet whose fingerprint matches the current tree |
| preflight | `production_improvement_preflight` now scopes numeric 177 checks to `177_*.sql`; `wave24_177_*` is a separate lane and ignored for that check | rerun `pre_deploy_verify.py --preflight-db autonomath.db --warn-only` in the final deploy packet before any GO decision |

## Current GO Gate Output

Latest local run:

```bash
uv run python scripts/ops/production_deploy_go_gate.py --warn-only
```

Current summary:

| check | result |
| --- | --- |
| `fly_app_command_contexts` | PASS (`fly.toml` app is `autonomath-api`; legacy Fly app command contexts clean) |
| `secret_registry_names` | PASS (`SECRETS_REGISTRY.md` documents required, conditional, and optional names; no secret values read) |
| `migration_target_boundaries` | PASS (`wave24_164` = `autonomath`, `wave24_166` = `jpintel`, dirty forward migrations declare allowed targets) |
| `dirty_tree` | FAIL: `dirty_tree_present:852` |
| `operator_ack` | FAIL: `operator_ack:not_provided_or_unreadable` |

Gate summary: `pass=3`, `fail=2`, `total=5`.

The NO-GO reason remains unchanged: dirty tree plus missing operator acknowledgement. No production deploy may proceed until both are resolved or explicitly reviewed through the allowed dirty-lane ack path.

Dirty fingerprint currently emitted by the gate:

| field | value |
| --- | --- |
| `current_head` | `f3679d6926d8654e106544523283fc04a729ea51` |
| `dirty_entries` | `852` |
| `status_counts` | `M=243`, `D=1`, `??=608` |
| `lane_counts` | `benchmarks_monitoring=28`, `billing_auth_security=10`, `cron_etl_ops=58`, `data_or_local_seed=1`, `generated_public_site=79`, `internal_docs=81`, `migrations=154`, `misc_review=32`, `openapi_distribution=6`, `operator_offline=29`, `public_docs=73`, `root_release_files=10`, `runtime_code=90`, `sdk_distribution=55`, `tests=128`, `workflows=18` |
| `critical_lanes_present` | `billing_auth_security`, `cron_etl_ops`, `migrations`, `root_release_files`, `runtime_code`, `workflows` |
| `path_sha256` | `f9961d8d65bfa63525d825240ef9c81392c2883486d02107e78bfe74209c81fe` |
| `staged_deletions` | `[]`; latest `git diff --cached --name-status` is empty, so the latest state has no staged deletion |
| `content_sha256` | ACK copy forbidden from this packet. Editing this markdown changes the dirty-tree content hash; rerun the gate and copy only the final machine output into an ACK |
| `content_hash_skipped_large_files` | `[]` |

The current `D=1` in `status_counts` is a worktree deletion, not a staged deletion. Do not read any older SDK tgz deletion wording as current staged state; latest state has no staged deletion.

## Workflow Static Gates

`tests/test_gbiz_ingest_workflow.py` fixes the monthly gBiz ingest workflow contract without touching live Fly or gBiz:

- `workflow_dispatch` mode is exactly `both`, `bulk-only`, `delta-only`.
- `FLY_APP` is `autonomath-api`.
- bulk and delta commands run through `flyctl ssh console` and write to `/data/autonomath.db`.
- delta matrix covers `corporate`, `subsidy`, `certification`, `commendation`, `procurement`.
- failure notifications are failure-only; GitHub secret refs are limited to `FLY_API_TOKEN` and optional `SLACK_WEBHOOK_INGEST`.

## gBiz Corporate Blocker Addendum

The main implementation has cleared the corporate blocker in local verification: schema preflight runs before fetch, dry-run preflight exercises the same guard path, canonical environment gating blocks ambiguous DB/env selection, and delta `update_log` now reports successful corporate updates. Recorded local test evidence for this closure is `38 passed`, `43 passed`, and `141 passed`. This does not approve live gBiz ingest or production deploy; the NO-GO gates above still apply.

## Source Receipts Quality Gate

`company_public_audit_pack` now treats source receipts as audit workpaper material. Each receipt exposes `source_url`, `source_fetched_at`, `content_hash`, `license`, and `used_in`; missing fields are surfaced as `known_gaps` with `gap_id=source_receipt_missing_fields` and also route to `human_review_required` as `source_receipt_gap:<receipt_id>`.

Source dictionaries that already carry `source_fetched_at`, `content_hash`, or `license` now preserve those fields into the receipt instead of being downgraded to URL-only evidence.

This matters commercially because the paid output is no longer just a generated summary. It becomes a reviewable public-source evidence packet: the user can see what source was used, where it was used, and what still needs human confirmation.

Current source receipt quality status is considered covered by the focused company public artifacts usage + audit-seal suite above; it is still local evidence only and does not imply any live-source refetch or production mutation.

## Secrets SOT

`docs/_internal/SECRETS_REGISTRY.md` is the current secret-name source of truth. It separates:

- required core production boot names, such as `API_KEY_SALT`, `AUDIT_SEAL_SECRET`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET`;
- conditional names, especially `CLOUDFLARE_TURNSTILE_SECRET` for APPI when enabled and `GBIZINFO_API_TOKEN` for live gBiz ingest;
- optional names, such as `JPINTEL_AUDIT_SEAL_KEYS`, `TG_BOT_TOKEN`, and `TG_CHAT_ID`.

The registry and gate intentionally deal in names and conditions only. They must not record secret values.

## 2026-05-06 Hard Gate Addendum

Machine gate failures may be limited to `workflow_targets_git_tracked`,
`dirty_tree`, and `operator_ack`, but that does not clear the operator-review
items in the NO-GO blocker table. Treat the machine gate list and the
operator-review table as separate inputs; deploy remains NO-GO until both are
green.

`PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` is a GitHub Actions secret containing the
ACK body, not a Fly, DB, or API secret value. It must be a YAML/JSON object with
all required ACK fields set to boolean `true`; string `"true"` is not accepted.
The workflow writes it only under `$RUNNER_TEMP`. Do not commit an ACK file to
the repository.

With `AUTONOMATH_BOOT_MIGRATION_MODE=manifest` and the default empty
`scripts/migrations/autonomath_boot_manifest.txt`, production boot auto-applies
no autonomath migrations. Any non-empty manifest entry or
`AUTONOMATH_BOOT_MIGRATION_MODE=discover` is an explicit deploy-packet mutation
and is forbidden without operator approval.

Paid artifact responses are fail-closed on audit-seal persistence failure:
metered artifact endpoints return `503 audit_seal_persist_failed`, do not
deliver the artifact body, and do not write `usage_events`. Operators must fix
`audit_seals` persistence or seal-key configuration; do not bypass this into
`_seal_unavailable` for paid artifacts. Free/trial artifact paths may return
`_seal_unavailable`, but those responses are not metered paid artifacts.

R2 bootstrap behavior is state-specific: missing DB background bootstrap is
allowed, but an existing DB with a SHA mismatch is fail-closed/foreground. Do
not treat an existing DB SHA mismatch as a background self-heal path.

Latest observed `release_readiness.py --warn-only` status is `9 pass / 1 fail /
10`, failing only `workflow_targets_git_tracked`. The current missing
tracked targets are workflow-referenced local script/test files; commit those
files with the workflow changes or remove them from `RUFF_TARGETS` /
`PYTEST_TARGETS` before deploy.

## Final GO Gate Command

ACK helper: see `docs/_internal/operator_deploy_ack_addendum_2026-05-06.md`.
When `--allow-dirty` is used, keep the final ACK file outside the repo (for
example `/tmp/jpcite_operator_deploy_ack_2026-05-06.json`) unless it is already
tracked and clean; the gate hashes dirty file contents and a repo-local mutable
ACK can invalidate its own `content_sha256`.

Run this as the last local check before any production mutation:

```bash
uv run python scripts/ops/production_deploy_go_gate.py \
  --operator-ack /tmp/jpcite_operator_deploy_ack_YYYY-MM-DD.json
```

The ack file must explicitly confirm:

- `fly_app_confirmed`
- `fly_secrets_names_confirmed`
- `appi_disabled_or_turnstile_secret_confirmed`
- `target_db_packet_reviewed`
- `rollback_reconciliation_packet_ready`
- `live_gbiz_ingest_disabled_or_approved`
- `dirty_lanes_reviewed`
- `pre_deploy_verify_clean`

If `--allow-dirty` is used, the ack must also include `dirty_tree_fingerprint` matching the final gate output: `current_head`, `dirty_entries`, `status_counts`, `lane_counts`, `path_sha256`, `content_sha256`, `content_hash_skipped_large_files`, and `critical_dirty_lanes_reviewed`. Do not copy `content_sha256` from this packet after editing it; rerun the gate and copy the machine output.

## Target DB Boundaries

| migration | target DB | runner | deployment rule |
| --- | --- | --- | --- |
| `wave24_164_gbiz_v2_mirror_tables.sql` | `autonomath` | `entrypoint.sh` autonomath self-heal | only after gBiz secret/app gate is resolved |
| `wave24_166_credit_pack_reservation.sql` | `jpintel` | `scripts/migrate.py` or explicit operator packet | apply only with rollback/reconciliation packet |
| rollback files | operator-only | never automatic | review destructive effects before use |
| generated surfaces | DA-01 eligibility predicate MCP import would move 139 -> 140 tools and requires a broad distribution packet | keep DA-01 paused until all manifests, docs, DXT, site JSON, and counts are regenerated together |

## Allowed Next Actions

- Fix app-name references in docs/runbooks without touching secrets.
- Split migration inventory by target DB and identify exactly which files belong to the next deploy packet.
- Add public-response gBiz attribution integration on top of the now-correct helper/envelope preservation.
- Commit or remove the workflow-referenced untracked lint/test targets so `workflow_targets_git_tracked` can turn green.
- Keep gBiz live ingest disabled until the app, secret, and migration gates are explicitly approved.
- Prepare `client_company_folder_v1` as a thin product alias for existing `company_folder_brief`, after deploy gates remain green.

## Forbidden Until GO

- `fly deploy`
- local `fly deploy` from the current Docker/build context
- `fly secrets set` or `fly secrets unset`
- live gBiz API ingest against production
- production `sqlite3` migration apply
- `scripts/migrations` auto-apply at production boot
- bulk cleanup of generated/site/sdk/offline-inbox files
