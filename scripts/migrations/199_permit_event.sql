-- target_db: autonomath
-- migration 199_permit_event
--
-- Per-permit event audit trail: issued / renewed / amended / suspended /
-- revoked / expired / status_change. Each row carries the event_at stamp,
-- prior_status / new_status, optional amount_yen (for refund-style permit
-- consequences), source_document_id, and known_gaps_json. The registry
-- holds the latest state; this table is the time-series the registry was
-- derived from and lets DD artifacts walk a permit's history.
--
-- Why this exists:
--   blueprint §4 P0 ETL DATA-006 needs the permit_risk artifact section to
--   quote the prior 5 years of status transitions. permit_registry can
--   only hold the latest snapshot; permit_event is the append-only history.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `199_permit_event_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS permit_event (
    permit_event_id      TEXT PRIMARY KEY,
    permit_registry_id   TEXT,
    permit_no            TEXT NOT NULL,
    issuing_authority    TEXT NOT NULL,
    event_kind           TEXT NOT NULL CHECK (event_kind IN (
                             'issued',
                             'renewed',
                             'amended',
                             'suspended',
                             'revoked',
                             'expired',
                             'lapsed',
                             'status_change',
                             'transfer',
                             'other'
                         )),
    event_at             TEXT,
    prior_status         TEXT,
    new_status           TEXT,
    holder_houjin_bangou TEXT,
    reason_text          TEXT,
    amount_yen           INTEGER CHECK (amount_yen IS NULL OR amount_yen >= 0),
    bridge_id            TEXT,
    source_document_id   TEXT,
    confidence_score     REAL CHECK (
                             confidence_score IS NULL OR
                             (confidence_score >= 0.0 AND confidence_score <= 1.0)
                         ),
    known_gaps_json      TEXT NOT NULL DEFAULT '[]',
    observed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_permit_event_registry
    ON permit_event(permit_registry_id, event_at DESC)
    WHERE permit_registry_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_permit_event_permit_no
    ON permit_event(permit_no, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_permit_event_authority_kind
    ON permit_event(issuing_authority, event_kind, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_permit_event_holder
    ON permit_event(holder_houjin_bangou, event_at DESC)
    WHERE holder_houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_permit_event_bridge
    ON permit_event(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_permit_event_source
    ON permit_event(source_document_id)
    WHERE source_document_id IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
