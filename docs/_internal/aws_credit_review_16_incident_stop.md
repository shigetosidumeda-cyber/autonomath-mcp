# AWS credit review 16: incident response / kill switch

作成日: 2026-05-15  
担当: インシデント対応、kill switch、自走制御、証跡保存、zero-bill復旧  
対象AWS account: `993693061769`  
AWS CLI profile想定: `bookyou-recovery`  
workload region想定: `us-east-1`  
実行状態: 計画のみ。AWS CLI/APIは実行していない。

## 0. 結論

今回のAWSクレジット消化は、ローカルのCodex/Claude Codeセッションに依存させない。最初にAWS内部へ「作業キュー」「進行状態」「停止条件」「停止処理」を置き、以後はEventBridge、Step Functions、AWS Batch、Budget Actions、CloudWatch Alarm、Lambda kill switchで自走させる。

ただし、自走させるのは「価値ある成果物を作るジョブ」だけである。停止条件と隔離条件はAWS内部で常時有効にし、Codex/Claude Codeのrate limit、ローカル端末切断、オペレーター不在が起きても、次の動きになるよう設計する。

1. 新規投入を止める。
2. キューを止める。
3. running jobをdrainまたはcancelする。
4. 高額・常駐サービスを削除する。
5. 証跡と成果物manifestを安全にexportする。
6. AWS上の課金リソースを削除してzero-bill状態へ持っていく。

重要な前提:

- AWS Budgetsはhard capではない。
- Cost Explorer、Budgets、tag反映には遅延がある。
- したがって停止判定は、見えている請求額だけでなく、running/queued exposure、service cap exposure、untagged exposure、ログ膨張、NAT/Public IPv4、OpenSearch残置を加味する。
- `USD 19,493.94`を使い切ることを狙っても、意図的に`USD 19,300`を超えない。
- `USD 18,900`到達後は新規価値探索を止め、finish/export/cleanupだけに移る。

## 1. このレビューの守備範囲

この文書は、次の事故が起きたときの即時停止、隔離、復旧、証跡保存、zero-bill化を扱う。

- 想定外請求
- Cost Explorer/Budgets/tag反映遅延
- AWS Batch、Step Functions、EventBridge、Lambda、Glue、Athena等のジョブ暴走
- NAT Gateway、Public IPv4、cross-region/cross-AZ、data transfer drift
- OpenSearch domain/collectionの残置
- CloudWatch Logs、Athena scan、S3 request、ECR pull/storageの膨張
- private CSV、個人情報、secret、raw会計row混入
- robots/terms/source license違反疑い
- 成果物品質劣化、no-hit誤表現、source receipt不足、forbidden claim混入
- Codex/Claude Codeのrate limitまたはローカル端末停止

この文書は、`aws_credit_review_01_cost_stoplines.md`、`aws_credit_review_02_zero_bill_cleanup.md`、`aws_credit_review_06_network_transfer_risk.md`、`aws_credit_review_07_iam_budget_policy.md`、`aws_credit_review_09_queue_sizing_pacing.md`、`aws_credit_review_11_source_terms_robots.md`、`aws_credit_review_12_csv_privacy_pipeline.md`を補強する。

## 2. 基本方針

### 2.1 自走はAWS内部、判断材料はmanifest

ローカル端末は、初回bootstrap、進行確認、最終export、最終cleanup確認だけに使う。長時間の`while`ループ、ローカルcron、Codex/Claude Codeの継続プロンプト、手元プロセスは制御面に含めない。

AWS内部に置く制御面:

- EventBridge Scheduler: sentinelとorchestratorを定期起動する。
- Step Functions: run全体の状態遷移を管理する。
- AWS Batch: shard単位の取得・抽出・検証・生成を実行する。
- SQS: manifest shardの投入とbackpressureに使う。
- DynamoDB control table: run状態、kill level、service caps、incident locksを保持する。
- S3 manifest bucket: input manifest、artifact manifest、evidence manifest、export manifestを置く。
- CloudWatch Alarms: spend proxy、job failure、log bytes、queue age、service drift、heartbeat staleを検知する。
- SNS: alarm通知とkill switch Lambdaへのfan-outに使う。
- Lambda kill switch: キュー停止、EventBridge停止、Step Functions停止、Batch compute縮小、Deny policy適用、危険サービス削除を行う。
- Budget Actions: operator/batch roleへDeny policyを貼る補助ブレーキに使う。

