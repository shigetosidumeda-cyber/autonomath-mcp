# AWS credit services matrix for jpcite

作成日: 2026-05-15  
担当: AWSサービス別の用途 / 費用リスク / 成果物マトリクス  
対象クレジット: USD 19,493.94  
状態: Markdown追加レビューのみ。実装、AWS CLI/API実行、Terraform/CDK作成、AWSリソース作成、ジョブ投入はしない。

## 0. 結論

今回のAWSクレジットは、長期インフラではなく、1-2週間の短期「公的source lake + receipt-grade extraction + packet/proof/eval成果物」へ変換する。採用優先度は次の通り。

| Tier | サービス | 判断 |
|---|---|---|
| Core | S3, AWS Batch, EC2 Spot, Fargate Spot, Glue Data Catalog, Athena, CloudWatch, ECR | 使う価値が高い。成果物がS3/Parquet/manifest/proof/reportとして残る。 |
| Conditional | Textract, Bedrock batch inference, OpenSearch, Step Functions, Lambda, CodeBuild | 用途を絞れば有効。単価・並列・ログ・常駐・モデル利用の費用暴走を強く制御する。 |
| Avoid / tiny pilot only | QuickSight, long-lived OpenSearch, long-lived Fargate service, NAT-heavy private networking, Reserved/Savings/Marketplace/Support upgrade | 短期クレジット消化に対して成果物が残りにくい、または現金請求・継続課金・契約リスクが大きい。 |

推奨アーキテクチャは **S3を正本、Batch/Spot/Fargateを短命compute、Glue/Athenaを検証面、Textract/Bedrock/OpenSearchは時間制限付きの価値増幅器** とする構成。QuickSightは意思決定用の人間ダッシュボードには便利だが、jpciteのGEO-first資産には直接効きにくいので、今回のクレジット計画では後回し。

## 1. 評価基準

| 軸 | 高評価 | 低評価 |
|---|---|---|
| jpcite用途適合 | source receipt, known gaps, public proof, packet fixture, GEO evalに直結 | 汎用BI、常時配信、運用便利機能だけ |
| 成果物残存性 | クレジット終了後もS3/Parquet/JSONL/HTML/reportとして残る | 実行ログ、ダッシュボード、常駐cluster、短期cacheだけ |
| 費用制御 | tag、queue disable、timeout、max concurrency、workgroup limitで止めやすい | 課金遅延、常駐、容量予約、出力爆発、データ転送料が読みにくい |
| セキュリティ/規約適合 | public-only、hash-only、metadata-only境界を守りやすい | private CSVや未確認sourceのraw保持を誘発する |
| 実行準備負荷 | 既存Python/CLI/batch化に近い | 大規模な新規運用面やIAM/ネットワーク設計が必要 |

スコア:

- `A`: 主用途に採用。
- `B`: 用途を限定して採用。
- `C`: 小規模pilotまたは代替不能時のみ。
- `D`: 今回は原則使わない。

## 2. サービス別マトリクス

