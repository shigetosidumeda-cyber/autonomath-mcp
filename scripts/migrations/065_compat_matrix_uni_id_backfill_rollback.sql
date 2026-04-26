-- target_db: autonomath
-- migration 065_compat_matrix_uni_id_backfill_rollback (R9 critical fix, 2026-04-25)
--
-- ROLLBACK COMPANION for 065_compat_matrix_uni_id_backfill.sql.
-- DRAFT ONLY — apply gated on user review (see TASK_REPORT in the forward
-- migration's header).
--
-- ============================================================================
-- USAGE
-- ============================================================================
-- The forward migration creates a snapshot table
--   jpi_exclusion_rules_pre052_snapshot (rule_id, program_a, program_b, snapshot_at)
-- BEFORE running any UPDATE. This file restores program_a / program_b to
-- their pre-052 legacy strings using that snapshot, byte-for-byte.
--
-- Apply only against autonomath.db. The script is idempotent: if 052 was
-- never applied, the snapshot table is empty and the UPDATEs are no-ops.
--
-- Recommended pre-rollback:
--   cp autonomath.db autonomath.db.pre_052_rollback_$(date +%Y%m%d_%H%M%S)
--
-- ============================================================================
-- RESTORE
-- ============================================================================

-- 1) program_a: restore from snapshot (matches by rule_id, exact string).
UPDATE jpi_exclusion_rules
   SET program_a = (
       SELECT s.program_a
         FROM jpi_exclusion_rules_pre052_snapshot s
        WHERE s.rule_id = jpi_exclusion_rules.rule_id
        LIMIT 1
   )
 WHERE EXISTS (
       SELECT 1 FROM jpi_exclusion_rules_pre052_snapshot s
        WHERE s.rule_id = jpi_exclusion_rules.rule_id
   );

-- 2) program_b: restore from snapshot (matches by rule_id, exact string).
UPDATE jpi_exclusion_rules
   SET program_b = (
       SELECT s.program_b
         FROM jpi_exclusion_rules_pre052_snapshot s
        WHERE s.rule_id = jpi_exclusion_rules.rule_id
        LIMIT 1
   )
 WHERE EXISTS (
       SELECT 1 FROM jpi_exclusion_rules_pre052_snapshot s
        WHERE s.rule_id = jpi_exclusion_rules.rule_id
   );

-- ============================================================================
-- VERIFY (run AFTER rollback — pure SELECT, comment-only)
-- ============================================================================
-- SELECT 'rollback_program_a_uni' AS k, COUNT(*) FROM jpi_exclusion_rules WHERE program_a LIKE 'UNI-%';
-- SELECT 'rollback_program_b_uni' AS k, COUNT(*) FROM jpi_exclusion_rules WHERE program_b LIKE 'UNI-%';
-- Expect to revert to pre-052 baseline: program_a UNI=13, program_b UNI=13
-- (verified live on autonomath.db at 2026-04-25). Any deviation means a
-- subsequent migration touched these rows; pause and audit migration log.
--
-- ============================================================================
-- POST-ROLLBACK
-- ============================================================================
-- Snapshot table is left intact for forensic comparison. Drop manually
-- when no longer needed:
--   DROP TABLE jpi_exclusion_rules_pre052_snapshot;
