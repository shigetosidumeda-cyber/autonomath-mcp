-- target_db: jpintel
-- rollback: wave24_190_restore_drill_log
-- WARNING: drops restore_drill_log audit history. Only run after exporting
-- to R2 (analytics/restore_rto_quarter.jsonl is a derived view, NOT a
-- substitute backup — it does not retain per-row sha256 / backup_key).

DROP INDEX IF EXISTS ix_restore_drill_red;
DROP INDEX IF EXISTS ix_restore_drill_kind_date;
DROP TABLE IF EXISTS restore_drill_log;
