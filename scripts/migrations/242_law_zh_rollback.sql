-- target_db: autonomath
-- rollback: 242_law_zh

BEGIN;

DROP INDEX IF EXISTS ix_am_law_article_body_zh_present;
DROP INDEX IF EXISTS ix_am_law_title_zh_present;
DROP INDEX IF EXISTS ix_am_law_body_zh_present;

COMMIT;
