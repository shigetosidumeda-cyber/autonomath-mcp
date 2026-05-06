-- target_db: autonomath
-- migration: wave24_170_source_catalog
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-03 (source_catalog / freshness / cross_source_signal)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Normalize the 104 rows in `02_A_SOURCE_PROFILE.jsonl` into a single
-- machine-readable spine that downstream artifacts (company folder, DD pack,
-- monthly digest, application strategy, etc.) can join against. This is the
-- "source license / robots / acquisition method" registry — NOT the freshness
-- ledger (171) and NOT the event-normalized signal layer (172). Those are
-- separate tables with FK-like joins back to source_id.
--
-- Field semantics
-- ---------------
-- source_id           PK, snake_case, stable (matches 02_A_SOURCE_PROFILE row)
-- source_family       12 canonical families: corporate_identity, public_revenue,
--                     risk_enforcement, risk_enforcement_local, industry_specific,
--                     rd_signal, loan_program, corporate_identity_proprietary,
--                     official_publication, judicial_precedent, public_statistic,
--                     legal_text. CHECK constraint enforces enum.
-- official_owner      Free-text, but kept short ("国税庁", "金融庁 EDINET").
-- source_url          Top-level entry URL of the source.
-- source_type         bulk_zip / rest_api / html / pdf / search_ui / etc.
-- data_objects        JSON array (TEXT). e.g. ["corporate_identity","name",...].
-- acquisition_method  Free-text; preserves cron + parser + auth notes.
-- api_key_required    BOOL (0/1). Used by `07_A_API_KEY_APPLICATION_LEDGER`
--                     to surface "needs operator manual action".
-- robots_policy       Free-text quoting robots.txt + ToS clauses verbatim.
-- license_or_terms    Free-text; quote primary terms verbatim. Used by the
--                     `am_source.license` short-tag column for redistribution
--                     decisions.
-- commercial_use      "allowed" / "conditional" / "denied". CHECK enforced.
-- redistribution_risk "low" / "medium" / "high". Folded buckets — original
--                     JSONL has compound strings ("low — PDL v1.0 explicit"),
--                     ETL must normalize to one of three.
-- update_frequency    "daily" / "weekly" / "monthly" / "quarterly" / "annual" /
--                     "event" / "irregular" / "realtime". Folded enum (CHECK).
-- attribution_text    Verbatim attribution phrase for artifact footer.
-- notes               Free-text; rolls up known_gaps_if_missing + acceptance.
--
-- Indexes
-- -------
-- (source_family)         — pillar / cohort discovery
-- (license_or_terms)      — license-driven redistribution gating
-- (redistribution_risk)   — fast filter when surfacing to paid customers
--
-- Backfill
-- --------
-- Companion ETL `scripts/etl/backfill_source_catalog.py` reads
-- `tools/offline/_inbox/value_growth_dual/A_source_foundation/02_A_SOURCE_PROFILE.jsonl`
-- and runs INSERT OR REPLACE per row. ETL is idempotent — re-running it just
-- refreshes rows whose `notes` / `acquisition_method` / `license_or_terms`
-- evolved. Test `tests/test_source_catalog_backfill.py` asserts that all 104
-- source_ids land.

CREATE TABLE IF NOT EXISTS source_catalog (
    source_id            TEXT NOT NULL PRIMARY KEY,
    source_family        TEXT NOT NULL CHECK (source_family IN (
        'corporate_identity',
        'corporate_identity_proprietary',
        'public_revenue',
        'risk_enforcement',
        'risk_enforcement_local',
        'industry_specific',
        'rd_signal',
        'loan_program',
        'official_publication',
        'judicial_precedent',
        'public_statistic',
        'legal_text'
    )),
    official_owner       TEXT NOT NULL,
    source_url           TEXT NOT NULL,
    source_type          TEXT NOT NULL,
    data_objects         TEXT NOT NULL DEFAULT '[]',  -- JSON array
    acquisition_method   TEXT NOT NULL DEFAULT '',
    api_key_required     INTEGER NOT NULL DEFAULT 0 CHECK (api_key_required IN (0,1)),
    robots_policy        TEXT NOT NULL DEFAULT '',
    license_or_terms     TEXT NOT NULL DEFAULT '',
    commercial_use       TEXT NOT NULL DEFAULT 'unknown' CHECK (commercial_use IN (
        'allowed', 'conditional', 'denied', 'unknown'
    )),
    redistribution_risk  TEXT NOT NULL DEFAULT 'medium' CHECK (redistribution_risk IN (
        'low', 'medium', 'high', 'unknown'
    )),
    update_frequency     TEXT NOT NULL DEFAULT 'irregular' CHECK (update_frequency IN (
        'realtime', 'daily', 'weekly', 'monthly', 'quarterly',
        'annual', 'event', 'irregular'
    )),
    attribution_text     TEXT NOT NULL DEFAULT '',
    notes                TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_source_catalog_family
    ON source_catalog (source_family);
CREATE INDEX IF NOT EXISTS idx_source_catalog_license
    ON source_catalog (license_or_terms);
CREATE INDEX IF NOT EXISTS idx_source_catalog_risk
    ON source_catalog (redistribution_risk);
CREATE INDEX IF NOT EXISTS idx_source_catalog_owner
    ON source_catalog (official_owner);
CREATE INDEX IF NOT EXISTS idx_source_catalog_freq
    ON source_catalog (update_frequency);

-- View: paid-surface eligible sources (low risk + commercial allowed).
-- Used by trust_center landing + license_review_queue.csv generator.
CREATE VIEW IF NOT EXISTS v_source_catalog_paid_safe AS
SELECT source_id, source_family, official_owner, source_url, license_or_terms,
       attribution_text, update_frequency
  FROM source_catalog
 WHERE redistribution_risk IN ('low')
   AND commercial_use IN ('allowed', 'conditional')
 ORDER BY source_family, source_id;

-- View: cohort × family rollup for prioritization dashboard.
CREATE VIEW IF NOT EXISTS v_source_catalog_family_rollup AS
SELECT source_family,
       COUNT(*)                                                 AS source_count,
       SUM(CASE WHEN api_key_required=1 THEN 1 ELSE 0 END)      AS needs_api_key,
       SUM(CASE WHEN redistribution_risk='low' THEN 1 ELSE 0 END) AS low_risk_count,
       SUM(CASE WHEN redistribution_risk='high' THEN 1 ELSE 0 END) AS high_risk_count
  FROM source_catalog
 GROUP BY source_family;
