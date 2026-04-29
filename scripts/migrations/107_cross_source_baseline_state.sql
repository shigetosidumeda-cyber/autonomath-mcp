-- target_db: autonomath
-- migration 107_cross_source_baseline_state
--
-- Self-tracking baseline state for the hourly `cross_source_check.py`
-- cron. The first wet run after migration 101 went live would otherwise
-- emit ~4.88M `correction_log` rows — every `am_entity_facts` row whose
-- `confirming_source_count` was the column DEFAULT (1) and whose live
-- distinct-source count came in at 0 / 1 / NULL. None of those are real
-- regressions; they are just the initial population of the column.
--
-- The Trust 8-pack agent flagged this as P0: emitting 4.88M false-positive
-- correction-log rows would (a) DDOS the public RSS feed and (b) destroy
-- our reputation as a trust-substrate operator, since every row triggers
-- a markdown post under site/news/correction-{id}.html.
--
-- This migration adds a single-row state table the cron consults on every
-- run. When `baseline_completed = 0` the cron behaves as `--baseline`
-- (refreshes `confirming_source_count` but writes ZERO `correction_log`
-- rows) and flips the flag at the end. From the second run onwards
-- regression detection runs normally.
--
-- Honest caveat: any genuine regression that would have fired on the
-- FIRST run (because it was already in the DB at migration time) is
-- suppressed by this scheme. Such a regression re-emits on the second
-- run ~1 hour later because the live count drops vs the now-recorded
-- baseline value. Net loss is at most 1 cron tick of detection latency.
--
-- Forward-only / idempotent. Re-running on each Fly boot is safe because
-- the CREATE uses IF NOT EXISTS and the seed INSERT uses INSERT OR IGNORE.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cross_source_baseline_state (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    baseline_run_at     TIMESTAMP,
    baseline_completed  BOOLEAN DEFAULT 0
);

INSERT OR IGNORE INTO cross_source_baseline_state (id, baseline_completed)
VALUES (1, 0);

-- migrate.py records this file's checksum so re-application is no-op.
