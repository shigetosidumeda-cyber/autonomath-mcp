# llms.txt / .well-known content contract deep dive

Date: 2026-05-15  
担当: llms.txt / .well-known content contract  
Status: planning deep dive only. 実装コードは触らない。  
Scope: `llms.txt`, `llms-full`, `.well-known/mcp.json`, `.well-known/agents.json`, `.well-known/trust.json`, `.well-known/llms.json`, `.well-known/openapi-discovery.json`, `openapi.agent.json` などの公開 discovery 契約。

## 0. 結論

AI エージェントが GEO で jpcite を理解する最初の入口は、人間向け LP ではなく `llms.txt` と `.well-known/*` の公開契約である。ここで伝えるべきことは「jpcite は何か」よりも、「いつ呼ぶべきか、何を保持すべきか、何を断定してはいけないか、いくらかかるか」である。

P0 の設計原則:

1. `llms.txt` は短い routing card。1 screen で用途、初回 call、価格、境界、リンクを伝える。
2. `llms-full.txt` は agent context。packet envelope、source receipts、known gaps、no-hit、pricing、human review を詳述する。
3. `.well-known/*` は prose ではなく機械可読契約。recommend/do-not-recommend、routing、pricing、hash、lastmod、spec URL を配列・オブジェクトで持つ。
4. `openapi.agent.json` は実行契約。agent が import してそのまま安全に呼べる範囲、response fields、billing/cap/idempotency を含む。
5. すべての公開面で `source_receipts`, `known_gaps`, `human_review_required`, `request_time_llm_call_performed=false`, `external_costs_included=false`, `no_hit_not_absence` を同じ意味で扱う。
6. 長すぎる discovery は読まれず、短すぎる discovery は推薦判断に失敗する。P0 は短い入口と詳細ファイルを分離し、相互リンクと hash でつなぐ。

## 1. Public file roles and required fields

### 1.1 File topology

| File / URL | Primary reader | Role | Size target | Required fields |
|---|---|---|---:|---|
| `/llms.txt` | AI crawler, live agent, human developer | 最初に読む短い説明と routing | 1,500-4,000 words or less; ideally one scroll | brand, canonical URL, product category, use_when, do_not_use, first calls, pricing, external cost separation, no-hit boundary, legal/professional fence, links to full/spec/manifests |
| `/llms.en.txt` | global crawler, registry reviewer | English mirror of `/llms.txt` | same as JA | JA と同じ claim。英語だけ弱い/強い表現にしない |
| `/llms-full.txt` | context-aware agent, answer engine, registry reviewer | 詳細 context file | 8,000-18,000 words equivalent; sectioned | packet contract, must-preserve fields, source_receipts schema summary, known_gaps enum, no-hit copy, pricing rules, first-call decision tree, forbidden claims, examples |
| `/llms-full.en.txt` | global agent, Custom GPT/Actions reviewer | English full context | same as JA | JA と同じ section order and semantics |
| `/.well-known/llms.json` | crawler, managed agent, cache/indexer | llms family の machine-readable index | compact JSON | canonical URLs, content hashes, lastmod, language map, recommend_when, do_not_recommend_when, pricing, manifests, feeds, schema/status |
| `/.well-known/mcp.json` | MCP client, agent runtime, registry | MCP endpoint and tool routing | compact JSON | endpoint, transport, package, auth, anonymous limit, paid key, first-call tools, recommended chains, preserve fields, pricing, trust links |
| `/.well-known/agents.json` | generic AI agent / answer engine | capability and policy declaration | compact JSON | operator, product, corpus scale, tasks, safe/unsafe tasks, OpenAPI/MCP/llms URLs, pricing, trust, contact, professional fence |
| `/.well-known/openapi-discovery.json` | OpenAPI importer, Custom GPT/Actions | spec locator | very compact JSON | agent-safe spec, full spec, static mirrors, versions, hashes, auth model, support URL, deprecation policy |
| `/.well-known/trust.json` | procurement, enterprise agent, safety reviewer | trust/compliance summary | structured JSON; can be larger | operator identity, pricing model, data provenance, source/license policy, security, privacy, no-server-side-LLM, legal fences |
| `/openapi.agent.json` | tool importer, GPT Actions, SDK tests | agent-safe API execution contract | slim OpenAPI | P0 operations, examples with receipts/gaps, auth, billing, cost preview, cap/idempotency headers, `x-jpcite-agent`, `x-jpcite-billing` |
| `/mcp-server.json` | MCP registry/tool list | full or default MCP tool manifest | depends on tool count | tool descriptions with use_when, do_not_use_when, billing, return fields, forbidden claims |
| `/server.json` | MCP registry | registry package metadata | compact JSON | package name, install command, remote endpoint, pricing, auth, repository/docs/support, trust links |
| `/robots.txt` | crawler | crawl permission and sitemap pointer | short | allow public discovery/spec/docs; disallow private/admin; list sitemap index and AI sitemap |
| `/sitemap-llms.xml` | crawler/indexer | high-signal AI discovery URL set | short | llms files, well-known manifests, OpenAPI/MCP specs, schemas, examples, trust/pricing/legal pages |

