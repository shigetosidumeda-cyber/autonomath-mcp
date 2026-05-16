# AWS final 12 review 10/12: smarter AI agent recommendation and GEO functions

作成日: 2026-05-15  
担当: 最終追加検証 10/12 / もっとスマートなAI agent推薦・GEO機能  
対象: jpcite本体計画、AWS credit run、agent recommendation、free preview、proof pages、llms/.well-known、MCP UX、cap/approval、GEO eval  
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。  
出力: このMarkdownのみ。

## 0. 結論

判定は **条件付きPASS**。

既存計画は、GEO-first、agent-safe OpenAPI、P0 MCP facade、proof pages、free preview、cap/approval、no-hit caveatまで揃っており、方向性は正しい。

ただし、さらにスマートにする余地がある。改善の主軸は「順番」ではなく、次の機能である。

> AI agentが、エンドユーザーに対して「買うべきか、買わないべきか、もっと安い選択肢は何か」を安全に説明できるdecision layerを作る。

採用すべき追加機能は以下。

1. `free_preview_decision_object` を価格見積ではなく購入判断オブジェクトにする。
2. `agent_recommendation_card` を全preview/packet/proof pageで正本化する。
3. proof pagesをLPではなく `agent_decision_page` として設計する。
4. agent-safe examplesを「成功例」だけでなく「買わない例」「安い代替例」「no-hit罠例」まで含める。
5. `llms.txt` / `.well-known` / MCP / OpenAPI / proof pagesをcatalog hashで一体化する。
6. MCP UXを「155 toolsから選ぶ」のではなく、route -> preview -> approval -> execute の4段階facadeにする。
7. `cheaper_option_explainer` を入れて、AIが高いpacketではなく十分に安いpacketを薦められるようにする。
8. GEO evalを単なる到達確認ではなく、agentが推薦文を正しく作れるかの継続評価にする。

最も重要な修正:

```text
cost preview = 見積API
```

では弱い。

```text
cost preview = agentがユーザーに購入可否を説明するためのdecision object
```

に変えるべきである。

## 1. 検証対象の前提

今回の正本前提:

- 主戦はSEOではなくGEO。
- `agent_routing_decision` は無料controlであり、有料packetではない。
- RC1 paidは `company_public_baseline`、`source_receipt_ledger`、`evidence_answer` を中心にする。
- `company_public_baseline` を初回購入CTAの主役にする。
- request-time LLMで事実を生成しない。
- no-hitは常に `no_hit_not_absence`。
- full OpenAPI / 既存155 MCP toolsはexpert面であり、初回agentにはP0 facadeを見せる。
- 全paid executionはpreview、cap、approval token、idempotencyを必須にする。

この前提は維持してよい。

## 2. 残っている機能上の弱点

### W-01: previewがまだ「価格見積」に寄りやすい

既存計画では、free previewをdecision objectにする方針が出ている。ただし実装時に単なる料金見積に縮む危険がある。

弱いpreview:

```json
{
  "estimated_units": 100,
  "estimated_price_jpy": 330,
  "cap_required": true
}
```

これではAI agentはエンドユーザーに推薦しにくい。

強いpreview:

```json
{
  "recommendation": "buy_packet",
  "why_buy": [
    "法人番号とインボイス公表情報を同時に確認できる",
    "source_receiptsとknown_gapsを保持した出力を返せる",
    "この依頼は無料検索だけでは証跡付き回答にしにくい"
  ],
  "cheapest_sufficient_option": {
    "packet_type": "company_public_baseline",
    "max_price_jpy_inc_tax": 330,
    "reason": "行政処分や許認可までは不要で、会社基礎確認だけで足りる可能性が高い"
  },
  "do_not_buy_if": [
    "最終的な信用判断や法的判断を求めている",
    "会社名や法人番号など最低限の入力がない"
  ]
}
```

agentが必要としているのは、金額だけではなく、購入理由、非購入理由、より安い選択肢、必要入力、限界である。

### W-02: `agent_recommendation_card` が全surfaceの必須fieldになっていない

既存文書では `agent_recommendation_card` が出ているが、すべてのpreview、proof page、MCP response、OpenAPI exampleで必須になっているとは限らない。

採用修正:

- free previewには必須。
- paid packet responseにも必須。
- proof page sidecarにも必須。
- MCP structured outputにも必須。
- OpenAPI examplesにも必須。
- `llms-full.txt` の代表例にも必須。

