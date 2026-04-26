-- 021_line_users.sql
-- Adds `line_users` table — LINE Messaging API (AutonoMath LINE bot) user
-- registry + billing state + conversation flow state.
--
-- Scope: the LINE bot is a SECOND product surface, distinct from the core
-- ¥1/req REST+MCP API. It targets SMEs who would not install a CLI/SDK but
-- will tap a 4-button structured flow inside LINE to find matching
-- 補助金/融資/税制 programs. Billing is a ¥500/月 (税込 ¥550) flat
-- subscription after 10 free queries/month per LINE user.
--
-- ============================================================================
-- PRODUCT / BUSINESS MODEL NOTES
-- ============================================================================
-- * This is a DIFFERENT SKU from the ¥1/req API. It does NOT violate the
--   "no tiers, no flat SaaS" rule for the API — the LINE bot is a
--   self-contained B2C/B2B2C retail surface priced separately. See
--   memory/project_autonomath_business_model.md for context.
-- * Zero-touch: no human handoff, no onboarding call, no Slack. All state
--   fits in this one table.
-- * Free tier is 10 queries/month per LINE user, resetting at JST 月初
--   00:00. Aligned with the API's monthly cadence (anon_rate_limit uses
--   the same boundary) so users have a single mental model.
-- * We never call an LLM API to generate responses — the flow is pure
--   button-driven. The column `current_flow_state_json` persists the
--   state machine position ({step, answers: {...}}).
--
-- ============================================================================
-- PRIVACY / TOS
-- ============================================================================
-- * `line_user_id` is LINE's opaque identifier (per OA+user). It is NOT
--   a human-facing handle and cannot be used to contact the user outside
--   LINE. Treat as a pseudonymous key.
-- * `display_name` and `picture_url` are optionally supplied by LINE on
--   the `follow` event; the user can change or revoke them. Store the
--   latest snapshot, do not maintain a history.
-- * `blocked_at` records when the user blocks our OA. LINE stops
--   delivering webhooks after that; we keep the row to avoid ballooning
--   a `message` retry queue and to preserve the counter for billing
--   disputes.
-- * Stripe customer / subscription IDs are stored for linkage. Revocation
--   (failed payment) moves plan back to 'free'.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op.
-- The runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- line_users -- LINE bot user registry
-- ============================================================================
-- Design notes:
--   * PRIMARY KEY is line_user_id (LINE's opaque per-OA identifier, ~33
--     chars, format "U" + 32 hex). Not a UUID — we want natural-key
--     idempotency on the `follow` webhook (user re-adds after blocking).
--   * plan CHECK ('free','paid'): two values only. Paid = active Stripe
--     subscription; free = everything else (never subscribed / cancelled /
--     payment failed / dunning). Keep the check narrow so a typo in
--     webhook handling code fails loudly.
--   * query_count_mtd is the month-to-date counter. The reset boundary
--     sits in `query_count_mtd_resets_at` (next JST 月初 00:00). Webhook
--     code checks "now >= resets_at → zero the counter and advance
--     resets_at" inline rather than running a cron; this keeps the table
--     self-healing if the process restarts mid-month.
--   * current_flow_state_json persists the conversation state so the
--     webhook is stateless. Example payload:
--       {"step":"prefecture","answers":{"industry":"飲食"}}
--     NULL means "no flow in progress" (user is at rich-menu idle).
--   * updated_at is always touched on row write. added_at is set exactly
--     once (on follow event); we do not reset it on re-follow — the
--     original onboarding date is useful for cohort analysis.

CREATE TABLE IF NOT EXISTS line_users (
    line_user_id TEXT PRIMARY KEY,               -- LINE opaque user id (U + 32 hex)
    display_name TEXT,                           -- LINE profile display name (mutable)
    picture_url TEXT,                            -- LINE profile picture URL (mutable)
    language TEXT NOT NULL DEFAULT 'ja',         -- BCP-47; we only ship ja in v1
    added_at TEXT NOT NULL,                      -- ISO 8601 UTC of first follow event
    blocked_at TEXT,                             -- ISO 8601 UTC when user blocked OA
    plan TEXT NOT NULL DEFAULT 'free',           -- 'free' | 'paid'
    stripe_customer_id TEXT,                     -- cus_...
    stripe_subscription_id TEXT,                 -- sub_...
    query_count_mtd INTEGER NOT NULL DEFAULT 0,  -- queries consumed this JST month
    query_count_mtd_resets_at TEXT NOT NULL,     -- ISO 8601 UTC of next JST 月初 00:00
    last_query_at TEXT,                          -- ISO 8601 UTC of last prescreen call
    current_flow_state_json TEXT,                -- conversation state; NULL = idle
    updated_at TEXT NOT NULL,                    -- ISO 8601 UTC of last row write
    CHECK(plan IN ('free','paid'))
);

-- ============================================================================
-- Indexes
-- ============================================================================
-- Plan filter is used by admin reports ("how many paid users") and by the
-- Stripe reconciliation cron (walk all 'paid' rows, verify sub is still
-- active). Low cardinality but cheap.
CREATE INDEX IF NOT EXISTS idx_line_users_plan ON line_users(plan);

-- Subscription id lookup on Stripe webhooks. NULL-heavy (most users are
-- free); a partial index keeps it small.
CREATE INDEX IF NOT EXISTS idx_line_users_subscription
    ON line_users(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
