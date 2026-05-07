-- target_db: jpintel
-- migration: 195_advisor_handoffs
-- generated_at: 2026-05-07
-- spec: docs/_internal/advisors_evidence_handoff_concrete_plan_2026-05-07.md
--
-- Purpose
-- -------
-- Persist the Evidence-to-Expert Handoff unit that links artifact/evidence
-- packets, known gaps, human-review posture, referral clicks, and advisor
-- events without changing the existing advisors/advisor_referrals flow.
--
-- Idempotency
-- -----------
-- CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS are native no-ops
-- on re-apply. SQLite still has no portable ADD COLUMN IF NOT EXISTS, so the
-- four advisor_referrals columns are nullable additive ALTER statements and
-- rely on scripts/migrate.py's per-statement duplicate-column skip. That
-- existing runner behavior lets a partially-applied DB continue through the
-- remaining column additions instead of aborting the whole migration.
--
-- LLM call: 0. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS advisor_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_token TEXT NOT NULL UNIQUE,
    source_artifact_id TEXT,
    source_packet_id TEXT,
    corpus_snapshot_id TEXT,
    source_type TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT,
    houjin_bangou TEXT,
    identity_confidence TEXT,
    prefecture TEXT,
    industry TEXT,
    specialty TEXT,
    known_gaps_json TEXT NOT NULL DEFAULT '[]',
    human_review_json TEXT NOT NULL DEFAULT '{}',
    source_receipts_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    recommended_professions_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    CHECK (status IN ('created', 'viewed', 'matched', 'consented', 'expired', 'revoked')),
    CHECK (
        identity_confidence IS NULL
        OR identity_confidence IN ('exact', 'high', 'medium', 'low', 'unmatched')
    )
);

CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_token
    ON advisor_handoffs(handoff_token);

CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_houjin
    ON advisor_handoffs(houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_created
    ON advisor_handoffs(created_at);

CREATE TABLE IF NOT EXISTS advisor_handoff_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER NOT NULL REFERENCES advisor_handoffs(id),
    event_name TEXT NOT NULL,
    advisor_id INTEGER,
    referral_id INTEGER,
    anon_ip_hash TEXT,
    key_hash TEXT,
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_advisor_handoff_events_handoff
    ON advisor_handoff_events(handoff_id, created_at);

CREATE INDEX IF NOT EXISTS idx_advisor_handoff_events_name
    ON advisor_handoff_events(event_name, created_at);

ALTER TABLE advisor_referrals ADD COLUMN handoff_id INTEGER REFERENCES advisor_handoffs(id);
ALTER TABLE advisor_referrals ADD COLUMN source_artifact_id TEXT;
ALTER TABLE advisor_referrals ADD COLUMN source_packet_id TEXT;
ALTER TABLE advisor_referrals ADD COLUMN evidence_digest TEXT;

CREATE TRIGGER IF NOT EXISTS trg_advisors_houjin_digits_insert
BEFORE INSERT ON advisors
WHEN NEW.houjin_bangou NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
BEGIN
    SELECT RAISE(ABORT, 'advisor houjin_bangou must be 13 digits');
END;

CREATE TRIGGER IF NOT EXISTS trg_advisors_houjin_digits_update
BEFORE UPDATE OF houjin_bangou ON advisors
WHEN NEW.houjin_bangou NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
BEGIN
    SELECT RAISE(ABORT, 'advisor houjin_bangou must be 13 digits');
END;

CREATE TRIGGER IF NOT EXISTS trg_advisors_no_lawyer_percent_insert
BEFORE INSERT ON advisors
WHEN NEW.firm_type = '弁護士' AND NEW.commission_model = 'percent'
BEGIN
    SELECT RAISE(ABORT, 'lawyer percent commission not allowed');
END;

CREATE TRIGGER IF NOT EXISTS trg_advisors_no_lawyer_percent_update
BEFORE UPDATE OF firm_type, commission_model ON advisors
WHEN NEW.firm_type = '弁護士' AND NEW.commission_model = 'percent'
BEGIN
    SELECT RAISE(ABORT, 'lawyer percent commission not allowed');
END;

-- Bookkeeping recorded by scripts/migrate.py via schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
