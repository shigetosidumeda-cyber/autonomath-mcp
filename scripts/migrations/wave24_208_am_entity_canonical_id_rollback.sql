-- target_db: autonomath
-- Rollback for wave24_208_am_entity_canonical_id.sql
--
-- Note: SQLite cannot DROP COLUMN before 3.35; this rollback intentionally
-- LEAVES the entity_id_canonical column in place. Re-applying the forward
-- migration is a no-op (ADD COLUMN errors out with "duplicate column" on
-- stderr, exit 0 from sqlite3 -bail at entrypoint.sh §4).
DROP VIEW IF EXISTS v_corp_program_judgment_law;
DROP INDEX IF EXISTS idx_am_compat_matrix_inferred;
DROP INDEX IF EXISTS idx_am_law_article_law_canonical;
DROP INDEX IF EXISTS idx_am_relation_type_target;
DROP INDEX IF EXISTS idx_am_relation_type_source;
DROP INDEX IF EXISTS idx_am_entity_facts_houjin_bangou;
DROP INDEX IF EXISTS idx_am_entities_kind_canonical;
DROP INDEX IF EXISTS idx_am_entities_canonical_axis;
-- Column entity_id_canonical: intentionally NOT dropped (SQLite < 3.35).
