-- target_db: autonomath
-- ROLLBACK companion for wave24_163_am_citation_network.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS ix_citation_kinds;
DROP INDEX IF EXISTS ix_citation_citing;
DROP INDEX IF EXISTS ix_citation_cited;
DROP TABLE IF EXISTS am_citation_network;
PRAGMA foreign_keys = ON;
