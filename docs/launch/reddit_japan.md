# r/japan

**Title**: `Made a search API for Japanese subsidy / tax / law data — useful for foreign founders trying to figure out what programs they qualify for`

---

## Body

Posting because this might be useful for r/japan readers running businesses or freelancing here.

I built jpcite — a search API over Japanese institutional public data:

- 11,684 subsidy programs across all 47 prefectures (national + local)
- 9,484 laws from e-Gov (CC-BY)
- 2,065 court decisions
- 50 tax rulesets (角度税制, 中小企業投資促進税制, etc.)
- 13,801 invoice-registry entries (適格事業者)
- Plus 2,286 historical adoption cases so you can see what actually got funded

Why this matters if you're a foreigner running a small business or 個人事業主 here: Japanese subsidy info is genuinely scattered across hundreds of prefecture / city / METI / MAFF / SMRJ portals. Aggregator sites exist but most are SEO-farms with broken or out-of-date data. I built the API specifically to point at primary sources: public records return a `source_url` to the ministry or prefecture page where available. Aggregators are excluded from source fields.

You can hit it from a script, from Claude Desktop / Cursor via MCP, from a ChatGPT Custom GPT through OpenAPI Actions, or just curl it manually. Free for 3 requests/day with no signup (anonymous, IP-based). After that it is ¥3 per billable unit metered; normal search/detail calls are 1 unit, with no monthly minimums, no subscription, cancel anytime.

**Important caveat**: this is a search/lookup tool, not tax or legal advice. 税理士法 §52 says only a 税理士 can give actual tax advice. Use the data to find programs and pull primary-source URLs, then talk to a licensed professional before making a business decision.

Quick demo — try this in a terminal:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=IT&prefecture=東京都"
```

Returns programs in Tokyo matching "IT" with primary-source URLs.

- Site: https://jpcite.com
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp

Solo project (just me, Bookyou株式会社). No support team — it's all self-service. AMA if you've ever banged your head trying to find subsidy info and want me to look something up.
