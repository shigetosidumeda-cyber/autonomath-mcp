-- target_db: autonomath
-- migration 168_am_actionable_answer_cache
--
-- W30 / Wave 30 follow-up: pre-cache the composite output envelope used
-- by the W30-2 (program 360 composite), W30-3 (houjin 360 composite),
-- and W30-4 (profile match composite) endpoints so cache-hit requests
-- skip the on-demand SQL JOIN entirely and return in 0-推論 latency.
--
-- Why this exists:
--   The composite envelopes for top-traffic subjects (top S/A program
--   tier rows, high-verification houjin rows, and the popular profile
--   match shapes) are deterministic functions of the corpus snapshot.
--   Computing them on demand requires 5-7 joins across am_entities /
--   am_entity_facts / jpi_invoice_registrants / jpi_adoption_records /
--   am_enforcement_detail / jpi_programs (and for `match`,
--   am_profile_match plus a top-10 program rollup). Precomputing the
--   envelope into one TEXT column lets the endpoint return the cached
--   bytes verbatim without re-executing the join.
--
-- Schema (as specified in the W30 follow-up plan):
--   subject_kind       TEXT NOT NULL — one of 'program' / 'houjin' / 'match'
--   subject_id         TEXT NOT NULL — UNI-* / 13-digit 法人番号 / profile_hash
--   output_json        TEXT NOT NULL — the composite envelope serialised as JSON
--   output_byte_size   INTEGER       — len(output_json) for cache audit
--   generated_at       TEXT          — ISO-8601, populator-stamped
--   corpus_snapshot_id TEXT          — for invalidation across snapshot bumps
--   PRIMARY KEY (subject_kind, subject_id)
--
--   ix_actionable_cache_kind on (subject_kind) — fast count + sweep per kind
--
-- Cache lookup priority (W30-2/3/4 endpoint contract):
--   1. SELECT output_json FROM am_actionable_answer_cache
--      WHERE subject_kind = ? AND subject_id = ?
--   2. If hit: parse output_json → return as JSONResponse (0-join, 0-推論).
--   3. If miss: fall through to the on-demand composer (existing
--      _build_houjin_360 / _build_program_full / _build_match_envelope
--      paths). Optionally also INSERT OR REPLACE into the cache so the
--      next request hits.
--
-- Idempotency:
--   * CREATE TABLE IF NOT EXISTS — re-runs on every Fly boot are safe.
--   * CREATE INDEX IF NOT EXISTS — same.
--   * Populator (scripts/cron/precompute_actionable_cache.py) uses
--     INSERT OR REPLACE so the same row can be re-warmed across snapshots.
--
-- Search-surface impact: NONE. This is a derived cache; no first-party
--   data lives here. Consumers must still fall through to the canonical
--   composers on miss so no stale snapshot ever masks a fresh row.
--
-- DOWN: companion file *_rollback.sql drops the table + index.
--   SQLite < 3.35 cannot DROP COLUMN, but full DROP TABLE is fine.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_actionable_answer_cache (
  subject_kind        TEXT NOT NULL,
  subject_id          TEXT NOT NULL,
  output_json         TEXT NOT NULL,
  output_byte_size    INTEGER,
  generated_at        TEXT DEFAULT (datetime('now')),
  corpus_snapshot_id  TEXT,
  PRIMARY KEY (subject_kind, subject_id)
);

CREATE INDEX IF NOT EXISTS ix_actionable_cache_kind
  ON am_actionable_answer_cache(subject_kind);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
