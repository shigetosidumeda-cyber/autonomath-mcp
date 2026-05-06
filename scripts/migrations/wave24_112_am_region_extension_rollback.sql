-- target_db: autonomath
-- ROLLBACK companion for wave24_112_am_region_extension.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.
--
-- Manual review required. SQLite does not support
-- ALTER TABLE DROP COLUMN before 3.35; on 3.35+ the dropped columns
-- still leave behind storage until a VACUUM. Operators should
-- weigh whether to drop the columns or simply ignore them. The
-- density table is destructive — the cron can rebuild it but the
-- recomputation may take several minutes.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_arpd_jsic;
DROP INDEX IF EXISTS idx_arpd_region;
DROP TABLE IF EXISTS am_region_program_density;

-- Column drops require SQLite 3.35+. Comment out if running on
-- an older runtime. Production Fly is on 3.46+ as of 2026-04.
ALTER TABLE am_region DROP COLUMN land_area_km2;
ALTER TABLE am_region DROP COLUMN longitude;
ALTER TABLE am_region DROP COLUMN latitude;
ALTER TABLE am_region DROP COLUMN climate_zone;
ALTER TABLE am_region DROP COLUMN business_count_as_of;
ALTER TABLE am_region DROP COLUMN business_count;
ALTER TABLE am_region DROP COLUMN gdp_source_url;
ALTER TABLE am_region DROP COLUMN gdp_as_of;
ALTER TABLE am_region DROP COLUMN gdp_million_yen;

PRAGMA foreign_keys = ON;
