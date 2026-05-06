-- target_db: autonomath
-- migration wave24_175_public_funding_ledger
--
-- Purpose
-- -------
-- Unified ledger for 採択・補助金・融資・保証・制度候補 keyed on the
-- recipient houjin_bangou. Every row represents either a confirmed
-- funding event (採択 result, loan disbursement, guarantee approval) or
-- a candidate program eligibility hit. Rows are partitioned across
-- `funding_kind` (one row per (kind, recipient, fiscal_year, agency,
-- program_id) tuple), with optional `amount_yen` when the source
-- discloses it. Without this layer, the `application_strategy_pack_v2`
-- (SYNTHESIS §8.13) cannot answer "what has this 法人 received before"
-- and the "sales dossier" artifact cannot rank prospects by aggregate
-- funding history.
--
-- Backlog row: SYNTHESIS_2026_05_06.md §8.14 row 7
-- (`public_funding_ledger`).
--
-- Source families covered (W1_A* / 02_A_SOURCE_PROFILE.jsonl):
--   * `gbizinfo_subsidy_v2`                    (P0, 補助金交付決定)
--   * `jgrants_subsidy_api`                    (P0, jGrants 採択発表)
--   * `monodukuri_hojo_saitaku_dataportal`     (P0, ものづくり補助金 採択)
--   * `it_hojo_saitaku_announcement`           (P0, IT導入補助金 採択)
--   * `prefecture_47_subsidy_program_index`    (P0, 47都道府県 補助金索引)
--   * `prefecture_47_credit_guarantee_loan_program` (P0, 47保証協会 制度)
--   * `designated_city_20_subsidy_program_index`     (P1, 政令市20)
--   * `chukaku_city_47_subsidy_program_index`        (P1, 中核市47)
--   * `jfc_loan_product_master`                (P0, 公庫 商品)
--   * `jfc_acceptance_statistics_regional`     (P0, 公庫 受付統計)
--   * `shinyo_hosho_kyokai_51_seido_listing`   (P0, 信用保証協会 51制度)
--   * `shoko_chukin_seido_listing`             (P1, 商工中金)
--   * `municipality_seido_yuushi_to_shinyo_hosho_link` (P1, 制度融資)
--   * `sbir_csti_adoption_index`               (P1, SBIR 採択)
--
-- Relationship to existing tables
-- -------------------------------
--   * `programs` (jpintel.db, 11,684 searchable) is the eligibility-search
--     master. This ledger is the recipient-side history pair.
--   * `case_studies` / `jpi_adoption_records` (autonomath, 201,845 rows
--     post Phase A) is the采択事例 corpus; this ledger projects it onto
--     a normalized (kind, year, amount) shape and joins with loan/保証
--     records that case_studies does not cover.
--   * `loan_programs` (jpintel.db, 108 rows) is the loan product catalog;
--     this ledger captures actual loan EVENTS (with recipient).
--   * `entity_resolution_bridge_v2` (mig 168) provides the houjin_bangou
--     resolution; this ledger respects the same 0.95 confidence floor
--     for sensitive surfaces.
--   * `source_receipt_ledger` (DF-02 / mig 171) — every ledger row carries
--     `receipt_id` FK so the audit chain is one JOIN away.
--
-- target_db = autonomath
-- ----------------------
-- First-line marker mandatory. NEVER re-enable Fly release_command.
--
-- Idempotency contract
-- --------------------
-- All CREATE statements use IF NOT EXISTS. No DML.
--
-- ¥3/req billing posture
-- ----------------------
-- Ledger reads are ¥3/req under /v1/funding/recipients/{houjin}/history
-- and the MCP equivalent. NO LLM call inside the read path.
--
-- Schema notes
-- ------------
--   * `ledger_id` INTEGER PRIMARY KEY AUTOINCREMENT — surrogate.
--   * `funding_kind` TEXT NOT NULL — enum-as-text:
--       'subsidy_adoption'      | 補助金 採択（確定）
--       'subsidy_disbursement'  | 補助金 交付決定（金額確定）
--       'loan_disbursement'     | 融資 実行
--       'loan_acceptance'       | 融資 受付（実行前）
--       'guarantee_approval'    | 信用保証 承諾
--       'sbir_award'            | SBIR 採択
--       'tax_incentive_use'     | 税制 適用（KPI 統計）
--       'candidate_program'     | 制度候補（未採択。eligibility hit）
--       'other'                 | 上記以外
--   * `recipient_houjin_bangou` TEXT — 13-digit; NULL when the source row
--     is anonymized or candidate-only (制度候補 = no recipient yet).
--   * `recipient_name`          TEXT — display string; never NULL.
--   * `recipient_match_confidence` REAL — same scale as bridge_v2.
--   * `fiscal_year` INTEGER NOT NULL — 4-digit Japanese fiscal year (e.g.
--     2025 means 令和7年度 / 2025年4月1日〜2026年3月31日). The fiscal_year
--     value is the BUDGETARY year, not the announcement calendar year —
--     this matters for late-year announcements that fall in 翌年4月.
--   * `amount_yen` INTEGER — actual amount when known; NULL when not
--     disclosed (very common for prefecture 採択 announcements).
--   * `amount_quality` TEXT — 'verified' / 'estimated' / 'undisclosed';
--     gates whether the row can appear in the verified surface artifact.
--   * `agency` TEXT NOT NULL — issuing agency / 主管庁; verbatim source
--     string (e.g. '中小企業庁', '東京都', '日本政策金融公庫').
--   * `agency_level` TEXT NOT NULL — enum: 'national' / 'prefecture' /
--     'designated_city' / 'core_city' / 'municipality' / 'public_corp'.
--   * `program_id` TEXT — stable program identifier (joins to
--     `programs.program_id` when applicable; opaque source-side ID
--     otherwise).
--   * `program_name`             TEXT NOT NULL — display string.
--   * `prefecture` TEXT — JIS X 0401 2-digit; NULL for national programs.
--   * `industry_jsic` TEXT — JSIC major (A..T); NULL when not classifiable.
--   * `status` TEXT NOT NULL — enum: 'adopted' / 'rejected' /
--     'pending' / 'withdrawn' / 'candidate'. NEVER NULL — a row with no
--     status is meaningless.
--   * `announced_at` TEXT — ISO-8601 date of public announcement.
--   * `disbursed_at` TEXT — ISO-8601 date of actual disbursement (NULL
--     until disbursement; for candidate rows always NULL).
--   * `source_url` TEXT NOT NULL.
--   * `source_id` TEXT NOT NULL — allowlist enforced by CHECK.
--   * `fetched_at` TEXT NOT NULL.
--   * `content_hash` TEXT NOT NULL.
--   * `license` TEXT NOT NULL — verbatim license tag.
--   * `redistribute_ok` INTEGER NOT NULL DEFAULT 0.
--   * `receipt_id` INTEGER — FK to source_receipt_ledger (DF-02).
--   * `dispute_flag` / `dispute_reason` — for corrected/disputed rows.
--   * `notes` TEXT — operator-only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS public_funding_ledger (
    ledger_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    funding_kind                TEXT NOT NULL,
    recipient_houjin_bangou     TEXT,
    recipient_name              TEXT NOT NULL,
    recipient_match_confidence  REAL,
    fiscal_year                 INTEGER NOT NULL,
    amount_yen                  INTEGER,
    amount_quality              TEXT NOT NULL DEFAULT 'undisclosed',
    agency                      TEXT NOT NULL,
    agency_level                TEXT NOT NULL,
    program_id                  TEXT,
    program_name                TEXT NOT NULL,
    prefecture                  TEXT,
    industry_jsic               TEXT,
    status                      TEXT NOT NULL,
    announced_at                TEXT,
    disbursed_at                TEXT,
    source_url                  TEXT NOT NULL,
    source_id                   TEXT NOT NULL,
    fetched_at                  TEXT NOT NULL,
    content_hash                TEXT NOT NULL,
    license                     TEXT NOT NULL,
    redistribute_ok             INTEGER NOT NULL DEFAULT 0 CHECK (redistribute_ok IN (0, 1)),
    receipt_id                  INTEGER,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    dispute_flag                INTEGER NOT NULL DEFAULT 0 CHECK (dispute_flag IN (0, 1)),
    dispute_reason              TEXT,
    notes                       TEXT,

    -- funding_kind enum.
    CHECK (funding_kind IN (
        'subsidy_adoption',
        'subsidy_disbursement',
        'loan_disbursement',
        'loan_acceptance',
        'guarantee_approval',
        'sbir_award',
        'tax_incentive_use',
        'candidate_program',
        'other'
    )),
    -- houjin format.
    CHECK (
        recipient_houjin_bangou IS NULL
        OR (length(recipient_houjin_bangou) = 13
            AND recipient_houjin_bangou GLOB '[0-9]*'
            AND recipient_houjin_bangou NOT GLOB '*[^0-9]*')
    ),
    -- match_confidence range.
    CHECK (
        recipient_match_confidence IS NULL
        OR (recipient_match_confidence >= 0.0
            AND recipient_match_confidence <= 1.0)
    ),
    -- fiscal_year sanity (1989..2100 covers 平成元..future buffer).
    CHECK (fiscal_year BETWEEN 1989 AND 2100),
    -- amount_yen non-negative when present.
    CHECK (amount_yen IS NULL OR amount_yen >= 0),
    -- amount_quality enum.
    CHECK (amount_quality IN ('verified', 'estimated', 'undisclosed')),
    -- amount_quality coherence: 'verified' requires amount_yen NOT NULL.
    CHECK (
        amount_quality <> 'verified'
        OR amount_yen IS NOT NULL
    ),
    -- agency_level enum.
    CHECK (agency_level IN (
        'national', 'prefecture', 'designated_city',
        'core_city', 'municipality', 'public_corp'
    )),
    -- prefecture format.
    CHECK (
        prefecture IS NULL
        OR (length(prefecture) = 2
            AND prefecture GLOB '[0-9]*'
            AND prefecture NOT GLOB '*[^0-9]*')
    ),
    -- industry_jsic format.
    CHECK (
        industry_jsic IS NULL
        OR industry_jsic GLOB '[A-T]'
    ),
    -- status enum.
    CHECK (status IN (
        'adopted', 'rejected', 'pending', 'withdrawn', 'candidate'
    )),
    -- candidate_program rows MUST have status='candidate'; conversely
    -- 'candidate' status is allowed only for candidate_program kind.
    CHECK (
        (funding_kind = 'candidate_program' AND status = 'candidate')
        OR (funding_kind <> 'candidate_program' AND status <> 'candidate')
    ),
    -- source_id allowlist.
    CHECK (source_id IN (
        'gbizinfo_subsidy_v2',
        'jgrants_subsidy_api',
        'monodukuri_hojo_saitaku_dataportal',
        'it_hojo_saitaku_announcement',
        'prefecture_47_subsidy_program_index',
        'prefecture_47_credit_guarantee_loan_program',
        'designated_city_20_subsidy_program_index',
        'chukaku_city_47_subsidy_program_index',
        'jfc_loan_product_master',
        'jfc_acceptance_statistics_regional',
        'shinyo_hosho_kyokai_51_seido_listing',
        'shoko_chukin_seido_listing',
        'municipality_seido_yuushi_to_shinyo_hosho_link',
        'sbir_csti_adoption_index',
        'manual_human_review'
    ))
);

