-- Q60_x402_credit_wallet_settlement_crosscheck.sql (Wave 100)
--
-- x402 + Credit Wallet settlement crosscheck — neither protocol carries
-- its own packet table at this snapshot (settlement events live in
-- Stripe metered + billing_event_ledger contract; verified 2026-05-17
-- against jpcite_credit_2026_05 catalog has NO packet_x402_* /
-- packet_wallet_* tables). The crosscheck is therefore reconstructed
-- from the closest LIVE-in-Glue proxies that carry the
-- "houjin × outcome × settlement-readiness" semantics that x402
-- micropayment + Credit Wallet topup ledger both need:
--   * settlement_readiness_anchor — application_strategy (Wave 53;
--     the outcome strategy whose execution settles ¥3/req).
--   * adjudicated_outcome — regulatory_audit_outcomes (Wave 97; audited
--     outcome = the "settlement-able" arm).
--   * eligibility_proxy — employment_program_eligibility (Wave 97;
--     proxy for "houjin is eligible to receive a settled outcome").
--   * accountability_chain — data_subject_request_handling (Wave 97;
--     DSR completion is a proxy for "settlement chain has audit trail").
--   * payor_universe — houjin_360 (foundation; payor universe anchor).
--   * payee_payment_history — vendor_payment_history_match (Wave 97;
--     payee-side payment-history match — settlement crosscheck arm).
--   * eligibility_attestation_cohort — acceptance_probability (Wave 53.3;
--     cost-band + freshness anchor — Credit Wallet topup justifiability).
--
-- Reads as: for each (jsic_major × settlement arm), what is the
-- crosscheck density? Answers the "is this houjin × outcome safely
-- settlement-able via x402 OR Credit Wallet?" question that the Wave 50
-- RC1 billing_event_ledger contract (mig 087 + mig 085) needs for
-- idempotent double-entry settlement.
--
-- Strategic read: cells where settlement_readiness + adjudicated +
-- accountability are all ≥1 → "agent can transact this outcome via
-- x402 (¥3 micropayment) or Credit Wallet (prefunded)"; cells missing
-- accountability → DOWN-vote settlement (predictive_merge bias).
--
-- 7-source cross-section (all LIVE in Glue, Wave 53 baseline + Wave 53.3
-- cost band + Wave 95-97 governance + foundation):
--   wave53_settle_anchor   → packet_application_strategy_v1
--   wave53_3_cost_attest   → packet_acceptance_probability
--   wave97_adjudicated     → packet_regulatory_audit_outcomes_v1
--   wave97_eligibility     → packet_employment_program_eligibility_v1
--   wave97_accountability  → packet_data_subject_request_handling_v1
--   wave97_payee_history   → packet_vendor_payment_history_match_v1
--   foundation             → packet_houjin_360
--
-- Scan target: ~100-500MB (7 sources, COUNT + approx_distinct on
-- subject.id only; Wave 97 vendor_payment_history is currently the
-- richest non-foundation arm at this snapshot).
-- Expected row count: ≤ 280 (7 src × ~20 jsic_major; LIMIT 1000
-- safety).
-- Time estimate: ≤ 90s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (10 cols):
--   wave_family / src / jsic_major / settlement_arm / row_count /
--   distinct_subjects / x402_eligible_flag / wallet_eligible_flag /
--   pct_of_arm_total / dual_rail_settlement_score

WITH settlement_sources AS (
  -- wave53_settle_anchor: outcome strategy whose execution settles ¥3/req
  SELECT 'wave53_settle_anchor' AS wave_family,
         'application_strategy' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id,
         'settlement_readiness' AS settlement_arm
  FROM jpcite_credit_2026_05.packet_application_strategy_v1

  -- wave53_3_cost_attest: cost-band attestation (Credit Wallet topup
  -- justifiability anchor)
  UNION ALL
  SELECT 'wave53_3_cost_attest',
         'acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         json_extract_scalar(cohort_definition, '$.cohort_id'),
         'cost_attest'
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- wave97_adjudicated: audited outcome arm — settlement-able anchor
  UNION ALL
  SELECT 'wave97_adjudicated',
         'regulatory_audit_outcomes',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'adjudicated'
  FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1

  -- wave97_eligibility: employment program eligibility (payee can
  -- receive a settled outcome)
  UNION ALL
  SELECT 'wave97_eligibility',
         'employment_program_eligibility',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'eligibility'
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1

  -- wave97_accountability: data subject request handling (audit trail
  -- proxy for settlement chain accountability)
  UNION ALL
  SELECT 'wave97_accountability',
         'data_subject_request_handling',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'accountability'
  FROM jpcite_credit_2026_05.packet_data_subject_request_handling_v1

  -- wave97_payee_history: payee-side payment history match (settlement
  -- crosscheck arm)
  UNION ALL
  SELECT 'wave97_payee_history',
         'vendor_payment_history_match',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'payee_history'
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1

  -- foundation: houjin_360 baseline (payor universe anchor)
  UNION ALL
  SELECT 'foundation',
         'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'foundation'
  FROM jpcite_credit_2026_05.packet_houjin_360
),
agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    settlement_arm,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM settlement_sources
  GROUP BY wave_family, src, jsic_major, settlement_arm
),
arm_totals AS (
  SELECT
    settlement_arm,
    SUM(row_count) AS arm_total_rows
  FROM agg
  GROUP BY settlement_arm
)
SELECT
  a.wave_family,
  a.src,
  a.jsic_major,
  a.settlement_arm,
  a.row_count,
  a.distinct_subjects,
  -- x402_eligible_flag: 1 if this row carries an arm that x402
  -- micropayment protocol needs — settlement_readiness + adjudicated
  -- + accountability. Read as "x402 can transact this outcome safely".
  CASE
    WHEN a.settlement_arm IN ('settlement_readiness', 'adjudicated',
                              'accountability') AND a.row_count > 0 THEN 1
    ELSE 0
  END AS x402_eligible_flag,
  -- wallet_eligible_flag: 1 if this row carries an arm that Credit
  -- Wallet topup ledger needs — cost_attest + eligibility +
  -- payee_history. Read as "Credit Wallet can prefund this houjin
  -- for this outcome".
  CASE
    WHEN a.settlement_arm IN ('cost_attest', 'eligibility',
                              'payee_history') AND a.row_count > 0 THEN 1
    ELSE 0
  END AS wallet_eligible_flag,
  -- pct_of_arm_total: this (wave_family, src, jsic_major) cell's
  -- share of its settlement arm's footprint.
  CASE
    WHEN at.arm_total_rows = 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE) / CAST(at.arm_total_rows AS DOUBLE)
  END AS pct_of_arm_total,
  -- dual_rail_settlement_score: log(1+row_count) weighted score —
  -- both x402 + Credit Wallet eligibility ≥1 contribute equally;
  -- foundation arm contributes baseline +0.5.
  CASE
    WHEN a.settlement_arm = 'foundation' THEN 0.5 * ln(1.0 + CAST(a.row_count AS DOUBLE))
    WHEN a.settlement_arm IN ('settlement_readiness', 'adjudicated',
                              'accountability',
                              'cost_attest', 'eligibility',
                              'payee_history') THEN ln(1.0 + CAST(a.row_count AS DOUBLE))
    ELSE 0.0
  END AS dual_rail_settlement_score
FROM agg a
JOIN arm_totals at ON a.settlement_arm = at.settlement_arm
ORDER BY a.settlement_arm, a.row_count DESC, a.wave_family
LIMIT 1000
