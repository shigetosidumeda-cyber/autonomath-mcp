-- 011_external_data_tables.sql
-- Adds five tables for the 2026-04-23 external data-collection drop
-- (see /tmp/autonomath_data_collection_2026-04-23/) plus two columns on
-- the existing `exclusion_rules` table so we can keep the richer
-- source-attribution fields those records carry.
--
-- Why a separate migration and not a schema.sql rewrite:
--   * schema.sql is re-applied on every init_db() call to cover fresh
--     volumes. Keeping the legacy shape there and layering these tables
--     via migrations mirrors the pattern 001_lineage / 008_email_schedule
--     already use — the runner (scripts/migrate.py) records this file in
--     schema_migrations so reapplies are a no-op.
--   * ALTER TABLE ADD COLUMN on `exclusion_rules` is idempotent only via
--     the duplicate-column fallback in migrate.py (SQLite has no
--     IF NOT EXISTS on ADD COLUMN). Running this file twice is safe.
--
-- Idempotency notes:
--   * Every CREATE is IF NOT EXISTS.
--   * The two ALTERs sit at the bottom so a partial reapply that already
--     has the new columns hits the duplicate-column fallback in the
--     runner (matches the pattern of 009_email_schedule_retry.sql).
--
-- Foreign keys:
--   * Intentionally NOT enforced to programs(unified_id). External data
--     carries `program_name_hint` / `program_name` free-text; resolution
--     to a canonical unified_id is a later concern (see docs/data_integrity.md
--     roadmap). Hard-FK would force us to drop records with no match yet.
--
-- Data types:
--   * SQLite has no native BOOLEAN or JSON. We use INTEGER 0/1 for bools
--     and TEXT for JSON (stored via orjson.dumps in the ingest script).
--     The column names keep `_json` suffix where the payload is JSON so
--     query callers can grep the schema for "this is JSON, not a scalar".

-- ---------------------------------------------------------------------------
-- program_documents
-- ---------------------------------------------------------------------------
-- Per-program application forms + URL + page count. Source: 04_program_documents.
-- UNIQUE(program_name, form_url_direct) gives us idempotent UPSERT — the
-- same application form can only be registered once per program/URL pair.
CREATE TABLE IF NOT EXISTS program_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name TEXT NOT NULL,
    form_name TEXT,
    form_type TEXT,
    form_format TEXT,
    form_url_direct TEXT,
    pages INTEGER,
    signature_required INTEGER,           -- 0/1/NULL
    support_org_needed INTEGER,           -- 0/1/NULL
    completion_example_url TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL,
    UNIQUE(program_name, form_url_direct)
);

CREATE INDEX IF NOT EXISTS idx_program_documents_program_name
    ON program_documents(program_name);
CREATE INDEX IF NOT EXISTS idx_program_documents_form_type
    ON program_documents(form_type);

