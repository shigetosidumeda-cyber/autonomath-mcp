-- target_db: autonomath
-- migration: 285_fact_signature_v2
-- generated_at: 2026-05-12
-- author: Wave 47 Phase 2 tick#6 — Dim F fact_signature storage extension
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- ADDITIVE extension to mig 262 (am_fact_signature) per
-- feedback_explainable_fact_design.md. The existing 262 table is a
-- per-fact single-signature store — one (fact_id) PK row carries the
-- latest Ed25519 sig. That is sufficient for tamper-detect on the
-- happy path but lacks two things the multi-attestation regime needs:
--
--   (1) A SINGLE fact may be co-signed by multiple keys (operator key
--       + customer auditor key + 3rd-party notary key) under the same
--       payload_sha256, and we want to enumerate ALL active attestations
--       for forensic / multi-party verify — not just the latest one.
--   (2) When a key is rotated or compromised, every prior signature
--       under that key needs an explicit REVOCATION row (not a silent
--       overwrite) so a verifier can render "signed-then-revoked" with
--       the revocation reason + timestamp.
--
-- This migration therefore introduces TWO new tables, leaving mig 262
-- untouched (no ALTER, no overwrite — per the "既存 mig 262 上書き禁止"
-- constraint):
--
--   * am_fact_signature_v2_attestation — multi-attestation per fact +
--     key pair. Each row is ONE Ed25519 signature under a specific key
--     and a specific corpus_snapshot_id. Append-only; UPSERT-only on
--     (fact_id, signer_pubkey, corpus_snapshot_id).
--   * am_fact_signature_v2_revocation_log — append-only revocation
--     events. revocation_id PK; signature_id FK -> attestation row.
--
-- Relationship to mig 262
-- -----------------------
-- mig 262 (am_fact_signature) remains the "latest signature pointer".
-- mig 285 (am_fact_signature_v2_*) carries the FULL attestation history
-- with revocation traceability. The verify endpoint reads 262 for the
-- O(1) latest path, then falls back to 285 for the enumerate-all path.
-- No data is duplicated: 262's latest row is also the latest 285 row,
-- so the rebuild ETL (build_fact_signatures_v2.py) reads 262 and
-- writes 285 — never the other way around.
--
-- LLM-0 discipline
-- ----------------
-- Pure cryptographic + schema work. ZERO Anthropic/OpenAI SDK touch.
-- Signing uses the Ed25519 private key in Fly secret AUTONOMATH_FACT_
-- SIGN_PRIVATE_KEY (per mig 262 comment). Verify is server-side
-- pynacl / cryptography only. No "ai_explanation" column.
--
-- ¥3/req billing posture
-- ----------------------
--   /v1/facts/{fact_id}/attestations              billable=1 (¥3)
--   /v1/facts/{fact_id}/attestations/{key_id}     billable=1 (¥3)
--   /v1/facts/{fact_id}/revocations               billable=0 (free — public)
--
-- Idempotency
-- -----------
-- CREATE TABLE / CREATE INDEX IF NOT EXISTS only. No DML. Boot-time safe.
--
-- DOWN
-- ----
-- See companion 285_fact_signature_v2_rollback.sql.

PRAGMA foreign_keys = ON;

BEGIN;

