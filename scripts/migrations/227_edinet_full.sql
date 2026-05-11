-- target_db: autonomath
-- migration: 227_edinet_full
-- generated_at: 2026-05-12
-- author: Wave 31 Axis 1c (jpcite_2026_05_12_axis1bc_jpo_edinet)
-- idempotent: every CREATE uses IF NOT EXISTS
--
-- Purpose
-- -------
-- Extend the existing `edinet_filing_signal_layer` (mig wave24_176, signal-only,
-- bibliographic envelope) with a **full-text** companion table backed by R2
-- for the actual body extraction. The signal layer remains the audit + ID
-- bridge; this `_full` table carries the parsed body excerpt + a R2 URL for
-- the full text artifact.
--
-- Why a separate table (not ALTER on signal_layer)
-- ------------------------------------------------
--   1. signal_layer is per-document SHA-keyed and append-only on `content_hash`
--      drift; full-text rows can be re-emitted from a stable doc_id without
--      churning the signal layer.
--   2. Full-text rows are LARGE (5 KB excerpt + R2 URL per filing × ~4,000
--      listed + ~20,000 EDINET-filing companies × N filings/year). Keeping
--      them in a sibling table preserves the lean signal_layer index.
--   3. R2 hosts the full body. The signal_layer was designed pre-R2 and
--      does not carry R2 URLs.
--
-- Table semantics
-- ---------------
-- edinet_code          E-prefix (E12345). FK target = signal_layer.edinet_code.
-- security_code        5-digit + check digit (上場 only). NULL for 非上場.
-- submit_date          JST date (YYYY-MM-DD). EDINET 提出日.
-- doc_type             EDINET 様式コード (e.g. '120' = 有報, '140' = 四半期報告書,
--                      '160' = 半期報告書, '030' = 訂正有価証券報告書,
--                      '350' = 大量保有報告書, '040' = 公開買付届出書 etc.).
-- filer_houjin_bangou  13桁 法人番号。NULL until entity_resolution_bridge_v2
--                      resolves (foreign filers + 個人 = NULL).
-- file_pdf_url         EDINET 公衆縦覧 PDF download URL.
-- file_xbrl_url        EDINET XBRL download URL (ZIPforDocs/{doc_id}.zip).
-- body_text_excerpt    XBRL → plain text 変換 後 の 抜粋 (~5 KB cap)。
-- full_text_r2_url     R2 上 の full body 配信 URL (signed URL or public URL)。
-- doc_id               EDINET documentId (S100XXXX form). One row per doc_id.
--                      Optional UNIQUE — not PK because we want signal_id-style
--                      explicit PK for future composite hashing.
-- content_hash         SHA-256 hex (lowercase, 64 chars) of canonical body
--                      — content drift 検出用。
-- ingested_at          ISO 8601 (UTC, milliseconds).
--
-- Source
-- ------
-- EDINET API (https://disclosure2.edinet-fsa.go.jp/) — endpoint
-- /api/v2/documents.json (one-shot daily list) + /api/v2/documents/{doc_id}
-- (download by docId). 公式 API のみ、aggregator (有報読み / Strainer 等) 禁止。
--
-- LLM call count: 0. XBRL → plain text 変換 は lxml + sqlite3 のみ。
--
-- Idempotency
-- -----------
-- INSERT OR REPLACE on doc_id is the upsert key. content_hash 一致時 は
-- UPDATE skip (no-op)。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_edinet_filings (
    filing_id              TEXT NOT NULL PRIMARY KEY,
    doc_id                 TEXT NOT NULL UNIQUE,
    edinet_code            TEXT NOT NULL CHECK (
                               length(edinet_code) >= 6 AND
                               substr(edinet_code, 1, 1) = 'E'
                           ),
    security_code          TEXT CHECK (
                               security_code IS NULL OR length(security_code) = 5
                           ),
    submit_date            TEXT NOT NULL CHECK (
                               submit_date LIKE '____-__-__' AND
                               length(submit_date) = 10
                           ),
    doc_type               TEXT NOT NULL,
    filer_houjin_bangou    TEXT CHECK (
                               filer_houjin_bangou IS NULL OR (
                                   length(filer_houjin_bangou) = 13 AND
                                   filer_houjin_bangou NOT GLOB '*[^0-9]*'
                               )
                           ),
    file_pdf_url           TEXT CHECK (
                               file_pdf_url IS NULL OR length(file_pdf_url) <= 2048
                           ),
    file_xbrl_url          TEXT CHECK (
                               file_xbrl_url IS NULL OR length(file_xbrl_url) <= 2048
                           ),
    body_text_excerpt      TEXT NOT NULL DEFAULT '' CHECK (length(body_text_excerpt) <= 5120),
    full_text_r2_url       TEXT CHECK (
                               full_text_r2_url IS NULL OR length(full_text_r2_url) <= 2048
                           ),
    content_hash           TEXT NOT NULL CHECK (length(content_hash) = 64),
    ingested_at            TEXT NOT NULL
                           DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- "show me last 10 filings by 法人" — primary cohort surface.
CREATE INDEX IF NOT EXISTS idx_edinet_filings_houjin_date
    ON am_edinet_filings (filer_houjin_bangou, submit_date DESC)
    WHERE filer_houjin_bangou IS NOT NULL;

-- "what was filed since {date}" — daily digest fan-out cron.
CREATE INDEX IF NOT EXISTS idx_edinet_filings_submit_date
    ON am_edinet_filings (submit_date DESC);

-- "only 有報 + 大量保有" filter.
CREATE INDEX IF NOT EXISTS idx_edinet_filings_doc_type
    ON am_edinet_filings (doc_type);

-- "edinet_code timeline" join into wave24_176 signal_layer.
CREATE INDEX IF NOT EXISTS idx_edinet_filings_edinet_code
    ON am_edinet_filings (edinet_code, submit_date DESC);

-- "上場 only" filter (security_code IS NOT NULL).
CREATE INDEX IF NOT EXISTS idx_edinet_filings_security_code
    ON am_edinet_filings (security_code)
    WHERE security_code IS NOT NULL;


-- Resolved view — only rows where filer_houjin_bangou bridged a houjin record.
CREATE VIEW IF NOT EXISTS v_edinet_filings_full_resolved AS
SELECT filing_id, doc_id, edinet_code, security_code, submit_date,
       doc_type, filer_houjin_bangou, file_pdf_url, file_xbrl_url,
       body_text_excerpt, full_text_r2_url, content_hash, ingested_at
  FROM am_edinet_filings
 WHERE filer_houjin_bangou IS NOT NULL;

-- Pending bridge resolution view — daily cron re-runs UPDATE pass on these.
CREATE VIEW IF NOT EXISTS v_edinet_filings_full_unresolved AS
SELECT filing_id, doc_id, edinet_code, security_code, submit_date, doc_type
  FROM am_edinet_filings
 WHERE filer_houjin_bangou IS NULL;
