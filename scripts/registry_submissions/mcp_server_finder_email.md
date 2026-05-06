# MCP Server Finder — Submission Email

**Submit to**: <info@mcpserverfinder.com>
**Method**: Plain-text email (curator-managed)
**Estimated review time**: 3–14 days (manual, variable)
**Status**: DRAFT — do NOT send

---

## Pre-flight

- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] Send from `info@bookyou.net` (operator email, matches the publisher field on every other registry)

---

## Email — copy-paste exactly

### To

```
info@mcpserverfinder.com
```

### From

```
info@bookyou.net
```

### Subject

```
[Server submission] AutonoMath — 139-tool MCP for Japanese institutional data (補助金 / 法令 / 判例 / 税制 / 適格事業者)
```

### Body

```
Hi MCP Server Finder team,

I'd like to submit AutonoMath for inclusion in your directory.

----- Quick facts -----

Name:               AutonoMath
GitHub:             https://github.com/shigetosidumeda-cyber/autonomath-mcp
Homepage:           https://jpcite.com
Docs:               https://jpcite.com/docs/
PyPI package:       autonomath-mcp (v0.3.2)
License:            MIT
Language:           Python (>= 3.11)
MCP protocol:       2025-06-18
Transport:          stdio
Install:            uvx autonomath-mcp
Tool count:         139 at default gates
Pricing:            ¥3/request tax-exclusive (¥3.30 tax-inclusive, fully metered via Stripe); first 3 requests/day per IP free (anonymous, JST next-day reset); no tier SKUs, no seat fees, no annual minimums, no signup required for the free tier.
Operator:           Bookyou株式会社 (T8010001213708) — 代表 梅田茂利 — info@bookyou.net

----- What it does -----

AutonoMath exposes Japanese institutional public data via MCP tools, with primary-source URLs on major public rows. Coverage:

- 11,684 searchable programs (補助金 / 融資 / 税制 / 認定; tier S=114, A=1,340, B=3,292, C=6,044; full table incl. tier X quarantine = 14,472)
- 2,286 採択事例 (adoption case studies)
- 108 loan products with 3-axis guarantor decomposition (担保 / 個人保証人 / 第三者保証人)
- 1,185 行政処分 records (administrative enforcement)
- 154 laws indexed full-text + 9,484 law catalog stubs (e-Gov CC-BY; full-text load is incremental, name resolver covers all 9,484)
- 2,065 court decisions
- 362 bids (GEPS + 47 都道府県)
- 50 tax rulesets (インボイス + 電帳法)
- 13,801 国税庁 qualified-invoice registrants (PDL v1.0 delta-only, redistributable with attribution)
- 4,300 sourced compatibility pairs (am_compat_matrix status='confirmed'; the additional 44,515 heuristic inferences are flagged status='unknown' and never surfaced as truth)
- 181 exclusion / prerequisite rules

Cross-dataset glue tools tie programs to statutes, statutes to court decisions, and stack tax / bid / law / case lookups in one call (trace_program_to_law / find_cases_by_law / combined_compliance_check). Aggregator domains (noukaweb, hojyokin-portal, biz.stayway) are banned from source_url to mitigate fraud risk on credit / DD use cases.

----- Claude Desktop config -----

{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}

----- Categories -----

Primary: Government, Legal, Finance
Tags:    japan, japanese, subsidies, grants, loans, tax, laws, court-decisions, invoice, primary-source, compliance, due-diligence, 補助金, 助成金, 融資, 税制

----- Disclaimer (税理士法 §52 fence; please render this if your listing has a disclaimer field) -----

AutonoMath is an information-retrieval service over published Japanese primary sources. It does NOT perform:

- Legal advice (弁護士法 §72)
- Tax advice or filing representation (税理士法 §52)
- Application representation (行政書士法 §1)
- Labour determinations (社労士法)

Search results are snapshots at fetch time; rates / sunset dates / authorities are subject to change. Verify primary-source URLs and consult licensed professionals for individual cases.

----- Logo / images -----

I can supply a 512×512 PNG icon and a 1200×630 OG image on request — please reply and I'll attach them. Alternatively, both are available at:
- https://jpcite.com/static/icons/autonomath-icon-512.png
- https://jpcite.com/static/og/autonomath-og-1200x630.png

----- Anything else -----

- 79-query public eval suite (evals/) runs in CI on every PR; per-tool precision table in docs/per_tool_precision.md.
- 4 broken tools (query_at_snapshot, intent_of, reason_answer, related_programs) are deliberately gated OFF — they remain in the codebase so a fix flips them ON without a manifest bump.
- Honest tool count is 139 at default gates. Older snapshots ("55", "59", "66", "72") may appear in historical files; please ignore those when listing.
- Evidence Pre-fetch / precomputed intelligence prepares source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins for retrieval; describe it as evidence packaging, not as model-cost savings.

Happy to provide additional info if helpful — feel free to reply directly.

Thanks,
梅田茂利
代表 / Founder
Bookyou株式会社 (T8010001213708)
info@bookyou.net
https://jpcite.com
```

---

## §52 disclaimer fence (also in body; restated here)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## After-send checklist

- [ ] Save the email and capture the message-id / sent timestamp.
- [ ] Tag the email thread for "MCP listing follow-up" so a reply can be answered within 24h.
- [ ] If no response in 14 days, send a polite single-line follow-up.
- [ ] When the listing goes live, capture the URL and add it to the homepage badge row.
