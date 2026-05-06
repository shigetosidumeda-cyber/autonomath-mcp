-- target_db: autonomath
-- migration wave24_106_amendment_snapshot_rebuild (D1 data-integrity, MASTER_PLAN_v1 章 3 §D1)
--
-- Why this exists:
--   `am_amendment_snapshot` carries 14,596 rows but agent SQL verify
--   (CLAUDE.md / MASTER_PLAN_v1 §D1) confirmed eligibility_hash is uniform
--   sha256-of-empty on 12,014/14,596 (82.3%) and NOT A SINGLE entity_id
--   carries hash drift between version_seq=1 and version_seq=2 — i.e. the
--   "time-series" surface is structurally fake. `track_amendment_lineage_am`
--   today emits an honesty caveat per response but the underlying corpus
--   cannot back any real lineage claim.
--
--   This migration does TWO things:
--
--     (a) Tag every existing am_amendment_snapshot row with
--         snapshot_source='legacy_v1' so the new daily-rebuild ETL can
--         INSERT new rows under a different snapshot_source value and
--         downstream queries can default-exclude the legacy corpus.
--
--     (b) Create a NEW append-only history table
--         `am_program_eligibility_history` that the daily ETL
--         (`scripts/etl/rebuild_amendment_snapshot.py`, JST 04:00 cron)
--         populates by running the structured eligibility extractor over
--         tier S/A program corpora. Each row carries content_hash +
--         eligibility_hash + eligibility_struct (JSON) + diff_from_prev
--         (JSON) + diff_reason. Real time-series lineage materializes the
--         moment a program's content_hash drifts.
--
-- Idempotency:
--   * ALTER TABLE ADD COLUMN raises "duplicate column name" on re-run; the
--     entrypoint loop swallows that OperationalError when the message is
--     ONLY "duplicate column" (same pattern used by 049 / 101 / 119 / 105).
--   * UPDATE for the legacy backfill is gated by `WHERE snapshot_source IS
--     NULL` so a re-run NO-OPs after the first apply.
--   * CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
--
-- DOWN:
--   See companion `wave24_106_amendment_snapshot_rebuild_rollback.sql`.

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 1. am_amendment_snapshot: snapshot_source + rebuilt_at columns.
--    DEFAULT 'legacy_v1' marks every existing row as the pre-rebuild
--    corpus so the new history table can grow alongside without
--    contaminating it. New rebuilt rows are inserted into
--    am_program_eligibility_history (NOT am_amendment_snapshot) so the
--    legacy_v1 marker is informational + future-proof.
-- ------------------------------------------------------------
ALTER TABLE am_amendment_snapshot ADD COLUMN snapshot_source TEXT DEFAULT 'legacy_v1';
ALTER TABLE am_amendment_snapshot ADD COLUMN rebuilt_at TEXT;

-- Backfill any NULL values that pre-existed the DEFAULT (paranoia: SQLite's
-- ALTER ADD COLUMN with DEFAULT applies to new rows but the existing rows
-- materialize the default lazily — explicit UPDATE makes the marker concrete
-- so reporting queries don't see NULL on the legacy corpus).
UPDATE am_amendment_snapshot
   SET snapshot_source = 'legacy_v1'
 WHERE snapshot_source IS NULL;

-- ------------------------------------------------------------
-- 2. am_program_eligibility_history — new history table.
--
--   * `program_id` references jpi_programs.unified_id (autonomath-side
--     program canonical key — `programs` is forbidden in autonomath.db
--     per AM_FORBIDDEN in scripts/schema_guard.py).
--   * `captured_at` is the ISO 8601 UTC timestamp the ETL run captured.
--   * `source_url` + `source_fetched_at` carry the canonical citation
--     for honesty auditing (memory `feedback_no_fake_data`).
--   * `content_hash` is SHA256 of the canonical body text the ETL
--     normalized at fetch time. Any drift triggers a new row.
--   * `eligibility_hash` is SHA256 of the canonicalized
--     eligibility_struct JSON (sorted keys, deduped lists). Drift here
--     means eligibility predicates moved even when the body text was
--     superficially the same.
--   * `eligibility_struct` is the structured extraction output (JSON).
--     Schema is the existing eligibility_extractor / amendment-diff
--     contract (target_set / amount / subsidy_rate / prerequisites / etc).
--   * `diff_from_prev` (JSON) is the per-field {prev,new} map vs the
--     immediately preceding row for the same program_id. NULL on the
--     first capture for a program.
--   * `diff_reason` is a coarse enum-like label ('initial' / 'content_drift' /
--     'eligibility_drift' / 'noop'). NULL when no diff (i.e. the row
--     was skipped at INSERT time — see UNIQUE below).
--
--   UNIQUE(program_id, content_hash) gives `INSERT OR IGNORE` semantics
--   to the daily ETL: re-running the rebuild on a content-stable program
--   is a no-op (the cron is idempotent within a 24h window). Only when
--   content_hash drifts does a new row land.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_program_eligibility_history (
    history_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id           TEXT NOT NULL,
    captured_at          TEXT NOT NULL,
    source_url           TEXT,
    source_fetched_at    TEXT,
    content_hash         TEXT NOT NULL,
    eligibility_hash     TEXT,
    eligibility_struct   TEXT,                  -- JSON
    diff_from_prev       TEXT,                  -- JSON {field: {prev, new}}
    diff_reason          TEXT,                  -- 'initial' | 'content_drift' | 'eligibility_drift' | 'noop'
    UNIQUE (program_id, content_hash)
);

-- Hot path: per-program time-series scan (track_amendment_lineage_am).
CREATE INDEX IF NOT EXISTS idx_apeh_program
    ON am_program_eligibility_history(program_id, captured_at);

-- Audit lookup: filter to rows that actually represent drift events
-- (skipping rows whose diff_reason was a NO-OP). Partial index keeps the
-- working set small for KPI reporting on lineage health.
CREATE INDEX IF NOT EXISTS idx_apeh_diff
    ON am_program_eligibility_history(diff_reason)
 WHERE diff_reason IS NOT NULL;
