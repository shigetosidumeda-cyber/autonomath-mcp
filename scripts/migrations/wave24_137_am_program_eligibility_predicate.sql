-- target_db: autonomath
-- migration wave24_137_am_program_eligibility_predicate (MASTER_PLAN_v1
-- 章 10.2.12 — eligibility predicate 結晶化テーブル + view)
--
-- Why this exists:
--   The Wave 21 `apply_eligibility_chain_am` and the Wave 22
--   `bundle_application_kit` tools both walk eligibility predicates
--   per program. Today they reconstruct predicates from the
--   eligibility_struct JSON in `am_amendment_snapshot`, which is
--   slow and forces every reader to know the JSON shape.
--
--   This migration crystallizes one row per (program × predicate)
--   so readers can SELECT WHERE predicate_kind = 'capital_max'
--   without JSON parsing. The companion view
--   `v_am_program_required_predicates` filters to predicates that
--   are mandatory (is_required=1) for downstream filter UIs.
--
-- Schema:
--   am_program_eligibility_predicate
--     * predicate_id INTEGER PRIMARY KEY AUTOINCREMENT
--     * program_unified_id TEXT NOT NULL
--     * predicate_kind TEXT NOT NULL CHECK (...)
--          'capital_max'|'capital_min'|'employee_max'|'employee_min'|
--          'fy_revenue_max'|'fy_revenue_min'|'jsic_in'|'jsic_not_in'|
--          'region_in'|'region_not_in'|'invoice_required'|
--          'tax_compliance_required'|'no_enforcement_within_years'|
--          'business_age_min_years'|'capital_band_in'|'other'
--     * operator TEXT NOT NULL CHECK (operator IN
--          ('=','!=','<','<=','>','>=','IN','NOT_IN','CONTAINS','EXISTS'))
--     * value_text TEXT
--     * value_num REAL
--     * value_json TEXT  — for IN / NOT_IN array values
--     * is_required INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1))
--     * source_url TEXT
--     * source_clause_quote TEXT  — literal substring from primary doc
--     * extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
--     * UNIQUE (program_unified_id, predicate_kind, operator,
--               COALESCE(value_text,''), COALESCE(value_num,0),
--               COALESCE(value_json,''))
--
--   The composite UNIQUE allows multiple predicates of the same
--   kind (e.g. region_in 'tokyo' and region_in 'osaka' as two rows)
--   without forcing JSON arrays.
--
--   v_am_program_required_predicates (view):
--     SELECT * FROM am_program_eligibility_predicate WHERE is_required = 1;
--
-- Indexes:
--   * (program_unified_id, predicate_kind) — predicate-set lookup.
--   * (predicate_kind, value_num) — "all programs requiring capital >= X".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. CREATE VIEW IF NOT EXISTS.
--
-- DOWN:
--   See companion `wave24_137_am_program_eligibility_predicate_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_eligibility_predicate (
    predicate_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_unified_id    TEXT NOT NULL,
    predicate_kind        TEXT NOT NULL CHECK (predicate_kind IN (
                            'capital_max','capital_min','employee_max','employee_min',
                            'fy_revenue_max','fy_revenue_min','jsic_in','jsic_not_in',
                            'region_in','region_not_in','invoice_required',
                            'tax_compliance_required','no_enforcement_within_years',
                            'business_age_min_years','capital_band_in','other'
                          )),
    operator              TEXT NOT NULL CHECK (operator IN (
                            '=','!=','<','<=','>','>=','IN','NOT_IN','CONTAINS','EXISTS'
                          )),
    value_text            TEXT,
    value_num             REAL,
    value_json            TEXT,
    is_required           INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1)),
    source_url            TEXT,
    source_clause_quote   TEXT,
    extracted_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- UNIQUE 句は CREATE UNIQUE INDEX で後付け (SQLite 3.31+ の expression UNIQUE INDEX)
-- inline UNIQUE (..., COALESCE(...)) は SQLite が
-- "expressions prohibited in PRIMARY KEY and UNIQUE constraints" で abort するため不可。
CREATE UNIQUE INDEX IF NOT EXISTS uq_apep_predicate
    ON am_program_eligibility_predicate(
        program_unified_id,
        predicate_kind,
        operator,
        COALESCE(value_text, ''),
        COALESCE(value_num, 0),
        COALESCE(value_json, '')
    );

CREATE INDEX IF NOT EXISTS idx_apep_program_kind
    ON am_program_eligibility_predicate(program_unified_id, predicate_kind);

CREATE INDEX IF NOT EXISTS idx_apep_kind_value
    ON am_program_eligibility_predicate(predicate_kind, value_num)
    WHERE value_num IS NOT NULL;

-- View — required predicates only.
CREATE VIEW IF NOT EXISTS v_am_program_required_predicates AS
SELECT predicate_id,
       program_unified_id,
       predicate_kind,
       operator,
       value_text,
       value_num,
       value_json,
       source_url,
       source_clause_quote,
       extracted_at
  FROM am_program_eligibility_predicate
 WHERE is_required = 1;
