-- migration 050: Tier=X quarantine leak fix (P0-10 / K5)
--
-- Finding (2026-04-25 audit K5): 1,206 rows have tier='X' but excluded=0,
-- which means the quarantine tier leaks into search/listing surfaces that
-- only filter on excluded=0.
--
-- Semantic invariant: tier='X' is the QUARANTINE tier. It must never be
-- visible in user-facing surfaces. The two source-of-truth filters in the
-- codebase use either `tier IN ('S','A','B','C')` (preferred) or
-- `excluded=0`. Rows where the two disagree are silent fraud risk.
--
-- Fix: every tier='X' row gets excluded=1. The X→excluded=1 direction is
-- additive (no row is un-excluded), preserving lineage. Rows already
-- marked excluded stay excluded; only the 1,206 leaked rows flip.
--
-- This migration is idempotent: a second run flips zero rows.
--
-- Affected counts (pre-fix):
--   tier=X excluded=0  → 1,206  (LEAK, will flip to excluded=1)
--   tier=X excluded=1  →   535  (already correct, no change)
-- Post-fix expectation: tier=X excluded=0 = 0.

UPDATE programs
   SET excluded = 1,
       exclusion_reason = COALESCE(
           NULLIF(exclusion_reason, ''),
           'tier_x_quarantine_migration_050'
       )
 WHERE tier = 'X' AND excluded = 0;
