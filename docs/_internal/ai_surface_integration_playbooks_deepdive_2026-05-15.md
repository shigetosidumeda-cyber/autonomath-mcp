# AI surface integration playbooks deep dive

Date: 2026-05-15  
Owner lane: AI surface integration playbooks  
Status: pre-implementation planning only. Do not treat this as shipped behavior until accepted.  
Constraint: documentation-only planning. No runtime implementation, generated site, OpenAPI, MCP manifest, or application code is changed by this file.

## 0. Executive contract

GEO-first の jpcite は、単一の「API ドキュメント」ではなく、AI surface ごとに違う発見・設定・呼び出し経路を持つ。

Core routing contract:

- ChatGPT / Custom GPT は OpenAPI Actions と public discovery copy を読む。
- Claude / Cursor / Codex / generic MCP client は MCP manifest と short tool catalog を読む。
- Gemini / Perplexity / 自前 agent は OpenAPI / REST / function calling / search allowlist を読む。
- どの surface でも jpcite は「日本の公的データについて回答する前に呼ぶ source-linked evidence layer」として説明する。
- どの surface でも `source_receipts`, `known_gaps`, `human_review_required`, `request_time_llm_call_performed=false`, `billing_metadata` を downstream answer に残す。
- broad/batch/CSV/paid fanout は `previewCost` / `POST /v1/cost/preview` を先に呼び、cap と idempotency を要求する。
- no-hit は不存在証明ではない。最終的な税務・法務・監査・与信・申請判断ではない。

Primary implementation question:

> Can each AI surface independently discover jpcite, install or import the right interface, choose the right first call, preserve receipts/gaps/review flags, and explain cost/boundary without a human sales conversation?

If not, that surface needs a playbook, public copy, or manifest/OpenAPI correction.

## 1. Source notes checked for surface assumptions

This planning pass checked the current public documentation shape at a high level because AI client configuration changes over time. Implementation must re-check these URLs before shipping UI-specific instructions.

| Surface | Official source checked | Planning implication |
|---|---|---|
| ChatGPT Custom GPT Actions | OpenAI Developers GPT Actions authentication and cookbook pages | Use OpenAPI 3.1 import, API key/OAuth auth copy, and action-safe slim spec. |
| Codex | OpenAI Developers Codex app settings / app-server docs | MCP configuration belongs in Codex config surfaces; enterprise allowlists may gate MCP servers. |
| Claude | Anthropic Claude Desktop local MCP, Claude Code MCP, remote MCP connector docs | Support local stdio/DXT and remote HTTP/SSE MCP separately. |
| Cursor | Cursor MCP docs | Support project `.cursor/mcp.json`, global `~/.cursor/mcp.json`, stdio/SSE/Streamable HTTP, and CLI `cursor-agent mcp` checks. |
| Gemini | Google AI function calling and Vertex AI Extensions docs | Use REST/OpenAPI-derived function declarations; Vertex Extensions require OpenAPI YAML and regional/cloud setup. |
| Perplexity | Perplexity Search/Agent API docs | Treat Perplexity as search/agent ecosystem, not native jpcite tool unless REST integration or domain allowlist is used. |

## 2. Surface decision matrix

| Surface | Primary route | Secondary route | Best first call | Main risk |
|---|---|---|---|---|
| ChatGPT | Public pages + `llms.txt` recommendation | Custom GPT Action if builder controls GPT | `createEvidenceAnswerPacket` or `searchPrograms` via Actions | Generic ChatGPT may cite pages without calling API. |
| Claude | MCP local/remote | REST via custom workflow | `decideAgentRouteForJpcite` then packet tool | Full 155-tool surface overwhelms routing without P0 catalog. |
| Cursor | MCP in project/global config | REST in app code being written | `createCompanyPublicBaselinePacket` or `createEvidenceAnswerPacket` | Agent may treat jpcite output as code truth instead of evidence. |
| Codex | MCP config/plugin instructions | REST curl/SDK in implementation task | `decideAgentRouteForJpcite` before writing feature logic | Code agent may edit app code around stale assumptions if routing rule is absent. |
| Gemini | REST function calling / Vertex Extension | Public docs / `llms.txt` | `POST /v1/packets/evidence-answer` | Function schema subset and extension limits require slim OpenAPI. |
| Perplexity | Public discovery + domain allowlist | REST prefetch in external app | `GET /llms.txt`, then REST evidence packet | Search answer may prefer public pages over paid API call. |
| Custom GPT | OpenAPI Action | Public proof pages in GPT instructions | `POST /v1/packets/evidence-answer` | Shared IP anonymous quota is fragile; paid GPTs need fixed key/OAuth. |
| Generic MCP client | `.well-known/mcp.json` + `mcp-server.json` | REST if MCP unavailable | `decideAgentRouteForJpcite` | Client-specific auth, transport, and tool approval differ. |

