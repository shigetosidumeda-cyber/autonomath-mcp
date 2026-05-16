# PulseMCP (pulsemcp.com) submission

**Method**: web form at https://www.pulsemcp.com/submit + auto-ingest from
Official MCP Registry (modelcontextprotocol.io). PulseMCP states:

> We ingest entries from the Official MCP Registry daily and process them
> weekly.

**Direct submit confirmed infeasible 2026-05-11** (Wave 23 probe):
- `GET /api`            -> HTTP 403 (Cloudflare CAPTCHA gate)
- `GET /api/servers`    -> HTTP 403
- `POST /submit`        -> client-side JS only; no backend `action=` URL
- pulse-mcp GitHub org  -> 404 (no public repo for PRs)

The form is OAuth-gated and ships through a closed Cloudflare Worker. The
sustainable path is the auto-ingest, plus an email follow-up to operators.

## Channels

| Channel  | URL                                          | Used for                       |
|----------|----------------------------------------------|--------------------------------|
| Form     | https://www.pulsemcp.com/submit              | Manual operator action only    |
| Discord  | https://discord.gg/dP2evEyTjS                | #support / #servers ping       |
| Twitter  | https://x.com/pulsemcp                       | Public ping when listing late  |
| LinkedIn | https://www.linkedin.com/company/pulsemcp    | Operator-to-operator ping      |
| Email    | (CF-obfuscated in footer; submit via discord)| Inquiries about listings       |

## Auto-discovery substrate already in place

The Anthropic Official Registry listing publishes the canonical
`server.json` for `io.github.shigetosidumeda-cyber/autonomath-mcp` at
v0.3.4 (verified Wave 22). PulseMCP's daily ingest mirrors that. Our
`pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` /
`mcp-server.json` quintet already advertises 139 tools at default gates and
the canonical homepage `https://jpcite.com`. No code change is needed for
the auto-mirror.

## Action checklist

- [x] Anthropic Official Registry listing LIVE at v0.3.4 (Wave 22 verify)
- [x] GitHub topics include `mcp-server`, `model-context-protocol`,
      `claude-mcp`, `smithery`, `glama`, `ai-agent-tools`
- [x] `server.json` carries homepage, repository, license, categories
- [x] Wave 23 follow-up: Discord ping to PulseMCP support (see
      `scripts/registry/pulsemcp_discord_followup.md` for the canonical
      message body — operator copy-paste path; no curl webhook because
      PulseMCP's Discord does not expose an incoming-webhook URL publicly)
- [ ] re-poll `https://www.pulsemcp.com/servers/jpcite` on 2026-05-18

## Expected ETA

Daily ingest + weekly process: listing should appear at
`pulsemcp.com/servers/jpcite` (or `/servers/autonomath-mcp` slug fallback)
**within 7 days of v0.3.4 publish (2026-05-06)** — earliest 2026-05-13,
latest 2026-05-20.

If still absent on 2026-05-20:
1. Operator submits the web form (5 min) using the body template below.
2. Operator pings #support on PulseMCP Discord with the form receipt.

## Mail / form body (canonical)

```
Subject: jpcite — Japanese public-program evidence MCP (server submission)

Hello PulseMCP team,

Adding jpcite (formerly AutonoMath, renamed 2026-04-30) to your catalog.
It's the only MCP server with first-party evidence (URL +
source_fetched_at + 互換/排他 rules) for the entire Japanese public-program
landscape: 補助金 / 融資 / 税制 / 認定.

Quick facts:
- Tools: 155 at default gates (verified `len(await mcp.list_tools())`)
- Corpus: 11,601 searchable programs + 9,484 e-Gov laws + 13,801 適格事業者
  + 166K corporate entities + 1,185 行政処分 + 2,065 court decisions
- Registry: io.github.shigetosidumeda-cyber/autonomath-mcp v0.3.4 LIVE at
  registry.modelcontextprotocol.io
- Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- Homepage: https://jpcite.com
- Smithery: @bookyou/jpcite (pending claim)
- Pricing: anonymous 3 req/day per IP free; metered ¥3/billable unit
- License: MIT

Please pull it into your daily ingest cycle. Happy to answer any compliance
or transport questions (we ship stdio + streamable HTTP).

— Bookyou株式会社 / info@bookyou.net
```

## Notes

- PulseMCP's `/submit` page is gated behind a SPA; operator-side submission
  is required only if auto-ingest does not pick the entry up by 2026-05-20.
- We do NOT pay the $39 expedited tier — fits zero-touch / organic policy.
- The CF-obfuscated PulseMCP support email is intentionally undisclosed in
  this doc to avoid stale-cache poisoning; resolve it live from the footer
  before sending. See `tools/offline/submit_pulsemcp_mail.py --discover-to`
  for the runtime resolver.
