-- target_db: autonomath
-- migration 065_compat_matrix_uni_id_backfill (R9 critical fix, 2026-04-25)
--
-- DRAFT ONLY — apply gated on user review (see TASK_REPORT below).
--
-- Reserved per docs/_internal/COORDINATION_2026-04-25.md §"am_compat_matrix
-- 48,815 row が完全 dead code". This file lex-sorts between
--   052_api_keys_subscription_status.sql  (jpintel.db, no marker)
--   052_perf_indexes.sql                  (jpintel.db, no marker)
-- and runs only against autonomath.db via the `-- target_db:` header
-- consumed by scripts/migrate.py:_sql_has_target_marker.
--
-- ============================================================================
-- BACKGROUND (verified against live autonomath.db at 2026-04-25)
-- ============================================================================
--   am_compat_matrix:                    48,815 rows, 393 unique program_a_id
--     - program_a_id LIKE 'UNI-%'        :     0 rows
--     - program_a_id LIKE 'certification:%' : 8,475 rows
--     - program_a_id (other, e.g. 'loan:jfc:…'): 40,340 rows
--
--   jpi_exclusion_rules:                  181 rows
--     - program_a LIKE 'UNI-%'           :    13 rows
--     - program_a LIKE 'certification:%' :     0 rows
--     - program_a human name (other)     :   166 rows
--   (program_b distribution is essentially identical — see header_query block.)
--
--   INNER JOIN am_compat_matrix.program_a_id = jpi_exclusion_rules.program_a
--     ⇒ 0 rows. The two tables share zero key space, so any cross-dataset
--     compliance walk that fans out from jpi_exclusion_rules misses the
--     entire compat_matrix payload — 48,815 rows of structural pairwise
--     compatibility data are dark to the runtime.
--
-- ============================================================================
-- FIX (this migration)
-- ============================================================================
--   Backfill jpi_exclusion_rules.program_a / program_b in place when AND ONLY
--   WHEN exactly one jpi_programs.primary_name matches the legacy display
--   string. Ambiguous matches (multiple primary_name dupes) and unresolvable
--   strings are LEFT UNTOUCHED — those become P0.2 manual-mapping work.
--
--   Per live verification (numbers below are the SELECT-only header running
--   immediately on apply; record them in the user report after dry-run):
--     program_a unambiguous resolvable : 10 rows  ← will be UPDATEd
--     program_b unambiguous resolvable :  6 rows  ← will be UPDATEd
--     program_a ambiguous (≥2 dupes)   :  varies — left as legacy string
--     program_a fully unresolvable     : ~146 rows total ← P0.2 human task
--
--   This migration does NOT touch:
--     - jpi_exclusion_rules rows where program_a is already 'UNI-%' / 'certification:%'
--     - rows where primary_name has duplicates (silent ambiguity, hand-map)
--     - source-of-truth `data/jpintel.db.exclusion_rules` (already augmented
--       via migration 051 with program_a_uid / program_b_uid columns).
--       This file mutates the autonomath.db MIRROR only.
--
-- ============================================================================
-- HUMAN-TASK (P0.2) follow-up
-- ============================================================================
--   The remaining ~146 program_a + ~140 program_b rows carry strings like
--   '認定新規就農者' (a category, not a program), '令和7年度〇〇枠' (year-suffixed
--   variant of an existing program), or names whose primary_name in
--   jpi_programs has multiple dupes. These need a human pass:
--     1. Decide whether the row references a category (drop _uid mapping)
--        or a program with year-stripped canonical (manual UNI-xxxx).
--     2. For multi-match cases, pick the correct unified_id by reading
--        authority + prefecture + program_kind in jpi_programs.
--   Track in analysis_wave18/_p02_exclusion_human_mapping_2026-04-25.md.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   Companion file scripts/migrations/065_compat_matrix_uni_id_backfill_rollback.sql
--   restores legacy strings from a snapshot table. Take a backup first:
--     cp autonomath.db autonomath.db.pre_052_compat_$(date +%Y%m%d_%H%M%S)
--
-- ============================================================================
-- DRY-RUN VERIFY (run BEFORE applying — pure SELECT, no writes)
-- ============================================================================
-- Pre-apply counts (informational; SELECTs only — they are SQL-comment lines
-- so the migration runner never executes them. Copy/paste into sqlite3 to
-- verify the numbers match the BACKGROUND block above on this DB).
--
-- SELECT 'pre_apply_program_a_resolvable' AS k, COUNT(*) FROM jpi_exclusion_rules e
--   WHERE e.program_a NOT LIKE 'UNI-%' AND e.program_a NOT LIKE 'certification:%'
--     AND (SELECT COUNT(*) FROM jpi_programs p WHERE p.primary_name = e.program_a) = 1;
-- SELECT 'pre_apply_program_b_resolvable' AS k, COUNT(*) FROM jpi_exclusion_rules e
--   WHERE e.program_b NOT LIKE 'UNI-%' AND e.program_b NOT LIKE 'certification:%'
--     AND (SELECT COUNT(*) FROM jpi_programs p WHERE p.primary_name = e.program_b) = 1;