| Service | Score | jpcite用途 | 費用リスク | 残す成果物 | ガードレール / 停止条件 |
|---|---:|---|---|---|---|
| S3 | A | source lake、raw/normalized/parquet、receipt、proof、eval report、cost manifestの正本 | storage増加、request、cross-region transfer、versioning肥大、lifecycle未設定 | `source-lake/*`, `receipts/*`, `reports/*`, `proof/*`, manifest | bucket/prefix単位tag、lifecycle、raw保持class、同一Region、temporary prefix削除 |
| AWS Batch | A | crawler/parser/OCR前処理/packet生成/static proof/GEO evalの大規模array job | timeout未設定、retry storm、RUNNABLE滞留、queue停止漏れ | job run manifest、artifact manifest、failure ledger | `attemptDurationSeconds`必須、max vCPU段階上げ、queue disable runbook、array shard小粒化 |
| Fargate / Fargate Spot | A- | 1-30分のstateless parser、small packet job、control job | vCPU/GB秒、public IPv4、CloudWatch Logs、image pull時間、Spot中断 | short-job outputs、parser summaries、small packet fixtures | Spotはinterrupt-tolerantのみ、task timeout、logs抑制、追加ephemeral storage禁止寄り |
| EC2 Spot | A | CPU heavy PDF parse、join、compaction、static generation、大量batch | interruption、EBS残存、AZ/instance不足、起動失敗、容量追跡 | Parquet、dedupe output、PDF parse ledger、static pages | checkpoint必須、managed Batch経由、mixed instance family、EBS cleanup、On-Demand rescue少量 |
| Glue Data Catalog | A- | S3 datasetsのschema catalog、partition、Athena分析面 | crawler乱用、DPU job常駐、metadata肥大、schema drift放置 | catalog schema、partition spec、schema drift report | Catalog中心。Glue ETLは必要時のみ。crawlerは範囲固定 |
| Athena | A- | coverage/freshness/no-hit/license/private leak/claim conflict query | raw JSON/HTML scan、巨大uncompressed file、workgroup制限なし、query result増殖 | QA SQL、daily reports、CSV/MD summaries | Parquet + compression、workgroup bytes scanned limit、result lifecycle、federated query禁止寄り |
| Textract | B+ | 自治体/省庁PDF、申請様式、表/フォーム抽出候補 | page単価、AnalyzeDocument featuresの選びすぎ、低品質PDF大量投入、human review backlog | extracted fact candidates、OCR confidence ledger、parse failure ledger | sample precision gate、DetectDocumentTextから開始、forms/tablesはP0だけ、page cap |
| Bedrock batch inference | B | public-only抽出候補の分類、要約、claim candidate normalization、GEO eval補助 | token/モデル単価、batch input重複、外部APIではないがAI出力review必須、quota | candidate claims、classification labels、review queue、eval judge draft | public-only、モデル/単価固定、max tokens、dedupe before inference、AI出力は未確定candidate |
| OpenSearch | B- | 短期retrieval quality benchmark、lexical/vector candidate search、exportable index eval | managed cluster/Serverless OCU常駐、storage、snapshot、ログ、削除忘れ | relevance benchmark、query set、index export/snapshot、ranking deltas | time-boxed、tiny corpus first、TTL、delete after export。長期production search化しない |
| CloudWatch | A- | Batch/Fargate/EC2/Step Functionsの最小監視、alarms、stop signal | log ingestion爆発、Logs Insights、custom metrics大量、retention未設定 | alarm history、log summaries、cost/failed job metrics | retention 3-14日、stdout要約のみ、debug logsはS3 sampleへ、custom metrics限定 |
| CodeBuild | B | container build、test matrix、SBOM/security scan、OpenAPI/MCP fixture validation | build minute、Docker image server/persistent cache、reserved capacity、Mac 24h minimum | build/test reports、scan reports、image digest、release gate evidence | bulk compute sinkにしない、reserved/Mac禁止、timeout、batch size制限 |
| Step Functions | B | orchestration、Distributed Map風の明示concurrency、human-readable run graph | state transition、retry multiplication、Express duration/payload、map並列暴走 | execution summary、orchestration manifest、failure routing report | `MaxConcurrency`必須、payloadはS3参照、retry上限、Batch nativeで足りるなら使わない |
| Lambda | B- | lightweight coordinator、manifest validator、Athena report trigger、stop helper | request/duration、concurrency、recursive trigger、S3 event storm、ログ課金 | validation result、small control reports | 15分以下、reserved concurrency、S3 prefix filter、large ETL禁止 |
| ECR | A- | batch image registry、immutable image digest、reproducible jobs | image storage肥大、cross-region pull、scan設定、lifecycle未設定 | image digest, SBOM, provenance, build manifest | lifecycle policy、same-region compute、tag immutability、必要imageだけ |
| QuickSight | C- | operator dashboard、coverage/cost overviewの人間閲覧 | user/subscription/SPICE/Reader/Author/alert課金、解約忘れ、成果物残存性が低い | dashboard screenshot/export程度 | 今回はAthena report + static MDで代替。使うなら1 author短期pilotだけ |
| Cost Explorer / Budgets | A | gross burn/paid exposure監視、service/tag別日次確認 | hard capではない、反映遅延、CE API/時間粒度費用 | daily cost ledger、threshold log | 既存guardrails計画に従う。Actual重視、forecastは補助 |
| IAM / SCP / KMS | B | stop policy、least privilege、S3 encryption | KMS request、過剰denyでcleanup不能、policy複雑化 | policy docs、access review | 最小限。Budget Actionやoperator stopを邪魔しない |
| VPC / NAT / Data Transfer | D for spend | private subnet化、egress control | NAT Gateway常駐、data transfer、public IPv4、cross-AZ | network cost reportのみ | 今回は同一Region・public AWS endpoint中心。NAT-heavy構成は避ける |

