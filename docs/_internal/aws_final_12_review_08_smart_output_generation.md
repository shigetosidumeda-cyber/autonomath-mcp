# AWS final 12 review 08/12: smart output generation functions

作成日: 2026-05-15  
担当: 最終追加検証 8/12 / もっとスマートな成果物生成機能  
対象: jpcite master execution plan、packet taxonomy、revenue packet計画、algorithm safety計画  
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。  
出力: このMarkdownのみ。  

## 0. 結論

判定は **条件付きPASS**。

現行計画は、次の大方針では正しい。

- GEO-first。
- AIエージェントがエンドユーザーに推薦する。
- 検索ではなく、証跡付き成果物packetを売る。
- request-time LLMで事実主張を作らない。
- `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`gap_coverage_matrix[]`、`no_hit_checks[]` を必須にする。
- no-hitを不存在・安全・問題なしの証明にしない。
- AWSは一時的なartifact factoryであり、本番runtimeではない。

ただし、「よりスマートな方法・機能」という観点では、まだ一段よくできる。

一番スマートな改善は、packetを単体APIとして増やすことではない。

> `Output Composer` を中核に置き、AIエージェントが「買うべき成果物」「買わない理由」「最安の代替」「不足質問」「bundle」「再利用できるreceipt」「次に取るべきaction」まで一度に判断できるようにすること。

つまり、jpciteは単にpacketを返すのではなく、次の中間生成物を標準化する。

- `decision_object`
- `agent_recommendation_card`
- `workflow_recipe`
- `question_set`
- `bundle_quote`
- `receipt_reuse_plan`
- `delta_to_action`
- `evidence_graph_view`
- `agent_facing_summary`

これにより、AIエージェントはエンドユーザーへこう説明できる。

```text
この依頼は jpcite の company_public_baseline が最安です。
無料preview上、法人番号/インボイス/gBizINFOの3系統で確認できます。
330円上限で、source receipt付きの公的ベースラインが返ります。
ただし行政処分や許認可まで見るなら counterparty_public_dd_packet の方が適切です。
不足情報は法人番号または所在地です。
```

この「購入判断のしやすさ」が、GEO経由売上の本体である。

## 1. 確認した前提

主に以下の既存計画と整合させた。

| 文書 | 確認した観点 |
|---|---|
| `aws_jpcite_master_execution_plan_2026-05-15.md` | 最終正本、AWS一時利用、packet、GEO、本番、zero-bill |
| `aws_final_12_review_02_revenue_packets.md` | 価格、free control、recommendation card、売上導線 |
| `aws_final_12_review_04_algorithm_safety.md` | hallucination防止、public packet compiler、禁止表現 |
| `aws_scope_expansion_27_packet_taxonomy.md` | packet taxonomy、source family、price tier、MCP名 |
| `aws_final_consistency_10_final_sot.md` | 最終SOT、矛盾解消、Go/No-Go |

このレビューではAWSを動かしていない。

## 2. 現行計画の不足

現行計画は「どのpacketを作るか」はかなり詰まっている。

一方で、AIエージェントが実際に売上へつなげるには、packetそのものより前に必要な機能がある。

### 2.1 AIが買う理由を説明する素材がまだ弱い

AIエージェントは、単にcatalogを見ても売りにくい。

必要なのは、次のような購入推薦用の構造化出力。

- この依頼に最適なpacketは何か。
- なぜそのpacketなのか。
- もっと安いpacketはないか。
- 逆に高いpacketにすべき条件は何か。
- いくらで止まるか。
- 何が返るか。
- 何は返らないか。
- どの不足質問をすれば精度が上がるか。
- no-hit時にどう説明するか。

これは `cost_preview` だけでは足りない。

### 2.2 packetが単発商品に見える

実際のユーザー依頼は単発packetではなく、workflowである。

例:

```text
この会社と取引してよいか見て
```

これは内部的には次の複合処理になる。

- 会社同定
- 法人番号確認
- インボイス確認
- gBizINFO確認
- EDINET有無確認
- 行政処分source確認
- 許認可source候補確認
- known gaps提示
- 追加質問提示

これを単体packetだけで見せると、AIが「どこまで買えばよいか」を判断しにくい。

### 2.3 receipt再利用が商品価値として前面に出ていない

同じ法人番号、同じsource、同じ取得日時範囲であれば、receiptは再利用できる。

再利用できると:

- 安くなる。
- 速くなる。
- 同じ証跡で複数packetを生成できる。
- エンドユーザーに「前回の確認結果を使って安くできます」と説明できる。

これはGEOでかなり売りやすいが、現行計画では少し裏方に寄っている。

### 2.4 deltaからactionへの変換が弱い

法令・制度・補助金・許認可・税労務では、差分そのものより「次に何を確認すべきか」が売れる。

単なる差分:

```text
条文Aが改正されました。
```

売れる成果物:

```text
あなたの業種/地域/事業内容では、以下3点を確認すべきです。
1. 届出要否の確認
2. 期限の確認
3. 既存契約/表示/社内規程への影響確認
```

`delta_to_action` が必要である。

### 2.5 evidence graphが内部用に留まっている

`source_receipts[]` と `claim_refs[]` は機械可読には強い。

しかしAIエージェントとエンドユーザーに売るには、次の形が必要。

- どの主張がどのsourceに支えられているか。
- どのsourceがno-hitだったか。
- どのsourceが未対応か。
- どの主張がhuman reviewなのか。
- どこに課金価値があるのか。

これを `evidence_graph_view` としてAPI/MCP/proof pageへ出せるようにするべき。

## 3. 採用すべき中核機能

### 3.1 `Output Composer`

`Output Composer` は、ユーザー依頼から「どの成果物をどう組み合わせるか」を決める機能である。

役割:

- ユーザー依頼を成果物候補へ写像する。
- 無料controlと有料packetを分ける。
- 最安で目的を満たすpacketを選ぶ。
- 必要ならbundle化する。
- 不足入力を質問に変える。
- 既存receiptを再利用できるか判定する。
- public packet compilerへ渡す出力blueprintを作る。

重要なのは、Output Composer自体は最終事実主張をしないこと。

Output Composerが出すのは「実行計画」と「購入判断」であり、最終claimはpacket compilerがreceipt付きで作る。

```json
{
  "object": "output_composition_plan",
  "user_task": "この会社を公的情報で確認して",
  "recommended_packet_type": "company_public_baseline",
  "alternative_packet_types": [
    "invoice_vendor_public_check",
    "counterparty_public_dd_packet"
  ],
  "free_controls_required": [
    "agent_routing_decision",
    "cost_preview_quote"
  ],
  "paid_execution_required": true,
  "final_claims_generated": false
}
```

### 3.2 `decision_object`

`decision_object` は、AIエージェントが「買う/買わない/質問する/安いpacketへ落とす」を判断するための中核出力。

これは無料で返す。

```json
{
  "object": "decision_object",
  "decision": "recommend_paid_packet",
  "recommended_packet_type": "company_public_baseline",
  "why": [
    "会社同定と公的ベースライン確認が依頼の中心です",
    "法人番号・インボイス・gBizINFOのsource familyで対応できます",
    "より重い取引先DDまでは現時点の依頼に不要です"
  ],
  "cheapest_sufficient_packet": "company_public_baseline",
  "upgrade_packet_if": [
    {
      "condition": "行政処分や許認可まで確認したい",
      "packet_type": "counterparty_public_dd_packet"
    },
    {
      "condition": "T番号だけを確認したい",
      "packet_type": "invoice_vendor_public_check"
    }
  ],
  "questions_before_paid_run": [
    {
      "question_id": "corporate_number_or_address_hint",
      "question": "法人番号、または会社名と所在地の手がかりを入力してください",
      "reason": "同名法人の取り違えを避けるためです"
    }
  ],
  "estimated_price_jpy_including_tax": 330,
  "cap_required": true,
  "request_time_llm_call_performed": false
}
```

採用理由:

- AIエージェントが購入推薦しやすい。
- エンドユーザーが費用に納得しやすい。
- 高いpacketを無理に売らず、最安packetを提示できる。
- 信頼が上がり、継続利用に寄与する。

### 3.3 `agent_recommendation_card`

`agent_recommendation_card` は、AIエージェントがそのままユーザーへ説明できる短いカードである。

ただし、カードは宣伝文ではなく、購入判断の構造化説明にする。

```json
{
  "object": "agent_recommendation_card",
  "title": "公的情報で会社のベースラインを確認できます",
  "recommended_action": "税込330円上限で company_public_baseline を実行",
  "plain_language_reason": "法人番号・インボイス・公的事業者情報を使い、会社同定と基本確認を出典付きで返します。",
  "what_user_gets": [
    "会社同定候補",
    "法人番号/所在地/商号の確認範囲",
    "インボイス登録確認範囲",
    "source receipts",
    "known gaps"
  ],
  "what_it_does_not_do": [
    "安全性の断定",
    "信用力の評価",
    "法的な最終判断",
    "非公開情報の調査"
  ],
  "price_cap": {
    "currency": "JPY",
    "including_tax": 330
  },
  "approval_phrase": "330円上限で公的ベースラインを取得してよいですか？"
}
```

これをMCP/APIの無料previewで返すと、AIエージェントは迷わず売れる。

### 3.4 `workflow_recipe`

`workflow_recipe` は、複数packetを業務の流れとして束ねる設計。

packet bundleとは別に、業務手順を定義する。

例: 取引先確認workflow

```json
{
  "object": "workflow_recipe",
  "recipe_id": "vendor_onboarding_public_check_v1",
  "user_goal": "新規取引先を公的情報で確認する",
  "steps": [
    {
      "step_id": "identify_company",
      "packet_type": "company_public_baseline",
      "required": true
    },
    {
      "step_id": "check_invoice_registry",
      "packet_type": "invoice_vendor_public_check",
      "required": false,
      "skip_if": "invoice_status_already_covered_by_company_public_baseline"
    },
    {
      "step_id": "public_dd_lite",
      "packet_type": "counterparty_public_dd_packet",
      "required": false,
      "ask_before_upgrade": true
    }
  ],
  "default_strategy": "cheapest_sufficient",
  "allowed_billing_mode": "stepwise_cap"
}
```

採用理由:

- AIに「次はこれを買うべき」と説明させやすい。
- 高単価bundleへ自然に進める。
- ただし初回は安く始められる。
- ユーザーが過剰課金を恐れにくい。

### 3.5 `question_generation`

質問生成は、成果物を安く速くするために重要である。

同名法人が複数あるのにいきなり高いpacketを回すより、先に1問聞いた方が安い。

質問生成はLLM自由生成ではなく、gapとambiguityから作る。

```json
{
  "object": "question_set",
  "reason": "paid_execution_would_be_ambiguous_or_expensive",
  "questions": [
    {
      "question_id": "address_hint",
      "question_type": "short_text",
      "question": "会社の所在地の都道府県または市区町村は分かりますか？",
      "why_it_matters": "同名法人の候補を絞るためです",
      "cost_reduction_expected": true
    },
    {
      "question_id": "desired_depth",
      "question_type": "single_select",
      "options": [
        "会社の基本確認だけ",
        "インボイス確認まで",
        "行政処分や許認可まで"
      ],
      "why_it_matters": "必要以上に高いpacketを避けるためです"
    }
  ]
}
```

質問生成の原則:

- 価格を下げる質問を優先する。
- 取り違えを防ぐ質問を優先する。
- 最終専門判断を求める質問にはしない。
- ユーザーに長いフォームを埋めさせない。
- 1回のpreviewでは最大3問程度に抑える。

### 3.6 `multi_packet_bundle`

bundleは、割引ではなく「receipt再利用」と「workflow完了」を商品化するもの。

例:

```json
{
  "object": "bundle_quote",
  "bundle_id": "vendor_check_starter_bundle",
  "packets": [
    "company_public_baseline",
    "invoice_vendor_public_check",
    "source_receipt_ledger"
  ],
  "normal_unit_total": 230,
  "reuse_adjusted_unit_total": 160,
  "why_cheaper": [
    "同じ法人同定receiptを再利用できます",
    "法人番号source receiptを複数packetで共有できます"
  ],
  "price_cap_jpy_including_tax": 528,
  "billing_mode": "accepted_artifact_bundle"
}
```

採用すべきbundle:

| Bundle | 構成 | 売れる理由 |
|---|---|---|
| `vendor_check_starter_bundle` | company baseline + invoice check + receipt ledger | 経理/購買に売りやすい |
| `counterparty_dd_lite_bundle` | company baseline + enforcement radar + permit source scope | B2B取引前確認に売りやすい |
| `grant_readiness_bundle` | grant shortlist + application checklist + question set | 補助金探索を行動へ変える |
| `permit_start_bundle` | permit scope checklist + source receipt ledger + missing input questions | 許認可相談前の準備に売れる |
| `monthly_csv_public_review_bundle` | CSV derived facts + tax/labor radar + grant candidates | 会計CSV価値を見せやすい |
| `reg_change_action_bundle` | regulation change impact + delta-to-action + evidence graph | 継続監視に売りやすい |

### 3.7 `receipt_reuse_plan`

receipt再利用は、コスト削減と売上増加の両方に効く。

```json
{
  "object": "receipt_reuse_plan",
  "subject_key": "jp_corporate_number:1234567890123",
  "reusable_receipts": [
    {
      "receipt_id": "src_rcpt_...",
      "source_family": "identity_tax",
      "freshness_state": "fresh",
      "usable_for_packet_types": [
        "company_public_baseline",
        "invoice_vendor_public_check",
        "counterparty_public_dd_packet"
      ]
    }
  ],
  "new_receipts_required": [
    {
      "source_family": "enforcement_safety",
      "reason": "counterparty DD requires administrative disposition scope"
    }
  ],
  "estimated_unit_savings": 70,
  "user_visible_message": "前回の法人番号確認receiptを再利用できるため、安く実行できます。"
}
```

実装上の注意:

- freshness TTLを過ぎたreceiptは自動再利用しない。
- terms/redistribution境界が変わったreceiptは再利用しない。
- public/private receiptを混ぜない。
- CSV-derived private receiptはtenant内だけで使う。
- reuseしてもclaimは必ず再コンパイルする。

### 3.8 `delta_to_action`

`delta_to_action` は、法令・制度・補助金・税労務・許認可の差分を、行動候補へ変える機能。

```json
{
  "object": "delta_to_action",
  "change_event_id": "chg_...",
  "change_type": "program_deadline_update",
  "affected_output_types": [
    "grant_candidate_shortlist_packet",
    "application_readiness_checklist_packet"
  ],
  "action_candidates": [
    {
      "action_type": "confirm_deadline",
      "priority": "high_review_priority",
      "reason": "公募締切日の更新が検出されています",
      "claim_refs": ["claim_..."],
      "known_gap_refs": []
    },
    {
      "action_type": "refresh_saved_packet",
      "priority": "needs_review",
      "reason": "過去のgrant shortlistに影響する可能性があります",
      "claim_refs": ["claim_..."],
      "known_gap_refs": ["gap_..."]
    }
  ],
  "not_final_advice": true
}
```

禁止:

- 「対応必須」と断定する。
- 「違反」や「適法」を断定する。
- 「申請可能」と断定する。

許可:

- 「確認優先度が高い」
- 「影響候補」
- 「追加確認事項」
- 「保存済みpacketの再確認候補」

### 3.9 `evidence_graph_view`

`evidence_graph_view` は、内部evidence graphをAI/人間が見やすい形へ投影したもの。

```json
{
  "object": "evidence_graph_view",
  "nodes": [
    {
      "node_id": "subject_1",
      "node_type": "subject",
      "label": "対象法人"
    },
    {
      "node_id": "source_nta_corporate",
      "node_type": "source_family",
      "label": "国税庁法人番号"
    },
    {
      "node_id": "claim_company_name",
      "node_type": "claim",
      "label": "商号確認"
    },
    {
      "node_id": "gap_enforcement_scope",
      "node_type": "known_gap",
      "label": "行政処分sourceは未確認"
    }
  ],
  "edges": [
    {
      "from": "source_nta_corporate",
      "to": "claim_company_name",
      "edge_type": "supports"
    },
    {
      "from": "gap_enforcement_scope",
      "to": "subject_1",
      "edge_type": "limits_interpretation"
    }
  ],
  "display_policy": {
    "hide_raw_screenshot": true,
    "hide_har_body": true,
    "show_receipt_metadata": true
  }
}
```

価値:

- AIが出典関係を説明しやすい。
- ユーザーが「何に基づく成果物か」を理解しやすい。
- known gapsを隠さない。
- proof pageの説得力が上がる。

### 3.10 `agent_facing_summary`

`agent_facing_summary` は、人間向け文章ではなく、AIが次の発話に使う短い構造化要約。

```json
{
  "object": "agent_facing_summary",
  "recommended_user_message": "この会社の公的ベースラインは330円上限で取得できます。法人番号・インボイス・gBizINFOの範囲で確認し、出典と不足情報も返ります。",
  "do_not_say": [
    "安全です",
    "問題ありません",
    "登録がないので不存在です",
    "許可不要です"
  ],
  "next_best_actions": [
    "法人番号または所在地を確認する",
    "330円上限でcompany_public_baselineを実行する",
    "行政処分まで必要ならcounterparty_public_dd_packetへ上げる"
  ],
  "approval_prompt": "330円上限で公的ベースラインを取得してよいですか？"
}
```

これはGEOで強い。

AIエージェントがjpciteを推薦した後、会話内で迷わずユーザー承認を取れる。

## 4. スマートな成果物生成アーキテクチャ

### 4.1 レイヤー構成

採用すべき構成:

```text
User task
  -> Free intent / route control
  -> Output Composer
  -> Decision Object
  -> Recommendation Card
  -> Question Set or Cost Preview
  -> Approval Token
  -> Packet Compiler
  -> Evidence Graph View
  -> Agent-facing Summary
  -> Billing Metadata