### 2.2 速く使うが、burn目的のburnはしない

ユーザー要件は、1-2週間で約USD 19,500相当のクレジットをなるべく価値へ変えることである。したがって、初期は高並列にする。ただし、CPU burn、意味のないload test、常駐OpenSearch、NAT-heavy構成、ログ垂れ流し、大規模Athena無制限scanは価値を生まないので禁止する。

速く使う対象:

- 公式source snapshot
- PDF/OCRの候補抽出
- source profile生成
- source receipt候補生成
- claim graph dedupe/conflict
- no-hit ledger
- packet/proof fixture生成
- GEO agent discovery/eval
- CSV private overlayのsynthetic/header-only安全検証

速く使ってはいけない対象:

- private CSVのAWS投入
- raw会計rowの保存
- request-time LLM
- public proofに載せられないraw全文の再配布
- source termsが不明な大量取得
- NAT Gateway前提のprivate subnet構成
- OpenSearch常駐
- 監査できないログ膨張

## 3. Kill level

kill switchは段階式にする。いきなり全削除だけにすると、証跡を失う、cleanup不能になる、まだ価値ある成果物を破棄するリスクがある。一方で、課金事故やprivate data混入では即時隔離が必要になる。

| Level | 名称 | 目的 | 主な動作 | 復帰可否 |
| --- | --- | --- | --- | --- |
| K0 | Monitor | 通常監視 | metrics収集、manifest更新、heartbeat確認 | 通常 |
| K1 | Source pause | source単位停止 | 対象source familyの新規shard停止、rate down、incident lock | 可 |
| K2 | No new work | 新規投入停止 | EventBridge submitter停止、SQS ingest停止、Batch queue新規受付停止 | 条件付き可 |
| K3 | Compute throttle | 計算停止 | Batch compute max vCPUを0または最小へ、queued cancel、running drain/cancel | 条件付き可 |
| K4 | Emergency deny | 追加作成禁止 | Budget Action/IAM Deny適用、OpenSearch/NAT/Public IPv4等の即時削除候補化 | 原則不可 |
| K5 | Zero-bill teardown | 完全撤収 | export後、全課金リソース削除、AWSに継続費用を残さない | 不可 |

原則:

- cost系incidentはK2以上。
- unknown paid exposureが大きい場合はK3以上。
- private CSV、secret、個人情報混入疑いはK4以上。
- NAT Gateway、OpenSearch残置、Public IPv4未管理はK3以上、継続が見えたらK4。
- USD 19,300到達または到達可能性が高い場合はK5へ進む。

## 4. Run state machine

AWS内部のrun stateは、次の状態だけに限定する。

| State | 意味 | 許可される処理 |
| --- | --- | --- |
| `PRECHECK` | 実行前確認 | IAM/Budget/Tag/S3/ECR/Batch dry-run相当、small smoke |
| `RUNNING_STANDARD` | 標準実行 | J01-J16の高yield job |
| `RUNNING_STRETCH` | 伸長実行 | J17-J24のうち承認済みjobのみ |
| `WATCH` | USD 17,000相当 | low-yield停止、high-yield継続 |
| `SLOWDOWN` | USD 18,300相当 | OCR/OpenSearch/大join/Bedrock拡張停止 |
| `NO_NEW_WORK` | USD 18,900相当 | 新規投入停止、finish/export/checksumのみ |
| `INCIDENT_ISOLATED` | 事故隔離中 | 証跡保存、対象サービス停止、原因判定 |
| `DRAIN` | drain中 | running job終了待ちまたはcancel、artifact確定 |
| `EXPORT` | export中 | final artifact、manifest、evidenceの外部退避 |
| `TEARDOWN` | 削除中 | zero-bill cleanup |
| `COMPLETE_ZERO_BILL` | 完了 | AWS上にcredit run課金リソースなし |

禁止状態:

- `RUNNING_STANDARD`へ手動で戻すこと。
- `NO_NEW_WORK`以後にsource探索を新規開始すること。
- `INCIDENT_ISOLATED`から原因不明のまま`RUNNING_STRETCH`へ戻すこと。
- `TEARDOWN`中にIAM/Budget/cleanup roleを先に消すこと。

## 5. Control table

DynamoDB control tableは、Step Functions、Batch submitter、kill switch、sentinelが共有する唯一の実行状態にする。ローカル端末の状態は信用しない。

推奨テーブル名:

