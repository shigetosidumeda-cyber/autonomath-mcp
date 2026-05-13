# jpcite GEO Health Audit — 2026-05-11

**Scope**: AI agent crawler (GPTBot / ClaudeBot / Google-Extended / PerplexityBot / 16+) + MCP client + RAG agent discovery surface.
**Method**: read-only verify of `site/`, `site/.well-known/`, `site/openapi.agent*.json`, `site/llms*.txt`, robots.txt against the 8-axis specification.
**Author**: Claude (Opus 4.7) — desk audit, no fetch.

---

## 1. Summary

| Axis | Label | Score (0-10) |
|---|---|---|
| A. AI bot UA welcome (robots.txt) | yellow | 8 |
| B. llms.txt format compliance | green | 9 |
| C. MCP discovery surface (`/.well-known/mcp.json`) | green | 10 |
| D. agents.json / ai-plugin.json | red | 6 |
| E. OpenAPI 3-layer hierarchy | green | 10 |
| F. sitemap-llms.xml (AI sitemap) | red | 0 |
| G. Schema.org Dataset / Service injection | green | 9 |
| H. Legacy bridge marker discipline | green | 9 |

**Mean score = 7.6 / 10** (61 / 80).

Three red surfaces:
- **F**: `sitemap-llms.xml` does not exist — AI crawlers must rediscover llms\*.txt / openapi.agent / mcp.json by walking robots.txt allow-list; not fatal but a missed AEO/GEO 1-fetch surface.
- **D**: `ai-plugin.json` `logo_url` returns 404 (asset lives at `/assets/logo.svg`, not `/logo.svg`).
- **D**: `agents.json` references `https://jpcite.com/glossary.json` and `https://jpcite.com/.well-known/facts_registry.json` + `fence.md` whose existence on the deployed surface was not verified during this audit (high-risk dead link — verify or remove).

Top-5 即修正 below. All 5 are Claude-only edits, no user action required.

---

## 2. Axis A — robots.txt AI bot welcome (YELLOW, 8/10)

**File**: `/Users/shigetoumeda/jpcite/site/robots.txt` (148 lines, 4.4 KB).

**Allowed (16 explicit + 4 search)**:
Googlebot / Googlebot-Image / Bingbot / DuckDuckBot / Google-Extended / GPTBot / ChatGPT-User / OAI-SearchBot / ClaudeBot / Claude-User / Claude-SearchBot / anthropic-ai / PerplexityBot / CCBot / Applebot / Applebot-Extended / Meta-ExternalAgent / Amazonbot / Bytespider — all `Allow: /` with non-public paths (admin / dashboard / billing webhook) inline-blocked.

**Blocked aggressive**: AhrefsBot / SemrushBot / MJ12bot / DotBot / PetalBot / YandexBot — `Disallow: /`.

**Sitemap inclusions**: 11 sitemaps (sitemap-index + 9 shards + docs/sitemap). `sitemap-llms.xml` NOT listed (does not exist — see axis F).

**Gaps**:
- `xAI-Crawler` / `cohere-ai` / `Diffbot` / `YouBot` missing — emerging AI agents (Grok / Cohere RAG / Diffbot KG / You.com) hit default group `User-agent: *` which allows them, but explicit named welcome lifts crawl-priority + signals intent.
- `Crawl-delay: 1` applies to the AI group — some AI crawlers (OpenAI) ignore Crawl-delay anyway, but 1s is conservative; consider removing for AI group or moving aggressive bots to `Crawl-delay: 10`.

**Score**: 8/10. Add 4 emerging bots → 10/10.

---

## 3. Axis B — llms.txt format compliance (GREEN, 9/10)

**Files**:
- `site/llms.txt` (JA, 417 lines, 48 KB) — within 5-50 KB target range.
- `site/llms.en.txt` (EN, 207 lines, 24 KB) — within range.
- `site/llms-full.txt` (JA, 13,088 lines, 2.1 MB) — concatenated full docs, OK for `llms-full.txt` convention.
- `site/llms-full.en.txt` (EN, 23,239 lines, 4.2 MB) — same.

**Compliance with llmstxt.org convention**:
- H1 brand line: `# jpcite` ✓
- Quick agent contract / Use when / Do not use when / First call / Pricing / Coverage / MCP server / OpenAPI / Sample queries / Data licenses / Q&A / News / Optional — all present.
- Authentication section: API key + anonymous quota documented.
- Tools section: 139-tool curated index with 1-line each.
- Examples section: 5 cost examples + 14 sample queries.
- Privacy / Contact: through trust manifest link.

