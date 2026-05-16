# AWS scope expansion 13: algorithmic output engine

作成日: 2026-05-15  
担当: 拡張深掘り 13/30 / 成果物生成アルゴリズム総論  
対象: jpcite 本体計画、AWS credit run、GEO-first organic acquisition、AI agent向けMCP/API  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

jpcite の中核は「LLMに自由生成させる成果物」ではなく、「公的一次情報と入力由来の安全な派生factを、再現可能なアルゴリズムで束ねる成果物生成エンジン」である。

エンドユーザーがAIに頼む自然な要求は、検索ではなく成果物である。

```text
この会社を契約前に公的情報で確認して。
この補助金を使えそうか、準備すべきことを整理して。
この業種で必要そうな許認可や制度を、根拠付きで出して。
このCSVから、取引先や制度候補の確認リストを安く作って。
法令や制度の変更が、自社に関係しそうか一次情報ベースで見て。
```

この要求に対して、jpcite が返すべき価値は「もっともらしい文章」ではない。

返すべきものは次である。

1. 何を確認したか。
2. どの一次情報を使ったか。
3. どのclaimがどのsource_receiptに支えられているか。
4. どこは未確認か。
5. no-hitを不存在・安全・適法・許可不要へ誤変換していないか。
6. どの決定表、制約、スコア、差分、証拠グラフで成果物を構成したか。
7. 人間・専門家・窓口に確認すべき点は何か。

したがって成果物生成エンジンの基本方針は次になる。

```text
Public primary sources + private safe derived facts
  -> source_receipts
  -> claim_refs
  -> evidence graph
  -> deterministic rules / constraint solving / scoring / diff detection
  -> packet sections
  -> AI-agent safe output
```

request-time LLM は使わない。使うとしても、AWS credit run で公開資料に対する候補抽出をオフラインに行い、span付き・receipt付き・gate付きの candidate fact に限定する。成果物そのものの主張は、必ず source_receipts / claim_refs / known_gaps に戻れる必要がある。

## 1. Product thesis

### 1.1 ユーザーはデータではなく成果物を買う

公的一次情報を大量に取るだけでは、AI agentは次のように判断しやすい。

```text
これは検索キャッシュであり、ユーザーに追加課金を薦めるほどではない。
```

一方、次の形で返せるなら課金理由が明確になる。

```text
このpacketは350円で、公式source receipt、確認範囲、未確認範囲、
次に聞くべき質問、稟議や相談に使える表まで返します。
通常のWeb検索より安く、速く、引用可能です。
```

つまり jpcite の商品は「source cache」ではなく「source-backed output packet」である。

### 1.2 AI agentが推薦しやすい条件

AI agent がエンドユーザーに jpcite 課金を薦めるには、次が必要である。

| 条件 | jpcite側の実装 |
|---|---|
| 価格が安い | free preview、micro packet、standard packetを分ける |
| 何が返るか明確 | packet catalog、example packet、OpenAPI/MCP examples |
| 公式根拠がある | `source_receipts[]` と `claim_refs[]` |
| 未確認範囲が明示される | `known_gaps[]` と no-hit semantics |
| AIが回答に組み込みやすい | sectioned JSON、citation-ready claims、receipt ledger |
| 危険な断定をしない | forbidden claim gate、disclaimer boundary |
| 繰り返し使える | entity/month/program/source単位の課金とmonitoring |

成果物生成アルゴリズムは、この推薦条件を満たすための内部エンジンである。

## 2. Non-negotiable boundaries

### 2.1 禁止すること

以下は成果物生成エンジンで禁止する。

| 禁止 | 理由 | 代替 |
|---|---|---|
| LLM自由生成による主張 | hallucination risk | claim_refsに基づくtemplate assembly |
| no-hitを不存在へ変換 | 公的sourceのcoverage限界がある | `no_hit_not_absence` と coverage note |
| 許認可充足の断定 | 法務/行政判断に見える | permit candidates + human review |
| 採択可能性の予測 | 不採択母集団がなく誤解される | `fit_score`, `review_priority` |
| 税務処理の正誤判定 | 税務判断に見える | CSV data quality / public cross-check |
| 信用スコア | 与信判断に見える | public evidence binder / review queue |
| raw CSVの保存・表示 | privacy risk | header/profile/aggregate only |
| 個人情報・給与・銀行明細の成果物化 | leakage risk | suppression + leak scan |
| CAPTCHA突破、ログイン突破、アクセス制限回避 | terms/security risk | public pages only, fail closed |

### 2.2 必須フィールド

すべての成果物は次を持つ。

```json
{
  "packet_id": "pkt_xxx",
  "packet_type": "counterparty_public_check",
  "schema_version": "2026-05-15",
  "algorithm_version": "algo-output-engine-v0.1.0",
  "corpus_snapshot_id": "public-corpus-YYYYMMDD",
  "request_time_llm_call_performed": false,
  "input_scope": {},
  "sections": [],
  "claim_refs": [],
  "source_receipts": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "human_review_required": [],
  "billing_metadata": {},
  "_disclaimer": {
    "not_legal_advice": true,
    "not_tax_advice": true,
    "not_financial_advice": true,
    "no_hit_not_absence": true
  }
}
```

必須ルール:

- `claim_refs[]` に戻れない断定文は出さない。
- `source_receipts[]` に戻れない `claim_ref` は `support_level=unbacked` とし、通常は表示しない。
- `known_gaps[]` は品質低下ではなく、成果物の価値そのものである。
- `human_review_required[]` は専門家・窓口・ユーザー確認へ分解する。

## 3. Core architecture

### 3.1 Layer model

成果物生成エンジンは、次の層に分ける。

```text
L0 source_profile
  出典の所有者、公式性、terms、取得方式、更新頻度、公開可否

L1 source_document
  取得したHTML/PDF/API/CSV/画像/スクリーンショット等

L2 source_receipt
  取得・観測・検索・no-hit・抽出の証跡

L3 claim_ref
  AIが再利用できる最小fact

L4 evidence_graph
  claim, receipt, entity, source, packet, gap の関係

L5 algorithm_trace
  決定表、制約、スコア、差分、探索、集約の実行記録

L6 packet_section
  成果物内の表、リスト、チェックリスト、質問、台帳

L7 public proof / API / MCP
  AI agentが発見し、エンドユーザーへ推薦できる公開面
```

この分離により、表現やUIを後から変えても、根拠と計算過程は変わらない。

### 3.2 Evidence graph

証拠グラフは次のノードとエッジで構成する。