```

各レイヤーの責務:

| Layer | 責務 | 有料/無料 |
|---|---|---|
| Route control | jpciteで扱うべきか判断 | 無料 |
| Output Composer | packet/bundle/question/reuseを計画 | 無料 |
| Decision Object | 買う/聞く/買わない/安くする判断 | 無料 |
| Recommendation Card | AIがユーザーへ説明するカード | 無料 |
| Question Set | 誤実行・高コスト化を防ぐ質問 | 無料 |
| Cost Preview | cap、単価、no-charge条件 | 無料 |
| Packet Compiler | paid artifact生成 | 有料 |
| Evidence Graph View | 成果物の証拠関係を表示 | 有料成果物に含める |
| Agent-facing Summary | AIが使う短い説明 | 有料成果物に含める |

### 4.2 Output Composerはclaimを作らない

矛盾防止のため、Output Composerはclaimを作らない。

許可:

- packet推薦
- bundle推薦
- 価格推定
- 入力不足の質問
- 既存receiptの再利用計画
- 実行不可理由

禁止:

- 会社情報の断定
- 登録状態の断定
- 行政処分有無の断定
- 許認可要否の断定
- 補助金の申請可否断定

claimは必ずPacket Compilerが `source_receipts[]` と `claim_refs[]` を付けて作る。

### 4.3 Packet Compilerはpublic outputの唯一の出口

`aws_final_12_review_04_algorithm_safety.md` の方針と一致させる。

全ての有料成果物は `Public Packet Compiler` を通す。

必須検査:

- `source_receipts[]` がある。
- `claim_refs[]` がある。
- `known_gaps[]` と `gap_coverage_matrix[]` がある。
- no-hitは `no_hit_not_absence`。
- generic `score` は外部出力されない。
- 外部表示禁止語がない。
- request-time LLMでfinal claimを作っていない。
- private CSV由来データがpublic proofへ出ていない。
- raw screenshot/DOM/HAR/OCR全文をpublicに出していない。

## 5. 成果物を安く速く売る機能

### 5.1 Cheapest Sufficient Packet Selector

目的:

ユーザー依頼を満たす最安packetを選ぶ。

例:

| ユーザー依頼 | 高すぎる選択 | 最安十分な選択 |
|---|---|---|
| T番号が有効か見たい | counterparty DD | invoice vendor public check |
| 会社の基本確認 | counterparty DD | company public baseline |
| 補助金の候補だけ見たい | application full checklist | grant candidate shortlist |
| 許認可の論点だけ見たい | legal opinion風output | permit scope checklist |

返すべき情報:

```json
{
  "cheapest_sufficient_packet": "invoice_vendor_public_check",
  "not_recommended_more_expensive_packets": [
    {
      "packet_type": "counterparty_public_dd_packet",
      "reason": "行政処分・許認可確認までは依頼されていません"
    }
  ]
}
```

### 5.2 Stepwise Paid Unlock

一度に高いpacketを売らず、段階課金にする。

```text
無料 route
  -> 330円 baseline
  -> 990円 DD lite
  -> 3,300円 professional checklist
