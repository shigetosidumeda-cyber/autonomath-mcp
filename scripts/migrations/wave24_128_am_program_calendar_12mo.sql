-- target_db: autonomath
-- migration wave24_128_am_program_calendar_12mo (MASTER_PLAN_v1 章
-- 10.2.3 — 制度 × 月 12 ヶ月カレンダー事前計算)
--
-- Why this exists:
--   `get_program_calendar_12mo` (#99) returns each program's
--   monthly open/close state for the next 12 months. Computing
--   this from `am_application_round` (1,256 rows) at request time
--   requires JOINing rounds × month windows × public-holiday
--   tables, which is expensive. We materialize one row per
--   (program × month) and let the read path SELECT directly.
--
--   Recompute cadence: nightly 02:30 JST, full rebuild. With
--   11,601 programs × 12 months = 139,212 rows, the table fits
--   comfortably in memory.
--
-- Schema:
--   * program_unified_id TEXT NOT NULL
--   * month_start TEXT NOT NULL          — first day of month, ISO YYYY-MM-01
--   * is_open INTEGER NOT NULL           — 0 / 1
--   * deadline TEXT                      — applicable deadline within month, ISO date
--   * round_id_json TEXT                 — JSON list of am_application_round ids
--   * notes TEXT                         — short note (e.g. "公募中" / "次回 5月")
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE(program_unified_id, month_start)
--
-- Indexes:
--   * (program_unified_id, month_start) — composite hot path.
--   * (month_start, is_open) — KPI roll-ups "open programs in 2026-06".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. UNIQUE makes `INSERT OR REPLACE` safe.
--
-- DOWN:
--   See companion `wave24_128_am_program_calendar_12mo_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_calendar_12mo (
    program_unified_id TEXT NOT NULL,
    month_start        TEXT NOT NULL,
    is_open            INTEGER NOT NULL CHECK (is_open IN (0, 1)),
    deadline           TEXT,
    round_id_json      TEXT,
    notes              TEXT,
    computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_unified_id, month_start)
);

CREATE INDEX IF NOT EXISTS idx_apcal_month_open
    ON am_program_calendar_12mo(month_start, is_open);