- `jpcite-credit-run-control-202605`

主キー:

- `run_id`

必須項目:

```json
{
  "run_id": "jpcite-aws-credit-2026-05",
  "account_id": "993693061769",
  "region": "us-east-1",
  "state": "RUNNING_STANDARD",
  "kill_level": "K0",
  "allow_new_work": true,
  "allow_stretch_work": false,
  "allow_managed_expensive_services": false,
  "max_control_spend_usd": 19300,
  "watch_line_usd": 17000,
  "slowdown_line_usd": 18300,
  "no_new_work_line_usd": 18900,
  "manual_stretch_min_usd": 19100,
  "manual_stretch_max_usd": 19300,
  "last_cost_observed_at": "2026-05-15T00:00:00Z",
  "last_sentinel_heartbeat_at": "2026-05-15T00:00:00Z",
  "cost_data_stale_minutes": 0,
  "estimated_running_exposure_usd": 0,
  "estimated_queued_exposure_usd": 0,
  "estimated_service_cap_exposure_usd": 0,
  "untagged_spend_observed_usd": 0,
  "paid_exposure_observed_usd": 0,
  "allowed_queues": [
    "jpcite-receipt-backbone-q",
    "jpcite-source-expand-q",
    "jpcite-pdf-ocr-q",
    "jpcite-product-artifact-q"
  ],
  "blocked_source_families": [],
  "incident_locks": [],
  "export_required": true,
  "zero_bill_required": true,
  "operator_note": "No request-time LLM. No private CSV in AWS."
}
```

各runnerは、job開始前にこのtableを読む。`allow_new_work=false`、`kill_level>=K2`、対象source familyが`blocked_source_families`に含まれる、対象serviceが`allow_managed_expensive_services=false`である場合、jobは開始せず終了する。

## 6. Cost sentinel

### 6.1 判定式

Cost Explorerは遅れる。したがって停止判定は次の保守的な値を使う。

```text
control_spend_usd =
  max(cost_explorer_actual_usd, budgets_actual_usd, operator_observed_usd)
  + estimated_running_exposure_usd
  + estimated_queued_exposure_usd
  + estimated_service_cap_exposure_usd
  + untagged_spend_penalty_usd
  + stale_cost_penalty_usd
```

`control_spend_usd`が停止線を超えたら、請求画面にまだ出ていなくても停止側へ倒す。

### 6.2 stale cost penalty

Cost dataが古いときは、遅延そのものをリスクとして扱う。

| 条件 | penalty | action |
| --- | --- | --- |
| Cost data stale 60分超 | running exposureを1.25倍 | K1候補 |
| Cost data stale 3時間超 | running + queued exposureを1.5倍 | K2 |
| Cost data stale 6時間超 | managed expensive service停止 | K3 |
| Cost data stale 12時間超 | 新規work禁止、export/drainへ | K3/K4 |

### 6.3 停止線

| control_spend_usd | State | Kill level | 動作 |
| --- | --- | --- | --- |
| 17,000 | `WATCH` | K1 | low-yield停止、queue cap縮小 |
| 18,300 | `SLOWDOWN` | K2 | OCR/OpenSearch/Bedrock/大join停止 |
| 18,900 | `NO_NEW_WORK` | K2/K3 | 新規投入停止、finish/export/checksumのみ |
| 19,100-19,300 | manual stretch area | K3 | 明示承認がない限りdrain/cleanup |
| 19,300 | `TEARDOWN` | K5 | emergency stop、zero-bill cleanup |

### 6.4 paid exposure条件

次のいずれかで停止する。

- credit適用外に見えるpaid exposureが`USD 1`以上: K1、原因特定。
- paid exposureが`USD 25`以上: K2、全新規投入停止。
- paid exposureが`USD 100`以上: K4、Emergency Deny、export/drain/cleanupへ。

## 7. Self-running architecture

### 7.1 ローカルに依存しない構成

初回bootstrap後、AWS側の制御は次のように動く。

