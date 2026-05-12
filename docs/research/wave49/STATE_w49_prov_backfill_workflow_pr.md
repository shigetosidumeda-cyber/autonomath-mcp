# Wave 49 — Dim O provenance backfill v2 daily cron wiring

- **date**: 2026-05-12 (Wave 49, tick#3 — eternal loop 1-min cadence)
- **branch**: `feat/jpcite_2026_05_12_wave49_provenance_backfill_workflow`
- **PR**: [#197](https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/197)
- **base HEAD before**: `74ec7b8f2` (PR #194 mig 288 boot manifest hot-fix — last main commit)
- **lane**: `/tmp/jpcite-w49-prov-cron.lane/` (atomic mkdir claim)
- **worktree**: `/tmp/jpcite-w49-prov-cron/`
- **memory anchors**:
  - `feedback_dual_cli_lane_atomic` — mkdir lane + ledger
  - `feedback_destruction_free_organization` — additive only, no rm/mv
  - `feedback_no_quick_check_on_huge_sqlite` — workflow does NOT inject
    PRAGMA quick_check on the 9.7 GB autonomath.db; v2 ETL is indexed
    cursor pagination only.
  - `feedback_no_operator_llm_api` — workflow only references
    `FLY_API_TOKEN` + `github.token`; zero LLM-vendor secret.

## Goal

Close the **cron MISSING** axis of the Wave 49 dim 19 dim O audit. The
v2 backfill ETL (`scripts/etl/provenance_backfill_6M_facts_v2.py`)
landed in Wave 49 Phase 1 covering the residual `am_entity_facts` rows
whose `am_fact_metadata` row is missing or has `source_doc IS NULL`,
but production cron wiring was never shipped — manual replay only.

This PR lands `.github/workflows/provenance-backfill-daily.yml`
(50 LOC YAML) which runs the v2 ETL daily 03:45 UTC (12:45 JST) on
the Fly machine via `flyctl ssh console -a autonomath-api`, with a
1,000-row-per-day batch (--max-rows 1000, --chunk-size 100). Across
~365 days the residual 6.12M-row EAV converges to a fully-explained
state without ever touching `am_fact_signature` (Wave 47 substrate
preserved) and without ever issuing a PRAGMA quick_check (9.7 GB DB
footgun avoided).

## Schedule rationale

03:45 UTC daily (= 12:45 JST):
- 30 min after `anonymized-cohort-audit-daily` (03:15 UTC, Dim N k>=5
  cohort rebuild). Keeps the daily fact-layer cluster in a clean ladder.
- Well clear of `refresh-fact-signatures-weekly` (Sunday 02:00 UTC,
  Dim F Ed25519 re-sign).
- Within the daily-cron window so failure issues land before JST
  business hours.

## Idempotency

The v2 ETL targets only `fact_id` rows where the metadata is missing
OR `source_doc IS NULL`. Re-running on a converged corpus is a no-op
— the daily cron is safe to fire on an already-100%-covered DB.

## Files (this PR)

| Path | LOC | Kind |
|---|---|---|
| `.github/workflows/provenance-backfill-daily.yml` | ~125 | NEW workflow |
| `tests/test_provenance_backfill_workflow.py` | ~135 | NEW test (8 cases) |
| `docs/research/wave49/STATE_w49_prov_backfill_workflow_pr.md` | this | NEW SOT |

## Test coverage (8 cases, all green locally)

1. `test_workflow_file_exists` — YAML present at canonical path.
2. `test_workflow_yaml_parses` — PyYAML safe_load round-trip.
3. `test_workflow_schedule_is_daily_0345_utc` — `"45 3 * * *"` cron.
4. `test_workflow_dispatch_inputs_present` — max_rows / chunk_size /
   dry_run override inputs.
5. `test_workflow_invokes_v2_etl_with_daily_1000` — Fly SSH calls the
   v2 ETL with 1,000-row / 100-row chunk defaults.
6. `test_workflow_concurrency_guard` — group + cancel-in-progress: false
   (parallel runs would lose am_fact_metadata UPSERTs).
7. `test_workflow_no_llm_secret_reference` — no LLM-vendor secret
   (Anthropic/OpenAI/Gemini/Google).
8. `test_workflow_does_not_invoke_quick_check` — no PRAGMA quick_check
   invocation (docstring mentions OK; executable forms banned).

## Verify before merge

```bash
cd /tmp/jpcite-w49-prov-cron
/Users/shigetoumeda/jpcite/.venv/bin/python -m pytest \
  tests/test_provenance_backfill_workflow.py \
  tests/test_no_llm_in_production.py \
  tests/test_dimension_f_fact_signature_v2.py -v
# Expected: 8 + 5 + 9 = 22 passed
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/provenance-backfill-daily.yml'))"
# Expected: silent success (parse OK)
```

## Out of scope (deliberate)

- No change to `scripts/etl/provenance_backfill_6M_facts_v2.py` (it
  already shipped in Wave 49 Phase 1; this PR only wires its cron).
- No change to `am_fact_signature` substrate (Wave 47 / migration 262).
- No new secrets — `FLY_API_TOKEN` is already mirrored
  (`feedback_secret_store_separation` already-satisfied).
- No SDK republish (Option B post-launch path unchanged).
- No deploy.yml edits (Wave 47 4-fix pattern unchanged).

## After merge — operational footprint

- 1 daily cron run, expected wall time < 5 min (1,000 rows x ~100 row
  chunk = 10 commits, each ~30 s on a 9.7 GB DB with indexed cursor).
- ~365 days to converge the 6.12 M residual EAV (back-of-envelope at
  1k/day; real cadence likely sub-100k since most rows already have
  a metadata row from the v1 walker).
- If converged early, the ETL becomes a no-op (idempotency guarantee)
  and the daily cron continues to be safe.
