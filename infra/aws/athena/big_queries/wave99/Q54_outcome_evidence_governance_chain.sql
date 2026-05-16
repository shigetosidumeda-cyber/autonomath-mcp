-- Q54_outcome_evidence_governance_chain.sql (Wave 99)
--
-- Outcome × evidence pairing surface — Wave 51 L3 cross_outcome_routing
-- does NOT have a dedicated Glue table at this snapshot (verified
-- 2026-05-17 against jpcite_credit_2026_05 catalog), so the canonical
-- outcome × evidence chain is reconstructed from the closest LIVE-in-
-- Glue surrogates that carry outcome / evidence semantics:
--   * data_subject_request_handling = outcome arm (本人請求 → 処理結果
--     status, which is the outcome of the request flow)
--   * consent_collection_record = evidence arm (consent capture is the
--     evidence anchor for downstream data handling)
--   * data_lineage_disclosure = chain arm (lineage = the routing path
--     between outcome and evidence)
--   * regulatory_audit_outcomes = audit arm (third-party-verified
--     outcome attestation)
--   * application_strategy = baseline anchor (Wave 53 outcome baseline)
--
-- Reads as: for each (jsic_major × wave_family), what is the
-- outcome ↔ evidence ↔ lineage ↔ audit chain density? Answers the
-- "can I attest this outcome with paired evidence + audited lineage?"
-- question that the Wave 51 L3 routing layer is designed to support.
--
-- 5-source cross-section (all LIVE in Glue, Wave 95-97 data governance
-- packets + Wave 53 baseline):
--   wave97_dsr → packet_data_subject_request_handling_v1
--   wave96_consent → packet_consent_collection_record_v1
--   wave95_lineage → packet_data_lineage_disclosure_v1
--   wave_audit → packet_regulatory_audit_outcomes_v1
--   wave53_baseline → packet_application_strategy_v1
--
-- Scan target: ~50-300MB (5 small CTE rollups per-family, COUNT +
-- approx_distinct on subject.id only). Wave 95-97 tables may carry 0
-- rows post-Glue-registration (FULL-SCALE generators in flight), in
-- which case the chain still resolves structurally at 0-rows.
-- Expected row count: ≤ 200 (5 sources × ~20 jsic_major; LIMIT 1000
-- safety).
-- Time estimate: ≤ 60s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (10 cols):
--   wave_family / src / jsic_major / row_count /
--   distinct_subjects / chain_position / chain_density_score /
--   has_outcome / has_evidence / has_lineage

WITH outcome_evidence_chain AS (
  -- wave97_dsr: outcome arm — 本人請求 処理結果 status
  SELECT 'wave97_dsr' AS wave_family,
         'data_subject_request_handling' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id,
         'outcome' AS chain_position
  FROM jpcite_credit_2026_05.packet_data_subject_request_handling_v1

  -- wave96_consent: evidence arm — consent capture record
  UNION ALL
  SELECT 'wave96_consent',
         'consent_collection_record',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'evidence'
  FROM jpcite_credit_2026_05.packet_consent_collection_record_v1

  -- wave95_lineage: chain arm — data lineage disclosure
  UNION ALL
  SELECT 'wave95_lineage',
         'data_lineage_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'lineage'
  FROM jpcite_credit_2026_05.packet_data_lineage_disclosure_v1

  -- wave_audit: audit arm — regulatory audit outcomes
  UNION ALL
  SELECT 'wave_audit',
         'regulatory_audit_outcomes',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'audit'
  FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1

  -- wave53_baseline: baseline anchor — Wave 53 application strategy
  UNION ALL
  SELECT 'wave53_baseline',
         'application_strategy',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'baseline'
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
),
chain_agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    chain_position,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM outcome_evidence_chain
  GROUP BY wave_family, src, jsic_major, chain_position
),
chain_total AS (
  SELECT SUM(row_count) AS total_chain_rows
  FROM chain_agg
)
SELECT
  ca.wave_family,
  ca.src,
  ca.jsic_major,
  ca.row_count,
  ca.distinct_subjects,
  ca.chain_position,
  -- chain_density_score: this (wave_family, jsic_major) cell's share of
  -- the 5-arm chain footprint — high score = densely populated arm in
  -- this JSIC, low score = sparse / empty arm.
  CASE
    WHEN ct.total_chain_rows = 0 THEN 0.0
    ELSE CAST(ca.row_count AS DOUBLE) / CAST(ct.total_chain_rows AS DOUBLE)
  END AS chain_density_score,
  -- has_outcome / has_evidence / has_lineage: boolean flags on the
  -- chain_position so downstream consumers can quickly filter "rows
  -- with all 3 arms ≥ 1 row" = full outcome ↔ evidence ↔ lineage
  -- closure for this (wave_family, jsic_major).
  CASE WHEN ca.chain_position = 'outcome' AND ca.row_count > 0 THEN 1 ELSE 0 END
    AS has_outcome,
  CASE WHEN ca.chain_position = 'evidence' AND ca.row_count > 0 THEN 1 ELSE 0 END
    AS has_evidence,
  CASE WHEN ca.chain_position = 'lineage' AND ca.row_count > 0 THEN 1 ELSE 0 END
    AS has_lineage
FROM chain_agg ca
CROSS JOIN chain_total ct
ORDER BY ca.chain_position, ca.wave_family, ca.row_count DESC
LIMIT 1000
