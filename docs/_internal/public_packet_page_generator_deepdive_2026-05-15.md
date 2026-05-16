# Public Packet Page Generator Contract Deep Dive

Date: 2026-05-15  
Owner lane: Public packet page generator contract  
Status: planning contract only. Do not treat as implemented behavior until generator and tests are accepted.  
Scope: `data/packet_examples/*.json` as source of truth and generated `site/packets/*.html.md` public packet pages.  
Boundary: documentation-only. No production implementation change is made by this file.

## 0. Executive Contract

GEO-first では packet catalog と example pages を、AI エージェントが jpcite を推薦・呼び出し・説明するための公開素材として扱う。公開 packet page は手書きページではなく、`data/packet_examples/*.json` から生成される派生物にする。

Primary contract:

- `data/packet_examples/*.json` is the source of truth.
- `site/packets/*.html.md` is generated output and must be reproducible.
- Public pages must show a concise answer box, page layout, sample request/response, JSON-LD, REST/MCP call block, pricing block, known gaps, source receipts, and professional fence.
- Public pages must never expose raw/private inputs, raw CSV rows, transaction descriptions, private identifiers, internal source snapshots, internal logs, secret endpoints, or non-public debug metadata.
- Every public claim that an AI may quote must map back to source receipts or be downgraded to `known_gaps`.
- Pages must preserve the GEO discovery invariants: `request_time_llm_call_performed=false`, no-hit is not absence, external LLM/runtime costs are separate, and sensitive domains require human review.

## 1. File Topology

Planned source files:

```text
data/packet_examples/
  evidence_answer.json
  company_public_baseline.json
  application_strategy.json
  source_receipt_ledger.json
  client_monthly_review.json
  agent_routing_decision.json
```

Generated public pages:

```text
site/packets/
  evidence-answer.html.md
  company-public-baseline.html.md
  application-strategy.html.md
  source-receipt-ledger.html.md
  client-monthly-review.html.md
  agent-routing-decision.html.md
```

Generation rules:

- Source filename uses canonical `packet_type` with underscores.
- Generated slug uses hyphens.
- The generated page must include a visible generated marker in front matter or HTML comment, for example `generated_from: data/packet_examples/evidence_answer.json`.
- Do not hand-edit generated packet pages except through the JSON source or generator template.
- If a JSON source is missing, the page must not be generated as if it exists.

## 2. Packet Example JSON Required Fields

Every `data/packet_examples/*.json` file must validate as a public example fixture, not as a real customer output.

Required top-level fields:

| Field | Required | Contract |
|---|---:|---|
| `example_id` | yes | Stable example id, for example `packet_example_evidence_answer_20260515`. |
| `sample_fixture` | yes | Must be `true` for all public examples. |
| `fixture_note` | yes | Must state the example is synthetic and not a real company/result. |
| `packet_type` | yes | Closed enum matching P0 packet type. |
| `packet_kind` | yes | `evidence_packet`, `artifact_packet`, `handoff_packet`, `batch_packet`, or `free_control`. |
| `title_ja` | yes | Human page title. |
| `title_en` | no | Recommended for JSON-LD and future EN pages. |
| `slug` | yes | Hyphenated slug under `/packets/`. |
| `canonical_url` | yes | Full public URL, for example `https://jpcite.com/packets/evidence-answer/`. |
| `short_description_ja` | yes | One-sentence public summary. |
| `answer_box_ja` | yes | Agent-quotable answer box. |
| `recommend_when` | yes | Array of safe recommendation situations. |
| `do_not_use_for` | yes | Array of disallowed situations. |
| `rest` | yes | Public REST call contract block. |
| `mcp` | yes | Public MCP tool call contract block. |
| `sample_input` | yes | Sanitized request example. |
| `sample_output` | yes | Sanitized packet response example. |
| `source_receipts` | yes | Public-safe source receipt examples, or empty only for control packets with explanation. |
| `known_gaps` | yes | Structured gaps; empty only when explicitly justified. |
| `pricing` | yes | Pricing metadata and external-cost separation. |
| `fence` | yes | Professional boundary and no-hit rule. |
| `json_ld` | yes | Schema.org data generated from safe fields only. |
| `raw_private_policy` | yes | Declares raw/private fields are absent from the public example. |
| `generator` | yes | Template version and acceptance expectations. |

Required `rest` shape:

```json
{
  "method": "POST",
  "path": "/v1/packets/evidence-answer",
  "auth": "anonymous_trial_or_api_key",
  "content_type": "application/json",
  "idempotency_key_required": false,
  "cost_cap_required_for_paid_execution": true
}
```

