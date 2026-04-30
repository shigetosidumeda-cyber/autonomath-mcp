# mcp.so — Submission Pack

**Submit to**: <https://mcp.so/submit>
**Method**: Web form (and/or GitHub issue at the mcp.so source repo)
**Estimated review time**: 1–7 days (manual or semi-automatic curation; high-traffic directory)
**Status**: DRAFT — do NOT submit

---

## Pre-flight

- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] README.md renders the install snippet and the `mcpServers` JSON

---

## Form fields — exact text to paste

### Server name

```
AutonoMath
```

### Slug (if requested)

```
autonomath-mcp
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

### Short description (~1 line, ~140 chars)

```
93 MCP tools over Japanese institutional data: 10,790 subsidies + laws + court + tax + invoice registrants. ¥3/req (¥3.30 tax-incl). 3/day free anon.
```

### Long description (4–8 sentences)

```
AutonoMath exposes Japanese institutional public data via 93 MCP tools at default gates (protocol 2025-06-18, stdio). Coverage: 10,790 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 loan products with 3-axis 担保/個人保証人/第三者保証人 decomposition + 1,185 行政処分 + 154 laws indexed full-text + 9,484 law catalog stubs (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 35 tax rulesets + 13,801 国税庁 qualified-invoice registrants (PDL v1.0 delta) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue: trace_program_to_law / find_cases_by_law / combined_compliance_check. Every row carries source_url + fetched_at; aggregator domains are banned. Pricing: ¥3/req tax-exclusive (¥3.30 tax-inclusive) fully metered, first 3 requests/day per IP free (anonymous, JST next-day reset), no tier SKUs.

Disclaimer (税理士法 §52 fence): AutonoMath is information retrieval, not advice. It does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1), or 労務判断 (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.
```

### Category / tags (whatever mcp.so accepts)

```
Categories: government, legal, finance, compliance, search
Tags: japan, japanese, subsidies, grants, loans, tax, laws, court-decisions, invoice, primary-source, compliance, due-diligence, mcp-2025-06-18, stdio, python, 補助金, 助成金, 融資, 税制
```

### Install command (rendered in the listing's "Quick start")

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
93 (at default gates). 4 additional tools gated off pending fix; 2 further tools held behind AUTONOMATH_36_KYOTEI_ENABLED for 社労士法 review. tools/list is the source of truth.
```

### License

```
MIT
```

### Language / runtime

```
Python >= 3.11
```

### MCP protocol version

```
2025-06-18
```

### Transport

```
stdio
```

### Pricing

```
¥3/request tax-exclusive (¥3.30 tax-inclusive, fully metered via Stripe). First 3 requests/day per IP free (anonymous, JST next-day reset). No tier SKUs, no seat fees, no annual minimums, no signup required for the free tier.
```

### Operator / publisher

```
Bookyou株式会社 (T8010001213708)
代表 梅田茂利
info@bookyou.net
```

### Contact email

```
info@bookyou.net
```

### Logo / OG image

```
1200×630 OG image: site/static/og/autonomath-og-1200x630.png
Square 512 icon: site/static/icons/autonomath-icon-512.png
```

### "Anything else?" / notes to reviewer

```
Honest counts (verified 2026-04-29 audit, v0.3.2):
- 93 tools at default gates (4 additional gated off pending fix: query_at_snapshot, intent_of, reason_answer, related_programs)
- 154 laws full-text indexed; 9,484 law catalog stubs (full-text load incremental)
- 4,300 sourced compatibility pairs (status='confirmed'); 44,515 heuristic inferences are flagged status='unknown' and never surfaced as truth
- 99%+ of rows carry source_url + fetched_at
- Aggregator domains (noukaweb, hojyokin-portal, biz.stayway) are banned from source_url
- Evidence Pre-fetch / precomputed intelligence prepares source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins for retrieval; describe it as evidence packaging, not as model-cost savings.

Earlier strings of "55 tools" / "59 tools" / "66 tools" / "72 tools" / "11,547 programs" / "424,054 entities" exist in some downstream files as historical state markers and should be ignored when listing.
```

---

## Optional: GitHub issue alternative

If mcp.so's web form is unavailable, the same content can be filed as an issue on the mcp.so source repository (find via the `submit` page footer). Use the long description above as the issue body, prefix the title with:

```
[Server submission] AutonoMath — 93-tool MCP for Japanese institutional data
```

---

## §52 disclaimer fence (must appear in the long description above; restated here)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## After-submit checklist

- [ ] Save the submission timestamp / response email.
- [ ] Verify the listing at `https://mcp.so/server/<slug>` once propagated.
- [ ] If the listing renders the wrong number of tools, re-submit with the audited 93 figure.
