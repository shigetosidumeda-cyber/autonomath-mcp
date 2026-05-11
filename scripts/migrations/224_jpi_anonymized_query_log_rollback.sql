-- migration 224_jpi_anonymized_query_log — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_anon_query_trending_7d;
DROP INDEX  IF EXISTS idx_anon_query_endpoint;
DROP INDEX  IF EXISTS idx_anon_query_category;
DROP INDEX  IF EXISTS idx_anon_query_shape;
DROP INDEX  IF EXISTS idx_anon_query_bucket;
DROP TABLE  IF EXISTS jpi_anonymized_query_log;
