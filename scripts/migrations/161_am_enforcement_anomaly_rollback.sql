-- target_db: autonomath
-- migration 161 ROLLBACK — am_enforcement_anomaly
--
-- Drops the anomaly table. Indexes drop transitively.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_aea_z;
DROP INDEX IF EXISTS idx_aea_anomaly;
DROP INDEX IF EXISTS idx_aea_jsic;
DROP INDEX IF EXISTS idx_aea_pref;
DROP TABLE IF EXISTS am_enforcement_anomaly;
