-- target_db: autonomath
-- rollback for wave24_176_edinet_filing_signal_layer
--
-- DROP VIEWS first (they depend on the table), then the table. Indexes are
-- dropped automatically when the table is dropped.
--
-- WARNING: dropping this table erases the EDINET filing event timeline. The
-- companion ETL (scripts/etl/backfill_edinet_filing_signal_layer.py) reads
-- from EDINET API v2 (`/api/v2/documents.json`) which is preserved upstream,
-- so re-creation is non-destructive over time. However, downstream artifacts
-- (DD pack, monthly digest, public_dd_evidence_book) lose the filing event
-- surface until the cron `scripts/cron/ingest_edinet_filings.py` rebuilds it.

DROP VIEW IF EXISTS v_edinet_filings_unresolved;
DROP VIEW IF EXISTS v_edinet_filings_resolved;
DROP TABLE IF EXISTS edinet_filing_signal_layer;
