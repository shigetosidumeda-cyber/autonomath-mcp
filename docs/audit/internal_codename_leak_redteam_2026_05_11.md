# Internal Codename Leak — Red Team Scan (2026-05-11)

**Scope**: `site/` + `site/.well-known/` + `functions/` + `docs/{announce,recipes,connect}/`
**Lens**: Stripe / Linear / Vercel / OpenAI / Anthropic style guide.
**Exceptions whitelisted**: `jpcite` brand, `Bookyou株式会社` / `T8010001213708`, `info@bookyou.net`, `@autonomath/sdk` (npm pkg name), `autonomath-mcp` (PyPI pkg name), public API paths.

---

## Executive numbers

| Tier | Distinct keywords with leaks | Total leak files | Total leak hits |
|------|------------------------------|------------------|-----------------|
| 1 (即修正) | 8 categories | 41 unique files | 217 hits (excluding pkg-name exception) |
| 2 (SEO bridge) | `formerly` / `previously known as` / `旧称` | 6 files | 13 hits (5 OK as bridge, 8 acceptable per memory) |
| False positive (excluded) | `autonomath-mcp` PyPI pkg, `@autonomath/sdk` npm pkg, `/connect/claude-code` integration page | many | n/a |

---

## ティア 1 leak (即修正対象)

### `AutonoMath` (brand spelling, NOT pkg name) — 6 hit

- `site/index.html:87`: `"alternateName": ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"],`
- `site/index.html:122`: `"alternateName": ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"],`
- `site/llms.txt:2`: `Brand: jpcite. (SEO citation bridge for 旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai)`
- `site/llms.en.txt:2`: same bridge marker
- `site/en/llms.txt:3`: `Brand history: formerly discovered as 税務会計AI / AutonoMath / zeimu-kaikei.ai;`
- `docs/announce/PUBLISH_ORDER_2026_05_11.md:7`: meta about checking for leaks (acceptable internal doc, but doc itself lives in `docs/announce/` shipped path)

**Judgement**: `site/llms*.txt` 3 instances are **SEO citation bridge** per `feedback_legacy_brand_marker.md` (allowed). The 2 `site/index.html` JSON-LD `alternateName` entries are **SEO crawlable HTML** — SV-grade peers (Stripe alternateName lists "Stripe.com", never "ex-Stripe Inc" / old codenames). **REMOVE** "AutonoMath" / "税務会計AI" / "zeimu-kaikei.ai" from `alternateName` array; 301 redirect already carries SEO continuity.

### `zeimu-kaikei.ai` — 8 hit

- `site/index.html:87, 122`: alternateName JSON-LD (same fix as above)
- `site/index.html:110`: `"https://zeimu-kaikei.ai",` (sameAs schema.org)
- `site/index.html:123`: `"sameAs": ["https://www.bookyou.net/", "https://zeimu-kaikei.ai"],`
- `site/llms.txt:2`, `site/llms.en.txt:2`, `site/llms-full.txt:2`, `site/llms-full.en.txt:2`, `site/en/llms.txt:3`: bridge marker (acceptable)

**Judgement**: `sameAs` in JSON-LD references an old domain — schema.org `sameAs` is for **active** social/web profiles. Listing a 301-redirected domain there sends a confused signal to crawlers and is brand-baggage in the eyes of a human reader. **REMOVE** `zeimu-kaikei.ai` from `sameAs` (kept only via 301 at HTTP layer, not JSON-LD).

### `税務会計AI` — 6 hit

- `site/index.html:87, 122`: same alternateName array
- `site/llms.txt:2`, `site/llms.en.txt:2`, `site/llms-full.txt:2`, `site/llms-full.en.txt:2`, `site/en/llms.txt:3`: bridge (acceptable)
- `docs/announce/PUBLISH_ORDER_2026_05_11.md:7,12,...`: internal QA checklist (this file is **internal**; should not ship under `docs/announce/` public path)

**Judgement**: Same as AutonoMath — remove from `alternateName`. `PUBLISH_ORDER_2026_05_11.md` is an internal checklist that shipped to `docs/announce/` accidentally — should move to `docs/_internal/` (or delete).

### `Wave N` / `W{n}-m` (internal dev phase) — 19 hit

