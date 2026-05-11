-- target_db: autonomath
-- migration 200_invoice_status_history
--
-- T-番号 (適格請求書発行事業者) status change history. invoice_registrants
-- (and the mirrored jpi_invoice_registrants) hold the latest snapshot; this
-- table is the append-only audit trail of each registered / suspended /
-- deregistered / name_change / address_change event so artifacts can quote
-- "T-番号 has been live since YYYY-MM-DD, prior status was X" without
-- re-walking NTA bulk.
--
-- Why this exists:
--   turn5 §4 names invoice_status_history as a corpus part the
--   `invoice_tax_surface` artifact section needs. DATA-002 monthly NTA bulk
--   has all the rows needed (登録番号 / 登録年月日 / 失効年月日 / 各種変更
--   届), this table normalises them into one event log keyed by invoice_no
--   + status + observed_at.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `200_invoice_status_history_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS invoice_status_history (
    invoice_status_event_id TEXT PRIMARY KEY,
    invoice_no              TEXT NOT NULL,
    houjin_bangou           TEXT,
    event_kind              TEXT NOT NULL CHECK (event_kind IN (
                                'registered',
                                'suspended',
                                'reinstated',
                                'deregistered',
                                'name_change',
                                'address_change',
                                'representative_change',
                                'other'
                            )),
    event_at                TEXT,
    prior_status            TEXT,
    new_status              TEXT NOT NULL CHECK (new_status IN (
                                'active',
                                'suspended',
                                'deregistered',
                                'pending',
                                'unknown'
                            )),
    prior_value             TEXT,
    new_value               TEXT,
    bridge_id               TEXT,
    source_document_id      TEXT,
    confidence_score        REAL CHECK (
                                confidence_score IS NULL OR
                                (confidence_score >= 0.0 AND confidence_score <= 1.0)
                            ),
    known_gaps_json         TEXT NOT NULL DEFAULT '[]',
    observed_at             TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json           TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_invoice
    ON invoice_status_history(invoice_no, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_houjin
    ON invoice_status_history(houjin_bangou, event_at DESC)
    WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_kind
    ON invoice_status_history(event_kind, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_new_status
    ON invoice_status_history(new_status, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_bridge
    ON invoice_status_history(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_status_history_source
    ON invoice_status_history(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_status_history_event
    ON invoice_status_history(
        invoice_no,
        event_kind,
        COALESCE(event_at, ''),
        COALESCE(new_value, '')
    );

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
