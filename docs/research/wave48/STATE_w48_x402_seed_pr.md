# Wave 48 tick#2 — STATE: x402 endpoint prod seed (entrypoint runner)

- **Date**: 2026-05-12
- **Branch**: `feat/jpcite_2026_05_12_wave48_x402_prod_seed`
- **Base SHA**: `81eacab9334523edee6b59d534a432e37824bc97` (main)
- **PR**: filled at open time
- **Lane**: `/tmp/jpcite-w48-x402-seed-entrypoint.lane` (mkdir-exclusive)

## Symptom (prod)

- `am_x402_endpoint_config` (created by migration 282, Wave 47) is empty on the
  Fly volume. As a result, `/v1/audit_workpaper`, `/v1/cases`, `/v1/programs`,
  `/v1/search`, `/v1/semantic_search` return **HTTP 404 (no x402 config row)**
  instead of the contracted **HTTP 402 (Payment Required)**.
- Wave 47 tick#2 had only run the seeder against a local DB during dev, never
  inside the prod container.

## Root cause

`scripts/etl/seed_x402_endpoints.py` exists and is idempotent, but nothing in
the container boot path invokes it. Migrations create the table; the seeder
is the ONLY mechanism that populates the 5 canonical rows.

## Fix

`entrypoint.sh` §4.x (new): post schema_guard, pre `exec "$@"`, invoke
`python /app/scripts/etl/seed_x402_endpoints.py --db "$DB_PATH"` when both
the seeder file and an autonomath DB are present. Idempotent (no `--force`).
Failure is logged via `err` but does NOT exit 1 — boot stays alive.

Memory invariants honored:
- `feedback_no_quick_check_on_huge_sqlite`: zero PRAGMA probes added.
  Seeder is O(5 SELECT + ≤5 INSERT) and well under Fly 60s grace.
- `feedback_destruction_free_organization`: additive only, no `rm`/`mv`,
  no `--force`. Operator-set repricing is preserved across boots.
- `feedback_dual_cli_lane_atomic`: lane claimed via `mkdir`.

## Diff

```
 entrypoint.sh                           | 26 ++++++++++++++++++++++++++
 tests/test_entrypoint_vec0_boot_gate.py |  8 ++++++++
 tests/test_x402_prod_seed_entrypoint.py | NEW ~180 LOC
 docs/research/wave48/STATE_w48_x402_seed_pr.md | NEW
```

- `entrypoint.sh` diff = **26 LOC inserted** (§4.x block before §5 exec).
- `tests/test_entrypoint_vec0_boot_gate.py` diff = **8 LOC** (replacement-order
  fix: hoist the seed path rewrite ABOVE the `/seed` substitution because
  `/seed` substring exists inside `/seed_x402_endpoints.py` and would
  otherwise corrupt the test-rewritten path).
- `tests/test_x402_prod_seed_entrypoint.py` = **NEW, ~180 LOC, 6 tests**.

## Test verdict

```
$ bash -n entrypoint.sh
OK

$ python -m pytest tests/test_x402_prod_seed_entrypoint.py tests/test_entrypoint_vec0_boot_gate.py \
    --deselect "...::test_autonomath_boot_manifest_exists_and_is_empty_allowlist_by_default" -q
20 passed, 1 deselected in 2.99s
```

The 1 deselected test (`test_autonomath_boot_manifest_exists_and_is_empty_allowlist_by_default`)
is a **pre-existing failure on main** (manifest now carries 43 entries from
Wave 43-47, asserts empty) and unrelated to this PR. Confirmed by re-running
on `main` HEAD: same failure, same line.

Live entrypoint exec sanity (`AUTONOMATH_ENABLED=true`, tmp paths, seed
script absent dev-build path):
```
[entrypoint] [W48.x402] seed_x402_endpoints.py absent — skipping x402 prod seed (dev build?)
[entrypoint] starting server: true
rc=0
```

## New test file structure (6 tests, ~180 LOC)

1. `test_entrypoint_invokes_seed_x402_endpoints_after_schema_guard`
   — order: schema_guard < seed invocation < exec
2. `test_entrypoint_seed_block_is_best_effort_not_boot_fatal`
   — block contains no `exit 1`, has `|| err ...` chain
3. `test_entrypoint_seed_block_skips_when_db_absent`
   — guards on `[ -s "$DB_PATH" ]`
4. `test_entrypoint_seed_block_omits_pragma_quick_check`
   — zero PRAGMA in EXECUTED shell (comment-stripped before scan)
5. `test_entrypoint_seed_block_does_not_pass_force_flag`
   — no `--force` arg (operator repricing preserved)
6. `test_seed_script_idempotent_against_fresh_schema`
   — live exec the seeder twice against an inline schema, assert
     2nd run is `{noop: 5}`

## Post-merge expected impact

- Fly redeploy after merge: §4.x kicks in on next boot, seeds 5 rows.
- `/v1/{audit_workpaper,cases,programs,search,semantic_search}` flip from
  **404 → 402 Payment Required** per x402 contract.
- Subsequent boots: idempotent noop.

## Out of scope (deferred)

- Live x402 settlement flow (Coinbase Base L2 callback) — separate tick.
- CF Pages `functions/x402_handler.ts` parity verify — already deployed
  per Wave 47 tick#2 STATE.
- Per-endpoint repricing telemetry — Dim V monthly snapshot already in place.
