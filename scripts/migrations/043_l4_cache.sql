-- 043_l4_cache.sql
-- L4 query-result cache (v8 P5-ε++ / 4-Layer cache architecture, dd_v8_C3).
--
-- Business context:
--   AutonoMath ships the "Pre-computed Reasoning Layer" — answers are not
--   recomputed on every customer request. Layers L0..L3 (storage / atomic
--   queries / composite joins / multi-tool reasoner) compute the "shape"
--   of each answer once at ingest / nightly. L4 sits ABOVE L3 and caches
--   the *serialized response blob* for hot queries — the Zipf-shaped tail
--   of identical params that hammers the same tool repeatedly.
--
-- Why not rely on jpintel.db's normal page cache:
--   * SQLite's page cache is per-connection and cold on every Fly machine
--     restart. L4 is a *DB row* keyed by sha256(tool + params), so it is
--     warm across restarts and across machines (the row is in the on-disk
--     file). cache_warm.py refreshes the top 100 entries every 24h so the
--     T+30d hit rate target (60%) holds even right after a deploy.
--   * Materialised views (the L2 / L3 layers) precompute SHAPES; L4 caches
--     the EXACT serialized JSON the API returns. That avoids the
--     join-and-format step, which dominates p95 for the high-cardinality
--     enums (search_tax_incentives by 9 sectors etc.).
--
-- Cost / margin posture:
--   * ¥3/req metered pricing is non-negotiable (project_autonomath_business_model).
--     Every request costs us ~¥0.24 of compute today. L4 cuts that to
--     ~¥0.04 for cache hits, which lifts margin from 92% → 95% at 80%
--     hit rate (Y1 Zipf saturation target).
--   * No Anthropic / claude / SDK calls. Pure SQLite blob storage.
--
-- Key shape (cache_key):
--   sha256(f"{tool_name}\n{canonical_json(params)}") → 64-char hex.
--   `canonical_json` = sort_keys + UTF-8 + no whitespace. The Python helper
--   in src/jpintel_mcp/cache/l4.py is the single source of truth — never
--   hand-roll a key elsewhere.
--
-- TTL semantics:
--   * `ttl_seconds` is per-row (default 86400 = 24h). Tools that depend on
--     amendment-snapshot freshness (laws / programs) override to 3600 = 1h.
--   * Read path is "row exists AND created_at + ttl_seconds > now-utc".
--     Stale rows are NOT deleted on read (avoid write-on-read amplification);
--     precompute_refresh.py / l4_cache_warm.py prune them on the nightly run.
--
-- LRU posture:
--   `last_hit_at` is bumped on every cache hit (single-row UPDATE, indexed).
--   The warm cron deletes the bottom-N rows by `last_hit_at` once the table
--   exceeds its soft cap (default 1000 rows), keeping the hot set in memory-
--   resident b-tree pages. hit_count is decorative (operator dashboards) and
--   NOT used for eviction.
--
-- Pre-launch state:
--   The table is created EMPTY. Customer query traffic will populate it
--   organically via cache.l4.get_or_compute(). l4_cache_warm.py also seeds
--   the top 100 Zipf candidates from usage_events (epoch >= now-7d) on its
--   first nightly run after launch. Empty table is the launch-day expected
--   state — do not block launch on a populated cache.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS l4_query_cache (
    cache_key   TEXT PRIMARY KEY,                       -- sha256(tool + canonical_json(params))
    tool_name   TEXT NOT NULL,
    params_json TEXT NOT NULL,                          -- canonical JSON (sort_keys, no whitespace)
    result_json TEXT NOT NULL,                          -- serialized API response blob
    hit_count   INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,                                   -- ISO 8601 UTC, bumped on every hit
    ttl_seconds INTEGER NOT NULL DEFAULT 86400,         -- per-row TTL (default 24h)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-tool eviction / inspection path (operator dashboards, refresh cron).
CREATE INDEX IF NOT EXISTS idx_l4_cache_tool
    ON l4_query_cache(tool_name);

-- LRU eviction path (warm cron deletes oldest last_hit_at once cap exceeded).
CREATE INDEX IF NOT EXISTS idx_l4_cache_lru
    ON l4_query_cache(last_hit_at);

-- TTL sweep path (refresh cron deletes rows where created_at + ttl < now).
CREATE INDEX IF NOT EXISTS idx_l4_cache_ttl
    ON l4_query_cache(created_at, ttl_seconds);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
