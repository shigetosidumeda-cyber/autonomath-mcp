# AWS credit review 05: Textract / Bedrock / OpenSearch

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 5/20  
担当: Textract / Bedrock / OpenSearch の使いどころ、短期価値条件、禁止条件、予算上限、成果物、停止条件  
状態: Markdown追加レビューのみ。実装、AWS CLI/API実行、Terraform/CDK作成、AWSリソース作成、ジョブ投入はしない。

## 0. 結論

Textract、Bedrock、OpenSearch は、今回のAWSクレジット消化で「主役」ではなく、S3/Batch/Athenaで作る public source receipt lane を短期で強化するための条件付きアクセラレータとして扱う。

採用判断は次の一行に集約する。

> 3サービスとも、成果物が `source_receipt` 候補または評価レポートとしてS3/Markdown/Parquet/JSONLに残る場合だけ使う。request-time LLM、private CSV投入、常駐検索基盤化、AI/OCR出力の確定claim化は禁止。

推奨順位:

| 順位 | サービス | 判断 |
|---:|---|---|
| 1 | Textract | 画像PDF・表・フォームでCPU/text-layer抽出が弱いP0/P1 public sourceに限定すれば価値が出る。 |
| 2 | Bedrock batch inference | public-only候補の分類・正規化・レビュー優先度付けに限定すれば使える。request-time回答には使わない。 |
| 3 | OpenSearch | 2-3日の検索品質評価に限定。常駐クラスタ、production search、private corpus投入は禁止。 |

このレビューでの保守的な上限は3サービス合計で **USD 5,100 absolute cap** とする。既存の全体計画では同領域により大きい余地があるが、この3サービスは費用対成果のブレが大きいため、短期価値が見えた時だけ段階解放する。

## 1. 非交渉条件

この文書の対象範囲では、以下を破った時点で利用しない。

- request-time LLMなし。ユーザーリクエスト時にBedrockを呼ぶ経路は作らない。
- private CSV投入なし。摘要、支払先、個人名、顧客固有識別子、row-levelの会計データをTextract/Bedrock/OpenSearch/S3評価prefixへ入れない。
- 成果物は `source_receipt` 候補と評価レポートに限定する。
- AI/OCR/検索結果を確定factとして扱わない。すべて candidate または eval result として扱う。
- 長期運用リソースを残さない。OpenSearchは評価後にexportして削除または停止する前提。
- 残クレジット消化を目的にしない。accepted candidate単価と評価改善が悪化したら止める。

## 2. 予算上限

上限はAWS Budgets等のhard capではなく、後続実行者が守る運用上限として扱う。実行前にはBilling、Pricing Calculator、Service Quotas、対象Region価格を再確認する。

| サービス | Pilot cap | Expand cap | Absolute cap | 解放条件 |
|---|---:|---:|---:|---|
| Textract | USD 150 | USD 1,200 | USD 2,400 | Pilotで `accepted_receipt_candidate_rate >= 25%`、かつ手動レビュー滞留が1営業日以内 |
| Bedrock batch | USD 100 | USD 900 | USD 1,800 | Pilotで重複除去後の分類/正規化がレビュー時間を短縮し、false promotionが0件 |
| OpenSearch | USD 75 | USD 350 | USD 900 | Pilotで既存BM25/SQLite/Athena等の簡易検索より評価指標が明確に改善 |
| 合計 | USD 325 | USD 2,450 | USD 5,100 | 3サービス合算でabsolute capを超えない |

補足:

- Textractはページ単価で直線的に増えやすい。最初にページcapを置く。
- Bedrockはモデル、入力token、出力token、重複投入、再実行で費用が変わる。最初にモデルとmax tokensを固定する。
- OpenSearchは常駐課金が最大リスク。評価期間、OCU/instance、storage、log、snapshotを先に閉じる。

## 3. 成果物の境界

許可する成果物は次だけ。

