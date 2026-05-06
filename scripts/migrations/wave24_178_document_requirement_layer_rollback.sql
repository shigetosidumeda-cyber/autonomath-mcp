-- target_db: autonomath
-- rollback for wave24_178_document_requirement_layer
--
-- DROP VIEWS first (they depend on the table), then the table. Indexes are
-- dropped automatically when the table is dropped.
--
-- WARNING: dropping this table erases the normalized 必要書類 surface.
-- The companion ETL (scripts/etl/backfill_document_requirement_layer.py)
-- can re-extract from `programs.必要書類_text` blobs but the regex
-- normalization rules are operator-curated (~120 lines per
-- ~22 document_kind canonicals); rebuild cost is ~3 h ETL +
-- ~6 h curator review on first pass, ~30 min thereafter.

DROP VIEW IF EXISTS v_doc_req_cross_program;
DROP VIEW IF EXISTS v_doc_req_per_program;
DROP TABLE IF EXISTS document_requirement_layer;
