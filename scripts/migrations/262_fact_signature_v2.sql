-- target_db: autonomath
-- migration: 262_fact_signature_v2
-- generated_at: 2026-05-12
-- author: Wave 43.2.5 — Dim E Verification trail (Ed25519 fact signature)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Per-fact Ed25519 cryptographic signature trail that lets a third party
-- verify a single `extracted_fact` row was committed under a specific
-- corpus snapshot without re-walking the entire Merkle anchor chain.
--
-- Wave 30 §52 / §47条の2 already covers the *narrative* audit_seal envelope
-- (api/_audit_seal.py + migration 089). Wave 33 R8 + W43.1.10 added the
-- daily Merkle root anchor (audit_proof endpoint, migration 146). What's
-- still missing is a per-fact, byte-tamper-detectable signature so:
--
--   (1) A customer-side audit working paper can cite a single fact_id and
--       prove it has not been amended since signing without dragging in
--       the daily Merkle leaves list.
--   (2) A tax bureau / 査察 audit can byte-flip a stored extracted_fact
--       row and the signature verify returns 409 instead of silently 200.
--   (3) The signature snapshots which `corpus_snapshot_id` was current at
--       sign time, so re-extraction under a newer snapshot is detectable
--       without comparing two full corpus dumps.
--
-- Why a new table (not ALTER on extracted_fact)
-- ----------------------------------------------
-- (a) `extracted_fact` is a hot write path (cron extract_program_facts +
--     16 fill_*.py ETLs). Adding a 96-byte BLOB column would inflate row
--     overhead on every read and a NULL default would defeat the point of
--     a tamper-evident signature (NULL = unsigned = ambiguous).
-- (b) Signatures are re-generated on amendment (refresh_fact_signatures_
--     weekly.py). Keeping them in a sidecar table lets the weekly cron
--     UPSERT without touching the canonical fact row's `last_modified`
--     timestamp — the fact didn't change, only its signature was renewed
--     under a new corpus snapshot.
-- (c) The 9.7 GB autonomath.db full-scan footgun (feedback_no_quick_check
--     _on_huge_sqlite memory): a separate small table keeps the signature
--     refresh job from pulling the full extracted_fact heap into cache.
--
-- Schema notes
-- ------------
-- * `ed25519_sig` BLOB(96): Ed25519 signature is 64 bytes raw; we reserve
--   96 to accommodate the deterministic encoding (8-byte version prefix +
--   64-byte sig + 8-byte key_id suffix used by the operator-side key
--   rotation scheme — see Bookyou株式会社 key custody runbook).
-- * `corpus_snapshot_id`: which snapshot was current when this signature
--   was produced. NULL allowed for legacy facts predating snapshotting.
-- * `signed_at` ISO-8601 UTC. Used for the (fact_id, signed_at DESC)
--   index so the verify endpoint always reads the latest valid signature
--   without an ORDER BY full-scan.
-- * `key_id` TEXT: short opaque key identifier (e.g., 'k20260512_a' for
--   the May 2026 rotation). Allows multi-key verify during rotation.
--
-- Source discipline
-- -----------------
-- No external API calls. The signing key lives in Fly secret `AUTONOMATH_
-- FACT_SIGN_PRIVATE_KEY` (Ed25519 private, never customer-visible). The
-- corresponding public key is exposed at GET /v1/audit/fact_pubkey for
-- third-party verify. NO LLM call in either sign or verify path.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/facts/{fact_id}/verify   — billable=1 (¥3 metered)
-- /v1/facts/{fact_id}/why      — billable=1 (¥3 metered)
--
-- Idempotency
-- -----------
-- CREATE TABLE / CREATE INDEX IF NOT EXISTS. No DML. Safe for boot-time
-- self-heal on every Fly machine restart.
--
-- DOWN
-- ----
-- See companion `262_fact_signature_v2_rollback.sql`.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_fact_signature (
    fact_id              TEXT PRIMARY KEY,
    ed25519_sig          BLOB NOT NULL,
    corpus_snapshot_id   TEXT,
    key_id               TEXT NOT NULL DEFAULT 'k20260512_a',
    signed_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    payload_sha256       TEXT NOT NULL,
    notes                TEXT,
    CONSTRAINT ck_am_fact_sig_size CHECK (length(ed25519_sig) <= 96),
    CONSTRAINT ck_am_fact_sig_min  CHECK (length(ed25519_sig) >= 64)
);

CREATE INDEX IF NOT EXISTS idx_am_fact_signature_lookup
    ON am_fact_signature(fact_id, signed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_fact_signature_snapshot
    ON am_fact_signature(corpus_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_am_fact_signature_keyid
    ON am_fact_signature(key_id);

DROP VIEW IF EXISTS v_am_fact_signature_latest;
CREATE VIEW v_am_fact_signature_latest AS
SELECT
    s.fact_id,
    s.ed25519_sig,
    s.corpus_snapshot_id,
    s.key_id,
    s.signed_at,
    s.payload_sha256
FROM am_fact_signature s;

COMMIT;
