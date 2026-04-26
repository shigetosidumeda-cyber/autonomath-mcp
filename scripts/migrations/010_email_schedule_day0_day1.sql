-- 010_email_schedule_day0_day1.sql
-- Extends the `email_schedule.kind` CHECK constraint to admit `day0` and
-- `day1`. D+0 is the one-time welcome mail (raw key delivery) and is still
-- fired synchronously from `api/billing.py::_send_welcome_safe` — the kind
-- is whitelisted only so retroactive / audit backfill INSERTs do not hit
-- the CHECK clause. D+1 is the first cron-fired mail of the onboarding
-- sequence and carries the "if you're stuck, try this" quick-win recipes.
--
-- Why a full table rebuild:
--   SQLite does not support ALTER on CHECK constraints. The documented
--   recipe is the create-copy-drop-rename dance below. We keep the same
--   primary key, UNIQUE constraint, column order, and data. We reapply
--   the two indices after the rename so query plans are unchanged.
--
-- Why `INSERT OR IGNORE`:
--   Re-applying this migration on a DB that already has the new CHECK
--   (fresh install via schema.sql) is still required because
--   scripts/migrate.py records per-file idempotency in schema_migrations,
--   but a reapply while the table carries the new shape must not fail on
--   a UNIQUE collision. INSERT OR IGNORE + the subsequent DROP-RENAME
--   makes this a no-op if someone re-runs the script.
--
-- Historic rows are preserved byte-for-byte. New rows can now carry
-- kind='day0' or kind='day1'.

BEGIN;

CREATE TABLE IF NOT EXISTS email_schedule_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id TEXT NOT NULL,
    email TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK(kind IN ('day0','day1','day3','day7','day14','day30')),
    send_at TIMESTAMP NOT NULL,
    sent_at TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    template_model_json TEXT,
    created_at TIMESTAMP NOT NULL,
    UNIQUE(api_key_id, kind)
);

INSERT OR IGNORE INTO email_schedule_new
    (id, api_key_id, email, kind, send_at, sent_at, attempts, last_error,
     template_model_json, created_at)
SELECT
    id, api_key_id, email, kind, send_at, sent_at, attempts, last_error,
    template_model_json, created_at
FROM email_schedule;

DROP TABLE email_schedule;

ALTER TABLE email_schedule_new RENAME TO email_schedule;

CREATE INDEX IF NOT EXISTS idx_email_schedule_due
    ON email_schedule(send_at, sent_at);
CREATE INDEX IF NOT EXISTS idx_email_schedule_api_key
    ON email_schedule(api_key_id);

COMMIT;
