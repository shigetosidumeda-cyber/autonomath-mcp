-- migration 224_jpi_anonymized_query_log
-- target_db: jpintel
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #9 (匿名化 query 分析)
--
-- Purpose
-- -------
-- jpi_user_search_history (mig 219) は **per-user** で 90-day 保管。
-- 一方、operator は「全 user 集計でどの query が伸びているか?」を
-- 知りたい (organic SEO の信号、新規 program ニーズの先取り)。
--
-- このテーブルは:
--   - key_hash を保存しない (= 匿名)
--   - query_text の bag-of-words → SHA-256 を保存 (= 復元不能化)
--   - 数値だけは集計可能 (per-day count、duration p50/p95、result_count
--     分布)
--   - 730 日 (2 年) 保管 — search_history の 23 倍長い。匿名なので
--     プライバシー的に許容範囲。
--
-- 旧 `jpi_query_aggregate` (mig 117) は **per-endpoint** で粗い。
-- これは **per-query-shape** で細かい。同 endpoint でも query が
-- 違えば別 row。
--
-- Privacy posture
-- ---------------
-- - **key_hash 列を持たない**。同 user の 2 回の検索は別 row として
--   見える (linkability なし)。
-- - query_text 原文は格納しない — 単語 bag を sort + sha256。
--   "東京都 補助金 IT" と "IT 東京都 補助金" は同じ hash。
-- - IP / UA / referer は一切持たない。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jpi_anonymized_query_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- query shape signature (SHA-256 of sorted token bag, 64 hex chars)
    query_shape     TEXT    NOT NULL,
    -- The endpoint hit. "/v1/programs/search" / "/v1/cases/search" etc.
    endpoint        TEXT    NOT NULL,
    -- Coarse category: 'programs' | 'cases' | 'laws' | 'tax_rules' | 'mixed' | 'other'
    query_category  TEXT    NOT NULL DEFAULT 'other',
    -- Token count of the original query (NOT the words themselves — just N).
    token_count     INTEGER NOT NULL DEFAULT 0,
    -- Result envelope summary
    result_count    INTEGER,
    duration_ms     INTEGER,
    http_status     INTEGER NOT NULL DEFAULT 200,
    -- When the query was issued (bucket to hour for de-fingerprinting).
    bucket_hour     TEXT    NOT NULL,                        -- "2026-05-11T22:00:00+09:00" — JST hour bucket
    -- 認証クラス: 'anonymous' | 'authenticated' (NO key_hash).
    auth_class      TEXT    NOT NULL DEFAULT 'anonymous',
    CONSTRAINT ck_anon_query_category CHECK (query_category IN (
        'programs', 'cases', 'laws', 'tax_rules', 'mixed', 'other'
    )),
    CONSTRAINT ck_anon_auth_class CHECK (auth_class IN ('anonymous', 'authenticated'))
);

-- Time-bucket rollup index (the main analytics surface).
CREATE INDEX IF NOT EXISTS idx_anon_query_bucket
    ON jpi_anonymized_query_log(bucket_hour DESC);

-- Per-shape trending (group by query_shape, order by bucket_hour).
CREATE INDEX IF NOT EXISTS idx_anon_query_shape
    ON jpi_anonymized_query_log(query_shape, bucket_hour DESC);

-- Category histograms (operator dashboard).
CREATE INDEX IF NOT EXISTS idx_anon_query_category
    ON jpi_anonymized_query_log(query_category, bucket_hour DESC);

-- Endpoint × hour for the rate analytics.
CREATE INDEX IF NOT EXISTS idx_anon_query_endpoint
    ON jpi_anonymized_query_log(endpoint, bucket_hour DESC);

-- View: trending shapes (last 7 days, ranked by count). This is a
-- materialization candidate for a precompute job — for now it's a
-- view, the operator dashboard tolerates a few-hundred-ms scan.
DROP VIEW IF EXISTS v_anon_query_trending_7d;
CREATE VIEW v_anon_query_trending_7d AS
SELECT
    query_shape,
    query_category,
    COUNT(*) AS hit_count,
    AVG(duration_ms) AS avg_duration_ms,
    AVG(result_count) AS avg_result_count
FROM jpi_anonymized_query_log
WHERE bucket_hour >= datetime('now', '-7 days')
GROUP BY query_shape, query_category;
