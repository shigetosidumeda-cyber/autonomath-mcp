-- 020_compliance_subscribers.sql
-- 法令改正アラート (Compliance Alerts) subscription tables.
--
-- Separate from the existing `subscribers` table (migration 002) on purpose:
--   * `subscribers` holds newsletter / launch-update opt-ins (single email,
--     no plan, no verification flow).
--   * `compliance_subscribers` holds paying / free-digest subscribers to the
--     ¥500/月 real-time alert product. The schema needs email verification,
--     houjin_bangou + industry codes for targeting, plan state, Stripe wiring,
--     and a per-email unsubscribe token.
--
-- Business model (see memory project_autonomath_business_model.md):
--   * plan='free'  — monthly digest only (1 email/月 on the 1st of the month)
--   * plan='paid'  — real-time alerts, ¥500/月 via Stripe, daily cron picks
--                    changes within 24h of updated_at.
-- The free plan exists so the user can see the email quality before paying;
-- there is no "free bonus quota" concept — it's a different product shape.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- compliance_subscribers — the subscription roster
-- ============================================================================
-- Design notes:
--   * `email` is NOT UNIQUE on its own; the unique index is
--     `(email, unsubscribe_token)` so a user who unsubscribes and later
--     re-subscribes gets a fresh row with a fresh token. The previous row
--     stays as the audit record (`canceled_at` set).
--   * `unsubscribe_token` is a hex-32 random string (not HMAC — we want
--     rotation on re-subscribe, and hex-32 is already 128 bits of entropy).
--   * `verification_token` is NULL once the user clicks the confirm link.
--     A non-NULL value + NULL `verified_at` means "awaiting double opt-in"
--     and the cron must skip this subscriber.
--   * `industry_codes_json` / `areas_of_interest_json` are JSON arrays.
--     The CHECK on areas_of_interest_json is NOT enforced in SQL (CHECK
--     cannot parse JSON); it's documented here and validated in Python
--     before INSERT.
--   * `plan CHECK IN ('free','paid')` matches the two-shape product; no
--     tier SKUs beyond this.
--   * `notification_count_mtd` is a monotonic counter reset by the cron on
--     month roll-over. Used for dashboard + abuse detection.
CREATE TABLE IF NOT EXISTS compliance_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    houjin_bangou TEXT,                        -- 13 digits, optional
    industry_codes_json TEXT,                  -- JSON array of JSIC codes
    areas_of_interest_json TEXT NOT NULL,      -- JSON array subset of
                                               -- ('invoice','ebook','subsidy',
                                               --  'loan','enforcement',
                                               --  'tax_ruleset','court')
    prefecture TEXT,                           -- 47 都道府県 name or NULL
    plan TEXT NOT NULL CHECK (plan IN ('free','paid')) DEFAULT 'free',
    stripe_customer_id TEXT,                   -- NULL for free
    stripe_subscription_id TEXT,               -- NULL for free
    subscribed_at TEXT NOT NULL,               -- ISO 8601 UTC
    canceled_at TEXT,                          -- NULL = active
    last_notified_at TEXT,                     -- ISO 8601 of last successful send
    notification_count_mtd INTEGER DEFAULT 0,  -- month-to-date sends
    unsubscribe_token TEXT NOT NULL UNIQUE,    -- hex 32
    verification_token TEXT,                   -- NULL once verified
    verified_at TEXT,                          -- ISO 8601 UTC
    source_lang TEXT DEFAULT 'ja',             -- 'ja' | 'en'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_compliance_subscribers_email_token
    ON compliance_subscribers(email, unsubscribe_token);
CREATE INDEX IF NOT EXISTS idx_compliance_subscribers_plan
    ON compliance_subscribers(plan);
CREATE INDEX IF NOT EXISTS idx_compliance_subscribers_verified
    ON compliance_subscribers(verified_at);

-- ============================================================================
-- compliance_notification_log — audit trail for idempotency + ops
-- ============================================================================
-- Written by scripts/compliance_cron.py after every successful send attempt.
-- The cron reads back this table with `WHERE subscriber_id=? AND date(sent_at)=?`
-- to make a second run on the same day a no-op (safety on top of the Postmark
-- idempotency window).
CREATE TABLE IF NOT EXISTS compliance_notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id INTEGER NOT NULL
        REFERENCES compliance_subscribers(id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL,                     -- ISO 8601 UTC
    subject TEXT NOT NULL,
    changes_json TEXT NOT NULL,                -- JSON array of
                                               -- {unified_id, table, summary, source_url}
    delivered INTEGER DEFAULT 0,               -- 0/1 boolean
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_compliance_log_subscriber
    ON compliance_notification_log(subscriber_id, sent_at);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
