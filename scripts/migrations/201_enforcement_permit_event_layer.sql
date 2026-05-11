-- target_db: autonomath
-- migration 201_enforcement_permit_event_layer
--
-- VIEW that unifies am_enforcement_detail (行政処分 corpus) with permit_event
-- (allow / suspend / revoke), so the `risk_angles` / `permit_risk` artifact
-- sections can read one ledger keyed by houjin_bangou + event_at instead
-- of joining 2 tables on every request. Each row carries its origin_table
-- discriminator so consumers can filter to one half if needed.
--
-- Why this exists:
--   blueprint §4 + turn5 §4 both want a single "enforcement + permit"
--   timeline per houjin. am_enforcement_detail covers 行政処分; permit_event
--   covers 許認可 issuance/withdrawal. Together they are the "this party
--   has had X actions against it" surface. A VIEW (no extra storage) keeps
--   the upstream tables canonical while giving artifacts one query path.
--
-- Idempotency:
--   CREATE VIEW IF NOT EXISTS. No seed data, no schema mutation.
--   am_enforcement_detail is created by earlier wave migrations; columns
--   referenced here are intersection columns that have existed since the
--   v15 unification. If any column is missing on a slim test DB, the VIEW
--   itself will still create but queries against it will error - acceptable
--   for a derivation layer.
--
-- DOWN:
--   See companion `201_enforcement_permit_event_layer_rollback.sql`.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS am_enforcement_detail (
    enforcement_id      TEXT PRIMARY KEY,
    houjin_bangou       TEXT,
    enforcement_kind    TEXT,
    occurred_at         TEXT,
    authority           TEXT,
    amount_yen          INTEGER,
    source_url          TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS permit_event (
    permit_event_id      TEXT PRIMARY KEY,
    permit_registry_id   TEXT,
    permit_no            TEXT NOT NULL,
    issuing_authority    TEXT,
    event_kind           TEXT,
    event_at             TEXT,
    new_status           TEXT,
    holder_houjin_bangou TEXT,
    amount_yen           INTEGER,
    bridge_id            TEXT,
    source_document_id   TEXT,
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE VIEW IF NOT EXISTS v_enforcement_permit_event_layer AS
    SELECT
        'enforcement'                         AS origin_table,
        ed.enforcement_id                     AS event_id,
        ed.houjin_bangou                      AS houjin_bangou,
        ed.enforcement_kind                   AS event_kind,
        ed.occurred_at                        AS event_at,
        ed.authority                          AS authority,
        NULL                                  AS permit_no,
        NULL                                  AS new_status,
        ed.amount_yen                         AS amount_yen,
        ed.source_url                         AS source_url,
        NULL                                  AS bridge_id,
        NULL                                  AS source_document_id,
        ed.metadata_json                      AS metadata_json
    FROM am_enforcement_detail AS ed
    UNION ALL
    SELECT
        'permit_event'                        AS origin_table,
        pe.permit_event_id                    AS event_id,
        pe.holder_houjin_bangou               AS houjin_bangou,
        pe.event_kind                         AS event_kind,
        pe.event_at                           AS event_at,
        pe.issuing_authority                  AS authority,
        pe.permit_no                          AS permit_no,
        pe.new_status                         AS new_status,
        pe.amount_yen                         AS amount_yen,
        NULL                                  AS source_url,
        pe.bridge_id                          AS bridge_id,
        pe.source_document_id                 AS source_document_id,
        pe.metadata_json                      AS metadata_json
    FROM permit_event AS pe;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
