-- target_db: autonomath
-- migration 213_bid_program_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: 入札 x 補助金 (bids x programs). One row per (bid_id,
-- program_id) pair with the `fiscal_year` of the bid for time-series
-- filtering. Surfaces "this bid was funded by program X" linkage that
-- otherwise has to be inferred from procurement metadata.
--
-- FK note
-- -------
-- jpi_bids.unified_id (TEXT) and jpi_programs.unified_id (TEXT) are the
-- canonical mirror keys.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 213_bid_program_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bid_program_refs (
    bid_id       TEXT NOT NULL REFERENCES jpi_bids(unified_id),
    program_id   TEXT NOT NULL REFERENCES jpi_programs(unified_id),
    fiscal_year  INTEGER,
    created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (bid_id, program_id)
);

CREATE INDEX IF NOT EXISTS idx_bid_program_refs_program
    ON bid_program_refs(program_id);

CREATE INDEX IF NOT EXISTS idx_bid_program_refs_fiscal_year
    ON bid_program_refs(fiscal_year)
    WHERE fiscal_year IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bid_program_refs_created_at
    ON bid_program_refs(created_at);
