# mcpservers.org submission

**Method**: web form at https://mcpservers.org/submit. Tier 2 "premium"
($39) is **not used** (zero-touch / organic policy).

**Direct submit confirmed infeasible 2026-05-11** (Wave 23 probe):
- `GET  /api`        -> HTTP 404 (no public REST surface)
- `GET  /api/submit` -> HTTP 404
- `GET  /add`        -> HTTP 404
- `GET  /servers/jpcite` -> HTTP 404
- Form action URL: client-side TanStack Start (createServerFn) — the
  endpoint resolves at runtime, not visible to plain `curl`.

The form lives behind a JS-only React-TanStack page (`server-list-*.js` +
`server-fns-*.js` confirmed in `<script>` tags). No public GitHub repo for
PR-based submissions; no JSON RPC for direct POST.

## Channels

| Channel | URL                                | Use                          |
|---------|------------------------------------|------------------------------|
| Form    | https://mcpservers.org/submit      | Operator manual submission   |
| Email   | contact@mcpservers.org             | Submissions + claims         |

Email decoded from CF email-protection hex `31525e5f45505245715c5241425443475443421f5e4356`
(XOR key 0x31).

## Mail body (canonical)

```
Subject: [mcp server submission] jpcite — Japanese public-program evidence

Hello mcpservers.org team,

I'd like jpcite added to the catalog. Short description and metadata below.

Server Name:        jpcite
Short Description:  Japanese public-program evidence MCP — subsidies, loans,
                    tax, law, invoice & corporate data. 139 tools. First-
                    party source citations (URL + source_fetched_at +
                    互換/排他 rules) for every row.
Link (GitHub):      https://github.com/shigetosidumeda-cyber/autonomath-mcp
Link (Homepage):    https://jpcite.com
Category:           Government / Legal / Finance / Data / Compliance
Contact Email:      info@bookyou.net

Additional metadata:
- PyPI:        autonomath-mcp v0.3.4
- Anthropic Official MCP Registry: LIVE
  https://registry.modelcontextprotocol.io/v0/servers?search=autonomath
- Smithery:    @bookyou/jpcite
- Transport:   stdio + Streamable HTTP (MCP 2025-06-18 protocol)
- License:     MIT

Honest scope: 11,601 searchable programs + 9,484 e-Gov laws + 13,801 適格
事業者 + 166K corporate entities + 1,185 行政処分 + 2,065 court decisions.
Maintained by Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708).

Pricing: anonymous tier 3 req/day per IP (free, no signup); metered tier
¥3/billable unit (税込 ¥3.30) — fits the public catalog "Free" badge with
a paid path for heavy users.

Please confirm receipt and ETA for listing. Happy to provide additional
evidence packets on request.

— Shigetoumi Umeda / Bookyou株式会社
  info@bookyou.net
```

## Action checklist

- [x] Email body canonicalized in this doc (§ Mail body)
- [x] Wave 23 dispatch helper: `tools/offline/submit_mcpservers_mail.py`
      (dry-run by default; `--send` for delivery)
- [x] Auto-discovery still relies on email submission — no GitHub PR path
- [ ] re-poll `https://mcpservers.org/servers/jpcite` on 2026-05-18

## Expected ETA

Manual review cycle (community-curated): **7-14 days from email send**.
Earliest 2026-05-18, latest 2026-05-25.

If no response by 2026-05-25, fall back to:
1. Submitting the web form (operator action).
2. DM via twitter.com/mcpservers if account is operator-discoverable.

## Why we don't pay the $39 expedited tier

Memory `feedback_no_cheapskate` says: prefer paths that raise success
probability, not ones that "cut cost". But the zero-touch / organic policy
(memories `feedback_zero_touch_solo` + `feedback_organic_only_no_ads`) is
strictly higher-priority than expedited registry tiers — paid expedite is
sales-channel-adjacent. Stay free, wait 14 days, escalate via Discord if
needed.