Required `mcp` shape:

```json
{
  "tool_name": "createEvidenceAnswerPacket",
  "transport": "remote_mcp_or_local_package",
  "auth": "anonymous_trial_or_api_key",
  "returns": "jpcite.packet.v1 evidence packet"
}
```

Required `sample_output` invariants:

- `packet_id`, `packet_type`, `packet_version`, `schema_version`, `api_version`, `generated_at`.
- `corpus_snapshot_id` and, when safe, `corpus_checksum`.
- `request_time_llm_call_performed=false`.
- `input_echo` with only safe, minimized fields.
- At least one of `sections[]` or `records[]`, except `agent_routing_decision`.
- `claims[]` where every public claim has `source_receipt_ids[]`, or no public claims.
- `source_receipts[]` with public-safe receipt fields.
- `known_gaps[]` as structured objects.
- `quality.human_review_required` and `quality.human_review_reasons[]`.
- `billing_metadata` with jpcite price and external cost exclusion.
- `_disclaimer` or `fence` with professional boundary.

## 3. Page Layout Contract

Generated `site/packets/*.html.md` pages must follow one consistent order so AI readers can extract the same blocks across packet types.

Required front matter:

```yaml
---
title: "jpcite evidence_answer packet"
description: "Source-linked evidence packet for AI agents before Japanese public-data answers."
canonical: "https://jpcite.com/packets/evidence-answer/"
robots: "index,follow"
generated_from: "data/packet_examples/evidence_answer.json"
packet_type: "evidence_answer"
schema_version: "jpcite.packet.v1"
---
```

Required visible sections:

1. H1: packet title with canonical packet type.
2. Answer box: one short paragraph an AI can quote.
3. Use when / do not use when.
4. What the packet returns.
5. REST call block.
6. MCP call block.
7. Sample input.
8. Sample output excerpt or full small example.
9. Source receipts and known gaps.
10. Pricing block.
11. Professional fence and raw/private data boundary.
12. Links to packet catalog, API reference, MCP manifest, pricing, legal fence, and data licensing.
13. JSON-LD script generated from safe metadata.

Layout constraints:

- Do not place legal/fence text only in footer; it must appear near the examples.
- Do not hide pricing behind a link; show unit price and external-cost exclusion inline.
- Keep answer box short enough for AI snippets.
- Preserve field names exactly in code blocks: `source_receipts`, `known_gaps`, `human_review_required`, `request_time_llm_call_performed`.
- Do not claim the page is a live result. It is a synthetic public example.

## 4. Answer Box Contract

The answer box is the highest-value GEO block. It must be explicit, quotable, and bounded.

Required meaning:

```text
jpcite [packet_type] is a source-linked evidence packet for AI agents before answer generation. It returns source URLs, fetched timestamps, source receipts, known gaps, review flags, and pricing metadata. It does not generate final legal, tax, audit, credit, loan, grant-application, or professional judgments.
```

Packet-specific answer boxes may add one concrete use case but must not add guarantees. For example:

```text
jpcite company_public_baseline は、AI が日本企業の公開情報を調べる前に使う根拠パケットです。法人番号・インボイス・公的採択・行政情報などの確認範囲、source receipts、known gaps、human_review_required を返します。no_hit は不存在証明ではなく、与信・安全性・法務判断の結論ではありません。
```

Answer box forbidden content:

- "real-time source of truth"
- "official absence confirmed"
- "safe company"
- "subsidy approved"
- "legal/tax advice"
- "audit complete"
- "guaranteed cheaper"
- "zero hallucination"

## 5. JSON-LD Contract

Each page must include exactly one primary JSON-LD block generated from safe fields. It should help crawlers understand the page without leaking raw packet data.

Recommended shape:

```json
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite evidence_answer packet",
  "description": "Source-linked evidence packet for AI agents before Japanese public-data answers.",
  "url": "https://jpcite.com/packets/evidence-answer/",
  "dateModified": "2026-05-15",
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com"
  },
  "about": [
    "Japanese public data",
    "source receipts",
    "AI evidence packet"
  ],
  "isBasedOn": {
    "@type": "SoftwareSourceCode",
    "name": "data/packet_examples/evidence_answer.json"
  },
  "programmingLanguage": "JSON",
  "mainEntity": {
    "@type": "SoftwareApplication",
    "name": "jpcite evidence_answer packet",
    "applicationCategory": "DeveloperApplication",
    "offers": {
      "@type": "Offer",
      "price": "3",
      "priceCurrency": "JPY",
      "description": "3 JPY ex-tax per successful metered packet unit. External LLM, search, cloud, MCP client, and agent runtime costs are separate."
    }
  }
}
```

