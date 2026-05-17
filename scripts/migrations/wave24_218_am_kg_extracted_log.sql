-- target_db: autonomath
-- migration: wave24_218_am_kg_extracted_log
-- generated_at: 2026-05-17
-- author: CC4 — Lane M1 PDF → KG extraction run ledger
-- idempotent: every CREATE uses IF NOT EXISTS; pure DDL, no DML.
--
-- Purpose
-- -------
-- Run-level ledger for the M1 (PDF → KG triples) batch extraction
-- pipeline at scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py.
--
-- Each run streams Textract OCR JSON from the Singapore staging bucket
-- (jpcite-credit-textract-apse1-202605/out/) and writes deterministic
-- entity_facts + relations to am_entity_facts / am_relation. The
-- per-run row tracks counts, byte budget, and skip reasons so future
-- analytical queries can audit what was harvested vs left on the table.
--
-- Idempotency contract
-- --------------------
--   * UNIQUE (run_id) — re-running with the same run_id is a no-op.
--   * The downstream INSERT OR IGNORE writes into am_entity_facts /
--     am_relation rely on existing uq_am_facts_entity_field_text and
--     ux_am_relation_harvest unique indexes — re-runs converge on the
--     same row set without dup growth.
--   * All indexes are CREATE INDEX IF NOT EXISTS.
--
-- LLM call: 0. Pure SQLite DDL + regex extraction over Textract output.
--
-- License posture
-- ---------------
-- Source PDFs are public-sector primary-source artifacts (gov_standard
-- v2.0 / PDL v1.0 equivalent). Textract OCR output is derived data; the
-- M1 KG harvest stays within the same license envelope. No third-party
-- aggregator hosts (noukaweb / hojyokin-portal / biz.stayway /
-- minnano-hojyokin) appear in source_url.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_kg_extracted_log — per-run M1 extraction summary
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_kg_extracted_log (
    run_id              TEXT PRIMARY KEY,             -- e.g. '20260517T1830Z'
    lane                TEXT NOT NULL DEFAULT 'M1'
                          CHECK (lane IN ('M1','M2','M11')),
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    mode                TEXT NOT NULL DEFAULT 'local'
                          CHECK (mode IN ('local','sagemaker','dryrun')),
    s3_bucket           TEXT NOT NULL,
    s3_prefix           TEXT NOT NULL,
    objects_scanned     INTEGER NOT NULL DEFAULT 0,
    objects_skipped     INTEGER NOT NULL DEFAULT 0,
    pages_processed     INTEGER NOT NULL DEFAULT 0,
    bytes_streamed      INTEGER NOT NULL DEFAULT 0,
    entity_facts_added  INTEGER NOT NULL DEFAULT 0,
    relations_added     INTEGER NOT NULL DEFAULT 0,
    burn_usd_preflight  REAL,
    burn_usd_postflight REAL,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS ix_am_kg_extracted_log_lane_started
    ON am_kg_extracted_log(lane, started_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_kg_extracted_log_mode
    ON am_kg_extracted_log(mode);
