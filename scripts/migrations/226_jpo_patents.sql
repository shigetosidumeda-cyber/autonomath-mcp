-- target_db: autonomath
-- migration: 226_jpo_patents
-- generated_at: 2026-05-12
-- author: Wave 31 Axis 1b (jpcite_2026_05_12_axis1bc_jpo_edinet)
-- idempotent: every CREATE uses IF NOT EXISTS
--
-- Purpose
-- -------
-- Land two domain tables on `autonomath.db` for JPO 特許/実用新案 ingest:
--
--   * `am_jpo_patents`         — 特許 (公開公報 + 登録公報) one row per 出願番号
--   * `am_jpo_utility_models`  — 実用新案 (登録公報) one row per 出願番号
--
-- Both surface the bibliographic envelope (出願番号 / 登録番号 / 標題 /
-- 出願人名 / 出願人 法人番号 / IPC分類 / 出願日 / 登録日 / 状態 / 公報全文URL)
-- and join into the existing `houjin_master` (mig 014 family) via
-- `applicant_houjin_bangou`.
--
-- One 法人 = N 特許 mapping is the typical case (大企業数千件, 中小数件).
-- Foreign 出願人 (法人番号 未付与) は applicant_houjin_bangou=NULL で
-- 受け付け、bibliographic-only row として残す。
--
-- Source
-- ------
-- One-time + daily diff fetch from J-PlatPat (https://www.j-platpat.inpit.go.jp/)
-- 公開公報 / 登録公報 daily release pages — bulk download index (or
-- sitemap-based incremental). NO aggregator (Patent-i / Patent Result /
-- Astamuse 等は banned per memory feedback_no_fake_data). 出典 column
-- `source_url` は J-PlatPat detail page URL のみ保存。
--
-- LLM call count: 0. ETL は lxml + sqlite3 + httpx 純正のみ。
--
-- Bibliographic field semantics
-- -----------------------------
-- application_no            出願番号 (e.g. "2024-123456" / "PCT/JP2024/000123").
--                           PRIMARY KEY = application_no。一意。
-- registration_no           登録番号 ("特許XXXXXXX") / 実用新案登録番号 ("実XXXXXXX").
--                           公開段階では NULL、登録後 fill in。
-- title                     発明・考案 の 標題 (日本語、最大 1024 chars)。
-- body                      要約 + 請求項 + 詳細 の 抜粋 (~10KB 上限、本文は
--                           `full_text_url` 経由 J-PlatPat に流すことで R2 へは
--                           pushしない — 公報 PDF は J-PlatPat hosting に依存)。
-- applicant_name            出願人名 (筆頭出願人。複数出願人は最初の 1 件のみ。
--                           full applicant list は `applicants_json` に保存)。
-- applicant_houjin_bangou   13桁 法人番号。foreign / 個人 出願人は NULL。
-- ipc_classification        IPC分類 (e.g. "G06F 17/30, H04L 67/02")。
--                           複数分類は ", " で連結した自由 text。
-- application_date          出願日 (YYYY-MM-DD)。
-- registration_date         登録日 (YYYY-MM-DD)。公開段階は NULL。
-- status                    'published' | 'registered' | 'rejected' | 'withdrawn' |
--                           'expired' | 'abandoned' | 'unknown'。
-- source_url                J-PlatPat detail page URL (一次資料 link)。
-- applicants_json           複数出願人を JSON array で全件 (筆頭含む)。
-- ipc_codes_json            IPC 主分類 + 副分類を JSON array で正規化保存。
-- content_hash              SHA-256 hex (lowercase, 64 chars) of canonical body
--                           — content drift 検出用。
-- ingested_at               ISO 8601 (UTC, milliseconds)。
--
-- Idempotency
-- -----------
-- INSERT OR REPLACE on (application_no) drives upsert. status / registration_no /
-- registration_date が 公開→登録 transition で更新される想定。
-- ETL は content_hash 一致時は UPDATE skip (no-op)。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_jpo_patents (
    application_no            TEXT NOT NULL PRIMARY KEY,
    registration_no           TEXT,
    title                     TEXT NOT NULL CHECK (length(title) <= 1024),
    body                      TEXT NOT NULL DEFAULT '' CHECK (length(body) <= 10240),
    applicant_name            TEXT NOT NULL DEFAULT '' CHECK (length(applicant_name) <= 512),
    applicant_houjin_bangou   TEXT CHECK (
                                  applicant_houjin_bangou IS NULL OR (
                                      length(applicant_houjin_bangou) = 13 AND
                                      applicant_houjin_bangou NOT GLOB '*[^0-9]*'
                                  )
                              ),
    ipc_classification        TEXT NOT NULL DEFAULT '',
    application_date          TEXT NOT NULL CHECK (
                                  application_date LIKE '____-__-__' AND
                                  length(application_date) = 10
                              ),
    registration_date         TEXT CHECK (
                                  registration_date IS NULL OR (
                                      registration_date LIKE '____-__-__' AND
                                      length(registration_date) = 10
                                  )
                              ),
    status                    TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN (
                                  'published', 'registered', 'rejected',
                                  'withdrawn', 'expired', 'abandoned', 'unknown'
                              )),
    source_url                TEXT NOT NULL CHECK (length(source_url) <= 2048),
    applicants_json           TEXT NOT NULL DEFAULT '[]',
    ipc_codes_json            TEXT NOT NULL DEFAULT '[]',
    content_hash              TEXT NOT NULL CHECK (length(content_hash) = 64),
    ingested_at               TEXT NOT NULL
                              DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_jpo_patents_houjin_date
    ON am_jpo_patents (applicant_houjin_bangou, application_date DESC)
    WHERE applicant_houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jpo_patents_registration_no
    ON am_jpo_patents (registration_no)
    WHERE registration_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jpo_patents_application_date
    ON am_jpo_patents (application_date DESC);

CREATE INDEX IF NOT EXISTS idx_jpo_patents_status
    ON am_jpo_patents (status);


CREATE TABLE IF NOT EXISTS am_jpo_utility_models (
    application_no            TEXT NOT NULL PRIMARY KEY,
    registration_no           TEXT,
    title                     TEXT NOT NULL CHECK (length(title) <= 1024),
    body                      TEXT NOT NULL DEFAULT '' CHECK (length(body) <= 10240),
    applicant_name            TEXT NOT NULL DEFAULT '' CHECK (length(applicant_name) <= 512),
    applicant_houjin_bangou   TEXT CHECK (
                                  applicant_houjin_bangou IS NULL OR (
                                      length(applicant_houjin_bangou) = 13 AND
                                      applicant_houjin_bangou NOT GLOB '*[^0-9]*'
                                  )
                              ),
    ipc_classification        TEXT NOT NULL DEFAULT '',
    application_date          TEXT NOT NULL CHECK (
                                  application_date LIKE '____-__-__' AND
                                  length(application_date) = 10
                              ),
    registration_date         TEXT CHECK (
                                  registration_date IS NULL OR (
                                      registration_date LIKE '____-__-__' AND
                                      length(registration_date) = 10
                                  )
                              ),
    status                    TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN (
                                  'published', 'registered', 'rejected',
                                  'withdrawn', 'expired', 'abandoned', 'unknown'
                              )),
    source_url                TEXT NOT NULL CHECK (length(source_url) <= 2048),
    applicants_json           TEXT NOT NULL DEFAULT '[]',
    ipc_codes_json            TEXT NOT NULL DEFAULT '[]',
    content_hash              TEXT NOT NULL CHECK (length(content_hash) = 64),
    ingested_at               TEXT NOT NULL
                              DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_jpo_utility_models_houjin_date
    ON am_jpo_utility_models (applicant_houjin_bangou, application_date DESC)
    WHERE applicant_houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jpo_utility_models_registration_no
    ON am_jpo_utility_models (registration_no)
    WHERE registration_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jpo_utility_models_application_date
    ON am_jpo_utility_models (application_date DESC);


-- Resolved view — only rows where applicant_houjin_bangou bridged a
-- houjin record. Useful for "show company X's patents" surface where
-- NULL applicant_houjin_bangou is noise (foreign / 個人 出願人).
CREATE VIEW IF NOT EXISTS v_jpo_patents_resolved AS
SELECT application_no, registration_no, title, applicant_name,
       applicant_houjin_bangou, ipc_classification, application_date,
       registration_date, status, source_url, ingested_at
  FROM am_jpo_patents
 WHERE applicant_houjin_bangou IS NOT NULL;

CREATE VIEW IF NOT EXISTS v_jpo_utility_models_resolved AS
SELECT application_no, registration_no, title, applicant_name,
       applicant_houjin_bangou, ipc_classification, application_date,
       registration_date, status, source_url, ingested_at
  FROM am_jpo_utility_models
 WHERE applicant_houjin_bangou IS NOT NULL;
