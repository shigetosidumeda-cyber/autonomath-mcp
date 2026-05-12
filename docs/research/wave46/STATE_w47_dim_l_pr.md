# Wave 47 Dim L (session_context) migration + storage PR

date: 2026-05-12
branch: feat/jpcite_2026_05_12_wave47_dim_l_migration
PR#: #155 (https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/155)

## Scope

Land the **optional persistence layer** behind Dim L
(`session_context_design`, PR #144's `/v1/session/{open,step,close}`
REST kernel). PR #144 ships an in-process LRU dict primitive
(`_SESSIONS: OrderedDict`) that is **single-process** and is intentionally
left untouched by this PR. Wave 47 adds two SQL audit tables + a daily
TTL purge so an operator-side daemon can keep a read-replica of open
sessions for audit, billing reconciliation, and restart-recovery
analytics — **without rewiring the live REST handler**.

This is the same shape as Wave 47 Dim K (PR #152): atomic storage
layer + ETL + integration test + dual boot-manifest registration, no
new REST endpoints, no LLM API import.

## Files added

| Path                                                       | LOC | Purpose                                                       |
| ---------------------------------------------------------- | --- | ------------------------------------------------------------- |
| `scripts/migrations/272_session_context.sql`               | 122 | `am_session_context` + `am_session_step_log` + alive view     |
| `scripts/migrations/272_session_context_rollback.sql`      |  27 | rollback (drop indexes/view/tables)                           |
| `scripts/etl/clean_session_context_expired.py`             | 248 | daily 24h TTL purge + 7d forensic window cleanup              |
| `tests/test_dim_l_storage_integration.py`                  | 525 | 16 integration tests (mig + ETL + REST kernel contract)       |
| `scripts/migrations/jpcite_boot_manifest.txt`              |  +9 | append `272_session_context.sql`                              |
| `scripts/migrations/autonomath_boot_manifest.txt`          |  +9 | append `272_session_context.sql`                              |

Migration LOC: **~150** (sql 122 + rollback 27).
Total touched: **~920** (sql 149 + etl 248 + tests 525).

## Schema (mig 272)

- `am_session_context`
  - `session_id TEXT PRIMARY KEY` (= state_token, hex 32)
  - `state_token TEXT NOT NULL` (redundant col for index symmetry)
  - `saved_context TEXT NOT NULL DEFAULT '{}'` — CHECK length ≤ 16 KiB
  - `created_at`, `expires_at` (epoch), `last_step_at`, `closed_at`
  - `status TEXT NOT NULL` CHECK in (`open`,`closed`,`expired`)
  - CHECK `length(state_token) = 32`
  - Indexes: unique on `state_token`; on `expires_at`; on `(status, expires_at)`
- `am_session_step_log`
  - `step_id INTEGER PK AUTOINCREMENT`
  - `session_id TEXT NOT NULL`, `step_index INTEGER` CHECK ≥ 1
  - `request_hash TEXT`, `response_hash TEXT` (sha256 of canonical body)
  - UNIQUE `(session_id, step_index)`
  - Indexes: `(session_id, step_index)`, `request_hash`, `created_at`
- View `v_session_context_alive`: rows with `status='open'` AND `expires_at > now`.

## ETL: `clean_session_context_expired.py`

4-step purge, idempotent, dry-run-able:

1. Mark `status='open'` rows with `expires_at < now` → `status='expired'`.
2. Delete `status IN ('expired','closed')` rows older than 7d
   (`COALESCE(closed_at, expires_at) < now - 7d`).
3. Delete orphan `am_session_step_log` rows (no parent `session_id`).
4. Delete `am_session_step_log` rows older than 7d (`created_at < now - 7d`).

Outputs JSON `{dim:"L", wave:47, dry_run, purge_stats:{expired_marked,
context_deleted, step_log_orphan_deleted, step_log_aged_deleted,
alive_remaining}}`. Designed to be wired into the daily cron in a
follow-up PR (no new workflow added here — strict storage-only PR).

## Verify

- `sqlite3 < 272_session_context.sql` clean (3 objects: 2 tables + 1 view).
- 2nd apply idempotent (every CREATE uses `IF NOT EXISTS`).
- Rollback drops table+view+indexes cleanly (`AFTER_ROLLBACK_TABLES_VIEWS: [sqlite_sequence]`).
- CHECK constraints fire on bad token len (≠32), `step_index < 1`,
  and saved_context > 16 KiB (live python probe confirmed all 3).
- ETL dry-run → JSON plan with 2 expired-marked + 1 context_deleted,
  zero rows written to disk.
- ETL apply → identical counts, real rows updated/removed; alive_remaining=1.
- 16 pytest cases land green via `.venv/bin/python -m pytest
  tests/test_dim_l_storage_integration.py` → **16/16 PASS in 1.66s**.
- REST kernel guard (case 6): `_SESSIONS: OrderedDict` still present,
  no `am_session_context` / `am_session_step_log` reference in the
  REST kernel — Wave 47 is pure additive at the storage layer.
- Both boot manifests register `272_session_context.sql`.
- No `import anthropic|openai|google.generativeai` in any new file
  (Dim L cleanup is fully deterministic per
  `feedback_no_operator_llm_api`).
- No legacy brand (`税務会計AI` / `zeimu-kaikei.ai`) in new files.

## Hard constraints honoured

- PR #144 REST kernel **untouched** (Wave 47 only adds the audit
  storage + TTL purge; the in-process LRU primitive stays
  source-of-truth on each Fly machine, per
  `feedback_session_context_design`).
- No `rm` / `mv` (destructive-free organization rule).
- No main worktree (atomic lane = `/tmp/jpcite-w47-dim-l-mig.lane`).
- No LLM API import in storage / ETL / migration layers.
- Migration number 272 (next free after 271 Dim K).
- Table names align with the disclaimer in `session_context.py`
  (`am_session_context` / `am_session_step_log`).
- jpcite brand discipline: jp brand-first comments, autonomath only
  as the historical SQLite filename (per `feedback_legacy_brand_marker`).
- 24h TTL (`SESSION_TTL_SEC = 86400`) mirrored exactly by the ETL
  purge step #1 (case 6 test asserts the constant matches).
- Step cap 32 (`_MAX_STEPS_PER_SESSION = 32`) verified against the
  schema CHECK `step_index >= 1` and REST-kernel-side cap.
- 16 KiB saved_context bound matched on both sides (REST cap +
  SQL CHECK `length(saved_context) <= 16384`).