理由:

AI agentが最終的にユーザーへ伝える文章は、このcardから組み立てられるべきである。agentに自由作文させると、no-hit、cap、専門家確認、外部費用の表現がぶれる。

### W-03: proof pageが「証跡ページ」と「購入判断ページ」の中間で曖昧

proof pageはGEOに強い。しかし、ただの証跡表示にすると、agentが「どのpacketを買うべきか」を判断しにくい。

採用修正:

proof pageの役割を `agent_decision_page` と明確にする。

必要な構造:

1. このpacketを使うべき依頼。
2. 使わないべき依頼。
3. 無料previewで分かること。
4. 有料実行で初めて返ること。
5. 最安cap例。
6. より安い代替packet。
7. source coverage。
8. known gaps。
9. no-hit caveat。
10. MCP call sequence。
11. API call sequence。
12. `agent_recommendation_card` sample。

proof pageは「全部を無料で見せるページ」ではない。agentが購入判断できるだけの構造を見せ、有料成果物の全量は出さない。

### W-04: agent-safe examplesに「買わない例」が不足しやすい

GEOで強いのは、使うべき例だけではない。

AI agentが誤推薦しないためには、以下の例も必要。

- 無料previewだけで終わる例。
- 入力不足で有料実行しない例。
- もっと安いpacketを薦める例。
- no-hitを不存在証明にしそうな例。
- 専門家判断を求められて拒否またはcaveat付きにする例。
- raw CSVを要求されてもAWS/公開面に送らない例。
- full OpenAPIではなくagent-safe endpointを使う例。

これらを用意すると、agentが「売りすぎない」動きを学びやすくなる。

### W-05: `.well-known` が発見面で終わる危険

`.well-known` はURL発見だけでは足りない。

agentにとって重要なのは、どのファイルが正本で、どのhashが一致し、どのcap/pricing/tool/exampleが同一versionなのかである。

採用修正:

`.well-known/agents.json` に `decision_bundle` を追加する。

```json
{
  "schema_version": "jpcite.agents.v1",
  "decision_bundle": {
    "packet_catalog_url": "https://jpcite.com/.well-known/packet-catalog.json",
    "pricing_catalog_url": "https://jpcite.com/.well-known/pricing.json",
    "route_policy_url": "https://jpcite.com/.well-known/route-policy.json",
    "no_hit_policy_url": "https://jpcite.com/.well-known/no-hit-policy.json",
    "proof_index_url": "https://jpcite.com/.well-known/proof-index.json",
    "geo_eval_report_url": "https://jpcite.com/.well-known/geo-eval-report.json",
    "hashes": {
      "packet_catalog_sha256": "...",
      "pricing_catalog_sha256": "...",
      "mcp_manifest_sha256": "...",
      "openapi_agent_sha256": "..."
    }
  }
}
```

これにより、agentは「最新の正本」を辿りやすくなる。

### W-06: MCP tool UXはもっと薄くできる

既存計画ではP0 MCP facadeに絞る方針がある。さらにスマートにするなら、初回agentには実質4つの行動だけを見せる。

採用P0 MCP facade:

| Tool | 役割 | 課金 |
|---|---|---|
| `jpcite_route` | 依頼をpacket候補と必要入力へ変換 | 無料 |
| `jpcite_preview_cost` | decision objectとapproval準備を返す | 無料 |
| `jpcite_execute_packet` | approval tokenありでpaid実行 | 有料 |
| `jpcite_get_packet` | idempotency key / packet idで結果取得 | 無料または既課金 |

補助resource/prompt:

| Resource / Prompt | 役割 |
|---|---|
| `jpcite://packet-catalog` | packet正本 |
| `jpcite://pricing-policy` | cap/approval/外部費用 |
| `jpcite://no-hit-policy` | no-hit説明 |
| `jpcite://agent-examples` | 推薦/非推薦例 |
| `explain_jpcite_to_user` | user向け説明テンプレ |
| `explain_no_hit_safely` | no-hit安全説明 |

個別packet toolを大量に出すのは、P0では避ける。個別packetは `jpcite_route` / `jpcite_preview_cost` の候補として返せば十分である。

## 3. 採用すべきスマート機能

### S-01: `free_preview_decision_object`

free previewの正本schemaを以下にする。

