-- target_db: jpintel
-- migration: wave24_190_restore_drill_log
-- generated_at: 2026-05-07
-- author: DEEP-62 R2 backup integrity verify cron + restore drill
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Audit log for the monthly R2 backup restore drill (DEEP-62). Each row
-- captures one drill execution so that:
--   1. operator can prove "we can actually restore the backup" at compliance
--      review time without re-running a 30-min drill on demand.
--   2. RTO p50/p95 trends can be aggregated into
--      `analytics/restore_rto_quarter.jsonl` and trigger DR re-design when
--      p95 violates SLA in 2 consecutive quarters.
--   3. corrupt backup generations can be identified by drill_date +
--      backup_db_kind without rehydrating the .db.gz off R2 again.
--
-- target_db = jpintel
-- -------------------
-- Drill log is small (12 rows/year per kind, ~24 rows/year total) and must
-- NOT be written into the 9.4 GB autonomath.db (which would defeat the
-- "9.4 GB stays mostly cold" RPO design). jpintel.db is 352 MB and already
-- carries audit-style append-only tables (verify_log on autonomath; this is
-- the symmetric jpintel-side audit log). entrypoint.sh §3 applies migrate.py
-- on jpintel.db which picks up this file by virtue of the
-- `-- target_db: jpintel` marker on line 1.
--
-- Idempotency contract
-- --------------------
--   * `CREATE TABLE IF NOT EXISTS` — re-run on a populated DB is a no-op.
--   * 1 index uses `CREATE INDEX IF NOT EXISTS`.
--   * No DML — drill rows are inserted by `scripts/cron/restore_drill_monthly.py`.
--
-- LLM call: 0. Pure SQLite write. Cron is python stdlib + sqlite3 + rclone.
--
-- Field semantics
-- ---------------
-- id                    INTEGER PRIMARY KEY AUTOINCREMENT — surrogate.
-- drill_date            TEXT, YYYY-MM-DD JST when drill ran.
-- backup_db_kind        TEXT enum [autonomath, jpintel]. Alternating per
--                       month-parity (even=autonomath, odd=jpintel).
-- backup_key            TEXT, the R2 object key sampled (full key path).
-- backup_sha256         TEXT, sha256 of the .db.gz fetched from R2.
-- backup_size_bytes     INTEGER, byte count of the .db.gz fetched.
-- download_seconds      REAL, wall-clock seconds for R2 download phase.
-- gunzip_seconds        REAL, wall-clock seconds for the gunzip step.
-- integrity_check_seconds REAL, wall-clock seconds for PRAGMA integrity_check.
-- fk_check_seconds      REAL, wall-clock seconds for PRAGMA foreign_key_check.
-- integrity_status      TEXT enum [ok, corrupted].
-- fk_status             TEXT enum [ok, violations].
-- rto_total_seconds     REAL, t_int_end - t_dl_start. SLA target: autonomath
--                       p95 < 1800s; jpintel p95 < 300s.
-- sampled_age_days      INTEGER, age of the sampled backup in days at drill
--                       time. Always >= 3 by sampler design.
-- top10_count_status    TEXT enum [ok, drift, skip]. ok = all 10 sampled
--                       table COUNT(*) within ±10% of expected; drift =
--                       at least one outside band; skip = expected.json
--                       missing or unreadable.
-- top10_count_detail    TEXT, JSON object {table: {expected, actual}} — only
--                       populated when status != 'skip'.
-- notes                 TEXT, free-text triage memo (operator only).
-- created_at            TEXT ISO 8601 UTC server clock; default now.

CREATE TABLE IF NOT EXISTS restore_drill_log (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  drill_date               TEXT NOT NULL,
  backup_db_kind           TEXT NOT NULL CHECK (backup_db_kind IN ('autonomath','jpintel')),
  backup_key               TEXT NOT NULL,
  backup_sha256            TEXT NOT NULL,
  backup_size_bytes        INTEGER NOT NULL,
  download_seconds         REAL NOT NULL,
  gunzip_seconds           REAL NOT NULL,
  integrity_check_seconds  REAL NOT NULL,
  fk_check_seconds         REAL NOT NULL,
  integrity_status         TEXT NOT NULL CHECK (integrity_status IN ('ok','corrupted')),
  fk_status                TEXT NOT NULL CHECK (fk_status IN ('ok','violations')),
  rto_total_seconds        REAL NOT NULL,
  sampled_age_days         INTEGER NOT NULL,
  top10_count_status       TEXT NOT NULL CHECK (top10_count_status IN ('ok','drift','skip')),
  top10_count_detail       TEXT,
  notes                    TEXT,
  created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Primary lookup pattern: "show drills for kind=X newest-first" (RTO trend
-- aggregator + integrity dashboard both read this shape).
CREATE INDEX IF NOT EXISTS ix_restore_drill_kind_date
  ON restore_drill_log(backup_db_kind, drill_date DESC);

-- Secondary lookup: "find every corrupted-or-violations row" (alert review
-- + post-mortem path). Partial index keeps it tiny.
CREATE INDEX IF NOT EXISTS ix_restore_drill_red
  ON restore_drill_log(drill_date DESC)
  WHERE integrity_status = 'corrupted' OR fk_status = 'violations';