-- Multi-attestation per (fact_id, signer_pubkey, corpus_snapshot_id).
-- One row = one Ed25519 signature under a specific key over a specific
-- payload_sha256. Append-only on the verify hot path; UPSERT only when
-- the same triplet is re-signed (idempotent retry).
CREATE TABLE IF NOT EXISTS am_fact_signature_v2_attestation (
    signature_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id               TEXT NOT NULL,                                           -- matches am_fact_signature.fact_id (mig 262); not a hard FK to allow legacy facts
    signer_pubkey         TEXT NOT NULL,                                           -- 64-char hex (32 raw bytes) Ed25519 public key
    signature_bytes       BLOB NOT NULL,                                           -- raw Ed25519 signature (64..96 bytes per mig 262 convention)
    corpus_snapshot_id    TEXT,                                                    -- snapshot at sign time; NULL allowed for legacy facts
    key_id                TEXT NOT NULL DEFAULT 'k20260512_a',                     -- short opaque key handle (rotation tag)
    payload_sha256        TEXT NOT NULL,                                           -- 64-char hex sha256 of the canonical payload that was signed
    signed_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    notes                 TEXT,                                                    -- free-form operator note (e.g. "auditor co-sign")
    CHECK (length(signer_pubkey) = 64),                                            -- hex(32 bytes)
    CHECK (length(payload_sha256) = 64),                                           -- hex(sha256)
    CHECK (length(signature_bytes) BETWEEN 64 AND 96),                             -- raw 64 .. operator prefixed 96 (matches mig 262)
    CHECK (length(fact_id) BETWEEN 1 AND 128)
);

-- Hot path: "list all attestations for fact" + "latest by signer".
CREATE INDEX IF NOT EXISTS idx_am_fact_sig_v2_att_fact
    ON am_fact_signature_v2_attestation(fact_id, signed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_sig_v2_att_signer
    ON am_fact_signature_v2_attestation(signer_pubkey, signed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_sig_v2_att_keyid
    ON am_fact_signature_v2_attestation(key_id);

-- Dedup: one signature per (fact, signer, snapshot) — re-signing under
-- the SAME snapshot is a no-op; re-signing under a NEW snapshot adds
-- a new row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_am_fact_sig_v2_att_triplet
    ON am_fact_signature_v2_attestation(fact_id, signer_pubkey, corpus_snapshot_id);

-- Revocation log. Append-only. signature_id is a logical FK to the
-- attestation table (declared as FK below). reason is free-form but
-- gated by a CHECK on the reason_class enum so we can aggregate it.
CREATE TABLE IF NOT EXISTS am_fact_signature_v2_revocation_log (
    revoke_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    signature_id          INTEGER NOT NULL,                                        -- FK -> am_fact_signature_v2_attestation(signature_id)
    reason_class          TEXT NOT NULL
                              CHECK (reason_class IN
                                  ('key_rotated', 'key_compromised',
                                   'payload_amended', 'operator_request',
                                   'auditor_request', 'other')),
    reason                TEXT,                                                    -- free-form detail; nullable for class='key_rotated' which is self-explanatory
    revoked_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    revoked_by            TEXT,                                                    -- opaque actor identifier (operator-token-hash or auditor-pubkey)
    CHECK (length(reason) IS NULL OR length(reason) BETWEEN 1 AND 1024),
    FOREIGN KEY (signature_id) REFERENCES am_fact_signature_v2_attestation(signature_id)
);

CREATE INDEX IF NOT EXISTS idx_am_fact_sig_v2_rev_signature
    ON am_fact_signature_v2_revocation_log(signature_id, revoked_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_sig_v2_rev_class
    ON am_fact_signature_v2_revocation_log(reason_class, revoked_at DESC);

-- A given attestation can only be revoked ONCE. Future "un-revoke" is
-- modelled as a fresh attestation row, not a revoke deletion.
CREATE UNIQUE INDEX IF NOT EXISTS uq_am_fact_sig_v2_rev_signature
    ON am_fact_signature_v2_revocation_log(signature_id);

-- Helper view: enumerate active (not revoked) attestations per fact.
-- The verify endpoint joins on this view so revoked sigs are excluded
-- without a WHERE clause in the handler.
DROP VIEW IF EXISTS v_am_fact_sig_v2_attestation_active;
CREATE VIEW v_am_fact_sig_v2_attestation_active AS
SELECT
    a.signature_id,
    a.fact_id,
    a.signer_pubkey,
    a.signature_bytes,
    a.corpus_snapshot_id,
    a.key_id,
    a.payload_sha256,
    a.signed_at
FROM am_fact_signature_v2_attestation a
LEFT JOIN am_fact_signature_v2_revocation_log r
    ON r.signature_id = a.signature_id
WHERE r.revoke_id IS NULL;

COMMIT;
