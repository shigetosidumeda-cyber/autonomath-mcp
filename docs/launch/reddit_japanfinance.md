# r/japanfinance

**Title**: `Search API for Japanese subsidy / tax / law data — useful for small-business owners trying to find programs they qualify for`

---

## Body

Posting here because r/japanfinance has a lot of small-business owners and 個人事業主 who've struggled with finding subsidy / tax-incentive info in Japan. I just launched jpcite — a search API over Japanese institutional public data that I built specifically to fix that accessibility problem.

## What it covers

- **11,601 subsidy programs** across all 47 prefectures + national (補助金 / 融資 / 税制 / 認定)
- **50 tax rulesets** (角度税制, 中小企業投資促進税制, 経営強化税制, etc.)
- **9,484 laws** from e-Gov (CC-BY)
- **13,801 適格事業者** entries (invoice-registry lookups)
- **2,286 adoption cases** so you can see what kinds of businesses actually got funded
- **2,065 court decisions** + **1,185 enforcement records** for risk-checking 業者

Returned public rows are designed to include a `source_url` to the original government page. Aggregator sites are banned from the source field — past portal incidents created 詐欺 risk for me, so I cut them entirely.

## Why this is useful for small-business owners

Japanese subsidy info is genuinely scattered across hundreds of prefecture / city / METI / MAFF / SMRJ portals. The aggregator sites you find on Google are often months out of date. As a 個人事業主 or small business owner you can either:

1. Pay a 行政書士 / 中小企業診断士 to find programs (¥30,000+ per consultation) — the high-quality path
2. Spend 10+ hours a month manually checking ministry portals — accurate but exhausting
3. Use this API for ¥3/billable unit with primary-source URLs, then verify with a licensed professional before applying

I'm not trying to replace path #1 — see disclaimer below. I'm trying to make path #3 a viable preliminary research step.

## Honest disclaimer

This is information lookup, not tax / legal advice (税理士法 §52, 行政書士法 §1). Specifically:

- I am **not** a 税理士. The API does not give tax advice.
- I am **not** a 行政書士. The API does not file applications.
- Use the data to discover programs and pull primary-source URLs, then talk to a licensed 税理士 / 行政書士 / 中小企業診断士 before applying.

## Pricing

¥3 per request, 税込 ¥3.30. **First 3 requests/day are free anonymously, no signup**, IP-based, JST daily reset. No subscription tiers, no minimums, cancel anytime.

For most people doing preliminary research on a single business, 3 req/day is enough. Power users buy an API key and get charged per request.

## Quick demo

Try this in a terminal — no signup needed:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=飲食&prefecture=東京都"
```

Returns subsidies in Tokyo for restaurants/food businesses with primary-source URLs.

## Links

- Site: https://jpcite.com
- Pricing: https://jpcite.com/docs/pricing/
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/

## Operator

Bookyou株式会社 (T8010001213708), 東京都文京区. Solo founder, 梅田茂利. No support team — it's all self-service. AMA on the data, the pricing, or specific subsidy categories you want me to explain.
