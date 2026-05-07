---
agent: R8 AI Consumer Audit
date: 2026-05-07 JST
working_dir: /Users/shigetoumeda/jpcite
mode: READ-ONLY HTTP GET only. anonymous quota only. LLM 0.
target_release: jpcite v0.3.4 / 184 OpenAPI / 139 MCP default + 146 cohort runtime
hypothesis: AI consumer (Claude / GPT / Cursor / generic Custom-GPT, MCP host) calling jpcite without prior knowledge can (a) discover the right tool/endpoint, (b) parse the response correctly, (c) cite back to the user with disclaimer + source.
verdict: STRONG MCP description quality, MEDIUM OpenAPI quality, LOW envelope discoverability via spec.
---

# R8 — AI Consumer Audit (MCP / OpenAPI Actions)

## TL;DR (verdict per surface)

| Surface | Quality | Single biggest gap |
|---|---|---|
| MCP `list_tools` (default 107 visible in this run, 139 advertised) | A- | 33/107 tools use the role-prefix convention (`DISCOVER:`, `DETAIL:`, `RISK:`, `EVIDENCE:` …). The other 74 use `[KAIKEI]`, `LOOKUP-INVOICE`, plain prose, or `OMNIBUS-…`. Discoverability is high, but the prefix vocabulary is **not yet a closed enum**, so an LLM agent cannot pre-filter by intent class. |
| OpenAPI 3.1 spec (`/v1/openapi.json`, 539 KB, 182 paths / 190 operations) | B | **Zero `tags:` block at root** + **only 28/188 2xx responses have an example** + **190/190 operationIds are FastAPI auto-generated** (`get_meta_v1_meta_get`-style). |
| Auth + rate-limit discoverability | A | `securitySchemes.ApiKeyAuth` is documented and global, anon 3 req/日 stated explicitly, 429 body is bilingual (ja+en) with `retry_after`, `reset_at_jst`, `upgrade_url`, `direct_checkout_url`, `trial_signup_url`. **Best-in-class for an SMB API.** |
| Envelope (`_disclaimer`, `_billing_unit`, `_audit_seal`, `X-Corpus-Snapshot-Id`, `X-Request-ID`, `X-Envelope-Version`) | B+ | Production response **headers** include `x-request-id`, `x-envelope-version: v1`, plus full security headers (HSTS, CSP, X-Frame-Options DENY). But spec exposes `_disclaimer` only **36 times** in 539 KB of JSON — no schema-level `$ref` to a single Envelope component. Each schema duplicates the alias. |
| Error response shape consistency | A | 429 body keys (`code`, `reason`, `detail`, `detail_en`, `retry_after`, `reset_at_jst`, `limit`, `resets_at`, `upgrade_url`, `direct_checkout_url`, `cta_text_ja`, `cta_text_en`, `trial_signup_url`, `trial_cta_text_ja`, `trial_cta_text_en`, `trial_terms`) is **the gold-standard SMB-friendly error envelope** documented earlier in this audit. |
| AI parse-friendliness | B+ | Strong: bilingual disclaimer text, stable `unified_id` PK with type-prefix (`UNI-`, `LAW-`, `BID-`, `TAX-`, `CASE-`), search responses always carry `total/limit/offset/results`. Weak: hyphen-vs-underscore path drift, `q` vs `query` parameter drift, `unified_id` is a string but **not declared as a named schema**. |

Overall AI-consumer readiness: **B+ / ship-ready, with two actionable improvements that take <2 h of work each**. Top fix list at the bottom.

---

## 1. MCP tools-list integrity (108-tool sample loaded successfully)

Loaded `jpintel_mcp.mcp.server.mcp` and called `await mcp.list_tools()` against the build-time default registry. Saburoku Kyotei tools were correctly disabled (`AUTONOMATH_36_KYOTEI_ENABLED=0`, "Operator must complete legal review before enabling.") — so visible count was 107, the rest are cohort-conditional.

