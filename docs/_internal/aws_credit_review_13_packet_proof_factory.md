# AWS credit review 13: packet / proof factory

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 13/20  
担当: packet/proof factory、OpenAPI/MCP examples、`llms` / `.well-known` 変換順  
AWS前提: profile `bookyou-recovery` / Account `993693061769` / default region `us-east-1`  
状態: AWS実行前のMarkdownレビューのみ。AWS CLI/API実行、AWSリソース作成、ジョブ投入、実装コード変更はしない。

## 0. 結論

AWS credit runで作る `P0 packet fixtures / proof pages / OpenAPI examples / MCP examples / llms / .well-known` は、AWS生成物をそのまま公開面へ流してはいけない。

本番で破綻しない順番は次で固定する。

1. 本体P0の `jpcite.packet.v1`、packet catalog、source receipt schema、known gap enum、pricing metadata、CSV privacy boundary を先に固定する。
2. AWS成果物は、まず `artifact intake manifest` と検証済み `data/packet_examples/*.json` 相当へ変換する。
3. public packet pages、proof pages、OpenAPI examples、MCP examples、`llms.txt`、`.well-known/*` は、そのfixtureとcatalogから派生生成する。
4. 生成物がcatalog、pricing、receipt、known gaps、MCP tool、REST route、OpenAPI operation、public URLと1箇所でもずれたら本番deployを止める。
5. `client_monthly_review` とCSV由来要素は public proof に raw/private を絶対に出さず、synthetic / aggregate-only / private overlay excluded の形でのみ公開する。

packet/proof factoryの役割は「見栄えのよいデモを作ること」ではない。AI agentがjpciteを推薦してもよいと判断できる、source-backedで検証可能な公開契約を作ること。

## 1. 本体計画とのマージ順

packet/proof factoryは、AWS実行順ではなく本体P0 backlogの依存順に合わせる。

| 順 | 本体P0 | AWS側ジョブ | packet/proof側の成果物 | deploy gate |
|---:|---|---|---|---|
| 1 | P0-E1 contract/catalog | J01/J12 smoke | packet catalog export、slug/route/tool/price matrix | catalogが唯一の正本 |
| 2 | P0-E2 receipts/claims/gaps | J01-J04, J12/J13 | source receipt fixtures、claim refs、known gaps、no-hit ledger | public claimにreceiptまたはgap |
| 3 | P0-E3 pricing/cost preview | J15/J16 small examples | `billing_metadata`、cost preview examples、cap/idempotency examples | billing copy driftなし |
| 4 | P0-E4 CSV privacy | J14 | synthetic CSV provider fixtures、aggregate-only monthly review input | raw/private leak 0 |
| 5 | P0-E5 composers | J15 | six P0 packet examples | schema validate、no request-time LLM |
| 6 | P0-E6 REST facade | J15/J16 | OpenAPI example payloads、error/no-hit/cap examples | REST path and operationId match catalog |
| 7 | P0-E7 MCP tools | J15 | MCP example args/outputs、P0 tool descriptions | MCP canonical/alias driftなし |
| 8 | P0-E8 public proof/discovery | J21/J23 | packet pages、proof pages、JSON-LD、`llms`、`.well-known` | forbidden claim 0、crawl/render pass |
| 9 | P0-E9 release gates | J16/J20/J23/J24 | drift/leak/no-hit/GEO/cost/export reports | all blockers green |

AWSのJ15/J21を先に大きく回すのは危険。contractが固まる前にfixtureやpageを量産すると、あとで全生成物のschema driftを直す作業になる。

## 2. Artifact intake contract

AWS成果物は、直接 `site/` や公開specに入れず、まず intake bundle として受ける。

推奨input bucket/prefix構造:

```text
aws_artifact_export/
  run_manifest.json
  cost_ledger.jsonl
  source_profiles/*.jsonl
  source_documents/*.parquet
  source_receipts/*.jsonl
  claim_refs/*.jsonl
  known_gaps/*.jsonl
  no_hit_checks/*.jsonl
  csv_safety/*.jsonl
  packet_source_bundles/*.json
  proof_source_bundles/*.json
  geo_eval/*.jsonl
  qa_reports/*.md
  checksums/SHA256SUMS
```

