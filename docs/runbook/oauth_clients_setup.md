---
title: Google + GitHub OAuth client setup runbook
updated: 2026-05-07
operator_only: true
category: deploy
---

# Google + GitHub OAuth client setup runbook

Operator-facing one-shot procedure for registering OAuth client IDs
on Google Cloud Console and GitHub. AI agents cannot run developer
console UIs — both registrations require operator-bound login + 2FA.

> Implementation note (Google): jpcite already implements the Google
> Sheets OAuth flow at `src/jpintel_mcp/api/integrations.py`
> (`/v1/integrations/google/start` + `/google/callback`). The flow
> stores Fernet-encrypted refresh tokens in `integration_accounts` and
> fails closed (HTTP 503) when `GOOGLE_OAUTH_CLIENT_ID` is unset. This
> runbook walks the operator through provisioning the missing client.
>
> Implementation note (GitHub): there is **no** GitHub OAuth login flow
> in production source yet (`grep -rE 'github.*(oauth|client_id)'
> src/` returns 0 hits as of 2026-05-07). The GitHub OAuth client is
> being registered **proactively** to support a future "Sign in with
> GitHub" surface for the developer-portal. Until that surface ships,
> the credentials sit in 1Password unused — that is OK.

Cross-references:
- `docs/_internal/integrations_setup.md` §2 — the Google Sheets
  customer-side flow (start + callback) plus the operator setup
  fields. This runbook supersedes that doc's step list with
  field-by-field detail.
- `docs/runbook/secret_rotation.md` — `GOOGLE_OAUTH_CLIENT_*` env-var
  rotation if compromise suspected.

## Section 1 — Google Cloud Console: OAuth 2.0 client ID

### Prerequisites

- Operator must be Google account owner of `info@bookyou.net` (or any
  account with Project Owner / Editor role on the jpcite GCP project).
- 2FA enabled (Stripe-style operator-only attestation; no AI delegation).
- A GCP project named `jpcite-prod` already exists, **or** the operator
  is willing to create one. Create at <https://console.cloud.google.com/projectcreate>
  if not — name the project `jpcite-prod`, organization = none (no GSuite
  org bound to Bookyou yet).

### Step 1.1: Enable required APIs

1. Open <https://console.cloud.google.com/> with the jpcite-prod project
   selected (top-left dropdown).
2. APIs & Services → Library → enable:
   - **Google Sheets API** (`sheets.googleapis.com`) — required for the
     existing `/v1/integrations/google/callback` flow that writes
     saved-search results into customer spreadsheets.
   - **Google+ API** (`plus.googleapis.com`) — used for `userinfo.email`
     resolution. Note: Google+ is deprecated in name but the userinfo
     endpoint still serves; if the API panel does not surface it,
     enable **People API** (`people.googleapis.com`) instead — both
     paths satisfy `auth/userinfo.email`.
   - **Google Drive API** (`drive.googleapis.com`) — required when the
     spreadsheet selection UI is enabled (future `Drive.readonly` scope).

### Step 1.2: Configure OAuth consent screen