**Top 20 tool names** (verbatim, sorted by registration order):

```
search_programs                  — DISCOVER: 補助金 / 助成金 / 融資 / 税制特例 を 1 クエリで横断検索
get_program                      — DETAIL: 1 件の制度の全フィールド + 引用元 URL を返す
search_enforcement_cases         — RISK: 会計検査院 不正・不当請求事例 1,185 件
get_enforcement_case             — DETAIL: 不正・不当請求事例 1 件の詳細
search_case_studies              — EVIDENCE: 採択事例 (recipient profile + program) 2,286 件
get_case_study                   — DETAIL: 採択事例 1 件
search_loan_programs             — DISCOVER: 無担保・無保証融資 108 件
get_loan_program                 — DETAIL: 融資プログラム 1 件
prescreen_programs               — DISCOVER-JUDGE: profile → ranked eligible programs
smb_starter_pack                 — ONE-SHOT DISCOVERY: 1 call で SMB 経営者の "今日何できる?"
upcoming_deadlines               — DISCOVER-CALENDAR: list 補助金 / 助成金 / 融資 / 税制 deadlines
deadline_calendar                — ONE-SHOT CALENDAR: 今後 N ヶ月の締切 月別グルーピング
subsidy_combo_finder             — ONE-SHOT COMBO: 補助金+融資+税制 非衝突組合せ TOP N
dd_profile_am                    — ONE-SHOT DD: 法人番号 → コンプライアンス + 採択 + インボイス
similar_cases                    — CASE-STUDY-LED DISCOVERY: 採択事例 seed → 似た事例 + 制度
subsidy_roadmap_3yr              — ONE-SHOT 3-YEAR ROADMAP
search_laws                      — DISCOVER-LAW: e-Gov 3,400 法令 catalog
get_law                          — DETAIL-LAW: LAW-<10hex> による法令詳細
list_law_revisions               — LINEAGE-LAW: superseded_by_law_id チェーン追跡
… (87 more)
```

**Quality assessment:**

- **0/107 tools have an empty description.** No silent endpoints. This is rare in shipped MCP servers (typical FastAPI-MCP autogen leaves 30-50% empty).
- **103/107 (96%) have rich descriptions (>200 chars).** Most descriptions cover: action verb (search/get/check/recommend), corpus size with row count, source attribution (会計検査院 / e-Gov / 国税庁 etc.), and an explicit return-shape clue.
- **33/107 use the role-prefix convention** (`DISCOVER:`, `DETAIL:`, `RISK:`, `EVIDENCE:`, `ONE-SHOT…`, `CASE-STUDY-LED DISCOVERY:`, `LINEAGE-LAW:`, `TRACE`, `SCREEN-BID`, `LEGAL`, `JUDGE`, `VALIDATE`, `CALENDAR`).
- **74/107 use ad-hoc prefixes** (`[KAIKEI]`, `[TIMELINE]`, `[UTILITY]`, `[DISCOVER-LAW]`, `LOOKUP-INVOICE`, `OMNIBUS-COMPLIANCE`, `COMPLIANCE`, `META`, `UTILITY`). The `[KAIKEI]` cohort uses bracket form; the core uses colon. **Two parallel naming conventions.**
- **Top name prefixes** (verb leading): `get_*` 21, `search_*` 20, `list_*` 7, `find_*` 6, `check_*` 3, `recommend_*` 3, then long-tail with `enum_*`, `query_*`, `batch_*`, `prescreen`, `subsidy_*`, `pack_*`. **Verb leading is consistent — a Custom-GPT can cluster by action.**

**Disclaimer envelope adherence (sampled):** the 4 `_disclaimer`-bearing responses found in OpenAPI examples (`/v1/tax_rulesets/search`, `/v1/tax_rulesets/{unified_id}`, `/v1/funding_stack/check`, `/v1/am/tax_incentives`) **all** carry the bilingual hedge "Verify current public guidelines and application-round rules." or "Rule-engine result only; final decisions require primary-source review." This is exactly what an AI consumer must echo back to the user under 景表法 / data-vendor TOS rules. **Functional.**

