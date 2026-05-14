---
title: "jpcite — Japanese public-info MCP server (11k+ subsidies, 9k+ laws, 1-line uvx install for Claude Code)"
published: true
tags: mcp, ai, rag, python, showdev
canonical_url: https://jpcite.com
---

## TL;DR

`uvx autonomath-mcp` is a one-line install MCP server that connects Claude Code / Cursor / ChatGPT Custom GPTs / OpenAI Agents SDK to a unified Japanese public-info corpus: **11,601+ subsidies**, **9,484+ law catalog stubs (e-Gov CC-BY-4.0)**, **1,185+ administrative-disposition cases**, **13,801+ invoice-eligible-issuer records (NTA PDL v1.0)**, **22,258+ enforcement details**, and **503,930+ corporate-entity rows** from gBizINFO. **151 MCP tools** at default gates. Every tool response carries an **Evidence Packet** (`source_url + fetched_at + content_hash`) so AI agents cannot fabricate provenance. Pricing is **fully metered ¥3 per request** (≈ USD 0.02) with **3 anonymous requests/IP/day free** — no API key needed to try it. Operator: **Bookyou Co., Ltd.** (qualified-invoice issuer T8010001213708).

## Why a Japan-specific Evidence Packet layer?

Japanese public-info (subsidies / regulations / administrative dispositions / qualified-invoice issuers / laws) is fragmented across 7+ government sites (METI / SME Agency / NTA / e-Gov / gBizINFO / ministry portals). Practitioners (tax accountants, M&A intermediaries, certified consultants) burn 2–3 hours per client cross-referencing these manually. Asking ChatGPT or Claude directly returns hallucinated subsidy names, outdated eligibility, and zero source URLs — the model has no view of the latest snapshot.

jpcite normalizes these 7 sources, attaches `source_url + fetched_at + content_hash` to every fact, and exposes the unified corpus through 4 AI-agent surfaces.

## Architecture

- **REST + MCP** dual surface (FastAPI + FastMCP stdio).
- **SQLite FTS5 trigram + sqlite-vec** backend over a unified 9.4 GB corpus (`autonomath.db`).
- **503,930 entities / 6.12M facts / 378,342 relations / 14,596 amendment snapshots**.
- **Evidence Packet** (`source_url + fetched_at + content_hash`) on every tool response.
- **8-statute fence** prevents the server from emitting individual tax / legal advice (Tax Accountant Act §52, Attorney Act §72, Certified Public Accountants Act §47-2, Administrative Scrivener Act §1, Judicial Scrivener Act §3, Labor and Social Security Attorney Act §27, Patent Attorney Act §75, Labor Standards Act §36).
- Fly.io Tokyo + Cloudflare edge + Stripe metered billing.
- Anonymous tier: **3 req/IP/day** via `AnonIpLimit` gate, JST midnight reset (no API key needed to try the playground).

SQLite is chosen because the data shape is read-heavy / bulk-updated monthly / single-binary deployable / FTS5 trigrams hit p50 50ms on a 9.4 GB mmap-resident corpus.

## Quickstart — 4 surfaces, 5 minutes each

### Claude Code

```bash
claude mcp add jpcite -- uvx autonomath-mcp
```

The 151 tools enumerate immediately in the tool picker. `/mcp` to verify connection, `/tools` to list, `/usage jpcite` to check this month's metered total.

### Cursor

```bash
mkdir -p .cursor && curl -O -L https://jpcite.com/.cursor/mcp.example.json
mv mcp.example.json .cursor/mcp.json
```

Drop in project root for team-wide sharing, or `~/.cursor/mcp.json` for user-wide.

### ChatGPT Custom GPTs

In Custom GPT settings → `Add actions` → `Import from URL`:

```
https://jpcite.com/openapi.agent.gpt30.json
```

A 30-path slim subset (GPT Actions limit) covering the most-used corpora. Auth = `X-API-Key` header with a `jc_xxx` key.

### OpenAI Agents SDK / Codex

```python
from agents import Agent, hosted_mcp

mcp = hosted_mcp(server_url="https://api.jpcite.com/mcp")
agent = Agent(name="jp_subsidy", tools=mcp.list_tools())  # 151 tools immediately
```

`hosted_mcp` covers tool discovery / call / response. Auth via header injection.

## Five product surfaces

1. **Company folder builder** — One corporation number → baseline + adoption history + enforcement + invoice status + related laws. 18 req per pack (≈ ¥54). Replaces 2–3 hours of manual cross-referencing for M&A pre-DD or new-counterparty KYC.
2. **Monthly client review (tax accountant fan-out)** — 100 clients × monthly = ¥300/month (≈ USD 2). Watch for invoice-registration cancellations, new enforcement cases, adoption results. Fans out as one batch on the first of the month.
3. **Intake evidence triage** — 1000 inquiries triaged = ¥48,000/month. From an inquirer's corporate name, fetch baseline + industry + size in 3 req for routing.
4. **M&A public-info DD** — 1 corporation = ¥141 (47 req). 6-source corporate + 5-year enforcement history + invoice-status timeline + adoption record + related laws + interlocking directorships, into one DD report. Replaces the FA / audit-firm first-screening pass.
5. **Pre-consultation diagnostic** — 50 inquiries = ¥1,200 (400 req). Tax accountants / administrative scriveners / labor consultants pre-fetch the client's public state in 8 req before the first call, so meetings shift from "hearing 50% / advice 80%" instead of "hearing 80% / advice 20%".

## Pricing

- **¥3/req** fully metered (≈ USD 0.02, JP-inclusive ¥3.30)
- **3 req/IP/day free** for anonymous (no API key needed)
- Stripe Checkout in 1 minute issues an API key
- No monthly minimum, cancel from dashboard with 1 click
- Qualified invoices (T8010001213708) auto-issued monthly for Japanese-corporate clients

## Data sources & licenses

- **NTA Qualified Invoice Issuer list**: PDL v1.0 (API redistribution permitted with attribution, confirmed 2026-04-24 direct ToS)
- **e-Gov laws**: CC-BY-4.0 (full text + amendment history + enforcement dates)
- **METI / SME Agency / ministry subsidies**: Government Standard Terms of Use v2.0
- **gBizINFO**: gBizINFO terms (METI)
- **Administrative dispositions**: each ministry's public-info posting (attribution required)

Every API response includes `meta.license` so downstream agents can auto-cite.

## Anti-hallucination by construction

The **Evidence Packet** isn't optional. Every MCP tool response carries:

```json
{
  "result": { ... },
  "evidence": {
    "source_url": "https://www.chusho.meti.go.jp/keiei/sapoin/...",
    "fetched_at": "2026-05-08T03:14:21+09:00",
    "content_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  "meta": { "license": "gov_standard_v2", "tool_count_at_call_time": 151 }
}
```

If the upstream source is gone, the `content_hash` is stale, and the agent can refuse to surface the fact. No silent fabrication.

## Links

- Site: https://jpcite.com
- Playground (3 req/IP/day free): https://jpcite.com/playground
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: `pip install autonomath-mcp==0.4.0`
- Contact: info@bookyou.net (Bookyou Co., Ltd., qualified-invoice issuer T8010001213708, Tokyo)

I'd love feedback on the Evidence Packet design — does the `content_hash` field feel like the right hook for agent-side staleness detection, or should I expose a separate `last_verified_at` even when our cron hasn't re-fetched yet?
