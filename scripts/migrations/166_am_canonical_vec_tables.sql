-- target_db: autonomath
-- migration 166_am_canonical_vec_tables
--
-- W28-5 vec coverage gap fix: existing am_entities_vec_<S/L/C/T/K/J/A>
-- (migration 147) are keyed by jpintel-side rowids (programs.rowid,
-- court_decisions.rowid, etc.) and have ZERO overlap with am_entities
-- canonical_id (TEXT, e.g. "program:...", "houjin:6020001136067",
-- "UNI-*"). Real canonical vec coverage = adoption only (100% via
-- jpi_adoption_records.id which is INTEGER and shared).
--
-- This migration adds 7 NEW vec tables keyed PER record_kind, where
-- canonical_id (TEXT) is preserved via a sidecar mapping table.
-- vec0 requires INTEGER PRIMARY KEY, so we use a synthetic rowid in
-- the *_map table and JOIN back to am_entities.canonical_id.
--
-- Vec table layout (one per record_kind):
--   am_canonical_vec_program       (kind=program,         11,601 candidates)
--   am_canonical_vec_enforcement   (kind=enforcement,     22,255)
--   am_canonical_vec_corporate     (kind=corporate_entity,166,969)
--   am_canonical_vec_statistic     (kind=statistic,       73,960)
--   am_canonical_vec_case_study    (kind=case_study,      2,885)
--   am_canonical_vec_law           (kind=law,             252)
--   am_canonical_vec_tax_measure   (kind=tax_measure,     285)
--
-- Each vec table has a sibling *_map (regular table) that holds the
-- (synthetic_id INTEGER PK, canonical_id TEXT UNIQUE, source_text TEXT)
-- mapping. Populator (tools/offline/embed_canonical_entities.py) writes
-- both atomically. Query path JOINs vec → map → am_entities.
--
-- NO LLM. embed model = sentence-transformers intfloat/multilingual-e5-large
-- (1024-dim), same model + dim as migration 147.
--
-- Idempotent. Re-runs on every Fly boot via entrypoint.sh §4 are safe
-- (CREATE * IF NOT EXISTS only). Populator handles INSERT OR REPLACE
-- on the *_map side and DELETE+INSERT on the vec0 side.

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_program USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_program_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_program_map_canon
  ON am_canonical_vec_program_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_enforcement USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_enforcement_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_enforcement_map_canon
  ON am_canonical_vec_enforcement_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_corporate USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_corporate_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_corporate_map_canon
  ON am_canonical_vec_corporate_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_statistic USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_statistic_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_statistic_map_canon
  ON am_canonical_vec_statistic_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_case_study USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_case_study_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_case_study_map_canon
  ON am_canonical_vec_case_study_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_law USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_law_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_law_map_canon
  ON am_canonical_vec_law_map(canonical_id);

CREATE VIRTUAL TABLE IF NOT EXISTS am_canonical_vec_tax_measure USING vec0(
  synthetic_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE TABLE IF NOT EXISTS am_canonical_vec_tax_measure_map (
  synthetic_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT NOT NULL UNIQUE,
  source_text  TEXT,
  embedded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_am_cvec_tax_measure_map_canon
  ON am_canonical_vec_tax_measure_map(canonical_id);
