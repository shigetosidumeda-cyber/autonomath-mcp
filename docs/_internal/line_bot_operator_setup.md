# LINE bot operator setup runbook

The LINE bot is the second product surface alongside the ¥3/req REST+MCP API
(CLAUDE.md cohort #6 「中小企業 LINE」). The Python webhook handler in
`src/jpintel_mcp/api/line_webhook.py` and the deterministic state machine in
`src/jpintel_mcp/line/flow.py` ship as code. The four operator-side actions
below cannot ship as code and must be performed manually in the LINE
Developers Console / official-account-manager.

## 1. Create the Messaging API channel

1. Sign in to <https://developers.line.biz/> with the Bookyou株式会社
   provider account.
2. Create a new channel of type **Messaging API**.
3. Channel name: 「AutonoMath 制度検索」.
4. Channel description: 「中小企業向け 公的支援制度検索 (Bookyou株式会社 / T8010001213708)」
5. Confirm the operator company name (Bookyou株式会社) and contact
   (info@bookyou.net) on the channel basic info screen.

## 2. Configure webhook delivery

In the channel "Messaging API" tab:

1. **Webhook URL:** `https://api.zeimu-kaikei.ai/v1/integrations/line/webhook`
2. **Use webhook:** ON
3. **Verify** — the Console tries a `POST` to the URL. Expected response:
   `200 OK` with `{"status":"ok","processed":"0","skipped":"0"}` because
   the verification body has zero events.
4. **Auto-reply messages:** OFF (we own all replies).
5. **Greeting messages:** OFF (the welcome string is rendered by our
   webhook on the `follow` event).

## 3. Capture the secrets

In the channel "Messaging API" tab:

1. **Channel secret** → set Fly secret:
   `fly secrets set LINE_CHANNEL_SECRET=<value>`
2. **Channel access token (long-lived)** → click "Issue", then:
   `fly secrets set LINE_CHANNEL_ACCESS_TOKEN=<value>`

These are read by `src/jpintel_mcp/line/config.py` at import time. After
setting, restart the API:
`fly apps restart autonomath-api`

When either secret is empty, the webhook returns **503** so dev mode
never silently auto-accepts unsigned bodies.

## 4. Configure the rich menu

LINE's official-account-manager (`https://manager.line.biz/`) hosts the
rich menu config. Code cannot upload a rich menu without an operator-
provisioned access token, so this is manual.

Recommended layout — 4 areas, full-width:

| Area | Label | Action |
|------|-------|--------|
| Top-left  | 制度を探す  | message: "建設業" (kicks off the flow on step 1) |
| Top-right | 使い方     | message: "ヘルプ" |
| Bottom-left | サイト    | URI: `https://zeimu-kaikei.ai/` |
| Bottom-right | お問合せ | URI: `mailto:info@bookyou.net` |

Image template: 2500x1686 px; PNG; brand color #1f6feb. The image asset
lives at `site/assets/line_richmenu.png` (regenerate via
`scripts/generate_line_richmenu.py` when copy changes).

Upload via official-account-manager → Rich menus → Create new.

## 5. Verify end-to-end

1. Add the OA as a friend from a test phone (the QR / `https://lin.ee/...`
   URL appears on the channel info screen after step 1).
2. The `follow` event triggers the welcome message (no quota debit).
3. Tap 制度を探す on the rich menu → the bot replies with the 業種
   quickreply. Each subsequent button tap walks the user through the 4
   steps (業種 → 都道府県 → 従業員数 → 年商) and ends with up to 5
   matching programs.
4. Open the DB to confirm the round trip:
   ```
   sqlite3 data/jpintel.db \
     "SELECT line_user_id, plan, query_count_mtd FROM line_users LIMIT 5;"
   sqlite3 data/jpintel.db \
     "SELECT direction, billed, quota_exceeded, flow_step \
      FROM line_message_log ORDER BY received_at DESC LIMIT 10;"
   ```

## 6. Constraints (locked policy)

- **NO LLM call** anywhere in the LINE webhook code path. Replies are
  fully determined by the user's quick-reply choice and a single
  parameterised SELECT against `programs`.
- **NO Stripe Connect / reseller / commission split.** The 100% organic
  acquisition policy in CLAUDE.md prohibits paid acquisition channels;
  any code or admin action that introduces a 税理士 reseller share is a
  policy violation. The constraint is enforced at test time by
  `tests/test_line_bot.py::test_no_connect_or_reseller_in_line_bot_code`.
- **¥3 per round trip** when billed against a parent api_key (rare in
  v1 — column reserved for migration 086 fan-out). Otherwise the event
  counts against the LINE user's monthly free quota of 50 events
  (resets at JST 月初 00:00).
- **Solo + zero-touch.** No admin UI, no operator approval flow, no
  per-customer DPA, no Slack support. Self-service only.

## 7. Daily operation

The webhook is stateless and self-healing — there is no required daily
operator action.

Optional health probe (e.g. UptimeRobot):

```
GET https://api.zeimu-kaikei.ai/healthz
```

The webhook is intentionally NOT mounted on the public health surface;
its 503-on-missing-secret is the only externally visible health
indicator. A quick smoke test:

```
curl -i -X POST https://api.zeimu-kaikei.ai/v1/integrations/line/webhook \
  -H "Content-Type: application/json" \
  -d '{"destination":"verify","events":[]}'
```

Expected response: **401 invalid signature** (proves the secret is
configured and the route is live).
