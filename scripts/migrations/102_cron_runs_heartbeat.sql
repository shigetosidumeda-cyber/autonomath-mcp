-- migration 102_cron_runs_heartbeat
--
-- Heartbeat / observability table for all `scripts/cron/*.py` entries.
-- Every cron writes one row per run on completion (success OR failure).
-- The single row carries enough metadata to:
--   * verify the cron actually executed (not just scheduled)
--   * detect missed runs (last_run_at gap exceeds expected interval)
--   * surface failure rate per cron (status='error' fraction)
--   * drive a /v1/admin/cron_status read-side endpoint
--
-- Targets jpintel.db (default target_db). Picked over autonomath.db
-- because the cron heartbeat is operational metadata, not entity-fact
-- substrate, and we already keep operational tables (api_keys,
-- usage_events, audit_seal, idempotency_cache) in jpintel.db.
--
-- Forward-only / idempotent. Re-applying on each migrate.py invocation
-- is safe because every DDL uses IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Heartbeat row per cron run.

CREATE TABLE IF NOT EXISTS cron_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cron_name       TEXT NOT NULL,        -- e.g. 'run_saved_searches', 'amendment_alert'
    started_at      TEXT NOT NULL,        -- ISO 8601 UTC, set when the script enters
    finished_at     TEXT,                 -- NULL while running; set on exit
    status          TEXT NOT NULL,        -- 'ok' | 'error' | 'partial' | 'dry_run' | 'running'
    rows_processed  INTEGER,              -- script-defined unit (emails sent, diffs inserted, ...)
    rows_skipped    INTEGER,              -- e.g. window-gated, dedup, idempotent skip
    error_message   TEXT,                 -- short error class on status='error' (no PII / no stack)
    metadata_json   TEXT,                 -- arbitrary JSON for per-cron summary stats
    workflow_run_id TEXT,                 -- GitHub Actions run id when triggered via GHA
    git_sha         TEXT                  -- commit SHA the cron was running against
);

CREATE INDEX IF NOT EXISTS idx_cron_runs_name_started
    ON cron_runs (cron_name, started_at DESC);

-- For "show me the latest run per cron" admin view.
CREATE INDEX IF NOT EXISTS idx_cron_runs_status_started
    ON cron_runs (status, started_at DESC);

-- ---------------------------------------------------------------------------
-- Retention: cap at ~10k rows per cron_name. The DELETE below is a hint;
-- the actual prune runs in send_daily_kpi_digest.py once table exists.
-- We do NOT prune in this migration to keep the migration idempotent and
-- read-only at apply time.
