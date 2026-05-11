-- target_db: autonomath
-- migration 217_am_amendment_announcement
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #2 (改正アナウンス)
--
-- Purpose
-- -------
-- am_amendment_snapshot + am_amendment_diff together capture **what
-- changed**, but they do not capture **how the change was announced**
-- to the public. For SLA / brand / auditor disclosure, we need to
-- preserve the announcement event itself:
--
--   - "When did the operator first see the announcement?"
--   - "Which authority pushed the announcement?"
--   - "Was the announcement a press release / Cabinet decision /
--      ministry circular / official-gazette entry?"
--   - "What was the canonical URL on the day of the announcement?"
--     (URLs rot — capturing the URL here, separate from
--      programs.source_url, gives a forensic trail.)
--
-- Without this table, an auditor asking "when did jpcite know that
-- 中小企業等経営強化法 was being amended on date X?" has to scrape git
-- history.
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/am/programs/{id}/amendments/announcements`.
-- - cron: `scripts/cron/scan_amendment_announcements.py` (NEW —
--   not part of this migration).
-- - feed: surfaced into the public RSS at `site/amendment-diff.xml`.
--
-- Idempotency: CREATE * IF NOT EXISTS only. Re-runs are no-ops.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_amendment_announcement (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    program_pid         TEXT,                                -- FK programs.pid (NULL = law-level)
    law_article_id      INTEGER,                             -- FK am_law_article.id (NULL = program-level)
    announcement_kind   TEXT    NOT NULL,                    -- enum below
    announced_at        TEXT    NOT NULL,                    -- ISO date YYYY-MM-DD (公布日)
    effective_from      TEXT,                                -- ISO date (施行日)
    authority_id        INTEGER,                             -- FK am_authority.id
    title               TEXT,                                -- 1-line headline
    body_excerpt        TEXT,                                -- up to 1,000 chars (本文)
    canonical_url       TEXT,                                -- evidence URL (primary source)
    archive_url         TEXT,                                -- web.archive.org fallback
    detected_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    source_kind         TEXT,                                -- 'rss' | 'scrape' | 'manual' | 'webhook'
    -- Provenance link: which snapshot pair triggered this announcement?
    diff_id             INTEGER,                             -- FK am_amendment_diff.id (loose, not enforced)
    review_status       TEXT    NOT NULL DEFAULT 'pending',
    reviewed_at         TEXT,
    reviewed_by         TEXT,
    CONSTRAINT ck_announcement_kind CHECK (announcement_kind IN (
        'press_release',         -- 報道発表
        'cabinet_decision',      -- 閣議決定
        'ministry_circular',     -- 通達 / 通知
        'official_gazette',      -- 官報
        'ministry_pubcomment',   -- パブコメ予告
        'other'
    )),
    CONSTRAINT ck_announcement_review CHECK (review_status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT ck_announcement_target CHECK (
        (program_pid IS NOT NULL OR law_article_id IS NOT NULL)
    )
);

-- Lookup by program (the most common surface query).
CREATE INDEX IF NOT EXISTS idx_am_announcement_program
    ON am_amendment_announcement(program_pid, announced_at DESC)
    WHERE program_pid IS NOT NULL;

-- Lookup by law article (for the law-side feed).
CREATE INDEX IF NOT EXISTS idx_am_announcement_law
    ON am_amendment_announcement(law_article_id, announced_at DESC)
    WHERE law_article_id IS NOT NULL;

-- Time-ordered for the RSS feed (most-recent first across all targets).
CREATE INDEX IF NOT EXISTS idx_am_announcement_chrono
    ON am_amendment_announcement(announced_at DESC)
    WHERE review_status = 'approved';

-- Surface view: approved only, with authority joined for the RSS title.
DROP VIEW IF EXISTS v_am_amendment_announcement_active;
CREATE VIEW v_am_amendment_announcement_active AS
SELECT
    a.id,
    a.program_pid,
    a.law_article_id,
    a.announcement_kind,
    a.announced_at,
    a.effective_from,
    a.authority_id,
    auth.name_ja AS authority_name,
    a.title,
    a.body_excerpt,
    a.canonical_url,
    a.archive_url,
    a.source_kind
FROM am_amendment_announcement AS a
LEFT JOIN am_authority AS auth ON auth.id = a.authority_id
WHERE a.review_status = 'approved';
