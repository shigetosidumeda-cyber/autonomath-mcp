-- target_db: jpintel
-- rollback for wave24_166_credit_pack_reservation
--
-- DROP TABLE removes the table + its indexes in one step. Safe to run on a DB
-- that never had the migration applied (DROP IF EXISTS is a no-op).
--
-- WARNING: dropping this table erases the idempotency record. If any in-flight
-- credit-pack grant has only reached `status='reserved'` (no Stripe balance
-- applied yet), the operator MUST manually reconcile against Stripe before
-- re-applying the migration — otherwise the next webhook retry will re-grant
-- against a fresh empty reservation table and double the customer balance.

DROP INDEX IF EXISTS idx_credit_pack_reservation_status_reserved_at;
DROP INDEX IF EXISTS idx_credit_pack_reservation_customer_status;
DROP TABLE IF EXISTS credit_pack_reservation;
