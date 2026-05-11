-- target_db: autonomath
-- migration: 263_realtime_signal_subscribers_rollback
-- generated_at: 2026-05-12

BEGIN;

DROP VIEW IF EXISTS v_realtime_subscribers_active;

DROP INDEX IF EXISTS idx_rts_dispatch_failed;
DROP INDEX IF EXISTS idx_rts_dispatch_kind_created;
DROP INDEX IF EXISTS idx_rts_dispatch_sub_created;
DROP TABLE IF EXISTS am_realtime_dispatch_history;

DROP INDEX IF EXISTS idx_rts_last_delivery;
DROP INDEX IF EXISTS idx_rts_kind_active;
DROP INDEX IF EXISTS idx_rts_key_active;
DROP TABLE IF EXISTS am_realtime_subscribers;

COMMIT;