## 3. 推奨サービス構成

### 3.1 Minimal useful stack

最小で価値が残る構成。

| Layer | Service | 役割 |
|---|---|---|
| Durable storage | S3 | raw/normalized/parquet/receipt/report/proofの正本 |
| Batch compute | AWS Batch on EC2 Spot and Fargate Spot | crawler、parser、normalizer、packet/proof生成 |
| Metadata/query | Glue Data Catalog + Athena | schema、coverage、freshness、license、no-hit、leak scan |
| Observability | CloudWatch + Budgets/Cost Explorer | 最小log、alarm、service別cost監視 |
| Reproducibility | ECR + CodeBuild tiny lane | container image、digest、test/security report |

このstackだけでも、jpciteに残る資産は十分作れる。Textract、Bedrock、OpenSearch、Step Functionsは、P0成果物の不足が明確な場合だけ足す。

### 3.2 Conditional accelerators

| Accelerator | 使う条件 | 使わない条件 |
|---|---|---|
| Textract | PDFが画像主体で、CPU parserでは表/フォーム抽出が弱い | text layer付きPDFが多い、OCR候補のreviewが詰まる |
| Bedrock batch | public-only fact候補を大量に分類/正規化し、人間reviewに回す | raw private CSV、法務/税務/信用の最終判断、request-time回答 |
| OpenSearch | retrieval benchmarkやquery routing改善を数日で測る | 長期検索基盤として常駐させるだけ |
| Step Functions | 監査可能なrun graphや複数サービス連携が必要 | Batch array + S3 manifestで足りる |
| Lambda | 小さいcontrol-plane hookが必要 | ETL本体、PDF処理、長時間join |
| QuickSight | どうしても人間向けdashboardが必要 | Markdown/CSV/Athena reportで足りる |

## 4. サービス別詳細

### 4.1 S3

採用: `A`

jpciteで最も重要。クレジット消化後も残る価値はS3上の成果物で決まる。

主用途:

- `source-lake/raw/{source_id}/snapshot_date=.../`
- `source-lake/normalized/{source_id}/snapshot_date=.../`
- `source-lake/parquet/{dataset}/snapshot_id=.../`
- `source-lake/receipts/{snapshot_id}/source_id=.../`
- `source-lake/reports/{run_id}/`
- `source-lake/proof/{packet_type}/{example_id}/`
- `source-lake/manifests/{run_id}/`

費用リスク:

- raw PDF/HTMLを全部保持するとstorageとrequestが増える。
- cross-region replicationや別Region computeからのアクセスはdata transferを増やす。
- versioningを雑に有効化すると削除したつもりのobjectが残る。
- Athena query result、CloudWatch export、temporary chunksが増殖する。

成果物:

- `object_manifest.parquet`
- `source_document_manifest.parquet`
- `source_receipt.parquet`
- `claim_source_link.parquet`
- `known_gaps.parquet`
- `cost_manifest.parquet`
- proof HTML/JSON

判断:

- raw保持は `raw_allowed`, `hash_only`, `metadata_only`, `blocked` に分ける。
- 本文再配布や第三者権利が曖昧なsourceは、長期raw保持ではなくhash/metadata/derived factへ寄せる。
- S3は節約対象ではなく成果物の保管場所。ただし中間prefixはlifecycleで短期削除。

### 4.2 AWS Batch

採用: `A`

今回の主compute面。Batchそのものが成果物を作るのではなく、S3に成果物を吐く短命job managerとして使う。

