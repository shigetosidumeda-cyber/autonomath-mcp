-- target_db: autonomath
-- §10.10 (7) Hallucination Guard — KPI rollup view.
-- Idempotent. Safe to re-run on every Fly boot via entrypoint.sh §4.
--
-- Depends on the §10.10 base tables created by migrations 140 / 141 / 142
-- (separate agent W1-14). scripts/migrate.py applies lexicographically,
-- so those base tables should exist before this view is queried.

DROP VIEW IF EXISTS am_narrative_quality_kpi;

CREATE VIEW IF NOT EXISTS am_narrative_quality_kpi AS
WITH per_week AS (
    SELECT
        strftime('%Y-W%W', extracted_at) AS iso_week,
        narrative_table,
        narrative_id,
        SUM(CASE entity_kind WHEN 'money'   THEN 3
                             WHEN 'law'     THEN 3
                             WHEN 'url'     THEN 2
                             WHEN 'houjin'  THEN 2
                             WHEN 'program' THEN 2
                             ELSE 1 END * corpus_match) AS num_w,
        SUM(CASE entity_kind WHEN 'money'   THEN 3
                             WHEN 'law'     THEN 3
                             WHEN 'url'     THEN 2
                             WHEN 'houjin'  THEN 2
                             WHEN 'program' THEN 2
                             ELSE 1 END)                AS den_w
      FROM am_narrative_extracted_entities
     GROUP BY iso_week, narrative_table, narrative_id
),
match_rates AS (
    SELECT
        iso_week,
        CASE WHEN den_w > 0 THEN (num_w * 1.0) / den_w ELSE 1.0 END AS match_rate
      FROM per_week
),
ranked_match_rates AS (
    SELECT
        iso_week,
        match_rate,
        ROW_NUMBER() OVER (PARTITION BY iso_week ORDER BY match_rate) AS rn,
        COUNT(*) OVER (PARTITION BY iso_week) AS cnt
      FROM match_rates
),
median_match_rates AS (
    SELECT
        iso_week,
        AVG(match_rate) AS factcheck_match_rate_median
      FROM ranked_match_rates
     WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
     GROUP BY iso_week
),
quarantine_per_week AS (
    SELECT
        strftime('%Y-W%W', detected_at) AS iso_week,
        COUNT(*) AS quarantine_rows,
        SUM(CASE WHEN reason = 'low_match_rate' THEN 1 ELSE 0 END) AS low_match,
        SUM(CASE WHEN reason = 'corpus_drift'   THEN 1 ELSE 0 END) AS drift,
        SUM(CASE WHEN reason = 'customer_report' THEN 1 ELSE 0 END) AS customer,
        SUM(CASE WHEN reason = 'operator_reject' THEN 1 ELSE 0 END) AS operator
      FROM am_narrative_quarantine
     GROUP BY iso_week
),
report_sla AS (
    SELECT
        strftime('%Y-W%W', created_at) AS iso_week,
        COUNT(*) AS total_reports,
        SUM(CASE WHEN state = 'inbox' AND sla_due_at < datetime('now')
                 THEN 1 ELSE 0 END) AS sla_breach
      FROM am_narrative_customer_reports
     GROUP BY iso_week
),
rollback_per_week AS (
    SELECT
        strftime('%Y-W%W', resolved_at) AS iso_week,
        COUNT(*) AS rollback_rows
      FROM am_narrative_quarantine
     WHERE resolution = 'rolled_back'
     GROUP BY iso_week
),
all_weeks AS (
    SELECT iso_week FROM median_match_rates WHERE iso_week IS NOT NULL
    UNION
    SELECT iso_week FROM quarantine_per_week WHERE iso_week IS NOT NULL
    UNION
    SELECT iso_week FROM report_sla WHERE iso_week IS NOT NULL
    UNION
    SELECT iso_week FROM rollback_per_week WHERE iso_week IS NOT NULL
)
SELECT
    w.iso_week,
    mmr.factcheck_match_rate_median,
    COALESCE(qpw.quarantine_rows, 0) AS quarantine_rows_total,
    COALESCE(qpw.low_match, 0)       AS quarantine_low_match,
    COALESCE(qpw.drift, 0)           AS quarantine_corpus_drift,
    COALESCE(qpw.customer, 0)        AS quarantine_customer_report,
    COALESCE(qpw.operator, 0)        AS quarantine_operator_reject,
    COALESCE(rs.total_reports, 0)    AS customer_reports_total,
    COALESCE(rs.sla_breach, 0)       AS customer_reports_sla_breach,
    COALESCE(rb.rollback_rows, 0)    AS rollback_rows
  FROM all_weeks w
  LEFT JOIN median_match_rates mmr USING (iso_week)
  LEFT JOIN quarantine_per_week qpw USING (iso_week)
  LEFT JOIN report_sla rs           USING (iso_week)
  LEFT JOIN rollback_per_week rb    USING (iso_week)
 ORDER BY w.iso_week DESC;
