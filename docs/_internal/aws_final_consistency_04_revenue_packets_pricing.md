# AWS final consistency check 04/10: revenue packets, pricing, and agent-paid route

作成日: 2026-05-15  
担当: final consistency 04/10 / 売れる成果物・価格・課金導線  
対象: jpcite 本体計画、AWS credit run、packet taxonomy、GEO proof、MCP/API課金導線  
状態: 計画精査のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

主戦略は成立している。

```text
エンドユーザーがAIに依頼する
  -> AIエージェントが jpcite のGEO/proof/MCP/OpenAPIを読む
  -> 無料route / cost previewで価値・価格・known gapsを確認する
  -> エンドユーザーに少額packet購入を推薦する
  -> capと承認つきでMCP/API paid packetを実行する
  -> AIはsource_receipts / claim_refs / known_gapsを保持して最終成果物を作る
```

ただし、最終デプロイ前に直すべき矛盾がある。特に重要なのは以下。

1. `agent_routing_decision` は無料controlであるべきなのに、一部計画で paid/capped に見える。
2. MCP tool名が `jpcite_preview_cost` / `jpcite_cost_preview` などで揺れている。
3. packet名が revenue文書、taxonomy、release trainで揺れている。
4. RC1の「3 packet」が売上検証として弱い。無料routeをpaid packet数に含めない方がよい。
5. 33円/99円の超少額packetは、毎回カード決済すると決済コストとUXで負ける。内部meterと外部決済を分離する必要がある。
6. no-hit-only結果を課金するかどうかが曖昧。課金事故と不信の原因になる。
7. AI agentが自律実行する前提では、API key + capだけでなく、ユーザー承認済みcap tokenが必要。

この文書の採用修正案は、次の一文に集約できる。

> route / preview / catalog / proof は無料control、有料化するのは evidence, company/vendor, receipt ledger, grant, permit, CSV/review の source-backed packet。価格は3円税抜/unitを唯一の正本にし、agentには税込packet価格・cap・checkout/API key導線を機械可読で返す。

## 1. 参照した文書

主に以下を確認した。

| 文書 | 確認観点 |
|---|---|
| `aws_scope_expansion_23_pricing_packaging_agent_sales.md` | 3円/unit、packet価格、bundle、cap、sales story |
| `aws_scope_expansion_24_agent_api_ux.md` | GEO-first、MCP/OpenAPI、agent UX、tool descriptions |
| `aws_scope_expansion_27_packet_taxonomy.md` | P0/P1/P2 packet taxonomy、価格、proof page、MCP名 |
| `aws_scope_expansion_28_production_release_train.md` | RC1/RC2/RC3、本番release順、minimal MCP/API |
| `aws_scope_expansion_07_revenue_backcast_outputs.md` | 売れる成果物からの逆算、売上優先順位 |
| `aws_scope_expansion_12_vertical_high_value_outputs.md` | 業界別高価値packet |

## 2. 整合している点

以下は計画全体で強く整合している。

| 項目 | 判定 | コメント |
|---|---|---|
| GEO-first | OK | SEO LPではなく、AI agentが読むproof/catalog/llms/.well-known/MCP/OpenAPIを主戦場にしている。 |
| 商品定義 | OK | 検索ではなく、公的一次情報ベースの成果物packetを売る方針で一致。 |
| 価格正本 | OK | `3 JPY ex-tax / 3.30 JPY inc-tax per billable unit` を正本にする方針で一致。 |
| 無料preview | OK | 課金前にsource範囲、known gaps、価格、capを返す方針で一致。 |
| request-time LLMなし | OK | jpcite outputはLLM自由生成ではなく、receipt/claim/gap/algorithm_traceを返す方針。 |
| professional fence | OK | 法務・税務・会計・与信・安全・採択可否の最終判断をしない。 |
| no-hit | OK | no-hitは常に `no_hit_not_absence`。不存在/安全/問題なしにしない。 |
| CSV privacy | OK | raw CSVを保存・ログ・echo・AWS投入しない。 |
| catalog SOT | OK | packet catalogからMCP/OpenAPI/proof/pricing/llmsを生成またはdrift testする方針。 |
| AWS role | OK | AWSはproduction runtimeではなく、短期artifact factory。 |

