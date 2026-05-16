# Release Gate / Go-No-Go Checklist Deep Dive

作成日: 2026-05-15  
担当: Release gate / go-no-go checklist  
位置づけ: 追加20本深掘りの38本目  
状態: pre-implementation release decision table. 実装コードは触らない。  
保存先: `docs/_internal/release_gate_checklist_deepdive_2026-05-15.md`

## 0. Executive Gate Contract

P0 実装後の release は、単に API が動くことではなく、GEO-first packet、CSV privacy、billing、source receipts、frontend copy、OpenAPI/MCP が同時に成立していることを条件にする。どれか 1 つが欠けると、AI agent が jpcite を推薦・呼び出し・引用・課金説明する流れのどこかで trust が壊れる。

Release decision:

- **GO**: P0 blocking gates が全て PASS し、manual review で blocker が残らず、post-release monitoring と rollback owner が明確。
- **CONDITIONAL GO**: blocking gate は PASS。non-blocking issue が残るが、公開文面で過剰主張せず、owner/date/monitoring が入っている。
- **NO-GO**: blocking gate が 1 件でも FAIL、不明、未実装、または証跡不足。

Hard premise:

> P0 release は **GEO-first、CSV privacy、billing、source_receipts、frontend copy、OpenAPI/MCP** が全部揃うまで出さない。

この doc は実装前の判定表であり、リリース直前に各項目を `[ ] PASS / [ ] FAIL / [ ] N/A` から 1 つ選び、証跡リンクまたはコマンド出力を記録する。

## 1. Release Gate Checklist

### 1.1 Decision Header

| Field | Value |
|---|---|
| Release candidate | `P0 GEO-first packet release` |
| Decision date/time | `YYYY-MM-DD HH:MM JST` |
| Decision owner | `__` |
| Technical owner | `__` |
| Privacy/billing reviewer | `__` |
| Public copy reviewer | `__` |
| Decision | `[ ] GO / [ ] CONDITIONAL GO / [ ] NO-GO` |
| Rollback owner | `__` |
| War-room channel | `__` |
| Release artifact hash/tag | `__` |

### 1.2 Master Gate

All blocking rows must PASS.

| Gate | Area | Blocking? | Required result | Status | Evidence |
|---|---|---:|---|---|---|
| RG-001 | P0 packet contract | Yes | All P0 packets share the common envelope and preserve source/billing/review fields | `[ ] PASS [ ] FAIL` | `__` |
| RG-002 | GEO-first positioning | Yes | Public and agent surfaces lead with evidence packets for AI discovery, not generic SEO claims | `[ ] PASS [ ] FAIL` | `__` |
| RG-003 | CSV privacy | Yes | Raw CSV rows, row-level normalized records, PII, memo, counterparty, payroll, bank/card data cannot appear in packet/debug/log/support output | `[ ] PASS [ ] FAIL` | `__` |
| RG-004 | Billing controls | Yes | Paid execution requires auth, cap, idempotency where applicable, and returns a billing receipt | `[ ] PASS [ ] FAIL` | `__` |
| RG-005 | No hidden charges | Yes | Preview, validation reject, auth reject, cap reject, quota reject, unsupported request, no-hit default, and server failure are no-charge | `[ ] PASS [ ] FAIL` | `__` |
| RG-006 | Source receipts | Yes | Every externally reusable claim maps to at least one receipt or moves to `known_gaps` | `[ ] PASS [ ] FAIL` | `__` |
| RG-007 | No-hit semantics | Yes | No-hit is represented as `no_hit_not_absence`; it never supports absence/safety/eligibility claims | `[ ] PASS [ ] FAIL` | `__` |
| RG-008 | Frontend copy | Yes | Human pages show cost, source, gap, review boundary, and professional fences without manifest/count overclaim | `[ ] PASS [ ] FAIL` | `__` |
| RG-009 | OpenAPI agent-safe | Yes | P0 or GPT30 agent spec exposes only safe first-call routes with billing/fence/must-preserve guidance | `[ ] PASS [ ] FAIL` | `__` |
| RG-010 | MCP P0 catalog | Yes | Recommended MCP first tools are discoverable, bounded, and semantically aligned with REST packet contract | `[ ] PASS [ ] FAIL` | `__` |
| RG-011 | Public examples | Yes | Examples are synthetic or public-safe, include source receipts, known gaps, cost preview, and human review flags | `[ ] PASS [ ] FAIL` | `__` |
| RG-012 | Professional boundary | Yes | No output claims final legal, tax, audit, credit, subsidy approval, or application judgment | `[ ] PASS [ ] FAIL` | `__` |
| RG-013 | Observability | Yes | Release has dashboards/alerts for usage, errors, billing, privacy rejects, source freshness, and receipt completion | `[ ] PASS [ ] FAIL` | `__` |
| RG-014 | Rollback/kill switch | Yes | Paid execution and public discovery surfaces can be disabled or rolled back independently | `[ ] PASS [ ] FAIL` | `__` |
| RG-015 | Evidence package | Yes | Release decision has test output, manual review notes, and known residual risks attached | `[ ] PASS [ ] FAIL` | `__` |

