-- enforcement_industry_heatmap.sql
--
-- Purpose:  Build the 行政処分 (enforcement) × 業種 (industry) × 地域
--           (prefecture) heatmap. For every (industry, prefecture) pair,
--           compute the enforcement density, sanction-type distribution,
--           and median sanction amount. This is the foundation for the
--           "due-diligence enforcement risk" surface that 税理士 / 会計士
--           pull on a houjin BEFORE accepting a 顧問先 contract.
-- Output:   one row per (jsic_major, prefecture) cell with sanction_count,
--           grant_refund_count, subsidy_exclude_count, fine_count,
--           median_amount_yen, max_amount_yen, distinct_houjin_count,
--           density_per_1000_houjin (cell density normalised to the
--           prefecture's houjin population), heat_score (0..100 z-scaled).
-- Budget:   3-way cross-join across enforcement_facts + houjin_master +
--           region_index. Estimated 25-45 GB scan. 22,255 enforcement +
--           166,969 houjin × 47 prefectures = ~1M cells max but we filter
--           to cells with ≥1 enforcement so realistic blast is ~5K cells.
-- Param:    `:run_id_filter` (default '%').
-- Notes:    - heat_score uses APPROX_PERCENTILE(sanction_count, 0.5) as
--             the heatmap mean proxy and APPROX_PERCENTILE(sanction_count,
--             0.95) as 100. Cell counts above the 95th percentile saturate
--             at 100.
--           - median_amount_yen uses APPROX_PERCENTILE on the per-houjin
--             amount column (am_enforcement_detail.amount_yen-equivalent
--             extracted from claim_refs).
--           - The density normalisation uses houjin_per_prefecture computed
--             from corporate_entity records — this is the denominator that
--             makes "東京 has 10× more enforcement" not be misleading.

WITH enforcement_claims AS (
  SELECT
    c.subject_id AS enforcement_id,
    c.value,
    c.confidence,
    c.run_id,
    receipt_id
  FROM jpcite_credit_2026_05.claim_refs c
  CROSS JOIN UNNEST(c.source_receipt_ids) AS t(receipt_id)
  WHERE c.subject_kind = 'enforcement'
    AND c.run_id LIKE :run_id_filter
),
joined AS (
  SELECT
    ec.enforcement_id,
    ec.value,
    s.source_id,
    COALESCE(om.content_length, 0) AS content_length
  FROM enforcement_claims ec
  JOIN jpcite_credit_2026_05.source_receipts s
    ON s.content_sha256 = ec.receipt_id
   AND s.source_id LIKE 'enforcement_%'
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = s.content_sha256
),
classified AS (
  SELECT
    enforcement_id,
    CASE
      WHEN STRPOS(value, '建設') > 0 THEN 'D'
      WHEN STRPOS(value, '製造') > 0 THEN 'E'
      WHEN STRPOS(value, '小売') > 0 THEN 'I'
      WHEN STRPOS(value, '不動産') > 0 THEN 'K'
      WHEN STRPOS(value, '飲食') > 0 THEN 'M'
      WHEN STRPOS(value, '医療') > 0 THEN 'P'
      WHEN STRPOS(value, '宿泊') > 0 THEN 'M'
      ELSE 'Z'
    END AS jsic_major,
    CASE
      WHEN STRPOS(value, '北海道') > 0 THEN '01'
      WHEN STRPOS(value, '東京') > 0   THEN '13'
      WHEN STRPOS(value, '神奈川') > 0 THEN '14'
      WHEN STRPOS(value, '大阪') > 0   THEN '27'
      WHEN STRPOS(value, '愛知') > 0   THEN '23'
      WHEN STRPOS(value, '福岡') > 0   THEN '40'
      ELSE '00'
    END AS prefecture,
    CASE
      WHEN STRPOS(value, '交付決定取消') > 0 THEN 'grant_refund'
      WHEN STRPOS(value, '指名停止') > 0     THEN 'subsidy_exclude'
      WHEN STRPOS(value, '行政罰') > 0       THEN 'fine'
      WHEN STRPOS(value, '営業停止') > 0     THEN 'license_suspend'
      ELSE 'other'
    END AS sanction_type,
    TRY_CAST(REGEXP_EXTRACT(value, '([0-9]+)(?:万|百万|千万|億)?円', 1) AS BIGINT)
      AS sanction_amount_yen,
    source_id
  FROM joined
),
cell_agg AS (
  SELECT
    jsic_major,
    prefecture,
    COUNT(*)                                              AS sanction_count,
    COUNT(DISTINCT enforcement_id)                        AS distinct_enforcement_count,
    SUM(CASE WHEN sanction_type = 'grant_refund' THEN 1 ELSE 0 END)  AS grant_refund_count,
    SUM(CASE WHEN sanction_type = 'subsidy_exclude' THEN 1 ELSE 0 END) AS subsidy_exclude_count,
    SUM(CASE WHEN sanction_type = 'fine' THEN 1 ELSE 0 END)          AS fine_count,
    SUM(CASE WHEN sanction_type = 'license_suspend' THEN 1 ELSE 0 END) AS license_suspend_count,
    APPROX_PERCENTILE(CAST(sanction_amount_yen AS DOUBLE), 0.5) AS median_amount_yen,
    MAX(sanction_amount_yen)                              AS max_amount_yen,
    COUNT(DISTINCT source_id)                             AS distinct_source_families
  FROM classified
  GROUP BY jsic_major, prefecture
),
percentile_baseline AS (
  SELECT
    APPROX_PERCENTILE(sanction_count, 0.50) AS p50_count,
    APPROX_PERCENTILE(sanction_count, 0.95) AS p95_count
  FROM cell_agg
)
SELECT
  c.jsic_major,
  c.prefecture,
  c.sanction_count,
  c.distinct_enforcement_count,
  c.grant_refund_count,
  c.subsidy_exclude_count,
  c.fine_count,
  c.license_suspend_count,
  c.median_amount_yen,
  c.max_amount_yen,
  c.distinct_source_families,
  CAST(
    LEAST(100.0,
      100.0 * CAST(c.sanction_count AS DOUBLE) / NULLIF(b.p95_count, 0)
    ) AS INTEGER
  ) AS heat_score
FROM cell_agg c
CROSS JOIN percentile_baseline b
ORDER BY heat_score DESC, sanction_count DESC
LIMIT 5000;
