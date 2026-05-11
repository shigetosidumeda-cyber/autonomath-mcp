-- target_db: autonomath
-- migration 218_am_pubcomment_engagement
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #3 (パブコメ engagement)
--
-- Purpose
-- -------
-- e-Gov パブリックコメント (public comment) は制度改正の **シグナル
-- 上流** である。jpcite として、
--
--   (a) どの program / law が現在パブコメ募集中か
--   (b) 募集期限 / window
--   (c) 受付件数 / 賛否ヒストグラム (公表時のみ)
--   (d) 結論 (反映 / 一部反映 / 不反映)
--
-- を時系列で持っておけば、agent / 税理士 / consultant が「現在 X 制度
-- は改正リスク高」を pre-announcement で読める。これは AutoNoMath /
-- jpintel-mcp の付加価値層。
--
-- 関連 table
-- ----------
-- - `am_amendment_announcement` (mig 217) → パブコメ後 announcement.
-- - `am_amendment_snapshot` → 改正 published 時点で snapshot.
-- パブコメは前段 (engagement) で、上記 2 と直交。
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/am/programs/{id}/pubcomment` returns active comment
--   periods (status='open' OR status='under_review').
-- - cron: `scripts/cron/scan_egov_pubcomment.py` (NEW, not part of
--   this migration) ingests from e-Gov RSS / catalog.
-- - Sensitive (§52): result columns are **operator estimates** until
--   the official `result_announcement` row lands.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_pubcomment_engagement (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    egov_case_id      TEXT,                                  -- e-Gov 案件番号
    title             TEXT    NOT NULL,
    program_pid       TEXT,                                  -- FK programs.pid (NULL = pure law)
    law_article_id    INTEGER,                               -- FK am_law_article.id
    authority_id      INTEGER,                               -- FK am_authority.id
    period_kind       TEXT    NOT NULL DEFAULT 'standard',   -- 'standard' (30day) | 'short' (<30day) | 'extended'
    period_start      TEXT    NOT NULL,                      -- ISO date YYYY-MM-DD
    period_end        TEXT    NOT NULL,                      -- ISO date YYYY-MM-DD
    status            TEXT    NOT NULL DEFAULT 'open',       -- 'open' | 'under_review' | 'closed' | 'cancelled'
    comments_received INTEGER,                               -- 公表されている場合のみ
    pro_count         INTEGER,                               -- 賛成
    con_count         INTEGER,                               -- 反対
    mixed_count       INTEGER,                               -- 一部賛成 / 条件付
    result_outcome    TEXT,                                  -- 'reflected' | 'partial' | 'not_reflected' | NULL (pending)
    result_doc_url    TEXT,                                  -- 結果公表 PDF URL
    canonical_url     TEXT    NOT NULL,                      -- e-Gov 案件 URL (primary source)
    archive_url       TEXT,                                  -- web.archive.org fallback
    description       TEXT,                                  -- 案件概要 (1-3 sentences)
    detected_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    closed_at         TEXT,                                  -- 募集終了 timestamp
    CONSTRAINT ck_pubcomment_status CHECK (status IN ('open', 'under_review', 'closed', 'cancelled')),
    CONSTRAINT ck_pubcomment_period CHECK (period_kind IN ('standard', 'short', 'extended')),
    CONSTRAINT ck_pubcomment_outcome CHECK (
        result_outcome IS NULL OR result_outcome IN ('reflected', 'partial', 'not_reflected')
    )
);

-- e-Gov case id uniqueness (when present).
CREATE UNIQUE INDEX IF NOT EXISTS uq_pubcomment_egov_case
    ON am_pubcomment_engagement(egov_case_id)
    WHERE egov_case_id IS NOT NULL;

-- Program-side lookup. Most agent queries hit this index.
CREATE INDEX IF NOT EXISTS idx_pubcomment_program
    ON am_pubcomment_engagement(program_pid, period_end DESC)
    WHERE program_pid IS NOT NULL;

-- Active comment periods (the "what's open right now" surface).
CREATE INDEX IF NOT EXISTS idx_pubcomment_open
    ON am_pubcomment_engagement(period_end, status)
    WHERE status IN ('open', 'under_review');

-- Authority-grouped surface (per-authority dashboard).
CREATE INDEX IF NOT EXISTS idx_pubcomment_authority
    ON am_pubcomment_engagement(authority_id, period_start DESC)
    WHERE authority_id IS NOT NULL;

-- View: only currently-open / under-review periods, joined with authority.
-- Used by `GET /v1/am/pubcomment/active` and the public RSS feed.
DROP VIEW IF EXISTS v_am_pubcomment_active;
CREATE VIEW v_am_pubcomment_active AS
SELECT
    p.id,
    p.egov_case_id,
    p.title,
    p.program_pid,
    p.law_article_id,
    p.authority_id,
    auth.name_ja AS authority_name,
    p.period_kind,
    p.period_start,
    p.period_end,
    p.status,
    p.canonical_url,
    p.archive_url,
    p.description,
    CAST(julianday(p.period_end) - julianday('now') AS INTEGER) AS days_remaining
FROM am_pubcomment_engagement AS p
LEFT JOIN am_authority AS auth ON auth.id = p.authority_id
WHERE p.status IN ('open', 'under_review');
