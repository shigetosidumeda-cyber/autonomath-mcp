-- target_db: autonomath
-- Rollback for wave24_198_am_relation_predicted.sql.
-- Drops view, indexes, and the predicted-edge table.

DROP VIEW  IF EXISTS v_am_relation_predicted_top;

DROP INDEX IF EXISTS ux_am_relation_predicted_hrtm;
DROP INDEX IF EXISTS ix_am_relation_predicted_model_score;
DROP INDEX IF EXISTS ix_am_relation_predicted_score;
DROP INDEX IF EXISTS ix_am_relation_predicted_tgt;
DROP INDEX IF EXISTS ix_am_relation_predicted_src;

DROP TABLE IF EXISTS am_relation_predicted;