主用途:

- official source profile sweep
- source receipt ledger precompute
- public PDF extraction
- evidence packet precompute
- cross-source join expansion
- static proof/public page generation
- GEO/SEO benchmark preprocessing
- Parquet compaction and dedupe

費用リスク:

- job timeout未設定。AWS Batchはtimeout未設定だとcontainer終了まで走る。
- retry storm。失敗jobが同じ入力で再試行し続ける。
- array jobが大きすぎて失敗単位が粗くなる。
- RUNNABLE backlogが見えず、queueを止めても既に投入済みの作業が残る。

成果物:

- `run_manifest.json`
- `job_parent_manifest.jsonl`
- `batch_child_result.jsonl`
- `failure_sample.jsonl`
- `accepted_artifact_manifest.parquet`

判断:

- 全jobに `attemptDurationSeconds`、workload-specific timeout、max retryを入れる。
- array sizeはまず100-500、安定後でも2,000以内を標準にする。
- queue単位で `DISABLED` にできる設計にする。
- `RUNNABLE/SUBMITTED/PENDING` はcancel、`STARTING/RUNNING` はterminateできるrunbookを前提にする。

### 4.3 Fargate / Fargate Spot

採用: `A-`

短いstateless jobには向く。EC2管理を避けられ、Batch on Fargateで小粒処理を流せる。

主用途:

- HTML/API parser
- small JSONL normalization
- packet fixture rendering
- small no-hit regression
- manifest validation

費用リスク:

- vCPU、memory、OS/architecture、storage、実行秒に応じて課金される。
- Fargate Spotは安いが中断されるため、checkpointなしの長時間処理に向かない。
- 20GBを超えるephemeral storage、public IPv4、CloudWatch Logsが副費用になる。
- image pull時間も実行時間に含まれるため、巨大imageは不利。

成果物:

- parser summary
- packet JSON
- validation report
- short job result manifest

判断:

- Fargate Spotは1-30分のinterrupt-tolerant作業。
- PDF OCRやlarge joinはEC2 Spot側へ寄せる。
- job stdoutは要約だけ。大きなdebugはS3 sampleへ。

### 4.4 EC2 Spot

採用: `A`

大きめのCPU/メモリ処理はEC2 Spotが最も費用対効果を出しやすい。Spotは最大90%程度の割引を得られる可能性があるが、capacityと中断が前提。

主用途:

- CPU PDF parse
- OCR前処理
- large join
- dedupe
- Parquet compaction
- static proof generation
- large GEO fixture generation

費用リスク:

- Spot interruptionで単発長時間jobが無駄になる。
- EBS volumeやENIが残る。
- instance family/AZに寄せすぎるとcapacity不足で詰まる。
- On-Demand rescueを広げすぎると費用が跳ねる。

成果物:

- PDF parse ledger
- compaction output
- join candidate table
- static proof pages
- benchmark tables

判断:

- AWS Batch managed compute environment経由に限定する。
- checkpointをS3に置き、1 shardを再実行可能にする。
- On-Demand rescueはdeadline前の少数再実行だけ。

### 4.5 Glue

採用: `A-`

Glueは、ETL実行基盤としてよりもData Catalogとschema QA面で価値が高い。

主用途:

- S3 Parquet datasetsのData Catalog
- source family / snapshot / receipt kind / freshness partition
- schema drift検査
- Athena reportの基盤

費用リスク:

- crawlerを広範囲に回すと無駄なmetadataと実行費が増える。
- Glue ETL jobを常用するとDPU課金が増える。
- 小ファイルを放置するとAthena側のquery効率も落ちる。

成果物:

- database/table schema
- partition projection spec
- schema drift report
- data quality report

判断:

- Catalog中心。ETLはBatch/Pythonで足りるならGlue jobに寄せない。
- crawlerはprefix固定、スケジュールなし、必要時だけ。
- `source_profile`, `source_document`, `source_receipt`, `claim_ref`, `no_hit_check`, `freshness_ledger` を最優先tableにする。

### 4.6 Athena

採用: `A-`

短期runの品質確認に強い。S3上のParquetをSQLで検査し、レポートを残す。

