-- target_db: jpintel
-- migration 089_audit_seal_table (税理士事務所 bundle — tamper-evident audit seal)
--
-- Why this exists:
--   税理士事務所 (tax accountant offices) using AutonoMath as a back-end
--   for client advisory work need a tamper-evident receipt for every
--   metered call so the resulting work product (顧問先 monthly brief,
--   税制特例 candidate list, etc.) carries a verifiable provenance chain
--   that survives 国税庁 査察 / 税理士法人 internal audit / 弁護士法 §72
--   boundary review.
--
--   Without a per-call seal, an accountant cannot prove WHICH specific
--   AutonoMath query produced WHICH specific recommendation 7 years
--   later when 帳簿保存義務 / 税理士法 §41 (帳簿等保存義務) audits arrive.
--   The seal converts each ¥3 metered call into an evidentiary artifact
--   the accountant can re-verify against AutonoMath at audit time via
--   GET /v1/me/audit_seal/{call_id}.
--
--   This is a SEPARATE column family from usage_events on purpose:
--     * usage_events is ephemeral — pruned at the operator's discretion
--       (no statutory retention window).
--     * audit_seals is statutory evidence — retained 7 years per
--       税理士法 §41 / 法人税法 §150-2 / 所得税法 §148 帳簿保存義務.
--       The retention_until column is set to ts + 7 years on insert.
--
-- Schema:
--   call_id          ULID-flavored 26-char string. Primary key, deterministic
--                    so a customer who lost the seal can re-derive it from
--                    (api_key_hash, ts, query_hash).
--   api_key_hash     FK to api_keys.key_hash. NOT NULL — anonymous calls
--                    never produce a seal (anonymous tier is non-metered,
--                    no audit value).
--   ts               ISO 8601 UTC of the response flush.
--   endpoint         Short endpoint name (matches usage_events.endpoint
--                    convention — 'programs.search', 'monthly_client_pack_am',
--                    etc.) so seals can be GROUP BY'd by tool.
--   query_hash       SHA-256 hex of the canonical-JSON-serialized request
--                    payload (params dict). Lossy by design — we never
--                    store the raw query (PII / 守秘義務).
--   response_hash    SHA-256 hex of the JSON-serialized response body
--                    AFTER PII redaction. Lossy — proves the customer
--                    received THIS response without storing it again.
--   source_urls_json JSON array of primary-source URLs cited in the
--                    response. Stored verbatim because URLs are public
--                    and the accountant needs to re-fetch them at audit
--                    time.
--   client_tag       Echoed from X-Client-Tag header (migration 085).
--                    NULL when caller did not pass one. Indexed so an
--                    accountant can pull all seals for a single 顧問先
--                    in one SELECT.
--   hmac             Hex SHA-256 HMAC over
--                      call_id || ts || query_hash || response_hash
--                    keyed on settings.audit_seal_secret. The secret is
--                    held by Bookyou株式会社 ONLY — the customer cannot
--                    forge a seal even with full DB access.
--   retention_until  ISO 8601 UTC date 7 years from ts. Cron sweep
--                    (TODO: scripts/cron/audit_seal_purge.py) deletes
--                    rows past this date. NEVER manually delete a row
--                    before retention_until — that breaks the customer's
--                    statutory chain.
--
-- Idempotency:
--   CREATE TABLE / INDEX are IF NOT EXISTS. Re-applying on every Fly boot
--   (entrypoint.sh §4) is safe.
--
-- DOWN:
--   No DROP. Audit seals are statutory evidence — once issued, they MUST
--   survive a rollback. If the column family is wrong, ALTER and add new
--   columns; never drop existing rows.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS audit_seals (
    call_id           TEXT PRIMARY KEY,
    api_key_hash      TEXT NOT NULL,
    ts                TEXT NOT NULL,
    endpoint          TEXT NOT NULL,
    query_hash        TEXT NOT NULL,
    response_hash     TEXT NOT NULL,
    source_urls_json  TEXT NOT NULL DEFAULT '[]',
    client_tag        TEXT,
    hmac              TEXT NOT NULL,
    retention_until   TEXT NOT NULL
);

-- Per-key audit log lookup (the dominant read pattern: an accountant
-- pulling all seals for one client_tag over a date range).
CREATE INDEX IF NOT EXISTS idx_audit_seals_key_ts
    ON audit_seals(api_key_hash, ts);

-- Per-client_tag lookup for accountants attributing seals to 顧問先.
-- Partial index — 90%+ of seals will have NULL client_tag at MVP scale.
CREATE INDEX IF NOT EXISTS idx_audit_seals_client_tag
    ON audit_seals(api_key_hash, client_tag, ts)
    WHERE client_tag IS NOT NULL;

-- Retention sweep index — the daily cron sorts rows by retention_until
-- to find expired ones in O(log n).
CREATE INDEX IF NOT EXISTS idx_audit_seals_retention
    ON audit_seals(retention_until);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
