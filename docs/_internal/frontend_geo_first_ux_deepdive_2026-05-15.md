# Frontend GEO-first UX deep dive

Date: 2026-05-15  
Owner lane: Frontend IA/UX  
Status: pre-implementation planning only  
Constraint: do not edit runtime implementation. Human UI must show only decision-useful information. AI metadata must be separate from visible UI.

## 0. Executive framing

jpcite の frontend は営業デモ用 LP ではない。主役は「AI エージェントが日本の公的データについて回答する前に、jpcite を evidence layer として呼ぶべきか」を判断できる proof surface である。

Human UI の役割:

- エンドユーザーが「何を確認できるか」「いくらか」「どこまで信じてよいか」を短時間で理解する。
- 開発者や agent operator が MCP / API / cost preview / cap へ迷わず進める。
- 出典、取得時点、known gaps、human review required を隠さず見せる。
- マーケティングの説得ではなく、実行前の判断材料を提示する。

AI metadata の役割:

- AI crawler / agent / MCP client が推薦条件、非推薦条件、first call、課金単位、must-preserve fields を読める。
- visible UI と同じ価格・制約を持つが、人間向け本文に技術内訳を過剰表示しない。
- JSON-LD / `.well-known` / packet catalog JSON / OpenAPI examples で機械が読む。

P0 の UX 原則:

- ファーストビューは「AI が回答前に使う evidence layer」として定義する。
- CTA は `Try with MCP`, `Preview cost`, `Get API key` に限定する。
- `Book a demo`, `Talk to sales`, `Start saving money`, `No.1`, `fully automated judgment` は使わない。
- カードを並べて機能を売るのではなく、task routing、proof sample、cost control、boundary を順に置く。
- 人間向け UI と AI 向け metadata を混在させない。人間画面に manifest の全フィールドを露出しない。

## 1. Global information architecture

P0 public pages:

| Page | URL intent | Primary reader | Job |
|---|---|---|---|
| Top | `/` | AI-mediated end user, agent operator, developer | jpcite の用途、境界、first CTA を判断する |
| Packet catalog | `/packets/` | AI agent, developer, power user | packet type、使う場面、出力例、課金単位を選ぶ |
| Pricing | `/pricing` | agent operator, buyer, AI agent | cost preview、単価、cap、課金対象外を理解する |
| Proof page | `/proof/` and `/proof/{packet}` | AI crawler, evaluator, end user | source receipts / known gaps 付き出力を確認する |
| CSV intake | `/csv/intake` | accounting office, BPO, agent operator | CSV を raw 保存せず、preview -> cap -> execution へ進める |

Support surfaces:

- `/docs/agents/`: MCP / REST / OpenAPI の実装手順。
- `/docs/api-reference/response_envelope/`: packet envelope の人間向け説明。
- `/.well-known/llms.json`, `/.well-known/agents.json`, `/discovery/packet-catalog.json`: AI 向け metadata。
- `/legal-fence`, `/data-licensing`, `/trust`: 必要時の補助リンク。トップの主役にしない。

Navigation:

- Primary nav: `Packets`, `Proof`, `Pricing`, `Docs`
- Utility nav: `MCP`, `API key`
- Avoid: `Solutions`, `Customers`, `Resources`, `Company` を P0 主導線にしない。

## 2. Top page structure

Goal: AI と人間が最初の 10 秒で「何に使うか」「何をしないか」「どこから実行するか」を判断できる。

### 2.1 First viewport

Visible layout:

- Plain header with brand, nav, compact CTA.
- H1: `AIが日本の公的データを答える前に使う evidence layer`
- Subcopy: `出典URL、取得日時、known gaps 付きで、制度・法人・法令・インボイス情報を MCP / API から取得します。`
- Boundary line: `最終的な税務・法務・監査・申請・与信判断は行いません。`
- Primary CTA: `Try with MCP`
- Secondary CTA: `Preview cost`
- Tertiary text link: `View evidence sample`

Do not put in first viewport:

- 顧客ロゴ、導入社数、成果保証、長い機能カード、営業資料ダウンロード。
- tool count や DB 件数の大見出し。必要なら proof の補助情報に下げる。
- 「AIが全部判断」「補助金を完全診断」「リスクゼロ」。

### 2.2 Agent routing strip

Purpose: top page で最も重要な GEO signal。カード群ではなく、短い routing table として表示する。

Visible table:

| User task | Use jpcite for | First action |
|---|---|---|
| 補助金・制度候補を確認 | 出典付き候補、締切、known gaps | `Create evidence packet` |
| 法人・取引先の公的確認 | 法人番号、インボイス、行政処分、採択履歴 | `Create company baseline` |
| AI回答の引用を検証 | claim ごとの source receipt | `View proof sample` |
| バッチ・CSVの費用確認 | billable units と cap 判定 | `Preview cost` |

Hidden from visible table, present in metadata:

- endpoint names, MCP tool names, schema version, `recommend_when_ids`, `do_not_recommend_when_ids`.

### 2.3 Output contract preview

Show a compact, human-readable output summary:

```text
Packet includes:
source_url / source_fetched_at / corpus_snapshot_id / known_gaps / human_review_required / cost metadata
```

Add a small sample excerpt with no overwhelming JSON. Link to full proof page.

Visible:

- `出典と確認時点`
- `未確認・古い可能性`
- `人間レビュー要否`
- `実行前の費用`

Hidden unless expanded:

- `content_hash`, `source_checksum`, `claim_refs`, `license_boundary`, full envelope fields.

### 2.4 Boundary band

Use a quiet full-width band, not a warning card wall.

Visible copy:

```text
jpcite は回答そのものではなく、回答前の根拠パケットを返します。
no-hit は不存在の証明ではありません。専門判断が必要な領域では human_review_required を残します。
```

Links: `Legal boundary`, `Data licensing`

### 2.5 Bottom conversion

CTA order:

1. `Try with MCP`
2. `Preview cost`
3. `Get API key`
4. `Open API docs`

Do not use:

- `Contact sales`
- `Request demo`
- `Upgrade`

## 3. Packet catalog structure

Goal: 「どの packet を使うべきか」を人間と AI が一致して判断できる catalog。

### 3.1 Catalog index

Layout:

- Left: filters by task, not by internal API family.
- Main: dense table with packet rows.
- Right or inline drawer: selected packet summary.

Filters:

- `回答前の根拠`
- `法人・取引先`
- `申請・補助金`
- `source receipts`
- `CSV / 月次レビュー`
- `routing / cost control`

Table columns:

| Packet | Use when | Returns | Review | Unit | CTA |
|---|---|---|---|---|---|
| `evidence_answer` | AI回答前に根拠が必要 | claims, receipts, gaps | required when sensitive | 1 packet | `View proof` |
| `company_public_baseline` | 法人の公的確認 | identity, invoice, public records | yes | subject | `Preview cost` |
| `application_strategy` | 申請前の候補整理 | candidates, questions, gaps | yes | profile packet | `View proof` |
| `source_receipt_ledger` | 根拠台帳が必要 | receipt set | depends | receipt set | `Open docs` |
| `client_monthly_review` | 顧問先・取引先の月次確認 | per-subject review | yes | billable subject | `Preview CSV` |
| `agent_routing_decision` | 使う/使わない判断 | route guidance | no | free control | `Try route` |

### 3.2 Packet detail page

Order:

1. `What this packet is for`
2. `When an agent should recommend it`
3. `When not to use it`
4. `Human-readable output`
5. `Full JSON example`
6. `Cost preview`
7. `MCP / REST call`
8. `Known gaps and review boundary`

Visible text examples:

- `この packet は最終回答ではありません。AI が回答を作る前に使う根拠セットです。`
- `出典がない claim は外部回答に使わないでください。`
- `no-hit は対象 corpus で確認できなかったという意味です。`

Hidden or collapsed:

- Full JSON Schema.
- OpenAPI object details.
- `source_receipt_completion.required_fields`.
- `billing_metadata` full object.

