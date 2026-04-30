-- target_db: autonomath
-- migration 101_trust_infrastructure
--
-- Trust infrastructure Top 8 — converts customers from "tooling" to
-- "core dependency" via:
--   * #4 correction_log         — public retrospective on every correction
--   * #5 audit_log_section52    — §52 compliance sample log
--   * #6 confirming_source_count — cross-source agreement column
--   * #7 correction_submissions — customer correction acceptance queue
--
-- Forward-only / idempotent. Re-running on each Fly boot is safe because
-- every CREATE uses IF NOT EXISTS and every ALTER is the SQLite
-- "duplicate column name" → swallow-by-entrypoint pattern (see
-- migrations/049_provenance_strengthen.sql for the established posture).
--
-- All five surfaces reference the operator entity:
--   Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
-- and stay within the §52 disclaimer fence (this file adds NO copy that
-- would constitute 助言 / advice; everything is descriptive metadata or
-- machine-readable status).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. correction_log  (#4 Public retrospective)
-- ---------------------------------------------------------------------------
-- Every detected correction is one row. Each row triggers a markdown post
-- under site/news/correction-{id}.html and a feed-item append into
-- site/audit-log.rss. The schema is intentionally narrow — anything
-- richer (e.g. multi-field corrections) is encoded by emitting multiple
-- rows referencing the same entity_id.

CREATE TABLE IF NOT EXISTS correction_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at         TEXT NOT NULL,           -- ISO-8601 UTC
    dataset             TEXT NOT NULL,           -- 'programs' / 'laws' / 'tax_rulesets' / 'court_decisions' / 'enforcement_cases' / etc.
    entity_id           TEXT NOT NULL,           -- unified_id or am_canonical_id
    field_name          TEXT,                    -- nullable for whole-row corrections
    prev_value_hash     TEXT,                    -- sha256:<16hex> of the previous value, NULL for new-row inserts
    new_value_hash      TEXT,                    -- sha256:<16hex> of the corrected value, NULL for retractions
    root_cause          TEXT NOT NULL,           -- 'source_amendment' / 'ingest_bug' / 'human_report' / 'cross_source_conflict' / 'license_change'
    source_url          TEXT,                    -- the primary URL that motivated the correction
    reproducer_sql      TEXT,                    -- SELECT that returns the corrected row, suitable for auditor verification
    correction_post_url TEXT,                    -- /news/correction-{id}.html (filled by generator script)
    rss_appended_at     TEXT                     -- when the row was added to audit-log.rss
);