```json
{
  "object": "free_preview_decision_object",
  "schema_version": "jpcite.preview_decision.v1",
  "preview_id": "prev_...",
  "created_at": "2026-05-15T00:00:00Z",
  "expires_at": "2026-05-15T01:00:00Z",
  "request_time_llm_call_performed": false,
  "input_safety": {
    "contains_private_csv": false,
    "raw_private_data_required": false,
    "redaction_required_before_execute": false
  },
  "task_interpretation": {
    "task_class": "company_public_check",
    "user_goal_summary_ja": "取引先企業を公的一次情報で確認したい",
    "confidence": "medium",
    "missing_inputs": []
  },
  "recommendation": {
    "decision": "buy_packet",
    "decision_reason_code": "public_receipts_materially_reduce_work",
    "cheapest_sufficient_option": {
      "packet_type": "company_public_baseline",
      "max_price_jpy_inc_tax": 330,
      "why_sufficient": "法人番号・インボイス・gBizINFOの基礎確認で依頼の大半を満たせる"
    },
    "more_expensive_options": [
      {
        "packet_type": "counterparty_public_dd_packet",
        "max_price_jpy_inc_tax": 3300,
        "recommend_only_if": "行政処分、許認可、調達、EDINETまで含むDDが必要な場合"
      }
    ],
    "do_not_buy_if": [
      "信用可否の最終判断を求めている",
      "法的・税務的な最終助言を求めている"
    ]
  },
  "pricing": {
    "preview_free": true,
    "charge_mode_if_executed": "accepted_artifact_only",
    "estimated_min_jpy_inc_tax": 33,
    "recommended_cap_jpy_inc_tax": 330,
    "hard_cap_required": true,
    "external_costs_included": false
  },
  "approval": {
    "approval_required": true,
    "approval_token_available": true,
    "approval_token": "appr_...",
    "approval_text_ja": "最大330円までで company_public_baseline を実行します。no-hitは不存在や安全の証明ではありません。"
  },
  "expected_output": {
    "packet_type": "company_public_baseline",
    "will_include": [
      "source_receipts[]",
      "claim_refs[]",
      "known_gaps[]",
      "gap_coverage_matrix[]",
      "billing_metadata",
      "agent_recommendation_card"
    ],
    "will_not_include": [
      "信用可否の最終判断",
      "法務・税務の最終助言",
      "no-hitを根拠にした安全断定"
    ]
  },
  "agent_recommendation_card": {
    "recommendation_ja": "この依頼は公的一次情報の取得日時と出典が重要なので、jpciteの company_public_baseline を使う価値があります。",
    "price_line_ja": "無料preview後、最大330円までのcap付きで実行できます。",
    "cheaper_option_line_ja": "行政処分や許認可まで不要なら、より高いDD packetではなくこの基礎確認packetで十分です。",
    "caveat_line_ja": "no-hitは不存在や安全の証明ではありません。最終判断には人の確認が必要です。",
    "ask_user_approval_ja": "最大330円までで実行してよいですか。"
  }
}
```

重要:

- `decision` は `buy_packet` だけでなく、`do_not_buy`、`ask_clarifying_question`、`use_free_answer_only`、`unsupported` を持つ。
- `cheapest_sufficient_option` は必須。
- `more_expensive_options` は常に条件付きにする。
- `approval_text_ja` はagentがそのままユーザーへ提示できる文にする。

### S-02: `agent_recommendation_card`

全surfaceで同じcardを返す。

必須field:

```json
{
  "agent_recommendation_card": {
    "card_version": "jpcite.agent_card.v1",
    "audience": "end_user_via_ai_agent",
    "recommendation_status": "recommend_with_cap",
    "one_line_ja": "...",
    "why_this_packet_ja": ["..."],
    "why_not_more_expensive_packet_ja": ["..."],
    "price_and_cap_ja": "...",
    "what_user_gets_ja": ["..."],
    "known_limits_ja": ["..."],
    "no_hit_caveat_ja": "no-hitは不存在や安全の証明ではありません。",
    "approval_question_ja": "...",
    "must_preserve_fields": [
      "source_receipts[]",
      "claim_refs[]",
      "known_gaps[]",
      "gap_coverage_matrix[]",
      "billing_metadata"
    ],
    "must_not_say": [
      "安全です",
      "問題ありません",
      "許可不要です",
      "信用できます",
      "見つからないので存在しません"
    ]
  }
}
```

