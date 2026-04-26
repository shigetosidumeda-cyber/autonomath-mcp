-- 014_business_intelligence_layer.sql
-- ---------------------------------------------------------------------------
-- Japanese business intelligence layer. Pivots all datasets on houjin_bangou
-- (13-digit national corporate ID), enabling 1-call composite queries via
-- analyze_fit(). Collected by parallel data-agent on 2026-04-23:
-- 188,532 records across 106 topics (post-cleanup: equity 除外 / エンジェル税制
-- keep / 終了制度 skip).
--
-- Perf critical: industry_program_density is a materialized view that
-- precomputes peer-adoption aggregates, collapsing the analyze_fit hot path
-- from O(peers × adoptions/peer) worst-case 200ms+ to O(log N) ~2ms.
--
-- Source discipline: every row here carries source_url + fetched_at + a
-- source_domain entry in source_lineage_audit. Banned aggregators
-- (noukaweb, hojyokin-portal, biz.stayway, subsidymap, navit-j) MUST be
-- rejected at ingest time. See scripts/ingest/check_lineage.py.
-- ---------------------------------------------------------------------------

PRAGMA foreign_keys = ON;

-- ============================================================================
-- houjin_master -- NTA (国税庁) 法人番号公表サイト canonical, 86,710 rows
-- ============================================================================

