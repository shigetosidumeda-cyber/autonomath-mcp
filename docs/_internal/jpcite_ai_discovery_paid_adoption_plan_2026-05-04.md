# jpcite AI Discovery / Paid Adoption Plan - 2026-05-04

## 0. Current State Snapshot (2026-05-04 PM)

### 0.1 Done since 2026-05-03 (committed + live)

- v0.3.3 PyPI published (`pypi-AgEIcHlwaS...` legacy token via twine; OIDC trusted publisher pre-req still outstanding for next bumps)
- v0.3.3 GitHub Release published with sdist + wheel
- MCP Registry 0.3.3 entry live with new English description (`Japan public-program MCP — subsidies, loans, tax, law, invoice, corp. 93 tools, ¥3/req metered`)
- Cloudflare Pages: 22,896 → 12,016 file (structured/ JSON-LD shards retired in favor of inline `<script type="application/ld+json">`)
- Fly.io v62 image live: `did_you_mean` middleware + `/v1/me/keys/children` REST + `saved_searches.profile_ids` fan-out + `houjin_watch.watch_kind` dispatcher filter + `schema_guard` `skip_quick_check` for autonomath profile
- 政令市 20 hub pages (cities/{札幌〜熊本}/index.html) with title `<市> の補助金 一覧 2026 — 中小企業・創業・ものづくり 主要 N 件`
- 5 trust surfaces: `site/trust/purchasing.html` + `site/security/index.html` + `site/data-licensing.html` + `site/legal-fence.html` + `site/.well-known/trust.json`
- 12-recipe Cookbook under `docs/cookbook/` (税理士 daily / Claude Desktop install / Cursor / GPT Custom GPT / Gemini extension / OpenAI Agents / 法人 360 / pref heatmap / 採択事例 / 行政処分 watch / 顧問先 alert / 月次 invoice verify) with mkdocs nav
- Manifest descriptions front-loaded with generic keywords (server.json + mcp-server.json + site/mcp-server.json + dxt/manifest.json + smithery.yaml + pyproject.toml keywords 13→26)
- README hero image (https://www.jpcite.com/assets/github-social-card.png) for OG fallback on LinkedIn / Twitter / Slack
- GitHub repo: 20 topics + homepage `https://jpcite.com` + description rewritten
- Registry submissions actually pushed: punkpeye/awesome-mcp-servers PR #5818 + cline/mcp-marketplace Issue #1500 + wong2/mcpservers.org form (id=1903 pending)
- Registry submissions blocked: appcypher/awesome-mcp-servers PR (GitHub anti-spam, account <90 days). 3 retry routines scheduled at 2026-05-18 / 05-25 / 06-01 (`trig_01XnhDbNVbtPry1EDtFMu1qb` / `trig_01M6iVX46rKoLMGrSRZZnvkR` / `trig_012NgUMgJCKUUBLKE2pbu6Hq`)

### 0.2 Verified live

- `https://api.jpcite.com/healthz` HTTP 200
- `https://api.jpcite.com/v1/am/health/deep` status=ok / version=v0.3.2 (Fly tag will refresh on next push)
- `did_you_mean`: `?perfecture=tokyo` → `unknown_query_parameter` body now includes `もしかして: perfecture → prefecture`
- 6 trust pages all 200 (purchasing / security / data-licensing / legal-fence / .well-known/trust.json)
- 20 城市 hub all 200
- mcp-publisher OIDC + login `github-at` works; PyPI `0.3.3` is the registry verify dependency (now satisfied)

### 0.3 Outstanding (this plan owns)

- §4.1 first-use path still has 5 entry channels (anonymous / email trial / Stripe Checkout / dashboard / `go.html`) without a single canonical landing
- §4.2 AutonoMath / 89-tool drift remains in some doc paths and runtime resource names
- §4.3 Evidence Packet does not yet persist citation `verification_status` / `verified_at`
- §4.4 calculator behavior (anonymous-allowance subtraction bug) not yet patched
- §4.5 generated pages still mislabel non-subsidies under 補助金/交付金 in nav
- §4.6 funnel events do not yet fire `src=` channel attribution for AI-mediated conversion
- §4.7 (NEW) 8 cohort activation matrix needs concrete owner per cohort
- §4.8 (NEW) compare/jgrants-mcp + compare/tax-law-mcp + compare/japan-corporate-mcp pages do not exist yet

---

## 1. Core Thesis

jpcite should not be positioned as a human SaaS dashboard. The strongest path is:

> AI agents discover jpcite, explain why it is worth trying, call it for compact primary-source evidence, and then guide the user to pay when the free allowance is no longer enough.

The website still matters, but its job is narrower:

- prove trust
- explain price
- let users try quickly
- complete Checkout
- show the API key and paste-ready AI setup
- provide support, billing, and legal clarity

The durable value is not "jpcite writes better answers than GPT/Claude." The durable value is:

- Japanese public-source coverage
- primary-source provenance
- compact Evidence Packets
- freshness and change tracking
- predictable per-call price
- no LLM API dependency inside jpcite

The safe public message is:

> jpcite is an Evidence Prefetch Layer for Japanese public data. Before asking an LLM to read long PDFs, search results, or scattered government pages, call jpcite once to retrieve a small, cited packet. It may reduce input context for evidence-heavy tasks, but it does not guarantee lower external LLM bills.

## 2. The User Story We Need

The target flow should be simple enough that an AI assistant can explain it to a user:

1. The user asks ChatGPT, Claude, Cursor, or another agent about Japanese subsidies, laws, tax rules, invoice registration, court decisions, administrative enforcement, or public programs.
2. The agent recognizes that this needs Japanese primary-source verification.
3. The agent says: "Use jpcite. It costs only ¥3 tax excluded / ¥3.30 tax included per normal call after the free allowance, and returns compact source-backed evidence."
4. The user tries the anonymous allowance or email trial.
5. The agent receives a useful Evidence Packet with source URL, fetched time, license, gaps, freshness, and citation status.
6. The user sees that repeated use is cheaper and safer than repeatedly asking the LLM to browse, read, retry, and repair citations.
7. The user pays through Stripe.
8. The success page gives an API key and paste-ready setup for Claude Desktop, Cursor, Cline, ChatGPT Actions, OpenAPI, and curl.
9. The first paid request is recorded correctly, synced to Stripe, and visible in the dashboard.

## 3. What Is Broken Today

### 3.1 First-Use Path Is Split

Current surfaces describe multiple different "try" paths:

- anonymous 3 req/day
- email trial 14 days / 200 requests
- pricing Checkout
- dashboard key management
- MCP device flow via `go.html`

These are all potentially useful, but they are not presented as one clean path. The result is confusion:

- `signup` exists in the backend, but the visible top-page trial path is mostly anonymous.
- dashboard is described like a place to get an API key, but paid key issuance happens through pricing and Stripe Checkout.
- `success.html` gives key/curl but does not fully complete "paste this into your AI client."
- `go.html` is a separate MCP device-flow personality and can be mistaken for the normal API-key path.
- support/contact are not clearly real product pages.

### 3.2 AI Discovery Assets Exist But Drift

The project already has many AI-readable surfaces:

- `llms.txt`
- `llms-full`
- OpenAPI specs
- MCP manifests
- `server.json`
- `mcp-server.json`
- robots/sitemaps
- registry drafts

But the repo has drift:

- root `server.json` and site copies can differ by version.
- site/docs OpenAPI copies can lag root docs.
- old `AutonoMath` / `autonomath` names still appear in runtime names, resources, registry drafts, docs, and prompts.
- Agent-safe OpenAPI exposes too few read-only endpoints compared with the underlying data product.
- robots rules are partly contradictory around `/.well-known/` and `/v1/`.

For AI discovery, this is serious. LLMs and registries do not just read the homepage. They read manifests, specs, descriptions, package names, and examples. Brand drift and stale specs reduce recommendation confidence.

### 3.3 The Token-Saving Story Is Real But Conditional

What can be said safely:

- Evidence Packets are small.
- Existing benchmark packets are in the hundreds to low-thousands of estimated tokens.
- If the alternative is "send a long PDF / several government pages / search result bundle to an LLM," jpcite can reduce input context materially.
- If the alternative is "ask a cheap model from memory and accept a vague answer," jpcite may add cost.

What cannot be claimed yet:

- "jpcite always reduces LLM bills."
- "jpcite reduces cost by X% for all users."
- "jpcite is cheaper than ChatGPT/Claude."

The product should sell "cheap enough to try" and "source-backed evidence in fewer tokens," not guaranteed token savings.

### 3.4 Human Pages Expose Too Much Internal Language

Top/pricing/docs include terms like:

- `known_gaps`
- `break_even_met`
- `caller baseline`
- raw field names
- internal benchmark language

These are useful in API reference, but they are strange in the buying path. A human buyer needs:

- what it does
- why it is trustworthy
- what it costs
- how to try it
- what happens after payment
- how to stop or get support

### 3.5 Data Moat Is Strong But Uneven

The database has meaningful assets:

- large entity/fact/source corpus
- laws and enforcement data
- program facts
- precomputed summaries
- amendment diff infrastructure
- citation verifier
- Evidence Packet composer

But quality is uneven:

- many HTTP sources are not recently verified.
- S/A tier entity mapping is weaker than it should be.
- non-program areas have thin `source_id` coverage.
- citation verification is not persisted into Evidence Packets.
- amendment diff exists, but user-facing before/after changes are not yet clean enough.
- cross-source agreement appears to reference a schema shape that may not match production data.

This matters because paid users will not pay for "more pages." They pay for "I can trust this packet enough to feed it into my AI workflow."

### 3.6 Distribution Is Still Mostly Prepared, Not Executed

The repo has many outreach and launch assets, but the adoption signal is weak:

- outreach tracker has little evidence of actual sends/replies.
- registry submissions are draft or blocked.
- launch posts need final source URLs and current counts.
- local usage evidence is still light.
- AI/MCP mediated conversion is not clearly separated from normal web traffic.

The project does not need more abstract planning before any signal. It needs shipping plus measurement.

## 4. The Plan

### 4.1 Make The First-Use Path Unambiguous

Goal:

> A new user can understand the choice in two clicks: anonymous trial, email trial, or paid API key.

Concrete work:

- Make the top page describe three paths in this order:
  - "Try anonymously: 3 req/day/IP"
  - "Email trial: 14 days / 200 requests" if this is truly supported
  - "Paid API key: ¥3 tax excluded / ¥3.30 tax included per normal call"
- Add or expose a real signup form for `/v1/signup`.
- Send all paid API-key issuance language to `pricing.html#api-paid`.
- Define dashboard as "manage an existing key," not "get a new key."
- Make `success.html` the real setup completion page:
  - API key
  - curl
  - Claude Desktop config
  - Cursor/Cline config
  - ChatGPT Actions/OpenAPI setup
  - dashboard link
  - support link
- Make `trial.html` and `success.html` share the same setup blocks.
- Make `go.html` explicitly "MCP automatic authorization only."
- Add `support.html` and route support/contact links there.

Acceptance:

- A user can go from homepage to first successful call without guessing where keys are issued.
- Paid Checkout success page alone is enough to configure an AI client.
- No main CTA sends a keyless user to dashboard as if dashboard issues paid keys.
- `contact.html` / `support.html` links are not broken or redirected to irrelevant legal pages.

### 4.2 Make AI Discovery Canonical

Goal:

> AI systems and registries see one name, one product description, one current version, and enough callable endpoints to recommend jpcite confidently.

Concrete work:

- Treat `jpcite` as the public display name everywhere.
- Keep `autonomath-mcp` only where it is required for backward-compatible package/install names.
- Align these surfaces:
  - root `server.json`
  - `site/server.json`
  - `site/mcp-server.json`
  - `docs/openapi/*.json`
  - `site/docs/openapi/*.json`
  - `site/openapi.agent.json`
  - `site/llms.txt`
  - `site/llms.en.txt`
  - registry drafts
  - README install examples
- Update MCP runtime display name and prompts to jpcite.
- Keep compatibility resource names only if changing them would break clients; otherwise alias old names to new names.
- Expand Agent-safe OpenAPI with read-only endpoints for the value areas:
  - subsidies/program search
  - program detail
  - Evidence Packet
  - precomputed intelligence
  - invoice registrants
  - laws/articles
  - court decisions
  - administrative enforcement
  - tax rulesets
  - corporate/public entity lookup
  - bids/public procurement
  - funding stack/check endpoints
- Continue excluding:
  - billing webhook
  - admin
  - account mutation
  - secret-bearing endpoints
- Simplify robots allow/disallow rules for AI-readable files:
  - `llms.txt`
  - `llms-full`
  - OpenAPI specs
  - MCP manifests
  - integration pages
  - pricing/support/trust pages
- Make registry submission assets current and submitted.

Acceptance:

- Public-facing old-brand references are gone except explicit compatibility notes.
- Agent OpenAPI has enough read-only endpoints that an LLM can solve real Japanese public-data tasks without needing the full human docs.
- Root/site/spec versions do not drift.
- robots and sitemap files do not contradict discovery of manifests and specs.
- Registry assets are submitted or marked with a concrete blocking reason and URL.

### 4.3 Turn Evidence Quality Into The Product

Goal:

> Every paid response should feel more reliable than asking an LLM directly.

Concrete work:

- Create an Evidence Quality Ledger that reports:
  - source coverage
  - redistributable source coverage
  - `last_verified` coverage
  - S/A tier mapping coverage
  - verified citation count
  - stale source count
  - packet token p50/p95
- Persist citation verification:
  - `verification_status`
  - `matched_form`
  - `source_checksum`
  - `verified_at`
  - `verification_basis`
- Add citation status into Evidence Packets:
  - `verified`
  - `inferred`
  - `unknown`
  - `stale`
- Separate source body hash from URL fingerprint if current hash semantics are mixed.
- Raise S/A tier entity mapping first, because these are likely demo and first-use queries.
- Extend `source_id` coverage beyond programs:
  - laws
  - tax measures
  - enforcement
  - adoption/case studies
  - invoice/corporate records where allowed
- Make amendment diff user-facing:
  - deadline changed
  - amount changed
  - eligibility changed
  - subsidy rate changed
  - application period changed
  - exclude internal/debug fields
- Formalize precomputed summary refresh:
  - source hash
  - generated_at
  - stale flag
  - regeneration trigger
- Fix cross-source agreement against production schema, not only fixture schema.
- Add packet profiles:
  - `brief`
  - `verified_only`
  - `changes_only`
  - `full`

Acceptance:

- High-value mapped coverage is high enough that first-use queries rarely miss.
- Evidence Packets clearly show which citations are verified and which are inferred or stale.
- Default packets stay compact, with a clear cursor/truncation path for full detail.
- User-facing amendment diffs show meaningful before/after changes.
- Trust signals are generated from real production schema.

### 4.4 Make The Price Story Quantitative But Honest

Goal:

> An AI can tell the user: "This is cheap enough to try, and for evidence-heavy tasks it may reduce context you need to send to the LLM."

Concrete work:

- Standardize the price sentence:
  - "1 normal request = 1 billable unit."
  - "¥3 tax excluded / ¥3.30 tax included per billable unit."
  - "Anonymous allowance: 3 req/day/IP."
  - "No monthly minimum."
  - "External LLM token/search/cache/tool fees are separate."
- Fix calculator behavior:
  - paid monthly estimate must not subtract anonymous free allowance.
  - anonymous estimate can separately show 3 req/day/IP.
  - backend cost preview and public calculator must match.
- Add a context break-even calculator:
  - source tokens or PDF pages
  - packet token estimate
  - input-token price entered by caller
  - avoided input tokens
  - jpcite request cost
  - "break-even for input context only"
- Expand benchmark dataset:
  - query
  - source URL/PDF
  - source token count or page count
  - packet token estimate
  - tokenizer/method
  - measured date
  - whether break-even was met
- Run paired benchmark:
  - direct web/browse workflow
  - jpcite Evidence Packet
  - jpcite precomputed intelligence
  - measure citation rate, hallucination rate, latency, web searches, input/output/reasoning tokens where available, and total estimated cost.
- Create an AI-facing recommendation template:
  - when to recommend jpcite
  - when not to recommend jpcite
  - how to explain price
  - how to explain token/context reduction
  - how to avoid guaranteed savings claims

Acceptance:

- No public surface claims guaranteed LLM bill reduction.
- The calculator never underestimates paid charges by incorrectly subtracting anonymous allowance.
- Any percent context-reduction claim links to a measured query set and methodology.
- AI-facing docs include a safe recommendation paragraph that can be reused by ChatGPT/Claude/Cursor.

### 4.5 Clean Human Trust Pages

Goal:

> The public site should not feel like internal system output.

Concrete work:

- Move raw internal terms out of homepage/pricing/success/dashboard.
- Keep raw fields in API reference only.
- Create one public count source:
  - searchable public programs
  - laws/articles
  - tax rules
  - corporate/invoice records
  - enforcement records
  - sources
  - last refresh date
- Replace drifting numbers with generated values from that source.
- Reconcile privacy/cookie/localStorage statements with implementation:
  - Cloudflare Analytics
  - Stripe
  - dashboard localStorage
  - success session/sessionStorage if used
  - Sentry
  - email provider
  - API logs
- Reclassify generated pages:
  - grants/subsidies
  - loans
  - tax incentives
  - regulation
  - enforcement
  - statistics
  - consultation/training
  - informational pages
- Stop displaying non-subsidy pages as "補助金・交付金".
- Fix odd agriculture/non-agriculture split in public navigation.
- Remove internal sample/debug wording from public docs.
- Add internal link checking for generated HTML.

Acceptance:

- A normal visitor can understand the homepage and pricing page without reading API internals.
- Legal/privacy pages match actual tracking/storage behavior.
- Generated pages do not mislabel enforcement/statistics/regulation as subsidies.
- Public docs no longer expose internal samples or implementation artifacts that weaken trust.
- Link checker has zero missing critical public links.

### 4.6 Execute Distribution And Measure Paid Conversion

Goal:

> Stop measuring only internal readiness. Measure whether AI-discovered users pay and keep using it.

Concrete work:

- Submit registry assets:
  - official MCP registry
  - Smithery
  - Glama
  - PulseMCP
  - Cline/Cursor-related directories
  - community MCP lists
- Add source codes to all distribution URLs:
  - `src=chatgpt_actions`
  - `src=claude_mcp`
  - `src=cursor_mcp`
  - `src=cline_mcp`
  - `src=hn_launch`
  - `src=zenn_intro`
  - `src=outreach_firm_01`
- Define AI-mediated conversion:
  - referer
  - source param
  - user-agent class
  - MCP device flow
  - OpenAPI/Actions setup flow
  - API SDK class
- Extend funnel analytics:
  - visitor
  - docs/spec view
  - playground success
  - pricing view
  - checkout start
  - checkout success
  - API key issued
  - first successful request
  - first billable usage event
  - Stripe sync
  - retained usage
- Run production-equivalent billing E2E:
  - pricing
  - Stripe Checkout
  - success key reveal
  - first API request
  - `usage_events`
  - Stripe usage sync
  - dashboard display
- **Organic only**: no proactive cold outreach, no email blast, no Slack Connect, no DPA / MSA negotiation. The funnel is "AI / search / GitHub / RSS discover jpcite → user converts on their own time." Outreach tracker is replaced by **inbound signal log**: which channel did the converter come from (`src=...` param), did they convert in the same session, did they pay within 7 days.
- Collect testimonials after real successful usage. Surface them in `site/testimonials.html` with explicit consent and `<blockquote cite=...>` schema.org markup.

Acceptance:

- AI-mediated paid conversion can be separated from normal web conversion.
- First paid request and Stripe usage sync are visible end to end.
- Major registry channels are listed, submitted, or blocked with a recorded reason.
- Outreach tracker has real sent dates, links, replies, and outcomes.

### 4.7 Cohort Activation Matrix (NEW)

Goal:

> Each of the 8 revenue cohorts (CLAUDE.md ▷ Cohort revenue model) has one owner endpoint or doc page that shortens "AI hears about cohort task → calls jpcite → user pays" to fewer than 5 steps.

| Cohort | Single owner deliverable | File / route | Acceptance |
|---|---|---|---|
| M&A | `houjin_watch.watch_kind` × `dispatch_webhooks` filter (DONE 2026-05-04) | `scripts/cron/dispatch_webhooks.py` | webhook event count by `watch_kind` visible in `/v1/admin/analytics_split` |
| 税理士 | `saved_searches.profile_ids_json` fan-out (DONE 2026-05-04) | `scripts/cron/run_saved_searches.py` | per-顧問先 row in `usage_events.client_tag` |
| 会計士 | Wave 22 `compose_audit_workpaper` MCP tool surface | `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` | tool returns audit workpaper PDF reference |
| Foreign FDI | `am_tax_treaty` 8 → 30 国 backfill + `law_articles.body_en` ingest | `scripts/etl/batch_translate_corpus.py` + manual JETRO IBSC dump | `SELECT COUNT(*) FROM am_tax_treaty` ≥ 30 |
| 補助金 consultant | `client_profiles_router` wired in `main.py` (was unwired per CLAUDE.md drift) | `src/jpintel_mcp/api/main.py` | `gh api ... /openapi.json` shows `/v1/client_profiles` |
| 中小企業 LINE | LINE webhook deep verify against current `widget_keys` | `src/jpintel_mcp/api/widget*.py` | round-trip from LINE → API → reply shows source URL |
| 信金商工会 organic | `site/audiences/shinkin.html` + `site/audiences/shokokai.html` (NEW) | new audience landing pages | 2 page 200 + JSON-LD valid |
| Industry packs | New 5 JSIC majors beyond construction/manufacturing/real_estate | `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py` | `pack_*` tool count ≥ 8 (was 3) |

### 4.8 Competitor MCP Differentiation (NEW)

Goal:

> When an AI client searches "japan tax MCP" / "japan subsidies MCP" / "japan corporate MCP" we want a public, cited compare page so the AI cites jpcite alongside (or above) the OSS-only single-source wrappers.

Concrete work:

- New `site/compare/jgrants-mcp/index.html`: jpcite (93 tools / 11 一次資料) vs `digital-go-jp/jgrants-mcp-server` (5 tools / 1 source). Recommend "jpcite for cross-source compliance check, jgrants-mcp for grant application path."
- New `site/compare/tax-law-mcp/index.html`: jpcite (50 tax_rulesets + 9,484 e-Gov laws + 28,201 article rows) vs `kentaroajisaka/tax-law-mcp` (live scrape, 30-60s latency). Recommend "jpcite for pre-indexed answers + 通達 cross-ref, tax-law-mcp for ad-hoc lookups."
- New `site/compare/japan-corporate-mcp/index.html`: jpcite (166,969 法人 + 13,801 適格事業者 + 22,258 enforcement, anonymous trial) vs `yamariki-hub/japan-corporate-mcp` (3 user API keys required). Recommend "jpcite for analyst pre-screening, japan-corporate-mcp for live regulator pulls when keys are already provisioned."
- README short table: `vs jgrants-mcp` / `vs tax-law-mcp` / `vs japan-corporate-mcp` 各 1 行
- 3 new MCP tools to widen the corporate layer (closest competitor ground): `get_houjin_360_am`, `list_edinet_disclosures`, `search_invoice_by_houjin_partial`

Acceptance:

- 3 compare pages 200 + neutral wording (no competitor disrespect, observable facts only)
- README compare table renders in GitHub
- corporate-layer tool count 93 → 96 (verified by `len(mcp._tool_manager.list_tools())`)

---

## 5. Execution Order

1. Fix the paid path and support path.
2. Remove public trust leaks and copy drift.
3. Unify AI-readable manifests/specs and old-brand references.
4. Expand Agent-safe OpenAPI enough for real AI workflows.
5. Fix calculator and price story.
6. Raise Evidence Packet trust: citation status, freshness, S/A mapping, compact profiles.
7. Fix generated page classification and link quality.
8. Submit registries and launch assets.
9. Measure AI-mediated conversion through first paid usage.
10. Use real usage and testimonials to improve the public story.

## 6. What Not To Do

- Do not build a new SaaS dashboard before first-use and paid setup are clean.
- Do not claim guaranteed token or LLM-cost savings.
- Do not expose internal debug fields on buying pages.
- Do not keep `AutonoMath` as a public display name except explicit compatibility notes.
- Do not publish more generated pages until classification and link checks are under control.
- Do not optimize for pageviews without measuring first successful paid request.
- Do not treat "more data" as value unless it improves verified evidence returned to the user.
- Do not introduce tier SKUs / Pro plan / Starter plan / seat fees. The price stays ¥3/billable unit single tier, no exceptions.
- Do not call any LLM API from inside production code. The `tests/test_no_llm_in_production.py` guard is non-negotiable.
- Do not add aggregator URLs (noukaweb / hojyokin-portal / biz.stayway / smart-hojokin) to `source_url`. Primary government sources only.
- Do not negotiate DPAs / MSAs / Slack Connect / Zoom kickoff calls. Solo zero-touch is the operating model; legal posture is published self-serve in `site/trust/purchasing.html` + `site/legal-fence.html`.
- Do not publish a v0.3.x bump without (a) test.yml green, (b) release.yml green, (c) PyPI publish, (d) MCP registry publish all running cleanly. Each prior failure has a recorded root cause; do not silently retry.

## 7. Most Important Product Sentence

Use this everywhere after minor copy adjustment:

> jpcite helps AI agents answer Japanese public-data questions with compact, cited evidence. A normal call costs ¥3 tax excluded / ¥3.30 tax included after the free allowance. For evidence-heavy tasks, this can reduce the amount of raw PDF and web text you need to pass into the LLM, while giving source URLs, fetched times, license notes, freshness, and known gaps. It is not a guarantee that your external LLM bill will go down; it is a cheap way to get better evidence before the model writes.

## 8. The Business Logic

The monetization does not depend on humans loving the website.

The website only needs to be trustworthy enough to:

- confirm the product exists
- show the price
- complete payment
- expose setup instructions
- provide legal/support pages

The real buyer experience can happen inside AI tools:

- ChatGPT/Claude/Cursor discovers jpcite from `llms.txt`, OpenAPI, MCP registries, docs, and examples.
- The AI explains why the task needs primary-source evidence.
- The AI calls jpcite or tells the user to connect it.
- The user sees compact evidence returned.
- The user pays because repeated calls are predictable and cheap.

This is why the highest-value work is not a prettier homepage. The highest-value work is making jpcite:

- discoverable by AI
- explainable by AI
- safe to recommend
- cheap to try
- easy to connect
- visibly better than raw LLM browsing for evidence-heavy Japanese public-data tasks

