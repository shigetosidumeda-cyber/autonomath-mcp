-- target_db: jpintel
-- DEEP-42 evolution dashboard snapshot rollback (jpcite v0.3.4).
-- Companion of wave24_188_evolution_dashboard_snapshot.sql.
-- The entrypoint.sh §4 self-heal loop excludes *_rollback.sql so this file
-- is only applied manually via `sqlite3 data/jpintel.db < <path>` when an
-- operator deliberately reverts the migration (e.g. schema redesign).

BEGIN;

DROP VIEW  IF EXISTS v_evolution_axis_status;
DROP VIEW  IF EXISTS v_evolution_dashboard_latest;
DROP INDEX IF EXISTS idx_eds_status;
DROP INDEX IF EXISTS idx_eds_date;
DROP INDEX IF EXISTS idx_eds_axis_date;
DROP TABLE IF EXISTS evolution_dashboard_snapshot;

COMMIT;