| Artifact | 形式 | 説明 |
|---|---|---|
| `source_receipt_candidates.parquet` | Parquet | public sourceから抽出されたreceipt候補。確定receiptではない。 |
| `source_receipt_candidate_review_queue.jsonl` | JSONL | 人間またはルール検証が必要な候補のqueue。 |
| `candidate_evidence_spans.jsonl` | JSONL | OCR/抽出/検索で得た根拠span、page、bbox、URL、hash等。 |
| `extraction_eval_report.md` | Markdown | Textract/CPU抽出の精度、費用、失敗理由、採否。 |
| `bedrock_candidate_eval_report.md` | Markdown | Bedrock batchの分類品質、誤分類、token/費用、停止判断。 |
| `retrieval_eval_report.md` | Markdown | OpenSearch評価のquery set、ranking delta、失敗例、削除確認項目。 |
| `cost_and_stop_ledger.csv` | CSV | 予算上限、消化見込み、停止判断の記録。private dataは含めない。 |

禁止する成果物:

- private CSV row、会計摘要、顧客名、支払先名を含むS3 object、index、prompt、log。
- Bedrock出力をそのまま公開するclaim。
- OpenSearchをproduction searchとして残すための運用runbook。
- Textract raw responseの無制限長期保管。必要最小のspan/confidence/geometryに縮約する。

## 4. Textract

### 4.1 使うべき条件

Textractは、P0/P1の公的PDFに対してCPU parserやtext-layer抽出が不足する場合だけ使う。

使う条件:

- 対象がpublic sourceで、取得元URL、snapshot hash、license/termsメモがある。
- PDFが画像主体、または表/フォーム構造がreceipt候補に直結する。
- 先にCPU/text-layer抽出を試し、抽出不能または構造欠落が記録されている。
- 抽出結果をレビューできる人間/ルール検証の容量がある。
- `source_receipt` 候補に必要なfieldが明確で、不要な全文OCRを増やさない。

短期で価値が出る例:

- 自治体補助金PDFの対象者、期限、必要書類、問い合わせ先、申請URL候補。
- 省庁PDFの表にある制度名、対象期間、地域、金額レンジ候補。
- HTMLには出ていないがPDFだけにある更新日、版番号、根拠資料名。

### 4.2 使ってはいけない条件

- text layer付きPDFで通常parserが十分な場合。
- 大量PDFをpage capなしに投げる場合。
- private CSV、顧客アップロード文書、契約書、請求書、個人情報を含む文書。
- OCR confidenceが低く、review queueが詰まっている状態。
- AnalyzeDocumentのForms/Tables/Queriesを全ページに広くかけるだけの設計。
- `AnalyzeExpense`、`AnalyzeID` のようにjpciteのpublic source receiptと関係が薄いAPI。

### 4.3 Pilot設計

Pilotは最大 USD 150 または最大 2,000 pages の小さい方で止める。

入力:

- P0/P1 source familyから最大20 document。
- CPU/text-layer抽出失敗または弱抽出のdocumentだけ。
- 1 documentあたり最大100 pages。長大PDFは重要page範囲を先に選ぶ。

出力:

- `textract_source_receipt_candidates.parquet`
- `textract_ocr_confidence_ledger.parquet`
- `textract_parse_failure_sample.jsonl`
- `extraction_eval_report.md`

Pilot合格条件:

- accepted receipt candidate rate が25%以上。
- `support_level=strong` または `support_level=reviewable` の候補が増える。
- OCR由来の誤読が公開claim化していない。
- 1 accepted candidateあたりの推定費用が、CPU抽出改善より明確に低い、またはCPUでは取れないfieldを埋めている。

停止条件:

- accepted receipt candidate rate が15%未満。
- low-confidence候補が全体の40%を超え、レビューが詰まる。
- 同一source familyでテンプレート崩れが多く、抽出規則化できない。
- private data混入の疑いが1件でも出る。
- Textract費用がExpand capの50%に達してもP0 receipt field充足率が改善しない。

## 5. Bedrock batch inference

### 5.1 使うべき条件

Bedrockは、request-time LLMではなく、offline/batchで public-only candidate を分類・正規化する用途に限定する。

使う条件:

- 入力はpublic URL、public documentから抽出された短いspan、既存のsource metadataだけ。
- dedupe済みで、同じspan/URL/titleを再投入しない。
- 出力schemaが閉じている。自由要約ではなく分類、field normalization、review priorityを中心にする。
- max input tokens、max output tokens、model id、temperature相当設定を固定する。
- すべて `candidate` として保存し、source receiptとルール検証なしに公開claimへ昇格しない。

