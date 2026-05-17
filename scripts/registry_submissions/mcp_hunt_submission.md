# MCP Hunt — Submission Pack

**Submit to**: <https://mcphunt.com> (the listing directory; web form)
**Companion site**: <https://mcp-hunt.com> (separate auto-crawl tool — no manual submit needed)
**Method**: Web form + community upvotes
**Estimated review time**: 1–3 days for listing; coordinate upvotes on launch day for visibility
**Status**: DRAFT — do NOT submit

---

## Important: dual URL caveat

`mcphunt.com` and `mcp-hunt.com` are different sites. We submit only to `mcphunt.com` (the curated directory). `mcp-hunt.com` auto-crawls public GitHub repos and does NOT take manual submissions; the public repo will appear there once it's published.

## Pre-flight

- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live with a usable README
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] Decided on launch-day timing for the upvote nudge (per memory: 2026-05-06 launch day)

---

## Form fields — exact text to paste

### Server name

```
AutonoMath
```

### One-line tagline (~100 chars)

```
155-tool MCP for Japanese institutional data — subsidies, laws, court decisions, tax rulesets, invoice registrants.
```

### Description (paragraph)

```
AutonoMath exposes Japanese institutional public data via 184 MCP tools at default gates (protocol 2025-06-18, stdio): 11,601 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 loan products with 3-axis 担保 / 個人保証人 / 第三者保証人 decomposition + 1,185 行政処分 + 6,493 laws full-text indexed + 9,484 law metadata records (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 50 tax rulesets + 13,801 国税庁 qualified-invoice registrants (PDL v1.0) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue: trace_program_to_law / find_cases_by_law / combined_compliance_check. Major public rows carry source_url + fetched_at; aggregator-only rows are excluded from public sourcing. ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) fully metered, first 3 requests/day per IP free (anonymous, JST next-day reset), no tier SKUs.

Disclaimer (税理士法 §52 fence): information retrieval only. Does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1の2), or 労務判断 (社労士法). Verify primary-source URLs and consult licensed professionals.
```

### GitHub URL

```
https://github.com/shigetosidumeda-cyber/autonomath-mcp
```

### Homepage URL

```
https://jpcite.com
```

### Documentation URL

```
https://jpcite.com/docs/
```

### Install command

```
uvx autonomath-mcp
```

### Pip alternative

```
pip install autonomath-mcp
```

### Claude Desktop config

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

### Tool count (if asked)

```
184 at default gates
```

### License

```
MIT
```

### Language

```
Python (>= 3.11)
```

### MCP protocol version

```
2025-06-18
```

### Transport

```
stdio
```

### Tags / keywords

```
japan, japanese, government, subsidies, grants, loans, tax, laws, court-decisions, invoice, e-gov, compliance, due-diligence, primary-source, mcp-2025-06-18, stdio, python, 補助金, 助成金, 融資, 税制
```

### Categories

```
Government
Legal
Finance
Compliance
Search
```

### Pricing

```
¥3 per request tax-exclusive (¥3.30 tax-inclusive, fully metered via Stripe). First 3 requests/day per IP free (anonymous, JST next-day reset). No tier SKUs, no seat fees, no annual minimums.
```

### Author / publisher

```
Bookyou株式会社 (T8010001213708) — 代表 梅田茂利 — info@bookyou.net
```

### Contact email

```
info@bookyou.net
```

### Logo / icon (if asked)

```
File: site/static/icons/autonomath-icon-512.png (512×512)
OG: site/static/og/autonomath-og-1200x630.png (1200×630)
```

### Submitter name

```
梅田茂利 (Bookyou株式会社)
```

### "Anything else?"

```
Honest figures verified 2026-04-29 (v0.3.2):
- 184 tools at default gates (4 broken tools gated off pending fix)
- 6,493 laws full-text indexed + 9,484 law metadata records (incremental full-text load)
- 4,300 sourced compatibility pairs (heuristic 44,515 inferences flagged status='unknown' and not surfaced as truth)
- major public rows carry source_url + fetched_at
- aggregator domains (noukaweb, hojyokin-portal, biz.stayway) banned from source_url
- Evidence Pre-fetch / precomputed intelligence prepares source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins for retrieval; describe it as evidence packaging, not as model-cost savings.
```

---

## §52 disclaimer fence (also in description; restated here)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1の2), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## Launch-day upvote coordination (2026-05-06)

- Post the listing link to operator's existing channels (X / Zenn / personal LinkedIn — no paid ads, organic only).
- Schedule 3–5 mutuals to upvote within the first hour after listing goes live.
- Do not solicit upvotes from anyone who hasn't tried the server — vanity upvotes from an empty audience get flagged and depress reach.

---

## After-submit checklist

- [ ] Save the listing URL once it goes live.
- [ ] Capture the listing screenshot for the homepage badge row.
- [ ] If `mcphunt.com` returns 404 or the form is offline, fall back to filing a GitHub issue at the project's source repo (find via the site footer).
- [ ] Confirm `mcp-hunt.com` (the auto-crawl tool) has indexed the GitHub repo within ~1 week. No manual action needed there.
