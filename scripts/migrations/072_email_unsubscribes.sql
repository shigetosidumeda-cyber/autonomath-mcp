-- migration 072: email_unsubscribes
--
-- target_db: jpintel.db
--
-- Background:
--   特定電子メール法 (Act on Regulation of Transmission of Specified
--   Electronic Mail) §3 requires opt-out for any "marketing" or "broadcast"
--   email — defined as 営業を目的とした広告又は宣伝のための電子メール.
--   Existing per-list unsubscribe state lives in two places today:
--     * `subscribers.unsubscribed_at` (newsletter / launch-updates list,
--       managed by api/subscribers.py + Postmark bounce/spam webhooks)
--     * `compliance_subscribers.deleted_at` (法令改正アラート paid list)
--   Both correctly suppress *their own* list, but neither acts as a global
--   "do-not-email" master record. A user who unsubscribes from the digest
--   today can still legitimately receive a future onboarding D+30 NPS mail
--   because the onboarding sequence keys off `email_schedule` rows tied
--   to the api_key, not the email address.
--
--   This table is the master suppression list — every transactional /
--   broadcast send path checks `email_unsubscribes.email` first, BEFORE
--   the per-list flag. The transactional security/取引関連 mails (D+0
--   welcome carrying the raw API key, key_rotated security notice, dunning
--   payment-failed) are EXEMPT from this check per 特電法 §3-2 i (取引
--   関連メール exemption) — those still fire even after the user opts out.
--
--   See docs/_internal/email_unsubscribe_2026-04-25.md (operator runbook,
--   to be authored at first ops incident — kept as a stub URL here).
--
-- Privacy / GDPR / 個情法:
--   `email` is the only column. We deliberately do NOT capture an IP, UA,
--   or any other request-derived metadata at unsubscribe time — the act
--   of opting out should not itself create a new personal-data record.
--   `unsubscribed_at` is server time (datetime('now') = UTC). `reason`
--   is free-text (max 64 chars enforced at the API layer) used by ops
--   to triage suppression sources: 'user-self-serve', 'bounce',
--   'spam-complaint', 'manual-ops'.
--
-- Idempotency:
--   IF NOT EXISTS on table. PRIMARY KEY on email means a second
--   unsubscribe of the same address is a silent no-op (INSERT OR IGNORE
--   at the API layer). Re-applying this migration via `migrate.py` and
--   `init_db()` on a fresh test/dev DB is safe (this DDL is mirrored at
--   the bottom of `src/jpintel_mcp/db/schema.sql`).
--
-- DOWN (commented — keep suppression history on rollback; 特電法 requires
-- the operator to be able to prove "we honoured the opt-out" for the
-- legal retention window):
--   -- DROP TABLE IF EXISTS email_unsubscribes;

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS email_unsubscribes (
    email TEXT PRIMARY KEY,
    unsubscribed_at TEXT NOT NULL DEFAULT (datetime('now')),
    reason TEXT
);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
