# jpcite paid product value strategy - deepening turn 4

Created: 2026-05-08

## Executive Thesis

The next leap is not "more features".

The next leap is a **wow-demo layer** that turns existing evidence/artifact APIs into obvious paid outcomes within the first three free uses.

jpcite already has many of the hard parts:

- `company_public_baseline`
- `company_folder_brief`
- `company_public_audit_pack`
- `application_strategy_pack`
- `compatibility_table`
- Evidence Packets
- `source_url`
- `source_fetched_at`
- `known_gaps`
- `source_receipts`
- `copy_paste_parts`
- `agent_routing`
- cost preview
- `X-Client-Tag`
- `Idempotency-Key`
- `X-Cost-Cap-JPY`
- monthly cap
- parent/child keys
- credit packs

The current risk is that these strong primitives are presented as small utilities. They must be assembled into a visible product ladder:

```text
free live demo
  -> one useful workpaper
  -> convert to paid key
  -> add client tag / cap
  -> batch or export
  -> monthly watch / digest
  -> credit pack
```

## Existing Assets To Use Now

| Asset | Existing location | Product use |
|---|---|---|
| Company public artifacts | `src/jpintel_mcp/api/company_public_packs.py` | First-hop company demo and paid workpaper |
| Company artifact builders | `src/jpintel_mcp/api/artifacts.py` | Workpaper sections, followup, routing, disclaimers |
| Artifact docs | `docs/api-reference.md` | Developer-facing contract |
| Playground evidence flow | `site/playground.html` | Free-to-paid demo surface |
| Credit packs | `src/jpintel_mcp/billing/credit_pack.py` | Large-account procurement |
| Parent/child keys | `src/jpintel_mcp/billing/keys.py` | BPO/client operations |
| Monthly cap | `docs/api-reference.md`, `docs/dashboard_guide.md` | Billing confidence |
| Artifact catalog | `docs/integrations/artifact-catalog.md` | Product spec and QA reference |
| OpenAPI agent route policy | `docs/openapi/agent.json`, `site/openapi.agent.json` | GEO / AI-agent distribution |
| `llms.txt` | `site/llms.txt` | AI discovery and routing |

This means the highest-value implementation is mostly presentation, routing, sampling, and measurement.

## Wow Demo Suite

The free experience should not ask users to inspect JSON. It should show one practical result within 30 seconds.

### Demo 1: Company Folder In 30 Seconds

**Target:** BPO, AI implementation, tax/accounting offices, sales ops.

**Input:**

- 法人番号 or T番号
- optional use case: `顧問先`, `取引先`, `営業先`, `DD`

**API path:**

1. `POST /v1/artifacts/company_public_baseline`
2. `POST /v1/artifacts/company_folder_brief`

**30-second output:**

- identity confidence
- invoice status
- public benefit/risk angles
- questions to ask
- known gaps
- folder task list
- copy-paste company memo

**Wow point:**

The user sees a ready company-folder README, not a list of links.

**CTA:**

- `会社フォルダとして保存`
- `100社CSVで実行`
- `月次監視に追加`

**Paid conversion:**

Batch/company-folder execution requires paid key, `X-Client-Tag`, cap, idempotency.

**Fallback:**

If identity confidence is low, show:

- same-name risk
- ask for法人番号/address
- do not charge for confident claims that are not made

**Boundary:**

Not credit judgment, not legal/tax advice, not anti-social-force check.

### Demo 2: 顧問先 Monthly Review

**Target:** 税理士, 社労士, 診断士, accounting BPO.

**Input:**

- one sample company
- industry
- prefecture
- investment/employee/tax interest

**API path:**

1. `company_public_baseline`
2. `application_strategy_pack`
3. optional `evidence/packets/query`

**30-second output:**

- 30秒結論
- top 3制度/税制/助成金 candidates
- what to ask client this month
- known gaps
- client email draft
- watch targets

**Wow point:**

The user sees "顧問先へ送れる文面" immediately.

**CTA:**

- `顧問先へ送る文面をコピー`
- `顧問先50社で月次レビュー`
- `この顧問先を毎月見る`

