-- target_db: autonomath
-- migration: wave24_185_kokkai_utterance
-- generated_at: 2026-05-07
-- author: DEEP-39 国会会議録 + 審議会議事録 weekly cron implementation
-- idempotent: every CREATE uses IF NOT EXISTS; every INSERT uses INSERT OR IGNORE
--             first-line target_db hint routes this file to autonomath.db via
--             entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_39_kokkai_shingikai_cron.md
--
-- DEEP-39 lands the 改正前 / 制度設計者意図 1次資料 layer for the time machine
-- spine (DEEP-22 am_amendment_diff is 改正後 diff only). 3 tables:
--
--   * kokkai_utterance       60万 utterance backlog target (国会会議録 API)
--   * shingikai_minutes      12 council weekly minutes (PDF mirror, 抽出 only)
--   * regulatory_signal      keyword-detected 改正 signal で lead time 6-18ヶ月
--
-- Field semantics
-- ---------------
-- All 3 tables carry source_url + retrieved_at + sha256 for the auditor
-- reproducibility envelope (Wave22 同等 contract). Idempotent INSERT OR IGNORE
-- on PK skips duplicate speechID / minute IDs / signal IDs.
--
-- LLM call: 0. Pure SQLite + regex inserts from
-- scripts/cron/ingest_kokkai_weekly.py + ingest_shingikai_weekly.py.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- kokkai_utterance — 国会会議録 speech rows (kokkai.ndl.go.jp /api/speech)
-- ============================================================================

CREATE TABLE IF NOT EXISTS kokkai_utterance (
    id              TEXT PRIMARY KEY,
    session_no      INTEGER NOT NULL,
    house           TEXT NOT NULL,
    committee       TEXT NOT NULL,
    date            TEXT NOT NULL,
    speaker         TEXT NOT NULL,
    speaker_role    TEXT,
    body            TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    retrieved_at    TEXT NOT NULL,
    sha256          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_kokkai_date
    ON kokkai_utterance(date);
CREATE INDEX IF NOT EXISTS ix_kokkai_committee_date
    ON kokkai_utterance(committee, date);

-- ============================================================================
-- shingikai_minutes — 12 council 議事録 (PDF抽出 only, no binary persisted)
-- ============================================================================

CREATE TABLE IF NOT EXISTS shingikai_minutes (
    id              TEXT PRIMARY KEY,
    ministry        TEXT NOT NULL,
    council         TEXT NOT NULL,
    date            TEXT NOT NULL,
    agenda          TEXT,
    body_text       TEXT NOT NULL,
    pdf_url         TEXT NOT NULL,
    retrieved_at    TEXT NOT NULL,
    sha256          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_shingikai_council_date
    ON shingikai_minutes(council, date);

-- ============================================================================
-- regulatory_signal — keyword/topic detected 改正 signal layer
-- ============================================================================

CREATE TABLE IF NOT EXISTS regulatory_signal (
    id                  TEXT PRIMARY KEY,
    signal_kind         TEXT NOT NULL CHECK(signal_kind IN
                            ('kokkai_keyword','shingikai_topic','pubcomment_announcement')),
    law_target          TEXT NOT NULL,
    lead_time_months    INTEGER,
    evidence_url        TEXT NOT NULL,
    detected_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_signal_law_detected
    ON regulatory_signal(law_target, detected_at);

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
