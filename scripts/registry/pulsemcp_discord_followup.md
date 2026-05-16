# PulseMCP Discord follow-up (operator action)

**Why**: PulseMCP's auto-ingest is daily-from-Official-Registry + weekly
process. v0.3.4 published 2026-05-06 should appear by 2026-05-20 at the
latest. If not, escalate via Discord (no incoming-webhook URL exposed).

**Channel**: <https://discord.gg/dP2evEyTjS> (`#support` or `#servers`).

**Paste-verbatim message**:

```
Hello PulseMCP team,

Following up on jpcite (formerly AutonoMath, renamed 2026-04-30).
The Anthropic Official MCP Registry listing has been LIVE since
2026-05-06 10:52 UTC at:
https://registry.modelcontextprotocol.io/v0/servers?search=autonomath

We expected the daily ingest + weekly process to surface this on
pulsemcp.com by 2026-05-20 at latest, but the listing is still missing.

Could you confirm whether something on our side is blocking ingest, or
just trigger a manual sync? Server metadata below for reference:

Server Name:     jpcite
Registry name:   io.github.shigetosidumeda-cyber/autonomath-mcp
Repo:            https://github.com/shigetosidumeda-cyber/autonomath-mcp
Homepage:        https://jpcite.com
License:         MIT
Tools:           155 at default gates (verified)
Transport:       stdio + Streamable HTTP (MCP 2025-06-18)
Pricing:         anonymous 3 req/day per IP free; metered ¥3/unit
Operator:        Bookyou株式会社 (T8010001213708), info@bookyou.net

Thank you for the directory work.
— Shigetoumi Umeda
```

## Triggering criteria

Run this **only** if `https://www.pulsemcp.com/servers/jpcite` AND
`https://www.pulsemcp.com/servers/autonomath-mcp` both return 404 on
2026-05-20 or later. Until then, auto-ingest is the cheaper path
(memory `feedback_zero_touch_solo`).
