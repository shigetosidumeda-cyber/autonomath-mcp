-- target_db: autonomath
-- migration: 242_law_zh
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 5c — 法令 中文 corpus extension
-- idempotent: ADD COLUMN swallowed; CREATE * IF NOT EXISTS

BEGIN;

ALTER TABLE am_law ADD COLUMN summary_zh TEXT;
ALTER TABLE am_law ADD COLUMN title_zh TEXT;
ALTER TABLE am_law ADD COLUMN body_zh TEXT;
ALTER TABLE am_law ADD COLUMN body_zh_source_url TEXT;
ALTER TABLE am_law ADD COLUMN body_zh_fetched_at TEXT;
ALTER TABLE am_law ADD COLUMN body_zh_license TEXT DEFAULT 'gov_public';

CREATE INDEX IF NOT EXISTS ix_am_law_body_zh_present
    ON am_law(canonical_id)
    WHERE body_zh IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_law_title_zh_present
    ON am_law(canonical_id)
    WHERE title_zh IS NOT NULL;

ALTER TABLE am_law_article ADD COLUMN body_zh TEXT;
ALTER TABLE am_law_article ADD COLUMN body_zh_source_url TEXT;
ALTER TABLE am_law_article ADD COLUMN body_zh_fetched_at TEXT;
ALTER TABLE am_law_article ADD COLUMN body_zh_license TEXT DEFAULT 'gov_public';

CREATE INDEX IF NOT EXISTS ix_am_law_article_body_zh_present
    ON am_law_article(law_canonical_id)
    WHERE body_zh IS NOT NULL;

COMMIT;
