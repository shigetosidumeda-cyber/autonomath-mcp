# AWS final 12 review 02/12: revenue packets, pricing, and GEO paid path

作成日: 2026-05-15  
担当: 最終追加検証 2/12 / 成果物・売上・価格導線  
対象: master execution plan、packet taxonomy、pricing、GEO / MCP / OpenAPI関連文書  
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。  
出力: このMarkdownのみ。  

## 0. 結論

判定は **条件付きPASS**。

計画の中核はかなり正しい。

```text
AIエージェントがユーザーの依頼を読む
  -> 日本の公的一次情報・出典・取得日時・known gaps が必要だと判断
  -> jpcite の無料 route / preview / proof / catalog を見る
  -> エンドユーザーへ「このpacketなら安く買う価値がある」と説明
  -> ユーザーがcapを承認
  -> capped paid MCP/API packetを実行
  -> AIがsource_receipts / claim_refs / known_gapsを保持して成果物に加工
```

ただし、実装前に潰すべき残留矛盾がある。

特に重要なのは次の5点。

1. `agent_routing_decision` と `cost_preview_quote` はcatalog上に載せてよいが、外部表現では **paid packetではなくfree control** と明示する。
2. `jpcite_preview_cost` / `jpcite_cost_preview`、`jpcite_source_receipts` / `jpcite_source_receipt_ledger` のようなtool名揺れをcatalog正本で止める。
3. RC1の売り方は `source_receipt_ledger` 中心ではなく、`company_public_baseline` 中心にする。
4. `invoice_vendor_public_check` は同じ法人番号/インボイス基盤で作れるため、RC1.1ではなく **可能ならRC1 feature flag** で用意する。
5. 3円/unitは内部meterとして正しいが、エンドユーザー向けには「税込33円から」「330円/990円/3,300円のcap付きpacket」と見せる。`billable_units: 1` のような有料sampleは出さない。

よりスマートな計画にするなら、単にpacket順を並べ替えるのではなく、売上導線の主語を次に固定する。

> 「証跡台帳を売る」ではなく、「AIがエンドユーザーに頼まれた具体的な仕事を、安い公的source-backed packetで片付ける」。

`source_receipt_ledger` は商品価値があるが、初回購入CTAの主役ではない。主役は `company_public_baseline`、`invoice_vendor_public_check`、`counterparty_public_dd_packet`、`grant_candidate_shortlist_packet`、`permit_scope_checklist_packet`。

追加修正後の重点結論:

> 一番賢い改善は「packetの順番」ではなく、無料previewを **AI agentが購入推薦できる決定オブジェクト** に変えること。previewが、価格だけでなく、買う理由、買わない理由、必要入力、出力skeleton、known gaps、cap token導線、より安い代替packetまで返すようにする。

## 1. 確認した文書

主に以下を確認した。

| 文書 | 確認観点 |
|---|---|
| `aws_jpcite_master_execution_plan_2026-05-15.md` | 最終正本、RC1 paid/free、AWSと本体計画の順序 |
| `aws_final_consistency_10_final_sot.md` | 最終SOT、free controls、RC1/RC2/RC3、release blockers |
| `aws_final_consistency_04_revenue_packets_pricing.md` | 売上packet、価格、cap token、tool名修正案 |
| `aws_scope_expansion_27_packet_taxonomy.md` | packet taxonomy、source family、価格tier、MCP tool名 |
| `aws_scope_expansion_23_pricing_packaging_agent_sales.md` | 3円/unit、表示価格、preview、bundle、GEO sales copy |
| `aws_scope_expansion_24_agent_api_ux.md` | agent UX、MCP/OpenAPI導線、GEO proof page |

## 2. すでに整合している点

### 2.1 GEO-first

SEO記事で人間を集めるより、AIエージェントが読む `llms.txt`、`.well-known`、proof pages、agent-safe OpenAPI、MCP facadeを主導線にする方針は正しい。

AIが課金を推薦するには、以下が1分以内に分かる必要がある。

- 何の成果物か。
- いくらか。
- 無料previewできるか。
- 何が返るか。
- 何が返らないか。
- no-hitをどう扱うか。
- capを超えないか。
- どのMCP/APIを呼ぶか。

現在の正本はこの方向に寄っている。

### 2.2 `agent_routing_decision` 無料化

master planとfinal SOTでは、`agent_routing_decision` は無料controlとして整理済み。

これは必須。入口を有料にすると、AIがユーザーに推薦する前に詰まる。

### 2.3 `company_public_baseline` のRC1入り

`company_public_baseline` をRC1 paidに入れた修正は正しい。

理由:

- ユーザーの自然文が多い: 「この会社を公的情報で確認して」。
- 必要sourceがP0-Aに近い: 法人番号、インボイス、gBizINFO、EDINET metadata。
- 330円の説明がしやすい。
- AIが「無料preview後、税込330円上限なら買う価値あり」と言いやすい。
- `counterparty_public_dd_packet` や `invoice_vendor_public_check` へ自然に拡張できる。

### 2.4 価格正本

`3円税抜/unit` を唯一の内部meterにし、表示はpacket tierに寄せる方針は成立している。

正しい構造:

```text
internal_meter = 3 JPY ex-tax / unit
public_display = 33円 / 99円 / 330円 / 990円 / 3,300円 / 9,900円
paid_execution = preview + cap + approval token + idempotency
```

