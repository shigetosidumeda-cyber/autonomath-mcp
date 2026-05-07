# Anthropic External Plugin Directory — Submission Pack

**Submit to**: <https://clau.de/plugin-directory-submission>
**Method**: Web form (Anthropic-hosted)
**Estimated review time**: 1–3 weeks (Anthropic curation)
**Status**: DRAFT — do NOT submit

---

## Pre-flight

- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] DXT bundle `autonomath-mcp.mcpb` is downloadable from `https://jpcite.com/downloads/autonomath-mcp.mcpb`
- [ ] Verify the form's current field names against the live page before pasting (Anthropic updates the form periodically)

---

## Form fields — exact text to paste

### Plugin name

```
AutonoMath
```

### Plugin slug / identifier (if asked)

```
autonomath-mcp
```

### Plugin type

```
MCP server (external)
```

### Short description (160 characters max)

```
Search Japanese institutional data: 11,601 subsidies + 6,493 laws full-text indexed + 2,065 court decisions + 13,801 invoice registrants. 139 MCP tools. ¥3/billable unit (¥3.30 tax-incl). 3/day free anon.
```

(Length: 156 characters.)

### Long description (500–800 characters)

```
AutonoMath exposes Japanese institutional public data via 139 MCP tools at default gates (39 core + 50 autonomath at runtime, protocol 2025-06-18, stdio): 11,601 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 融資 (担保 / 個人保証人 / 第三者保証人 三軸分解) + 1,185 行政処分 + 6,493 laws full-text indexed + 9,484 law metadata records (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 50 tax rulesets + 13,801 国税庁 適格事業者 (PDL v1.0) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue: trace_program_to_law / find_cases_by_law / combined_compliance_check. Major public rows carry source_url + fetched_at; aggregator-only rows are excluded from public sourcing. ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive), 3 req/day per IP free (anonymous, JST next-day reset). Information retrieval only — not 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1), or 労務判断 (社労士法).
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

### License

```
MIT
```

### Programming language

```
Python (>= 3.11)
```

### Runtime / install command

```
uvx autonomath-mcp
```

### Alternative install (pip)

```
pip install autonomath-mcp && autonomath-mcp
```

### MCP protocol version

```
2025-06-18
```

### Transport

```
stdio
```

### Number of tools (if asked)

```
139 (at default gates; tools/list is the source of truth)
```

### Categories / tags (multi-select; pick the ones the form lists)

Likely matches on the form:
```
Government
Legal
Finance
Compliance
Search
Japan / Japanese
```

### Free-text tags

```
japan, japanese, government, subsidies, grants, loans, tax, laws, court-decisions, compliance, due-diligence, primary-source, mcp-2025-06-18, stdio, python, 補助金, 助成金, 融資, 税制, 採択事例, 行政処分, インボイス
```

### Pricing model

```
Pay-per-request: ¥3 per request (税込 ¥3.30, fully metered via Stripe). Anonymous tier: first 3 requests/day per IP free (JST next-day reset, no signup). No subscription tiers, no seat fees, no annual minimums.
```

### Privacy / data handling

```
- API receives only the request payload (search query, filters, IDs).
- No PII collection beyond billing email if the user upgrades to a metered API key.
- No third-party tracking pixels or analytics SDKs in the API surface.
- Privacy policy: https://jpcite.com/privacy
- Terms of Service: https://jpcite.com/tos
- 特定商取引法 disclosure: https://jpcite.com/tokushoho
```

### Operator / publisher

```
Bookyou株式会社
適格請求書発行事業者番号: T8010001213708
適格請求書発行事業者番号: T8010001213708
代表: 梅田茂利
連絡先: info@bookyou.net
所在地: 東京都文京区小日向2-22-1
```

### Contact email

```
info@bookyou.net
```

### Support URL (if asked)

```
https://github.com/shigetosidumeda-cyber/autonomath-mcp/issues
```

### Demo / example prompts (if asked)

Paste each as a separate example:

1. ```
   農業に使える東京都の補助金を教えて。期日が近い順で。
   ```
2. ```
   houjin_bangou=1010001012345 の DD プロファイルを取得して、行政処分と適格事業者登録を確認して。
   ```
3. ```
   電子帳簿保存法の改正動向と、関連する判例を併せて返して。
   ```
4. ```
   創業 3 年の IT 企業が併用できる補助金 + 融資 + 税制の組み合わせを、排他ルール込みで提案して。
   ```

### Required disclaimer / legal notice (paste exactly — §52 fence)

```
AutonoMath is an information-retrieval service over published Japanese primary sources (e-Gov, ministries, prefectures, 日本政策金融公庫, 国税庁, 裁判所). It does NOT provide:
- Legal advice (弁護士法 §72)
- Tax advice or filing representation (税理士法 §52)
- Application representation (行政書士法 §1)
- Labour determinations (社労士法)

Search results are snapshots at fetch time; rates / sunset dates / authorities are subject to change. Verify primary-source URLs and consult a licensed professional for individual cases.
```

### Content rating / audience

```
Developers building Claude / Claude Code agents that need authoritative Japanese institutional data with primary-source lineage. Suitable for general business use; not consumer-facing.
```

### Logo / icon (if upload required)

```
File: site/static/og/autonomath-og-1200x630.png (existing OG image)
Square variant: site/static/icons/autonomath-icon-512.png (if needed)
```

### Screenshots (if asked)

```
1. Claude Desktop tool-call demo: search_programs with prefecture=東京都, q=農業
2. Tool list (139 tools enumerated)
3. Cross-dataset glue example: trace_program_to_law output with law_id + article
```

### Anything else to share?

```
- Public 79-query gold-standard eval suite at evals/ runs in CI on every PR.
- Per-tool precision table at docs/per_tool_precision.md.
- major public rows carry source_url + fetched_at (12 rows lack URL because the originating small-municipality CMS has no dedicated page).
- 4 broken tools are gated OFF (not stripped) so a fix can flip them back ON without a manifest bump.
- Evidence Pre-fetch / precomputed intelligence prepares source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins for retrieval; describe it as evidence packaging, not as model-cost savings.
- Fully metered ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) with no tiers reflects a deliberate solo-operator + zero-touch ops policy.
```

---

## After-submit checklist

- [ ] Save the submission ID returned by the form.
- [ ] Capture a screenshot of the confirmation page.
- [ ] Update `scripts/registry_submissions/README.md` with the submission ID and date.
- [ ] If accepted: cross-check the listing at the directory URL, fix any rendering issues, and link from the homepage.