-- ============================================================================
-- SNAPSHOT (rollback prerequisite — runs BEFORE the UPDATEs)
-- ============================================================================
-- Capture every row that COULD be touched, so 052_rollback can restore
-- exact pre-migration values regardless of how many UPDATEs land. Snapshot
-- table is idempotent: CREATE IF NOT EXISTS + DELETE before re-INSERT.
CREATE TABLE IF NOT EXISTS jpi_exclusion_rules_pre052_snapshot (
    rule_id    TEXT PRIMARY KEY,
    program_a  TEXT,
    program_b  TEXT,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now'))
);

DELETE FROM jpi_exclusion_rules_pre052_snapshot;

INSERT INTO jpi_exclusion_rules_pre052_snapshot (rule_id, program_a, program_b)
SELECT rule_id, program_a, program_b
  FROM jpi_exclusion_rules
 WHERE program_a IS NOT NULL OR program_b IS NOT NULL;

-- ============================================================================
-- BACKFILL (machine-resolvable rows ONLY — unambiguous primary_name match)
-- ============================================================================

-- 1) program_a: legacy human name → jpi_programs.unified_id (10 rows expected)
UPDATE jpi_exclusion_rules
   SET program_a = (
       SELECT p.unified_id
         FROM jpi_programs p
        WHERE p.primary_name = jpi_exclusion_rules.program_a
        LIMIT 1
   )
 WHERE program_a IS NOT NULL
   AND program_a NOT LIKE 'UNI-%'
   AND program_a NOT LIKE 'certification:%'
   AND (
       SELECT COUNT(*) FROM jpi_programs p2
        WHERE p2.primary_name = jpi_exclusion_rules.program_a
   ) = 1;

-- 2) program_b: legacy human name → jpi_programs.unified_id (6 rows expected)
UPDATE jpi_exclusion_rules
   SET program_b = (
       SELECT p.unified_id
         FROM jpi_programs p
        WHERE p.primary_name = jpi_exclusion_rules.program_b
        LIMIT 1
   )
 WHERE program_b IS NOT NULL
   AND program_b NOT LIKE 'UNI-%'
   AND program_b NOT LIKE 'certification:%'
   AND (
       SELECT COUNT(*) FROM jpi_programs p2
        WHERE p2.primary_name = jpi_exclusion_rules.program_b
   ) = 1;

-- ============================================================================
-- POST-APPLY VERIFY  (run after — same lines, SELECT-only, expect deltas)
-- ============================================================================
-- SELECT 'post_apply_program_a_uni'   AS k, COUNT(*) FROM jpi_exclusion_rules WHERE program_a LIKE 'UNI-%';
-- SELECT 'post_apply_program_b_uni'   AS k, COUNT(*) FROM jpi_exclusion_rules WHERE program_b LIKE 'UNI-%';
-- Expect program_a UNI count: 13 → 23 ; program_b UNI count: 13 → 19.
-- Any deviation means jpi_programs primary_name dupe shape changed since
-- 2026-04-25 verify; pause and re-audit before proceeding to P0.2.
