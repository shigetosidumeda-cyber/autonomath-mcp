-- 008_email_schedule.sql
-- Activation-sequence scheduler for the D+3 / D+7 / D+14 / D+30 post-signup
-- emails. Powers `scripts/send_scheduled_emails.py` (run daily via the
-- `.github/workflows/email-daily.yml` cron).
--
-- Why a table instead of cron-time cohort math:
--   * Idempotent re-runs. Each row carries its own `sent_at` marker, so a
--     cron replay after a partial failure does NOT double-send. Cohort-only
--     approaches (`WHERE created_at + N days == today`) re-fire on every
--     run until you layer bookkeeping on top anyway.
--   * Exactly-once schedule per (api_key, kind). The UNIQUE(api_key_id,
--     kind) constraint lets `issue_key()` blindly INSERT 4 rows at
--     issuance — a retry from Stripe (duplicate invoice.paid) is a harmless
--     IntegrityError that keeps existing rows intact.
--   * Retry on transient Postmark failure. `sent_at` stays NULL on a 5xx
--     send; tomorrow's cron picks the row back up. No dedicated retry
--     queue, no crontab surgery.
--
-- kind CHECK clause gates the enum at write-time so a typo in a migration
-- or an upstream refactor cannot silently insert `day_3` vs `day3`. The
-- scheduler script dispatches on this exact string.
--
-- Index idx_email_schedule_due serves the hot path:
--     SELECT ... WHERE send_at <= ? AND sent_at IS NULL
-- Ordering columns as (send_at, sent_at) keeps planning simple; a partial
-- index on sent_at IS NULL would be slightly tighter but SQLite only added
-- partial index cost-estimation recently and we keep this portable.
--
-- Unsubscribe routing: an onboarding email that the recipient unsubscribes
-- from (by clicking the footer link, bouncing, or marking spam) flips
-- subscribers.unsubscribed_at on the matching email row. The sender script
-- skips rows whose Stripe customer email is already in `subscribers` with
-- `unsubscribed_at IS NOT NULL` — see send_scheduled_emails.py for the
-- suppression join.
--
-- NO foreign key to api_keys(key_hash) because api_keys has key_hash as PK
-- (TEXT), not an INTEGER id. We cascade-delete manually in revoke_key /
-- revoke_subscription paths; losing the ability to delete the key while
-- schedule rows linger is actually fine — the daily cron will try to send,
-- find the key revoked via a LEFT JOIN, and mark the row skipped.

CREATE TABLE IF NOT EXISTS email_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id TEXT NOT NULL,              -- api_keys.key_hash (TEXT PK over there)
    email TEXT NOT NULL,                   -- resolved recipient at schedule time
    kind TEXT NOT NULL
        CHECK(kind IN ('day3','day7','day14','day30')),
    send_at TIMESTAMP NOT NULL,            -- ISO 8601 UTC; cron compares lexicographically
    sent_at TIMESTAMP,                     -- NULL until successfully dispatched
    created_at TIMESTAMP NOT NULL,
    UNIQUE(api_key_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_email_schedule_due
    ON email_schedule(send_at, sent_at);

CREATE INDEX IF NOT EXISTS idx_email_schedule_api_key
    ON email_schedule(api_key_id);
