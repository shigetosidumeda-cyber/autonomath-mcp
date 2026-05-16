-- q22_entity360_x_houjin_x_allwave_footprint.sql (Wave 70-more)
--
-- Entity_360 (Wave 69) × foundation packet_houjin_360 entity resolution
-- × all-Wave footprint. Counts, per houjin_bangou (when present), how
-- many distinct Wave 69 entity_360 facets co-occur with the houjin in
-- the foundation packet_houjin_360, and how many Wave 53-76 packet
-- sources reference the same houjin somewhere in their subject or
-- entity_id JSON paths.
--
-- This is the canonical "give me an entity footprint" query — given
-- a houjin, list how many distinct packet families touch it and which
-- 360 facets are populated. Drives the M&A advisor + 採択コンサル
-- "moat density per entity" surface.
--
-- Pattern: foundation houjin_360 provides the entity baseline (note:
-- houjin_bangou lives inside the subject JSON for packet_houjin_360,
-- and as a top-level column on the Wave 69 entity_360_* family).
-- We approximate the cross-wave footprint with COUNT(DISTINCT) over
-- per-packet houjin_bangou observations. Packets without houjin_bangou
-- as a top-level column AND without a subject.houjin_bangou json key
-- are intentionally excluded from the carrier list so the scan stays
-- cheap (no per-row json walk on unrelated paths).

WITH houjin_baseline AS (
  -- Foundation: packet_houjin_360 has houjin_bangou inside the subject JSON.
  SELECT
    'foundation_houjin_360' AS facet,
    json_extract_scalar(subject, '$.id') AS houjin_bangou,
    COUNT(*) AS row_count
  FROM jpcite_credit_2026_05.packet_houjin_360
  WHERE json_extract_scalar(subject, '$.id') IS NOT NULL
    AND json_extract_scalar(subject, '$.id') <> ''
    AND json_extract_scalar(subject, '$.kind') = 'houjin'
  GROUP BY json_extract_scalar(subject, '$.id')
),
e360_facets AS (
  -- Wave 69 entity_360 family (9 packets, all top-level houjin_bangou)
  SELECT 'entity_360_summary' AS facet, houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_certification_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_certification_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_compliance_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_compliance_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_court_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_court_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_invoice_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_invoice_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_partner_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_partner_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_risk_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_risk_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_subsidy_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_subsidy_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'entity_succession_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_succession_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
),
allwave_carriers AS (
  -- Wave 53-76 packets that expose houjin_bangou as a top-level Glue
  -- column. (packet_houjin_360 / patent_corp_360 / gbiz_invoice /
  -- invoice_registrant_public_check / vendor_due_diligence /
  -- succession_program_matching carry it only inside JSON and are
  -- excluded to keep the scan cheap.)
  SELECT 'wave58_board_member_overlap' AS src, houjin_bangou
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'wave58_business_partner_360', houjin_bangou
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'wave68_vendor_payment_history_match', houjin_bangou
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'wave69_entity_360_summary', houjin_bangou
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'wave76_founding_succession_chain', houjin_bangou
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
  UNION ALL SELECT 'wave76_succession_event_pulse', houjin_bangou
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> ''
),
e360_per_houjin AS (
  -- For each houjin: how many distinct entity_360 facets co-occur
  SELECT houjin_bangou,
         COUNT(DISTINCT facet) AS e360_distinct_facets,
         COUNT(*) AS e360_total_rows
  FROM e360_facets
  GROUP BY houjin_bangou
),
allwave_per_houjin AS (
  -- For each houjin: how many distinct cross-wave packets touch it
  SELECT houjin_bangou,
         COUNT(DISTINCT src) AS allwave_distinct_packets,
         COUNT(*) AS allwave_total_observations
  FROM allwave_carriers
  GROUP BY houjin_bangou
),
top_carriers AS (
  -- Rank houjin by footprint density and surface top 200
  SELECT
    f.houjin_bangou,
    f.row_count AS foundation_row_count,
    COALESCE(e.e360_distinct_facets, 0) AS e360_distinct_facets,
    COALESCE(e.e360_total_rows, 0) AS e360_total_rows,
    COALESCE(a.allwave_distinct_packets, 0) AS allwave_distinct_packets,
    COALESCE(a.allwave_total_observations, 0) AS allwave_total_observations,
    -- 'footprint score' = 360 facet density + allwave packet density,
    -- both 0-1 normalized (e360 has 9 facets, allwave has 6 carriers).
    (COALESCE(e.e360_distinct_facets, 0) / 9.0) +
    (COALESCE(a.allwave_distinct_packets, 0) / 6.0) AS footprint_score
  FROM houjin_baseline f
  LEFT JOIN e360_per_houjin e ON e.houjin_bangou = f.houjin_bangou
  LEFT JOIN allwave_per_houjin a ON a.houjin_bangou = f.houjin_bangou
)
SELECT
  houjin_bangou,
  foundation_row_count,
  e360_distinct_facets,
  e360_total_rows,
  allwave_distinct_packets,
  allwave_total_observations,
  CAST(footprint_score AS DECIMAL(4, 3)) AS footprint_score
FROM top_carriers
ORDER BY footprint_score DESC, foundation_row_count DESC
LIMIT 200