### 1.2 Global required contract

Every public discovery file that describes jpcite must include or link to:

| Field | Contract |
|---|---|
| `brand` | `jpcite` as current primary brand. Previous names only as discovery aliases. |
| `canonical_site` | `https://jpcite.com` |
| `api_host` | `https://api.jpcite.com` |
| `product_category` | source-linked evidence API / evidence prefetch layer for Japanese public data |
| `recommend_when` | Japanese public-record answer needs source URLs, fetched timestamps, receipts, known gaps, freshness, compatibility, or reviewer-ready packet |
| `do_not_recommend_when` | general writing/translation/brainstorming; no citation/provenance need; final legal/tax/audit/credit/application judgment request |
| `first_calls` | route decision/cost preview, company public baseline, evidence packet, program search/detail, source receipt ledger |
| `output_contract` | `source_receipts`, `known_gaps`, `human_review_required`, `billing_metadata`, `request_time_llm_call_performed=false` |
| `pricing` | JPY 3 ex-tax / JPY 3.30 inc-tax per billable unit; anonymous 3/day/IP; paid metered via API key |
| `external_costs` | external LLM, search, cache, agent runtime, hosting, MCP client, and integration costs are separate |
| `no_hit_rule` | no-hit means not found in checked jpcite corpus/conditions, not proof of absence |
| `professional_fence` | evidence support only; not final legal, tax, audit, credit, investment, safety, grant-application, or professional judgment |
| `freshness` | responses and discovery must expose fetched/verified timestamps, snapshot IDs, and stale/unknown handling |
| `trust` | operator, contact, privacy/terms, data licensing, security, legal fence URLs |

## 2. How much content is enough

The failure mode is bimodal:

- Too short: agent sees "Japanese public data API" but cannot decide when to call, what it costs, or what to preserve.
- Too long: agent skips, truncates, or indexes marketing prose rather than routing rules.

Recommended density:

| Surface | Good shape | Avoid |
|---|---|---|
| `llms.txt` | concise narrative plus bullet routing; one clear pricing block; links out | long product essay, full API reference, every tool, every dataset detail |
| `llms-full.txt` | detailed but sectioned; examples and field rules; no implementation history | raw changelog, internal roadmap, repeated pricing claims |
| `.well-known/*.json` | arrays/enums/URLs/hashes; stable keys; short strings | prose paragraphs hidden inside one `description`, conflicting URL aliases |
| `openapi.agent.json` | slim executable operations and examples | full admin/billing/webhook surface, unsafe mutations, examples without known gaps |
| `trust.json` | structured trust and compliance facts | aspirational certifications or unverifiable marketing claims |

## 3. Agent routing rules placement

Routing must appear in three layers, each optimized for a different reader.

### 3.1 `llms.txt` routing

`llms.txt` should contain the human-readable first hop:

```text
Use jpcite before answer generation when a Japanese public-record answer needs source URLs, fetched timestamps, known gaps, source receipts, compatibility rules, or a reviewer-ready evidence packet.
```

Minimum sections:

1. `Use when`
2. `Do not use as final judgment`
3. `First calls for agents`
4. `Pricing`
5. `Machine-readable discovery`