1. EventBridge Schedulerが`jpcite-credit-sentinel`を15分ごとに起動する。
2. Sentinel LambdaまたはStep Functions taskがCost/Budget/Batch/S3/CloudWatch/OpenSearch/NAT/EIP/Log metricsを読む。
3. Sentinelがcontrol tableへ`control_spend_usd`、state、kill_level、incident_locksを更新する。
4. EventBridge Schedulerが`jpcite-credit-orchestrator`を5-15分ごとに起動する。
5. Orchestratorはcontrol tableを読んで、許可されたqueueへだけmanifest shardを投入する。
6. Batch jobは開始時と終了時にcontrol tableを読み、禁止状態ならself-abortする。
7. CloudWatch AlarmまたはBudget Actionが発火したらSNS経由でkill switch Lambdaを起動する。
8. kill switch Lambdaはcontrol tableをK2/K3/K4/K5へ更新し、EventBridge/Step Functions/Batch/managed servicesへ停止操作をかける。

Codex/Claude Codeがrate limitになっても、以上はAWS内部で続く。逆に、rate limit中に停止条件を超えた場合でも、AWS内部のkill switchが効く。

### 7.2 自走させるもの

- J01-J04の公式backbone取得
- J05/J07/J08/J09/J10/J11のsource expansion
- J06/J17のPDF/OCR候補抽出
- J12/J13のreceipt/claim graph QA
- J14のsynthetic/header-only CSV privacy fixture検証
- J15/J16/J20/J21/J23/J24のpacket/proof/GEO/export/checksum生成

### 7.3 自走させないもの

- AWSアカウント権限の拡大
- Budget/guardrail削除
- manual stretch承認
- private CSV投入
- request-time LLM有効化
- raw全文のpublic API化
- source terms不明な大量取得
- zero-bill cleanup後の再起動

## 8. Kill switch Lambda design

kill switch Lambdaは、次の順番で動くようにする。

1. control tableを`INCIDENT_ISOLATED`または`TEARDOWN`へ更新する。
2. `allow_new_work=false`にする。
3. EventBridge submitter/schedulerをdisableする。
4. Step Functionsの新規executionを止め、running executionへstop signalを入れる。
5. AWS Batch job queuesをdisabled相当にし、compute environmentのmax vCPUを0または最小にする。
6. queued jobをcancelする。
7. running jobはincident typeに応じてdrainまたはterminateする。
8. managed expensive servicesを停止または削除キューへ入れる。
9. IAM Deny policyをOperator/BatchExecution/BatchJob roleへ貼る。
10. evidence manifestを作成する。
11. zero-bill cleanup state machineを起動するか、手動確認待ちへ移す。

kill switch Lambdaが消してはいけないもの:

- cleanup role
- break-glass role
- control table
- evidence manifest保存先
- Budget/Cost確認に必要な読み取り権限

これらを先に消すと、復旧やzero-bill確認が不能になる。

## 9. Incident matrix

### 9.1 想定外請求

| 項目 | 内容 |
| --- | --- |
| Trigger | daily/hourly spendが予定より高い、paid exposure、untagged spend、service mix drift |
| Immediate level | K2。paid exposure USD 100以上ならK4 |
| Stop | 新規投入停止、low-yield queue停止、managed expensive service停止 |
| Isolate | service別cost、usage type、tag有無、resource inventoryを保存 |
| Evidence | cost snapshot、resource tags、queue depth、running job list、service cap ledger |
| Recovery | 原因serviceをblock listに入れ、高yield既知jobだけ再開候補 |
| Zero-bill | 原因serviceを削除、untagged resource全削除、final inventory |

特記事項:

- Cost Explorerが見えた時点では遅い可能性がある。
- `running_exposure + queued_exposure`が大きい場合は、請求画面に出る前に止める。
- untagged spendが出たら、tag条件に頼った集計が壊れているのでK2以上。

### 9.2 Cost Explorer / Budgets / tag反映遅延

| 項目 | 内容 |
| --- | --- |
| Trigger | cost data stale、tag反映なし、Budget発火遅れ、CEとBudgetの乖離 |
| Immediate level | K2。6時間以上staleならK3 |
| Stop | 新規work停止、queue cap縮小、expensive service停止 |
| Isolate | stale時刻、最後に信用できるcost、queued/running exposureを記録 |
| Evidence | sentinel heartbeat、cost API response metadata、fallback estimate |
| Recovery | costが復帰し、control spendが停止線未満、paid exposureなしなら限定再開 |
| Zero-bill | staleが長いまま18,900近傍ならcleanupへ進む |

### 9.3 ジョブ暴走

