-- target_db: autonomath
-- migration wave24_142_am_narrative_customer_reports (MASTER_PLAN_v1
-- 章 10.10.1 — customer-side narrative defect inbox + serve log)
--
-- Why this exists:
--   §10.10.4 customer report channel: REST `POST /v1/narrative/{id}/report`
--   inserts one row here per customer-flagged defect. Auto-severity
--   (P0..P3) drives SLA: P0/P1 → 24h, P2/P3 → 72h. P0 also flips
--   `is_active=0` on the reported narrative immediately.
--
--   §10.10.6 rollback: `am_narrative_serve_log` records every
--   served narrative response (best-effort) so a rollback can
--   identify the API keys that received the bad row in the past 30
--   days and credit them ¥3 per affected serve.
--
-- Schema:
--   am_narrative_customer_reports
--     * report_id INTEGER PRIMARY KEY AUTOINCREMENT
--     * narrative_id INTEGER NOT NULL
--     * narrative_table TEXT NOT NULL CHECK (...)
--     * api_key_id INTEGER  — NULL for anonymous reports
--     * severity_auto TEXT NOT NULL CHECK (severity_auto IN
--          ('P0','P1','P2','P3'))
--     * field_path TEXT  — e.g. 'narrative.eligibility' or
--                          'application_documents[2].url'
--     * claimed_wrong TEXT NOT NULL
--     * claimed_correct TEXT
--     * evidence_url TEXT
--     * state TEXT NOT NULL DEFAULT 'inbox' CHECK (state IN
--          ('inbox','triaged','resolved','dismissed'))
--     * operator_note TEXT
--     * created_at TEXT NOT NULL DEFAULT (datetime('now'))
--     * sla_due_at TEXT NOT NULL
--
--   am_narrative_serve_log
--     * served_at TEXT NOT NULL
--     * narrative_id INTEGER NOT NULL
--     * narrative_table TEXT NOT NULL
--     * api_key_id INTEGER  — NULL for anonymous serves (no credit possible)
--     * request_id TEXT NOT NULL  — UUID from middleware, dedupes double-write
--
--   No UNIQUE on serve_log because the same (api_key_id, narrative_id)
--   serving multiple times legitimately bills multiple times. The
--   prune cron deletes rows older than 30 days.
--
-- Indexes:
--   * idx_ncr_state_due — operator queue by SLA due ascending.
--   * idx_nsl_narrative_time — rollback fan-out scan.
--   * idx_nsl_recent — covering index for the past-30d retention scan.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, no DML.
--
-- DOWN:
--   See companion `wave24_142_am_narrative_customer_reports_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_narrative_customer_reports (
    report_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id     INTEGER NOT NULL,
    narrative_table  TEXT NOT NULL CHECK (narrative_table IN (
                        'am_program_narrative','am_houjin_360_narrative',
                        'am_enforcement_summary','am_case_study_narrative',
                        'am_law_article_summary'
                     )),
    api_key_id       INTEGER,
    severity_auto    TEXT NOT NULL CHECK (severity_auto IN
                        ('P0','P1','P2','P3')),
    field_path       TEXT,
    claimed_wrong    TEXT NOT NULL,
    claimed_correct  TEXT,
    evidence_url     TEXT,
    state            TEXT NOT NULL DEFAULT 'inbox' CHECK (state IN (
                        'inbox','triaged','resolved','dismissed'
                     )),
    operator_note    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    sla_due_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ncr_state_due
    ON am_narrative_customer_reports(state, sla_due_at);

CREATE INDEX IF NOT EXISTS idx_ncr_narrative
    ON am_narrative_customer_reports(narrative_table, narrative_id);

CREATE TABLE IF NOT EXISTS am_narrative_serve_log (
    served_at        TEXT NOT NULL,
    narrative_id     INTEGER NOT NULL,
    narrative_table  TEXT NOT NULL,
    api_key_id       INTEGER,
    request_id       TEXT NOT NULL
);

-- Rollback fan-out scan: "every api_key that served this narrative
-- in the past 30 days".
CREATE INDEX IF NOT EXISTS idx_nsl_narrative_time
    ON am_narrative_serve_log(narrative_id, narrative_table, served_at);

-- Retention prune cron: covering scan for served_at < threshold.
CREATE INDEX IF NOT EXISTS idx_nsl_recent
    ON am_narrative_serve_log(served_at);
