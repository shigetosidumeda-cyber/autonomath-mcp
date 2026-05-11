# Glama Discord escalation (Wave 23)

**Why**: 24-72h auto-crawl window expired on the v0.3.4 listing.
- v0.3.4 Anthropic Official Registry publish: 2026-05-06 10:52 UTC
- elapsed at Wave 23 start: ~5 days (>120h, well past the 72h ETA)
- `glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp`
  still returns HTTP 404 (Wave 22 + Wave 23 probes)

**Path**: Glama Discord at <https://discord.gg/C3eCXhYWtJ> (302 redirect
target of <https://glama.ai/discord>, captured Wave 23 2026-05-11).

We do **not** have a Glama-side incoming webhook URL; Discord webhooks
are channel-scoped and require an admin to provision one. The escalation
is therefore an **operator action**: paste the message body below into
`#support` (preferred) or `#mcp-servers` after joining the server.

## Escalation message (paste verbatim)

```
Hello Glama team,

jpcite (io.github.shigetosidumeda-cyber/autonomath-mcp) — Japanese
public-program evidence MCP — has been LIVE in the Anthropic Official
Registry since 2026-05-06 10:52 UTC (5+ days, well past the 24-72h
auto-crawl ETA quoted in your docs), but the Glama listing is still 404
at https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp.

PR #6192 on punkpeye/awesome-mcp-servers is blocked on the glama-bot
score badge, which depends on the Glama listing being live, so this is
on the critical path for our public-catalog visibility.

Request: trigger a manual re-crawl on the server and confirm whether
something on our side is blocking discovery (smithery.yaml id collision?
server.json schema?). Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp

We have all canonical signals already published:
- Anthropic Official Registry: LIVE v0.3.4 (verifiable via
  https://registry.modelcontextprotocol.io/v0/servers?search=autonomath)
- server.json + smithery.yaml + mcp-server.json at repo root
- Dockerfile + GitHub topics (mcp-server, model-context-protocol,
  claude-mcp, smithery, glama, ai-agent-tools)
- 139 tools, MIT license, homepage https://jpcite.com

Operator contact: info@bookyou.net (Bookyou株式会社, T8010001213708).
Happy to provide any additional metadata.

Thank you for the directory work.
— Shigetoumi Umeda
```

## Operator checklist

1. Open <https://discord.gg/C3eCXhYWtJ> in browser, accept Glama server
   invite (one-time).
2. Locate `#support` (fallback: `#mcp-servers`).
3. Paste message above. Attach a screenshot of `registry.modelcontextprotocol.io`
   search result if `#support` is read-only.
4. Wait 24h for a maintainer response. If none, fall back to:
   - `@punkpeye` mention on the awesome-mcp PR #6192
   - X/Twitter DM to `@glama_ai`
5. Update `analytics/registry_status_w23.json` with the response timestamp
   in `platforms[id=glama_ai].escalation_log`.

## Why this is operator-only

- Discord webhooks for Glama's official server are channel-scoped and
  require Glama-admin provisioning; there is no anonymous incoming-webhook
  URL to curl-POST.
- Posting via a bot account would require Discord OAuth + Glama-admin
  approval — both of which violate memory `feedback_zero_touch_solo`
  (no human-in-the-loop ops) at a steeper cost than a one-shot paste.

## Logged at

- `analytics/registry_status_w23.json` → `platforms[id=glama_ai].next_action`
- This doc (canonical message body)