-- ---------------------------------------------------------------------------
-- case_studies
-- ---------------------------------------------------------------------------
-- Mirasapo 事例ナビ company case studies. Source: 22_mirasapo_cases.
-- case_id (e.g. "mirasapo_case_118") is the natural PK. Re-ingest UPSERTs
-- on this key.
CREATE TABLE IF NOT EXISTS case_studies (
    case_id TEXT PRIMARY KEY,
    company_name TEXT,
    houjin_bangou TEXT,
    is_sole_proprietor INTEGER,           -- 0/1/NULL
    prefecture TEXT,
    municipality TEXT,
    industry_jsic TEXT,
    industry_name TEXT,
    employees INTEGER,
    founded_year INTEGER,
    capital_yen INTEGER,
    case_title TEXT,
    case_summary TEXT,
    programs_used_json TEXT,              -- list[str]
    total_subsidy_received_yen INTEGER,
    outcomes_json TEXT,                   -- list[str]
    patterns_json TEXT,                   -- list[str]
    publication_date TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_case_studies_houjin_bangou
    ON case_studies(houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_case_studies_prefecture
    ON case_studies(prefecture);
CREATE INDEX IF NOT EXISTS idx_case_studies_industry_jsic
    ON case_studies(industry_jsic);

-- ---------------------------------------------------------------------------
-- enforcement_cases
-- ---------------------------------------------------------------------------
-- 会計検査院 / ministry enforcement cases (clawbacks, admin penalties,
-- audit findings). Source: 13_enforcement_cases. case_id (e.g.
-- "jbaudit_r03_2021-r03-0046-0_1") is the natural PK.
CREATE TABLE IF NOT EXISTS enforcement_cases (
    case_id TEXT PRIMARY KEY,
    event_type TEXT,
    program_name_hint TEXT,
    recipient_name TEXT,
    recipient_kind TEXT,
    recipient_houjin_bangou TEXT,
    is_sole_proprietor INTEGER,           -- 0/1/NULL
    bureau TEXT,
    intermediate_recipient TEXT,
    prefecture TEXT,
    ministry TEXT,
    occurred_fiscal_years_json TEXT,      -- list[int]
    amount_yen INTEGER,
    amount_project_cost_yen INTEGER,
    amount_grant_paid_yen INTEGER,
    amount_improper_grant_yen INTEGER,
    amount_improper_project_cost_yen INTEGER,
    reason_excerpt TEXT,
    legal_basis TEXT,
    source_url TEXT,
    source_section TEXT,
    source_title TEXT,
    disclosed_date TEXT,
    disclosed_until TEXT,
    fetched_at TEXT,
    confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_enforcement_program_name_hint
    ON enforcement_cases(program_name_hint);
CREATE INDEX IF NOT EXISTS idx_enforcement_houjin_bangou
    ON enforcement_cases(recipient_houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_enforcement_prefecture
    ON enforcement_cases(prefecture);
CREATE INDEX IF NOT EXISTS idx_enforcement_legal_basis
    ON enforcement_cases(legal_basis);
CREATE INDEX IF NOT EXISTS idx_enforcement_disclosed_date
    ON enforcement_cases(disclosed_date);

-- ---------------------------------------------------------------------------
-- new_program_candidates
-- ---------------------------------------------------------------------------
-- Programs mentioned in tax-reform outlines / budget proposals but not yet
-- registered in the canonical programs table. Source: 07_new_program_candidates.
-- UNIQUE(candidate_name, source_url) lets us track the same mention across
-- multiple source docs without duplicating per re-ingest.
CREATE TABLE IF NOT EXISTS new_program_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_name TEXT NOT NULL,
    mentioned_in TEXT,
    ministry TEXT,
    budget_yen INTEGER,
    program_kind_hint TEXT,
    expected_start TEXT,
    policy_background_excerpt TEXT,
    source_url TEXT,
    source_pdf_page TEXT,
    fetched_at TEXT,
    confidence REAL,
    UNIQUE(candidate_name, source_url)
);

CREATE INDEX IF NOT EXISTS idx_new_program_candidates_name
    ON new_program_candidates(candidate_name);
CREATE INDEX IF NOT EXISTS idx_new_program_candidates_ministry
    ON new_program_candidates(ministry);

-- ---------------------------------------------------------------------------
-- loan_programs
-- ---------------------------------------------------------------------------
-- Loan programs with rate / period / provider detail. Source: 08_loan_programs.
-- UNIQUE(program_name, provider) — same-named products exist across
-- providers (e.g. JFC 国民事業 vs 中小事業), distinguished by provider.
CREATE TABLE IF NOT EXISTS loan_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name TEXT NOT NULL,
    provider TEXT,
    loan_type TEXT,
    amount_max_yen INTEGER,
    loan_period_years_max INTEGER,
    grace_period_years_max INTEGER,
    interest_rate_base_annual REAL,
    interest_rate_special_annual REAL,
    rate_names TEXT,
    security_required TEXT,
    target_conditions TEXT,
    official_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL,
    UNIQUE(program_name, provider)
);

CREATE INDEX IF NOT EXISTS idx_loan_programs_program_name
    ON loan_programs(program_name);
CREATE INDEX IF NOT EXISTS idx_loan_programs_provider
    ON loan_programs(provider);

-- ---------------------------------------------------------------------------
-- exclusion_rules extensions
-- ---------------------------------------------------------------------------
-- The 03_exclusion_rules records carry two fields the legacy schema does
-- not model. We add them without rewriting existing rows. `condition` is
-- the free-text conjunction (e.g. "同一の補助対象経費"), `source_excerpt`
-- is the verbatim quote that grounds the rule.
--
-- Duplicate-column fallback in scripts/migrate.py swallows reapply errors.
ALTER TABLE exclusion_rules ADD COLUMN source_excerpt TEXT;
ALTER TABLE exclusion_rules ADD COLUMN condition TEXT;
