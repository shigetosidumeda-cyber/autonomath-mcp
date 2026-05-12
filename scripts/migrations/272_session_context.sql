-- target_db: autonomath
-- migration: 272_session_context
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim L (session_context_design) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Optional persistence layer for the Dim L contextual session surface
-- (`src/jpintel_mcp/api/session_context.py`, PR #144). The REST kernel
-- keeps its in-process `dict` primitive untouched — this migration only
-- adds two tables that an operator-side daemon can synchronise to so a
-- separate read-replica process (audit, billing reconciliation, restart
-- recovery) can inspect open sessions without touching the live handler.
--
-- The REST surface is NOT rewired to read/write SQL by this PR; sync is
-- an opt-in side-effect added in a follow-up wave so the in-process LRU
-- primitive remains the source of truth on each Fly machine.
--
-- Tables
-- ------
-- - am_session_context: row-per-open-session with state_token (PK),
--   saved_context JSON envelope (capped 16 KiB at REST surface), open
--   timestamp, expiry (24h TTL), and the most recent step timestamp.
-- - am_session_step_log: append-only per-step audit with request_hash +
--   response_hash so a downstream reconciliation pass can replay a step
--   sequence without keeping the raw payload (Dim N — k=5 anonymity).
--
-- Why TWO tables (not one)
-- ------------------------
-- - am_session_context: small, capped at ~10,000 sessions/process (the
--   in-process LRU bound). Read-heavy on state_token lookup.
-- - am_session_step_log: append-only, grows with traffic. Indexed by
--   session_id + step_index for replay; by request_hash for forensics.
-- Mixing both would force a scan of every step on every state-token
-- read, defeating the LRU primitive's O(1) access pattern.
--
-- 24h TTL discipline
-- ------------------
-- SESSION_TTL_SEC (REST kernel) = 24h. `expires_at` mirrors that exact
-- value at insert. The `clean_session_context_expired.py` daily ETL
-- purges any row where `expires_at < strftime('%s','now')`.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/session/{open,step,close} each remain 1 metered unit (the per-call
-- invariant documented in session_context.py). This audit layer is
-- internal — no customer-facing read path here.
--
-- Retention
-- ---------
-- am_session_context: 24h sliding (TTL purge daily).
-- am_session_step_log: 7-day rolling window swept by the same cleanup
-- pass; longer retention violates Dim L "conversation glue, not durable
-- state" stance (per feedback_session_context_design).
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST
-- surface envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_session_context (
    session_id        TEXT PRIMARY KEY,                      -- state_token (hex 32)
    state_token       TEXT NOT NULL,                         -- redundant column for index symmetry
    saved_context     TEXT NOT NULL DEFAULT '{}',            -- JSON envelope, <= 16 KiB
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at        INTEGER NOT NULL,                      -- epoch seconds (created + 24h)
    last_step_at      INTEGER,                               -- epoch seconds; NULL if no step yet
    closed_at         INTEGER,                               -- epoch seconds; NULL while open
    status            TEXT NOT NULL DEFAULT 'open'           -- open / closed / expired
                      CHECK (status IN ('open','closed','expired')),
    CHECK (length(saved_context) <= 16384),
    CHECK (length(state_token) = 32)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_am_session_context_token
    ON am_session_context(state_token);

CREATE INDEX IF NOT EXISTS idx_am_session_context_expires
    ON am_session_context(expires_at);

CREATE INDEX IF NOT EXISTS idx_am_session_context_status_expires
    ON am_session_context(status, expires_at);

-- Helper view: rows that are still alive (status=open AND not expired).
DROP VIEW IF EXISTS v_session_context_alive;
CREATE VIEW v_session_context_alive AS
SELECT
    session_id,
    state_token,
    created_at,
    expires_at,
    last_step_at,
    saved_context
FROM am_session_context
WHERE status = 'open'
  AND expires_at > strftime('%s','now');

-- Append-only per-step audit log.
CREATE TABLE IF NOT EXISTS am_session_step_log (
    step_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL,
    step_index        INTEGER NOT NULL                        -- 1-based ordinal within session
                      CHECK (step_index >= 1),
    request_hash      TEXT NOT NULL,                          -- sha256 of canonical request body
    response_hash     TEXT NOT NULL,                          -- sha256 of canonical response body
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (session_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_am_session_step_log_session_step
    ON am_session_step_log(session_id, step_index);

CREATE INDEX IF NOT EXISTS idx_am_session_step_log_request_hash
    ON am_session_step_log(request_hash);

CREATE INDEX IF NOT EXISTS idx_am_session_step_log_created
    ON am_session_step_log(created_at);

COMMIT;
