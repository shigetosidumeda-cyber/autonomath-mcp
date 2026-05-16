-- Q58_outcome_x_cost_band_x_evidence_freshness.sql (Wave 100)
--
-- Outcome × cost band × evidence freshness — Wave 99 outcome_cost_band
-- routing × Wave 51 L3 cross_outcome_routing × Wave 51 L4
-- predictive_merge. Wave 51 L3/L4 internal modules do NOT carry their
-- own Glue tables at this snapshot (verified 2026-05-17 against
-- jpcite_credit_2026_05 catalog) — they are surfaced via the
-- representative-table proxy pattern established in Q54/Q55/Q56:
--   * outcome arm — application_strategy (Wave 53) + data_subject_request_handling
--     (Wave 97 outcome arm) + regulatory_audit_outcomes (Wave 97 audit arm)
--   * cost-band proxy — acceptance_probability (Wave 53.3) carries
--     freshest_announced_at + probability_estimate which fence the
--     outcome estimated_price_jpy ¥300-¥900 band (Wave 50 RC1 14
--     outcome contracts).
--   * evidence freshness arm — application_strategy.generated_at + data_lineage_disclosure
--     + master_data_governance (Wave 95-96 governance freshness anchor).
--
-- Reads as: for each (jsic_major × outcome arm), which cost-band stratum
-- carries the freshest evidence chain? Answers the "is this outcome's
-- pricing justifiable AND evidence-current?" question that Wave 51 L4
-- predictive_merge needs for outcome contract enforcement.
--
-- Strategic read: high-density cells where outcome arm = high + cost_band
-- proxy = mid + evidence freshness = recent (≤ 30d via generated_at)
-- → "agent can charge ¥3 with current evidence and outcome attestation".
-- Low-density cells → stale evidence or untrusted cost band → predictive
-- merge should DOWN-vote the outcome.
--
-- 5-source cross-section (all LIVE in Glue, Wave 53 baseline + Wave 53.3
-- cost-band proxy + Wave 95-97 governance freshness anchor):
--   wave53_outcome → packet_application_strategy_v1
--   wave53_3_cost_band → packet_acceptance_probability
--   wave95_lineage_freshness → packet_data_lineage_disclosure_v1
--   wave96_master_freshness → packet_master_data_governance_v1
--   wave97_audit_outcome → packet_regulatory_audit_outcomes_v1
--
-- Scan target: ~50-300MB (5 sources, COUNT + approx_distinct, no
-- full-row materialization). Wave 95-97 tables may carry 0 rows
-- post-Glue-registration (FULL-SCALE generators in flight), in which
-- case the chain still resolves structurally at 0-rows and the
-- freshness arm folds gracefully to NULL evidence_age_days.
-- Expected row count: ≤ 200 (5 sources × ~20 jsic_major; LIMIT 1000
-- safety).
-- Time estimate: ≤ 60s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (10 cols):
--   wave_family / src / jsic_major / outcome_arm / cost_band /
--   row_count / distinct_subjects / evidence_age_days /
--   freshness_grade / outcome_x_cost_proxy_score

WITH outcome_cost_freshness AS (
  -- wave53_outcome: application strategy baseline (outcome anchor)
  SELECT 'wave53_outcome' AS wave_family,
         'application_strategy' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id,
         'outcome' AS outcome_arm,
         'baseline' AS cost_band,
         try(date_diff('day',
                       try(date_parse(generated_at, '%Y-%m-%dT%H:%i:%s')),
                       current_date)) AS evidence_age_days
  FROM jpcite_credit_2026_05.packet_application_strategy_v1

  -- wave53_3_cost_band: acceptance probability (cost-band proxy via
  -- probability_estimate — fences outcome ¥300-¥900 band).
  UNION ALL
  SELECT 'wave53_3_cost_band',
         'acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         json_extract_scalar(cohort_definition, '$.cohort_id'),
         'cost_band',
         CASE
           WHEN try_cast(probability_estimate AS DOUBLE) >= 0.7 THEN 'high_300'
           WHEN try_cast(probability_estimate AS DOUBLE) >= 0.4 THEN 'mid_600'
           WHEN try_cast(probability_estimate AS DOUBLE) >= 0.1 THEN 'low_900'
           ELSE 'unknown'
         END,
         try(date_diff('day',
                       try(date_parse(freshest_announced_at, '%Y-%m-%dT%H:%i:%s')),
                       current_date))
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- wave95_lineage_freshness: data lineage disclosure (evidence chain
  -- freshness anchor)
  UNION ALL
  SELECT 'wave95_lineage_freshness',
         'data_lineage_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'freshness',
         'evidence_anchor',
         try(date_diff('day',
                       try(date_parse(generated_at, '%Y-%m-%dT%H:%i:%s')),
                       current_date))
  FROM jpcite_credit_2026_05.packet_data_lineage_disclosure_v1

  -- wave96_master_freshness: master data governance (evidence chain
  -- freshness anchor)
  UNION ALL
  SELECT 'wave96_master_freshness',
         'master_data_governance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'freshness',
         'evidence_anchor',
         try(date_diff('day',
                       try(date_parse(generated_at, '%Y-%m-%dT%H:%i:%s')),
                       current_date))
  FROM jpcite_credit_2026_05.packet_master_data_governance_v1

  -- wave97_audit_outcome: regulatory audit outcomes (audit-attested
  -- outcome arm — third-party verified)
  UNION ALL
  SELECT 'wave97_audit_outcome',
         'regulatory_audit_outcomes',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'outcome',
         'audited',
         try(date_diff('day',
                       try(date_parse(generated_at, '%Y-%m-%dT%H:%i:%s')),
                       current_date))
  FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1
),
agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    outcome_arm,
    cost_band,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects,
    avg(CAST(evidence_age_days AS DOUBLE)) AS avg_evidence_age_days
  FROM outcome_cost_freshness
  GROUP BY wave_family, src, jsic_major, outcome_arm, cost_band
)
SELECT
  a.wave_family,
  a.src,
  a.jsic_major,
  a.outcome_arm,
  a.cost_band,
  a.row_count,
  a.distinct_subjects,
  -- evidence_age_days: avg per (wave_family, jsic_major, outcome_arm,
  -- cost_band) cell — NULL when source lacks generated_at parseability.
  a.avg_evidence_age_days AS evidence_age_days,
  -- freshness_grade: A (≤30d) / B (≤90d) / C (≤365d) / D (>365d) /
  -- UNK (no parseable timestamp). Wave 51 L4 predictive_merge bias:
  -- A,B = trustable; C = downvote 0.5; D = downvote 0.2; UNK = skip.
  CASE
    WHEN a.avg_evidence_age_days IS NULL THEN 'UNK'
    WHEN a.avg_evidence_age_days <= 30 THEN 'A'
    WHEN a.avg_evidence_age_days <= 90 THEN 'B'
    WHEN a.avg_evidence_age_days <= 365 THEN 'C'
    ELSE 'D'
  END AS freshness_grade,
  -- outcome_x_cost_proxy_score: row_count weighted by inverse age
  -- (rough trust signal for the outcome × cost-band × freshness cell;
  -- higher = more outcome attestation backed by current evidence).
  CASE
    WHEN a.avg_evidence_age_days IS NULL OR a.avg_evidence_age_days < 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE)
         / (1.0 + CAST(a.avg_evidence_age_days AS DOUBLE) / 30.0)
  END AS outcome_x_cost_proxy_score
FROM agg a
ORDER BY a.outcome_arm, a.cost_band, a.row_count DESC, a.wave_family
LIMIT 1000