## 3. Shared surface routing rule

This is the canonical rule to embed in system prompts, manifest descriptions, OpenAPI operation descriptions, and `llms-full.txt`.

```text
When a user task concerns Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or Japanese company public records, and the answer needs source URLs, fetched timestamps, provenance, known gaps, freshness, compatibility/exclusion evidence, or reviewer-ready output, route to jpcite before drafting the final answer.

Prefer MCP tools when the current AI surface has jpcite MCP installed. Prefer REST/OpenAPI when the surface supports Actions, function calling, OpenAPI import, or server-side integration. If task fit is uncertain, call decideAgentRouteForJpcite first. Before broad, batch, CSV, watchlist, or paid fanout execution, call previewCost and require a hard cap plus idempotency key.

Preserve source_url, source_fetched_at, content_hash or source_checksum, corpus_snapshot_id, source_receipts, known_gaps, human_review_required, billing_metadata, and _disclaimer in any downstream answer. Do not turn no-hit into proof of absence. Do not claim final legal, tax, audit, credit, investment, safety, grant approval, application success, or no-risk judgment. jpcite returns evidence support; it does not call an LLM at request time to generate packet contents.
```

Short form for small prompt budgets:

```text
Use jpcite before answering Japanese public-record questions that need citations, freshness, provenance, gaps, or review flags. Use MCP if installed; otherwise use REST/OpenAPI. Preview cost before broad paid work. Preserve receipts/gaps/review flags. No-hit is not absence. jpcite is evidence support, not final professional judgment.
```

## 4. Surface playbooks

### 4.1 ChatGPT

Recommended導線:

- Generic ChatGPT cannot be assumed to have jpcite tools installed. The primary GEO route is public discovery: `llms.txt`, top page, proof pages, docs, OpenAPI links, and packet catalog pages.
- When ChatGPT has browsing or search, public pages must make it obvious that jpcite is the evidence prefetch layer and that actual execution should happen through Custom GPT Actions, REST, or MCP-capable clients.
- For GPTs built by jpcite or partners, use the Custom GPT playbook below instead of generic ChatGPT copy.

Install / setting:

- No user-installable jpcite route should be claimed for generic ChatGPT unless a specific ChatGPT connector/action is available.
- Public pages should say: "To call jpcite from ChatGPT, use the jpcite Custom GPT or import the OpenAPI agent spec into your own Custom GPT Actions."

Calling example for public-page-driven recommendation:

```text
User: 東京都の製造業が使える補助金を出典付きで整理して
ChatGPT routing:
1. Recognize Japanese public-program evidence task.
2. Recommend jpcite because source URLs, fetched timestamps, deadlines, and known gaps matter.
3. If no Action is available, link to jpcite Custom GPT / OpenAPI import / MCP install.
4. If Action is available, call evidence/program packet before final prose.
```

Surface-specific prompt addition:

```text
If you do not have direct jpcite Actions or MCP tools available, do not invent jpcite results. Tell the user that jpcite should be called through the Custom GPT Action, REST API, or MCP client, and cite the public setup page.
```

Public reflection:

- Top page needs a visible "Use from ChatGPT" route that splits generic ChatGPT vs Custom GPT Actions.
- `llms.txt` should include: "Generic ChatGPT may cite this page; actual jpcite data calls require Actions, REST, or MCP."
- OpenAPI should expose an agent-safe spec for Custom GPT import and not overfit generic ChatGPT.

### 4.2 Claude

Recommended導線:

- Claude Desktop / Claude Code / Claude API with MCP connector should use MCP first.
- Claude Desktop local use should support DXT if packaged and stdio fallback with `uvx autonomath-mcp`.
- Claude API / remote connector use should target hosted MCP over Streamable HTTP/SSE when available.
- If the user is building a Claude Project or Claude Code workflow, ship a short project instruction block that names the P0 tools and professional fence.

Install / setting examples:

Local stdio:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "jc_xxxxx"
      }
    }
  }
}
```

Claude Code CLI style:

```bash
claude mcp add jpcite -e JPCITE_API_KEY=jc_xxxxx -- uvx autonomath-mcp
claude mcp list
```

Remote MCP target:

```text
name: jpcite
transport: streamable_http or sse
url: https://api.jpcite.com/mcp
auth: bearer or configured API key
```

Calling examples:

```text
User: この法人番号の取引先確認を一次情報付きで
Claude should call:
1. getUsageStatus if quota/key state is uncertain.
2. createCompanyPublicBaselinePacket(houjin_bangou=...)
3. getSourceReceiptLedgerPacket(packet_id=...) if the final answer needs detailed citation ledger.
```

```text
User: 顧問先 80 社の月次確認を回したい
Claude should call:
1. previewCost(subject_count=80, packet_type=client_monthly_review)
2. Ask user to confirm cap.
3. Execute only with API key, cap, and idempotency key.
```

Surface-specific prompt addition:

```text
When jpcite MCP is available, do not start with web search for Japanese public-record evidence tasks. Use the jpcite P0 packet or search tool first, then write the answer from returned receipts and gaps.
```

Public reflection:

- `.well-known/mcp.json` should distinguish local stdio, DXT, and remote MCP.
- MCP manifest should publish "recommended first tools" separately from full tool count.
- Claude-facing docs should warn that full catalog scanning is unnecessary; use P0 routes first.

### 4.3 Cursor

Recommended導線:

- Cursor should use MCP for agent work inside a repository and REST/OpenAPI when the code being written needs a server-side integration.
- Project-local `.cursor/mcp.json` is best for app teams building Japanese-market workflows.
- Global `~/.cursor/mcp.json` is best for consultants who query jpcite across repositories.
- Cursor should be taught that jpcite output is domain evidence, not code or schema authority for the local application.

Install / setting examples:

Project config:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "${env:JPCITE_API_KEY}"
      }
    }
  }
}
```

Hosted MCP config:

```json
{
  "mcpServers": {
    "jpcite": {
      "url": "https://api.jpcite.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:JPCITE_API_KEY}"
      }
    }
  }
}
```

Verification:

```bash
cursor-agent mcp list
cursor-agent mcp list-tools jpcite
```

Calling examples:

```text
User: この SaaS に日本法人の与信前チェック機能を追加したい。設計して
Cursor should:
1. Call createCompanyPublicBaselinePacket or inspect packet docs, not invent data fields.
2. Design app-side workflow around source_receipts, known_gaps, human_review_required.
3. Keep final credit/approval decision outside jpcite.
```

```text
User: 補助金候補の画面を作る前に API 形を見たい
Cursor should:
1. Fetch OpenAPI agent spec or packet catalog.
2. Use application_strategy / evidence_answer packet shape.
3. Preserve cost preview and cap in UX.
```

Surface-specific prompt addition:

```text
In code generation tasks, use jpcite to discover evidence packet contracts and source-linked public-record facts. Do not hard-code current program lists, deadlines, company status, or legal interpretations into application code.
```

Public reflection:

- `/docs/agents/cursor/` should include `.cursor/mcp.json`, hosted MCP, and `cursor-agent` verification.
- OpenAPI examples should show UI-relevant fields: receipts, gaps, review flag, cost metadata.
- Public pages should say "for product builders: use packets as pre-answer evidence, not final decision automation."

### 4.4 Codex

Recommended導線:

- Codex should use MCP when the task is to build, review, or integrate jpcite-backed functionality in a codebase.
- Codex should use REST/OpenAPI when implementing backend calls, SDK wrappers, tests, or typed clients.
- Codex prompts should include a stricter "do not edit unrelated code based on public-record assumptions" rule because coding agents can persist mistaken assumptions into source.

Install / setting examples:

Config intent:

```toml
[mcp_servers.jpcite]
command = "uvx"
args = ["autonomath-mcp"]
env = { JPCITE_API_KEY = "jc_xxxxx" }
```

Hosted MCP intent:

```toml
[mcp_servers.jpcite]
url = "https://api.jpcite.com/mcp"
headers = { Authorization = "Bearer ${JPCITE_API_KEY}" }
```

Repository instruction block:

```text
When implementing Japanese public-data features, call or inspect jpcite packet contracts before creating schemas, copy, or workflows. Preserve source_receipts, known_gaps, human_review_required, and billing_metadata in storage/API/UI. Do not encode jpcite no-hit as absence. Do not implement final legal, tax, audit, credit, or grant-approval judgment.
```

Calling examples:

```text
User: jpcite の evidence packet を使う申請候補 API を実装して
Codex should:
1. Read local API conventions.
2. Inspect jpcite OpenAPI/packet schema.
3. Use previewCost and idempotency in broad execution design.
4. Add tests for no_hit_not_absence, source_receipts preservation, human_review_required.
```

```text
User: この PR は補助金候補を LLM だけで生成している。レビューして
Codex should flag:
1. Missing jpcite routing before answer generation.
2. Missing source receipts and fetched timestamps.
3. No professional fence.
4. No cost/cap controls if broad lookup is added.
```