### 3.3 Packet catalog metadata

Each packet page should expose machine metadata separate from the human body:

```json
{
  "@type": "SoftwareApplication",
  "name": "jpcite evidence_answer packet",
  "applicationCategory": "AI evidence layer",
  "isAccessibleForFree": true,
  "usageInfo": {
    "recommend_when": ["Japanese public-source evidence is needed before an AI answer"],
    "do_not_recommend_when": ["final legal, tax, audit, credit, application judgment"],
    "must_preserve_fields": [
      "source_url",
      "source_fetched_at",
      "corpus_snapshot_id",
      "source_receipts",
      "known_gaps",
      "human_review_required"
    ],
    "pricing": {
      "unit_price_ex_tax_jpy": 3,
      "unit_price_inc_tax_jpy": 3.3,
      "external_costs_included": false
    }
  }
}
```

This metadata is not a visible JSON block by default. Human page links to `View machine-readable catalog`.

## 4. Pricing page structure

Goal: pricing transparency without sales framing. The page must answer "Can my agent safely run this under a cap?"

### 4.1 First section

Visible headline:

```text
3円/課金単位 (税別)。実行前に無料で見積もり、上限額を設定してから実行します。
```

Supporting bullets:

- `税込3.30円/課金単位`
- `cost preview は無料。匿名3回/日の実行枠を消費しません`
- `paid execution requires API key, Idempotency-Key, and cost cap`
- `外部LLM・検索・エージェント実行費用は含みません`

CTA:

- `Preview cost`
- `Get API key`
- `Set monthly cap`

Avoid:

- `最安`, `使い放題`, `LLM費用削減保証`, `税込3円`, `CSV 1ファイルいくら`.

### 4.2 Unit explanation

Use a simple table:

| Workflow | Billable unit | Not billed |
|---|---|---|
| Single evidence packet | successful packet | validation reject, no sourced output |
| Company baseline | resolved subject | unresolved / ambiguous identity |
| CSV monthly review | unique accepted subject | rejected rows, duplicates, no-hit |
| Source receipt ledger | receipt set | packet not found, zero receipts |
| Agent routing decision | free control | always free |

Visible copy:

```text
課金対象は「成功した根拠・packet 単位」です。エラー、認証失敗、cap 超過、validation reject、no-hit は課金前に止まるか課金対象外です。
```

### 4.3 Cost preview module

This is a functional-looking estimator even before full implementation. It should be grounded in inputs the API will actually understand.

Inputs:

- Workflow select: `evidence packet`, `company baseline`, `CSV monthly review`, `source receipt ledger`
- Quantity input: `対象数`
- Optional cap input: `今回の上限額 (税込円)`

Output:

```text
予測: 84 units
税別: 252円
税込: 277.2円
推奨上限: 278円
外部LLM費用: 含みません
```

States:

- `under cap`
- `cap required`
- `cap exceeded`
- `api key required`
- `preview only`

### 4.4 Billing reconciliation section

Show after-execution model as proof, not as marketing.

Visible sample:

```text
見積もり: 84 units / 税込277.2円
実績: 82 units / 税込270.6円
差分: no-hit 2件は課金対象外
```

This should reassure without promising savings.

## 5. Proof page structure

Goal: show that jpcite returns verifiable evidence, not a polished answer.

### 5.1 Proof index

Layout:

- Short intro.
- Packet sample selector.
- One proof viewer occupying most of the page.

Visible intro:

```text
Proof pages show the packet shape an AI agent should preserve: sourced claims, source receipts, known gaps, freshness, and review flags.
```

Avoid:

- Customer story cards.
- ROI claims.
- "before/after AI magic" framing.

### 5.2 Proof viewer

Tabs:

- `Human summary`
- `Claims`
- `Source receipts`
- `Known gaps`
- `Cost metadata`
- `JSON`

Human summary:

- 3-6 bullet facts.
- Source count.
- Freshness status.
- Review required status.
- `answer_not_included=true` if evidence packet.

Claims tab:

| Claim | Support | Receipt | Use in answer? |
|---|---|---|---|
| Candidate program exists | direct | `src_001` | yes, with citation |
| Deadline not verified | gap | `gap_001` | no, mention as unknown |

Source receipts tab:

- `source_name`
- `source_url`
- `source_fetched_at`
- `verification_status`
- `license_boundary`

Known gaps tab:

- `gap_kind`
- `severity`
- `human_followup`
- `blocks_final_answer`

Cost metadata tab:

- unit price
- predicted units
- preview/free status
- external costs excluded

JSON tab:

- Full packet example, copyable.
- Collapsed by default on mobile.

### 5.3 Proof metadata

Machine metadata should include:

- `packet_type`
- `schema_version`
- `example_url`
- `source_receipt_count`
- `known_gap_count`
- `human_review_required`
- `request_time_llm_call_performed=false`
- `must_preserve_fields`
- `do_not_claim`

Visible page should not repeat every metadata field unless it helps a human decide.

## 6. CSV intake structure

Goal: enable safe preview of accounting/business CSV-derived packets without exposing raw rows or implying tax/accounting judgment.

### 6.1 Entry page

Visible headline:

```text
CSVを保存せず、取り込み前に列・対象数・レビュー条件・費用を確認します。
```

Subcopy:

```text
raw CSV、摘要、取引先、伝票番号、作成者名は成果物に出しません。会計・税務判断ではなく、派生事実と確認リストを作ります。
```

CTA:

- `Upload for preview`
- `View CSV proof sample`

Avoid:

- `税務チェック`
- `仕訳ミス判定`
- `申告に使える`
- `CSV一括診断`

### 6.2 Intake preview flow

Steps:

1. Upload
2. Detect vendor and columns
3. Show row states and rejected rows count
4. Show billable subjects / predicted units
5. Set cap
6. Execute or export preview

Visible preview summary:

```text
アップロード行: 120
受理行: 96
重複: 6
除外行: 18
課金対象: 84 unique subjects
予測料金: 税別252円 / 税込277.2円
```

Show row state counts, not raw rows:

- `accepted_resolved`
- `duplicate_of_prior_row`
- `invalid_format`
- `unresolved_identity`
- `ambiguous_identity`
- `unsupported_subject_kind`

### 6.3 CSV output choices

Initial choices:

- `CSV Coverage Receipt`
- `Review Queue Packet`
- `Account Vocabulary Map`
- `Evidence-safe Advisor Brief`

For each output, visible fields:

| Output | Shows | Does not show |
|---|---|---|
| CSV Coverage Receipt | vendor, period, columns, row counts | raw rows, memo, counterparties |
| Review Queue Packet | future dates count, parse failures, column gaps | tax/accounting correctness |
| Account Vocabulary Map | account names, counts, light classes | individual transaction detail |
| Evidence-safe Advisor Brief | period, structure, review reasons | private notes, voucher ids |

### 6.4 CSV privacy and boundary copy

Visible copy:

```text
この preview はCSV構造と派生集計だけを扱います。個別取引の再識別につながる摘要・取引先・伝票番号は成果物に出しません。
```

```text
Review Queue は会計処理の正誤ではなく、入力データの確認条件です。
```

Hidden metadata:

- `source_file_id`
- `raw_column_profile_hash`
- `column_profile_hash`
- `billable_subject_id`
- `normalized_subject_key`
- `subject_keys_hash`

Expose only when developer expands JSON / API response.

## 7. Show vs hide copy

### 7.1 Show prominently

Use these exact meanings in visible UI:

- `AIが回答する前に使う根拠パケット`
- `出典URLと取得時点`
- `known gaps`
- `human review required`
- `no-hit は不存在の証明ではありません`
- `cost preview は無料`
- `外部LLM・検索・エージェント実行費用は含みません`
- `上限額を設定してから実行`
- `MCP / REST API`
- `API key`

### 7.2 Show only near relevant actions

