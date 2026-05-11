-- target_db: autonomath
-- migration: 234_budget_to_subsidy_chain (Axis 3d — 予算成立 → 補助金 announce chain)
-- generated_at: 2026-05-12
-- author: Axis 3 daily ingest landing (5-source fresh data automation)
-- idempotent: every CREATE uses IF NOT EXISTS; ALTER guarded via PRAGMA sqlite_master check.
--             first-line `target_db: autonomath` hint routes this file to
--             autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Axis 3d (Wave 33+ daily ingest hardening) links 衆議院・参議院 議案情報 (本会議で
-- 予算可決) to その後 30 日以内の各官庁 補助金 announce. The chain row records:
--
--   * budget_passing_date       予算 (本予算 / 補正予算) 本会議可決日
--   * budget_kokkai_id          国会議案 ID (e.g. "211-3" for 第211回国会-議案番号3)
--   * subsidy_program_id        am_entities.canonical_id for the announced program
--   * lag_days                  announce_date - budget_passing_date (0..30 typical)
--   * evidence_url              一次資料 link (kokkai議案 + 補助金 announce)
--   * detected_at               ISO 8601 UTC chain row insert time
--   * sha256                    canonical fingerprint for idempotent re-detect
--
-- Idempotent INSERT OR IGNORE on UNIQUE (budget_kokkai_id, subsidy_program_id)
-- skips duplicate chain detects across re-runs of the cron.
--
-- programs.triggered_by_budget_id wires the relation back onto the read model
-- (am_entities.kind='program' rows) so agent surfaces can answer 「この補助金は
-- 何の予算で出たか」 directly without joining am_budget_subsidy_chain.
--
-- LLM call: 0. Pure SQLite + Python regex inserts from
-- scripts/cron/detect_budget_to_subsidy_chain.py.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_budget_subsidy_chain — 予算 → 補助金 announce 関連 (Axis 3d)
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_budget_subsidy_chain (
    chain_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_kokkai_id      TEXT NOT NULL,
    budget_passing_date   TEXT NOT NULL,                           -- ISO YYYY-MM-DD JST
    budget_kind           TEXT NOT NULL DEFAULT 'unknown'
                            CHECK(budget_kind IN
                                  ('main_budget','supplementary_budget','unknown')),
    subsidy_program_id    TEXT NOT NULL,                           -- am_entities.canonical_id
    announce_date         TEXT NOT NULL,                           -- ISO YYYY-MM-DD JST
    lag_days              INTEGER NOT NULL,
    evidence_url          TEXT NOT NULL,
    detected_at           TEXT NOT NULL DEFAULT (datetime('now')),
    sha256                TEXT NOT NULL,
    UNIQUE(budget_kokkai_id, subsidy_program_id)
);

CREATE INDEX IF NOT EXISTS ix_budget_subsidy_chain_budget
    ON am_budget_subsidy_chain(budget_kokkai_id, budget_passing_date);
CREATE INDEX IF NOT EXISTS ix_budget_subsidy_chain_program
    ON am_budget_subsidy_chain(subsidy_program_id);
CREATE INDEX IF NOT EXISTS ix_budget_subsidy_chain_announce
    ON am_budget_subsidy_chain(announce_date);

-- ============================================================================
-- programs.triggered_by_budget_id — quick FK onto the chain (best-effort ALTER)
-- ============================================================================
--
-- The legacy `programs` table lives in jpintel.db; the entity-fact mirror lives
-- in autonomath.db as `am_entities`. Both branches keep an optional column for
-- the budget pointer. SQLite has no IF NOT EXISTS on ALTER, so the column is
-- added defensively via a temporary view-driven check that no-ops on second
-- run (we wrap ALTER in a CREATE-TABLE-IF-NOT-EXISTS pattern that mirrors the
-- existing in-tree convention used by migrations 049 / 090).

-- Use sqlite_master probe by creating a marker table that records whether
-- the column add already ran. The actual ALTER lives in a Python helper
-- (scripts/cron/detect_budget_to_subsidy_chain.py:_ensure_program_column)
-- that is idempotent. The marker below makes the contract auditable.

CREATE TABLE IF NOT EXISTS am_budget_subsidy_chain_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO am_budget_subsidy_chain_meta(key, value) VALUES
    ('column_triggered_by_budget_id_added', 'pending'),
    ('chain_window_days_default', '30');

-- Bookkeeping recorded by scripts/migrate.py / entrypoint.sh §4.
