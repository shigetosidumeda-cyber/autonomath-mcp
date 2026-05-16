# Billing Risk Controls Deep Dive

作成日: 2026-05-15  
担当: Billing risk / fraud / retry / quota edge cases  
位置づけ: 追加20本深掘りの30本目  
状態: pre-implementation planning only  
制約: 実装コードは触らない。課金・不正利用・再送・quota の信頼境界を仕様化する。

## 0. Executive Control Contract

AI エージェント経由の従量課金で最も壊れやすい信頼は「ユーザーが意図していない請求」「再送による二重課金」「無料 preview の誤解」「共有 IP による quota 不信」「漏洩 key による cost DDoS」である。jpcite は単価の安さだけで推薦されるのではなく、エージェントが安全に呼べる課金制御を持つことで推薦される。

P0 contract:

- Paid execution は API key、hard cap、Idempotency-Key の 3 点が揃うまで billable work を開始しない。
- Cost preview / route decision / usage status / auth failure / validation reject / cap reject / quota reject / unsupported request / server failure は no-charge event とする。
- Retry は同じ customer、API key、endpoint、normalized payload、Idempotency-Key に束ね、成功済み execution を二重課金しない。
- Anonymous quota は trial/discovery 用であり、AI hosted agent、Custom GPT、MCP relay、office/VPN/NAT の本番利用を支えるものとして説明しない。
- 無料 preview は「見積もりだけが無料」であり、preview の結果から paid execution へ進むには明示 cap と user/operator confirmation が必要。
- Billing receipt は every paid response に含め、billed / not_billed / cap / idempotency / external cost exclusion / support trace を機械可読にする。
- Agent loop は billing risk と abuse risk の両方として扱い、tool description、schema、server-side guard、receipt、alert の全層で止める。

## 1. Risk Principles

| Principle | Required rule | Why it matters for AI agents |
|---|---|---|
| Charge only after useful success | Bill only after a successful billable output exists and is attached to a receipt. | Agent retries and tool loops must not create invisible charges. |
| Reject before work | Auth, cap, quota, validation, unsupported scope, and idempotency conflicts fail before expensive execution. | A model can make mistakes; the server must be the final guard. |
| Preview is not permission | Preview returns estimate only. It does not authorize execution, reserve spend, or consume execution quota. | Agents often treat a successful dry run as approval; do not. |
| Cap is hard | If predicted maximum exceeds request cap or monthly cap, no billable work starts. | Prevents "small unit price, huge fanout" failures. |
| Retry is deduped | Same idempotency scope returns the same execution/receipt, not a new billable event. | Network timeouts are normal in agent chains. |
| Quota is honest | Anonymous IP quota is presented as best-effort trial only. Paid key/OAuth is required for reliable attribution. | Shared IPs make per-person fairness impossible. |
| Key leaks are assumed | Caps, anomaly alerts, revoke path, and key redaction assume keys will be pasted into prompts/logs someday. | Agent ecosystems copy config across tools. |
| External costs are separate | jpcite receipt excludes LLM, search, runtime, cloud, platform, and integration costs. | Users must not infer "total AI workflow cost" from jpcite billing alone. |

## 2. Abuse Scenarios

### 2.1 Scenario Matrix

