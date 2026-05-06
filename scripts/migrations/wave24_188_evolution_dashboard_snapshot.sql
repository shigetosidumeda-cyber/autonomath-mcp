-- target_db: jpintel
-- DEEP-42 evolution dashboard snapshot table (jpcite v0.3.4).
-- Stores weekly aggregated 12 axis × N signal snapshots for the moat
-- "evolution" dashboard sister to DEEP-58 production gate dashboard.
-- Idempotent: every statement uses IF NOT EXISTS so the entrypoint.sh
-- self-heal loop can re-apply on every boot without error.
--
-- Migration ordering note: 188 sits in the Wave-24 band; rollback companion
-- ships as wave24_188_evolution_dashboard_snapshot_rollback.sql so the
-- entrypoint loop ignores it (entrypoint.sh §4 excludes *_rollback.sql).
--
-- Axis IDs: IA-01 .. IA-12 (see DEEP-42 spec § "集約 source 12 axis").
-- Status enum: 'healthy' / 'degraded' / 'broken' (axis-specific thresholds
-- live in data/evolution_thresholds.yml, quarterly review by operator).

BEGIN;

CREATE TABLE IF NOT EXISTS evolution_dashboard_snapshot (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date     TEXT    NOT NULL,                                -- ISO YYYY-WW (week granularity)
    axis_id           TEXT    NOT NULL,                                -- 'IA-01' .. 'IA-12'
    signal_id         TEXT    NOT NULL,                                -- axis-internal signal slug
    signal_value      REAL,                                            -- scalar (count / rate / λ etc.)
    signal_value_json TEXT,                                            -- structured (timeseries / multi-dim) JSON
    status            TEXT    NOT NULL CHECK (status IN ('healthy','degraded','broken')),
    computed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (snapshot_date, axis_id, signal_id)
);

CREATE INDEX IF NOT EXISTS idx_eds_axis_date
    ON evolution_dashboard_snapshot (axis_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_eds_date
    ON evolution_dashboard_snapshot (snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_eds_status
    ON evolution_dashboard_snapshot (status, snapshot_date DESC);

-- Convenience view: latest week's snapshot per (axis_id, signal_id).
CREATE VIEW IF NOT EXISTS v_evolution_dashboard_latest AS
SELECT eds.axis_id,
       eds.signal_id,
       eds.signal_value,
       eds.signal_value_json,
       eds.status,
       eds.snapshot_date,
       eds.computed_at
FROM evolution_dashboard_snapshot AS eds
JOIN (
    SELECT axis_id, signal_id, MAX(snapshot_date) AS max_date
    FROM evolution_dashboard_snapshot
    GROUP BY axis_id, signal_id
) AS latest
  ON latest.axis_id   = eds.axis_id
 AND latest.signal_id = eds.signal_id
 AND latest.max_date  = eds.snapshot_date;

-- Convenience view: per-axis worst status in latest week (for badge surface).
CREATE VIEW IF NOT EXISTS v_evolution_axis_status AS
SELECT axis_id,
       snapshot_date,
       CASE
           WHEN SUM(CASE WHEN status='broken'   THEN 1 ELSE 0 END) > 0 THEN 'broken'
           WHEN SUM(CASE WHEN status='degraded' THEN 1 ELSE 0 END) > 0 THEN 'degraded'
           ELSE 'healthy'
       END AS axis_status,
       COUNT(*) AS signal_count
FROM evolution_dashboard_snapshot
GROUP BY axis_id, snapshot_date;

COMMIT;