短期で価値が出る例:

- `receipt_field_type` の分類: deadline、amount、eligibility、region、source_owner、update_date。
- no-hit/gap reason分類: not_found、not_public、ambiguous、stale、license_unknown。
- OCR候補の正規化: 和暦/西暦、全角半角、部署名、制度名の表記ゆれ。
- eval補助: forbidden claim候補、weak source候補、review priorityの下書き。

### 5.2 使ってはいけない条件

- request-time回答、チャット、API response生成。
- private CSV、会計データ、顧客文書、個人情報を含むprompt。
- 法務、税務、信用、補助金可否などの最終判断。
- 長文PDF全文を丸ごと投入する設計。
- RAG基盤やKnowledge Basesを今回の短期成果物目的で新設すること。
- Guardrails、Agents、Model Evaluation等の周辺機能を目的なしに広げること。

### 5.3 Pilot設計

Pilotは最大 USD 100 または最大 10,000 candidate input records の小さい方で止める。

入力:

- Textract/CPU抽出済みのpublic span。
- 1 recordあたり短い根拠span、source URL、source id、document hash、既存field候補。
- promptには「確定しない」「不明ならunknown」「出典span外を補完しない」を明記する。

出力:

- `bedrock_receipt_field_labels.jsonl`
- `bedrock_claim_normalization_candidates.jsonl`
- `bedrock_review_priority_candidates.jsonl`
- `bedrock_candidate_eval_report.md`

Pilot合格条件:

- `unknown` を許容し、出典span外の補完が出ない。
- サンプルレビューで false promotion が0件。
- ルールだけでは分類しづらいfieldのレビュー時間を短縮する。
- accepted candidate単価がExpand前に見積もれる。

停止条件:

- 出典spanにない補完、断定、推測がサンプルで1件でも出る。
- private data混入の疑いが1件でも出る。
- token重複率が10%を超える。
- 出力の30%以上が人間レビューで修正必要。
- request-time LLM経路への転用圧が出た時点で今回範囲から外す。

## 6. OpenSearch

### 6.1 使うべき条件

OpenSearchは、短期のretrieval quality benchmarkだけに使う。正本はS3/Parquetであり、OpenSearch indexは評価用の一時派生物とする。

使う条件:

- query set、expected source family、評価指標が事前にある。
- 評価対象はpublic source receipt候補とpublic metadataだけ。
- 2-3日のtime-boxがある。
- index config、query results、ranking deltaをexportして削除できる。
- 簡易検索では足りない理由がある。例: 日本語tokenizer、同義語、field boost、hybrid lexical/vector routingの比較。

短期で価値が出る例:

- 制度名・自治体名・対象者・金額表現の表記ゆれ検索評価。
- source receipt候補の上位N件retrievalで、既存検索と比較したrecall/precision改善。
- no-hit判定の妥当性チェック。
- GEO evalで参照されるsource候補のranking改善。

### 6.2 使ってはいけない条件

- production search基盤として残すこと。
- private CSV、顧客行、会計摘要、支払先、個人名のindexing。
- ダッシュボードやログ分析を目的にした常駐化。
- Serverless/managed clusterの最低容量や常駐費用を読まずに作ること。
- snapshot/export/deleteの完了条件なしに評価を始めること。
- Bedrock等で生成した未検証テキストを検索正本としてindexすること。

### 6.3 Pilot設計

Pilotは最大 USD 75 または最大72時間の小さい方で止める。

入力:

- 最大50,000 source receipt candidate records。
- 最大200 query set。
- private fieldを持たないpublic metadataだけ。

出力:

- `opensearch_query_relevance_cases.jsonl`
- `opensearch_ranking_delta.csv`
- `opensearch_index_config_export.json`
- `retrieval_eval_report.md`
- `opensearch_delete_checklist.md`

Pilot合格条件:

- 既存検索baselineに対して、P0 query setでrecall@10またはreview hit rateが明確に改善する。
- false positiveがレビュー可能な範囲に収まる。
- index configとquery resultがexportされ、OpenSearchなしで評価レポートを読める。
- 削除手順と削除確認が成果物に残る。

停止条件:

- 24時間以内にbaseline差分が出ない。
- 検索品質改善より運用設定/IAM/network設定の作業が大きくなる。
- 常駐利用の要望が出る。
- private data混入、public exposure、削除不能のいずれかの疑いがある。
- OpenSearch costがPilot capに近づいても評価レポートが作れない。

## 7. 統合フロー

3サービスを使う場合も、次の順番を崩さない。

1. S3/Batch/CPU parserでpublic source候補を作る。
2. Athena/ローカル検証でprivate data混入と重複を落とす。
3. TextractはCPU抽出が弱いP0/P1 PDFだけにかける。
4. Bedrock batchはdedupe済み短文spanだけを分類・正規化する。
5. OpenSearchはexport可能な一時indexでretrieval benchmarkを行う。
6. すべての出力を `source_receipt` 候補または評価レポートとして保存する。
7. AI/OCR/search候補はsource receipt検証を通るまで公開claimにしない。

## 8. Go / No-Go matrix

| 状況 | Textract | Bedrock batch | OpenSearch |
|---|---|---|---|
| public PDFが画像主体で、期限/対象/金額が表にある | Go | Maybe after OCR | Maybe for retrieval eval |
| text layer抽出でreceipt fieldが埋まる | No-Go | Maybe for normalization | No-Go unless benchmark need |
| private CSVや顧客データを含む | No-Go | No-Go | No-Go |
| request-time回答を改善したい | No-Go | No-Go | No-Go for this review |
| public candidateが多くreview優先度付けが必要 | Maybe | Go | Maybe |
| 検索品質の定量比較だけしたい | No-Go | Maybe for labels | Go |
| 成果物がreport/exportなしの一時画面だけ | No-Go | No-Go | No-Go |
| 常駐サービスとして残したい | No-Go | No-Go | No-Go |

## 9. 停止判断

サービス個別の停止条件に加え、次の横断条件で全停止する。

- 3サービス合計でPilot cap USD 325に達したが、どの評価レポートにもGo根拠がない。
- 3サービス合計でExpand cap USD 2,450に達した時点で、P0 source receipt候補の採用率・coverage・review効率が改善していない。
- absolute cap USD 5,100に近づいた。
- private data混入の疑いがある。
- request-time LLMやproduction searchへ転用する設計変更が必要になった。
- review queueが処理容量を超え、候補が滞留する。
- 成果物がsource receipt候補や評価レポートではなく、運用ログや一時indexだけになっている。

停止後に残すもの:

- cost and stop ledger
- candidate manifests
- evaluation reports
- OpenSearch export/delete confirmation
- blocked reason ledger

停止後に残さないもの:

- running jobs
- OpenSearch domain/serverless collection
- 評価再現に不要なtemporary index snapshots
- raw private data
- unbounded CloudWatch debug logs

## 10. 後続実行者へのチェックリスト

このレビュー自体では実行しない。後続で実行する場合は、開始前に次を満たす。

- [ ] AWS account/profile/region/billing visibilityが確認済み。
- [ ] `request_time_llm_call_performed=false` を成果物メタデータに残す。
- [ ] private CSV pathや顧客データpathが入力manifestに存在しない。
- [ ] service別Pilot cap、Expand cap、Absolute capがrun ledgerに記載済み。
- [ ] Textract page cap、Bedrock token cap、OpenSearch time-boxが設定済み。
- [ ] 成果物prefixが `source_receipt_candidates/` と `eval_reports/` に限定されている。
- [ ] OpenSearchは開始前にexport/delete checklistがある。
- [ ] 成果物レビュー担当と停止判断者が決まっている。

## 11. References checked

2026-05-15時点で、設計判断のため公式AWSページを確認した。価格、Region、quota、クレジット適用条件は変わり得るため、実行直前にAWS Billing/Pricing Calculator/Service Quotasで再確認する。

- Amazon Textract pricing: https://aws.amazon.com/textract/pricing/
- Amazon Bedrock pricing: https://aws.amazon.com/bedrock/pricing/
- Amazon Bedrock batch inference documentation: https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html
- Amazon OpenSearch Service pricing: https://aws.amazon.com/opensearch-service/pricing/
- Existing internal matrix: `docs/_internal/aws_credit_services_matrix_agent.md`
- Existing internal guardrails: `docs/_internal/aws_credit_cost_guardrails_agent.md`