| ID | Scenario | Trigger | Failure if uncontrolled | P0 control | Billing result |
|---|---|---|---|---|---|
| BR-001 | Shared IP exhausts anonymous quota | Hosted GPT/agent traffic from same egress | Real user sees quota exceeded and thinks product is broken | Treat anonymous quota as trial only; expose usage status; recommend API key/OAuth for production | Not billed |
| BR-002 | Retry after timeout double-charges | Agent retries POST with new request id | Two successful packets billed for same intent | Require Idempotency-Key on paid POST/batch/CSV/watchlist/export | One billed execution |
| BR-003 | Agent tool loop | Model repeatedly calls paid packet for same answer | Many small charges accumulate | Max paid tool calls per conversation/task, cap, repeated-payload detection | Stop once cap/loop guard hit; rejected calls not billed |
| BR-004 | Missing cap on broad fanout | Agent expands all matching programs/companies | Cost exceeds user expectation | Hard reject paid broad work without cap; preview first | Not billed |
| BR-005 | Cap too low but work begins partially | Server starts execution then discovers cap gap | Partial charge dispute | Conservative preflight estimate and reject before work | Not billed |
| BR-006 | API key pasted into prompt | User/agent exposes key to model transcript | Key reused by third party | Key pattern redaction, rotate/revoke, monthly cap, suspicious-use alerts | Legit calls billed until revoke unless abuse policy credits |
| BR-007 | Key committed to repo | Developer publishes key | Automated scraping spends cap | Secret scanning docs, emergency revoke, per-key anomaly limits | Charges capped; disputed abuse review possible |
| BR-008 | Free preview misunderstood | User believes preview result means execution free | Paid call surprises user | Preview response says no charge for preview, execution requires API key/cap/confirmation | Preview not billed; execution billed only with controls |
| BR-009 | Preview scraping | Bot calls cost preview as free metadata endpoint | Availability degradation | Separate preview rate limit and payload size limits; no execution quota consumption | Not billed |
| BR-010 | Idempotency key reused with changed payload | Client bug reuses key | Wrong cached receipt returned or hidden execution | Conflict on same key + different normalized payload hash | Not billed |
| BR-011 | Cross-tenant idempotency collision | Shared client uses same idempotency key | Tenant sees another tenant state | Scope idempotency by tenant/customer/API key/endpoint/payload hash | Not billed and no data leak |
| BR-012 | No-hit charged as proof of absence | User pays for not_found and treats it as official absence proof | Trust/legal dispute | No-hit/not-found is not billable by default and marked known gap | Not billed |
| BR-013 | Batch includes duplicates | CSV repeats same entity 100 times | User billed for rows not subjects | Normalize and dedupe billable subjects before estimate/execution | Duplicate rows not billed |
| BR-014 | Pairwise matrix explosion | N programs create N*(N-1)/2 pairs | Unexpected large charge | Preview pair count; cap check; default max pair limit | Reject above cap/limit; not billed |
| BR-015 | Agent retries with different idempotency keys | Model generates new key every retry | Server cannot dedupe intent | Client guidance plus server repeated payload window warning/throttle | First success billed; repeated suspicious calls may be blocked |
| BR-016 | Billing webhook replay | Payment provider retries event | Duplicate ledger entry | Ledger event idempotency by provider event id and internal usage id | No duplicate invoice line |
| BR-017 | Partial server failure after output | Output produced but receipt write fails | User sees result without billing trace | Atomic usage ledger/receipt write before response; fail closed if receipt cannot persist | Prefer no response/no charge over unreceipted charge |
| BR-018 | Partial server failure after receipt | Receipt persisted but response timeout | User retries and fears double charge | Idempotency returns same receipt and artifact pointer | One billed execution |
| BR-019 | Clock/month boundary race | Calls near month end across timezones | Monthly cap inconsistently applied | Use canonical billing timezone and ledger period in receipt | Deterministic bill or reject |
| BR-020 | Stolen key cost DDoS | Valid key used from unusual IP/tool | Monthly cap burns quickly | Per-key velocity anomaly, new ASN/device alerts, emergency revoke | Capped; suspicious usage review |
| BR-021 | Client tag spoofing | Agent changes `X-Client-Tag` to bypass per-client cap | Spend misattributed | Client tag is metadata, not auth; cap scope remains key/customer/project | Bill to key owner only |
| BR-022 | Tool description omits billing | Agent calls paid tool without warning user | Recommendation penalty | Tool descriptions include billable unit, preview/cap/idempotency rule | Server still enforces controls |
| BR-023 | Streaming output billed before completion | Stream starts then disconnects | User charged for unusable partial output | Bill only on committed artifact/receipt; partial streams not billed unless resumable artifact exists | Not billed unless committed |
| BR-024 | Free preview calls paid subtool internally | Preview implementation reuses paid execution path | Hidden charges | Preview path cannot emit usage ledger rows; contract test | Not billed |
| BR-025 | Quota bypass via IPv6 rotation | Anonymous actor changes IPs | Free endpoint scraping | WAF/device/rate heuristics; require API key for broad work | Not billed |
| BR-026 | Organization shared key no per-project cap | One integration consumes all budget | Internal dispute | Optional project/client cap under customer monthly cap | Bill within configured scopes |
| BR-027 | Unsupported professional judgment request | Agent asks for legal/tax/credit conclusion | Charge for unusable answer | Reject or return free boundary guidance before billable work | Not billed |
| BR-028 | Invoice mismatch with API receipt | Stripe/tax invoice differs from API estimate | Accounting distrust | Receipt marks API estimate vs final tax/invoice authority | Ledger reconciles with invoice |
| BR-029 | Sandbox/preview environment confused with production | User tests with real key in dev | Unexpected charges | Environment marker in key/receipt; test keys cannot bill | Test not billed |
| BR-030 | Support cannot explain charge | User asks "why was I billed?" | Refund/support burden | Receipt contains request id, usage id, idempotency key hash, units, cap, artifact pointer | Support can reconcile |

### 2.2 Highest-Risk Agent Patterns