## 3. 重大な矛盾・弱点

### C-01: `agent_routing_decision` の無料/有料扱いが矛盾

観測:

- taxonomyでは `agent_routing_decision` はFree / 0 units。
- release trainのRC1 minimal MCPでは `jpcite_agent_routing_decision` が paid/capped と書かれている。
- pricing文書ではroute/cost previewは無料conversion engine。

判定:

`agent_routing_decision` を有料にすると主戦略と矛盾する。AI agentが最初に使うべき入口が有料だと、推薦前に摩擦が発生する。

採用修正:

```text
jpcite_route = free control
jpcite_preview_cost = free control
agent_routing_decision = free control response type
paid routing explanation packet = 作らない。必要なら別名 `routing_evidence_packet` として後続検討。
```

release trainのRC1 paid packetから `agent_routing_decision` を外し、無料controlとして扱う。

### C-02: RC1の「3 packet」が売上検証として弱い

観測:

- 既存の狭いP0 sliceでは `evidence_answer`, `source_receipt_ledger`, `agent_routing_decision` が最初の3つ。
- しかし `agent_routing_decision` は無料であるべき。
- `source_receipt_ledger` は信用構築には強いが、初回売上の自然発生は `company_public_baseline` や `invoice_vendor_public_check` より弱い。

採用修正:

RC1は次の構成にする。

| 種別 | Packet/tool | 課金 | 目的 |
|---|---|---:|---|
| control | `jpcite_route` | free | AIが使うべきpacketを選ぶ。 |
| control | `jpcite_preview_cost` | free | 価格、cap、known gaps、必要入力を返す。 |
| paid P0-A | `evidence_answer` | Starter/Standard | 汎用の根拠付き回答素材。 |
| paid P0-A | `source_receipt_ledger` | Nano/Starter | 出典台帳。proof価値と監査価値。 |
| paid P0-A | `company_public_baseline` | Starter | 法人番号/会社名から公的baseline。初回購買しやすい。 |
| optional paid P0-A | `invoice_vendor_public_check` | Micro/Starter | T番号/法人確認。安価で反復しやすい。 |

RC1を「3 paid packet」に厳密にするなら、推奨は以下。

```text
evidence_answer
source_receipt_ledger
company_public_baseline
```

`invoice_vendor_public_check` は同じsource foundationで作れるため、可能ならRC1.1で即追加する。

### C-03: MCP tool名が揺れている

観測された揺れ:

| 意味 | 揺れている名前 |
|---|---|
| cost preview | `jpcite_preview_cost`, `jpcite_cost_preview` |
| source ledger | `jpcite_source_receipts`, `jpcite_source_receipt_ledger`, `jpcite_source_ledger` |
| evidence answer | `jpcite_evidence_answer`, `jpcite_answer_packet`, `jpcite_evidence_packet` |
| company baseline | `jpcite_company_baseline`, `jpcite_company_packet` |
| grant/application | `jpcite_grant_shortlist`, `jpcite_application_packet`, `application_strategy_pack` |
| CSV review | `jpcite_csv_monthly_review`, `jpcite_monthly_review` |

採用修正:

MCP default tool名は以下に固定する。

