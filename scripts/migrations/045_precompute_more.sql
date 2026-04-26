-- 045_precompute_more.sql
-- 18 additional pre-compute (pc_*) tables — Reasoning Layer L3 expansion
-- (v8 P5-ε++ / dd_v8_D8). 14 from migration 044 + 18 here = 32 total,
-- meeting the v8 plan T+30d target of 33 (33 = 19 launch baseline already
-- live + 14 from 044).
--
-- Same conventions as 044:
--   * Naming: pc_<entity>_by_<dim> | pc_<src>_to_<tgt> | pc_<entity>_<agg>
--   * Idempotency: every CREATE is IF NOT EXISTS.
--   * Population: nightly via scripts/cron/precompute_refresh.py
--     (DELETE-then-INSERT). Pre-launch all tables ship empty — the API
--     read path falls through to L0/L1/L2 on miss, so launch behaviour is
--     unchanged regardless of cron run state.
--   * Storage: each table is bounded (worst case ~10K rows). Total
--     additional footprint < 5 MB.
--   * Read posture: pc_* tables are READ-ONLY from API code. Only the
--     precompute_refresh cron may DELETE/INSERT.
--
-- 18 tables in this migration:
--   1. pc_amendment_recent_by_law              (law × 直近 365 日 amendment)
--   2. pc_program_geographic_density           (prefecture × 件数 × tier 分布)
--   3. pc_authority_action_frequency           (authority × 月次 action count)
--   4. pc_law_to_amendment_chain               (law_id → amendment chain)
--   5. pc_industry_jsic_to_program             (jsic → top 50 programs)
--   6. pc_amount_max_distribution              (amount range × program count)
--   7. pc_program_to_loan_combo                (program × compatible loans)
--   8. pc_program_to_certification_combo       (program × required certs)
--   9. pc_program_to_tax_combo                 (program × applicable tax 特例)
--  10. pc_acceptance_rate_by_authority         (authority × FY × 採択率)
--  11. pc_application_close_calendar           (month × deadline programs)
--  12. pc_amount_to_recipient_size             (amount × SMB size correlation)
--  13. pc_law_text_to_program_count            (law_id × programs referencing)
--  14. pc_court_decision_law_chain             (court × law × related)
--  15. pc_enforcement_industry_distribution    (industry × 5yr count)
--  16. pc_loan_collateral_to_program           (collateral type × matchable programs)
--  17. pc_invoice_registrant_by_pref           (pref × 適格事業者 count)
--  18. pc_amendment_severity_distribution      (severity × month × count)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. pc_amendment_recent_by_law
--    For each law, the amendment events that touched it in the last 365 days.
--    Sibling of pc_law_amendments_recent (044 #10) but indexed law-first.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_amendment_recent_by_law (
    law_id           TEXT NOT NULL,
    amendment_id     TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (
                         severity IN ('critical','important','info')
                     ),
    effective_date   TEXT NOT NULL,                      -- ISO 8601 date
    summary          TEXT,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (law_id, amendment_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_amend_recent_law_date
    ON pc_amendment_recent_by_law(effective_date);

-- ---------------------------------------------------------------------------
-- 2. pc_program_geographic_density
--    For each prefecture, count + tier histogram of programs available there.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_program_geographic_density (
    prefecture_code  TEXT NOT NULL,                      -- e.g. "JP-13"
    tier             TEXT NOT NULL CHECK (tier IN ('S','A','B','C')),
    program_count    INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (prefecture_code, tier)
);
CREATE INDEX IF NOT EXISTS idx_pc_geo_density_tier
    ON pc_program_geographic_density(tier);

-- ---------------------------------------------------------------------------
-- 3. pc_authority_action_frequency
--    authority × calendar month × number of regulatory actions issued.
--    Backs "which authority is active right now" charts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_authority_action_frequency (
    authority_id     TEXT NOT NULL,
    month_yyyymm     TEXT NOT NULL,                      -- 'YYYY-MM'
    action_count     INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (authority_id, month_yyyymm)
);
CREATE INDEX IF NOT EXISTS idx_pc_auth_action_month
    ON pc_authority_action_frequency(month_yyyymm);

-- ---------------------------------------------------------------------------
-- 4. pc_law_to_amendment_chain
--    Graph edge: law_id → ordered amendment chain (parent / child).
--    `position` is 1-based; chain head has parent_amendment_id = NULL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_law_to_amendment_chain (
    law_id                 TEXT NOT NULL,
    amendment_id           TEXT NOT NULL,
    parent_amendment_id    TEXT,                          -- NULL = chain head
    position               INTEGER NOT NULL,              -- 1..N
    effective_date         TEXT NOT NULL,
    refreshed_at           TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (law_id, amendment_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_law_amend_chain_pos
    ON pc_law_to_amendment_chain(law_id, position);

-- ---------------------------------------------------------------------------
-- 5. pc_industry_jsic_to_program
--    JSIC industry code → top 50 programs (relevance-ranked).
--    Sibling of pc_top_subsidies_by_industry (044 #1) but covers ALL programs
--    (not just subsidies) and goes to rank 50 (vs 20).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_industry_jsic_to_program (
    industry_jsic    TEXT NOT NULL,
    rank             INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 50),
    program_id       TEXT NOT NULL,
    relevance_score  REAL NOT NULL,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (industry_jsic, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_jsic_prog_program
    ON pc_industry_jsic_to_program(program_id);

-- ---------------------------------------------------------------------------
-- 6. pc_amount_max_distribution
--    Histogram bucket → number of programs whose amount_max falls in that
--    bucket. Buckets are bounded enum (no free-text drift).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_amount_max_distribution (
    bucket           TEXT NOT NULL CHECK (
                         bucket IN (
                             '<1M','1M-5M','5M-10M','10M-50M',
                             '50M-100M','100M-500M','500M-1B','>1B','unknown'
                         )
                     ),
    program_count    INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (bucket)
);

-- ---------------------------------------------------------------------------
-- 7. pc_program_to_loan_combo
--    program_id → loan products commonly stacked alongside it.
--    compat_kind keeps the same enum vocabulary as pc_combo_pairs (044 #6).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_program_to_loan_combo (
    program_id       TEXT NOT NULL,
    loan_program_id  TEXT NOT NULL,
    compat_kind      TEXT NOT NULL CHECK (
                         compat_kind IN ('compatible','prerequisite','conflict')
                     ),
    rationale        TEXT,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, loan_program_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_prog_loan_loan
    ON pc_program_to_loan_combo(loan_program_id);

-- ---------------------------------------------------------------------------
-- 8. pc_program_to_certification_combo
--    program_id → certifications required (or strongly recommended) for
--    eligibility / scoring uplift.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_program_to_certification_combo (
    program_id        TEXT NOT NULL,
    certification_id  TEXT NOT NULL,
    requirement_kind  TEXT NOT NULL CHECK (
                         requirement_kind IN ('required','preferred','exempt_with')
                      ),
    refreshed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, certification_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_prog_cert_cert
    ON pc_program_to_certification_combo(certification_id);

-- ---------------------------------------------------------------------------
-- 9. pc_program_to_tax_combo
--    program_id → applicable tax 特例 / rulesets.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_program_to_tax_combo (
    program_id       TEXT NOT NULL,
    tax_ruleset_id   TEXT NOT NULL,
    applicability    TEXT NOT NULL CHECK (
                         applicability IN ('mandatory','optional','sunset_replaces')
                     ),
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, tax_ruleset_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_prog_tax_ruleset
    ON pc_program_to_tax_combo(tax_ruleset_id);

-- ---------------------------------------------------------------------------
-- 10. pc_acceptance_rate_by_authority
--     authority × FY × aggregated 採択率 across all the authority's programs.
--     Sibling of pc_acceptance_stats_by_program (044 #5) at the authority
--     rollup level.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_acceptance_rate_by_authority (
    authority_id      TEXT NOT NULL,
    fiscal_year       INTEGER NOT NULL,                  -- e.g. 2025
    applied_count     INTEGER NOT NULL DEFAULT 0,
    accepted_count    INTEGER NOT NULL DEFAULT 0,
    acceptance_rate   REAL,                              -- accepted / applied (NULL if 0)
    program_coverage  INTEGER NOT NULL DEFAULT 0,        -- distinct programs aggregated
    refreshed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (authority_id, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_pc_accept_rate_auth_fy
    ON pc_acceptance_rate_by_authority(fiscal_year);

-- ---------------------------------------------------------------------------
-- 11. pc_application_close_calendar
--     month_of_year × programs whose application **closes** in that month.
--     Distinct from pc_seasonal_calendar (044 #7) which captures any
--     deadline kind including interim / rolling. This one is "close only".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_application_close_calendar (
    month_of_year    INTEGER NOT NULL CHECK (month_of_year BETWEEN 1 AND 12),
    program_id       TEXT NOT NULL,
    close_date       TEXT NOT NULL,                      -- ISO 8601 date
    days_until       INTEGER,                            -- from refreshed_at; can be negative for past
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (month_of_year, program_id, close_date)
);
CREATE INDEX IF NOT EXISTS idx_pc_app_close_program
    ON pc_application_close_calendar(program_id);
CREATE INDEX IF NOT EXISTS idx_pc_app_close_days
    ON pc_application_close_calendar(days_until);

-- ---------------------------------------------------------------------------
-- 12. pc_amount_to_recipient_size
--     Cross-tab: amount bucket × SMB size class (employee headcount band) →
--     count of historically-accepted recipients. Backs "what scale of
--     company actually wins this size of grant" guidance.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_amount_to_recipient_size (
    amount_bucket    TEXT NOT NULL CHECK (
                         amount_bucket IN (
                             '<1M','1M-5M','5M-10M','10M-50M',
                             '50M-100M','100M-500M','500M-1B','>1B','unknown'
                         )
                     ),
    smb_size_class   TEXT NOT NULL CHECK (
                         smb_size_class IN (
                             '1-5','6-20','21-50','51-100','101-300','301+','unknown'
                         )
                     ),
    recipient_count  INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (amount_bucket, smb_size_class)
);

-- ---------------------------------------------------------------------------
-- 13. pc_law_text_to_program_count
--     law_id → number of programs that reference the law in canonical text.
--     Lighter rollup vs pc_law_to_program_index (044 #3) which holds the
--     full edge list.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_law_text_to_program_count (
    law_id           TEXT PRIMARY KEY,
    program_count    INTEGER NOT NULL DEFAULT 0,
    last_cited_at    TEXT,                               -- ISO 8601 date
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- 14. pc_court_decision_law_chain
--     court_id × law_id × decision_id triple — links court decisions to the
--     laws cited and to related decisions. Backs the case-law lookup tools.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_court_decision_law_chain (
    court_id         TEXT NOT NULL,
    law_id           TEXT NOT NULL,
    decision_id      TEXT NOT NULL,
    relation_kind    TEXT NOT NULL CHECK (
                         relation_kind IN ('cites','interprets','overturns','distinguishes')
                     ),
    decided_at       TEXT,                               -- ISO 8601 date
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (court_id, law_id, decision_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_court_law_law
    ON pc_court_decision_law_chain(law_id);
CREATE INDEX IF NOT EXISTS idx_pc_court_law_decision
    ON pc_court_decision_law_chain(decision_id);

-- ---------------------------------------------------------------------------
-- 15. pc_enforcement_industry_distribution
--     industry × rolling 5-year enforcement count + severity histogram.
--     Sibling of pc_enforcement_by_industry (044 #11) at the count level.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_enforcement_industry_distribution (
    industry_jsic    TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (
                         severity IN ('warning','suspension','revocation','fine','prosecution')
                     ),
    five_year_count  INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (industry_jsic, severity)
);
CREATE INDEX IF NOT EXISTS idx_pc_enf_dist_severity
    ON pc_enforcement_industry_distribution(severity);

-- ---------------------------------------------------------------------------
-- 16. pc_loan_collateral_to_program
--     collateral_type → programs whose accepted recipients commonly used
--     loans of that collateral type. Bridge between the loan and program
--     graphs across the 担保 axis.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_loan_collateral_to_program (
    collateral_type  TEXT NOT NULL CHECK (
                         collateral_type IN (
                             'unsecured','real_estate','equipment',
                             'inventory','accounts_receivable','other'
                         )
                     ),
    program_id       TEXT NOT NULL,
    rank             INTEGER NOT NULL,                   -- 1..N
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collateral_type, rank)
);
CREATE INDEX IF NOT EXISTS idx_pc_loan_coll_prog_program
    ON pc_loan_collateral_to_program(program_id);

-- ---------------------------------------------------------------------------
-- 17. pc_invoice_registrant_by_pref
--     prefecture × 適格事業者 count, sourced from the invoice_registrants
--     table (delta-only as of 2026-04-25; full bulk pending). PDL v1.0
--     attribution requirement is honoured at the API output layer.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_invoice_registrant_by_pref (
    prefecture_code  TEXT PRIMARY KEY,                   -- e.g. "JP-13"
    registrant_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at     TEXT,                               -- ISO 8601 date
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- 18. pc_amendment_severity_distribution
--     severity × month_yyyymm → count of amendments. Backs the change-feed
--     trend chart on the docs landing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pc_amendment_severity_distribution (
    severity         TEXT NOT NULL CHECK (
                         severity IN ('critical','important','info')
                     ),
    month_yyyymm     TEXT NOT NULL,                      -- 'YYYY-MM'
    amendment_count  INTEGER NOT NULL DEFAULT 0,
    refreshed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (severity, month_yyyymm)
);
CREATE INDEX IF NOT EXISTS idx_pc_amend_sev_month
    ON pc_amendment_severity_distribution(month_yyyymm);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations.
-- Do NOT INSERT here.
