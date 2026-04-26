-- 009_email_schedule_retry.sql
-- Retry bookkeeping columns for the onboarding scheduler. Extends the table
-- from 008_email_schedule.sql without rewriting existing rows.
--
-- Why these three columns:
--
--   attempts INTEGER NOT NULL DEFAULT 0
--     Incremented by `scripts/send_scheduled_emails.py` on every dispatch
--     attempt (both success and failure). A row whose `sent_at IS NULL AND
--     attempts >= N` can be rolled into a dead-letter alert without losing
--     the original schedule — we never delete scheduled rows, just stop
--     picking them.
--
--   last_error TEXT
--     Last transport / API error string from the Postmark send path. Reset
--     to NULL on a successful dispatch. Operators read this when a row
--     lingers with sent_at IS NULL to decide between "retry" and "give up".
--
--   template_model_json TEXT
--     Serialized TemplateModel dict the scheduler should hand to Postmark.
--     Nullable so rows created by 008 (pre-retry) keep working — the
--     scheduler rebuilds the model from the current api_keys + usage rows
--     when this column is NULL, and writes it back on first read so the
--     payload is frozen at send time going forward.
--
-- SQLite ALTER TABLE ADD COLUMN is cheap (no rewrite) and idempotent when
-- wrapped in IF NOT EXISTS — but SQLite does NOT support IF NOT EXISTS on
-- ADD COLUMN. We use `pragma_table_info` guards via the migrate.py runner
-- so re-applies do not fail.

ALTER TABLE email_schedule ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE email_schedule ADD COLUMN last_error TEXT;
ALTER TABLE email_schedule ADD COLUMN template_model_json TEXT;
