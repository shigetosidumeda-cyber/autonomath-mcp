# mcphub.tools submission

**STATUS (2026-04-23): requires 2026-04 check — likely not viable.**

Attempted `WebFetch https://mcphub.tools` on 2026-04-23 — response was only
"Cloudflare Registrar", suggesting the domain is parked (registered but no
active site). Task #29's earlier research did not list `mcphub.tools` either;
the user's original task description pulled this name from 2025 / early 2026
MCP ecosystem discussion but it may never have shipped.

## Decision

- **Do not submit to mcphub.tools** until someone can confirm an active site
  with a public submission path. Re-check closer to launch (D-3).
- Two likely confusion points:
  1. `mcphub.tools` (this one — parked / not live)
  2. `mcphub.x` or `mcphubx.com` (separate aggregators, different operators)
- If mcphub.tools is still parked on D-3: **skip**, no traffic lost.

## Replacement candidates at the same traffic tier

| Registry | URL | Method | Status |
|---|---|---|---|
| mcpservers.org | https://mcpservers.org/submit | Free web form (email + 5 fields) | ACTIVE (confirmed 2026-04-23) |
| mcp.so | https://mcp.so/submit | GitHub issue template | ACTIVE per scripts/mcp_registries.md |
| MCP Servers Hunt | https://mcphunt.com/ | Community form + upvotes | ACTIVE per Task #29 |

See the dedicated files for each. Recommend backfilling mcphub.tools's slot
with `mcpservers.org` on D-0 (lowest effort free path).

## If mcphub.tools DOES come alive before launch

Expected fields based on similar aggregators:

| Field | Value |
|---|---|
| Server name | `autonomath-mcp` |
| Description | Japanese institutional data (補助金 / 融資 / 税制 / 共済) via MCP 2025-06-18. 6,771 programs, exclusion-rule aware. |
| GitHub URL | `https://github.com/shigetosidumeda-cyber/jpintel-mcp` |
| Install | `pip install autonomath-mcp` |
| Category | Finance / Government / Data |
| Contact | `sss@bookyou.net` |

Do NOT pay for premium placement — free tier only.
