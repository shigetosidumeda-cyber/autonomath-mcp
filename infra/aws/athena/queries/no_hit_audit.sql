-- no_hit_audit.sql
--
-- Purpose:  Audit `receipt_kind='no_hit_check'` rows. These are receipts that
--           proves we LOOKED for evidence and did NOT find it — the JPCIR
--           "no_hit_not_absence" contract requires that absence claims be
--           backed by a no_hit_check receipt before being surfaced as
--           known_gap. Use this query to verify the no_hit chain is intact.
-- Output:   one row per no_hit_check receipt with (source_id, source_url,
--           source_fetched_at, claim_kind it was looking for, support_level).
-- Budget:   single-partition scan ~20 MB.
-- Convention: support_level for no_hit_check rows should be one of
--           'no_hit_confirmed' / 'no_hit_inconclusive'; anything else is
--           a schema drift.

SELECT
  source_id,
  claim_kind,
  source_url,
  source_fetched_at,
  content_sha256,
  license_boundary,
  support_level
FROM jpcite_credit_2026_05.source_receipts
WHERE run_id = :run_id
  AND receipt_kind = 'no_hit_check'
ORDER BY source_id, source_fetched_at DESC;
