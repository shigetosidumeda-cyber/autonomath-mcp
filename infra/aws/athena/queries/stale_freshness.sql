-- stale_freshness.sql
--
-- Purpose:  Surface receipts whose `source_fetched_at` is older than 30 days
--           relative to query time. These rows should be paired with a
--           `freshness_stale_or_unknown` known_gap before surfacing in
--           customer-facing claims. Run weekly to catch drift.
-- Output:   source_id, source_url, source_fetched_at, days_stale,
--           support_level.
-- Budget:   single-partition scan ~20-40 MB.
-- Notes:    source_fetched_at is stored as STRING (ISO-8601); we cast via
--           from_iso8601_timestamp. Rows that fail parse return NULL and
--           are filtered into a separate bucket via `parse_failed`.

SELECT
  source_id,
  source_url,
  source_fetched_at,
  CASE
    WHEN parsed_at IS NULL THEN NULL
    ELSE date_diff('day', parsed_at, current_timestamp)
  END                              AS days_stale,
  support_level,
  CASE WHEN parsed_at IS NULL THEN 1 ELSE 0 END AS parse_failed
FROM (
  SELECT
    source_id,
    source_url,
    source_fetched_at,
    support_level,
    TRY(from_iso8601_timestamp(source_fetched_at)) AS parsed_at
  FROM jpcite_credit_2026_05.source_receipts
  WHERE run_id = :run_id
) t
WHERE parsed_at IS NULL
   OR parsed_at < (current_timestamp - INTERVAL '30' DAY)
ORDER BY parse_failed DESC, days_stale DESC NULLS LAST
LIMIT 5000;
