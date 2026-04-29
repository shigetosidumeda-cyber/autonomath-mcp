-- target_db: jpintel
-- migration 080_customer_webhooks (Customer-side outbound webhooks, ¥3/req metered)
--
-- Why this exists:
--   `alert_subscriptions` (mig 038) is a FREE retention surface for amendment
--   alerts only — fan-out cost is absorbed as customer success. This new
--   surface is materially different in three ways:
--     1. SCOPE — covers structured product events (program.created /
--        program.amended / enforcement.added / tax_ruleset.amended /
--        invoice_registrant.matched), not just am_amendment_snapshot rows.
--     2. PRICING — every successful delivery is metered ¥3/req via Stripe
--        usage_records (project_autonomath_business_model). Customer pays
--        for the proactive push the same way they would have paid for the
--        equivalent poll request.
--     3. SECURITY — HMAC-sha256 signature is REQUIRED (not optional like
--        the alerts surface). The shared secret is generated server-side at
--        registration time and revealed exactly once.
--
-- Append-only delivery log:
--   `webhook_deliveries` is the per-attempt audit trail. One row per
--   POST attempt (initial + retries). The dispatcher uses it for
--   idempotency (event_id+webhook_id dedup) and for the dashboard "recent
--   deliveries" table. After 5 consecutive failures the parent
--   customer_webhooks row flips status='disabled' so a runaway billing
--   loop is impossible. The customer reactivates via DELETE+re-register.
--
-- Idempotency: this migration is idempotent — every CREATE uses IF NOT EXISTS
-- and there is no DML. Running on every Fly boot via entrypoint.sh §4 is safe.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customer_webhooks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash        TEXT NOT NULL,
    url                 TEXT NOT NULL,
    -- JSON array of subscribed event types. Examples:
    --   ["program.created","program.amended"]
    --   ["enforcement.added","tax_ruleset.amended","invoice_registrant.matched"]
    -- Empty array == register but receive nothing (defensive default).
    event_types_json    TEXT NOT NULL DEFAULT '[]',
    -- HMAC-sha256 shared secret (raw, server-issued). Surfaced to the
    -- customer ONCE on POST /v1/me/webhooks (parity with raw API key
    -- issuance via /signup → success.html). Subsequent GET /v1/me/webhooks
    -- returns only the last 4 chars; full secret is impossible to recover
    -- from the API alone (the customer must re-register to get a new one).
    secret_hmac         TEXT NOT NULL,
    -- 'active' / 'disabled' (auto-disabled after 5 consecutive failures
    -- — see scripts/cron/dispatch_webhooks.py). Customer can also manually
    -- DELETE which flips status to 'disabled' AND drops the row from the
    -- listing.
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'disabled')),
    last_delivery_at    TEXT,
    -- Consecutive failure counter. Reset to 0 on the first successful
    -- delivery after a streak. Reaching `failure_count >= 5` triggers
    -- auto-disable + customer email.
    failure_count       INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    disabled_at         TEXT,
    -- When auto-disabled by the dispatcher, this is the human-readable
    -- reason ("5 consecutive failures: connection_refused"). NULL when
    -- the webhook is active or was disabled manually by the customer.
    disabled_reason     TEXT
);

CREATE INDEX IF NOT EXISTS idx_customer_webhooks_key
    ON customer_webhooks(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_customer_webhooks_active
    ON customer_webhooks(status, api_key_hash) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id      INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    -- Stable identifier for the underlying event so the dispatcher can
    -- skip already-delivered events on re-run. For program.amended this
    -- is the am_amendment_diff.diff_id; for enforcement.added it is
    -- enforcement_cases.case_id; etc. Combined with webhook_id this is
    -- the natural dedup key.
    event_id        TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    -- HTTP status code from the final attempt. NULL while the row is
    -- still pending dispatch (initial insert before the first POST).
    status_code     INTEGER,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    delivered_at    TEXT,
    -- Short error string (truncated to 1024 chars). NULL on success.
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (webhook_id) REFERENCES customer_webhooks(id)
);

-- Dedup hot path: "did we already deliver event X to webhook Y?"
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_deliveries_dedup
    ON webhook_deliveries(webhook_id, event_type, event_id);

-- Dashboard "recent 10 deliveries" hot path.
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_recent
    ON webhook_deliveries(webhook_id, created_at DESC);

-- Bookkeeping recorded by scripts/migrate.py.