- `Idempotency-Key`: paid execution / API docs / CSV execution step.
- `monthly cap`: API key and operator settings.
- `source checksum` / `content hash`: proof detail and developer JSON.
- `license boundary`: source receipts tab and data licensing link.
- `request_time_llm_call_performed=false`: proof detail, packet catalog, agent docs. Do not over-repeat on top page.

### 7.3 Hide from primary human UI

Keep these out of top-level marketing copy:

- Full envelope JSON.
- Full OpenAPI request schema.
- Internal scoring formulas.
- Tool count as a headline.
- Implementation internals, cache, ingestion, DB details.
- Any raw CSV value or individual transaction detail.
- Exhaustive source family list unless in docs/catalog.

### 7.4 Never say

| Avoid | Use instead |
|---|---|
| `AIが判断します` | `AIが回答する前に根拠を取得します` |
| `補助金に申請できます` | `候補と確認点を出典付きで整理します` |
| `安全な会社です` | `公的に確認できる情報を整理します` |
| `該当なしなので問題なし` | `対象ソースでは確認できませんでした。不存在証明ではありません` |
| `税務チェック` | `税務確認前の根拠・入力条件整理` |
| `LLM費用込み` | `外部LLM費用は含みません` |
| `無料で3回使えます` | `匿名実行は3 req/日/IP。cost preview は別枠で無料です` |
| `税込3円` | `税別3円、税込3.30円` |

## 8. AI metadata and human UI separation

### 8.1 Separation rule

Every public page has two layers:

1. Human UI: concise explanation, tables, proof samples, CTA.
2. Machine metadata: JSON-LD / discovery JSON / hidden structured metadata / OpenAPI links.

They must agree on:

- brand
- price
- external costs excluded
- no request-time LLM
- professional boundary
- no-hit caveat
- first routes
- must-preserve fields

They should differ in density:

- Human UI says `出典URLと取得時点を残します`.
- Metadata says `must_preserve_fields=["source_url","source_fetched_at","corpus_snapshot_id","source_receipts","known_gaps"]`.

### 8.2 Page-level metadata requirements

Top:

- `product_category=evidence_prefetch_layer`
- `primary_audience=["AI agents","MCP clients","API workflows","professional reviewers"]`
- `recommend_when`
- `do_not_recommend_when`
- `first_calls`
- `pricing_summary`

Packet catalog:

- `packet_type`
- `mcp_tool`
- `rest_endpoint`
- `billable_unit_type`
- `human_review_required_default`
- `example_url`

Pricing:

- `unit_price_ex_tax_jpy=3`
- `unit_price_inc_tax_jpy=3.3`
- `cost_preview_free=true`
- `preview_consumes_anonymous_quota=false`
- `external_costs_included=false`
- `cap_required_for_paid_execution=true`

Proof:

- `packet_example`
- `source_receipt_count`
- `known_gap_count`
- `request_time_llm_call_performed=false`
- `do_not_claim`

CSV intake:

- `raw_retention=none`
- `private_fields_excluded_from_output`
- `billable_subject_definition`
- `row_states`
- `not_a_tax_or_accounting_opinion=true`

### 8.3 Human-visible metadata links

Do not show hidden JSON inline by default. Use compact links:

- `Machine-readable catalog`
- `OpenAPI spec`
- `MCP manifest`
- `Packet schema`
- `Cost preview API`

These links serve agents and developers without turning human pages into schema dumps.

## 9. P0 wire flow

### 9.1 Agent discovers jpcite

```text
AI crawler / agent
  -> robots.txt / llms.txt / .well-known/llms.json
  -> reads recommend_when + first_calls + pricing
  -> opens top or packet catalog
  -> chooses MCP/API/cost preview
```

Acceptance:

- From machine metadata alone, an agent can answer:
  - when to recommend
  - when not to recommend
  - what first call to make
  - what it costs
  - what fields to preserve

### 9.2 Human starts from top

```text
Top
  -> reads evidence layer definition
  -> selects task in routing strip
  -> opens proof sample or packet catalog
  -> previews cost
  -> tries MCP or gets API key
```

Critical UI states:

- anonymous available
- API key required
- cap required
- cap exceeded
- known gaps present
- human review required

