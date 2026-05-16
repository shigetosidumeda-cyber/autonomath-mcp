-- entity_resolution_full.sql
--
-- Purpose:  Identity resolution across the three corporate-entity-keyed
--           packet families (corresponding to J02 法人番号 / J07 gBizINFO /
--           J10 法務局 source families):
--             - packet_houjin_360                   (kind = "houjin", id = houjin_bangou)
--             - packet_invoice_houjin_cross_check_v1 (id = T-prefixed invoice)
--             - packet_invoice_registrant_public_check_v1 (id = T-prefixed invoice)
--             - packet_company_public_baseline_v1    (id = houjin_bangou)
--             - packet_vendor_due_diligence_v1       (id = houjin_bangou)
--
-- Output:   one row per houjin_bangou with axis presence + cross-source
--           agreement signal:
--             - houjin_bangou                       13-digit corp number (or T-prefix invoice trimmed)
--             - has_houjin_360                      0/1 presence flag
--             - has_invoice_cross_check             0/1
--             - has_invoice_registrant              0/1
--             - has_company_baseline                0/1
--             - has_vendor_dd                       0/1
--             - axis_presence_bitmap                5-bit summary 0..31
--             - distinct_source_axes                COUNT(non-null axes)
--             - resolution_confidence               =distinct_source_axes / 5.0
--             - top_axes_concat                     CSV of present axes
--
-- Budget:   ~200-400 MB scan across 5 packet tables.
-- Notes:    Trims the leading 'T' on packet_invoice_* object_ids so the
--           join key matches the 13-digit houjin_bangou used by the
--           other tables. ``packet_houjin_360.subject`` is JSON-string,
--           so we ``json_extract_scalar(subject, '$.id')`` to pull the
--           id; same pattern for ``packet_vendor_due_diligence_v1``
--           and ``packet_company_public_baseline_v1``.

WITH h360 AS (
  SELECT DISTINCT json_extract_scalar(subject, '$.id') AS houjin_bangou
  FROM jpcite_credit_2026_05.packet_houjin_360
  WHERE json_extract_scalar(subject, '$.kind') = 'houjin'
),
inv_cross AS (
  SELECT DISTINCT
    CASE
      WHEN SUBSTR(object_id, 1, 1) = 'T' THEN SUBSTR(object_id, 2)
      ELSE object_id
    END AS houjin_bangou
  FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
),
inv_reg AS (
  SELECT DISTINCT
    CASE
      -- object_id pattern: "invoice_registrant_public_check_v1:T<13>"
      WHEN STRPOS(object_id, ':T') > 0 THEN SUBSTR(object_id, STRPOS(object_id, ':T') + 2)
      WHEN SUBSTR(object_id, 1, 1) = 'T' THEN SUBSTR(object_id, 2)
      ELSE object_id
    END AS houjin_bangou
  FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
),
co_base AS (
  SELECT DISTINCT
    CASE
      WHEN STRPOS(object_id, ':') > 0 THEN ELEMENT_AT(SPLIT(object_id, ':'), CARDINALITY(SPLIT(object_id, ':')))
      ELSE object_id
    END AS houjin_bangou
  FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
),
vendor_dd AS (
  SELECT DISTINCT object_id AS houjin_bangou
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
),
all_ids AS (
  SELECT houjin_bangou FROM h360
  UNION
  SELECT houjin_bangou FROM inv_cross
  UNION
  SELECT houjin_bangou FROM inv_reg
  UNION
  SELECT houjin_bangou FROM co_base
  UNION
  SELECT houjin_bangou FROM vendor_dd
)
SELECT
  a.houjin_bangou,
  CASE WHEN h.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END AS has_houjin_360,
  CASE WHEN ic.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END AS has_invoice_cross_check,
  CASE WHEN ir.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END AS has_invoice_registrant,
  CASE WHEN cb.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END AS has_company_baseline,
  CASE WHEN vd.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END AS has_vendor_dd,
  (
    (CASE WHEN h.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    + (CASE WHEN ic.houjin_bangou IS NOT NULL THEN 2 ELSE 0 END)
    + (CASE WHEN ir.houjin_bangou IS NOT NULL THEN 4 ELSE 0 END)
    + (CASE WHEN cb.houjin_bangou IS NOT NULL THEN 8 ELSE 0 END)
    + (CASE WHEN vd.houjin_bangou IS NOT NULL THEN 16 ELSE 0 END)
  ) AS axis_presence_bitmap,
  (
    (CASE WHEN h.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    + (CASE WHEN ic.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    + (CASE WHEN ir.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    + (CASE WHEN cb.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    + (CASE WHEN vd.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
  ) AS distinct_source_axes,
  (
    (
      (CASE WHEN h.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN ic.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN ir.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN cb.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN vd.houjin_bangou IS NOT NULL THEN 1 ELSE 0 END)
    ) / 5.0
  ) AS resolution_confidence,
  CONCAT_WS(',',
    CASE WHEN h.houjin_bangou IS NOT NULL THEN 'h360' END,
    CASE WHEN ic.houjin_bangou IS NOT NULL THEN 'invoice_cross_check' END,
    CASE WHEN ir.houjin_bangou IS NOT NULL THEN 'invoice_registrant' END,
    CASE WHEN cb.houjin_bangou IS NOT NULL THEN 'company_baseline' END,
    CASE WHEN vd.houjin_bangou IS NOT NULL THEN 'vendor_dd' END
  ) AS top_axes_concat
FROM all_ids a
LEFT JOIN h360 h        ON a.houjin_bangou = h.houjin_bangou
LEFT JOIN inv_cross ic  ON a.houjin_bangou = ic.houjin_bangou
LEFT JOIN inv_reg ir    ON a.houjin_bangou = ir.houjin_bangou
LEFT JOIN co_base cb    ON a.houjin_bangou = cb.houjin_bangou
LEFT JOIN vendor_dd vd  ON a.houjin_bangou = vd.houjin_bangou
ORDER BY distinct_source_axes DESC, a.houjin_bangou ASC
LIMIT 50000;
