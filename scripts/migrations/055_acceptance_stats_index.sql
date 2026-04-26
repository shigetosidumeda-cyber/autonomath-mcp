-- target_db: autonomath
-- 055_acceptance_stats_index.sql -- Speed up search_acceptance_stats_am.
-- audit: af97f374f06b1aa89 (2026-04-25)
--
-- search_acceptance_stats_am hot path narrows to source_topic IN
-- ('01_meti_acceptance_stats','02_maff_acceptance_stats','05_adoption_additional')
-- (~70k rows) via existing ix_am_entities_topic_kind, then re-filters on
-- json_extract(raw_json,'$.fiscal_year') / substr(announced_date,1,4) for
-- every row. With ~70k rows and JSON evaluation per row this lands at
-- ~215ms median / 484ms max (P1 perf concern from benchmark af97f374f06b1aa89).
--
-- Two partial expression indexes scoped to the relevant record_kinds turn the
-- per-row JSON re-evaluation into an indexed lookup. Partial scope keeps
-- index size minimal (only ~70k rows, not all 503k entities).
--
-- Naming: ix_am_<table>_<cols> (perf prefix 'ix_' per 052 convention).
-- Both CREATE INDEX statements are IF NOT EXISTS, so safe to re-run.

BEGIN IMMEDIATE;

-- 1. Expression index on fiscal_year for adoption/statistic rows.
--    Collapses 70k-row JSON re-evaluation to ~constant-time index probe.
CREATE INDEX IF NOT EXISTS ix_am_entities_acceptance_fiscal_year
    ON am_entities(CAST(json_extract(raw_json, '$.fiscal_year') AS INTEGER))
 WHERE record_kind IN ('adoption','statistic')
   AND json_extract(raw_json, '$.fiscal_year') IS NOT NULL;

-- 2. Expression index on announced_date YYYY prefix (year filter falls back
--    to announced_date when fiscal_year is NULL).
CREATE INDEX IF NOT EXISTS ix_am_entities_acceptance_announced_year
    ON am_entities(substr(json_extract(raw_json, '$.announced_date'), 1, 4))
 WHERE record_kind IN ('adoption','statistic')
   AND json_extract(raw_json, '$.announced_date') IS NOT NULL;

COMMIT;

-- After-apply expectations on autonomath.db (503,930 entities; 69,738 rows in
-- record_kind IN ('adoption','statistic') AND source_topic IN (...stats...)):
--   median search_acceptance_stats_am(year=2024) drops <100 ms (target).
--   ANALYZE recommended after apply so the planner picks the new indexes:
--     sqlite3 autonomath.db "ANALYZE am_entities;"
