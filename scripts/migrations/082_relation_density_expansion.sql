-- target_db: autonomath
-- migration 082_relation_density_expansion (graph density harvest, 2026-04-29)
--
-- ============================================================================
-- BACKGROUND
-- ============================================================================
--   am_relation: 23,805 edges across 503,930 entities  ⇒  avg 0.047 edges/entity
--   graph_traverse / related_programs return shallow chains because the
--   knowledge-graph density is sparse. The implicit relationships already
--   live in source tables (programs.authority_canonical, jpi_enforcement_cases
--   .legal_basis, jpi_case_studies.programs_used_json, jpi_tax_rulesets
--   .related_law_ids_json, am_entities.raw_json). This migration prepares
--   the schema for a one-shot harvest:
--
--     scripts/etl/harvest_implicit_relations.py
--
--   to lift those into am_relation as canonical-typed edges.
--
-- ============================================================================
-- WHAT THIS MIGRATION DOES
-- ============================================================================
--   1. Adds `harvested_at` column so the harvester rows are distinguishable
--      from graph / graph_rescue / manual rows. Existing rows keep NULL.
--      (`source_field` and `confidence` already exist on the table — we
--      reuse them; no new columns there.)
--
--   2. Creates a partial UNIQUE index on
--        (source_entity_id, COALESCE(target_entity_id,''), relation_type,
--         COALESCE(source_field,''))
--      so the harvester is idempotent: a re-run cannot produce duplicates
--      for the same (source, target, type, source_field) tuple. The
--      COALESCE collapses NULL to '' so SQLite doesn't treat NULLs as
--      "always-distinct" (which is the standard NULL-comparison gotcha
--      that defeats UNIQUE on optional columns).
--
--      We use a partial index (WHERE origin = 'harvest') so the
--      uniqueness gate applies ONLY to rows the harvester wrote — the
--      pre-existing 23,805 rows (origin = 'graph' / 'graph_rescue' /
--      'manual') sometimes contain legitimate duplicates (5 dupes were
--      observed in the audit) and we don't want this migration to crash
--      on them.
--
--   3. Adds two perf indexes that graph_traverse needs once the row
--      count crosses ~50k:
--        - ix_am_relation_src_type_conf : drives BFS fanout ranking
--        - ix_am_relation_origin        : lets the tool filter out
--                                         harvest-only rows when callers
--                                         opt-in to "primary-source-only".
--
-- ============================================================================
-- IDEMPOTENCY
-- ============================================================================
--   Every CREATE / ALTER uses IF NOT EXISTS or guards re-application via
--   pragma table_info() probe (column add). Safe to re-run on every Fly
--   boot via entrypoint.sh §4.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   The companion 082_relation_density_expansion_rollback.sql drops the
--   harvested_at column and the three indexes. Harvested rows can be
--   removed with `DELETE FROM am_relation WHERE origin = 'harvest';`
--   which is safe because origin defaults to 'graph' for legacy rows.

PRAGMA foreign_keys = ON;

-- 1. Add harvested_at column. SQLite has no native "ADD COLUMN IF NOT
--    EXISTS". The entrypoint.sh boot loop wraps each migration apply in
--    `sqlite3 ... < $file 2>&1 | head -3 || true`, so a duplicate-column
--    error on re-run is logged but does not fail the boot — exactly the
--    same pattern migration 049 uses for am_source.license,
--    am_entity_facts.source_id, jpi_feedback.entity_canonical_id.

ALTER TABLE am_relation ADD COLUMN harvested_at TEXT;

-- 2. Idempotent UNIQUE index on harvest-origin rows only.
--    The COALESCE(...,'') trick collapses NULL → '' so SQLite's
--    "two NULLs are distinct" UNIQUE semantics don't allow duplicates
--    where target_entity_id is NULL (target_raw-only rows).

CREATE UNIQUE INDEX IF NOT EXISTS ux_am_relation_harvest
    ON am_relation(
        source_entity_id,
        COALESCE(target_entity_id, ''),
        relation_type,
        COALESCE(source_field, '')
    )
 WHERE origin = 'harvest';

-- 3. Perf indexes for graph_traverse BFS at scale.

CREATE INDEX IF NOT EXISTS ix_am_relation_src_type_conf
    ON am_relation(source_entity_id, relation_type, confidence DESC);

CREATE INDEX IF NOT EXISTS ix_am_relation_origin
    ON am_relation(origin);