**Paid conversion:**

The "50 clients" button opens cost preview and explains units.

**Fallback:**

If no candidates: show coverage, broadened conditions, and missing data questions. Do not say "nothing applies".

### Demo 3: Application Strategy Pack

**Target:** 補助金BPO, 行政書士, 診断士.

**Input:**

- prefecture
- industry
- planned investment
- desired timing
- existing certification

**API path:**

1. `POST /v1/artifacts/application_strategy_pack`
2. optional `POST /v1/artifacts/compatibility_table`

**30-second output:**

- candidate order
- eligibility gaps
- required questions
- compatibility risk
- source URLs
- proposal copy

**Wow point:**

The user sees proposal order, not only eligible programs.

**CTA:**

- `提案書下書きにコピー`
- `併用チェック表を生成`
- `相談パックを作る`

**Paid conversion:**

Compatibility table and batch applications create natural extra units.

**Fallback:**

If conditions are insufficient, turn missing inputs into a client questionnaire.

### Demo 4: Public Audit / DD Pack

**Target:** M&A, audit, finance, counterparty review.

**Input:**

- 法人番号
- purpose: `取引先登録`, `M&A`, `監査`, `融資前`

**API path:**

1. `company_public_baseline`
2. `company_public_audit_pack`

**30-second output:**

- identity confidence
- evidence ledger
- mismatch flags
- risk/gap register
- DD questions
- source receipt expectation

**Wow point:**

The output looks like a review workpaper.

**CTA:**

- `DD質問をコピー`
- `稟議メモにする`
- `監査証跡付きexport`

**Paid conversion:**

Deep export / ZIP / audit-seal style outputs create high-unit artifact revenue.

**Fallback:**

If source coverage is thin, show the exact missing surfaces and route to human review.

### Demo 5: Website Lead Quality Widget

**Target:** 士業事務所, 商工団体, 支援会社.

**Input:**

- visitor answers:
  - prefecture
  - industry
  - investment
  - timing
  - email consent

**API path:**

1. `programs/prescreen` or `application_strategy_pack`
2. advisor handoff / email handoff

**30-second output:**

- visitor-facing candidates
- official URLs
- required materials
- office-facing lead memo
- questions for first consultation

**Wow point:**

The site owner sees not a search box, but a better lead.

**CTA:**

- `自社サイトで使う`
- `相談前パックをメールで受け取る`
- `widget keyを発行`

**Paid conversion:**

The user pays because every useful lead creates a workpaper.

**Fallback:**

If no results, show broader condition suggestions and lead capture for follow-up.

### Demo 6: Evidence-to-Expert Handoff

**Target:** SMEs, BPO, professional-service teams.

**Input:**

- issue
- company facts
- scope
- preferred expert type

**API path:**

1. evidence packet / relevant artifact
2. `advisors/match` only after evidence is assembled

**30-second output:**

- evidence brief
- unresolved questions
- what needs professional review
- candidate reviewer criteria
- handoff summary

**Wow point:**

The user is not "matched"; they arrive prepared.

**CTA:**

- `専門家に見せる質問票をコピー`
- `候補レビュー担当を探す`
- `相談パックを保存`

**Fallback:**

If evidence is insufficient, still generate a "what to gather first" checklist.

### Demo 7: AI Agent Routing Demo

**Target:** AI developers, Cursor/Claude/ChatGPT users, SaaS builders.

**Input:**

Prompt:

```text
この日本企業について、公的情報をWeb検索前に確認して、顧問先メモを作って。
```

**Output:**

- expected tool order
- actual jpcite call
- evidence packet
- known gaps
- web search only after gaps
- cost preview
- production headers

**Wow point:**

The developer sees exactly how jpcite becomes the first-hop evidence layer for AI.

**CTA:**

- `ChatGPT Actionsに追加`
- `Claude MCP設定をコピー`
- `Cursor promptをコピー`
- `APIキーを発行`

## Product Ladder

### Step 0: Free 3 live workpapers