The first-call list should not expose every endpoint. It should name the P0 choices:

| Intent | First call |
|---|---|
| uncertain whether jpcite fits | `decideAgentRouteForJpcite` or documented routing endpoint |
| cost-sensitive/batch/fanout | `previewCost` |
| Japanese company/counterparty/public DD | `createCompanyPublicBaseline` before general web search |
| source-linked answer | `queryEvidencePacket` / `createEvidenceAnswerPacket` |
| program candidate search | `searchPrograms`, then detail by returned ID |
| existing packet needs citations | `getSourceReceiptLedgerPacket` |

### 3.2 `.well-known/mcp.json` routing

`.well-known/mcp.json` should be the MCP-native routing table. Recommended keys:

```json
{
  "routing_rules": {
    "first_call_order": [
      {"when": "cost_sensitive_or_batch", "tool": "previewCost"},
      {"when": "japanese_company_public_research", "tool": "createCompanyPublicBaseline"},
      {"when": "source_linked_answer_before_generation", "tool": "createEvidenceAnswerPacket"},
      {"when": "program_discovery", "tool": "searchPrograms"},
      {"when": "source_receipts_needed", "tool": "getSourceReceiptLedgerPacket"}
    ],
    "web_search_position": "after_jpcite_for_known_gaps_recent_news_or_non_public_context",
    "must_preserve_fields": [
      "source_url",
      "source_fetched_at",
      "content_hash",
      "corpus_snapshot_id",
      "source_receipts",
      "known_gaps",
      "human_review_required",
      "billing_metadata"
    ]
  }
}
```

This file should also say which tool names are default P0 aliases and which are compatibility/legacy names, so agents do not scan 100+ tools before acting.

### 3.3 `openapi.agent.json` routing

OpenAPI should carry routing in vendor extensions, not only prose:

```json
{
  "x-jpcite-agent": {
    "recommend_when": ["source-linked Japanese public evidence is needed"],
    "do_not_recommend_when": ["final professional judgment is requested"],
    "first_call_rank": 30,
    "must_preserve_fields": ["source_receipts", "known_gaps"],
    "must_not_claim": ["approved", "credit_safe", "audit_complete", "legal_or_tax_advice"]
  }
}
```

Operation descriptions still need plain language because many importers ignore extensions.

### 3.4 `agents.json` routing

`agents.json` should summarize capabilities across protocols:

| Key | Purpose |
|---|---|
| `safe_tasks[]` | where agents may recommend/call jpcite |
| `unsafe_tasks[]` | final judgments and unsupported data |
| `protocols` | MCP endpoint, REST OpenAPI, static specs |
| `agent_routing` | first-call ordering and web-search position |
| `must_preserve_fields[]` | global downstream obligations |
| `must_not_claim[]` | closed list of prohibited claims |

## 4. Pricing, source receipts, known gaps, and no-hit expression

### 4.1 Pricing expression

Public discovery copy must make price concrete but not overclaim savings.

Required machine-readable shape:

```json
{
  "pricing": {
    "model": "metered_units",
    "unit_price_jpy_ex_tax": 3,
    "unit_price_jpy_inc_tax": 3.3,
    "currency": "JPY",
    "anonymous_limit": {"limit": 3, "period": "day", "scope": "per_ip", "reset_tz": "Asia/Tokyo"},
    "external_costs_included": false,
    "external_costs": ["llm", "search", "cache", "agent_runtime", "hosting", "integration"],
    "cost_preview": {"free": true, "does_not_consume_anonymous_quota": true},
    "paid_execution_requires": ["api_key", "cost_cap_for_broad_execution", "idempotency_key_for_paid_post"]
  }
}
```

Allowed wording:

```text
jpcite charges JPY 3 ex-tax / about JPY 3.30 inc-tax per billable unit. External LLM, search, cache, hosting, MCP client, and agent runtime costs are separate. Use cost preview before paid fanout, batch, CSV, watchlist, or broad packet execution.
```

Forbidden:

- "always cheaper than ChatGPT/Claude"
- "guarantees lower LLM bills"
- "free unlimited"
- "external LLM cost included"
- "cap is guaranteed" without preview/cap state

