-- target_db: jpintel
-- migration 088_houjin_watch — Real-time amendment watch surface
--
-- Why this exists:
--   The M&A pillar bundle (2026-04-29) lifts boutique ARPU 16x by exposing
--   four high-leverage surfaces on top of the existing ¥3/req metering.
--   `customer_watches` is the persistent registration table for Pillar 2:
--   real-time amendment watches scoped to one of three target kinds:
--
--     * 'houjin'   — watch a 法人番号 for amendment / enforcement / invoice
--                    delta events (joins am_amendment_diff +
--                    jpi_enforcement_cases + jpi_invoice_registrants).
--     * 'program'  — watch a programs.unified_id for amendment fan-out
--                    (joins am_amendment_diff scoped to the program).
--     * 'law'      — watch a laws.law_id for am_amendment_diff rows whose
--                    detected change references the statute.
--
--   Distinct from `customer_webhooks` (migration 080) which is the *delivery
--   channel* (URL + secret + event_types). A watch row says "fire on any
--   event matching this target"; the dispatcher then materialises the event,
--   looks up the customer's webhook(s) and POSTs once per delivery (¥3
--   metered per delivery, retries free — same pricing as the existing
--   webhook surface).
--
-- Pricing (project_autonomath_business_model — immutable):
--   Watch *registration* is FREE. Each successful HTTP 2xx delivery emits
--   one Stripe usage_record at ¥3/req. Failed deliveries (timeout, 4xx,
--   5xx) and retries do NOT bill. Auto-disable after 5 consecutive
--   failures (parent customer_webhooks.status='disabled') prevents runaway
--   billing.
--
-- Idempotency: this migration is idempotent — every CREATE uses IF NOT
-- EXISTS and there is no DML. Running on every Fly boot via entrypoint.sh
-- §4 is safe.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customer_watches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash    TEXT NOT NULL,
    -- 'houjin' | 'program' | 'law'. CHECK constraint mirrors the dispatcher's
    -- collector switch. Adding a new watch_kind requires both:
    --   (a) extending the CHECK below
    --   (b) wiring a collector in scripts/cron/dispatch_watch_events.py
    watch_kind      TEXT NOT NULL
                        CHECK (watch_kind IN ('houjin', 'program', 'law')),
    -- For watch_kind='houjin' this is the 13-digit 法人番号 (NFKC-stripped,
    -- no 'T' prefix). For 'program' it is programs.unified_id. For 'law'
    -- it is laws.law_id. The dispatcher MUST treat target_id as opaque per
    -- watch_kind and never cross-resolve.
    target_id       TEXT NOT NULL,
    registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    -- Updated by the dispatcher when an event matching this watch is fired.
    -- NULL means no event has been delivered yet.
    last_event_at   TEXT,
    -- 'active' | 'disabled'. Customer-side soft-delete via DELETE
    -- /v1/me/watches/{id} flips to 'disabled'; the row stays for audit.
    -- The dispatcher only collects events for status='active' rows.
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'disabled')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    disabled_at     TEXT,
    -- Free-form short reason ("deleted_by_customer", etc.). NULL when active.
    disabled_reason TEXT
);

-- Hot path: list-my-watches and "is this (api_key_hash, watch_kind,
-- target_id) already registered?" dedup check at register time.
CREATE INDEX IF NOT EXISTS idx_customer_watches_key
    ON customer_watches(api_key_hash, status);

-- Dispatcher collector hot path: for each (kind, target_id) tuple, find all
-- active watches subscribed. Indexed only on active rows so the planner can
-- skip the disabled tail entirely.
CREATE INDEX IF NOT EXISTS idx_customer_watches_target_active
    ON customer_watches(watch_kind, target_id, api_key_hash)
 WHERE status = 'active';

-- Dedup: a single (api_key_hash, watch_kind, target_id) tuple should only
-- ever have one ACTIVE row. The application-side register handler enforces
-- this (re-registering a target soft-toggles the existing row); this
-- partial unique index is the belt-and-suspenders backstop. Idempotent
-- create is safe — sqlite silently accepts the same definition.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_watches_active_target
    ON customer_watches(api_key_hash, watch_kind, target_id)
 WHERE status = 'active';

-- Bookkeeping recorded by scripts/migrate.py.
