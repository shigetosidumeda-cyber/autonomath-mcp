-- target_db: autonomath
-- migration: 274_anonymized_query
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim N (anonymized_query / PII redact) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Persists the anonymized query audit log + materialized aggregate view
-- consumed by /v1/network/anonymized_outcomes (Dim N, PR #139). The REST
-- surface (src/jpintel_mcp/api/anonymized_query.py) currently uses an
-- in-memory ring buffer (_AUDIT_LOG, maxlen=1000) for audit + a
-- deterministic synthetic aggregator. This migration lands the production
-- substrate so the audit trail survives machine swaps and the cohort
-- outcomes view can be refreshed nightly from the real entity corpus.
--
-- Pattern
-- -------
-- Two tables (catalogue + log), one helper view, mirroring the Dim K
-- (271_rule_tree) split. The log is append-only and grows linearly with
-- traffic; the view is rebuilt nightly by
-- scripts/etl/aggregate_anonymized_outcomes.py from am_entities +
-- am_entity_facts joined against am_industry_jsic / am_region — only
-- cohorts with k >= K_ANONYMITY_MIN (5) land in the view, so a query
-- against the view alone cannot expose sub-k cohorts.
--
-- Hard constraint: k=5 minimum
-- ----------------------------
-- The aggregator ETL enforces k>=5 at materialization time (HAVING
-- COUNT(*) >= 5). A SQL CHECK constraint on am_aggregated_outcome_view
-- (k_value >= 5) doubles as an integrity test catching any future
-- mistake that tries to INSERT a smaller cohort. Per
-- feedback_anonymized_query_pii_redact: k=5 floor cannot be lowered at
-- runtime.
--
-- PII strip
-- ---------
-- am_anonymized_query_log stores ONLY the SHA-256 hash of the filter
-- triple (industry/region/size) — never the raw values, never any
-- houjin_bangou / company_name / address / contact. The pii_stripped
-- JSON column carries the redact policy version + cohort_size only.
--
-- Audit token
-- -----------
-- Each row carries an audit_token (random 16-hex). Used by ops to map a
-- specific REST response back to its log row when investigating a
-- redact-policy regression. Token is NOT exposed to callers.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/network/anonymized_outcomes stays at 1 metered unit regardless of
-- cohort breadth — the log table is internal only.
--
-- Retention
-- ---------
-- am_anonymized_query_log: 180-day rolling window swept by dlq_drain.py
-- cleanup pass. am_aggregated_outcome_view: rebuilt nightly, old rows
-- deleted before insert (single-snapshot semantics).

PRAGMA foreign_keys = ON;

BEGIN;

-- Per-call audit trail. Append-only.
CREATE TABLE IF NOT EXISTS am_anonymized_query_log (
    query_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash          TEXT NOT NULL,                       -- sha256(industry|region|size)[:16]
    k_anonymity_value   INTEGER NOT NULL                     -- cohort size at evaluation
                        CHECK (k_anonymity_value >= 0),
    pii_stripped        TEXT NOT NULL DEFAULT '{}',          -- JSON: {redact_policy_version, cohort_size}
    audit_token         TEXT NOT NULL,                       -- random hex, ops trace
    requested_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_anon_query_log_hash
    ON am_anonymized_query_log(query_hash, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_anon_query_log_time
    ON am_anonymized_query_log(requested_at DESC);

-- Materialized aggregate view. Hard k=5 floor enforced by CHECK; the
-- nightly aggregator ETL applies HAVING COUNT(*) >= 5 before INSERT.
CREATE TABLE IF NOT EXISTS am_aggregated_outcome_view (
    cluster_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_cluster_id   TEXT NOT NULL,                       -- e.g. 'industry=F|region=13000|size=sme'
    outcome_type        TEXT NOT NULL                        -- adoption / enforcement / amendment
                        CHECK (outcome_type IN ('adoption','enforcement','amendment','program_apply')),
    count               INTEGER NOT NULL
                        CHECK (count >= 5),                  -- k=5 floor
    k_value             INTEGER NOT NULL
                        CHECK (k_value >= 5),                -- k=5 floor (mirrors count for clarity)
    mean_amount_yen     INTEGER,
    median_amount_yen   INTEGER,
    last_updated        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (entity_cluster_id, outcome_type)
);

CREATE INDEX IF NOT EXISTS idx_am_agg_outcome_cluster
    ON am_aggregated_outcome_view(entity_cluster_id);

CREATE INDEX IF NOT EXISTS idx_am_agg_outcome_type
    ON am_aggregated_outcome_view(outcome_type, last_updated DESC);

-- Helper view: latest cohort summary for ops dashboards. Filters
-- defensively to k>=5 even though the table CHECK already enforces it.
DROP VIEW IF EXISTS v_anon_cohort_outcomes_latest;
CREATE VIEW v_anon_cohort_outcomes_latest AS
SELECT
    entity_cluster_id,
    outcome_type,
    count,
    k_value,
    mean_amount_yen,
    median_amount_yen,
    last_updated
FROM am_aggregated_outcome_view
WHERE k_value >= 5;

COMMIT;