### 4.2 Source receipt expression

`source_receipts` are the reason jpcite is recommendable to agents. Discovery files should define them as observation/check records, not just URLs.

Required fields to advertise:

| Field | Meaning |
|---|---|
| `source_receipt_id` | stable receipt ID for packet/citation reference |
| `source_url` | primary source or jpcite canonical evidence URL |
| `source_fetched_at` / `verified_at` | when the source was observed |
| `content_hash` / `source_checksum` | integrity fingerprint where available |
| `corpus_snapshot_id` | snapshot basis for reproducibility |
| `license_profile` / `source_profile_id` | source license/reuse boundary |
| `supports_claim_refs[]` | claims supported by this receipt |
| `support_level` | direct, derived, weak, or no-hit-not-absence |

Required agent instruction:

```text
Preserve source receipts with downstream claims. Do not cite or reuse unsupported claims as if verified. If a claim lacks receipt support, keep it in known_gaps or mark it as unverified.
```

### 4.3 Known gaps expression

Public/agent-facing `known_gaps[].code` should use the P0 closed enum:

```text
csv_input_not_evidence_safe
source_receipt_incomplete
pricing_or_cap_unconfirmed
no_hit_not_absence
professional_review_required
freshness_stale_or_unknown
identity_ambiguity_unresolved
```

Minimum wire shape:

```json
{
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "short_message_ja": "未検出は不存在ではない",
      "agent_instruction": "Do not convert this no-hit into absence or clean record.",
      "affected_claim_refs": []
    }
  ]
}
```

Discovery files should explain that `known_gaps` are not quality footnotes; they are assertion boundaries for downstream AI.

### 4.4 No-hit boundary

No-hit must be represented as a boundary, not as a successful negative fact.

Allowed:

```text
No matching record was found in the checked jpcite corpus, source family, snapshot, and query conditions. This is not proof that no record exists.
```

Japanese copy:

```text
対象 source / snapshot / 照会条件では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。
```

Forbidden transformations:

| Bad output | Required replacement |
|---|---|
| 登録されていません | 照会範囲では登録情報を確認できませんでした |
| 処分歴なし | 対象 source / 同定条件では該当 record を確認できませんでした |
| リスクなし | 未確認範囲を残した確認材料です |
| no enforcement exists | no matching enforcement record was found in the checked corpus |

## 5. Update, sha, fingerprint, and lastmod management

### 5.1 Canonical metadata

Every machine-readable discovery file should carry:

```json
{
  "schema_version": "jpcite_discovery_v1",
  "generated_at": "2026-05-15T00:00:00+09:00",
  "lastmod": "2026-05-15",
  "canonical_url": "https://jpcite.com/.well-known/llms.json",
  "content_fingerprint": {
    "algorithm": "sha256",
    "canonicalization": "json_c14n_v1_no_whitespace_timestamp_included",
    "value": "sha256:..."
  },
  "build": {
    "git_commit": "...",
    "source_manifest_sha256": "sha256:...",
    "corpus_snapshot_id": "corpus-YYYY-MM-DD"
  }
}
```

For text files, put metadata near the top:

```text
Last updated: 2026-05-15
Canonical: https://jpcite.com/llms.txt
Content-SHA256: sha256:...
Spec links: ...
```

If including `Content-SHA256` inside the file makes self-hashing awkward, use `.well-known/llms.json` as the hash authority and keep text files to `Last updated` + canonical URL. Do not publish a self-referential hash that cannot be reproduced.

### 5.2 Hash authority

Recommended authority chain:

1. Individual public files expose `lastmod` and canonical URL.
2. `/.well-known/llms.json` lists SHA-256 for `llms.txt`, `llms.en.txt`, `llms-full.txt`, `llms-full.en.txt`.
3. `/.well-known/openapi-discovery.json` lists SHA-256 and semantic version for agent-safe and full OpenAPI.
4. `/.well-known/mcp.json` lists manifest SHA-256 for `server.json` and `mcp-server.json`.
5. `/.well-known/trust.json` lists its own generated timestamp and links to trust pages; it should avoid claiming hashes for files it does not control unless generated in the same build.