### 2.5 no-hitとno-charge

no-hitを不存在・安全・問題なしにしない方針は正しい。

また、no-hit-onlyを黙って課金しない設計も必要。これはユーザー信頼に直結する。

## 3. 残っている矛盾・改善点

### R-01: taxonomyではfree controlが「P0 packet」に見える

`aws_scope_expansion_27_packet_taxonomy.md` では、`agent_routing_decision` と `cost_preview_quote` がP0一覧に入っている。

catalogに載せること自体はよい。ただし、外部表示で「packet」と呼ぶと paid packet と混同される。

採用修正:

```json
{
  "artifact_type": "control",
  "packet_type": "agent_routing_decision",
  "charge_mode": "free",
  "billable": false,
  "shown_in_paid_packet_list": false
}
```

外部では次のように分ける。

| 区分 | 含めるもの |
|---|---|
| Free controls | `jpcite_route`, `jpcite_preview_cost`, catalog, proof lookup |
| Paid packets | `company_public_baseline`, `source_receipt_ledger`, `evidence_answer` など |

### R-02: MCP tool名がまだ揺れている

残留揺れ:

| 意味 | 古い/揺れた名前 | 採用名 |
|---|---|---|
| cost preview | `jpcite_cost_preview` | `jpcite_preview_cost` |
| source ledger | `jpcite_source_receipts` | `jpcite_source_receipt_ledger` |
| application/grant | `application_strategy`, `jpcite_application_packet` | `grant_candidate_shortlist_packet`, `jpcite_grant_shortlist` |
| CSV monthly | `client_monthly_review` | `csv_monthly_public_review_packet` |
| vendor risk | `vendor risk score` | `vendor_public_risk_attention_packet` |

採用修正:

- public MCP defaultにはcanonicalだけを出す。
- aliasは内部互換だけにする。
- alias responseには必ず `canonical_tool` と `canonical_packet_type` を返す。
- proof page、OpenAPI、MCP、pricing、examples、llmsでcanonical以外が主語になったらrelease blocker。

### R-03: RC1の売上順序がまだ少し証跡寄り

RC1 paid set:

```text
company_public_baseline
source_receipt_ledger
evidence_answer
```

この構成は実装検証としてはよい。ただし売上導線としては、`source_receipt_ledger` を主CTAにしすぎると弱い。

理由:

- エンドユーザーは「証跡台帳が欲しい」とは言いにくい。
- AI agent / developer / auditorには刺さるが、一般SMBには抽象的。
- 初回購入は「会社確認」「インボイス確認」「取引先確認」の方が自然。

採用修正:

RC1の実装scopeは維持してよいが、公開導線の優先順位は次にする。

| 表示順 | Packet | 役割 |
|---:|---|---|
| 1 | `company_public_baseline` | 初回購入の主CTA |
| 2 | `evidence_answer` | 広い質問のfallback |
| 3 | `source_receipt_ledger` | 出典・監査・agent向け補助CTA |

`source_receipt_ledger` はproof pageやAPI docsでは強く見せるが、人間向け販売文では「成果物に含まれる証跡」または「監査用追加packet」として見せる。

### R-04: `invoice_vendor_public_check` はRC1.1より前倒し候補

`invoice_vendor_public_check` は高頻度・低単価・反復性が強い。

しかも必要sourceは `company_public_baseline` とかなり重なる。

```text
identity_tax
invoice_registry
entity_resolution
receipt_builder
no_hit_ledger
```

採用修正:

- RC1の必須blockerにはしない。
- ただしAWS/fixture/catalog/API設計ではRC1から含める。
- 本番は `api.packet.invoice_vendor_public_check.enabled=false` で隠し、RC1が安定したらRC1.1で即ON。

スマートな理由:

- 初回売上だけでなく反復利用に向く。
- freee/MF/弥生CSV overlayの将来価値とも直結する。
- 税理士/BPO/経理AIが推薦しやすい。

### R-05: `evidence_answer` は便利だが曖昧になりやすい

`evidence_answer` は汎用入口として重要。ただし名前が広すぎるため、AIが何でも投げてくる危険がある。

採用修正:

`evidence_answer` のpreviewでは、必ず次を返す。

```json
{
  "recommended_more_specific_packet": "company_public_baseline | grant_candidate_shortlist_packet | permit_scope_checklist_packet | null",
  "why_not_specific_packet": "...",
  "forbidden_final_judgment_detected": false
}
```

方針:

- `evidence_answer` は広い質問のfallback。
- 具体成果物へ寄せられるなら、routeで縦packetへ誘導する。
- 有料実行前に「この依頼はcompany baselineの方が安く正確」と言えるようにする。

### R-06: 3円/unitと「数円から」の表現がまだ危険

内部meterとして1 unit = 3円税抜はよい。

ただしエンドユーザー/AI向けに「数円から」と言うと、3円で何か買えるように見える。

採用修正:

外部表現:

```text
無料preview。必要なら税込33円からのreceipt、99円/330円/990円/3,300円のcap付きpacket。
```

禁止:

```text
数円から買えます
3円で確認できます
billable_units: 1 の有料packet sample
```

### R-07: fixed priceとdynamic unitの境界が曖昧になりやすい

