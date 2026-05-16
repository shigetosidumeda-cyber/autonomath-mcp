-- artifact_size_per_run.sql
--
-- Purpose:  Storage footprint per run. SUM(content_length) gives total bytes
--           landed under s3://jpcite-credit-…-derived/<table>/run_id=…/. Use
--           to track J0x storage growth, set retention pruning windows, and
--           feed budget canary attestations.
-- Output:   run_id, object_count, total_bytes, total_gib, distinct_sources,
--           distinct_content_types.
-- Budget:   FULL TABLE SCAN; object_manifest is small (one row per S3 obj),
--           typical ~5-30 MB. Bind `:run_id_filter` to scope.

SELECT
  run_id,
  COUNT(*)                                AS object_count,
  SUM(content_length)                     AS total_bytes,
  ROUND(SUM(content_length) / 1024.0 / 1024.0 / 1024.0, 3) AS total_gib,
  COUNT(DISTINCT source_id)               AS distinct_sources,
  COUNT(DISTINCT content_type)            AS distinct_content_types
FROM jpcite_credit_2026_05.object_manifest
WHERE run_id LIKE :run_id_filter
GROUP BY run_id
ORDER BY total_bytes DESC;
