-- target_db: autonomath
-- migration 115_source_manifest_view
--
-- Source Manifest view — backs `GET /v1/source_manifest/{program_id}` and
-- the `get_source_manifest` MCP tool. Per docs/_internal/value_maximization
-- _plan_no_llm_api.md §7.7 + §28.1, every value (制度 detail, eligibility,
-- amount, deadline) needs a per-field citation envelope. Today, the
-- per-fact provenance column `am_entity_facts.source_id` is largely NULL
-- (1.12M / 6.12M = ~18.3% filled, with ZERO program-fact rows populated as
-- of 2026-04-30). The view honestly emits the sparse signal so callers can
-- reason about coverage rather than us hiding it.
--
-- Why the view does NOT join `programs`
-- -------------------------------------
-- programs lives in jpintel.db; autonomath.db carries the mirrored
-- `jpi_programs` (13,578 rows, mig 032). Cross-DB ATTACH is forbidden
-- (CLAUDE.md). The endpoint Python-side resolves `program_id` → entity
-- canonical_id via:
--   * `entity_id_map` (UNI-... ↔ program:..., 6,339 rows) when the caller
--     passes a unified_id
--   * direct match when the caller passes an `am_canonical_id` already
--   * `jpi_programs.unified_id` for the primary_name + primary_source_url
--     fallback when no entity link exists
--
-- The view's job is the per-entity rollup: aggregate `am_entity_facts ↔
-- am_source` (per-fact provenance, sparse) plus `am_entity_source ↔
-- am_source` (entity-level rollup, dense for programs). The endpoint
-- joins THIS view's rows with `jpi_programs` in Python.
--
-- Sparse-data posture
-- -------------------
-- field_paths_covered will be empty (`[]`) for programs whose facts have
-- no source_id set yet. That's intentional — the API surfaces a
-- `_disclaimer` explaining "manifest reflects per-fact provenance where
-- source_id is populated; unpopulated facts inherit the program's
-- primary_source_url" so downstream LLMs / auditors can choose to fall
-- back to the program-row primary_source_url without us pretending we
-- have richer provenance than we do. See feedback_no_fake_data.md.
--
-- Idempotency
-- -----------
-- SQLite has no `CREATE OR REPLACE VIEW`. We DROP IF EXISTS then CREATE,
-- both inside the same script. The entrypoint self-heal loop applies
-- migrations once per migration_id (recorded in schema_migrations); a
-- second invocation with the same id is skipped. A manual re-apply
-- (e.g. operator running `sqlite3 autonomath.db < 115_*.sql`) is also
-- safe — DROP is a no-op when the view doesn't exist.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- v_program_source_manifest — per-entity rollup of fact-level + entity-level
-- provenance, JSON-aggregated for one-shot READ from the API endpoint.
--
-- Columns:
--   entity_id              — am_entities.canonical_id (e.g. 'program:...')
--   field_paths_covered    — JSON array of distinct field_name entries that
--                            have source_id populated. Empty array when
--                            zero facts have provenance pinned.
--   source_count           — DISTINCT source_id count across both per-fact
--                            (am_entity_facts.source_id) and entity-level
--                            (am_entity_source.source_id) signals.
--   latest_fetched_at      — MAX(am_source.first_seen) across all linked
--                            sources. NULL when no source links exist.
--   oldest_fetched_at      — MIN(am_source.first_seen) across the same.
--   unique_publishers      — DISTINCT count of am_source.domain values
--                            (proxy for "publisher" since am_source has no
--                            dedicated publisher column — domain is the
--                            stable identifier; same-publisher subdomains
--                            collapse here).
--   license_set            — JSON array of distinct license values across
--                            linked sources. Each value is a license enum
--                            string (pdl_v1.0 / cc_by_4.0 /
--                            gov_standard_v2.0 / public_domain /
--                            proprietary / unknown) or 'unknown_null' for
--                            am_source rows whose license column is NULL.
--
-- Performance
-- -----------
-- The view UNION-ALLs two CTE sources (fact-level + entity-level). On the
-- 84,327 program-fact rows + ~280k am_entity_source rows the rollup
-- completes well under 1s with the existing indexes
-- (idx_am_efacts_source, ix_am_entity_source_src). No new indexes are
-- created — the view is on-demand, not materialized.

DROP VIEW IF EXISTS v_program_source_manifest;

CREATE VIEW v_program_source_manifest AS
WITH
    -- Per-fact provenance signal: only rows where source_id IS NOT NULL.
    -- This is the "sparse" half — 0 program facts populate this CTE today.
    fact_links AS (
        SELECT
            f.entity_id        AS entity_id,
            f.field_name       AS field_name,
            f.source_id        AS source_id
        FROM am_entity_facts f
        WHERE f.source_id IS NOT NULL
    ),
    -- Entity-level provenance signal: am_entity_source rolls up the entity
    -- to its primary / pdf / application sources via role. Field is NULL
    -- here because the linkage is at the entity granularity, not per-field.
    entity_links AS (
        SELECT
            es.entity_id       AS entity_id,
            NULL               AS field_name,
            es.source_id       AS source_id
        FROM am_entity_source es
    ),
    -- Combined view; we keep field_name distinct from NULL so the
    -- field_paths_covered aggregate only sums per-fact links.
    all_links AS (
        SELECT entity_id, field_name, source_id FROM fact_links
        UNION ALL
        SELECT entity_id, field_name, source_id FROM entity_links
    ),
    -- Source detail per link (one row per (entity_id, source_id) pair).
    -- DISTINCT collapses both halves of the UNION into one row per source
    -- so source_count / latest_fetched_at don't double-count when the
    -- same source is referenced both per-fact and entity-level.
    distinct_entity_sources AS (
        SELECT DISTINCT
            al.entity_id       AS entity_id,
            al.source_id       AS source_id,
            s.domain           AS domain,
            s.first_seen       AS first_seen,
            COALESCE(s.license, 'unknown_null') AS license
        FROM all_links al
        JOIN am_source s ON s.id = al.source_id
    )
SELECT
    al.entity_id                                         AS entity_id,
    -- Per-fact field_paths only (entity_links contribute NULL field_name
    -- and are filtered out by the WHERE on the JSON_GROUP_ARRAY's input).
    (
        SELECT json_group_array(DISTINCT fl.field_name)
        FROM fact_links fl
        WHERE fl.entity_id = al.entity_id
          AND fl.field_name IS NOT NULL
    )                                                    AS field_paths_covered,
    (
        SELECT COUNT(DISTINCT des.source_id)
        FROM distinct_entity_sources des
        WHERE des.entity_id = al.entity_id
    )                                                    AS source_count,
    (
        SELECT MAX(des.first_seen)
        FROM distinct_entity_sources des
        WHERE des.entity_id = al.entity_id
    )                                                    AS latest_fetched_at,
    (
        SELECT MIN(des.first_seen)
        FROM distinct_entity_sources des
        WHERE des.entity_id = al.entity_id
    )                                                    AS oldest_fetched_at,
    (
        SELECT COUNT(DISTINCT des.domain)
        FROM distinct_entity_sources des
        WHERE des.entity_id = al.entity_id
          AND des.domain IS NOT NULL
    )                                                    AS unique_publishers,
    (
        SELECT json_group_array(DISTINCT des.license)
        FROM distinct_entity_sources des
        WHERE des.entity_id = al.entity_id
    )                                                    AS license_set
FROM all_links al
GROUP BY al.entity_id;

-- ---------------------------------------------------------------------------
-- Migration bookkeeping
-- ---------------------------------------------------------------------------
-- entrypoint.sh self-heal loop records this migration id in
-- schema_migrations after the first successful boot apply. The DROP +
-- CREATE pattern above is safe to re-execute (idempotent) because no
-- writer holds a long-lived reference to the view.