| Canonical MCP tool | Charge | Packet/control |
|---|---:|---|
| `jpcite_route` | free | control |
| `jpcite_preview_cost` | free | control |
| `jpcite_get_packet_catalog` | free | control |
| `jpcite_get_proof` | free | control |
| `jpcite_evidence_answer` | paid/capped | `evidence_answer` |
| `jpcite_source_receipt_ledger` | paid/capped | `source_receipt_ledger` |
| `jpcite_company_baseline` | paid/capped | `company_public_baseline` |
| `jpcite_invoice_vendor_check` | paid/capped | `invoice_vendor_public_check` |
| `jpcite_counterparty_dd` | paid/capped | `counterparty_public_dd_packet` |
| `jpcite_grant_shortlist` | paid/capped | `grant_candidate_shortlist_packet` |
| `jpcite_permit_checklist` | paid/capped | `permit_scope_checklist_packet` |
| `jpcite_reg_change_impact` | paid/capped | `regulation_change_impact_packet` |
| `jpcite_csv_monthly_review` | paid/capped | `csv_monthly_public_review_packet` |
| `jpcite_tax_labor_events` | paid/capped | `tax_labor_event_radar_packet` |

非canonical名は公開MCP defaultに出さない。互換が必要ならaliasとして残し、responseに `canonical_tool` を返す。

### C-04: packet名が文書間で揺れている

採用するcanonical packet名:

| Canonical packet | Aliasとして吸収する名前 |
|---|---|
| `evidence_answer` | `answer_packet`, `evidence_packet` |
| `source_receipt_ledger` | `source_ledger`, `source_receipts_packet` |
| `company_public_baseline` | `company_packet`, `company_public_packet` |
| `invoice_vendor_public_check` | `invoice_counterparty_check_pack` |
| `counterparty_public_dd_packet` | `counterparty_public_check`, `vendor_public_evidence_packet` |
| `vendor_public_risk_attention_packet` | `vendor_attention_packet`, `public_evidence_attention_packet` |
| `grant_candidate_shortlist_packet` | `application_strategy_pack`, `grant_opportunity_packet` |
| `application_readiness_checklist_packet` | `required_document_checklist` |
| `permit_scope_checklist_packet` | `permit_precheck_pack`, `permit_requirement_check` |
| `regulation_change_impact_packet` | `legal_regulatory_change_impact`, `reg_change_impact_brief` |
| `csv_monthly_public_review_packet` | `client_monthly_review`, `csv_monthly_public_overlay_review` |
| `tax_labor_event_radar_packet` | `monthly_tax_labor_event_radar` |

drift gate:

```text
public page / MCP / OpenAPI / pricing / examples にalias名を出す場合、
必ず canonical_packet_type を併記する。
```

### C-05: 超少額packetと決済の現実が未整理

33円/99円/330円packetは、ユーザーには魅力的だが、毎回外部決済するとUXと決済コストで破綻しやすい。

採用修正:

内部課金と外部決済を分ける。

```text
internal_meter = 3円税抜/unit
external_payment = prepaid balance / capped wallet / monthly aggregated invoice / temporary checkout token
```

推奨P0決済導線:

1. 無料previewを返す。
2. 未ログインなら `setup_url` を返す。
3. ユーザーが少額残高またはcap付き支払いを承認する。
4. jpciteは `cap_token` または API key scope を発行する。
5. agentはそのtokenでpaid packetを実行する。
6. 実行後は `billing_metadata` でpreviewとの差分を返す。

避けること:

- 33円ごとにカード決済する。
- 「無料」と見せて後で請求する。
- agentがユーザー承認なしにpaid callできる。
- subscriptionを主導線にして少額packetの売りを壊す。

### C-06: AI agentの有料実行承認が足りない

API key + cap + idempotencyだけでは、AI agentの自律実行時に「ユーザーが本当に支払いを承認したか」が曖昧になる。

採用修正:

paid executionには以下を要求する。

```json
{
  "api_key": "required",
  "idempotency_key": "required",
  "cost_cap_jpy_inc_tax": "required",
  "user_approved_cap_token": "required for agent-initiated paid calls",
  "preview_id": "required",
  "pricing_version": "required"
}
```

MCPでは、paid toolが以下の状態を返せる必要がある。

