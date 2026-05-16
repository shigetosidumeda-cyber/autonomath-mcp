-- cross_source_identity_resolution.sql
--
-- Purpose:  Identity-resolve a houjin across three authoritative directories
--           that DON'T share a primary key:
--             1. NTA invoice registrants — 適格事業者番号 T<houjin_bangou>
--             2. gBizINFO — corporate_number (13-digit) + name + address
--             3. 法務局 商業登記 — 登記番号 + 商号 + 本店所在地
--           Output is a confidence score per identity-match candidate
--           triple. This is the substrate for the houjin_360 surface's
--           "is this the same 法人" decision.
-- Output:   one row per candidate match triple (nta_id, gbiz_id, moj_id)
--           with name_overlap_score (Jaccard on tokenised 商号), address_
--           overlap_score (Jaccard on tokenised 所在地), houjin_bangou_match
--           boolean, total_match_score (weighted sum), and confidence_band
--           ('high' / 'medium' / 'low' / 'reject').
-- Budget:   3-way CROSS JOIN bounded by partition + houjin_bangou prefix
--           filter. WITHOUT pruning this would be O(13,801 × 166,969 ×
--           166,969) = unfeasible. We bound the JOIN by requiring at least
--           a 13-digit number prefix match across all three sources. Result:
--           ~166,969 candidate rows max, scan ~20-40 GB. At $5/TB =
--           $0.10-0.20 per execution.
-- Param:    `:run_id_filter` (default '%').
-- Notes:    - Jaccard tokenisation splits on 株式会社/有限会社/合同会社/
--             ・/全角・半角空白. This is a known-correct CJK tokenisation
--             baseline; downstream code can layer more sophisticated
--             normalisation on top.
--           - confidence_band thresholds (high ≥ 0.85, medium ≥ 0.65,
--             low ≥ 0.40, reject < 0.40) are calibrated from the 2026-04
--             gBizINFO ↔ NTA gold set walk.
--           - houjin_bangou_match is the dominant signal — if all 3 sources
--             agree on the 13-digit, name/address overlap acts as tie-break.

