-- target_db: autonomath
-- migration: 268_state_checkpoint
-- generated_at: 2026-05-12
-- author: Wave 43.3.6 — AX Resilience cell 6 (boundary state checkpoint)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- AX Resilience layer cell 6 persists boundary-state snapshots so that
-- long-running multi-step workflows (e.g. cohort fan-out, NTA bulk
-- ingest, compose_audit_workpaper) survive Fly machine swaps (~25s
-- p99) and SIGTERM mid-stream without re-doing completed steps.
--
-- Pattern
-- -------
-- A workflow declares a stable `workflow_id` (e.g. ULID) and writes a
-- checkpoint at each *idempotent boundary*. On resume, the runner
-- reads the latest checkpoint for the workflow_id and skips work whose
-- `step_index` is <= the checkpointed value. The schema deliberately
-- does NOT carry an idempotency token here — that surface lives in
-- the bg_task_queue dedup_key column (mig 060) and the replay-token
-- module (Wave 43.3.5).
--
-- Why a side table (not a column on bg_task_queue)
-- ------------------------------------------------
-- A workflow has N checkpoints; bg_task_queue has 1 row per work
-- unit. Storing checkpoints inline would either overwrite each one
-- (losing partial-progress audit trail) or require an array column
-- that SQLite cannot index. The side table keeps each step row
-- queryable for forensics.
--
-- ¥3/req billing posture
-- ----------------------
-- Checkpoints are internal — no customer-facing read path. The cron
-- entry uses /v1/admin/* unmetered surfaces if exposed.
--
-- Retention
-- ---------
-- 30-day rolling window kept by `scripts/cron/dlq_drain.py` cleanup
-- sweep (cell 5 piggybacks on the same hourly cron). Completed
-- workflows older than 30d are eligible for purge; failed (status
-- IN ('aborted','expired')) workflows are retained for 90d for
-- post-mortem evidence.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_state_checkpoint (
    checkpoint_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id         TEXT NOT NULL,                      -- ULID / UUID assigned by caller
    workflow_kind       TEXT NOT NULL,                      -- e.g. 'cohort_fanout', 'nta_bulk_ingest'
    step_index          INTEGER NOT NULL                    -- monotonically increasing
                        CHECK (step_index >= 0),
    step_name           TEXT NOT NULL,                      -- human-readable step label
    state_blob          TEXT NOT NULL DEFAULT '{}',         -- JSON payload (caller-defined)
    status              TEXT NOT NULL DEFAULT 'committed'   -- committed / aborted / expired
                        CHECK (status IN ('committed','aborted','expired')),
    committed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at          TEXT,                               -- optional TTL boundary
    notes               TEXT,
    UNIQUE (workflow_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_state_checkpoint_workflow
    ON am_state_checkpoint(workflow_id, step_index DESC);

CREATE INDEX IF NOT EXISTS idx_state_checkpoint_kind_committed
    ON am_state_checkpoint(workflow_kind, committed_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_checkpoint_status_expires
    ON am_state_checkpoint(status, expires_at);

-- Helper view: latest checkpoint per workflow (used by resume logic).
DROP VIEW IF EXISTS v_state_checkpoint_latest;
CREATE VIEW v_state_checkpoint_latest AS
SELECT
    workflow_id,
    workflow_kind,
    MAX(step_index)     AS latest_step_index,
    COUNT(*)            AS total_steps,
    MIN(committed_at)   AS started_at,
    MAX(committed_at)   AS last_step_at
FROM am_state_checkpoint
WHERE status = 'committed'
GROUP BY workflow_id, workflow_kind;

COMMIT;