ユーザーには固定価格が分かりやすい。一方、実行時はsource数、receipt数、対象数でコストが変わる。

採用修正:

全paid packetに次を必須化する。

```json
{
  "included_scope": {
    "max_subjects": 1,
    "max_source_families": 6,
    "max_source_receipts": 25,
    "max_no_hit_checks": 20
  },
  "over_scope_behavior": "truncate_to_known_gaps_or_require_new_preview",
  "auto_overage_allowed": false
}
```

原則:

- 固定tierを超えたら勝手に追加課金しない。
- 追加調査は再previewとcap再承認。
- CSV/batch/portfolioだけ最初からdynamic capped runにする。

### R-08: approval tokenを最終SOTにもっと強く入れるべき

master planでは approval token が入っている。古いUX文書では API key + cap + idempotency の記述に寄っている箇所がある。

AI agent経由課金では、ユーザー承認済みcap tokenが必要。

採用正本:

```json
{
  "paid_execution_requires": [
    "api_key_or_session",
    "preview_id",
    "pricing_version",
    "cost_cap_jpy_inc_tax",
    "user_approved_cap_token",
    "idempotency_key"
  ]
}
```

MCP paid toolは、足りない場合に課金せず次を返す。

| Error | Charge | Agent action |
|---|---:|---|
| `cost_preview_required` | 0 | `jpcite_preview_cost` を呼ぶ |
| `user_approval_required` | 0 | preview文と承認URLをユーザーに提示 |
| `cap_token_required` | 0 | 承認済みcap tokenを取得 |
| `api_key_required` | 0 | API key / MCP setupへ誘導 |
| `idempotency_key_required` | 0 | agent側で安定keyを生成 |

### R-09: no-hit-only課金の扱いをcatalogに入れるべき

最終SOTでは方向性があるが、packetごとに明示しないと実装時に揺れる。

採用修正:

catalogに必須fieldを追加する。

```json
{
  "no_hit_billing_policy": {
    "default": "not_billed_when_no_hit_only",
    "billable_only_if_explicit_no_hit_receipt_requested": true,
    "not_billed_reason": "no_hit_only_without_explicit_no_hit_receipt"
  }
}
```

標準:

| 状態 | 課金 |
|---|---:|
| identity unresolved | 0 |
| invalid input | 0 |
| terms/source blocked before execution | 0 |
| no-hit-only and not explicitly requested | 0 |
| explicit no-hit receipt | Nano/Microで事前承認時のみ |
| mixed hit + no-hit ledger | 通常課金 |

### R-10: proof pageが無料で価値を漏らしすぎる可能性

GEOではproof pageが重要。ただし、実例を出しすぎると有料packetの価値を食う。

採用修正:

proof pageは次に限定する。

- public-safe sample subject
- syntheticまたは再配布許諾確認済みの例
- `example_excerpt` だけ
- full `source_receipts[]` は出さない
- high-value hitの全量は出さない
- paidで増える範囲を明示する

GEO crawlerには構造を見せ、人間/AIには価値を理解させる。ただし成果物の全量は無料で出さない。

### R-11: free previewの濫用対策が必要

無料previewは主導線なので広く開けるべき。ただし無制限だとagentやbotに叩かれる。

採用修正:

preview quotaはexecution quotaと別にする。

| Quota | 方針 |
|---|---|
| anonymous preview | IP/ASN/UAで低めに制御 |
| authenticated preview | 高めに許可 |
| known agent preview | agent id / client / refererで観測 |
| proof page crawl | GEO用に許可。ただし高価値JSON全量は出さない |
| paid execution | cap tokenとidempotency必須 |

### R-12: 決済導線は「毎回カード決済」にしない

33円/99円/330円packetを毎回checkoutすると、決済コストとUXが勝つ。

採用修正:

```text
internal_meter = 3円税抜/unit
external_payment = prepaid balance / capped wallet / monthly aggregated invoice / temporary checkout token
```

RC1では次のどれかを選ぶ。

| 導線 | 向く用途 |
|---|---|
| temporary cap token | AI経由の単発購入 |
| prepaid wallet | 低単価反復 |
| org monthly cap | API/MCPを継続利用する会社 |
| invoice/manual billing | 初期の法人検証 |

外部表示では「capを超えない」「承認なしに課金しない」を強く出す。

## 4. 順序ではなく、よりスマートな方法・機能・設計

ここが追加修正の主眼。

「どのpacketを先に出すか」より重要なのは、AI agentがエンドユーザーに対して自然に推薦し、ユーザーが安く納得して買える仕組みを作ること。

### S-01: 無料previewを「見積」ではなく「購入推薦decision object」にする

現在のpreviewは、価格、cap、必要入力、known gapsを返す設計になっている。これは正しいが、さらに賢くする余地がある。

AI agentが欲しいのは単なる価格ではなく、次の判断材料。

```text
この依頼にjpciteは役立つか
どのpacketが最も安く目的に合うか
買わない方がよい場合は何か
有料実行で何が返るか
ユーザーへどう説明すべきか
承認をどう取ればよいか
```

採用設計:

