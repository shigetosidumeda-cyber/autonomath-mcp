-- target_db: autonomath
-- migration: 275_explainable_fact (rollback)
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim O (explainable_fact_design) rollback
--
-- Drops the explainability sidecar tables, indexes, and views added by
-- 275_explainable_fact.sql. Idempotent: every DROP uses IF EXISTS.
--
-- WARNING
-- -------
-- This rollback removes the 4-axis explainability metadata
-- (source_doc / extracted_at / verified_by / confidence band) AND the
-- append-only attestation audit log. Downstream consumers
-- (/v1/facts/{id}/why, /v1/facts/{id}/attestations) will return 503
-- until the migration is re-applied. The byte-tamper Ed25519 verify
-- path (api/fact_verify.py) is UNAFFECTED — it reads from
-- am_fact_signature (migration 262) which is not touched here.

PRAGMA foreign_keys = ON;

BEGIN;

DROP VIEW IF EXISTS v_am_fact_explainability;
DROP VIEW IF EXISTS v_am_fact_attestation_latest;

DROP INDEX IF EXISTS idx_am_fact_attestation_log_attester;
DROP INDEX IF EXISTS idx_am_fact_attestation_log_fact_time;
DROP TABLE IF EXISTS am_fact_attestation_log;

DROP INDEX IF EXISTS idx_am_fact_metadata_source_doc;
DROP INDEX IF EXISTS idx_am_fact_metadata_verified_by;
DROP INDEX IF EXISTS idx_am_fact_metadata_extracted_at;
DROP TABLE IF EXISTS am_fact_metadata;

COMMIT;
