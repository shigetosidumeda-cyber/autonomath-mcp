-- target_db: jpintel
-- migration 167_programs_audit_quarantined (rollback)
--
-- SQLite < 3.35 cannot DROP COLUMN. The columns
-- `audit_quarantined`, `audit_quarantined_reason`, and
-- `audit_quarantined_at` are nullable / default-zero, so leaving them
-- in place on rollback is harmless. Search paths that AND in
-- `audit_quarantined = 0` continue to function (everything stays
-- visible because the default is 0 and the rollback would also reset
-- the repair flag set during populate).
--
-- This file is a placeholder so the rollback companion exists alongside
-- the forward migration (entrypoint.sh §4 excludes *_rollback.sql from
-- the autonomath self-heal loop, but the convention is enforced for
-- jpintel-target migrations too).

SELECT 1;
