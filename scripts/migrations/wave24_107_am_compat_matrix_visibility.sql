-- target_db: autonomath
-- migration wave24_107_am_compat_matrix_visibility (MASTER_PLAN_v1 章 3 §D2)
--
-- Why this exists:
--   am_compat_matrix carries 43,966 rows = 3,823 sourced (inferred_only=0,
--   source_url filled) + 40,143 heuristic / unknown. Migration 077 added
--   `inferred_only` so the rule_engine could prefer sourced rows, but the
--   honest sourced/heuristic split is still surfaced via boolean filtering
--   inside every caller. That hides the 'unknown' bucket — a status used
--   for pure heuristic guesses with no citation — behind the same
--   inferred_only=1 flag as legitimate "rationale present, source missing"
--   rows.
--
--   §D2 of the plan promotes this from a 1-bit (sourced / not) to a 3-bit
--   visibility ladder so the public API gates default to public-only and
--   downstream tools (find_combinable_programs et al.) cannot accidentally
--   leak heuristic guesses as primary-sourced advice:
--
--     * public      — sourced (inferred_only=0 AND source_url filled)
--                     → return by default from /v1/am/compat/*.
--     * internal    — heuristic (inferred_only=1 OR source_url empty) but
--                     not unknown — caller must opt-in via
--                     include_heuristic=True to see these.
--     * quarantine  — compat_status='unknown' rows; never returned to
--                     paying callers (no surface), kept in-table for the
--                     monthly LLM batch (§D2 (d)) that promotes them to
--                     'public' as it adds citations.
--
--   The 3-bucket ladder also feeds the §15 KPI:
--     SELECT COUNT(*) FROM am_compat_matrix
--      WHERE visibility='internal'
--        AND program_a IN (SELECT id FROM programs WHERE tier IN ('S','A'));
--   which the operator-LLM monthly batch must drive toward zero.
--
-- Idempotency:
--   * ALTER TABLE ADD COLUMN raises "duplicate column name" on re-run; the
--     entrypoint loop swallows that OperationalError (same pattern used by
--     migrations 049 / 077 / 101 / 119 / wave24_105). The CHECK constraint
--     on the new column requires SQLite ≥ 3.37 (production is 3.45.x).
--   * CREATE INDEX uses IF NOT EXISTS.
--   * Both UPDATE statements are guarded by predicates that re-stamp the
--     same value on a re-run — the WHERE clause includes
--     `AND visibility='internal'` so already-promoted rows are not
--     re-touched (and never demoted).
--
-- Expected post-apply distribution (verified against live autonomath.db
-- 2026-04-30, ~43,966 row total):
--   visibility='public'     ≈ 3,823   (sourced, inferred_only=0 + source_url)
--   visibility='quarantine' ≈ 0..few thousand (status='unknown', if any
--                                    survived migration 077 hard-delete;
--                                    077 deleted unknown+evidence_relation
--                                    NULL rows but kept others)
--   visibility='internal'   ≈ 40,143  (remainder — heuristic with rationale
--                                    but no first-party source_url)
--
--   §D2 検証 SQL: public=3,823 / internal+quarantine 合計 40,143.
--
-- DOWN:
--   See companion `wave24_107_am_compat_matrix_visibility_rollback.sql`.
--   Rollback drops the index and the column; the column drop requires
--   SQLite ≥ 3.35 (production OK).

PRAGMA foreign_keys = ON;

-- ============================================================================
-- 1) Add visibility column with CHECK constraint.
--    DEFAULT 'internal' so legacy rows (pre-migration) and any future
--    INSERT that forgets to set it land in the safe-default bucket
--    (heuristic, NOT public). The two UPDATE statements below promote /
--    demote rows out of 'internal' into 'public' / 'quarantine' as
--    appropriate.
-- ============================================================================

ALTER TABLE am_compat_matrix
    ADD COLUMN visibility TEXT NOT NULL DEFAULT 'internal'
    CHECK (visibility IN ('public','internal','quarantine'));

-- ============================================================================
-- 2) Lookup index — visibility-first composite so the hot path
--    (find_combinable_programs / search_compat default) can range-scan on
--    visibility='public' then narrow by program pair. Keeps the existing
--    primary-key index untouched; this index is additive.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_am_compat_visibility
    ON am_compat_matrix(visibility, program_a_id, program_b_id);

-- ============================================================================
-- 3) Promote sourced rows to 'public'.
--    Conditions: inferred_only=0 AND source_url is non-empty AND we have
--    not already touched this row (visibility='internal' guard makes the
--    UPDATE a no-op on re-apply and prevents demotion of any future
--    operator-LLM-batch promoted row that already carries visibility=public).
-- ============================================================================

UPDATE am_compat_matrix
   SET visibility = 'public'
 WHERE inferred_only = 0
   AND source_url IS NOT NULL
   AND source_url != ''
   AND visibility = 'internal';

-- ============================================================================
-- 4) Demote unknown-status rows to 'quarantine'.
--    These are pure heuristic guesses (no citation, status='unknown'); we
--    keep them in-table so the §D2 (d) monthly LLM batch can promote them
--    after enriching with source_url, but we never surface them to paying
--    callers. The visibility='internal' guard makes the UPDATE re-runnable
--    and avoids demoting rows that may have been hand-promoted to public.
-- ============================================================================

UPDATE am_compat_matrix
   SET visibility = 'quarantine'
 WHERE compat_status = 'unknown'
   AND visibility = 'internal';

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
