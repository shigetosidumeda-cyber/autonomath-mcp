# dev.to — long-form launch article

**Title**: `Building a Japanese institutional-data API for AI agents (and why ¥3/billable unit metered beats subscription tiers)`

**Tags**: `api`, `ai`, `python`, `showdev`

**Cover image**: TBD — use repo logo or screenshot of `/v1/programs/search` JSON response

---

## TL;DR

I shipped jpcite (`autonomath-mcp` on PyPI) — a REST + MCP search API over 11,601 Japanese subsidies, 9,484 laws, 2,065 court decisions, 13,801 invoice-registry entries, 50 tax rulesets, and 2,286 adoption cases. Returned public rows are designed to include a primary-source URL. Pricing is ¥3 per request metered with 3/day free anonymously. No subscription tiers. No signup for the free path.

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

That's it. Read on if you want the architecture, the data hygiene story, the MCP integration, and why I think tier-based SaaS pricing is the wrong shape for AI-agent traffic.

---

## What it is, in one sentence

A search index over Japanese institutional public data, exposed as REST + MCP, returning records with primary-source URLs.

## What it is not

- Not legal advice (弁護士法 §72)
- Not tax advice (税理士法 §52) — this is the big one. I am not a 税理士. Use this to find programs and pull primary-source URLs; verify with a licensed professional before making any business decision.
- Not 行政書士 work (§1)
- Not real-time amendment tracking — snapshots with partial historical diffs

The honest framing matters because Japanese institutional data is exactly the kind of domain where confident-sounding hallucinations will get someone in trouble. I'd rather under-promise on the legal surface than have a customer get sued over a subsidy claim my API hallucinated.

---

## Why this exists

The existing surface for Japanese institutional data is genuinely bad:

1. **Government portals are old.** Search is keyword-AND only on most prefecture sites. Half the URLs 404 within 18 months as ministries rotate CMSes.
2. **Aggregators pollute SERPs.** Sites like noukaweb / hojyokin-portal / biz.stayway rank for almost every subsidy query but their data is often months out of date and they cite each other instead of primary sources. I've seen the same stale subsidy syndicated across 8 aggregators for a year after it ended.
3. **There's no machine-readable layer.** If you're building an LLM agent that needs to reason about Japanese subsidies for a small business, you have no clean API to plug in. So the agent either hallucinates or web-scrapes garbage.

I built this because I wanted that layer to exist for my own work. Once I had ~80% of the data ingested I realized other people would want it too.

---

## Architecture

Single SQLite file. No microservices. No Kafka. No Snowflake.

```
src/jpintel_mcp/
  api/      FastAPI REST, mounted at /v1/*
  mcp/      FastMCP stdio server (184 tools, protocol 2025-06-18)
  ingest/   Data ingestion + canonical tier scoring
  db/       SQLite migrations + query helpers
  billing/  Stripe metered billing
  email/    Transactional email
```

### The DB

- One unified SQLite file: `autonomath.db` at 8.29 GB
- Schema is EAV-style: 503,930 件の正規化レコード (12 record kinds — programs, laws, corporate entities, statistics, enforcement records, etc.), 612 万件の structured 属性, 17.7 万件の関係性 link, 別名・略称 index 335,605 行
- 全文検索インデックスを 2 種類用意: 3-gram (CJK の部分一致に強い) と unicode61 (分かち書き済み日本語向け)
- ベクトル検索 で hybrid lexical+semantic search — 5 段階の階層インデックス
- 78 mirrored 派生 tables (424,417 rows total) ported from a previous separate jpintel.db, merged in via migration 032

Why SQLite and not Postgres? Because:

- The dataset is read-mostly. Writes happen during nightly ingest, reads happen 24/7.
- 8.29 GB fits on a Fly.io volume cheaply.
- 全文検索 + ベクトル検索 の組み合わせは、このワークロードでは Postgres + pg_vector + tsvector とほぼ互角で、可動部品が 1 つ少ない。
- I can ship the entire database to a customer's local machine for a self-hosted MCP install. They can't do that with Postgres without ops work.

### REST surface

Everything under `/v1/*`:

- `/v1/programs/*` — subsidies / loans / tax incentives / certifications
- `/v1/laws/*` — e-Gov laws (CC-BY)
- `/v1/court-decisions/*`, `/v1/case-studies/*`, `/v1/loan-programs/*`, `/v1/enforcement-cases/*`
- `/v1/tax_rulesets/*` — tax rulesets like 中小企業投資促進税制
- `/v1/exclusions/*` — eligibility rules
- `/v1/am/*` — annotations, validation, provenance, static resources, example profiles

OpenAPI lives at `https://api.jpcite.com/v1/openapi.json`.

### MCP surface

184 tools at default gates, protocol `2025-06-18`, FastMCP over stdio. The tool inventory mirrors the REST surface: search, get-by-ID, lifecycle, prerequisite chain, rule-engine check, snapshot-time queries, provenance lookup. Drop into Claude Desktop config:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

Restart Claude Desktop. Ask 「農業に使える東京都の補助金を教えて」. Claude calls `search_programs`, gets back rows with primary-source URLs, and cites them.

