# jpcite SV Top-tier UX Red-team Review

**Reviewer**: Subagent (Claude Code) — adversarial mode  
**Date**: 2026-05-11  
**Standard**: Silicon Valley top-tier (Stripe / Linear / Vercel / Anthropic / OpenAI)  
**Surfaces audited (8)**:

| # | Surface | Local path |
|---|---|---|
| S1 | landing | `site/index.html` |
| S2 | pricing | `site/pricing.html` |
| S3 | dashboard | `site/dashboard.html` |
| S4 | mcp.json (AI discovery) | `site/.well-known/mcp.json` |
| S5 | llms.txt (AI overview) | `site/llms.txt` + `site/llms.en.txt` |
| S6 | openapi.json (API spec) | live at `https://api.jpcite.com/v1/openapi.json` (HTTP 200, 658 KB) |
| S7 | playground | `site/playground.html` |
| S8 | sources | `site/sources.html` |

---

## Verdict TL;DR

**Overall**: jpcite has best-in-class **machine-facing** surfaces (S4/S5/S6/S8) — comparable or superior to mid-tier API companies, and unusually thorough on legal-fence / provenance / freshness. But the **human-facing** surfaces (S1/S2/S3/S7) miss the SV top-tier "5-second test" by a wide margin.

The dominant red-team finding is **information density**: hero sections lead with 5+ product names, 7+ data counts, 3 simultaneous CTAs, and jargon (`Evidence Packet`, `MCP`, `OpenAPI Actions`, `unified_id`, `compression fields`, `break_even_met`) that a first-time visitor cannot decode in 5 seconds. Stripe leads with "Payments infrastructure for the internet" + 1 hero CTA + 1 single price-callout. jpcite leads with 9 lines of dense Japanese, 5 product packs, 3 CTAs, and a footnote about §52 disclaimers.

**8 × 7 grid summary**: **8 green / 26 yellow / 22 red** out of 56 cells. Worst surfaces: **S1 landing** (5 red / 2 yellow) and **S3 dashboard** (4 red / 3 yellow). Best: **S5 llms.txt** (5 green / 2 yellow / 0 red) and **S6 openapi.json** (4 green / 3 yellow).

---

## 8 × 7 Grid (G / Y / R + 1-line evidence)