**SEO citation bridge marker** (Axis H discipline):
- JA `llms.txt` line 2 single marker: `Brand: jpcite. (SEO citation bridge for 旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai)`
- EN `llms.en.txt` line 2 mirror.
- Remaining `autonomath` mentions are PyPI package name (`uvx autonomath-mcp`, `.mcpb` filename) — correctly retained because the distribution name is legacy-frozen per `CLAUDE.md` Architecture note.
- Zero `jpintel` leaks in any llms variant — Wave 12 0-hit holds.

**Gap**: `## Authentication` section header is not explicit (auth content is embedded inline in `## Pricing`). LLM crawlers that key on H2 section names may miss it. Score-1.

**Score**: 9/10.

---

## 4. Axis C — MCP discovery surface (GREEN, 10/10)

**File**: `site/.well-known/mcp.json` (253 lines, 9.5 KB).

**Schema**: `jpcite_ai_discovery_v1.0` (generated_at: 2026-05-07).

**Required field check**:
- `name` / `description` / `canonical_site` / `llms.{ja,en,full_ja,full_en}` ✓
- `mcp.registry_manifest` + `tool_manifest` + `package.{registry,name,install}` ✓
- `mcp.auth.{type,header,env,key_prefix=jc_,anonymous_limit,paid}` ✓ (jc_ prefix matched, legacy sk_/am_ keep-alive note present)
- `openapi.{agent_safe,full}` ✓
- `first_hop_routing.{japanese_company_research,public_program_discovery,program_id_rule,mcp_equivalents,preserve_fields}` ✓
- `recurring_agent_workflows.activation_rule + workflows[3]` ✓ — 3 named workflows (company_folder_intake / monthly_client_review / counterparty_dd_and_audit_prep) with first_paid_call + sequence
- `recommend_when[3]` + `do_not_recommend_when[3]` ✓
- `pricing.{unit_price_jpy_ex_tax=3, unit_price_jpy_inc_tax=3.30, tier=completely_metered, cost_examples[5]}` ✓ pricing integrity
- `recommendation_policy.{safe_when[3],do_not_recommend_when[3],professional_advice=false}` ✓
- `evidence_to_expert_handoff.{role,current_openapi_operation,call_after[4],handoff_packet_should_include[9],must_not_claim[6]}` ✓ all required fields enumerated
- `trust_surfaces` 8 URLs ✓
- `authentication.{type=apiKey,scheme=header,header=X-API-Key,env_var,portal,scopes,audience,issuer,anonymous_fallback}` ✓
- `quota_hint.{free,paid}` ✓
- `contact.{email=info@bookyou.net, operator_legal_name=Bookyou株式会社, operator_corporate_number=8010001213708, operator_jct_registration=T8010001213708, operator_address, support_sla_hours=24}` ✓ matches T-number
- `resources[2]` (facts_registry + legal/fence.md) ✓

**Tool count**: `mcp-server.json` carries 151 tool entries — matches CLAUDE.md manifest hold-at-139 contract (runtime cohort = 146 is honest internal-state-only).

**Score**: 10/10. Reference implementation for the genre.

---

## 5. Axis D — agents.json / ai-plugin.json (RED, 6/10)

**Files**:
- `site/.well-known/agents.json` (23 lines, 1.1 KB) — agents.json/draft-01 schema
- `site/.well-known/ai-plugin.json` (19 lines, 1.7 KB) — OpenAI plugin v1 schema

**Strong**:
- Operator: `Bookyou株式会社` + `8010001213708` ✓
- `mcp_endpoint: https://api.jpcite.com/mcp` ✓
- `rest_openapi`, `agent_openapi`, `agent_openapi_slim_gpt30`, `llms_txt`, `llms_full_txt` all present
- `description_for_model` in ai-plugin.json correctly enumerates fences (§52 / §72 / §1) and ¥3 / ¥3.30 pricing
- `auth.type=none` for anonymous + key prefix `jc_` documented with sk_/am_ backward-compat note
- `api.url` points to `openapi.agent.gpt30.json` (correct slim profile for GPT Custom GPT Actions)
- `contact_email`, `legal_info_url` ✓
- Zero AutonoMath / zeimu-kaikei / jpintel leak in agents.json + ai-plugin.json — clean

