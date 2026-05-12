# Wave 49 tick#2 — provenance backfill ETL `fact_id` → `id` 1-axis fix

## Context

The Wave 49 tick#3 PR landed the daily cron workflow for
`scripts/etl/provenance_backfill_6M_facts_v2.py`. The workflow LIVE-fired
the script via `--dry-run` against the prod 9.7 GB `autonomath.db` and
the cron actually executed, but the **non-dry-run** path crashed on the
very first batch SELECT with::

    sqlite3.OperationalError: no such column: fact_id

Root cause: the walker cursor SELECT and 3 derive-helpers
referenced `am_entity_facts.fact_id` — but the canonical prod schema PK
column is `am_entity_facts.id` (confirmed by migration 049 doc string,
migration 265 inline comment "pointer to am_entity_facts.id", migration
069 view definition "fact_id — am_entity_facts.id", and the canonical
`CREATE TABLE` in `tests/test_evidence_packet.py:71-82`). prod write was
0 (dry-run gate held) so no rows corrupted, but Dim O backfill made 0
progress beyond row 0.

## 1-axis fix (6 SQL replacements, single conceptual edit)

Only the column **NAME** `am_entity_facts.fact_id` was changed to `id`
in 5 SQL statements (6 total token replacements — `WHERE`/`ORDER BY`/
`SELECT` clauses on the same column). The Python variable names
`fact_id` and the `am_fact_metadata.fact_id` / `am_fact_attestation_log.fact_id`
column references were **kept** (those columns are correctly named per
migration 275).

| File | Line | Before | After |
| --- | --- | --- | --- |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | 143 | `SELECT source_id FROM am_entity_facts WHERE fact_id = ? LIMIT 1` | `SELECT source_id FROM am_entity_facts WHERE id = ? LIMIT 1` |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | 163 | `SELECT confidence FROM am_entity_facts WHERE fact_id = ? LIMIT 1` | `SELECT confidence FROM am_entity_facts WHERE id = ? LIMIT 1` |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | 183 | `SELECT created_at FROM am_entity_facts WHERE fact_id = ? LIMIT 1` | `SELECT created_at FROM am_entity_facts WHERE id = ? LIMIT 1` |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | 295-296 | `SELECT fact_id ... ORDER BY fact_id ASC` | `SELECT id ... ORDER BY id ASC` |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | 301-302 | `SELECT fact_id ... WHERE fact_id > ? ORDER BY fact_id ASC` | `SELECT id ... WHERE id > ? ORDER BY id ASC` |

## Companion test stub correction

`tests/test_dim_o_provenance_attach.py:55-60` declared the stub
`am_entity_facts` table with `fact_id TEXT PRIMARY KEY` — i.e. it
was testing against a non-canonical schema that masked the prod bug.
The stub is now renamed to `id TEXT PRIMARY KEY` (TEXT kept for
seed ergonomics — prod is INTEGER PK AUTOINCREMENT, but the walker
SELECTs by column NAME and passes the value through verbatim, so type
is irrelevant for the code path under test).

## New regression test

`tests/test_provenance_etl_id_schema.py` (~210 LOC) — 5 tests:

1. `test_am_entity_facts_pk_is_id_not_fact_id` — schema-shape lock
2. `test_am_fact_metadata_has_fact_id_column` — am_fact_metadata mig 275 column kept
3. `test_etl_script_uses_id_for_am_entity_facts` — forbidden-pattern source-grep
4. `test_walker_dry_run_does_not_write` — --dry-run gate verify
5. `test_walker_non_dry_run_writes_with_placeholder_sig` — idempotency + placeholder sig

## grep result

Verified with `grep -n 'fact_id\|am_entity_facts'`::

    143:            "SELECT source_id FROM am_entity_facts WHERE id = ? LIMIT 1",
    163:            "SELECT confidence FROM am_entity_facts WHERE id = ? LIMIT 1",
    183:            "SELECT created_at FROM am_entity_facts WHERE id = ? LIMIT 1",
    295:                "SELECT id FROM am_entity_facts "
    301:                "SELECT id FROM am_entity_facts "

`am_entity_facts.fact_id` references: **0** (was 6 before fix).
`am_fact_metadata.fact_id` references: preserved as-is (canonical
column name per migration 275).

## Test verdict

    tests/test_dim_o_provenance_attach.py        — 18 passed (was 1 fail)
    tests/test_provenance_etl_id_schema.py       —  5 passed (new)
    tests/test_provenance_backfill_workflow.py   —  3 passed
    Total: 26 passed, 0 failed
    ruff: All checks passed

## Hard constraints honored

- No `PRAGMA quick_check` (memory: `feedback_no_quick_check_on_huge_sqlite`).
- No LLM SDK import (memory: `feedback_no_operator_llm_api`).
- No destructive `rm`/`mv` (memory: `feedback_destruction_free_organization`).
- Lane: dedicated worktree `/tmp/jpcite-w49-prov-etl-fix`, branch
  `feat/jpcite_2026_05_12_wave49_prov_etl_fact_id_fix` (memory:
  `feedback_dual_cli_lane_atomic`).

## Out of scope (separate ticks)

- `_derive_source_doc` line 150 references `am_source.url` (column is
  `source_url`) and `WHERE source_id = ?` (am_source PK is `id`) — also
  broken but distinct: a separate adjacent-schema-drift bug. Filed as
  follow-up tick. The current PR is laser-focused on the `fact_id`→`id`
  blocker; fixing `am_source` references is additive and orthogonal.
