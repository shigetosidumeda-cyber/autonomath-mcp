-- target_db: jpintel
-- migration 111_analytics_events
--
-- P0-10 fix (2026-04-30): `usage_events` is 0 rows in production because
-- `usage_events.key_hash NOT NULL` forbids anonymous traffic, and 99% of
-- launch-window traffic is anonymous (3/day free tier). Result: every
-- analytics / adoption / feature-coverage dashboard reads zero.
--
-- Fix: capture EVERY HTTP request (auth + anon) in a separate
-- `analytics_events` table, written by `AnalyticsRecorderMiddleware` via
-- BackgroundTasks (never blocks response). `usage_events` remains the
-- authoritative billing ledger; this table is for traffic analytics only.
-- The two are intentionally orthogonal — billing must not double-count,
-- analytics must not under-count.
--
-- PII posture: raw IP NEVER stored. `anon_ip_hash` is the same daily-rotated
-- sha256(ip||salt||day) hash used by `empty_search_log.ip_hash` (see
-- `deps.hash_ip_for_telemetry`). `key_hash` is the existing HMAC, NOT raw
-- key material. `path` is the URL path with query string stripped.
--
-- Idempotent: every CREATE uses IF NOT EXISTS. Re-applying on every boot
-- via entrypoint.sh §4 (jpintel target) is safe.

CREATE TABLE IF NOT EXISTS analytics_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    status        INTEGER NOT NULL,
    latency_ms    INTEGER,
    key_hash      TEXT,
    anon_ip_hash  TEXT,
    client_tag    TEXT,
    is_anonymous  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_ts
    ON analytics_events(ts DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_events_path_ts
    ON analytics_events(path, ts DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_events_key_ts
    ON analytics_events(key_hash, ts DESC)
    WHERE key_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_analytics_events_anon_ts
    ON analytics_events(anon_ip_hash, ts DESC)
    WHERE anon_ip_hash IS NOT NULL;