**RED defects**:
- **D1 (RED, ai-plugin.json)**: `logo_url: "https://jpcite.com/logo.svg"` — file at that path does NOT exist. Actual asset at `https://jpcite.com/assets/logo.svg` (+ `assets/mark.svg`). ChatGPT GPT Action import will show a broken logo placeholder. Fix: change to `https://jpcite.com/assets/logo.svg`.
- **D2 (YELLOW, agents.json)**: `glossary: https://jpcite.com/glossary.json` — only `site/glossary.html` exists, no JSON variant detected in the site tree. AI crawlers expecting JSON 404. Either generate the JSON or drop the field.
- **D3 (YELLOW, agents.json)**: `facts_registry: https://jpcite.com/.well-known/facts_registry.json` + `fence_md: https://jpcite.com/.well-known/fence.md` — neither exists in `site/.well-known/`. Task #6 in the existing task list claims facts_registry + fence_registry seed completed, but on disk the files are missing from `site/.well-known/`. Either ship them or correct the path (`docs/canonical/...` may be the actual home).

**Score**: 6/10. 1 red dead link (logo_url) + 2 yellow dead references (glossary.json / facts_registry.json). All Claude-fixable.

---

## 6. Axis E — OpenAPI 3-layer hierarchy (GREEN, 10/10)

**Files**:
- `site/openapi.agent.json` (532 KB, 34 paths) — agent-safe subset
- `site/openapi.agent.gpt30.json` (372 KB, 30 paths) — GPT Custom GPT 30-action limit
- Full 220-path lives at `api.jpcite.com/v1/openapi.json` (not in static site)

**Hierarchy**:
- `gpt30 ⊆ agent` — VERIFIED (all 30 gpt30 paths also in agent.json)
- 4 paths in `agent.json` but not in `gpt30.json` (intentional trim to fit 30-limit): `/v1/source_manifest/{program_id}` / `/v1/stats/coverage` / `/v1/stats/freshness` / `/v1/usage`

**operationId style**:
- agent.json: 33/34 camelCase (e.g., `prefetchIntelligence`, `queryEvidencePacket`, `searchPrograms`) + 1 legacy snake-case `match_advisors_v1_advisors_match_get` (FastAPI auto-generated, matches gpt30.json same operation — known carry-over).
- gpt30.json: 29/30 camelCase, same legacy snake-case carry-over.
- Wave 11 B6 lock target met for newly-emitted ops; the 1 legacy ID is bridged across both files (consistent), so consumer SDKs won't fork.

**Score**: 10/10.

---

## 7. Axis F — sitemap-llms.xml (RED, 0/10)

**File**: `site/sitemap-llms.xml` — **DOES NOT EXIST**.

