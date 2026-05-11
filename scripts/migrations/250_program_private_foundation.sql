-- target_db: autonomath
-- migration: 250_program_private_foundation
-- generated_at: 2026-05-12
-- author: Wave 43.1.3 — 民間助成財団 2,000+ 助成プログラム コーポラ
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Materialize the 民間 (公益財団 / 一般財団 / NPO / 業界団体) 助成 program
-- corpus on top of the existing 11,601 公的 programs cohort. The corpus
-- broadens the "実在制度" base from 公的 (省庁 + 自治体 + 政策金融公庫) to
-- include the private grant ecosystem — corporate foundations (e.g. トヨタ
-- 財団 / SOMPO 環境財団), academic foundations, and 業界団体 grants — so
-- agentic discovery via /v1/foundation/* yields a wider 制度 surface
-- without sacrificing 一次資料 discipline.
--
-- Source discipline (non-negotiable, memory `feedback_no_fake_data`)
-- ------------------------------------------------------------------
-- * 公益財団協会 (https://www.koeki-info.go.jp/) — 公益法人 information
--   site authoritative on 公益財団 listings.
-- * 各 公益財団 official sites — primary domain only, e.g.
--   - トヨタ財団 https://www.toyotafound.or.jp/
--   - サントリー文化財団 https://www.suntory.co.jp/sfnd/
--   - SOMPO 環境財団 https://www.sompo-ef.org/
--   - 大林財団 https://obayashifoundation.or.jp/
-- * NPO 法人 listings — 内閣府 NPO 認証 master list 公開資料 (only when
--   the NPO itself runs a 助成 program; not a generic NPO list).
-- * 業界団体 grants — primary 業界団体 site (経団連 / 商工会議所 / 同友会)
--   public grant pages only.
-- * Aggregator domains BANNED: 助成財団検索サイト, hojyokin-portal.com,
--   助成団体検索ナビ等. memory `project_jpcite_2026_05_07_state` data
--   hygiene + CLAUDE.md `Aggregators ... are banned` rule.
--
-- Schema notes
-- ------------
-- * foundation_id     — autoincrement PRIMARY KEY (internal).
-- * foundation_name   — 公益・一般財団・NPO・業界団体 canonical name (一次
--                       資料 から取得; we never normalize the name).
-- * foundation_type   — closed enum (CHECK below):
--     - '公益財団'   公益財団法人 (内閣府 認定済)
--     - '一般財団'   一般財団法人
--     - 'NPO'        特定非営利活動法人
--     - '業界団体'   業界団体 (経団連 / 商工会議所 / 同友会 / 業界別 協会)
-- * grant_program_name — 助成 program 名 (e.g. "研究助成", "国際交流助成").
-- * grant_amount_range — 助成金額 範囲 (e.g. "100万円〜500万円", "上限300万円").
--                        Free text; not normalized to ¥ integer because
--                        財団 published ranges are heterogeneous.
-- * grant_theme        — 助成テーマ (e.g. "環境", "国際交流", "研究", "福祉").
-- * donation_category  — 寄付金分類 (closed enum):
--     - 'specified_public_interest'  特定公益増進法人 ¥寄付金 (税優遇 大)
--     - 'public_interest'             公益法人 寄付金 (税優遇 中)
--     - 'general'                     一般 (税優遇 小 or なし)
--     - 'unknown'                     一次資料 該当条文記載なし
-- * application_period_json — JSON {open_date, close_date, cycle} — 通年 /
--                             随時 / 単発 等 を JSON で柔軟に表現.
-- * source_url           — 一次資料 URL (財団 公式 site).
-- * source_kind          — 'koeki_info' / 'official_site' / 'cabinet_npo' /
--                          'gyokai_dantai' / 'other'.
--
-- Why precompute (not a runtime web fetch)
-- ----------------------------------------
-- * 公益財団協会 + 各財団 公式 site は HTML — runtime fetch + parse blows
--   the FastMCP 1s envelope and is rate-limited at source.
-- * 助成 program publication cadence は財団ごとに ばらつき (年1回 / 通年 /
--   隔年) — 一次資料 walking は週次〜月次 batch ETL 適.
-- * memory `feedback_no_quick_check_on_huge_sqlite` 制約 — precompute lands
--   once per ingest cycle.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_program_private_foundation (
    foundation_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    foundation_name         TEXT NOT NULL,
    foundation_type         TEXT NOT NULL,
    grant_program_name      TEXT,
    grant_amount_range      TEXT,
    grant_theme             TEXT,
    donation_category       TEXT NOT NULL DEFAULT 'unknown',
    application_period_json TEXT,
    source_url              TEXT,
    source_kind             TEXT,
    notes                   TEXT,
    refreshed_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_foundation_type CHECK (foundation_type IN (
        '公益財団', '一般財団', 'NPO', '業界団体'
    )),
    CONSTRAINT ck_donation_category CHECK (donation_category IN (
        'specified_public_interest', 'public_interest', 'general', 'unknown'
    )),
    CONSTRAINT ck_foundation_source_kind CHECK (
        source_kind IS NULL OR source_kind IN (
            'koeki_info', 'official_site', 'cabinet_npo', 'gyokai_dantai', 'other'
        )
    )
);

-- Hot path: REST endpoint pivots on foundation_type + theme.
CREATE INDEX IF NOT EXISTS idx_am_foundation_type
    ON am_program_private_foundation(foundation_type, refreshed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_foundation_theme
    ON am_program_private_foundation(grant_theme)
    WHERE grant_theme IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_am_foundation_donation
    ON am_program_private_foundation(donation_category, foundation_type);

CREATE INDEX IF NOT EXISTS idx_am_foundation_refreshed
    ON am_program_private_foundation(refreshed_at);

-- Unique (foundation_name, grant_program_name) — one foundation may run
-- multiple grant programs (e.g. トヨタ財団 has 研究助成 + 国際助成 + 国内助成);
-- ingest dedupes per (foundation, program) tuple.
CREATE UNIQUE INDEX IF NOT EXISTS ux_am_foundation_program
    ON am_program_private_foundation(
        foundation_name,
        COALESCE(grant_program_name, '_unnamed')
    );

-- Operator-side ingest log — one row per ingest invocation, append-only.
CREATE TABLE IF NOT EXISTS am_program_private_foundation_ingest_log (
    ingest_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    rows_seen       INTEGER NOT NULL DEFAULT 0,
    rows_upserted   INTEGER NOT NULL DEFAULT 0,
    rows_skipped    INTEGER NOT NULL DEFAULT 0,
    source_kind     TEXT,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_foundation_ingest_log_started
    ON am_program_private_foundation_ingest_log(started_at DESC);

-- Operator dashboard view: foundation type x donation category density.
DROP VIEW IF EXISTS v_program_private_foundation_summary;
CREATE VIEW v_program_private_foundation_summary AS
SELECT
    foundation_type,
    donation_category,
    COUNT(*) AS program_count,
    COUNT(DISTINCT foundation_name) AS foundation_count,
    MAX(refreshed_at) AS latest_refresh
FROM am_program_private_foundation
GROUP BY foundation_type, donation_category
ORDER BY program_count DESC;

COMMIT;