```

これにより:

- 初回購入の心理的抵抗が下がる。
- AIが推薦しやすい。
- receipt再利用でupgradeが安くなる。
- 売上導線が自然になる。

### 5.3 Accepted Artifact Billing

課金は「処理したから」ではなく「受け入れ可能な成果物を生成したから」に寄せる。

ただし、no-hit-onlyを完全無料にする必要はない。

採用ルール:

- previewで「no-hit ledger / coverage audit も成果物」と明示した場合だけ課金可能。
- 何も有用なartifactが生成されなければ課金しない。
- `accepted_artifact_count` と `billable_artifact_count` を返す。
- no-hitを安全や不存在に見せた場合はrelease blocker。

```json
{
  "billing_metadata": {
    "charge_mode": "accepted_artifact",
    "accepted_artifact_count": 3,
    "billable_artifact_count": 2,
    "no_hit_only_charge_disclosed_before_run": true
  }
}
```

### 5.4 Receipt Wallet

ユーザーまたはagent session単位で、再利用可能receiptを管理する。

名前は `receipt_cache` より `receipt_wallet` の方が商品価値が伝わる。

機能:

- 過去receiptを再利用。
- freshness切れを警告。
- source terms変更時に再利用停止。
- public/privateを分離。
- packet upgrade時の割引理由に使う。

外部メッセージ例:

```text
前回取得した法人番号source receiptを再利用できるため、今回のDD liteは通常より少ないunitで実行できます。
```

### 5.5 Bundle Optimizer

複数packetを組むとき、単純合算ではなく再利用込みで見積もる。

```json
{
  "bundle_optimizer_result": {
    "normal_units": 500,
    "reuse_adjusted_units": 360,
    "unit_savings": 140,
    "savings_reason": [
      "entity_resolution result reused",
      "identity_tax receipt reused",
      "invoice_registry no-hit ledger reused"
    ]
  }
}
```

### 5.6 Gap-to-Question Minimizer

known gapをただ列挙するのではなく、もっとも費用対効果の高い質問へ変換する。

例:

```json
{
  "gap_id": "gap_same_name_companies",
  "best_question": "所在地の都道府県は分かりますか？",
  "expected_effect": "候補法人を12件から2件へ減らせます",
  "cost_effect": "paid lookup unitを減らせます"
}
```

これにより、AIはユーザーに短く確認できる。

## 6. 成果物別のスマート化案

### 6.1 `company_public_baseline`

追加すべき機能:

- 同名法人が多い場合、即課金せず質問へ回す。
- `receipt_reuse_plan` を必ず返す。
- `invoice_vendor_public_check` へのcheap upgradeを提示する。
- `counterparty_public_dd_packet` へのupgrade条件を明示する。
- `agent_recommendation_card` を無料previewで返す。

スマートなpreview:

```json
{
  "recommended_packet_type": "company_public_baseline",
  "why_not_counterparty_dd_yet": "行政処分・許認可確認までは依頼に含まれていません",
  "cheap_upgrade_available": "invoice_vendor_public_check"
}
```

### 6.2 `invoice_vendor_public_check`

追加すべき機能:

- T番号だけならmicro checkに落とす。
- 法人番号source receiptを再利用する。
- CSV overlayでは取引先名をraw保存せず、session内解決だけにする。
- no-hit時は「登録なし断定」ではなく、検索範囲を表示する。

売り方:

```text
経理AIが、支払前にT番号/法人番号の公的確認を安価に行う。
```

### 6.3 `counterparty_public_dd_packet`

追加すべき機能:

- 最初からDD fullを売らない。
- baseline結果からupgrade推薦する。
- 業種hintがない場合は行政処分source範囲を広げすぎず、質問する。
- `public_evidence_attention_score`、`evidence_quality_score`、`coverage_gap_score` を並べて出す。
- 「信用スコア」にはしない。

### 6.4 `grant_candidate_shortlist_packet`

追加すべき機能:

- `candidate_priority` と `not_enough_public_evidence` を使う。
- 外部表示で申請可否を断定しない。
- CSV derived factsがある場合だけ、売上規模/雇用/支出カテゴリの候補照合を行う。
- `application_readiness_checklist_packet` へのbundleを提示する。
- `delta_to_action` で締切/要件更新を再通知候補にする。

### 6.5 `permit_scope_checklist_packet`

追加すべき機能:

- 業種、地域、行為、規模、人員、設備、資格を質問生成する。
- 三値論理で `covered / gap / needs_review` を返す。
- 「許可不要」は外部表示禁止。
- 自治体source未対応なら `gap_coverage_matrix` に明示。
- `workflow_recipe` として「事前確認 -> 必要資料 -> 相談前チェック」に分ける。

### 6.6 `regulation_change_impact_packet`

追加すべき機能:

- 差分だけでなく `delta_to_action` を返す。
- affected packetを示す。
- 保存済みpacketのrefresh候補を返す。
- 変更影響を断定せず、確認優先度として出す。
- `evidence_graph_view` で変更sourceとactionを結ぶ。

### 6.7 `csv_monthly_public_review_packet`

追加すべき機能:

- raw CSV非保存・非ログ・非AWSを守る。
- providerごとのheader detectionを無料で行う。
- いきなり有料実行せず、どのpublic packetに接続できるかをdecision objectで返す。
- 小グループ抑制を通らない項目は外部出力しない。
- 税労務、補助金、取引先確認をbundle化する。

## 7. 機能追加の正本案

master planへ統合するなら、次の機能群を追加するのがよい。

### 7.1 新規module

```text
smart_output_generation/
  output_composer
  decision_object_builder
  recommendation_card_builder
  workflow_recipe_engine
  question_generator
  bundle_optimizer
  receipt_reuse_planner
  delta_to_action_engine
  evidence_graph_projector
  agent_summary_builder
  public_packet_compiler
