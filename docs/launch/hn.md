# Hacker News — Show HN

**Submit URL field**: `https://jpcite.com`
**Title (73 chars)**: `Show HN: jpcite – Japanese tax & subsidy data API for LLM agents (¥3/billable unit)`

ASCII fallback if HN strips the kanji:
`Show HN: jpcite - Japanese tax/subsidy data API for LLM agents (3 yen/billable unit)`

---

## First comment (text post body)

Hi HN. I've been building jpcite (autonomath-mcp on PyPI) for about a year — a search API + MCP server over Japanese institutional data: 11,601 subsidy programs, 9,484 e-Gov laws, 2,065 court decisions, 13,801 invoice registrants, 50 tax rulesets, 1,185 enforcement records, 2,286 採択事例. Returned public rows are designed to carry a primary-source URL (ministry / prefecture / 公庫 / 国税庁) — aggregators are explicitly banned from the source field.

I built it because the existing surface for accessing this data is awful. The portals are PHP-era, search is keyword-AND only, half the URLs 404 within 18 months, and aggregator sites SEO-spam the rest. For an LLM agent doing due diligence on a Japanese SMB, there was no clean machine-readable layer. So I made one.

- **Stack**: SQLite 全文検索 (3-gram + unicode61) + ベクトル検索 for hybrid search, FastAPI for REST, FastMCP for the stdio MCP server. 8.29 GB unified DB, 503,930 entities + 6.12M facts in an EAV schema. Single binary deploys to Fly.io Tokyo.
- **MCP**: 139 tools at default gates, protocol 2025-06-18. Drop into Claude Desktop config and ask in Japanese — it routes through search → primary-URL records.
- **Pricing**: ¥3/billable unit metered (≈ $0.02), 税込 ¥3.30. 3 req/day free anonymously, no signup. No tiers, no seat fees, no annual minimums. Solo founder + zero-touch ops, so it has to be self-service.

Honest positioning — this is **information lookup, not advice**. It's not a 税理士 replacement (税理士法 §52), not 弁護士 work (弁護士法 §72), not 行政書士 (§1). Verify the primary-source URL before any business decision. The whole point is to give agents a clean lookup layer; the human-in-the-loop still owns the judgment call.

Try it (no key needed for the first 3/day):

```
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Returns JSON with primary-source URLs. OpenAPI: `https://api.jpcite.com/v1/openapi.json`.

Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
PyPI: https://pypi.org/project/autonomath-mcp/
Pricing: https://jpcite.com/docs/pricing/

I'm one person (Bookyou株式会社, T8010001213708). No VC, no support team. Happy to answer architecture / data-pipeline / pricing questions in this thread.
