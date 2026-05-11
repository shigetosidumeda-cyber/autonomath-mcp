-- migration 233_supplier_chain — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_supplier_chain_breadth;
DROP INDEX  IF EXISTS ux_supplier_chain_edge;
DROP INDEX  IF EXISTS idx_supplier_chain_type;
DROP INDEX  IF EXISTS idx_supplier_chain_partner;
DROP INDEX  IF EXISTS idx_supplier_chain_anchor;
DROP TABLE  IF EXISTS am_supplier_chain;
