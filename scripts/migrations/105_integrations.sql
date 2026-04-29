-- target_db: jpintel
-- 105_integrations.sql
-- Workflow integrations 5-pack — Google Sheets OAuth + kintone REST + Postmark
-- inbound delivery audit. Slack and Excel pieces are already covered:
--   * Slack: saved_searches.channel_format='slack' + channel_url (migration 099)
--           plus /v1/me/recurring/slack bind+verify (api/recurring_quarterly.py).
--   * Excel: GET /v1/me/saved_searches/{id}/results.xlsx renders via the
--           existing _format_dispatch.xlsx.render() (api/formats/xlsx.py).
--
-- This migration adds the substrate for the two integrations that need
-- per-customer credential storage (Google Sheets OAuth refresh-token,
-- kintone API token) plus an idempotency log for the email-inbound and
-- bulk-sync flows so a Postmark retry / a kintone-cron rerun cannot
-- double-bill a single delivery.
--
-- Idempotent — every CREATE * uses IF NOT EXISTS. Safe to re-apply on
-- every Fly entrypoint.sh boot loop.
--
-- ---------------------------------------------------------------------------
-- integration_accounts — per-key, per-provider encrypted credential row
-- ---------------------------------------------------------------------------
--
-- One row per (api_key_hash, provider) pair. Fernet-encrypted blob holds
-- the provider-specific secret material (Google OAuth refresh+access token
-- pair, or kintone API token + app-id + domain). The encryption key is
-- the env-var INTEGRATION_TOKEN_SECRET (Fernet 32-byte url-safe key) — rotation
-- is operator-side via re-encrypting and overwriting the column. We do NOT
-- store plaintext at any rest layer — the route handler decrypts on read,
-- uses the credential, and discards.
--
-- Why per-api-key (not per-customer): a customer can issue child API keys
-- (migration 086) for fan-out to 顧問先, and each child binds its own
-- integration credentials. Aggregation back to the parent key happens in
-- the billing layer, not here.
CREATE TABLE IF NOT EXISTS integration_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash    TEXT NOT NULL,
    provider        TEXT NOT NULL CHECK (provider IN ('google_sheets','kintone','postmark_inbound')),
    -- Fernet-encrypted JSON blob with provider-specific fields:
    --   google_sheets: {"refresh_token":"...","access_token":"...","expires_at":"ISO8601","scope":"..."}
    --   kintone:       {"domain":"acme.cybozu.com","app_id":42,"api_token":"..."}
    --   postmark_inbound: {"reply_from":"query@parse.zeimu-kaikei.ai"} (no
    --                     secret — row is a presence-flag for routing)
    encrypted_blob  BLOB NOT NULL,
    -- Plaintext provider-side identity for at-a-glance triage (NOT a
    -- secret — this is the customer's own Google email / kintone domain,
    -- never the token). Helps the dashboard render "Connected as alice@..."
    -- without round-tripping through Fernet.
    display_handle  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    revoked_at      TEXT,
    UNIQUE (api_key_hash, provider)
);

CREATE INDEX IF NOT EXISTS idx_integration_accounts_provider
    ON integration_accounts (provider, revoked_at);

-- ---------------------------------------------------------------------------
-- integration_sync_log — idempotency + audit for delivery + sync events
-- ---------------------------------------------------------------------------
--
-- One row per delivery / sync event. The (provider, idempotency_key)
-- UNIQUE index is the dedup gate: Postmark Message-Id, kintone-sync
-- (saved_search_id + run_date), Google-sheets-append (saved_search_id +
-- run_date). A repeat call with the same key returns the cached
-- result_count + status without billing again.
--
-- Pricing rule (project_autonomath_business_model — ¥3/req metered ONLY):
-- one row in integration_sync_log == one ¥3 charge against the calling
-- api_key_hash. A bulk sync of 100 kintone records is ONE row, ONE ¥3 —
-- not 100 × ¥3. The result_count column carries the row delta for audit.
CREATE TABLE IF NOT EXISTS integration_sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash    TEXT NOT NULL,
    provider        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    saved_search_id INTEGER,
    -- short status: 'ok' | 'noop' | 'error' | 'unauthorized' | 'rate_limited'
    status          TEXT NOT NULL,
    -- rows delivered / appended / replied — NOT a billing multiplier
    result_count    INTEGER NOT NULL DEFAULT 0,
    error_class     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (provider, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_integration_sync_log_key_recent
    ON integration_sync_log (api_key_hash, created_at DESC);

-- ---------------------------------------------------------------------------
-- saved_searches.sheet_id — Google Sheets target binding
-- ---------------------------------------------------------------------------
--
-- One Google Sheets spreadsheet ID per saved search (the customer's own
-- sheet, not ours). When non-NULL, the daily cron append-rows to this
-- sheet via the customer's stored google_sheets refresh token.
-- ALTER TABLE ADD COLUMN is not idempotent under SQLite, but the migration
-- runner sniffs PRAGMA table_info first and skips on column-present, so
-- this is safe to re-apply.
ALTER TABLE saved_searches ADD COLUMN sheet_id TEXT;
ALTER TABLE saved_searches ADD COLUMN sheet_tab_name TEXT;
