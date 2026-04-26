-- 038_alert_subscriptions.sql
-- Tier 3 amendment alert subscriptions (v8 P5-ι++ / dd_v8_08 H/I).
--
-- Business context:
--   * AutonoMath ingests 法令改正 / 制度新設 / 行政処分 events into
--     am_amendment_snapshot (autonomath.db, 14,596 rows). Customers want to
--     be notified proactively when a change matches their book — instead of
--     polling /v1/laws or /v1/programs daily.
--   * The subscription itself is FREE (no per-event ¥3/req surcharge). It
--     is a retention / customer-success feature, not a metered surface.
--     project_autonomath_business_model keeps ¥3/req immutable; the alert
--     fan-out cost is ours to absorb.
--   * Solo + zero-touch: filters live on the customer's row (api_key_hash),
--     no admin-side allow-list, no per-customer onboarding. Self-serve via
--     POST /v1/me/alerts/subscribe (alerts.py, this migration's twin).
--
-- Filter semantics:
--   filter_type ∈ ('tool', 'law_id', 'program_id', 'industry_jsic', 'all')
--     - 'all'           : match every amendment (filter_value ignored / NULL).
--     - 'tool'          : match by MCP tool name (e.g. 'search_tax_incentives').
--     - 'law_id'        : match by law_id reference on the entity.
--     - 'program_id'    : match by unified_id / canonical_id.
--     - 'industry_jsic' : match by JSIC industry code (am_industry_jsic join).
--
--   min_severity ∈ ('critical', 'important', 'info'):
--     - critical : 法令改廃 / 制度終了 (effective_until が新たに設定された 等)
--     - important: 補助率変更 / 上限額変更 / 対象拡大縮小
--     - info     : 出典再取得・微修正
--   The cron emits an alert only when the amendment's severity >= subscription's
--   min_severity (severity ranking: critical > important > info).
--
-- Webhook posture:
--   * webhook_url MUST be HTTPS (cron rejects http:// / scheme-less). The cron
--     also blocks RFC1918 / loopback hosts (127.0.0.1, 10.*, 172.16-31.*,
--     192.168.*) so a leaked URL cannot pivot into the internal network.
--   * email is optional fallback (NULL ⇒ webhook-only). Both can be set;
--     the cron tries webhook first, then sends email regardless of webhook
--     outcome (intentional: humans + machines are different consumers).
--
-- Idempotency: re-running this migration is safe — the runner records the
-- duplicate-table error and proceeds (CREATE TABLE IF NOT EXISTS is not
-- supported on schema_migrations bookkeeping path). Use `IF NOT EXISTS`
-- everywhere defensively.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash    TEXT NOT NULL,
    filter_type     TEXT NOT NULL CHECK (
                        filter_type IN ('tool', 'law_id', 'program_id', 'industry_jsic', 'all')
                    ),
    filter_value    TEXT,
    min_severity    TEXT NOT NULL DEFAULT 'important' CHECK (
                        min_severity IN ('critical', 'important', 'info')
                    ),
    webhook_url     TEXT,
    email           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_triggered  TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_sub_key
    ON alert_subscriptions(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_alert_sub_active
    ON alert_subscriptions(active, filter_type);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
