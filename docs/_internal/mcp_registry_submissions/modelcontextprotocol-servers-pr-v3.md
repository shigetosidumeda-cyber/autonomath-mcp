# modelcontextprotocol/servers PR draft v3

## Target repo & section
https://github.com/modelcontextprotocol/servers → README.md → `## 🌎 Community Servers` section

## PR title
Add jpcite — Japanese public-program evidence API/MCP (139 tools)

## Md snippet (bilingual, ja+en, copy-paste ready)

```markdown
- **[jpcite](https://github.com/shigetosidumeda-cyber/autonomath-mcp)** — Japanese public-program evidence MCP. 日本の補助金・融資・許認可・行政処分・適格事業者・法令を法人番号 1 つで横断照会する Evidence API。139 tools, `uvx autonomath-mcp` 1-line install. Anonymous 3 req/day/IP free, ¥3/billable unit metered via Stripe. PDL v1.0 + CC-BY-4.0 compliant. Operated by Bookyou株式会社 (T8010001213708).
```

## PR body (英語、コミュニティ向け)

### Summary
jpcite is a Model Context Protocol server providing AI agents (Claude Code / Cursor / ChatGPT / Codex) with structured access to Japanese public-program data. The server exposes 139 tools across six data domains and returns Evidence Packets — every response payload includes `source_url`, `source_fetched_at`, and `content_hash` so downstream agents can cite and cache-invalidate at the field level.

### Data domains covered
1. **Subsidies (補助金)** — 11,601+ active programs across MAFF / METI / MHLW / Cabinet Office / 47 prefectures
2. **Loans (融資)** — JFC (日本政策金融公庫) + commercial banking program metadata
3. **Licenses (許認可)** — 7 業法 scope incl. construction / real estate / financial-instruments / pharma
4. **Administrative dispositions (行政処分)** — 1,185+ records with party / law / disposition-date
5. **Qualified-invoice registry (適格請求書発行事業者)** — 13,801+ T-number registrants joinable by 法人番号
6. **e-Gov laws (法令)** — 9,484+ statute metadata entries with article-level navigation

### Why this fits modelcontextprotocol/servers Community Servers
- Standard MCP stdio protocol, no custom transport
- Single-binary install via `uvx autonomath-mcp` (no Docker required)
- Tested against Claude Desktop, Claude Code, Cursor, Continue, Windsurf
- Listing fits the existing alphabetical/categorical organization
- No external service dependencies for anonymous tier (3 req/day/IP works offline of payment infra)

### Technical specs
- **Transport**: stdio (MCP standard)
- **Language**: Python 3.11+
- **License**: MIT (code) + PDL v1.0 / CC-BY-4.0 (data)
- **Auth**: Bearer token (optional); anonymous tier no-key
- **Rate limit**: 3 req/day/IP anonymous, unlimited metered (¥3/billable unit)
- **PyPI**: `autonomath-mcp` (0.3.4)
- **Container**: not required; uvx isolates env
- **Endpoint**: https://api.jpcite.com (Fly.io, multi-region)

### Pre-merge verification
- [x] `uvx autonomath-mcp --help` returns usage
- [x] `await mcp.list_tools()` returns ≥139 entries
- [x] `python -c "import autonomath_mcp"` no import error
- [x] PyPI 0.3.4 published and pip-installable
- [x] Repo has MIT LICENSE and README with install/usage
- [x] CI green (GitHub Actions run 25475753541, 14/14 step SUCCESS)
- [x] Production deploy live (deployment-01KR0AGKRFD39QZZJ10VWYZXS5, healthz=200)

### Brand note
User-facing brand is **jpcite** (jpcite.com). PyPI distribution name remains `autonomath-mcp` for backwards compatibility with existing ecosystem references. Both names refer to the same product operated by Bookyou株式会社 (法人番号 T8010001213708, 東京都文京区小日向2-22-1).

### Companion registrations
- punkpeye/awesome-mcp-servers PR (filed)
- Smithery listing (https://smithery.ai/server/jpcite)
- LobeHub plugin manifest (https://jpcite.com/.well-known/lobehub-plugin.json)
- OpenAI Custom GPT (jpcite — 日本公的制度 Evidence)
- Glama / MCPHub (already listed v1)

### Maintainer contact
- Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- Site: https://jpcite.com
- Mail: info@bookyou.net
- Entity: Bookyou株式会社 (T8010001213708, 東京都文京区小日向2-22-1)

### Listing snippet positioning
Recommend placement under `## 🌎 Community Servers` in alphabetical order at `J` (jpcite). Adjacent entries in current README:
- `joshuaday/mcp-jira` (J)
- `jpcite` ← **insert here**
- `kvthr/mcp-monad` (K)

If maintainers prefer a separate "Japan / Government / Regtech" subsection, jpcite is willing to be the seed entry and document the category description.

### License clearance
- **Code**: MIT (compatible with modelcontextprotocol/servers repo policy)
- **Data**: PDL v1.0 + CC-BY-4.0 with attribution baked into Evidence Packet `source_url` field
- **TOS confirmation**: National Tax Agency 適格事業者 bulk redistribution direct-confirmed 2026-04-24 (per repo CLAUDE.md SOT)
- **No aggregator scraping**: All primary government endpoints; no `gBizINFO` API key required for re-distribution

### Operator commitments
- Response SLA on PR review: 24 hours
- Production uptime target: 99.5%/month on api.jpcite.com
- Stable PyPI dist: `autonomath-mcp` (no rename planned despite jpcite branding)
- Issue tracker monitored daily

### Snippet positioning alternative
If maintainers feel the entry overlaps with existing `japan-gov-mcp` (LobeHub-incubated), jpcite proposes a sub-bullet structure clarifying the differentiation: jpcite is **2.8× tool surface (139 vs 50)**, ships **Evidence Packet** contract, and has **7 業法 fence** — these are non-trivial AI-agent-facing differentiators worth a separate entry.

### Visual badges (optional, for repo README)
- [![smithery](https://smithery.ai/badge/jpcite)](https://smithery.ai/server/jpcite)
- [![PyPI](https://img.shields.io/pypi/v/autonomath-mcp.svg)](https://pypi.org/project/autonomath-mcp/)
- [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
- [![Live](https://img.shields.io/badge/api-live-brightgreen.svg)](https://api.jpcite.com/healthz)