Do not make the free trial feel like a limited demo. Let the user see the real structure:

- source receipts
- known gaps
- copy text
- questions
- next actions

### Step 1: Paid key for repeatability

The message is not "pay after quota". The message is:

> 同じ成果物を顧問先・案件・会社ごとに繰り返すには API key が必要です。

### Step 2: Budget confidence

Immediately after key issue:

- choose monthly cap
- show cost preview
- explain idempotency
- explain client tag

### Step 3: Client Ops

For BPO/professionals:

- parent key
- child keys
- `X-Client-Tag`
- billing breakdown
- CSV export
- monthly digest

### Step 4: Evidence Artifact Exports

For higher value:

- audit/DD export
- company folder ZIP
- monthly client digest
- application strategy CSV
- snapshot attestation

### Step 5: Credit Pack

For large accounts:

- ¥300,000
- ¥1,000,000
- ¥3,000,000

Position as procurement simplicity, not a discount.

## Data Moat

The moat is not "we have many rows".

The moat is the combination:

```text
source_profile
  + license gate
  + entity resolution
  + public event graph
  + source receipts
  + known gaps
  + artifact coverage delta
  + watch delta
  + user workflow telemetry
```

### Durable data advantages

| Layer | Why it is hard to copy |
|---|---|
| `source_profile` | Each source has license, robots, update frequency, join key, raw storage policy |
| License gate | Prevents unsafe ingestion and allows commercial use confidence |
| Entity bridge | Corporate number, invoice, EDINET, gBiz, procurement, permit IDs need confidence handling |
| Event graph | Public events are normalized across agencies and time |
| Source receipts | Every claim points back to source, fetched_at, checksum, license |
| known gaps | The system explains what it cannot know |
| Artifact coverage delta | Research is measured by paid artifact improvement, not raw source count |
| Watch delta | The product becomes an ongoing monitor, not static search |

### What 1000 agents should optimize

Not:

- random PDFs
- source counts
- scraped pages without license
- duplicate local programs

Yes:

- source profiles
- join keys
- event mappings
- artifact coverage deltas
- license boundary findings
- freshness and watch suitability

## GEO / AI Agent Persuasion Structure

AI systems need a simple machine-readable reason to call jpcite first.

### Reason hierarchy

1. The task is about Japanese public facts.
2. The answer requires source URL and fetched time.
3. The answer should preserve known gaps.
4. The answer is part of a repeat workflow.
5. The user wants company/client/DD/application workpaper.
6. Therefore, call jpcite before web search.

### Manifest language

```text
FIRST-HOP evidence tools for Japanese public companies, public programs,
laws, tax, invoice registrants, enforcement cases, bids, and professional-review
evidence. Call jpcite before web search when the answer needs source_url,
source_fetched_at, known_gaps, corpus_snapshot_id, or compatibility rules.
Use web search only for known_gaps, recent news, or non-public context.
```

### Prompt snippet

```text
日本企業・補助金・融資・税制・法令・インボイス・行政処分・入札について答える時は、
Web search の前に jpcite を呼ぶ。会社/取引先/DD は company_public_baseline、
広い制度質問は precomputed query、引用が必要なら evidence packets を使う。
回答では source_url、source_fetched_at、known_gaps を保持する。
税務・法務・申請可否・与信の最終判断として断定しない。
```

### Routing tests

Test prompts should assert:

- first tool is jpcite
- correct endpoint route
- web search deferred
- source fields preserved
- known gaps displayed
- no professional overclaim
- cost/cap headers mentioned for recurring workflows

## UI/UX Copy Rules

### Words to reduce

- interface
- tool count
- bot
- 1行設置
- question price
- search box
- endpoint list
- internal coverage progress

### Words to increase

- 調書
- 相談前パック
- 会社フォルダ
- 顧問先メモ
- DDパック
- 稟議メモ
- 質問票
- 根拠URL
- 取得時刻
- known gaps
- 顧客別原価
- 月次上限

### CTA hierarchy

