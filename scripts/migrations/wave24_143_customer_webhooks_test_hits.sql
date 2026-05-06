-- target_db: jpintel
-- migration wave24_143_customer_webhooks_test_hits (M15: SQLite-persisted webhook test rate limit)
--
-- Why this exists:
--   `customer_webhooks.py` previously enforced the 5 req/min/webhook test
--   delivery rate limit via an in-process `_test_hits: dict[int, list[float]]`
--   sliding window. That works for a single uvicorn worker but fails as
--   soon as we run 2+ workers (uvicorn --workers N, gunicorn -w N, or any
--   horizontal scale): each worker keeps its own dict and a customer can
--   trivially exceed the 5/min cap by spreading test deliveries across
--   workers. The cap exists to protect the customer's downstream from a
--   "save → test → tweak → test" misconfigure-loop hammering their endpoint
--   — bypassing it defeats that intent.
--
--   Persisting hits in SQLite gives worker-cross visibility. Every worker
--   reads the same table, so `SELECT COUNT(*) WHERE webhook_id = ? AND
--   hit_at >= datetime('now', '-1 minute')` correctly aggregates across
--   the entire fleet.
--
-- Schema:
--   webhook_id  INTEGER NOT NULL — FK-shape (no FK enforced) to
--                                   customer_webhooks.id. Hits are
--                                   intentionally *not* cascade-deleted on
--                                   parent DELETE because the test endpoint
--                                   already 404s on disabled rows; the
--                                   stale rows here age out of the
--                                   1-minute window almost immediately.
--   hit_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')) — UTC. The
--                                   1-minute window check uses
--                                   datetime('now', '-1 minute') which is
--                                   also UTC, so the comparison is
--                                   timezone-consistent.
--   ip          TEXT — caller IP (best-effort; recorded for forensics if
--                                   a single IP is abusing many webhook
--                                   ids). May be NULL if the request did
--                                   not surface a client.host (e.g. tests).
--
-- Index posture:
--   The hot path lookup is `WHERE webhook_id = ? AND hit_at >=
--   datetime('now', '-1 minute')`. A composite index on
--   (webhook_id, hit_at DESC) carries that lookup in one BTree walk and
--   also makes the prune query (`DELETE WHERE hit_at < datetime('now',
--   '-5 minutes')`) cheap if we add a periodic vacuum task later.
--
-- Idempotency:
--   `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` make
--   re-apply a no-op. No DML.
--
-- DOWN:
--   Additive only — drop the index then the table to roll back; the
--   read path falls back to the in-process dict path only if explicitly
--   reverted in `customer_webhooks.py`. With this migration applied and
--   the new code path live, the in-process dict is ignored.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customer_webhooks_test_hits (
    webhook_id  INTEGER NOT NULL,
    hit_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    ip          TEXT
);

CREATE INDEX IF NOT EXISTS idx_customer_webhooks_test_hits_lookup
    ON customer_webhooks_test_hits(webhook_id, hit_at DESC);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
