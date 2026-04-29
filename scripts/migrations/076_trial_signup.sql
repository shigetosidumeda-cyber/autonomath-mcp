-- migration 076: email-only trial signup (magic-link → time-boxed evaluation key)
--
-- target_db: jpintel.db
--
-- Background (conversion-pathway audit, 2026-04-29):
--   The only path to a real API key today is Stripe Checkout (card required
--   up-front). That loses dev evaluators who want to try N free trial calls
--   before committing — the OpenAI / Anthropic / Stripe norm is "email +
--   verification → time-boxed trial → in-app prompt to add a card". 100% of
--   anonymous bouncers leave no contact info today; we cannot remarket,
--   rescue, or learn why they left.
--
--   This migration adds the storage for an email-only signup flow:
--
--     1. POST /v1/signup            { email } → row in trial_signups,
--                                                magic-link mailed.
--     2. GET  /v1/signup/verify     ?token=...  → trial api_keys row
--                                                 issued (tier='trial',
--                                                 14 days, 200 reqs hard
--                                                 cap, no card on file).
--     3. Cron `expire_trials.py`    → revokes keys past 14 days OR over
--                                     the request cap.
--
--   The trial is NOT a "Free tier" SKU — pricing stays ¥3/req metered
--   post-trial. After expiry the user can re-sign up via Stripe Checkout
--   for a paid key (existing path), or fall back to the anonymous
--   50/月 per-IP free quota (existing AnonIpLimitDep). See
--   project_autonomath_business_model + feedback_zero_touch_solo.
--
-- Constraints:
--   * Solo + zero-touch: NO operator approval. Email verification is the
--     only gate. The magic-link token is HMAC-bound to the trial_signups
--     row so verify() needs no DB read for token validity (same recipe as
--     api/subscribers.make_unsubscribe_token).
--   * 1 trial per email lifetime — UNIQUE on email_normalized below.
--     Re-signing up returns 409 with a pointer to Stripe Checkout.
--   * 1 trial signup per IP per 24h — enforced at the API layer with a
--     short-window check against created_at; no separate index needed,
--     the email PK + idx_trial_signups_ip_recent below cover both.
--   * Email dedup is gmail-aware. A.user+tag@gmail.com and auser@gmail.com
--     normalize to the same email_normalized so a determined attacker
--     can't claim 100 trials by walking the +tag namespace.
--
-- Schema layout:
--
--   trial_signups
--     One row per (email_normalized) lifetime. Holds the unverified
--     pending state until magic-link click; once clicked, a row in
--     api_keys (tier='trial') is born and trial_signups.verified_at
--     stamps the moment. The token never goes into the DB — we store
--     `token_hash` (HMAC) so a DB exfil cannot replay the magic link.
--
--   api_keys.tier
--     The tier column is already TEXT (not enum-constrained — see
--     schema.sql:107). 'trial' joins {'free','paid'} as the third
--     legal value. require_key() (api/deps.py) currently treats
--     anything that's not 'paid' as non-metered, which is the correct
--     posture for trial keys: NO Stripe usage_records, NO billing.
--     The trial cap is enforced via api_keys.monthly_cap_yen (existing
--     CustomerCapMiddleware) by setting it to 200 * ¥3 = ¥600 — every
--     metered=0 trial request is capped on the request count side via
--     the new trial_requests_used column (see below) which the
--     middleware checks BEFORE the cap_yen check.
--
--   api_keys.trial_email
--     Captured at trial issuance. Lets the expire_trials cron fire the
--     "your trial ended" mail without joining back to trial_signups.
--   api_keys.trial_started_at
--     ISO timestamp of magic-link verify (== api_keys.created_at for
--     trial rows; duplicated here so the cron can index on a single
--     column without a tier filter).
--   api_keys.trial_expires_at
--     ISO timestamp 14 days after start. Cron compares
--     `datetime('now') >= trial_expires_at` and revokes.
--   api_keys.trial_requests_used
--     Counter incremented by middleware on every successful trial-key
--     request. When >= 200, key is force-revoked (cron sweeps daily
--     but middleware can also short-circuit on hit).
--
-- Idempotency:
--   IF NOT EXISTS on table + ALTER TABLE ADD COLUMN (no-op-on-duplicate
--   per scripts/migrate.py). Re-applying via init_db() on a fresh
--   test DB is safe.
--
-- DOWN (commented; suppress / signup history must be preserved per
-- 特電法 §3-2 i + 30-day APPI deletion SLA):
--   -- (no-op)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. trial_signups — one row per (email_normalized) lifetime
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trial_signups (
    -- The submitted email, preserved verbatim for the welcome mail. We
    -- never echo this back via API.
    email TEXT NOT NULL,
    -- Lower-cased + gmail-dot-collapsed + plus-tag-stripped form. Used
    -- as the dedup key. Computed by the API layer (see
    -- src/jpintel_mcp/api/signup.py::_normalize_email).
    email_normalized TEXT PRIMARY KEY,
    -- HMAC(api_key_salt, email_normalized || created_at) — verify() recomputes
    -- and compare_digest. Stored so `_verify_token` can reject after
    -- expiry without trusting the URL alone (server-side log of which
    -- token was actually issued).
    token_hash TEXT NOT NULL,
    -- ISO 8601 UTC. Magic-link valid window is 24h from this stamp.
    created_at TEXT NOT NULL,
    -- IP that submitted the signup. Stored for the 24h-per-IP rate gate
    -- (the API layer COUNTs rows WHERE created_ip_hash = ? AND
    -- created_at > now()-24h). Hashed (HMAC, same recipe as
    -- anon_limit.hash_ip) so a DB exfil cannot reverse to raw IPs.
    created_ip_hash TEXT,
    -- ISO 8601 UTC. Stamped at /v1/signup/verify. Until non-NULL the
    -- signup is unverified and no api_keys row exists.
    verified_at TEXT,
    -- key_hash of the issued trial api_keys row. NULL until verified.
    -- FK to api_keys.key_hash so a manual revoke cascades.
    issued_api_key_hash TEXT,
    FOREIGN KEY(issued_api_key_hash) REFERENCES api_keys(key_hash)
);

-- For the 24h-per-IP signup gate. NOT a UNIQUE — multiple distinct
-- emails from one IP within 24h is allowed once (the per-IP cap is
-- 1, but counting via this index is faster than a tablescan).
CREATE INDEX IF NOT EXISTS idx_trial_signups_ip_recent
    ON trial_signups(created_ip_hash, created_at);

-- For the cron `expire_trials` daily sweep — it scans trial_signups
-- joined with api_keys WHERE verified_at IS NOT NULL.
CREATE INDEX IF NOT EXISTS idx_trial_signups_verified
    ON trial_signups(verified_at)
    WHERE verified_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. api_keys.trial_* columns — issued-trial-key state
-- ---------------------------------------------------------------------------
-- ALTER TABLE ADD COLUMN is no-op-on-duplicate per the migrate runner.

ALTER TABLE api_keys ADD COLUMN trial_email TEXT;
ALTER TABLE api_keys ADD COLUMN trial_started_at TEXT;
ALTER TABLE api_keys ADD COLUMN trial_expires_at TEXT;
ALTER TABLE api_keys ADD COLUMN trial_requests_used INTEGER NOT NULL DEFAULT 0;

-- Cron sweep: WHERE tier='trial' AND revoked_at IS NULL ORDER BY
-- trial_expires_at. Partial-index keeps scan cost ≈ open-trial count.
CREATE INDEX IF NOT EXISTS idx_api_keys_trial_expiry
    ON api_keys(trial_expires_at)
    WHERE tier = 'trial' AND revoked_at IS NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
