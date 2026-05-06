-- target_db: autonomath
-- migration 176_source_foundation_domain_tables
--
-- Schema-only receivers for the first public-source domain slices promoted
-- from the 2026-05-06 SourceProfile backlog.
--
-- Why this exists:
--   The foundation ledgers in 172-175 store snapshots, artifacts, source
--   documents, and extracted facts. Several high-value sources also need
--   source-shaped domain rows before they can safely power paid artifacts:
--
--     * NTA corporate-number change history for entity-spine drift.
--     * Ministry enforcement source rows linked back to am_enforcement_detail.
--     * e-Gov law revision and attachment metadata without mutating laws/am_law.
--     * p-portal award rows as a child of canonical bids, for multi-winner
--       detail that does not fit the existing one-row bid surface.
--
--   These tables deliberately avoid making a second canonical copy of
--   existing runtime tables. They are source/companion tables that offline
--   builders can reconcile into the current API-facing tables.
--
-- Schema notes:
--   * JSON arrays/objects are serialized TEXT.
--   * source_document_id, artifact_id, corpus_snapshot_id, enforcement_id,
--     entity_id, bid_unified_id, law_canonical_id, and law_unified_id are
--     soft references so the migration remains independently idempotent.
--   * No customer-private material is stored here.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `176_source_foundation_domain_tables_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS houjin_change_history (
    history_id                 TEXT PRIMARY KEY,
    houjin_bangou              TEXT NOT NULL CHECK (
                                   length(houjin_bangou) = 13 AND
                                   houjin_bangou NOT GLOB '*[^0-9]*'
                               ),
    sequence_number            INTEGER CHECK (sequence_number IS NULL OR sequence_number >= 0),
    change_date                TEXT,
    process                    TEXT,
    correct                    TEXT,
    before_value_json          TEXT NOT NULL DEFAULT '{}',
    after_value_json           TEXT NOT NULL DEFAULT '{}',
    raw_row_json               TEXT NOT NULL DEFAULT '{}',
    diff_zip_filename          TEXT,
    source_row_hash            TEXT,
    source_url                 TEXT,
    source_checksum            TEXT,
    source_document_id         TEXT,
    corpus_snapshot_id         TEXT,
    fetched_at                 TEXT,
    pgp_signature_verified     INTEGER CHECK (
                                   pgp_signature_verified IS NULL OR
                                   pgp_signature_verified IN (0, 1)
                               ),
    application_id_used        TEXT,
    known_gaps_json            TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_houjin_change_history_houjin_date
    ON houjin_change_history(houjin_bangou, change_date DESC);

CREATE INDEX IF NOT EXISTS idx_houjin_change_history_change_process
    ON houjin_change_history(change_date, process);

CREATE INDEX IF NOT EXISTS idx_houjin_change_history_source_checksum
    ON houjin_change_history(source_checksum)
    WHERE source_checksum IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_houjin_change_history_source_document
    ON houjin_change_history(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_houjin_change_history_snapshot
    ON houjin_change_history(corpus_snapshot_id)
    WHERE corpus_snapshot_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_houjin_change_history_source_row_hash
    ON houjin_change_history(source_row_hash)
    WHERE source_row_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_houjin_change_history_diff_sequence
    ON houjin_change_history(diff_zip_filename, sequence_number)
    WHERE diff_zip_filename IS NOT NULL AND sequence_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS houjin_master_refresh_run (
    refresh_run_id             TEXT PRIMARY KEY,
    source_id                  TEXT NOT NULL DEFAULT 'nta_houjin_bangou' CHECK (
                                   length(source_id) BETWEEN 3 AND 80 AND
                                   source_id NOT GLOB '*[^a-z0-9_]*'
                               ),
    acquisition_method         TEXT NOT NULL CHECK (acquisition_method IN (
                                   'bulk_csv','diff_zip','webapi','manual',
                                   'backfill','other'
                               )),
    started_at                 TEXT NOT NULL,
    finished_at                TEXT,
    status                     TEXT NOT NULL CHECK (status IN (
                                   'started','succeeded','failed','partial'
                               )),
    row_count                  INTEGER CHECK (row_count IS NULL OR row_count >= 0),
    inserted_count             INTEGER CHECK (inserted_count IS NULL OR inserted_count >= 0),
    updated_count              INTEGER CHECK (updated_count IS NULL OR updated_count >= 0),
    unchanged_count            INTEGER CHECK (unchanged_count IS NULL OR unchanged_count >= 0),
    deleted_count              INTEGER CHECK (deleted_count IS NULL OR deleted_count >= 0),
    source_url                 TEXT,
    source_checksum            TEXT,
    source_document_id         TEXT,
    artifact_id                TEXT,
    corpus_snapshot_id         TEXT,
    pgp_signature_verified     INTEGER CHECK (
                                   pgp_signature_verified IS NULL OR
                                   pgp_signature_verified IN (0, 1)
                               ),
    application_id_used        TEXT,
    known_gaps_json            TEXT NOT NULL DEFAULT '[]',
    metadata_json              TEXT NOT NULL DEFAULT '{}',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_houjin_master_refresh_run_source_time
    ON houjin_master_refresh_run(source_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_houjin_master_refresh_run_status
    ON houjin_master_refresh_run(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_houjin_master_refresh_run_snapshot
    ON houjin_master_refresh_run(corpus_snapshot_id)
    WHERE corpus_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_houjin_master_refresh_run_source_document
    ON houjin_master_refresh_run(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_houjin_master_refresh_run_artifact
    ON houjin_master_refresh_run(artifact_id)
    WHERE artifact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS am_enforcement_source_index (
    source_index_id            TEXT PRIMARY KEY,
    source_id                  TEXT NOT NULL CHECK (
                                   length(source_id) BETWEEN 3 AND 80 AND
                                   source_id NOT GLOB '*[^a-z0-9_]*'
                               ),
    source_action_id           TEXT,
    source_document_id         TEXT,
    artifact_id                TEXT,
    enforcement_id             TEXT,
    entity_id                  TEXT,
    houjin_bangou              TEXT CHECK (
                                   houjin_bangou IS NULL OR (
                                       length(houjin_bangou) = 13 AND
                                       houjin_bangou NOT GLOB '*[^0-9]*'
                                   )
                               ),
    corp_name_normalized       TEXT,
    respondent_name            TEXT NOT NULL,
    respondent_kind            TEXT NOT NULL DEFAULT 'unknown' CHECK (respondent_kind IN (
                                   'corporation','individual','government',
                                   'organization','unknown','other'
                               )),
    authority                  TEXT,
    authority_code             TEXT,
    bureau                     TEXT,
    sector_category            TEXT,
    permit_no                  TEXT,
    publication_date           TEXT,
    action_date                TEXT,
    action_kind_raw            TEXT,
    enforcement_kind           TEXT,
    legal_basis                TEXT,
    reason_summary             TEXT,
    amount_yen                 INTEGER CHECK (amount_yen IS NULL OR amount_yen >= 0),
    period_start               TEXT,
    period_end                 TEXT,
    as_of_date                 TEXT,
    source_url                 TEXT,
    content_hash               TEXT,
    fetched_at                 TEXT,
    raw_json                   TEXT NOT NULL DEFAULT '{}',
    known_gaps_json            TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_aesi_source_action
    ON am_enforcement_source_index(source_id, source_action_id)
    WHERE source_action_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aesi_enforcement
    ON am_enforcement_source_index(enforcement_id)
    WHERE enforcement_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aesi_entity
    ON am_enforcement_source_index(entity_id)
    WHERE entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aesi_houjin_dates
    ON am_enforcement_source_index(houjin_bangou, action_date DESC, publication_date DESC)
    WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aesi_source_dates
    ON am_enforcement_source_index(source_id, action_date DESC, publication_date DESC);

CREATE INDEX IF NOT EXISTS idx_aesi_authority_sector
    ON am_enforcement_source_index(authority, sector_category);

CREATE INDEX IF NOT EXISTS idx_aesi_permit
    ON am_enforcement_source_index(permit_no)
    WHERE permit_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aesi_source_document
    ON am_enforcement_source_index(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS law_revisions (
    law_revision_id                     TEXT PRIMARY KEY,
    law_id                              TEXT NOT NULL,
    law_num                             TEXT,
    law_canonical_id                    TEXT,
    law_unified_id                      TEXT,
    law_title                           TEXT,
    amendment_promulgate_date           TEXT,
    amendment_enforcement_date          TEXT,
    amendment_scheduled_enforcement_date TEXT,
    amendment_enforcement_comment       TEXT,
    amendment_law_id                    TEXT,
    amendment_law_num                   TEXT,
    amendment_law_title                 TEXT,
    amendment_type                      TEXT,
    mission                             TEXT,
    repeal_status                       TEXT,
    repeal_date                         TEXT,
    remain_in_force                     INTEGER CHECK (
                                            remain_in_force IS NULL OR
                                            remain_in_force IN (0, 1)
                                        ),
    current_revision_status             TEXT,
    source_url                          TEXT,
    source_document_id                  TEXT,
    corpus_snapshot_id                  TEXT,
    fetched_at                          TEXT,
    content_hash                        TEXT,
    raw_json                            TEXT NOT NULL DEFAULT '{}',
    known_gaps_json                     TEXT NOT NULL DEFAULT '[]',
    created_at                          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_law_revisions_law_enforcement
    ON law_revisions(law_id, amendment_enforcement_date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_law_revisions_law_revision
    ON law_revisions(law_id, law_revision_id);

CREATE INDEX IF NOT EXISTS idx_law_revisions_canonical
    ON law_revisions(law_canonical_id)
    WHERE law_canonical_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_revisions_unified
    ON law_revisions(law_unified_id)
    WHERE law_unified_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_revisions_amendment_law
    ON law_revisions(amendment_law_id)
    WHERE amendment_law_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_revisions_status
    ON law_revisions(current_revision_status, repeal_status);

CREATE INDEX IF NOT EXISTS idx_law_revisions_source_document
    ON law_revisions(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS law_attachment (
    attachment_id              TEXT PRIMARY KEY,
    law_revision_id            TEXT NOT NULL,
    law_id                     TEXT,
    src                        TEXT NOT NULL,
    updated                    TEXT,
    attachment_api_url         TEXT,
    source_document_id         TEXT,
    artifact_id                TEXT,
    content_hash               TEXT,
    mime_type                  TEXT,
    bytes                      INTEGER CHECK (bytes IS NULL OR bytes >= 0),
    fetched_at                 TEXT,
    raw_json                   TEXT NOT NULL DEFAULT '{}',
    known_gaps_json            TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_law_attachment_revision_src
    ON law_attachment(law_revision_id, src);

CREATE INDEX IF NOT EXISTS idx_law_attachment_law
    ON law_attachment(law_id)
    WHERE law_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_attachment_source_document
    ON law_attachment(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_attachment_artifact
    ON law_attachment(artifact_id)
    WHERE artifact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS procurement_award (
    award_id                   TEXT PRIMARY KEY,
    bid_unified_id             TEXT,
    source_id                  TEXT NOT NULL DEFAULT 'p_portal_chotatsu' CHECK (
                                   length(source_id) BETWEEN 3 AND 80 AND
                                   source_id NOT GLOB '*[^a-z0-9_]*'
                               ),
    procurement_item_no        TEXT,
    procurement_item_info_id   TEXT,
    source_row_hash            TEXT,
    award_date                 TEXT,
    awarded_amount_yen         INTEGER CHECK (
                                   awarded_amount_yen IS NULL OR awarded_amount_yen >= 0
                               ),
    winner_name                TEXT NOT NULL,
    winner_houjin_bangou       TEXT CHECK (
                                   winner_houjin_bangou IS NULL OR (
                                       length(winner_houjin_bangou) = 13 AND
                                       winner_houjin_bangou NOT GLOB '*[^0-9]*'
                                   )
                               ),
    winner_kojin_flag          INTEGER CHECK (
                                   winner_kojin_flag IS NULL OR winner_kojin_flag IN (0, 1)
                               ),
    ministry_cd                TEXT,
    procuring_entity           TEXT,
    bidding_method_cd          TEXT,
    source_url                 TEXT,
    source_document_id         TEXT,
    source_checksum            TEXT,
    fetched_at                 TEXT,
    updated_at                 TEXT NOT NULL DEFAULT (datetime('now')),
    raw_json                   TEXT NOT NULL DEFAULT '{}',
    known_gaps_json            TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_procurement_award_bid
    ON procurement_award(bid_unified_id)
    WHERE bid_unified_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_procurement_award_item_no
    ON procurement_award(procurement_item_no)
    WHERE procurement_item_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_procurement_award_winner
    ON procurement_award(winner_houjin_bangou)
    WHERE winner_houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_procurement_award_date_amount
    ON procurement_award(award_date DESC, awarded_amount_yen);

CREATE INDEX IF NOT EXISTS idx_procurement_award_source_document
    ON procurement_award(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_procurement_award_source_row_hash
    ON procurement_award(source_row_hash)
    WHERE source_row_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_procurement_award_source_natural
    ON procurement_award(
        source_id,
        procurement_item_no,
        COALESCE(procurement_item_info_id, ''),
        COALESCE(winner_houjin_bangou, ''),
        winner_name,
        COALESCE(award_date, ''),
        COALESCE(awarded_amount_yen, -1)
    )
    WHERE procurement_item_no IS NOT NULL
      AND winner_name IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
