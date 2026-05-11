-- target_db: autonomath
-- migration: 265_cross_source_agreement
-- generated_at: 2026-05-12
-- author: Wave 43.2.9 — Dim I cross-source agreement score (fact_id → 0.0..1.0)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Dim I (Wave 43.2 catalog) materializes a per-fact agreement score that
-- captures HOW MANY DISTINCT first-party government sources confirm a given
-- (entity_id, field_name) fact, AND what fraction of those sources agree
-- on the actual value. This is the "cross-source agreement" surface paired
-- with the hourly cron `scripts/cron/cross_source_agreement_check.py`.
--
-- Existing substrate (migration 101 / 107)
-- ----------------------------------------
-- am_entity_facts.confirming_source_count  : how many sources confirm
--                                            (count, not ratio)
-- cross_source_baseline_state              : baseline-pass state
--
-- What this migration ADDS
-- ------------------------
-- am_fact_source_agreement : a per-fact agreement row carrying:
--   * agreement_ratio   REAL 0.0..1.0    (= sources_agree / sources_total)
--   * sources_total     INTEGER          (distinct sources that produced
--                                          ANY value for this fact)
--   * sources_agree     INTEGER          (sources whose value matches the
--                                          canonical / mode value)
--   * canonical_value   TEXT             (the mode / agreed value)
--   * source_breakdown  JSON             ({"egov": 1, "nta": 1, "meti": 0, ...})
--   * computed_at       TEXT             (ISO 8601)
--
-- Why a NEW table (not a column on am_entity_facts)
-- ------------------------------------------------
-- am_entity_facts is a 6.12M-row EAV table; adding 4-5 columns there bloats
-- every read and complicates the hot search path. A side-by-side aggregate
-- table is read-only, refreshed by cron, and joined ONLY when callers
-- explicitly request the agreement signal (¥3/req endpoint).
--
-- License posture
-- ---------------
-- Pure computation over already-ingested first-party data (e-Gov / NTA / METI
-- 公式 sources). No new external fetches at migration time. License inherited
-- from the underlying am_entity_facts rows.
--
-- ¥3/req billing posture
-- ----------------------
-- Read paths under `/v1/facts/{fact_id}/agreement` are ¥3/req (税込 ¥3.30).
-- NO LLM call inside the read or write path — pure SQLite + Python aggregation.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_fact_source_agreement (
    agreement_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id             INTEGER NOT NULL,                  -- pointer to am_entity_facts.id
    entity_id           TEXT NOT NULL,                     -- denormalized for read speed
    field_name          TEXT NOT NULL,                     -- denormalized for read speed
    agreement_ratio     REAL NOT NULL DEFAULT 0.0          -- 0.0..1.0
                        CHECK (agreement_ratio >= 0.0 AND agreement_ratio <= 1.0),
    sources_total       INTEGER NOT NULL DEFAULT 0         -- distinct sources observed
                        CHECK (sources_total >= 0),
    sources_agree       INTEGER NOT NULL DEFAULT 0         -- sources matching canonical
                        CHECK (sources_agree >= 0),
    canonical_value     TEXT,                              -- mode value (NULL if no consensus)
    source_breakdown    TEXT NOT NULL DEFAULT '{}',        -- JSON {source_kind: count}
    egov_value          TEXT,                              -- value reported by e-Gov (if any)
    nta_value           TEXT,                              -- value reported by NTA (if any)
    meti_value          TEXT,                              -- value reported by METI (if any)
    other_value         TEXT,                              -- value reported by other gov (if any)
    computed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    notes               TEXT,
    UNIQUE (fact_id),
    CONSTRAINT ck_agreement_ratio_bounds CHECK (
        sources_agree <= sources_total
    )
);

CREATE INDEX IF NOT EXISTS idx_fact_agreement_fact
    ON am_fact_source_agreement(fact_id);

CREATE INDEX IF NOT EXISTS idx_fact_agreement_entity_field
    ON am_fact_source_agreement(entity_id, field_name);

CREATE INDEX IF NOT EXISTS idx_fact_agreement_ratio
    ON am_fact_source_agreement(agreement_ratio DESC, sources_total DESC);

-- Helper view for the REST + MCP surface.
DROP VIEW IF EXISTS v_fact_source_agreement;
CREATE VIEW v_fact_source_agreement AS
SELECT
    fact_id, entity_id, field_name,
    agreement_ratio, sources_total, sources_agree,
    canonical_value, source_breakdown,
    egov_value, nta_value, meti_value, other_value,
    computed_at,
    CASE
        WHEN sources_total >= 3 AND agreement_ratio >= 0.66
            THEN 'high'
        WHEN sources_total >= 2 AND agreement_ratio >= 0.50
            THEN 'medium'
        WHEN sources_total >= 1
            THEN 'low'
        ELSE 'unknown'
    END AS confidence_band
FROM am_fact_source_agreement;

-- Run log: tracks each scripts/cron/cross_source_agreement_check.py pass.
CREATE TABLE IF NOT EXISTS am_fact_source_agreement_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    facts_scanned   INTEGER NOT NULL DEFAULT 0,
    facts_upserted  INTEGER NOT NULL DEFAULT 0,
    facts_skipped   INTEGER NOT NULL DEFAULT 0,
    errors_count    INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_agreement_run_log_started
    ON am_fact_source_agreement_run_log(started_at DESC);

COMMIT;
