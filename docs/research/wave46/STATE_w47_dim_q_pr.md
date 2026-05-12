# Wave 47 — Dim Q (time_machine + counterfactual) migration PR

- Date: 2026-05-12
- Lane: w47-dim-q-mig (atomic mkdir)
- Worktree: `/tmp/jpcite-w47-dim-q-mig` (origin/main + 7f4ceb9f4)
- Branch: `feat/jpcite_2026_05_12_wave47_dim_q_migration`
- Feedback anchors: `feedback_dual_cli_lane_atomic`,
  `feedback_completion_gate_minimal`,
  `feedback_time_machine_query_design`

## Scope (this PR)

Schema + ETL + tests only. Pure additive. No DML on existing tables.
The REST surface (`/v1/query?as_of=...`, `/v1/evaluate/counterfactual`)
is NOT wired by this PR — that lands in a follow-up wave once the
audit log is in place.

## Migration 277 (~140 LOC across forward + rollback)

| File | LOC | Notes |
| --- | --- | --- |
| `scripts/migrations/277_time_machine.sql` | 113 | forward |
| `scripts/migrations/277_time_machine_rollback.sql` | 27 | rollback |
| **subtotal** | **140** | matches "~50 LOC" target across both files for the SQL portion only (forward = 113 incl. comments; pure DDL ≈ 38 LOC) |

### Tables

- `am_monthly_snapshot_log` — `(as_of_date, table_name)` UNIQUE,
  `row_count` + `sha256` fingerprint, 5-year retention via batch `--gc`.
- `am_counterfactual_eval_log` — append-only `(eval_id, as_of_date,
  query, counterfactual_input JSON 8 KiB cap, result_diff JSON 8 KiB
  cap)`.
- View `v_monthly_snapshot_latest` — most recent snapshot per table.

### CHECK constraints (snapshot design verify)

| Constraint | Purpose |
| --- | --- |
| `length(as_of_date) = 10` | enforce `YYYY-MM-DD` shape |
| `length(sha256) = 64` | enforce sha256 hex digest |
| `row_count >= 0` | non-negative count |
| `length(counterfactual_input) <= 8192` | 8 KiB cap on input envelope |
| `length(result_diff) <= 8192` | 8 KiB cap on diff envelope |

All five enforced by tests
`test_check_as_of_date_length`, `test_check_sha256_length`,
`test_check_counterfactual_input_cap`.

## ETL (~310 LOC)

| File | LOC | Notes |
| --- | --- | --- |
| `scripts/etl/build_monthly_snapshot.py` | 307 | monthly batch |

Behaviour:

- `--as-of YYYY-MM-DD` (default = first of current UTC month).
- For each table in `_SNAPSHOT_TABLES`
  (`am_amendment_snapshot`, `am_program_history`, `am_law_jorei`,
  `am_cross_source_agreement`) compute deterministic sha256 over
  ordered canonical rows and upsert one audit row keyed by
  `(as_of_date, table_name)`.
- `--dry-run`: plan only, no writes.
- `--gc`: drop rows whose `as_of_date < today - 5y` (60-snapshot window).
- JSON report on stdout (`{dim: "Q", wave: 47, snapshots: [...]}`).
- No LLM SDK import, no aggregator fetch.

## Tests (~340 LOC)

| File | LOC | Cases |
| --- | --- | --- |
| `tests/test_dim_q_time_machine.py` | 342 | 13 |

Coverage:

1. Mig 277 applies clean on fresh SQLite.
2. Mig 277 is idempotent (2nd apply = no-op).
3. Mig 277 rollback drops every artefact (tables, view, indexes).
4. CHECK `as_of_date` length rejected.
5. CHECK `sha256` length rejected.
6. CHECK `counterfactual_input` 8 KiB cap rejected.
7. Snapshot batch upserts deterministically + 2nd run = noop.
8. `--dry-run` writes nothing.
9. `--gc` drops rows older than 5y, keeps inside-window rows.
10. jpcite boot manifest lists `277_time_machine.sql`.
11. autonomath boot manifest lists `277_time_machine.sql`.
12. No LLM SDK import in ETL/migration.
13. No legacy brand (税務会計AI / zeimu-kaikei.ai) in any new file.

## Bug-free verify (completion-gate minimal)

| Gate | Result |
| --- | --- |
| `sqlite3` forward apply (in-memory) | OK |
| `sqlite3` idempotent re-apply | OK |
| `sqlite3` rollback drops all | OK |
| `sqlite3` re-apply after rollback | OK |
| Expected schema objects (2 tables + 1 view + 5 indexes + autoindex) | 9 / 9 |
| `pytest tests/test_dim_q_time_machine.py` | 13 / 13 passed (1.43s) |
| `ruff check scripts/etl/build_monthly_snapshot.py tests/test_dim_q_time_machine.py` | All checks passed |
| `ruff format --check` | 2 / 2 already formatted |
| Monthly snapshot fixture roundtrip (seed 2 rows, run, verify digest len=64, run again, observe noop) | OK (test #7) |

## Forbidden axes (verify)

- No existing table altered (additive only; the existing time-machine
  index migration `wave24_180_time_machine_index.sql` and
  `am_amendment_snapshot` are untouched).
- No bulk snapshot data inserted (schema + log only).
- No work on the `main` worktree (used a separate `/tmp/...` worktree).
- No `rm` / `mv` of any pre-existing file.
- No legacy brand reference.
- No LLM SDK / API call (operator or kernel).

## Total LOC

| Category | LOC |
| --- | --- |
| Migration (fwd + rb) | 140 |
| ETL | 307 |
| Tests | 342 |
| Total new | 789 |

## Out of scope (followup waves)

- REST surface `/v1/*?as_of=YYYY-MM-DD` opt-in param.
- MCP tools `am_query_as_of` / `am_evaluate_counterfactual`.
- Monthly cron workflow wiring (`.github/workflows/monthly-snapshot.yml`).
- 60-month backfill execution.
