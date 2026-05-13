# r/Entrepreneur (or r/SaaS)

**Title**: `Launched a Japanese regtech B2B SaaS today — ¥3/billable unit metered, no subscription tiers, solo founder. Here's why I picked that pricing model.`

---

## Body

Today I launched jpcite — a search API + MCP server over Japanese institutional data (subsidies, laws, court decisions, invoice registry, tax rulesets, enforcement records). Target users: AI/dev teams building agents that need to reason about Japanese regulation, plus accounting / consulting firms that want clean machine-readable lookups.

I'm posting here mostly to explain why I chose **fully metered ¥3/billable unit** instead of the usual SaaS tier playbook, since that's been the most-asked question from people who've previewed it.

## Why ¥3/billable unit metered, not Free/Pro/Enterprise

**1. Solo + zero-touch.** I'm one person. Bookyou株式会社 (T8010001213708). No CS team, no sales, no DPA negotiation, no Slack Connect, no onboarding calls. The only way that math works is if every single feature is self-service. Tier SKUs require sales conversations to land Enterprise customers — I can't do that, and I don't want to.

**2. Japan B2B is annual-contract heavy.** Standard JP B2B SaaS sells annual minimums + seat fees + custom DPA. To compete on that surface I'd need a sales team, a legal team, and a procurement-integration team. I have none of those and won't hire them.

**3. AI-agent traffic is bursty.** Customers running agent workloads have requests that spike 100x for a few minutes then go to zero. Tier SKUs over-charge the steady users and under-serve the bursty ones. Pure metering matches the actual cost shape.

**4. Trust is built by removing risk.** No subscription = no cancel friction = no annual lock-in = lower bar to try. My acquisition strategy is 100% organic (no paid ads, no cold outreach), so removing the friction matters more than capturing a higher contract value.

**5. The honest answer to "what if you grow?"** — I can charge more per request later, or expose enterprise features (private deploy, SLA) as separate add-ons. I don't have to break the core pricing.

## The product

- 11,601 subsidies + 9,484 laws + 2,065 court decisions + 13,801 invoice registrants + 50 tax rulesets + 1,185 enforcement records + 2,286 adoption cases
- Returned public rows are designed to include a primary-source URL (ministry / prefecture / 国税庁 / 公庫). Aggregators banned.
- REST API + MCP server (151 tools at default gates, protocol 2025-06-18)
- ¥3/billable unit (税込 ¥3.30), 3 req/日 free anonymously, no signup

## Honest positioning

This is information lookup, not tax / legal advice. 税理士法 §52 disclaimer — not a 税理士 replacement. The whole pitch is "give your agent clean primary-source lookups; humans still own the judgment."

## Try it

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Returns programs in Tokyo with primary-source URLs.

- Site: https://jpcite.com
- Pricing detail: https://jpcite.com/docs/pricing/
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp

No VC, no team, no plans to raise. AMA on the pricing decision, the JP regtech market, or the data plumbing.
