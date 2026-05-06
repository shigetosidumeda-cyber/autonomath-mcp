-- target_db: autonomath
-- rollback: wave24_183_citation_log
-- WARNING: drops citation_log + every minted request_id row. The SVG
-- endpoint will return `invalid` for all previously minted badges and
-- the static MD pages on jpcite.com/citation/* will 404 on regeneration.
-- Only run after exporting to R2 cold storage.

DROP INDEX IF EXISTS idx_citation_log_api_key;
DROP INDEX IF EXISTS idx_citation_log_status;
DROP INDEX IF EXISTS idx_citation_log_created;
DROP TABLE IF EXISTS citation_log;
