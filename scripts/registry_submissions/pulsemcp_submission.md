# PulseMCP — Submission Pack

**Submit to**: <https://www.pulsemcp.com/submit>
**Method**: Web form (also auto-ingests the Official MCP Registry — direct form is for corrections / expedited listing)
**Estimated review time**: 7 days (weekly batch, hand-reviewed by founder); auto-ingest path can be faster if the official-registry entry is live
**Status**: DRAFT — do NOT submit

---

## Pre-flight

- [ ] Confirmed an entry has NOT already auto-ingested from the Official MCP Registry. If it has, use the form to correct fields, do not double-submit.
- [ ] PyPI package `autonomath-mcp` v0.3.1 is published
- [ ] Public repo `github.com/shigetosidumeda-cyber/jpintel-mcp` is live and renders the README

---

## Form fields — exact text to paste

### Server name

```
AutonoMath
```

### GitHub URL

```
https://github.com/shigetosidumeda-cyber/jpintel-mcp
```

### Homepage / website URL

```
https://jpcite.com
```

### Documentation URL

```
https://jpcite.com/docs/
```

### Short description (1 sentence; PulseMCP renders this in the listing card)

```
68 MCP tools over Japanese institutional data — subsidies, laws, court decisions, tax rulesets, invoice registrants — with primary-source URLs on 99%+ of rows.
```

### Long description (paragraph; PulseMCP renders this on the detail page)

```
AutonoMath exposes Japanese institutional public data via 68 MCP tools at default gates (protocol 2025-06-18, stdio): 10,790 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 loan products with 3-axis guarantor decomposition (担保 / 個人保証人 / 第三者保証人) + 1,185 行政処分 + 154 laws indexed full-text + 9,484 law catalog stubs (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 35 tax rulesets + 13,801 国税庁 qualified-invoice registrants (PDL v1.0 delta) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue tools tie programs to statutes, statutes to court decisions, and stack tax / bid / law / case lookups in one call. Every row carries source_url + fetched_at and aggregator domains are banned. Pricing: ¥3.30/req (税込) fully metered, first 50 requests/month free per IP (anonymous, JST monthly reset), no tier SKUs.

Disclaimer (税理士法 §52 fence): AutonoMath is information retrieval, not advice. It does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1), or 労務判断 (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.
```

### Categories (pick from PulseMCP's list)

```
Government
Legal
Finance
Compliance
Search
```

### Tags (free text)

```
japan, japanese, government, subsidies, grants, loans, tax, laws, court-decisions, invoice, e-gov, primary-source, compliance, due-diligence, mcp-2025-06-18, stdio, python, 補助金, 助成金, 融資, 税制
```

### License

```
MIT
```

### Language

```
Python
```

### Install command (the value PulseMCP renders in copy-paste blocks)

```
uvx autonomath-mcp
```

### Alternate install

```
pip install autonomath-mcp
```

### Claude Desktop config (PulseMCP often wants this verbatim)

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
68 at default gates (4 additional tools gated off pending fix: query_at_snapshot, intent_of, reason_answer, related_programs; 2 further tools held behind AUTONOMATH_36_KYOTEI_ENABLED for 社労士法 review)
```

### Pricing

```
¥3.30 per request (税込, fully metered via Stripe). First 50 requests/month free per IP (anonymous, JST monthly reset). No tier SKUs, no seat fees, no annual minimums.
```

### Author / publisher

```
Bookyou株式会社 (T8010001213708) — info@bookyou.net
```

### Contact email

```
info@bookyou.net
```

### Logo (if upload required)

```
File: site/static/og/autonomath-og-1200x630.png
Square variant if needed: site/static/icons/autonomath-icon-512.png
```

### Screenshots / demo (if optional)

```
1. search_programs result for 「東京都 農業 補助金」
2. trace_program_to_law output with statutory basis
3. dd_profile_am output keyed by houjin_bangou
```

### "Anything else?" / notes to reviewer

```
- Honest tool count is 68 at default gates. Earlier listings of "66" or "72" reflect older snapshots (manifest bumps on 2026-04-25 and v0.3.1 audit on 2026-04-29).
- 4 tools (query_at_snapshot, intent_of, reason_answer, related_programs) are deliberately gated OFF after a smoke test caught underlying schema/package gaps. They are kept in the codebase so a fix flips them ON without a manifest bump.
- Honest data counts:
  - 154 laws full-text (incremental load); 9,484 catalog stubs cover the long tail name-resolver-only.
  - 4,300 sourced compatibility pairs (am_compat_matrix status='confirmed'). 44,515 heuristic inferences are flagged status='unknown' and not surfaced as truth.
  - 99%+ of rows carry source_url + fetched_at; 12 rows lack URL because the originating municipal CMS has no dedicated page.
- Aggregator domains (noukaweb / hojyokin-portal / biz.stayway) are banned from source_url to mitigate fraud risk on credit / DD use cases.
```

---

## §52 disclaimer (must appear in the long description above; restated here for the maintainer)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## After-submit checklist

- [ ] Save the submission timestamp / email confirmation.
- [ ] Verify within 7 days at <https://www.pulsemcp.com/servers/autonomath> (or the slug PulseMCP assigns).
- [ ] If listing fields are wrong, re-submit the form with corrections (PulseMCP supports update via the same form).