### 1.3 Area Gate Details

#### A. GEO-first P0 Packet Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| P0 packet list is fixed | Yes | `evidence_answer`, `company_public_baseline`, `application_strategy`, `source_receipt_ledger`, `client_monthly_review`, `agent_routing_decision` are documented and implemented or explicitly gated off from public launch. |
| Common envelope is present | Yes | Packet response includes `packet_id`, `packet_type`, `packet_version`, `schema_version`, `generated_at`, `corpus_snapshot_id`, `source_receipts`, `known_gaps`, `quality`, `billing_metadata`, `agent_guidance`, `_disclaimer`. |
| `request_time_llm_call_performed=false` | Yes | Present and true-to-behavior for every evidence packet. |
| Agent guidance exists | Yes | `use_when`, `do_not_use_when`, `must_preserve_fields`, `professional_fence`, and next safe step are machine-readable. |
| Public sample completeness | Yes | Each public P0 sample includes input, output JSON, source receipts, known gaps, legal/professional fence, cost preview, REST call, and MCP tool name. |
| GEO-first copy | Yes | Public pages and metadata explain that jpcite is an evidence layer for agents before answer generation. |
| Legacy route bridge | Non-blocking | Legacy evidence/artifact endpoints may remain, but docs point agents to P0 packet facade or stable equivalent. |

#### B. CSV Privacy Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Raw persistence ban | Yes | Raw CSV bytes, raw rows, row-level normalized records, memo, counterparty value, file name value, and private identifiers are not persisted or emitted. |
| Reject clusters | Yes | Payroll identity+amount, bank transfer/account identifier, card context/long digit, person contact, sensitive personal context trigger reject before packet generation. |
| Aggregate-only output | Yes | External CSV-derived packet exposes only allowed aggregate facts with row/value reconstruction risk removed. |
| Small-cell suppression | Yes | `entry_count < 3` suppresses by default; sensitive contexts use stricter k/coarsening where needed. |
| Hash policy | Yes | Public hash output is forbidden; internal dedupe uses tenant-scoped HMAC only. |
| Debug/log safety | Yes | Logs include shape/count/reject code/policy decision only; no payload value, row sample, cell value, raw exception body. |
| CSV billing interplay | Yes | Rejected rows and duplicates are not billed; preview shows accepted/rejected/duplicate counts before paid execution. |
| Support template safety | Yes | Support/admin responses cannot echo offending cell values. |

#### C. Billing / Quota / Fraud Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Paid preflight order | Yes | Auth, cap, quota, validation, unsupported scope, and idempotency conflict are checked before billable work. |
| Idempotency required | Yes | Paid POST, batch, CSV, watchlist, fanout, packet execution, and exports require `Idempotency-Key` or equivalent retry-safe mechanism. |
| Hard cap required | Yes | Paid broad execution requires request cap; production keys have monthly/customer cap. |
| Billing receipt | Yes | Every paid response includes units, unit price/version, billed/not_billed, usage id, cap state, idempotency scope/hash, external cost exclusion, support trace. |
| No-charge events | Yes | Preview, route decision, usage status, auth failure, validation reject, cap reject, quota reject, unsupported professional judgment, no-hit default, retryable server failure are no-charge. |
| Double-charge prevention | Yes | Same customer/key/endpoint/normalized payload/idempotency key returns same artifact/receipt or conflict, not a second charge. |
| Agent loop guard | Yes | Repeated paid calls for same task are capped/throttled and observable. |
| Webhook/ledger idempotency | Yes | Provider event replay cannot duplicate ledger or invoice lines. |
| Abuse response | Yes | Key revoke, anomaly alert, emergency cap, and support reconciliation path exist. |