主用途:

- P0 source coverage
- source profile completeness
- receipt missing fields
- no-hit safety audit
- freshness breach
- license boundary exposure
- claim conflict report
- private leak scan

費用リスク:

- Athena SQLはscan量が費用に直結する。
- raw text/JSON/HTMLを直接scanすると高い。
- query resultsもS3保存費になる。
- federated queryはLambda等の追加費用を生む。

成果物:

- `athena_report/*.csv`
- `athena_report/*.md`
- `quality_gate_summary.json`
- query SQL files

判断:

- Parquet + compression + partition必須。
- workgroupにbytes scanned limitを置く。
- SQLはreport生成用に固定し、探索queryを無制限にしない。

### 4.7 Textract

採用: `B+`

画像PDFや表/フォームが多い公的文書では有効。ただし単価とreview backlogが最大リスク。

主用途:

- 自治体補助金PDF
- 申請様式PDF
- 省庁資料の表/フォーム
- 期限、対象者、除外条件、必要書類の候補抽出

費用リスク:

- page単価。大量PDF投入で直線的に増える。
- AnalyzeDocumentでForms/Tables/Queriesを広く使うとDetectDocumentTextより高くなりやすい。
- OCR confidenceが低いままcandidateを増やすと人間reviewが詰まる。
- 非公開/権利未確認PDFをraw保持すると法務リスクがある。

成果物:

- `textract_candidates.jsonl`
- `ocr_confidence_ledger.parquet`
- `pdf_parse_failure_ledger.parquet`
- `human_review_queue.jsonl`

判断:

- まずCPU/text-layer抽出で十分か判定。
- TextractはP0/P1 PDFだけ、page capを置く。
- `support_level=weak` の候補はpacketに直接出さずreview queueへ。

### 4.8 Bedrock batch inference

採用: `B`

AI inferenceを使うなら、request-time回答ではなく、public-only候補の分類・正規化・review支援に限定する。Bedrock batch inferenceは対象モデルでon-demandより安い場合があるが、モデル・Region・quota・入力設計で費用が大きく変わる。

主用途:

- public sourceのclaim candidate分類
- PDF抽出候補のfield normalization
- no-hit/gap reasonの分類
- GEO evalの補助judge draft
- source profileのpolicy field候補作成

費用リスク:

- token量、モデル選択、出力長、重複入力。
- AI出力を確定factとして扱う品質リスク。
- batch quota、job待ち、再実行時の重複課金。
- Guardrails等の周辺機能を広げると追加費用。

成果物:

- `bedrock_candidate_labels.jsonl`
- `claim_normalization_candidates.jsonl`
- `review_required_queue.jsonl`
- `eval_judge_draft.jsonl`

判断:

- private CSVや顧客情報は入れない。
- `request_time_llm_call_performed=false` は維持する。
- dedupe後に投入し、max tokensを短く固定。
- 出力は必ずcandidateであり、source receiptと人間/ルール検証なしに公開claimへ昇格しない。

### 4.9 OpenSearch

採用: `B-`

検索品質の短期評価には使えるが、常駐させるとクレジット後の継続費用が残る。jpciteの正本はS3/Parquetであり、OpenSearchは評価用indexと考える。

主用途:

- retrieval benchmark
- source/claim candidate search
- synonym/tokenizer比較
- hybrid lexical/vector routing評価

費用リスク:

- managed clusterはinstance hour、storage、data transferが継続する。
- ServerlessはOCU等の常駐/最低容量の読み違いが起きやすい。
- indexing logs、slow logs、snapshot storageも増える。
- benchmark終了後に削除し忘れると成果物より費用が残る。

成果物:

- `retrieval_benchmark_summary.md`
- `query_relevance_cases.jsonl`
- `index_config_export.json`
- `ranking_delta.csv`

判断:

- 2-3日のtime-boxed pilotに限定。
- 成果物export後は削除またはscale down。
- production searchの恒久採用判断は別計画。

### 4.10 CloudWatch

採用: `A-`

短期runの安全運用には必要。ただしCloudWatch Logsは成果物ではない。

