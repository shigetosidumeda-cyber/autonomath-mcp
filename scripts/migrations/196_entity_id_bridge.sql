-- target_db: autonomath
-- migration 196_entity_id_bridge
--
-- Primary bridge table that ties non-houjin-number IDs into a single spine.
-- Each row records one observed equivalence among houjin_bangou / invoice_no
-- (T-番号) / EDINET code / permit_no (許認可番号) / procurement_id (調達契約
-- 番号) / law_id with valid_from / valid_to so the join can be replayed by
-- date and superseded when the upstream re-issues an ID.
--
-- Why this exists:
--   ai_professional_public_layer_implementation_blueprint_2026-05-06.md §4
--   Entity bridge namespace, paid_product_value_strategy_data_expansion_turn5
--   _2026-05-08.md §4 existing parts (entity_resolution_bridge_v2 already on
--   disk, this is the canonical replacement scoped at the public-corpus
--   foundation layer). Lets every artifact section quote a single bridge row
--   plus a confidence_score and source_document_id without re-resolving.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `196_entity_id_bridge_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity_id_bridge (
    bridge_id            TEXT PRIMARY KEY,
    houjin_bangou        TEXT,
    invoice_no           TEXT,
    edinet_code          TEXT,
    permit_no            TEXT,
    procurement_id       TEXT,
    law_id               TEXT,
    bridge_type          TEXT NOT NULL CHECK (bridge_type IN (
                             'houjin_to_invoice',
                             'houjin_to_edinet',
                             'houjin_to_permit',
                             'houjin_to_procurement',
                             'houjin_to_law',
                             'invoice_to_edinet',
                             'invoice_to_permit',
                             'permit_to_procurement',
                             'law_to_permit',
                             'cross_namespace',
                             'self_alias',
                             'other'
                         )),
    valid_from           TEXT,
    valid_to             TEXT,
    source_document_id   TEXT,
    confidence_score     REAL CHECK (
                             confidence_score IS NULL OR
                             (confidence_score >= 0.0 AND confidence_score <= 1.0)
                         ),
    observed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_by        TEXT,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    CHECK (
        valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
    )
);

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_houjin
    ON entity_id_bridge(houjin_bangou)
    WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_invoice
    ON entity_id_bridge(invoice_no)
    WHERE invoice_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_edinet
    ON entity_id_bridge(edinet_code)
    WHERE edinet_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_permit
    ON entity_id_bridge(permit_no)
    WHERE permit_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_procurement
    ON entity_id_bridge(procurement_id)
    WHERE procurement_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_law
    ON entity_id_bridge(law_id)
    WHERE law_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_validity
    ON entity_id_bridge(valid_from, valid_to)
    WHERE valid_from IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_id_bridge_natural_key
    ON entity_id_bridge(
        bridge_type,
        COALESCE(houjin_bangou, ''),
        COALESCE(invoice_no, ''),
        COALESCE(edinet_code, ''),
        COALESCE(permit_no, ''),
        COALESCE(procurement_id, ''),
        COALESCE(law_id, ''),
        COALESCE(valid_from, '')
    );

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