#### D. Source Receipts / Claim Graph Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Claim granularity | Yes | Claim IDs attach only to minimal reusable facts, not final judgments or paragraphs. |
| Claim to receipt link | Yes | Every external claim has `source_receipt_ids[]` or becomes `known_gaps`. |
| Required receipt fields | Yes | Complete receipts include source URL, fetched/verified time, content hash/checksum, corpus snapshot, license, and `used_in`. |
| Public/private namespace split | Yes | Private CSV-derived claims never enter public claim namespace, public proof pages, or AI crawler surface. |
| No-hit separation | Yes | No-hit checks are separate from positive receipts and have `support_level=no_hit_not_absence`. |
| Dedupe correctness | Yes | Dedupe does not cross public/private, tenants, values, time scopes, or no-hit/positive semantics. |
| Stale/source gap visibility | Yes | Stale, missing, inferred, weak, license-limited, and unknown support are visible as `known_gaps`. |
| Receipt completion metric | Non-blocking unless below launch floor | Completion is monitored by packet type and source kind; launch floor must be set in decision notes. |

#### E. Frontend Copy / Public Surface Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Human value copy | Yes | Homepage/pricing/packet pages explain task, evidence, source receipts, known gaps, review boundary, and cost before execution. |
| Copy avoids overclaim | Yes | No "complete", "guaranteed", "100%", "final advice", "absence proven", "zero hallucination", or unsupported superiority claims. |
| Technical inventory is not hero copy | Yes | Raw MCP tool counts, REST path counts, schema internals, migration flags, route inventories, and internal table names do not lead public human pages. |
| Pricing copy | Yes | `¥3/billable unit`, free preview, cap requirement, external cost exclusion, no-charge rejects, and tax/invoice distinction are visible. |
| CSV copy | Yes | Lifecycle shows preview -> accepted/rejected/duplicate -> cap -> execute; rejected/duplicate rows not billed; raw/private rows not shown. |
| Packet page copy | Yes | Use when/do not use when, source receipts, known gaps, review boundary, synthetic fixture note, REST/MCP calls are present. |
| Agent metadata separation | Yes | Exact tool names, endpoint paths, operation IDs, must-preserve fields, and full billing metadata live in technical blocks/specs, not primary marketing prose. |
| Japanese/English consistency | Non-blocking unless contradiction | Key boundaries and cost rules match across languages and page variants. |

#### F. OpenAPI / MCP Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Agent-safe spec size | Yes | P0 strict is 12-16 paths or GPT30 slim is <=28 paths; public docs point agents to the safe subset by default. |
| Full vs agent spec split | Yes | Full OpenAPI remains complete for developers; agent-safe excludes billing mutation, OAuth mutation, admin, webhook, export, broad batch, and dangerous stateful routes. |
| Operation descriptions | Yes | P0 operations include use-when, do-not-use-when, professional fence, billing rule, no-hit rule, and must-preserve guidance. |
| Vendor metadata | Yes | Agent-safe operations include billing and agent extensions or equivalent structured metadata. |
| Required examples | Yes | Success, no-hit, validation error, rate limit, cap reject, and idempotency conflict examples exist for P0 paid/broad operations. |
| MCP P0 first tools | Yes | `previewCost`, evidence packet, company baseline, application strategy, source receipt ledger, client monthly review, usage status, route decision or stable equivalents are discoverable. |
| REST/MCP semantic parity | Yes | Same packet contract fields appear across MCP and REST outputs. |
| Discovery files | Yes | `.well-known`, MCP manifest, OpenAPI URLs, and docs links resolve and do not contradict counts or route names. |
| Legacy catalog handling | Non-blocking | Full catalog can exist, but P0 docs do not require agents to scan 100+ tools first. |

#### G. Operations / Monitoring Gate

| Check | Blocking? | Pass condition |
|---|---:|---|
| Health checks | Yes | API, docs/static, OpenAPI files, MCP manifest, cost preview, usage status, and packet creation have smoke checks. |
| Error budgets | Yes | Launch has explicit thresholds for 5xx, timeout, packet failure, billing ledger failure, privacy reject anomaly, and receipt completion drop. |
| Kill switches | Yes | Paid execution, CSV execution, packet generation, public examples, agent-safe spec, and MCP manifest can be rolled back or disabled independently. |
| Support readiness | Yes | Support can reconcile a charge from request id/usage id/idempotency hash without seeing private CSV values. |
| Incident runbook | Yes | Privacy leak, double charge, source freshness regression, OpenAPI bad publish, MCP manifest bad publish, and public copy overclaim have owner/action. |

## 2. Blocking / Non-Blocking Criteria

### 2.1 Blocking Criteria

Any item below is an automatic NO-GO until resolved or publicly gated off.

