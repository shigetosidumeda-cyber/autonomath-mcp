-- target_db: autonomath
-- ROLLBACK companion for wave24_164_gbiz_v2_mirror_tables.sql
-- entrypoint.sh §4 EXCLUDES files matching *_rollback.sql, so this is operator-only.
-- DROP order: reverse FK dependency (children first, parent last).
PRAGMA foreign_keys = OFF;

-- 8. gbiz_procurement
DROP INDEX IF EXISTS ix_gbiz_proc_agency_date;
DROP INDEX IF EXISTS ix_gbiz_proc_houjin_date;
DROP TABLE IF EXISTS gbiz_procurement;

-- 7. gbiz_commendation
DROP INDEX IF EXISTS ix_gbiz_commend_houjin_date;
DROP TABLE IF EXISTS gbiz_commendation;

-- 6. gbiz_certification
DROP INDEX IF EXISTS ix_gbiz_cert_authority;
DROP INDEX IF EXISTS ix_gbiz_cert_houjin;
DROP TABLE IF EXISTS gbiz_certification;

-- 5. gbiz_subsidy_award
DROP INDEX IF EXISTS ix_gbiz_subsidy_program_fy;
DROP INDEX IF EXISTS ix_gbiz_subsidy_houjin_fy;
DROP TABLE IF EXISTS gbiz_subsidy_award;

-- 4. gbiz_update_log
DROP INDEX IF EXISTS ix_gbiz_update_log_family_from;
DROP TABLE IF EXISTS gbiz_update_log;

-- 3. gbiz_workplace
DROP INDEX IF EXISTS ix_gbiz_workplace_houjin;
DROP TABLE IF EXISTS gbiz_workplace;

-- 2. gbiz_corporation_branch (FK depends on gbiz_corp_activity — drop before parent)
DROP INDEX IF EXISTS ix_gbiz_corp_branch_houjin;
DROP TABLE IF EXISTS gbiz_corporation_branch;

-- 1. gbiz_corp_activity (parent — drop last)
DROP INDEX IF EXISTS ix_gbiz_corp_activity_postal;
DROP INDEX IF EXISTS ix_gbiz_corp_activity_kind;
DROP INDEX IF EXISTS ix_gbiz_corp_activity_status;
DROP TABLE IF EXISTS gbiz_corp_activity;

PRAGMA foreign_keys = ON;