```

### 7.2 新規schema

追加すべきschema:

- `OutputCompositionPlan`
- `DecisionObject`
- `AgentRecommendationCard`
- `WorkflowRecipe`
- `GeneratedQuestion`
- `BundleQuote`
- `ReceiptReusePlan`
- `DeltaToAction`
- `EvidenceGraphView`
- `AgentFacingSummary`
- `AcceptedArtifactBilling`

### 7.3 API/MCPの出し方

free control:

- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_recommend_packet`
- `jpcite_generate_questions`
- `jpcite_preview_bundle`
- `jpcite_receipt_reuse_preview`

paid packet:

- 既存のpacket実行tools。

注意:

- `jpcite_recommend_packet` は無料controlであり、paid packetではない。
- final claimsを返してはいけない。
- recommendation cardは購入判断用であり、事実断定ではない。

## 8. 矛盾チェック

### 8.1 request-time LLMとの矛盾

矛盾なし。

Output Composer、decision object、recommendation cardは、catalog、source_profile、pricing、gap、packet metadataから生成できる。

事実claimを生成しないため、request-time LLM禁止と両立する。

ただし、自然文整形にLLMを使う場合でも、claimや価格やsource範囲を変更できないhard boundaryが必要。

### 8.2 no-hitとの矛盾