The wheel on PyPI doesn't ship the DB (8.29 GB is too big for a wheel). Instead it auto-detects empty local DB and HTTP-falls-back to `api.jpcite.com`. The first 3 req/day per IP are free, no signup. Past that, ¥3/billable unit metered with an API key.

If you want full local-mode MCP, clone the repo, fetch the DB tarball, run `autonomath-mcp` against the local file. No network.

---

## Data hygiene — the part nobody warns you about

About 70% of the past year was data plumbing, 30% was product. Some hard lessons:

### 1. Aggregators are poison

I had a tier-scoring system (S/A/B/C) that initially gave A-tier weight to programs cited by ≥3 aggregator sites. Then I realized aggregators cite each other recursively. The A-tier was full of stale junk. I rewrote the scorer to **ban aggregators from `source_url` entirely** — only ministry / prefecture / 公庫 / 国税庁 URLs count.

That dropped my "active programs" count by ~30%, which was painful. But the remaining rows are real.

### 2. Source-URL rot is constant

About 8% of source URLs decay per year as ministries rotate CMSes. I run a nightly checker against the `source_url + fetched_at` columns and route 404s into a public-hold bucket (2,871 rows currently). The user-facing `programs` count (11,601) excludes the public-hold rows.

### 3. Primary sources disagree with themselves

The same subsidy will show up on a METI page with one deadline and on the SMRJ portal with another. I had to pick a canonical hierarchy: **ministry > prefecture > affiliated agency > 公庫**. When they conflict, ministry wins. I document the conflict in the row's notes field.

### 4. Snapshots > "real-time"

I initially tried to track law amendments in real time. Then I realized e-Gov updates aren't atomic — they push partial corrections weekly, and you can get your reader into inconsistent states. I switched to monthly snapshots with diff records (制度時系列 snapshot), and the surface got dramatically more reliable.

---

## Why ¥3/billable unit metered, not Free/Pro/Enterprise

I get this question more than any other, so here's the long version.

**1. Solo + zero-touch.** I'm one person. No CS team, no sales, no DPA-negotiation team, no Slack Connect, no onboarding calls. The only economics that work are 100% self-service. Tier-based SKUs implicitly require sales conversations for the upper tiers — I can't do that, and I won't.

**2. Japanese B2B SaaS norms work against me.** Standard JP B2B sells annual minimums + seat fees + custom DPA + procurement integration. Competing on that surface needs sales + legal + integrations teams I don't have and won't hire. So I'm explicitly not selling to procurement-driven buyers; I'm selling to dev teams who can swipe a card.

**3. AI-agent traffic is bursty.** Agent workloads spike 100x for a few minutes then go to zero. Tier SKUs over-charge steady users and under-serve bursty ones. Pure metering matches actual cost shape.

**4. Removing risk > capturing value.** No subscription = no cancel friction = no annual lock-in = lower bar to try. My acquisition strategy is 100% organic, so reducing friction beats capturing higher LTV.

**5. The DB cost is a roughly known function of billable usage volume.** ¥3/billable unit has comfortable margin over my Fly.io + Stripe + bandwidth costs. It scales linearly. I can drop the price later if volume justifies.

The anonymous free allowance is intentional and aggressive: **3 req/day per IP, no signup**. I want devs to be able to type a curl command into a terminal and see real data back without filling out a form. Most agent prototypes won't exceed 3 req/day anyway, so the free path is genuinely usable.

```bash
# This works, no key needed
curl "https://api.jpcite.com/v1/programs/search?q=AI&prefecture=東京都"
```

---

## What's next

Things I'm explicitly **not** doing (per Bookyou株式会社 strategy):

- No paid ads. 100% organic acquisition.
- No sales team. Solo + zero-touch.
- No tier SKUs. Pure ¥3/billable unit metered, forever.
- No DPA negotiation. Public terms only.
- No Slack Connect / private support. Public docs + GitHub issues only.

Things I'm working on:

- More tax rulesets (50 → ~150 target)
- e-Gov full law coverage (9,484 → ~14k once monthly snapshots catch up)
- Better adoption-case grounding for "what actually got funded"
- A `provenance` MCP tool that returns the full source chain for any fact

---

## Try it

The free anonymous path works without any account:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

Sample response:

```json
{
  "total": 47,
  "results": [
    {
      "program_id": "tokyo_agri_dx_2026",
      "name": "東京都 農業 DX 推進事業補助金",
      "amount_yen_max": 5000000,
      "deadline": "2026-06-30",
      "source_url": "https://www.metro.tokyo.lg.jp/.../agri_dx.html",
      "tier": "A"
    }
  ]
}
```

For Claude Desktop / Claude Code MCP, see the README.

- Site: https://jpcite.com
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- Pricing: https://jpcite.com/docs/pricing/
- OpenAPI: https://api.jpcite.com/v1/openapi.json

Solo project under Bookyou株式会社 (T8010001213708). No VC, no team. Public docs and GitHub issues only.

Comments / questions / pricing-philosophy disagreements all welcome.