- `site/playground.html:702, 733, 2745, 2757, 2784`: "Wave 8 で full / Wave 8 で SSE 化" — exposes future plan
- `site/artifact.html:6`: `Pages Function 化は Wave 8 で行う`
- `site/dashboard.html:1347, 1360, 1361, 1363, 1364, 1365, 1366`: 7 `Wave 8` references in placeholder copy
- `site/audiences/shihoshoshi.html:244`: `(Wave 22)` next to tool name
- `site/legal-fence.html:369`: `Wave 30 disclaimer hardening 済`
- `site/trust/purchasing.html:278`: `Wave 30 hardening 済`
- `site/status/v2.html:51`: `Wave 8 で詳細`
- `site/dashboard/savings.html`: **12 hits** of `W28-4` codename in user-visible math anchor
- `site/calculator/index.html:461`: `(client-side derivation; primary axis per W28-4 reframe)`
- `site/mcp-server.json:431` / `site/mcp-server.full.json:431`: `density_score (W22-9)` in public tool description
- `docs/announce/note_jpcite_mcp.md:88`: `Wave 23 で追加分散中`
- `docs/announce/zenn_jpcite_mcp.md:71`: `Wave 21 で 5 chain tools、Wave 22 で 5 composition tools、Wave 23 で industry packs`

**Judgement**: **HIGHEST IMPACT LEAK CATEGORY**. SV-grade peers never name internal dev phases in product copy. Linear writes "v1.2" not "Wave 6"; Stripe writes "v3 API" not "Project Spaceship". Replace "Wave 8" → "次期 release" or remove entirely. `W28-4` in savings math is especially bad — looks like a JIRA ticket leaked into customer-facing finance copy. Replace `W28-4 sim` → "internal measurement (2026-05 baseline)".

### `autonomath` internal (db/intake/env var, NOT pkg name) — ~25 hit

- `site/legal-fence.html:359, 365`: `AUTONOMATH_36_KYOTEI_ENABLED` env var name
- `site/connect/claude-code.html:173`: `AUTONOMATH_36_KYOTEI_ENABLED=false`
- `site/connect/cursor.html:173`: same
- `site/connect/codex.html:124`: same
- `site/mcp-server.json:339, 359, 403, 431`, `site/mcp-server.full.json:339, 359, 403, 431`: `autonomath.db`, `autonomath.intake.<known>` internal paths in public OpenAPI/tool descriptions
- `site/transparency/llm-citation-rate.html:361`: `autonomath.citation_sample`
- `docs/announce/zenn_jpcite_mcp.md:67`: `Backend = SQLite FTS5 (autonomath.db 9.4GB 統合 + jpintel.db 352MB FTS index)`
- `site/widget/autonomath.src.css` (54 hit), `site/widget/autonomath.js`/`autonomath.src.js`/`jpcite.js` (75 hit × 3): **BEM CSS class names** `.autonomath-widget__*` exposed to host embedders + `window.Autonomath` JS global

**Judgement**:
- **Env var `AUTONOMATH_36_KYOTEI_ENABLED`**: stays as-is in code per CLAUDE.md, but **must not be quoted in user-facing connect docs**. Replace with neutral phrasing: "default 139 tools (36協定 render gate off)".
- **`autonomath.db` / `autonomath.intake` in OpenAPI description**: exposes physical DB file name + Python module path. Replace with "primary corpus database" / "internal predicate dispatch".
- **Widget BEM `.autonomath-widget__*` + `window.Autonomath`**: **highest blast radius** — this CSS prefix is shipped to every host site that embeds the widget. Once 100+ host sites adopt these classes, **renaming becomes breaking change**. **MUST FIX BEFORE EMBED SDK GA**. Rename `.autonomath-widget__*` → `.jpcite-widget__*` (alias retained for 6mo), and `window.Autonomath` → `window.Jpcite` (already coexists as alias; deprecate the `Autonomath` alias path on next major).

### `jpintel` (legacy package name) — 5 hit

- `site/_redirects:124, 125, 126`: 301 redirects from `/jpintel*` to `/` (acceptable migration scaffold)
- `site/contribute/scrubber.js:3`: `// Mirrors src/jpintel_mcp/api/contribute.py server-side gates so genuine` (comment exposing internal import path)
- `docs/announce/zenn_jpcite_mcp.md:67`: same `jpintel.db` exposure as above

**Judgement**: 301 redirects = fine (transparent migration). `scrubber.js` comment exposing `src/jpintel_mcp/` import path = code path leak — replace with "Mirrors server-side validation gates" (no path).

### Internal ticket IDs (`DEEP-49` etc, `W28-4`, `W22-9`) — covered in Wave bucket

(Counted in Wave row; same-file fixes overlap.)

### `feedback_*` memory key references — 9 hit

