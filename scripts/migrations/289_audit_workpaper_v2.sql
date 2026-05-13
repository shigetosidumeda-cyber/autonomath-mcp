-- target_db: autonomath
-- migration: 289_audit_workpaper_v2
-- generated_at: 2026-05-13
-- idempotent: every CREATE uses IF NOT EXISTS; no destructive DML.
--
-- Storage substrate for scripts/etl/build_audit_workpaper_v2.py.
-- The live REST composer remains source-table backed; this cache supports
-- cohort scans and dashboards without changing auth or billing behavior.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_audit_workpaper (
    workpaper_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou             TEXT NOT NULL,
    fiscal_year               INTEGER NOT NULL,
    fy_start                  TEXT NOT NULL,
    fy_end                    TEXT NOT NULL,
    fy_adoption_count         INTEGER NOT NULL DEFAULT 0,
    fy_enforcement_count      INTEGER NOT NULL DEFAULT 0,
    fy_amendment_alert_count  INTEGER NOT NULL DEFAULT 0,
    jurisdiction_mismatch     INTEGER NOT NULL DEFAULT 0 CHECK (jurisdiction_mismatch IN (0, 1)),
    auditor_flag_count        INTEGER NOT NULL DEFAULT 0,
    snapshot_json             TEXT NOT NULL,
    snapshot_bytes            INTEGER NOT NULL DEFAULT 0,
    composed_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    composer_version          TEXT NOT NULL DEFAULT 'audit_workpaper_v2',
    UNIQUE (houjin_bangou, fiscal_year),
    CHECK (length(houjin_bangou) = 13),
    CHECK (fiscal_year BETWEEN 2000 AND 2100),
    CHECK (fy_start <= fy_end),
    CHECK (fy_adoption_count >= 0),
    CHECK (fy_enforcement_count >= 0),
    CHECK (fy_amendment_alert_count >= 0),
    CHECK (auditor_flag_count >= 0),
    CHECK (snapshot_bytes >= 0),
    CHECK (json_valid(snapshot_json))
);

CREATE INDEX IF NOT EXISTS idx_am_audit_workpaper_houjin
    ON am_audit_workpaper(houjin_bangou, fiscal_year DESC);

CREATE INDEX IF NOT EXISTS idx_am_audit_workpaper_fy_counts
    ON am_audit_workpaper(fiscal_year, fy_adoption_count DESC, fy_enforcement_count DESC);

CREATE INDEX IF NOT EXISTS idx_am_audit_workpaper_composed
    ON am_audit_workpaper(composed_at DESC);

CREATE TABLE IF NOT EXISTS am_audit_workpaper_run_log (
    run_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    houjin_scanned       INTEGER NOT NULL DEFAULT 0,
    workpapers_upserted  INTEGER NOT NULL DEFAULT 0,
    workpapers_skipped   INTEGER NOT NULL DEFAULT 0,
    errors_count         INTEGER NOT NULL DEFAULT 0,
    error_text           TEXT,
    CHECK (houjin_scanned >= 0),
    CHECK (workpapers_upserted >= 0),
    CHECK (workpapers_skipped >= 0),
    CHECK (errors_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_am_audit_workpaper_run_started
    ON am_audit_workpaper_run_log(started_at DESC);

-- Source-table support for scripts/etl/build_audit_workpaper_v2.py and
-- src/jpintel_mcp/api/audit_workpaper_v2.py. These mirror the exact lookup
-- predicates used by the live composer and cache builder.
CREATE INDEX IF NOT EXISTS idx_289_jpi_adoption_records_houjin_announced
    ON jpi_adoption_records(houjin_bangou, announced_at DESC);

CREATE INDEX IF NOT EXISTS idx_289_jpi_adoption_records_announced_houjin
    ON jpi_adoption_records(announced_at, houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_289_jpi_adoption_records_houjin_prefecture
    ON jpi_adoption_records(houjin_bangou, prefecture);

CREATE INDEX IF NOT EXISTS idx_289_am_enforcement_detail_houjin_issuance
    ON am_enforcement_detail(houjin_bangou, issuance_date DESC);

CREATE INDEX IF NOT EXISTS idx_289_jpi_invoice_registrants_houjin_registered
    ON jpi_invoice_registrants(houjin_bangou, registered_date DESC);

CREATE INDEX IF NOT EXISTS idx_289_am_amendment_diff_entity_detected
    ON am_amendment_diff(entity_id, detected_at DESC);

COMMIT;