主用途:

- Batch/Fargate/EC2のfailed/running metrics
- budget/stop alarmの補助
- minimal operational logs
- Step Functions/Lambda error observation

費用リスク:

- stdout大量出力によるlogs ingestion。
- Logs Insightsの大規模scan。
- high-cardinality custom metrics。
- retention未設定のlog group。

成果物:

- alarm history
- failed job summary
- cost/usage checkpoint report

判断:

- log retentionは3-14日。
- job logは要約とerror sampleだけ。
- 成果物はS3に保存し、CloudWatchをデータ保管庫にしない。

### 4.11 CodeBuild

採用: `B`

build/test/security laneとしては有用。大量compute消化には使わない。

主用途:

- batch container build
- SBOM/security scan
- test matrix
- OpenAPI/MCP fixture validation
- static proof render check

費用リスク:

- build minute / selected compute type。
- Docker image serverやpersistent cacheの継続課金。
- reserved capacityやMac instanceは短期クレジットに不向き。
- build logs過多。

成果物:

- image digest
- SBOM
- vulnerability scan report
- test report
- release gate evidence

判断:

- reserved/Macは禁止。
- timeoutとartifact retentionを明示。
- CodeBuildは品質ゲートであり、ETL本体はBatchへ。

### 4.12 Step Functions

採用: `B`

監査しやすいworkflowには向くが、Batchのarray jobで足りるなら増やさない。

主用途:

- crawl -> parse -> normalize -> QA -> report のrun graph
- manual approval checkpoint
- small fan-out orchestration
- failure routing

費用リスク:

- Standardはstate transition課金。retryもtransitionを増やす。
- Expressはrequest、duration、memory/payloadで課金。
- Map/Parallelのconcurrencyを誤ると下流Batch/Lambdaが暴走する。
- payloadに大きなJSONを持たせると費用と失敗率が上がる。

成果物:

- execution summary
- stage duration report
- failure routing ledger

判断:

- `MaxConcurrency` と retry cap必須。
- payloadはS3 key参照。
- 大規模fan-outはBatch native優先。

### 4.13 Lambda

採用: `B-`

小さいcontrol-plane処理だけに使う。データ処理本体はBatch/EC2/Fargateへ寄せる。

主用途:

- manifest validation
- Athena report trigger
- S3 object event filter
- emergency stop helper
- cost checkpoint formatter

費用リスク:

- S3 event storm。
- recursive trigger。
- concurrency上限未設定。
- logs出力過多。
- 15分制限に引っかかる処理を無理に詰める。

成果物:

- validation report
- trigger audit log
- stop helper output

判断:

- reserved concurrencyを小さく固定。
- prefix filter必須。
- large file parse、OCR、joinは禁止。

### 4.14 ECR

採用: `A-`

Batch/Fargate/CodeBuildの再現性を支える。費用は小さめだが、image肥大とcross-region pullに注意。

主用途:

- parser/normalizer image
- packet generator image
- eval runner image
- immutable digestによるrun再現性

費用リスク:

- 古いimage tagが残る。
- cross-region replication/pull。
- scan設定の誤解。
- imageが巨大化し、Fargate pull時間も増える。

成果物:

- image digest manifest
- build provenance
- SBOM
- vulnerability report

判断:

- lifecycle policyで古いuntagged image削除。
- same-region computeからpull。
- tag immutabilityとdigest pinning。

### 4.15 QuickSight

採用: `C-`

人間向けdashboardには便利だが、今回の目的であるAI/agent向け成果物には弱い。

主用途:

- operator向けcoverage dashboard
- cost/service breakdown visualization
- source family health overview

費用リスク:

- user subscription、Reader/Author、SPICE、alert/anomaly detection。
- クレジット終了後も契約/ユーザーが残りやすい。
- dashboardは成果物としてrepoやstatic siteに残しにくい。

成果物:

- dashboard export/screenshot
- data dictionary
- dashboard definition

判断:

- 原則使わない。
- Athena report + static Markdown/CSVで代替する。
- 使う場合は1 Author、短期、SPICE最小、AutoStop/delete checklist必須。