| Node | 例 | 意味 |
|---|---|---|
| `entity` | company, program, law, permit, public_notice | 主体 |
| `source_profile` | NTA, e-Gov, MLIT, local gov | 出典契約 |
| `source_document` | HTML, PDF, API payload, screenshot | 取得物 |
| `source_receipt` | positive hit, no-hit, fetch, OCR, parse | 観測証跡 |
| `claim_ref` | program.deadline, company.address | 最小fact |
| `known_gap` | stale, ambiguous identity, coverage_limited | 限界 |
| `algorithm_trace` | rule_eval, constraint_result, score_component | 計算過程 |
| `packet` | paid/free output | 成果物 |

| Edge | 例 | ルール |
|---|---|---|
| `document_observed_by_receipt` | PDF -> receipt | hashと取得時刻を持つ |
| `receipt_supports_claim` | receipt -> claim | support_levelを持つ |
| `claim_used_in_trace` | claim -> score_component | feature単位で接続 |
| `gap_affects_claim` | gap -> claim | gap severityを持つ |
| `trace_generates_section` | score -> ranked list | 出力sectionへ接続 |
| `packet_includes_receipt` | packet -> receipt | packet内で参照可能 |

support precedence:

```text
direct > derived > weak > no_hit_not_absence > unbacked
```

`no_hit_not_absence` は実体claimを支えない。支えられるのは「このsource集合をこのqueryで検索し、該当が見つからなかった」という検査claimだけである。

### 3.3 Algorithm trace

すべての計算は `algorithm_trace` として記録する。

```json
{
  "trace_id": "trace_...",
  "algorithm_id": "constraint_permit_precheck",
  "algorithm_version": "0.1.0",
  "input_claim_ids": ["claim_..."],
  "input_receipt_ids": ["sr_..."],
  "parameters": {
    "threshold": 0.72,
    "rulebook_version": "permit-rules-2026-05-15"
  },
  "outputs": {
    "result_id": "res_...",
    "label": "review_candidate",
    "score": 74.2
  },
  "known_gap_ids": ["gap_..."],
  "generated_at": "2026-05-15T00:00:00+09:00"
}
```

このtraceにより、後から「なぜこのpacketがこの候補を出したか」を説明できる。

## 4. Standard pipeline

### 4.1 Pipeline overview

```text
1. User/AI intent normalization
2. Packet type selection
3. Input safety classification
4. Source coverage plan
5. Entity and identity resolution
6. Feature extraction
7. Evidence graph construction
8. Algorithm execution
9. Output section assembly
10. Quality gates
11. Cost/billing metadata
12. API/MCP/proof surface rendering
```

### 4.2 Step 1: User/AI intent normalization

ユーザー要求は、直接自由回答へ渡さない。まず成果物型に落とす。

| User intent | Packet candidates | Safe handling |
|---|---|---|
| 取引先を確認して | `counterparty_public_check`, `vendor_onboarding_evidence_pack` | 安全/信用の断定は禁止 |
| 使える補助金を探して | `application_strategy_pack`, `grant_candidate_shortlist` | 採択可否は禁止 |
| 許認可が必要か見て | `permit_precheck_pack` | 許認可不要の断定は禁止 |
| 法改正の影響を知りたい | `legal_regulatory_change_impact` | 法的助言は禁止 |
| CSVを見てほしい | `csv_overlay_review`, `monthly_client_review` | raw CSV保存禁止 |
| 入札候補を探して | `procurement_opportunity_pack` | 参加資格充足の断定禁止 |

intent classifier の出力:

```json
{
  "intent_id": "intent_...",
  "candidate_packet_types": [
    {"packet_type": "counterparty_public_check", "priority": 1},
    {"packet_type": "source_receipt_ledger", "priority": 2}
  ],
  "forbidden_claim_risk": ["credit_safety", "legal_validity"],
  "required_inputs": ["company_name_or_number"],
  "preview_allowed": true
}
```

### 4.3 Step 2: Packet type selection

packet catalog には、成果物ごとの入力、source、アルゴリズム、価格、禁止線を登録する。

```json
{
  "packet_type": "counterparty_public_check",
  "billable_unit": "subject",
  "default_price_tier": "standard",
  "required_sources": ["identity_tax"],
  "optional_sources": ["invoice_registry", "enforcement_safety", "procurement_contract"],
  "algorithms": [
    "entity_identity_resolution",
    "public_status_ledger",
    "no_hit_scope_builder",
    "evidence_binder_assembler"
  ],
  "forbidden_labels": ["safe", "no_problem", "creditworthy"],
  "output_sections": [
    "identity_candidates",
    "public_registry_hits",
    "public_notice_hits",
    "no_hit_scope",
    "known_gaps",
    "review_questions"
  ]
}
```

### 4.4 Step 3: Input safety classification

入力は次に分類する。

| Class | 例 | 保存方針 |
|---|---|---|
| `public_identifier` | 法人番号、T番号、公的登録番号 | 保存可 |
| `public_query` | 会社名、制度名、自治体名 | packet log可。ただし最小化 |
| `private_profile` | 業種、地域、従業員数、予定投資 | tenant scoped |
| `private_csv_raw` | freee/MF/弥生CSV raw | 保存禁止 |
| `private_csv_derived` | 行数、期間、列profile、集計bucket | tenant scoped / aggregate only |
| `sensitive_personal` | 個人名、給与、銀行、医療 | suppression or reject |

CSVはAWSへ上げない。AWS credit run では synthetic/header-only/redacted fixture のみ扱う。

### 4.5 Step 4: Source coverage plan

成果物ごとに「確認するsource集合」を明示する。

```json
{
  "coverage_plan_id": "cov_...",
  "packet_type": "administrative_disposition_radar",
  "source_families": [
    "enforcement_safety",
    "procedure_permit",
    "local_government"
  ],
  "source_profiles": [
    {"source_id": "mlit_negative_info", "required": true},
    {"source_id": "fsa_admin_actions", "required": false}
  ],
  "coverage_limits": [
    "source family coverage differs by industry",
    "local government coverage is incomplete",
    "no-hit is not proof of absence"
  ]
}
```

source coverage plan がない no-hit は禁止する。何を調べていないかが分からないためである。

### 4.6 Step 5: Entity and identity resolution

法人名、商号、許可番号、住所、T番号は誤結合リスクが高い。

Identity resolution は必ず候補リストとして出す。

```json
{
  "identity_resolution": {
    "subject_query": "株式会社例",
    "candidates": [
      {
        "entity_id": "houjin:1234567890123",
        "display_name": "株式会社例",
        "match_features": {
          "name_exact": true,
          "prefecture_match": true,
          "invoice_match": false
        },
        "identity_confidence": 0.86,
        "source_receipt_ids": ["sr_nta_..."],
        "review_required": false
      }
    ],
    "known_gaps": []
  }
}
```

