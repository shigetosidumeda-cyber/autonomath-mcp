-- target_db: autonomath
-- migration 159_am_id_bridge
--
-- ID-namespace bridge between jpi_adoption_records.program_id (UNI-* canonical
-- IDs from the jpintel namespace, e.g. "UNI-442fcccdd0") and the AutonoMath
-- matrix-resident namespace used by `am_compat_matrix.program_a_id` /
-- `program_b_id` (e.g. "certification:09_certification_programs:...",
-- "program:04_program_documents:...", "loan:...", "tax_measure:...").
--
-- W22-6 launch audit (2026-05-04) found that exclusion-rule + complementary
-- combo evaluation against the top 15 program combinations from
-- `jpi_adoption_records` returned 100% "matrix unmapped" because
-- `entity_id_map` only carries 6,339 UNI -> `program:*` rows (no
-- `certification:*` and partial `program:*` coverage). Fuzzy-name matching
-- against `am_entities.primary_name` recovers the missing edges.
--
-- bridge_kind enum:
--   * exact          -- already present in entity_id_map (1.0 confidence)
--   * fuzzy_name     -- token_set_ratio >= 0.85 against primary_name
--   * derived_keyword -- topical keyword overlap (kept for future use)
--   * manual         -- hand-curated overrides
--
-- Idempotent: CREATE * IF NOT EXISTS. Populator
-- (`scripts/etl/build_id_bridge.py`) uses INSERT OR REPLACE keyed on
-- (id_a, id_b). Safe to re-apply on every Fly boot via entrypoint.sh §4.
--
-- DOWN: see companion `159_am_id_bridge_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_id_bridge (
    id_a         TEXT NOT NULL,
    id_b         TEXT NOT NULL,
    bridge_kind  TEXT NOT NULL CHECK (bridge_kind IN (
                    'exact', 'fuzzy_name', 'derived_keyword', 'manual'
                 )),
    confidence   REAL NOT NULL DEFAULT 1.0
                 CHECK (confidence BETWEEN 0.0 AND 1.0),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (id_a, id_b)
);

CREATE INDEX IF NOT EXISTS ix_id_bridge_a ON am_id_bridge(id_a);
CREATE INDEX IF NOT EXISTS ix_id_bridge_b ON am_id_bridge(id_b);
CREATE INDEX IF NOT EXISTS ix_id_bridge_kind ON am_id_bridge(bridge_kind);
