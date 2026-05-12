-- target_db: autonomath
-- migration: 275_explainable_fact
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim O (explainable_fact_design) knowledge graph metadata
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Per-fact 4-axis explainability metadata + Ed25519 attestation audit log
-- that an auditor can join against ``am_fact_signature`` (migration 262,
-- byte-tamper Ed25519 verify) and ``am_entity_facts`` (the canonical
-- 6.12M-row EAV store) to answer:
--
--   * Where did this fact come from?         (source_doc URL anchor)
--   * When was it extracted?                  (extracted_at timestamp)
--   * Who attested to it?                     (verified_by, attester chain)
--   * How confident is the extractor?         (confidence_lower/upper)
--
-- Wave 43.2.5 / migration 262 already lands ``am_fact_signature``
-- (fact_id PK + 64-96 byte ed25519_sig + corpus_snapshot_id + key_id +
-- signed_at + payload_sha256). That table answers "has this fact been
-- byte-tampered with since signing?" but does NOT carry the explainability
-- 4-tuple (source_doc / extracted_at / verified_by / confidence_band).
-- Migration 275 adds the explainability sidecar so that:
--
--   (a) /v1/facts/{fact_id}/why can return a self-contained explanation
--       payload (source_doc URL, extraction timestamp, attester chain,
--       confidence band) WITHOUT joining 4 tables at request time.
--   (b) the attestation chain is append-only — every attestation event
--       (initial sign, re-sign on amendment, re-sign on key rotation) is
--       logged into am_fact_attestation_log with the attester identity
--       and the raw Ed25519 signature hex, so the chain is auditable
--       independently of the latest signature in am_fact_signature.
--   (c) the confidence band is a [lower, upper] interval (not a single
--       point estimate) so the extractor honestly surfaces uncertainty
--       — e.g., 0.7 ≤ p ≤ 0.95 for NER-derived facts, 1.0 ≤ p ≤ 1.0 for
--       e-Gov authoritative facts.
--
-- Why a separate sidecar (not ALTER on am_fact_signature)
-- -------------------------------------------------------
-- (a) am_fact_signature is the byte-tamper substrate — adding 4 metadata
--     columns + 1 audit log table would change its semantics. Keeping
--     migration 262 stable lets future Ed25519 algorithm upgrades land
--     without touching the explainability layer.
-- (b) am_fact_attestation_log is **append-only** and grows linearly with
--     attestation events; mixing it into am_fact_signature would force
--     the signature read path (a hot probe surface) to scan past the
--     audit history on every lookup.
-- (c) confidence_lower/upper are NULL-able by design — legacy facts
--     extracted before this migration land with NULL bands and the
--     /v1/facts/{fact_id}/why endpoint surfaces this honestly as
--     "confidence_band unavailable, legacy extraction".
--
-- Schema notes
-- ------------
-- * ``fact_id`` is the PRIMARY KEY on am_fact_metadata. There is at most
--   one explainability metadata row per fact_id; updates land via
--   UPSERT (INSERT ... ON CONFLICT DO UPDATE) in the daily ETL.
-- * ``source_doc`` is a URL (typically e-Gov / NTA / METI / 公庫) or a
--   stable in-house anchor like ``corpus/snapshot_2026-05-12/<sha>``.
--   No CHECK constraint on format — the extractor honestly surfaces
--   whatever source string it had access to.
-- * ``extracted_at`` ISO-8601 UTC. Distinct from am_fact_signature.signed_at
--   (the latter is the signing event time, NOT the extraction event time).
-- * ``verified_by`` TEXT — short identifier for the attester / extractor
--   pipeline (e.g., 'etl_program_facts_v3', 'manual_walk_2026-05-12_a',
--   'cross_source_check_v2'). NULL allowed for unattested legacy rows.
-- * ``confidence_lower`` / ``confidence_upper`` REAL in [0.0, 1.0].
--   CHECK constraints enforce lower <= upper and both in band.
-- * ``ed25519_sig`` BLOB(96) — 64-byte raw sig + 8-byte version prefix +
--   8-byte key_id suffix (same shape as am_fact_signature.ed25519_sig).
--   NOT NULL: every metadata row carries its own attestation signature
--   so the attestation event is byte-verifiable even if the parallel
--   am_fact_signature row is later regenerated under a new corpus.
--
-- Attestation audit log
-- ---------------------
-- am_fact_attestation_log is APPEND-ONLY (no UPDATE, no DELETE in normal
-- operation). Each row records: (attestation_id INTEGER PK auto, fact_id
-- FK-by-convention, attester TEXT, signed_at ISO-8601 UTC, signature_hex
-- TEXT — 128 hex chars = 64 raw bytes). The signature_hex column is the
-- hex-encoded raw Ed25519 sig (NOT the prefixed 96-byte form) so an
-- auditor can replay the verify path with a pure standard library
-- ed25519 implementation without unpacking jpcite's version-prefix
-- encoding. Index on (fact_id, signed_at DESC) for chain walk.
--
-- Source discipline
-- -----------------
-- No external API calls. Sign key reuses Fly secret
-- ``AUTONOMATH_FACT_SIGN_PRIVATE_KEY`` (Ed25519 private, never
-- customer-visible). Verify key remains at GET /v1/audit/fact_pubkey.
-- NO LLM call in either sign or metadata-read path.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/facts/{fact_id}/why          — billable=1 (¥3 metered)
-- /v1/facts/{fact_id}/attestations — billable=1 (¥3 metered)
--
-- Idempotency
-- -----------
-- CREATE TABLE / CREATE INDEX IF NOT EXISTS. No DML. Safe for boot-time
-- self-heal on every Fly machine restart.
--
-- DOWN
-- ----
-- See companion ``275_explainable_fact_rollback.sql``.