| Pattern | Why it is dangerous | Required prevention |
|---|---|---|
| "Keep searching until confident" | Confidence loops can repeatedly call paid tools. | Tool schema must require max units/cap and server loop detection. |
| "Retry on any non-2xx" | Validation/cap/quota errors become repeated requests. | Error response includes `retryable=false` and `billing=no_charge`. |
| "Use a new idempotency key every call" | Dedupe no longer maps to user intent. | Client docs distinguish first execution key from retry key. |
| "Preview every candidate then execute all" | Free preview becomes broad discovery crawler. | Preview rate limits and broad preview limits. |
| "Ask tool to decide if paid call is worth it" | Paid tool can be called just to route. | Free `agent_routing_decision` remains control plane. |
| "Batch all rows in uploaded CSV" | Invalid/duplicate/private rows inflate perceived bill. | Preview shows rejected/duplicate/accepted billable subjects first. |
| "Use anonymous mode in public GPT" | Shared IP quota collapses and attribution is impossible. | Public GPTs require fixed builder key or per-user auth for paid mode. |

## 3. Idempotency Controls

### 3.1 Required Scope

Paid retry-sensitive operations require `Idempotency-Key`:

- Paid POST packet creation.
- Batch search/detail/packet creation.
- CSV intake execution and CSV-derived packet creation.
- Fanout over companies, programs, sources, watchlists, or saved searches.
- Export/download bundle creation.
- Any operation that can create a usage ledger row, artifact, or invoice line.

Canonical idempotency scope:

```text
idempotency_scope =
  customer_id
  + api_key_id
  + billing_environment
  + endpoint_id
  + normalized_payload_hash
  + idempotency_key
```

Do not scope only by raw `Idempotency-Key`. Agents and SDKs can reuse common strings such as `retry-1`, `test`, or timestamps across tenants.

### 3.2 Normalized Payload Hash

The payload hash must be generated after canonicalization:

- Sort object keys and normalize enum casing where the API already treats values as equivalent.
- Remove non-semantic fields such as client request id, local timestamp, UI trace label, or retry attempt count.
- Preserve semantic fields such as subject identifiers, requested packet type, filters, requested limit, export format, cap value, and billing environment.
- For CSV, hash the approved normalized execution manifest, not raw CSV values. Raw CSV bytes and cells must not be persisted for idempotency.
- Include pricing version when a different pricing version would change billed units.

### 3.3 State Machine

| State | Meaning | Retry behavior | Billing behavior |
|---|---|---|---|
| `started` | Preflight accepted and execution lock acquired | Return pending or retry-after | No bill yet |
| `preflight_rejected` | Auth/cap/quota/validation/idempotency conflict failed before work | Return same rejection if same scope | Not billed |
| `executing` | Billable work running | Return pending if duplicate arrives | No new bill |
| `committed_success` | Artifact/output and usage ledger committed | Return same receipt/artifact pointer | Already billed once |
| `committed_no_charge` | Completed but produced no billable unit | Return same no-charge receipt | Not billed |
| `failed_retryable` | Internal failure before committed output | Allow retry with same key | Not billed unless later succeeds |
| `failed_terminal` | Unsupported or invalid after safe preflight | Return same error | Not billed |

### 3.4 Conflict Rules

| Case | Response | Charge |
|---|---|---|
| Same key, same normalized payload, first request still running | `202 idempotency_in_progress` or existing pending envelope | No new charge |
| Same key, same normalized payload, previous success | `200/201` with same artifact and receipt | No new charge |
| Same key, different normalized payload | `409 idempotency_key_conflict` | Not billed |
| Same payload, different key, within suspicious retry window | Execute only if under cap, but emit warning/throttle if pattern repeats | At most one per accepted execution; abuse controls may block |
| Same key after expiry | Treat as new only if outside retention and client explicitly accepts | Billed only if new execution succeeds |

P0 retention target: 72 hours for idempotency metadata. Longer retention is preferred for batch/CSV/export because agents and background jobs often retry after human intervention.

## 4. Cap Controls

### 4.1 Cap Types

| Cap | Scope | Required? | Purpose |
|---|---|---:|---|
| Request hard cap | One paid execution request | Yes for all paid execution | Stops a single tool call from exceeding user intent |
| Monthly customer cap | Customer billing period | Yes for production paid key | Stops leaked key or loop from burning unlimited spend |
| API key cap | Individual key | Recommended | Isolates integrations and agents |
| Project/client cap | `X-Client-Tag` or project id under authenticated customer | Recommended for agencies/accountants | Separates end-client spend |
| Tool-call cap | Conversation/task level | Recommended for agent clients | Stops repeated calls even when each is cheap |
| Preview rate cap | IP/key/client | Yes | Prevents free preview scraping and availability abuse |

### 4.2 Preflight Order

Paid execution must pass checks in this order before billable work:

1. Parse request shape without running external or expensive source work.
2. Authenticate API key and verify environment.
3. Reject query-string keys or malformed Authorization.
4. Validate endpoint supports paid execution.
5. Validate request is not a prohibited professional judgment or unsupported scope.
6. Validate `Idempotency-Key` is present for retry-sensitive operations.
7. Compute normalized payload hash and acquire idempotency lock.
8. Build execution manifest and conservative predicted billable units.
9. Require request hard cap and compare predicted maximum to cap.
10. Compare predicted maximum to monthly/key/project remaining caps.
11. Apply rate/velocity/abuse limits.
12. Start billable work only after all checks pass.

