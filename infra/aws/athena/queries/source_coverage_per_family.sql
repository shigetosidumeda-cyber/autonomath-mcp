-- source_coverage_per_family.sql
--
-- Purpose:  Per-source-family row count from claim_refs joined back through
--           source_receipts so we can see which J0x source families are
--           pulling weight and which are thin. AVG(confidence) shows whether
--           the family is producing high- or low-confidence claims.
-- Output:   one row per source_id with (row_count, distinct_subjects,
--           avg_confidence, distinct_claim_kinds).
-- Budget:   partition-aware (filter run_id); typical scan ~50 MB per run.
-- Notes:    UNNEST(source_receipt_ids) is required because claim_refs stores
--           the receipt linkage as an ARRAY<STRING>.

WITH cr AS (
  SELECT
    c.subject_kind,
    c.subject_id,
    c.claim_kind,
    c.confidence,
    receipt_id
  FROM jpcite_credit_2026_05.claim_refs AS c
  CROSS JOIN UNNEST(c.source_receipt_ids) AS t(receipt_id)
  WHERE c.run_id = :run_id
)
SELECT
  s.source_id,
  COUNT(*)                            AS claim_rows,
  COUNT(DISTINCT cr.subject_id)       AS distinct_subjects,
  AVG(cr.confidence)                  AS avg_confidence,
  COUNT(DISTINCT cr.claim_kind)       AS distinct_claim_kinds
FROM cr
JOIN jpcite_credit_2026_05.source_receipts AS s
  ON s.content_sha256 = cr.receipt_id
 AND s.run_id = :run_id
GROUP BY s.source_id
ORDER BY claim_rows DESC;
