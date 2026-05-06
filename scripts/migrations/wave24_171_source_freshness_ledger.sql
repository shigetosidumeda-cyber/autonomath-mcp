-- target_db: autonomath
-- migration: wave24_171_source_freshness_ledger
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-03 (source_catalog / freshness / cross_source_signal)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Track the *honesty anchor* of every source_id: when did we last fetch, when
-- did the last success / failure occur, what was the failure reason, and what
-- is the as_of_date of the data currently surfaced from this source.
--
-- This is the source-of-truth for:
--   1. `known_gaps` blocks in artifact responses ("X 日前に最後 fetch 成功"),
--   2. trust_center freshness dashboard,
--   3. cron health alerts (>7 days stale on a tier-S source = pageable issue),
--   4. CI gates that block release if too many sources are stale.
--
-- Field semantics
-- ---------------
-- source_id              FK-like reference to source_catalog.source_id (no
--                        hard FK because catalog row can lag the ledger).
-- last_fetched_at        ISO 8601 UTC. ANY fetch attempt updates this.
-- last_success_at        ISO 8601 UTC. Only HTTP 200 + parse OK updates this.
-- last_failure_at        ISO 8601 UTC. Set on any non-success.
-- last_failure_reason    Short tag: "http_5xx", "http_4xx", "dns_fail",
--                        "parse_fail", "timeout", "auth_fail", "license_drift",
--                        "robots_drift", "schema_drift", "throttled". Free
--                        text past tag is allowed for paging.
-- consecutive_failures   INTEGER. Reset to 0 on success. Trigger threshold:
--                        >= 3 consecutive failures + tier-S source = alert.
-- next_scheduled_at      ISO 8601 UTC. When the cron expects to fetch next.
-- as_of_date             DATE (ISO 8601 yyyy-mm-dd). The freshness anchor of
--                        the data, NOT of the fetch. e.g. NTA monthly bulk
--                        fetched 2026-05-06 contains the 2026-04-30 snapshot,
--                        so as_of_date = 2026-04-30.
-- health_status          Derived: "fresh" / "warn" / "stale" / "alert".
--                        Updated by `refresh_source_freshness.py` cron based
--                        on ((now - last_success_at) vs update_frequency).
--
-- Indexes
-- -------
-- (source_id)                               — primary lookup
-- (next_scheduled_at, last_failure_at)      — cron scheduler hot path
-- (consecutive_failures DESC)               — alert prioritization
-- (health_status, source_id)                — dashboard rollup
-- (as_of_date DESC)                         — "what data is freshest"
--
-- Companion cron
-- --------------
-- `scripts/cron/refresh_source_freshness.py` walks every source_id in
-- source_catalog, runs a small HEAD-fetch (or GET on the smallest
-- canonical resource if HEAD is unsupported) to verify the URL still
-- resolves, and updates last_success_at / last_failure_at. The cron does
-- NOT re-pull the full bulk — it only verifies liveness. Full ingest is
-- the job of per-source cron scripts (e.g. nta-bulk-monthly).

CREATE TABLE IF NOT EXISTS source_freshness_ledger (
    source_id              TEXT NOT NULL PRIMARY KEY,
    last_fetched_at        TEXT,
    last_success_at        TEXT,
    last_failure_at        TEXT,
    last_failure_reason    TEXT NOT NULL DEFAULT '',
    consecutive_failures   INTEGER NOT NULL DEFAULT 0,
    next_scheduled_at      TEXT,
    as_of_date             TEXT,             -- ISO 8601 yyyy-mm-dd
    health_status          TEXT NOT NULL DEFAULT 'unknown' CHECK (health_status IN (
        'fresh', 'warn', 'stale', 'alert', 'unknown'
    )),
    last_http_status       INTEGER,           -- nullable; null = pre-fetch
    last_payload_bytes     INTEGER,           -- nullable; size sanity check
    last_etag              TEXT,              -- HTTP ETag if available
    last_last_modified     TEXT,              -- HTTP Last-Modified if available
    notes                  TEXT NOT NULL DEFAULT '',
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_freshness_source_id
    ON source_freshness_ledger (source_id);
CREATE INDEX IF NOT EXISTS idx_freshness_schedule
    ON source_freshness_ledger (next_scheduled_at, last_failure_at);
CREATE INDEX IF NOT EXISTS idx_freshness_consec_fail
    ON source_freshness_ledger (consecutive_failures DESC);
CREATE INDEX IF NOT EXISTS idx_freshness_health
    ON source_freshness_ledger (health_status, source_id);
CREATE INDEX IF NOT EXISTS idx_freshness_as_of
    ON source_freshness_ledger (as_of_date DESC);

-- View: alert candidates for daily ops sweep.
-- A tier-S source is "alert" if last_success_at is older than 7 days.
-- A tier-A source is "alert" at 14 days. Tier is read by joining source_catalog
-- (source_family) → tier mapping in v_source_freshness_alerts.
CREATE VIEW IF NOT EXISTS v_source_freshness_alerts AS
SELECT f.source_id,
       c.source_family,
       c.official_owner,
       c.update_frequency,
       f.last_success_at,
       f.last_failure_at,
       f.last_failure_reason,
       f.consecutive_failures,
       f.health_status,
       CAST(
         (julianday('now') - julianday(COALESCE(f.last_success_at, '1970-01-01')))
         AS INTEGER
       ) AS days_since_success
  FROM source_freshness_ledger f
  LEFT JOIN source_catalog c ON c.source_id = f.source_id
 WHERE f.health_status IN ('stale', 'alert')
    OR f.consecutive_failures >= 3
 ORDER BY f.consecutive_failures DESC, days_since_success DESC;

-- View: trust_center public freshness dashboard substrate.
-- Surfaced by GET /v1/sources/freshness (¥3/req).
CREATE VIEW IF NOT EXISTS v_source_freshness_public AS
SELECT f.source_id,
       c.source_family,
       c.update_frequency,
       f.as_of_date,
       f.health_status,
       CASE
         WHEN f.last_success_at IS NULL THEN NULL
         ELSE substr(f.last_success_at, 1, 10)
       END AS last_success_date
  FROM source_freshness_ledger f
  LEFT JOIN source_catalog c ON c.source_id = f.source_id
 ORDER BY f.health_status DESC, c.source_family, f.source_id;