If any step rejects, response must include `billing.no_charge=true`.

### 4.3 Conservative Estimate Rules

| Workflow | Conservative predicted units | Notes |
|---|---:|---|
| Single evidence packet | 1 | Final may be 0 if no sourced output. |
| Company baseline | Count of unique resolvable candidate subjects | Ambiguous/unresolved subjects rejected before billable work. |
| CSV monthly review | Count of accepted unique billable subjects | Duplicates, invalid rows, unsupported rows excluded. |
| Batch packets | Requested subject count after dedupe, capped by request limit | No-hit final units may be lower. |
| Funding traceback | Requested limit or maximum records to return | No-hit not billed. |
| Pairwise compatibility | `N*(N-1)/2` for unique program ids | Default hard limit required. |
| Export bundle | `ceil(records_exported / 100)`, min 1 | Only if export artifact is created. |
| Watchlist delta | Accepted watchlist items evaluated | If changed-only pricing is later introduced, preview must say so. |

### 4.4 Cap Error Semantics

| Condition | HTTP / code | Retryable | Charge |
|---|---|---:|---:|
| Missing request cap | `400 cost_cap_required` | false until caller adds cap | no |
| Request cap below predicted maximum | `402 cost_cap_exceeded` | false unless scope/cap changes | no |
| Monthly customer cap reached | `402 monthly_cap_reached` or `429 spend_limit_reached` | false until period/cap changes | no |
| Key cap reached | `402 key_cap_reached` | false until cap/key changes | no |
| Project/client cap reached | `402 client_cap_reached` | false until cap/client changes | no |
| Preview rate limit | `429 preview_rate_limited` | true after reset | no |
| Execution rate limit | `429 execution_rate_limited` | true after reset | no |

Every cap response must include:

- `predicted_units`
- `predicted_jpy_ex_tax`
- `predicted_jpy_inc_tax`
- `provided_cap_jpy_inc_tax` when present
- `remaining_cap_jpy_inc_tax` when authenticated
- `billing.no_charge=true`
- `retryable`
- `suggested_next_action`

## 5. Quota Controls

### 5.1 Anonymous Quota Positioning

Anonymous quota is for small discovery and demos only:

```text
anonymous_free_quota = 3 execution requests / day / IP
cost_preview_consumes_anonymous_execution_quota = false
paid_batch_csv_watchlist_export_anonymous_allowed = false
```

Agent-facing copy must avoid implying that anonymous quota maps to a person. Hosted agents, shared offices, VPNs, mobile carrier NAT, CI, and Custom GPT actions can share egress IPs.

Required phrasing:

```text
Anonymous quota is best-effort trial capacity by observed network origin. For reliable usage attribution, spend caps, receipts, and support, use an API key or per-user authentication.
```

### 5.2 Quota Buckets

| Bucket | Key | Applies to | Billing impact |
|---|---|---|---|
| Anonymous execution | IP + day + endpoint class | Free small execution only | Exceeded calls not billed |
| Anonymous preview | IP + day/hour + payload class | Cost preview | Separate from execution quota; not billed |
| Authenticated execution rate | API key + endpoint class + time window | Paid calls | Rate rejected calls not billed |
| Authenticated preview | API key + time window | Preview | Not billed |
| Abuse velocity | API key/customer/IP/ASN/tool tag | Sudden spikes and loops | May block before work; not billed |
| Monthly cap | Customer + billing period | Paid ledger | Prevents additional billed work |
| Project cap | Customer + project/client tag + period | Paid ledger | Prevents additional billed work |

### 5.3 Shared IP Edge Cases

| Edge case | Expected behavior | User-facing explanation |
|---|---|---|
| Custom GPT users share egress and hit quota | Return anonymous quota exceeded; no paid fallback without key | "The shared anonymous trial pool is exhausted; use a configured API key for reliable use." |
| Corporate VPN user is blocked by coworker usage | Same as above | "Anonymous quota is network-origin based, not per-person." |
| MCP stdio client cannot reveal true end-user IP | Do not claim reliable anonymous quota | "Usage attribution requires API key or host-provided auth." |
| CI tests repeatedly call free endpoints | Rate limit or require test key | "Automated usage needs a non-billing test key or paid key with cap." |
| IPv6 rotation | Aggregate by subnet/behavior where possible | Do not overpromise fairness; broad work still requires key. |

## 6. API Key Checks

### 6.1 Key Acceptance Rules

