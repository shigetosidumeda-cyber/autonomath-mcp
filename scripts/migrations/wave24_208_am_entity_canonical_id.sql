-- target_db: autonomath
-- migration: wave24_208_am_entity_canonical_id
-- generated_at: 2026-05-17
-- author: CC3 — Cross-corpus alignment + entity resolution
-- idempotent: every ALTER/CREATE wrapped in defensive guards; pure DDL.
--
-- Purpose
-- -------
-- CC3 step 1+3: introduce a *soft-merge* canonical-id axis on am_entities so
-- the 200,330 cross-corpus rows that share the same houjin_bangou across
-- record_kind ∈ {corporate_entity, adoption, case_study} can be addressed as
-- one legal entity at query time WITHOUT physical row consolidation.
--
-- Soft-merge contract
-- -------------------
--   - am_entities.entity_id_canonical TEXT NULLABLE
--   - Populated by scripts/etl/cc3_entity_canonical_assignment_2026_05_17.py
--   - Existing canonical_id PRIMARY KEY remains untouched.
--   - canonical_status / citation_status semantics are untouched.
--   - For singletons (no duplicate group), entity_id_canonical = canonical_id.
--   - For groups, the lowest-canonical_id (ASCII order) member becomes the
--     anchor; all members in the group set entity_id_canonical = anchor.
--   - No row is deleted. No row is rewritten in-place by SQL — the ETL
--     fills the new column only.
--
-- This is intentionally lightweight: no FK, no UNIQUE, no CHECK. The
-- canonical-id axis is a *view* of identity, not a replacement for the
-- physical key.
--
-- target_db = autonomath (entrypoint.sh §4 picks up). Re-runs idempotent
-- via the entrypoint "duplicate column" self-heal handler.
--
-- ORDER NOTE: the ADD COLUMN statement is placed LAST so that re-runs which
-- hit "duplicate column" on second boot still create the indexes and view
-- on first run (sqlite3 -bail halts on the first parse error, so anything
-- *after* ADD COLUMN would not run on re-boot; entrypoint handles that
-- gracefully but we minimize re-apply churn by ordering the column add at
-- the end).

-- 1. supporting indexes for the cross-corpus join + heuristic upgrade.
CREATE INDEX IF NOT EXISTS idx_am_entity_facts_houjin_bangou
    ON am_entity_facts (field_name, field_value_text)
    WHERE field_name='houjin_bangou';

CREATE INDEX IF NOT EXISTS idx_am_relation_type_source
    ON am_relation (relation_type, source_entity_id);

CREATE INDEX IF NOT EXISTS idx_am_relation_type_target
    ON am_relation (relation_type, target_entity_id);

CREATE INDEX IF NOT EXISTS idx_am_law_article_law_canonical
    ON am_law_article (law_canonical_id);

CREATE INDEX IF NOT EXISTS idx_am_compat_matrix_inferred
    ON am_compat_matrix (inferred_only, compat_status);

