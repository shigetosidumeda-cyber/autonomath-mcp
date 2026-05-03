-- target_db: jpintel
-- migration 123_funnel_events
--
-- §4-E (jpcite_user_value_execution_plan_2026-05-03.md) — measurement
-- recovery. Two adjustments to the analytics layer:
--
-- 1. New table `funnel_events`: lightweight breadcrumbs from the static
--    site (Playground, pricing, MCP install, OpenAPI import, checkout,
--    dashboard sign-in) so the operator can answer "did the visitor get
--    past pricing", "did the curl copy fire", "did the playground
--    succeed N times before pricing view" — none of which surfaces in
--    `analytics_events` because that table only sees server-side traffic
--    and only as URL paths.
--
-- 2. Two new columns on `analytics_events` to separate bot-included
--    Cloudflare PV from human-ish API usage:
--
--      - `user_agent_class` — bucketed UA label (claude-code / cursor /
--        bot:googlebot / browser:firefox / unknown / ...) computed by
--        `_classify_user_agent` in `api/anon_limit.py`. Used to filter
--        bot traffic out of paid-conversion denominators.
--      - `is_bot` — derived flag (1 when the UA class starts with
--        `bot:`). Stored explicitly so dashboards can `WHERE is_bot=0`
--        without re-implementing the classifier.
--
-- Idempotent: every CREATE / ALTER is guarded against re-apply.
--   - CREATE TABLE / INDEX uses IF NOT EXISTS.
--   - ALTER TABLE ADD COLUMN — SQLite has no IF NOT EXISTS, but
--     `scripts/migrate.py:218` and `entrypoint.sh §4` both swallow
--     "duplicate column" errors and mark the migration applied.
--
-- PII posture: `funnel_events.anon_ip_hash` reuses the same daily-rotated
-- sha256(ip||salt||day) as `analytics_events.anon_ip_hash`. Raw IP NEVER
-- stored. `session_id` is a client-generated random 128-bit hex (no PII;
-- session-scoped only — sessionStorage on the browser side, not
-- persistent identifier).

-- ---- 1. funnel_events table -------------------------------------------------
CREATE TABLE IF NOT EXISTS funnel_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    -- Closed enum, validated in api/funnel_events.py (NOT a DB CHECK so
    -- that adding new event types in code does not require a migration):
    --   pricing_view, cta_click, playground_request, playground_success,
    --   playground_quota_exhausted, quickstart_copy, openapi_import_click,
    --   mcp_install_copy, checkout_start, dashboard_signin_success
    event_name      TEXT    NOT NULL,
    -- Page where the event fired (URL path, query stripped, PII redacted).
    page            TEXT,
    -- Optional discriminator (e.g. cta_click -> {"target":"playground"}).
    -- Capped at 512 chars in the API layer to keep this table compact.
    properties_json TEXT,
    -- Same daily-rotated hash as analytics_events.anon_ip_hash.
    anon_ip_hash    TEXT,
    -- Client-side random session id (sessionStorage; rotates per tab).
    session_id      TEXT,
    -- HMAC api_key hash when the visitor is signed in (dashboard pages).
    key_hash        TEXT,
    -- UA class label (mirrors analytics_events.user_agent_class).
    user_agent_class TEXT,
    -- 1 when the UA class starts with `bot:` — denormalised for fast
    -- filtering (paid_conversion_denominator excludes is_bot=1).
    is_bot          INTEGER NOT NULL DEFAULT 0,
    -- 1 when no key_hash present (anonymous visitor).
    is_anonymous    INTEGER NOT NULL DEFAULT 1,
    -- Optional referer host (e.g. "google.com", "claude.ai").
    referer_host    TEXT
);

CREATE INDEX IF NOT EXISTS idx_funnel_events_ts
    ON funnel_events(ts DESC);

CREATE INDEX IF NOT EXISTS idx_funnel_events_event_ts
    ON funnel_events(event_name, ts DESC);

CREATE INDEX IF NOT EXISTS idx_funnel_events_session
    ON funnel_events(session_id, ts ASC)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_funnel_events_key_ts
    ON funnel_events(key_hash, ts DESC)
    WHERE key_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_funnel_events_human_event_ts
    ON funnel_events(event_name, ts DESC)
    WHERE is_bot = 0;

-- ---- 2. analytics_events: add user_agent_class + is_bot --------------------
-- ALTER TABLE ADD COLUMN raises "duplicate column" on second apply; both
-- migrate.py and entrypoint.sh treat that as success and record the migration.
ALTER TABLE analytics_events ADD COLUMN user_agent_class TEXT;
ALTER TABLE analytics_events ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0;

-- Indexes for "humans only" queries (paid conversion denominator).
CREATE INDEX IF NOT EXISTS idx_analytics_events_human_path_ts
    ON analytics_events(path, ts DESC)
    WHERE is_bot = 0;

CREATE INDEX IF NOT EXISTS idx_analytics_events_ua_class_ts
    ON analytics_events(user_agent_class, ts DESC)
    WHERE user_agent_class IS NOT NULL;