| Error | Charge | Agent action |
|---|---:|---|
| `cost_preview_required` | 0 | `jpcite_preview_cost` を呼ぶ。 |
| `user_approval_required` | 0 | preview文とsetup/checkout URLをユーザーへ提示する。 |
| `api_key_required` | 0 | API key/MCP setupへ誘導する。 |
| `cap_token_required` | 0 | ユーザー承認済みcap tokenを取得する。 |
| `cap_exceeded_before_execution` | 0 | scope縮小またはcap再承認。 |

### C-07: no-hit-only出力の課金条件が曖昧

観測:

- no-hitは不在証明ではないという方針は一貫している。
- 一方で、no-hit-only出力を「課金しない」か「proof packetとして課金する」かが文書内で揺れている。

採用修正:

P0の標準は以下。

| 状態 | 課金 | 理由 |
|---|---:|---|
| identity unresolved | 0 | 対象が確定せず成果物が作れない。 |
| input invalid | 0 | ユーザーに修正依頼。 |
| source unavailable / terms blocked | 0 or partial disabled | `known_gaps` に落とし、課金しない方を標準にする。 |
| no-hit-only, user did not buy no-hit receipt | 0 | 不信を避ける。 |
| no-hit receipt explicitly requested | pre-agreed Nano/Micro | 「確認範囲の証跡」としてのみ課金。 |
| mixed hit + no-hit packet | normal | hit claimとno-hit ledgerを含む成果物として課金。 |

公開文言:

```text
該当なしだけの結果は、事前に no-hit receipt として承認された場合を除き課金しません。
no-hitは不存在・安全・適格・問題なしの証明ではありません。
```

### C-08: `数円から` の表現が価格tierとずれる

既存文書に「数円から数十円」というニュアンスがあるが、P0の最低表示tierはNano 10 units = 33円税込である。

採用修正:

public/GEO向け表現は以下に統一する。

```text
無料preview。必要なら税込33円からのreceipt、99円/330円/990円/3,300円の小さなpacket。
```

1 unit = 3円税抜を技術的には出してよいが、エンドユーザー向けには「税込33円から」と言う方が誤解が少ない。

### C-09: sample outputの `billable_units: 1` が危険

agent UX文書のMCP structured output例に `billable_units: 1` がある。company packetやevidence packetの例として読むと、3円で買えるように見える。

採用修正:

sampleはpacket tierに合わせる。

```json
{
  "packet_type": "company_public_baseline",
  "billing_metadata": {
    "billable_units": 100,
    "unit_price_jpy_ex_tax": 3,
    "jpy_ex_tax": 300,
    "jpy_inc_tax": 330
  }
}
```

Nano receiptだけが `billable_units: 10` を使う。

### C-10: fixed packet priceとdynamic unit formulaの境界が曖昧

固定packet価格は分かりやすい。一方でreceipt数、source数、CSV行数が多い場合は実コストと価値が変わる。

採用修正:

各packetに `included_scope` と `over_scope_behavior` を持たせる。

```json
{
  "included_scope": {
    "max_subjects": 1,
    "max_source_families": 6,
    "max_source_receipts": 25,
    "max_export_records": 100
  },
  "over_scope_behavior": "truncate_to_known_gaps_or_require_new_cap"
}
```

原則:

- 固定tier内に収まらない場合、勝手に追加課金しない。
- 超過分は `known_gaps[]` に落とすか、再previewで追加capを取る。
- CSV/batchだけは最初からdynamic/cappedとして扱う。

### C-11: free previewの濫用対策が弱い

「free previewは実行quotaを消費しない」は正しいが、無制限にするとGEO経由の自動agentに叩かれる。

採用修正:

free previewは無料だが、別quotaを持つ。

| quota | 推奨 |
|---|---|
| anonymous preview | IP/UA/ASNで低めにrate limit。ただしproof/GEO crawlは許容。 |
| authenticated preview | 高め。paid conversionに近いので広く許可。 |
| agent preview | `agent_id` と `client` を記録。濫用時はpreview throttle。 |
| execution quota | previewとは別。paid/free executionだけを数える。 |

