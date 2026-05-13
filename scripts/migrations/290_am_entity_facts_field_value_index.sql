-- target_db: autonomath
-- 290_am_entity_facts_field_value_index.sql -- R3 P0-1 hot-path index for
-- intel_news_brief.
--
-- Background: src/jpintel_mcp/api/intel_news_brief.py executed a
-- 5-column LIKE-OR with leading wildcards over am_entity_facts (6.12M rows,
-- 8.29 GB DB) which produced a full-table scan with p99 5-15s. The route was
-- rewritten to use a single text axis (program OR law OR houjin OR industry)
-- mapped to a narrow allow-list of field_name values combined with a
-- field_value_text LIKE filter. This index supports that query shape.
--
-- The composite (field_name, value) lets SQLite seek directly to the
-- correct field_name bucket and then range-scan only the rows in that bucket
-- while applying the LIKE predicate; a 6.12M-row table scan collapses to a
-- per-bucket walk (max bucket ~370k for houjin_bangou, typical buckets are
-- under 250k).
--
-- All statements are idempotent (CREATE INDEX IF NOT EXISTS), safe to re-run
-- on every boot via entrypoint.sh §4 self-heal.

BEGIN IMMEDIATE;

CREATE INDEX IF NOT EXISTS idx_am_entity_facts_field_name_value
    ON am_entity_facts(field_name, field_value_text);

COMMIT;
