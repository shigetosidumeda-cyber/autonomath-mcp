-- target_db: autonomath
-- rollback: 243_law_ko

BEGIN;
DROP INDEX IF EXISTS ix_am_law_article_body_ko_present;
DROP INDEX IF EXISTS ix_am_law_title_ko_present;
DROP INDEX IF EXISTS ix_am_law_body_ko_present;
COMMIT;