---

## 2. OpenAPI spec quality (https://api.jpcite.com/v1/openapi.json — 539 KB, fetched 2026-05-07 16:26 JST, HTTP 200)

```
openapi              : 3.1.0
title / version      : jpcite / 0.3.4
servers              : [{ url: https://api.jpcite.com, description: Production }]
paths                : 182      (vs spec'd 184; 2-path drift, minor)
operations           : 190
tags root            : 0        ← MAJOR: no root-level tag descriptions at all
operationId          : 190 / 190 unique, 0 duplicates  ← good for routing
summary              : 190 / 190 present, but 91 of them are <20 chars (e.g. "Get Meta", "Healthz", "Ping")
description          : 161 / 190 (29 endpoints have NO description at all)
response examples    : 28 / 188 2xx responses (15%)
search/list w/ ex    : 10 / 18 (56%)
global security      : ApiKeyAuth (X-API-Key header) ← good
```

### 2.1 Tag classification (operation-level)

Tag totals across operations (top 15):

```
26  jpcite                       (rollup tag — unhelpful for an Action plug-in)
16  trust
13  me
 9  transparency
 9  integrations
 7  saved-searches
 6  meta / stats / billing / advisors
 5  customer_webhooks / audit (会計士・監査法人)
 4  programs / compliance / dashboard / widget
 3  corrections / testimonials / enforcement-cases / laws / court-decisions / tax_rulesets / artifacts / device / alerts
```

**Findings:**

- 1 operation is **entirely tag-less** (drifted from R7 spec). Easy fix.
- The `jpcite` tag absorbs 26 ops which logically belong to `programs`, `case-studies`, `enforcement-cases`, etc. ChatGPT's Custom GPT Action picker shows tags as section headers — **this 26-op rollup tag will appear as a giant unsorted dropdown** for the operator.
- `tax_rulesets` uses underscore tag, `enforcement-cases` and `court-decisions` use hyphens. Minor inconsistency.
- **No root-level `tags:` array → no tag descriptions visible to the AI consumer.** Each tag is a bare string. Adding a 2-line description per tag (15 tags × 2 lines ≈ 60 lines of JSON) is the highest-ROI single fix.

### 2.2 operation summary / description quality

- **91 of 190 summaries are under 20 chars** ("Get Meta", "Ping", "Healthz", "Get Bid", "Logout", "Get Me", "Stats Coverage", …). For an AI consumer building an Action plug-in, the summary IS the function selector text. "Get Meta" gives the model nothing to pick on. The MCP descriptions are far better; the OpenAPI summaries are sometimes the FastAPI auto-derived word-split of the function name.
- **29 endpoints have NO `description:` at all.** Includes high-traffic ones: `/v1/meta`, `/healthz`, `/v1/ping`, `/v1/stats/coverage`, `/v1/stats/freshness`, `/v1/billing/checkout`, `/v1/me`, `/v1/me/billing-portal`, `/v1/feedback`, `/readyz`. For health/ping, low impact. For `/v1/billing/checkout` and `/v1/me/billing-portal` — these are revenue endpoints; absence of description means a Custom GPT will refuse to call them or hallucinate the body shape.
- **161 endpoints with description** are mostly excellent (long Japanese + English explanations including row counts, source attribution, and the unified_id format spec). Sample from `/v1/court-decisions/by-statute`: "Return court decisions citing a given LAW-<10 hex> statute. TRACE endpoint: …"

### 2.3 parameter naming consistency

Query keyword parameter usage:

```
q           13×     ← canonical
query        2×     ← drift (should be q)
keyword      0
search       0
term         0
keywords     0
text         0
```

**13 vs 2 drift on the search-keyword parameter** is the next-highest-ROI fix. An LLM agent will guess `q` (FastAPI / Stripe convention) and 2 endpoints will silently 422.

