# awesome-mcp-servers PR draft v3 (punkpeye/awesome-mcp-servers, 86.6k★)

## PR title
Add jpcite — Japanese public-program evidence API/MCP (139 tools, ¥3/req metered)

## Target file & section
README.md → `### Other / Government / Public Data` (なければ最も近い category に追加)

## Md snippet to insert
- [jpcite](https://github.com/shigetosidumeda-cyber/autonomath-mcp) — Japanese public-program evidence layer (subsidies / loans / licenses / enforcement / qualified-invoice registry / e-Gov laws). 139 tools, `uvx autonomath-mcp` 1-line install, ¥3/billable unit metered, free 3 req/day per IP, no API key required for anon tier.

## PR body (英語 3 段落)

**What this adds**: jpcite is a Japanese public-program evidence MCP/API providing first-hop access to 11,601+ subsidies, 1,185+ administrative dispositions, 13,801+ qualified-invoice registrants, 9,484+ law metadata entries — all joinable by 13-digit corporate number (法人番号). Anonymous 3 req/day/IP works without API key; metered ¥3/billable unit with key via Stripe.

**Why it belongs**: AI agents (Claude Code / Cursor / ChatGPT / Codex) using Japanese subsidy/regulatory data currently need 3-10 separate API calls per query across gBizINFO / EDINET / J-Grants. jpcite returns evidence packets (`source_url + fetched_at + content_hash`) with PDL v1.0 / CC-BY-4.0 license compliance baked in.

**Verification**: `uvx autonomath-mcp --help` works as expected; built-in 7 業法 fence respects Tax Accountant Law §52 / Lawyer Law §72 / Administrative Scrivener Law §1 / Judicial Scrivener Law §73 / Labor & Social Security Attorney Law §27 / SME Diagnostician Registration Rules / Patent Attorney Law §75 by not producing individual tax/legal advice. Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp (PyPI: autonomath-mcp@0.3.4)

## Brand note for reviewer
User-facing brand is **jpcite** (jpcite.com); PyPI distribution name is `autonomath-mcp` (legacy, retained for ecosystem stability). Both refer to the same product operated by Bookyou株式会社 (T8010001213708, info@bookyou.net).

## Differentiation vs nearest existing entry
The repository currently lists `japan-gov-mcp` (LobeHub-incubated, ~50+ tools) under government data. jpcite is differentiated on five concrete axes that AI agents care about:
1. **Tool surface**: 139 tools vs ~50 (~2.8× breadth) — covers subsidies, loans, licenses, dispositions, qualified-invoice registry, e-Gov laws in a single MCP.
2. **Evidence Packet contract**: Every response includes `source_url`, `source_fetched_at`, and `content_hash` so downstream agents can cite or invalidate cache.
3. **License compliance built-in**: PDL v1.0 + CC-BY-4.0 attribution is part of the payload; National Tax Agency invoice registry redistribution is TOS-cleared per 2026-04-24 direct confirmation.
4. **7 業法 fence**: Programmatic refusal in the seven Japanese professional-services statute scopes (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 / 司法書士法 §73 / 社労士法 §27 / 中小企業診断士登録規則 / 弁理士法 §75) instead of free-form generative answers.
5. **Anonymous-first pricing**: 3 req/day/IP without API key, then ¥3/billable unit metered via Stripe. No tiered SaaS, no sales call, zero onboarding friction.

## PR submission checklist (operator-facing)
- [ ] Fork punkpeye/awesome-mcp-servers
- [ ] Locate `### Government` or nearest category in README.md
- [ ] Insert the Md snippet line above
- [ ] Open PR with the 3-paragraph body
- [ ] Link companion submissions: modelcontextprotocol/servers PR, Smithery listing, LobeHub plugin manifest, OpenAI Custom GPT
- [ ] Respond to maintainer feedback within 24h
- [ ] If category mismatch, accept maintainer's suggested category (do not argue)

## Contact for reviewer
- Maintainer entity: Bookyou株式会社 (法人番号 T8010001213708)
- Mail: info@bookyou.net
- Site: https://jpcite.com
- Repo issues: https://github.com/shigetosidumeda-cyber/autonomath-mcp/issues

## Production readiness evidence
- **Deployment**: Fly.io deployment-01KR0AGKRFD39QZZJ10VWYZXS5 LIVE
- **CI**: GitHub Actions run 25475753541 = 14/14 step SUCCESS
- **Commit**: GH_SHA=b1de8b2 (38 commit hardening series)
- **Health**: https://api.jpcite.com/healthz returns 200
- **OpenAPI**: v0.3.4, 182 paths (net +3 from baseline)
- **PyPI**: autonomath-mcp 0.3.4 installable via `pip install autonomath-mcp` or `uvx autonomath-mcp`

## Why agents need this entry now
Japanese SME / regtech queries are a documented gap in the awesome-mcp-servers index. Currently `japan-gov-mcp` is the only Japan-focused entry, with ~50 tools and no Evidence Packet contract. jpcite closes the gap with 2.8× tool surface and citation-grade outputs that AI agents can replay and cite without fabrication risk.

## License & redistribution clearance
- Code: MIT
- Data: PDL v1.0 (National Tax Agency 適格事業者 redistribution per 2026-04-24 direct TOS confirmation) + CC-BY-4.0 (e-Gov, MAFF, METI sources)
- Attribution is mechanically generated in every Evidence Packet `source_url` and `source_fetched_at` fields
- No scraping of license-restricted aggregators; all data sourced from primary government endpoints

## Maintainer commitment
- Response SLA on reviewer feedback: 24 hours
- Production stability target: 99.5% monthly uptime on api.jpcite.com (Fly.io multi-region)
- Update cadence: weekly (Wave releases) at minimum during launch quarter
- Issue tracker monitored daily: https://github.com/shigetosidumeda-cyber/autonomath-mcp/issues

## Pre-PR-open verification checklist (operator-facing)
- [ ] Fork synced with upstream punkpeye/awesome-mcp-servers main
- [ ] Branch named `add-jpcite` created
- [ ] README.md insertion verified visually (alphabetical or category-correct)
- [ ] No trailing whitespace or accidental file changes outside README.md
- [ ] PR body uses three-paragraph structure exactly as drafted above
- [ ] Companion links to modelcontextprotocol/servers PR, Smithery, LobeHub, OpenAI GPT included as edit-comment after PR open
- [ ] Verify https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/README.md is publicly viewable
- [ ] Verify `uvx autonomath-mcp --help` works on a fresh machine (cold cache)
- [ ] Verify https://api.jpcite.com/healthz returns 200 (paste curl output into PR as proof)

## Post-merge follow-ups
- [ ] Add awesome-mcp-servers badge to repo README.md
- [ ] Tweet/Bluesky announce merge with link
- [ ] Update https://jpcite.com homepage to show "Listed on awesome-mcp-servers"
- [ ] Cross-post merged-PR link in Zenn/note articles (Wave 4 Q output)
- [ ] Monitor incoming traffic from awesome-mcp-servers referrer in 30-day window

## Rejection contingency
If maintainers reject (rare but possible reasons):
- **Reason: too commercial** → Emphasize anonymous tier (3 req/day/IP free, no signup). MIT code license.
- **Reason: duplicate of japan-gov-mcp** → Provide the 5-axis differentiation table inline in the PR thread.
- **Reason: not enough community usage** → Reapply after Q3 once GitHub star count / Stripe MRR clears community-server bar.
- **Reason: category mismatch** → Accept maintainer suggestion immediately; do not argue.
