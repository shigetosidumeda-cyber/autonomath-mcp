-- target_db: jpintel
-- migration 085_usage_events_client_tag (X-Client-Tag header attribution)
--
-- Why this exists:
--   税理士事務所 (tax accountant offices) using AutonoMath as a back-end
--   need to attribute API consumption to individual 顧問先 (client firms)
--   for invoice line-item passthrough. Without per-call attribution the
--   accountant must allocate ¥3/req across an opaque pool — that is a
--   bookkeeping stopper for the segment.
--
--   `client_tag` is an OPTIONAL caller-supplied tag, server-validated
--   alphanumeric+hyphen+underscore, max 32 chars. The middleware reads
--   `X-Client-Tag` from the request, validates the shape, and forwards it
--   into `log_usage` as the new column. Aggregations are surfaced via
--   GET /v1/me/usage?group_by=client_tag.
--
--   This is a data-attribution column only. It does NOT alter pricing,
--   cap enforcement, or the parent/child relationship (migration 086).
--   ¥3/req remains the unit price; client_tag is purely metadata for
--   the accountant's internal cost allocation.
--
-- Schema:
--   client_tag TEXT
--     Caller-supplied tag, max 32 chars, alphanumeric+hyphen+underscore.
--     NULL when the caller did not pass `X-Client-Tag` (the 90% case).
--     Indexed on (api_key_id == key_hash, client_tag, ts) so the per-tag
--     monthly aggregate query for /v1/me/usage?group_by=client_tag is a
--     covering index lookup.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is a no-op on the second run. CREATE INDEX
--   uses IF NOT EXISTS. Re-applying this migration on every Fly boot is
--   safe (entrypoint.sh §4 may re-run it).
--
-- DOWN:
--   SQLite < 3.35 cannot DROP COLUMN. Leaving the column in place on
--   rollback is harmless because it is nullable and unindexed except
--   for the partial composite index below.

PRAGMA foreign_keys = ON;

ALTER TABLE usage_events ADD COLUMN client_tag TEXT;

-- Composite index for the per-tag monthly aggregate: /v1/me/usage?group_by=client_tag
-- and /v1/me/usage.csv?group_by=client_tag both run
--   SELECT client_tag, COUNT(*) FROM usage_events
--    WHERE key_hash = ? AND ts >= ? AND client_tag IS NOT NULL
--    GROUP BY client_tag
-- which is a covering scan against this index. Partial WHERE keeps the
-- on-disk footprint trivial — the 90%+ rows that have client_tag IS NULL
-- never materialize an entry here.
CREATE INDEX IF NOT EXISTS idx_usage_events_client_tag
    ON usage_events(key_hash, client_tag, ts)
    WHERE client_tag IS NOT NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