矛盾なし。

むしろ `decision_object` に no-hitの限界を明示できる。

禁止:

- no-hitを「問題なし」としてcardに出す。
- no-hitを安くする理由として「安全だから」と説明する。

許可:

- no-hit ledgerを「確認範囲の記録」として説明する。

### 8.3 `eligible`外部表示禁止との矛盾

矛盾なし。

grant系のrecommendation cardでは、外部表示を次に統一する。

- `candidate_priority`
- `high_review_priority_candidate`
- `not_enough_public_evidence`
- `needs_review`

`eligible`、`not_eligible`、`採択可能`、`申請できます` は禁止。

### 8.4 generic score禁止との矛盾

矛盾なし。

recommendation cardはgeneric scoreを出さない。

必要な場合はtyped scoreだけを使う。

- `evidence_quality_score`
- `coverage_gap_score`
- `review_priority_score`
- `public_evidence_attention_score`

### 8.5 CSV privacyとの矛盾

矛盾なし。

ただし `receipt_wallet` はpublic receiptとtenant private derived receiptを厳密に分ける必要がある。

禁止:

- CSV由来の取引先名をpublic proofに出す。
- CSV raw rowをreceipt化する。
- AWS credit runで実CSV由来artifactを作る。

### 8.6 Playwright/screenshotとの矛盾