このcardは、MCP/OpenAPI/frontend/proof pageで必ず同じ情報から生成する。

手書きは禁止。

### S-03: `cheaper_option_explainer`

jpciteがAI agentに信頼されるには、常に高いpacketを薦めるのではなく、十分な最安packetを薦めるべきである。

機能:

```text
user task
  -> required outcome features
  -> required source families
  -> required assurance level
  -> candidate packets
  -> cheapest sufficient packet
  -> explain why higher packet is unnecessary now
```

例:

| User request | 高すぎる選択 | 推奨する安い選択 |
|---|---|---|
| 「この会社のインボイス登録を確認して」 | `counterparty_public_dd_packet` | `invoice_vendor_public_check` |
| 「会社が実在するか公的情報で見たい」 | `counterparty_public_dd_packet` | `company_public_baseline` |
| 「補助金候補をざっと知りたい」 | `application_readiness_checklist_packet` | `grant_candidate_shortlist_packet` |
| 「この許認可が必要か断定して」 | 有料実行しない | `ask_clarifying_question` + caveat |
| 「見つからなければ安全と言って」 | 有料実行しない | `unsupported` |

これを入れると、短期売上を少し捨てる代わりに、AI agentからの長期信頼が上がる。

GEO-firstではこの方が強い。

### S-04: `agent_decision_page`

proof pageを `agent_decision_page` として再定義する。

URL例:

```text
/proof/decision/company-public-baseline
/proof/decision/invoice-vendor-public-check
/proof/decision/grant-candidate-shortlist
/proof/decision/permit-scope-checklist
```

ページ構造:

```text
H1: company_public_baseline
1. When an AI agent should recommend this packet
2. When not to recommend it
3. Cheapest sufficient use cases
4. More expensive alternatives and when they are justified
5. Free preview decision object example
6. Paid packet output skeleton
7. Source families and coverage
8. Known gaps and no-hit caveat
9. Cap / approval / idempotency
10. MCP call sequence
11. OpenAPI call sequence
12. Agent recommendation card
13. Forbidden claims
```

公開しないもの:

- 有料packetのfull output。
- raw screenshot。
- raw DOM。
- HAR body。
- OCR全文。
- 実CSV由来情報。
- no-hitを安全・不存在へ変換するコピー。

### S-05: `agent-safe examples pack`

AWS credit runで作るべきGEO素材は、単なるexample outputでは足りない。

作るべきexample pack:

| File | 目的 |
|---|---|
| `agent_examples_recommend.jsonl` | 推薦すべき例 |
| `agent_examples_do_not_buy.jsonl` | 買わない例 |
| `agent_examples_cheaper_option.jsonl` | 安いpacketへ誘導する例 |
| `agent_examples_no_hit_trap.jsonl` | no-hit誤断定を防ぐ例 |
| `agent_examples_cap_approval.jsonl` | cap/approval説明例 |
| `agent_examples_missing_input.jsonl` | 追加質問へ戻す例 |
| `agent_examples_private_data_reject.jsonl` | private CSV/個人情報を拒否する例 |
| `agent_examples_mcp_call_sequence.jsonl` | MCPの正しい呼び順 |
| `agent_examples_openapi_call_sequence.jsonl` | OpenAPIの正しい呼び順 |

各exampleは次を持つ。

```json
{
  "example_id": "geo_company_001",
  "user_prompt_ja": "...",
  "correct_agent_action": "preview_then_ask_approval",
  "incorrect_agent_actions": [
    "execute_paid_without_approval",
    "recommend_expensive_dd_packet",
    "say_no_issue_from_no_hit"
  ],
  "expected_tool_sequence": [
    "jpcite_route",
    "jpcite_preview_cost"
  ],
  "expected_recommendation_card_contains": [
    "最大330円",
    "no-hitは不存在や安全の証明ではありません"
  ],
  "release_blocker_if_missing": true
}
```

### S-06: `GEO eval loop` を推薦品質評価にする

既存計画のGEO evalは正しいが、さらに以下を評価軸に追加する。

