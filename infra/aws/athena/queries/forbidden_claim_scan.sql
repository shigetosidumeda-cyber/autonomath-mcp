-- forbidden_claim_scan.sql
--
-- Purpose:  Safety regression scan. claim_refs.value MUST NOT carry strings
--           that imply a regulated determination ('適格' / 'safe' / '免税'
--           / '推奨' / '承認' / '保証') without a paired known_gap row
--           declaring professional_review_required. If any row here is NOT
--           paired with a professional_review_required gap, that's a §52 /
--           §47条の2 / 行政書士法 boundary violation.
-- Output:   claim_id, subject_kind, subject_id, claim_kind, value (truncated
--           300 char), confidence, and a derived `has_review_gap` flag.
-- Budget:   single-partition scan ~30 MB; LIKE wildcards force full row scan
--           inside the partition so keep run_id pinned.

WITH suspect AS (
  SELECT
    claim_id,
    subject_kind,
    subject_id,
    claim_kind,
    SUBSTR(value, 1, 300) AS value_preview,
    value,
    confidence
  FROM jpcite_credit_2026_05.claim_refs
  WHERE run_id = :run_id
    AND (
         value LIKE '%適格%'
      OR value LIKE '%safe%'
      OR value LIKE '%免税%'
      OR value LIKE '%推奨%'
      OR value LIKE '%承認済%'
      OR value LIKE '%保証%'
    )
),
review_gaps AS (
  SELECT DISTINCT subject_kind, subject_id
  FROM jpcite_credit_2026_05.known_gaps
  WHERE run_id = :run_id
    AND gap_code = 'professional_review_required'
)
SELECT
  s.claim_id,
  s.subject_kind,
  s.subject_id,
  s.claim_kind,
  s.value_preview,
  s.confidence,
  CASE WHEN rg.subject_id IS NULL THEN 0 ELSE 1 END AS has_review_gap
FROM suspect s
LEFT JOIN review_gaps rg
  ON rg.subject_kind = s.subject_kind
 AND rg.subject_id   = s.subject_id
ORDER BY has_review_gap ASC, s.claim_kind, s.subject_id;