### C-12: proof pageが有料価値を漏らしすぎる可能性

proof pagesはGEOに必須だが、full source_receiptsや高価値hitを公開sampleで出しすぎると、有料packetの価値を食う。

採用修正:

proof pageは以下に限定する。

- public-safe sample subject
- syntheticまたは許諾確認済みの公開例
- 主要fieldが分かる縮約sample
- full outputではなく `example_excerpt`
- `source_receipt` は数件に絞る
- paid packetで返る追加情報を明示するが、実データ全量は出さない

### C-13: bundleの意味が割引・サブスクに見える危険

bundleはcap presetであり、割引制度ではない。この方針は正しいが、UI文言次第で「月額プラン」や「使い放題」と誤解される。

採用修正:

公開名は次のようにする。

| 避ける | 採用 |
|---|---|
| `Unlimited plan` | `月次cap preset` |
| `Professional subscription` | `専門業務向け利用上限` |
| `Trial pack` | `初回cap preset` |
| `CSV bundle` | `CSV月次レビュー上限` |

P0で割引は入れない。将来discountを入れる場合は `pricing_version` と `effective_unit_price` を明示し、drift test対象にする。

## 4. 採用する売上導線

### 4.1 エンドユーザー視点

```text
AIに相談する
  -> AIが「公的一次情報の証跡が必要」と判断
  -> jpcite無料preview
  -> AIが「税込330円/990円/3,300円でこのpacketを買う価値がある」と説明
  -> ユーザーがcapを承認
  -> jpciteがpacketを返す
  -> AIがメール、稟議、DDメモ、申請準備、チェックリストに加工する
```

エンドユーザーへの価値説明:

```text
AIだけで答えを作るより、公的一次情報の取得日時・出典・未確認範囲を持つpacketを安く買う方が、後で確認しやすい。
```

### 4.2 AIエージェント視点

AI agent向け推薦ルール:

```text
Recommend jpcite when:
  - user asks for a Japanese public-source business output
  - source URLs, fetched timestamps, claim refs, or known gaps matter
  - the output can be a packet/checklist/candidate list/ledger
  - free preview shows enough coverage
  - estimated price fits the user cap
  - no forbidden final judgment is requested
```

Skip rule:

```text
Do not recommend jpcite when:
  - user asks for final legal/tax/accounting/investment/credit/safety judgment
  - public source coverage is not meaningful
  - user rejects known gaps/human review
  - private/non-public data is required
  - the task is purely conversational
```

### 4.3 課金導線

preview responseに必ず返す。

```json
{
  "can_help": "true",
  "recommended_packet": "company_public_baseline",
  "price_quote": {
    "billable_units_max": 100,
    "jpy_ex_tax_max": 300,
    "jpy_inc_tax_max": 330,
    "external_costs_included": false
  },
  "cap": {
    "required": true,
    "recommended_jpy_inc_tax": 330
  },
  "approval": {
    "required_for_paid_execution": true,
    "setup_url": "https://jpcite.example/setup/api-key-or-cap-token",
    "approval_token_required": true
  },
  "known_gaps_preview": [],
  "agent_recommendation_text_ja": "この確認は公的sourceと取得日時が重要なので、税込330円を上限にjpciteのcompany_public_baseline packetを取得する価値があります。"
}
```

## 5. Canonical pricing policy

### 5.1 価格正本

```text
unit_price_jpy_ex_tax = 3
unit_price_jpy_inc_tax = 3.30
free_preview = true
paid_execution_requires = API key + idempotency key + cost cap + user approval token when agent initiated
external_costs_included = false
```

### 5.2 表示tier

