-- target_db: autonomath
-- migration 176_source_foundation_domain_tables (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.
--
-- Bookkeeping note:
--   This rollback follows the existing repo convention and does not mutate
--   schema_migrations. If an operator wants boot self-heal to re-apply the
--   forward migration after rollback, delete the matching row manually:
--
--     DELETE FROM schema_migrations
--      WHERE id = '176_source_foundation_domain_tables.sql';

DROP INDEX IF EXISTS uq_procurement_award_source_natural;
DROP INDEX IF EXISTS uq_procurement_award_source_row_hash;
DROP INDEX IF EXISTS idx_procurement_award_source_document;
DROP INDEX IF EXISTS idx_procurement_award_date_amount;
DROP INDEX IF EXISTS idx_procurement_award_winner;
DROP INDEX IF EXISTS idx_procurement_award_item_no;
DROP INDEX IF EXISTS idx_procurement_award_bid;
DROP TABLE IF EXISTS procurement_award;

DROP INDEX IF EXISTS idx_law_attachment_artifact;
DROP INDEX IF EXISTS idx_law_attachment_source_document;
DROP INDEX IF EXISTS idx_law_attachment_law;
DROP INDEX IF EXISTS uq_law_attachment_revision_src;
DROP TABLE IF EXISTS law_attachment;

DROP INDEX IF EXISTS idx_law_revisions_source_document;
DROP INDEX IF EXISTS idx_law_revisions_status;
DROP INDEX IF EXISTS idx_law_revisions_amendment_law;
DROP INDEX IF EXISTS idx_law_revisions_unified;
DROP INDEX IF EXISTS idx_law_revisions_canonical;
DROP INDEX IF EXISTS uq_law_revisions_law_revision;
DROP INDEX IF EXISTS idx_law_revisions_law_enforcement;
DROP TABLE IF EXISTS law_revisions;

DROP INDEX IF EXISTS idx_aesi_source_document;
DROP INDEX IF EXISTS idx_aesi_permit;
DROP INDEX IF EXISTS idx_aesi_authority_sector;
DROP INDEX IF EXISTS idx_aesi_source_dates;
DROP INDEX IF EXISTS idx_aesi_houjin_dates;
DROP INDEX IF EXISTS idx_aesi_entity;
DROP INDEX IF EXISTS idx_aesi_enforcement;
DROP INDEX IF EXISTS uq_aesi_source_action;
DROP TABLE IF EXISTS am_enforcement_source_index;

DROP INDEX IF EXISTS idx_houjin_master_refresh_run_artifact;
DROP INDEX IF EXISTS idx_houjin_master_refresh_run_source_document;
DROP INDEX IF EXISTS idx_houjin_master_refresh_run_snapshot;
DROP INDEX IF EXISTS idx_houjin_master_refresh_run_status;
DROP INDEX IF EXISTS idx_houjin_master_refresh_run_source_time;
DROP TABLE IF EXISTS houjin_master_refresh_run;

DROP INDEX IF EXISTS uq_houjin_change_history_diff_sequence;
DROP INDEX IF EXISTS uq_houjin_change_history_source_row_hash;
DROP INDEX IF EXISTS idx_houjin_change_history_snapshot;
DROP INDEX IF EXISTS idx_houjin_change_history_source_document;
DROP INDEX IF EXISTS idx_houjin_change_history_source_checksum;
DROP INDEX IF EXISTS idx_houjin_change_history_change_process;
DROP INDEX IF EXISTS idx_houjin_change_history_houjin_date;
DROP TABLE IF EXISTS houjin_change_history;
