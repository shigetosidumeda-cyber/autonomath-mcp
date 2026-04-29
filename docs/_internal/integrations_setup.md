# Workflow integrations 5-pack — operator setup

Internal runbook for the 5-pack mounted at `/v1/integrations/*` (see
`src/jpintel_mcp/api/integrations.py`). Customers self-configure via API;
the operator-side setup below is one-time-per-environment.

## Required env vars (Fly secrets)

```bash
fly secrets set \
  INTEGRATION_TOKEN_SECRET="<fernet-key>" \
  GOOGLE_OAUTH_CLIENT_ID="<from google cloud console>" \
  GOOGLE_OAUTH_CLIENT_SECRET="<from google cloud console>"
```

`INTEGRATION_TOKEN_SECRET` MUST be a 32-byte URL-safe base64 string
(`Fernet.generate_key().decode()`). Rotation requires re-encrypting all
rows in `integration_accounts` — the route handlers fail closed (HTTP
503) when the env var is unset or the key cannot decrypt an existing
row.

## 1) Slack — done, no operator setup required

Customer side only:
1. Create an incoming webhook at `https://api.slack.com/apps`.
2. POST `/v1/me/recurring/slack` with
   `{"saved_search_id": <id>, "channel_url": "https://hooks.slack.com/services/..."}`.
3. SSRF defense: server rejects any URL that does not start with
   `https://hooks.slack.com/services/` (HTTP 422).

## 2) Google Sheets OAuth — manual operator setup REQUIRED

`manual_setup_required: true`

1. Create a Google Cloud project.
2. Enable APIs: **Google Sheets API**, **Google+ API** (for userinfo).
3. Configure OAuth consent screen:
   - User type: **External**
   - Scopes: `auth/spreadsheets`, `auth/userinfo.email`
   - Authorized domains: `zeimu-kaikei.ai`
4. Create OAuth 2.0 Client ID (type: **Web application**):
   - Authorized redirect URI:
     `https://api.zeimu-kaikei.ai/v1/integrations/google/callback`
5. Copy Client ID + Client Secret into Fly secrets above.

Customer-side flow:
1. `POST /v1/integrations/google/start` (X-API-Key required) →
   returns `{authorize_url, state}`.
2. Customer opens `authorize_url` in a browser, grants consent.
3. Google redirects to `/v1/integrations/google/callback?code=...&state=...`.
4. Server exchanges code → stores Fernet-encrypted refresh+access token
   in `integration_accounts (provider='google_sheets')`.
5. Customer calls `POST /v1/me/saved_searches/{id}/sheet` with
   `{"sheet_id": "1AbC..."}` to bind a target spreadsheet.

## 3) Postmark inbound — manual operator setup REQUIRED

`manual_setup_required: true`

1. In Postmark dashboard, create an inbound stream.
2. Bind it to the parse address `parse.zeimu-kaikei.ai` (or whatever
   subdomain is configured).
3. Set the webhook URL to:
   `https://api.zeimu-kaikei.ai/v1/integrations/email/inbound`
4. (Optional) Set inbound spam filter to **strict**.

Customer-side flow:
1. Customer emails `query+am_xxx@parse.zeimu-kaikei.ai` with subject
   `find DX 補助金` (subject = query string).
2. Postmark parses → POSTs JSON to our webhook.
3. Server decodes plus-addressing → resolves api_key_hash → runs search →
   replies via Postmark outbound.
4. Idempotency: Postmark Message-Id is the dedup key in
   `integration_sync_log (provider='postmark_inbound')`.

## 4) Excel — done, no operator setup required

Two surfaces share the brand:
- **WEBSERVICE template** (cell formula): `GET /v1/integrations/excel?key=am_...&q=...`
  returns `text/plain` for a single cell.
- **Saved-search XLSX download**: `GET /v1/me/saved_searches/{id}/results.xlsx`
  re-uses `api/formats/xlsx.py` for the full workbook.

## 5) kintone — pure REST (no OAuth)

Customer side only:
1. In kintone, create an app.
2. Generate an API token for the app with **Add records** permission.
3. POST `/v1/integrations/kintone/connect` with:
   ```json
   {"domain": "acme.cybozu.com", "app_id": 42, "api_token": "..."}
   ```
4. POST `/v1/integrations/kintone/sync` with `{"saved_search_id": <id>}`
   to push rows. Idempotency on `(saved_search_id + UTC date)` so a cron
   re-run is safe.

Daily cron `scripts/cron/sync_kintone.py` walks every saved_search whose
key has an active kintone account and pushes today's results.

## Pricing recap

| Endpoint                                  | Cost |
|------------------------------------------|-----|
| Slack slash command POST                  | ¥3  |
| Slack webhook drop-in                     | ¥3  |
| Sheets cell formula callback              | ¥3  |
| Excel WEBSERVICE                          | ¥3  |
| kintone plugin button                     | ¥3  |
| kintone /sync (regardless of row count)   | ¥3  |
| Email inbound parse + reply               | ¥3  |
| `/google/start`, `/connect`, `/sheet` bind | FREE |
| Saved-search XLSX download                | ¥3  |

Each successful delivery == one row in `usage_events` == one Stripe
metered usage_record. Bulk syncs do NOT multiply.

## Token storage threat model

- `integration_accounts.encrypted_blob` is Fernet ciphertext. Plaintext
  refresh-token / API-token is never persisted.
- Decryption is via `_integration_tokens._fernet()` at request time.
- Rotation: regenerate `INTEGRATION_TOKEN_SECRET`, then re-encrypt every
  row (out-of-band script, not yet automated).
- Revocation: `DELETE /v1/integrations/google` flips `revoked_at` on the
  row. The cron skips revoked rows. Hard delete happens via a
  separate operator-only path.

## Test coverage

`tests/test_integrations.py` covers:
- Slack slash command happy-path + empty-query help text
- Slack `/v1/me/recurring/slack` SSRF prefix rejection
- Google OAuth start (configured + 503 unconfigured)
- Google callback persists Fernet-encrypted token (NOT plaintext)
- Saved-search → Sheet bind round-trip
- Email connect flag persists
- Email inbound silently 200s on unknown api-key
- Saved-search XLSX returns workbook bytes
- kintone domain validation rejects non-cybozu/kintone domains
- kintone `/sync` happy path + idempotency dedup
- Token blob Fernet round-trip (encrypt → ciphertext != plaintext → decrypt)

Run: `.venv/bin/pytest tests/test_integrations.py`