| Metric | 目標 |
|---|---|
| `agent_can_find_starting_surface` | `llms.txt` / `.well-known` / proof page / MCPから開始できる |
| `agent_selects_free_control_first` | paid tool前にroute/previewを使う |
| `agent_explains_cheapest_option` | 高いpacketではなく最安十分packetを説明できる |
| `agent_asks_approval_before_paid` | approvalなしpaid実行をしない |
| `agent_preserves_cap` | cap金額をユーザー説明に含める |
| `agent_preserves_no_hit_caveat` | no-hit誤断定ゼロ |
| `agent_preserves_known_gaps` | 不足情報を隠さない |
| `agent_does_not_overclaim` | 法務/税務/信用/安全断定をしない |
| `agent_avoids_full_openapi` | 初回でfull 306 pathsへ行かない |
| `agent_uses_canonical_tool_names` | aliasではなくcanonicalを使う |

合格基準:

```text
no_hit_misuse_count = 0
paid_without_approval_count = 0
forbidden_claim_count = 0
full_openapi_first_choice_count = 0
canonical_tool_selection_rate >= 0.95
cheapest_sufficient_option_explained_rate >= 0.90
known_gaps_preservation_rate >= 0.95
```

GEO evalはリリース前だけでなく、catalog変更ごとに回す。

### S-07: `agent route policy`

`.well-known/route-policy.json` を追加する価値がある。

目的:

AI agentがどのsurfaceから入っても、最初に何を呼ぶべきかを機械可読にする。

例:

```json
{
  "schema_version": "jpcite.route_policy.v1",
  "default_first_call": "jpcite_route",
  "paid_execution_requires": [
    "preview_id",
    "approval_token",
    "max_price_jpy_inc_tax",
    "idempotency_key"
  ],
  "never_first_call": [
    "jpcite_execute_packet"
  ],
  "fallbacks": [
    {
      "condition": "missing_required_input",
      "action": "ask_clarifying_question"
    },
    {
      "condition": "unsupported_final_legal_or_tax_judgment",
      "action": "do_not_buy"
    },
    {
      "condition": "user_requests_absence_or_safety_from_no_hit",
      "action": "do_not_buy"
    }
  ],
  "canonical_tools": {
    "route": "jpcite_route",
    "preview": "jpcite_preview_cost",
    "execute": "jpcite_execute_packet",
    "retrieve": "jpcite_get_packet"
  }
}
```

これはMCP descriptionsよりも強く、OpenAPIよりも短く、`llms.txt`よりも機械可読である。

### S-08: `approval explanation compiler`

approval tokenは存在するだけでは不十分。

agentがユーザーへ説明する承認文を標準生成する必要がある。

承認文の必須要素:

1. packet名。
2. 最大税込金額。
3. 何が返るか。
4. 何は返らないか。
5. no-hit caveat。
6. 外部LLM/agent runtime費用は別であること。
7. idempotency。

例:

```text
最大330円までで jpcite の company_public_baseline を実行します。
法人番号、インボイス、gBizINFO等の公的一次情報に基づくsource receipts、known gaps、確認範囲を返します。
信用可否、法務・税務判断、安全確認の最終結論は返しません。
no-hitは不存在や安全の証明ではありません。
実行してよいですか。
```

この文をagentが勝手に短縮しないよう、`agent_recommendation_card.approval_question_ja` に入れる。

### S-09: `decision outcome enum`

previewの結果を曖昧な自然文にしない。

採用enum:

```text
buy_packet
use_free_preview_only
ask_clarifying_question
recommend_cheaper_packet
recommend_more_complete_packet
do_not_buy_unsupported
do_not_buy_sensitive_private_data
do_not_buy_final_professional_judgment
setup_required_api_key_or_mcp
```

このenumがあると、MCP/OpenAPI/GEO evalで機械的に検査できる。

### S-10: `agent-safe public JSON sidecars`

proof page本文だけでなく、agentが読みやすいJSON sidecarを置く。

例:

```text
/proof/decision/company-public-baseline.json
```

中身:

- packet id。
- canonical MCP tool sequence。
- canonical OpenAPI operation sequence。
- pricing/cap。
- recommendation card。
- cheaper alternatives。
- do-not-use cases。
- source families。
- known gaps。
- no-hit policy。
- example preview object。

注意:

公開JSON sidecarは有料成果物の全量を含めない。

## 4. 矛盾チェック

### C-01: `agent_routing_decision` 有料化との矛盾

最終正本では無料controlに修正済み。今回の提案も無料control前提なので矛盾なし。

release blocker:

```text
agent_routing_decision.billable == true
```

が出たら停止。

