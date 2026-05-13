# Cursor Marketplace — Submission Pack

**Submit to**: <https://cursor.com/marketplace> (and/or the Cursor IDE plugin-submission flow)
**Method**: Web form (Cursor team curation)
**Estimated review time**: 7–14 days (manual review)
**Status**: DRAFT — do NOT submit

---

## Pre-flight

- [ ] Confirm the current submission flow on `https://cursor.com/marketplace` — Cursor sometimes routes to a Typeform or to a GitHub issue. Adjust the wording below if the form asks different fields.
- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] Tested the server inside Cursor locally (Cursor → Settings → MCP → add `uvx autonomath-mcp`) and captured a screenshot of the tool list rendering 151 tools

---

## Form fields — exact text to paste

### Plugin / extension name

```
AutonoMath
```

### Slug (if asked)

```
autonomath-mcp
```

### Type

```
MCP server
```

### Repository URL

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

### Tagline (~80 chars)

```
151-tool MCP for Japanese institutional data — subsidies, laws, court, tax, invoice
```

### Short description (~160 chars)

```
Search 11,601 subsidies + 6,493 laws full-text indexed + 2,065 court decisions + 13,801 invoice registrants from Cursor. 151 MCP tools, primary-source URLs, ¥3/billable unit (¥3.30 tax-incl), 3/day free anon.
```

### Long description

```
AutonoMath exposes Japanese institutional public data via 151 MCP tools at default gates (protocol 2025-06-18, stdio). Drop it into Cursor and ask: 「東京都の農業 DX 補助金を期日順に教えて」or「houjin_bangou=… の DD プロファイルと適格事業者登録を確認して」.

Coverage: 11,601 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 loan products with 3-axis guarantor decomposition (担保 / 個人保証人 / 第三者保証人) + 1,185 行政処分 + 6,493 laws full-text indexed + 9,484 law metadata records (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 50 tax rulesets + 13,801 国税庁 qualified-invoice registrants (PDL v1.0) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue: trace_program_to_law / find_cases_by_law / combined_compliance_check.

Major public rows carry source_url + fetched_at where available; known aggregator sources are excluded where detected. ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) fully metered, first 3 requests/day per IP free (anonymous, JST next-day reset), no tier SKUs.

Disclaimer (税理士法 §52 fence): information retrieval only. Does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1), or 労務判断 (社労士法).
```

### Install snippet — Cursor MCP config (paste into Cursor → Settings → MCP)

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

### Alternative install

```
pip install autonomath-mcp
```

### Categories (pick what Cursor's form lists)

```
Productivity
Search
Reference
Government / Legal / Finance (if available)
```

### Tags / keywords (free text)

```
mcp, japan, japanese, government, subsidies, grants, loans, tax, laws, court-decisions, invoice, primary-source, compliance, due-diligence, 補助金, 融資, 税制
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

### Tool count (if asked)

```
151 at default gates. Source of truth: tools/list at runtime.
```

### Pricing

```
¥3/billable unit tax-exclusive (¥3.30 tax-inclusive, fully metered). First 3 requests/day per IP free (anonymous, JST next-day reset). No tier SKUs, no seat fees, no annual minimums, no signup required for anonymous checks.
```

### Author / publisher

```
Bookyou株式会社 (T8010001213708)
代表 梅田茂利
info@bookyou.net
```

### Contact email

```
info@bookyou.net
```

### Privacy policy URL

```
https://jpcite.com/privacy
```

### Terms of Service URL

```
https://jpcite.com/tos
```

### Screenshots (Cursor often asks for 1–3)

```
1. cursor-screenshot-tool-list-139.png — Cursor settings showing the 151 tools loaded under the AutonoMath server
2. cursor-screenshot-search-programs.png — Cursor chat using search_programs to find 東京都 農業 DX 補助金
3. cursor-screenshot-trace-program-to-law.png — Cursor chat using trace_program_to_law to surface the statutory basis of a chosen program
```

### Logo / icon

```
512×512 PNG: site/static/icons/autonomath-icon-512.png
1200×630 OG: site/static/og/autonomath-og-1200x630.png
```

### "Anything else?"

```
- 79-query gold-standard public eval suite at evals/ runs in CI on every PR; per-tool precision in docs/per_tool_precision.md.
- Honest tool count = 151 at default gates. Older snapshots ("55", "59", "66", "72") may appear in historical files and should be ignored.
- 4 broken tools are deliberately gated OFF (query_at_snapshot, intent_of, reason_answer, related_programs) — they remain in code so a fix re-enables them without a manifest bump.
- Evidence Pre-fetch / precomputed intelligence prepares source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins for retrieval; describe it as evidence packaging, not as model-cost savings.
- major public rows include primary-source URL lineage; aggregator domains banned.
```

---

## §52 disclaimer fence (also in long description; restated here)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## After-submit checklist

- [ ] Save the submission ID / confirmation email.
- [ ] Watch for a Cursor team email asking for additional info — they sometimes request a quick demo video.
- [ ] If accepted, verify the listing at `https://cursor.com/marketplace/<slug>` and update homepage copy with the listing badge.
