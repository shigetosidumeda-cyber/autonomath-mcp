-- target_db: autonomath
-- migration wave24_153_am_entity_appearance_count
--
-- Cross-table entity resolution rollup (2026-05-05).
--
-- For every distinct 13-digit houjin_bangou seen across the autonomath +
-- mirrored-jpintel corporate surfaces, materialise:
--
--   (a) `v_houjin_appearances`  — runtime view, one row per houjin_bangou
--                                  with table_count + JSON list of source
--                                  tables. Cheap on read, no maintenance
--                                  cost (recomputes on query).
--   (b) `am_entity_appearance_count` — physical table populated by
--                                  scripts/etl/populate_entity_appearance_count.py
--                                  so callers (entity_id_map enricher,
--                                  /api/v1/houjin/{bangou} aggregator,
--                                  customer narrative) can JOIN without
--                                  paying the UNION cost on every request.
--
-- Sources scanned (all live in autonomath.db so the view is single-DB):
--
--   * jpi_invoice_registrants     (jpintel mirror, NTA invoice 13桁 truth)
--   * jpi_case_studies            (jpintel mirror)
--   * jpi_houjin_master           (jpintel mirror, NTA corp registry)
--   * jpi_adoption_records        (autonomath canonical adoption ledger)
--   * am_entities (record_kind='corporate_entity')
--   * am_entities (record_kind='invoice_registrant')
--   * am_entities (record_kind='adoption')
--
-- jpi_enforcement_cases is intentionally excluded: recipient_houjin_bangou
-- is null for 100% of rows (MHLW disclosure withholds 13桁), so the table
-- contributes zero appearances and only inflates UNION cost.
--
-- Idempotent (CREATE … IF NOT EXISTS / DROP VIEW IF EXISTS). Safe to re-run
-- on every Fly boot via entrypoint.sh §4. The view is dropped+recreated so
-- a future column edit reapplies cleanly.

DROP VIEW IF EXISTS v_houjin_appearances;

CREATE VIEW v_houjin_appearances AS
WITH appearances AS (
    SELECT DISTINCT houjin_bangou, 'jpi_invoice_registrants' AS source_table
      FROM jpi_invoice_registrants
     WHERE length(houjin_bangou) = 13
    UNION ALL
    SELECT DISTINCT houjin_bangou, 'jpi_case_studies'
      FROM jpi_case_studies
     WHERE length(houjin_bangou) = 13
    UNION ALL
    SELECT DISTINCT houjin_bangou, 'jpi_houjin_master'
      FROM jpi_houjin_master
     WHERE length(houjin_bangou) = 13
    UNION ALL
    SELECT DISTINCT houjin_bangou, 'jpi_adoption_records'
      FROM jpi_adoption_records
     WHERE length(houjin_bangou) = 13
    UNION ALL
    SELECT DISTINCT
           json_extract(raw_json, '$.houjin_bangou') AS houjin_bangou,
           'am_entities_corporate' AS source_table
      FROM am_entities
     WHERE record_kind = 'corporate_entity'
       AND length(json_extract(raw_json, '$.houjin_bangou')) = 13
    UNION ALL
    SELECT DISTINCT
           json_extract(raw_json, '$.houjin_bangou') AS houjin_bangou,
           'am_entities_invoice' AS source_table
      FROM am_entities
     WHERE record_kind = 'invoice_registrant'
       AND length(json_extract(raw_json, '$.houjin_bangou')) = 13
    UNION ALL
    SELECT DISTINCT
           json_extract(raw_json, '$.houjin_bangou') AS houjin_bangou,
           'am_entities_adoption' AS source_table
      FROM am_entities
     WHERE record_kind = 'adoption'
       AND length(json_extract(raw_json, '$.houjin_bangou')) = 13
)
SELECT houjin_bangou,
       COUNT(DISTINCT source_table) AS table_count,
       json_group_array(DISTINCT source_table) AS tables_json
  FROM appearances
 GROUP BY houjin_bangou;

CREATE TABLE IF NOT EXISTS am_entity_appearance_count (
    houjin_bangou     TEXT PRIMARY KEY,
    appearance_count  INTEGER NOT NULL,
    tables_json       TEXT NOT NULL,
    computed_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_appearance_count_count
    ON am_entity_appearance_count(appearance_count DESC);