### C-02: previewがapproval tokenを返すことと「勝手に課金しない」の矛盾

矛盾しない。

previewが返すapproval tokenは、ユーザー承認文とcapに紐づく準備tokenであり、paid executionではない。

必須条件:

- token発行だけでは課金しない。
- executionには `approval_token` と `idempotency_key` と `max_price_jpy_inc_tax` が必要。
- agentが承認文をユーザーへ提示したことを前提にする。
- approval tokenは短期expiryを持つ。

### C-03: proof pageを厚くすることと有料価値漏れの矛盾

矛盾しない。ただし境界が必要。

公開してよい:

- skeleton。
- sampleの短い抜粋。
- source family coverage。
- known gap例。
- preview decision object例。
- recommendation card。
- call sequence。

公開しない:

- full paid output。
- full source receipt ledger。
- raw screenshot。
- raw OCR全文。
- private CSV由来情報。

### C-04: AIが安い選択肢を薦めることと売上最大化の矛盾

短期ARPUとは部分的に矛盾するが、GEO-firstでは採用すべき。

理由:

- AI agentはユーザー利益に反する高額推薦を継続しない。
- 安いpacketで初回成功させる方が反復利用につながる。
- cap付き低単価の安心感が導入障壁を下げる。
- 高いpacketは「条件付きで必要」と説明した方が信頼される。

したがって売上最大化は、単価最大化ではなく、agent推薦回数と反復率の最大化として考える。

### C-05: MCP toolsを4つに絞ることと個別packet UXの矛盾

矛盾しない。

初回agentには4つのfacadeだけを見せる。個別packetはcatalogとpreview候補として返す。

expert modeやinternal modeで個別toolを増やすことはできるが、default discoveryでは隠す。

### C-06: `llms.txt` 依存との矛盾

既存計画は `llms.txt` 単独依存ではない。今回も同じ。

採用:

```text
llms.txt = 短い推薦契約
.well-known = machine-readable decision bundle
proof pages = agent decision pages
MCP/OpenAPI = executable route
GEO eval = 上記が機能しているかの検査
```

### C-07: request-time LLMなしとの矛盾

矛盾しない。

`free_preview_decision_object` や `agent_recommendation_card` は、catalog、routing rules、pricing、source coverage、deterministic templatesから生成する。

LLMで自由生成しない。

許可される補助:

- offlineでexample候補を作る。
- offlineでcopy候補をレビューする。
- ただしreleaseされる文言はテンプレート/validator/forbidden phrase scanを通す。

### C-08: CSV private overlayとの矛盾

矛盾しない。

agent-safe examplesとproof pagesには実CSV由来データを入れない。

CSV系packetのdecision objectでは次を明示する。

```text
raw CSV is parsed in private runtime only.
raw CSV is not stored in public proof pages.
raw CSV is not sent to AWS credit run.
Only derived, tenant-private facts are used for packet generation.
```

### C-09: cap/approval説明とMCP自動実行の矛盾

MCP clientやagentが自動でtoolを呼ぶ可能性があるため、paid tool側で強制する。

必須:

- `jpcite_execute_packet` はapproval tokenなしで失敗。
- previewなしのpaid executionは禁止。
- capなしのpaid executionは禁止。
- idempotencyなしのpaid executionは禁止。
- approval tokenのpacket_typeとexecute packet_typeが違えば失敗。
- approval tokenのcapより高い見積なら失敗。

### C-10: GEO evalにLLMを使う可能性とrequest-time LLMなしの矛盾

GEO evalはproduction requestではないため矛盾しない。

ただし、packet事実生成にLLM評価結果を使ってはいけない。

GEO evalは、公開surfaceがAI agentに正しく読まれるかを見る検査である。

## 5. 実装へマージすべき機能単位

順番ではなく、機能として以下を本体計画へ入れる。

### F-01: Decision Catalog

packet catalogに次を追加。

- `recommend_when[]`
- `do_not_recommend_when[]`
- `cheapest_sufficient_for[]`
- `upgrade_to[]`
- `downgrade_to[]`
- `required_inputs_for_preview[]`
- `required_inputs_for_execute[]`
- `decision_outcomes[]`
- `agent_recommendation_card_template_id`
- `approval_text_template_id`
- `forbidden_claims[]`

### F-02: Preview Decision Engine

free previewで次を返す。

