# r/programming

**Title**: `Built a Japanese tax / subsidy data API for LLM agents — SQLite 全文検索 + ベクトル検索, ¥3/req metered`

---

## Body

I shipped jpcite today. It's a search API + MCP server over Japanese institutional data — 11,601 subsidy programs, 9,484 laws (e-Gov CC-BY), 2,065 court decisions, 13,801 invoice registrants, 50 tax rulesets, plus 1,185 enforcement records and 2,286 historical adoption cases. Returned public rows are designed to point to a primary-source URL (ministry / prefecture / 国税庁 / 日本政策金融公庫). Aggregator sites are banned from the source field.

The existing access surface for this data is genuinely bad — government portals are old, search is keyword-AND only, URLs rot, and aggregator sites pollute SERPs. I wanted a clean machine-readable layer for LLM agents doing due diligence on Japanese SMBs.

**Stack**:

- SQLite 全文検索 (3-gram + unicode61 二重インデックスで CJK 対応) + ベクトル検索 で hybrid lexical/semantic search
- FastAPI for the REST surface (`/v1/programs/*`, `/v1/laws/*`, `/v1/case-studies/*`, etc.)
- FastMCP stdio server, MCP protocol 2025-06-18, 139 tools at default gates
- 8.29 GB unified DB, 503,930 entities + 6.12M facts in EAV
- Fly.io Tokyo single-region deploy, Cloudflare Pages for the static site, Stripe metered billing

**Pricing**: ¥3/req metered (~$0.02). 3/day free anonymously, no signup. No subscription tiers — I'm a solo founder running zero-touch ops, so the whole thing has to be self-service.

**Honest framing**: it's information lookup, not tax advice. Not a substitute for a 税理士 (税理士法 §52). Verify primary sources before any business decision.

Demo curl (works without an API key for the first 3 req/day):

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Returns JSON with `program_id`, `name`, `amount_yen_max`, `deadline`, `source_url`, `tier`.

- Site: https://jpcite.com
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/

Happy to dig into the 全文検索 schema choices, the EAV trade-offs, or the data-ingest pipeline (e-Gov XML, NTA CSV bulk, prefecture HTML scraping) if anyone's interested.