PRAGMA foreign_keys = ON;

BEGIN;

-- 4-axis explainability metadata (1 row per fact_id).
CREATE TABLE IF NOT EXISTS am_fact_metadata (
    fact_id              TEXT PRIMARY KEY,
    source_doc           TEXT,
    extracted_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    verified_by          TEXT,
    confidence_lower     REAL,
    confidence_upper     REAL,
    ed25519_sig          BLOB NOT NULL,
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_am_fact_meta_sig_size_max CHECK (length(ed25519_sig) <= 96),
    CONSTRAINT ck_am_fact_meta_sig_size_min CHECK (length(ed25519_sig) >= 64),
    CONSTRAINT ck_am_fact_meta_conf_lower_band
        CHECK (confidence_lower IS NULL OR (confidence_lower >= 0.0 AND confidence_lower <= 1.0)),
    CONSTRAINT ck_am_fact_meta_conf_upper_band
        CHECK (confidence_upper IS NULL OR (confidence_upper >= 0.0 AND confidence_upper <= 1.0)),
    CONSTRAINT ck_am_fact_meta_conf_order
        CHECK (confidence_lower IS NULL OR confidence_upper IS NULL
               OR confidence_lower <= confidence_upper)
);

CREATE INDEX IF NOT EXISTS idx_am_fact_metadata_extracted_at
    ON am_fact_metadata(extracted_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_metadata_verified_by
    ON am_fact_metadata(verified_by);

CREATE INDEX IF NOT EXISTS idx_am_fact_metadata_source_doc
    ON am_fact_metadata(source_doc);

-- Append-only attestation audit log.
CREATE TABLE IF NOT EXISTS am_fact_attestation_log (
    attestation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id           TEXT NOT NULL,
    attester          TEXT NOT NULL,
    signed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    signature_hex     TEXT NOT NULL,
    notes             TEXT,
    CONSTRAINT ck_am_fact_attest_sig_hex_len
        CHECK (length(signature_hex) >= 128 AND length(signature_hex) <= 256),
    CONSTRAINT ck_am_fact_attest_sig_hex_chars
        CHECK (signature_hex GLOB '*[0-9a-fA-F]*')
);

CREATE INDEX IF NOT EXISTS idx_am_fact_attestation_log_fact_time
    ON am_fact_attestation_log(fact_id, signed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_attestation_log_attester
    ON am_fact_attestation_log(attester);

-- Helper view: latest attestation per fact (used by /v1/facts/{id}/why).
DROP VIEW IF EXISTS v_am_fact_attestation_latest;
CREATE VIEW v_am_fact_attestation_latest AS
SELECT
    fact_id,
    MAX(signed_at)             AS latest_signed_at,
    COUNT(*)                   AS attestation_count
FROM am_fact_attestation_log
GROUP BY fact_id;

-- Helper view: join 4-axis metadata + latest attestation summary.
DROP VIEW IF EXISTS v_am_fact_explainability;
CREATE VIEW v_am_fact_explainability AS
SELECT
    m.fact_id,
    m.source_doc,
    m.extracted_at,
    m.verified_by,
    m.confidence_lower,
    m.confidence_upper,
    length(m.ed25519_sig)      AS sig_byte_length,
    m.created_at,
    m.updated_at,
    a.latest_signed_at,
    a.attestation_count
FROM am_fact_metadata m
LEFT JOIN v_am_fact_attestation_latest a
    ON a.fact_id = m.fact_id;

COMMIT;
