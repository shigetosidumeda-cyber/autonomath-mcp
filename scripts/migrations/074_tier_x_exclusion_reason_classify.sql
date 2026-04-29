-- migration 074: Tier=X exclusion_reason classification (Wave 17 P0)
--
-- Finding (2026-04-26 Wave 17 data freshness audit):
--   tier=X (quarantine) row count = 1,741. Of those:
--     1,206 (69.3%) carry the opaque marker
--                   exclusion_reason='tier_x_quarantine_migration_050'
--       509 (29.2%) carry NULL/empty exclusion_reason
--        26 ( 1.5%) carry the free-text 'legacy: 令和4年度予算表記'
--   Operator opening the row cannot tell WHY it is in quarantine.
--   This is a P0: silent fraud risk (we hide the row but can't justify why).
--
-- Fix: backfill exclusion_reason on the 1,715 unclassified rows
-- (opaque marker + NULL/empty) to a 9-value enum. The 26 already-classified
-- 'legacy' rows are mapped to the enum value `legacy_year_budget` so all
-- tier=X rows end up enum-compliant. Non-X excluded rows keep their existing
-- free-text reasons (rich curator notes worth preserving).
--
-- Enum values (also seeded into reference table `exclusion_reason_codes`):
--   no_source_url        — source_url is NULL/empty (no primary citation)
--   external_info_entry  — UNI-ext-* prefix: statistics/news, never was a
--                          program (875 in opaque batch)
--   no_amount_data       — both amount_max + amount_min NULL (unscoped)
--   unknown_target       — target_types_json empty/[] (no eligibility shape)
--   legacy_year_budget   — name encodes 令和4年度/令和3年度/平成 budget year
--   dead_official_url    — official_url confirmed 4xx via source_last_check_status
--   duplicate_of         — name contains '重複' marker
--   insufficient_data    — multiple gaps but no single dominant signal
--   unclassified_legacy  — fallthrough: needs human review
--   manual_quarantine    — reserved: operator manually quarantined
--
-- Order of UPDATE matters: more-specific rules run before more-general ones,
-- and each rule guards on `exclusion_reason IN ('tier_x_quarantine_migration_050','')`
-- OR `exclusion_reason IS NULL` so it only touches the target subset and is
-- idempotent (re-runs flip zero rows).
--
-- Soft enforcement: a trigger raises if a NEW exclusion_reason on a tier=X
-- row is not in the enum table. Curator free-text on non-X rows is unaffected
-- (the trigger checks tier=X only). The trigger is idempotent on re-create.

------------------------------------------------------------------------
-- 1. Reference enum table (idempotent, lookup + documentation)
------------------------------------------------------------------------

-- Pre-flight: `source_last_check_status` is required by the dead_official_url
-- backfill rule below. The column was historically added by
-- `scripts/refresh_sources.py` at startup, but a fresh prod DB whose first
-- run is this migration (e.g. test_lineage / a CI-rebuild) fails with
-- "no such column". Add it idempotently here. We can't use `ALTER TABLE
-- IF NOT EXISTS`, so the migration runner's duplicate-column-skip path
-- (see migrate.py:223) catches the re-run as a no-op.
ALTER TABLE programs ADD COLUMN source_last_check_status INTEGER;

CREATE TABLE IF NOT EXISTS exclusion_reason_codes (
    code        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO exclusion_reason_codes (code, description) VALUES
  ('no_source_url',        'source_url is NULL/empty: no primary citation available'),
  ('external_info_entry',  'UNI-ext-* prefix: statistics/news/reference, not a program'),
  ('no_amount_data',       'both amount_max_man_yen and amount_min_man_yen are NULL'),
  ('unknown_target',       'target_types_json empty/[]: eligibility shape unknown'),
  ('legacy_year_budget',   'name encodes a past fiscal year budget (令和4/令和3/平成 etc.)'),
  ('dead_official_url',    'official_url confirmed 4xx via source_last_check_status'),
  ('duplicate_of',         'name contains explicit 重複 marker'),
  ('insufficient_data',    'multiple data gaps with no single dominant cause'),
  ('unclassified_legacy',  'classifier fallthrough: needs human review'),
  ('manual_quarantine',    'operator manually quarantined for ad-hoc reason');

------------------------------------------------------------------------
-- 2. Backfill: opaque + NULL/empty rows on tier=X
--    Predicate: tier='X' AND (exclusion_reason='tier_x_quarantine_migration_050'
--                             OR exclusion_reason IS NULL
--                             OR exclusion_reason='')
--    More-specific rules first (so they win the assignment).
------------------------------------------------------------------------

-- 2a. external_info_entry (UNI-ext- prefix). Highest specificity.
UPDATE programs
   SET exclusion_reason = 'external_info_entry'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND unified_id LIKE 'UNI-ext-%';

-- 2b. legacy_year_budget (name carries old fiscal-year marker).
UPDATE programs
   SET exclusion_reason = 'legacy_year_budget'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND (
       primary_name LIKE '%令和4年度%'
    OR primary_name LIKE '%令和3年度%'
    OR primary_name LIKE '%令和2年度%'
    OR primary_name LIKE '%令和元年度%'
    OR primary_name LIKE '%平成%年度%'
   );

-- 2c. duplicate_of (explicit duplicate marker in name).
UPDATE programs
   SET exclusion_reason = 'duplicate_of'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND primary_name LIKE '%重複%';

-- 2d. dead_official_url (404 confirmed via source_last_check_status).
UPDATE programs
   SET exclusion_reason = 'dead_official_url'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND source_last_check_status IS NOT NULL
   AND source_last_check_status >= 400;

-- 2e. no_source_url (no primary citation at all).
UPDATE programs
   SET exclusion_reason = 'no_source_url'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND (source_url IS NULL OR source_url = '');

-- 2f. no_amount_data (both amount fields NULL).
UPDATE programs
   SET exclusion_reason = 'no_amount_data'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND amount_max_man_yen IS NULL
   AND amount_min_man_yen IS NULL;

-- 2g. unknown_target (target_types_json empty / []).
UPDATE programs
   SET exclusion_reason = 'unknown_target'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '')
   AND (target_types_json IS NULL
        OR target_types_json = ''
        OR target_types_json = '[]');

-- 2h. unclassified_legacy (fallthrough — opaque/NULL still after 2a-2g).
UPDATE programs
   SET exclusion_reason = 'unclassified_legacy'
 WHERE tier = 'X'
   AND (exclusion_reason = 'tier_x_quarantine_migration_050'
        OR exclusion_reason IS NULL
        OR exclusion_reason = '');

------------------------------------------------------------------------
-- 3. Normalize the 26 existing 'legacy: 令和4年度予算表記' rows on tier=X
--    onto the enum. (Non-X tier=excluded rows keep their existing
--    'legacy: 令和4年度予算表記' / scope: / pinpoint: / phantom: free-text:
--    those carry curator audit detail worth preserving.)
------------------------------------------------------------------------

UPDATE programs
   SET exclusion_reason = 'legacy_year_budget'
 WHERE tier = 'X'
   AND exclusion_reason = 'legacy: 令和4年度予算表記';

------------------------------------------------------------------------
-- 4. Soft enforcement trigger: raise if any future tier=X row is set to
--    a value not in the enum table. Curator-authored non-X free-text is
--    unaffected.
------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_programs_exclusion_reason_enum_x;
CREATE TRIGGER trg_programs_exclusion_reason_enum_x
BEFORE UPDATE OF exclusion_reason, tier ON programs
FOR EACH ROW
WHEN NEW.tier = 'X'
 AND NEW.exclusion_reason IS NOT NULL
 AND NEW.exclusion_reason != ''
 AND NEW.exclusion_reason NOT IN (
       SELECT code FROM exclusion_reason_codes
   )
BEGIN
    SELECT RAISE(ABORT,
        'exclusion_reason on tier=X must be one of exclusion_reason_codes.code');
END;

DROP TRIGGER IF EXISTS trg_programs_exclusion_reason_enum_x_ins;
CREATE TRIGGER trg_programs_exclusion_reason_enum_x_ins
BEFORE INSERT ON programs
FOR EACH ROW
WHEN NEW.tier = 'X'
 AND NEW.exclusion_reason IS NOT NULL
 AND NEW.exclusion_reason != ''
 AND NEW.exclusion_reason NOT IN (
       SELECT code FROM exclusion_reason_codes
   )
BEGIN
    SELECT RAISE(ABORT,
        'exclusion_reason on tier=X must be one of exclusion_reason_codes.code');
END;