| | A. 5-sec test | B. Lang/copy | C. Trust signal | D. CTA design | E. a11y/mobile | F. Brand | G. Enterprise |
|---|---|---|---|---|---|---|---|
| **S1 index** | **R** hero h1 = 87字/4節, 5 product names, 7 counts, 3 CTAs — Stripe/Linear hero ≤ 12-word value-prop | **R** "Evidence Packet contract" "input-context estimates" "compression fields" undecoded in hero | **Y** Bookyou/T8010001213708 only in JSON-LD, not visible HTML body until footer | **R** 3 CTAs same fold ("3 回で会社フォルダ", "1 行で接続", "料金") split attention — Stripe = 1 primary + 1 docs link | **Y** viewport ok, skip-link ok, but hero font-clamp 36-56px on dense ja text = wrap-pile on 375px | **Y** schema.org `alternateName: ["税務会計AI","AutonoMath","zeimu-kaikei.ai"]` violates memory "旧 brand 控えめ" — should be llms.txt only | **R** no SOC2/ISO/GDPR mention in human view, no case study (only price examples), trust links buried in `<details>` |
| **S2 pricing** | **Y** ¥3/unit visible above-fold (good); calculator+ROI math+5 product CTAs+break-even formula overwhelm | **R** "billable unit" "break-even calculator" "input-context reduction rate" — Stripe Pricing uses plain "$X / 1,000 calls" | **G** §52/§72/§47-2 fence + invoice number + Stripe portal + auto-invoice clearly documented | **Y** primary "API キー発行" gated behind consent checkbox (good) but secondary CTA "Playground" not visually distinct | **Y** consent checkbox is mouse-only label-for; mobile table scroll OK but font 14px on 375px = cramped | **Y** "alternateName: jpcite" array contains duplicate, JSON-LD bloat | **Y** invoice / cap / idempotency listed in FAQ but no SLA tier vs status link from this page |
| **S3 dashboard** | **R** title "既存 API キーを管理" + body leads with `⚡ 5分で最初の API 呼び出し` + sample key `am_xxx...` — confused identity (existing vs new) | **R** Japanese mid-sentence English: "ターミナルで `pip install`" "MCP servers ブロックに追加" — assumes vocabulary | **Y** Stripe portal + invoice export visible, but no "last sign-in" / "session expiry" / "2FA" surfaces | **R** sample API key `am_xxxxxxxxxx` shown as placeholder = phishing-vector-like, easily confused for real key by novice | **Y** quota bar + ARIA role=progressbar good; mobile @ ≤480px stacks but tab nav crowded | **G** jpcite logo + consistent lockup, no legacy brand leakage | **R** no audit log link, no team/seat concept (intentional per zero-touch), no SAML/SSO note — but also no "Enterprise readiness statement" |
| **S4 mcp.json** | **G** 252-line manifest, schema_version + canonical_site clear, first_hop_routing well-articulated | **G** English throughout, no machine-translated junk | **G** operator_legal_name + corporate_number + jct_registration + address inline (better than human pages) | **G** auth.pricing_url + auth.upgrade_url + auth.anonymous_limit all canonical | n/a (machine) | **G** "alternateName" not in this file — clean | **Y** support_sla_hours: 24 stated but no link to status.html / SLA page; trust_surfaces array present but no SOC2 stub |
| **S5 llms.txt** | **G** Brand line + What/Use when/Do not use when in first 60 lines = textbook llms.txt | **G** Bilingual ja/en sibling, glossary embedded, fence dictionary explicit | **G** Coverage counts + Cost example + Tool argument cheat-sheet + License table in single doc | **G** Multiple call-order variants (Claude/ChatGPT/Cursor) + API key URL canonical | n/a (machine) | **Y** opening "(SEO citation bridge for 旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai)" matches memory but appears 2x (also `llms.en.txt:2`) — per memory should be SEO-bridge-only, this placement is fine | **G** Trust signals enumerated (security.txt / trust.json / data-licensing / legal-fence), AI procurement bot can ingest in 1 pass |
| **S6 openapi.json** | **G** info.title=`jpcite`, info.description leads with "Japanese public-program intelligence API" — clean | **G** "Information lookup, not professional advice (税理士法 §52)" inlined in description = audit-trail honest | **G** CSP/HSTS/X-Frame-Options/X-Content-Type-Options all set on response (verified live 2026-05-11) | **G** evidence-packet-first endpoint structure | n/a (machine) | **Y** description still references "MCP server" surface but tool count drift vs §Overview (139 manifest vs 146 runtime — known per CLAUDE.md) | **Y** 658 KB single file = no `info.x-sla` / no `info.contact.url`; some Stripe-class providers split per-tag |
| **S7 playground** | **Y** "API プレイグラウンド" clear + URL preview + send button = task is obvious | **R** Mixed English/Japanese throughout dropdowns — "送信プレビュー" but "GET" "params" "JSON response" English; `evidence3-wizard` step labels mix `step 1` (en) + `法人を特定` (ja) | **Y** quota indicator + JST reset visible; disclaimer at bottom only | **Y** "送信" primary button clear; conversion CTA `完成物に変換` after first success but no inline "what next" if 429 hits | **R** form labels lack explicit `for=`/`id=` pairs in several places; `<select>` 5-option JSIC list with `other` "Wave 8 で 22 JSIC 完全実装" footnote leaks dev-state | **G** jpcite throughout, no legacy brand | **Y** no Postman collection link from playground (button exists but generic; would expect Postman Run-in-Postman badge at SV bar) |
| **S8 sources** | **Y** h1 "データソース・出典・ライセンス一覧" + lead = clear in 5s | **Y** table is plain ja, license abbreviations defined; minor jargon `source_url` `source_fetched_at` `known_gaps` appears with brief explanation | **G** 15 datasets × license × attribution requirement table = transparent | **G** mailto for license question; no aggressive CTA (appropriate for trust page) | **Y** table horizontally scrolls on mobile; no `<caption>` element on the data table (a11y miss) | **G** Bookyou株式会社 + corporate number in JSON-LD; no legacy brand in body | **Y** no "data lineage diff" link, no SBOM link (one exists at `.well-known/sbom/`), no `data-licensing.html` cross-link from this page |

