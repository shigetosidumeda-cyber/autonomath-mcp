-- target_db: autonomath
-- migration 064_unified_rule_view (R9 unified rule_engine, 2026-04-25)
--
-- Creates the SQL view `am_unified_rule` projecting all 6 rule corpora into a
-- single (rule_id, source_table, scope_program_id, kind, severity, message_ja,
-- source_url) shape. This is the read surface for the new MCP tool
-- `rule_engine_check` (see src/jpintel_mcp/mcp/autonomath_tools/rule_engine_tool.py).
--
-- Design source: analysis_wave18/_r9_unified_rule_engine_2026-04-25.md §4.2.
--
-- ============================================================================
-- BACKGROUND
-- ============================================================================
--   Six rule corpora live in autonomath.db today, each with disjoint id
--   namespaces and disjoint consumers:
--
--     jpi_exclusion_rules       181 rows  (mixed: 13 UNI-…, 166 human names)
--     am_compat_matrix       48,815 rows  (certification:… / program:… / loan:…)
--     am_combo_calculator        56 rows  (members_json with arbitrary ids)
--     am_subsidy_rule            44 rows  (program:…)
--     am_tax_rule               145 rows  (tax_measure:…)
--     am_validation_rule          6 rows  (applies_to=intake; no per-program scope)
--
--   Cross-coverage at apply time (R9 §1):
--     subsidy_rule ∩ compat = 4/43  (9%)
--     tax_rule     ∩ compat = 37/133 (28%)
--     exclusion    ∩ compat = 0/125 (DISJOINT — manual mapping P0.2 pending)
--
--   The 0% exclusion ∩ compat join means the dark-inventory risk is silent
--   miss, not contradiction. The unified view exposes ALL rows projected to
--   the same shape so the rule_engine can iterate them without per-corpus
--   special casing. Coverage is reported back to the caller via a
--   data_quality.exclusion_join_coverage_pct field.
--
-- ============================================================================
-- VIEW
-- ============================================================================
-- Columns:
--   rule_id           unique within source_table; we prepend source_table to
--                     guarantee global uniqueness in the unified surface.
--   source_table      provenance — caller can re-fetch the raw row.
--   scope_program_id  the program(s) the rule applies to (NULL = global).
--                     For pairwise corpora (compat / exclusion), this is the
--                     A side; the B side is exposed in pair_program_id.
--   pair_program_id   the B side for pairwise corpora; NULL otherwise.
--   kind              taxonomy across corpora: absolute / exclude / prerequisite
--                     / compat:compatible / compat:incompatible / compat:case_by_case
--                     / compat:unknown / combo / subsidy / tax / validation.
--   severity          critical / warning / info / NULL.
--   message_ja        human-readable Japanese summary.
--   source_url        primary-source citation (or NULL when not stored).
--
-- A view (not materialized) is sufficient: read traffic is bounded by the
-- rule_engine's per-call program_id filter (≤ a few thousand rows touched),
-- and indexes on the underlying tables drive the query plan.
-- ============================================================================

DROP VIEW IF EXISTS am_unified_rule;

CREATE VIEW am_unified_rule AS
-- 1) jpi_exclusion_rules → exclude / prerequisite / absolute / etc.
SELECT
    'exclusion:' || rule_id                          AS rule_id,
    'jpi_exclusion_rules'                            AS source_table,
    program_a                                        AS scope_program_id,
    program_b                                        AS pair_program_id,
    CASE
        WHEN kind = 'exclude'      THEN 'exclude'
        WHEN kind = 'prerequisite' THEN 'prerequisite'
        WHEN kind = 'absolute'     THEN 'absolute'
        ELSE 'exclude:' || kind
    END                                              AS kind,
    severity                                         AS severity,
    description                                      AS message_ja,
    json_extract(source_urls_json, '$[0]')           AS source_url
FROM jpi_exclusion_rules

UNION ALL

-- 2) am_compat_matrix → compat:<status> (the dark inventory, 48,815 rows)
SELECT
    'compat:' || program_a_id || ':' || program_b_id AS rule_id,
    'am_compat_matrix'                               AS source_table,
    program_a_id                                     AS scope_program_id,
    program_b_id                                     AS pair_program_id,
    'compat:' || compat_status                       AS kind,
    CASE compat_status
        WHEN 'incompatible' THEN 'critical'
        WHEN 'case_by_case' THEN 'warning'
        ELSE 'info'
    END                                              AS severity,
    COALESCE(rationale_short, conditions_text)       AS message_ja,
    source_url                                       AS source_url
FROM am_compat_matrix

UNION ALL

-- 3) am_combo_calculator → combo (legal stacking patterns)
SELECT
    'combo:' || combo_id                             AS rule_id,
    'am_combo_calculator'                            AS source_table,
    NULL                                             AS scope_program_id,
    NULL                                             AS pair_program_id,
    'combo'                                          AS kind,
    'info'                                           AS severity,
    combo_name                                       AS message_ja,
    NULL                                             AS source_url
FROM am_combo_calculator

UNION ALL

-- 4) am_subsidy_rule → subsidy (per-program rate / cap)
SELECT
    'subsidy:' || subsidy_rule_id                    AS rule_id,
    'am_subsidy_rule'                                AS source_table,
    program_entity_id                                AS scope_program_id,
    NULL                                             AS pair_program_id,
    'subsidy'                                        AS kind,
    'info'                                           AS severity,
    rule_type                                        AS message_ja,
    source_url                                       AS source_url
FROM am_subsidy_rule

UNION ALL

-- 5) am_tax_rule → tax (per-measure rate / cap / period)
SELECT
    'tax:' || tax_measure_entity_id || ':' || rule_type AS rule_id,
    'am_tax_rule'                                       AS source_table,
    tax_measure_entity_id                               AS scope_program_id,
    NULL                                                AS pair_program_id,
    'tax'                                               AS kind,
    'info'                                              AS severity,
    rule_type || COALESCE(' (' || article_ref || ')', '') AS message_ja,
    source_url                                          AS source_url
FROM am_tax_rule

UNION ALL

-- 6) am_validation_rule → validation (6 generic predicates)
SELECT
    'validation:' || rule_id                         AS rule_id,
    'am_validation_rule'                             AS source_table,
    scope_entity_id                                  AS scope_program_id,
    NULL                                             AS pair_program_id,
    'validation'                                     AS kind,
    severity                                         AS severity,
    message_ja                                       AS message_ja,
    NULL                                             AS source_url
FROM am_validation_rule
WHERE active = 1;

-- Sanity counts (informational; SELECT-only, never executed by the runner):
--   SELECT source_table, COUNT(*) FROM am_unified_rule GROUP BY source_table;
--     jpi_exclusion_rules     181
--     am_compat_matrix     48,815
--     am_combo_calculator      56
--     am_subsidy_rule          44
--     am_tax_rule             145
--     am_validation_rule        6
--     ---------------------------
--     TOTAL                49,247
