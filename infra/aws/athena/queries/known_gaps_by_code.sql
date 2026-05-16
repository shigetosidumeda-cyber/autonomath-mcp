-- known_gaps_by_code.sql
--
-- Purpose:  Distribution of the 7-code JPCIR gap enum
--           (csv_input_not_evidence_safe, source_receipt_incomplete,
--            pricing_or_cap_unconfirmed, no_hit_not_absence,
--            professional_review_required, freshness_stale_or_unknown,
--            identity_ambiguity_unresolved).
--           Surfaces the shape of "we don't know" vs "we know but cannot
--           assert" boundaries. Any row whose gap_code is NOT in that 7-enum
--           is a contract violation — flagged in `unknown_codes` column.
-- Output:   gap_code, count, distinct_subjects, distinct_severities.
-- Budget:   single-partition scan ~10-30 MB.

SELECT
  gap_code,
  COUNT(*)                          AS gap_rows,
  COUNT(DISTINCT subject_id)        AS distinct_subjects,
  COUNT(DISTINCT severity)          AS distinct_severities,
  CASE WHEN gap_code IN (
      'csv_input_not_evidence_safe',
      'source_receipt_incomplete',
      'pricing_or_cap_unconfirmed',
      'no_hit_not_absence',
      'professional_review_required',
      'freshness_stale_or_unknown',
      'identity_ambiguity_unresolved'
    ) THEN 0 ELSE 1 END             AS is_unknown_code
FROM jpcite_credit_2026_05.known_gaps
WHERE run_id = :run_id
GROUP BY gap_code
ORDER BY gap_rows DESC;
