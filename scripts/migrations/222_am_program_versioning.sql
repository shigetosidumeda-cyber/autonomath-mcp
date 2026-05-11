-- target_db: autonomath
-- migration 222_am_program_versioning
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #7 (条文単位の version 管理)
--
-- Purpose
-- -------
-- am_amendment_snapshot は **テーブル全体** の snapshot を取るが、
-- 条文単位の "this article changed from v1.0.2 to v1.0.3 on YYYY-MM-DD
-- and the change was a 'minor' (eligibility unchanged) vs 'major'
-- (eligibility changed)" 区別がない。
--
-- conversational agent と税理士 / consultant にとって、major / minor
-- 区別は重大:
--   - minor (typo / 表記 normalization): "no action needed"
--   - major (eligibility / 期日 / 金額): "you must re-evaluate"
--
-- このテーブルは program × article × semver 単位で version を打つ。
-- 同じ program_pid 配下で article_id ごとに独立 version sequence を
-- 進める。
--
-- Semver convention
-- ------------------
-- - MAJOR: eligibility 変更、金額 cap 変更、申請期限ルール変更
-- - MINOR: 説明文の補足、罰則 wording のみ変更、表記揺れ正規化
-- - PATCH: typo、リンク差し替え、PDF URL 更新
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/am/programs/{id}/versions` returns the version
--   timeline for the program (all articles aggregated).
-- - MCP: `program_version_timeline` (additive — does NOT bump
--   tool count, surfaced via existing `program_lifecycle`).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_version (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    program_pid       TEXT    NOT NULL,                      -- FK programs.pid
    article_id        INTEGER,                               -- FK am_law_article.id (NULL = program-level metadata)
    semver_major      INTEGER NOT NULL DEFAULT 1,
    semver_minor      INTEGER NOT NULL DEFAULT 0,
    semver_patch      INTEGER NOT NULL DEFAULT 0,
    change_kind       TEXT    NOT NULL,                      -- 'major' | 'minor' | 'patch'
    change_summary    TEXT    NOT NULL,                      -- 1-3 sentence human note
    effective_from    TEXT,                                  -- ISO date (施行日)
    detected_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Provenance: which snapshot pair triggered this version?
    snapshot_v1_id    INTEGER,                               -- FK am_amendment_snapshot.id (predecessor)
    snapshot_v2_id    INTEGER,                               -- FK am_amendment_snapshot.id (successor)
    diff_id           INTEGER,                               -- FK am_amendment_diff.id
    -- The eligibility_hash captured at this version. Materialized so
    -- a downstream query can dedup versions that didn't actually
    -- change eligibility (the v1/v2 same-hash case).
    eligibility_hash  TEXT,
    -- review_status: cron-detected versions start as 'pending';
    -- operator-approved versions are surfaced.
    review_status     TEXT    NOT NULL DEFAULT 'pending',
    reviewed_at       TEXT,
    reviewed_by       TEXT,
    CONSTRAINT ck_version_change_kind CHECK (change_kind IN ('major', 'minor', 'patch')),
    CONSTRAINT ck_version_review CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

-- Unique semver per (program, article).
CREATE UNIQUE INDEX IF NOT EXISTS uq_program_version_sv
    ON am_program_version(
        program_pid,
        COALESCE(article_id, -1),
        semver_major,
        semver_minor,
        semver_patch
    );

-- Program-side timeline lookup.
CREATE INDEX IF NOT EXISTS idx_program_version_program
    ON am_program_version(program_pid, effective_from DESC);

-- Article-side timeline lookup.
CREATE INDEX IF NOT EXISTS idx_program_version_article
    ON am_program_version(article_id, effective_from DESC)
    WHERE article_id IS NOT NULL;

-- Major-change subset (the "must re-evaluate" surface).
CREATE INDEX IF NOT EXISTS idx_program_version_major
    ON am_program_version(program_pid, effective_from DESC)
    WHERE change_kind = 'major' AND review_status = 'approved';

-- View: approved versions timeline (used by REST + MCP).
DROP VIEW IF EXISTS v_am_program_version_timeline;
CREATE VIEW v_am_program_version_timeline AS
SELECT
    id,
    program_pid,
    article_id,
    semver_major || '.' || semver_minor || '.' || semver_patch AS semver,
    change_kind,
    change_summary,
    effective_from,
    detected_at,
    eligibility_hash
FROM am_program_version
WHERE review_status = 'approved';
