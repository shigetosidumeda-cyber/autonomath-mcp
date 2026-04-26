-- 039_healthcare_schema.sql
-- Healthcare V3 cohort foundation: medical institutions + care subsidies.
--
-- Business context (analysis_wave18 P6-D / dd_v8_06):
--   Healthcare V3 expands the AutonoMath cohort beyond agriculture / SMB
--   into 医療法人 (3-5k 法人) / 介護施設 (50k+) / 薬局 (60k+) / 訪問介護.
--   T+90d (2026-08-04) launch on a 6-week timeline; this migration is W1
--   schema prep. W2-W3 ingest will populate the two tables; W4 wires 6
--   new MCP tools (search_healthcare_programs, get_medical_institution,
--   search_healthcare_compliance, check_drug_approval,
--   search_care_subsidies, dd_medical_institution_am).
--
-- Why TWO tables, not a cross-domain extension of `programs`:
--   * `medical_institutions` is a *registry* (法人/施設/薬局 master) — the
--     canonical entity row used as join target for compliance queries
--     and dd_medical_institution_am tool. It carries facility-level
--     attributes (beds / 許可番号 / opened_at / closed_at) that have no
--     parallel in 補助金 / 融資 / 税制 rows.
--   * `care_subsidies` is healthcare-specialised *subsidy/incentive*
--     rows that don't fit `programs` (which is agriculture-leaning) —
--     law_basis must reference 介護保険法 / 薬機法 / 医療法 explicitly,
--     and `institution_type_target` constrains eligibility to a single
--     facility class. Putting these into `programs` would force every
--     existing search path to add a healthcare-specific filter.
--
-- Why on jpintel.db (not autonomath.db):
--   autonomath.db is the read-only EAV primary source (collection CLI
--   territory). The collection CLI has its own `record_kind` extension
--   path scheduled for W2-W3 (handled by a different agent / migration).
--   This migration only touches jpintel.db so the launch CLI can wire
--   tools without coordinating with the collection CLI's release cycle.
--
-- Schema discipline:
--   * institution_type / authority_level / tier are CHECK-constrained
--     enums — text values must match enum lists exactly (matches the
--     bounded-text-to-select rule from feedback_bounded_text_to_select).
--   * canonical_id is TEXT PRIMARY KEY (no AUTOINCREMENT) so ingest can
--     write deterministic IDs derived from source URLs.
--   * source_url / source_fetched_at are NOT NULL — every row must have
--     primary-source lineage (whitelist enforced at ingest time, same
--     rule as 015_laws / 018_tax_rulesets).
--   * tier / excluded mirror the existing programs convention so the
--     judgment engine reuses the same filter logic.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying this file is a
-- no-op. The runner (scripts/migrate.py) records this in
-- schema_migrations(id, checksum, applied_at).

PRAGMA foreign_keys = ON;

-- ============================================================================
-- medical_institutions — canonical registry of 医療法人 / 介護施設 / 薬局
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_institutions (
    canonical_id TEXT PRIMARY KEY,
    institution_type TEXT NOT NULL CHECK (institution_type IN (
        '医療法人', '個人医院', '介護施設', '薬局', '訪問介護', 'その他'
    )),
    name TEXT NOT NULL,
    name_kana TEXT,
    prefecture TEXT NOT NULL,
    city TEXT,
    postal_code TEXT,
    phone TEXT,
    beds INTEGER,
    license_number TEXT,
    license_authority TEXT,
    opened_at TEXT,
    closed_at TEXT,
    jsic_code TEXT,
    source_url TEXT NOT NULL,
    source_fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_medical_pref_type
    ON medical_institutions(prefecture, institution_type);
CREATE INDEX IF NOT EXISTS idx_medical_jsic
    ON medical_institutions(jsic_code);

-- ============================================================================
-- care_subsidies — 介護 / 薬機 / 医療 法令ベースの助成・加算
-- ============================================================================

CREATE TABLE IF NOT EXISTS care_subsidies (
    canonical_id TEXT PRIMARY KEY,
    program_name TEXT NOT NULL,
    authority TEXT NOT NULL,
    authority_level TEXT CHECK (authority_level IN ('national', 'prefecture', 'city')),
    prefecture TEXT,
    city TEXT,
    institution_type_target TEXT,  -- 介護施設 / 薬局 など
    max_amount_yen INTEGER,
    application_open_at TEXT,
    application_close_at TEXT,
    law_basis TEXT,                -- 介護保険法 / 薬機法 / 医療法
    source_url TEXT NOT NULL,
    source_fetched_at TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'B' CHECK (tier IN ('S','A','B','C','X')),
    excluded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_care_pref
    ON care_subsidies(prefecture, tier);
CREATE INDEX IF NOT EXISTS idx_care_law
    ON care_subsidies(law_basis);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
