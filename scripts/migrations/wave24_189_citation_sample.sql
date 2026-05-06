-- target_db: autonomath
-- migration: wave24_189_citation_sample
-- generated_at: 2026-05-07
-- author: DEEP-43 AI crawler / LLM citation rate manual sample protocol
-- idempotent: every CREATE uses IF NOT EXISTS; first-line target_db hint
--             routes this file to autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_43_ai_crawler_citation_sample.md
--
-- CLV2-11 cascade ODE で q (LLM 内 citation share) が critical q* = 0.10
-- を越えると 1 % → 10 % → 80 % の tipping に入る。 q を観測しない限り
-- tipping 突入判定が不可能。 自動 LLM sampling は memory
-- feedback_no_operator_llm_api 違反 (Anthropic API 呼出 = ¥0.5/req
-- 構造で赤字)。 本 protocol は operator が月 1 回 30 分 manual で 400
-- sample を採取し、 logger script が集計するだけ の zero-API pipeline
-- で q を月次測定する。
--
-- Sampling cadence: 毎月 1 日 09:00-09:30 JST、 4 LLM × 100 query = 400 sample
--
-- Field semantics
-- ---------------
-- id              INTEGER PK AUTOINCREMENT
-- sample_month    YYYY-MM (e.g. '2026-05')
-- llm_provider    enum CHECK: 'claude' / 'perplexity' / 'chatgpt' / 'gemini'
-- query_id        Q001..Q100 (固定 100 query set, 5 % 月次 rotate)
-- query_text      operator が web UI に入力した文字列 (snapshot)
-- jpcite_cited    0/1 — 回答内に jpcite.com / api.jpcite.com / jpcite citation
--                 が出現したか (operator 目視判定)
-- competitor_cited 0/1 — jgrants-mcp / aggregator / e-Gov のみ引用
-- citation_url    引用 URL 1 件 (jpcite 優先、 無ければ competitor / NULL)
-- sampled_at      ISO 8601 UTC timestamp
-- sampled_by      operator email or 'operator' (default)
--
-- Indexes:
--   * (sample_month) — 月次 rollup
--   * (llm_provider) — LLM 別 citation rate
--   * (sample_month, llm_provider) — UNIQUE 制約は付けない
--     (同月 同 LLM 同 query が複数回 sample されても可、 trend smoothing 用)

PRAGMA foreign_keys = ON;

-- ============================================================================
-- citation_sample -- one row per (month, llm, query) operator manual sample
-- ============================================================================

CREATE TABLE IF NOT EXISTS citation_sample (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_month     TEXT NOT NULL,
    llm_provider     TEXT NOT NULL CHECK (llm_provider IN (
        'claude',
        'perplexity',
        'chatgpt',
        'gemini'
    )),
    query_id         TEXT NOT NULL,
    query_text       TEXT NOT NULL,
    jpcite_cited     INTEGER NOT NULL DEFAULT 0
                     CHECK (jpcite_cited IN (0, 1)),
    competitor_cited INTEGER NOT NULL DEFAULT 0
                     CHECK (competitor_cited IN (0, 1)),
    citation_url     TEXT,
    sampled_at       TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    sampled_by       TEXT NOT NULL DEFAULT 'operator'
);

CREATE INDEX IF NOT EXISTS idx_citation_sample_month
    ON citation_sample (sample_month);

CREATE INDEX IF NOT EXISTS idx_citation_sample_provider
    ON citation_sample (llm_provider);

CREATE INDEX IF NOT EXISTS idx_citation_sample_month_provider
    ON citation_sample (sample_month, llm_provider);

-- ============================================================================
-- View: 月次 LLM 別 citation rate
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_citation_rate_monthly AS
SELECT
    sample_month,
    llm_provider,
    COUNT(*)                              AS sample_count,
    SUM(jpcite_cited)                     AS jpcite_cited_count,
    SUM(competitor_cited)                 AS competitor_cited_count,
    ROUND(CAST(SUM(jpcite_cited) AS REAL)
          / NULLIF(COUNT(*), 0), 4)       AS jpcite_citation_rate,
    ROUND(CAST(SUM(competitor_cited) AS REAL)
          / NULLIF(COUNT(*), 0), 4)       AS competitor_citation_rate
  FROM citation_sample
 GROUP BY sample_month, llm_provider;

-- View: 月次全体 q (cascade tipping panel feed)
CREATE VIEW IF NOT EXISTS v_citation_q_monthly AS
SELECT
    sample_month,
    COUNT(*)                              AS total_samples,
    SUM(jpcite_cited)                     AS total_jpcite_cited,
    SUM(competitor_cited)                 AS total_competitor_cited,
    ROUND(CAST(SUM(jpcite_cited) AS REAL)
          / NULLIF(COUNT(*), 0), 4)       AS q_jpcite,
    ROUND(CAST(SUM(competitor_cited) AS REAL)
          / NULLIF(COUNT(*), 0), 4)       AS q_competitor,
    CASE
        WHEN CAST(SUM(jpcite_cited) AS REAL) / NULLIF(COUNT(*), 0) < 0.05
            THEN 'pre_tipping'
        WHEN CAST(SUM(jpcite_cited) AS REAL) / NULLIF(COUNT(*), 0) < 0.10
            THEN 'approach'
        ELSE 'tipping_confirmed'
    END                                   AS cascade_state
  FROM citation_sample
 GROUP BY sample_month;

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
