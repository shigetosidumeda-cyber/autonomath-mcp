-- target_db: autonomath
-- migration: 270_audit_workpaper
-- generated_at: 2026-05-12
-- author: Wave 46 dim 19 D-final — am_audit_workpaper cached snapshot table
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Dim D (Wave 46 dim 19 audit) materializes the 5-source compose surface
-- produced by `src/jpintel_mcp/api/audit_workpaper_v2.py` (Wave 43.2.4)
-- into a per-(houjin_bangou, fiscal_year) row so:
--
--   * `GET /v1/audit/workpaper/snapshot?houjin=..&fy=..` returns in O(1)
--     vs the 5-fan-out live compose (jpi_houjin_master +
--     jpi_adoption_records + am_enforcement_detail + jpi_invoice_registrants
--     + am_amendment_diff).
--   * The weekly cron `scripts/etl/build_audit_workpaper_v2.py` walks
--     active 法人 × current+previous FY and upserts the snapshot, so a
--     read-only ¥3/req endpoint can ship the cached envelope without the
--     5-unit live recompute price (5-unit live compose remains via the
--     POST surface — this snapshot is purely a discoverability / cohort
--     prefetch layer).
--   * Auditor cohort dashboards (税理士・会計士 surfaces) can scan
--     ``am_audit_workpaper`` directly for risk-flag rollups without the
--     5-fan-out per-row cost.
--
-- Why a NEW table (not a column on jpi_houjin_master)
-- ---------------------------------------------------
-- jpi_houjin_master holds the canonical 法人 row keyed by houjin_bangou
-- only; the audit workpaper is keyed by (houjin_bangou, fiscal_year) and
-- carries large JSON payloads (fy_adoptions / fy_enforcement /
-- amendment_alerts / auditor_flags). A side-by-side cache table keeps
-- the master surface lean and lets the snapshot be rebuilt independently.
--
-- License posture
-- ---------------
-- Pure computation over already-ingested first-party data (公開情報の
-- 監査調書サブストレート). No new external fetches at migration time.
-- License inherited from the 5 source tables (jpi_houjin_master /
-- jpi_adoption_records / am_enforcement_detail / jpi_invoice_registrants
-- / am_amendment_diff), all gov_standard / gov_public.
--
-- ¥3/req billing posture
-- ----------------------
-- Read paths under `/v1/audit/workpaper/snapshot` are ¥3/req (税込ぐ¥3.30).
-- The 5-unit POST /v1/audit/workpaper live compose endpoint is unchanged.
-- NO LLM call inside the read or write path — pure SQLite + Python.
--
-- Sensitive surface
-- -----------------
-- Same fence text as the POST surface: 税理士法 §52 / 公認会計士法 §47条の2
-- / 弁護士法 §72 / 行政書士法 §1. ``_disclaimer`` envelope is required on
-- every read.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_audit_workpaper (
    workpaper_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou       TEXT NOT NULL,              -- 13-digit canonical
    fiscal_year         INTEGER NOT NULL            -- FY start year (e.g. 2025)
                        CHECK (fiscal_year >= 2000 AND fiscal_year <= 2100),
    fy_start            TEXT NOT NULL,              -- YYYY-04-01
    fy_end              TEXT NOT NULL,              -- (FY+1)-03-31
    -- counts (denormalized for cohort dashboard scan)
    fy_adoption_count       INTEGER NOT NULL DEFAULT 0 CHECK (fy_adoption_count >= 0),
    fy_enforcement_count    INTEGER NOT NULL DEFAULT 0 CHECK (fy_enforcement_count >= 0),
    fy_amendment_alert_count INTEGER NOT NULL DEFAULT 0 CHECK (fy_amendment_alert_count >= 0),
    jurisdiction_mismatch   INTEGER NOT NULL DEFAULT 0 CHECK (jurisdiction_mismatch IN (0, 1)),
    auditor_flag_count      INTEGER NOT NULL DEFAULT 0 CHECK (auditor_flag_count >= 0),
    -- full envelope (JSON)
    snapshot_json       TEXT NOT NULL DEFAULT '{}',
    snapshot_bytes      INTEGER NOT NULL DEFAULT 0 CHECK (snapshot_bytes >= 0),
    -- provenance
    composed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    composer_version    TEXT NOT NULL DEFAULT 'audit_workpaper_v2',
    UNIQUE (houjin_bangou, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_audit_workpaper_houjin
    ON am_audit_workpaper(houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_audit_workpaper_fy
    ON am_audit_workpaper(fiscal_year DESC, composed_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_workpaper_flags
    ON am_audit_workpaper(auditor_flag_count DESC, fy_enforcement_count DESC);

-- Helper view: rollup cohort scan for auditor dashboards (NO snapshot_json,
-- so cohort listings stay cheap and PII-light).
DROP VIEW IF EXISTS v_audit_workpaper_cohort;
CREATE VIEW v_audit_workpaper_cohort AS
SELECT
    workpaper_id,
    houjin_bangou,
    fiscal_year,
    fy_start, fy_end,
    fy_adoption_count,
    fy_enforcement_count,
    fy_amendment_alert_count,
    jurisdiction_mismatch,
    auditor_flag_count,
    snapshot_bytes,
    composed_at,
    composer_version,
    CASE
        WHEN auditor_flag_count >= 3 OR fy_enforcement_count >= 1 THEN 'high_risk'
        WHEN auditor_flag_count >= 1 OR jurisdiction_mismatch = 1 THEN 'medium_risk'
        ELSE 'low_risk'
    END AS risk_band
FROM am_audit_workpaper;

-- Run log: one row per `build_audit_workpaper_v2.py` ETL invocation.
CREATE TABLE IF NOT EXISTS am_audit_workpaper_run_log (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    houjin_scanned      INTEGER NOT NULL DEFAULT 0,
    workpapers_upserted INTEGER NOT NULL DEFAULT 0,
    workpapers_skipped  INTEGER NOT NULL DEFAULT 0,
    errors_count        INTEGER NOT NULL DEFAULT 0,
    error_text          TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_workpaper_run_log_started
    ON am_audit_workpaper_run_log(started_at DESC);

COMMIT;
