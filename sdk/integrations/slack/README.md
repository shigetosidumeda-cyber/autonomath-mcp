# jpcite — Slack bot (`/jpcite`)

> Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) · brand: jpcite ·
> API base: `https://api.jpcite.com` · cost: **¥3/req** metered (税込 ¥3.30)

A minimal Slack bot exposing one slash command `/jpcite <query>` that
returns a Slack message backed by the jpcite REST API:

| Input                                  | Endpoint                                         | Slack response          |
| -------------------------------------- | ------------------------------------------------ | ----------------------- |
| `/jpcite 8010001213708`                | `GET /v1/houjin/{bangou}`                        | 法人 360 (6 fields)     |
| `/jpcite 補助金 東京都 設備投資`        | `GET /v1/programs/search?q=...&limit=5`          | 上位 5 制度 (link list) |
| `/jpcite` (empty)                      | —                                                | help (ephemeral)        |

The bot is **stateless**: no DB, no cache, no LLM. Each successful
slash command is a single jpcite API call billed at ¥3/req (税込 ¥3.30).

## 7-step install (customer-side)

> **Prerequisite (operator side)**: `slack_bot.py` is meant to run inside
> *your own* infra (Fly.io, Cloud Run, k8s, etc.) under a Slack App that
> *you own*. Bookyou never proxies Slack traffic and never holds your
> Slack signing secret or jpcite API key.

1. **Create a Slack App from the manifest.**
   https://api.slack.com/apps → **Create New App** → **From an app manifest**
   → pick your workspace → paste the contents of `manifest.yaml` → review
   → **Create**.

2. **Set the slash command request URL.**
   Slack defaults the manifest's `https://slack.jpcite.com/slack/commands`
   placeholder to your bot. Edit **Slash Commands** → `/jpcite` →
   replace the URL with the public address where you'll host
   `slack_bot.py` (e.g. `https://slack.example-corp.dev/slack/commands`).

3. **Install the app to a workspace.**
   **OAuth & Permissions** → **Install to Workspace** → approve. Note
   the **Bot User OAuth Token** (`xoxb-...`) — you do **not** need it
   for slash commands themselves, but you'll need it later if you add
   `chat.postMessage` follow-ups.

4. **Copy the signing secret.**
   **Basic Information** → **App Credentials** → **Signing Secret** →
   reveal & copy. Set it as env var:

   ```bash
   export SLACK_SIGNING_SECRET="<your_signing_secret>"
   ```

5. **Issue a jpcite API key.**
   https://jpcite.com/dashboard → **API Keys** → **Issue new** → copy.

   ```bash
   export JPCITE_API_KEY="jpcite_sk_..."
   # optional override (defaults to https://api.jpcite.com)
   export JPCITE_API_BASE="https://api.jpcite.com"
   ```

6. **Run the bot.**

   ```bash
   pip install flask httpx
   python slack_bot.py
   # listens on :8080 by default; gunicorn / uvicorn-wsgi compatible
   ```

   For Fly.io / Cloud Run, build a small Dockerfile that runs
   `gunicorn 'slack_bot:build_flask_app()' --bind 0.0.0.0:8080`.

7. **Verify.**

   ```
   /jpcite 8010001213708
   /jpcite 補助金 東京都 設備投資
   /jpcite
   ```

   The first two should post an `in_channel` Block Kit message; the
   empty form should reply with an ephemeral help card.

## What the bot does *not* do

- **No LLM call.** The bot returns deterministic REST output. Pipe
  results into your own Claude / ChatGPT downstream if you want
  reasoning or summarization.
- **No write-back.** It does not call `chat.postMessage`,
  `chat.scheduleMessage`, or any other state-changing Slack API.
  Slash-command responses are handled inline in the HTTP response.
- **No DB.** No usage logging, no per-user history. Slack already
  retains your slash-command audit log.
- **No retries.** If `api.jpcite.com` returns 5xx, the user sees an
  ephemeral error and is responsible for retrying.

## Cost model

Each successful slash command = 1 request = ¥3 (税込 ¥3.30). Stripe
metered billing is computed by the jpcite API gateway, not by this
bot. Failed calls (4xx/5xx surfaced to Slack) are not billed
because they never produce a successful jpcite response.

## Supported endpoints today

| jpcite endpoint                | Trigger                         |
| ------------------------------ | ------------------------------- |
| `GET /v1/houjin/{bangou}`      | 13-digit numeric input          |
| `GET /v1/programs/search`      | Anything else (free text)       |

Future commands (`/jpcite-laws`, `/jpcite-enforcement`,
`/jpcite-saiketsu`) are planned but not yet wired — file a request
at info@bookyou.net.

## License

MIT. See `LICENSE` in the repo root.

## 不具合報告

info@bookyou.net (Bookyou株式会社, 適格請求書発行事業者番号 T8010001213708)