| ID | Blocking condition | Why it blocks release |
|---|---|---|
| B-001 | Any P0 packet lacks `source_receipts`, `known_gaps`, `human_review_required`, or `billing_metadata` | Agents cannot preserve evidence, limits, or cost. |
| B-002 | A reusable claim can appear without a receipt or explicit known gap | Citation/provenance contract is broken. |
| B-003 | No-hit is presented as absence, safety, eligibility, or approval evidence | Creates legal/trust risk. |
| B-004 | CSV raw rows, private identifiers, memo, counterparty values, payroll/bank/card values, or row-level detail appear in output/log/debug/support | Privacy boundary is broken. |
| B-005 | Small-cell suppression is missing for CSV-derived aggregates | Aggregate output may reconstruct private facts. |
| B-006 | Paid execution can start without required auth, cap, or idempotency controls | User can be surprised or double-charged. |
| B-007 | Preview, reject, no-hit default, or failed preflight can create a usage charge | Billing trust is broken. |
| B-008 | Billing receipt is absent or cannot reconcile invoice/support trace | Charges cannot be explained. |
| B-009 | OpenAPI agent-safe exposes admin, billing mutation, webhook, OAuth mutation, export, broad batch, or unstable internal routes | Generic agents may call unsafe stateful surfaces. |
| B-010 | MCP catalog or OpenAPI describes a route/tool as safe while runtime behavior violates cap, billing, source, or professional-fence rules | Machine-readable contract lies. |
| B-011 | Public copy claims final legal/tax/audit/credit/application judgment or guaranteed results | Professional boundary is broken. |
| B-012 | Public examples use real/private customer data or omit synthetic/public-safe marking | Demo surface leaks trust risk. |
| B-013 | Release lacks rollback/kill switch for paid execution or public discovery spec | Bad release cannot be contained quickly. |
| B-014 | Monitoring cannot detect billing ledger failure, privacy reject anomalies, source receipt completion drop, or elevated 5xx | Post-release failure is invisible. |
| B-015 | Test evidence is missing for any release-critical area | PASS is unverifiable. |

### 2.2 Non-Blocking Criteria

These can ship only if documented with owner, date, and user-visible copy that avoids overclaim.

| ID | Non-blocking condition | Required mitigation |
|---|---|---|
| NB-001 | Full public OpenAPI still has broad legacy surface | Default docs point agents to P0/GPT30 agent-safe spec; full spec is labeled developer reference. |
| NB-002 | Some legacy MCP tools remain discoverable | P0 catalog is default; legacy/gated tools are not recommended first. |
| NB-003 | Receipt completion is below ideal but above launch floor | Packet marks gaps clearly; monitoring tracks completion by packet/source kind. |
| NB-004 | Some packet facade names are bridged to existing stable endpoints | Docs show stable equivalent and avoid promising unshipped route names. |
| NB-005 | Non-critical language/localization mismatch | No contradiction on cost, privacy, source, or professional boundary. |
| NB-006 | Optional registry submissions are pending | Core discovery URLs and manifests are live; pending registries have owner/date. |
| NB-007 | Advanced SDK/CLI examples are incomplete | API/MCP quickstart and raw OpenAPI examples are enough for P0 integration. |
| NB-008 | Dashboard polish is incomplete | Alerts and minimum operational views exist; cosmetic gaps have owner/date. |
| NB-009 | Historical internal docs have old counts | Public current docs and manifests are consistent; internal stale docs are not linked as release truth. |

### 2.3 Conditional GO Template

Use only when all blocking checks PASS.

```text
Decision: CONDITIONAL GO
Remaining non-blocking issues:
- NB-__:
  Owner:
  Due:
  User-visible mitigation:
  Monitoring:

Operator accepts residual risk: [ ] yes
Rollback trigger if issue worsens:
```

## 3. Required Tests by Area

This section defines required release tests, not implementation details. Tests may be automated, scripted smoke checks, or manual verification with captured output, but every blocking gate needs evidence.

### 3.1 Packet / GEO-first Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-PKT-001 | Contract test | Every P0 packet type | Common envelope fields exist and required fields are non-null where applicable. |
| T-PKT-002 | Schema compatibility | REST and MCP packet output | Same semantic fields and compatible shapes for `source_receipts`, `known_gaps`, `billing_metadata`, `quality`, `_disclaimer`. |
| T-PKT-003 | Agent guidance | Every P0 tool/endpoint | `use_when`, `do_not_use_when`, `must_preserve_fields`, no-hit rule, cost rule, and professional fence present. |
| T-PKT-004 | Example completeness | Public examples | Input, output JSON, receipts, known gaps, cost preview, REST call, MCP tool name, synthetic/public-safe note present. |
| T-PKT-005 | Final-judgment guard | Sensitive prompts | Output does not make final legal/tax/audit/credit/application/professional decisions. |
| T-PKT-006 | LLM boundary | Packet generation | `request_time_llm_call_performed=false` is present and true-to-runtime. |