## 5. jpcite成果物別のサービス対応

| 成果物 | Primary services | Optional services | 完了条件 |
|---|---|---|---|
| S3 source lake | S3, Batch, EC2 Spot/Fargate | Glue, Athena | raw/normalized/parquet/manifestが揃う |
| source profile registry | Batch, S3, Athena | Bedrock batch | license/freshness/no-hit fieldsの欠損が減る |
| source receipt ledger | Batch, S3, Athena | Textract, Bedrock batch | required receipt fieldsが埋まり、weak claimsがknown_gapsへ移る |
| PDF extraction candidates | EC2 Spot, S3 | Textract, Bedrock batch | confidence ledgerとreview queueが残る |
| Parquet canonical datasets | Batch, S3, Glue, Athena | Glue ETL | partitioned compressed Parquetでqueryが安定 |
| public packet examples | Batch/Fargate, S3 | Bedrock batch for candidate normalization | P0 6 packet typesがreceipt付きで完成 |
| proof pages | Batch/EC2 Spot, S3, CodeBuild | OpenSearch for retrieval validation | 全visible claimがreceiptまたはknown_gapsに接続 |
| GEO eval reports | Batch, S3, Athena, CodeBuild | Bedrock batch for draft judging | 200-query core + mutation + forbidden claim scan |
| OpenAPI/MCP discovery assets | CodeBuild, S3 | Lambda validation | schema hash、examples、must-preserve fieldsが固定 |
| retrieval benchmark | S3, Batch | OpenSearch | query set、ranking delta、exportが残りcluster削除 |
| cost/ops ledger | CloudWatch, Budgets, Cost Explorer, S3 | Athena | service/tag/day別のcost ledgerが残る |

## 6. 推奨予算配分

全体の安全消化目標は既存計画に合わせて、意図的な消化をUSD 18,300-18,700に抑え、USD 800-1,200をバッファとして残す。

| Bucket | Services | 推奨枠 | コメント |
|---|---|---:|---|
| Storage / source lake | S3, ECR | USD 900-1,600 | S3成果物は残す。ECRは小さく保つ。 |
| Batch compute | AWS Batch, EC2 Spot, Fargate Spot | USD 5,000-7,000 | 主消化枠。accepted artifact単価で停止判断。 |
| Catalog / analytics | Glue, Athena | USD 1,200-2,200 | QA/report用。scan制御が前提。 |
| OCR / extraction | Textract, EC2 Spot | USD 2,000-3,800 | TextractはP0 PDFに限定。 |
| AI candidate processing | Bedrock batch | USD 1,500-3,000 | public-only candidate。モデル/出力長固定。 |
| Retrieval benchmark | OpenSearch | USD 700-1,800 | time-boxed。削除忘れ禁止。 |
| Build / release evidence | CodeBuild, ECR, S3 | USD 600-1,200 | build/test/scan。bulk computeにはしない。 |
| Orchestration / control | Step Functions, Lambda, CloudWatch | USD 300-900 | 便利枠。ログ過多を防ぐ。 |
| Human dashboard | QuickSight | USD 0-200 | 原則0。必要なら短期pilotのみ。 |
| Reserved buffer | none | USD 800-1,200 | 意図して使わない。 |

## 7. Cost risk checklist

実行担当CLIが後続で使うべき事前確認。ここでは実行しない。

| Risk | 対象サービス | 必須対策 |
|---|---|---|
| hard cap誤認 | Budgets, Cost Explorer | Budgetはhard capではない。actual + manual stopを主にする |
| timeoutなし | Batch, Fargate, CodeBuild, Lambda | timeout、retry cap、max runtimeを必ず設定 |
| concurrency暴走 | Batch, Step Functions, Lambda | max vCPU、MaxConcurrency、reserved concurrency |
| log課金 | CloudWatch, CodeBuild, Lambda, Fargate | stdout要約、retention、debug sampleはS3へ |
| query scan課金 | Athena | Parquet/partition/workgroup bytes limit |
| 常駐課金 | OpenSearch, QuickSight, NAT, Fargate service | TTL、delete checklist、常駐化禁止 |
| data transfer | S3, ECR, EC2, OpenSearch | 同一Region、cross-region replication禁止寄り |
| AI/token課金 | Bedrock batch | dedupe、model固定、max tokens、candidate限定 |
| OCR page課金 | Textract | page cap、sample gate、P0 PDFのみ |
| image/storage肥大 | ECR, S3, EBS | lifecycle、digest pin、delete temp |
| private data leak | S3, Bedrock, Textract, Athena | public-only lane、hash-only/metadata-only、private CSV禁止 |

