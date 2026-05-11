-- target_db: autonomath
-- migration 198_permit_registry
--
-- Permit (許認可) master registry: one row per active permit identity, keyed
-- by issuing authority + permit_no. Carries holder identity (houjin_bangou +
-- name + address), permit_type (建設業 / 産廃 / 介護 / 運送 / 飲食 / 不動産 /
-- 旅行業 / 警備業 / 等), issued/expiry dates, status, and a bridge_id back
-- to entity_id_bridge so permit_to_houjin lookups stay one query.
--
-- Why this exists:
--   blueprint §4 P0 ETL DATA-006 surfaces permit risk via this registry +
--   permit_event (199). Without it, "is this contractor's permit still
--   live?" requires fanning out to MHLW / MLIT / METI portals on every
--   request. The registry caches the latest known state, permit_event keeps
--   the audit trail.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `198_permit_registry_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS permit_registry (
    permit_registry_id   TEXT PRIMARY KEY,
    permit_no            TEXT NOT NULL,
    issuing_authority    TEXT NOT NULL,
    permit_type          TEXT NOT NULL,
    permit_category      TEXT,
    holder_houjin_bangou TEXT,
    holder_name          TEXT,
    holder_address       TEXT,
    prefecture_code      TEXT,
    issued_at            TEXT,
    expires_at           TEXT,
    renewed_at           TEXT,
    status               TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN (
                             'active',
                             'suspended',
                             'revoked',
                             'expired',
                             'pending',
                             'lapsed',
                             'unknown'
                         )),
    bridge_id            TEXT,
    source_document_id   TEXT,
    last_verified_at     TEXT,
    confidence_score     REAL CHECK (
                             confidence_score IS NULL OR
                             (confidence_score >= 0.0 AND confidence_score <= 1.0)
                         ),
    known_gaps_json      TEXT NOT NULL DEFAULT '[]',
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_permit_registry_no
    ON permit_registry(permit_no);

CREATE INDEX IF NOT EXISTS idx_permit_registry_authority_type
    ON permit_registry(issuing_authority, permit_type);

CREATE INDEX IF NOT EXISTS idx_permit_registry_holder_houjin
    ON permit_registry(holder_houjin_bangou)
    WHERE holder_houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_permit_registry_prefecture
    ON permit_registry(prefecture_code, permit_type)
    WHERE prefecture_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_permit_registry_status_expires
    ON permit_registry(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_permit_registry_bridge
    ON permit_registry(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_permit_registry_natural_key
    ON permit_registry(issuing_authority, permit_no, permit_type);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
