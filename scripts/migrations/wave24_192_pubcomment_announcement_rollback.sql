-- target_db: autonomath
-- rollback: wave24_192_pubcomment_announcement
-- WARNING: drops pubcomment_announcement audit history. Only run after
-- exporting to R2 backup.

DROP INDEX IF EXISTS ix_pubcomment_law_relevant;
DROP INDEX IF EXISTS ix_pubcomment_deadline;
DROP INDEX IF EXISTS ix_pubcomment_announce_date;
DROP TABLE IF EXISTS pubcomment_announcement;