- `docs/announce/PUBLISH_ORDER_2026_05_11.md`: 3 references (this is internal QA doc, see "ship-path" issue below)
- `site/transparency/llm-citation-rate.html:363`: `(memory feedback_no_operator_llm_api)` — directly exposes Claude memory schema to public
- `site/practitioner-eval/index.html:113`: `code feedback_no_operator_llm_api`
- `site/mcp-server.json:339`, `site/mcp-server.full.json:339`: `policy: feedback_autonomath_no_api_use` in OpenAPI tool description
- `site/mcp-server.json:359`, `site/mcp-server.full.json:359`: `景表法 / 消費者契約法 fences (see feedback_no_fake_data)`

**Judgement**: **CRITICAL LEAK**. `feedback_*.md` is the Claude operator's memory naming scheme — exposing it tells every reader "this product is operated by a Claude agent reading memory keys". Replace with "internal policy reference" or remove. SV-grade peers never name their internal Notion doc IDs / Loom titles in customer docs.

---

## ティア 2 leak (許可)

- `site/llms.txt`, `site/llms.en.txt`, `site/llms-full.txt`, `site/llms-full.en.txt`, `site/en/llms.txt`: 5 hits of `formerly` / `previously known as` / `旧称` are **legitimate SEO citation bridge** per `feedback_legacy_brand_marker.md`. No fix.
- `site/humans.txt:20`: `URL: https://jpcite.com (formerly jpcite / jpcite.com)` — **tautological** (formerly itself == new name). Bug. Replace with single canonical line.
- `docs/announce/PUBLISH_ORDER_2026_05_11.md`: 8 `旧称言及無し` table cells = internal checklist (move to `_internal/`).
- `site/docs/schemas/client_company_folder_v1_request.schema.json:50`: `曖昧 hint (旧称・関係者名・案件キーワード等)` — uses 旧称 as **generic noun for "former company name"**, not brand reference. False positive; keep.
- `site/facts.html:411`: `別名・略称・旧称データ` — same generic-noun usage in data dictionary. Keep.

---

## False positive 除外

| Path | Count | Reason |
|------|-------|--------|
| `site/llms*.txt`, `site/en/llms.txt`, `site/llms-full*.txt` | 5 × `formerly`/`旧称` | SEO citation bridge per memory policy |
| Anywhere PyPI install snippet (`uvx autonomath-mcp`, `pip install autonomath-mcp`) | ~80 hits across `connect/*`, `audiences/*`, `compare/*`, `integrations/*`, `mcp-server.json`, `server.json`, `.well-known/mcp.json`, llms.txt | Pkg name is the public install identifier — explicit exception in task brief |
| `site/.well-known/sbom.json:10`, `sbom/*.json:47` | `@autonomath/sdk` npm pkg | Explicit exception (npm pkg name) |
| `site/connect/claude-code.html` (8 hits) | URL slug + meta tag | Integration page for Anthropic Claude Code — vendor integration is legitimate (Stripe ships `/connect/stripe.html`-style pages too) |
| `site/dashboard.html:1367` | `Claude Code / Cursor / ChatGPT / Codex` enumeration in docs connector list | Legitimate vendor list, parity with other agents |
| `site/index.html:378` | hero CTA link to `/connect/claude-code.html` | Legitimate integration CTA |
| `site/_redirects:196, 198` | `/facts_registry.json` URL alias | Public API surface (path is the contract — not internal-only) |

---

## SV top-tier 企業比較 (ブランド毀損度)

| Leak type | Stripe equivalent | Brand damage | Severity |
|-----------|-------------------|--------------|----------|
| `AutonoMath` in `alternateName` JSON-LD | Stripe listing "FastSpring" / "PaymentCo" as alternateName | **HIGH** — looks like rebrand chasing, weakens trust mark | Linear/Vercel never do this |
| `Wave 8 で full` in dashboard placeholder copy | Stripe shipping "Project Albatross — Q3" in dashboard | **VERY HIGH** — exposes internal roadmap, looks unfinished | Anthropic never ships "Phase 2" copy |
| `W28-4 sim 実測 anchor` in savings calculator | OpenAI showing "JIRA-1247 baseline" on pricing page | **VERY HIGH** — JIRA-ticket-leak vibe in finance copy | OpenAI never does this |
| `.autonomath-widget__*` CSS BEM | Stripe shipping `.acme-widget__btn` to host sites | **MEDIUM now / CRITICAL after GA** — breaking change inevitable | Stripe uses `.StripeElement` consistently |
| `policy: feedback_autonomath_no_api_use` in OpenAPI | Anthropic showing "see Notion doc internal_safety_v3" in API docs | **HIGH** — outs Claude-memory ops model | Anthropic never names internal docs in public copy |
| `AUTONOMATH_36_KYOTEI_ENABLED=false` in /connect docs | Stripe writing "set `STRIPE_INTERNAL_BETA_X=false`" on connector page | **MEDIUM** — env var naming exposes legacy brand | Linear/Vercel hide env var brand |
| `autonomath.db 9.4GB / jpintel.db 352MB` in zenn announcement | Stripe announcing "our payments.db is 14TB on PG" | **LOW for engineer audience, MEDIUM for executives** — engineering blog tone is OK, but file-name brand leak adds noise |