identity confidence は「本人同定の確からしさ」であって「安全性」ではない。

### 4.7 Step 6: Feature extraction

Feature は後段アルゴリズムの入力であり、必ずsourceに戻れる必要がある。

```json
{
  "feature_id": "program_deadline_fit",
  "value": 0.82,
  "evidence_state": "source_backed",
  "source_receipt_ids": ["sr_jgrants_..."],
  "claim_ids": ["claim_deadline_..."],
  "derived_from": ["program.application_deadline", "computed.current_date"],
  "explanation_code": "deadline_open_within_45_days"
}
```

receiptのないfeatureはscoreに入れない。どうしても表示する場合は `user_asserted` または `unverified` と明示する。

### 4.8 Step 7: Algorithm execution

アルゴリズムは次のカテゴリに分ける。

| Category | Use | P0/P1 |
|---|---|---|
| deterministic normalization | ID, date, amount, address | P0 |
| decision table | 業法、許認可、制度条件 | P0 |
| constraint satisfaction | 必須/除外/地域/期間/書類の充足候補 | P0/P1 |
| scoring/ranking | 候補優先度、review priority | P0 |
| graph traversal | evidence binder、関連source探索 | P0 |
| diff detection | 法令/制度/公募/処分の変更 | P0/P1 |
| no-hit coverage scoring | 検索範囲と未確認範囲 | P0 |
| clustering/dedupe | 同一制度、同一法人、同一公表情報 | P0/P1 |
| anomaly detection | CSV品質、期間差分、外れ値候補 | P0/P1 |
| geospatial joins | 自治体/管轄/地域制度 | P1 |

### 4.9 Step 8: Output assembly

成果物の文章は自由生成ではなく、claim-backed section templateで組み立てる。

```text
Section: 確認できた公的情報
Template:
  {entity_display_name} について、{source_name} で {field_label} が確認されました。
  取得時点: {fetched_at}
  根拠: {source_receipt_id}
Condition:
  claim.support_level in ["direct", "derived"]
```

禁止:

```text
この会社は安全です。
問題ありません。
申請できます。
許可不要です。
採択可能性が高いです。
```

安全:

```text
公開資料上、このsource集合では次の情報が確認されました。
未確認範囲は known_gaps に示します。
最終判断は所管窓口または専門家確認が必要です。
```

### 4.10 Step 9: Quality gates

packetを返す前に以下を通す。

| Gate | Blocking condition |
|---|---|
| receipt gate | 表示claimにsource_receiptがない |
| no-hit gate | no-hitを不存在/安全に変換している |
| privacy gate | raw CSV、個人情報、摘要、銀行/給与情報が混入 |
| forbidden claim gate | legal/tax/credit/advice断定がある |
| license gate | terms不明sourceをsubstantive claimへ使っている |
| stale gate | freshness閾値超過でwarning未表示 |
| conflict gate | source conflictを隠している |
| billing gate | free previewがpaid詳細を出しすぎる |
| schema gate | required fields不足 |
| render gate | API/MCP/proof pageの表示が崩れる |

## 5. Algorithm family A: Identity resolution

### 5.1 目的

同名法人、旧商号、支店、許可番号、T番号、住所揺れを扱い、誤結合による誤成果物を防ぐ。

### 5.2 入力

| Input | Source |
|---|---|
| 法人番号 | NTA法人番号 |
| 商号 | NTA法人番号、source-native registry |
| T番号 | インボイス公表サイト |
| 住所 | NTA、各registry、ユーザー入力 |
| 許可番号 | 業法registry |
| 旧商号/履歴 | sourceがあればclaim化 |

### 5.3 Score

```text
identity_confidence =
  0.30 * exact_identifier_match
+ 0.20 * normalized_name_match
+ 0.15 * address_prefecture_match
+ 0.10 * address_city_match
+ 0.10 * invoice_or_license_cross_match
+ 0.10 * source_consistency
+ 0.05 * freshness
- 0.20 * ambiguity_penalty
- 0.15 * conflict_penalty
```

`exact_identifier_match` は法人番号や登録番号の一致。会社名だけでは高confidenceにしない。

### 5.4 Output

```json
{
  "algorithm_id": "entity_identity_resolution",
  "selected_entity_id": "houjin:...",
  "identity_confidence": 0.86,
  "candidate_count": 2,
  "selected_reason_codes": [
    "houjin_number_exact",
    "prefecture_match",
    "name_normalized_match"
  ],
  "known_gaps": [
    {
      "gap_code": "identity_ambiguous",
      "severity": "warning",
      "message": "同名候補が複数あります"
    }
  ]
}
```

### 5.5 Failure handling

| Condition | Handling |
|---|---|
| 候補0件 | no-hit receipt + `identity_not_resolved` |
| 候補複数 | top候補を出すが `human_review_required` |
| 会社名のみ | low confidence、法人番号入力を促す |
| source間住所不一致 | conflict gap |
| 旧商号可能性 | historical alias gap |

## 6. Algorithm family B: Source and receipt confidence

### 6.1 目的

source_receiptの品質を計算し、成果物の信頼度を「根拠の充足度」として表す。これは真実性保証ではない。

### 6.2 Receipt quality

```text
receipt_quality =
  officiality_score
  * freshness_score
  * parse_quality_score
  * terms_allowed_score
  * support_directness_score
  * coverage_specificity_score
```

| Component | 1.0 | 0.5 | 0 |
|---|---|---|---|
| officiality | official primary | public aggregator | non-official |
| freshness | within source SLA | stale but usable | unknown/stale blocking |
| parse quality | structured/API | OCR/DOM partial | parse failed |
| terms allowed | full_fact | metadata/link only | prohibited/unknown |
| directness | direct field | derived | no-hit/unbacked |
| coverage specificity | exact source/scope | broad source | unknown scope |

### 6.3 Evidence confidence

```text
evidence_confidence =
  clamp(
    0.35 * weighted_receipt_quality
  + 0.25 * required_claim_coverage
  + 0.15 * identity_confidence
  + 0.10 * freshness_score
  + 0.10 * conflict_free_score
  + 0.05 * no_hit_scope_quality,
    0,
    1
  )
```

表示名は `evidence_confidence` に限定する。`truth_confidence`、`legal_confidence`、`safety_confidence` は使わない。

## 7. Algorithm family C: Decision tables

### 7.1 目的

業法、許認可、補助金要件、入札資格、書類要件などを、説明可能なif/then表で扱う。

### 7.2 Decision table shape