| Rule | Required behavior |
|---|---|
| Header only | Accept API key only via `Authorization: Bearer ...` or approved server-side connector config. |
| No query string | Reject keys in query string with no charge and redact value from logs. |
| No echo | Never return key value in API response, receipt, error, logs, examples, support export, or generated artifact. |
| Store hash only | Store server-side HMAC/hash and metadata, not plaintext key. |
| Environment-bound | Test/sandbox keys cannot create production charges. Production keys cannot be used in test examples by default. |
| Scope-bound | Key metadata should include customer, environment, allowed endpoint classes, cap, status, created_at, last_used_at. |
| Revocable | Revocation takes effect immediately for auth, rate, cap, idempotency, and cache namespaces. |
| Rotatable | Rotation supports overlapping validity window only when explicitly requested. |
| Least privilege | Public demo/GPT builder keys should be restricted to specific endpoint classes and low caps. |

### 6.2 Leak Response

| Signal | Severity | Action |
|---|---|---|
| Key appears in incoming prompt/payload | high | Redact in logs, warn response if safe, recommend rotation |
| Key appears in query string | high | Reject request, revoke optional, no charge |
| Key appears in public repo/known secret scanner alert | critical | Revoke or suspend key, notify owner |
| Unusual ASN/country/tool tag for key | medium/high | Alert, reduce concurrency, require confirmation for broad work |
| Spend velocity above baseline | high | Temporarily enforce stricter cap/rate until owner confirms |
| Repeated cap failures after key leak signal | high | Suspend broad endpoints for key |

### 6.3 Key Metadata for Receipts

Receipts must not expose secret values. They may expose:

- `api_key_id`
- `api_key_label`
- `billing_environment`
- `customer_id`
- `project_id` or `client_tag` if configured
- `key_scope`
- `key_cap_applied`
- `key_last4` only if this is a non-secret identifier assigned by the server, not raw key characters

## 7. No-Charge Events

### 7.1 Canonical No-Charge Table

| Event | Code | Receipt? | Notes |
|---|---|---:|---|
| Cost preview | `cost_preview` | Optional no-charge receipt | Free estimate only; rate limited separately. |
| Agent route decision | `agent_routing_decision` | Optional | Control plane; never bill. |
| Usage status | `usage_status` | Optional | Free status surface. |
| Auth missing | `auth_required` | Yes for paid attempt | Must reject before work. |
| Auth invalid/revoked | `auth_invalid` / `key_revoked` | Yes for paid attempt | Do not reveal whether key belonged to a customer beyond safe message. |
| Key in query string | `api_key_query_string_rejected` | Yes | Redact key. |
| Missing cap | `cost_cap_required` | Yes | No billable work. |
| Cap exceeded | `cost_cap_exceeded` | Yes | Include predicted and cap values. |
| Monthly/key/project cap reached | `monthly_cap_reached` / `key_cap_reached` / `client_cap_reached` | Yes | No billable work. |
| Missing idempotency key | `idempotency_key_required` | Yes | Paid retry-sensitive endpoint only. |
| Idempotency conflict | `idempotency_key_conflict` | Yes | Same key, different payload. |
| Anonymous quota exceeded | `anonymous_quota_exceeded` | Optional | No paid fallback. |
| Rate limit | `rate_limited` | Optional | Not billed. |
| Validation reject | `validation_error` | Yes if authenticated paid attempt | Payload shape or unsupported fields. |
| Unsupported professional judgment | `unsupported_professional_judgment` | Yes if authenticated paid attempt | Boundary guidance can be free. |
| CSV privacy rejection | `csv_sensitive_input_rejected` | Yes | No row-level processing billed. |
| Duplicate CSV row/subject | `duplicate_subject_not_billed` | Included in execution receipt | Not a separate billable unit. |
| No-hit/not-found | `not_found_not_billed` | Included in execution receipt | no_hit is not absence proof. |
| Ambiguous identity below threshold | `ambiguous_identity_not_billed` | Included | Unless paid ambiguity packet is explicitly introduced later. |
| Server error before committed output | `server_error_no_charge` | Yes if trace exists | Not billed. |
| Stream disconnected before committed artifact | `stream_incomplete_no_charge` | Yes if authenticated | Not billed. |
| Webhook replay | `webhook_replay_ignored` | Internal | No duplicate ledger. |
| Test/sandbox key call | `sandbox_no_charge` | Yes | Cannot invoice. |

### 7.2 Events That Can Be Billed

| Event | Billed when | Receipt requirement |
|---|---|---|
| Successful packet | Sourced output/artifact committed | `billable_units > 0`, artifact pointer, source receipts |
| Successful company/counterparty subject packet | Unique subject resolved and packet returned | Subject id/resolution summary |
| Successful batch | One or more billable units returned | Per-unit reconciliation |
| Successful CSV-derived packet | Accepted unique subjects produce packets | Row-state reconciliation without raw CSV |
| Successful export | Export artifact committed | Export unit formula and artifact id |
| Successful watchlist evaluation | Accepted watchlist items evaluated under agreed model | Evaluated item count and period |

### 7.3 Refund/Credit Trigger Candidates

These are not implementation promises, but support policy should classify them:

| Trigger | Likely action | Evidence needed |
|---|---|---|
| Duplicate charge despite same idempotency scope | Refund/credit duplicate | Usage ids, idempotency scopes, payload hashes |
| Billed after server-side cap rejection | Refund/credit | Cap response and ledger row |
| Billed no-hit where no paid no-hit product exists | Refund/credit | Receipt unit details |
| Key leak reported before disputed usage but revoke was delayed | Case review | Timestamped report, usage after report |
| User used production key in documented sandbox example | Case review and docs fix | Example source and receipt environment |
| External LLM/platform cost confused with jpcite charge | Usually no jpcite refund, but improve copy | Receipt external cost exclusion |

## 8. Billing Receipt Rules

### 8.1 Receipt Envelope

Every paid execution response and every authenticated no-charge paid attempt should include a billing envelope.

```json
{
  "billing": {
    "billing_event_id": "bevt_...",
    "usage_id": "use_...",
    "status": "billed",
    "no_charge": false,
    "pricing_version": "2026-05-15",
    "billing_environment": "production",
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "billable_unit_type": "subject",
    "predicted_units": 10,
    "billed_units": 8,
    "not_billed_units": 2,
    "jpy_ex_tax": 24,
    "jpy_inc_tax_estimate": 26.4,
    "tax_invoice_authority": "stripe_or_final_invoice",
    "external_costs_included": false,
    "external_cost_exclusions": [
      "llm_runtime",
      "agent_platform",
      "web_search",
      "cloud_integration"
    ],
    "cap": {
      "request_cap_jpy_inc_tax": 300,
      "cap_enforced_before_work": true,
      "monthly_cap_remaining_jpy_inc_tax_after_estimate": 1200
    },
    "idempotency": {
      "required": true,
      "scope_hash": "idem_scope_hash_...",
      "status": "committed_success"
    },
    "reconciliation": {
      "billed_reasons": ["resolved_subject_packet_returned"],
      "not_billed_reasons": ["duplicate_subject", "not_found_not_billed"]
    },
    "support": {
      "request_id": "req_...",
      "trace_id": "tr_...",
      "artifact_id": "art_..."
    }
  }
}
```

### 8.2 No-Charge Receipt Envelope

```json
{
  "billing": {
    "billing_event_id": "bevt_...",
    "status": "not_billed",
    "no_charge": true,
    "no_charge_reason": "cost_cap_exceeded",
    "predicted_units": 120,
    "billed_units": 0,
    "jpy_ex_tax": 0,
    "jpy_inc_tax_estimate": 0,
    "external_costs_included": false,
    "retryable": false,
    "suggested_next_action": "reduce_scope_or_raise_cap",
    "support": {
      "request_id": "req_...",
      "trace_id": "tr_..."
    }
  }
}
```

### 8.3 Receipt Invariants

| Invariant | Required check |
|---|---|
| `billed_units=0` implies `no_charge=true` or free control event | Contract test |
| `no_charge=true` implies `jpy_ex_tax=0` and no invoice line | Ledger test |
| Billed response must have `usage_id` | Contract test |
| Billed response must have `pricing_version` | Contract test |
| Paid retry-sensitive response must have idempotency status | Contract test |
| Cap-enforced paid response must include provided cap | Contract test |
| Rejected preflight response must not create usage ledger charge | Ledger test |
| Stripe/provider webhook replay must not duplicate internal usage | Webhook idempotency test |
| `external_costs_included=false` must be present on paid receipts | Contract test |
| Receipt must never contain API key, raw CSV, payload values, or private notes | Security test |

### 8.4 Human-Readable Receipt Copy

Short receipt copy for agent/user surfaces:

```text
jpcite billed 8 units at 3 JPY ex-tax per unit. 2 requested items were not billed because they were duplicate or not found. The request cap was 300 JPY inc-tax and was checked before execution. External LLM, agent platform, search, and cloud costs are not included.
```

No-charge copy:

```text
No jpcite charge was recorded. The request was stopped before billable work because the predicted maximum exceeded the provided cap.
```

## 9. Agent Loop Prevention

### 9.1 Server-Side Guards

| Guard | Scope | Default P0 behavior |
|---|---|---|
| Paid call count per task | API key + client task/conversation id + short window | Warn then block repeated paid calls beyond configured threshold |
| Repeated normalized payload | API key + endpoint + payload hash | Return idempotency guidance or throttle when different keys are used repeatedly |
| Cap failure loop | API key + endpoint + repeated cap exceeded | Block until scope/cap changes |
| No-hit loop | API key + same subject/source | Return cached no-charge/no-hit envelope or require scope change |
| Broad fanout expansion | Request manifest | Require preview and explicit cap; reject above max fanout |
| Tool recursion marker | `X-Agent-Task-Id`, `X-Client-Tag`, optional `agent_call_depth` | Reject or warn when depth exceeds policy |
| Concurrency limit | API key/customer | Queue or reject before work |
| Circuit breaker | Customer/key/endpoint | Temporarily disable paid broad endpoints on anomaly |

