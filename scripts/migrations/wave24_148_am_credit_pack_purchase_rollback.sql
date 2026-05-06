-- target_db: autonomath
-- Rollback companion for wave24_148_am_credit_pack_purchase.
-- Manual-review only. The entrypoint loop excludes *_rollback.sql files
-- from boot-time idempotent migrations.

DROP INDEX IF EXISTS ix_credit_pack_customer;
DROP TABLE IF EXISTS am_credit_pack_purchase;