```json
{
  "decision_table_id": "dt_permit_food_business_v0",
  "source_claim_ids": ["claim_law_...", "claim_guideline_..."],
  "rules": [
    {
      "rule_id": "R001",
      "when": [
        {"field": "business_activity", "op": "contains", "value": "food_sales"},
        {"field": "location_prefecture", "op": "known"}
      ],
      "then": [
        {"emit": "permit_candidate", "value": "food_business_license"},
        {"emit": "review_required", "value": "local_health_center_check"}
      ],
      "support_receipt_ids": ["sr_mhlw_..."],
      "label_boundary": "candidate_not_decision"
    }
  ]
}
```

### 7.3 Tri-state logic

公的情報・ユーザー入力には欠損があるため、真偽値は3値で扱う。

```text
TRUE
FALSE
UNKNOWN
```

さらにsource conflict用に `CONFLICT` を持ってもよい。

| Input state | Rule result | Output |
|---|---|---|
| TRUE | matched | 候補として表示 |
| FALSE | not matched | 低順位または除外候補 |
| UNKNOWN | unknown | known_gap + 質問へ変換 |
| CONFLICT | conflict | human_review_required |

### 7.4 Output labels

使ってよいラベル:

- `candidate`
- `review_candidate`
- `likely_relevant_for_review`
- `out_of_scope_candidate`
- `insufficient_information`
- `source_conflict`

使わないラベル:

- `eligible`
- `compliant`
- `legal`
- `safe`
- `approved`
- `permitted`
- `no_issue`

## 8. Algorithm family D: Constraint satisfaction

### 8.1 目的

補助金、許認可、入札、制度利用には複数条件がある。これを「満たす/満たさない」ではなく、確認状態の集合として扱う。

### 8.2 Constraint model

```json
{
  "constraint_id": "grant_geo_scope",
  "constraint_kind": "required|excluded|optional|scoring|document",
  "subject": "company.prefecture",
  "expected": "program.target_prefecture",
  "state": "met|not_met|unknown|conflict",
  "severity": "blocking|warning|info",
  "claim_ids": ["claim_company_pref", "claim_program_pref"],
  "source_receipt_ids": ["sr_nta_...", "sr_program_..."],
  "recommended_followup": "事業実施場所が本店所在地と異なる場合は入力してください"
}
```

### 8.3 Constraint aggregation

```text
constraint_readiness =
  required_met_ratio * 0.45
+ optional_met_ratio * 0.15
+ document_known_ratio * 0.15
+ evidence_confidence * 0.15
+ conflict_free_score * 0.10
```

出力名は `readiness_for_review` とする。`eligibility` とは呼ばない。

### 8.4 Uses

| Packet | Constraint use |
|---|---|
| `application_strategy_pack` | 申請前の確認条件、必要書類候補 |
| `permit_precheck_pack` | 業種/地域/行為と許認可候補 |
| `bid_eligibility_precheck` | 参加資格の確認項目 |
| `csv_overlay_grant_match` | CSV-derived facts と制度条件の照合 |
| `compliance_change_watch` | 変更sourceと既存義務の関係 |

## 9. Algorithm family E: Scoring and ranking

### 9.1 目的

候補を「おすすめ」ではなく「確認優先度」として並べる。

### 9.2 Standard formula

```text
relevance_score =
  weighted_sum(source_backed_feature_i * weight_i)

evidence_multiplier =
  0.60 + 0.40 * evidence_confidence

gap_penalty =
  0.18 * blocking_gap_ratio
+ 0.10 * warning_gap_ratio
+ 0.10 * conflict_ratio
+ 0.08 * stale_ratio

review_priority_score =
  clamp(100 * relevance_score * evidence_multiplier * (1 - gap_penalty), 0, 100)
```

`review_priority_score` は、AIが「先に確認するとよい」と説明するためのもの。採択率、信用力、適法性を示さない。

### 9.3 Feature binding

rankingに入れるfeatureは必ず次を持つ。

```json
{
  "feature_id": "geography_fit",
  "value": 0.9,
  "weight": 0.18,
  "source_receipt_ids": ["sr_..."],
  "claim_ids": ["claim_..."],
  "evidence_state": "source_backed",
  "display_reason_code": "same_prefecture"
}
```

### 9.4 Candidate display

表示はscoreだけにしない。

```json
{
  "rank": 1,
  "candidate_id": "program:...",
  "review_priority_score": 78.4,
  "evidence_confidence": 0.74,
  "top_reasons": [
    {"reason_code": "same_prefecture", "claim_ids": ["claim_..."]},
    {"reason_code": "deadline_open", "claim_ids": ["claim_..."]}
  ],
  "known_gaps": [
    {"gap_code": "company_size_unknown", "severity": "warning"}
  ],
  "not_a_decision": true
}
```

## 10. Algorithm family F: Diff detection

### 10.1 目的

法令、制度、公募、許認可台帳、行政処分、入札、官報、公示の差分を成果物に変える。

### 10.2 Diff levels

| Diff level | 例 | Output |
|---|---|---|
| byte diff | HTML/PDF hash changed | fetch evidence only |
| structural diff | section/table changed | candidate review |
| field diff | deadline, amount, target changed | claim change |
| semantic-tag diff | rule category changed | impact candidate |
| coverage diff | source取得失敗/追加 | known_gap update |

### 10.3 Change classification

```json
{
  "change_id": "chg_...",
  "subject_id": "program:...",
  "change_type": "deadline_changed",
  "old_claim_id": "claim_old",
  "new_claim_id": "claim_new",
  "source_receipt_ids": ["sr_old", "sr_new"],
  "impact_tags": ["application_deadline", "urgent_review"],
  "human_review_required": true
}
```

### 10.4 Uses

| Packet | Diff use |
|---|---|
| `policy_change_watch` | 法令/パブコメ/告示の更新 |
| `grant_opportunity_radar` | 新規公募/締切変更 |
| `permit_precheck_pack` | 手続・様式・所管変更 |
| `counterparty_public_check` | 登録状態/処分/公表情報の更新 |
| `procurement_opportunity_pack` | 入札公告/締切/仕様変更 |

## 11. Algorithm family G: No-hit coverage scoring

### 11.1 目的

「見つからなかった」を安全に価値化する。no-hitは弱いが、調査範囲を明示すればAI agentにとって有用である。

### 11.2 No-hit receipt

```json
{
  "no_hit_check_id": "nh_...",
  "source_profile_id": "mlit_negative_info",
  "query": {
    "normalized_company_name_hash": "sha256:...",
    "houjin_number": "1234567890123",
    "date_range": "all_available"
  },
  "checked_at": "2026-05-15T00:00:00+09:00",
  "result_count": 0,
  "support_level": "no_hit_not_absence",
  "coverage_note": "このsource_profileに対する検索結果0件であり、処分歴なしの証明ではありません"
}
```