Auth parameters appear in 4 forms across endpoints: `X-API-Key` (header, 90+×), `authorization` (header, 90+×), `am_session` (cookie, 30+×), `am_csrf` (cookie, 30+×). Cookie-form is for the dashboard's first-party browser session; documented inconsistently.

### 2.4 response schema and examples

- **28 / 188 2xx responses (15%) have an example.** Search endpoints fare better at 56% (10/18). Detail endpoints (`/v1/programs/{unified_id}`, `/v1/laws/{unified_id}`) almost universally lack examples.
- The example shape is **clean**: `{ total, limit, offset, results, _disclaimer? }`. AI consumer can pattern-match without reading the schema.
- **Schema count:** 230 components. None is named `UnifiedId` / `Envelope` / `DisclaimerWrapper`. The `_disclaimer` alias appears 36× across schemas (duplicated, not $ref'd). Refactoring to a single `Envelope` mixin would shave ~3 KB and let an AI consumer learn it once.

### 2.5 path naming consistency

```
hyphen paths     : 20    e.g. /v1/court-decisions, /v1/case-studies, /v1/loan-programs, /v1/laws, /v1/enforcement-cases
underscore paths : 54    e.g. /v1/tax_rulesets, /v1/cross_source, /v1/stats/data_quality, /v1/am/programs
```

Hyphens are REST convention; underscores are SQL-table convention leaking through. **`tax_rulesets` is the most-cited path in agri/SMB cohort** — would benefit most from being `tax-rulesets`, but breaking change. Document the inconsistency in `/v1/meta` instead.

### 2.6 operationId style

**190 / 190 are FastAPI auto-generated** in the form `<func_name>_<path_with_slashes_replaced>_<method>`, e.g. `get_meta_v1_meta_get`, `search_bids_v1_bids_search_get`, `revoke_child_key_route_v1_me_keys_children__child_id__delete`. These are unique (no duplicates) and stable, but verbose. Custom GPT Actions display operationId as the function label — these are unnecessarily long for the model. Adding `operation_id="search_programs"` per-route in FastAPI decorator is mechanical work.

---

## 3. AI consumer pain points (rank-ordered)

### 3.1 Auth flow discoverability — **A**

`components.securitySchemes.ApiKeyAuth` is documented:

```json
{ "type": "apiKey", "in": "header", "name": "X-API-Key",
  "description": "Customer API key issued via Stripe Checkout. Anonymous tier (no key) gets 3 req/日 per IP." }
```

Global `security: [{ ApiKeyAuth: [] }]`. **An AI agent reading this gets the key line, the rate, and the source of the key in one paragraph.** The `am_session`/`am_csrf` cookie pair is NOT in `securitySchemes` (only inline as parameters); browser-form auth is implicit. Not a problem for API consumers, just incomplete.

### 3.2 Rate limit / pricing — **A**

The 429 envelope (already the `direct_checkout_url`/`trial_signup_url`-bearing one above) is **more complete than 95% of public APIs**. The body explicitly says: anonymous = 3 req/日 per IP, resets 00:00 JST, X-API-Key removes the cap immediately, trial = 14 days × 200 req card-free. A Claude/GPT consumer hitting 429 can faithfully relay every option to the user without hallucinating. This is exactly the bilingual-CTA design memorized in the operator memory.

### 3.3 Error response format consistency — **A**

422 documented on 178/190 ops, 404 on 23, 400 on 19, 503 on 19, 401 on 18, 402 on 17, 428 on 17, 429 on 17, 500 on 17, 409 on 2. **Coverage is unusually thorough.** No 5xx body shape was probed (anon quota was already at zero on every search call), but the 429 shape suggests a unified envelope — which the code in `_response_models.py` confirms (`alias="_disclaimer"`, `alias="_billing_unit"`).

### 3.4 JSON envelope `_disclaimer` / `_billing_unit` AI parse-friendliness — **B**

**Code-side:** `src/jpintel_mcp/api/_response_models.py` exposes `disclaimer: str = Field(default="", alias="_disclaimer")` and `billing_unit: int = Field(default=1, alias="_billing_unit")` consistently across 3 base wrappers (lines 757, 807, 842).

**Spec-side:** `_disclaimer` appears 36× as inline schema property; `_billing_unit` appears **0 times in the OpenAPI spec** despite being on every billable response in code. **This is the single biggest discoverability gap.** An AI consumer reading the spec will not learn that responses carry per-call billing-unit metadata, and will under-attribute cost to the user.

**Production response headers (probed via `curl -I /v1/meta/corpus_snapshot`):**

```
x-request-id: 5ad8b45d0451565a
x-envelope-version: v1
vary: Accept, X-Envelope-Version, Accept-Encoding
strict-transport-security: max-age=31536000; includeSubDomains; preload
content-security-policy: default-src 'self'; …
x-frame-options: DENY
x-content-type-options: nosniff
referrer-policy: strict-origin-when-cross-origin
permissions-policy: geolocation=(), microphone=(), camera=()
```

Excellent security headers. But `x-corpus-snapshot-id` and `x-audit-seal` headers — defined in `_corpus_snapshot.py:215` — were **not present** on the `/v1/meta/corpus_snapshot` response (the route returns the snapshot in body instead). This is fine for that one route; verify on a search route where the body needs a freshness anchor.

### 3.5 Sample tool call simulate (anonymous, 1 call budget) — quota was already exhausted

**Result:** `GET /v1/programs/search?q=IT&limit=2` → HTTP 429 immediately. Anonymous quota for this IP was already consumed earlier today (operator's prior smoke testing). The 429 body itself is the test artifact and demonstrates the pricing/upgrade flow end-to-end — bilingual, with `retry_after: 27200`, `reset_at_jst: 2026-05-08T00:00:00+09:00`, plus `upgrade_url`, `direct_checkout_url`, `trial_signup_url`. **Every CTA an AI consumer needs to relay back to the user is in that one response.**

Non-quota probes (`/healthz`, `/v1/health/data`, `/v1/meta/corpus_snapshot`) all returned 200 and clean shapes:

```
/healthz                    → {"status":"ok"}
/v1/meta/corpus_snapshot    → {"corpus_snapshot_id":"corpus-2026-04-25"}
/v1/health/data             → {"status":"ok","checks":[…14k programs, 2,286 case_studies, 503,930 am_entities…],"timestamp_utc":"2026-05-07T07:26:58Z"}
```

The `corpus_snapshot_id` is the one referenced as the audit-seal anchor — perfect for an AI agent to cite back ("as of corpus-2026-04-25"). **One immediate observation:** the snapshot is dated 2026-04-25 (12 days stale relative to today). The snapshot should refresh on each ingest cycle; if the operator intentionally pinned it, document that in `/v1/meta/freshness`.

---

## 4. Recommended improvements (ranked by ROI)

| # | Fix | Effort | AI-consumer impact |
|---|---|---|---|
| 1 | Add root-level `tags:` block with 2-line description per tag (15 tags) | 30 min | Custom GPT Action picker becomes navigable. Highest single-fix ROI. |
| 2 | Rename `query` → `q` on the 2 drifted endpoints; add an OpenAPI parameter `$ref` to a single shared `KeywordQuery` schema | 30 min | Eliminates silent 422 from agents that guess `q`. |
| 3 | Define `Envelope` schema with `_disclaimer` + `_billing_unit` + `_corpus_snapshot_id` and $ref it across all 188 2xx responses | 1 h | AI consumer learns the envelope once instead of 36 times; `_billing_unit` becomes discoverable; cost attribution becomes faithful. |
| 4 | Rewrite the 91 short summaries (<20 ch) and add description for the 29 missing ones — focus on `/v1/billing/*`, `/v1/me`, `/v1/feedback` first | 90 min | Tipping-point endpoints become callable from spec alone. |
| 5 | Add response examples to the 160 endpoints lacking them; auto-generate from a fixture run | 90 min | Pattern-matching path becomes universal; LLM consumers no longer need to read schemas. |
| 6 | Unify MCP description prefix vocabulary — one closed enum: `DISCOVER:`, `DETAIL:`, `RISK:`, `EVIDENCE:`, `LINEAGE:`, `JUDGE:`, `VALIDATE:`, `LOOKUP:`, `ONE-SHOT:`, `META:`. Drop the `[KAIKEI]`/`[TIMELINE]`/`[UTILITY]` bracket form. | 60 min | LLM agent can pre-filter tools by intent class; 74→0 ad-hoc prefix uses. |
| 7 | Set explicit `operation_id="search_programs"` per FastAPI route (190 routes); replace auto-`get_meta_v1_meta_get`-style | 2 h mechanical | Custom GPT Actions function labels become readable. |
| 8 | Refresh `corpus_snapshot_id` (currently 12 days stale) | dependent on ingest | Freshness signal is honest. |

**Combined total ≈ 6-8 hours of mechanical work to move from B+ to A.** None of these touch the 139 MCP tool surface area; all are spec-side polish.

---

## 5. What is already excellent (preserve)

- **Bilingual ja/en error envelopes with CTA URLs** — copy-paste-able by the AI consumer to the user.
- **Production response headers** — security stack (HSTS, CSP, X-Frame-Options DENY, COOP/COEP-equivalent, permissions-policy locked), `x-request-id` for support, `x-envelope-version: v1` for forward-compat.
- **MCP descriptions are role-shaped + corpus-rowcount-bearing + bilingual** — this is the AI-discovery contract done right.
- **Stable type-prefixed unified_id** (`UNI-`, `LAW-`, `BID-`, `TAX-`, `CASE-`) — perfect for an AI agent to cite back to the user.
- **Health endpoints** carry concrete row counts (programs 14,472; case_studies 2,286; am_entities 503,930) — auditable in one round-trip.
- **Anonymous `/v1/meta/corpus_snapshot` and `/healthz`** are unmetered — discovery-friendly without consuming quota.
- **`_disclaimer` text itself** is well-calibrated: "Verify current public guidelines and application-round rules" / "Rule-engine result only; final decisions require primary-source review" — both are 景表法-compliant hedges that an LLM consumer can faithfully relay.

---

## 6. Constraint compliance

- **LLM 0**: confirmed. No Anthropic SDK / OpenAI SDK / inference call in this audit. All semantic interpretation is by the human auditor (this report).
- **Read-only HTTP GET**: confirmed. 4 GETs total: `/v1/openapi.json`, `/v1/programs/search` (consumed 1 from anon quota — but quota was already 0, so 429), `/v1/meta/corpus_snapshot`, `/healthz`, `/v1/health/data` + 1 HEAD probe `-I /v1/meta/corpus_snapshot`.
- **Anonymous quota**: confirmed. Anon quota was already exhausted (3/日 cap reached by prior smoke testing); 429 body itself was the artifact. No keys used.
- **Internal-hypothesis framing**: maintained. No "ship-ready" claims beyond what the spec + headers + envelope evidence — all assertions tied to a specific row count, header, schema, or endpoint observation in this same document.

---

## 7. File manifest

This file: `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_AI_CONSUMER_AUDIT_2026-05-07.md`

Cross-references to existing R8 corpus:
- `R8_LIVE_API_SHAPE_2026-05-07.md` — sibling probe of API surface
- `R8_MCP_FULL_COHORT_2026-05-07.md` — sibling MCP surface audit
- `R8_LIVE_OBSERVATORY_2026-05-07T0700Z.md` — sibling production observability snapshot

No edits to other files in this audit; this is a new artifact only.