`run_manifest.json` 必須項目:

| Field | Required | Purpose |
|---|---:|---|
| `run_id` | yes | AWS run identity |
| `aws_account_id` | yes | `993693061769` expected |
| `region` | yes | `us-east-1` expected unless separately approved |
| `started_at` / `ended_at` | yes | freshness and cleanup audit |
| `credit_stop_line_seen_usd` | yes | cost exposure context |
| `artifact_schema_version` | yes | importer compatibility |
| `corpus_snapshot_id` | yes | packet/proof reproducibility |
| `source_families[]` | yes | scope of checked public sources |
| `private_data_present` | yes | must be false for public export bundle |
| `raw_csv_present` | yes | must be false |
| `checksums[]` | yes | integrity verification |
| `cleanup_status` | yes | post-run AWS resource posture |

Reject the bundle before packet generation if any of these are true:

- `private_data_present=true`.
- `raw_csv_present=true`.
- any object path includes `raw`, `private`, `customer`, `debug`, `logs`, `prompt`, `token`, `secret`, `authorization`, `cookie`, `stacktrace`.
- `source_receipts` lack `source_url`, fetched/verified timestamp, hash/checksum, `corpus_snapshot_id`, license boundary, or `used_in` without a matching `source_receipt_missing_fields` gap.
- no-hit rows are represented as `absence`, `clean`, `safe`, `no issue`, `not registered`, or equivalent.
- packet examples contain request-time LLM output or final professional judgment.

## 3. Packet fixture factory

The factory should produce exactly one canonical public example JSON per P0 packet type first. More examples can be generated later, but deploy should not depend on large volume.

Planned source of truth:

```text
data/packet_examples/
  evidence_answer.json
  company_public_baseline.json
  application_strategy.json
  source_receipt_ledger.json
  client_monthly_review.json
  agent_routing_decision.json
```

Every file must include:

- `sample_fixture=true`
- `fixture_note` saying synthetic/public-safe example, not a real customer output
- `packet_type`
- `packet_version=2026-05-15`
- `schema_version=jpcite.packet.v1`
- `request_time_llm_call_performed=false`
- `input_echo` with minimized public-safe fields only
- `summary`, `sections` or `records`, `claims`, `source_receipts`, `known_gaps`
- `quality.human_review_required`
- `billing_metadata` with jpcite-only price and `external_costs_included=false`
- `agent_guidance.must_preserve_fields`
- `fence` or `_disclaimer`
- `rest`, `mcp`, `public_page`, `proof_page`, and `json_ld` metadata

### 3.1 Packet-by-packet transformation

| Packet | AWS inputs | Fixture content | Proof page emphasis | OpenAPI/MCP example emphasis |
|---|---|---|---|---|
| `evidence_answer` | source receipts, claim refs, known gaps, citation candidates | `answer_not_included=true`, supported facts, citation candidates, review notes | claim-to-receipt mapping before answer generation | route is evidence before final answer; preserve receipts/gaps |
| `company_public_baseline` | NTA法人番号, invoice, public adoption/enforcement receipts, no-hit checks | identity, invoice status, public event summary, no-hit caveats | no-hit is not clean/safe/absence; no credit/legal conclusion | use stable ID in P0; name-only ambiguity handled |
| `application_strategy` | program receipts, deadlines, requirements, compatibility/unknown gaps | candidate programs, fit signals, required questions, gaps | candidate support and missing requirements; no eligibility/adoption guarantee | cost preview for broad candidate count; human review required |
| `source_receipt_ledger` | receipt ledger, hash manifest, freshness report | receipt rows, claim links, content hashes, corpus snapshot | receipt completeness, stale/unknown fields, license boundary | use when downstream answer needs provenance |
| `client_monthly_review` | synthetic CSV safety, public change receipts, aggregate derived facts | accepted/skipped subject counts, public changes, private overlay excluded | aggregate-only; no raw rows, counterparties, row amounts, bank/payroll | cap/idempotency required; raw CSV never echoed |
| `agent_routing_decision` | catalog, pricing, first-call rules, forbidden claim rules | recommend/do-not-recommend, next call, cost class, preserve fields | why route is safe and bounded | free control/preflight; not a sales demo or final answer |