CREATE INDEX IF NOT EXISTS idx_correction_log_detected_at
    ON correction_log(detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_correction_log_dataset
    ON correction_log(dataset, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_correction_log_entity
    ON correction_log(entity_id, detected_at DESC);

-- ---------------------------------------------------------------------------
-- 2. audit_log_section52  (#5 §52 compliance audit log)
-- ---------------------------------------------------------------------------
-- Daily sampler scans up to 1000 recent tool calls, regexes the response
-- bodies for advisory-shape phrases (「〜すべき」/「〜することをお勧めします」/
-- 「判断は妥当」), and persists the verdict here. The cron then aggregates
-- the daily violation count to site/compliance/section52.html.
--
-- Hash-only — raw request / response bodies never land in this table.
-- The disclaimer_present flag answers "did the response carry the §52
-- _disclaimer envelope key" so a missing-disclaimer regression is also
-- visible without storing the body.

CREATE TABLE IF NOT EXISTS audit_log_section52 (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at                  TEXT NOT NULL,    -- ISO-8601 UTC, when the sampler ran
    tool                        TEXT NOT NULL,    -- e.g. 'POST /v1/tax_rulesets/evaluate' or 'mcp.search_tax_incentives'
    request_hash                TEXT NOT NULL,    -- sha256:<16hex> over canonical request payload
    response_hash               TEXT NOT NULL,    -- sha256:<16hex> over response body
    disclaimer_present          INTEGER NOT NULL, -- 0 / 1
    advisory_terms_in_response  TEXT,             -- JSON array of matched phrases (NULL when none)
    violation                   INTEGER NOT NULL DEFAULT 0  -- 1 when advisory_terms_in_response IS NOT NULL OR disclaimer_present = 0
);

CREATE INDEX IF NOT EXISTS idx_audit_log_section52_sampled_at
    ON audit_log_section52(sampled_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_section52_violation
    ON audit_log_section52(violation, sampled_at DESC)
    WHERE violation = 1;

-- ---------------------------------------------------------------------------
-- 3. am_entity_facts.confirming_source_count  (#6 Cross-source agreement)
-- ---------------------------------------------------------------------------
-- New column counting how many distinct primary sources confirm a fact.
-- Populated weekly by scripts/cron/cross_source_agreement.py. Defaults
-- to 1 (the original source). Higher values surface in /v1/am responses
-- as `confirming_sources` so an LLM agent (or its human in the loop)
-- can decide how aggressively to cite the value.
--
-- SQLite has no IF NOT EXISTS for ADD COLUMN; entrypoint.sh swallows the
-- "duplicate column" error so re-runs are safe.

ALTER TABLE am_entity_facts ADD COLUMN confirming_source_count INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_am_entity_facts_csc
    ON am_entity_facts(entity_id, field_name, confirming_source_count DESC);

-- ---------------------------------------------------------------------------
-- 4. correction_submissions  (#7 Customer correction acceptance queue)
-- ---------------------------------------------------------------------------
-- Queue of customer-submitted correction reports (POST /v1/am/corrections).
-- Operator triages via SQL UPDATE. The cron `correction_review.py` only
-- generates report files; the actual approve/reject decision is a manual
-- single-row UPDATE that the operator owns (zero-touch + solo ops:
-- automated triage on legal-shape data is a fraud risk vector — see
-- feedback_no_fake_data + feedback_autonomath_fraud_risk).
--
-- status values:
--   'pending'   — newly submitted, awaiting operator review
--   'accepted'  — operator agrees; ingest will rewrite the cell
--   'rejected'  — operator disagrees; rationale captured in reviewer_note
--   'duplicate' — same submission already in queue / already-fixed
--   'retracted' — submitter withdrew (POST /v1/am/corrections/{id}/retract)

CREATE TABLE IF NOT EXISTS correction_submissions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    submitted_at            TEXT NOT NULL,        -- ISO-8601 UTC
    entity_id               TEXT NOT NULL,        -- unified_id / am_canonical_id
    field                   TEXT NOT NULL,        -- e.g. 'amount_max_yen'
    claimed_correct_value   TEXT NOT NULL,        -- the submitter's proposed value (TEXT — type interpreted at review time)
    evidence_url            TEXT NOT NULL,        -- HTTPS URL to a primary source supporting the claim
    reporter_email          TEXT,                 -- HMAC'd email; raw email never persisted
    reporter_email_hmac     TEXT NOT NULL,        -- HMAC-SHA256 of email under api_key_salt
    reporter_ip_hash        TEXT NOT NULL,        -- HMAC-SHA256 of submitter IP (rate limit dedup key)
    reporter_key_hash       TEXT,                 -- non-null when submitter authenticated; useful for trust scoring
    status                  TEXT NOT NULL DEFAULT 'pending',
    reviewed_at             TEXT,                 -- when the operator updated status
    reviewer_note           TEXT,                 -- operator-supplied rationale (public)
    correction_log_id       INTEGER,              -- FK to correction_log when status='accepted' resolves into a published correction
    FOREIGN KEY (correction_log_id) REFERENCES correction_log(id)
);

CREATE INDEX IF NOT EXISTS idx_correction_submissions_status
    ON correction_submissions(status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_correction_submissions_entity
    ON correction_submissions(entity_id, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_correction_submissions_dedup
    ON correction_submissions(reporter_ip_hash, submitted_at DESC);

-- Same-day dedup uniqueness: one (entity_id, field, reporter_ip_hash, day)
-- combination should not produce more than one row. The cron rate limiter
-- catches most cases; the index lets us tolerate races.
CREATE INDEX IF NOT EXISTS idx_correction_submissions_dedup_full
    ON correction_submissions(
        entity_id, field, reporter_ip_hash, substr(submitted_at, 1, 10)
    );

-- ---------------------------------------------------------------------------
-- 5. quality_metrics_daily  (#3 Public quality dashboard)
-- ---------------------------------------------------------------------------
-- Per-dataset daily computed metrics. The cron `quality_dashboard_refresh.py`
-- writes one row per (dataset, computed_for_date) and the public page
-- /quality.html reads the latest set via /v1/am/quality. We persist to
-- both this table AND data/quality_metrics.json — the JSON is what the
-- static page actually polls; the table is the audit trail / SLO check.

CREATE TABLE IF NOT EXISTS quality_metrics_daily (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at                 TEXT NOT NULL,    -- ISO-8601 UTC
    computed_for_date           TEXT NOT NULL,    -- 'YYYY-MM-DD'
    dataset                     TEXT NOT NULL,    -- 'programs' / 'laws' / etc.
    precision_estimate          REAL,             -- 0.0 - 1.0 from 100-row sample × diff vs re-fetch
    recall_estimate             REAL,             -- 0.0 - 1.0 proxy via am_validation_result pass-rate
    freshness_p50_days          INTEGER,          -- days since fetched_at, p50 across rows
    cite_chain_coverage_pct     REAL,             -- 0.0 - 100.0 fraction of rows with non-empty source_url
    dead_url_pct                REAL,             -- 0.0 - 100.0 fraction of rows whose source_fail_count >= 3
    license_compliance_pct      REAL,             -- 0.0 - 100.0 fraction of rows with non-NULL license
    sample_size                 INTEGER,          -- 100 unless dataset has < 100 rows
    notes                       TEXT,             -- operator-supplied annotations (NULL by default)
    UNIQUE (dataset, computed_for_date)
);

CREATE INDEX IF NOT EXISTS idx_quality_metrics_daily_date
    ON quality_metrics_daily(computed_for_date DESC, dataset);

-- ---------------------------------------------------------------------------
-- 6. dead_url_alerts  (#8 Stale data alert webhook routing)
-- ---------------------------------------------------------------------------
-- Each row is one detected 404 on an entity that some customer accessed
-- in the last 30 days. The dispatch_webhooks cron consumes pending rows
-- and fires source.dead_url events to subscribed customer webhooks; rows
-- transition to 'dispatched' once at least one delivery succeeded.

CREATE TABLE IF NOT EXISTS dead_url_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at         TEXT NOT NULL,
    dataset             TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    dead_url            TEXT NOT NULL,
    http_status         INTEGER,
    last_customer_access_at TEXT,             -- when the 30-day-window check passed
    status              TEXT NOT NULL DEFAULT 'pending',
    dispatched_at       TEXT,
    UNIQUE (dataset, entity_id, dead_url)
);

CREATE INDEX IF NOT EXISTS idx_dead_url_alerts_status
    ON dead_url_alerts(status, detected_at DESC);

-- ---------------------------------------------------------------------------
-- 7. reproducibility_snapshots  (#1 Reproducibility cert formalize)
-- ---------------------------------------------------------------------------
-- Records the snapshot_id values that were ever served plus the on-disk
-- corpus state (R2 archive present? row counts at the time?). The
-- /v1/am/reproducibility/{snapshot_id} endpoint reads from this table —
-- when no row matches, we degrade gracefully to "snapshot may have
-- existed but archive is unavailable" rather than 404, because an
-- auditor's cite must be answerable years later.

CREATE TABLE IF NOT EXISTS reproducibility_snapshots (
    snapshot_id         TEXT PRIMARY KEY,         -- the corpus_snapshot_id served at the time
    captured_at         TEXT NOT NULL,            -- ISO-8601 UTC of the capture (cron-side)
    api_version         TEXT NOT NULL,
    row_counts_json     TEXT NOT NULL,            -- {"programs": N, "laws": N, ...}
    on_disk             INTEGER NOT NULL DEFAULT 1,  -- 1 if corpus state still recoverable from R2 archive
    r2_archive_url      TEXT,                     -- r2://... pointer when on_disk=1
    cookbook_md         TEXT,                     -- copy of the re-evaluation cookbook used at the time
    retention_until     TEXT NOT NULL             -- ISO-8601 date — 7 years past captured_at per docs/audit_trail.md
);

CREATE INDEX IF NOT EXISTS idx_reproducibility_snapshots_captured
    ON reproducibility_snapshots(captured_at DESC);

-- ---------------------------------------------------------------------------
-- Migration bookkeeping
-- ---------------------------------------------------------------------------
-- migrate.py records this file's checksum so re-application is idempotent.
-- Operator (Bookyou株式会社, T8010001213708) acknowledges the §52 fence
-- still applies — none of these tables introduce 助言 surfaces; they all
-- describe data quality, corrections, and audit reproducibility.