```json
{
  "preview_type": "agent_purchase_decision",
  "recommended_action": "buy_packet | ask_followup | skip_jpcite | use_free_guidance",
  "recommended_packet": "company_public_baseline",
  "cheaper_alternative_packet": "invoice_vendor_public_check",
  "why_buy": [
    "法人番号/インボイス/gBizINFOの公的source receiptを返せる",
    "AI単独回答より取得日時とknown gapsを保持できる"
  ],
  "why_not_buy": [
    "最終的な信用判断はできない",
    "非公開情報は扱えない"
  ],
  "required_inputs_now": ["company_name or corporate_number"],
  "optional_inputs_that_improve_output": ["address_hint", "t_number"],
  "expected_output_skeleton": {
    "claims_estimated": 4,
    "source_families": ["identity_tax", "invoice_registry", "corporate_activity"],
    "known_gaps_expected": ["EDINETは対象外の場合あり"]
  },
  "price_quote": {
    "jpy_inc_tax_max": 330,
    "cap_required": true
  },
  "approval": {
    "approval_token_required": true,
    "setup_url": "..."
  },
  "agent_recommendation_text_ja": "この確認は公的sourceと取得日時が重要なので、税込330円を上限にjpciteのcompany_public_baselineを取得する価値があります。"
}
```

これにより、preview自体がGEO上の販売員になる。

重要:

- previewは高価値hitを漏らさない。
- previewは「買うべき」と常に言わない。
- `skip_jpcite` も返す。これが信頼につながる。

### S-02: 「最安packet推薦」を組み込む

AI agentは、ユーザーに無駄な高いpacketを薦めると信頼を失う。

同じ依頼でも、安いpacketで足りる場合がある。

例:

| ユーザー依頼 | 高すぎる推薦 | より賢い推薦 |
|---|---|---|
| T番号を確認して | `counterparty_public_dd_packet` 990円 | `invoice_vendor_public_check` 99-330円 |
| 会社の基本情報を確認して | `counterparty_public_dd_packet` 990円 | `company_public_baseline` 330円 |
| 補助金を全部探して | heavy custom | まず `grant_candidate_shortlist_packet` 3,300円 |
| 許認可が関係しそうかだけ見て | full legal analysis | `permit_scope_checklist_packet` 3,300円、最終判断不可 |

採用アルゴリズム:

```text
candidate_packets = route(user_task)
for each packet:
  compute fit_score
  compute coverage_score
  compute price_score
  compute risk_of_overclaim
choose cheapest packet where:
  fit_score >= threshold
  coverage_score >= threshold
  forbidden_final_judgment == false
  expected_known_gaps are explainable
```

preview responseに必ず入れる。

```json
{
  "recommended_packet": "invoice_vendor_public_check",
  "not_recommended_packets": [
    {
      "packet": "counterparty_public_dd_packet",
      "reason": "ユーザー依頼はT番号確認だけなので990円DDは過剰"
    }
  ]
}
```

これにより「安く取れる」というコンセプトが実装される。

### S-03: 成果物skeletonをpreviewで見せる

ユーザーは「何が返るか」が分からないと買いにくい。

しかしfull outputを無料で出すと有料価値が漏れる。

採用設計:

previewでは `output_skeleton` を返す。

```json
{
  "output_skeleton": {
    "packet_type": "company_public_baseline",
    "will_include": [
      "resolved_subject",
      "source_receipts[]",
      "claim_refs[]",
      "known_gaps[]",
      "no_hit_checks[] if relevant",
      "billing_metadata"
    ],
    "will_not_include": [
      "final credit judgment",
      "safety guarantee",
      "non-public information",
      "legal/accounting advice"
    ],
    "example_excerpt_url": "/proof/packets/company-public-baseline#example"
  }
}
```

これにより、AI agentはユーザーに「買うと何が来るか」を説明できる。

### S-04: AI agent向けの recommendation card を返す

MCP/OpenAPI responseは、人間ではなくAI agentが読む。

そのため、有料推薦に必要な要素を1つのcardにまとめるべき。

採用設計:

```json
{
  "agent_recommendation_card": {
    "preserve_in_user_message": true,
    "headline_ja": "公的source付きで会社確認できます",
    "recommended_sentence_ja": "無料previewでは確認範囲と費用を見積もれます。実行する場合は税込330円を上限に承認してください。",
    "cost_line_ja": "最大税込330円。承認したcapを超えません。",
    "caveat_line_ja": "no-hitは不存在や安全の証明ではありません。",
    "approval_question_ja": "この上限額でjpciteの有料packetを実行しますか？",
    "must_preserve": [
      "price",
      "cap",
      "known_gaps",
      "no_hit_not_absence",
      "human_review_required"
    ]
  }
}
```

これがあると、AI agentが勝手に言い換えて危険な表現にする確率を下げられる。

### S-05: cap token導線を「agent-safe checkout」にする

AI agentはカード番号や決済詳細を扱うべきではない。

採用導線:

```text
1. agent calls preview
2. preview returns setup_url / approval_url
3. user opens jpcite page
4. user approves packet, price, cap, scope
5. jpcite issues short-lived cap token
6. agent calls paid packet with cap token + preview_id + idempotency_key
7. output returns billing_metadata
```

cap tokenは以下を含む。

```json
{
  "cap_token_scope": {
    "packet_type": "company_public_baseline",
    "preview_id": "cpv_...",
    "max_jpy_inc_tax": 330,
    "max_subjects": 1,
    "expires_at": "...",
    "single_use": true
  }
}
```

