-- claim_refs_per_subject.sql
--
-- Purpose:  Fact density per entity. For each (subject_kind, subject_id)
--           tuple, count distinct claim_kinds and total claim rows. Subjects
--           with < 3 distinct claim_kinds are thin candidates for further
--           crawl, while subjects with > 30 are likely high-value cohort
--           rows worth promoting.
-- Output:   subject_kind, subject_id, claim_rows, distinct_claim_kinds,
--           avg_confidence.
-- Budget:   single-partition scan ~30-80 MB; aggregation cheap.

SELECT
  subject_kind,
  subject_id,
  COUNT(*)                          AS claim_rows,
  COUNT(DISTINCT claim_kind)        AS distinct_claim_kinds,
  AVG(confidence)                   AS avg_confidence
FROM jpcite_credit_2026_05.claim_refs
WHERE run_id = :run_id
GROUP BY subject_kind, subject_id
ORDER BY claim_rows DESC
LIMIT 5000;
