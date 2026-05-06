-- target_db: autonomath
-- migration: wave24_164_gbiz_v2_mirror_tables
-- generated_at: 2026-05-06
-- author: M01 gBizINFO ingest activation (DEEP-01)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Why this exists:
--   Mirror tables for gBizINFO REST API v2 (6 endpoint families per
--   DEEP-01 §1.5). Cross-link layer to am_entities
--   (record_kind='corporate_entity') + am_entity_facts (corp.* namespace)
--   so the unified entity graph absorbs gBizINFO data without redundant
--   re-shaping. Companion to scripts/cron/ingest_gbiz_*_v2.py (one cron
--   per endpoint family). Authoritative ToS:
--   tools/offline/_inbox/public_source_foundation/gbizinfo_tos_verbatim_2026-05-06.md
--
-- Authority:
--   経済産業省 経済産業政策局 (gBizINFO 運営)
--
-- License:
--   政府標準利用規約 第2.0版 (CC-BY 4.0 互換) per gBizINFO ToS §出典表記
--
-- Tables (8 total):
--   1. gbiz_corp_activity        — 法人活動 基本+corporation+workplace summary
--   2. gbiz_corporation_branch   — 事業所/支店 (branch list per houjin)
--   3. gbiz_workplace            — 事業所別 雇用情報 (workplace list)
--   4. gbiz_update_log           — delta sync /v2/hojin/updateInfo/* log
--   5. gbiz_subsidy_award        — 補助金採択 (mirror; canonical = jpi_adoption_records)
--   6. gbiz_certification        — 認定/届出 (健康経営 / 経営力向上計画 etc.)
--   7. gbiz_commendation         — 表彰
--   8. gbiz_procurement          — 公的調達落札 (mirror; canonical = bids p-portal)
--
-- DOWN: see wave24_164_gbiz_v2_mirror_tables_rollback.sql.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. gbiz_corp_activity
--    Single-row-per-houjin mirror of /v2/hojin/{n} basic profile + corporation
--    summary + workplace summary (collapsed). Detail rows split into
--    gbiz_corporation_branch (2) and gbiz_workplace (3).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_corp_activity (
    houjin_bangou           TEXT PRIMARY KEY NOT NULL,
    legal_name              TEXT,
    legal_name_kana         TEXT,
    legal_name_en           TEXT,
    name                    TEXT,
    name_kana               TEXT,
    location                TEXT,
    status                  TEXT,
    postal_code             TEXT,
    kind                    TEXT,
    capital_stock_yen       INTEGER,
    employee_number         INTEGER,
    employee_male           INTEGER,
    employee_female         INTEGER,
    business_summary        TEXT,
    business_items_json     TEXT,
    representative_name     TEXT,
    representative_position TEXT,
    founding_year           INTEGER,
    date_of_establishment   TEXT,
    close_date              TEXT,
    close_cause             TEXT,
    founded_date            TEXT,
    settlement_date         TEXT,
    company_url             TEXT,
    qualification_grade     TEXT,
    gbiz_update_date        TEXT,
    cache_age_hours         REAL,
    upstream_source         TEXT,
    source_url              TEXT,
    fetched_at              TEXT NOT NULL,
    content_hash            TEXT,
    attribution_json        TEXT,
    raw_json                TEXT
);

CREATE INDEX IF NOT EXISTS ix_gbiz_corp_activity_status
    ON gbiz_corp_activity(status);

CREATE INDEX IF NOT EXISTS ix_gbiz_corp_activity_kind
    ON gbiz_corp_activity(kind);

CREATE INDEX IF NOT EXISTS ix_gbiz_corp_activity_postal
    ON gbiz_corp_activity(postal_code);

-- ---------------------------------------------------------------------------
-- 2. gbiz_corporation_branch
--    支店/事業所 list from /v2/hojin/{n}/corporation. FK to gbiz_corp_activity
--    on houjin_bangou (logical, not enforced at DB level — gBizINFO can
--    return branches before the parent corp row is upserted in cron order).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_corporation_branch (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou           TEXT NOT NULL,
    branch_name             TEXT,
    branch_kana             TEXT,
    location                TEXT,
    branch_location         TEXT,
    postal_code             TEXT,
    branch_postal_code      TEXT,
    branch_kind             TEXT,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    raw_json                TEXT,
    FOREIGN KEY (houjin_bangou) REFERENCES gbiz_corp_activity(houjin_bangou)
);

CREATE INDEX IF NOT EXISTS ix_gbiz_corp_branch_houjin
    ON gbiz_corporation_branch(houjin_bangou);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gbiz_corp_branch_identity
    ON gbiz_corporation_branch(houjin_bangou, branch_name, location);

-- ---------------------------------------------------------------------------
-- 3. gbiz_workplace
--    事業所別 雇用情報 from /v2/hojin/{n}/workplace.
--    UNIQUE (houjin_bangou, workplace_id) so re-runs upsert cleanly.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_workplace (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou           TEXT NOT NULL,
    workplace_id            TEXT,
    workplace_name          TEXT,
    location                TEXT,
    postal_code             TEXT,
    employee_number         INTEGER,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    raw_json                TEXT,
    UNIQUE (houjin_bangou, workplace_id)
);

CREATE INDEX IF NOT EXISTS ix_gbiz_workplace_houjin
    ON gbiz_workplace(houjin_bangou);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gbiz_workplace_identity
    ON gbiz_workplace(houjin_bangou, workplace_name, location);

-- ---------------------------------------------------------------------------
-- 4. gbiz_update_log
--    Delta sync log for /v2/hojin/updateInfo/{family}?from=&to= cron pulls.
--    Family is checked at DB level so unknown endpoints fail fast.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_update_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    family                  TEXT CHECK (family IN ('corporation','subsidy','certification','commendation','procurement')),
    endpoint                TEXT,
    date_from               TEXT,
    from_date               TEXT,
    date_to                 TEXT,
    to_date                 TEXT,
    fetched_at              TEXT NOT NULL,
    records_count           INTEGER,
    record_count            INTEGER,
    http_status             INTEGER,
    next_token              TEXT,
    attribution_json        TEXT
);

CREATE INDEX IF NOT EXISTS ix_gbiz_update_log_family_from
    ON gbiz_update_log(family, date_from);

CREATE INDEX IF NOT EXISTS ix_gbiz_update_log_endpoint_from
    ON gbiz_update_log(endpoint, from_date);

-- ---------------------------------------------------------------------------
-- 5. gbiz_subsidy_award
--    補助金採択 (mirror; canonical = jpi_adoption_records). Composite PK
--    accommodates multiple awards per (houjin, program, FY).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_subsidy_award (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    subsidy_resource_id     TEXT,
    houjin_bangou           TEXT NOT NULL,
    title                   TEXT,
    date_of_approval        TEXT,
    government_departments  TEXT,
    target                  TEXT,
    note                    TEXT,
    upstream_source         TEXT,
    raw_json                TEXT,
    program_id              TEXT,
    fiscal_year             INTEGER,
    award_id                TEXT,
    program_name            TEXT,
    amount_yen              INTEGER,
    award_date              TEXT,
    agency_name             TEXT,
    status                  TEXT,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    attribution_json        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gbiz_subsidy_award_resource
    ON gbiz_subsidy_award(houjin_bangou, subsidy_resource_id);

CREATE INDEX IF NOT EXISTS ix_gbiz_subsidy_houjin_fy
    ON gbiz_subsidy_award(houjin_bangou, fiscal_year DESC);

CREATE INDEX IF NOT EXISTS ix_gbiz_subsidy_program_fy
    ON gbiz_subsidy_award(program_id, fiscal_year);

-- ---------------------------------------------------------------------------
-- 6. gbiz_certification
--    認定/届出 (健康経営 / 経営力向上計画 / 等). Composite PK on
--    (houjin_bangou, cert_id) — cert_id assumed unique per certification body.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_certification (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou           TEXT NOT NULL,
    title                   TEXT,
    category                TEXT,
    date_of_approval        TEXT,
    government_departments  TEXT,
    target                  TEXT,
    upstream_source         TEXT,
    raw_json                TEXT,
    cert_id                 TEXT,
    cert_name               TEXT,
    issuing_authority       TEXT,
    issued_date             TEXT,
    valid_until             TEXT,
    cert_url                TEXT,
    status                  TEXT,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    attribution_json        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gbiz_certification_identity
    ON gbiz_certification(houjin_bangou, title, date_of_approval, government_departments);

CREATE INDEX IF NOT EXISTS ix_gbiz_cert_houjin
    ON gbiz_certification(houjin_bangou);

CREATE INDEX IF NOT EXISTS ix_gbiz_cert_authority
    ON gbiz_certification(issuing_authority);

-- ---------------------------------------------------------------------------
-- 7. gbiz_commendation
--    表彰 (各府省/知事 表彰 等). PK on (houjin_bangou, award_id).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_commendation (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou           TEXT NOT NULL,
    title                   TEXT,
    date_of_commendation    TEXT,
    government_departments  TEXT,
    target                  TEXT,
    upstream_source         TEXT,
    raw_json                TEXT,
    award_id                TEXT,
    award_name              TEXT,
    award_date              TEXT,
    granting_authority      TEXT,
    category                TEXT,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    attribution_json        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gbiz_commendation_identity
    ON gbiz_commendation(houjin_bangou, title, date_of_commendation, government_departments);

CREATE INDEX IF NOT EXISTS ix_gbiz_commend_houjin_date
    ON gbiz_commendation(houjin_bangou, award_date DESC);

-- ---------------------------------------------------------------------------
-- 8. gbiz_procurement
--    公的調達落札 (mirror; canonical = bids from p-portal). Single-PK on
--    procurement_resource_id (gBizINFO assigns globally unique IDs);
--    UNIQUE (houjin_bangou, procurement_resource_id) defends against
--    duplicate inserts across cron re-runs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gbiz_procurement (
    houjin_bangou           TEXT NOT NULL,
    procurement_resource_id TEXT NOT NULL,
    title                   TEXT,
    amount_yen              INTEGER,
    date_of_order           TEXT,
    government_departments  TEXT,
    note                    TEXT,
    upstream_source         TEXT,
    raw_json                TEXT,
    agency                  TEXT,
    contract_date           TEXT,
    contract_amount_yen     INTEGER,
    subject                 TEXT,
    procedure_type          TEXT,
    source_url              TEXT,
    fetched_at              TEXT,
    content_hash            TEXT,
    attribution_json        TEXT,
    PRIMARY KEY (procurement_resource_id),
    UNIQUE (houjin_bangou, procurement_resource_id)
);

CREATE INDEX IF NOT EXISTS ix_gbiz_proc_houjin_date
    ON gbiz_procurement(houjin_bangou, contract_date DESC);

CREATE INDEX IF NOT EXISTS ix_gbiz_proc_agency_date
    ON gbiz_procurement(agency, contract_date DESC);

-- ---------------------------------------------------------------------------
-- NO-OP terminator — observable, idempotent re-run signal.
-- ---------------------------------------------------------------------------
SELECT 'wave24_164_gbiz_v2_mirror_tables applied' AS status;