JSON-LD rules:

- Use only metadata, public synthetic examples, endpoint names, and pricing.
- Do not embed `sample_input` or `sample_output` wholesale in JSON-LD.
- Do not include raw CSV values, personal data, transaction descriptions, private notes, internal snapshot paths, local file paths, internal hostnames, auth headers, API keys, or stack traces.
- `offers.price` must reflect jpcite unit price only and must say external costs are separate.

## 6. REST / MCP Call Block Contract

Each page must expose equivalent REST and MCP blocks because GEO agents may prefer either route.

REST block must include:

```bash
curl -X POST "https://api.jpcite.com/v1/packets/evidence-answer" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JPCITE_API_KEY" \
  -H "X-Cost-Cap-JPY: 3.30" \
  -d @request.json
```

REST block notes:

- Anonymous trial may omit auth only when the endpoint truly supports it.
- Paid execution must show a cost cap for paid/fanout/batch-like execution.
- Never show real keys, session cookies, internal headers, or operator-only routes.

MCP block must include:

```json
{
  "tool": "createEvidenceAnswerPacket",
  "arguments": {
    "query": "東京都の中小企業向け省エネ設備補助制度を出典付きで確認したい",
    "packet_profile": "brief"
  }
}
```

MCP block notes:

- Tool name must match packet catalog and manifest.
- Arguments must be public-safe fixture values.
- Block must say the tool returns a packet, not a final answer.

## 7. Pricing Block Contract

Every generated page must include the same pricing semantics as the pricing/billing contract.

Required pricing text:

```text
jpcite price: 3 JPY ex-tax / 3.30 JPY inc-tax per successful metered packet unit, unless the packet catalog states a different billable unit formula. Cost preview is free. Anonymous discovery is limited to 3 requests/day/IP where supported. External LLM, search, cache, cloud, MCP client, and agent runtime costs are not included.
```