| 項目 | 内容 |
| --- | --- |
| Trigger | queue age増大、retry rate > 15%、failure rate > 10%、same input hash再投入、runtime超過 |
| Immediate level | K2。高額service連動ならK3 |
| Stop | 対象queue停止、重複job cancel、max vCPU縮小 |
| Isolate | shard id、input hash、container image digest、job definition revisionを固定 |
| Evidence | job attempts、stderr tail、artifact manifest、retry ledger |
| Recovery | shardをfailed quarantineへ移し、retry budgetを0-1へ制限 |
| Zero-bill | Batch/ECS/EC2/EBS/CloudWatch Logsの残骸を削除 |

禁止:

- retry unlimited
- source全量を同じmanifestで再投入
- failure原因不明のままparallelismを上げる

### 9.4 NAT / Public IPv4 / data transfer drift

| 項目 | 内容 |
| --- | --- |
| Trigger | NAT Gateway作成、EIP割当、Public IPv4増加、cross-region transfer、cross-AZ transfer |
| Immediate level | K3。NAT GatewayがrunningならK4候補 |
| Stop | network関連の新規作成Deny、対象route/service停止 |
| Isolate | VPC、route table、ENI、EIP、subnet、AZ、regionを棚卸し |
| Evidence | usage type、resource id、created time、tag、関連job |
| Recovery | NATなし構成へ戻す。必要ならpublic subnet + no inbound + least privilegeで短期job |
| Zero-bill | NAT Gateway、EIP、unused ENI、load balancer、VPC endpointを削除 |

原則:

- private subnetだから安全、という理由だけでNAT Gatewayを置かない。
- AWS credit runは単一region `us-east-1`に寄せる。
- ECR/S3/Athena/CloudWatch/OpenSearchをregion分散させない。

### 9.5 OpenSearch残置

| 項目 | 内容 |
| --- | --- |
| Trigger | domain/collectionがbenchmark終了後も残る、node hour継続、storage増加 |
| Immediate level | K3。NO_NEW_WORK以後ならK4 |
| Stop | 新規index作成停止、ingest停止、query benchmark停止 |
| Isolate | index config、query set、eval result、snapshot要否をmanifest化 |
| Evidence | exported mapping/settings、retrieval metrics、created/deleted timestamps |
| Recovery | benchmark結果をS3/localへexportし、OpenSearch自体は削除 |
| Zero-bill | domain/collection、snapshot bucket、security policy、log groupを削除 |

OpenSearchは本番検索基盤ではなく、一時的なretrieval benchmarkである。常駐させない。

### 9.6 CloudWatch Logs / Athena / S3 / ECR膨張

| 項目 | 内容 |
| --- | --- |
| Trigger | log bytes急増、Athena scan増大、S3 request急増、ECR image増殖 |
| Immediate level | K2。急増が止まらなければK3 |
| Stop | debug logging停止、Athena workgroup limit、duplicate query停止、old image cleanup |
| Isolate | log group、query id、bucket prefix、image digestを記録 |
| Evidence | sampled sanitized logs、query plan、scan bytes、object count、image list |
| Recovery | log levelをWARN/ERRORへ、Parquet/partitionだけ再実行 |
| Zero-bill | log groups、Athena results、temporary S3 prefix、ECR imagesを削除 |

禁止:

- raw HTML/PDF/CSV本文をCloudWatch Logsへ出す。
- request/response全量dumpを有効化する。
- Athenaでraw lake全体を無制限scanする。

### 9.7 private CSV / 個人情報 / secret混入

| 項目 | 内容 |
| --- | --- |
| Trigger | raw CSV row、摘要、個人名、口座情報、API key、secret、private upload prefix検出 |
| Immediate level | K4 |
| Stop | 全新規job停止、対象bucket/prefix/index/log group隔離、operator role書込停止 |
| Isolate | object key、hash、job id、container image digest、source code revisionを保存 |
| Evidence | raw値は保存しない。hash、byte range、detector id、redacted sampleのみ |
| Recovery | contaminated artifactsを全破棄。合成fixture/header-onlyから再生成 |
| Zero-bill | contaminated S3 objects/logs/indexを削除、削除manifestを保存 |

private CSVについての絶対ルール:

- raw CSVをAWSへ上げない。
- raw会計rowをS3、CloudWatch、OpenSearch、Bedrock、Textract、Athena resultsへ入れない。
- freee/Money Forward/弥生のfixtureはsynthetic/header-only/redactedだけにする。
- ユーザー由来の値をpublic proofやagent responseにechoしない。
- derived aggregateだけをpacketに入れる。

