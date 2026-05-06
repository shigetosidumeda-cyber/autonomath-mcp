-- target_db: autonomath
-- migration 164_am_program_eligibility_predicate
--
-- Why this exists:
--   Customer LLMs currently re-derive eligibility from narrative text every
--   query: "does program X cover corp Y in 大阪府, 資本金1,000万円, 従業員10名,
--   建設業 (JSIC D)?". That walk consumes many input tokens because the LLM
--   has to read free-form 公募要領 prose and re-extract industry / region /
--   capital cap / employee cap / 業歴 each time.
--
--   This table caches a *machine-readable predicate* per program so a customer
--   tool call can return structured JSON the LLM evaluates with simple boolean
--   logic — no narrative re-reading, no re-extraction. Eligibility predicate
--   becomes a reusable artifact, dropping per-eval token cost.
--
-- Why a new table (not wave24_137):
--   wave24_137 created `am_program_eligibility_predicate` with one row per
--   predicate (predicate_kind / operator / value_num split into columns),
--   targeted at SQL filter UIs (apply_eligibility_chain_am consumer). This
--   migration carries a *single JSON blob per program* (predicate_json) for
--   LLM-side evaluation — orthogonal use case, different access pattern.
--   Both can coexist (the 137 row store stays empty until its own backfill
--   lands; this _json store is populated by extract_eligibility_predicate.py).
--
-- Schema:
--   * program_id                          TEXT PRIMARY KEY  — jpi_programs.unified_id
--   * predicate_json                      TEXT NOT NULL     — JSON object, see shape below
--   * extraction_method                   TEXT              — 'rule_based' / 'llm_extracted' / 'manual'
--   * confidence                          REAL              — 0.0..1.0; rule_based heuristic
--   * extracted_at                        TEXT              — datetime('now') default
--   * source_program_corpus_snapshot_id   TEXT              — corpus snapshot id for reproducibility
--
--   predicate_json shape (all axes optional; missing = no constraint extracted):
--     {
--       "industries_jsic":      ["A","D"],            -- JSIC major letters
--       "prefectures":          ["大阪府"],            -- Japanese prefecture names
--       "prefecture_jis":       ["27"],               -- 2-digit JIS prefecture codes
--       "municipalities":       ["大阪市"],            -- municipality names (when scoped)
--       "capital_max_yen":      100000000,            -- integer yen, NULL if no cap
--       "employee_max":         100,                  -- integer, NULL if no cap
--       "min_business_years":   1,                    -- integer, NULL if not stated
--       "target_entity_types":  ["corporation","sole_proprietor"],
--       "crop_categories":      ["facility_vegetable","fruit_tree"],
--       "funding_purposes":     ["新規就農","設備投資"],
--       "certifications_any_of":["認定新規就農者","認定農業者"],
--       "age":                  {"min": null, "max": 67},
--       "raw_constraints":      ["original sentence 1", "..."]   -- regex-fail residue
--     }
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS + INSERT OR REPLACE on (program_id). Re-runs of
--   scripts/etl/extract_eligibility_predicate.py overwrite predicate_json;
--   primary key prevents row growth.
--
-- DOWN: see 164_am_program_eligibility_predicate_rollback.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_eligibility_predicate_json (
    program_id                        TEXT PRIMARY KEY,
    predicate_json                    TEXT NOT NULL,
    extraction_method                 TEXT NOT NULL DEFAULT 'rule_based'
                                       CHECK (extraction_method IN
                                              ('rule_based','llm_extracted','manual')),
    confidence                        REAL,
    extracted_at                      TEXT NOT NULL DEFAULT (datetime('now')),
    source_program_corpus_snapshot_id TEXT
);

CREATE INDEX IF NOT EXISTS ix_apepj_method
    ON am_program_eligibility_predicate_json(extraction_method);

CREATE INDEX IF NOT EXISTS ix_apepj_extracted_at
    ON am_program_eligibility_predicate_json(extracted_at);
