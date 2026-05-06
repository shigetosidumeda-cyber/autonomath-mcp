-- target_db: autonomath
-- migration: wave24_172_cross_source_signal_layer
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-03 (source_catalog / freshness / cross_source_signal)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Project the 7 cross-domain event types onto a single normalized event row
-- so downstream artifacts (monthly digest, DD pack timeline, application
-- strategy retrospective) can pull "all signals for houjin_bangou X between
-- date A and B" with one query, instead of UNION-ing 6+ source-family tables.
--
-- The 7 normalized signal kinds (CHECK enum):
--   1. saiyaku    — 採択 (subsidy/grant award)
--   2. ninetei    — 認定 (formal certification by ministry/agency)
--   3. hyousho    — 表彰 (commendation, award by ministry/agency)
--   4. shobun     — 処分 (enforcement / sanction by regulator)
--   5. chotatsu   — 調達 (public procurement award)
--   6. kyoninka   — 許認可 (license / permit grant or renewal)
--   7. kaisei     — 改正 (law / ordinance / rule amendment)
--
-- The signal layer is *append-only by design*. Re-runs of the regenerator
-- cron de-dupe by content_hash + source_id, so the same event from two
-- redundant sources (gBizINFO + p-portal both publishing the same 採択)
-- collapses into ONE signal row, with the canonical source_url chosen by
-- a fixed precedence (primary ministry > aggregator).
--
-- Field semantics
-- ---------------
-- signal_id       PK AUTOINCREMENT — internal stable id, not user-facing.
-- signal_kind     One of 7 enum values above.
-- event_date      DATE (yyyy-mm-dd). The actual event date as published by
--                 the source (e.g. 採択公表日, not jpcite ingest date).
-- entity_id       Optional FK-like reference to am_entities.entity_id. NULL
--                 if the event was published with no resolvable corporate
--                 entity (e.g. 法令改正).
-- houjin_bangou   13-digit corporate number. NULL allowed (法令 events,
--                 個人事業主 sources without houjin_bangou). When present,
--                 must match houjin_master.houjin_bangou.
-- summary_short   <= 120 chars JP. Used by digest list view.
-- summary_long    Full description, no length cap.
-- severity        info / opportunity / risk / compliance. CHECK enforced.
--   - info        : fact-only ("X社が採択された")
--   - opportunity : actionable upside ("対象なら今期申請可")
--   - risk        : negative for the entity ("行政処分受領")
--   - compliance  : tax/regulatory deadline ("法改正により施行日")
-- source_id       FK-like reference to source_catalog.source_id.
-- source_url      Direct deep-link to the event page on the official source.
-- content_hash    SHA-256 of canonicalized payload. Used for dedup.
-- license         Short license tag matching am_source.license vocabulary
--                 ("pdl_v1.0", "cc_by_4.0", "gov_standard", "proprietary").
-- created_at      ISO 8601 UTC. jpcite ingest time.
--
-- Backfill
-- --------
-- Companion ETL `scripts/cron/regenerate_cross_source_signal.py` walks:
--   - jpi_adoption_records / gbiz_subsidy_award      → signal_kind='saiyaku'
--   - jpi_certifications / gbiz_certification        → signal_kind='ninetei'
--   - gbiz_commendation                              → signal_kind='hyousho'
--   - enforcement_cases / am_enforcement_detail      → signal_kind='shobun'
--   - bids / gbiz_procurement                        → signal_kind='chotatsu'
--   - permit/license tables (M00 follow-up wave)     → signal_kind='kyoninka'
--   - am_amendment_diff / law_articles diff          → signal_kind='kaisei'
-- and INSERTs with INSERT OR IGNORE keyed on (signal_kind, event_date,
-- houjin_bangou, content_hash). Re-runs are safe.
--
-- Indexes
-- -------
-- (signal_kind, event_date DESC)            — feed-style "latest 採択" query
-- (houjin_bangou, event_date DESC)          — per-company timeline
-- (severity, event_date DESC)               — risk feed for DD pack
-- (entity_id, event_date DESC)              — entity_resolution_bridge join
-- (source_id, created_at DESC)              — per-source debug walks
-- UNIQUE (signal_kind, content_hash, source_id)  — dedup guard

CREATE TABLE IF NOT EXISTS cross_source_signal_layer (
    signal_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_kind    TEXT NOT NULL CHECK (signal_kind IN (
        'saiyaku', 'ninetei', 'hyousho', 'shobun',
        'chotatsu', 'kyoninka', 'kaisei'
    )),
    event_date     TEXT NOT NULL,            -- yyyy-mm-dd
    entity_id      TEXT,                     -- am_entities.entity_id (nullable)
    houjin_bangou  TEXT,                     -- 13-digit (nullable)
    summary_short  TEXT NOT NULL DEFAULT '',
    summary_long   TEXT NOT NULL DEFAULT '',
    severity       TEXT NOT NULL DEFAULT 'info' CHECK (severity IN (
        'info', 'opportunity', 'risk', 'compliance'
    )),
    source_id      TEXT NOT NULL,
    source_url     TEXT NOT NULL DEFAULT '',
    content_hash   TEXT NOT NULL,
    license        TEXT NOT NULL DEFAULT 'unknown',
    extras_json    TEXT NOT NULL DEFAULT '{}',  -- per-kind extra fields
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_signal_kind_date
    ON cross_source_signal_layer (signal_kind, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_houjin_date
    ON cross_source_signal_layer (houjin_bangou, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_severity_date
    ON cross_source_signal_layer (severity, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_entity_date
    ON cross_source_signal_layer (entity_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_source_created
    ON cross_source_signal_layer (source_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_dedup
    ON cross_source_signal_layer (signal_kind, content_hash, source_id);

-- View: per-houjin recent signal stream (DD pack hot path).
CREATE VIEW IF NOT EXISTS v_signal_per_houjin_recent AS
SELECT signal_id, signal_kind, event_date, houjin_bangou,
       summary_short, severity, source_id, source_url, license
  FROM cross_source_signal_layer
 WHERE houjin_bangou IS NOT NULL
   AND event_date >= date('now', '-3 years')
 ORDER BY houjin_bangou, event_date DESC;

-- View: severity feed (DD pack risk timeline).
CREATE VIEW IF NOT EXISTS v_signal_risk_feed AS
SELECT signal_id, signal_kind, event_date, houjin_bangou,
       summary_short, summary_long, severity, source_id, source_url, license
  FROM cross_source_signal_layer
 WHERE severity IN ('risk', 'compliance')
   AND event_date >= date('now', '-1 year')
 ORDER BY event_date DESC;

-- View: monthly digest substrate. Used by send_daily_kpi_digest.py +
-- recurring_quarterly to fan out.
CREATE VIEW IF NOT EXISTS v_signal_monthly_digest AS
SELECT signal_kind,
       substr(event_date, 1, 7) AS month_yyyymm,
       COUNT(*) AS signal_count,
       SUM(CASE WHEN severity='risk' THEN 1 ELSE 0 END)        AS risk_count,
       SUM(CASE WHEN severity='compliance' THEN 1 ELSE 0 END)  AS compliance_count,
       SUM(CASE WHEN severity='opportunity' THEN 1 ELSE 0 END) AS opportunity_count
  FROM cross_source_signal_layer
 WHERE event_date >= date('now', '-13 months')
 GROUP BY signal_kind, month_yyyymm
 ORDER BY month_yyyymm DESC, signal_kind;