1. APIs & Services → OAuth consent screen.
2. User type: **External** (we serve customers outside Bookyou's GSuite).
3. App information:
   - App name: `jpcite`
   - User support email: `info@bookyou.net`
   - App logo: upload `site/_static/logo-512.png` (Google enforces
     1MB / 512×512 / square / PNG-or-JPG).
4. App domain:
   - Application home page: `https://jpcite.com`
   - Application privacy policy link: `https://jpcite.com/legal/privacy`
   - Application terms of service link: `https://jpcite.com/legal/terms`
5. Authorized domains: add `jpcite.com` (Google enforces apex registry,
   subdomains inherit).
6. Developer contact information: `info@bookyou.net`.
7. Scopes (click "Add or Remove Scopes"):
   - `openid`
   - `profile`
   - `email`
   - `https://www.googleapis.com/auth/spreadsheets` — sensitive,
     justification field required ("Write saved-search results into
     customer-owned spreadsheets at customer's explicit selection").
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/drive.readonly` — sensitive,
     justification field required ("List customer's spreadsheets so the
     customer can pick which one to bind"). **Optional** — only enable
     if the spreadsheet picker UI is shipping in this release; otherwise
     omit and the existing customer-types-the-sheet-id flow keeps
     working.
8. Test users: add `info@bookyou.net` + `shigetosidumeda@gmail.com` so
   the flow works in "Testing" status before Google verifies the app.
9. Submit for verification **only when** the spreadsheet picker UI is
   ready — Google verification is needed for the sensitive scopes when
   the app graduates from "Testing" to "In production". Until then,
   keep status = Testing (≤ 100 users limit, fine for early launch).

### Step 1.3: Create OAuth 2.0 client ID

1. APIs & Services → Credentials → "+ Create credentials" → OAuth
   client ID.
2. Application type: **Web application**.
3. Name: `jpcite-prod`.
4. Authorized JavaScript origins (one per line):
   - `https://jpcite.com`
   - `https://api.jpcite.com`
5. Authorized redirect URIs (one per line — must match
   `_google_oauth_redirect_uri()` in
   `src/jpintel_mcp/api/integrations.py:828`):
   - `https://api.jpcite.com/v1/integrations/google/callback`
6. Click Create. Google shows Client ID + Client Secret modal — copy
   both immediately. Client Secret is shown once; if missed, re-issue
   from the credentials list (rotates the secret).

### Step 1.4: Mint into Fly secrets

```bash
fly secrets set \
  GOOGLE_OAUTH_CLIENT_ID="<Client ID>.apps.googleusercontent.com" \
  GOOGLE_OAUTH_CLIENT_SECRET="<Client Secret>" \
  -a autonomath-api
```

Verify post-restart:

```bash
curl -s -X POST https://api.jpcite.com/v1/integrations/google/start \
  -H "X-API-Key: am_test_..." | jq .
# Expect: {"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?...", "state": "..."}
# Failure mode: HTTP 503 "Google Sheets integration not configured" → secrets not loaded yet.
```

## Section 2 — GitHub OAuth App

### Prerequisites

- Operator must have admin access to the Bookyou GitHub org (or the
  personal account hosting the jpcite repos pre-org-migration).
- 2FA enabled with hardware key or TOTP — GitHub disables OAuth app
  creation on accounts without 2FA.

### Step 2.1: Create OAuth App

1. <https://github.com/settings/developers> → OAuth Apps → New OAuth App.
   (If the repos are owned by a Bookyou org, do this at
   <https://github.com/organizations/bookyou/settings/applications>
   instead so the app is org-scoped — preferred long-term.)
2. Application name: `jpcite`
3. Homepage URL: `https://jpcite.com`
4. Application description: `jpcite developer portal — Sign in with GitHub`
5. Authorization callback URL: `https://api.jpcite.com/v1/auth/github/callback`
   - **Note**: this path is **not yet implemented** in source as of
     2026-05-07. When the developer-portal "Sign in with GitHub"
     surface ships, the handler must mount at exactly this URL — the
     OAuth app registration locks the path. Pick the path now; AI
     agents implement the route handler later. Path naming follows
     the existing Google convention
     (`/v1/integrations/google/callback`); for login (not integration)
     we use `/v1/auth/github/callback`.
6. Enable Device Flow: **unchecked** (web flow only).
7. Click Register application.
8. GitHub shows Client ID immediately. Click "Generate a new client
   secret" → secret shown once. Copy both.

### Step 2.2: Scopes (requested at authorize time, not registered)

GitHub OAuth Apps do not pre-register scopes — they are requested in
the authorize URL. When the future "Sign in with GitHub" handler is
implemented, request **only**:

- `read:user` — public profile + verified email (no write access).
- `user:email` — primary verified email (private if user marked it so).

Do **not** request `repo`, `admin:org`, `workflow`, or any write scope.
The auth use case is identity confirmation only; broader scopes
trigger user-side hesitation (and expand our breach blast radius).

### Step 2.3: Mint into 1Password (do not deploy yet)

The handler does not exist, so deploying the secret to Fly now would
just sit unused. Park the credentials in 1Password under
"jpcite / GitHub OAuth (prod)" with these fields:

- `GITHUB_OAUTH_CLIENT_ID`: `Iv1.________________`
- `GITHUB_OAUTH_CLIENT_SECRET`: `ghos_________________________`
- Issued: `<date>`
- Callback URL (locked): `https://api.jpcite.com/v1/auth/github/callback`

When the developer-portal lands, retrieve these and:

```bash
fly secrets set \
  GITHUB_OAUTH_CLIENT_ID="Iv1...." \
  GITHUB_OAUTH_CLIENT_SECRET="ghos_..." \
  -a autonomath-api
```

Then implement `/v1/auth/github/callback` mirroring the Google flow's
state nonce + Fernet-encrypted refresh-token storage pattern.

## Common gotchas

- **Google verification timing.** Submitting for verification before
  the spreadsheet picker UI is live is wasted process — Google may
  request demo videos, scope justifications, etc. that change once the
  UI ships. Keep status = Testing until UI is ready.
- **Redirect URI exact-match.** Google enforces full string equality
  including trailing slash. The callback must be
  `https://api.jpcite.com/v1/integrations/google/callback` (no
  trailing slash; matches `integrations.py:828`).
- **GitHub OAuth Apps vs GitHub Apps.** This runbook is for **OAuth
  App** (user identity). GitHub Apps are for repo-bot integrations
  (e.g. CI). They are different UI flows; do not confuse.
- **Client Secret display is one-shot.** If lost, regenerate from the
  credentials page (Google) or "Generate a new client secret" (GitHub).
  Old secret stays valid for ~24h to allow rolling deploy.
- **Org-owned vs personal-owned (GitHub).** Personal-owned OAuth Apps
  cannot be transferred to an org later — the app must be re-created
  under the org. If a Bookyou GitHub org exists, register there from
  the start.
- **`info@bookyou.net` as developer contact.** Google sends scope-
  review escalations to this address; missing replies stall
  verification by weeks. Confirm the inbox is monitored before
  submitting.

## Verification checklist (post-setup)

- [ ] `fly secrets list -a autonomath-api` shows `GOOGLE_OAUTH_CLIENT_ID`
      + `GOOGLE_OAUTH_CLIENT_SECRET` updated within last 30 min
- [ ] `curl -X POST https://api.jpcite.com/v1/integrations/google/start
      -H "X-API-Key: am_..."` returns 200 + valid `authorize_url`
- [ ] Walking the `authorize_url` in a clean browser → consent →
      callback resolves to `/v1/integrations/google/callback?code=...`
      and the API stores a row in `integration_accounts`
      (`provider='google_sheets'`)
- [ ] GitHub OAuth App credentials parked in 1Password, callback URL
      locked, `Sign in with GitHub` route reserved for future
      developer-portal milestone
