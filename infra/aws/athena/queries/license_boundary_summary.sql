-- license_boundary_summary.sql
--
-- Purpose:  Distribution of `license_boundary` on source_receipts. Expected
--           values include 'pdl_v1.0', 'cc_by_4.0', 'gov_standard',
--           'public_domain', 'proprietary', 'unknown'. Anything else is a
--           license-classifier drift. `unknown` should trend down over
--           successive runs; `proprietary` rows must not be re-distributed
--           via the API surface.
-- Output:   license_boundary, count, distinct_sources, sample_url.
-- Budget:   single-partition scan ~10-20 MB.

SELECT
  license_boundary,
  COUNT(*)                          AS receipt_rows,
  COUNT(DISTINCT source_id)         AS distinct_sources,
  ARBITRARY(source_url)             AS sample_url
FROM jpcite_credit_2026_05.source_receipts
WHERE run_id = :run_id
GROUP BY license_boundary
ORDER BY receipt_rows DESC;