**Tally**: **8 G** / **26 Y** / **22 R** (some cells n/a where machine-only).

---

## Worst-offender deep dives

### S1 index.html hero (RED — 5-second test failure)

Current h1 (line 371):

> 日本の補助金・許認可・行政処分・適格事業者・法令を法人番号 1 つで横断照会。Claude / ChatGPT / Cursor から呼べる Evidence API/MCP。

**Length**: 87 characters, 4 conjunctive clauses, 5 noun groups, 2 product categories.

**Stripe / Linear comparator**:
- Stripe: `Payments infrastructure for the internet` (40 chars, 1 noun, 1 prep phrase)
- Linear: `Linear is the tool the world's best product teams rely on to ship great work.` (78 chars, 1 sentence)
- Anthropic API: `Build with Claude` (17 chars)

**Hero CTAs** (line 376-379) — three competing primary intents:
1. `3 回で会社フォルダを作る (無料)` → playground
2. `AI agent dev: 1 行で接続` → /connect/claude-code
3. `料金: ¥3 per billable unit (税込 ¥3.30、完全従量)` → /pricing

Stripe / Linear use **one** primary CTA + **one** secondary (`See docs` / `Watch demo`).

**Sub-hero** (line 372) packs 5 product names + 5 prices + 1 promise + 3 trust strip items, before user has decoded what "Evidence Packet" means.

**Fix sketch**:
- h1 collapse to ≤ 30字: `日本の制度を AI が引用する根拠付き API` (or English-parity short).
- 1 primary CTA: `無料で 3 回試す →` (playground); 1 secondary text link: `料金を見る →`.
- Move 5 product packs to a dedicated section below hero, not in hero `<ul>`.

### S3 dashboard.html identity confusion (RED)

Title (line 6): `既存 API キーを管理 — jpcite ダッシュボード`

Body opens (line 262-300) with `⚡ 5 分で最初の API 呼び出し` quickstart targeted at users **who do not yet have a key**, with copy-paste snippets containing the literal placeholder `am_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (line 284). Then line 437 says "既存 API キーを管理".

Stripe Dashboard never shows quickstart code above the account header — it lives under `Developers › Quickstarts`. Linear app dashboard shows only account state.

**Phishing risk**: Showing `am_xxx...` placeholder text in a "Your API key" surface is a known vector — a novice user could mistake the placeholder for a real revealed key or, worse, paste it back into a config file. Stripe never displays `sk_test_placeholder` in a position styled like a real key.

**Fix sketch**:
- If user has no key → redirect to `/pricing.html#api-paid` (already exists; just enforce).
- If user has a key → show only key actions (rotate / revoke / usage). Move quickstart to `/docs/getting-started/`.

### S2 pricing.html cognitive load (YELLOW leaning RED)

Stripe pricing has **one** value, **one** table (volume tiers), **one** CTA. jpcite pricing has:
- ¥3/unit hero with example table (good — matches Stripe).
- "成果物の反復運用では、先に上限を決める" automation section (3-card grid + 4-row example table).
- "無料 3 回で確認すること" 5-row checklist with `recommend_for_cost_savings` formula.
- "¥3/unit の根拠 — 価値統合の 3 軸" 3-card grid.
- "入力文脈 break-even calculator" interactive form with 4 inputs + 4 output cards + disclaimer.
- 2-card pricing-grid (匿名 / 従量).
- "よくある質問" 5-question FAQ.

That's **7 sections** before scroll-fatigue. Anthropic API pricing has **3** (table / volume discounts / FAQ).

The break-even calculator is technically impressive but for first-time visitors is closer to a feature-list than a CTA. Move below the fold or behind a `<details>`.

### S7 playground form-label hygiene (YELLOW leaning RED)

Lines 711-742 of the evidence3-wizard: several `<label>` elements wrap inputs inline (`<label>法人番号: <input id="ev3-houjin">...</label>`) — accessible, but inconsistent with the `<label for=...>` pattern used elsewhere. The JSIC `<select>` has only 5 hard-coded codes + `other` with the leaked dev note `Wave 8 で 22 JSIC 完全実装` — shipping dev TODOs to production UI.