### 3.2 Source Receipt / Claim Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-SRC-001 | Contract test | Claims in all P0 packets | Every external claim has at least one `source_receipt_id` or is not emitted as a claim. |
| T-SRC-002 | Gap routing | Missing receipt fields | Incomplete support creates `known_gaps` with affected fields/records. |
| T-SRC-003 | No-hit semantics | No matching public record | Response uses `no_hit_not_absence` and does not assert absence or safety. |
| T-SRC-004 | Dedupe | Duplicate claims from multiple sources | Dedupe preserves all receipt IDs and does not upgrade support incorrectly. |
| T-SRC-005 | Public/private split | CSV-derived private facts | Private claims never appear in public receipt ledger, proof page, or crawler-facing samples. |
| T-SRC-006 | Freshness/license | Stale or restricted source | Stale/license-limited support appears as `known_gaps` or constrained `license_boundary`. |

### 3.3 CSV Privacy Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-CSV-001 | Reject fixture | Payroll CSV | Processing stops with safe reject code; no row/cell/sample value in response/log. |
| T-CSV-002 | Reject fixture | Bank transfer/account CSV | Processing stops before aggregate generation; no account/name/value leakage. |
| T-CSV-003 | Reject fixture | Card/payment identifier CSV | Processing stops with no PAN-like value echoed. |
| T-CSV-004 | Redaction fixture | Memo/counterparty/free-text CSV | Output contains presence/count/safe category only; raw memo/counterparty values absent. |
| T-CSV-005 | Small-cell fixture | Aggregates with `entry_count` 1-2 | Cell suppressed or coarsened; exact value and dimensions not reconstructable. |
| T-CSV-006 | Hash fixture | Dedupe/idempotency | Public response contains no raw hash; internal hash, if exposed to logs, is tenant-scoped and non-reversible by policy. |
| T-CSV-007 | Formula injection | Cells beginning `=`, `+`, `-`, `@` | Values are rejected/redacted/escaped and never emitted as spreadsheet-executable text. |
| T-CSV-008 | Billing CSV fixture | Duplicate/rejected/accepted rows | Preview and receipt bill only accepted deduped subjects. |
| T-CSV-009 | Support/debug audit | Error paths | Logs/support payloads include only reject code, shape, counts, and trace IDs. |

### 3.4 Billing / Quota / Fraud Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-BILL-001 | Preflight | Paid request without API key | Rejected before work; no usage ledger charge. |
| T-BILL-002 | Preflight | Paid request without cap | Rejected before work; no usage ledger charge. |
| T-BILL-003 | Idempotency | Same key and same normalized payload | Retry returns same artifact/receipt or pending state; no duplicate charge. |
| T-BILL-004 | Idempotency conflict | Same key and different payload | `409` or equivalent conflict; no charge. |
| T-BILL-005 | No-charge events | Preview, validation reject, quota reject, cap reject, unsupported professional judgment, no-hit default | No usage charge and response says no-charge. |
| T-BILL-006 | Receipt completeness | Successful paid execution | Receipt includes usage id, units, price/version, cap, idempotency hash/scope, billed state, external cost exclusion. |
| T-BILL-007 | Webhook replay | Provider event repeated | Ledger/invoice line remains single. |
| T-BILL-008 | Cap boundary | Request would exceed cap | Rejected before billable work; receipt/error is no-charge. |
| T-BILL-009 | Agent loop | Repeated paid calls with same/near-same intent | Loop guard or throttle triggers and is observable. |
| T-BILL-010 | Support reconciliation | Given request id/usage id | Operator can explain charge without private CSV values. |

### 3.5 Frontend Copy Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-COPY-001 | Copy lint | Public homepage, pricing, packet pages, CSV page, docs quickstart | Banned overclaim/professional-final terms are absent or safely fenced. |
| T-COPY-002 | Pricing review | Pricing and execution CTAs | Unit price, free preview, cap, no-charge rejects, external cost exclusion, tax/invoice distinction are visible. |
| T-COPY-003 | CSV page review | CSV intake docs/UI | Raw/private row boundary, accepted/rejected/duplicate flow, cap, and no billing for rejects/duplicates are clear. |
| T-COPY-004 | Packet page review | P0 packet pages | Use when/do not use when, receipts, gaps, review flag, synthetic note, REST/MCP call block present. |
| T-COPY-005 | Metadata separation | Human UI vs technical docs | Raw route/tool counts and schema internals are not first-view marketing claims. |
| T-COPY-006 | Language consistency | Japanese/English or page variants | Cost, privacy, source, and professional boundary do not contradict each other. |

