-- 042_real_estate_schema.sql
-- Real Estate V5 cohort foundation: real_estate_programs + zoning_overlays.
--
-- Business context (analysis_wave18 P6-F / dd_v8_06):
--   Real Estate V5 expands the AutonoMath cohort beyond agriculture / SMB /
--   healthcare into 不動産 開発 (デベロッパー) / 賃貸管理 (PM 業者) /
--   不動産 M&A (仲介業者) / 建築設計事務所 / 不動産 SaaS 開発者.
--   T+200d (≈2026-11-11) launch on a 4-week timeline; this migration is W1
--   schema prep. W2 ingest 建築基準法 / 都市計画法 / 不動産登記法 / 借地借家法
--   / 建物区分所有法 (~500 articles via e-Gov). W3 ingest 国交省 / 都道府県 /
--   市町村 不動産関連 補助金・助成金 (~500 programs). W4 wires 5 new tools
--   (search_real_estate_programs / get_zoning_overlay /
--   search_real_estate_compliance / dd_property_am / cross_check_zoning).
--
-- Why TWO tables, not a cross-domain extension of `programs`:
--   * `real_estate_programs` is a real-estate-specialised *program* row that
--     mixes 補助金 / 税制優遇 / 融資 / 認定 / zoning into one queryable
--     surface — `program_kind` enum is real-estate-shaped (subsidy /
--     tax_incentive / loan / certification / zoning), and `property_type_target`
--     + `law_basis` constrain eligibility along axes that have no parallel in
--     `programs` (which is agriculture-leaning). Putting these into `programs`
--     would force every existing search path to add a real-estate-specific
--     filter and would mix 用途地域 zoning rows with 補助金 rows.
--   * `zoning_overlays` is a *spatial overlay registry* (用途地域 / 防火地域
--     / 高度地区 / 景観地区 / etc.) keyed by (prefecture, city, district).
--     It is the canonical join target for `cross_check_zoning` (W4) and for
--     dd_property_am to pull 建蔽率 / 容積率 / 高さ制限 from `restrictions_json`.
--     These rows have no monetary amount (they are restrictions, not programs)
--     so they don't fit alongside subsidies / loans / tax incentives.
--
-- Why on jpintel.db (not autonomath.db):
--   autonomath.db is the read-only EAV primary source (collection CLI
--   territory). The collection CLI has its own `record_kind` extension
--   path scheduled for W2 (handled by a different agent / migration).
--   This migration only touches jpintel.db so the launch CLI can wire
--   tools without coordinating with the collection CLI's release cycle.
--
-- Schema discipline:
--   * program_kind / zoning_type / tier are CHECK-constrained enums — text
--     values must match enum lists exactly (matches the bounded-text-to-select
--     rule from feedback_bounded_text_to_select).
--   * canonical_id is TEXT PRIMARY KEY (no AUTOINCREMENT) so ingest can
--     write deterministic IDs derived from source URLs.
--   * source_url / source_fetched_at are NOT NULL — every row must have
--     primary-source lineage (whitelist enforced at ingest time, same
--     rule as 015_laws / 018_tax_rulesets / 039_healthcare_schema).
--     Aggregator hosts (suumo / homes / athome / lifull) are banned at
--     the ingest layer.
--   * tier / excluded mirror the existing programs convention so the
--     judgment engine reuses the same filter logic. zoning_overlays has
--     no tier column because zoning rules are facts, not graded programs.
--   * restrictions_json is application-managed JSON (建蔽率 / 容積率 /
--     高さ制限 / 日影規制 etc.). Schema validation enforced at the ingest
--     layer, not at the SQLite CHECK level (sqlite3 JSON1 is optional).
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying this file is a
-- no-op. The runner (scripts/migrate.py) records this in
-- schema_migrations(id, checksum, applied_at).

PRAGMA foreign_keys = ON;

-- ============================================================================
-- real_estate_programs — 不動産関連 補助金 / 税制優遇 / 融資 / 認定 / zoning
-- ============================================================================

CREATE TABLE IF NOT EXISTS real_estate_programs (
    canonical_id TEXT PRIMARY KEY,
    program_kind TEXT NOT NULL CHECK (program_kind IN (
        'subsidy', 'tax_incentive', 'loan', 'certification', 'zoning'
    )),
    name TEXT NOT NULL,
    authority TEXT NOT NULL,
    authority_level TEXT,
    prefecture TEXT,
    city TEXT,
    property_type_target TEXT,         -- 商業 / 住宅 / 工場 / 農地 / 林地 など
    law_basis TEXT,                    -- 建築基準法 / 都市計画法 / 不動産登記法 など
    amount_max_yen INTEGER,
    application_open_at TEXT,
    application_close_at TEXT,
    source_url TEXT NOT NULL,
    source_fetched_at TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'B' CHECK (tier IN ('S','A','B','C','X')),
    excluded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_real_estate_pref_kind
    ON real_estate_programs(prefecture, program_kind, tier);
CREATE INDEX IF NOT EXISTS idx_real_estate_law
    ON real_estate_programs(law_basis);

-- ============================================================================
-- zoning_overlays — 用途地域 / 防火地域 / 高度地区 / 景観地区 など spatial overlays
-- ============================================================================

CREATE TABLE IF NOT EXISTS zoning_overlays (
    canonical_id TEXT PRIMARY KEY,
    prefecture TEXT NOT NULL,
    city TEXT NOT NULL,
    district TEXT,
    zoning_type TEXT NOT NULL CHECK (zoning_type IN (
        '用途地域', '防火地域', '準防火地域', '高度地区', '景観地区',
        '特別用途地区', 'その他'
    )),
    restrictions_json TEXT,            -- JSON: {建蔽率: 60, 容積率: 200, etc.}
    law_basis TEXT,
    source_url TEXT NOT NULL,
    source_fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_zoning_pref_city
    ON zoning_overlays(prefecture, city);
CREATE INDEX IF NOT EXISTS idx_zoning_type
    ON zoning_overlays(zoning_type);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
