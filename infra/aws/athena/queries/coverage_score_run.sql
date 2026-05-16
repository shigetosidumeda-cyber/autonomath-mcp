-- coverage_score_run.sql
--
-- Purpose:  Per-run aggregate scorecard. Combines source_receipts,
--           claim_refs, known_gaps, object_manifest into one row per run_id
--           so we can diff successive runs and trend coverage / gap rate /
--           data volume over time.
-- Output:   one row per run_id with (receipts, claims, gaps, objects,
--           distinct_sources, avg_confidence, no_hit_check_share,
--           review_gap_share, total_bytes).
-- Budget:   FULL TABLE SCAN across all partitions — bounded by listing a
--           specific cohort of run_ids when possible. Typical full scan
--           sits at ~150-400 MB; pin to recent run_ids in WHERE if cost
--           pressure shows.
-- Param:    optional `:run_id_filter` LIKE expression (default '%' matches
--           all). Bind as `'2026-05-%'` to scope to a month.

SELECT
  s.run_id,
  COUNT(DISTINCT s.content_sha256)                                     AS receipts,
  c.claim_rows,
  g.gap_rows,
  o.object_rows,
  COUNT(DISTINCT s.source_id)                                          AS distinct_sources,
  c.avg_confidence,
  SUM(CASE WHEN s.receipt_kind = 'no_hit_check' THEN 1 ELSE 0 END)     AS no_hit_check_rows,
  g.review_gap_rows,
  o.total_bytes
FROM jpcite_credit_2026_05.source_receipts s
LEFT JOIN (
  SELECT run_id,
         COUNT(*)              AS claim_rows,
         AVG(confidence)       AS avg_confidence
  FROM jpcite_credit_2026_05.claim_refs
  GROUP BY run_id
) c ON c.run_id = s.run_id
LEFT JOIN (
  SELECT run_id,
         COUNT(*)                                                                 AS gap_rows,
         SUM(CASE WHEN gap_code = 'professional_review_required' THEN 1 ELSE 0 END) AS review_gap_rows
  FROM jpcite_credit_2026_05.known_gaps
  GROUP BY run_id
) g ON g.run_id = s.run_id
LEFT JOIN (
  SELECT run_id,
         COUNT(*)              AS object_rows,
         SUM(content_length)   AS total_bytes
  FROM jpcite_credit_2026_05.object_manifest
  GROUP BY run_id
) o ON o.run_id = s.run_id
WHERE s.run_id LIKE :run_id_filter
GROUP BY s.run_id, c.claim_rows, c.avg_confidence, g.gap_rows, g.review_gap_rows, o.object_rows, o.total_bytes
ORDER BY s.run_id DESC;
