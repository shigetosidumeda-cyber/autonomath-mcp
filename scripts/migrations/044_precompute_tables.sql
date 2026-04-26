-- 044_precompute_tables.sql
-- 14 new pre-compute (pc_*) tables — Reasoning Layer L2/L3 (v8 P5-ε++ / dd_v8_C3).
--
-- Business context:
--   v8 plan target: T+30d 33 / T+90d 47 / T+180d 79 / Y3 100+ pre-compute
--   tables. Launch baseline = 19. This migration adds 14 new pc_* tables,
--   bringing the count to 33 (T+30d target). All tables are EMPTY at launch
--   — population happens nightly via scripts/cron/precompute_refresh.py.
--
-- Naming convention:
--   pc_<entity>_by_<dimension>          (lookup-by-dimension materialized view)
--   pc_<source>_to_<target>_index       (graph adjacency materialized view)
--   pc_<entity>_<aggregate>             (rollup / stats)
--
-- Why nightly population (not on-write triggers):
--   * Source rows live across two SQLite files (jpintel.db + autonomath.db,
--     no ATTACH allowed by the architecture rule). A trigger cannot reach
--     across files; nightly cron python opens both connections and merges.
--   * L2 freshness target = "yesterday's data is fine". Customers paying
--     ¥3/req for a Zipf-hot enum query do not need single-second freshness;
--     they need reproducible, tested rollups. The amendment_alert cron is
--     the real-time path for change-notification.
--
-- Read posture:
--   * pc_* tables are READ-ONLY from API code. Only the precompute_refresh
--     cron may DELETE/INSERT.
--   * API tools (search_*, list_*) consult pc_* first; on miss they fall
--     through to the original L0/L1 tables. This makes the launch path
--     identical to today even if the refresh cron has not run yet.
--
-- Storage budget:
--   Each pc_* table is small (47 prefectures × top 20 = 940 rows max, etc.).
--   Total estimated footprint: < 10 MB. The point is index economy + serialised
--   response shape, not row-count savings.
--
-- 14 tables in this migration:
--   1. pc_top_subsidies_by_industry          (industry × top 20 subsidies)
--   2. pc_top_subsidies_by_prefecture        (47 prefectures × top 20)
--   3. pc_law_to_program_index               (law_id → program_ids[])
--   4. pc_program_to_amendments              (program_id → amendment_ids[])
--   5. pc_acceptance_stats_by_program        (program_id × FY × 採択率)
--   6. pc_combo_pairs                        (program_a × program_b × compat)
--   7. pc_seasonal_calendar                  (month × deadline programs)
--   8. pc_industry_jsic_aliases              (alias → JSIC mapping)
--   9. pc_authority_to_programs              (authority_id → program_ids[])
--  10. pc_law_amendments_recent              (last 365 days amendments)
--  11. pc_enforcement_by_industry            (industry × recent enforcement)
--  12. pc_loan_by_collateral_type            (collateral × top loans)
--  13. pc_certification_by_subject           (subject × top certs)
--  14. pc_starter_packs_per_audience         (5 audience × pre-built pack)
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. pc_top_subsidies_by_industry
--    For each (industry_jsic, rank), the top-20 subsidies by relevance score.
--    Backs search_tax_incentives + list_open_programs when filter_by=industry.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_top_subsidies_by_industry (
    industry_jsic    TEXT NOT NULL,
    rank             INTEGER NOT NULL,                   -- 1..20
    program_id       TEXT NOT NULL,
    relevance_score  REAL NOT NULL,
    cached_payload   TEXT,                               -- optional pre-serialized JSON
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (industry_jsic, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_top_subs_ind_program
    ON pc_top_subsidies_by_industry(program_id);

-- ---------------------------------------------------------------------------
-- 2. pc_top_subsidies_by_prefecture
--    47 prefectures × top 20. Backs search_tax_incentives.region filter.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_top_subsidies_by_prefecture (
    prefecture_code  TEXT NOT NULL,                      -- ISO 3166-2:JP, e.g. "JP-13"
    rank             INTEGER NOT NULL,                   -- 1..20
    program_id       TEXT NOT NULL,
    relevance_score  REAL NOT NULL,
    cached_payload   TEXT,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (prefecture_code, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_top_subs_pref_program
    ON pc_top_subsidies_by_prefecture(program_id);

-- ---------------------------------------------------------------------------
-- 3. pc_law_to_program_index
--    law_id → list of program_ids that cite the law in their canonical text.
--    Edge of the law ⇄ program graph. One row per (law_id, program_id) pair.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_law_to_program_index (
    law_id           TEXT NOT NULL,
    program_id       TEXT NOT NULL,
    citation_kind    TEXT NOT NULL CHECK (
                         citation_kind IN ('basis','reference','sunset','enforcement')
                     ),
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (law_id, program_id, citation_kind)
);
CREATE INDEX IF NOT EXISTS idx_pc_law_program_byprog
    ON pc_law_to_program_index(program_id);

-- ---------------------------------------------------------------------------
-- 4. pc_program_to_amendments
--    program_id → all amendment events affecting it. Replaces the live JOIN
--    against am_amendment_snapshot for change-history endpoints.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_program_to_amendments (
    program_id       TEXT NOT NULL,
    amendment_id     TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (
                         severity IN ('critical','important','info')
                     ),
    observed_at      TEXT NOT NULL,                      -- ISO 8601 UTC
    summary          TEXT,                               -- one-line human summary
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, amendment_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_prog_amend_observed
    ON pc_program_to_amendments(observed_at);

-- ---------------------------------------------------------------------------
-- 5. pc_acceptance_stats_by_program
--    program_id × FY (会計年度) × applied / accepted / 採択率. Backs
--    search_acceptance_stats_am without the on-demand 集計 step.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_acceptance_stats_by_program (
    program_id       TEXT NOT NULL,
    fiscal_year      INTEGER NOT NULL,                   -- e.g. 2025
    round_label      TEXT,                               -- "1次", "2次", NULL=annual
    applied_count    INTEGER NOT NULL DEFAULT 0,
    accepted_count   INTEGER NOT NULL DEFAULT 0,
    acceptance_rate  REAL,                               -- accepted / applied (NULL if 0)
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, fiscal_year, round_label)
);
CREATE INDEX IF NOT EXISTS idx_pc_accept_stats_fy
    ON pc_acceptance_stats_by_program(fiscal_year);

-- ---------------------------------------------------------------------------
-- 6. pc_combo_pairs
--    Pairs of programs known to be co-applicable (compatible) or mutually
--    exclusive (conflict). Backs subsidy_combo_finder. compat_kind
--    enumerates the relationship (no free-text — bounded enum per
--    feedback_bounded_text_to_select).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_combo_pairs (
    program_a        TEXT NOT NULL,
    program_b        TEXT NOT NULL,
    compat_kind      TEXT NOT NULL CHECK (
                         compat_kind IN ('compatible','conflict','prerequisite','sunset_replaces')
                     ),
    rationale        TEXT,                               -- citation / explanation
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_a, program_b)
);
CREATE INDEX IF NOT EXISTS idx_pc_combo_b
    ON pc_combo_pairs(program_b);

-- ---------------------------------------------------------------------------
-- 7. pc_seasonal_calendar
--    month_of_year (1..12) × programs whose deadline falls in that month.
--    Backs deadline_calendar tool. Refreshed nightly so "month" reflects the
--    next 12-month rolling window (not literal calendar months).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_seasonal_calendar (
    month_of_year    INTEGER NOT NULL CHECK (month_of_year BETWEEN 1 AND 12),
    program_id       TEXT NOT NULL,
    deadline_date    TEXT NOT NULL,                      -- ISO 8601 date
    deadline_kind    TEXT NOT NULL CHECK (
                         deadline_kind IN ('application','interim','final','rolling')
                     ),
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (month_of_year, program_id, deadline_date)
);
CREATE INDEX IF NOT EXISTS idx_pc_seasonal_program
    ON pc_seasonal_calendar(program_id);

-- ---------------------------------------------------------------------------
-- 8. pc_industry_jsic_aliases
--    alias_text → canonical JSIC code. Backs the natural-language industry
--    matcher (e.g. "農業" → JSIC A0). Mirrors the matcher-side ALIAS table
--    discussed in project_registry_vocab_drift.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_industry_jsic_aliases (
    alias_text       TEXT NOT NULL,                      -- normalized lowercase
    industry_jsic    TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 1.0,          -- 0.0..1.0
    source           TEXT,                               -- 'jsic_official' | 'derived' | ...
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (alias_text, industry_jsic)
);
CREATE INDEX IF NOT EXISTS idx_pc_jsic_alias_jsic
    ON pc_industry_jsic_aliases(industry_jsic);

-- ---------------------------------------------------------------------------
-- 9. pc_authority_to_programs
--    authority_id (中央省庁 / 自治体 / 公庫 etc.) → program_ids[].
--    Backs the "all programs from METI" style enumerations.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_authority_to_programs (
    authority_id     TEXT NOT NULL,
    program_id       TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (
                         role IN ('issuer','co_issuer','administrator','reviewer')
                     ),
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (authority_id, program_id, role)
);
CREATE INDEX IF NOT EXISTS idx_pc_auth_prog_program
    ON pc_authority_to_programs(program_id);

-- ---------------------------------------------------------------------------
-- 10. pc_law_amendments_recent
--    Rolling 365-day window of law amendments. Refreshed nightly with a
--    DELETE-then-INSERT pattern so the cron is idempotent.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_law_amendments_recent (
    amendment_id     TEXT PRIMARY KEY,
    law_id           TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (
                         severity IN ('critical','important','info')
                     ),
    effective_date   TEXT NOT NULL,                      -- ISO 8601 date
    observed_at      TEXT NOT NULL,                      -- ISO 8601 UTC
    summary          TEXT,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pc_law_amend_recent_law
    ON pc_law_amendments_recent(law_id);
CREATE INDEX IF NOT EXISTS idx_pc_law_amend_recent_date
    ON pc_law_amendments_recent(effective_date);

-- ---------------------------------------------------------------------------
-- 11. pc_enforcement_by_industry
--    industry_jsic × recent (last 365d) enforcement actions. Backs
--    check_enforcement_am for industry-scoped queries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_enforcement_by_industry (
    industry_jsic    TEXT NOT NULL,
    enforcement_id   TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (
                         severity IN ('warning','suspension','revocation','fine','prosecution')
                     ),
    observed_at      TEXT NOT NULL,                      -- ISO 8601 UTC
    headline         TEXT,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (industry_jsic, enforcement_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_enf_ind_observed
    ON pc_enforcement_by_industry(observed_at);

-- ---------------------------------------------------------------------------
-- 12. pc_loan_by_collateral_type
--    collateral_type × top loan products. Mirrors the 3-axis loan
--    decomposition (担保 / 個人保証人 / 第三者保証人) — this table covers
--    the 担保 axis. Backs search_loans_am with collateral filter.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_loan_by_collateral_type (
    collateral_type  TEXT NOT NULL CHECK (
                         collateral_type IN (
                            'unsecured','real_estate','equipment',
                            'inventory','accounts_receivable','other'
                         )
                     ),
    rank             INTEGER NOT NULL,                   -- 1..N
    loan_program_id  TEXT NOT NULL,
    cap_amount_yen   INTEGER,                            -- 上限額 (NULL=無制限)
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collateral_type, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_loan_coll_loan
    ON pc_loan_by_collateral_type(loan_program_id);

-- ---------------------------------------------------------------------------
-- 13. pc_certification_by_subject
--    subject (e.g. ISO27001, JISQ15001, PrivacyMark) × top certifications
--    that grant or recognise it. Backs search_certifications.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_certification_by_subject (
    subject_code     TEXT NOT NULL,                      -- e.g. 'iso27001', 'p_mark'
    rank             INTEGER NOT NULL,                   -- 1..N
    certification_id TEXT NOT NULL,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (subject_code, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_cert_subj_cert
    ON pc_certification_by_subject(certification_id);

-- ---------------------------------------------------------------------------
-- 14. pc_starter_packs_per_audience
--    5 audience buckets (税理士 / 行政書士 / SMB / VC / Dev) × pre-built
--    starter pack (a curated bundle of programs + tools the audience needs
--    on day 1). Backs smb_starter_pack and the audience-aware landing page.
--
--    audience matches the testimonials.audience CHECK enum (041_).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_starter_packs_per_audience (
    audience         TEXT NOT NULL CHECK (
                         audience IN ('税理士','行政書士','SMB','VC','Dev')
                     ),
    rank             INTEGER NOT NULL,                   -- 1..N
    program_id       TEXT NOT NULL,
    note             TEXT,                               -- one-line "why" copy
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (audience, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_starter_audience_program
    ON pc_starter_packs_per_audience(program_id);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