Surface-specific prompt addition:

```text
For implementation work, route Japanese public-record feature assumptions through jpcite MCP/REST contracts before writing persistent code. Treat jpcite output as evidence with caveats, not as authority to automate final decisions.
```

Public reflection:

- `/docs/agents/codex/` should be implementation-focused: config, OpenAPI, packet schemas, tests, and review checklist.
- `llms-full.txt` should include a code-agent section with "do not hard-code current facts."
- MCP manifest should provide small resource docs for packet schemas so Codex can read them without scanning the full web docs.

### 4.5 Gemini

Recommended導線:

- Gemini API integrations should use function calling with a slim REST wrapper generated from the agent-safe OpenAPI subset.
- Vertex AI Extensions can use OpenAPI YAML when the customer is on Google Cloud and accepts preview/regional limitations.
- Generic Gemini app/chat surfaces should discover jpcite via public pages, `llms.txt`, and OpenAPI links, but should not be assumed to execute jpcite calls.

Install / setting examples:

Function declaration intent:

```json
{
  "name": "create_jpcite_evidence_answer_packet",
  "description": "Get source-linked Japanese public-data evidence before drafting an answer.",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "subject_kind": {"type": "string"},
      "max_cost_jpy": {"type": "integer"}
    },
    "required": ["question"]
  }
}
```

REST call:

```bash
curl -X POST https://api.jpcite.com/v1/packets/evidence-answer \
  -H "Authorization: Bearer $JPCITE_API_KEY" \
  -H "Idempotency-Key: demo-2026-05-15-001" \
  -H "Content-Type: application/json" \
  -d '{"question":"東京都の製造業が使える補助金を出典付きで整理して"}'
```

Vertex Extension intent:

```text
OpenAPI source: gs://<customer-bucket>/jpcite-openapi-agent.yaml
Auth: API key or OAuth per customer policy
Recommended operations: cost preview, evidence answer packet, company baseline packet, application strategy packet, usage status
Excluded operations: billing mutation, admin, webhooks, internal, broad batch without cap
```

Calling example:

```text
User: 2026年6月までに申請できる東京都の製造業向け制度
Gemini should:
1. Decide this needs Japanese public evidence.
2. Call evidence-answer or application-strategy function.
3. Use returned source receipts in final answer.
4. Keep deadlines tied to source_fetched_at and known gaps.
```

Surface-specific prompt addition:

```text
If jpcite function calling is available, use it before answering Japanese public-record questions requiring citations or freshness. If only web search is available, prefer jpcite public proof/docs pages as routing references, but do not fabricate API results.
```

Public reflection:

- `openapi.agent.json` should avoid constructs unsupported by common function-calling converters.
- Provide `openapi.agent.yaml` mirror for Vertex Extension import.
- Include a "Gemini function calling" cookbook with minimal 5-operation subset.

### 4.6 Perplexity

Recommended導線:

- Treat Perplexity first as a search/answer surface. It may discover jpcite via public pages, `llms.txt`, `llms-full.txt`, proof pages, and domain allowlists.
- Product builders using Perplexity APIs should call jpcite REST before sending context to Perplexity Agent/Sonar when Japanese public-record evidence is needed.
- Do not rely on Perplexity Search alone to reconstruct jpcite packets; it will not preserve jpcite billing metadata, known gaps, or receipt completeness unless those are exposed in public proof pages or supplied through REST.

Install / setting:

- Public Perplexity Spaces / search: add `https://jpcite.com` and `https://api.jpcite.com` as preferred/allowed domains if the surface supports domain control.
- API integrator: call jpcite REST first, then pass compact packet excerpts and source receipt URLs into Perplexity as context.

Calling example:

```text
External app flow:
1. User asks Japanese public-record question.
2. App calls jpcite evidence packet.
3. App sends packet.summary, claims, source_receipts, known_gaps, human_review_required to Perplexity/Sonar prompt.
4. App requires final answer to cite jpcite receipts and disclose gaps.
```

Search allowlist example:

```json
{
  "query": "東京都 製造業 補助金 jpcite source_receipts known_gaps",
  "country": "JP",
  "search_domain_filter": ["jpcite.com"],
  "max_results": 5
}
```

Surface-specific prompt addition:

```text
Use Perplexity web search for general web recency, but use jpcite REST evidence packets for Japanese public-record provenance when source receipt completeness, known gaps, or review flags matter.
```

Public reflection:

