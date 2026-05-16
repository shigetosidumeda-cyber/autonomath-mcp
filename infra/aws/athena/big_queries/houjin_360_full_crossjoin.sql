-- houjin_360_full_crossjoin.sql
--
-- Purpose:  Materialise a 7-axis 法人360 packet for every corporate_entity
--           record (target 166,969 houjin) by cross-joining the seven
--           authoritative source families that we crawl into the derived
--           bucket:
--             1. NTA invoice registrants (適格事業者番号)
--             2. gBizINFO houjin master (代表者・所在地・資本金)
--             3. 法務局 (公告 / 商業登記簿)
--             4. 行政処分 (J05) — enforcement_decision_refs
--             5. 採択事例 (J03 / J0X_deep)
--             6. 通達 / 法令引用 (J04 + J06)
--             7. 入札 / 落札履歴 (J07)
--           Output is one wide row per houjin_bangou with arrays of citations
--           per axis. Downstream `generate_houjin_360_packets.py` consumes
--           this row directly.
-- Output:   one row per houjin_bangou with 7 ARRAY<ROW> axes + axis_coverage
--           bitmap (0..127) + last_updated_at + total_cited_bytes.
-- Budget:   FULL cross-source scan across all derived partitions. Estimated
--           ~40-80 GB scan after deep + ultradeep land (currently <1 GB).
--           At $5/TB that's $0.20-0.40 per execution at full corpus.
-- Param:    `:run_id_filter` LIKE expression (default '%' = all runs).
--           Pin to a specific cohort with e.g. `'2026-05-1%'` for prod.
-- Notes:    - CROSS JOIN UNNEST(source_receipt_ids) is used to bridge
--             claim_refs → source_receipts on the receipt fanout axis.
--           - axis_coverage_bitmap is a 7-bit summary: bit i = axis i has
--             ≥1 citation. Downstream cohort matchers index on this.
--           - LIMIT 200000 is a hard cap so a runaway scan stays under the
--             100 GB workgroup cutoff. 166,969 houjin + headroom.

WITH cr AS (
  SELECT
    c.subject_id  AS houjin_bangou,
    c.claim_kind,
    c.value,
    c.confidence,
    c.run_id,
    receipt_id
  FROM jpcite_credit_2026_05.claim_refs AS c
  CROSS JOIN UNNEST(c.source_receipt_ids) AS t(receipt_id)
  WHERE c.subject_kind = 'houjin'
    AND c.run_id LIKE :run_id_filter
),
joined AS (
  SELECT
    cr.houjin_bangou,
    cr.claim_kind,
    cr.value,
    cr.confidence,
    cr.run_id,
    s.source_id,
    s.receipt_kind,
    COALESCE(om.content_length, 0) AS content_length
  FROM cr
  JOIN jpcite_credit_2026_05.source_receipts AS s
    ON s.content_sha256 = cr.receipt_id
   AND s.run_id = cr.run_id
  LEFT JOIN jpcite_credit_2026_05.object_manifest AS om
    ON om.content_sha256 = s.content_sha256
   AND om.run_id = s.run_id
)
SELECT
  houjin_bangou,
  -- Axis 1: NTA invoice registrants
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'nta_%' THEN value END)
    FILTER (WHERE source_id LIKE 'nta_%')                           AS nta_invoice_axis,
  -- Axis 2: gBizINFO houjin master
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'gbiz_%' THEN value END)
    FILTER (WHERE source_id LIKE 'gbiz_%')                          AS gbiz_master_axis,
  -- Axis 3: 法務局 (J10)
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'moj_%' THEN value END)
    FILTER (WHERE source_id LIKE 'moj_%')                           AS moj_registry_axis,
  -- Axis 4: 行政処分 (J05)
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'enforcement_%' THEN value END)
    FILTER (WHERE source_id LIKE 'enforcement_%')                   AS enforcement_axis,
  -- Axis 5: 採択事例 (J03 / J0X_deep)
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'adoption_%' OR source_id LIKE 'j03_%' THEN value END)
    FILTER (WHERE source_id LIKE 'adoption_%' OR source_id LIKE 'j03_%') AS adoption_axis,
  -- Axis 6: 通達 / 法令引用 (J04 + J06)
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'law_%' OR source_id LIKE 'tsutatsu_%' THEN value END)
    FILTER (WHERE source_id LIKE 'law_%' OR source_id LIKE 'tsutatsu_%') AS law_tsutatsu_axis,
  -- Axis 7: 入札 / 落札履歴 (J07)
  ARRAY_AGG(DISTINCT CASE WHEN source_id LIKE 'bid_%' THEN value END)
    FILTER (WHERE source_id LIKE 'bid_%')                           AS bid_axis,
  -- 7-bit axis_coverage_bitmap
  (CASE WHEN COUNT(CASE WHEN source_id LIKE 'nta_%' THEN 1 END) > 0 THEN 1 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'gbiz_%' THEN 1 END) > 0 THEN 2 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'moj_%' THEN 1 END) > 0 THEN 4 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'enforcement_%' THEN 1 END) > 0 THEN 8 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'adoption_%' OR source_id LIKE 'j03_%' THEN 1 END) > 0 THEN 16 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'law_%' OR source_id LIKE 'tsutatsu_%' THEN 1 END) > 0 THEN 32 ELSE 0 END)
  + (CASE WHEN COUNT(CASE WHEN source_id LIKE 'bid_%' THEN 1 END) > 0 THEN 64 ELSE 0 END)
    AS axis_coverage_bitmap,
  COUNT(DISTINCT source_id)            AS distinct_source_families,
  AVG(confidence)                      AS avg_confidence,
  SUM(content_length)                  AS total_cited_bytes,
  MAX(run_id)                          AS last_run_id
FROM joined
GROUP BY houjin_bangou
HAVING COUNT(DISTINCT source_id) >= 2
ORDER BY distinct_source_families DESC, total_cited_bytes DESC
LIMIT 200000;
