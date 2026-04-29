---
targets: Cursor Directory + Windsurf (Codeium) MCP marketplaces
prepared: 2026-04-23
status: DRAFT — submit post PyPI publish (#74)
---

# Cursor Directory + Windsurf MCP Marketplace Submissions

Both accept MCP servers via a web form / GitHub-based pipeline. Because MCP is
protocol-level, the same `autonomath-mcp` binary installs on both.

**BLOCKER**: submit only after `autonomath-mcp` v0.1.0 is live on PyPI (task #74).

---

## A. Cursor Directory (`cursor.directory/plugins`)

### Submission URL
https://cursor.directory/plugins (Submit button)

### Form fields

| Field | Value |
|-------|-------|
| Plugin name | `AutonoMath` |
| Slug | `autonomath-mcp` |
| Tagline (< 200 chars) | `日本の公的制度 (補助金・融資・税制・認定) 13,578 件 + 採択事例 + 融資三軸分解 + 行政処分 を横断検索する MCP サーバ. 35 排他ルール, protocol 2025-06-18, 12 tools.` |
| Category | Data / Productivity / Developer Tools |
| Icon (256×256 PNG) | `https://zeimu-kaikei.ai/assets/mcp_preview_1.png` |
| Tile (1200×630) | `https://zeimu-kaikei.ai/assets/mcp_preview_1.png` |
| Repo URL | `https://github.com/shigetosidumeda-cyber/jpintel-mcp` |
| Homepage URL | `https://zeimu-kaikei.ai/` |
| Author | Bookyou 株式会社 |
| Contact email | `info@bookyou.net` |
| License | MIT |
| Install command | `uvx autonomath-mcp` |
| Pricing | Free 50 req/month per IP (JST first-of-month reset); ¥3/req tax-exclusive (¥3.30 tax-inclusive) metered |
| Tags | `japan, japanese, subsidy, 補助金, grant, loan, tax, certification, government, mcp, stdio, 2025-06-18` |

### Cursor `.cursor/mcp.json` snippet (users copy into project)

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

### Expected review
- manual curation, **3-10 日**
- badge post-acceptance
- community upvotes amplify discovery

---

## B. Windsurf (Codeium) MCP

### Submission channel
Windsurf supports MCP natively via `~/.codeium/windsurf/mcp_config.json`. There is
no public "directory" as of 2026-04. Listing occurs by:

1. Official MCP Registry (task #102) → Windsurf ingests daily
2. README + install doc on `zeimu-kaikei.ai/docs/getting-started/`
3. Community post on Codeium community (see below)

### User-side config snippet (for README / docs)

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

Path: `~/.codeium/windsurf/mcp_config.json` (macOS / Linux); `%USERPROFILE%\.codeium\windsurf\mcp_config.json` (Windows).

### Community announcement targets
- Codeium Discord `#mcp` channel (post launch + install snippet)
- Codeium community feedback URL: https://codeium.canny.io/ (feature request: "日本の制度 MCP")
- Windsurf "Cascade" chat — the team accepts docs PRs at `github.com/codeium/windsurf-docs` (unofficial mirror)

### Expected review
- No formal directory — inclusion occurs via Official MCP Registry (#102) propagation
- Visibility driver: ambient discovery through Codeium community + docs PR

---

## Pre-submission checklist (shared)

- [ ] `autonomath-mcp` v0.1.0 published on PyPI (`pip install autonomath-mcp` resolves)
- [ ] `uvx autonomath-mcp` works on a clean machine (test on spare laptop)
- [ ] Cursor Directory account created
- [ ] GitHub repo `AutonoMath/autonomath-mcp` public with README + LICENSE + CHANGELOG
- [ ] Tile images accessible: `https://zeimu-kaikei.ai/assets/mcp_preview_{1,2}.png` → 200 OK
- [ ] Screenshot of Cursor MCP panel showing 12 tools after `.cursor/mcp.json` install

## Rollout timing (per machine-speed launch plan)

- D+3: submit Cursor Directory (10 min form, review 3-10 days)
- D+3: post Codeium community announcement + Windsurf docs PR
- D+7: verify propagation from Official MCP Registry → Windsurf auto-discovery (if any)

## Related

- `/docs/_internal/mcp_registry_submissions/anthropic_external_plugins.md` — Claude Desktop Extensions
- `/docs/_internal/mcp_registry_submissions/official_registry_submission.md` — primary source for auto-propagation
- `/docs/_internal/mcp_registry_submissions/smithery_submission.md` — Smithery parallel submission
- `/docs/_internal/mcp_registry_submissions/README.md` — full registry map (8 targets)