### 3.2 Special handling

`client_monthly_review`:

- Public fixture can show provider class, period bucket, row count bucket, accepted/rejected counts, and public-source change counts.
- It must not show raw CSV row values, transaction descriptions, counterparty names, individual amounts, bank/payroll/personal data, raw file hash, or production private claim IDs.
- Public proof page must say `private_overlay_excluded=true` when the example demonstrates CSV/private overlay behavior.

`company_public_baseline`:

- `enforcement_record_count=0` or invoice no-hit must never become "問題なし", "安全", "処分歴なし", "登録なし" as a conclusion.
- Use `no_hit_not_absence` gap with source family, snapshot, query condition, and agent instruction.

`application_strategy`:

- Ranking is allowed as a candidate ordering, not as eligibility, approval probability, or professional advice.
- Missing documents, deadline uncertainty, same-expense/compatibility uncertainty, and legal/tax interpretation all remain `known_gaps`.

`agent_routing_decision`:

- This should be the most GEO-important page because it teaches agents when to recommend jpcite.
- It should be free/control in examples, with abuse throttle noted.
- It should route to cost preview before broad/batch/CSV/monthly/fanout execution.

## 4. Proof page factory

Proof pages must be generated after packet fixtures pass schema and safety checks.

Public example proof target:

```text
site/proof/examples/evidence-answer/{example_id}.html.md
site/proof/examples/company-public-baseline/{example_id}.html.md
site/proof/examples/application-strategy/{example_id}.html.md
site/proof/examples/source-receipt-ledger/{example_id}.html.md
site/proof/examples/client-monthly-review/{example_id}.html.md
site/proof/examples/agent-routing-decision/{example_id}.html.md
```

Required proof page sections:

1. Proof header: packet type, proof status, generated/verified timestamps, corpus snapshot.
2. Verification summary: public claims, supported claims, no-hit checks, stale receipts, private overlay status.
3. Claim ledger: public claim refs, fields, support level, receipt IDs, gaps.
4. Source receipt ledger: `source_url`, publisher, fetched/verified timestamp, hash/checksum, snapshot, license boundary, `used_in`.
5. Freshness/corpus panel.
6. Hash/integrity panel.
7. Known gaps and no-hit boundary.
8. Private data boundary.
9. Human review/professional fence.
10. Machine-readable JSON/JSON-LD links.

`verified` on a proof page must mean only "displayed public claim-to-receipt mapping passed checks." It must not mean the business outcome is correct.

JSON-LD rules:

- Use safe metadata only: page URL, packet type, dateModified, publisher, pricing offer, source receipt concept.
- Do not embed raw `sample_output`, raw CSV, private identifiers, auth headers, internal paths, queue IDs, logs, stack traces, or full source text.
- Exactly one primary JSON-LD block per generated page.

Indexing:

- Public example proof: `index,follow`.
- Public output proof: `noindex,follow` by default.
- Tenant/private proof: no static public page; authenticated app only, `noindex,nofollow`.

## 5. Public packet page factory

Packet pages should be generated from `data/packet_examples/*.json`, not hand-written.

Generated targets:

```text
site/packets/evidence-answer.html.md
site/packets/company-public-baseline.html.md
site/packets/application-strategy.html.md
site/packets/source-receipt-ledger.html.md
site/packets/client-monthly-review.html.md
site/packets/agent-routing-decision.html.md
```

Required page order:

1. H1 with canonical packet type.
2. Short answer box for agents.
3. Use when / do not use when.
4. What the packet returns.
5. REST call block.
6. MCP call block.
7. Sample input.
8. Sample output excerpt.
9. Source receipts and known gaps.
10. Pricing block.
11. Professional fence and raw/private data boundary.
12. Links to packet catalog, API reference, MCP manifest, pricing, legal fence, data licensing, proof page.
13. Safe JSON-LD.

