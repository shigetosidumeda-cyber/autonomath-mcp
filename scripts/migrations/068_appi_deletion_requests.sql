-- migration 068: appi_deletion_requests
--
-- target_db: jpintel.db
--
-- Background:
--   APPI (個人情報の保護に関する法律) §33 grants the data subject a right to
--   request DELETION of personal data the operator holds about them — the
--   symmetrical right to §31 (disclosure, migration 066). Same P4 audit
--   (2026-04-25) flagged the same gBizINFO/NTA-sourced columns as
--   personal-data candidates: corp.representative / corp.location /
--   corp.postal_code / corp.phone / corp.company_url.
--
--   This table records every §33 deletion request received via
--   `POST /v1/privacy/deletion_request`. Operators (info@bookyou.net)
--   process the request manually within 30 days (§33-3 法定上限). We never
--   delete automatically — the endpoint only mints `request_id` and
--   notifies the operator + the requester. The actual deletion (or 不削除
--   reason) is delivered out-of-band after identity verification, and the
--   set of categories the operator actually deleted is recorded in
--   `deletion_completed_categories` at processing time.
--
--   See also docs/_internal/privacy_appi_31.md (operator runbook,
--   shared §31/§33 process).
--
-- Idempotency:
--   IF NOT EXISTS on table + indexes. Safe to re-apply via migrate.py and
--   via init_db() on a fresh test/dev DB (this DDL is mirrored at the
--   bottom of src/jpintel_mcp/db/schema.sql).
--
-- DOWN (commented — keep deletion-request history on rollback; APPI
-- requires a record of deletion requests for the legal retention window
-- so the operator can prove compliance with §33 SLA):
--   -- DROP INDEX IF EXISTS ix_appi_del_status;
--   -- DROP INDEX IF EXISTS ix_appi_del_received;
--   -- DROP TABLE IF EXISTS appi_deletion_requests;

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS appi_deletion_requests (
    request_id TEXT PRIMARY KEY,
    requester_email TEXT NOT NULL,
    requester_legal_name TEXT NOT NULL,
    target_houjin_bangou TEXT,
    target_data_categories TEXT NOT NULL,  -- JSON: ["representative", "address", "phone", ...]
    identity_verification_method TEXT NOT NULL,
    deletion_reason TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
    processed_at TEXT,
    processed_by TEXT,
    deletion_completed_categories TEXT  -- JSON of actually deleted categories
);

CREATE INDEX IF NOT EXISTS ix_appi_del_received
    ON appi_deletion_requests(received_at);

CREATE INDEX IF NOT EXISTS ix_appi_del_status
    ON appi_deletion_requests(status);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
