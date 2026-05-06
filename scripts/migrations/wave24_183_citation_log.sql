-- target_db: autonomath
-- migration: wave24_183_citation_log
-- generated_at: 2026-05-07
-- author: DEEP-27 citation badge widget (CL-08)
-- idempotent: every CREATE uses IF NOT EXISTS; safe under entrypoint.sh §4 self-heal loop.
--
-- Purpose
-- -------
-- Persistent log for the `jpcite verified` badge widget. Every metered
-- ¥3 call mints a UUIDv4 `request_id`; that id is the primary key here
-- and is the canonical link between:
--   * `widget.jpcite.com/badge.svg?request_id={UUID}` (Cloudflare Worker
--     SVG endpoint, 4 visual states),
--   * `jpcite.com/citation/{REQUEST_ID}`              (static MD page on
--     Cloudflare Pages, generated at receipt-creation time),
--   * the originating tool response in `audit_seal` (mig 089).
--
-- Verified status enum (4 states):
--   verified       — fresh row, HMAC valid, within ttl_days.
--   expired        — created_at older than ttl_days (default 90 d) OR
--                    customer-page 404 detected by weekly crawler.
--   invalid        — HMAC mismatch (badge tampered) or row never existed.
--   boundary_warn  — forbidden_phrase detected within 500 chars of the
--                    badge on the customer page (DEEP-23 fence).
--
-- Retention
-- ---------
-- ttl_days defaults to 90 d. `scripts/cron/expire_trials.py` (or its
-- DEEP-27 neighbor `expire_verify_log.py`) flips
-- `verified_status='expired'` for rows older than ttl_days. Rows are
-- never deleted — the citation page itself is permanent corpus history;
-- the SVG simply renders grey when expired.
--
-- LLM call: 0. The migration is pure DDL; the cron worker that updates
-- verified_status is also pure SQLite + httpx HEAD + regex.
--
-- APPI posture
-- ------------
-- `answer_text` is scrubbed (1) by the response sanitizer before any
-- corpus write and (2) again here, capped at 4 KB. PII patterns
-- (個人マイナンバー / 電話 / email / 番地 / カード番号) are redacted to
-- placeholders before INSERT — see the `_scrubber` regex set in
-- `src/jpintel_mcp/api/citation_badge.py` Scrub() helper.
-- 法人番号 / 郵便番号 / 都道府県 / 市区町村 are PUBLIC info and never
-- redacted here.

CREATE TABLE IF NOT EXISTS citation_log (
  request_id      TEXT PRIMARY KEY,
  api_key_id      INTEGER,
  answer_text     TEXT CHECK(length(answer_text) <= 4096),
  source_urls     TEXT NOT NULL DEFAULT '[]',
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  verified_status TEXT NOT NULL DEFAULT 'verified'
                  CHECK(verified_status IN ('verified','expired','invalid','boundary_warn')),
  ttl_days        INTEGER NOT NULL DEFAULT 90 CHECK(ttl_days > 0)
);

CREATE INDEX IF NOT EXISTS idx_citation_log_created  ON citation_log(created_at);
CREATE INDEX IF NOT EXISTS idx_citation_log_status   ON citation_log(verified_status);
CREATE INDEX IF NOT EXISTS idx_citation_log_api_key  ON citation_log(api_key_id);
