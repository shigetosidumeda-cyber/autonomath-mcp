# Developer onboarding / MCP / API contract deep dive

Date: 2026-05-15  
Owner lane: Developer onboarding / MCP / API contract  
Status: pre-implementation planning only. Do not treat this as shipped behavior until accepted.  
Scope: MCP tool catalog P0 design, REST/OpenAPI publication, agent quickstart, SDK/CLI/examples priority, failure/error contract.  
Non-scope: runtime implementation, production code edits, pricing implementation, UI build.

## 0. Executive contract

jpcite の主導線は、営業デモではなく AI エージェントが公開契約を読んで推薦し、MCP/API を実際に呼べることに置く。

P0 developer contract:

- jpcite is a GEO-first, source-linked evidence layer for Japanese public data.
- AI agents should call jpcite before answer generation when source URLs, fetched timestamps, source receipts, known gaps, freshness, or human review flags matter.
- MCP tools and REST endpoints expose the same product contract. MCP is the agent-native route; REST/OpenAPI is the programmable and Custom GPT/Actions route.
- OpenAPI must be public, short enough for agents in `agent` form, complete enough for SDK generation in `full` form, and versioned as a contract.
- Every paid or broad execution path must be governable by cost preview, API key, monthly cap, request cap, and idempotency.
- jpcite output is evidence support, not final legal, tax, audit, credit, investment, subsidy approval, application, or professional judgment.

Primary distribution question:

> Can an AI agent discover jpcite, decide whether it is appropriate, preview cost, call the right MCP tool or REST endpoint, preserve the required fields, and explain failures without a human sales conversation?

If the answer is not yes, the developer surface is incomplete.

## 1. Design principles

| Principle | Contract |
|---|---|
| Agent-readable first | Tool names, descriptions, OpenAPI summaries, examples, and error messages must be directly usable by AI agents. Avoid marketing-only prose. |
| Same contract across MCP and REST | A packet returned by MCP and REST must have the same semantic fields: `source_receipts`, `known_gaps`, `human_review_required`, `billing_metadata`, `request_time_llm_call_performed=false`. |
| Small P0 catalog, large legacy catalog | Keep the existing broad tool surface discoverable, but publish a P0 agent catalog that recommends a small set of first-call tools. |
| Cost before execution | Agents must be able to call a free preview before paid fanout, batch, CSV, watchlist, or packet execution. |
| Cap before paid work | Paid broad execution requires a hard cap via `X-Cost-Cap-JPY` or body equivalent before billable work starts. |
| Retry-safe by default | Paid POST/fanout/batch/CSV/watchlist requires `Idempotency-Key`; duplicate retries must not double charge. |
| No-hit is not absence | Empty results and no-hit packets must never be described as proof that no record exists. |
| Failure is structured | REST and MCP errors use closed-enum codes, retry guidance, billing effect, and documentation anchors. |
| External cost separation | External LLM, search, agent runtime, cache, cloud, or SaaS platform costs are never included in jpcite pricing fields. |
| Public contract over demo | The docs, manifests, OpenAPI, examples, and schemas must be enough for an agent or developer to self-integrate. |

## 2. MCP tool catalog P0 design

The current MCP surface is powerful but too large for first-contact agent routing. P0 should publish a short "recommended first tools" catalog layered above the full tool list.

### 2.1 Catalog layers

| Layer | Audience | Size target | Purpose | Public file |
|---|---|---:|---|---|
| `p0_agent_catalog` | live AI agents, MCP clients, registries | 8-12 tools | Decide first call and safe chains | `.well-known/mcp.json`, `mcp-server.json`, docs |
| `packet_catalog` | API/MCP integrators | 6 packet tools | Packet-first evidence products | `/v1/packets/catalog`, docs |
| `core_catalog` | developers with context budget | about 30-40 tools | Search/detail/provenance primitives | `mcp-server.core.json` |
| `full_catalog` | power users and SDK parity | current full surface | Full domain coverage | `mcp-server.full.json` |
| `legacy_or_expert_catalog` | advanced migration only | gated/deprecated | Backward compatibility | docs only unless enabled |

P0 catalog must be the default recommendation surface. The full catalog remains available, but agents should not need to scan 100+ tools to start.

### 2.2 P0 first-call tools