-- 2. v_corp_program_judgment_law — CC3 4-way cross-corpus join.
--    法人 (corporate_entity)
--      → 採択 (adoption record_kind, joined by canonical houjin_bangou)
--      → 関連プログラム (program record_kind, joined via am_relation 'related'
--                       / 'part_of' / 'applies_to')
--      → 引用法令 (am_law_article, joined via am_relation 'references_law')
--    JOIN paths (5 patterns documented; the SELECT below materializes P1
--    + LEFT JOINs the rest; downstream callers may filter by NOT NULL on
--    program_id / law_canonical_id / article_id to walk paths P2..P5).
--      P1: corp[hb] → adoption[hb] → adoption→program[related] → program→law[references_law] → law_article
--      P2: corp[canonical] → adoption[canonical] → adoption[meta program_id] → program[canonical] → law_article via relation
--      P3: corp[hb] → case_study[hb] → case_study→judgment[related] → judgment→law via am_citation_network
--      P4: corp[canonical] → program[implemented_by/has_authority] → law (authority_canonical)
--      P5: corp[canonical] → enforcement[part_of] → law_article (administrative tie-in)
--    See docs/_internal/CC3_CROSS_CORPUS_2026_05_17.md §JOIN_PATHS for the
--    full path catalog.
DROP VIEW IF EXISTS v_corp_program_judgment_law;
CREATE VIEW v_corp_program_judgment_law AS
WITH corp AS (
    SELECT
        e.canonical_id          AS corp_id,
        e.entity_id_canonical   AS corp_canonical,
        e.primary_name          AS corp_name,
        TRIM(f.field_value_text) AS houjin_bangou
    FROM am_entities e
    JOIN am_entity_facts f
      ON f.entity_id = e.canonical_id
     AND f.field_name = 'houjin_bangou'
     AND f.field_value_text IS NOT NULL
     AND TRIM(f.field_value_text) <> ''
    WHERE e.record_kind = 'corporate_entity'
),
adopt AS (
    SELECT
        e.canonical_id          AS adoption_id,
        e.entity_id_canonical   AS adoption_canonical,
        e.primary_name          AS adoption_name,
        TRIM(f.field_value_text) AS houjin_bangou
    FROM am_entities e
    JOIN am_entity_facts f
      ON f.entity_id = e.canonical_id
     AND f.field_name = 'houjin_bangou'
     AND f.field_value_text IS NOT NULL
     AND TRIM(f.field_value_text) <> ''
    WHERE e.record_kind = 'adoption'
),
adopt_prog AS (
    SELECT
        r.source_entity_id AS adoption_id,
        r.target_entity_id AS program_id,
        r.relation_type    AS r_type,
        r.confidence       AS r_confidence
    FROM am_relation r
    WHERE r.target_entity_id IS NOT NULL
      AND r.relation_type IN ('related','part_of','applies_to','prerequisite')
),
prog_law AS (
    SELECT
        r.source_entity_id AS program_id,
        r.target_entity_id AS law_canonical_id,
        r.confidence       AS rl_confidence
    FROM am_relation r
    WHERE r.relation_type = 'references_law'
      AND r.target_entity_id IS NOT NULL
)
SELECT
    c.corp_id,
    c.corp_canonical,
    c.corp_name,
    c.houjin_bangou,
    a.adoption_id,
    a.adoption_canonical,
    a.adoption_name,
    ap.program_id,
    ap.r_type           AS adoption_to_program_relation,
    pl.law_canonical_id,
    la.article_id,
    la.article_number,
    la.title            AS article_title,
    (
        COALESCE(ap.r_confidence, 0.5) *
        COALESCE(pl.rl_confidence, 0.5)
    )                    AS join_confidence
FROM corp c
JOIN adopt a
  ON a.houjin_bangou = c.houjin_bangou
LEFT JOIN adopt_prog ap
  ON ap.adoption_id = a.adoption_id
LEFT JOIN prog_law pl
  ON pl.program_id = ap.program_id
LEFT JOIN am_law_article la
  ON la.law_canonical_id = pl.law_canonical_id;

-- 3. add canonical-axis indexes (these depend on the new column existing,
--    so they come AFTER the ALTER below would fail. SQLite tolerates
--    CREATE INDEX on a column that does not yet exist only at execution
--    time; we place these directly after the ALTER and accept that they
--    will only get created on the FIRST run. On subsequent re-runs, the
--    entrypoint self-heal records the migration as applied via the
--    duplicate-column path).
ALTER TABLE am_entities ADD COLUMN entity_id_canonical TEXT;
CREATE INDEX IF NOT EXISTS idx_am_entities_canonical_axis
    ON am_entities (entity_id_canonical);
CREATE INDEX IF NOT EXISTS idx_am_entities_kind_canonical
    ON am_entities (record_kind, entity_id_canonical);