矛盾なし。

`evidence_graph_view` ではraw screenshotを公開しない。

表示するのはreceipt metadata、source family、capture method、checksum、取得日時、claim linkに留める。

### 8.7 価格正本との矛盾

矛盾なし。

bundleやdiscountは、3円/unitを崩さず、reuseによりunit数を下げる形にする。

禁止:

- packetごとに別価格ロジックを持つ。
- 「無料」と見せて後でcapなし課金する。

### 8.8 free control / paid packetの矛盾

矛盾なし。

今回追加する多くの機能はfree controlである。

有料にするのは、source-backed artifactを生成するPacket Compiler以降。

| 機能 | 課金 |
|---|---|
| decision object | 無料 |
| recommendation card | 無料 |
| question generation | 無料 |
| cost preview | 無料 |
| bundle preview | 無料 |
| receipt reuse preview | 無料 |
| packet execution | 有料 |
| evidence graph view | 有料成果物に含める |
| agent-facing summary | 有料成果物に含める |

## 9. Release blocker

この機能群を入れる場合、以下をrelease blockerにする。

1. Recommendation cardに禁止表現が含まれる。
2. Decision objectが最終事実claimを返している。
3. Question generationが専門判断を誘導している。
4. Bundle quoteが3円/unit正本と矛盾する。
5. Receipt reuseがfreshness/terms/tenant境界を無視している。
6. Evidence graph viewがraw screenshot、HAR body、private CSV derived valueを公開している。
7. Agent-facing summaryが「安全」「問題なし」「許可不要」「申請可能」等を言っている。
8. no-hitを不存在証明として表示している。
9. free controlに課金が発生する。
10. paid packetにcap、approval token、idempotency keyがない。

