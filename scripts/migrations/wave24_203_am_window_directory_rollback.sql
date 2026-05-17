-- target_db: autonomath
-- rollback for: wave24_203_am_window_directory
-- generated_at: 2026-05-17

DROP VIEW IF EXISTS v_am_window_by_region;
DROP VIEW IF EXISTS v_am_window_by_kind;
DROP INDEX IF EXISTS ix_am_window_parent;
DROP INDEX IF EXISTS ix_am_window_postcode;
DROP INDEX IF EXISTS ix_am_window_region;
DROP INDEX IF EXISTS ix_am_window_kind;
DROP INDEX IF EXISTS ix_am_window_kind_region;
DROP TABLE IF EXISTS am_window_directory;
