# AWS Final Consistency 05/10: Algorithm Safety / Hallucination Elimination

作成日: 2026-05-15  
担当: 最終矛盾チェック 5/10 / アルゴリズム・ハルシネーション排除  
対象: 決定表、制約充足、スコアリング、差分検出、証拠グラフ、CSV private overlay、LLM利用制限  
AWS実行: なし。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行は行っていない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

全体コンセプト「一次情報でハルシネーションなし」は成立する。ただし、成立条件はかなり厳しい。

最終的な安全契約は次で固定する。

1. 成果物の主張は `claim_refs[]` から `source_receipts[]` へ必ず戻れる。
2. `no-hit` は `no_hit_not_absence` であり、不存在、安全、対象外、適法、登録不要、申請不可の証明にしない。
3. score は確率、信用度、安全度、採択可能性ではなく、レビュー優先度または根拠充足度としてだけ扱う。
4. LLMはrequest-timeで主張を作らない。使う場合も公開一次情報の候補抽出、分類補助、重複候補整理までで、claim supportにはしない。
5. CSV private overlay は raw CSV非保存、非ログ、非AWS、非echoを固定し、安全な派生factだけを使う。
6. `known_gaps[]` は必須。空の場合も「確認したgap categories」を明示し、未確認範囲を隠さない。
7. 出力文は自由作文ではなく、allowed phrase templateで組み立てる。

判定: 条件付きPASS。下記の修正契約を本体計画にマージすれば、アルゴリズム面の大きな矛盾は潰せる。

## 1. 確認した主要文書

- `aws_scope_expansion_13_algorithmic_output_engine.md`
- `aws_scope_expansion_14_grant_matching_algorithm.md`
- `aws_scope_expansion_15_permit_rule_algorithm.md`
- `aws_scope_expansion_16_vendor_risk_algorithm.md`
- `aws_scope_expansion_17_reg_change_diff_algorithm.md`
- `aws_scope_expansion_18_csv_overlay_algorithm.md`
- `aws_scope_expansion_26_data_quality_gates.md`
- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_08_artifact_manifest_schema.md`
- `aws_credit_review_12_csv_privacy_pipeline.md`
- `aws_credit_review_13_packet_proof_factory.md`
- `aws_credit_review_14_geo_eval_pipeline.md`

## 2. 大筋で整合している点

### 2.1 アルゴリズム優先でLLM自由生成ではない

`algorithmic_output_engine` は、成果物生成を次の流れに分けている。

```text
Public primary sources + private safe derived facts
  -> source_receipts
  -> claim_refs
  -> evidence graph
  -> deterministic rules / constraint solving / scoring / diff detection
  -> packet sections
  -> AI-agent safe output
