-- target_db: jpintel
-- 113_weekly_digest_state.sql
-- Saved Searches → Weekly Digest content-hash diff state + analytics_events
-- digest_delivered signal columns (60-day Advisor Loop core).
--
-- Business context (docs/_internal/value_maximization_plan_no_llm_api.md
-- §22.4 + §28.1 + §28.7 + §28.8):
--   * North Star is `weekly_evidence_loops` — a 7-day window in which a
--     single account satisfies (client_profile_imported OR client_tag>=5)
--     AND saved_search_created>=1 AND digest_delivered>=1.
--   * The legacy daily run_saved_searches.py uses `am_amendment_diff` for
--     "what changed" detection, but the weekly Advisor Loop wants a
--     content-hash diff against the previous result snapshot so we can
--     surface NEW / REMOVED / MODIFIED markers per match across runs.
--   * `analytics_events` (migration 111) is wired to record EVERY HTTP
--     request, but it has no surface for offline cron emissions — without
--     extending it, `digest_delivered` cannot be observed by the North
--     Star query that powers the dashboards.
--
-- Schema additions (additive, idempotent):
--
--   saved_searches:
--     * last_result_signature TEXT   — sha256 of the canonical last result
--                                      set (sorted unified_id list); enables
--                                      NEW / REMOVED / MODIFIED detection
--                                      across weekly runs without storing
--                                      the full payload.
--     * last_delta_count INTEGER     — count of NEW + REMOVED + MODIFIED
--                                      surfaced in the most recent digest;
--                                      surfaced in the next run's telemetry
--                                      and dashboards.
--     * is_active INTEGER NOT NULL DEFAULT 1
--                                    — soft-disable knob. The legacy
--                                      surface uses hard DELETE for "off",
--                                      but the cron's filter clause needs a
--                                      pause-without-delete path for the
--                                      Advisor Loop rollout (consultant
--                                      pauses a saved search during a
--                                      vacation period without losing the
--                                      query). Default 1 keeps every
--                                      existing row honest.
--
--   analytics_events:
--     * event_name TEXT             — non-NULL when this row is an
--                                      offline-cron-emitted signal (e.g.
--                                      'digest_delivered'); NULL for the
--                                      regular HTTP request rows that
--                                      AnalyticsRecorderMiddleware writes.
--                                      The path column already carries the
--                                      semantic identity for HTTP rows.
--     * saved_search_id INTEGER     — FK-shape (no enforced constraint to
--                                      preserve idempotency under partial
--                                      table state); NULL for non-digest
--                                      rows.
--     * delta_count INTEGER         — NEW + REMOVED + MODIFIED count for
--                                      digest rows; NULL otherwise.
--
-- Idempotency:
--   * SQLite has no `ALTER TABLE ADD COLUMN IF NOT EXISTS`. We rely on the
--     entrypoint.sh self-heal loop tolerating "duplicate column name" as a
--     boot-warning continuation (matches mig 049 / 097 patterns).
--   * Re-running this file on every Fly boot is safe: each ALTER fails-and-
--     continues, each CREATE INDEX uses IF NOT EXISTS.
--
-- DOWN:
--   No rollback companion. SQLite cannot drop columns without a table
--   rebuild, and the new columns are nullable / default-safe so leaving
--   them in place is the documented forward path.

PRAGMA foreign_keys = ON;

-- saved_searches additive columns (Advisor Loop content-hash diff state).
ALTER TABLE saved_searches ADD COLUMN last_result_signature TEXT;
ALTER TABLE saved_searches ADD COLUMN last_delta_count INTEGER;
ALTER TABLE saved_searches ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;

-- The cron's hot-path predicate is
--   WHERE frequency='weekly' AND is_active=1 AND
--         (last_run_at IS NULL OR last_run_at < ?)
-- so a partial index on the (frequency, is_active) shape pays off once the
-- table grows past a few thousand rows. Partial because >99% of rows are
-- is_active=1 — including is_active=0 rows in the index would waste space.
CREATE INDEX IF NOT EXISTS idx_saved_searches_weekly_active
    ON saved_searches(frequency, last_run_at)
    WHERE is_active = 1;

-- analytics_events offline-cron signal columns.
ALTER TABLE analytics_events ADD COLUMN event_name TEXT;
ALTER TABLE analytics_events ADD COLUMN saved_search_id INTEGER;
ALTER TABLE analytics_events ADD COLUMN delta_count INTEGER;

-- The North Star query (weekly_evidence_loops) groups by account x ts-bucket
-- where event_name='digest_delivered'. A partial index on event_name keeps
-- the index narrow because >99% of rows are HTTP traffic with NULL
-- event_name; only the offline-cron rows carry a value.
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_name_ts
    ON analytics_events(event_name, ts DESC)
    WHERE event_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_analytics_events_saved_search
    ON analytics_events(saved_search_id, ts DESC)
    WHERE saved_search_id IS NOT NULL;

-- Bookkeeping recorded by scripts/migrate.py into schema_migrations.
-- Do NOT INSERT here.