これにより、agentが課金権限を持ちすぎない。

### S-06: 商品は単発packetだけでなく「task pack」に束ねる

packet単体はAPI的にはよいが、エンドユーザーは業務単位で理解する。

割引bundleではなく、cap preset付きのtask packとして見せる。

| Task pack | 内部packet | 価格/上限の見せ方 |
|---|---|---|
| 取引先確認pack | `company_public_baseline` + `invoice_vendor_public_check` + optional `counterparty_public_dd_packet` | 330円から、DD込み990円上限 |
| 補助金準備pack | `grant_candidate_shortlist_packet` + `application_readiness_checklist_packet` | 3,300円から、追加checklistは再preview |
| 許認可確認pack | `permit_scope_checklist_packet` + local/procedure sources | 3,300円上限 |
| 月次会計public review pack | CSV derived facts + `invoice_vendor_public_check` + `tax_labor_event_radar_packet` | cap制、raw CSV非保存 |
| 制度変更watch pack | `regulation_change_impact_packet` + `policy_change_watch` | 月次cap preset |

重要:

- task packは割引ではない。
- task packは「どのpacketを組み合わせるか」の見せ方。
- 内部課金は3円/unitのまま。
- capとincluded scopeを明示する。

### S-07: 既存receipt再利用で安く速くする

同じ公的sourceを毎回取り直すと遅く、高くなる。

ただし「古い情報を最新として出す」のは危険。

採用設計:

```text
freshness-aware receipt reuse
```

previewで返す。

```json
{
  "receipt_reuse": {
    "reusable_receipts_available": true,
    "freshness_ttl_status": "within_ttl",
    "will_refresh_sources": ["invoice_registry"],
    "will_reuse_sources": ["identity_tax"],
    "price_effect": "same_or_lower_cap",
    "freshness_caveat": "取得日時を出力に明示"
  }
}
```

これにより、安さと速さを両立できる。

禁止:

- 古いreceiptを最新確認として見せる。
- reuseであることを隠す。
- no-hit cacheを不存在証明にする。

### S-08: 追加質問を最小化する

AI agent経由では、質問が多すぎると離脱する。

採用設計:

previewは `blocking_questions` と `optional_questions` を分ける。

```json
{
  "blocking_questions": [
    {
      "field": "company_name_or_corporate_number",
      "reason": "対象同定に必須"
    }
  ],
  "optional_questions": [
    {
      "field": "address_hint",
      "reason": "同名法人の絞り込みに有効"
    }
  ],
  "can_run_without_optional_questions": true
}
```

これにより、agentはユーザーに最低限だけ聞ける。

### S-09: 成果物生成は「claim graph + renderer hints」にする

jpciteは最終文章をLLM生成しない方針だが、AI agentが最終成果物に加工しやすくする必要がある。

採用設計:

packet outputに `agent_rendering_hints` を含める。

```json
{
  "agent_rendering_hints": {
    "suitable_outputs": [
      "取引先確認メモ",
      "稟議添付用source一覧",
      "顧問先への確認依頼メール"
    ],
    "recommended_structure": [
      "確認できたこと",
      "確認できなかったこと",
      "追加で聞くこと",
      "専門家確認が必要な点"
    ],
    "must_not_rephrase_as": [
      "安全です",
      "問題ありません",
      "許可不要です"
    ]
  }
}
```

これにより、jpciteは「文章生成AI」ではなく「AIが成果物化しやすい構造化証拠」を売れる。

### S-10: preview段階で「買わない理由」を返す

売上だけを見ると買わせたくなるが、AI agentに信頼されるにはskip判断が重要。

採用設計:

```json
{
  "do_not_buy_reasons": [
    "ユーザーは最終法務判断を求めている",
    "非公開情報が必要",
    "公的source coverageが弱い",
    "無料guidanceで足りる"
  ],
  "free_guidance": {
    "suggested_next_step": "法人番号またはT番号を確認してから再previewしてください"
  }
}
```

これにより、AIは無理に課金を薦めず、結果として長期的な推薦率が上がる。

### S-11: no-hitを「売らない」のではなく「確認範囲の価値」にする

no-hit-onlyは原則非課金でよい。

ただし、ユーザーが明示的に「この範囲を確認した証跡がほしい」と言う場合は、Nano/Microのno-hit receiptとして価値がある。

採用商品:

```text
checked_scope_receipt
```

外部文言:

```text
指定した公的sourceと期間で確認した範囲の証跡です。不存在・安全・問題なしの証明ではありません。
```

これは監査、稟議、問い合わせ対応で売れる可能性がある。

### S-12: GEO proof pageを「商品説明」ではなく「agent decision page」にする

proof pageは人間LPではなく、AI agentが推薦判断するページにする。

必須section:

```text
When to recommend
When not to recommend
Cheapest sufficient packet
Free preview behavior
Paid output skeleton
Price/cap examples
No-hit policy
Human review boundary
MCP/OpenAPI call sequence
Agent wording to preserve
```

通常のLP文言より、AIがそのままユーザーに説明できる短文を優先する。

### S-13: 成果物別の「支払い意思」をpreviewで推定する

売上を上げるには、高いpacketを並べるより、支払い意思がある場面を捉える必要がある。

採用score:

```text
purchase_intent_score =
  urgency_score
  * repeatability_score
  * public_source_fit_score
  * price_fit_score
  * output_clarity_score
  * risk_of_forbidden_judgment_penalty
```

高い例:

- 契約前の取引先確認
- T番号/法人番号確認
- 締切が近い補助金
- 許認可の事前確認
- 月次CSVレビュー

低い例:

- 雑談
- 一般知識
- 最終法務判断
- 非公開情報が中心
- ニュース感想

previewはこのscoreを内部利用し、外部には `recommended_action` と理由だけ返す。

### S-14: 「安さ」を単価でなく削減時間で説明する

3,300円は高く見えることがあるが、補助金/許認可/制度変更では人間の調査時間を大きく減らせる。

agent向けには、価格だけでなく削減される作業を返す。

```json
{
  "value_explanation": {
    "manual_work_reduced": [
      "公式source探索",
      "取得日時とURLの保存",
      "条件表の確認",
      "known gapsの整理",
      "次に聞く質問の生成"
    ],
    "not_replaced": [
      "専門家判断",
      "最終申請可否",
      "個別事情の判断"
    ]
  }
}
```

これにより、AIは「なぜ330円/990円/3,300円を払う価値があるか」を説明できる。

### S-15: 商品化は「packet」だけでなく「agent workflow recipe」にする

AI agentが売上を作るには、単一toolだけでなくworkflowが必要。

採用するrecipe:

```json
{
  "recipe_id": "vendor_onboarding_public_check",
  "steps": [
    "jpcite_route",
    "jpcite_preview_cost",
    "jpcite_company_baseline",
    "jpcite_invoice_vendor_check",
    "jpcite_counterparty_dd_optional"
  ],
  "approval_points": [
    "before_paid_packet",
    "before_optional_dd"
  ],
  "stop_conditions": [
    "identity_unresolved",
    "cap_rejected",
    "forbidden_final_judgment"
  ]
}
```

公開するrecipe例:

- `vendor_onboarding_public_check`
- `grant_application_prep`
- `regulated_business_precheck`
- `monthly_accounting_public_review`
- `policy_change_watch_setup`

これがあると、AI agentは「どう使うか」を迷わない。

### S-16: 無料previewで「次の一手」を売る

previewは有料実行だけに誘導する必要はない。

有料実行しない場合でも次の一手を返す。

```json
{
  "next_best_action": {
    "type": "ask_user_for_input | buy_packet | use_free_public_link | skip",
    "message_ja": "法人番号または所在地を入力すると、330円上限で公的baselineを取得できます。"
  }
}
```

これにより、preview自体がCVR改善のUIになる。

### S-17: 課金対象は「API呼び出し」ではなく「accepted artifact」にする

売上と信頼を両立するには、APIを呼んだだけで課金しない。

採用正本:

```text
charge only when accepted_artifact_created = true
```

課金される条件:

- paid packet outputが生成された。
- `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata` が揃った。
- cap内。
- approval token有効。
- idempotency重複ではない。

課金しない条件:

- invalid input。
- identity unresolved。
- preview required。
- source blocked before execution。
- no-hit-only without explicit no-hit receipt。
- release gate failure。

これはAI agentに説明しやすく、課金不信を下げる。

### S-18: `source_receipt_ledger` を裏方価値として商品化する

`source_receipt_ledger` は単独販売より、他packetの信頼を高める裏方として強い。

採用方法:

1. すべてのpaid packetに小さなreceipt ledgerを内包。
2. 追加で「full receipt ledger export」を有料optionalにする。
3. agent/developer向けには `source_receipt_ledger` 単体を残す。

外部表現:

```text
通常packetには確認に使ったsource receiptの要約が含まれます。監査・稟議用に完全なreceipt ledgerが必要な場合だけ追加できます。
```

これなら抽象的な証跡台帳を、実業務の付加価値に変換できる。

### S-19: AWS成果物を「商品素材」だけでなく「販売素材」にする

AWSで作るべきものはsource dataだけではない。

売上に直結するAWS成果物:

| Artifact | 売上上の用途 |
|---|---|
| `agent_recommendation_cards.jsonl` | AIがユーザーに推薦する文面の検証 |
| `do_not_buy_examples.jsonl` | 無理な課金推薦を防ぐ |
| `preview_response_fixtures.jsonl` | previewのCVRと安全性を検証 |
| `output_skeleton_examples.jsonl` | proof pageとagent説明に使う |
| `task_recipe_catalog.json` | AI workflowとして売る |
| `accepted_artifact_billing_fixtures.jsonl` | 課金条件のテスト |
| `public_safe_example_excerpts.jsonl` | GEO proof用 |
| `cheap_alternative_routing_eval.jsonl` | 最安packet推薦の評価 |

これにより、AWS credit runが単なるデータ収集ではなく、商品化・GEO・課金導線の素材生成になる。

### S-20: AI agentに「推薦してよい条件」と「推薦してはいけない条件」を機械可読で渡す

`llms.txt`だけでは弱い。packet catalogに推薦ポリシーを入れる。

