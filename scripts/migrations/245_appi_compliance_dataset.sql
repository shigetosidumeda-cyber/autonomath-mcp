-- target_db: autonomath
-- migration: 245_appi_compliance_dataset
-- generated_at: 2026-05-12
-- author: Wave 41 Axis 7a — 個情法 (令和5年改正) compliance dataset
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Materialize the APPI (個人情報の保護に関する法律, 令和5年改正) compliance
-- state for every 法人 we have a houjin_bangou for, sourced from:
--
--   * PPC (個人情報保護委員会) 公開リスト — operator notifications,
--     guideline-violation administrative orders (§148 命令), and §26
--     漏えい等 報告。https://www.ppc.go.jp/ 公開資料.
--   * EDINET 開示情報 — 有報 + 内部統制報告書 で開示される個情法対応状況
--     (data governance / 第三者監査 / 認証 取得 状況).
--   * 一般財団法人日本情報経済社会推進協会 (JIPDEC) PrivacyMark / ISMS
--     公開リスト — § 26 / §27 個人データ取扱 体制 認証状態.
--
-- Why precompute (not a runtime web fetch)
-- ----------------------------------------
-- * PPC public list is HTML — runtime fetch + parse blows the FastMCP 1s
--   envelope and is rate-limited at source.
-- * Memory `feedback_no_quick_check_on_huge_sqlite` forbids full-scan ops
--   on the 9.7GB autonomath.db at runtime — precompute lands once
--   per ingest cycle.
-- * §44-3 (越境移転) 関連 通知 + §26 (漏えい等 報告) 関連 状態 は sensitive
--   surface — handler-side disclaimer fence required regardless.
--
-- Schema notes
-- ------------
-- * organization_id  — autoincrement PRIMARY KEY.
-- * houjin_bangou    — 13-digit 法人番号. May be NULL when source row is a
--                      非法人 任意団体 (operator notice still picks up
--                      these via name match).
-- * organization_name — first-party canonical name from PPC / EDINET /
--                       JIPDEC. We never normalize the source-given name.
-- * compliance_status — closed enum (CHECK below):
--     - 'registered'      § 26/§27 体制 登録済 (PrivacyMark / ISMS-P)
--     - 'pending'          審査中 / 通知段階
--     - 'non-compliant'    §148 命令 / §26 漏えい等 報告 履歴
--     - 'exempt'           §16-2 対象外 (個人取扱 100 人以下 等)
--     - 'unknown'          一次資料に該当条文記載なし
-- * pic_certification — 個人情報取扱者 認証 (boolean: 0/1).
-- * last_audit_date    — yyyy-mm-dd, NULL until first ingest.
-- * source_url         — 一次資料 URL (PPC / EDINET / JIPDEC).

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_appi_compliance (
    organization_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou       TEXT,
    organization_name   TEXT NOT NULL,
    compliance_status   TEXT NOT NULL,
    pic_certification   INTEGER NOT NULL DEFAULT 0 CHECK (pic_certification IN (0,1)),
    last_audit_date     TEXT,
    source_url          TEXT,
    source_kind         TEXT,
    notes               TEXT,
    refreshed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_appi_compliance_status CHECK (compliance_status IN (
        'registered', 'pending', 'non-compliant', 'exempt', 'unknown'
    )),
    CONSTRAINT ck_appi_compliance_houjin_len CHECK (
        houjin_bangou IS NULL OR length(houjin_bangou) = 13
    ),
    CONSTRAINT ck_appi_compliance_source_kind CHECK (
        source_kind IS NULL OR source_kind IN ('ppc','edinet','jipdec','other')
    )
);

-- Hot path: REST endpoint pivots on houjin_bangou.
CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_houjin
    ON am_appi_compliance(houjin_bangou)
    WHERE houjin_bangou IS NOT NULL;

-- Compliance state filter (e.g. "show me every non-compliant").
CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_status
    ON am_appi_compliance(compliance_status, refreshed_at DESC);

-- Refresh staleness sweep.
CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_refreshed
    ON am_appi_compliance(refreshed_at);

-- Unique (houjin_bangou, source_kind) — same houjin may carry BOTH PPC
-- and JIPDEC rows simultaneously; ingest dedupes per source.
CREATE UNIQUE INDEX IF NOT EXISTS ux_am_appi_compliance_houjin_source
    ON am_appi_compliance(
        COALESCE(houjin_bangou, '_anonymous'),
        COALESCE(source_kind, 'other'),
        organization_name
    );

-- Operator-side ingest log — one row per ingest invocation, append-only.
CREATE TABLE IF NOT EXISTS am_appi_compliance_ingest_log (
    ingest_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    rows_seen       INTEGER NOT NULL DEFAULT 0,
    rows_upserted   INTEGER NOT NULL DEFAULT 0,
    rows_skipped    INTEGER NOT NULL DEFAULT 0,
    source_kind     TEXT,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_ingest_log_started
    ON am_appi_compliance_ingest_log(started_at DESC);

-- Operator dashboard view: counts per compliance_status.
DROP VIEW IF EXISTS v_appi_compliance_summary;
CREATE VIEW v_appi_compliance_summary AS
SELECT
    compliance_status,
    COUNT(*) AS organizations,
    SUM(CASE WHEN pic_certification = 1 THEN 1 ELSE 0 END) AS pic_certified,
    MAX(refreshed_at) AS latest_refresh
FROM am_appi_compliance
GROUP BY compliance_status
ORDER BY organizations DESC;

COMMIT;