### 9.8 robots / terms / license違反疑い

| 項目 | 内容 |
| --- | --- |
| Trigger | robots deny、terms不明、rate limit違反、再配布禁止、source profile未承認 |
| Immediate level | K1。大量取得済みならK3 |
| Stop | source family pause、crawler停止、raw再配布停止 |
| Isolate | source_id、URL、terms snapshot、robots snapshot、取得時刻を保存 |
| Evidence | source profile version、allow/deny判断、rate policy、artifact keys |
| Recovery | green sourceだけ再開。yellow/redはmanual reviewまで止める |
| Zero-bill | 再利用不可rawを削除。derived factsもlicense_boundaryに従う |

public outputに出せるもの:

- source_receipt
- source URL
- retrieved_at
- short factual snippetまたは構造化fact
- license/terms boundary
- known_gaps

public outputに出してはいけないもの:

- terms不明なraw全文
- private CSV
- 有料DB由来の再配布禁止データ
- robots/termsに反する大量mirror

### 9.9 成果物品質劣化

| 項目 | 内容 |
| --- | --- |
| Trigger | source_receipt欠落、claim_refs不足、known_gapsなし、no-hit誤表現、forbidden claim、confidence低下 |
| Immediate level | K1/K2 |
| Stop | 対象packet family停止、proof generation停止、public import禁止 |
| Isolate | failing packet examples、schema version、validator report、source ids |
| Evidence | validation report、diff、expected/actual、gating failure |
| Recovery | composer修正、fixture再生成、validator再実行 |
| Zero-bill | 品質不合格artifactはAWSからexportしないか、quarantineとして明示 |

品質事故は請求事故ではないが、jpciteの価値を壊す。特に次は公開不可。

- no-hitを「不存在証明」「安全証明」と表現する。
- source receiptなしに断定する。
- request-time LLM生成文をsource-backed packetのように見せる。
- CSV由来のprivate detailを成果物に混ぜる。
- `human_review_required`を必要なケースで落とす。

## 10. Evidence preservation

### 10.1 保存する証跡

証跡は、後で原因を説明できる最小量にする。private raw値は保存しない。

保存する:

- run_id
- incident_id
- timestamp
- account_id
- region
- state before/after
- kill_level before/after
- trigger metric
- affected service
- resource ids
- job ids
- image digest
- source code revision
- manifest version
- input hash
- artifact hash
- redacted detector result
- cost snapshot
- resource inventory snapshot
- cleanup action manifest

保存しない:

- raw private CSV
- raw会計row
- API key
- secret
- 個人情報本文
- terms不明raw全文
- CloudWatch log全文dump

### 10.2 Evidence manifest schema

```json
{
  "incident_id": "inc-20260515-001",
  "run_id": "jpcite-aws-credit-2026-05",
  "detected_at": "2026-05-15T00:00:00Z",
  "account_id": "993693061769",
  "region": "us-east-1",
  "trigger": {
    "type": "cost_spike|private_data_leak|network_drift|quality_gate|terms_violation|job_runaway",
    "metric": "control_spend_usd",
    "observed_value": 18950,
    "threshold": 18900
  },
  "state_transition": {
    "from": "RUNNING_STANDARD",
    "to": "NO_NEW_WORK",
    "kill_level": "K2"
  },
  "affected_resources": [
    {
      "service": "batch",
      "resource_id": "job/...",
      "tag_run_id": "jpcite-aws-credit-2026-05",
      "action": "cancel_queued"
    }
  ],
  "evidence_objects": [
    {
      "kind": "sanitized_log_sample|cost_snapshot|resource_inventory|artifact_manifest",
      "uri": "s3://.../evidence/...",
      "sha256": "..."
    }
  ],
  "private_data_status": "not_detected|suspected|confirmed_redacted",
  "zero_bill_required": true,
  "operator_review_required": true
}
```

## 11. Isolation zones

Incident発生時、成果物を3区分に分ける。

| Zone | 意味 | 扱い |
| --- | --- | --- |
| `accepted` | 品質・権利・privacy・receiptを通過 | export候補 |
| `quarantine` | 原因調査用に隔離 | public import禁止、redacted evidenceのみ |
| `delete_required` | private/secret/terms違反など | export禁止、削除manifest作成後に削除 |

S3 prefix例:

