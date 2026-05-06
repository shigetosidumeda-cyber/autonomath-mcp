-- target_db: autonomath
-- rollback for wave24_172_cross_source_signal_layer
--
-- DROP VIEWS first, then the table + autoincrement counter row, then the
-- unique dedup index (table drop already removes it but explicit DROP is
-- defensive against partial state).
--
-- WARNING: dropping this table erases the normalized event spine. The
-- companion regenerator cron (scripts/cron/regenerate_cross_source_signal.py)
-- can rebuild from the source-family tables (jpi_adoption_records,
-- enforcement_cases, am_enforcement_detail, gbiz_*, am_amendment_diff, etc.)
-- in a single weekly run. Rebuild time on production data: ~30-45 min for
-- ~750k row scan. signal_id values are NOT preserved across rollback +
-- recreate (AUTOINCREMENT restarts).

DROP VIEW IF EXISTS v_signal_monthly_digest;
DROP VIEW IF EXISTS v_signal_risk_feed;
DROP VIEW IF EXISTS v_signal_per_houjin_recent;
DROP TABLE IF EXISTS cross_source_signal_layer;

-- AUTOINCREMENT counter cleanup (SQLite-internal table). Defensive only.
DELETE FROM sqlite_sequence WHERE name='cross_source_signal_layer';
