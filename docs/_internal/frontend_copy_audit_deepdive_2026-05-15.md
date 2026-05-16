# Frontend copy audit deep dive

Date: 2026-05-15  
Owner lane: Frontend copy audit / user-visible vs agent-visible separation  
Status: documentation-only planning. Do not treat as shipped UI behavior until implementation and copy QA are accepted.  
Constraint: do not edit runtime implementation from this audit.  
Scope: public-facing homepage, pricing, packet, CSV, proof, and docs copy rules; visible vs metadata separation; technical counter policy; copy lint candidates.

## 0. Executive decision

jpcite should keep the human UI focused on decision-useful trust, cost, and boundary information. Agent and developer metadata should remain complete, but it should not leak into first-view human copy as raw implementation inventory.

The practical split:

- Human UI can show `MCP`, `API`, `REST`, `OpenAPI`, packet names, price, cost caps, source receipts, known gaps, freshness, and review boundaries when they help a buyer or operator decide what to do next.
- Human UI should not lead with full MCP tool counts, full REST path counts, internal table names, route inventories, schema internals, migration history, default gates, or implementation flags.
- Agent-visible metadata can expose exact tool names, operation IDs, endpoint paths, schema versions, must-preserve fields, billing metadata, route recommendation IDs, and do-not-use conditions.
- Developer docs can expose the full technical contract, but should still separate "quick path" from full inventory.

The copy goal is not to hide technical capability. It is to prevent human pages from reading like a manifest dump while preserving enough machine-readable detail for AI agents to recommend and call jpcite safely.

## 1. Information classification

### 1.1 Human UI: show by default

Show these in visible copy because they help non-internal readers decide fit, cost, and risk:

| Category | Examples | Copy rule |
|---|---|---|
| Product role | "AIが回答前に使う根拠パケット", "Japanese public-data evidence layer" | Lead with job-to-be-done, not implementation shape. |
| Supported tasks |制度候補確認, 法人・取引先確認, インボイス確認, source receipt review, CSV月次レビュー | Express as user tasks. |
| Output promise | 出典URL, 取得日時, known gaps, human_review_required, cost metadata | Use short labels; keep full field names in sample/code blocks or details. |
| Boundaries | no-hit is not absence, not legal/tax/audit/credit/application judgment | Repeat near examples and CTAs. |
| Cost control | `¥3/billable unit`, free preview, cap required, external costs excluded | Show before execution CTAs. |
| Primary entrypoints | `Try with MCP`, `Preview cost`, `Get API key`, `Open docs` | Use action labels, not endpoint lists. |
| Freshness and provenance | source fetched date, corpus snapshot, official source URL | Show near evidence output, not as abstract platform metrics. |
| Public sample status | synthetic fixture, not real customer/company result | Show wherever sample output is quotable. |

### 1.2 Human UI: do not show by default

Do not place these in first viewport, product summaries, pricing cards, or general buyer copy:

| Category | Examples | Reason | Better location |
|---|---|---|---|
| Raw inventory counts | "155 MCP tools", "306 REST paths", "34 agent-safe paths" | Looks unstable and implementation-first; invites count drift. | Docs changelog, developer docs, metadata, internal QA. |
| Full route lists | `/v1/...` path tables across all families | Overwhelms non-developer readers. | API reference, OpenAPI, collapsed developer drawer. |
| Internal implementation flags | default gates, env flags, broken/gated tools, table counts | Internal operational state, not product value. | Internal docs or release notes if public-safe. |
| Schema internals as persuasion | `schema_version`, `operationId`, `x-jpcite-agent`, enum IDs | Necessary for agents, but noisy for humans. | JSON-LD, OpenAPI, packet catalog JSON, code blocks. |
| Database/source pipeline details | migration IDs, mat table names, REFRESHERS dict, crawl job names | Does not help users decide usage; may leak maintainability risk. | Engineering docs. |
| Debug/billing internals | Stripe event names, usage row names, idempotency storage keys | Confuses pricing story and exposes internals. | API docs only when relevant. |
| Grandiose technical volume claims | "largest", "complete", "zero hallucination", "all endpoints" | High legal/trust risk and usually unverifiable. | Avoid. |

