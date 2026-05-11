-- target_db: autonomath
-- migration: 227_edinet_full_rollback
-- generated_at: 2026-05-12
-- author: Wave 31 Axis 1c (jpcite_2026_05_12_axis1bc_jpo_edinet)
--
-- Rolls back 227_edinet_full.sql. Drops the EDINET full-text companion table
-- and its dependent views. INDEX drops are implicit via DROP TABLE.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_edinet_filings_full_unresolved;
DROP VIEW IF EXISTS v_edinet_filings_full_resolved;

DROP TABLE IF EXISTS am_edinet_filings;
