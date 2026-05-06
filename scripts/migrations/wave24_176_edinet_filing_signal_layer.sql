-- target_db: autonomath
-- migration: wave24_176_edinet_filing_signal_layer
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-05 (edinet_filing_signal_layer)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Normalize EDINET 提出書類 (有報・四半期・半期・大量保有・公開買付・特定証券情報・
-- 内部統制報告書・自己株式取得状況報告書 etc.) into a single signal-layer table.
-- The upstream `02_A_SOURCE_PROFILE.jsonl` row id `edinet_codelist_master`
-- (W1_A03) gives us the *bridge* (EDINET code ↔ houjin_bangou ↔ sec code) but
-- not the *filing event timeline* — that is what this layer is for.
--
-- Key design decisions
-- --------------------
-- 1. `houjin_bangou` is NULLABLE.
--    EDINET issues codes for individuals (3,213 個人組合 cases per
--    02_A_SOURCE_PROFILE.jsonl line 10) and for foreign filers without a
--    Japanese 法人番号. Forcing NOT NULL would drop ~2-3% of valid rows.
--    Instead, the resolve happens *post-insert* via the DF-01
--    `entity_resolution_bridge_v2` (`wave24_168`) edinet→houjin walk.
--    A periodic backfill job runs `UPDATE edinet_filing_signal_layer
--    SET houjin_bangou = (SELECT b.houjin_bangou FROM
--    entity_resolution_bridge_v2 b WHERE b.edinet_code = ...)` whenever
--    the bridge resolves a previously NULL link.
--
-- 2. `sec_code` is NULLABLE.
--    非上場 transition cases (delisted but still 報告義務 for ~1 year,
--    private 重要事業者 / 大量保有 ≥5% holders, ETF / REIT / J-REIT
--    administrators, 投信委託会社 etc.) have no securities code. EDINET
--    explicitly emits empty `sec_code` for those; we preserve the
--    distinction with NULL.
--
-- 3. `content_hash` is the 256-bit SHA-256 of the canonicalized XBRL
--    + attached PDFs concatenation, *not* the EDINET-supplied
--    `documentId`. This lets us detect silent overwrites (EDINET allows
--    再提出 / 訂正 within the same documentId on rare occasions — the
--    documentId stays stable but the content actually changes).
--
-- 4. `attached_files_count` includes inline XBRL + 公衆縦覧 PDFs +
--    監査報告書 attachments. EDINET typically yields 5-30 files per 有報.
--
-- Field semantics
-- ---------------
-- signal_id            PK, deterministic = sha1(doc_id || ':' || content_hash)
-- doc_id               EDINET documentId (S100XXXX form). UNIQUE.
-- edinet_code          E-prefix (E12345). FK target = entity_resolution_bridge_v2.
-- sec_code             5-digit + check digit (e.g. '13010'). NULL for 非上場.
-- houjin_bangou        13-digit string. NULL until DF-01 bridge resolves.
-- submission_date      JST date the filing was submitted (YYYY-MM-DD).
-- document_type        EDINET 様式コード ('120' = 有価証券報告書, '140' = 四半期報告書,
--                      '160' = 半期報告書, '030' = 訂正有価証券報告書, '350' = 大量保有報告書,
--                      '040' = 公開買付届出書 etc.). Free-text but stable.
-- fiscal_year          'YYYY' or 'YYYY-YYYY' for 連結 cross-year. May be NULL for
--                      非継続開示 (大量保有 reports use submission date instead).
-- attached_files_count INTEGER >= 1
-- source_url           https://disclosure2dl.edinet-fsa.go.jp/searchdocument/
--                      ZIPforDocs/{doc_id}.zip ; preserved for paid-surface
--                      Source URL: <…> footer.
-- content_hash         SHA-256 hex (lowercase, 64 chars)
-- ingested_at          ISO 8601 with milliseconds (UTC)
--
-- Indexes
-- -------
-- (houjin_bangou, submission_date DESC)
--     — 法人 detail dashboard "show me last 10 filings"
-- (edinet_code)
--     — bridge fanout from entity_resolution_bridge_v2.edinet_code
-- (doc_id) is automatic via UNIQUE constraint
-- (submission_date)
--     — recurring monthly digest "what was filed since last cycle"
-- (document_type)
--     — DD pack filter "only 有報 + 大量保有"

CREATE TABLE IF NOT EXISTS edinet_filing_signal_layer (
    signal_id              TEXT NOT NULL PRIMARY KEY,
    doc_id                 TEXT NOT NULL UNIQUE,
    edinet_code            TEXT NOT NULL,
    sec_code               TEXT,
    houjin_bangou          TEXT,
    submission_date        TEXT NOT NULL,
    document_type          TEXT NOT NULL,
    fiscal_year            TEXT,
    attached_files_count   INTEGER NOT NULL DEFAULT 1
                           CHECK (attached_files_count >= 1),
    source_url             TEXT NOT NULL,
    content_hash           TEXT NOT NULL
                           CHECK (length(content_hash) = 64),
    ingested_at            TEXT NOT NULL
                           DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_edinet_signal_houjin_date
    ON edinet_filing_signal_layer (houjin_bangou, submission_date DESC);

CREATE INDEX IF NOT EXISTS idx_edinet_signal_edinet_code
    ON edinet_filing_signal_layer (edinet_code);

CREATE INDEX IF NOT EXISTS idx_edinet_signal_submission_date
    ON edinet_filing_signal_layer (submission_date);

CREATE INDEX IF NOT EXISTS idx_edinet_signal_document_type
    ON edinet_filing_signal_layer (document_type);

-- View: only the rows where the bridge has resolved 法人番号. Useful for
-- "company folder filings" surface where NULL houjin_bangou is noise.
CREATE VIEW IF NOT EXISTS v_edinet_filings_resolved AS
SELECT signal_id, doc_id, edinet_code, sec_code, houjin_bangou,
       submission_date, document_type, fiscal_year, source_url,
       content_hash, ingested_at
  FROM edinet_filing_signal_layer
 WHERE houjin_bangou IS NOT NULL;

-- View: pending bridge resolution. Cron job re-runs UPDATE pass on these.
CREATE VIEW IF NOT EXISTS v_edinet_filings_unresolved AS
SELECT signal_id, doc_id, edinet_code, sec_code, submission_date,
       document_type
  FROM edinet_filing_signal_layer
 WHERE houjin_bangou IS NULL;