### 1.3 Agent metadata only

Expose these for AI agents and tool importers, but not as primary human prose:

| Metadata | Where it belongs | Human substitute |
|---|---|---|
| Exact MCP tool name | `.well-known`, MCP manifest, packet JSON, docs code block | "Create evidence packet" |
| Exact REST method/path | OpenAPI, docs code block, packet detail technical block | "Open API docs" or "REST call available" |
| `operationId` | OpenAPI only | none |
| `must_preserve_fields` | OpenAPI vendor extension, packet metadata, docs reference | "Keep source URLs, fetched timestamps, gaps, and review flags" |
| `recommend_when_ids` / `do_not_recommend_when_ids` | metadata JSON | Use when / Do not use when copy |
| Full `billing_metadata` object | API response examples, docs reference | "Preview units and set a cap before paid execution" |
| `request_time_llm_call_performed=false` | packet JSON, proof sample, agent docs | "jpcite returns evidence, not an LLM-generated final answer" |
| Closed enum error codes | API docs, error reference | Plain recovery copy in UI |
| Full schema version and packet version | metadata, sample JSON, technical details | "Example packet format" |

### 1.4 Developer docs visible

Developer docs are allowed to be precise, but they need progressive disclosure:

1. Quickstart: first-call tools, cost preview, caps, examples.
2. Agent-safe contract: small endpoint/tool subset and routing rules.
3. Full reference: OpenAPI, full MCP catalog, schemas, error codes.
4. Changelog/audit: counts, path totals, default gates, deprecations.

## 2. Page-level copy rules

### 2.1 Homepage

Homepage job: answer "What is this, when should I use it, what are the limits, and what is the next action?"

Show:

- One role statement: `AIが日本の公的データを答える前に使う evidence layer`.
- Three to five task rows: evidence answer, company baseline, application strategy, source receipt ledger, CSV/monthly review.
- Core output labels: source URL, fetched timestamp, known gaps, review flag, cost preview.
- Boundary line: not final legal/tax/audit/credit/application judgment.
- CTAs: `Try with MCP`, `Preview cost`, `View proof sample`, `Get API key`.

Do not show:

- Full MCP tool count in hero.
- Full REST path count in hero.
- Large "coverage count" stat without date, source, and scope.
- Endpoint families as product cards.
- Internal product history or old brand/tool names.

Allowed technical copy:

- `MCP / API` can appear in subcopy and nav because it tells agent operators how to connect.
- `OpenAPI` can appear as a docs link, not as the central value proposition.
- A single "Developer path" strip may say: `MCP, REST, and OpenAPI expose the same packet contract.`

### 2.2 Pricing

Pricing job: make cost and guardrails understandable before execution.

Show:

- `¥3/billable unit` and tax handling.
- Free cost preview.
- Anonymous quota, if stable and current.
- Paid execution requires API key.
- Paid batch/CSV/fanout/watchlist/packet execution requires a hard cap.
- External LLM, search, cloud, agent runtime, MCP client, and integration costs are excluded.
- Examples in user units: one packet, one resolved company, one accepted CSV subject, one receipt-set bundle.

Do not show:

- Endpoint-by-endpoint billing table on the first pricing screen.
- Internal `billable_unit_type` enum list as marketing copy.
- Stripe event names, usage table names, webhook behavior, invoice internals.
- Unqualified "cheap", "lowest price", or "guaranteed savings".

Allowed technical copy:

- Use `billable unit` visibly because it is the pricing primitive.
- Use exact formula only in examples or details: `accepted subjects x ¥3`.
- Use endpoint names only in API/docs tabs, not in pricing cards.

### 2.3 Packet pages

Packet page job: let human and AI agree on when a packet should be used and what the output means.

Show:

- Packet title and one-sentence use case.
- Use when / do not use when.
- Human-readable output summary.
- Source receipts, known gaps, review boundary.
- Pricing block with unit and external-cost exclusion.
- Synthetic fixture note for examples.
- A compact REST/MCP call block below the human explanation.