```text
s3://jpcite-credit-run-202605/artifacts/accepted/
s3://jpcite-credit-run-202605/artifacts/quarantine/
s3://jpcite-credit-run-202605/artifacts/delete_required/
s3://jpcite-credit-run-202605/evidence/redacted/
s3://jpcite-credit-run-202605/manifests/
```

ただし、zero-bill完了時にはS3 bucketも削除する。最終成果物とredacted evidenceはAWS外へexportしてから削除する。

## 12. Recovery rules

復帰は、事故typeによって制限する。

| Incident | 復帰可否 | 条件 |
| --- | --- | --- |
| Cost spike | 条件付き可 | 原因service特定、paid exposureなし、control spend停止線未満 |
| Cost stale | 条件付き可 | cost data復帰、running/queued exposure再計算済み |
| Job runaway | 条件付き可 | duplicate防止、retry budget制限、対象manifest修正済み |
| NAT/Public IPv4 | 原則不可 | 削除確認後、NATなし構成だけ可 |
| OpenSearch残置 | 原則不可 | export後削除。再作成は明示benchmarkだけ |
| Log/Athena膨張 | 条件付き可 | log level/workgroup cap/partition修正済み |
| Private CSV/secret | 不可 | contaminated artifact破棄後、synthetic-onlyから再開 |
| Terms/robots違反 | manual reviewまで不可 | source profile更新、license_boundary確認済み |
| Quality degradation | 条件付き可 | validator修正、fixture再生成、gate再通過 |

復帰時も、停止線は戻さない。例えば`NO_NEW_WORK`到達後に事故が解決しても、`RUNNING_STANDARD`へは戻さない。

## 13. Zero-bill teardown trigger

次のいずれかでzero-bill teardownへ進む。

- `control_spend_usd >= 19,300`
- paid exposureが`USD 100`以上
- private CSV/secret混入がconfirmed
- Cost data stale 12時間超かつ18,900近傍
- NAT/OpenSearch等の常駐課金が止まらない
- AWS上で新規workを安全に止められない
- ユーザーが「これ以上請求が走らない状態」を指示した最終段階

teardown順:

1. EventBridge/Scheduler/CI/trigger停止
2. Step Functions新規停止、running停止
3. Batch queue停止、queued cancel、compute max vCPU 0
4. ECS/Fargate/EC2/Auto Scaling停止
5. OpenSearch/NAT/ELB/EIP/unused ENI削除
6. Glue/Athena/Lambda/CloudWatch Logs/EventBridge/SQS削除
7. ECR images削除
8. S3 accepted/evidenceをAWS外へexport
9. checksum照合
10. S3 bucket/object削除
11. IAM/Budget/Cost monitorを必要最小限に整理
12. final resource inventory
13. `COMPLETE_ZERO_BILL`

BudgetやCost Anomaly monitorは課金リソースではないが、ユーザー要件が「AWSをこれ以上使わない」なら、最終確認後に削除してよい。削除前にfinal reportを残す。

## 14. Production deployment readiness

本番デプロイを早めるため、AWS credit runは「本番環境を直接いじる」のではなく、本番デプロイに必要な材料を短期で作る。

AWS runが作るもの:

- source registry candidates
- source receipt backbone
- claim_refs examples
- known_gaps examples
- no-hit ledger
- packet fixtures
- MCP/API response examples
- pricing/cost preview fixture
- CSV privacy fixture matrix
- GEO proof pages
- public discovery pages候補
- OpenAPI/MCP/llms/.well-known candidate artifacts
- quality gate reports
- forbidden-claim reports
- cleanup/final checksum reports

本番デプロイ前gate:

| Gate | 条件 |
| --- | --- |
| Contract | packet schema、source_receipts、claim_refs、known_gaps、billing_metadataが固定 |
| Privacy | private CSV/raw valuesがartifact/log/indexに0 |
| Rights | source profileがgreen/yellowで、redはpublic importなし |
| Quality | no-hit forbidden wording 0、source receipt missing 0、human_review_required漏れ0 |
| Cost | request-time LLMなし、MCP/API課金metadataあり |
| GEO | agent-facing proof pages、llms/.well-known、OpenAPI/MCP examplesが整合 |
| Deploy | exported artifactをrepoへimportでき、AWS依存なしでlocal/build/testが通る |

AWS credit run中に本番deployを急ぐ場合でも、次はしない。

- AWS temporary bucketを本番APIから直接読む。
- OpenSearch temporary benchmarkを本番検索として流用する。
- quality gate未通過artifactをpublic proofへ出す。
- cleanup前提resourceを本番dependencyにする。

