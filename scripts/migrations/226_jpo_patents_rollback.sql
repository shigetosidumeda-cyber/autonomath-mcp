-- target_db: autonomath
-- migration: 226_jpo_patents_rollback
-- generated_at: 2026-05-12
-- author: Wave 31 Axis 1b (jpcite_2026_05_12_axis1bc_jpo_edinet)
--
-- Rolls back 226_jpo_patents.sql. Drops the two JPO 特許/実用新案 tables and
-- their dependent views. INDEX drops are implicit via DROP TABLE.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_jpo_utility_models_resolved;
DROP VIEW IF EXISTS v_jpo_patents_resolved;

DROP TABLE IF EXISTS am_jpo_utility_models;
DROP TABLE IF EXISTS am_jpo_patents;
