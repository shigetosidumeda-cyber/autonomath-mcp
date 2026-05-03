# Twitter / X — 6-tweet launch thread

**Account**: founder personal X
**Schedule**: post within 30 minutes of HN submission, retweet at +6h and +18h for diurnal coverage

---

## Tweet 1/6 — what

Just shipped jpcite: a search API + MCP server over Japanese institutional data.

11,684 subsidies / 9,484 laws / 2,065 court decisions / 13,801 invoice registrants / 50 tax rulesets — public rows include primary-source URLs where available.

¥3/req metered. 3/day free anonymously, no signup.

🧵

---

## Tweet 2/6 — why

Existing access surface for Japanese institutional data is bad: aging gov portals, aggregator SEO-spam, URL rot, no machine-readable layer for AI agents.

I needed it for my own work. Built it for ~1 year. Today it's public.

Solo founder. Bookyou株式会社. No VC.

---

## Tweet 3/6 — how it works

Stack:

• SQLite 全文検索 (3-gram + unicode61 二重インデックスで CJK 対応)
• ベクトル検索 で hybrid lexical+semantic
• FastAPI (REST) + FastMCP (stdio)
• 8.29 GB unified DB, 503k entities, 6.12M facts (EAV)
• Fly.io Tokyo, single-region

93 MCP tools, protocol 2025-06-18.

---

## Tweet 4/6 — pricing

¥3/req metered (税込 ¥3.30). 3 req/日 anonymous free.

No tiers. No minimums. No subscription. No annual contracts.

Why? Solo + zero-touch ops. AI-agent traffic is bursty. No sales team to negotiate Enterprise SKUs. Pure metering matches actual cost shape.

https://jpcite.com/docs/pricing/

---

## Tweet 5/6 — try it

Free anonymous demo, no key needed:

```
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Returns Tokyo agri subsidies with primary-source URLs.

Honest framing: it's information lookup, not tax advice (税理士法 §52). Verify before any business decision.

---

## Tweet 6/6 — call to action

If you're building agents that touch Japanese regulation, I'd love feedback.

🌐 https://jpcite.com
📦 https://pypi.org/project/autonomath-mcp/
🐙 https://github.com/shigetosidumeda-cyber/autonomath-mcp

DMs open. Public docs only — no Slack Connect, no DPA negotiation. Self-service all the way.

/end
