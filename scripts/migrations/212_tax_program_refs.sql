-- target_db: autonomath
-- migration 212_tax_program_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: 税制 x 補助金 (tax_rulesets x programs). One row per
-- (tax_rule_id, program_id) pair with an `applicability` flag describing
-- how the tax rule applies to the program:
--   - 'mandatory'   : tax rule MUST be applied alongside the program
--   - 'recommended' : tax rule typically stacks for additional benefit
--   - 'mutually_exclusive' : tax rule and program cannot both be claimed
--   - 'conditional' : applies under specific entity-size / industry gates
--   - 'informational' : surfaced as related but no direct interaction
--
-- FK note
-- -------
-- jpi_tax_rulesets.unified_id (TEXT) is the canonical mirror key.
-- jpi_programs.unified_id (TEXT) is the canonical mirror key.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 212_tax_program_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tax_program_refs (
    tax_rule_id    TEXT NOT NULL REFERENCES jpi_tax_rulesets(unified_id),
    program_id     TEXT NOT NULL REFERENCES jpi_programs(unified_id),
    applicability  TEXT NOT NULL CHECK (applicability IN (
                       'mandatory',
                       'recommended',
                       'mutually_exclusive',
                       'conditional',
                       'informational'
                   )),
    created_at     INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (tax_rule_id, program_id)
);

CREATE INDEX IF NOT EXISTS idx_tax_program_refs_program
    ON tax_program_refs(program_id);

CREATE INDEX IF NOT EXISTS idx_tax_program_refs_applicability
    ON tax_program_refs(applicability);

CREATE INDEX IF NOT EXISTS idx_tax_program_refs_created_at
    ON tax_program_refs(created_at);
