-- target_db: autonomath
-- migration 069_uncertainty_view (O8 — per-fact Bayesian uncertainty)
--
-- Adds the `am_uncertainty_view` SQL view that surfaces, for every
-- am_entity_facts row, the inputs needed to compute a per-fact
-- Beta(α, β) posterior in pure Python (see analytics.uncertainty +
-- api.uncertainty).
--
-- The view stays *read-only*: no new columns, no triggers, no
-- backfill. Schema impact = zero. Rolling back O8 = drop the view.
--
-- Inputs surfaced (all derivable from existing columns):
--   * fact_id              — am_entity_facts.id
--   * entity_id            — am_entity_facts.entity_id
--   * field_name           — am_entity_facts.field_name
--   * field_kind           — am_entity_facts.field_kind (enum 8 buckets)
--   * source_id            — am_entity_facts.source_id (NULL = unknown)
--   * license              — am_source.license (6 enum + NULL)
--   * first_seen           — am_source.first_seen (datetime)
--   * days_since_fetch     — INT, julianday('now') - julianday(first_seen)
--   * n_sources            — COUNT DISTINCT source_id per (entity_id, field_name)
--   * n_distinct_values    — COUNT DISTINCT value-string per same key
--   * agreement            — 1 iff n_sources >= 2 AND n_distinct_values = 1
--
-- Application code reads this view per-fact and runs Beta math through
-- the existing analytics.bayesian.beta_posterior / confidence_interval_95
-- helpers (no new math, no new dependency).
--
-- DOWN: DROP VIEW IF EXISTS am_uncertainty_view;

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS am_uncertainty_view;

CREATE VIEW am_uncertainty_view AS
WITH per_pair AS (
    -- Cross-source agreement signal: same (entity_id, field_name) with
    -- multiple sources whose value strings agree => bonus α.
    SELECT
        entity_id,
        field_name,
        COUNT(DISTINCT source_id) AS n_sources,
        COUNT(DISTINCT
              COALESCE(field_value_text,
                       CAST(field_value_numeric AS TEXT))
        ) AS n_distinct_values
    FROM am_entity_facts
    WHERE source_id IS NOT NULL
    GROUP BY entity_id, field_name
)
SELECT
    f.id                                                AS fact_id,
    f.entity_id                                         AS entity_id,
    f.field_name                                        AS field_name,
    f.field_kind                                        AS field_kind,
    f.source_id                                         AS source_id,
    s.license                                           AS license,
    s.first_seen                                        AS first_seen,
    CAST(julianday('now') - julianday(s.first_seen)
         AS INTEGER)                                    AS days_since_fetch,
    COALESCE(p.n_sources, 0)                            AS n_sources,
    COALESCE(p.n_distinct_values, 0)                    AS n_distinct_values,
    CASE
        WHEN COALESCE(p.n_sources, 0) >= 2
             AND COALESCE(p.n_distinct_values, 0) = 1 THEN 1
        ELSE 0
    END                                                 AS agreement
FROM am_entity_facts f
LEFT JOIN am_source  s ON s.id = f.source_id
LEFT JOIN per_pair   p ON p.entity_id  = f.entity_id
                       AND p.field_name = f.field_name;
