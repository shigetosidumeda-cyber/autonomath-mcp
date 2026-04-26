-- target_db: autonomath
-- 052_perf_indexes.sql -- AutonoMath perf index codification (2026-04-25, Wave 3 perf audit).
--
-- Persists the 19 performance indexes from autonomath_staging/perf/indexes_to_add.sql
-- into the canonical migration sequence so a DB rebuild does not lose them.
-- All indexes were already applied to autonomath.db in-place during Wave 3 profiling
-- (2026-04-24); this migration is a no-op on the live DB but guarantees the indexes
-- come back if anyone replays migrations from scratch.
--
-- Naming: ix_am_<table>_<cols> (perf prefix 'ix_' to distinguish from baseline 'idx_').
-- All CREATE INDEX statements are IF NOT EXISTS, so safe to re-run.

BEGIN IMMEDIATE;

-- 1. am_entity_facts relation lookup (bind_i03 LIKE 'relation.%.to_name_raw').
CREATE INDEX IF NOT EXISTS ix_am_facts_relation_to_name_entity
    ON am_entity_facts(entity_id)
 WHERE field_name LIKE 'relation.%.to_name_raw';

CREATE INDEX IF NOT EXISTS ix_am_facts_relation_kind_entity
    ON am_entity_facts(entity_id)
 WHERE field_name LIKE 'relation.%.kind';

CREATE INDEX IF NOT EXISTS ix_am_facts_relation_prefix_entity
    ON am_entity_facts(entity_id, field_name)
 WHERE field_name LIKE 'relation.%';

-- 2. am_entity_facts covering index for batch hydration (entity_id + field_name).
CREATE INDEX IF NOT EXISTS ix_am_facts_entity_field_covering
    ON am_entity_facts(entity_id, field_name, field_value_text, field_value_numeric);

-- 3. am_entities composite indexes for list_open_programs / active_programs_at /
--    confidence-sorted FTS gating.
CREATE INDEX IF NOT EXISTS ix_am_entities_kind_name
    ON am_entities(record_kind, primary_name);

CREATE INDEX IF NOT EXISTS ix_am_entities_kind_confidence
    ON am_entities(record_kind, confidence DESC);

CREATE INDEX IF NOT EXISTS ix_am_entities_kind_topic
    ON am_entities(record_kind, source_topic);

CREATE INDEX IF NOT EXISTS ix_am_entities_kind_fetched
    ON am_entities(record_kind, fetched_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_entities_kind_auth_fetched
    ON am_entities(record_kind, authority_canonical, fetched_at DESC);

-- 4. am_entities.source_topic + record_kind reverse composite (bind_i02 narrow path).
CREATE INDEX IF NOT EXISTS ix_am_entities_topic_kind
    ON am_entities(source_topic, record_kind);

-- 6. am_alias canonical->alias reverse index (bind_i10).
CREATE INDEX IF NOT EXISTS ix_am_alias_canonical
    ON am_alias(canonical_id, entity_table);

-- 7. am_authority parent tree walk filtered by level (bind_i08).
CREATE INDEX IF NOT EXISTS ix_am_authority_level_parent
    ON am_authority(level, parent_id);

-- 8. am_law_reference (currently empty) -- prepared for graph promotion.
CREATE INDEX IF NOT EXISTS ix_am_law_reference_law_entity
    ON am_law_reference(law_canonical_id, entity_id)
 WHERE law_canonical_id IS NOT NULL;

-- 9. am_relation (currently empty) -- target-direction index.
CREATE INDEX IF NOT EXISTS ix_am_relation_tgt
    ON am_relation(target_entity_id, relation_type)
 WHERE target_entity_id IS NOT NULL;

-- 10. am_entity_source reverse covering for "which entities cite source X".
CREATE INDEX IF NOT EXISTS ix_am_entity_source_reverse
    ON am_entity_source(source_id, entity_id);

-- 11. Expression indexes for enum_values GROUP BY json_extract().
--     Collapse 277k-row SCAN to <10ms for authority/ministry/program_kind/prefecture.
CREATE INDEX IF NOT EXISTS ix_am_entities_json_authority_name
    ON am_entities(json_extract(raw_json, '$.authority_name'))
 WHERE json_extract(raw_json, '$.authority_name') IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_entities_json_ministry
    ON am_entities(json_extract(raw_json, '$.ministry'))
 WHERE json_extract(raw_json, '$.ministry') IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_entities_json_program_kind
    ON am_entities(json_extract(raw_json, '$.program_kind'))
 WHERE record_kind = 'program'
   AND json_extract(raw_json, '$.program_kind') IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_entities_json_prefecture
    ON am_entities(json_extract(raw_json, '$.prefecture'));

COMMIT;
