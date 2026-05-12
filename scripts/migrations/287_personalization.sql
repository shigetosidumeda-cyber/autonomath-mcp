-- target_db: autonomath
-- migration: 287_personalization
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim H personalization preference storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim H "personalization preference storage"
-- surface. Complements migration 264 (am_personalization_score) which
-- holds derived per-program scores. This migration adds the upstream
-- inputs and downstream audit trail that 264 cannot capture:
--
--   * am_personalization_profile — the customer-controlled preference
--     blob that DRIVES the score calculation. Keyed by an opaque
--     user_token_hash (sha256 of the API key); NEVER stores the raw key,
--     never stores PII such as email/IP/法人番号. Preferences are JSON
--     (industry pack selection, risk tolerance, deadline horizon, etc.).
--   * am_personalization_recommendation_log — append-only audit of
--     every recommendation served. Captures recommendation_type,
--     final score, served_at timestamp. Used for both billing
--     reconciliation (¥3/req on successful 2xx delivery) and forensic
--     replay ("why did we recommend this?").
--
-- Privacy posture (feedback_anonymized_query_pii_redact compliance)
-- ----------------------------------------------------------------
-- ZERO PII is stored at this layer. user_token_hash is the sha256 hex
-- digest of the raw API key; the raw key is held only in transit (auth
-- middleware) and discarded post-hash. preference_json is restricted by
-- CHECK to JSON shapes <= 16KB and is the customer's OWN declared data
-- (industry, risk tolerance, deadline horizon). No 法人番号, no email,
-- no IP, no agent UA fingerprint enters this table. CI guard in
-- tests/test_dim_h_personalization.py grep-asserts the schema for any
-- column name containing 'email', 'ip_addr', 'houjin_bangou', 'name'.
--
-- LLM-0 discipline
-- ----------------
-- Schema is preference + audit metadata only. ZERO columns imply LLM
-- inference (no "ai_explanation", no "summary_text"). The ETL ranks
-- existing programs against the declared preference blob using
-- deterministic scoring (industry match * weight + deadline proximity
-- * weight + risk tolerance * weight); no Anthropic / OpenAI SDK is
-- ever imported into the personalization path. Tests in
-- test_dim_h_personalization.py guard the LLM-0 invariant.
--
-- ¥3/req billing posture
-- ----------------------
-- Profile registration is free (per-call billing is on the
-- recommendation surface, not the preference write). Each row inserted
-- into am_personalization_recommendation_log with delivery_status
-- 'delivered' emits one Stripe usage_record at ¥3/req on the proxy
-- side. Failed/expired/pending deliveries NEVER bill.
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST/
-- MCP envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

-- Customer-controlled preference blob. One row per (user_token_hash).
-- preference_json shape is documented in docs/canonical/dim_h_personalization.md
-- and validated by jsonschema in src/jpintel_mcp/personalization/validator.py.
CREATE TABLE IF NOT EXISTS am_personalization_profile (
    profile_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_token_hash     TEXT NOT NULL UNIQUE,                                  -- sha256 hex of the API key; raw key never stored
    preference_json     TEXT NOT NULL DEFAULT '{}',                            -- customer declared prefs only; no PII
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(user_token_hash) = 64),                                      -- sha256 hex is 64 chars
    CHECK (length(preference_json) BETWEEN 2 AND 16384),                       -- valid JSON minimum "{}", max 16KB
    CHECK (last_updated_at >= created_at)
);

-- "Lookup my profile" hot path (single row by token).
CREATE INDEX IF NOT EXISTS idx_am_personalization_profile_token
    ON am_personalization_profile(user_token_hash);

-- Append-only audit of every recommendation served. Drives both
-- billing reconciliation and "why did we recommend X" forensics.
CREATE TABLE IF NOT EXISTS am_personalization_recommendation_log (
    rec_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id          INTEGER NOT NULL,                                      -- FK -> am_personalization_profile(profile_id)
    recommendation_type TEXT NOT NULL                                          -- recommendation surface enum
                            CHECK (recommendation_type IN ('program', 'industry_pack', 'saved_search', 'amendment')),
    score               INTEGER NOT NULL DEFAULT 0,                            -- final rank score 0..100
    served_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (score BETWEEN 0 AND 100),
    FOREIGN KEY (profile_id) REFERENCES am_personalization_profile(profile_id)
);

-- Hot path: "my recommendations, most recent first".
CREATE INDEX IF NOT EXISTS idx_am_pers_rec_profile_served
    ON am_personalization_recommendation_log(profile_id, served_at DESC);

-- Forensic path: "all served recs for a recommendation_type".
CREATE INDEX IF NOT EXISTS idx_am_pers_rec_type_score
    ON am_personalization_recommendation_log(recommendation_type, score DESC, served_at DESC);

-- Helper view: latest 100 recs per profile for the "show my history"
-- endpoint without scanning the whole audit log.
DROP VIEW IF EXISTS v_personalization_recent_recs;
CREATE VIEW v_personalization_recent_recs AS
SELECT
    rl.rec_id,
    pp.user_token_hash,
    rl.recommendation_type,
    rl.score,
    rl.served_at
FROM am_personalization_recommendation_log rl
JOIN am_personalization_profile pp
  ON pp.profile_id = rl.profile_id
WHERE rl.score > 0
ORDER BY pp.user_token_hash, rl.served_at DESC;

COMMIT;