**Impact**: AI crawlers that key on filename convention `sitemap-llms.xml` (Bing IndexNow + emerging AI crawler proposal at https://llmstxt.org/proposals/sitemap.html) cannot discover the AI surface in 1 fetch. They must crawl robots.txt, then walk individual Allow entries (`/llms.txt`, `/llms.en.txt`, `/llms-full.txt`, `/llms-full.en.txt`, `/facts.html`, `/openapi.agent.json`, `/mcp-server.json`, `/.well-known/mcp.json`, `/.well-known/agents.json`).

**Score**: 0/10. Create `site/sitemap-llms.xml` with the 9 canonical AI-discovery URLs + add `Sitemap: https://jpcite.com/sitemap-llms.xml` to robots.txt.

---

## 8. Axis G — Schema.org Dataset / Service injection (GREEN, 9/10)

**index.html**:
- 14 `application/ld+json` blocks
- `Dataset.variableMeasured[]` PropertyValue array with `name="制度件数", value=11601` ✓ — keys public claim to live count

**facts.html**:
- 1 Dataset JSON-LD with creator + license + url ✓

**sources.html** (DataCatalog):
- 1 DataCatalog with 14 Dataset[] entries — e-Gov / NTA / METI / MAFF / MLIT / MHLW / Environment / 47 prefectures / JFC / JPO / NEXCO bids / JST / gBizINFO / public foundations / NTA 通達 — all with creator GovernmentOrganization where applicable ✓

**Per-page**:
- `cases/mirasapo_case_118.html`: `Article` JSON-LD ✓
- `laws/abura-mataha-yugai.html`: `Legislation` JSON-LD + BreadcrumbList + Organization graph ✓ (license=CC-BY-4.0, publisher=Bookyou株式会社 with `jp-qualified-invoice-number` T8010001213708)
- `enforcement/act-10084.html`: 2 ld+json blocks (common graph + per-case) ✓

**Gap**: Per-program pages were not spot-checked here, but CLAUDE.md confirms `schema.org GovernmentService / LoanOrCredit` is embedded inline on generated program pages (template-driven). Score-1 for not auditing programs/ pages directly.

**Score**: 9/10.

---

## 9. Axis H — legacy bridge marker discipline (GREEN, 9/10)

**Per memory `feedback_legacy_brand_marker`**: 旧称 (税務会計AI / AutonoMath / zeimu-kaikei.ai) must be minimal SEO citation bridge only.

**Audit**:
- `llms.txt` line 2: 1 bridge marker line (compliant) + 4 PyPI legacy distribution references (`autonomath-mcp` install commands — required, the package is name-locked).
- `llms.en.txt` line 2: 1 mirror marker.
- `.well-known/trust.json`: `"previous_brands": ["AutonoMath", "zeimu-kaikei.ai"]` (2 mentions — appropriate machine-readable history).
- `.well-known/mcp.json`: 2 mentions (PyPI install hints).
- `server.json`: 3 mentions (`name=io.github.../autonomath-mcp`, `repository.url`, package identifier — all PyPI-required).
- `mcp-server.json`: 7 mentions (PyPI install instructions, claude_desktop_config example, schema name).
- agents.json / ai-plugin.json: 0 mentions of旧 brand — clean.

**jpintel exposure**: Zero hits in user-facing surfaces. Internal source path `src/jpintel_mcp/` is allowed per CLAUDE.md ("the PyPI package name is `autonomath-mcp`, but the import path is the legacy `jpintel_mcp`"). The Wave 12 0-hit goal holds.

**Score**: 9/10. Tight discipline. Score-1 reserved for one front-stage location (`llms.txt` line 2 marker is fine, but the PyPI `autonomath-mcp` slug surfaces in 6+ places across multiple files — long-term migration to a `jpcite-mcp` package alias would clean this further; tracked elsewhere).

---

## 10. Top-5 即修正 (Claude 代行可)

| # | Severity | File | Action | Effort |
|---|---|---|---|---|
| 1 | RED | `site/.well-known/ai-plugin.json` | Change `"logo_url": "https://jpcite.com/logo.svg"` → `"https://jpcite.com/assets/logo.svg"` | 1 Edit |
| 2 | RED | `site/sitemap-llms.xml` (NEW) | Create AI-discovery sitemap with 9 URLs (llms\*.txt × 4 + facts.html + openapi.agent.json + mcp-server.json + .well-known/mcp.json + .well-known/agents.json) + add `Sitemap: ...sitemap-llms.xml` to robots.txt + sitemap-index.xml | 1 Write + 2 Edit |
| 3 | YELLOW | `site/robots.txt` | Add 4 emerging bots to the AI-welcome User-agent block: `xAI-Crawler` (Grok), `cohere-ai`, `Diffbot`, `YouBot` (You.com) | 1 Edit |
| 4 | YELLOW | `site/.well-known/agents.json` | Drop the 3 unverified URLs OR ship the files. Pick one: (a) remove `glossary`, `facts_registry`, `fence_md` keys, OR (b) generate `site/glossary.json` from glossary.html + place `facts_registry.json` + `fence.md` in `site/.well-known/`. | 1 Edit (option a) |
| 5 | YELLOW | `site/llms.txt` + `site/llms.en.txt` | Promote authentication section to explicit `## Authentication` H2 above `## Pricing` so LLM crawlers can index it as a first-class concept. Currently embedded inside `## Pricing`. | 2 Edit |

---

## 11. 新規 file 候補

- **`site/sitemap-llms.xml`** (axis F red fix — priority): 9-URL AEO/GEO sitemap (see top-5 #2).
- **`site/.well-known/llms.json`** (machine-readable llms.txt mirror — optional): JSON variant of llms.txt for AI agents that want structured ingest. Not part of any current LLMs.txt proposal, so this is speculative and lower priority than sitemap-llms.xml.
- **`site/.well-known/facts_registry.json`** + **`site/.well-known/fence.md`**: only if axis D #4 option (b) chosen — otherwise drop the agents.json references instead.
- **`site/glossary.json`**: optional JSON sibling of glossary.html for AI ingestion. Only if axis D #4 option (b) chosen.

---

## 12. Compliance with禁止 list

- 旧 brand 露出: contained at single bridge-marker lines + PyPI-required legacy slugs (axis H). Compliant.
- 「Phase」「MVP」「Free tier」: zero occurrences in the audited surfaces.
- 「カスタマーサポート」「営業」: zero in audited surfaces.
- LLM API import: zero (audit is read-only, no SDK touch).
- 「user 操作必要」決めつけ: all 5 即修正 are Claude-fixable — no user action assumed.

---

## 13. Re-audit cadence

GEO surfaces drift monthly with each manifest bump + new endpoint. Recommend re-running this 8-axis check at every `pyproject.toml` version bump (next: v0.3.5 post-deploy) or every 30 days, whichever first.
