-- top_10_largest_documents.sql
--
-- Purpose:  Identify the 10 largest individual documents landed in
--           object_manifest. Useful for spotting accidental whole-PDF dumps,
--           unexpected video downloads, or aggregator-only HTML mirrors.
--           Large outliers should be inspected before they consume the
--           run-budget envelope.
-- Output:   one row per outlier with (s3_key, content_length, content_type,
--           content_mib, source_id, fetched_at, retention_class).
-- Budget:   single-partition scan ~5-20 MB.

SELECT
  s3_key,
  content_length,
  ROUND(content_length / 1024.0 / 1024.0, 3) AS content_mib,
  content_type,
  source_id,
  fetched_at,
  retention_class
FROM jpcite_credit_2026_05.object_manifest
WHERE run_id = :run_id
ORDER BY content_length DESC
LIMIT 10;