## 15. Operator playbook

### 15.1 通常時

1. sentinel heartbeatが更新されている。
2. control table stateが妥当である。
3. `control_spend_usd`が停止線未満である。
4. queue depthとrunning exposureが見積内である。
5. accepted artifact yieldが悪くない。
6. private leak scanが0である。
7. source terms incidentがない。
8. high-risk serviceが予定どおり短期利用に留まっている。

### 15.2 Rate limit時

Codex/Claude Codeが止まったら、人間は焦って新しいローカルループを作らない。AWS内部は次の状態であるべき。

- EventBridge sentinelが回っている。
- Step Functions orchestratorがcontrol tableを読んでいる。
- Batch jobが開始前にself-abort条件を見ている。
- Budget ActionsがDeny policyを貼れる。
- kill switch LambdaがEventBridge/SNSから起動できる。
- `NO_NEW_WORK`以後に自動でexport/drain/cleanupへ進める。

Rate limit中に確認できない場合でも、AWS側は`cost_data_stale`と`sentinel_heartbeat`で自動的に保守側へ倒れる。

### 15.3 手動介入が必要なとき

手動介入が必要なのは次だけに限定する。

- manual stretch承認
- source terms判断
- private data incidentの法務/安全判断
- final export先の確認
- zero-bill完了確認
- 本番deploy取り込み判断

## 16. Go / No-Go

### Go

- control table、sentinel、orchestrator、kill switch、Budget Actions、cleanup roleが揃っている。
- EventBridge/SNS/Lambda経路でkill switchが起動できる設計になっている。
- Batch jobがcontrol tableを読み、self-abortできる。
- `USD 17,000 / 18,300 / 18,900 / 19,300`の状態遷移が固定されている。
- NAT Gateway、OpenSearch、CloudWatch Logs、Athena scan、S3 storageに個別capがある。
- private CSVはAWS投入不可である。
- zero-bill teardownでS3まで削除する前提が明記されている。

### No-Go

- ローカルCodex/Claude Codeの継続実行が停止条件になっている。
- Budgetsだけをhard cap扱いしている。
- Cost Explorerの遅延を考慮していない。
- kill switchがcleanup roleまで消してしまう。
- NAT GatewayやOpenSearchが常駐する。
- raw private CSV、個人情報、secretがS3/log/index/promptに入る余地がある。
- `NO_NEW_WORK`以後に新規source探索が可能なまま。
- final artifactsがAWS temporary bucketに依存している。

## 17. 本体計画へのマージ位置

本体の実行順に、このincident/kill switchを次の位置で差し込む。

1. P0 contract freeze
2. AWS account/profile/region確認
3. IAM/Budget/permission boundary作成
4. **incident control plane作成**
5. **kill switch dry-run設計確認**
6. S3/ECR/Batch/SQS/Step Functions/EventBridgeの骨格
7. Smoke run
8. J01-J04 backbone
9. J05/J07/J08/J09/J10/J11 expansion
10. J06/J17 PDF/OCR conditional
11. J14 CSV synthetic/privacy
12. J12/J13 receipt/claim QA
13. J15/J16 packet/GEO
14. J20/J21/J23/J24 stretch/export
15. **No-new-work/drain/export**
16. **zero-bill teardown**
17. repo import
18. production deploy gate

この順番にしないと、ジョブが走った後に停止装置を後付けする形になる。今回の規模ではそれは許容しない。

## 18. 最終判定

このincident/kill switch設計を入れれば、次の要求を同時に満たせる。

- AWSクレジットを短期間で価値ある成果物へ変える。
- Codex/Claude Codeがrate limitになってもAWS側は自走する。
- ただし停止条件はAWS内部で効く。
- Cost Explorer遅延やBudget非hard-capを前提に保守側へ倒す。
- private CSV、robots/terms、品質劣化を請求事故と同じ強さで止める。
- 最後はAWS上に課金リソースを残さない。

このレビューでの最重要追加点は、`kill switch`を「人間が手で押すボタン」ではなく、「AWS内部の状態機械、Budget Action、CloudWatch Alarm、Lambda、Batch self-abortの組み合わせ」として設計することである。これにより、ローカルAIエージェントが一時的に止まっても、AWS側は成果物生成を継続し、停止線に近づけば自動的にdrainとzero-bill cleanupへ進められる。