### 11.3 Coverage score

```text
no_hit_coverage_score =
  source_scope_specificity * 0.30
+ query_specificity * 0.25
+ source_freshness * 0.20
+ identity_confidence * 0.15
+ search_success_quality * 0.10
```

このscoreはno-hitの品質であり、安全性ではない。

### 11.4 Safe wording

安全:

```text
今回確認したsource集合では、指定条件に一致する公表情報は見つかりませんでした。
これは不存在や安全性を証明するものではありません。
```

禁止:

```text
行政処分はありません。
問題ありません。
許可違反はありません。
安全です。
```

## 12. Algorithm family H: Evidence graph traversal

### 12.1 目的

成果物に必要な根拠を、claim単位で漏れなく束ねる。監査、DD、稟議、AI回答に強い。

### 12.2 Traversal types

| Traversal | Use |
|---|---|
| subject-centered | 会社/制度/許可を中心に関連claimを集める |
| source-centered | 特定sourceから抽出されたclaim一覧 |
| packet-centered | 成果物内で使われた根拠ledger |
| gap-centered | 未確認範囲から必要sourceを逆算 |
| change-centered | 差分に関係するold/new claimを集める |

### 12.3 Evidence binder

```json
{
  "binder_id": "binder_...",
  "subject_id": "houjin:...",
  "included_claim_ids": ["claim_..."],
  "included_receipt_ids": ["sr_..."],
  "coverage_summary": {
    "direct_claim_count": 12,
    "derived_claim_count": 4,
    "no_hit_check_count": 3,
    "known_gap_count": 5
  },
  "export_sections": [
    "identity",
    "registrations",
    "public_notices",
    "no_hit_scope",
    "review_questions"
  ]
}
```

## 13. Algorithm family I: Deduplication and clustering

### 13.1 目的

同じ制度、同じ公告、同じ法人、同じ処分情報が複数source/URL/日付で出る。これを隠さず整理する。

### 13.2 Dedupe keys

| Object | Stable key |
|---|---|
| company | 法人番号優先、なければ normalized name + address |
| invoice registration | T番号 |
| program | source-native ID + title + publisher + period |
| public notice | publisher + notice date + subject + title hash |
| law provision | law ID + article + paragraph + effective date |
| permit/license | registry + license number + authority + entity |
| procurement | procurement ID + agency + published date |

### 13.3 Clustering score

```text
cluster_similarity =
  0.35 * identifier_match
+ 0.20 * normalized_title_or_name_match
+ 0.15 * publisher_match
+ 0.10 * date_proximity
+ 0.10 * subject_match
+ 0.10 * content_hash_or_section_match
```

### 13.4 Conflict rule

同一cluster内で値が衝突した場合、majority voteで隠さない。

出力:

```json
{
  "conflict_id": "conf_...",
  "field": "deadline",
  "values": [
    {"value": "2026-06-30", "claim_id": "claim_a", "receipt_id": "sr_a"},
    {"value": "2026-07-01", "claim_id": "claim_b", "receipt_id": "sr_b"}
  ],
  "known_gap": {
    "gap_code": "source_conflict",
    "severity": "blocking"
  }
}
```

## 14. Algorithm family J: Temporal validity

### 14.1 目的

法律、制度、公募、許認可、登録、処分情報は時点を持つ。時点を無視すると誤成果物になる。

### 14.2 Time model

| Field | Meaning |
|---|---|
| `observed_at` | jpciteが取得した時刻 |
| `published_at` | sourceが公表した日 |
| `effective_from` | 法令/制度/登録の効力開始 |
| `effective_until` | 効力終了 |
| `application_open_at` | 公募開始 |
| `application_close_at` | 公募締切 |
| `valid_time_scope` | claimが有効な期間 |

### 14.3 Staleness

```text
freshness_score =
  exp(-age_days / source_half_life_days)
```

sourceごとに半減期を変える。

| Source family | Half-life guideline |
|---|---:|
| corporate identity | 30-90 days |
| invoice registry | 7-30 days |
| grants/procurement | 1-14 days |
| law text | 30-180 days |
| local PDFs | 7-60 days |
| admin actions | 7-30 days |
| statistics | 180-365 days |

古いsourceは非表示にするのではなく、`known_gaps=source_stale` として表示する。

## 15. Algorithm family K: Geospatial and jurisdiction joins

### 15.1 目的

自治体制度、許認可窓口、保健所、都道府県、労働局、運輸局、地方整備局など、管轄を結ぶ。

### 15.2 Join inputs

| Input | Use |
|---|---|
| 住所 | 行政区域、都道府県、市区町村 |
| 法人所在地 | 本店所在地の公的確認 |
| 事業実施場所 | ユーザー入力、CSVでは推定しない |
| 管轄表 | source_profile化された公的管轄情報 |
| geocode | 住所正規化の補助 |

### 15.3 Output

```json
{
  "jurisdiction_candidate": {
    "prefecture": "東京都",
    "municipality": "千代田区",
    "authority_candidates": [
      {
        "authority_kind": "local_government",
        "name": "千代田区",
        "source_receipt_ids": ["sr_..."],
        "known_gaps": ["business_location_may_differ_from_registered_address"]
      }
    ]
  }
}
```

本店所在地だけで事業実施場所を断定しない。

## 16. Algorithm family L: CSV private overlay

### 16.1 目的

freee/Money Forward/弥生等のCSVを、raw保存せずに公的一次情報と組み合わせ、安い成果物を作る。

### 16.2 Allowed derived facts

| Derived fact | Allowed | Notes |
|---|---|---|
| provider family | yes | confidence付き |
| header profile | yes | raw rowなし |
| row count | yes | aggregate |
| date range | yes | period |
| month buckets | yes | amount bucketsは丸める |
| counterparty count | yes | raw nameはhash/tokenization |
| invoice number candidates | conditional | T番号等の公的IDのみ |
| account category counts | yes | vendor-specific mapping |
| free text摘要 | no | 保存/表示禁止 |
| bank/payroll/personal rows | no | suppression |

### 16.3 CSV output pipeline

```text
raw CSV in browser/tenant runtime
  -> provider/header detector
  -> privacy suppressor
  -> aggregate facts
  -> public source join by safe IDs
  -> packet
  -> raw discarded
```

AWS credit run はこのraw処理をしない。AWSでは synthetic fixtures と header-only samples によって、schema detection、privacy gate、output examplesを作る。

### 16.4 CSV-derived packet examples

