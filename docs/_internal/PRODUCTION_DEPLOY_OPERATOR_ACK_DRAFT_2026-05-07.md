# Production Deploy Operator ACK Draft 2026-05-07

Status: NO-GO draft only.

This document is not a deploy approval and is not a usable final
`operator_ack` file. It records the shape required by
`scripts/ops/production_deploy_go_gate.py` and the current incomplete state so
an operator can complete the final ACK outside the repo after the gates are
green.

No production deploy, secret mutation, live gBiz ingest, production migration
apply, workflow change, site rebuild, package publish, or rollback is
authorized by this draft.

## Gate Input Shape

`production_deploy_go_gate.py` loads `--operator-ack` as YAML or JSON and
requires a top-level object. These fields must be JSON/YAML booleans with value
`true`; strings such as `"true"` do not pass.

Required `operator_ack` fields:

- `fly_app_confirmed`
- `fly_secrets_names_confirmed`
- `appi_disabled_or_turnstile_secret_confirmed`
- `target_db_packet_reviewed`
- `rollback_reconciliation_packet_ready`
- `live_gbiz_ingest_disabled_or_approved`
- `dirty_lanes_reviewed`
- `pre_deploy_verify_clean`

When the final gate is run with `--allow-dirty`, the ACK must also include a
matching `dirty_tree_fingerprint` object with these required fields:

- `current_head`
- `dirty_entries`
- `status_counts`
- `lane_counts`
- `path_sha256`
- `content_sha256`
- `content_hash_skipped_large_files`

The dirty fingerprint may also include `critical_dirty_lanes_reviewed`; the
gate compares it against the current critical dirty lanes and fails if any
critical lane is not reviewed.

## Current Observed State

Latest local read-only observations on 2026-05-07 JST:

- `uv run python scripts/ops/production_deploy_go_gate.py --warn-only`: NO-GO,
  `3 pass / 2 fail / 5`.
- GO gate failures: `dirty_tree_present:903` and
  `operator_ack:not_provided_or_unreadable`.
- Dirty critical lanes present: `billing_auth_security`, `cron_etl_ops`,
  `migrations`, `root_release_files`, `runtime_code`, `workflows`.
- Dirty fingerprint skipped large files: `[]`.
- `uv run python scripts/ops/pre_deploy_verify.py --warn-only`: NO-GO,
  `2 pass / 1 fail / 3`.
- Pre-deploy failure: `release_readiness.workflow_targets_git_tracked`.
- `uv run python scripts/ops/release_readiness.py --warn-only`: NO-GO,
  `8 pass / 1 fail / 9`.
- Workflow target failure: workflow-referenced lint/test targets exist locally
  but are not tracked by git.

Machine checks currently passing in the GO gate:

- `fly_app_command_contexts`: PASS; `fly.toml` app is `autonomath-api`.
- `secret_registry_names`: PASS; required and conditional names are documented,
  and no secret values are read by the gate.
- `migration_target_boundaries`: PASS for the gate's expected targets
  (`wave24_164_gbiz_v2_mirror_tables.sql` -> `autonomath`,
  `wave24_166_credit_pack_reservation.sql` -> `jpintel`), with dirty forward
  migration targets detected and still requiring operator packet review before
  any production mutation.

## Draft ACK Values

Use these values as the honest current draft state. Do not paste this block as
the final ACK.

```yaml
fly_app_confirmed: false
fly_secrets_names_confirmed: false
appi_disabled_or_turnstile_secret_confirmed: false
target_db_packet_reviewed: false
rollback_reconciliation_packet_ready: false
live_gbiz_ingest_disabled_or_approved: false
dirty_lanes_reviewed: false
pre_deploy_verify_clean: false
```

Reason for `false` values:

- `fly_app_confirmed`: machine gate currently passes, but the operator has not
  made the final deploy-time confirmation in an out-of-repo ACK.
- `fly_secrets_names_confirmed`: registry names are documented, but production
  Fly secret names have not been final-confirmed by the operator for this
  deploy.
- `appi_disabled_or_turnstile_secret_confirmed`: APPI disabled state or
  `CLOUDFLARE_TURNSTILE_SECRET` presence has not been final-confirmed.
- `target_db_packet_reviewed`: gate target checks pass, but the broad dirty
  migration packet is not approved for production mutation.
