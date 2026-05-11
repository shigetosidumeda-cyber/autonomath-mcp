-- target_db: autonomath
-- migration 208_program_case_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: programs x cases (採択事例). One row per (program_id, case_id)
-- pair with a similarity score 0.0-1.0 derived from text + 業種 + 規模
-- overlap. Drives the "similar adopted cases for this program" tool +
-- portfolio retrieval.
--
-- FK note
-- -------
-- jpi_programs.unified_id (TEXT) and jpi_case_studies.case_id (TEXT) are
-- the canonical mirror keys on autonomath.db.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 208_program_case_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS program_case_refs (
    program_id        TEXT NOT NULL REFERENCES jpi_programs(unified_id),
    case_id           TEXT NOT NULL REFERENCES jpi_case_studies(case_id),
    similarity_score  REAL NOT NULL CHECK (
                          similarity_score >= 0.0 AND similarity_score <= 1.0
                      ),
    created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (program_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_program_case_refs_case
    ON program_case_refs(case_id);

CREATE INDEX IF NOT EXISTS idx_program_case_refs_score
    ON program_case_refs(program_id, similarity_score DESC);

CREATE INDEX IF NOT EXISTS idx_program_case_refs_created_at
    ON program_case_refs(created_at);