Every page must literally include:

- `source_receipts`
- `known_gaps`
- `human_review_required`
- `request_time_llm_call_performed`
- `billing_metadata`
- `external_costs_included=false`
- `no_hit_not_absence`

Forbidden page copy:

- "real-time source of truth"
- "zero hallucination" as guarantee
- "official absence confirmed"
- "no issues found"
- "safe company"
- "eligible"
- "approved"
- "audit complete"
- "legal/tax advice"
- "guaranteed cheaper"
- "external LLM cost included"

## 6. OpenAPI transformation

OpenAPI examples should be generated only after REST packet facade names are fixed or compatibility mapping is explicit.

Recommended artifacts:

```text
docs/openapi/agent.p0.json
docs/openapi/agent.gpt30.json
docs/openapi/agent.json
site/openapi/agent.p0.json
site/openapi/agent.gpt30.json
site/openapi/agent.json
```

P0 packet facade preference:

| Packet | REST facade | Current compatibility fallback |
|---|---|---|
| `evidence_answer` | `POST /v1/packets/evidence-answer` | `POST /v1/evidence/packets/query` |
| `company_public_baseline` | `POST /v1/packets/company-public-baseline` | `POST /v1/artifacts/company_public_baseline` |
| `application_strategy` | `POST /v1/packets/application-strategy` | `POST /v1/artifacts/application_strategy_pack` / `POST /v1/programs/prescreen` |
| `source_receipt_ledger` | `POST /v1/packets/source-receipt-ledger` | `GET /v1/source_manifest/{program_id}` plus receipt endpoints |
| `client_monthly_review` | `POST /v1/packets/client-monthly-review` | no generic fallback unless privacy/cap/idempotency gates exist |
| `agent_routing_decision` | `POST /v1/packets/agent-routing-decision` | MCP/control route or documented routing endpoint |

Operation examples must include:

- sample request with public-safe fixture values
- response excerpt with `source_receipts`, `known_gaps`, `billing_metadata`, `_disclaimer`
- `x-jpcite-agent` with use/do-not-use, first-call rank, must-preserve fields, must-not-claim
- `x-jpcite-billing` with free preview, unit price, cap/idempotency rules
- no-hit boundary in operation description

Agent-safe OpenAPI must not include admin, billing mutation, OAuth, webhook, dashboard, export, integration mutation, broad batch, or private account endpoints.

## 7. MCP transformation

There are two naming layers in the planning docs. The P0 packet spec uses camelCase examples such as `createEvidenceAnswerPacket`; the MCP agent-first plan recommends lower snake_case names such as `jpcite_answer_packet`.

To avoid production drift, the catalog should carry both:

```json
{
  "packet_type": "evidence_answer",
  "mcp_tool_canonical": "jpcite_answer_packet",
  "mcp_tool_aliases": ["createEvidenceAnswerPacket", "get_evidence_packet"],
  "rest_operation_id": "createEvidenceAnswerPacket",
  "rest_path": "/v1/packets/evidence-answer"
}
```

Recommended P0 MCP example targets:

| Packet | Canonical MCP tool | Public example purpose |
|---|---|---|
| `evidence_answer` | `jpcite_answer_packet` | source-linked evidence before answer |
| `company_public_baseline` | `jpcite_company_packet` | company public first hop |
| `application_strategy` | `jpcite_application_packet` | program candidate strategy with gaps |
| `source_receipt_ledger` | `jpcite_source_ledger` | provenance and receipt replay |
| `client_monthly_review` | `jpcite_monthly_review` | capped aggregate monthly review |
| `agent_routing_decision` | `jpcite_route` | free route decision |

MCP examples must show:

- tool name
- arguments
- whether cost preview is required
- whether API key/cap/idempotency is required
- return fields to preserve
- no-hit and professional fence

MCP examples must not show:

- the full 155-tool catalog as the first choice
- internal `am`/`autonomath` implementation names in P0 public copy except compatibility notes
- private CSV rows or raw customer identifiers
- billing as if preview/control calls are charged