**Overall**: A Stripe / Linear PR review would block release of:
1. `site/index.html` JSON-LD (alternateName + sameAs old brand)
2. `site/dashboard/savings.html` (W28-4 leak in finance copy)
3. `site/dashboard.html` (7 × "Wave 8 で hydrate" placeholder)
4. `site/mcp-server.json` + `mcp-server.full.json` (feedback_* memory key in tool desc)
5. `site/playground.html` (Wave 8 leaks in 5 places + JSIC checkbox copy)

---

## 即修正必要 file 数 = **15 file**

Ranked by blast radius:

1. **`site/index.html`** — JSON-LD `alternateName` + `sameAs` brand baggage (3 lines; HIGHEST visible, indexed by Google/Bing/LLMs).
2. **`site/dashboard.html`** — 7 `Wave 8 で hydrate` placeholders in customer dashboard. Replace with "近日対応" or remove.
3. **`site/dashboard/savings.html`** — 12 × `W28-4` in financial sim anchor. Replace with "internal 2026-05 baseline".
4. **`site/mcp-server.json` + `site/mcp-server.full.json`** — 4 × `feedback_*` memory key + 2 × `autonomath.db` + 2 × `W22-9`. Public tool description hit by every MCP registry crawler.
5. **`site/playground.html`** — 5 × Wave 8.
6. **`site/widget/jpcite.js` + `autonomath.js` + `autonomath.src.js` + `autonomath.src.css`** — CSS BEM `.autonomath-widget__*` + `window.Autonomath` JS global. Rename before host embeddings proliferate (current count: 0 known; window is open NOW).
7. **`site/legal-fence.html`** — 2 × `AUTONOMATH_36_KYOTEI_ENABLED` env var name in legal copy.
8. **`site/connect/{claude-code,cursor,codex}.html`** — 1 each, env var quote in connect doc.
9. **`site/transparency/llm-citation-rate.html` + `site/practitioner-eval/index.html`** — `feedback_no_operator_llm_api` exposed as code reference.
10. **`site/audiences/shihoshoshi.html`** — `(Wave 22)` next to public tool name.
11. **`site/artifact.html`** — `Wave 8 で行う` placeholder comment in shipped HTML.
12. **`site/trust/purchasing.html`** + **`site/legal-fence.html`** — `Wave 30 hardening 済` (replace with "2026-04 hardening" date anchor).
13. **`site/calculator/index.html`** — 1 × `W28-4 reframe`.
14. **`site/contribute/scrubber.js`** — comment exposes `src/jpintel_mcp/api/contribute.py` path.
15. **`site/humans.txt`** — tautological `formerly` typo.

**`docs/announce/PUBLISH_ORDER_2026_05_11.md`** is internal QA — move to `docs/_internal/` (not user-facing). Counts apart from this file.

---

## 推奨 fix top-3

| Priority | File | Current | Fix |
|----------|------|---------|-----|
| **P0** | `site/index.html` (2 × alternateName + 2 × sameAs) | `"alternateName": ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]` + `"sameAs": [..., "https://zeimu-kaikei.ai"]` | `"alternateName": ["jpcite"]` + remove old domain from `sameAs` (kept only at HTTP 301 layer). |
| **P0** | `site/dashboard.html` (7 × Wave 8 / 1 × api-keys section header references) | `"...実装は Wave 8 で hydrate"` | `"...近日リリース"` or remove placeholder section, ship the hydration. |
| **P1** | `site/widget/{jpcite.js,autonomath.js,autonomath.src.js,autonomath.src.css}` (~280 hits combined) | `.autonomath-widget__*` BEM + `window.Autonomath` JS global | Rename to `.jpcite-widget__*` + `window.Jpcite` as primary; retain `.autonomath-widget__*` + `window.Autonomath` as 6-month deprecation alias with console.warn on first invoke. Stripe pattern. |
