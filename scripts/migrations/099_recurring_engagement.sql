-- target_db: jpintel
-- 099_recurring_engagement.sql
-- Top-5 recurring engagement (M9 channel digests + M5 email courses + M14
-- sunset calendar key + M6 morning briefing key + M3 quarterly report key).
--
-- Business context (project_autonomath_business_model — immutable ¥3/req):
--   * Each delivery (channel digest post, course email, sunset email,
--     morning briefing, quarterly report email) is metered at ¥3 per
--     successful delivery.
--   * 0-match runs do NOT bill — the cron records nothing if there is
--     nothing to send. HONEST surface.
--   * Subscribe / unsubscribe paths are FREE — only delivery is metered.
--
-- This migration is idempotent (CREATE TABLE IF NOT EXISTS, ALTER TABLE
-- guarded by feature detection in the migrate.py runner). Safe to re-apply
-- on every Fly boot via entrypoint.sh self-heal loop.
--
-- ---------------------------------------------------------------------------
-- M9 — Slack/Discord/Teams/RSS digest channel via saved_searches
-- ---------------------------------------------------------------------------
--
-- Extends saved_searches with two columns:
--   * channel_format: ENUM('email','slack','discord','teams','rss') —
--     default 'email' to preserve the W3 contract for existing rows.
--   * channel_url:    HTTPS webhook URL (Slack incoming-webhook /
--     Discord webhook / Teams Incoming Webhook). NULL when channel_format
--     IN ('email','rss'). For RSS the cron writes a public feed under
--     /feeds/saved-searches/{id}.xml; for Slack/Discord/Teams the cron
--     POSTs to channel_url with the channel's native shape.
--
-- SQLite does NOT enforce CHECK on ALTER TABLE ADD COLUMN, but we add the
-- CHECK to the column declaration so future SQLite-level validation
-- (and grep-time documentation) carries the enum.
--
-- The notify_email column stays NOT NULL for back-compat — even slack/
-- discord/teams subscribers carry an email so we can route fallback /
-- channel-disabled notifications to a human inbox.

ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'
    CHECK (channel_format IN ('email','slack','discord','teams','rss'));
ALTER TABLE saved_searches ADD COLUMN channel_url TEXT;

CREATE INDEX IF NOT EXISTS idx_saved_searches_channel
    ON saved_searches(channel_format);

-- ---------------------------------------------------------------------------
-- M5 — Email course series subscriptions
-- ---------------------------------------------------------------------------
--
-- Tracks which customers are enrolled in which pre-recorded course
-- ("5日でわかるインボイス" / "7日でマスター電帳法"). Distinct from
-- email_schedule (onboarding D+0..D+30) because:
--   1. Course subscriptions are customer-initiated (POST /v1/me/courses).
--   2. They have N days each, not the fixed onboarding cadence.
--   3. They stack across multiple courses per customer simultaneously.
--   4. Course content is purely educational; §52 fence stays in the
--      template footer, never advisory.
--
-- One row per (api_key_id, course_slug). Re-subscribing while status='active'
-- is a no-op (UNIQUE constraint). Re-subscribing after completion/cancel
-- is a fresh row insertion (started_at moves forward).
--
-- The cron (scripts/cron/course_dispatcher.py) wakes daily; for every row
-- whose started_at + current_day*24h has elapsed AND status='active',
-- fires the next day's email and bumps current_day. When current_day
-- exceeds the course length the row flips to status='complete' and the
-- next-action upsell email (M1 saved_search) is enqueued via the
-- onboarding completion hook.

CREATE TABLE IF NOT EXISTS course_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id      TEXT NOT NULL,                          -- api_keys.key_hash
    email           TEXT NOT NULL,                          -- delivery target captured at subscribe time
    course_slug     TEXT NOT NULL CHECK (
                        course_slug IN ('invoice','dencho')
                    ),
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    current_day     INTEGER NOT NULL DEFAULT 0,             -- 0 = no email sent yet; 1..N = D{N} sent
    status          TEXT NOT NULL DEFAULT 'active' CHECK (
                        status IN ('active','complete','cancelled')
                    ),
    last_sent_at    TEXT,                                   -- ISO 8601 UTC of the most recent successful send
    completed_at    TEXT,                                   -- set when status flips to 'complete'
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(api_key_id, course_slug, started_at)
);

CREATE INDEX IF NOT EXISTS idx_course_subs_active
    ON course_subscriptions(status, last_sent_at);
CREATE INDEX IF NOT EXISTS idx_course_subs_key
    ON course_subscriptions(api_key_id);

-- Bookkeeping: scripts/migrate.py records this filename into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
