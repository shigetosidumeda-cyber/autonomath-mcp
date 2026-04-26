-- migration 048: jpi_pc_program_health (program 健康度集計 pre-cache)
-- am_entity_annotation を集計して per-program な健康度スナップショットを保持
-- DELETE-then-INSERT で precompute_refresh.py から定期更新

CREATE TABLE IF NOT EXISTS jpi_pc_program_health (
    program_id            TEXT PRIMARY KEY,                       -- jpi_programs.unified_id (TEXT)
    quality_score         REAL,
    warning_count_recent  INTEGER NOT NULL DEFAULT 0,
    critical_count_recent INTEGER NOT NULL DEFAULT 0,
    last_validated_at     TEXT,
    refreshed_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jpi_pc_health_score
    ON jpi_pc_program_health(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_jpi_pc_health_warn
    ON jpi_pc_program_health(warning_count_recent DESC);
CREATE INDEX IF NOT EXISTS idx_jpi_pc_health_refresh
    ON jpi_pc_program_health(refreshed_at);