```json
{
  "recommendation_policy": {
    "recommend_when": [
      "user asks for Japanese public-source business evidence",
      "source URL and fetched timestamp matter",
      "output can be evidence packet/checklist/candidate list"
    ],
    "do_not_recommend_when": [
      "final legal/tax/accounting/credit/safety judgment requested",
      "private or non-public data is required",
      "user refuses known gaps or human review boundary",
      "free public link is sufficient"
    ],
    "must_ask_user_before_paid_call": true
  }
}
```

これがあると、agentが勝手に課金したり、過剰推薦したりするリスクを下げられる。

## 5. 補足: packet順序の扱い

### 5.1 実装順と販売順を分ける

実装順:

1. catalog/pricing/preview/approval token
2. `source_receipt_ledger`
3. `evidence_answer`
4. `company_public_baseline`
5. `invoice_vendor_public_check`
6. `counterparty_public_dd_packet`

販売順:

1. `company_public_baseline`
2. `invoice_vendor_public_check`
3. `counterparty_public_dd_packet`
4. `grant_candidate_shortlist_packet`
5. `permit_scope_checklist_packet`
6. `source_receipt_ledger`
7. `evidence_answer`

理由:

- 実装では証跡/汎用基盤を先に作る必要がある。
- 売るときはユーザーの自然な依頼から入る方が強い。

### 5.2 推奨release train

#### RC0: 無料control

```text
jpcite_route
jpcite_preview_cost
jpcite_get_packet_catalog
jpcite_get_proof
```

目的:

- AIがjpciteを推薦できる状態を作る。
- 課金前に価格、gap、必要入力、禁止用途を理解させる。

#### RC1: limited paid

必須:

```text
company_public_baseline
source_receipt_ledger
evidence_answer
```

ただし公開CTAの順序:

```text
1. company_public_baseline
2. evidence_answer
3. source_receipt_ledger
```

feature flag候補:

```text
invoice_vendor_public_check
```

#### RC1.1: low-friction repeat packets

```text
invoice_vendor_public_check
counterparty_public_dd_packet
```

ここでpreview-to-paid率、平均cap、no-charge率、repeat率を見る。

#### RC2: high-ticket task packets

```text
grant_candidate_shortlist_packet
application_readiness_checklist_packet
permit_scope_checklist_packet
administrative_disposition_radar_packet
regulation_change_impact_packet
```

3,300円級の価値を出しやすい。

#### RC3: recurring and batch

```text
csv_monthly_public_review_packet
tax_labor_event_radar_packet
portfolio_public_monitor_packet
subsidy_watchlist_delta_packet
policy_change_watch
```

ここは反復売上が大きいが、privacy、suppression、billing reconciliation、cap tokenが完全に通ってから出す。

## 6. 成果物から逆算した販売ストーリー

AIエージェントがエンドユーザーに推薦しやすい自然文は次。

| ユーザー依頼 | 推薦packet | 価格感 | AIが言える価値 |
|---|---|---:|---|
| この会社を公的情報で確認して | `company_public_baseline` | 330円 | 法人番号/インボイス/gBizINFO等の確認範囲と不足を返せる |
| この請求書のT番号を確認して | `invoice_vendor_public_check` | 99-330円 | 経理確認を安く反復できる |
| 契約前に取引先を確認して | `counterparty_public_dd_packet` | 990円 | 公的source上の確認範囲と注意情報をまとめる |
| 使える補助金を探して | `grant_candidate_shortlist_packet` | 3,300円 | 候補、根拠、足りない入力、締切を返す |
| 申請に何が必要か整理して | `application_readiness_checklist_packet` | 990-3,300円 | 必要書類/不足入力/窓口質問を作る |
| この事業に許認可が関係しそうか | `permit_scope_checklist_packet` | 3,300円 | 三値論理で確認事項と追加質問を返す |
| 最近の制度変更の影響を見て | `regulation_change_impact_packet` | 990-3,300円 | 法令/通達/告示差分から影響候補を返す |
| CSVから月次の注意点を見て | `csv_monthly_public_review_packet` | cap制 | raw CSVを保存せず派生factsと公的情報を重ねる |

## 7. catalog正本に追加すべきfield

実装前に `packet_catalog.canonical.json` へ以下を入れる。

```json
{
  "packet_type": "company_public_baseline",
  "artifact_type": "paid_packet",
  "launch_phase": "RC1",
  "canonical_mcp_tool": "jpcite_company_baseline",
  "aliases": [],
  "charge_mode": "paid_capped",
  "unit_price_jpy_ex_tax": 3,
  "unit_price_jpy_inc_tax": 3.3,
  "default_units": 100,
  "display_price_jpy_inc_tax": 330,
  "minimum_public_price_jpy_inc_tax": 33,
  "free_preview_required": true,
  "approval_token_required": true,
  "idempotency_required": true,
  "external_costs_included": false,
  "included_scope": {
    "max_subjects": 1,
    "max_source_families": 6,
    "max_source_receipts": 25
  },
  "over_scope_behavior": "truncate_to_known_gaps_or_require_new_preview",
  "no_hit_billing_policy": {
    "default": "not_billed_when_no_hit_only",
    "explicit_no_hit_receipt_allowed": true
  },
  "must_preserve": [
    "source_receipts[]",
    "claim_refs[]",
    "known_gaps[]",
    "gap_coverage_matrix[]",
    "billing_metadata",
    "request_time_llm_call_performed=false",
    "no_hit_not_absence"
  ],
  "must_not_claim": [
    "safe",
    "no issue",
    "eligible",
    "permission not required",
    "credit score",
    "proved absent"
  ]
}
```