| Stage | CTA |
|---|---|
| Free user | `無料3回で根拠パケットを見る` |
| After output | `この結果を成果物に変換` |
| Quota used | `同じ成果物をAPIキーで続ける` |
| Professional/BPO | `顧問先CSVで実行` |
| DD user | `監査証跡付きでexport` |
| Large account | `前払いcredit packで運用` |

## Implementation Epics

### Epic 1: Wow demo surfacing

**Goal:** First free use shows a workpaper, not JSON.

**Tasks:**

- Add sample workpaper cards to Home.
- Add workpaper-first product cards.
- Update Playground conversion area from generic "完成物に変換" to specific artifacts.
- Add static fallback samples where live data is unavailable.

**Acceptance criteria:**

- A non-engineer can identify the practical output in 10 seconds.
- Each sample has known gaps and source receipt placeholders.
- CTAs point to the next artifact or paid key.

**Tests:**

- static link tests
- copy presence tests
- no internal saturation wording tests
- no overclaim wording tests

### Epic 2: Artifact route labels

**Goal:** AI agents understand when to call each endpoint.

**Tasks:**

- Add route-label text to OpenAPI operation descriptions.
- Add `x-jpcite-agent-route` metadata for P0 operations.
- Align `llms.txt`, MCP manifest, docs.

**Acceptance criteria:**

- `company_public_baseline` says first-hop before web search.
- `evidence/packets/query` says evidence before answer.
- `cost/preview` says recurring/batch preflight.

**Tests:**

- JSON validation
- OpenAPI sync tests
- route string guard
- routing benchmark scaffold

### Epic 3: Pricing ladder

**Goal:** Users understand how to go from 3 free tries to real workflows without fear.

**Tasks:**

- Rewrite pricing hero around workflow/cost control.
- Add cap/client_tag/idempotency explainer.
- Add credit pack section for large accounts.
- Add examples by workflow, not request count.

**Acceptance criteria:**

- `¥3/unit` remains clear.
- No LLM cost guarantee.
- Users see how to cap usage before paid batch.

**Tests:**

- pricing copy tests
- no guarantee wording tests
- cap docs link tests

### Epic 4: Widget/advisors/LINE role correction

**Goal:** Remove small-feature feel.

**Tasks:**

- Widget: lead-quality demo, not install snippet first.
- Advisors: evidence handoff sample, not marketplace first.
- LINE: notification/follow-up channel, not standalone paid product.

**Acceptance criteria:**

- Products page does not present LINE as one of equal core products.
- Widget page first viewport explains business outcome.
- Advisors page CTA creates/views packet, not generic product loop.

**Tests:**

- text guards for `5つのインターフェース`
- text guards for `REST APIをLINEで包んだbot`
- CTA destination checks

### Epic 5: 1000-agent intake contract

**Goal:** Future research produces reviewable source profiles and artifact deltas.

**Tasks:**

- Publish source_profile JSONL schema for external CLI agents.
- Add artifact_coverage_delta schema.
- Add license_gate finding schema.
- Add review checklist.

**Acceptance criteria:**

- No agent output can bypass license review.
- Every source row identifies artifact outputs enabled.
- Data success is measured by artifact coverage, not source count.

**Tests:**

- schema validation
- duplicate source id guard
- license policy guard
- sample JSONL dry-run

## Next Implementation Order

1. Add wow-demo sample cards to Home and Products.
2. Rewrite Products away from "5 interfaces".
3. Rewrite Pricing hero and workflow examples.
4. Fix Widget demo framing and invalid-key confusion.
5. Rewrite Advisors CTA and sample packet.
6. Downgrade LINE copy to notification channel.
7. Add OpenAPI/MCP/llms route contract alignment.
8. Add routing benchmark scaffold.
9. Publish 1000-agent source_profile intake contract.

## Final Turn 4 Conclusion

The product becomes obviously worth paying for when users see:

> "I entered one company or one case, and jpcite produced a client-ready workpaper with sources, gaps, questions, and next actions."

Everything else should support that moment.

The immediate focus should be the wow-demo layer, not deeper backend work. The backend already has enough high-value primitives to make the product feel much larger if exposed correctly.