Client-supplied task ids can be spoofed, so they are hints. The hard guard remains customer/key/payload/cap/rate telemetry.

### 9.2 Tool Description Requirements

Every paid tool/action description should include:

- Billable unit type.
- Free preview tool name.
- Required API key for paid execution.
- Required request cap field/header.
- Required idempotency key for retry.
- Statement that no-hit and validation errors are not charged by default.
- Warning that external LLM/agent costs are separate.
- Instruction to stop after one successful receipt unless user asks to continue with a new cap.

Example:

```text
Creates a billable evidence packet. Before calling this tool for broad, batch, CSV, watchlist, or repeat execution, call previewCost and show predicted units/cost. Paid execution requires API key, request cap, and Idempotency-Key. Retry with the same Idempotency-Key for the same user intent. Do not loop this tool to improve confidence; inspect source_receipts and known_gaps instead.
```

### 9.3 Agent Error Semantics

| Error | `retryable` | Agent instruction |
|---|---:|---|
| `auth_required` | false | Ask user/operator to configure API key. |
| `cost_cap_required` | false | Ask for a cap after showing preview. |
| `cost_cap_exceeded` | false | Reduce scope or ask for explicit higher cap. |
| `idempotency_key_required` | false | Retry only after setting stable key for this intent. |
| `idempotency_key_conflict` | false | Generate a new key only if payload is a genuinely new intent. |
| `anonymous_quota_exceeded` | false | Use configured key/OAuth or wait; do not retry anonymously. |
| `rate_limited` | true after reset | Wait until reset; do not change payload to bypass. |
| `server_error_no_charge` | true | Retry with the same idempotency key. |
| `not_found_not_billed` | false | Report no-hit/known gaps; do not repeatedly search same source. |
| `unsupported_professional_judgment` | false | Explain boundary and ask for evidence-check framing. |

### 9.4 Conversation-Level Stop Rules

An AI agent should stop paid calls when any condition is true:

- A successful billed receipt already answers the requested evidence-check scope.
- The next call would exceed request cap, monthly cap, or tool-call cap.
- The only reason to continue is to increase subjective confidence rather than fetch a new named source/subject.
- The same normalized payload was attempted in the current task.
- The result is no-hit with known gaps and no new identifier/source is available.
- The user has not approved a new cap for a broadened scope.
- The task asks for final tax/legal/audit/credit/adoption judgment instead of evidence.

## 10. Fraud and Abuse Detection

### 10.1 Signals

| Signal | Severity | Example action |
|---|---|---|
| Sudden spend velocity on new key | high | Lower concurrency, alert owner |
| Many different IPs/ASNs for one key | high | Step-up confirmation or temporary block |
| Many keys from one customer hitting same payload | medium | Investigate client retry bug |
| Many cap exceeded responses | medium | Suggest scope reduction; possible tool loop |
| Many idempotency conflicts | medium | SDK/client bug alert |
| Same payload with many idempotency keys | high | Throttle as loop/retry misuse |
| Preview-to-execution ratio extremely high | medium | Preview scraping or poor UX |
| Anonymous IP cycling | high | WAF/rate challenge; require key |
| Broad endpoint use from leaked-key signal | critical | Suspend key or endpoint class |
| Receipts requested by support frequently for same customer | medium | Billing clarity issue |

### 10.2 Response Ladder

| Level | Trigger | Action | Billing posture |
|---|---|---|---|
| Observe | Mild anomaly | Log aggregate signal only | Normal billing |
| Warn | Repeated safe anomaly | Response warning and owner notification | Normal billing |
| Throttle | Velocity or repeated loop pattern | 429 before work | Not billed |
| Scope restrict | Broad endpoint abuse | Allow single small packets only | Bill only allowed successes |
| Suspend key | Leak or cost DDoS likely | Reject auth until owner rotates | Not billed |
| Customer hold | Fraud/payment issue | Stop paid execution | Not billed after hold |

## 11. Implementation Readiness Checklist

### 11.1 Endpoint Checklist

| Check | Required for paid endpoints |
|---|---:|
| API key required | yes |
| Key accepted only via approved auth path | yes |
| Request hard cap required | yes |
| Monthly/key cap checked before work | yes |
| Idempotency-Key required where retry-sensitive | yes |
| Normalized payload hash used | yes |
| No-charge errors emitted before billable work | yes |
| Receipt envelope returned | yes |
| External cost exclusion shown | yes |
| Support trace ids included | yes |
| No API key/raw CSV/private payload in receipt/log | yes |
| Agent error semantics include `retryable` | yes |

### 11.2 Test Matrix