### 3.6 OpenAPI / MCP Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-API-001 | Spec size | Agent-safe OpenAPI | P0 strict 12-16 paths or GPT30 <=28 paths; documented default points there. |
| T-API-002 | Spec exclusion | Agent-safe paths | No admin, billing mutation, OAuth mutation, webhook, export, broad batch, internal/private route. |
| T-API-003 | Operation metadata | P0 operations | Descriptions include routing, fence, billing, no-hit, must-preserve fields, and examples. |
| T-API-004 | Error examples | P0 paid/broad operations | Validation, rate limit, cap reject, idempotency conflict, no-hit examples exist. |
| T-API-005 | MCP catalog | P0 tools | P0 first tools are discoverable, have REST equivalents, and state billing/cap/idempotency rules. |
| T-API-006 | REST/MCP parity | Representative packet via REST and MCP | Same semantic packet fields; no contradictory billing or source fields. |
| T-API-007 | Discovery smoke | `.well-known`, `llms.txt`, MCP manifest, OpenAPI URLs | All resolve, have current version/date, and do not contradict public docs. |
| T-API-008 | Full spec continuity | Full public OpenAPI | Full spec remains available for SDK/backend use; agent-safe is not the only contract. |

### 3.7 Ops / Monitoring Tests

| Test ID | Type | Required coverage | Pass condition |
|---|---|---|---|
| T-OPS-001 | Smoke | API health, docs, OpenAPI, MCP manifest, cost preview, usage status | All pass from external network. |
| T-OPS-002 | Alert test | 5xx/timeout, billing ledger failure, source receipt completion drop, privacy reject spike | Alerts route to owner channel with runbook link. |
| T-OPS-003 | Rollback drill | Paid execution off, CSV execution off, agent spec rollback, MCP manifest rollback | Operator can execute without code changes. |
| T-OPS-004 | Dashboard review | Launch dashboard | Shows traffic, paid executions, no-charge events, cap rejects, privacy rejects, receipt completion, source freshness, agent-safe spec hits. |
| T-OPS-005 | Incident templates | Privacy leak, double charge, bad source, bad spec, bad copy | Templates exist with owner, severity, user notice, and rollback path. |

## 4. Manual Review Checklist

Manual review is required because the highest-risk failures are semantic: overclaim, privacy leakage through examples, no-hit misuse, and agent routing ambiguity.

### 4.1 Reviewer Assignment

| Area | Reviewer | Backup | Completed |
|---|---|---|---|
| GEO-first packet contract | `__` | `__` | `[ ]` |
| CSV privacy | `__` | `__` | `[ ]` |
| Billing / quota / fraud | `__` | `__` | `[ ]` |
| Source receipts / claim graph | `__` | `__` | `[ ]` |
| Frontend/public copy | `__` | `__` | `[ ]` |
| OpenAPI/MCP | `__` | `__` | `[ ]` |
| Ops/monitoring/rollback | `__` | `__` | `[ ]` |

### 4.2 Manual Packet Review

- [ ] For each P0 packet, open one success example and one gap/no-hit example.
- [ ] Confirm no packet reads like final professional advice.
- [ ] Confirm `known_gaps` are understandable to both humans and agents.
- [ ] Confirm `human_review_required=true` appears for legal, tax, audit, credit, application, grant, DD, or accounting-adjacent contexts.
- [ ] Confirm `request_time_llm_call_performed=false` is not contradicted by copy.
- [ ] Confirm cost preview and execution receipt examples do not imply external LLM/search/cloud/runtime costs are included.
- [ ] Confirm examples are synthetic or public-safe and labeled as such.

### 4.3 Manual CSV Privacy Review

- [ ] Inspect CSV examples and screenshots for private row values, names, counterparties, memo text, payroll, bank, card, email, phone, address, or file-name leakage.
- [ ] Inspect rejected CSV responses for safe reject code only, no offending value.
- [ ] Inspect debug/admin/support examples for counts/shape only, no row sample.
- [ ] Verify small-cell examples suppress `entry_count < 3`.
- [ ] Verify duplicate/rejected rows are described as not billed.
- [ ] Verify public CSV packet examples cannot reconstruct a row by combining dimensions.

