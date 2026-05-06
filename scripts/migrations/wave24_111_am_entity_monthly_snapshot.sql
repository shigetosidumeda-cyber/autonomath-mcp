-- target_db: autonomath
-- migration wave24_111_am_entity_monthly_snapshot (MASTER_PLAN_v1 章
-- 10.1.b — am_entity 月次 snapshot for time-series KPI / 法人 360°
-- trend / corpus drift detection)
--
-- Why this exists:
--   `am_entities` (503,930 rows) is mutable — every ETL pass can flip
--   facts. Without a periodic frozen snapshot we cannot answer
--   "this entity's state at fiscal-month X" honestly. The Wave 24
--   tools `get_houjin_360_snapshot_history` (#102) and the corpus
--   drift detector under §10.10.5 both need point-in-time snapshots
--   to show real time-series, not lossy "current state" only.
--
--   We snapshot ONLY the small set of columns that drive the 360°
--   surface (record_kind, primary identifiers, capital_yen, employee
--   count, status flags) plus a `payload_json` blob carrying the
--   full row at snapshot time. The blob lets future tools rehydrate
--   without us guessing today which columns matter tomorrow.
--
-- Schema:
--   * `entity_id` — joins to am_entities.rowid.
--   * `snapshot_month TEXT` — YYYY-MM, JST cron writes the 1st of
--     each month at 03:00 JST. UNIQUE(entity_id, snapshot_month) so
--     `INSERT OR IGNORE` makes the cron idempotent within a month.
--   * `record_kind` — copied from am_entities at snapshot time
--     (corporate_entity / program / case_study / ...). Lets KPI
--     queries filter without an extra join.
--   * `primary_label` — the source-of-truth display name at snapshot
--     time. Captures rename events.
--   * `capital_yen / employee_count / status_active` — denormalized
--     hot fields for trend queries (we don't want to JSON-extract
--     every row). NULLable.
--   * `payload_json` — the full am_entities row + key am_entity_facts
--     rollup serialized as JSON, so future readers can recover any
--     column without us re-snapshotting.
--   * `snapshot_source` — defaults to 'monthly_cron', leaves room
--     for ad-hoc snapshots (e.g. 'pre_launch' / 'audit_request').
--   * `created_at` — ISO 8601 UTC, when the row landed.
--
-- Indexes:
--   * `idx_aems_month_kind` — KPI roll-up "all corporate_entity rows
--     in 2026-05" hot path.
--   * `idx_aems_entity_month` — single-entity time-series scan
--     (already covered by the UNIQUE, but explicit index keeps
--     descending scans cheap).
--
-- Idempotency:
--   `CREATE TABLE IF NOT EXISTS` + UNIQUE(entity_id, snapshot_month)
--   so the monthly cron's `INSERT OR IGNORE` is safe to retry.
--
-- DOWN:
--   See companion `wave24_111_am_entity_monthly_snapshot_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_entity_monthly_snapshot (
    snapshot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id        INTEGER NOT NULL,
    snapshot_month   TEXT NOT NULL,                       -- YYYY-MM (JST)
    record_kind      TEXT,
    primary_label    TEXT,
    capital_yen      INTEGER,
    employee_count   INTEGER,
    status_active    INTEGER,                             -- 0/1, NULL=unknown
    payload_json     TEXT,                                -- full am_entities + facts rollup
    snapshot_source  TEXT NOT NULL DEFAULT 'monthly_cron',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entity_id, snapshot_month)
);

-- KPI roll-up: which corporate_entity rows were captured in YYYY-MM.
CREATE INDEX IF NOT EXISTS idx_aems_month_kind
    ON am_entity_monthly_snapshot(snapshot_month, record_kind);

-- Single-entity descending time-series scan for `get_houjin_360_snapshot_history`.
CREATE INDEX IF NOT EXISTS idx_aems_entity_month
    ON am_entity_monthly_snapshot(entity_id, snapshot_month DESC);

-- Bookkeeping by entrypoint.sh §4. No DML beyond schema.