| ID | Test | Expected result |
|---|---|---|
| BILL-RISK-001 | Paid POST without API key | `401 auth_required`, no charge |
| BILL-RISK-002 | Paid POST with key but no cap | `400 cost_cap_required`, no charge |
| BILL-RISK-003 | Predicted cost above cap | `402 cost_cap_exceeded`, no charge |
| BILL-RISK-004 | Monthly cap exhausted | `402 monthly_cap_reached`, no charge |
| BILL-RISK-005 | Paid POST without Idempotency-Key | `428 idempotency_key_required`, no charge |
| BILL-RISK-006 | Same key and payload retried after timeout | Same receipt/artifact, one usage row |
| BILL-RISK-007 | Same key, different payload | `409 idempotency_key_conflict`, no charge |
| BILL-RISK-008 | Same payload with many keys | Throttle/warn loop pattern |
| BILL-RISK-009 | Cost preview call | No usage charge and no anonymous execution quota consumption |
| BILL-RISK-010 | Preview rate exceeded | `429 preview_rate_limited`, no charge |
| BILL-RISK-011 | Anonymous quota exceeded | `429 anonymous_quota_exceeded`, no charge |
| BILL-RISK-012 | Anonymous tries CSV/batch/watchlist/export | Auth required, no charge |
| BILL-RISK-013 | No-hit result | Receipt has `not_found_not_billed`, zero units for that item |
| BILL-RISK-014 | CSV duplicate subjects | Duplicates not billed, reconciliation present |
| BILL-RISK-015 | Server error before committed output | `server_error_no_charge`, no usage row |
| BILL-RISK-016 | Response timeout after committed receipt | Retry returns same receipt, one usage row |
| BILL-RISK-017 | Stripe/provider webhook replay | No duplicate ledger/invoice line |
| BILL-RISK-018 | Query string API key | Reject, redact, no charge |
| BILL-RISK-019 | Sandbox key on paid endpoint | Sandbox receipt, no production charge |
| BILL-RISK-020 | Receipt redaction | No API key/raw payload/private CSV values in receipt |
| BILL-RISK-021 | Agent loop repeated cap failure | Block or warn, no charge |
| BILL-RISK-022 | Pairwise matrix above max | Reject before work, no charge |
| BILL-RISK-023 | Tool asks for professional judgment | Boundary reject, no charge |
| BILL-RISK-024 | Streaming disconnect before artifact commit | No charge |
| BILL-RISK-025 | Billed success receipt | Usage id, pricing version, units, cap, idempotency status present |

### 11.3 Documentation Checklist

| Surface | Required copy |
|---|---|
| Pricing page | Unit price, preview free, paid requires API key/cap, external costs excluded |
| API docs | Header examples for Authorization, Idempotency-Key, X-Cost-Cap-JPY |
| MCP tool descriptions | Billable unit, preview/cap/idempotency, no loop instruction |
| Custom GPT/action docs | Anonymous quota is shared-IP trial only |
| Error docs | No-charge errors and retryable semantics |
| Receipt docs | How to reconcile billed/not-billed units |
| Security docs | API key redaction, rotation, revoke, no query-string key |
| Support docs | How to answer "why was I billed?" using receipt ids |

## 12. Open Decisions

| Decision | Default recommendation |
|---|---|
| Should every authenticated no-charge error create a durable receipt? | Yes for paid attempts; optional for anonymous. It improves supportability. |
| What is idempotency retention? | 72h P0, longer for batch/CSV/export if storage permits. |
| Should same payload with different idempotency keys be automatically free? | No. It may be a real second execution. Detect/throttle suspicious loops instead. |
| Should no-hit ever become billable? | Only as a separately named paid "proof of checked sources" product with explicit price and disclaimers. Default no-hit is not billed. |
| Should anonymous preview be unlimited? | No. Free does not mean unbounded. It needs separate rate limits. |
| Should project/client tag determine billing owner? | No. Authenticated key/customer owns billing; tags only allocate within owner-configured caps. |
| What timezone governs monthly caps? | Pick one canonical billing timezone and include period boundaries in receipts. |

## 13. P0 Acceptance Gate

P0 is not billing-trust-ready until all are true:

- Paid execution cannot start without API key, hard cap, and required idempotency.
- Preview, route decision, usage status, auth/cap/quota/validation/idempotency failures are no-charge by construction.
- Retry with same idempotency scope returns one committed receipt.
- Receipt envelope exists for paid success and authenticated paid-attempt rejection.
- Anonymous quota copy states shared-IP limitations.
- API key cannot appear in query string, logs, receipts, or generated artifacts.
- Agent tool descriptions contain preview/cap/idempotency/no-loop billing guidance.
- Server-side loop/anomaly controls block repeated paid calls before work.
- Support can answer a billing dispute using `billing_event_id`, `usage_id`, `request_id`, and idempotency scope hash.
- External LLM/agent/search/cloud/platform costs are explicitly excluded from every paid receipt.