CREATE TABLE IF NOT EXISTS houjin_master (
    houjin_bangou TEXT PRIMARY KEY,          -- 13-digit national corporate ID
    normalized_name TEXT NOT NULL,
    alternative_names_json TEXT,             -- list[str] (kana / old names)
    address_normalized TEXT,
    prefecture TEXT,
    municipality TEXT,
    corporation_type TEXT,                   -- 株式会社 / 合同会社 / 一般社団 / ...
    established_date TEXT,                   -- ISO date or NULL
    close_date TEXT,                         -- ISO date or NULL (NULL = active)
    last_updated_nta TEXT,                   -- NTA's last update timestamp
    data_sources_json TEXT,                  -- ['nta_public_detail', 'gbiz', ...]
    total_adoptions INTEGER NOT NULL DEFAULT 0,       -- denorm cache
    total_received_yen INTEGER NOT NULL DEFAULT 0,    -- denorm cache
    notes TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_houjin_name
    ON houjin_master(normalized_name);
CREATE INDEX IF NOT EXISTS idx_houjin_prefecture
    ON houjin_master(prefecture, municipality);
CREATE INDEX IF NOT EXISTS idx_houjin_ctype
    ON houjin_master(corporation_type);
CREATE INDEX IF NOT EXISTS idx_houjin_active
    ON houjin_master(close_date) WHERE close_date IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS houjin_master_fts USING fts5(
    houjin_bangou UNINDEXED,
    normalized_name,
    alternative_names,
    address,
    tokenize='trigram'
);

-- ============================================================================
-- adoption_records -- flat 採択実績 (誰が・何を・いくら) ~125K rows
--   Sources: jigyou-saikouchiku 17.9K + meti/maff acceptance stats + mirasapo
--   2.2K (federated). houjin_bangou required; program_id_hint resolves to
--   programs.unified_id during ingest normalization.
-- ============================================================================

CREATE TABLE IF NOT EXISTS adoption_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou TEXT NOT NULL,
    program_id_hint TEXT,                    -- matches programs.unified_id when resolved
    program_name_raw TEXT,                   -- as appeared in source PDF
    company_name_raw TEXT,                   -- name at time of adoption
    round_label TEXT,                        -- '第11回' / 'R5通常' / ...
    round_number INTEGER,
    announced_at TEXT,                       -- ISO date of adoption announcement
    prefecture TEXT,
    municipality TEXT,
    project_title TEXT,
    industry_raw TEXT,                       -- freeform from PDF
    industry_jsic_medium TEXT,               -- normalized JSIC 2-digit (01-99)
    amount_granted_yen INTEGER,              -- 交付決定額 (may be NULL)
    amount_project_total_yen INTEGER,        -- 事業総額 (may be NULL)
    source_url TEXT NOT NULL,
    source_pdf_page TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.85,
    FOREIGN KEY (houjin_bangou)
        REFERENCES houjin_master(houjin_bangou) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_adoption_houjin
    ON adoption_records(houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_adoption_program_hint
    ON adoption_records(program_id_hint);
CREATE INDEX IF NOT EXISTS idx_adoption_jsic_pref
    ON adoption_records(industry_jsic_medium, prefecture);
CREATE INDEX IF NOT EXISTS idx_adoption_announced
    ON adoption_records(announced_at);
CREATE INDEX IF NOT EXISTS idx_adoption_round
    ON adoption_records(program_id_hint, round_number);

CREATE VIRTUAL TABLE IF NOT EXISTS adoption_fts USING fts5(
    record_id UNINDEXED,
    project_title,
    industry_raw,
    company_name_raw,
    program_name_raw,
    tokenize='trigram'
);

-- ============================================================================
-- industry_stats -- e-Stat 事業所統計 / 経済センサス, 81,831 rows
--   JSIC × area × scale × org_type distribution. Answers "what is the typical
--   SME in this segment" to power peer-normalized recommendations.
-- ============================================================================

CREATE TABLE IF NOT EXISTS industry_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statistic_source TEXT NOT NULL,          -- 'e-Stat_establishment_survey', '経済センサス', ...
    statistic_year INTEGER,
    jsic_code_large TEXT,                    -- A-T
    jsic_name_large TEXT,
    jsic_code_medium TEXT,                   -- 01-99
    jsic_name_medium TEXT,
    prefecture TEXT,
    area_code TEXT,
    area_type TEXT,                          -- 'national' | 'prefecture' | 'city'
    scale_code TEXT,                         -- e.g., '1_4' for 1-4 employees
    scale_employees_bucket TEXT,             -- human-readable
    org_type TEXT,                           -- '会社' | '個人' | '法人その他'
    establishment_count INTEGER,
    employee_count_total INTEGER,
    employee_count_male INTEGER,
    employee_count_female INTEGER,
    regular_employee_total INTEGER,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.95,
    UNIQUE(statistic_source, statistic_year, jsic_code_medium, prefecture, area_code, scale_code, org_type)
);

CREATE INDEX IF NOT EXISTS idx_industry_stats_jsic_pref
    ON industry_stats(jsic_code_medium, prefecture, scale_code);
CREATE INDEX IF NOT EXISTS idx_industry_stats_year
    ON industry_stats(statistic_year);
CREATE INDEX IF NOT EXISTS idx_industry_stats_large
    ON industry_stats(jsic_code_large, prefecture);

-- ============================================================================
-- support_org -- 認定支援機関 + IT vendor + J-Startup + 中央会, 26,229 rows
-- ============================================================================

CREATE TABLE IF NOT EXISTS support_org (
    org_id TEXT PRIMARY KEY,                 -- registry-specific ID
    org_type TEXT NOT NULL,                  -- 'it_vendor' | 'ninteishien' | 'jstartup' | 'chuokai' | 'yorozu'
    org_name TEXT NOT NULL,
    houjin_bangou TEXT,                      -- may be NULL (sole prop / unregistered)
    prefecture TEXT,
    municipality TEXT,
    services_json TEXT,                      -- ['subsidy_application', 'it_introduction', ...]
    specialties_json TEXT,                   -- industry specialties
    registration_date TEXT,
    registration_expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'expired' | 'suspended'
    contact_url TEXT,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.9
);

CREATE INDEX IF NOT EXISTS idx_support_org_type
    ON support_org(org_type, status);
CREATE INDEX IF NOT EXISTS idx_support_org_pref
    ON support_org(prefecture, org_type);
CREATE INDEX IF NOT EXISTS idx_support_org_houjin
    ON support_org(houjin_bangou) WHERE houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_support_org_active
    ON support_org(status, prefecture) WHERE status = 'active';

CREATE VIRTUAL TABLE IF NOT EXISTS support_org_fts USING fts5(
    org_id UNINDEXED,
    org_name,
    services,
    specialties,
    tokenize='trigram'
);

-- ============================================================================
-- ministry_faq -- 省庁公式 Q&A, 552 rows (grows over time)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ministry_faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name_hint TEXT,
    ministry TEXT,
    category TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_section TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.92,
    UNIQUE(program_name_hint, question)
);

CREATE INDEX IF NOT EXISTS idx_faq_program_hint
    ON ministry_faq(program_name_hint);
CREATE INDEX IF NOT EXISTS idx_faq_ministry_cat
    ON ministry_faq(ministry, category);

CREATE VIRTUAL TABLE IF NOT EXISTS ministry_faq_fts USING fts5(
    faq_id UNINDEXED,
    question,
    answer,
    category,
    tokenize='trigram'
);