### 4.4 Manual Billing Review

- [ ] Confirm every paid CTA or tool description requires preview/cap where relevant.
- [ ] Confirm paid POST/batch/CSV/watchlist/fanout docs require idempotency.
- [ ] Confirm no-charge cases are listed in pricing/docs/error examples.
- [ ] Confirm receipt example has enough fields for support reconciliation.
- [ ] Confirm "¥3/billable unit" is not framed as total workflow cost.
- [ ] Confirm anonymous quota copy does not promise reliable production attribution.
- [ ] Confirm support/refund paths can handle double-charge or key-leak disputes.

### 4.5 Manual Source Receipt Review

- [ ] Pick at least 10 claims across packet types and trace each to source receipts.
- [ ] Confirm no-hit examples are not used as positive support.
- [ ] Confirm stale, inferred, weak, missing, and license-limited support surfaces as `known_gaps`.
- [ ] Confirm source receipt fields include URL, fetched/verified time, hash/checksum, snapshot, license, and used-in references.
- [ ] Confirm private CSV-derived facts are tenant/private only and absent from public proof/discovery pages.
- [ ] Confirm claim IDs are fact-level and not paragraph/final-judgment IDs.

### 4.6 Manual Frontend Copy Review

- [ ] Homepage first viewport explains evidence layer value without raw route/tool inventory.
- [ ] Pricing page shows preview, cap, billable unit, no-charge rejects, external cost exclusion.
- [ ] Packet pages show use when/do not use when and professional boundary.
- [ ] CSV page leads with privacy and billing lifecycle, not broad upload claims.
- [ ] No page claims guaranteed eligibility, guaranteed savings, complete data, final advice, absence proof, or official approval.
- [ ] Technical details are available in docs/code blocks/specs without overwhelming buyer copy.
- [ ] Japanese and English copy do not disagree on cost, privacy, source, or professional boundary.

### 4.7 Manual OpenAPI / MCP Review

- [ ] Import agent-safe OpenAPI into a generic agent/action builder and confirm operation names are understandable.
- [ ] Confirm first-call route choice is obvious for public-data evidence, company baseline, application strategy, CSV review, and citation verification.
- [ ] Confirm agent-safe spec does not expose admin/billing mutation/webhook/OAuth mutation/export/broad batch routes.
- [ ] Confirm P0 operation descriptions include billing, cap, idempotency, no-hit, professional fence, and must-preserve fields.
- [ ] Confirm MCP P0 catalog maps to REST equivalents and does not require scanning the full catalog.
- [ ] Confirm discovery files and docs do not publish contradictory path/tool counts.

### 4.8 Manual Ops Review

- [ ] Run release smoke from outside the deployment network.
- [ ] Confirm rollback/kill switches are documented and assigned.
- [ ] Confirm dashboards are visible to on-call owner.
- [ ] Confirm alert routing is active.
- [ ] Confirm incident templates and public/internal communication drafts exist for privacy leak and double-charge.
- [ ] Confirm a post-release checkpoint is scheduled at 1h, 4h, 24h, and 72h.

## 5. Post-Release Monitoring Items

### 5.1 First 72 Hours

| Metric / Signal | Owner | Threshold / Watch Rule | Action |
|---|---|---|---|
| API 5xx rate | `__` | Above launch SLO threshold for 10 minutes | Pause paid execution if packet creation affected; investigate. |
| Packet success rate by type | `__` | Sudden drop or one packet type failing | Gate affected packet type and update status copy. |
| Source receipt completion | `__` | Completion below release floor or sharp drop | Disable affected packet examples or mark gaps; investigate source pipeline. |
| Known gap rate | `__` | Spike in blocking/stale/source_missing gaps | Check source freshness and receipt generation. |
| No-hit outputs | `__` | Increase in no-hit packets or user complaints | Audit no-hit copy and routing; confirm no absence claims. |
| Privacy rejects | `__` | Unexpected drop to near zero or spike | Drop may mean detector failure; spike may mean bad UX or attack. |
| CSV small-cell suppression count | `__` | Unexpected drop on CSV traffic | Check suppression pipeline before continuing CSV release. |
| Billing no-charge ratio | `__` | Unexpected paid/no-charge mix | Audit preview/reject billing rules. |
| Duplicate/idempotent retries | `__` | Spike or duplicate charge report | Verify idempotency ledger and support queue. |
| Cap rejects | `__` | Spike after docs/agent launch | Improve preview/cap UX; not a release blocker unless paid work starts anyway. |
| Usage ledger failures | `__` | Any sustained error | Stop paid execution; prevent unreceipted charges. |
| Agent-safe OpenAPI hits/errors | `__` | 404/5xx/import failures | Roll back spec URL or static mirror. |
| MCP manifest fetch/errors | `__` | Registry/client fetch failure | Roll back manifest or disable changed entries. |
| Public copy error reports | `__` | Any credible overclaim/privacy/cost confusion | Patch copy or unpublish affected page. |
| Support tickets | `__` | Billing surprise, privacy concern, no-hit misunderstanding | Triage daily during first 72h. |