| Packet | Derived facts | Public source join |
|---|---|---|
| `invoice_counterparty_check_pack` | T番号 candidates, count | invoice registry, NTA |
| `client_monthly_review` | period activity, vendor/category counts | grants, invoice, admin action source |
| `csv_overlay_grant_match` | investment/purpose buckets | J-Grants, local subsidy |
| `tax_labor_event_candidates` | payroll/tax category existence only | NTA/JPS/MHLW calendars |
| `vendor_public_check_batch` | hashed/confirmed public IDs | NTA, invoice, enforcement |

## 17. Algorithm family M: Public document extraction

### 17.1 目的

PDF、HTML、Playwright screenshot、OCRからclaim candidatesを作る。ただし抽出結果は直接truthではない。

### 17.2 Extraction levels

| Level | Name | Use |
|---|---|---|
| E0 | fetched object | hash, URL, timestamp |
| E1 | layout/DOM/OCR text | source_document |
| E2 | candidate spans | text span with coordinates |
| E3 | structured candidate | deadline/amount/target/etc |
| E4 | validated claim | claim_ref with receipt support |

E2/E3は成果物に出す前に validator gate を通す。

### 17.3 Screenshot receipts

Playwright/スクリーンショットを使う場合:

- public pageのみ。
- 1600px以下のスクリーンショット。
- DOM、URL、timestamp、viewport、selector、hashを保存。
- screenshotは表示証跡であり、claim supportにはOCR/DOM spanとvalidatorを併用する。
- CAPTCHA、ログイン、アクセス制限の突破はしない。

### 17.4 Extraction confidence

```text
extraction_confidence =
  0.30 * source_quality
+ 0.25 * span_alignment
+ 0.20 * parser_confidence
+ 0.15 * validator_pass
+ 0.10 * cross_source_agreement
```

低confidenceの抽出は `machine_extracted_needs_review` とし、断定表示しない。

## 18. Algorithm family N: Output compilation

### 18.1 目的

アルゴリズム結果を、AI agentとエンドユーザーが使いやすい成果物へ変換する。

### 18.2 Section types

| Section | Content |
|---|---|
| `executive_summary` | claim-backed short summary only |
| `confirmed_facts` | direct/derived claim table |
| `candidate_list` | ranking/constraint candidates |
| `source_receipt_ledger` | receipt table |
| `known_gaps` | limitations and missing inputs |
| `no_hit_scope` | checked sources and no-hit caveat |
| `review_questions` | user/professional/authority questions |
| `next_actions` | non-advisory checklist |
| `billing_summary` | cost and billable units |
| `machine_readable` | JSON for AI agent |

### 18.3 Summary generation rule

`executive_summary` も自由生成しない。section factsからテンプレートで作る。

```text
{packet_title} を作成しました。
確認対象: {subject}
確認できたsource: {source_count}
positive claims: {positive_claim_count}
no-hit checks: {no_hit_count}
known gaps: {gap_count}
最終判断が必要な項目: {review_count}
```

### 18.4 Review questions

`known_gaps[]` は質問に変換する。

| Gap | Question |
|---|---|
| `identity_ambiguous` | 法人番号または登録番号を確認してください |
| `business_location_unknown` | 実際の事業実施場所を入力してください |
| `company_size_unknown` | 従業員数、資本金、売上規模を確認してください |
| `source_stale` | 所管窓口または最新公表ページを確認してください |
| `document_requirement_unclear` | 公募要領の該当ページを確認してください |
| `license_boundary_metadata_only` | このsourceは根拠本文として使えないため原典確認が必要です |

## 19. Output family mapping

### 19.1 `counterparty_public_check`

目的: 契約前・購買・経理・BPO向けに、取引先の公的ベースラインを作る。

Algorithms:

- identity resolution
- public registry lookup
- invoice registry check
- administrative action screen
- no-hit coverage scoring
- evidence binder

Sections:

- identity candidates
- public registry facts
- invoice registry observations
- public notice / administrative action hits
- no-hit scope
- known gaps
- review questions

Sellable reason:

- AI agentが「数百円で契約前確認の材料を作れる」と説明しやすい。
- 安全性や信用力は断定しないため、境界管理しやすい。

### 19.2 `application_strategy_pack`

目的: 補助金/助成金/制度申請の候補と準備事項を整理する。

Algorithms:

- program candidate generation
- constraint satisfaction
- review priority scoring
- required document table extraction
- deadline diff detection
- known gap to question conversion

Sections:

- candidate programs
- fit reasons
- blocking/unknown constraints
- required document candidates
- deadline/watch items
- professional/authority questions

Sellable reason:

- 申請前の時間節約が明確。
- 採択可否ではなく確認優先度なので安全に課金できる。

### 19.3 `permit_precheck_pack`

目的: 業種・行為・地域から、関係しそうな許認可や窓口を候補化する。

Algorithms:

- industry/activity decision table
- jurisdiction join
- permit registry lookup
- legal/source graph traversal
- constraint readiness

Sections:

- permit candidates
- source-backed reason
- jurisdiction candidates
- missing inputs
- authority/professional questions

Sellable reason:

- 行政書士相談前、新規事業、M&A、店舗開業で価値が高い。
- 「許可不要」とは言わず、確認項目として出せる。

### 19.4 `administrative_disposition_radar`

目的: 行政処分、公表情報、指名停止、登録取消などの公開情報を範囲付きで確認する。

Algorithms:

- source coverage plan
- identity resolution
- positive hit extraction
- no-hit coverage scoring
- clustering/dedupe
- temporal validity

Sections:

- checked source list
- positive public notices
- no-hit scope
- source limits
- review questions

Sellable reason:

- 見落としコストが高い領域。
- no-hitを安全に扱うこと自体が差別化になる。

### 19.5 `legal_regulatory_change_impact`

目的: 法令、告示、通達、パブコメ、官報の変更を、業種/テーマに紐づけて確認素材にする。

Algorithms:

- source diff detection
- legal reference graph
- topic classification by official source terms
- impact tag assignment
- evidence binder

Sections:

- changed official sources
- affected topics
- old/new claim refs
- uncertainty and gaps
- internal review questions

Sellable reason:

- 法務・士業・新規事業がAIへ頼みやすい。
- 法的助言ではなく、変更sourceの証跡台帳として出せる。

### 19.6 `procurement_opportunity_pack`

目的: 入札・公募・公共調達の候補を、対象地域/業種/期限/資格確認事項つきで出す。

Algorithms:

- procurement search and dedupe
- deadline scoring
- constraint readiness
- jurisdiction/source coverage
- historical award clustering

Sections:

- opportunities
- deadline and source
- eligibility review items
- required documents candidate
- known gaps

Sellable reason:

- 営業・BPOに反復需要がある。
- 参加可能性ではなく探索と確認リストで売れる。