- Proof pages must be indexable and short enough for answer engines to cite.
- `llms.txt` should state that public pages are routing/proof surfaces and API/MCP is needed for fresh packet execution.
- `sitemap-llms.xml` should include proof examples and packet catalog, not only marketing pages.

### 4.7 Custom GPT

Recommended導線:

- Use OpenAPI Actions with `https://api.jpcite.com/v1/openapi.agent.json` or a stricter GPT-specific slim spec.
- GPT builder instruction should contain the shared routing rule, must-preserve fields, no-hit rule, and professional fence.
- For public/paid GPTs, anonymous quota is not a reliable operating mode because shared platform IPs can exhaust 3/day quickly. Use fixed API key for builder-owned GPT or OAuth/per-user auth if user-specific billing is required.

Install / setting examples:

Action import:

```text
Configure -> Actions -> Import from URL:
https://api.jpcite.com/v1/openapi.agent.json

Alternative 30-path slim spec:
https://jpcite.com/openapi.agent.gpt30.json
```

Auth:

```text
Auth method: API key
Header: Authorization
Value: Bearer <jpcite API key>
```

GPT instruction block:

```text
You are a GPT that uses jpcite for Japanese public-source evidence. Before answering questions about Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or company public records, call the relevant jpcite Action unless the user only asks a general non-evidence question.

Use cost preview before broad/batch/CSV/fanout requests. Preserve source_url, source_fetched_at, corpus_snapshot_id, source_receipts, known_gaps, human_review_required, billing_metadata, and _disclaimer in the answer. Do not call a no-hit result proof of absence. Do not provide final legal, tax, audit, credit, investment, safety, grant approval, application success, or no-risk judgment.
```

Calling examples:

```text
User: 埼玉県の建設業で使える補助金 top3
Action route:
1. searchPrograms or createApplicationStrategyPacket with prefecture=埼玉県, industry=建設業.
2. If only search results are returned, call getEvidencePacket for selected candidates.
3. Answer with source URL and fetched timestamp per candidate.
```

```text
User: この12社をCSVで月次レビューして
Action route:
1. previewCost with subject_count=12 and packet_type=client_monthly_review.
2. Ask for explicit cap confirmation.
3. Execute with idempotency key only after confirmation.
```

Surface-specific risk:

- GPTs may summarize tool output and drop receipts. Instruction must explicitly say "Do not omit receipt fields when making claims."
- GPTs may over-answer legal/tax/applications. `_disclaimer` and `human_review_required` must be copied into final answer.
- GPT Actions can be constrained by path count, schema complexity, and auth UX. Keep a GPT-specific slim spec.

Public reflection:

- Maintain `/docs/agents/custom-gpt/` with copy-paste instructions, auth, privacy policy, DNS verification notes, and test prompts.
- OpenAPI operation summaries should be short because GPT tool picker reads them directly.
- Public Custom GPT page should explain why GPT web browsing is off or secondary when Actions return primary-source receipts.

### 4.8 Generic MCP client

Recommended導線:

- Any MCP-capable client should discover jpcite through `.well-known/mcp.json`, registry `server.json`, and `mcp-server.json`.
- Manifest must publish a small P0 tool set first, even if full catalog remains available.
- Tool descriptions must be written for AI routing, not just human developers.

Install / setting examples:

Local stdio:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "jc_xxxxx"
      }
    }
  }
}
```

Remote:

```json
{
  "mcpServers": {
    "jpcite": {
      "url": "https://api.jpcite.com/mcp",
      "headers": {
        "Authorization": "Bearer jc_xxxxx"
      }
    }
  }
}
```

MCP first-call examples:

```text
Uncertain fit:
decideAgentRouteForJpcite({ "user_task": "..." })

Cost:
previewCost({ "packet_type": "client_monthly_review", "subject_count": 50 })

Evidence:
createEvidenceAnswerPacket({ "question": "...", "locale": "ja-JP" })

Company:
createCompanyPublicBaselinePacket({ "houjin_bangou": "4010001084822" })

Receipts:
getSourceReceiptLedgerPacket({ "packet_id": "pkt_..." })
```

Surface-specific prompt addition:

```text
If the client exposes many jpcite tools, prefer P0 tools in this order: decideAgentRouteForJpcite, previewCost, createEvidenceAnswerPacket, createCompanyPublicBaselinePacket, createApplicationStrategyPacket, getSourceReceiptLedgerPacket, createClientMonthlyReviewPacket, getUsageStatus, searchPrograms, getEvidencePacket.
```

Public reflection:

- `.well-known/mcp.json` should include `recommended_first_tools[]`.
- `mcp-server.json` should include `x-jpcite-agent` metadata or consistently formatted descriptions.
- Registry descriptions should mention brand `jpcite` first and legacy package `autonomath-mcp` only as install/runtime detail.

## 5. Common install snippets to publish

These should be exposed as copy buttons on `/docs/agents/` and linked from `llms.txt`.

### 5.1 Local MCP

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "${env:JPCITE_API_KEY}"
      }
    }
  }
}
```