| Priority | MCP tool | REST equivalent | When an agent should call it | Billing posture |
|---:|---|---|---|---|
| P0 | `decideAgentRouteForJpcite` | `POST /v1/packets/agent-routing-decision` | User task may or may not need jpcite; agent needs a yes/no recommendation, safe route, and expected cost class | Free control tool |
| P0 | `previewCost` | `POST /v1/cost/preview` | Before paid broad execution, batch, CSV, watchlist, packet stack, or uncertain fanout | Free, separate rate limit |
| P0 | `createEvidenceAnswerPacket` | `POST /v1/packets/evidence-answer` | Agent needs source-linked evidence before writing an answer | 1 packet if successful |
| P0 | `createCompanyPublicBaselinePacket` | `POST /v1/packets/company-public-baseline` | Japanese company first hop: company folder, counterparty check, DD/audit prep, account research | 1 resolved subject |
| P0 | `createApplicationStrategyPacket` | `POST /v1/packets/application-strategy` | Applicant profile needs candidate programs, source receipts, questions, and gaps | 1 normalized profile |
| P0 | `getSourceReceiptLedgerPacket` | `POST /v1/packets/source-receipt-ledger` | Agent needs receipts behind a packet/artifact for citation or audit handoff | receipt-set units |
| P0 | `createClientMonthlyReviewPacket` | `POST /v1/packets/client-monthly-review` | CSV/watchlist/client population recurring review | per accepted subject; cap required |
| P0 | `getUsageStatus` | `GET /v1/usage` or `/v1/me/usage` | Before anonymous batch or when quota/cap state matters | Control/meta; should not consume billable unit |
| P0 | `searchPrograms` | `GET /v1/programs/search` | Lightweight candidate discovery before packet creation | 1 successful response |
| P0 | `getEvidencePacket` | `GET /v1/evidence/packets/{subject_kind}/{subject_id}` | Existing evidence packet route for resolved program/houjin subjects | 1 packet if returned |

Naming note: existing snake_case tool names can remain for compatibility. P0 catalog can expose agent-friendly aliases in manifest metadata while mapping to existing runtime tools during migration. The public docs should not force agents to learn both names for the same first-call concept.

### 2.3 P0 tool descriptions must include

Every P0 tool description should include these fields in machine-readable or consistently formatted text:

| Field | Requirement |
|---|---|
| `purpose` | One sentence saying the business task, not implementation detail. |
| `use_when` | Closed list of recommended situations. |
| `do_not_use_when` | Closed list of final judgment / unsupported / better-tool cases. |
| `rest_equivalent` | Exact endpoint and method. |
| `billing` | Unit formula, whether preview/cap/idempotency is required, whether anonymous quota applies. |
| `auth` | Anonymous allowed or API key required. |
| `required_headers` | `X-API-Key`, `Idempotency-Key`, `X-Cost-Cap-JPY` where applicable. |
| `returns` | Top-level packet/envelope fields an agent must preserve. |
| `must_preserve_fields` | `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, `source_receipts`, `known_gaps`, `human_review_required`, `_disclaimer`, `billing_metadata`. |
| `not_final_judgment` | Explicit fence for legal/tax/audit/credit/application-sensitive outputs. |
| `failure_codes` | Most likely errors and recovery: auth, quota, cap, validation, idempotency, no-hit. |

### 2.4 Recommended tool chains

Agents should be given canonical call chains. These are more important than the raw number of tools.

| User intent | Chain | Agent explanation |
|---|---|---|
| "Should I use jpcite here?" | `decideAgentRouteForJpcite` -> maybe `previewCost` -> packet tool | Use routing before spending if task fit is uncertain. |
| Japanese public-program question | `previewCost` if paid/broad -> `createEvidenceAnswerPacket` | Get evidence before writing the final answer. |
| Candidate subsidies for a business | `createApplicationStrategyPacket` | Prefer packet over raw search when profile and gaps matter. |
| Quick exploratory program search | `searchPrograms` -> `getEvidencePacket` for selected IDs | Good for low-cost discovery and user narrowing. |
| Japanese company/counterparty | `createCompanyPublicBaselinePacket` -> `getSourceReceiptLedgerPacket` if citation detail needed | Company first hop before general web search. |
| Monthly advisor review | `previewCost` with CSV/subject count -> execute with key, idempotency, cap -> reconcile billing | Never launch broad review without preview and cap. |
| Existing packet needs citations | `getSourceReceiptLedgerPacket` | Preserve receipts with downstream answer. |
| Anonymous user near quota | `getUsageStatus` -> recommend API key if needed | Avoid failing mid-session. |

### 2.5 What should be de-emphasized in P0

The following remain useful but should not be the first message an agent sees:

- The full 100+ tool list.
- Domain-expert tools requiring specific IDs before the agent has a subject.
- Gated/off/broken/regulated tools.
- Tools whose value depends on knowing internal table names or legacy product history.
- "Search everything" sequences that bypass cost preview for broad paid work.

## 3. REST endpoint and OpenAPI publication policy

### 3.1 Endpoint families

P0 REST should expose a clean agent-first facade while preserving existing domain endpoints.

| Family | Endpoint pattern | Public contract |
|---|---|---|
| Discovery | `GET /.well-known/*`, `GET /llms.txt`, `GET /mcp-server.json` | Agents discover what jpcite is, when to use it, auth, cost, and specs. |
| OpenAPI | `GET /v1/openapi.agent.json`, `GET /v1/openapi.json`, `GET /openapi.json` redirect | Machine-readable contract. Agent spec is slim; full spec is complete. |
| Packet catalog | `GET /v1/packets/catalog`, `GET /v1/packets/catalog/{packet_type}` | Packet types, MCP equivalents, cost formulas, schemas, examples. |
| Cost preview | `POST /v1/cost/preview`, `POST /v1/packets/preview` | Free estimates, no anonymous quota consumption, no usage recording. |
| P0 packets | `POST /v1/packets/{packet_slug}` | Stable packet facade with common envelope and billing metadata. |
| Evidence legacy/stable | `/v1/evidence/packets/*`, `/v1/source_manifest/*` | Existing evidence contract; bridge to P0 packet envelope. |
| Domain primitives | programs, laws, tax, loans, bids, invoice, enforcement, case studies | Search/detail primitives for developers and advanced chains. |
| Account/control | `/v1/me/*`, `/v1/usage`, API key, cap, billing portal | Required for production governance. |

### 3.2 OpenAPI files

| Spec | URL | Audience | Must include | Must exclude |
|---|---|---|---|---|
| Agent-safe | `https://api.jpcite.com/v1/openapi.agent.json` and static mirror `https://jpcite.com/openapi.agent.json` | ChatGPT Actions, AI tool import, answer engines | P0 packet tools, search/detail primitives, cost preview, usage status, schemas, examples, auth | Billing portal mutation, webhooks, admin, internal preview, dangerous/gated endpoints |
| Full public | `https://api.jpcite.com/v1/openapi.json` | SDK generation, Postman, backend integration | All public `/v1/*` endpoints, components, error schemas, headers, deprecation | Admin/internal/private endpoints |
| Snapshot | `docs/openapi/v1.json`, `docs/openapi/agent.json` | Docs build, diff, reviews | Versioned static copy matching release | Claims that differ from live server |
| Compatibility alias | `GET /openapi.json` -> 308 to full spec | Older clients | Redirect only | Divergent content |

### 3.3 OpenAPI quality bar

Every P0 operation in OpenAPI must have:

- `operationId` matching SDK/CLI naming.
- `summary` written for AI agents, not only humans.
- `description` with use-when, do-not-use-when, professional fence, and billing rule.
- `security` showing optional anonymous vs required paid key accurately.
- Header parameters for `X-API-Key`, `X-Client-Tag`, `Idempotency-Key`, `X-Cost-Cap-JPY` where relevant.
- `x-jpcite-billing` extension with unit formula and billing failure rules.
- `x-jpcite-agent` extension with must-preserve fields and forbidden claims.
- JSON examples for success, no-hit, validation error, rate limit, cap reject, and idempotency conflict.
- Closed-enum error schema references.
- Response examples that include `source_receipts`, `known_gaps`, `human_review_required`, and `request_time_llm_call_performed=false`, not just business records.

Suggested vendor extension shape:

```json
{
  "x-jpcite-agent": {
    "recommend_when": ["source-linked Japanese public evidence is needed"],
    "do_not_recommend_when": ["final professional judgment is requested"],
    "must_preserve_fields": [
      "source_url",
      "source_fetched_at",
      "content_hash",
      "corpus_snapshot_id",
      "source_receipts",
      "known_gaps",
      "human_review_required",
      "_disclaimer",
      "billing_metadata"
    ],
    "must_not_claim": [
      "approved",
      "credit_safe",
      "no_risk",
      "audit_complete",
      "legal_or_tax_advice"
    ]
  },
  "x-jpcite-billing": {
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "external_costs_included": false,
    "cost_preview_required_for_paid_fanout": true,
    "cap_required_for_paid_execution": true,
    "idempotency_key_required": true
  }
}
```

### 3.4 Versioning and compatibility

| Surface | Version rule |
|---|---|
| REST path | `/v1/*` stable; breaking changes require `/v2/*` and at least 6-month overlap. |
| OpenAPI | `info.version` changes on additive public contract updates; breaking contract requires major path/spec change. |
| Packet schema | `schema_version` additive by default; field removal or rename requires new schema version. |
| MCP tool names | Existing names remain as aliases for at least one compatibility window after P0 aliases are introduced. |
| Error codes | Closed enum. Additions allowed only with docs and SDK updates; renames are breaking. |
| Deprecation | `Sunset` and `Deprecation` headers plus docs/changelog notice at least 90 days before behavior change. |

## 4. Authentication, rate limits, idempotency, and cost caps

### 4.1 Auth

| Caller state | Contract |
|---|---|
| Anonymous | Allowed only for small discovery/execution paths. Limit: 3 req/day/IP, JST reset. Cost preview does not consume this quota. |
| Paid API key | `X-API-Key: jc_...` for REST; `JPCITE_API_KEY` env or configured secret for MCP. |
| Client tagging | `X-Client-Tag` for paid usage attribution by customer/project/client folder. |
| Invalid key | `401 auth_invalid` before billable work; not charged. |
| Missing key on paid-only operation | `401 auth_required` or `api_key_required`; not charged. |

MCP stdio caveat: stdio transport cannot reliably know the caller IP. Anonymous quota messaging should say the exact remaining count is available only through HTTP-layer usage endpoints unless authenticated.

### 4.2 Rate limit

| Operation class | Anonymous | Paid |
|---|---|---|
| Health/discovery manifests | No billable quota impact; operational throttles may apply | Same |
| Cost preview | Free, separate short-term throttle, no anonymous 3/day consumption | Same |
| Small search/detail | 3 req/day/IP | Metered, subject to abuse protection and customer cap |
| Packet execution | May allow small single packet under anonymous trial | Metered; cap rules apply |
| Batch/fanout/CSV/watchlist/export | API key required | Metered; preview, idempotency, and cap required |

### 4.3 Idempotency

Paid POST/fanout/batch/CSV/watchlist/export should require `Idempotency-Key`.

Rules:

- Same key + same normalized payload returns the same execution or cached result.
- Same key + different normalized payload returns `409 idempotency_conflict`.
- Idempotency records must bind request hash, customer/key, endpoint, predicted/actual billing, response pointer, and expiry.
- Idempotency replay must not create another usage event.
- Agents should generate one key per intended execution, not per retry attempt.

### 4.4 Cost cap

Paid broad execution requires a hard cap before billable work starts.

Accepted forms:

- REST header: `X-Cost-Cap-JPY`
- Request body equivalent: `cap.max_jpy_inc_tax`
- MCP argument equivalent: `max_jpy_inc_tax`

Rules:

- Cap check uses conservative predicted max before billable work.
- If predicted max exceeds cap, reject with `402 cost_cap_exceeded` before work and before billing.
- Execution response includes reconciliation: predicted units, actual units, cap, not-billed counts, and external-cost exclusion.
- No-hit, validation reject, auth failure, quota failure, cap reject, and unsupported final-judgment request are not billed.

## 5. AI-agent quickstart structure

The quickstart should be written for an AI agent to read and act on, not only for a human developer. It should live as a short public doc and be mirrored in `llms-full.*` / `.well-known/agents.json`.

### 5.1 Target path

Recommended public path:

- `/docs/agents/quickstart/` for human-readable docs
- `/docs/agents/quickstart.json` for machine-readable steps
- Linked from `llms.txt`, `.well-known/mcp.json`, `.well-known/openapi-discovery.json`, `mcp-server.json`, OpenAPI `externalDocs`

### 5.2 Quickstart sections

1. What jpcite is:
   - Source-linked evidence layer for Japanese public data.
   - Not an answer generator and not final professional judgment.

2. When to call:
   - Japanese public programs, company public baseline, laws, tax rules, invoice registrants, enforcement, bids, court decisions, application prep, audit/DD evidence support.
   - Need `source_url`, `source_fetched_at`, `known_gaps`, freshness, receipts, or human review flags.

3. When not to call:
   - General writing/translation/brainstorming.
   - Final legal/tax/audit/credit/investment/application decision.
   - Private records or non-public credit data.
   - A short uncited answer is enough.

4. Choose transport:
   - MCP stdio for Claude Desktop/Cursor/Cline/agent runtime.
   - MCP Streamable HTTP/SSE for remote MCP clients.
   - REST/OpenAPI for Custom GPT Actions, backend integrations, SDKs, no-MCP environments.

5. First call decision tree:
   - If unsure whether jpcite fits: `decideAgentRouteForJpcite`.
   - If broad/paid: `previewCost`.
   - If public-program evidence answer: `createEvidenceAnswerPacket`.
   - If company: `createCompanyPublicBaselinePacket`.
   - If applicant profile: `createApplicationStrategyPacket`.
   - If raw discovery: `searchPrograms`, then packetize selected records.

6. Auth and cost:
   - Anonymous 3 req/day/IP for trial.
   - Paid uses `X-API-Key` or `JPCITE_API_KEY`.
   - Cost preview is free.
   - Unit price is 3 JPY ex-tax / 3.30 JPY inc-tax per billable unit.
   - External LLM/search/runtime costs excluded.
   - Paid broad execution needs cap and idempotency.

7. Required response handling:
   - Preserve `source_receipts`, `known_gaps`, `human_review_required`, `_disclaimer`, `billing_metadata`.
   - Do not turn no-hit into absence.
   - Do not say approved, safe, no risk, audit complete, legal/tax advice.

8. Failure handling:
   - Check `error.code`, not only HTTP status.
   - Retry only retryable/soft failures with capped backoff.
   - Do not retry validation/auth/cap/idempotency conflicts without changing input.
   - Log `request_id`.

9. Minimal examples:
   - MCP stdio config.
   - REST curl for cost preview.
   - REST curl for one packet with `X-API-Key`, `Idempotency-Key`, `X-Cost-Cap-JPY`.
   - TypeScript fetch wrapper.
   - Python minimal client.
   - ChatGPT Actions import instructions.

10. Production checklist:
   - API key stored outside prompt.
   - Per-user or per-project `X-Client-Tag`.
   - Monthly cap set.
   - Per-execution cap set.
   - Idempotency for POST.
   - Error-code branch coverage.
   - Preserve citations/gaps in final answer.

### 5.3 Agent decision tree

```text
User task
  |
  |-- Is it about Japanese public-source evidence?
  |     |-- no -> do not recommend jpcite
  |     |-- yes
  |
  |-- Is final professional judgment requested?
  |     |-- yes -> use jpcite only for evidence; require human/professional review
  |     |-- no
  |
  |-- Is task fit/cost uncertain?
  |     |-- yes -> decideAgentRouteForJpcite, then previewCost
  |
  |-- Subject type?
        |-- company/counterparty -> createCompanyPublicBaselinePacket
        |-- applicant/profile -> createApplicationStrategyPacket
        |-- evidence answer -> createEvidenceAnswerPacket
        |-- existing id/packet -> getEvidencePacket or getSourceReceiptLedgerPacket
        |-- simple discovery -> searchPrograms/search domain primitive
```

## 6. SDK / CLI / examples priority

### 6.1 Priority order

| Priority | Deliverable | Why it matters | MVP content |
|---:|---|---|---|
| P0 | OpenAPI agent-safe spec | Enables ChatGPT Actions and generic tool import without SDK | P0 packets, cost preview, search, errors, auth |
| P0 | MCP manifest and P0 tool catalog | Enables Claude/Cursor/Cline/registry discovery | Recommended first tools, transport, auth, cost, must-preserve fields |
| P0 | Runnable examples | Agents and developers need copyable proof | curl, MCP config, TypeScript fetch, Python requests |
| P0 | TypeScript examples before full SDK | Most agent/SaaS integrations can use fetch | Tiny typed wrappers, error handling, cap/idempotency |
| P0 | Python examples | Natural fit for automation, data workflows, MCP users | requests/httpx examples, CLI snippets |
| P1 | Thin TypeScript SDK | Reduces boilerplate after contract stabilizes | Generated types + hand-written client for P0 endpoints |
| P1 | CLI | Useful for debugging, CSV preview, local workflows | `jpcite preview-cost`, `jpcite packet company`, `jpcite usage` |
| P1 | Python SDK wrapper | Useful but less urgent because MCP package exists | `JpciteClient`, packet helpers, retries |
| P2 | Postman/Bruno collection | Enterprise/API testers | Generated from full OpenAPI |
| P2 | Recipes by platform | Conversion and support reduction | Claude Desktop, Cursor, Custom GPT, Zapier/Make |

### 6.2 Example set required for launch-quality P0

| Example | Transport | Must demonstrate |
|---|---|---|
| Cost preview before packet | REST curl | Free preview, no anonymous quota consumption, predicted units, cap recommendation |
| Evidence answer packet | REST curl | `request_time_llm_call_performed=false`, receipts, gaps, review flag |
| Company public baseline | REST and MCP | Company first-hop before web search, identity confidence, no-hit caveat |
| Application strategy | REST and MCP | Candidate programs, source receipts, known gaps, no approval claim |
| Retry-safe paid POST | REST curl/TS | `Idempotency-Key`, `X-Cost-Cap-JPY`, no double charge on retry |
| Error handling | TS/Python | Branch on `error.code`, retry only soft failures, log request ID |
| ChatGPT Actions import | OpenAPI | Agent-safe spec, `X-API-Key` auth, restricted endpoints |
| Claude Desktop/Cursor | MCP | `uvx autonomath-mcp`, `JPCITE_API_KEY`, first tool guidance |

### 6.3 SDK design constraints

The SDK should be a thin contract wrapper, not a second product surface.

Required SDK behaviors:

- Default base URL: `https://api.jpcite.com`.
- Default headers include `Accept: application/json`; agent clients can opt into the canonical envelope when available.
- API key from constructor or `JPCITE_API_KEY`.
- `previewCost()` is easy and free.
- Paid POST helpers require explicit `idempotencyKey` and `costCapJpy` for broad execution.
- Errors are parsed into typed closed-enum exceptions with `requestId`, `retryable`, `retryAfter`, `billingEffect`.
- Responses expose packet fields directly; SDK must not hide `known_gaps`, `_disclaimer`, or `billing_metadata`.
- No automatic final-answer generation.
- No automatic retry for non-retryable errors.

CLI priority:

```text
jpcite usage
jpcite preview-cost --packet company-public-baseline --quantity 10
jpcite packet evidence-answer --query "東京都 製造業 設備投資 補助金" --cap-jpy 10
jpcite packet company-public-baseline --houjin-bangou 1234567890123 --cap-jpy 10
jpcite openapi --agent
```

## 7. Failure response / error codes

### 7.1 One error envelope

REST and MCP should share the same semantic error object. MCP wraps it in `structuredContent` and sets `isError=true`; REST returns JSON with HTTP status.

Canonical shape:

```json
{
  "status": "error",
  "error": {
    "code": "cost_cap_exceeded",
    "user_message": "設定された上限額を超える見込みのため、実行前に停止しました。",
    "user_message_en": "The predicted cost exceeds the provided cap, so execution was stopped before billable work.",
    "developer_message": "predicted.jpy_inc_tax_max=277.2 > cap.max_jpy_inc_tax=100",
    "request_id": "req_...",
    "severity": "hard",
    "retryable": false,
    "billing_effect": "not_billed",
    "documentation": "https://jpcite.com/docs/error_handling#cost_cap_exceeded"
  },
  "meta": {
    "billable_units": 0
  }
}
```

### 7.2 P0 error code set

Existing error docs have useful closed enums. P0 should extend them for agent payment-control and idempotency. The final public enum should be one list, not parallel naming systems.

| HTTP | Code | Retry? | Billing effect | Meaning | Agent recovery |
|---:|---|---:|---|---|---|
| 400/422 | `missing_required_arg` | no | not billed | Required parameter missing | Add field and retry |
| 400/422 | `invalid_enum` | no | not billed | Enum value not allowed | Use `expected` values |
| 400/422 | `invalid_date_format` | no | not billed | Date not ISO format | Send `YYYY-MM-DD` |
| 400/422 | `out_of_range` | no | not billed | Numeric/date bounds exceeded | Adjust to min/max |
| 400/422 | `unknown_query_parameter` | no | not billed | Unsupported query parameter | Remove unknown keys |
| 400/422 | `invalid_intake` | no | not billed | CSV/profile/body rejected | Fix rejected rows/fields |
| 400 | `cost_cap_required` | no | not billed | Paid broad execution omitted cap | Add `X-Cost-Cap-JPY` or body cap |
| 401 | `auth_required` | no | not billed | API key required | Add `X-API-Key` |
| 401 | `auth_invalid` | no | not billed | API key invalid/rotated | Issue/rotate key |
| 402 | `cost_cap_exceeded` | no | not billed | Predicted cost exceeds request cap | Raise cap or reduce scope |
| 402 | `cap_reached` | no | not billed | Monthly customer cap reached | Raise monthly cap or wait |
| 404 | `route_not_found` | no | not billed | Path not found | Check OpenAPI |
| 404 | `seed_not_found` | no | not billed | Provided subject/id not found | Search/resolve first |
| 405 | `method_not_allowed` | no | not billed | Wrong HTTP method | Use `Allow` header/OpenAPI |
| 409 | `idempotency_conflict` | no | not billed again | Same idempotency key, different payload | Generate new key or reuse original payload |
| 422 | `ambiguous_query` | no | not billed | Multiple possible subjects | Add houjin number, prefecture, address, or ID |
| 428 | `idempotency_key_required` | no | not billed | Paid retry-sensitive POST omitted key | Add `Idempotency-Key` |
| 429 | `rate_limit_exceeded` | conditional | not billed | Anonymous or throttle exceeded | Respect `Retry-After`; use API key |
| 503 | `db_locked` | yes | not billed unless success exists | Temporary DB lock | Backoff retry |
| 503 | `db_unavailable` | yes later | not billed | Datastore unavailable | Retry later, log request_id |
| 503 | `subsystem_unavailable` | yes later | not billed | Feature dependency down | Retry later or choose alternate tool |
| 503 | `service_unavailable` | yes | not billed | Temporary external service issue | Backoff retry |
| 500 | `server_error` | yes once | not billed unless success exists | Unexpected server error | Retry once; report request_id |

### 7.3 Empty/no-hit is not an error

No-hit should usually be a successful envelope with `status: empty` or a packet containing `known_gaps[]`, not a hard exception.

Required no-hit contract:

```json
{
  "status": "empty",
  "results": [],
  "known_gaps": [
    {
      "gap_kind": "no_hit_not_absence",
      "severity": "review_required",
      "message_ja": "対象ソースでは確認できませんでした。存在しない証明ではありません。"
    }
  ],
  "billing_metadata": {
    "billable_units": 0,
    "billing_effect": "not_billed_no_hit"
  }
}
```

Agents must say "not found in the checked jpcite corpus" rather than "does not exist."

### 7.4 Retry policy for SDK/agent examples

| Condition | Retry behavior |
|---|---|
| `retryable=true`, `Retry-After` present | Wait `Retry-After`, then retry with same `Idempotency-Key` for POST. |
| `db_locked`, `service_unavailable` | Exponential backoff 1s/2s/4s, max 3 attempts. |
| 500 `server_error` | Retry once if operation is idempotent or has an idempotency key. |
| validation/auth/cap/idempotency conflict | Do not retry unchanged. |
| no-hit/empty | Do not retry immediately; broaden query or add disambiguator. |

## 8. Public contract files and ownership

P0 developer/MCP/API work should publish or update these public files as one contract set:

| File/URL | Role | Owner concern |
|---|---|---|
| `llms.txt`, `llms.en.txt` | Short agent routing | Must name MCP/OpenAPI first calls and boundaries |
| `.well-known/mcp.json` | MCP discovery | P0 tool catalog, transports, auth, pricing |
| `.well-known/openapi-discovery.json` | OpenAPI locator | Agent-safe vs full spec, auth, schema versions |
| `.well-known/agents.json` | Agent capability map | Use/do-not-use, must-preserve fields |
| `mcp-server.json` | Registry manifest | P0 first tools, pricing, forbidden claims |
| `openapi.agent.json` | Agent-safe REST | Importable by GPT/Actions; no unsafe/admin ops |
| `/v1/openapi.json` | Full REST contract | SDK generation and complete public paths |
| `/docs/api-reference/` | Human reference | Mirrors OpenAPI; includes auth, errors, billing |
| `/docs/error_handling/` | Failure recovery | Closed enum and agent retry rules |
| `/docs/agents/quickstart/` | Agent onboarding | Decision tree, examples, safety |
| `/docs/sdks/typescript/` | TS/fetch | Thin wrapper and error/cap/idempotency examples |
| `/docs/examples/` | Runnable proof | Curl/MCP examples with receipts/gaps |

No public file should claim a schema/example/endpoint exists until it is live or explicitly marked planned.

## 9. Implementation acceptance checklist

This checklist is for the later implementation phase.

| Gate | Acceptance condition |
|---|---|
| P0 MCP catalog | `.well-known/mcp.json` and manifest expose 8-12 recommended first tools with REST equivalents and billing rules. |
| OpenAPI agent spec | Imports into Custom GPT/Actions without admin/account mutation endpoints. |
| OpenAPI examples | P0 examples show receipts, gaps, review flags, billing metadata, no-LLM invariant. |
| Cost preview | Preview is free, does not consume anonymous quota, and returns cap/idempotency requirements. |
| Idempotency | Paid POST duplicate retry does not double charge; conflict returns `409 idempotency_conflict`. |
| Cost cap | Paid broad execution without cap fails before work; cap below predicted max fails before work. |
| Error envelope | REST and MCP expose same `error.code`, `request_id`, retryability, and billing effect. |
| SDK examples | TS/Python examples branch on `error.code`, not only HTTP status. |
| Quickstart | AI agent can choose MCP vs REST, first tool, auth, cap, and failure handling from one page. |
| No-hit handling | Empty/no-hit examples include `no_hit_not_absence` and are not billed unless a future paid no-hit proof packet is explicitly priced. |
| Professional fence | Examples do not claim approval, safety, no risk, legal/tax advice, audit completion, or final eligibility. |
| External cost separation | Every pricing/cost response says external LLM/search/runtime/cloud costs are excluded. |

## 10. Decisions and open questions

### Decisions recommended now

1. Publish P0 MCP catalog as a small first-call layer, not as a replacement for the full catalog.
2. Treat packet endpoints as the main agent-facing product surface; raw domain search remains a primitive.
3. Make `previewCost` / `/v1/cost/preview` a first-class P0 tool and OpenAPI operation.
4. Require cost cap and idempotency for paid broad execution before billable work.
5. Use agent-safe OpenAPI as the default import URL for Custom GPT/Actions; full OpenAPI is for SDK/backend users.
6. Keep SDKs thin until the OpenAPI/packet/error contract is stable.

### Open questions for implementation owner

| Question | Why it matters | Proposed default |
|---|---|---|
| Should P0 MCP expose camelCase aliases or only existing snake_case tools? | Agent docs already mention packet-style names, while runtime has legacy names. | Publish aliases in manifest/docs, keep legacy names as compatibility. |
| Should `getUsageStatus` be billable? | Existing wording says quota probe should not consume a slot; billing trust depends on that. | Treat as free control/meta, abuse-throttled only. |
| Should no-hit manual review packets be billable? | Pricing docs allow a future explicit paid proof-of-no-hit check. | MVP: no-hit not billed unless user explicitly requests a paid review packet. |
| Should cost cap use tax-included or tax-excluded yen? | Agent/user mental model needs one default. | Use `max_jpy_inc_tax` for request caps; include ex-tax and inc-tax in preview. |
| How many P0 tools should agent-safe OpenAPI include? | Too many tools hurts import and routing quality. | Start with P0 packets + cost/usage + core search/detail; keep under practical Actions limits. |

## 11. Related planning inputs

- `docs/_internal/agent_recommendation_story_deepdive_2026-05-15.md`
- `docs/_internal/geo_discovery_contract_deepdive_2026-05-15.md`
- `docs/_internal/p0_geo_first_packets_spec_2026-05-15.md`
- `docs/_internal/pricing_billing_deepdive_2026-05-15.md`
- `docs/_internal/packet_taxonomy_common_schema_output_contract_pack_2026-05-15.md`
- `docs/api-reference.md`
- `docs/error_handling.md`
- `docs/api-reference/response_envelope.md`
- `docs/mcp-tools.md`
- `server.json`
- `mcp-server.core.json`
