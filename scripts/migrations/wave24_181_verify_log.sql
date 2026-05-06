-- target_db: autonomath
-- migration: wave24_181_verify_log
-- generated_at: 2026-05-07
-- author: DEEP-25 + DEEP-37 verifiable answer primitive
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Audit log for the `POST /v1/verify/answer` endpoint (DEEP-25).
-- Each row captures one verify call so that:
--   1. anonymous-IP rate limit (3 req/day) and api_key billable counters
--      can be cross-referenced post-hoc when a customer disputes ¥3 charges.
--   2. accuracy regression on `sources_match` / `boundary_clean` axes can
--      be measured against ground-truth fixtures without re-replaying
--      production calls (answer_hash is the dedup key).
--   3. boundary_violations_count > 0 rows can be sampled by the operator
--      for §52 / §72 / §1 fence calibration drift.
--
-- Retention
-- ---------
-- Default 90 days. Hard cap 1 year. `scripts/cron/expire_verify_log.py`
-- runs daily and deletes rows older than 90 days. APPI 配慮 — `client_ip_hash`
-- is salted sha256, never raw IP.
--
-- LLM call: 0. Pure SQLite write from `_verifier.py` after the synchronous
-- 4-axis score is computed.
--
-- Field semantics
-- ---------------
-- request_id            UUIDv4 generated server-side, primary key.
-- answer_hash           sha256(answer_text) hex, dedup + audit.
-- score                 0-100 integer, 4-axis weighted (DEEP-37 §2.5).
-- per_claim_json        JSON array of ClaimResult (verbatim response field).
-- source_alive_count    Count of source URLs that returned 2xx/3xx HEAD.
-- source_dead_count     Count of source URLs that returned 4xx/5xx or timeout.
-- boundary_violations_count  Count of detected business-law fence violations.
-- boundary_violations_json   nullable JSON array of Violation records.
-- language              'ja' or 'en' — matches request body.
-- api_key_id            nullable; NULL = anonymous tier.
-- client_ip_hash        salted sha256, never raw IP. Empty string allowed
--                       when X-Forwarded-For is missing (test harness).
-- created_at            ISO 8601 UTC timestamp (server clock).

CREATE TABLE IF NOT EXISTS verify_log (
  request_id TEXT PRIMARY KEY,
  answer_hash TEXT NOT NULL,
  score INTEGER NOT NULL,
  per_claim_json TEXT NOT NULL,
  source_alive_count INTEGER NOT NULL DEFAULT 0,
  source_dead_count INTEGER NOT NULL DEFAULT 0,
  boundary_violations_count INTEGER NOT NULL DEFAULT 0,
  boundary_violations_json TEXT,
  language TEXT NOT NULL DEFAULT 'ja' CHECK(language IN ('ja','en')),
  api_key_id INTEGER,
  client_ip_hash TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_verify_log_created_at ON verify_log(created_at);
CREATE INDEX IF NOT EXISTS ix_verify_log_answer_hash ON verify_log(answer_hash);
CREATE INDEX IF NOT EXISTS ix_verify_log_api_key_id ON verify_log(api_key_id);
CREATE INDEX IF NOT EXISTS ix_verify_log_score ON verify_log(score);
CREATE INDEX IF NOT EXISTS ix_verify_log_boundary_count ON verify_log(boundary_violations_count);