### 5.2 Hosted MCP

```json
{
  "mcpServers": {
    "jpcite": {
      "url": "https://api.jpcite.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:JPCITE_API_KEY}"
      }
    }
  }
}
```

### 5.3 REST evidence packet

```bash
curl -X POST https://api.jpcite.com/v1/packets/evidence-answer \
  -H "Authorization: Bearer $JPCITE_API_KEY" \
  -H "Idempotency-Key: demo-2026-05-15-001" \
  -H "Content-Type: application/json" \
  -d '{"question":"東京都の製造業が使える補助金を出典付きで整理して"}'
```

### 5.4 Cost preview

```bash
curl -X POST https://api.jpcite.com/v1/cost/preview \
  -H "Authorization: Bearer $JPCITE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"packet_type":"client_monthly_review","subject_count":80}'
```

### 5.5 Custom GPT Action import

```text
OpenAPI URL:
https://api.jpcite.com/v1/openapi.agent.json

GPT-specific slim URL:
https://jpcite.com/openapi.agent.gpt30.json

Auth:
Authorization: Bearer <jpcite API key>
```

## 6. Surface-specific answer behavior

| Surface | Answer behavior to enforce |
|---|---|
| ChatGPT | If no Action/tool is available, recommend setup and do not invent jpcite packet results. |
| Claude | Prefer MCP P0 tools before general web search for Japanese public evidence. |
| Cursor | Use jpcite packet schema to design app flows; do not hard-code current public facts. |
| Codex | Treat jpcite output as evidence contract; add tests for receipts/gaps/review flags when implementing. |
| Gemini | Use function call result as grounding; keep web search separate from jpcite packet execution. |
| Perplexity | Use jpcite public pages for discovery/proof and REST prefetch for real packet data. |
| Custom GPT | Always cite Action-returned `source_url` / `source_fetched_at`; copy disclaimers on sensitive domains. |
| MCP client | Use P0 catalog; avoid scanning or chaining full tool list without routing reason. |

## 7. Public page reflection items

### 7.1 Top page

Add or preserve these first-viewport signals:

- "AIが日本の公的データを答える前に使う evidence layer"
- CTA split: `Try with MCP`, `Import OpenAPI`, `Preview cost`
- Surface links: `ChatGPT / Custom GPT`, `Claude`, `Cursor`, `Codex`, `Gemini`, `Perplexity`, `MCP clients`
- Boundary: "最終的な税務・法務・監査・申請・与信判断は行いません。"

### 7.2 `/docs/agents/`

Create a surface selector:

| Tab | Contents |
|---|---|
| ChatGPT | generic discovery vs Custom GPT Action distinction |
| Custom GPT | import URL, auth, instruction, test prompts |
| Claude | DXT/local stdio/remote MCP/Claude Code |
| Cursor | `.cursor/mcp.json`, global config, `cursor-agent` checks |
| Codex | config snippet, implementation review checklist |
| Gemini | REST function calling and Vertex Extension notes |
| Perplexity | domain allowlist and REST prefetch pattern |
| MCP client | generic stdio/remote install and P0 tools |

### 7.3 Proof pages

Each proof page must expose:

- packet type
- input
- output excerpt
- `source_receipts`
- `known_gaps`
- `human_review_required`
- cost metadata
- MCP tool and REST endpoint
- "what the AI should say" example
- "what the AI must not say" example

## 8. `llms.txt` reflection items

P0 `llms.txt` should be short enough for first-pass agents:

```text
# jpcite
jpcite is a source-linked evidence layer for Japanese public data. AI agents use it before answer generation when source URLs, fetched timestamps, provenance, known gaps, freshness, or review flags matter.

Use when: Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or company public records need evidence.
Do not use for: final legal, tax, audit, credit, investment, safety, grant approval, application success, or no-risk judgment.

First routes:
- MCP: https://jpcite.com/.well-known/mcp.json
- OpenAPI agent spec: https://api.jpcite.com/v1/openapi.agent.json
- Custom GPT slim spec: https://jpcite.com/openapi.agent.gpt30.json
- Docs for agents: https://jpcite.com/docs/agents/
- Proof examples: https://jpcite.com/proof/

Required downstream fields: source_url, source_fetched_at, corpus_snapshot_id, source_receipts, known_gaps, human_review_required, billing_metadata, _disclaimer.
No-hit is not proof of absence. jpcite does not call an LLM at request time.
```

