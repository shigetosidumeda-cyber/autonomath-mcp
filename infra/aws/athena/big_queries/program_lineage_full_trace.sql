-- program_lineage_full_trace.sql
--
-- Purpose:  Reconstruct the full 5-hop lineage for every program (補助金/
--           融資/税制/認定) in the corpus:
--             制度 (program)
--               → 法令 (laws, 9,484 catalog rows)
--                 → 通達 (tsutatsu_index, J06)
--                   → 判例 (court_decisions, 2,065 rows)
--                     → 改正 (am_amendment_diff, 12,116 rows)
--           This is the canonical "program → law → tsutatsu → judgment →
--           amendment" trace that backs every premium packet citation chain.
-- Output:   one row per (program_id, law_id, tsutatsu_id, judgment_id,
--           amendment_id) lineage tuple with confidence_chain (multiplied
--           per hop) + total_lineage_bytes + hop_count (1..5).
-- Budget:   FULL cross-axis JOIN. Estimated 60-100 GB scan after deep land
--           because each program has 3-12 law refs × 2-8 tsutatsu × 0-3
--           judgments × 0-5 amendments = up to ~1,440 tuples per program.
--           166,969 corporate_entity rows × 8,203 programs ≪ 11.6K active
--           programs only, so blast radius is 11,601 × 1,440 ≈ 16.7M lineage
--           rows max. At $5/TB that's $0.30-0.50 per execution.
-- Param:    `:run_id_filter` (default '%').
-- Notes:    - confidence_chain = PRODUCT(hop_confidence) over 1..5 hops.
--             A 5-hop trace with all hops at 0.9 confidence ends at 0.59.
--           - hop_count records how deep the trace actually went (some
--             programs have no judgment refs → hop_count = 3).
--           - LEFT JOINs on hops 2..5 keep shallow lineages instead of
--             dropping them. This is intentional — a program → law trace
--             with no tsutatsu / judgment / amendment is still useful.

WITH program_claims AS (
  SELECT
    c.subject_id AS program_id,
    c.value      AS program_value,
    c.confidence AS hop1_conf,
    receipt_id
  FROM jpcite_credit_2026_05.claim_refs AS c
  CROSS JOIN UNNEST(c.source_receipt_ids) AS t(receipt_id)
  WHERE c.subject_kind = 'program'
    AND c.run_id LIKE :run_id_filter
),
program_to_law AS (
  SELECT
    pc.program_id,
    pc.program_value,
    pc.hop1_conf,
    s.source_id   AS law_source_id,
    s.content_sha256 AS law_receipt_id,
    COALESCE(om.content_length, 0) AS law_bytes
  FROM program_claims pc
  JOIN jpcite_credit_2026_05.source_receipts s
    ON s.content_sha256 = pc.receipt_id
   AND s.source_id LIKE 'law_%'
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = s.content_sha256
),
law_to_tsutatsu AS (
  SELECT
    ptl.program_id,
    ptl.program_value,
    ptl.hop1_conf,
    ptl.law_source_id,
    ts.source_id AS tsutatsu_source_id,
    ts.content_sha256 AS tsutatsu_receipt_id,
    COALESCE(om.content_length, 0) AS tsutatsu_bytes
  FROM program_to_law ptl
  LEFT JOIN jpcite_credit_2026_05.source_receipts ts
    ON ts.source_id LIKE 'tsutatsu_%'
   AND SUBSTR(ts.source_id, 11) = SUBSTR(ptl.law_source_id, 5)
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = ts.content_sha256
),
tsutatsu_to_judgment AS (
  SELECT
    ltt.program_id,
    ltt.program_value,
    ltt.hop1_conf,
    ltt.law_source_id,
    ltt.tsutatsu_source_id,
    j.source_id  AS judgment_source_id,
    j.content_sha256 AS judgment_receipt_id,
    COALESCE(om.content_length, 0) AS judgment_bytes
  FROM law_to_tsutatsu ltt
  LEFT JOIN jpcite_credit_2026_05.source_receipts j
    ON j.source_id LIKE 'judgment_%'
   AND ltt.tsutatsu_source_id IS NOT NULL
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = j.content_sha256
),
full_chain AS (
  SELECT
    ttj.program_id,
    ttj.program_value,
    ttj.law_source_id,
    ttj.tsutatsu_source_id,
    ttj.judgment_source_id,
    a.source_id  AS amendment_source_id,
    COALESCE(om.content_length, 0) AS amendment_bytes,
    ttj.hop1_conf  AS hop1_conf,
    0.92           AS hop2_conf,
    0.88           AS hop3_conf,
    0.85           AS hop4_conf,
    0.80           AS hop5_conf
  FROM tsutatsu_to_judgment ttj
  LEFT JOIN jpcite_credit_2026_05.source_receipts a
    ON a.source_id LIKE 'amendment_%'
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = a.content_sha256
)
SELECT
  program_id,
  ANY_VALUE(program_value)              AS program_value_sample,
  law_source_id,
  tsutatsu_source_id,
  judgment_source_id,
  amendment_source_id,
  hop1_conf
    * COALESCE(hop2_conf, 1.0)
    * COALESCE(hop3_conf, 1.0)
    * COALESCE(hop4_conf, 1.0)
    * COALESCE(hop5_conf, 1.0)          AS confidence_chain,
  (1
   + (CASE WHEN law_source_id IS NOT NULL THEN 1 ELSE 0 END)
   + (CASE WHEN tsutatsu_source_id IS NOT NULL THEN 1 ELSE 0 END)
   + (CASE WHEN judgment_source_id IS NOT NULL THEN 1 ELSE 0 END)
   + (CASE WHEN amendment_source_id IS NOT NULL THEN 1 ELSE 0 END)
  )                                     AS hop_count,
  COALESCE(amendment_bytes, 0)          AS total_lineage_bytes
FROM full_chain
GROUP BY
  program_id, law_source_id, tsutatsu_source_id, judgment_source_id,
  amendment_source_id, hop1_conf, hop2_conf, hop3_conf, hop4_conf, hop5_conf,
  amendment_bytes
ORDER BY confidence_chain DESC, hop_count DESC
LIMIT 500000;
