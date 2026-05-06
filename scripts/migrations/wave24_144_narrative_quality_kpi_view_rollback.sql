-- target_db: autonomath
-- ROLLBACK companion for wave24_144_narrative_quality_kpi_view.sql
-- Manual review required only to confirm no dashboard depends on the view.

DROP VIEW IF EXISTS am_narrative_quality_kpi;
