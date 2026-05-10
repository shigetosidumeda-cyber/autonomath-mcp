# Smithery v3 submission

## URL
https://smithery.ai/new

## smithery.yaml (final, copy-paste into repo root if not present)

```yaml
startCommand:
  type: stdio
  commandFunction:
    identifier: uvx
    args: ["autonomath-mcp"]
    env:
      JPCITE_API_KEY:
        required: false
        description: "Optional. Anonymous 3 req/day per IP works without key. ¥3/billable unit metered with key."
      JPCITE_API_BASE:
        required: false
        default: "https://api.jpcite.com"
metadata:
  version: "0.3.4"
  displayName: "jpcite — Japanese public-program evidence MCP"
  homepage: "https://jpcite.com"
  repository: "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
  license: "MIT"
  tags: ["mcp", "japan", "subsidy", "regtech", "claude", "cursor", "chatgpt"]
```

## Verify before submit
- [ ] `uvx --no-cache autonomath-mcp --help` works locally
- [ ] PyPI 0.3.4 listed: https://pypi.org/project/autonomath-mcp/
- [ ] Smoke test: `len(await mcp.list_tools())` >= 139
- [ ] Site https://jpcite.com returns 200 with valid TLS
- [ ] API https://api.jpcite.com/healthz returns 200
- [ ] OpenAPI https://jpcite.com/openapi.json reachable (paths=182)
- [ ] smithery.yaml present at repo root of shigetosidumeda-cyber/autonomath-mcp

## Submission steps
1. Open https://smithery.ai/new
2. GitHub login → select repo `shigetosidumeda-cyber/autonomath-mcp`
3. Smithery auto-detects smithery.yaml → publish
4. Listing page reachable at https://smithery.ai/server/jpcite (or auto-slug)

## Display name & slug strategy
- Display name uses **jpcite** (user-facing brand)
- Slug preference order: `jpcite` → `jpcite-mcp` → `jpcite-japanese-public` (whatever Smithery auto-resolves without collision)
- Do NOT use slug `autonomath` — that is PyPI legacy only, brand has migrated

## Tagline (140 字 limit, English)
> Japanese public-program evidence MCP — subsidies, loans, licenses, dispositions, invoice registry, e-Gov laws. 139 tools, ¥3/req metered, anonymous 3 req/day/IP free.

## Tagline (140 字 limit, 日本語)
> 日本の補助金・融資・許認可・行政処分・適格事業者・法令を法人番号で横断照会する Evidence MCP。139 tool、¥3/req 従量、無料 3 req/IP/日。

## Description (long-form, 800 字 limit)

jpcite is a Model Context Protocol (MCP) server that gives AI agents structured access to Japan's public-program landscape — 11,601+ subsidies, 1,185+ administrative dispositions, 13,801+ qualified-invoice registrants, 9,484+ law metadata entries, all joinable by 13-digit corporate number (法人番号).

Every response is an **Evidence Packet** containing `source_url`, `source_fetched_at`, and `content_hash`. Agents can cite, cache-invalidate, and replay queries deterministically. PDL v1.0 + CC-BY-4.0 license compliance is built into the payload schema.

**Tooling**: 139 MCP tools across six domains. `uvx autonomath-mcp` installs in one line, no Docker. Tested against Claude Desktop / Claude Code / Cursor / Continue / Windsurf.

**Pricing**: Anonymous 3 req/day/IP free, no signup. ¥3/billable unit metered via Stripe with API key. No tiered SaaS, no sales call.

**Fence**: 7 業法 (Tax Accountant §52 / Lawyer §72 / Administrative Scrivener §1 / Judicial Scrivener §73 / Labor-Social Insurance §27 / SME Diagnostician / Patent Attorney §75) scopes refuse with programmatic guard — no free-form professional advice generation.

**Brand note**: User-facing brand jpcite, PyPI dist autonomath-mcp (legacy, retained for ecosystem stability). Operated by Bookyou株式会社 (T8010001213708, 東京都文京区小日向2-22-1).

## Post-submit verification
- [ ] Listing https://smithery.ai/server/jpcite returns 200
- [ ] Install button shows `uvx autonomath-mcp`
- [ ] Tool count badge >= 139
- [ ] Description renders without markdown corruption
- [ ] Add Smithery badge to README.md of repo: `[![Smithery](https://smithery.ai/badge/jpcite)](https://smithery.ai/server/jpcite)`
- [ ] Cross-link from https://jpcite.com homepage to Smithery listing

## Maintainer entity
- Bookyou株式会社 (T8010001213708)
- info@bookyou.net
- https://jpcite.com
