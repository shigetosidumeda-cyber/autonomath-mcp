-- migration 054: appi_disclosure_requests
--
-- target_db: jpintel.db
--
-- Background:
--   APPI (個人情報の保護に関する法律) §31 grants the data subject a right to
--   request disclosure of personal data the operator holds about them. P4
--   audit (2026-04-25) flagged that `corp.representative` (5,904 rows) /
--   `corp.location` (121,881) / `corp.postal_code` (121,878) /
--   `corp.company_url` (7,136) sourced from gBizINFO + NTA can include
--   information the data subject considers personal — primarily for
--   sole-proprietor 法人 and small 同族会社 where 代表者 + 所在地 are the
--   data subject's own home / name.
--
--   This table records every §31 disclosure request received via
--   `POST /v1/privacy/disclosure_request`. Operators (info@bookyou.net)
--   process the request manually within 14 days. We never disclose
--   automatically — the endpoint only mints `request_id` and notifies the
--   operator + the requester. The actual disclosure (or 不開示 reason) is
--   delivered out-of-band after identity verification.
--
--   See also docs/_internal/privacy_appi_31.md (operator runbook).
--
-- Idempotency:
--   IF NOT EXISTS on table + index. Safe to re-apply via migrate.py and via
--   init_db() on a fresh test/dev DB (this DDL is mirrored at the bottom of
--   src/jpintel_mcp/db/schema.sql).
--
-- DOWN (commented — keep request history on rollback; APPI requires a
-- record of disclosure requests for the legal retention window):
--   -- DROP INDEX IF EXISTS ix_appi_disclosure_requests_received_at;
--   -- DROP INDEX IF EXISTS ix_appi_disclosure_requests_status;
--   -- DROP TABLE IF EXISTS appi_disclosure_requests;

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS appi_disclosure_requests (
    request_id TEXT PRIMARY KEY,
    requester_email TEXT NOT NULL,
    requester_legal_name TEXT NOT NULL,
    target_houjin_bangou TEXT,
    identity_verification_method TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
    processed_at TEXT,
    processed_by TEXT
);

CREATE INDEX IF NOT EXISTS ix_appi_disclosure_requests_received_at
    ON appi_disclosure_requests(received_at DESC);

CREATE INDEX IF NOT EXISTS ix_appi_disclosure_requests_status
    ON appi_disclosure_requests(status);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