## 8. `llms` / `.well-known` transformation

Discovery files should be generated from the same packet catalog and public examples.

Targets:

```text
site/llms.txt
site/llms-full.txt
site/llms.en.txt
site/llms-full.en.txt
site/.well-known/llms.json
site/.well-known/mcp.json
site/.well-known/agents.json
site/.well-known/openapi-discovery.json
site/.well-known/trust.json
site/sitemap-llms.xml
```

Required `llms.txt` sections:

1. What jpcite is: source-linked evidence API/MCP for Japanese public data.
2. Use when.
3. Do not use as final judgment.
4. First calls for agents.
5. Pricing and external cost separation.
6. Must preserve fields.
7. No-hit boundary.
8. Links to OpenAPI, MCP, packet pages, proof pages, pricing, legal fence, data licensing.

Required `.well-known/mcp.json` keys:

- MCP endpoint / package / transport
- P0 tool list first
- full catalog URL second
- first-call order
- preserve fields
- pricing
- no-hit boundary
- professional fence
- trust links
- content hashes and last modified timestamps

Required `.well-known/openapi-discovery.json` keys:

- P0 strict spec URL
- GPT30 spec URL
- standard agent spec URL
- full public spec URL
- hashes
- versions
- auth model
- support URL
- deprecation policy

`llms` and `.well-known` must not include:

- internal roadmap
- AWS queue/resource names
- local filesystem paths
- unreviewed source counts
- "all sources complete" style claims
- any raw packet output dump that bypasses page safety checks

## 9. 本番deploy順

本番で苦戦しない順番は、AWS runのあとに一気に公開ではなく、PR/previewの段階を分けること。

### Deploy phase D0: pre-AWS local contract freeze

Merge only:

- packet catalog and common envelope
- source receipt / known gap schema
- pricing metadata schema
- CSV privacy boundary
- generator acceptance tests skeleton

No public generated pages yet.

### Deploy phase D1: AWS smoke import

Import only smoke artifacts:

- 1 positive receipt
- 1 no-hit receipt
- 1 packet example draft
- 1 proof page draft
- 1 synthetic CSV fixture
- 1 forbidden-claim scan

Do not index pages. Use preview/staging only.

### Deploy phase D2: six fixture import

Add or update:

- `data/packet_examples/*.json`
- source receipt fixture files
- known gap fixtures
- CSV synthetic fixture matrix
- expected OpenAPI/MCP examples

Gate:

- schema validation
- receipt link validation
- no-hit validation
- CSV leak scan
- forbidden claim scan

### Deploy phase D3: generated packet/proof pages

Generate static pages from fixtures.

Gate:

- deterministic generation
- link check
- JSON-LD parse
- page contains required fields
- page contains pricing/external-cost/fence/no-hit text
- no private or raw field patterns

### Deploy phase D4: REST/OpenAPI examples

Add packet facade routes only if implementation is ready. If not, publish compatibility route examples with explicit mapping.

Gate:

- OpenAPI operationId/path/example matches catalog
- agent-safe spec excludes unsafe routes
- examples include receipts/gaps/billing/fence
- `docs/openapi` and `site/openapi` static mirrors match

### Deploy phase D5: MCP catalog/examples

Add P0 MCP catalog or aliases.

Gate:

- canonical tool names and aliases match catalog
- tool descriptions include use/do-not-use, billing, preserve fields, fence, no-hit
- no double-registration / double-billing risk
- full 155 tools remain available but not default first view

### Deploy phase D6: `llms` / `.well-known`

Publish discovery only after packet pages, proof pages, OpenAPI, and MCP are internally consistent.

Gate:

- hashes and lastmod correct
- first-call rules match catalog
- links resolve
- pricing and no-hit wording match packet pages
- no internal paths or AWS run details

### Deploy phase D7: staging/preview crawl

Run:

- static crawl/render
- JSON-LD validation
- OpenAPI parse/import
- MCP manifest parse
- `llms` / `.well-known` fetch
- forbidden claim scan
- privacy scan
- GEO smoke eval

