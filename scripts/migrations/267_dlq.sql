-- target_db: autonomath
-- migration: 267_dlq
-- generated_at: 2026-05-12
-- author: Wave 43.3.4 — AX Resilience cell 4 (Dead-Letter Queue + drain log)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- AX Resilience layer cell 4 captures permanently-failed work units from
-- the durable bg_task_queue surface (migration 060) and the customer
-- webhook dispatcher (`scripts/cron/dispatch_webhooks.py`). After the
-- in-line retry budget is exhausted (bg_task_queue max_attempts=5,
-- webhook deliveries=3+5 escalation), the failing unit is moved to
-- `am_dlq` so:
--
--   1. The hot retry path stops billing CPU on a unit that will not
--      recover without operator intervention.
--   2. An operator can replay the unit via `scripts/cron/dlq_drain.py`
--      once the upstream root cause is fixed (e.g. customer endpoint
--      returns 2xx, vendor API restored, Stripe webhook signature
--      rotated).
--   3. The audit-seal chain (税理士法 §41 帳簿等保存義務) retains
--      provenance — DLQ rows are never silently DELETEd; they are
--      flipped to status='replayed' or status='abandoned' with a
--      reason.
--
-- Why NOT just extend bg_task_queue
-- ---------------------------------
-- bg_task_queue is the hot path scanned every 2s by `_bg_task_worker.py`.
-- A failed-and-abandoned row sitting there forever drags index hot
-- pages out of cache. Quarantine to a side table keeps the hot worker
-- index small (pending+processing+done rows only) while preserving the
-- forensic record for as long as audit retention requires.
--
-- ¥3/req billing posture
-- ----------------------
-- DLQ replay is operator-only — no customer-facing read path. The
-- `am_dlq` write happens inside the same transaction as the parent
-- `bg_task_queue.status='failed'` flip, so there is no double-bill
-- and no orphan window. The drain log is read-only via internal
-- /v1/admin/* surface (not metered).
--
-- License posture
-- ---------------
-- Pure operational table; no external data ingest, no redistribution.
-- License field omitted (operational schema).

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_dlq (
    dlq_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind         TEXT NOT NULL                       -- 'bg_task' / 'webhook_delivery' / 'cron_etl'
                        CHECK (source_kind IN ('bg_task','webhook_delivery','cron_etl','other')),
    source_id           TEXT NOT NULL,                      -- bg_task_queue.id / webhook_deliveries.id / cron-run-id
    kind                TEXT NOT NULL,                      -- task kind (e.g. 'welcome_email', 'program.amended')
    payload             TEXT NOT NULL,                      -- JSON snapshot of the failed work unit
    attempts            INTEGER NOT NULL DEFAULT 0
                        CHECK (attempts >= 0),
    last_error          TEXT,                               -- truncated error text (~2KB max)
    first_failed_at     TEXT NOT NULL,
    last_failed_at      TEXT NOT NULL,
    abandoned_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    status              TEXT NOT NULL DEFAULT 'quarantined' -- quarantined / replayed / abandoned
                        CHECK (status IN ('quarantined','replayed','abandoned')),
    replayed_at         TEXT,                               -- ISO 8601 (set on replay success)
    replay_run_id       INTEGER,                            -- FK to dlq_drain_log.run_id
    notes               TEXT,
    UNIQUE (source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS idx_am_dlq_status_abandoned
    ON am_dlq(status, abandoned_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_dlq_source_kind_kind
    ON am_dlq(source_kind, kind);

CREATE INDEX IF NOT EXISTS idx_am_dlq_replay_run
    ON am_dlq(replay_run_id);

-- Quarantine summary view for the /v1/admin/dlq dashboard surface.
DROP VIEW IF EXISTS v_am_dlq_quarantine_summary;
CREATE VIEW v_am_dlq_quarantine_summary AS
SELECT
    source_kind, kind, status,
    COUNT(*)            AS cnt,
    MIN(abandoned_at)   AS oldest_abandoned_at,
    MAX(abandoned_at)   AS newest_abandoned_at
FROM am_dlq
GROUP BY source_kind, kind, status;

CREATE TABLE IF NOT EXISTS dlq_drain_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    scanned         INTEGER NOT NULL DEFAULT 0
                    CHECK (scanned >= 0),
    replayed_ok     INTEGER NOT NULL DEFAULT 0
                    CHECK (replayed_ok >= 0),
    replayed_failed INTEGER NOT NULL DEFAULT 0
                    CHECK (replayed_failed >= 0),
    abandoned       INTEGER NOT NULL DEFAULT 0
                    CHECK (abandoned >= 0),
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_dlq_drain_log_started
    ON dlq_drain_log(started_at DESC);

COMMIT;
