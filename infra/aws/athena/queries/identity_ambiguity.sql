-- identity_ambiguity.sql
--
-- Purpose:  Claims attached to a houjin (法人) subject with confidence < 0.5
--           are candidates for the `identity_ambiguity_unresolved` gap code.
--           A high count here means the houjin_bangou resolver is leaking;
--           a sustained zero means the resolver is healthy. Pair the result
--           with known_gaps to verify each ambiguous claim is flagged.
-- Output:   subject_id (houjin_bangou), claim_kind, value (truncated 200),
--           confidence, has_identity_gap flag.
-- Budget:   single-partition scan ~30 MB.

WITH ambiguous AS (
  SELECT
    claim_id,
    subject_kind,
    subject_id,
    claim_kind,
    SUBSTR(value, 1, 200) AS value_preview,
    confidence
  FROM jpcite_credit_2026_05.claim_refs
  WHERE run_id = :run_id
    AND subject_kind = 'houjin'
    AND confidence < 0.5
),
id_gaps AS (
  SELECT DISTINCT subject_id
  FROM jpcite_credit_2026_05.known_gaps
  WHERE run_id = :run_id
    AND gap_code = 'identity_ambiguity_unresolved'
)
SELECT
  a.claim_id,
  a.subject_id,
  a.claim_kind,
  a.value_preview,
  a.confidence,
  CASE WHEN g.subject_id IS NULL THEN 0 ELSE 1 END AS has_identity_gap
FROM ambiguous a
LEFT JOIN id_gaps g ON g.subject_id = a.subject_id
ORDER BY has_identity_gap ASC, a.confidence ASC;
