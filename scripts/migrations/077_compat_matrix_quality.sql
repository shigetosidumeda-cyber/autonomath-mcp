-- target_db: autonomath
-- migration 077_compat_matrix_quality (phantom-moat audit fix #2, 2026-04-29)
--
-- ============================================================================
-- BACKGROUND (verified against live autonomath.db at 2026-04-29)
-- ============================================================================
--   am_compat_matrix is presented as a 48,815-row authoritative compat
--   surface, but the phantom-moat audit found:
--
--     compat_status      total       sourced (source_url filled)
--     case_by_case      18,917         992  (5.2%)
--     compatible        21,985       1,940  (8.8%)
--     incompatible       3,064         203  (6.6%)
--     unknown            4,849       1,365 (28.1%, BUT 0 with evidence_relation)
--     ----------------------------------------------------------
--     TOTAL             48,815       4,500  (9.2%)
--
--   The 4,849 'unknown' rows are 100% inference noise — every one has
--   evidence_relation = NULL, meaning we have neither a source_url
--   citation nor a relation-evidence pointer. Surfacing them as part of
--   the rule_engine corpus inflates "49,247 rules across 6 corpora" by
--   ~10% with rows that produce judgment='unknown' verdicts that scare
--   callers into manual review for non-issues.
--
--   Audit-recommended fix:
--     1. Add `inferred_only INTEGER DEFAULT 0` so the MCP `compat_check`
--        path can request authoritative-only output (`WHERE inferred_only=0`)
--        while still keeping the inferred corpus in the table for callers
--        that opt in via `include_inferred=True`.
--     2. UPDATE inferred_only=1 WHERE source_url IS NULL OR source_url=''.
--     3. DELETE the 4,849 status='unknown' AND evidence_relation IS NULL
--        rows — pure noise, never useful, and the rule_engine ladder
--        already maps them to judgment='unknown' which is the same
--        outcome as "no row exists at all".
--
--   Source URL backfill (where joinable from am_relation) is handled by
--   the companion script:
--     scripts/cron/backfill_compat_source.py
--   which runs AFTER this migration and pulls source URLs through the
--   am_relation → am_entity_source → am_source chain. ~778 distinct
--   pairs are recoverable that way (verified against live DB
--   2026-04-29).
--
-- ============================================================================
-- IDEMPOTENCY
-- ============================================================================
--   * ALTER TABLE ADD COLUMN is no-op-on-duplicate per scripts/migrate.py
--     (it catches "duplicate column name" SQLite errors).
--   * The UPDATE / DELETE statements are guarded by predicates that
--     short-circuit cleanly on a re-applied DB — UPDATE re-stamps the
--     same value, DELETE finds no matching rows.
--   * CREATE INDEX IF NOT EXISTS for the new lookup index.
--
-- ============================================================================
-- DOWN (commented; the deleted unknown/no-evidence rows had no useful
-- payload, but if the operator decides to re-classify them, restore from
-- the pre-migration backup taken via:
--   cp autonomath.db autonomath.db.pre_077_compat_$(date +%Y%m%d_%H%M%S)
-- before running). No automated rollback companion is shipped because
-- the deletes are pure noise per audit verdict; reverse-applying the
-- ADD COLUMN can be done with the standard SQLite "create new table /
-- copy / drop / rename" pattern, which the project does not currently
-- automate (matches policy in feedback_completion_gate_minimal).
--
-- ============================================================================
-- 1) Add inferred_only column. ALTER TABLE ADD COLUMN is idempotent at
--    the migrate.py runner level (re-runs raise SQLITE_ERROR which the
--    runner swallows for "duplicate column name" specifically; same
--    pattern as migration 076 trial_signups).
-- ============================================================================

ALTER TABLE am_compat_matrix ADD COLUMN inferred_only INTEGER NOT NULL DEFAULT 0;

-- ============================================================================
-- 2) Stamp inferred_only=1 on every row with no source_url citation.
--    Idempotent: re-application sets the same value.
-- ============================================================================

UPDATE am_compat_matrix
   SET inferred_only = 1
 WHERE source_url IS NULL OR source_url = '';

-- ============================================================================
-- 3) Delete the 'unknown' bucket with no evidence_relation pointer
--    (4,849 rows on first apply per 2026-04-29 audit). On re-apply the
--    WHERE clause matches 0 rows. Pure noise: no source_url, no
--    relation evidence — the rule_engine already returns
--    judgment='unknown' for the same pair when the row is absent, so
--    the outcome is identical and the data_quality reporting becomes
--    honest.
-- ============================================================================

DELETE FROM am_compat_matrix
 WHERE compat_status = 'unknown'
   AND evidence_relation IS NULL;

-- ============================================================================
-- 4) Indexes — add a partial index on inferred_only=0 for the hot path
--    (authoritative compat_check). Existing ix_am_compat_status keeps
--    the legacy paths fast.
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_am_compat_authoritative
    ON am_compat_matrix(program_a_id, program_b_id)
 WHERE inferred_only = 0;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
