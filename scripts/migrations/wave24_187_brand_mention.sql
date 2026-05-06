-- target_db: autonomath
-- migration: wave24_187_brand_mention
-- generated_at: 2026-05-07
-- author: DEEP-41 brand mention dashboard cron (IA-12 横断 KPI)
-- idempotent: every CREATE uses IF NOT EXISTS; first-line target_db hint
--             routes this file to autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_41_brand_mention_dashboard.md
--
-- DEEP-41 stitches IA-12's 10 brand-signal sources into ONE weekly cron +
-- ONE dashboard JSON + ONE transparency page so that the root KPI
-- "self mentions < other mentions" can be computed objectively. NO LLM
-- calls, NO paid intel SaaS (Crayon / Klue / Brandwatch named-NG), public
-- API + organic only. The 10 sources are GitHub / PyPI / npm / Zenn /
-- Qiita / X (public search HTML) / Hacker News / Lobste.rs / 業界誌
-- (DEEP-40 industry_journal_mention join) / 業界団体 ICT (semi-annual).
--
-- Field semantics
-- ---------------
-- id            INTEGER PK AUTOINCREMENT
-- source        CHECK enum (10 sources, see DEEP-41 §1)
-- mention_url   first-party URL of the mention. UNIQUE per (source, url).
-- author        handle / username / publisher (NULL for industry_assoc PDFs)
-- mention_date  ISO 8601 date (YYYY-MM-DD); when the mention was published
-- mention_kind  CHECK ('self', 'other'); auto-classified via
--               data/brand_self_accounts.json allowlist (author match).
-- snippet       short text snippet around 'jpcite' / 'autonomath' regex hit
-- retrieved_at  ISO 8601 UTC of cron pull
--
-- Indexes:
--   * UNIQUE (source, mention_url) — dedup hot path for cron INSERT OR IGNORE
--   * (source, mention_date DESC)  — per-source recency rollup
--   * (mention_kind, mention_date DESC) — root KPI "self vs other" rollup

PRAGMA foreign_keys = ON;

-- ============================================================================
-- brand_mention -- one row per (source, mention_url) tuple
-- ============================================================================

CREATE TABLE IF NOT EXISTS brand_mention (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL CHECK (source IN (
        'github',
        'pypi',
        'npm',
        'zenn',
        'qiita',
        'x',
        'hn',
        'lobsters',
        'industry_journal',
        'industry_assoc'
    )),
    mention_url   TEXT NOT NULL,
    author        TEXT,
    mention_date  TEXT NOT NULL,
    mention_kind  TEXT NOT NULL CHECK (mention_kind IN ('self', 'other')),
    snippet       TEXT,
    retrieved_at  TEXT NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (source, mention_url)
);

CREATE INDEX IF NOT EXISTS idx_brand_mention_source_date
    ON brand_mention (source, mention_date DESC);

CREATE INDEX IF NOT EXISTS idx_brand_mention_kind_date
    ON brand_mention (mention_kind, mention_date DESC);

-- ============================================================================
-- View: source rollup (counts by source)
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_brand_mention_source_rollup AS
SELECT source,
       COUNT(*) AS mention_count,
       SUM(CASE WHEN mention_kind = 'self'  THEN 1 ELSE 0 END) AS self_count,
       SUM(CASE WHEN mention_kind = 'other' THEN 1 ELSE 0 END) AS other_count,
       MAX(mention_date) AS latest_mention_date
  FROM brand_mention
 GROUP BY source;

-- View: monthly trend (self vs other by month)
CREATE VIEW IF NOT EXISTS v_brand_mention_monthly_trend AS
SELECT substr(mention_date, 1, 7) AS month,
       SUM(CASE WHEN mention_kind = 'self'  THEN 1 ELSE 0 END) AS self_count,
       SUM(CASE WHEN mention_kind = 'other' THEN 1 ELSE 0 END) AS other_count
  FROM brand_mention
 GROUP BY substr(mention_date, 1, 7)
 ORDER BY month;

-- View: root KPI gate (self < other?)
CREATE VIEW IF NOT EXISTS v_brand_mention_root_kpi AS
SELECT (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'self')  AS self_count,
       (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'other') AS other_count,
       CASE
         WHEN (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'self') = 0
         THEN NULL
         ELSE (SELECT CAST(COUNT(*) AS REAL) FROM brand_mention WHERE mention_kind = 'other')
              / (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'self')
       END AS ratio_other_per_self,
       CASE
         WHEN (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'other')
            > (SELECT COUNT(*) FROM brand_mention WHERE mention_kind = 'self')
         THEN 1
         ELSE 0
       END AS organic_self_walking;

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here -- that is the runner's job.