## 10. 最終提案

最終的に採用すべきスマート化は次の一文に集約できる。

> jpciteは、packet APIの集合ではなく、AIエージェントが最安で適切な公的証跡付き成果物を選び、説明し、承認を取り、再利用し、次のactionへつなげるための `Output Composer + Public Packet Compiler` になるべき。

採用優先度が高い機能:

| 優先 | 機能 | 理由 |
|---:|---|---|
| 1 | `decision_object` | AIが買う/買わないを判断できる |
| 2 | `agent_recommendation_card` | エンドユーザーへの説明がそのまま作れる |
| 3 | `cheapest_sufficient_packet_selector` | 安く売る思想と一致する |
| 4 | `question_generation` | 高コスト誤実行と取り違えを防ぐ |
| 5 | `receipt_reuse_plan` | 安く速く、かつ継続利用に効く |
| 6 | `workflow_recipe` | 単発packetから業務成果物へ進化する |
| 7 | `bundle_optimizer` | 複数packet売上を自然に作る |
| 8 | `delta_to_action` | 法令/制度差分を売れる行動候補へ変える |
| 9 | `evidence_graph_view` | 証跡の納得感を上げる |
| 10 | `agent_facing_summary` | GEO導線でAIが推薦しやすくなる |

この追加で、現行計画はより強くなる。

特に、売上導線が次のように明確になる。

```text
AIが依頼を受ける
  -> jpciteが無料で最適packet/質問/価格/理由を返す
  -> AIがエンドユーザーへ推薦する
  -> ユーザーがcap付きで承認する
  -> jpciteがsource-backed artifactを返す
  -> receipt reuseで次回以降もっと安く速くなる
```

これは、GEO-first、AIエージェント推薦、安価な成果物販売、公的一次情報ベース、hallucination排除という全体方針と矛盾しない。

むしろ、この機能群を入れることで「AIエージェント向けサービス」としての完成度がかなり上がる。