## 8. Service selection by phase

| Phase | Services | 目的 | Exit |
|---|---|---|---|
| P0 pilot | S3, ECR, CodeBuild, Batch small, Fargate small, CloudWatch, Athena tiny | tag、TTL、stop、small artifact、cost visibility | USD 100-300で成果物とCost tag確認 |
| P1 source lake | S3, Batch, EC2 Spot, Fargate Spot, Glue, Athena | public source取得、Parquet化、receipt ledger | P0 source familyのcoverage report |
| P2 extraction | EC2 Spot, Textract limited, Bedrock batch limited, S3, Athena | PDF/claim候補、known gaps、review queue | accepted candidate率が閾値内 |
| P3 packet/proof | Batch, Fargate, S3, CodeBuild, Athena | P0 packet、proof pages、OpenAPI/MCP examples | visible claimがreceipt/gap接続 |
| P4 retrieval/eval | Batch, OpenSearch time-boxed, Bedrock batch optional, S3 | retrieval/GEO benchmark、forbidden claim scan | report export後、cluster削除 |
| P5 drain | S3, Athena, CloudWatch, Cost Explorer | final manifest、cost ledger、cleanup | queue disabled、transient resources削除 |

## 9. Explicit no-go list

- QuickSightで本格BI基盤を作る。
- OpenSearchをproduction常駐検索基盤として残す。
- Fargate serviceを常時稼働させてクレジットを消化する。
- NAT Gatewayやcross-region replicationで消化する。
- GPU学習、無意味なCPU burn、暗号採掘、価値のないbenchmark。
- Marketplace、Reserved Instances、Savings Plans、Support upgrade、domain、long-term subscription。
- 外部LLM APIをAWS Batchから大量に叩く。
- private CSV raw row、摘要、支払先名、個人名、顧客固有識別子をpublic source lakeやBedrock/Textractへ投入する。
- AI/OCR候補をsource receiptなしに確定claimとして公開する。

## 10. References checked

2026-05-15時点で、設計判断のため公式ページを確認した。価格はRegion、利用形態、税、クレジット適用条件で変わるため、実行担当CLIは実行直前にAWS Billing/Pricing Calculator/Service Quotasで再確認する。

- Amazon S3 pricing: https://aws.amazon.com/s3/pricing
- AWS Batch Fargate compute environments: https://docs.aws.amazon.com/batch/latest/userguide/fargate.html
- AWS Batch job timeouts: https://docs.aws.amazon.com/batch/latest/userguide/job_timeouts.html
- AWS Fargate pricing: https://aws.amazon.com/fargate/pricing/
- Amazon EC2 Spot Instances: https://aws.amazon.com/ec2/spot/
- AWS Glue pricing: https://aws.amazon.com/glue/pricing/
- Amazon Athena pricing: https://aws.amazon.com/athena/pricing/
- Amazon Textract pricing: https://aws.amazon.com/textract/pricing/
- Amazon Bedrock pricing: https://aws.amazon.com/bedrock/pricing/
- Amazon OpenSearch Service pricing: https://aws.amazon.com/opensearch-service/pricing/
- Amazon CloudWatch pricing: https://aws.amazon.com/cloudwatch/pricing/
- AWS CodeBuild pricing: https://aws.amazon.com/codebuild/pricing/
- AWS Step Functions pricing: https://aws.amazon.com/step-functions/pricing/
- AWS Lambda pricing: https://aws.amazon.com/lambda/pricing/
- Amazon ECR pricing: https://aws.amazon.com/ecr/pricing/
- Amazon QuickSight pricing: https://aws.amazon.com/quicksight/pricing/