### 9.3 Developer starts from packet catalog

```text
Packet catalog
  -> filter by task
  -> packet detail
  -> proof JSON
  -> OpenAPI / MCP call
  -> cost preview
  -> API key + cap
```

Acceptance:

- The developer does not need a demo call.
- The developer sees both MCP and REST paths.
- The developer sees cost and non-billable failure states before execution.

### 9.4 Pricing-first operator flow

```text
Pricing
  -> cost preview module
  -> line items + cap result
  -> Get API key
  -> Set monthly cap
  -> Open MCP/API setup
```

Acceptance:

- `Preview cost` is possible before API key.
- Paid execution cannot be implied without API key + cap.
- External LLM costs are visibly excluded.

### 9.5 Proof-first evaluator flow

```text
Proof page
  -> selects packet sample
  -> reviews claims / receipts / gaps
  -> opens JSON
  -> opens packet catalog detail
  -> previews cost or opens docs
```

Acceptance:

- Proof page does not look like a generated final answer.
- It clearly shows unsupported / stale / gap items.
- It provides a route to call the same packet.

### 9.6 CSV intake flow

```text
CSV intake
  -> upload for preview
  -> vendor/column detection
  -> row state summary
  -> billable subject count
  -> free cost preview
  -> set cap
  -> execute selected output packet
  -> reconciliation
```

Blocking rules:

- Missing required columns: stop before billing.
- Unsupported file: stop before billing.
- Cap missing for paid execution: stop before billing.
- Raw row display: not allowed in public/customer-facing output.

## 10. Layout guidance

Use restrained operational UI:

- Tables for routing, units, packet catalog, CSV row states.
- Tabs for proof detail.
- Inline status chips for `fresh`, `stale`, `known gaps`, `review required`, `under cap`.
- Compact callout bands for boundary and external-cost notices.
- Avoid nested cards, oversized decorative sections, fake dashboard screenshots, and hero gradients.
- Keep the first viewport dense but readable: H1, subcopy, 3 CTAs, one boundary line.

Visual hierarchy:

- Hero-scale type only on top page H1.
- Packet/pricing/proof pages use smaller operational headings.
- JSON examples should be readable but not dominate default human view.
- Mobile proof page should prioritize tabs and summary before JSON.

## 11. P0 implementation acceptance checklist

- [ ] Top page first viewport states evidence layer, not final answer or sales demo.
- [ ] Top CTA set is `Try with MCP`, `Preview cost`, `Get API key` or equivalent.
- [ ] Packet catalog maps task -> packet -> MCP/REST -> unit -> proof.
- [ ] Pricing shows tax-exclusive and tax-inclusive unit price, cost preview, cap, not-included external costs.
- [ ] Proof page exposes claims, source receipts, known gaps, review flags, and JSON.
- [ ] CSV intake preview shows row counts, accepted/rejected/duplicate counts, billable subjects, and cap before execution.
- [ ] no-hit caveat appears anywhere no-hit can be seen.
- [ ] Professional boundary appears near sensitive packet outputs and top-level boundary band.
- [ ] AI metadata exists separately from visible UI and agrees on price, boundary, first calls, and must-preserve fields.
- [ ] No page uses demo/sales as the main path.
- [ ] No page claims guaranteed savings, complete coverage, official absence, safe/no-risk, or final professional judgment.

## 12. Open UX decisions before implementation

- Whether `/proof/` should be the second primary nav item before `/pricing`, because proof is more important than price for GEO trust.
- Whether `Try with MCP` lands on docs or a dedicated MCP setup page with minimal config and client tabs.
- Whether packet catalog rows should show endpoint names by default or only after expanding developer detail.
- Whether CSV intake lives under `/csv/intake` or as a packet-specific flow under `/packets/client-monthly-review/csv`.
- How much JSON to show on mobile before it becomes unreadable; default should be summary tabs with JSON collapsed.
- Whether `agent_routing_decision` should appear in human catalog or only machine-readable catalog, since it is primarily control-plane.