Do not show:

- Entire full schema before the reader sees the outcome.
- All equivalent legacy route names.
- Tool aliases in the primary title.
- Internal packet generator details except `generated_from` in metadata/front matter.

Allowed technical copy:

- Show canonical packet type such as `evidence_answer` beside the human title.
- Show exact `POST /v1/packets/...` and MCP tool name in a clearly labeled technical section.
- Preserve field names in code blocks: `source_receipts`, `known_gaps`, `human_review_required`, `billing_metadata`.

### 2.4 CSV intake pages

CSV page job: reduce fear about private rows, cost surprise, and billing ambiguity.

Show:

- Lifecycle: upload or provide sample -> preview -> accepted/rejected/duplicate rows -> cap -> execute -> reconciliation.
- Privacy boundary: raw rows are minimized; public examples never show private rows or transaction descriptions.
- Billing unit in human language: one normalized, deduped accepted subject.
- Rejected rows are not billed.
- Duplicates are not billed.
- Unresolved/ambiguous rows are not billed unless a specific manual-review packet is explicitly requested.
- Cap math in plain text.

Do not show:

- Raw customer CSV row examples with personal names, transaction descriptions, memos, bank text, or private identifiers.
- Provider-specific parser internals as UI copy.
- Column inference/debug metadata by default.
- Full field-level schema unless user opens docs.

Allowed technical copy:

- `billable_subject` can appear in a details section, paired with a plain-language definition.
- `row_state` codes can appear in download/reconciliation views, not in the first explanation.
- API endpoint names belong under "Automate this workflow".

### 2.5 Proof pages

Proof page job: let an evaluator or crawler inspect evidence quality without mistaking samples for live determinations.

Show:

- The claim being supported.
- Source receipts with URL/domain, fetched date, snapshot or hash where public-safe.
- Known gaps and stale/freshness caveats.
- No-hit wording: "not found in this corpus/snapshot", not "does not exist".
- Human review requirement.
- Small sample packet excerpt with enough fields for AI citation behavior.

Do not show:

- Raw internal crawl logs.
- Full corpus checksums if they are not public-safe.
- Private packet IDs from customers.
- "Officially verified absent", "risk-free", "approved", "compliant" without human professional context.

Allowed technical copy:

- `source_receipts` and `known_gaps` should be visible because they are the proof product.
- `content_hash` and `corpus_snapshot_id` may be visible in proof details if public-safe.
- Full JSON belongs in collapsible/example section or downloadable sample, not above the proof summary.

### 2.6 Docs

Docs job: enable correct implementation without making beginner paths feel like a full platform inventory.

Show:

- Quickstart with recommended first calls.
- Agent-safe subset before full reference.
- Exact REST paths, MCP tool names, headers, idempotency, cap requirements, errors, and examples.
- Full counts only when scoped and dated.

Do not show:

- Count claims without generated source and date.
- Conflicting counts across roadmap, smoke runbook, docs index, manifest, and OpenAPI.
- Deprecated tool names as first recommendation.
- Internal-only endpoints in public docs.

Allowed technical copy:

- Full REST paths are correct in API docs and code examples.
- Full MCP tool names are correct in MCP docs and manifests.
- Count summaries are acceptable in changelog/release notes when tied to a generated artifact.

## 3. Technical counters policy

Technical counters include MCP tool count, default-gated tool count, OpenAPI path count, agent-safe path count, public program count, tax rule count, route count, source count, and benchmark row count.

### 3.1 Counter classes

| Class | Visible? | Examples | Rule |
|---|---:|---|---|
| Product decision counter | yes, with scope/date | `14,472 public program records as of YYYY-MM-DD` | Use only if the user benefit is obvious and the source is generated. |
| Trust/proof counter | yes, near proof | `source receipts in this packet`, `known gaps count` | Packet-local counters are useful and less drift-prone. |
| Cost counter | yes | predicted units, accepted subjects, rejected rows | Required for cost transparency. |
| Technical inventory counter | not homepage/pricing | MCP tools, REST paths, OpenAPI paths, routers | Use in developer docs, release notes, registry submissions. |
| Operational counter | internal only by default | migrations, materialized tables, default gates, broken tools | Keep in internal docs unless publishing an engineering post. |
| Benchmark counter | docs/proof only | queries, P95, precision, sample size | Must include method, date, and fixture/snapshot. |

