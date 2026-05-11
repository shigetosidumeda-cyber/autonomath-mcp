-- target_db: autonomath
-- ROLLBACK for migration 214_invoice_houjin_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_invoice_houjin_refs_created_at;
DROP INDEX IF EXISTS idx_invoice_houjin_refs_registered;
DROP INDEX IF EXISTS idx_invoice_houjin_refs_houjin;
DROP TABLE IF EXISTS invoice_houjin_refs;
