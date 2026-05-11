-- target_db: autonomath
-- migration 211_loan_program_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: 融資 x 補助金 (loan_programs x programs). One row per
-- (loan_id, program_id) pair with a complementary_score 0.0-1.0 that
-- captures how well the loan + 補助金 stack (担保 / 個人保証人 /
-- 第三者保証人 三軸 + 自己資金率). Drives the "loan + 補助金 combo"
-- finder tool.
--
-- FK note
-- -------
-- jpi_loan_programs.id (INTEGER) is the canonical mirror key.
-- jpi_programs.unified_id (TEXT) is the canonical mirror key on the
-- program side.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 211_loan_program_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS loan_program_refs (
    loan_id              INTEGER NOT NULL REFERENCES jpi_loan_programs(id),
    program_id           TEXT NOT NULL REFERENCES jpi_programs(unified_id),
    complementary_score  REAL NOT NULL CHECK (
                             complementary_score >= 0.0 AND complementary_score <= 1.0
                         ),
    created_at           INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (loan_id, program_id)
);

CREATE INDEX IF NOT EXISTS idx_loan_program_refs_program
    ON loan_program_refs(program_id);

CREATE INDEX IF NOT EXISTS idx_loan_program_refs_score
    ON loan_program_refs(loan_id, complementary_score DESC);

CREATE INDEX IF NOT EXISTS idx_loan_program_refs_created_at
    ON loan_program_refs(created_at);