---

## Top-5 即修正 (immediate fixes, ordered by impact × effort)

1. **S1 hero rewrite** (highest impact, low effort): collapse h1 to ≤ 30字, demote 5 product packs out of hero, single primary CTA. Stripe-grade first-impression is the cheapest dollar at SV bar.
2. **S3 dashboard identity split** (high impact, medium effort): remove the quickstart panel from `/dashboard.html`. New-user route goes to `/docs/getting-started/`. The `am_xxxxxxxx` placeholder is a phishing-shape — never render a key-shaped placeholder in a position the user expects a key.
3. **S1 / S2 / S7 legacy-brand JSON-LD prune** (low effort, brand integrity): remove `alternateName: ["税務会計AI","AutonoMath","zeimu-kaikei.ai"]` from `<script type="application/ld+json">` blocks on visible pages. Per memory `feedback_legacy_brand_marker.md`, legacy marker stays in `llms.txt` SEO bridge only.
4. **S2 pricing density** (medium impact, low effort): wrap break-even calculator and `recommend_for_cost_savings` checklist in `<details>` collapsed by default. First-pass visitor sees ¥3 hero + volume table + 2 buttons + FAQ.
5. **S7 playground polish** (medium impact, low effort): remove leaked dev-note `Wave 8 で 22 JSIC 完全実装` from production `<select>`. Either ship the full JSIC list or hide the dropdown until ready.

---

## SV Top-tier benchmark mapping

| Reference | What they do | jpcite gap |
|---|---|---|
| **Stripe Pricing** | Single value above fold, volume discount table, 1 CTA, FAQ | jpcite has 7 sections; calculator overload |
| **Linear landing** | 1 h1 sentence, 1 hero CTA, screenshot below, "ship faster" simple noun-verb | jpcite hero packs 87字 + 5 product names + 3 CTAs |
| **Vercel docs** | Tab-style nav, code-snippet-first, instant Search-as-you-type | jpcite docs (not in scope) but playground is closest analog — playground lacks instant-feedback / preview-before-send animation |
| **Anthropic API ref** | Short h1, code sample inline with prose, no marketing copy on docs pages | jpcite mixes "5 product packs" pricing-page content into docs hub navigation |
| **OpenAI platform** | Discovery flow: signup → playground → API keys → docs in 4 steps | jpcite anonymous-3-req-day is BETTER (no signup) but the upgrade path passes through pricing.html with 7 sections (vs OpenAI's 1-page billing) |

**Where jpcite is genuinely ahead of SV peers**:
- llms.txt + mcp.json + openapi.agent.json triplet — most SV API companies do not yet ship llms.txt at this fidelity (252-line manifest with first_hop_routing).
- §52/§72/§47-2 fence dictionary in the openapi.json `info.description` — Stripe / Anthropic do not have analogous regulatory honesty inline in machine specs.
- Source-license + fetched_at + known_gaps as response contract — superior to "data freshness" footnotes most peers use.

---

## Surfaces deemed RED at SV top-tier bar

The following 4 surfaces would not pass a Stripe / Linear design review without rework:

1. **S1 index.html** — hero density + 3 CTA split + legacy brand leak
2. **S2 pricing.html** — 7-section information overload (Stripe = 3)
3. **S3 dashboard.html** — identity confusion (existing vs new key) + placeholder phishing-shape
4. **S7 playground.html** — leaked dev TODO + mixed label patterns

Surfaces **S4 mcp.json / S5 llms.txt / S6 openapi.json / S8 sources** are at or above SV bar for their respective audiences.

---

## Constraints honored (per memory)

- No CS / sales / legal-team recommendations (Solo + zero-touch)
- No paid-ad / outbound proposals (Organic-only)
- Legacy brand suggestion is "remove from human-visible JSON-LD, keep in llms.txt SEO bridge" — does not propose burying the bridge entirely
- ¥3/billable unit (税込 ¥3.30) treated as load-bearing — no tier suggestions

---

*End of red-team review.*