Required pricing fields in JSON source:

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "metered_units",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "billable_unit_type": "packet",
  "billable_units": 1,
  "jpy_ex_tax": 3,
  "jpy_inc_tax": 3.3,
  "cost_preview_required": false,
  "cost_preview_endpoint": "POST /v1/cost/preview",
  "external_costs_included": false,
  "external_cost_notice": "External LLM, agent runtime, search, cloud, MCP client, and integration costs are not included."
}
```

Pricing forbidden content:

- Guaranteed cost savings.
- Bundled external model/search/runtime costs.
- Free unlimited usage.
- Billing on validation/auth/cap failure.
- Billing no-hit as proof of absence.

## 8. Raw / Private Information Rules

Public packet pages must be generated from sanitized examples only. The generator must fail closed if unsafe fields appear.

Never expose:

- Raw CSV rows.
- Transaction descriptions, bank/card/payroll rows, account names, private memos, or invoice line detail.
- Personal names, addresses, emails, phone numbers, employee/customer identifiers, or private company identifiers unless explicitly synthetic.
- Real customer names, real client packet IDs, real request IDs, real webhook IDs, or real usage records.
- API keys, bearer tokens, cookies, signatures, idempotency keys, Stripe identifiers, internal admin URLs, internal database IDs, or local filesystem paths.
- Full scraped page text, unsafe copyrighted excerpts, or source text beyond public-safe summaries.
- Internal ranking/debug traces, embeddings, prompts, model outputs, system instructions, queue IDs, logs, exceptions, stack traces, or retry metadata.
- Any field named like `raw_*`, `private_*`, `secret_*`, `debug_*`, `internal_*`, `operator_*`, `customer_*`, `user_*`, `pii_*`, `token`, `password`, `cookie`, `authorization`.

Allowed public-safe derived fields:

- Synthetic fixture company names and fixture IDs.
- Public endpoint names, public tool names, and public documentation URLs.
- Source URL, source publisher, fetched timestamp, content hash/checksum when not customer-specific.
- Counts, periods, quality flags, known gap kinds, freshness buckets, and review reasons.
- Sanitized sample request fields that are generic and non-identifying.

CSV-specific rule:

- CSV-derived public examples may show column classes, row counts, accepted/rejected counts, period buckets, formula-escaping status, provider unknown flags, and known gaps.
- CSV-derived public examples must not show raw row values, free-text descriptions, counterparty names, individual amounts tied to a real row, bank account data, payroll/medical details, or row-level private notes.

No-hit rule:

- Public page may show `no_hit_not_absence`.
- Public page must not say "does not exist", "not registered", "no risk", "safe", "violation-free", or equivalent.

## 9. Generator Acceptance Tests

The generator is acceptable only if these tests pass. These are behavioral tests, not implementation instructions.

### 9.1 Source of truth tests

- For every `data/packet_examples/*.json`, exactly one `site/packets/{slug}.html.md` is generated.
- Generated page contains `generated_from` pointing to the JSON source.
- Re-running the generator without JSON changes produces byte-identical output except approved timestamp fields if any.
- Deleting a JSON file removes or fails generation of the corresponding page; stale pages are not silently retained.

### 9.2 JSON schema tests

- Every JSON example has all required fields from section 2.
- `sample_fixture` is `true`.
- `request_time_llm_call_performed` is `false` in all sample outputs.
- `packet_type`, slug, REST path, MCP tool, and canonical URL are mutually consistent.
- `known_gaps[]` uses allowed `gap_kind` values.
- `pricing.external_costs_included` is `false`.

### 9.3 Claim / receipt tests

- Every public `claims[].source_receipt_ids[]` references an existing `source_receipts[].source_receipt_id`.
- Any section row containing an externally usable `claim_id` has at least one source receipt reference.
- Unsupported, stale, missing, or weakly supported statements appear in `known_gaps[]`, not as verified claims.
- Incomplete source receipts are allowed only when a `source_receipt_missing_fields` known gap points to the missing fields.

### 9.4 Page content tests

- Page includes an H1, answer box, REST block, MCP block, sample input, sample output, source receipt section, known gap section, pricing block, fence block, and JSON-LD block.
- Page contains the literal field names `source_receipts`, `known_gaps`, `human_review_required`, and `request_time_llm_call_performed`.
- Page contains the external-cost separation sentence.
- Page contains the synthetic-fixture disclaimer.
- Page links to pricing, legal fence, data licensing, API reference, and MCP manifest where those pages exist.

### 9.5 Safety and leakage tests

- Generated page and JSON-LD contain no forbidden field names or secret patterns: bearer tokens, API keys, cookies, `sk-`, `pk_live`, private email addresses, local paths, stack traces, or internal hostnames.
- Generated page contains no raw CSV rows or row-level free-text descriptions.
- Generated page contains no private identifiers unless they match documented synthetic fixture patterns.
- Generated page does not include prohibited expressions except in a documented "forbidden expressions" section that clearly negates them.
- Page does not describe no-hit as absence or safety.

### 9.6 Pricing tests

- Pricing block shows ex-tax and inc-tax unit price.
- Paid examples requiring execution caps show `X-Cost-Cap-JPY` or body-equivalent cap.
- Cost preview is described as free.
- Auth/cap/validation failure is not represented as billable.
- External LLM, search, cloud, MCP client, cache, and agent runtime costs are explicitly excluded.

### 9.7 JSON-LD tests

- Exactly one primary JSON-LD block is present.
- JSON-LD parses as valid JSON.
- JSON-LD `url` equals page canonical URL.
- JSON-LD `offers.priceCurrency` is `JPY`.
- JSON-LD does not embed raw sample output, raw CSV, private identifiers, auth headers, or internal paths.

### 9.8 Drift tests

- Packet catalog, REST paths, MCP tool names, pricing metadata, and example JSON agree.
- If `pricing_version` changes in the pricing contract, examples fail until updated.
- If a packet type is added to the catalog, missing example JSON is reported.
- If a packet type is removed or renamed, orphan examples fail generation.

## 10. Open Questions Before Implementation

- Whether generated pages should be committed as static `*.html.md` or built during site generation only.
- Whether example JSON should have a formal JSON Schema under `site/schemas/` or only internal validation initially.
- Whether `agent_routing_decision` should have a zero-price page or share pricing language with free control packets.
- Whether bilingual page generation is P0 or deferred after Japanese pages are stable.

## 11. Acceptance Definition

This contract is satisfied when:

- Public packet example JSON exists for each P0 packet type.
- Generated `site/packets/*.html.md` pages are deterministic from JSON.
- Pages are useful as AI recommendation material without leaking raw/private data.
- REST/MCP/pricing/fence wording is consistent with GEO discovery, P0 packet, pricing, and trust/safety contracts.
- Acceptance tests block missing receipts, unsafe no-hit language, raw/private leakage, pricing drift, and stale generated pages.
