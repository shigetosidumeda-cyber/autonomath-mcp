-- target_db: autonomath
-- migration 207_program_law_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: programs x laws. One row per (program_id, law_id, article_no)
-- citation. `ref_kind` distinguishes cited / amended / targeted references:
--   - 'cited'   : program text quotes the article as legal basis
--   - 'amended' : the program is gated by an amended version of the article
--   - 'targeted': the program targets entities regulated by the article
--
-- FK note
-- -------
-- ATTACH-less mirror tables: programs is mirrored as `jpi_programs`, laws
-- is mirrored as `jpi_laws` on autonomath.db. Both mirrors use TEXT
-- `unified_id` as PRIMARY KEY. References point at the mirror so the join
-- is enforceable inside a single DB file.
--
-- Naming distinction from jpintel.db migration 015_laws
-- -----------------------------------------------------
-- jpintel.db has a join table `program_law_refs` (migration 015) whose FKs
-- reference programs(id) + laws(law_id) on the jpintel side. This file
-- defines the autonomath.db twin on the jpi_* mirror surface. Both tables
-- live in physically separate SQLite files; CREATE TABLE IF NOT EXISTS is
-- safe even if the same table name exists on the other DB.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 207_program_law_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS program_law_refs (
    program_id    TEXT NOT NULL REFERENCES jpi_programs(unified_id),
    law_id        TEXT NOT NULL REFERENCES jpi_laws(unified_id),
    article_no    TEXT NOT NULL DEFAULT '',
    ref_kind      TEXT NOT NULL CHECK (ref_kind IN (
                      'cited',
                      'amended',
                      'targeted'
                  )),
    created_at    INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (program_id, law_id, article_no, ref_kind)
);

CREATE INDEX IF NOT EXISTS idx_program_law_refs_law
    ON program_law_refs(law_id, article_no);

CREATE INDEX IF NOT EXISTS idx_program_law_refs_kind
    ON program_law_refs(ref_kind);

CREATE INDEX IF NOT EXISTS idx_program_law_refs_created_at
    ON program_law_refs(created_at);