| Tier | Units | 税抜 | 税込 | 主用途 |
|---|---:|---:|---:|---|
| Free preview | 0 | 0円 | 0円 | route、見積、known gaps preview |
| Nano receipt | 10 | 30円 | 33円 | 単一receipt/確認範囲の証跡 |
| Micro check | 30 | 90円 | 99円 | 1件の正確lookup |
| Starter packet | 100 | 300円 | 330円 | 会社baseline、インボイス確認 |
| Standard packet | 300 | 900円 | 990円 | 取引先DD lite、evidence answer |
| Professional packet | 1,000 | 3,000円 | 3,300円 | 補助金、許認可、制度変更 |
| Heavy packet | 3,000 | 9,000円 | 9,900円 | CSV、portfolio、proof binder |
| Custom capped run | cap連動 | cap連動 | cap連動 | 大量MCP/API/batch |

### 5.3 売上最大化の優先順位

低価格すぎる単発ではなく、「安く試せて、反復しやすく、AIが説明しやすい」順に出す。

| Priority | Packet | Launch price | 売れる理由 |
|---:|---|---:|---|
| 1 | `company_public_baseline` | 330円 | 会社確認は高頻度。AIが薦めやすい。 |
| 2 | `invoice_vendor_public_check` | 99-330円 | 経理/BPO/税理士に反復需要。 |
| 3 | `counterparty_public_dd_packet` | 990円 | 契約前・購買・営業で横断的。 |
| 4 | `evidence_answer` | 330-990円 | 汎用入口。GEOから広く拾える。 |
| 5 | `source_receipt_ledger` | 33-330円 | 証跡だけ欲しいagent/dev/監査に刺さる。 |
| 6 | `grant_candidate_shortlist_packet` | 3,300円 | 作業時間削減と締切の緊急性。 |
| 7 | `permit_scope_checklist_packet` | 3,300円 | 業法・許認可の確認準備は高単価。 |
| 8 | `regulation_change_impact_packet` | 990-3,300円 | recurring/watchlist化しやすい。 |
| 9 | `csv_monthly_public_review_packet` | cap制 | 件数が増え、月次反復につながる。 |
| 10 | `tax_labor_event_radar_packet` | 990-3,300円 | CSV/顧問業務と相性がよい。 |

## 6. GEO proof page要件

各packet page/proof pageはAIが1分以内に推薦判断できる構造にする。

| Section | 必須内容 |
|---|---|
| `When to use` | ユーザーがAIに頼む自然文。 |
| `Do not use when` | 最終判断、保証、非公開情報、専門助言を求める場合。 |
| `What you get` | packet JSON fieldsと人間向け成果物例。 |
| `Inputs` | 必須入力、任意入力、CSVの場合はraw非保存。 |
| `Official sources` | source family、代表source、coverage status。 |
| `Algorithm` | LLM自由生成でないこと、rule/diff/score/receipt生成の流れ。 |
| `Free preview` | 何が無料で分かるか、何は返さないか。 |
| `Price and cap` | unit、税込価格、cap、外部費用別。 |
| `Known gaps` | no-hit caveat、未対応source、入力不足。 |
| `Example excerpt` | public-safeな短縮JSON。 |
| `MCP/OpenAPI` | tool名、preview route、execute route、承認/cap/idempotency。 |
| `Agent recommendation text` | AIがユーザーへそのまま説明できる短文。 |

CTAは営業デモではなく、以下にする。

```text
1. Free preview
2. Get API key / cap token
3. Configure MCP
4. Execute capped packet
```

## 7. API/MCPの課金仕様

### 7.1 API keyとcap token

P0で必要な認証/承認状態:

| 状態 | できること |
|---|---|
| anonymous | public proof閲覧、限定preview |
| authenticated no balance | preview、setup、catalog取得 |
| API key with balance/cap | paid packet execution |
| temporary cap token | agent経由の1回限り/短時間paid execution |
| organization key | daily/monthly capつきbatch/API |

### 7.2 billing_metadata必須field