## 8. GEO page / MCP / OpenAPIの必須統一

同じpacketについて、次が完全一致していなければrelease blocker。

| Surface | 一致させる項目 |
|---|---|
| public proof page | packet名、価格、cap、preview、known gaps |
| pricing page | unit、税込/税抜、included scope |
| MCP tool | canonical tool名、preview必須、approval token必須 |
| OpenAPI | operationId、route、request/response schema |
| `llms.txt` | when to use、do not use、cost/cap |
| `.well-known` | catalog hash、pricing hash、MCP/OpenAPI URL |
| runtime response | `billing_metadata`, `pricing_version`, `charged`, `not_billed_reason` |

古い名前は公開面では主語にしない。

## 9. 最終release blockers

売上・価格導線の観点では、以下が1つでも残れば本番paid launchを止める。

| Blocker | 理由 |
|---|---|
| `agent_routing_decision` が有料扱い | GEO入口を塞ぐ |
| `jpcite_cost_preview` と `jpcite_preview_cost` が混在 | agentが誤routeする |
| `jpcite_source_receipts` が主tool名として公開 | canonical不一致 |
| `application_strategy` / `client_monthly_review` が公開主語 | packet名が古い |
| `数円から` という外部表現 | 価格誤認 |
| paid sampleに `billable_units: 1` | 3円で買える誤解 |
| previewなしでpaid execution可能 | 課金事故 |
| approval tokenなしでagent paid execution可能 | ユーザー承認不明 |
| cap超過時に自動追加課金 | 信頼毀損 |
| no-hit-onlyを黙って課金 | 信頼毀損 |
| proof pageにfull paid outputを掲載 | 有料価値漏れ |
| public page価格とruntime preview価格が違う | 課金不信 |
| `source_receipts[]` / `claim_refs[]` / `known_gaps[]` 欠落 | 商品価値消失 |

## 10. 最終採用案

### 10.1 もっともスマートな販売構造

```text
Free:
  - route
  - cost preview
  - proof/catalog
  - no-hit/cap/known gaps説明

Low-friction paid:
  - company_public_baseline
  - invoice_vendor_public_check
  - counterparty_public_dd_packet

High-value paid:
  - grant_candidate_shortlist_packet
  - application_readiness_checklist_packet
  - permit_scope_checklist_packet
  - regulation_change_impact_packet

Recurring/batch:
  - csv_monthly_public_review_packet
  - tax_labor_event_radar_packet
  - watchlist / portfolio capped runs
```

### 10.2 RC1で絶対に証明すること

RC1の目的は「最大売上」ではない。以下の導線が本当に通るかを証明すること。

```text
AIがjpciteを発見
  -> free preview
  -> ユーザーに330円/990円capを説明
  -> cap token承認
  -> paid packet実行
  -> source-backed output返却
  -> AIが最終回答にreceipt/gap/no-hit caveatを保持
```

この証明に最適な有料packetは `company_public_baseline`。

### 10.3 RC1.1で売上を取りに行くpacket

RC1が通ったら、すぐに以下をONにする。

```text
invoice_vendor_public_check
counterparty_public_dd_packet
```

ここが最初の売上観測に一番向く。

見る指標:

- preview_calls
- preview_to_paid_rate
- average_approved_cap_jpy
- no_charge_rate
- repeat_user_rate
- repeat_agent_rate
- agent_recommendation_text_preservation_rate
- pricing_drift_count
- billing_reconciliation_error_count

## 11. まとめ

これ以上大きく別の計画に変える必要はない。

ただし、よりスマートにするなら「順番」ではなく次の機能設計を入れる。

1. 無料previewを単なる見積ではなく、`agent_purchase_decision` として返す。
2. previewで最安packet、買う理由、買わない理由、出力skeleton、必要入力、cap token導線を返す。
3. AI agentがそのままユーザーに提示できる `agent_recommendation_card` を返す。
4. paid executionはAPI呼び出しではなく、`accepted_artifact_created=true` の成果物生成に対してだけ課金する。
5. 単発packetだけでなく、`vendor_onboarding_public_check` などの agent workflow recipe と task pack を公開する。
6. 既存receiptはfreshness-awareに再利用し、取得日時とTTLを明示して安く速くする。
7. `source_receipt_ledger` は初回販売の主役ではなく、各packetに内包される信頼機能 + 監査用optionalとして商品化する。
8. `agent_routing_decision` / `cost_preview_quote` はpaid packetとは別枠のfree controlにする。
9. 3円/unitは内部meter、外部は税込tierとcapで説明する。
10. approval token、cap、idempotency、preview_id、pricing_versionをpaid execution必須にする。
11. no-hit-onlyは原則非課金。明示的なchecked-scope receipt購入時だけ課金する。
12. tool名とpacket名はcatalog正本から生成し、古い名前が公開面に出たらdeployを止める。

この修正を入れれば、計画は「packetを順番に売るサービス」ではなく、AIエージェントが無料previewを通じて **買うべき成果物・買わないべき理由・上限額・出力skeleton** を判断し、エンドユーザーに自然に推薦できる **低単価・高反復・証跡付き成果物サービス** になる。
