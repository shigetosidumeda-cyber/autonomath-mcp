-- target_db: autonomath
-- migration wave24_180_time_machine_index (DEEP-22 / CL-01)
--
-- DEEP-22 Regulatory Time Machine — composite-index hot path for
-- query_at_snapshot(program_id, as_of) and query_program_evolution
-- (year). Pivots the time-machine onto the autonomath spine
-- (am_amendment_snapshot.effective_from) so the tool can run without
-- waiting on the never-landed jpintel-side migration 067.
--
-- The two new tools surface 14,596 captures + 144 definitive-dated rows
-- as the moat layer: callers ask "what eligibility was live on
-- 2024-06-01" and we replay the snapshot row whose effective_from <=
-- as_of, ordered by effective_from DESC then version_seq DESC.
--
-- Forward-only / idempotent. Re-running on every Fly boot is safe — all
-- DDL guarded by IF NOT EXISTS, all DML guarded by NULL checks.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Hot-path composite indexes for am_amendment_snapshot
-- ---------------------------------------------------------------------------
-- query_at_snapshot resolves "the version live at as_of" with the
-- predicate `entity_id = ? AND (effective_from IS NULL OR effective_from
-- <= ?)` ordered by `effective_from DESC, version_seq DESC LIMIT 1`.
-- Without these indexes the planner falls back to ix_amendment_entity_obs
-- which is sorted by observed_at, not effective_from — a full sort +
-- table-scan per call on a 14,596-row table.
CREATE INDEX IF NOT EXISTS ix_am_amendment_snapshot_entity_effective
    ON am_amendment_snapshot(entity_id, effective_from);

CREATE INDEX IF NOT EXISTS ix_am_amendment_snapshot_entity_version
    ON am_amendment_snapshot(entity_id, version_seq DESC);

-- ---------------------------------------------------------------------------
-- Quality-flag derivation index
-- ---------------------------------------------------------------------------
-- Wrapper code branches on whether effective_from IS NULL to assign
-- quality_flag in {definitive, inferred, template_default}. Partial
-- index keeps lookups O(log n) on the 144-row definitive cohort.
CREATE INDEX IF NOT EXISTS ix_am_amendment_snapshot_quality
    ON am_amendment_snapshot(effective_from)
    WHERE effective_from IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Snapshot-snapshot composite for the 12-month evolution grid
-- ---------------------------------------------------------------------------
-- query_program_evolution(program_id, year) walks 12 monthly pivots.
-- (entity_id, effective_from) covers the inner SELECT for each month.
-- ix_amendment_effective (single-col, pre-existing) is preserved.
CREATE INDEX IF NOT EXISTS ix_am_amendment_snapshot_eligibility_hash
    ON am_amendment_snapshot(entity_id, eligibility_hash);
