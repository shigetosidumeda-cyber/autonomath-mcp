-- 062_empty_search_log.sql
-- Capture the gold dataset for "missing programs": every search query that
-- returned 0 results. P0 from audit ada8db68240c63c66 — without this we
-- silently lose the most valuable signal (queries our corpus does not yet
-- answer). Solo-ops + zero-touch means this dataset drives ingest
-- prioritization, not a CS team.
--
-- PII rule (memory: feedback_no_fake_data + privacy posture):
--   * `query` is stored RAW — operator must triage missing-program signal,
--     and a hash defeats the entire point of the dataset.
--   * `ip_hash` is sha256 of (raw_ip || daily_salt). Raw IP is NEVER stored.
--     The daily salt rotation (see api/admin_telemetry.py::_ip_hash) means
--     the hash cannot be linked across days, so the table cannot serve as
--     a long-term tracking surface.
--   * `endpoint` is the short tool name ('search_programs', 'search_laws',
--     'search_case_studies', 'search_loan_programs', 'search_enforcement_cases',
--     'search_tax_rulesets', 'search_invoice_registrants') NOT a URL path —
--     URL paths can carry T-numbers in path params; tool names cannot.
--
-- The (query) index supports per-query distinct rollup for the operator
-- dashboard `top recent empty queries`. The (created_at DESC) index
-- backstops "recent N hours" sliding windows.

CREATE TABLE IF NOT EXISTS empty_search_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    filters_json TEXT,
    ip_hash      TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_empty_search_log_query
    ON empty_search_log(query);

CREATE INDEX IF NOT EXISTS idx_empty_search_log_created
    ON empty_search_log(created_at DESC);