### 3.2 When counters are allowed in public UI

A counter is allowed only if it passes all checks:

- The counter is generated from a canonical artifact or source query.
- The copy names what is counted.
- The copy includes date or snapshot when drift matters.
- The counter helps a user choose an action.
- The page has a fallback if the counter is missing.

Good:

```text
この packet には 8 件の source receipts と 2 件の known gaps が含まれます。
```

Good:

```text
CSV preview: 120 rows -> 84 accepted subjects -> predicted 84 units.
```

Avoid on homepage:

```text
155 MCP tools / 306 REST paths
```

Better:

```text
Agents can start with a small recommended MCP/API surface, then open the full reference when needed.
```

### 3.3 Count drift controls

- Never hard-code tool/path counts in marketing copy.
- If count copy is necessary, drive it from the same generated artifact used by docs or manifests.
- Add copy lint for old count patterns: `155 tools`, `142 tools`, `306 paths`, `34 paths`, `111 paths`, `240 paths`, `100+ tools`.
- Use dated phrasing in docs: `Snapshot checked 2026-05-15: 34 paths`.
- Prefer qualitative labels on human pages: `recommended first-call tools`, `full developer reference`, `packet catalog`.

## 4. Frontend copy lint candidates

These lint candidates can be implemented later as a docs/site copy check. They are intentionally phrased as detection rules, not code changes.

### 4.1 User-visible technical leakage

Flag in homepage/pricing/packet index/proof index/CSV landing copy:

- `\b\d+\s*(MCP\s*)?tools?\b`
- `\b\d+\s*(REST\s*)?paths?\b`
- `\b\d+\s*endpoints?\b` when not in docs/API reference
- `default gates?`
- `env[-_ ]?flag`
- `router files?`
- `migration(s)?`
- `mat_` / `pc_` table prefixes
- `schema_migrations`
- `REFRESHERS`
- `operationId`
- `x-jpcite-`
- `full_catalog` / `legacy_or_expert_catalog`

Severity: warn on docs, error on homepage/pricing first-view copy.

### 4.2 Unsafe guarantee language

Flag everywhere public:

- `完全診断`
- `最終判断`
- `受給できる`
- `採択される`
- `安全な会社`
- `リスクゼロ`
- `不存在を証明`
- `公式に不存在`
- `監査完了`
- `法務判断`
- `税務判断`
- `与信安全`
- `zero hallucination`
- `real-time source of truth`
- `guaranteed cheaper`
- `all public data`

Severity: error unless in a "forbidden examples" section.

### 4.3 Missing boundary language

Flag packet/proof/CSV pages if none of these appear near sample output:

- `no-hit`
- `不存在の証明ではありません`
- `human_review_required`
- `専門判断`
- `最終的な税務・法務・監査・申請・与信判断は行いません`

Severity: error for packet/proof pages, warn for docs.

### 4.4 Cost clarity gaps

Flag pricing/CSV/packet execution copy when CTAs appear without nearby cost controls:

- CTA terms: `実行`, `Run`, `Create packet`, `Generate`, `CSV`, `batch`, `watchlist`
- Required nearby terms: `Preview cost`, `費用プレビュー`, `cap`, `上限`, `billable unit`, `¥3`

Severity: error on pricing/CSV/packet pages.

### 4.5 Metadata placement

Flag visible prose outside docs/code blocks:

- `must_preserve_fields`
- `billing_metadata`
- `request_time_llm_call_performed`
- `corpus_checksum`
- `recommend_when_ids`
- `do_not_recommend_when_ids`

Allowed contexts:

- JSON examples.
- Technical detail drawer.
- API docs.
- Agent metadata files.