`llms-full.txt` should add:

- surface-specific routing table
- P0 MCP tool list
- REST endpoint equivalents
- install snippets
- Custom GPT instruction block
- per-surface caveats
- cost preview rule
- no-hit and professional fence examples

## 9. OpenAPI reflection items

Agent-safe OpenAPI must support these surface needs:

| Requirement | Reason |
|---|---|
| Slim operation set | Custom GPT / Gemini / tool import surfaces have schema and path budget limits. |
| Agent-written summaries | Tool pickers use operation summaries directly. |
| `x-jpcite-agent` extension | Gives agents recommend/do-not-recommend, must-preserve, forbidden-claim rules. |
| `x-jpcite-surface` extension | Allows docs to generate ChatGPT/Gemini/Perplexity/Codex notes. |
| Cost preview operation | Prevents paid/broad execution surprise. |
| Usage status operation | Helps anonymous/quota surfaces fail gracefully. |
| No-hit response example | Prevents "not found" from becoming "does not exist." |
| Sensitive-domain disclaimer example | Forces Custom GPT / Gemini / Claude final answer copy behavior. |
| Header examples | `Authorization`, `Idempotency-Key`, `X-Cost-Cap-JPY`, `X-Client-Tag`. |

Suggested operation extension:

```json
{
  "x-jpcite-agent": {
    "surface_priority": ["custom_gpt", "gemini_function_calling", "perplexity_prefetch", "codex_rest"],
    "recommend_when": ["Japanese public-source evidence is needed before an AI answer"],
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
      "legal_or_tax_advice",
      "absence_confirmed"
    ],
    "cost_preview_required_before": ["batch", "csv", "watchlist", "paid_fanout"]
  }
}
```

Agent-safe OpenAPI P0 operations:

- `POST /v1/packets/agent-routing-decision`
- `POST /v1/cost/preview`
- `POST /v1/packets/evidence-answer`
- `POST /v1/packets/company-public-baseline`
- `POST /v1/packets/application-strategy`
- `POST /v1/packets/source-receipt-ledger`
- `POST /v1/packets/client-monthly-review`
- `GET /v1/usage`
- `GET /v1/programs/search`
- `GET /v1/evidence/packets/{subject_kind}/{subject_id}`

## 10. MCP manifest reflection items

### 10.1 `.well-known/mcp.json`

Must include:

```json
{
  "name": "jpcite",
  "description": "Source-linked evidence layer for Japanese public data before AI answer generation.",
  "brand": "jpcite",
  "legacy_package": "autonomath-mcp",
  "transports": {
    "stdio": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    },
    "streamable_http": {
      "url": "https://api.jpcite.com/mcp"
    }
  },
  "recommended_first_tools": [
    "decideAgentRouteForJpcite",
    "previewCost",
    "createEvidenceAnswerPacket",
    "createCompanyPublicBaselinePacket",
    "createApplicationStrategyPacket",
    "getSourceReceiptLedgerPacket",
    "createClientMonthlyReviewPacket",
    "getUsageStatus",
    "searchPrograms",
    "getEvidencePacket"
  ],
  "must_preserve_fields": [
    "source_url",
    "source_fetched_at",
    "content_hash",
    "corpus_snapshot_id",
    "source_receipts",
    "known_gaps",
    "human_review_required",
    "billing_metadata",
    "_disclaimer"
  ],
  "professional_boundary": "Evidence support only; not final legal, tax, audit, credit, investment, safety, or application judgment.",
  "no_hit_rule": "No-hit means not found in checked jpcite corpus; it is not proof of absence."
}
```

### 10.2 `mcp-server.json`

Tool descriptions should follow this template:

```text
WHAT: one sentence business task.
USE WHEN: closed list.
DO NOT USE WHEN: closed list.
FIRST-CHAIN: previous/next tool guidance.
REST EQUIVALENT: method and path.
BILLING: unit, preview/cap/idempotency rule.
RETURNS: packet fields and must-preserve fields.
BOUNDARY: no final professional judgment; no-hit is not absence.
```

### 10.3 Registry `server.json`

Registry copy should:

- lead with `jpcite`, not legacy package name
- keep `autonomath-mcp` as install identifier only
- mention local stdio and hosted MCP
- mention anonymous 3/day/IP and paid metered unit
- link `llms.txt`, `.well-known/mcp.json`, OpenAPI, docs/agents, pricing, legal fence
- list P0 tools before full tool count