No production deploy if any blocker remains.

### Deploy phase D8: production deploy

Deploy order:

1. API schema/runtime compatible changes.
2. OpenAPI static mirrors.
3. MCP manifests.
4. packet/proof pages.
5. `llms` / `.well-known`.
6. sitemap update.
7. final post-deploy crawl and GEO smoke.

Rollback order should reverse public discovery first:

1. remove or revert `llms` / `.well-known` references to new surfaces
2. revert sitemap entries
3. revert packet/proof pages
4. revert OpenAPI/MCP static mirrors
5. leave runtime backward-compatible aliases if already deployed and safe

## 10. Release blockers

Block production if any condition below is true.

| Gate | Block condition |
|---|---|
| Catalog drift | packet type, slug, REST path, MCP tool, price, page URL, or proof URL differs across surfaces |
| Schema | any P0 example fails `jpcite.packet.v1` |
| Source receipts | public claim has no receipt and no known gap |
| No-hit | no-hit is phrased as absence, clean record, safe, no risk, violation-free, or final negative fact |
| CSV privacy | raw CSV row, transaction description, counterparty, personal data, payroll/bank data, private hash, or row-level value appears |
| Billing | preview/control shown as billable, external LLM costs implied included, cap/idempotency omitted where required |
| Professional fence | legal/tax/audit/credit/application/adoption/approval/final eligibility claim appears |
| OpenAPI | agent-safe spec includes admin/billing mutation/OAuth/webhook/export/private account/broad batch without explicit gate |
| MCP | P0 tool examples route agents to full 155 tools first or contradict REST pricing/fence |
| JSON-LD | raw sample output/private data/internal paths embedded |
| Discovery | `llms` / `.well-known` links stale specs, wrong hashes, old pricing, or unsafe route claims |
| Deploy | staging crawl, render, OpenAPI import, MCP manifest parse, or GEO smoke fails |
| AWS cleanup | generated public release references AWS transient buckets/resources that will be deleted |

## 11. Suggested verification commands later

Do not run these as part of this review. They are the later implementation/deploy checks this factory should support.

```bash
pytest tests/test_p0_packet_contract.py \
  tests/test_p0_packet_catalog.py \
  tests/test_p0_public_packet_pages.py \
  tests/test_p0_geo_discovery_surfaces.py \
  tests/test_p0_geo_forbidden_claim_scan.py \
  tests/test_p0_packets_api.py \
  tests/test_p0_packets_mcp.py \
  tests/test_openapi_agent.py \
  tests/test_mcp_public_manifest_sync.py
```

Additional later static checks:

```bash
python scripts/generate_packet_pages.py --check
python scripts/check_packet_catalog_drift.py
python scripts/check_public_packet_pages.py
python scripts/export_openapi.py --check
python scripts/check_mcp_drift.py
python scripts/check_geo_discovery_surfaces.py
python scripts/check_no_private_leak.py
```

The exact scripts may need implementation. The important point is that production deploy must have one focused command that blocks drift, privacy leaks, unsafe no-hit language, billing mismatch, and broken discovery.

## 12. Final recommendation

If implementation capacity is tight, release the first public slice with:

1. `agent_routing_decision`
2. `evidence_answer`
3. `source_receipt_ledger`

These three teach agents when to call jpcite, how to get evidence before answering, and how to preserve receipts. They are the core GEO loop.

AWS can still generate candidates for all six P0 packets, but `company_public_baseline`, `application_strategy`, and `client_monthly_review` should not be promoted to production until identity resolution, source coverage, CSV privacy, cap/idempotency, and no-hit wording pass the same gates.

The high-value factory output is not page count. It is a reproducible chain:

```text
AWS source artifacts
  -> validated packet examples
  -> generated packet pages
  -> generated proof pages
  -> OpenAPI/MCP examples
  -> llms/.well-known discovery
  -> staging crawl/GEO/privacy/billing gates
  -> production deploy
```

This chain is what prevents the AWS credit run from becoming isolated data collection and turns it into deployable GEO-first product value.