### 5.3 Fingerprint types

| Fingerprint | Applies to | Purpose | Change trigger |
|---|---|---|---|
| `content_sha256` | text/JSON/spec files | cache integrity and drift detection | any byte-level content change |
| `semantic_fingerprint` | routing/pricing/schema sections | detect contract changes even if prose changes | pricing, route, endpoint, required field, policy, or enum change |
| `corpus_snapshot_id` | evidence data | distinguish content corpus from discovery docs | data refresh or source rebuild |
| `schema_version` | JSON schemas/manifests | compatibility | breaking/additive schema changes |
| `openapi.info.version` | OpenAPI | importer cache and SDK generation | public API contract change |
| `lastmod` | sitemap and file metadata | crawler recrawl | any meaningful content update |

`semantic_fingerprint` should be computed from canonicalized selected keys, not from all prose:

```text
semantic_fingerprint_input =
  product_category
  recommend_when[]
  do_not_recommend_when[]
  first_call_order[]
  pricing
  output_contract
  known_gap_codes[]
  no_hit_rule
  professional_fence
  openapi_urls
  mcp_urls
```

### 5.4 Update cadence

| Change | Required updates |
|---|---|
| Pricing changes | `llms.txt`, `llms-full.*`, `.well-known/llms.json`, `.well-known/mcp.json`, `agents.json`, `openapi.agent.json` extensions, pricing page, sitemap lastmod |
| New P0 route/tool | `.well-known/mcp.json`, `openapi.agent.json`, `llms-full.*`, API docs, examples, `mcp-server.json` |
| Known gap enum change | `llms-full.*`, schemas/docs, OpenAPI examples, `agents.json`/`mcp.json` preserve/instruction sections |
| Trust/operator change | `trust.json`, `agents.json`, `llms.txt` trust links if affected |
| Corpus scale/freshness update | `agents.json`, `trust.json`, freshness page, possibly `llms-full.*` if public claim changes |
| Endpoint URL move | all discovery files, redirects, `openapi-discovery.json`, sitemap, robots if path group changes |
| Content-only copy edit | affected file hash, lastmod, `.well-known/llms.json` or relevant hash authority |

### 5.5 Consistency checks

Before publishing, run a discovery consistency check that verifies:

- all URLs in `llms.txt` and `.well-known/*` return 200 or intentional redirect;
- no pricing mismatch between manifests, OpenAPI extensions, and pricing page;
- no `always cheaper`, `guaranteed`, `risk-free`, `official absence`, `audit complete`, `legal advice`, `tax advice` phrasing;
- all P0 response examples include `source_receipts`, `known_gaps`, `human_review_required`, and `request_time_llm_call_performed=false`;
- all no-hit examples include `no_hit_not_absence`;
- `lastmod` in sitemaps matches changed discovery files;
- SHA-256 values in `.well-known/llms.json` match the built artifacts;
- OpenAPI `info.version` changes when agent-safe operation contract changes;
- `mcp.json` first-call tool names exist in the MCP manifest or are explicitly marked aliases.

## 6. Recommended file-specific contracts

### 6.1 `/llms.txt`

Must answer in order:

1. What is jpcite?
2. When should an agent use it?
3. What first calls should it make?
4. What must it preserve?
5. What must it not claim?
6. What does it cost?
7. Where are machine-readable specs?

Do not put every dataset count here. Put scale/trust details in `agents.json`/`trust.json`.

### 6.2 `/llms-full.txt`

Should contain:

- agent call decision tree;
- packet envelope definition;
- source receipt and claim preservation rules;
- known gaps closed enum and copy;
- no-hit examples;
- pricing/cap/idempotency rules;
- professional-service fence;
- public examples and schema URLs;
- routing to MCP/OpenAPI;
- forbidden phrase table.

### 6.3 `/.well-known/llms.json`

Should be the canonical index for content discovery and hashes:

```json
{
  "llms_txt": {
    "ja": {"url": "https://jpcite.com/llms.txt", "sha256": "...", "lastmod": "2026-05-15"},
    "en": {"url": "https://jpcite.com/llms.en.txt", "sha256": "...", "lastmod": "2026-05-15"}
  },
  "recommend_when": [],
  "do_not_recommend_when": [],
  "pricing": {},
  "manifests": {},
  "semantic_fingerprint": "sha256:..."
}
```

