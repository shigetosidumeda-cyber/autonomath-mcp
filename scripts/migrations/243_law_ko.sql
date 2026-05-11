-- target_db: autonomath
-- migration: 243_law_ko
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 5d — 法令 韓国語 corpus extension
-- idempotent: ADD COLUMN swallowed; CREATE * IF NOT EXISTS

BEGIN;

ALTER TABLE am_law ADD COLUMN summary_ko TEXT;
ALTER TABLE am_law ADD COLUMN title_ko TEXT;
ALTER TABLE am_law ADD COLUMN body_ko TEXT;
ALTER TABLE am_law ADD COLUMN body_ko_source_url TEXT;
ALTER TABLE am_law ADD COLUMN body_ko_fetched_at TEXT;
ALTER TABLE am_law ADD COLUMN body_ko_license TEXT DEFAULT 'gov_public';

CREATE INDEX IF NOT EXISTS ix_am_law_body_ko_present
    ON am_law(canonical_id)
    WHERE body_ko IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_law_title_ko_present
    ON am_law(canonical_id)
    WHERE title_ko IS NOT NULL;

ALTER TABLE am_law_article ADD COLUMN body_ko TEXT;
ALTER TABLE am_law_article ADD COLUMN body_ko_source_url TEXT;
ALTER TABLE am_law_article ADD COLUMN body_ko_fetched_at TEXT;
ALTER TABLE am_law_article ADD COLUMN body_ko_license TEXT DEFAULT 'gov_public';

CREATE INDEX IF NOT EXISTS ix_am_law_article_body_ko_present
    ON am_law_article(law_canonical_id)
    WHERE body_ko IS NOT NULL;

COMMIT;
