-- target_db: autonomath
-- ROLLBACK companion for wave24_133_am_invoice_buyer_seller_graph.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_aibsg_confidence;
DROP INDEX IF EXISTS idx_aibsg_buyer;
DROP INDEX IF EXISTS idx_aibsg_seller;
DROP TABLE IF EXISTS am_invoice_buyer_seller_graph;
PRAGMA foreign_keys = ON;
