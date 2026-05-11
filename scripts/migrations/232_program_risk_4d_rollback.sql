-- migration 232_program_risk_4d — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_program_risk_4d_top;
DROP INDEX  IF EXISTS ux_program_risk_4d_tuple;
DROP INDEX  IF EXISTS idx_program_risk_4d_refresh;
DROP INDEX  IF EXISTS idx_program_risk_4d_gyouhou;
DROP INDEX  IF EXISTS idx_program_risk_4d_program_score;
DROP TABLE  IF EXISTS am_program_risk_4d;