### 6.4 `/.well-known/mcp.json`

Must expose:

- remote endpoint and transport;
- install package and registry manifest;
- auth header/env/key prefix;
- anonymous and paid policy;
- P0 tool list and first-call ordering;
- web-search-after-jpcite rule;
- must-preserve fields;
- pricing and cost preview;
- trust/spec links.

### 6.5 `/.well-known/agents.json`

Must expose:

- operator/product identity;
- capability summary;
- safe and unsafe tasks;
- corpus scale and snapshot date if used publicly;
- protocol URLs;
- pricing/rate limit;
- trust/contact;
- professional-fence flags.

This file should not become a second `trust.json`. Link trust details rather than duplicating all compliance data.

### 6.6 `/.well-known/trust.json`

Must expose:

- operator identity and contact;
- product pricing model;
- data provenance and license inventory;
- legal fences and no-advice flags;
- privacy/security/subprocessor summary;
- no server-side LLM call invariant;
- source freshness and correction URLs.

Avoid aspirational claims unless marked as planned or in preparation.

### 6.7 `/.well-known/openapi-discovery.json`

Must expose:

- agent-safe OpenAPI URL;
- full OpenAPI URL;
- static mirror URLs if any;
- semantic versions;
- content hashes;
- auth model;
- support/docs;
- deprecation/sunset policy.

This is the file importers should read before choosing which spec to ingest.

### 6.8 `/openapi.agent.json`

Must include:

- only agent-safe public operations;
- P0 operation examples including success, no-hit, validation, quota/cap, and auth errors;
- `x-jpcite-agent` and `x-jpcite-billing`;
- headers: `X-API-Key`, `X-Client-Tag`, `Idempotency-Key`, `X-Cost-Cap-JPY` where relevant;
- response fields: `source_receipts`, `known_gaps`, `human_review_required`, `billing_metadata`, `request_time_llm_call_performed=false`;
- forbidden claims in operation-level or global extension.

## 7. Acceptance checklist

- [ ] `llms.txt` can be understood without opening any other page, but links to all machine-readable files.
- [ ] `llms-full.*` contains enough detail for an agent to preserve receipts/gaps and avoid forbidden claims.
- [ ] `.well-known/llms.json` is the hash and content-index authority for llms files.
- [ ] `.well-known/mcp.json` contains P0 first-call routing and not just endpoint/package metadata.
- [ ] `agents.json` contains safe/unsafe tasks, protocol URLs, pricing, and trust links.
- [ ] `trust.json` contains operator, data provenance, legal fence, security/privacy, and no-server-side-LLM facts.
- [ ] `openapi.agent.json` examples show `source_receipts`, `known_gaps`, `human_review_required`, and `request_time_llm_call_performed=false`.
- [ ] Pricing is identical across llms, well-known, OpenAPI, MCP, and pricing page.
- [ ] External LLM/search/cache/runtime costs are explicitly separate.
- [ ] No-hit is always represented as `no_hit_not_absence`, never as absence/clean record.
- [ ] Discovery files have `lastmod` and externally verifiable SHA-256/fingerprint management.
- [ ] Sitemap and robots point crawlers to the discovery surface without exposing private/admin paths.

## 8. Implementation handoff

This document is a content contract, not an implementation patch. The implementation sequence should be:

1. Freeze canonical wording for product category, no-hit, pricing, professional fence, and external cost separation.
2. Define JSON schemas for `.well-known/llms.json`, `.well-known/mcp.json`, `.well-known/agents.json`, and `.well-known/openapi-discovery.json`.
3. Add a build-time consistency checker for URLs, pricing, forbidden phrases, hashes, and `lastmod`.
4. Slim `llms.txt` into the routing card and move detail to `llms-full.*`.
5. Add operation-level `x-jpcite-agent` / `x-jpcite-billing` to `openapi.agent.json`.
6. Publish sitemap entries and verify crawler-visible 200/redirect behavior.