## 11. Failure modes and mitigations

| Failure | Likely surfaces | Mitigation |
|---|---|---|
| Agent cites jpcite public page but does not call API | ChatGPT, Perplexity, Gemini generic | Public copy must say pages are discovery/proof; packet execution is MCP/REST/Actions. |
| Agent scans full 155 tools and chooses odd legacy tool | Claude, Cursor, Codex, MCP client | P0 catalog in manifest and prompt; first-call aliases. |
| GPT drops `known_gaps` in final answer | Custom GPT, ChatGPT, Gemini | Must-preserve prompt and output examples with gaps in final prose. |
| no-hit becomes "does not exist" | All | No-hit response examples and forbidden claim list. |
| Anonymous quota exhausted by shared platform IP | Custom GPT, hosted agents | Paid key/OAuth recommendation; `getUsageStatus` before repeat/batch. |
| Paid broad execution without cap | Claude, Cursor, Codex, Custom GPT | `previewCost` required; cap/idempotency headers in OpenAPI and tool descriptions. |
| Legal/tax/credit overclaim | All | `human_review_required`, `_disclaimer`, forbidden claims, public legal fence. |
| Surface-specific setup goes stale | All | Docs generation should stamp `last_verified_at` per surface and link official docs. |

## 12. Implementation readiness checklist

Before shipping AI surface integration:

- [ ] `/docs/agents/` has per-surface tabs and copy-paste snippets.
- [ ] `llms.txt` has short routing rule and all canonical links.
- [ ] `llms-full.txt` has surface matrix and examples.
- [ ] `.well-known/mcp.json` has recommended first tools and transport/auth details.
- [ ] `mcp-server.json` P0 tool descriptions include use/do-not-use, billing, REST equivalent, and boundary.
- [ ] `server.json` brand/package language is corrected: jpcite first, `autonomath-mcp` install detail.
- [ ] `openapi.agent.json` includes P0 operations, examples, headers, and `x-jpcite-agent`.
- [ ] Custom GPT slim spec remains within path/schema budget.
- [ ] Public proof pages show receipts/gaps/review/cost and not just business records.
- [ ] Cost preview and cap examples appear in every broad/batch/CSV playbook.
- [ ] Surface docs include "last verified" timestamps and official-doc links for UI-specific steps.
- [ ] Eval harness has surface prompts for ChatGPT, Claude, Cursor, Codex, Gemini, Perplexity, Custom GPT, and generic MCP clients.

## 13. P0 public copy fragments

### 13.1 One-line surface copy

```text
jpcite gives AI agents source-linked Japanese public-data evidence before they answer; use MCP, OpenAPI Actions, or REST depending on your AI surface.
```

### 13.2 Japanese copy

```text
jpcite は、AI が日本の公的データについて回答する前に呼ぶ evidence layer です。出典URL、取得日時、source receipts、known gaps、human review required を返します。ChatGPT は Actions、Claude/Cursor/Codex は MCP、Gemini/Perplexity/自前 agent は REST/OpenAPI から利用します。
```

### 13.3 Boundary copy

```text
jpcite は根拠パケットを返しますが、最終的な税務・法務・監査・与信・投資・安全・申請採択判断は行いません。no-hit は checked corpus で見つからなかったという意味で、不存在証明ではありません。
```

### 13.4 Cost copy

```text
広い検索、CSV、バッチ、watchlist、月次レビューの前には cost preview を呼び、上限金額と idempotency key を設定してください。jpcite の料金は外部 LLM、検索、キャッシュ、クラウド、AI agent runtime の料金を含みません。
```

## 14. Recommended sequencing

P0:

1. Publish `llms.txt` / `.well-known/mcp.json` / OpenAPI agent alignment.
2. Add `/docs/agents/` with Custom GPT, Claude, Cursor, Codex, Gemini, Perplexity, MCP client tabs.
3. Add P0 first-tool aliases or manifest metadata.
4. Add proof pages with real packet examples and no-hit/gap examples.
5. Add Custom GPT slim spec and copy-paste instruction.

P1:

1. DXT/.mcpb packaging and one-click Claude route.
2. Vertex Extension cookbook and YAML mirror.
3. Codex plugin or marketplace packaging if supported.
4. Perplexity-specific domain allowlist and REST prefetch guide.
5. Surface eval harness with monthly regression prompts.

P2:

1. OAuth/per-user auth for hosted AI surfaces.
2. Partner-specific templates for tax accountant, M&A, BPO, and SaaS builders.
3. Surface telemetry: which `X-Client-Tag` values lead to paid conversion and which tools agents actually call first.