- `rollback_reconciliation_packet_ready`: final rollback reconciliation and
  Stripe balance-transaction review readiness are not complete.
- `live_gbiz_ingest_disabled_or_approved`: live gBiz ingest has not been
  approved for production, and `GBIZINFO_API_TOKEN` placement must not be
  assumed.
- `dirty_lanes_reviewed`: dirty tree is broad and mixed; critical lanes are not
  final-reviewed and no matching final dirty fingerprint ACK exists.
- `pre_deploy_verify_clean`: false because `pre_deploy_verify.py --warn-only`
  is currently NO-GO due to `release_readiness.workflow_targets_git_tracked`.

## NO-GO Reasons

- Dirty tree is present: `dirty_tree_present:903`.
- Critical dirty lanes include production-sensitive lanes:
  `billing_auth_security`, `cron_etl_ops`, `migrations`,
  `root_release_files`, `runtime_code`, and `workflows`.
- Workflow target tracking fails:
  `release_readiness.workflow_targets_git_tracked`.
- Aggregate pre-deploy verify fails because release readiness fails.
- Final operator ACK is missing and must not be generated from this draft while
  `pre_deploy_verify_clean` and dirty review are incomplete.

## Operator Completion Checklist

Before setting any final ACK field to `true`, the operator must confirm:

- [ ] Final gate command will use `uv run python`, not system `python3`.
- [ ] Final ACK file will be outside the repo, or tracked and clean before the
  final fingerprint is captured.
- [ ] `fly_app_confirmed`: Fly app command contexts and `fly.toml` target
  `autonomath-api`; no legacy Fly app command contexts remain.
- [ ] `fly_secrets_names_confirmed`: required and conditional production secret
  names are confirmed by name only; no secret values are copied into docs,
  logs, chat, or git.
- [ ] `appi_disabled_or_turnstile_secret_confirmed`: APPI is explicitly
  disabled, or `CLOUDFLARE_TURNSTILE_SECRET` is confirmed present by name.
- [ ] `target_db_packet_reviewed`: exact migration files, target DBs, and
  runners are reviewed; no broad dirty migration auto-apply is allowed.
- [ ] `rollback_reconciliation_packet_ready`: rollback consequences are
  reviewed and reconciliation steps are ready before any rollback.
- [ ] `live_gbiz_ingest_disabled_or_approved`: live gBiz ingest is disabled, or
  explicitly approved with intentional production token placement.
- [ ] `dirty_lanes_reviewed`: tree is clean, or every dirty lane has been
  reviewed and critical dirty lanes are listed in
  `critical_dirty_lanes_reviewed`.
- [ ] `pre_deploy_verify_clean`: final
  `uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db`
  exits clean with `"ok": true`; `--warn-only` is inspection only.
- [ ] If `--allow-dirty` is used, copy `dirty_tree_fingerprint` from the final
  machine gate output after all repo edits are complete.
- [ ] Final
  `uv run python scripts/ops/production_deploy_go_gate.py --operator-ack ...`
  exits clean with `"ok": true` before any production deploy command.

## Final ACK Skeleton For Operator Use

This skeleton is intentionally incomplete and must remain outside the repo when
completed.

```yaml
fly_app_confirmed: true
fly_secrets_names_confirmed: true
appi_disabled_or_turnstile_secret_confirmed: true
target_db_packet_reviewed: true
rollback_reconciliation_packet_ready: true
live_gbiz_ingest_disabled_or_approved: true
dirty_lanes_reviewed: true
pre_deploy_verify_clean: true
# Required only when running production_deploy_go_gate.py with --allow-dirty:
# dirty_tree_fingerprint:
#   current_head: copy_from_final_gate_output
#   dirty_entries: copy_from_final_gate_output
#   status_counts: copy_from_final_gate_output
#   lane_counts: copy_from_final_gate_output
#   path_sha256: copy_from_final_gate_output
#   content_sha256: copy_from_final_gate_output
#   content_hash_skipped_large_files: copy_from_final_gate_output
#   critical_dirty_lanes_reviewed:
#     - billing_auth_security
#     - cron_etl_ops
#     - migrations
#     - root_release_files
#     - runtime_code
#     - workflows
```
