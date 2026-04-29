-- 106_line_message_log.sql
-- Adds `line_message_log` table — append-only audit trail for every
-- inbound LINE Messaging API event we processed (and every outbound
-- reply we sent in response). Required for billing reconciliation, fraud
-- investigation (replay attempts that fail signature verification), and
-- product analytics (rich-menu drop-off rate).
--
-- Scope reminder
-- --------------
-- The LINE bot is a SECOND product surface alongside the ¥3/req REST+MCP
-- API (migration 021's `line_users` is the user registry). This table is
-- purely structural — no LLM is involved, no LLM API is called from any
-- LINE webhook code path. Conversational flow is the deterministic state
-- machine in `src/jpintel_mcp/line/flow.py`.
--
-- Each inbound webhook event is **billed exactly once** at the moment we
-- process it:
--   * If the event's source `line_user_id` resolves to a `line_users` row
--     with `plan='paid'` (active Stripe subscription), the row is logged
--     here with `billed=1` and `billed_yen=3` and the event itself counts
--     as one ¥3 metered call against the parent `api_keys` row attached
--     to the LINE user (or against a synthetic LINE-product Stripe meter
--     in the absence of a parent key — see api/line_webhook.py for the
--     resolution order).
--   * If the event resolves to a `line_users` row with `plan='free'`,
--     the row is logged with `billed=0` and counted against the user's
--     monthly free quota in `line_users.query_count_mtd`. Quota exceeded
--     → we still log here (`billed=0`, `quota_exceeded=1`) so the audit
--     of "what we replied to vs what we billed for" is complete; the
--     reply payload is the rate-limit explainer instead of a result list.
--   * Anonymous (no `line_users` row yet — pre-`follow` event) is rare
--     because LINE delivers `follow` before `message`, but if it happens
--     we log with `billed=0` and `quota_exceeded=0`; the webhook flow
--     auto-creates the `line_users` row before responding.
--
-- Privacy / TOS
-- -------------
-- * `event_id` is LINE's own webhook event id (delivery-once token); we
--   use it for idempotency on retry — duplicate POSTs from LINE re-enter
--   this row's UNIQUE index and short-circuit re-billing.
-- * `payload_json` stores the **redacted** webhook event (we strip
--   `replyToken` and any 個人情報-shaped string before write — see
--   `_redact_payload` in api/line_webhook.py). Raw bodies never land here.
-- * 90-day rolling retention is enforced by the cron `purge_line_logs.py`
--   which DELETEs rows older than 90 days from `received_at`. We keep
--   the billing aggregate in `line_users.query_count_mtd` so the purge
--   does not lose audit-relevant numbers.
--
-- Idempotency
-- -----------
-- Every CREATE is IF NOT EXISTS; re-applying the migration is a no-op.
-- The `event_id` UNIQUE constraint is the dedup key for LINE retry
-- semantics: LINE re-POSTs an event after a 5xx from us, and we MUST not
-- double-bill (or worse, double-reply with stale state) — the INSERT OR
-- IGNORE in the webhook handler relies on this index.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS line_message_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,                      -- LINE webhook event id (delivery-once)
    line_user_id TEXT,                           -- FK to line_users.line_user_id (NULL pre-follow)
    event_type TEXT NOT NULL,                    -- 'message' | 'follow' | 'unfollow' | 'postback'
    direction TEXT NOT NULL,                     -- 'inbound' | 'outbound_reply' | 'outbound_push'
    flow_step TEXT,                              -- 'industry'|'prefecture'|'employees'|'revenue'|'results'|NULL
    payload_json TEXT NOT NULL,                  -- redacted event JSON (NO replyToken)
    billed INTEGER NOT NULL DEFAULT 0,           -- 0/1 — did we charge ¥3 for this round trip
    billed_yen INTEGER NOT NULL DEFAULT 0,       -- typically 0 or 3 (税抜); 税込 view in app code
    quota_exceeded INTEGER NOT NULL DEFAULT 0,   -- 0/1 — anon ran out of free queries
    api_key_hash TEXT,                           -- parent api_keys.key_hash if billed via parent
    received_at TEXT NOT NULL,                   -- ISO 8601 UTC of POST receipt
    processed_at TEXT,                           -- ISO 8601 UTC of reply send (NULL on inbound-only)
    CHECK(direction IN ('inbound','outbound_reply','outbound_push')),
    CHECK(billed IN (0,1)),
    CHECK(quota_exceeded IN (0,1))
);

-- LINE retry dedup. INSERT OR IGNORE on (event_id, direction) means a
-- replayed POST observes the prior INSERT's row and skips re-billing.
-- A single event has one inbound row plus optionally one outbound_reply
-- row, so the unique key includes direction.
CREATE UNIQUE INDEX IF NOT EXISTS idx_line_message_log_event_direction
    ON line_message_log(event_id, direction);

-- Hot path: "what is the user's current flow position?" — the webhook
-- could read line_users.current_flow_state_json for that, but for
-- analytics ("how many users dropped at step=prefecture this month?")
-- we want to query the log directly.
CREATE INDEX IF NOT EXISTS idx_line_message_log_user_received
    ON line_message_log(line_user_id, received_at);

-- Billing reconciliation: walk all billed=1 rows in a billing period to
-- cross-check against the Stripe metered meter for the LINE product.
CREATE INDEX IF NOT EXISTS idx_line_message_log_billed_received
    ON line_message_log(received_at) WHERE billed = 1;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
