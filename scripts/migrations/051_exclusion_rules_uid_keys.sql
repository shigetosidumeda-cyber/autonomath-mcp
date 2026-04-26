-- migration 051: exclusion_rules name/slug → unified_id key augmentation
--                 (P0-3 / J10 / K4)
--
-- Finding (2026-04-25 audit J10/K4): of 181 exclusion_rules rows, only
-- 13 program_a entries reference a unified_id (UNI-...). The remaining
-- 168 use either an English slug ('keiei-kaishi-shikin') or a Japanese
-- canonical name ('IT導入補助金2025 (通常枠)'). When MCP clients call
-- check_exclusions(program_ids=['UNI-2611050f9a']) — the natural shape
-- after search_programs — the rule lookup compares slug-keyed program_a
-- against UNI-keyed input and returns 0 hits. Silent fraud risk.
--
-- Fix: ADD columns program_a_uid / program_b_uid so each row carries
-- BOTH the legacy display key (program_a, kept verbatim, never deleted)
-- AND the resolved unified_id when programs.primary_name matches. The
-- check_exclusions logic (server.py + api/exclusions.py) is updated in
-- the same wave to do dual-key matching: caller-provided IDs are
-- expanded with both unified_ids and primary_names so matches succeed
-- regardless of which key the caller passes.
--
-- This migration is additive and idempotent:
--   * no exclusion_rules rows are deleted or rewritten in place
--   * ALTER TABLE ADD COLUMN with IF NOT EXISTS semantics: re-runs are a
--     no-op once the migration runner records the file (the runner's
--     duplicate-column fallback handles re-application gracefully)
--   * UPDATE only sets program_a_uid / program_b_uid where they are NULL
--
-- Resolution strategy:
--   1. If program_a already starts with 'UNI-' → copy to program_a_uid.
--   2. Else if exactly one programs.primary_name == program_a → use that
--      programs.unified_id. Ties (multiple primary_name matches) leave
--      the column NULL — application logic falls back to the legacy
--      string-equality path.
--
-- Unresolved rows (NULL after this migration) are an honest report of
-- the data drift: they're either Japanese names with year/round suffixes
-- that don't match the canonical primary_name, or non-program category
-- strings ('認定新規就農者', etc.) that intentionally have no programs
-- row. The check_exclusions code path treats both legacy strings and
-- _uid columns simultaneously, so behavior is preserved.

ALTER TABLE exclusion_rules ADD COLUMN program_a_uid TEXT;
ALTER TABLE exclusion_rules ADD COLUMN program_b_uid TEXT;

CREATE INDEX IF NOT EXISTS idx_exclusion_program_a_uid
    ON exclusion_rules(program_a_uid);
CREATE INDEX IF NOT EXISTS idx_exclusion_program_b_uid
    ON exclusion_rules(program_b_uid);

-- 1. Copy already-UNI keys verbatim (cheap path).
UPDATE exclusion_rules
   SET program_a_uid = program_a
 WHERE program_a_uid IS NULL
   AND program_a LIKE 'UNI-%';

UPDATE exclusion_rules
   SET program_b_uid = program_b
 WHERE program_b_uid IS NULL
   AND program_b LIKE 'UNI-%';

-- 2. Resolve via primary_name. Skip when multiple programs share the
--    same primary_name to avoid ambiguous mappings.
UPDATE exclusion_rules
   SET program_a_uid = (
       SELECT p.unified_id
         FROM programs p
        WHERE p.primary_name = exclusion_rules.program_a
        LIMIT 1
   )
 WHERE program_a_uid IS NULL
   AND program_a IS NOT NULL
   AND program_a NOT LIKE 'UNI-%'
   AND (
       SELECT COUNT(*) FROM programs p2
        WHERE p2.primary_name = exclusion_rules.program_a
   ) = 1;

UPDATE exclusion_rules
   SET program_b_uid = (
       SELECT p.unified_id
         FROM programs p
        WHERE p.primary_name = exclusion_rules.program_b
        LIMIT 1
   )
 WHERE program_b_uid IS NULL
   AND program_b IS NOT NULL
   AND program_b NOT LIKE 'UNI-%'
   AND (
       SELECT COUNT(*) FROM programs p2
        WHERE p2.primary_name = exclusion_rules.program_b
   ) = 1;