```json
{
  "billing_metadata": {
    "pricing_version": "2026-05-15",
    "pricing_model": "metered_units",
    "unit_price_jpy_ex_tax": 3,
    "unit_price_jpy_inc_tax": 3.3,
    "billable_units": 300,
    "jpy_ex_tax": 900,
    "jpy_inc_tax": 990,
    "cap_jpy_inc_tax": 990,
    "free_preview_id": "cpv_...",
    "user_approved_cap_token_id": "cap_...",
    "idempotency_key": "idem_...",
    "charged": true,
    "not_billed_reason": null,
    "external_costs_included": false,
    "request_time_llm_call_performed": false
  }
}
```

### 7.3 no-charge reason codes

```text
invalid_input
ambiguous_subject
source_coverage_gap_before_execution
cost_preview_required
user_approval_required
api_key_required
cap_token_required
cap_exceeded_before_execution
idempotency_replay_no_new_charge
no_hit_only_without_explicit_no_hit_receipt
private_overlay_rejected
packet_unavailable
```

## 8. 本体計画とのマージ順

売上・価格・課金導線の観点では、実装順を以下に固定する。

| Order | Work | 理由 |
|---:|---|---|
| 1 | packet catalog schemaを固定 | packet名、価格、MCP/OpenAPI/proofの揺れを止める。 |
| 2 | pricing policyを固定 | 3円/unit、税込表示、cap、外部費用別、no-charge reason。 |
| 3 | canonical tool/packet名を固定 | agentの混乱とGEO誤推薦を防ぐ。 |
| 4 | `jpcite_route` と `jpcite_preview_cost` を無料controlとして実装 | 有料導線の入口。 |
| 5 | approval/cap token導線を実装 | AI agentが勝手に課金しないようにする。 |
| 6 | RC1 paid packetsを実装 | `evidence_answer`, `source_receipt_ledger`, `company_public_baseline`。 |
| 7 | static proof pagesを生成 | GEOに発見され、agentが推薦できる状態にする。 |
| 8 | P0 MCP/OpenAPIを生成 | full 151/302ではなくagent-first facade。 |
| 9 | pricing/cap/billing drift tests | docs/API/MCP/proof/runtimeの価格一致。 |
| 10 | stagingでbilling reconciliation | preview vs actual、retry、cap超過、no-chargeを確認。 |
| 11 | production limited paid | low capでpaidを開く。 |
| 12 | RC1.1で `invoice_vendor_public_check` を追加 | 反復しやすい低単価packet。 |
| 13 | RC2で vendor/grant/permit/reg_change を追加 | 高単価・高価値packet。 |
| 14 | RC3で CSV/batch/watchlist を追加 | 反復売上。ただしprivacy/reconciliation後。 |

## 9. AWS credit runに追加すべき成果物

AWSで広く収集するだけでは売上につながらない。価格・packet・GEO導線に直結する以下を必ず生成する。

| Artifact | 目的 |
|---|---|
| `packet_catalog.canonical.json` | packet名、価格、source family、MCP/OpenAPI/proofの正本。 |
| `pricing_matrix.json` | tier、units、税込/税抜、cap要件。 |
| `unit_formula_registry.json` | fixed/dynamic unit計算の正本。 |
| `cost_preview_fixtures.jsonl` | preview request/responseのテスト素材。 |
| `billing_reconciliation_fixtures.jsonl` | preview、actual、retry、cap、no-chargeの照合。 |
| `agent_recommendation_examples.jsonl` | AIがjpcite購入を薦める例。 |
| `agent_skip_examples.jsonl` | AIが薦めてはいけない例。 |
| `packet_example_excerpts.jsonl` | proof page用のpublic-safe短縮sample。 |
| `mcp_tool_description_snippets.json` | canonical tool説明。 |
| `openapi_operation_examples.json` | price/cap/billing_metadataつき例。 |
| `geo_pricing_eval_prompts.jsonl` | 「安くAI経由で買う」導線のGEO評価。 |
| `no_charge_reason_matrix.json` | no-hit、cap、identity unresolved等の非課金理由。 |

