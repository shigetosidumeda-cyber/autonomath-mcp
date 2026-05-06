-- target_db: autonomath
-- rollback for 158_am_entity_density_score

DROP INDEX IF EXISTS ix_density_score_rank;
DROP INDEX IF EXISTS ix_density_score_kind;
DROP INDEX IF EXISTS ix_density_score;
DROP TABLE IF EXISTS am_entity_density_score;
