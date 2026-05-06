-- target_db: autonomath
-- migration wave24_138_am_program_documents (MASTER_PLAN_v1 章 10.2.13
-- — 申請書類 list, #110 用)
--
-- Why this exists:
--   `get_program_application_documents` (#110, sensitive=YES) returns
--   the list of 申請書類 a program requires. Today the data lives in
--   loose JSON in `programs.enriched_json` which is hard to query.
--   We materialize one row per (program × document) so readers can
--   filter by required-vs-optional / 様式番号 / source URL availability.
--
-- Schema:
--   * doc_id INTEGER PRIMARY KEY AUTOINCREMENT
--   * program_unified_id TEXT NOT NULL
--   * doc_name TEXT NOT NULL
--   * doc_kind TEXT  — '申請書'|'計画書'|'見積書'|'登記簿'|'納税証明'|
--                     '財務諸表'|'同意書'|'その他'
--   * yoshiki_no TEXT  — 様式番号 (e.g. '様式第1号')
--   * is_required INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1))
--   * url TEXT  — direct download URL when available
--   * source_clause_quote TEXT  — literal substring from primary 公募要領
--   * notes TEXT
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE (program_unified_id, doc_name, yoshiki_no)
--
--   The yoshiki_no in UNIQUE accommodates the case where two
--   different yoshiki carry the same doc_name (rare but happens
--   in sub-applications).
--
-- Indexes:
--   * (program_unified_id, is_required) — primary read pattern.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. UNIQUE allows `INSERT OR REPLACE`.
--
-- DOWN:
--   See companion `wave24_138_am_program_documents_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_documents (
    doc_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    program_unified_id   TEXT NOT NULL,
    doc_name             TEXT NOT NULL,
    doc_kind             TEXT CHECK (doc_kind IS NULL OR doc_kind IN (
                            '申請書','計画書','見積書','登記簿','納税証明',
                            '財務諸表','同意書','その他'
                         )),
    yoshiki_no           TEXT,
    is_required          INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1)),
    url                  TEXT,
    source_clause_quote  TEXT,
    notes                TEXT,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- UNIQUE 句は CREATE UNIQUE INDEX で後付け (SQLite 3.31+ の expression UNIQUE INDEX)
-- inline UNIQUE (..., COALESCE(...)) は SQLite が
-- "expressions prohibited in PRIMARY KEY and UNIQUE constraints" で abort するため不可。
CREATE UNIQUE INDEX IF NOT EXISTS uq_apd_document
    ON am_program_documents(program_unified_id, doc_name, COALESCE(yoshiki_no, ''));

CREATE INDEX IF NOT EXISTS idx_apd_program_required
    ON am_program_documents(program_unified_id, is_required);