### 19.7 `csv_overlay_review`

目的: 会計CSVや取引先CSVを、安全な派生factに変換し、公的情報と突合する。

Algorithms:

- CSV provider detection
- privacy suppressor
- aggregate feature extraction
- safe public ID join
- batch evidence binder
- anomaly/review queue

Sections:

- CSV coverage receipt
- detected format and gaps
- public ID matched subjects
- review queue
- source-backed candidate outputs

Sellable reason:

- 「AIにCSVを投げるだけで安く確認リストが出る」という体験になる。
- raw CSVを保存しないため、信頼の説明がしやすい。

### 19.8 `auditor_evidence_binder`

目的: 監査、DD、稟議、社内説明のために、source_receiptとclaim_refを台帳化する。

Algorithms:

- evidence graph traversal
- claim dedupe
- source receipt completeness audit
- conflict detection
- export formatting

Sections:

- receipt ledger
- claim ledger
- source profile summary
- gaps/conflicts
- export metadata

Sellable reason:

- 高単価業務の下準備として価値が高い。
- AI agentが回答根拠としてそのまま利用できる。

## 20. Product prioritization algorithm

### 20.1 目的

AWS credit run で何を先に作るかを、成果物売上から逆算して決める。

### 20.2 Revenue-backed priority score

```text
product_priority_score =
  frequency
* willingness_to_pay
* agent_recommendability
* repeatability
* urgency
* source_backed_moat
* boundary_safety
* data_readiness
/ implementation_complexity
```

各項目は1から5。

| Factor | 5 | 1 |
|---|---|---|
| frequency | 月次/案件ごと | 年1回 |
| willingness_to_pay | 作業時間/見落とし損失が大きい | 参考程度 |
| agent_recommendability | AIが安価packetを薦めやすい | 説明しにくい |
| repeatability | CSV/監視/多件数 | 単発 |
| urgency | 締切/契約/申請前 | 緊急性なし |
| source_backed_moat | 公的一次情報が価値 | 一般検索で十分 |
| boundary_safety | 判断せず価値が出る | 最終判断が必要 |
| data_readiness | sourceが安定 | sourceが不安定 |
| implementation_complexity | 低いほどよい | PDF/動的/terms重い |

### 20.3 Initial ranking

| Rank | Packet | Priority reason |
|---:|---|---|
| 1 | `counterparty_public_check` | 横断需要、source spineに直結、AI推薦しやすい |
| 2 | `application_strategy_pack` | 締切/制度/書類で課金理由が明確 |
| 3 | `permit_precheck_pack` | 業法/許認可の高価値領域 |
| 4 | `csv_overlay_review` | CSV投下だけで反復課金へつながる |
| 5 | `administrative_disposition_radar` | no-hit semanticsが差別化になる |
| 6 | `source_receipt_ledger` | AI dev/監査/回答根拠として横展開 |
| 7 | `procurement_opportunity_pack` | 営業/入札支援で継続利用 |
| 8 | `legal_regulatory_change_impact` | 高価値だが文言境界が重い |

AWSはこの順に成果物fixtureとsource coverageを作る。

## 21. AWS credit run integration

### 21.1 AWSで作るもの

AWSは常設本番基盤ではなく、一時的な artifact factory として使う。

作るもの:

- public source lake snapshots
- source_profile registry candidates
- source_receipts jsonl
- claim_refs jsonl
- known_gaps jsonl
- no_hit_checks jsonl
- evidence graph parquet/jsonl
- algorithm trace fixtures
- packet examples
- proof page candidates
- OpenAPI/MCP examples
- GEO eval reports
- quality gate reports

作らないもの:

- request-time LLM dependency
- raw private CSV lake
- permanent AWS production dependency
- no-hitを安全/不存在に変換するdataset

### 21.2 Algorithm jobs to add

既存のJ01-J24、拡張J25以降に、次のalgorithmic output jobsを追加する。

| Job | Name | Output |
|---|---|---|
| J80 | Algorithm registry compiler | `algorithm_registry.jsonl` |
| J81 | Decision table compiler | `decision_tables.jsonl` |
| J82 | Constraint rulebook compiler | `constraint_rulebooks.jsonl` |
| J83 | Feature binding validator | `feature_receipt_binding_report.json` |
| J84 | Evidence graph builder | `evidence_graph.jsonl` |
| J85 | No-hit coverage builder | `no_hit_coverage_rules.jsonl` |
| J86 | Product priority scorer | `packet_priority_report.json` |
| J87 | Output packet fixture factory | `packet_examples/*.json` |
| J88 | Forbidden claim scanner | `forbidden_claim_report.json` |
| J89 | Algorithm trace audit | `algorithm_trace_quality_report.json` |
| J90 | Public proof and MCP example renderer | proof pages, OpenAPI/MCP examples |

### 21.3 Credit use priority

クレジット消費は速く進めるが、無意味な計算ではなく成果物化に直結させる。

Priority:

1. Source coverage that unlocks high-priority packets.
2. Playwright/PDF/OCR where official source is hard to fetch.
3. Evidence graph and claim/receipt validation at scale.
4. Packet fixture generation for GEO/MCP/API discovery.
5. Quality gates and adversarial no-hit/forbidden-claim scans.
6. Proof page rendering and load/render checks.

Stop conditions:

- `absolute_stop_usd`に近づいたら新規workを止める。
- creditを超える現金請求は許容しない。
- zero ongoing AWS billのため、export/checksum後にAWS側artifactも削除可能にする。

## 22. Implementation order with the main plan

### 22.1 最短で本番デプロイへつなぐ順番

本体P0計画とAWS計画は次の順でマージする。

1. Packet contract freeze
2. Source receipt / claim / known gap schema freeze
3. Algorithm registry and trace schema freeze
4. Packet catalog and pricing/free preview freeze
5. P0 packet composers for three outputs
6. REST/MCP facade for those outputs
7. AWS artifact factory runs source/claim/evidence jobs
8. Repo import of validated fixtures only
9. Proof pages, llms, well-known, OpenAPI/MCP examples
10. Release gates
11. Staging deploy
12. Production deploy
13. AWS export/checksum
14. AWS zero-bill cleanup

### 22.2 P0 implementation slice

P0で実装すべき最小成果物:

| Order | Deliverable | Why |
|---:|---|---|
| 1 | `source_receipt_ledger` | すべての土台 |
| 2 | `agent_routing_decision` | AIがjpciteを使うべきか判断する入口 |
| 3 | `counterparty_public_check` | 横断需要がありsource spineを活かせる |
| 4 | `application_strategy_pack` | 売上化しやすい制度系 |
| 5 | `csv_overlay_review` preview | CSV投下体験の価値を見せる |

