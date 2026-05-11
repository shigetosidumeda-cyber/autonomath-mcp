-- target_db: autonomath
-- migration 209_case_enforcement_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: 採択事例 x 行政処分 (case_studies x enforcement_cases). One
-- row per (case_id, enforcement_id) co-occurrence with the year + ministry
-- of the enforcement event for time-series filtering.
--
-- FK note
-- -------
-- jpi_case_studies.case_id (TEXT) and jpi_enforcement_cases.case_id (TEXT)
-- are both TEXT PKs. Column names are disambiguated below (case_id +
-- enforcement_id) to avoid join-side confusion.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 209_case_enforcement_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS case_enforcement_refs (
    case_id         TEXT NOT NULL REFERENCES jpi_case_studies(case_id),
    enforcement_id  TEXT NOT NULL REFERENCES jpi_enforcement_cases(case_id),
    year            INTEGER,
    ministry        TEXT,
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (case_id, enforcement_id)
);

CREATE INDEX IF NOT EXISTS idx_case_enforcement_refs_enforcement
    ON case_enforcement_refs(enforcement_id);

CREATE INDEX IF NOT EXISTS idx_case_enforcement_refs_year_ministry
    ON case_enforcement_refs(year, ministry);

CREATE INDEX IF NOT EXISTS idx_case_enforcement_refs_created_at
    ON case_enforcement_refs(created_at);
