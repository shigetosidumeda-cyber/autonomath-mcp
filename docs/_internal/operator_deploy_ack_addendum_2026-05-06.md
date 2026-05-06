# Operator Deploy ACK Addendum 2026-05-06

Status: deploy-prep addendum only. No production deploy, secret mutation,
live gBiz ingest, production migration apply, workflow change, site rebuild, or
SDK/package change is authorized by this document.

Purpose: make the missing `operator_ack` blocker in
`PRODUCTION_DEPLOY_PACKET_2026-05-06.md` easy to resolve without weakening the
GO gate. The gate remains authoritative.

## Current Gate Meaning

`scripts/ops/production_deploy_go_gate.py` is read-only. It does not call the
network, read secret values, or apply migrations. The current NO-GO condition
is:

- dirty tree is present; and
- operator ACK is not provided or unreadable.

The ACK is not a blanket deploy approval. It is only an operator statement that
the required production-risk confirmations were reviewed. Final deploy remains
blocked unless the final gate output has `"ok": true`.

Use `uv run python`, not the system `python3`; the local system Python may be
3.9 and cannot import `datetime.UTC`.

## ACK File Placement

For the dirty-tree path, do not create or edit the final ACK file inside the
repo after copying the dirty fingerprint. The gate hashes dirty file contents;
a repo-local untracked or modified ACK file can invalidate its own
`content_sha256`.

Use an out-of-repo final ACK path such as:

```bash
/tmp/jpcite_operator_deploy_ack_2026-05-06.json
```

A repo-local path under `docs/_internal/` is acceptable only if it is already
tracked and clean before the final fingerprint is copied, or if the tree is
clean and the ACK file itself is part of the reviewed release commit.

## Required Confirmation Checklist

Set each ACK field to JSON boolean `true` only after the corresponding review
is complete. The gate does not accept `"true"` strings.

| ACK field | what must be true before setting it |
| --- | --- |
| `fly_app_confirmed` | Fly command targets and `fly.toml` use `autonomath-api`; legacy aliases are not present in command contexts. |
| `fly_secrets_names_confirmed` | Required and conditional secret names are documented in `SECRETS_REGISTRY.md`; only names were checked, not values. |
| `appi_disabled_or_turnstile_secret_confirmed` | APPI intake is intentionally disabled with `AUTONOMATH_APPI_ENABLED=0` / `false`, or `CLOUDFLARE_TURNSTILE_SECRET` is present by name on Fly. |
| `target_db_packet_reviewed` | Deploy packet migration targets are reviewed; `wave24_164_gbiz_v2_mirror_tables.sql` is `autonomath`, `wave24_166_credit_pack_reservation.sql` is `jpintel`, and no unreviewed bulk migration apply is allowed. |
| `rollback_reconciliation_packet_ready` | The destructive credit-pack rollback risk is understood; reconciliation SQL and Stripe balance-transaction review are ready before any rollback. |
| `live_gbiz_ingest_disabled_or_approved` | Live gBiz ingest is disabled, or explicitly approved with `GBIZINFO_API_TOKEN` placed intentionally on the Fly machine. |
| `dirty_lanes_reviewed` | The worktree is clean, or the dirty-lane packet has been reviewed by lane and critical dirty lanes are covered in `critical_dirty_lanes_reviewed`. |
| `pre_deploy_verify_clean` | `uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db` completed with `"ok": true`; `--warn-only` output may be used for inspection, not as a pass by itself. |

## Clean-Tree ACK

Create the ACK outside the repo:

```json
{
  "fly_app_confirmed": true,
  "fly_secrets_names_confirmed": true,
  "appi_disabled_or_turnstile_secret_confirmed": true,
  "target_db_packet_reviewed": true,
  "rollback_reconciliation_packet_ready": true,
  "live_gbiz_ingest_disabled_or_approved": true,
  "dirty_lanes_reviewed": true,
  "pre_deploy_verify_clean": true
}
```

Then run the final gate without `--warn-only`:

```bash
uv run python scripts/ops/production_deploy_go_gate.py \
  --operator-ack /tmp/jpcite_operator_deploy_ack_2026-05-06.json
```

## Reviewed Dirty-Tree ACK

Use this path only when deploy must proceed from a reviewed dirty tree.

1. Run the local pre-deploy verifier and require `"ok": true`:

```bash
uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db
```

2. Capture the current gate evidence after all repo edits are done:

```bash
uv run python scripts/ops/production_deploy_go_gate.py --warn-only \
  > /tmp/jpcite_go_gate_before_ack_2026-05-06.json
```

3. Extract the dirty fingerprint:

```bash
jq '.checks[] | select(.name == "dirty_tree").evidence | {
  current_head,
  dirty_entries,
  status_counts,
  lane_counts,
  path_sha256,
  content_sha256,
  content_hash_skipped_large_files,
  critical_lanes_present
}' /tmp/jpcite_go_gate_before_ack_2026-05-06.json
```

4. Create `/tmp/jpcite_operator_deploy_ack_2026-05-06.json` with the required
   fields plus `dirty_tree_fingerprint`. Copy the extracted values exactly,
   then set `critical_dirty_lanes_reviewed` to the critical lanes that were
   actually reviewed. The JSON below is a shape example; replace every
   `copy_from_gate_output` and placeholder count before using it:

```json
{
  "fly_app_confirmed": true,
  "fly_secrets_names_confirmed": true,
  "appi_disabled_or_turnstile_secret_confirmed": true,
  "target_db_packet_reviewed": true,
  "rollback_reconciliation_packet_ready": true,
  "live_gbiz_ingest_disabled_or_approved": true,
  "dirty_lanes_reviewed": true,
  "pre_deploy_verify_clean": true,
  "dirty_tree_fingerprint": {
    "current_head": "copy_from_gate_output",
    "dirty_entries": 0,
    "status_counts": {},
    "lane_counts": {},
    "path_sha256": "copy_from_gate_output",
    "content_sha256": "copy_from_gate_output",
    "content_hash_skipped_large_files": [],
    "critical_dirty_lanes_reviewed": [
      "billing_auth_security",
      "cron_etl_ops",
      "migrations",
      "root_release_files",
      "runtime_code",
      "workflows"
    ]
  }
}
```

5. Run the final gate without `--warn-only`:

```bash
uv run python scripts/ops/production_deploy_go_gate.py \
  --allow-dirty \
  --operator-ack /tmp/jpcite_operator_deploy_ack_2026-05-06.json
```

If any repo file changes after step 2, rerun step 2 and refresh the fingerprint
before the final gate.

## Do Not ACK These States

- `pre_deploy_verify.py` reports `"ok": false`.
- `content_hash_skipped_large_files` is non-empty; the gate blocks this even
  with `--allow-dirty`.
- `dirty_fingerprint_mismatch:*` appears in final gate output.
- `dirty_critical_lanes_not_reviewed:*` appears in final gate output.
- Any required ACK field would be set by assumption rather than observed
  evidence.

## Source Documents

- `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md`
- `docs/_internal/CURRENT_SOT_2026-05-06.md`
- `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md`
- `docs/_internal/SECRETS_REGISTRY.md`
- `docs/_internal/waf_deploy_gate_prepare_2026-05-06.md`
- `docs/_internal/release_readiness_2026-05-06.md`