```

これは「AIがそれっぽく作文するサービス」ではなく、「公的一次情報を証跡グラフ化し、決定表・制約・score・diffで成果物を作るサービス」として一貫している。

### 2.2 request-time LLM禁止は全体に通っている

複数文書で、request-time LLMを使わない方針が通っている。Bedrockなどを使う場合も、AWS credit run中のオフライン候補抽出・分類補助に限定されている。

ただし後述のとおり、実装では `llm_assisted_candidate` が `confirmed claim` に昇格する条件を機械的に塞ぐ必要がある。

### 2.3 no-hitの意味は原則統一されている

`no_hit_not_absence` がほぼ全体で使われている。no-hitは「指定source、指定query、指定時点、指定正規化条件で一致が見つからなかった」だけを意味する。

### 2.4 scoreを断定に使わない方針も概ね整合している

特に `vendor_risk_algorithm` は、単一risk scoreではなく次の3軸を要求しており、誤読をかなり抑えられる。

- `public_evidence_risk_attention_score`
- `evidence_quality_score`
- `coverage_gap_score`

この思想は他packetにも横展開すべき。

## 3. 見つかった矛盾・弱点と修正契約

### 3.1 `eligible` ラベルが強すぎる

矛盾:

- `grant_matching_algorithm` の前半では `eligible / likely / needs_review / not_enough_info` を許容している。
- 一方、CSV overlay側では output ranking として `eligible` / `not eligible` を出さない方針がある。

リスク:

AI agentやエンドユーザーが `eligible` を「申請可能」「採択可能」「対象確定」と誤読する。

修正契約:

P0本番API・MCP・proof pageでは `eligible` を外部表示しない。

外部表示ラベルは次に固定する。

```text
high_relevance_needs_user_confirmation
medium_relevance
low_relevance_watch_only
not_recommended_due_to_missing_required_facts
```

内部で `eligible_signal` を持つ場合も、公開payloadでは次のように変換する。

```json
{
  "candidate_class": "high_relevance_needs_user_confirmation",
  "decision_status": "not_a_final_decision",
  "not_a_final_application_decision": true,
  "human_review_required": true,
  "known_gaps": []
}
```

禁止:

- `申請できます`
- `対象です`
- `採択可能性が高いです`
- `eligible`
- `not eligible`

許可:

- `収集済み一次情報と入力条件の範囲では、確認優先度が高い候補です`
- `未確認条件があるため、申請可否は確定していません`

### 3.2 `safety` というsource family名が誤読を誘う

矛盾:

一部文書に `enforcement_safety` や `safe_preview` のような名称がある。内部用語としては意図が分かるが、外部payloadやUIに出ると「安全確認済み」と誤読される。

修正契約:

外部API・MCP・proof page・packet catalogでは次へ置換する。

| 現在の表現 | 外部向け表現 |
|---|---|
| `enforcement_safety` | `public_enforcement_records` |
| `safe_preview` | `privacy_limited_preview` |
| `safety score` | 使用禁止 |
| `safe_to_release` | `privacy_release_status` |

内部コードでも、可能なら `safe` は privacy-only のprefixに限定する。

例:

```json
{
  "privacy_release_status": "k_anonymized_aggregate_only",
  "business_safety_assertion": false
}
```

### 3.3 no-hitを「安全な説明に使う」という文が誤読される

矛盾:

`vendor_risk_algorithm` に「no-hitをGEO向けの安全な説明に使う」という趣旨の記述がある。文脈上は「安全な表現で説明する」の意味だが、「安全の説明」と誤読できる。

修正契約:

表現を次に固定する。

```text
no-hitは、指定したsource集合・検索条件・取得時点で一致が見つからなかった検査結果としてだけ説明する。
これは不存在、安全、適法、問題なし、登録不要、対象外を意味しない。
```

no-hit objectは必ず次を持つ。

```json
{
  "result": "no_hit",
  "support_level": "no_hit_not_absence",
  "allowed_statement_key": "no_hit_scope_only",
  "forbidden_conclusions": [
    "absence",
    "safe",
    "no_problem",
    "compliant",
    "not_registered",
    "not_applicable",
    "license_not_required"
  ],
  "known_gaps": []
}
```

### 3.4 generic `score` フィールドが危険

矛盾:

`algorithm_trace` の例に `"score": 74.2` のような汎用scoreがある。一方、各成果物では score の意味を厳密に分ける方針になっている。

リスク:

外部実装やAI agentが score を「確率」「安全度」「信用度」「採択可能性」として扱う。

修正契約:

外部payloadに汎用 `score` を出さない。必ず typed score にする。

```json
{
  "score_set": [
    {
      "score_name": "review_priority_score",
      "value": 74,
      "range": [0, 100],
      "semantics": "review_ordering_only",
      "not_probability": true,
      "not_safety": true,
      "not_creditworthiness": true,
      "not_legal_or_tax_decision": true,
      "score_components": [],
      "source_claim_refs": [],
      "known_gap_refs": []
    }
  ]
}
```

`score_status` が次の場合、数値scoreを返さない。

- `withheld_due_to_insufficient_evidence`
- `withheld_due_to_ambiguous_identity`
- `withheld_due_to_source_terms_unverified`
- `withheld_due_to_csv_privacy_suppression`
- `withheld_due_to_llm_only_candidate`

### 3.5 LLM-assisted extractionの昇格条件がまだ曖昧

整合:

文書上は「LLM-assisted extractionはclaimを直接支えない」とされている。

残リスク:

実装で `llm_assisted_candidate` が parser output と同じ配列に入り、うっかり `confirmed` 扱いになる可能性がある。

修正契約:

LLM由来の候補は必ず隔離する。

```json
{
  "candidate_origin": "llm_assisted_public_source_extraction",
  "can_support_claim": false,
  "requires_deterministic_validation": true,
  "requires_human_review_if_used": true,
  "max_support_level_before_validation": "candidate_only"
}
```

claimへ昇格できる条件:

1. 公式source receiptがある。
2. 対象span、page、row、field、DOM selector、PDF page、OCR bboxのいずれかに戻れる。
3. deterministic validatorが通る。
4. source termsが通る。
5. forbidden claim scannerが通る。
6. `known_gaps[]` が生成される。

この6条件のどれかが欠ける場合、claimではなく `extraction_candidate` に留める。

### 3.6 CSV private overlayの「安全」がprivacy safetyとbusiness safetyで混ざる

整合:

raw CSV非保存、非ログ、非AWS、派生factのみという方針は強い。

残リスク:

`safe_to_release` や `safe public ID join` のような表現が、取引先・制度・税務の安全性と混ざる可能性がある。

修正契約:

CSVまわりの `safe` は公開payloadでは使わず、privacy限定語へ置換する。

```json
{
  "csv_processing": {
    "raw_csv_persisted": false,
    "raw_csv_logged": false,
    "raw_csv_sent_to_aws": false,
    "privacy_release_status": "aggregate_only",
    "suppression_applied": true,
    "small_group_suppression_threshold": 5
  }
}
```

CSV由来factは次のsupportに限定する。

| CSV fact | 支えられること | 支えられないこと |
|---|---|---|
| `period_covered` | 分析対象期間 | 継続企業性 |
| `expense_bucket_signal` | 支出カテゴリ候補 | 経費適格性の確定 |
| `vendor_identifier_candidate` | public source join候補 | 取引先の安全性 |
| `revenue_size_bucket` | 制度候補の絞り込み | 税務判定 |
| `headcount_bucket_user_supplied` | 条件確認候補 | 労務・社保の正誤 |

### 3.7 `known_gaps[]` が空のときの意味が不足

矛盾:

多くの文書で `known_gaps[]` 必須とされているが、サンプルでは空配列もある。空配列が「gapなし」と誤読される可能性がある。

修正契約:

P0では `known_gaps[]` を単なる配列ではなく、coverage matrixとセットにする。

```json
{
  "known_gaps": [],
  "gap_coverage_matrix": [
    {
      "gap_category": "source_coverage",
      "checked": true,
      "status": "no_known_gap_in_connected_sources",
      "does_not_mean_complete_coverage": true
    },
    {
      "gap_category": "local_government_sources",
      "checked": true,
      "status": "partial_coverage",
      "gap_refs": ["gap_local_pdf_uncollected"]
    }
  ]
}
```

`known_gaps=[]` だけを返すことは禁止する。

### 3.8 決定表の `not_triggered_by_known_inputs` が「不要」と読まれやすい

整合:

`permit_rule_algorithm` は、入力済み条件だけでは発火しないことを「許可不要」としない方針を明記している。

残リスク:

UIで `not_triggered_by_known_inputs` が簡略化されると「許可不要」に変換される。

修正契約:

決定表の外部状態は次に限定する。

```text
triggered_needs_review
not_triggered_by_provided_facts_only
blocked_by_missing_required_facts
ambiguous_requires_user_answer
out_of_scope_for_connected_sources
```

禁止:

- `許可不要`
- `登録不要`
- `届出不要`
- `適法`
- `違法ではない`

許可:

- `入力済み条件だけでは、このルールの発火は確認できませんでした`
- `未入力条件があるため、許認可不要とは判断できません`

## 4. 成果物別の安全契約

### 4.1 補助金・助成金packet

外部ラベル:

- `high_relevance_needs_user_confirmation`
- `medium_relevance`
- `low_relevance_watch_only`
- `not_recommended_due_to_missing_required_facts`

score名:

- `grant_review_priority_score`
- `source_quality_score`
- `known_gap_score`

禁止:

- 採択可能性
- 申請可能
- 対象確定
- 対象外確定
- `eligible` の外部表示

必須gap:

- 所在地
- 業種
- 従業員数
- 売上規模
- 対象経費
- 過去申請・採択
- 期限
- source freshness

### 4.2 許認可・業法packet

外部状態:

- `rule_trigger_candidate`
- `requires_user_confirmation`
- `not_triggered_by_provided_facts_only`
- `source_gap_blocks_decision`

禁止:

- 許可不要
- 適法
- 違法ではない
- 登録不要
- 届出不要

必須:

- 決定表trace
- 入力fact list
- missing questions
- source_receipts
- known_gaps
- human_review_required

### 4.3 取引先・公的確認packet

scoreは3軸固定。

```text
public_evidence_risk_attention_score
evidence_quality_score
coverage_gap_score
```

禁止:

- 信用スコア
- 安全度
- 反社チェック完了
- 問題なし
- 処分歴なし
- 倒産確率

no-hitはscoreを下げない。no-hitはcoverage説明にだけ使う。

### 4.4 法令・制度変更packet

diffから出せるのは「変更候補」「影響候補」「確認候補」まで。

禁止:

- 法的義務の最終判断
- 対応不要
- 違反確定
- 適用対象外確定

必須:

- old/new receipt
- diff span
- effective date candidate
- affected industry candidate
- known_gaps
- human review

### 4.5 CSV overlay packet

CSV由来factはprivate overlayであり、公的sourceそのものではない。

禁止:

- raw CSV保存
- raw CSVログ
- raw CSVをAWSへ送る
- 摘要・個人名・銀行・給与明細の表示
- 取引先名の無抑制表示
- CSVだけで税務・労務・許認可判断

必須:

- privacy release status
- suppression summary
- formula injection対策
- derived fact schema
- leak scan result

## 5. 統一API contract

全packetは最低限この形にする。

```json
{
  "packet_id": "pkt_xxx",
  "packet_type": "string",
  "schema_version": "2026-05-15",
  "algorithm_version": "string",
  "corpus_snapshot_id": "string",
  "request_time_llm_call_performed": false,
  "input_scope": {},
  "source_receipts": [],
  "claim_refs": [],
  "no_hit_checks": [],
  "known_gaps": [],
  "gap_coverage_matrix": [],
  "algorithm_trace": [],
  "score_set": [],
  "human_review_required": [],
  "safety_contract": {
    "no_hit_semantics": "no_hit_not_absence",
    "unsupported_conclusions_forbidden": true,
    "known_gaps_must_be_displayed": true,
    "generic_score_forbidden": true,
    "request_time_llm_claim_generation_forbidden": true
  },
  "billing_metadata": {},
  "_disclaimer": {
    "not_legal_advice": true,
    "not_tax_advice": true,
    "not_financial_advice": true,
    "not_credit_opinion": true,
    "no_hit_not_absence": true
  }
}
```

block条件:

- `request_time_llm_call_performed=true`
- 表示claimに `claim_refs[]` がない
- `claim_ref` に `source_receipts[]` がない
- `known_gaps[]` または `gap_coverage_matrix[]` がない
- no-hitがabsence/safety/complianceへ変換されている
- scoreがprobability/safety/credit/legal/tax decisionとして表示されている
- private CSV raw値が出力・ログ・AWS artifactに残っている
- LLM候補がdeterministic validationなしでclaim化されている

## 6. Forbidden phrase gate

日本語:

```text
安全
安心
問題なし
違反なし
適法
違法ではない
許可不要
登録不要
届出不要
処分歴なし
反社ではない
信用できる
信用力
倒産確率
採択可能性
申請できます
対象です
対象外です
該当なし
存在しません
最新を保証
完全
保証
```

英語:

```text
safe
no risk
no issue
compliant
non-compliant
legal
illegal
license not required
eligible
not eligible
approved
approval likelihood
creditworthy
bankruptcy probability
guaranteed
complete coverage
```

例外:

- 禁止語リスト自体として表示する場合。
- `privacy_release_status` の説明で、business safetyと明確に分離されている場合。
- no-hit disclaimerとして「安全ではありません」「安全を意味しません」と否定形で使う場合。

実装では単純regexだけでなく、否定形・禁止リスト文脈を区別する。ただしP0では過検知を許容し、manual reviewへ送る方が安全。

## 7. Algorithm trace必須項目

すべての決定表、制約充足、score、diff、graph traversalは次を持つ。

```json
{
  "trace_id": "trace_xxx",
  "algorithm_id": "string",
  "algorithm_version": "string",
  "algorithm_family": "decision_table|constraint_satisfaction|scoring|diff_detection|evidence_graph|csv_overlay",
  "input_claim_refs": [],
  "input_source_receipts": [],
  "input_private_fact_refs": [],
  "parameters": {},
  "output_state": "candidate|confirmed|needs_review|withheld",
  "score_set": [],
  "known_gap_refs": [],
  "forbidden_conclusion_check": "pass|block",
  "generated_at": "datetime"
}
```

`output_state=confirmed` にできるのは、source receiptとdeterministic validationがある場合だけ。

## 8. Evidence graphの必須不変条件

1. `claim_ref -> source_receipt` のedgeがないclaimはpaid outputに出さない。
2. `no_hit` receiptは実体claimをsupportしない。
3. `llm_assisted_candidate` は `candidate_only` nodeとして隔離する。
4. `private_csv_derived_fact` はpublic corpusへ混入させない。
5. `known_gap` はpacket, claim, source, traceの少なくとも1つへ接続する。
6. conflictがあるclaimは `conflict_state` を持つ。
7. screenshot/OCR由来claimはbbox/page/hash/viewportを持つ。
8. score componentは、使ったclaimと除外したgapを列挙する。

## 9. AWS credit runへの反映

AWSで大量取得・Playwright・OCR・Bedrock補助を行う場合も、以下を守る。

### 9.1 AWSで作ってよいもの

- public source receipts
- public claim candidates
- source profile registry
- screenshot receipts
- OCR candidate spans
- diff candidates
- no-hit ledgers
- forbidden phrase eval corpus
- packet examples
- proof page examples
- GEO eval reports

### 9.2 AWSで作ってはいけないもの

- private raw CSVを含むartifact
- request-time user CSV処理
- LLMだけで確定したclaim
- no-hitからabsence/safetyを作ったdataset
- scoreだけのランキング
- source terms未確認のsubstantive claim

### 9.3 Bedrock/LLM利用の制限

Bedrock等は次に限定する。

- 公開一次情報の候補分類
- PDF/OCR抽出候補のラベル付け
- duplicate候補のクラスタリング補助
- proof/GEO eval用の攻撃的プロンプト生成

Bedrock等を使った場合、artifactには必ず次を残す。

```json
{
  "llm_used_offline": true,
  "llm_role": "candidate_extraction_only",
  "can_support_claim_without_validation": false,
  "validation_required": true,
  "request_time_llm_call_performed": false
}
```

## 10. 実装順へのマージ

本体計画とAWS計画へ入れる順番は次が正しい。

1. Packet contractに `safety_contract`、typed `score_set`、`gap_coverage_matrix` を追加。
2. forbidden phrase gateを先に実装。
3. no-hit objectを共通schema化。
4. source_receipt / claim_ref / known_gap / algorithm_trace のgraph不変条件をテスト化。
5. CSV private overlayのraw非保存・非ログ・非AWS gateをテスト化。
6. grant/permit/vendor/reg-changeの外部ラベルを弱い候補表現へ統一。
7. scoreの単独表示を禁止し、typed scoreだけ許可。
8. LLM-assisted candidate隔離schemaを実装。
9. AWS artifact import時に上記gateを通す。
10. proof/API/MCP/GEO evalでAI agentが禁止断定へ変換しないか確認。

## 11. Release blocker

以下が1件でもあれば本番デプロイ不可。

- no-hitを「不存在」「安全」「問題なし」「対象外」「登録なし」へ変換した出力。
- `eligible`、`申請できます`、`許可不要`、`信用スコア`、`安全度` の外部表示。
- `score` という汎用数値だけが返るpayload。
- `known_gaps[]` または `gap_coverage_matrix[]` が欠けるpayload。
- LLM-assisted candidateがvalidationなしでclaim化されている。
- raw CSV、摘要、個人名、銀行、給与、取引先名が抑制なしでartifactやログに残っている。
- screenshot/OCR claimにhash、page、bbox、viewport、retrieved_atがない。
- score説明に `not_probability`、`not_safety`、`not_final_decision` がない。
- source terms未確認のデータがsubstantive claimに使われている。

## 12. 最終判定

アルゴリズム設計は、ハルシネーション排除型のAI agent向けサービスとして成立する。

ただし勝ち筋は「AIが判断する」ではなく、次である。

```text
一次情報を取る
証跡化する
claimへ分解する
gapを隠さない
決定表・制約・score・diffで候補成果物を作る
危険な断定を機械的に止める
AI agentには安全なJSONと説明テンプレートだけを渡す
```

この文書の修正契約を本体計画にマージすることを、実装前の必須条件にする。