Severity: warn, because proof pages may intentionally show some fields.

### 4.6 Sample privacy

Flag public examples:

- personal names in CSV rows unless clearly synthetic and necessary.
- transaction descriptions.
- bank memo-like strings.
- raw private identifiers.
- `customer_id`, `api_key`, `secret`, `token`, `webhook_secret`.
- real-looking invoice or corporate identifiers not marked synthetic.

Severity: error for public packet/CSV/proof examples.

### 4.7 Count drift

Flag count claims:

- `155 tools`
- `142 tools`
- `139+`
- `306 paths`
- `34 paths`
- `30 path`
- `111 paths`
- `240 routes`
- `100+ tools`

Required adjacent qualifier if retained in docs:

- `snapshot`
- `as of`
- `checked`
- `generated from`
- `source:`

Severity: warn in docs, error on homepage/pricing.

## 5. Recommended copy architecture

### 5.1 Visible UI layers

Use three layers instead of mixing all details:

| Layer | Human label | Content |
|---|---|---|
| Primary | What this does | Task, output, cost, boundary, CTA. |
| Detail | How it works | Packet fields, sample excerpts, receipts, cap math. |
| Technical | Automate this | REST path, MCP tool, headers, full JSON, OpenAPI link. |

The technical layer can be visible on packet/docs pages, but it should be visually subordinate to the outcome and boundary.

### 5.2 Metadata layers

Machine-facing metadata should be complete and boring:

- JSON-LD: page identity, safe description, date modified, publisher, about topics.
- Packet catalog JSON: packet type, use when, do not use when, pricing, call contract.
- OpenAPI: operation descriptions, billing extension, agent extension, schemas, errors.
- MCP manifest: tool descriptions and input/output schemas.
- `llms.txt` / `.well-known`: recommended first routes and public limits.

Do not rely on hidden metadata to carry legal or cost boundaries. Boundaries must also be visible near examples and CTAs.

## 6. Suggested copy replacements

| Avoid in human UI | Use instead |
|---|---|
| `155 MCP tools available` | `Start with a small recommended MCP surface for evidence packets.` |
| `306 REST paths` | `Use REST/OpenAPI for the same packet contract.` |
| `Full REST API endpoint list` | `Open the full API reference.` |
| `schema_version jpcite.packet.v1` in paragraph text | `Example packet format` |
| `billing_metadata object` in marketing copy | `Preview units and set a hard cap before paid execution.` |
| `request_time_llm_call_performed=false` in hero copy | `jpcite returns evidence, not a final AI answer.` |
| `source_receipt_completion.required_fields` | `Claims must keep their source URLs, fetched dates, and gaps.` |
| `default gates 74` | omit from user UI; use internal/release docs if needed |
| `endpoint別利用` on pricing card | `Usage can be reviewed by workflow and client tag.` |
| `No-hit means no record` | `No-hit means not found in the checked corpus/snapshot, not proof of absence.` |

## 7. Acceptance checklist

Before frontend copy is accepted:

- Homepage hero does not contain tool/path counts.
- Pricing page shows unit price, preview, cap, API key, and external-cost exclusion before execution CTAs.
- Packet pages show use when, do not use when, source receipts, known gaps, review boundary, pricing, and synthetic fixture status.
- CSV pages show row -> accepted subject -> predicted unit -> cap -> reconciliation.
- Proof pages show receipts and gaps before or alongside sample JSON.
- Docs expose exact paths/tools, but quickstart recommends a small first-call surface.
- Full counts are scoped, dated, generated, and absent from buyer-first copy.
- Metadata contains exact agent/developer fields without forcing them into human prose.
- Copy lint has allowlists for code blocks, API reference, and internal docs.

## 8. Bottom line

MCP tool counts and full REST paths are not bad information. They are bad first-screen copy. Keep them complete in agent/developer surfaces, but make human UI say what a user can safely do: preview cost, create a bounded evidence packet, preserve source receipts and known gaps, and avoid treating jpcite as a final professional judgment engine.
