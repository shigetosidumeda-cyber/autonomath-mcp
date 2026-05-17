-- target_db: autonomath
-- migration: wave24_216_am_pdf_watch_log
-- generated_at: 2026-05-17
-- author: CC4 — Real-time PDF detection + auto Textract + KG extract pipeline
-- idempotent: every CREATE uses IF NOT EXISTS; pure DDL, no DML.
--
-- Purpose
-- -------
-- Closed-loop ledger for the CC4 sustained-moat pipeline:
--
--   1. scripts/cron/pdf_watch_detect_2026_05_17.py polls 47-prefecture +
--      6-省庁 PDF watch sources hourly. For each new (source_url,
--      content_hash) pair it inserts a row with textract_status='pending'.
--   2. infra/aws/lambda/pdf_watch_textract_submit.py drains the SQS
--      queue, calls Textract StartDocumentAnalysis, flips
--      textract_status='submitted' and records textract_job_id.
--   3. Textract completion SNS triggers pdf_watch_textract_collect.py
--      which writes the OCR result to S3 and flips textract_status to
--      'completed' (or 'failed') + records s3_result_key.
--   4. pdf_watch_kg_extract.py drains the 'completed' rows, runs
--      spaCy ja_core_news_lg NER + relation extraction, writes
--      am_entity_facts / am_relation, and flips kg_extract_status to
--      'completed' + sets ingested_at.
--
-- Idempotency contract
-- --------------------
--   * UNIQUE (source_url, content_hash) — re-detection of the same PDF
--     bytes is a no-op (cron checks before insert; DB rejects dup as
--     defence-in-depth).
--   * All indexes are CREATE INDEX IF NOT EXISTS.
--   * Status enum columns are CHECK-constrained; downstream workers
--     advance via UPDATE WHERE current_status = expected_status (no
--     missed-update races).
--
-- LLM call: 0. Pure SQLite DDL + spaCy NER (no Anthropic / OpenAI).
--
-- License posture
-- ---------------
-- All sources are public-sector primary-source PDFs (NTA, FSA, MHLW,
-- METI, MLIT, MOJ, 47 prefectures, e-Gov 法令データ). gov_standard
-- per the JP government open-data policy. Aggregator ban: no third-party
-- re-publish, robots.txt strictly observed by the cron (1 req / 3 sec
-- per host floor).
--
-- Field semantics
-- ---------------
-- watch_id              INTEGER PK AUTOINCREMENT
-- source_kind           TEXT — 'nta' / 'fsa' / 'mhlw' / 'meti' / 'mlit' /
--                              'moj' / 'pref_<JIS2>' / 'egov_law'
-- source_url            TEXT — absolute https URL of the PDF
-- content_hash          TEXT — sha256 hex of the PDF bytes (or the
--                              landing-page HTML when source is a sitemap
--                              before the PDF link is finalised).
-- detected_at           TEXT — ISO 8601 UTC, first observation.
-- textract_status       TEXT — 'pending' / 'submitted' / 'completed' /
--                              'failed' / 'skipped'
-- textract_job_id       TEXT — Textract JobId once submitted (nullable).
-- s3_input_key          TEXT — s3:// key under the staging bucket.
-- s3_result_key         TEXT — s3:// key under the result bucket.
-- kg_extract_status     TEXT — 'pending' / 'running' / 'completed' /
--                              'failed' / 'skipped'
-- kg_entity_count       INT  — number of am_entity_facts rows produced.
-- kg_relation_count     INT  — number of am_relation rows produced.
-- ingested_at           TEXT — ISO 8601 UTC, when KG ingest completed.
-- last_error            TEXT — short human-readable error (truncated 512c).
-- updated_at            TEXT — ISO 8601 UTC, last status flip.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_pdf_watch_log — closed-loop ledger for PDF → Textract → KG pipeline
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_pdf_watch_log (
    watch_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind        TEXT NOT NULL
                        CHECK (source_kind IN (
                          'nta',
                          'fsa',
                          'mhlw',
                          'meti',
                          'mlit',
                          'moj',
                          'pref_hokkaido',
                          'pref_aomori',
                          'pref_iwate',
                          'pref_miyagi',
                          'pref_akita',
                          'pref_yamagata',
                          'pref_fukushima',
                          'pref_ibaraki',
                          'pref_tochigi',
                          'pref_gunma',
                          'pref_saitama',
                          'pref_chiba',
                          'pref_tokyo',
                          'pref_kanagawa',
                          'pref_niigata',
                          'pref_toyama',
                          'pref_ishikawa',
                          'pref_fukui',
                          'pref_yamanashi',
                          'pref_nagano',
                          'pref_gifu',
                          'pref_shizuoka',
                          'pref_aichi',
                          'pref_mie',
                          'pref_shiga',
                          'pref_kyoto',
                          'pref_osaka',
                          'pref_hyogo',
                          'pref_nara',
                          'pref_wakayama',
                          'pref_tottori',
                          'pref_shimane',
                          'pref_okayama',
                          'pref_hiroshima',
                          'pref_yamaguchi',
                          'pref_tokushima',
                          'pref_kagawa',
                          'pref_ehime',
                          'pref_kochi',
                          'pref_fukuoka',
                          'pref_saga',
                          'pref_nagasaki',
                          'pref_kumamoto',
                          'pref_oita',
                          'pref_miyazaki',
                          'pref_kagoshima',
                          'pref_okinawa',
                          'egov_law'
                        )),
    source_url         TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    detected_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    textract_status    TEXT NOT NULL DEFAULT 'pending'
                        CHECK (textract_status IN (
                          'pending', 'submitted', 'completed', 'failed', 'skipped'
                        )),
    textract_job_id    TEXT,
    s3_input_key       TEXT,
    s3_result_key      TEXT,
    kg_extract_status  TEXT NOT NULL DEFAULT 'pending'
                        CHECK (kg_extract_status IN (
                          'pending', 'running', 'completed', 'failed', 'skipped'
                        )),
    kg_entity_count    INTEGER NOT NULL DEFAULT 0,
    kg_relation_count  INTEGER NOT NULL DEFAULT 0,
    ingested_at        TEXT,
    last_error         TEXT,
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (source_url, content_hash)
);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_source_kind
    ON am_pdf_watch_log(source_kind, detected_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_textract_status
    ON am_pdf_watch_log(textract_status, detected_at);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_kg_status
    ON am_pdf_watch_log(kg_extract_status, detected_at);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_detected_at
    ON am_pdf_watch_log(detected_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_content_hash
    ON am_pdf_watch_log(content_hash);

CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_textract_job_id
    ON am_pdf_watch_log(textract_job_id)
    WHERE textract_job_id IS NOT NULL;

-- Convenience view: per-source funnel for operator dashboards.
CREATE VIEW IF NOT EXISTS v_am_pdf_watch_funnel AS
    SELECT
        source_kind,
        COUNT(*)                                            AS detected_total,
        SUM(textract_status = 'completed')                  AS textract_completed,
        SUM(textract_status = 'failed')                     AS textract_failed,
        SUM(kg_extract_status = 'completed')                AS kg_completed,
        SUM(kg_extract_status = 'failed')                   AS kg_failed,
        MIN(detected_at)                                    AS earliest_detected,
        MAX(detected_at)                                    AS latest_detected,
        MAX(ingested_at)                                    AS latest_ingested
      FROM am_pdf_watch_log
     GROUP BY source_kind;
