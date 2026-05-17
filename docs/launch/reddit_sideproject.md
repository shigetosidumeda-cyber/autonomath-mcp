# r/SideProject

**Title**: `Solo-built a Japanese tax/subsidy data API for AI agents over the past year — launching today at ¥3/billable unit`

---

## Body

After about a year of nights and weekends, I launched jpcite today. It's a search API + MCP server over Japanese institutional data — 11,601 subsidy programs, 9,484 laws, 2,065 court decisions, 13,801 invoice registrants, plus tax rulesets and enforcement records. Returned public rows are designed to include a primary-source URL.

**The 1-year build journey, condensed**:

- Started as a personal tool to find Japanese subsidies for my own business (Bookyou株式会社). Realized the source data was a mess and aggregators were SEO-spam.
- Pivoted from "tool for me" to "API for AI agents" once I started using Claude Code / Claude Desktop heavily and saw that LLMs needed clean institutional data way more than humans did.
- Spent ~6 months on data ingest: e-Gov XML, NTA CSV bulk, prefecture HTML scraping, dedup, primary-source linking. Built a tier scoring system (S/A/B/C) based on data completeness.
- Last 3 months: MCP server (184 tools, protocol 2025-06-18), Stripe metered billing, Cloudflare Pages static site, Fly.io Tokyo deploy.
- Pricing went through 4 iterations. Landed on **¥3/billable unit metered, 3/day free anonymously, no tiers, no minimums**. As a solo founder I literally cannot afford to negotiate annual contracts — has to be self-service.

**Stack**: SQLite 全文検索 + ベクトル検索, FastAPI, FastMCP, Fly.io Tokyo, Cloudflare Pages, Stripe metered. 8.29 GB unified DB.

**Honest framing**: it's information lookup, not tax advice. 税理士法 §52 disclaimer in the body. Not a 税理士 replacement.

**Try it**:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Returns JSON with primary-source URLs. No key needed for first 3/day.

- Site: https://jpcite.com
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/

**What I'd do differently**: I underestimated how much time data hygiene would take vs. building features. Probably 70% of the year was data plumbing, 30% was product. If you're building anything in regtech/govtech, budget that ratio.

No VC, no team, no support staff. Just one person and a database. AMA on the build, the data, the pricing decision, or anything else.