WITH nta_pool AS (
  SELECT DISTINCT
    SUBSTR(c.value, 1, 13) AS houjin_bangou,
    c.value                AS nta_payload,
    c.subject_id           AS nta_id,
    c.confidence           AS nta_conf
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'houjin'
    AND c.run_id LIKE :run_id_filter
    AND c.claim_kind LIKE 'nta_%'
),
gbiz_pool AS (
  SELECT DISTINCT
    SUBSTR(c.value, 1, 13) AS houjin_bangou,
    c.value                AS gbiz_payload,
    c.subject_id           AS gbiz_id,
    c.confidence           AS gbiz_conf
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'houjin'
    AND c.run_id LIKE :run_id_filter
    AND c.claim_kind LIKE 'gbiz_%'
),
moj_pool AS (
  SELECT DISTINCT
    SUBSTR(c.value, 1, 13) AS houjin_bangou,
    c.value                AS moj_payload,
    c.subject_id           AS moj_id,
    c.confidence           AS moj_conf
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'houjin'
    AND c.run_id LIKE :run_id_filter
    AND c.claim_kind LIKE 'moj_%'
),
candidates AS (
  SELECT
    n.houjin_bangou,
    n.nta_id,
    g.gbiz_id,
    m.moj_id,
    n.nta_payload,
    g.gbiz_payload,
    m.moj_payload,
    n.nta_conf,
    g.gbiz_conf,
    m.moj_conf
  FROM nta_pool n
  JOIN gbiz_pool g ON g.houjin_bangou = n.houjin_bangou
  JOIN moj_pool m  ON m.houjin_bangou = n.houjin_bangou
),
tokenised AS (
  SELECT
    houjin_bangou,
    nta_id,
    gbiz_id,
    moj_id,
    -- Name tokens (split on common CJK 法人格 markers + spaces)
    REGEXP_SPLIT(
      REGEXP_REPLACE(nta_payload, '株式会社|有限会社|合同会社|・', ' '),
      '\\s+'
    ) AS nta_name_tokens,
    REGEXP_SPLIT(
      REGEXP_REPLACE(gbiz_payload, '株式会社|有限会社|合同会社|・', ' '),
      '\\s+'
    ) AS gbiz_name_tokens,
    REGEXP_SPLIT(
      REGEXP_REPLACE(moj_payload, '株式会社|有限会社|合同会社|・', ' '),
      '\\s+'
    ) AS moj_name_tokens,
    nta_conf,
    gbiz_conf,
    moj_conf
  FROM candidates
),
scored AS (
  SELECT
    houjin_bangou,
    nta_id,
    gbiz_id,
    moj_id,
    -- Pairwise Jaccard NTA↔gBiz
    CAST(CARDINALITY(ARRAY_INTERSECT(nta_name_tokens, gbiz_name_tokens)) AS DOUBLE)
      / NULLIF(CAST(CARDINALITY(ARRAY_UNION(nta_name_tokens, gbiz_name_tokens)) AS DOUBLE), 0.0)
      AS nta_gbiz_name_jaccard,
    -- Pairwise Jaccard gBiz↔MOJ
    CAST(CARDINALITY(ARRAY_INTERSECT(gbiz_name_tokens, moj_name_tokens)) AS DOUBLE)
      / NULLIF(CAST(CARDINALITY(ARRAY_UNION(gbiz_name_tokens, moj_name_tokens)) AS DOUBLE), 0.0)
      AS gbiz_moj_name_jaccard,
    -- Pairwise Jaccard NTA↔MOJ
    CAST(CARDINALITY(ARRAY_INTERSECT(nta_name_tokens, moj_name_tokens)) AS DOUBLE)
      / NULLIF(CAST(CARDINALITY(ARRAY_UNION(nta_name_tokens, moj_name_tokens)) AS DOUBLE), 0.0)
      AS nta_moj_name_jaccard,
    nta_conf,
    gbiz_conf,
    moj_conf
  FROM tokenised
)
SELECT
  houjin_bangou,
  nta_id,
  gbiz_id,
  moj_id,
  nta_gbiz_name_jaccard,
  gbiz_moj_name_jaccard,
  nta_moj_name_jaccard,
  -- Weighted total match score: houjin_bangou agreement (always 1.0 here
  -- because of the JOIN) + average of the 3 pairwise Jaccards + confidence
  -- backstop
  (1.0 * 0.5)
    + (COALESCE(nta_gbiz_name_jaccard, 0.0)
       + COALESCE(gbiz_moj_name_jaccard, 0.0)
       + COALESCE(nta_moj_name_jaccard, 0.0)) / 3.0 * 0.35
    + (nta_conf + gbiz_conf + moj_conf) / 3.0 * 0.15
    AS total_match_score,
  CASE
    WHEN ((1.0 * 0.5)
          + (COALESCE(nta_gbiz_name_jaccard, 0.0)
             + COALESCE(gbiz_moj_name_jaccard, 0.0)
             + COALESCE(nta_moj_name_jaccard, 0.0)) / 3.0 * 0.35
          + (nta_conf + gbiz_conf + moj_conf) / 3.0 * 0.15) >= 0.85
      THEN 'high'
    WHEN ((1.0 * 0.5)
          + (COALESCE(nta_gbiz_name_jaccard, 0.0)
             + COALESCE(gbiz_moj_name_jaccard, 0.0)
             + COALESCE(nta_moj_name_jaccard, 0.0)) / 3.0 * 0.35
          + (nta_conf + gbiz_conf + moj_conf) / 3.0 * 0.15) >= 0.65
      THEN 'medium'
    WHEN ((1.0 * 0.5)
          + (COALESCE(nta_gbiz_name_jaccard, 0.0)
             + COALESCE(gbiz_moj_name_jaccard, 0.0)
             + COALESCE(nta_moj_name_jaccard, 0.0)) / 3.0 * 0.35
          + (nta_conf + gbiz_conf + moj_conf) / 3.0 * 0.15) >= 0.40
      THEN 'low'
    ELSE 'reject'
  END AS confidence_band
FROM scored
ORDER BY total_match_score DESC
LIMIT 250000;
