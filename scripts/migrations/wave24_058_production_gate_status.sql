-- target_db: jpintel
-- DEEP-58 production gate status table (session A draft, jpcite v0.3.4).
-- Stores daily aggregated status for the 4 blockers + 8 ACK booleans.
-- Idempotent: every statement uses IF NOT EXISTS so the entrypoint.sh
-- self-heal loop can re-apply on every boot without error.
--
-- Migration ordering note: 058_* numbering reserves the slot inside the
-- Wave-24 band; 056..061 are reserved for the DEEP-56..61 cluster. This
-- file lives under scripts/migrations/ once promoted out of session A.

BEGIN;

CREATE TABLE IF NOT EXISTS production_gate_status (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT    NOT NULL,                                       -- ISO date (UTC)
    blocker_id    TEXT    NOT NULL,                                       -- e.g. BLOCKER_DIRTY_TREE / ACK_MIGRATION_TARGETS
    status        TEXT    NOT NULL CHECK (status IN ('BLOCKED','PARTIAL','RESOLVED')),
    evidence_url  TEXT,                                                   -- workflow_run permalink or scripts/* path
    sha256        TEXT,                                                   -- evidence body hash (tamper detection)
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, blocker_id)
);

CREATE INDEX IF NOT EXISTS idx_pgs_date
    ON production_gate_status (snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_pgs_blocker
    ON production_gate_status (blocker_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_pgs_status
    ON production_gate_status (status, snapshot_date DESC);

-- Convenience view: latest status per blocker_id.
CREATE VIEW IF NOT EXISTS v_production_gate_latest AS
SELECT pgs.blocker_id,
       pgs.status,
       pgs.evidence_url,
       pgs.sha256,
       pgs.snapshot_date,
       pgs.created_at
FROM production_gate_status AS pgs
JOIN (
    SELECT blocker_id, MAX(snapshot_date) AS max_date
    FROM production_gate_status
    GROUP BY blocker_id
) AS latest
  ON latest.blocker_id = pgs.blocker_id
 AND latest.max_date   = pgs.snapshot_date;

COMMIT;
