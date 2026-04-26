-- 022_widget_keys.sql
-- Embed Widget SDK — origin-whitelisted API keys for the 「1 行で埋め込める」
-- 補助金検索 widget (税理士事務所・商工会議所・中小企業支援サイト向け).
--
-- Business model (distinct from the main ¥1/req metered API):
--   - Business plan: ¥10,000/月 base, 10,000 req/月 含む, ¥1/req overage,
--     "powered by AutonoMath" footer mandatory.
--   - Whitelabel plan: ¥30,000/月 base, effectively unlimited (fair use 100,000/月),
--     footer can be hidden.
--
-- Why a separate table from `api_keys`:
--   * Different key format (`wgt_live_{32 hex}` vs `am_{...}`). An agent
--     that leaks an `am_` key from a server can wreck the bill; a `wgt_`
--     key is already exposed in the browser by design, but is gated by
--     Origin header + rate limit so blast radius is bounded.
--   * Different permissions: widget keys only reach `/v1/widget/*`
--     (search + enum_values + usage), not the full programs / billing
--     surface. Separate table makes the permission gap explicit at the
--     schema level, not just the handler level.
--   * Different quota shape: monthly bucket with an "included" volume
--     plus overage, not daily dunning or pure metered. reqs_used_mtd /
--     reqs_total are kept denormalized on the row to avoid a usage_events
--     JOIN on every request — the widget path is read-heavy and rate
--     limited so a counter on the row is enough.
--
-- CORS contract:
--   * allowed_origins_json is a JSON array of allowed Origin headers.
--     Exact match ("https://example.com") or wildcard subdomain
--     ("https://*.example.com"). The match is performed in Python
--     (src/jpintel_mcp/api/widget_auth.py::_origin_allowed) — SQLite does
--     not do pattern matching inside a JSON array natively, and we do
--     NOT want LIKE-injection vectors.
--   * CORS preflight (OPTIONS) returns the matched origin verbatim —
--     never "*" — so the browser validates the key belongs on that site.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS widget_keys (
    key_id TEXT PRIMARY KEY,                 -- 'wgt_live_' + 32 hex chars
    owner_email TEXT NOT NULL,               -- Stripe customer email (contact + 特商法)
    label TEXT,                              -- user-friendly name e.g. "My Tax Advisor Site"
    allowed_origins_json TEXT NOT NULL,      -- JSON array of allowed Origins
    stripe_customer_id TEXT NOT NULL,
    stripe_subscription_id TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'business',   -- 'business' | 'business_whitelabel'
    included_reqs_mtd INTEGER NOT NULL DEFAULT 10000,
    reqs_used_mtd INTEGER NOT NULL DEFAULT 0,  -- rolls over at JST 月初 00:00
    reqs_total INTEGER NOT NULL DEFAULT 0,     -- lifetime counter, never resets
    branding_removed INTEGER NOT NULL DEFAULT 0, -- BOOLEAN (SQLite stores 0/1)
    bucket_month TEXT,                       -- 'YYYY-MM' JST; monthly rollover key
    created_at TEXT NOT NULL,
    disabled_at TEXT,                        -- NULL = active
    last_used_at TEXT,
    updated_at TEXT NOT NULL,
    CHECK(plan IN ('business', 'business_whitelabel')),
    CHECK(length(key_id) = 41 AND substr(key_id, 1, 9) = 'wgt_live_'),
    CHECK(branding_removed IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_widget_keys_customer
    ON widget_keys(stripe_customer_id);

-- Partial index on active keys — the hot path is "is this key active?".
CREATE INDEX IF NOT EXISTS idx_widget_keys_active
    ON widget_keys(disabled_at) WHERE disabled_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_widget_keys_subscription
    ON widget_keys(stripe_subscription_id);

-- Bookkeeping recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