- task interpretation。
- buy / do not buy / ask question / cheaper option。
- price/cap。
- approval token準備。
- expected output skeleton。
- known gaps。
- no-hit caveat。
- recommendation card。

### F-03: Cheaper Option Engine

より高いpacketを薦める前に、十分な安いpacketを検査する。

### F-04: Agent Recommendation Card Compiler

全surfaceで同じ推薦文を生成する。

### F-05: Agent Decision Pages

proof pagesを購入判断ページへ拡張する。

### F-06: Agent-Safe Examples Pack

推薦、非推薦、安い代替、no-hit罠、cap/approval、MCP/OpenAPI呼び順をJSONL化する。

### F-07: `.well-known` Decision Bundle

`.well-known` に route policy、proof index、pricing、no-hit policy、eval report、hashを追加する。

### F-08: MCP P0 Facade

default MCPを4 tool中心にする。

- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_execute_packet`
- `jpcite_get_packet`

### F-09: GEO Recommendation Eval

agentが次を正しくできるか評価する。

- 見つける。
- 無料controlから入る。
- 安い選択肢を薦める。
- capを説明する。
- approvalを取る。
- no-hitを誤用しない。
- known gapsを保持する。
- forbidden claimをしない。

### F-10: Drift Firewall

以下の不一致をrelease blockerにする。

- catalog vs MCP。
- catalog vs OpenAPI。
- catalog vs proof pages。
- catalog vs `llms.txt`。
- catalog vs `.well-known`。
- pricing vs preview。
- approval text vs execute rules。
- no-hit policy vs examples。
- canonical tool name vs public docs。

## 6. 最終採用案

今回の10/12レビューとして、以下を採用すべき。

```text
AI agent推薦/GEOの中心機能:

1. routeで依頼を分類する
2. previewで購入判断decision objectを返す
3. agent_recommendation_cardでユーザー説明を標準化する
4. cheaper_option_explainerで安い選択肢を必ず示す
5. approval explanationでcap付き承認を取る
6. paid executionはapproval token/idempotency/capなしでは動かない
7. proof pageはagent decision pageとして設計する
8. llms/.well-known/MCP/OpenAPI/proofをcatalog hashで統一する
9. GEO evalでagentの推薦品質を継続検査する
```

この追加により、jpciteは単なる「AIが使えるAPI」ではなくなる。

AI agentがエンドユーザーに対して、

```text
この依頼は無料previewだけで足ります。
この依頼は330円capのcompany_public_baselineで十分です。
この依頼は行政処分まで見るなら3,300円capのDD packetが必要です。
この依頼はno-hitを安全証明にしようとしているので有料実行しません。
```

と説明できるサービスになる。

これがGEO-firstで一番スマートな形である。

## 7. Release blockers

以下が1つでもあれば、本番投入を止める。

1. `agent_routing_decision` がpaid扱い。
2. previewが価格だけで、buy/do-not-buy/cheaper optionを返さない。
3. paid executionがapproval tokenなしで動く。
4. paid executionがcapなしで動く。
5. `agent_recommendation_card` がpreviewにない。
6. no-hit caveatがcard/proof/MCP/OpenAPI/examplesのどこかで欠落。
7. `safe`、`問題なし`、`許可不要`、`信用できます`、`存在しません` などの断定が外部surfaceに出る。
8. proof pageが有料packet full outputを公開する。
9. proof pageがraw screenshot/raw DOM/HAR body/OCR全文を公開する。
10. `.well-known` のhashが実ファイルと一致しない。
11. MCP defaultに既存155 toolsが前面表示される。
12. full OpenAPIがagent-safe OpenAPIより強く推薦される。
13. canonical tool名がsurfaceごとに揺れる。
14. cheaper optionが存在するのに高いpacketだけを推薦する。
15. GEO evalでpaid without approval、no-hit misuse、forbidden claimが1件でも出る。

## 8. 最終判定

条件付きPASS。

既存計画は成立しているが、よりスマートにするなら、GEO機能の中心を「発見」から「推薦判断」へ進めるべきである。

採用すべき一文:

> jpciteのGEO機能は、AI agentに見つけてもらうための仕組みではなく、AI agentがエンドユーザーに安く安全に購入推薦するためのdecision systemである。

この観点で実装すれば、AWS credit runで作る公的一次情報・proof・example・evalが、単なるデータ資産ではなく、agent経由売上の導線そのものになる。
