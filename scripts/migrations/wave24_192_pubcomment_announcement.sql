-- target_db: autonomath
-- migration: wave24_192_pubcomment_announcement
-- generated_at: 2026-05-07
-- author: DEEP-45 e-Gov パブコメ follow daily cron implementation
-- idempotent: every CREATE uses IF NOT EXISTS; every INSERT uses INSERT OR IGNORE
--             first-line target_db hint routes this file to autonomath.db via
--             entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_45_egov_pubcomment_follow.md
--
-- DEEP-45 lands the IA-04 #3 axis (e-Gov パブコメ 公示 follow) — lead time
-- 30-60 日 / 確実性最高 の 改正案公示 surface. DEEP-39 国会会議録 (6-18 ヶ月,
-- noisy) と 審議会議事録 (9-18 ヶ月, PDF抽出失敗あり) が 上流 detect なのに対し,
-- パブコメ公示は 改正案 30-60 日前の 確定 surface (政令・省令 改正案は 30 日,
-- 法律案は 60 日 の 公示期間 法定). ここで detect すれば jpcite cohort kit
-- (DEEP-34) / disclaimer-spec (DEEP-32) / pricing surface を 改正発効 30-60 日前
-- に 再生成可能.
--
-- Field semantics
-- ---------------
--   * id                       e-Gov 案件番号 (PK)
--   * ministry                 関係省庁 (財務省 / 国税庁 等)
--   * target_law               改正対象法令 (税理士法 等)
--   * announcement_date        ISO YYYY-MM-DD JST 公示日
--   * comment_deadline         ISO YYYY-MM-DD JST 意見提出締切
--   * summary_text             公示概要 (HTML 抽出)
--   * full_text_url            改正案本文 PDF/HTML URL
--   * retrieved_at             ISO 8601 UTC 取得日時
--   * sha256                   summary_text + full_text_url SHA256 fingerprint
--   * jpcite_relevant          1 if 業法 keyword union hits, else 0
--   * jpcite_cohort_impact     JSON rollup of (cohort × hit_keyword) when relevant
--
-- Idempotent INSERT OR IGNORE on (id) PK skips duplicate fetches across re-runs.
--
-- LLM call: 0. Pure SQLite + regex inserts from
-- scripts/cron/ingest_egov_pubcomment_daily.py.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- pubcomment_announcement — e-Gov パブコメ 公示 rows
-- ============================================================================

CREATE TABLE IF NOT EXISTS pubcomment_announcement (
    id                      TEXT PRIMARY KEY,
    ministry                TEXT NOT NULL,
    target_law              TEXT NOT NULL,
    announcement_date       TEXT NOT NULL,
    comment_deadline        TEXT NOT NULL,
    summary_text            TEXT NOT NULL,
    full_text_url           TEXT NOT NULL,
    retrieved_at            TEXT NOT NULL,
    sha256                  TEXT NOT NULL,
    jpcite_relevant         INTEGER NOT NULL DEFAULT 0
                              CHECK(jpcite_relevant IN (0,1)),
    jpcite_cohort_impact    TEXT
);

CREATE INDEX IF NOT EXISTS ix_pubcomment_announce_date
    ON pubcomment_announcement(announcement_date);
CREATE INDEX IF NOT EXISTS ix_pubcomment_deadline
    ON pubcomment_announcement(comment_deadline);
CREATE INDEX IF NOT EXISTS ix_pubcomment_law_relevant
    ON pubcomment_announcement(target_law, jpcite_relevant);

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