-- ============================================================================
-- verticals_deep -- Wave 2-7 business-vertical deep dives, 2,957 rows
--   Unified schema with vertical_code tag so 106 industry verticals
--   (医療DX, Web3, EV/FCV, 宇宙, 半導体, 防衛経済安保, ドローン, 民泊,
--    eスポーツ, バイオ製造, 伝統工芸, 消費者保護, JETRO FTA/EPA, ...)
--   live in one table instead of 106 separate tables.
-- ============================================================================

CREATE TABLE IF NOT EXISTS verticals_deep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical_code TEXT NOT NULL,             -- e.g., '106_medical_dx_ehr_telehealth'
    vertical_label TEXT NOT NULL,            -- '医療DX / EHR / 遠隔医療'
    wave_number INTEGER,                     -- 2-7
    record_type TEXT NOT NULL,               -- 'program' | 'regulation' | 'certification' | 'reference'
    record_title TEXT NOT NULL,
    record_summary TEXT,
    ministry TEXT,
    prefecture TEXT,
    program_id_hint TEXT,                    -- links to programs.unified_id when applicable
    effective_from TEXT,
    effective_until TEXT,
    source_url TEXT NOT NULL,
    source_excerpt TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.88
);

CREATE INDEX IF NOT EXISTS idx_verticals_code
    ON verticals_deep(vertical_code);
CREATE INDEX IF NOT EXISTS idx_verticals_type
    ON verticals_deep(record_type, ministry);
CREATE INDEX IF NOT EXISTS idx_verticals_program
    ON verticals_deep(program_id_hint) WHERE program_id_hint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_verticals_wave
    ON verticals_deep(wave_number, vertical_code);

CREATE VIRTUAL TABLE IF NOT EXISTS verticals_deep_fts USING fts5(
    vertical_id UNINDEXED,
    vertical_label,
    record_title,
    record_summary,
    tokenize='trigram'
);

-- ============================================================================
-- industry_program_density -- MATERIALIZED VIEW (perf-critical)
--   Precomputed peer-adoption density keyed on (jsic_medium, prefecture,
--   program_id). Collapses analyze_fit step 4-5 aggregation from
--   O(peers × adoptions/peer) worst-case 200ms to O(log N) ~2ms.
--   Refreshed nightly by scripts/refresh_density.py (DELETE + INSERT).
-- ============================================================================

CREATE TABLE IF NOT EXISTS industry_program_density (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jsic_code_medium TEXT NOT NULL,
    prefecture TEXT NOT NULL,
    program_id TEXT NOT NULL,                -- programs.unified_id or stable hash
    peer_count INTEGER NOT NULL,
    total_granted_yen INTEGER,
    avg_granted_yen INTEGER,
    stddev_granted_yen REAL,
    min_granted_yen INTEGER,
    max_granted_yen INTEGER,
    latest_announced_at TEXT,
    last_refreshed_at TEXT NOT NULL,
    UNIQUE(jsic_code_medium, prefecture, program_id)
);

CREATE INDEX IF NOT EXISTS idx_density_program
    ON industry_program_density(program_id);
CREATE INDEX IF NOT EXISTS idx_density_peer_count
    ON industry_program_density(peer_count DESC);
CREATE INDEX IF NOT EXISTS idx_density_segment
    ON industry_program_density(jsic_code_medium, prefecture, peer_count DESC);

-- ============================================================================
-- source_lineage_audit -- row-level provenance (fraud-risk self-check)
--   Every inserted row in houjin/adoption/industry/support/faq/verticals gets
--   one entry here. Ingest refuses banned domains (noukaweb, hojyokin-portal,
--   biz.stayway, subsidymap, navit-j). Daily scripts/audit_lineage.py scans
--   for newly appearing domains and flags for manual review.
-- ============================================================================

CREATE TABLE IF NOT EXISTS source_lineage_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_key TEXT NOT NULL,                   -- PK of the row in its source table
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,             -- extracted once for banned-domain filter
    fetched_at TEXT NOT NULL,
    primary_source INTEGER NOT NULL DEFAULT 1,  -- 1=go.jp/official, 0=suspect
    audited_at TEXT,
    audit_status TEXT NOT NULL DEFAULT 'unaudited',  -- 'unaudited' | 'clean' | 'flagged' | 'removed'
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_lineage_table_row
    ON source_lineage_audit(table_name, row_key);
CREATE INDEX IF NOT EXISTS idx_lineage_domain
    ON source_lineage_audit(source_domain, primary_source);
CREATE INDEX IF NOT EXISTS idx_lineage_flag
    ON source_lineage_audit(audit_status)
    WHERE audit_status != 'clean';

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