-- Index 1: recipient timeline — DOMINANT query shape from sales dossier
-- and application_strategy artifacts.
CREATE INDEX IF NOT EXISTS idx_public_funding_recipient_year
    ON public_funding_ledger (recipient_houjin_bangou, fiscal_year DESC)
    WHERE recipient_houjin_bangou IS NOT NULL;

-- Index 2: kind × fiscal_year — for cohort statistics.
CREATE INDEX IF NOT EXISTS idx_public_funding_kind_year
    ON public_funding_ledger (funding_kind, fiscal_year DESC);

-- Index 3: agency timeline — "all 中小企業庁 採択 in 2025年度".
CREATE INDEX IF NOT EXISTS idx_public_funding_agency
    ON public_funding_ledger (agency, fiscal_year DESC);

-- Index 4: prefecture × industry rollup.
CREATE INDEX IF NOT EXISTS idx_public_funding_pref_industry
    ON public_funding_ledger (prefecture, industry_jsic, fiscal_year DESC);

-- Index 5: receipt audit chain.
CREATE INDEX IF NOT EXISTS idx_public_funding_receipt
    ON public_funding_ledger (receipt_id)
    WHERE receipt_id IS NOT NULL;

-- Index 6: program_id join axis to programs.program_id.
CREATE INDEX IF NOT EXISTS idx_public_funding_program
    ON public_funding_ledger (program_id, fiscal_year DESC)
    WHERE program_id IS NOT NULL;

-- Public-surface view: enforces redistribute_ok + dispute_flag=0 +
-- (when houjin_bangou is bound) confidence >= 0.95. The verified surface
-- additionally requires amount_quality='verified' — see the public
-- artifact's `quality_tier='verified'` filter (SYNTHESIS §8.16 P1).
CREATE VIEW IF NOT EXISTS v_public_funding_ledger_public AS
SELECT
    ledger_id,
    funding_kind,
    recipient_houjin_bangou,
    recipient_name,
    fiscal_year,
    amount_yen,
    amount_quality,
    agency,
    agency_level,
    program_id,
    program_name,
    prefecture,
    industry_jsic,
    status,
    announced_at,
    disbursed_at,
    source_url,
    source_id,
    fetched_at,
    content_hash,
    license
FROM public_funding_ledger
WHERE redistribute_ok = 1
  AND dispute_flag = 0
  AND (
      recipient_houjin_bangou IS NULL
      OR recipient_match_confidence >= 0.95
  );
