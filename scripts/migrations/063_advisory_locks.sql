-- 063_advisory_locks.sql
-- App-level advisory locks for SQLite, keyed by arbitrary TEXT.
-- audit: a23909ea8a7d67d64 (2026-04-25)
--
-- Stripe subscription status refresh runs from BOTH the
-- `customer.subscription.updated` webhook AND the BackgroundTasks helper
-- `_refresh_subscription_status_from_stripe_bg` (now also via
-- bg_task_queue worker). Two refreshes for the same subscription_id can
-- race the UPDATE on `api_keys.stripe_subscription_status` -- whichever
-- writer's stale-by-a-few-ms read of Stripe wins last. SQLite has no
-- native advisory locks like Postgres `pg_advisory_lock(int)`, so we roll
-- our own keyed-by-TEXT, TTL-protected table.
--
-- Design notes:
--   * `key` is a free-form TEXT primary key (e.g. "subscription:sub_xyz",
--     "customer:cus_abc"). Caller picks a namespace; this table is
--     namespace-agnostic.
--   * `holder` identifies WHO owns the lock so only the original holder
--     can release. Format = f"{os.getpid()}:{threading.get_ident()}:{time.monotonic_ns()}".
--     The monotonic_ns suffix prevents a (pid, tid) pair from accidentally
--     releasing a previous lock with the same identity after a quick
--     acquire/release/acquire cycle.
--   * `ttl_s` is the maximum lock duration. Default 30s matches the
--     subscription refresh path -- Stripe.Subscription.retrieve P95 is
--     well under 5s, but a stuck call must not wedge the lock forever.
--     Cleanup happens on EVERY acquire attempt (DELETE WHERE expires_at
--     < now()) so a crashed holder cannot block subsequent work.
--   * `expires_at` is precomputed at acquire time = acquired_at + ttl_s.
--     We store the absolute expiry (not just ttl_s) so the cleanup query
--     is a single index range scan with no per-row arithmetic.
--
-- The (expires_at) index supports the cleanup hot path; without it the
-- DELETE-then-INSERT contention pattern would degrade into a full-table
-- scan once thousands of expired-but-uncleaned rows accumulate (e.g. if
-- the cleanup phase silently fails).

CREATE TABLE IF NOT EXISTS advisory_locks (
    key TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    ttl_s INTEGER NOT NULL DEFAULT 30,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_advisory_locks_expires
    ON advisory_locks(expires_at);