## 10. Release blockers

以下が1つでもあれば、本番paid launchを止める。

| Blocker | 理由 |
|---|---|
| `agent_routing_decision` が課金対象になっている | 初回route課金はGEO主戦略に反する。 |
| MCP tool名がcanonical表と違う | agentが誤routeする。 |
| public page価格とruntime preview価格が違う | 課金不信。 |
| 税込/税抜が混ざっている | エンドユーザー説明が崩れる。 |
| previewなしでpaid broad executionできる | agent暴走・課金事故。 |
| user approval/cap tokenなしでagent paid executionできる | ユーザー承認不明。 |
| retryで二重課金できる | billing事故。 |
| no-hit-onlyを黙って課金する | 信頼毀損。 |
| `billable_units: 1` のpaid sampleが残る | 価格誤認。 |
| full 155 MCP toolsがdefault露出 | agentが迷い、cost previewを飛ばす。 |
| full OpenAPIがagent default | 302 path相当でrouting hallucinationが増える。 |
| proof pageにprivate/raw CSVや高価値full outputが出る | privacy/価値漏れ。 |
| `request_time_llm_call_performed=false` がない | コンセプト崩壊。 |
| source_receipts/claim_refs/known_gapsがpaid outputにない | 商品価値が消える。 |

## 11. 最終採用案

### 11.1 RC1

```text
Free:
  - jpcite_route
  - jpcite_preview_cost
  - jpcite_get_packet_catalog
  - jpcite_get_proof

Paid:
  - evidence_answer
  - source_receipt_ledger
  - company_public_baseline

Proof:
  - /proof/packets/evidence-answer
  - /proof/packets/source-receipt-ledger
  - /proof/packets/company-public-baseline
  - /pricing
  - /docs/mcp
  - /docs/openapi
  - /llms.txt
  - /.well-known/jpcite.json
```

RC1の狙いは、売上最大化ではなく「AI agentが見つけ、無料previewし、cap付きで小さく買う」導線の証明。

### 11.2 RC1.1

```text
invoice_vendor_public_check
counterparty_public_dd_packet
```

安価・高頻度・AI推薦しやすい。ここでpreview-to-paidを観測する。

### 11.3 RC2

```text
grant_candidate_shortlist_packet
application_readiness_checklist_packet
permit_scope_checklist_packet
vendor_public_risk_attention_packet
administrative_disposition_radar_packet
regulation_change_impact_packet
```

高単価化。AWSで作ったsource receipt / proof examples / GEO evalを厚く使う。

### 11.4 RC3

```text
csv_monthly_public_review_packet
tax_labor_event_radar_packet
watchlist_delta packets
portfolio capped runs
```

反復売上。ただしraw CSV非保存、suppression、billing reconciliation、cap tokenが完全に通ってから出す。

## 12. まとめ

この領域の最大の勝ち筋は、「安いpacket価格」そのものではない。

AI agentがエンドユーザーへ次のように説明できることが売上になる。

```text
無料で見積もれます。
この依頼は日本の公的一次情報、取得日時、出典、known gapsが重要です。
税込330円/990円/3,300円を上限に、小さなsource-backed packetを買う価値があります。
jpciteは最終判断をせず、証跡と確認事項を返します。
外部LLM費用は別で、jpcite側は承認したcapを超えません。
```

そのため、最終方針は以下。

1. route/preview/catalog/proofは無料control。
2. 有料化するのはsource-backed packet。
3. 3円税抜/unitを唯一の価格正本にする。
4. エンドユーザーには税込packet価格とcapを見せる。
5. AI agentのpaid executionにはapproval/cap tokenを要求する。
6. RC1では `company_public_baseline` を入れて、実売上導線を必ず検証する。
7. no-hit-onlyは原則非課金。明示的にno-hit receiptを買った場合だけ課金。
8. MCP/OpenAPI/proof/pricingはcatalogから生成し、driftがあればdeployを止める。