### 5.2 Ongoing Weekly Monitoring

| Item | Review cadence | Required output |
|---|---|---|
| Receipt completion by source kind and packet type | Weekly | Trend and top gap reasons. |
| Source freshness buckets | Weekly | Fresh/acceptable/stale distribution and stale owner list. |
| Billing disputes and refunds | Weekly | Count, root cause, prevention action. |
| CSV rejects and suppression | Weekly | Reject reason distribution; false-positive/false-negative review. |
| Agent route usage | Weekly | Which P0 tools/endpoints agents call first and where they fail. |
| OpenAPI/MCP drift | Weekly | Diff between live spec, static docs, manifest, examples, and docs copy. |
| Public copy drift | Weekly | New pages checked for banned claims and pricing/privacy boundary. |
| Error code distribution | Weekly | Top validation/quota/cap/idempotency/no-hit errors and docs improvements. |
| Abuse/key anomaly | Weekly | Key leak, unusual ASN/device, cap burn, preview scraping. |
| Support reconciliation quality | Weekly | Time to explain charge without private data. |

### 5.3 Rollback Triggers

Rollback or disable the affected surface immediately when any trigger occurs.

| Trigger | Scope to disable | Owner action |
|---|---|---|
| Private CSV value appears in output/log/debug/support | CSV execution and public CSV examples | Disable CSV packet path, preserve logs, incident response. |
| Duplicate charge confirmed | Paid execution for affected operation | Disable paid path, reconcile ledger, notify affected users. |
| Paid work starts after cap/auth/idempotency reject | Paid execution | Stop paid execution until preflight is fixed. |
| Agent-safe spec exposes unsafe stateful route | Agent-safe OpenAPI and MCP catalog | Roll back spec/manifest to previous known-good snapshot. |
| No-hit copy/output implies absence or approval | Affected packet/page/spec examples | Patch or unpublish; audit similar surfaces. |
| Source receipts missing from successful packets | Affected packet type | Disable packet type or mark as preview-only. |
| Public page makes professional-final or guaranteed-result claim | Affected page | Unpublish/patch immediately. |
| Usage receipt write fails while output is served | Paid execution | Fail closed; stop paid route until atomicity restored. |
| Monitoring blind spot discovered for billing/privacy/source receipts | Release-wide or affected area | Pause expansion; add monitoring before more traffic. |

## 6. Final Sign-Off Form

```text
Release candidate:
Decision time:

Blocking gates:
- GEO-first P0 packets: PASS / FAIL
- CSV privacy: PASS / FAIL
- Billing controls: PASS / FAIL
- Source receipts: PASS / FAIL
- Frontend copy: PASS / FAIL
- OpenAPI/MCP: PASS / FAIL
- Ops/monitoring/rollback: PASS / FAIL

Automated test evidence:
- Packet:
- CSV:
- Billing:
- Source receipt:
- Frontend copy:
- OpenAPI/MCP:
- Ops:

Manual review evidence:
- Packet:
- CSV privacy:
- Billing:
- Source receipts:
- Copy:
- OpenAPI/MCP:
- Ops:

Known non-blocking issues:
- 

Post-release monitoring owner:
Rollback owner:

Final decision:
[ ] GO
[ ] CONDITIONAL GO
[ ] NO-GO

Approver:
```

## 7. Related Internal Specs

- `docs/_internal/p0_geo_first_packets_spec_2026-05-15.md`
- `docs/_internal/csv_privacy_edge_cases_deepdive_2026-05-15.md`
- `docs/_internal/billing_risk_controls_deepdive_2026-05-15.md`
- `docs/_internal/source_receipt_claim_graph_deepdive_2026-05-15.md`
- `docs/_internal/frontend_copy_audit_deepdive_2026-05-15.md`
- `docs/_internal/openapi_agent_safe_subset_deepdive_2026-05-15.md`
- `docs/_internal/developer_mcp_api_deepdive_2026-05-15.md`
- `docs/_internal/go_no_go_gate.md`