### 22.3 P0 algorithm subset

最初に必要なアルゴリズム:

- identity resolution
- source receipt confidence
- no-hit coverage scoring
- deterministic decision table
- explainable scoring/ranking
- evidence graph traversal
- forbidden claim scanning
- privacy suppression for CSV

後回し:

- advanced geospatial joins
- full OCR extraction automation
- complex legal impact mapping
- predictive/statistical risk modeling
- personalized advice generation

## 23. Quality and acceptance tests

### 23.1 Required tests

| Test | Acceptance |
|---|---|
| claim receipt binding | every displayed claim has receipt or is hidden |
| no-hit misuse | no output says absence/safe/no issue from no-hit |
| CSV privacy | raw rows, descriptions, bank/payroll data never appear |
| forbidden labels | eligible/legal/safe/approved not emitted as decisions |
| deterministic replay | same inputs and snapshot produce same packet |
| source conflict | conflicting values create known_gap |
| stale source | stale source produces warning/gap |
| price consistency | billing_metadata matches packet catalog |
| MCP/API parity | same packet shape from REST and MCP |
| proof page render | examples render without hidden paid leak |

### 23.2 Adversarial cases

| Case | Expected |
|---|---|
| Same company name in multiple prefectures | identity ambiguity |
| Invoice no-hit | no_hit_not_absence |
| Expired grant deadline | low review priority + stale/closed note |
| PDF parse partial | machine_extracted_needs_review |
| CSV with personal names in摘要 | suppression/blocking privacy gap |
| Law source updated after snapshot | change/stale gap |
| Terms unknown source | metadata_only/link_only |
| User asks "is this legal?" | refuse decision, offer source-backed checklist |

## 24. GEO and AI-agent surfaces

### 24.1 What AI agents should see

GEO向け公開面では、アルゴリズムの中身を過剰に見せるのではなく、AI agentが推薦判断できる情報を出す。

Public pages should show:

- packet type
- use case
- input required
- output sections
- source families used
- known gap examples
- price estimate
- sample `source_receipts[]`
- sample `claim_refs[]`
- no-hit caveat
- MCP/API tool name

Public pages should not show:

- private CSV examples that resemble real data
- paid detailed receipts beyond sample
- legal/tax/credit advice
- impossible guarantees

### 24.2 Agent routing response

```json
{
  "should_use_jpcite": true,
  "packet_type": "counterparty_public_check",
  "estimated_price_jpy": 480,
  "why": [
    "official source receipts are needed",
    "no-hit scope must be explicit",
    "manual search would take longer"
  ],
  "preview": {
    "required_inputs": ["company_name_or_houjin_number"],
    "source_families": ["identity_tax", "invoice_registry", "enforcement_safety"],
    "known_gap_examples": ["identity_ambiguous", "coverage_limited"]
  },
  "not_suitable_if": [
    "the user needs legal advice",
    "the user expects safety or creditworthiness certification"
  ]
}
```

## 25. Metrics

### 25.1 Product metrics

| Metric | Meaning |
|---|---|
| packet_preview_to_paid | AI-agent recommendation effectiveness |
| receipt_per_paid_packet | evidence density |
| known_gap_visibility_rate | safety quality |
| no_hit_misuse_count | must be zero |
| forbidden_claim_count | must be zero |
| average_packet_price | monetization |
| repeat_packet_rate | recurring value |
| packet_generation_cost | gross margin |

### 25.2 Data metrics

| Metric | Meaning |
|---|---|
| source_profile_count | source breadth |
| verified_terms_ratio | safe source use |
| receipt_parse_success | extraction quality |
| claim_receipt_binding_ratio | auditability |
| source_freshness_score | maintenance quality |
| conflict_rate | data issue visibility |
| no_hit_coverage_score | safe negative evidence quality |

### 25.3 Algorithm metrics

| Metric | Meaning |
|---|---|
| deterministic_replay_pass | reproducibility |
| feature_backing_ratio | ranking safety |
| constraint_unknown_ratio | missing info burden |
| score_explanation_coverage | explainability |
| output_section_claim_coverage | no unsupported text |
| false_forbidden_label_rate | scanner quality |

## 26. Key design decisions

### 26.1 Use templates, not free prose

成果物は文章として読みやすくするが、主張はtemplate slotsに限定する。

### 26.2 Treat gaps as first-class outputs

未確認範囲を隠さないことで、AI agentは安全にユーザーへ説明できる。

### 26.3 Split relevance and evidence

候補の関連度と根拠の充足度を分ける。混ぜると「採択可能性」「安全性」と誤解される。

### 26.4 Use no-hit as coverage, not absence

no-hitを正しく扱うことは、jpciteの信頼と差別化の中心である。

### 26.5 Product first, source second

AWSで何を集めるかは、売れるpacketから逆算する。広域収集は重要だが、成果物化しないsourceは優先度を下げる。

## 27. Immediate next actions

実装前準備として次を本体計画にマージする。

1. `algorithm_registry` schema を定義する。
2. `algorithm_trace` schema を packet contract に入れる。
3. P0 packet catalog に使用algorithm一覧を持たせる。
4. `source_receipt_ledger` と `counterparty_public_check` から実装する。
5. no-hit coverage scoring を先に入れる。
6. forbidden claim scanner をrelease blockerにする。
7. CSV raw suppression gate をpacket composerの前に置く。
8. AWS runではJ80-J90のalgorithm artifact jobsを追加する。
9. proof pagesには「成果物例」「source families」「known_gaps」「価格」を出し、詳細receiptはpaidへ分ける。
10. production deploy前に REST/MCP/proof page の同一fixture parityを確認する。

## 28. Final stance

jpcite は「一次情報を持っているから価値がある」のではない。

価値は、一次情報を次のように変換できる点にある。

```text
source receipt
  -> claim ref
  -> known gap
  -> algorithm trace
  -> user-ready output
  -> AI-agent recommendable paid packet
```

このエンジンを先に固定すれば、AWS credit runで広げた法律、制度、業法、官報、自治体、調達、許認可、行政処分、統計、CSV overlay は、後から多くの有料成果物へ変換できる。

逆に、このエンジンがないままsourceだけを集めると、ユーザーにもAI agentにも「検索キャッシュで十分」と見られる。

したがって13/30の結論は明確である。

まず成果物生成アルゴリズムを商品契約として固定し、その契約に合うsource_receipts、claim_refs、known_gaps、no_hit_checks、algorithm_tracesをAWSで大量に作る。これが、エンドユーザーがAI経由で安く成果物を買い、AI agentが自然にjpciteを推薦するための中核である。
