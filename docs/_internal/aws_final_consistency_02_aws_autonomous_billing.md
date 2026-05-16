# AWS final consistency check 02/10: autonomous AWS run, billing stoplines, and zero-bill cleanup

作成日: 2026-05-15  
担当: 最終矛盾チェック 2/10 / AWS請求・停止・自走  
対象AWS profile: `bookyou-recovery`  
対象AWS account: `993693061769`  
対象region: `us-east-1`  
実行状態: 計画精査のみ。AWS CLI/APIコマンド、AWSリソース作成、ジョブ投入、削除は行っていない。  
出力制約: この1ファイルのみを作成する。

## 0. 結論

現行計画は、方向性としては成立する。ただし、次の3点を本体計画へ明示的にマージしないと、実行時に矛盾が出る。

1. 「USD 19,493.94をちょうど使い切る」と「現金請求を絶対に出さない」は同時に厳密達成できない。  
   修正後の正しい表現は、**意図的な新規投入上限をUSD 19,300に置き、遅延請求・非クレジット対象・削除遅延のために約USD 193.94を安全余白として残す**、である。これは実務上の「ほぼ全額消化」であり、現金請求回避を上位制約にする。

2. 「Codex/Claudeが止まってもAWSが走り続ける」と「stoplineで必ず止まる」は、AWS内部に制御面を置けば両立する。  
   必須構成は、EventBridge Scheduler、Step Functions Standard、AWS Batch、SQS、DynamoDB control table、CloudWatch alarms、Budgets Actions、kill switch Lambda、明示Deny policyである。ローカル端末やチャットエージェントをheartbeatにしてはいけない。

3. 「AWS終了後zero-bill」と「成果物を必ず保持する」は、外部退避先がなければ最後に衝突する。  
   厳密なzero-billではS3も削除する必要がある。したがって、full run前に**AWS外へのexport確認ゲート**を追加する。外部退避が未確認なら、AWSは新規workを止めるが、zero-bill cleanupまで自動完了できない。ここは計画上の最大の未解決点だったため、本レビューで必須ゲートに昇格する。

この修正を入れれば、1週間以内にUSD 18,900からUSD 19,300相当まで高速に成果物化し、同時に現金請求リスクを抑え、本番デプロイもAWS全量完了を待たずに進められる。

## 1. 精査対象

主に以下の既存計画を前提に精査した。

- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_01_cost_stoplines.md`
- `aws_credit_review_02_zero_bill_cleanup.md`
- `aws_credit_review_07_iam_budget_policy.md`
- `aws_credit_review_09_queue_sizing_pacing.md`
- `aws_credit_review_10_terminal_command_stages.md`
- `aws_credit_review_16_incident_stop.md`
- `aws_credit_review_17_daily_operator_schedule.md`
- `aws_scope_expansion_25_fast_spend_scheduler.md`
- `aws_scope_expansion_28_production_release_train.md`
- `aws_scope_expansion_29_post_aws_assetization.md`
- `aws_scope_expansion_30_synthesis.md`

公式仕様として、AWS Budgets Actions、AWS Batch、Step Functions、EventBridge Scheduler、Cost Explorer `GetCostAndUsage`、CloudWatchの公開ドキュメントを確認した。参照URLは末尾に列挙する。

## 2. 矛盾チェック結果

### C-01: 「ちょうど使い切る」と「現金請求絶対回避」

判定: 矛盾あり。ただし運用定義を変えれば解消可能。

問題:

- Cost Explorer、Budgets、タグ反映は遅れる。
- AWS creditsは、契約・プロモーション・サービス・税・サポート・Marketplace・コミットメント等の条件により、全費用へ同じように適用されるとは限らない。
- そのため、AWS画面上でUSD 19,493.94ぴったりを狙う設計は、現金請求を出す可能性がある。

修正:

- ユーザー向け計画上の表現を、以下に統一する。

```text
Credit face value: USD 19,493.94
Useful intentional usage target: USD 18,900-19,300
Absolute intentional launch cap: USD 19,300
Safety reserve: at least USD 193.94
Cash billing avoidance: higher priority than exact credit exhaustion
```

「ちょうど使い切る」は、請求画面の最終数字を合わせる意味ではなく、**安全線まで価値ある成果物に変換し、残りは遅延・非対象・cleanup余白として消える可能性を織り込む**という意味に変える。

### C-02: 「AWS自走」と「stopline停止」

判定: 両立可能。ただし、ローカルCLIループでは不可。

問題:

- Codex/Claude/ローカル端末が制御面だと、rate limitや端末切断で停止・減速・cleanupが効かない。
- 一方で、AWSを完全自走にすると、止める人間が不在でも費用が増え続ける危険がある。

修正:

- 自走はAWS内部で行う。
- ただし、各runnerは必ずDynamoDB control tableを読み、`allow_new_work=false`、`kill_level>=K2`、`state=NO_NEW_WORK|DRAIN|EXPORT|TEARDOWN` の場合は自己停止する。
- EventBridge Schedulerは起動係、Step Functions Standardは状態遷移係、AWS Batchはworker係、Budget Actions/IAM Deny/kill switch Lambdaはブレーキ係に分ける。

### C-03: Budgetsをhard capのように扱う危険

判定: 既存計画は「hard capではない」と書けているが、実行手順ではさらに明確化が必要。

問題:

- Budgets Actionsは閾値超過時にIAM policy/SCP適用や一部リソース操作を行えるが、すべてのAWS費用をリアルタイムに止めるhard capではない。
- すでに走っているBatch job、OpenSearch、NAT Gateway、CloudWatch Logs、Athena scan等の追加費用は、Deny policyだけでは即時ゼロにならない。

修正:

- Budget Actionは補助ブレーキと定義する。
- 実ブレーキは次の順序に固定する。

```text
1. EventBridge submitter停止
2. Step Functions新規分岐停止
3. SQS shard投入停止
4. Batch queue disable
5. queued job cancel
6. running job terminate or bounded drain
7. compute environment max vCPU = 0
8. OpenSearch / NAT / EIP / unmanaged EC2 / Glue / Athena / Logs の停止・削除
9. export/checksum
10. zero-bill cleanup
```

### C-04: zero-bill cleanupと成果物保持

判定: 最大の実行前修正点。

問題:

- zero-billを厳密に要求する場合、S3 bucket、CloudWatch Logs、ECR、Glue/Athena、OpenSearch等も削除対象になる。
- しかし、Codex/ClaudeやローカルCLIが止まっている間にAWSが成果物を作り続けた場合、最終成果物は一時的にS3にしか存在しない可能性がある。
- S3を残すとzero-billではない。S3を消すと未退避成果物を失う。

修正:

full run前に次のゲートを追加する。

```text
G2.5 External Export Gate

GO条件:
- AWS外の成果物退避先が決まっている。
- export_manifest と checksum_manifest の保存先がAWS外にある。
- exportが2-4時間ごとに小分けで走る。
- 最終cleanup時、exported_artifact_count と checksumが一致する。

NO-GO:
- S3に置けばよい、という状態。
- ローカル端末が戻るまで成果物がAWSにしかない状態。
- export確認なしでS3削除する状態。
```

選択肢は3つある。

| Option | 成果物保持 | zero-bill | 推奨 |
|---|---:|---:|---|
| A. 外部退避確認後にS3削除 | 可能 | 可能 | 採用 |
| B. S3 final bucketを残す | 可能 | 不可 | ユーザー要件に反する |
| C. 未退避でもS3削除 | 不可 | 可能 | 価値を失うため不可 |

したがって、採用はAのみ。**full-speed AWS runは、外部退避経路を確定してから開始する。**

### C-05: 1週間以内消化と品質gate

判定: 両立可能。ただし、すべてのsourceを同じ速度で走らせてはいけない。

問題:

- 早く消化するために広域Playwright/OCR/Bedrock/OpenSearchを同時に開けると、robots/terms、失敗retry、ログ膨張、非成果物コストが増える。
- 反対に慎重すぎると、1週間以内にクレジットが消化できない。

修正:

- Day 0-1でguardrail/canaryを終え、Day 1-4でBand A/Bを高速化し、Day 4-6でBand C/D/Eへ広げる。
- ただし、source_profile gateを通ったsourceだけを大量処理する。
- accepted artifact yieldが落ちたjobは、費用が残っていても止める。

目安:

| Window | 目標累計 | 方針 |
|---|---:|---|
| Day 0 | USD 0-300 | guardrail, stop drill, canary |
| Day 1-2 | USD 3,000-8,000 | J01-J16 backboneを高速化 |
| Day 3-4 | USD 10,000-15,500 | revenue-first source, packet/proof, QA |
| Day 5 | USD 17,000前後 | low-yield停止、high-yieldだけ継続 |
| Day 6 | USD 18,300-18,900 | slowdown, final artifact重視 |
| Day 6-7 | USD 18,900-19,300 | 事前承認済みstretchのみ、export/checksum/cleanupへ |

この速度なら、公式source側のアクセス制限やterms stopが多発しない限り、1週間以内に「ほぼ全額の価値化」は可能。ただし、現金請求絶対回避のため、USD 19,300超えは狙わない。

### C-06: region不整合

判定: 既存計画の一部に `ap-northeast-1` 例があり、ユーザー指定と矛盾する。

修正:

- 今回の最終計画では、profile/account/regionを次に固定する。

```text
AWS profile: bookyou-recovery
AWS account: 993693061769
Workload region: us-east-1
Billing/control region: us-east-1
```

- 日本の公的一次情報を扱うことと、AWS workload regionは別問題として扱う。
- 別regionが必要なBedrock/Textract等は、明示承認されたsub-runとして扱い、デフォルトでは使わない。

## 3. 最終自走アーキテクチャ

### 3.1 構成

| Component | 役割 | 止め方 |
|---|---|---|
| EventBridge Scheduler | sentinel/orchestrator/cleanup tickを定期起動 | schedule disable/delete |
| Step Functions Standard | run全体の状態遷移、auditable workflow | execution stop、stateをDRAIN/TEARDOWNへ |
| SQS | shard queue、backpressure | send停止、queue purgeはexport後 |
| AWS Batch | public source処理、Playwright/OCR feeder、proof生成 | queue disable、job cancel/terminate、CE cap 0 |
| DynamoDB control table | run state, kill level, spend cap, queue cap, incident lock | cleanup前まで残す |
| Lambda sentinel | cost/telemetry/resource drift監視 | kill policy適用対象外にする |
| Lambda kill switch | K2-K5の停止操作 | cleanup roleで実行 |
| CloudWatch Alarms | queue age, failure, log bytes, spend proxy, heartbeat | alarm actionでkill switch |
| Budgets Actions | DenyNewWork/EmergencyDenyCreates適用 | cleanup権限は残す |
| S3 | 一時artifact, manifest, export staging | 外部export後にbucket削除 |

Step FunctionsはStandardを採用する。長時間・監査可能なworkflowに向いており、BatchやGlue等との統合も使えるためである。Expressは高頻度短時間には向くが、今回の「数日間の状態管理」にはStandardのほうが自然。

### 3.2 Control table

最低限の状態を次のように固定する。

```json
{
  "run_id": "jpcite-aws-credit-2026-05",
  "account_id": "993693061769",
  "region": "us-east-1",
  "state": "RUNNING_STANDARD",
  "kill_level": "K0",
  "allow_new_work": true,
  "allow_stretch_work": false,
  "preapproved_manual_stretch": false,
  "zero_bill_required": true,
  "external_export_gate_passed": false,
  "max_control_spend_usd": 19300,
  "watch_line_usd": 17000,
  "slowdown_line_usd": 18300,
  "no_new_work_line_usd": 18900,
  "manual_stretch_min_usd": 18900,
  "manual_stretch_max_usd": 19300,
  "paid_exposure_observed_usd": 0,
  "untagged_spend_observed_usd": 0,
  "estimated_running_exposure_usd": 0,
  "estimated_queued_exposure_usd": 0,
  "estimated_service_cap_exposure_usd": 0,
  "last_cost_observed_at": "2026-05-15T00:00:00Z",
  "cost_data_stale_minutes": 0
}
```

重要:

- `external_export_gate_passed=false` のまま、full runへ行かない。
- `preapproved_manual_stretch=false` のまま、USD 18,900以降の新規workをしない。
- `zero_bill_required=true` の場合、最終状態はS3削除まで含む。

### 3.3 Run states

| State | 許可 | 禁止 |
|---|---|---|
| `PRECHECK` | read-only確認、guardrail準備、dummy stop drill | 大量取得、OCR、OpenSearch |
| `CANARY` | USD 100-300の小片 | 並列拡大 |
| `RUNNING_STANDARD` | J01-J16、J25-J40のうちsource_profile gate済み | 未審査source大量処理 |
| `WATCH` | high-yield継続、low-yield停止 | 低価値backfill |
| `SLOWDOWN` | packet/proof/QA/export準備 | 新規OCR拡張、OpenSearch、広いAthena |
| `NO_NEW_WORK` | finish, export, checksum, cleanup準備 | 新規job投入 |
| `RUNNING_STRETCH` | 事前承認済み小型stretchのみ | 探索的処理 |
| `DRAIN` | queued cancel、running bounded drain | 新規work |
| `EXPORT` | 外部退避、checksum照合 | 新規work |
| `TEARDOWN` | zero-bill cleanup | 追加成果物生成 |
| `COMPLETE_ZERO_BILL` | 翌日/3日後/月末確認 | 有料リソース残置 |

## 4. 請求制御の数学

停止判定は、請求画面の数字だけで行わない。

```text
control_spend_usd =
  max(
    cost_explorer_unblended_actual_usd,
    budget_gross_actual_usd,
    internal_operator_ledger_usd
  )
  + estimated_running_exposure_usd
  + estimated_queued_exposure_usd
  + estimated_service_cap_exposure_usd
  + stale_cost_penalty_usd
  + untagged_spend_penalty_usd
  + cleanup_reserve_usd
```

推奨値:

| 項目 | 初期値 |
|---|---:|
| `cleanup_reserve_usd` | 50-100 |
| Cost data stale 60分超 | running exposure x 1.25 |
| Cost data stale 3時間超 | running + queued exposure x 1.5 |
| Cost data stale 6時間超 | managed expensive service停止 |
| Cost data stale 12時間超 | no-new-work固定 |

paid exposureは別判定にする。

| Paid exposure | 動作 |
|---:|---|
| USD 1以上 | scale-up禁止、原因特定 |
| USD 25以上 | no-new-work |
| USD 100以上 | emergency deny、drain/export/cleanup |

untagged spendも停止条件にする。

| Untagged spend | 動作 |
|---:|---|
| USD 1以上 | inventory照合 |
| USD 25以上 | 該当serviceの新規work停止 |
| 説明不能30分 | account-wide no-new-work |

## 5. Stopline別の自動動作

| Line | `control_spend_usd` | 自動state | kill level | 動作 |
|---|---:|---|---|---|
| Watch | 17,000 | `WATCH` | K1 | low-yield停止、queue cap縮小、成果物単価確認 |
| Slowdown | 18,300 | `SLOWDOWN` | K2 | OCR/OpenSearch/Bedrock/大join停止、proof/QA/export優先 |
| No-new-work | 18,900 | `NO_NEW_WORK` | K2/K3 | 新規job投入停止、queued cancel、bounded drain |
| Stretch | 18,900-19,300 | `RUNNING_STRETCH` or `DRAIN` | K3 | 事前承認がありtelemetry cleanなら小型stretch、それ以外はdrain |
| Safety | 19,300 | `TEARDOWN` | K5 | emergency stop、export済みartifact確認、zero-bill cleanup |

### 5.1 事前承認型stretch

Codex/Claudeが止まってもUSD 18,900以降へ進めたいなら、run開始前に事前承認トークンをcontrol tableへ入れる。

条件:

- `preapproved_manual_stretch=true`
- `external_export_gate_passed=true`
- paid exposure = 0
- untagged spend = 0 または説明済み
- Cost data stale < 60分
- running + queued + service cap exposureを足してもUSD 19,300未満
- stretch jobが2時間以内に止められる
- accepted artifact yieldが直近2時間で増えている

この条件を1つでも外したら、USD 18,900以降は自動的に`DRAIN`へ進む。

## 6. Queue設計の最終修正

### 6.1 Queue分類

| Queue | 目的 | stopline時の扱い |
|---|---|---|
| `jpcite-control-q` | sentinel補助、manifest、checksum、cleanup | 最後まで残す。ただし低cap |
| `jpcite-receipt-backbone-q` | J01-J04, identity/law/backbone | 18,300で新規shard停止 |
| `jpcite-source-expand-q` | 補助金、調達、行政処分、業法、統計 | 17,000以降low-yield停止 |
| `jpcite-render-ocr-q` | Playwright、1600px screenshot、OCR/Textract feeder | 18,300で原則停止 |
| `jpcite-qa-graph-q` | completeness, conflict, no-hit, forbidden claim | 18,900以降もfinal QAだけ許可 |
| `jpcite-product-artifact-q` | packet/proof/GEO/OpenAPI/MCP素材 | 18,900以降はfinal/export限定 |
| `jpcite-stretch-q` | Bedrock/OpenSearch/追加OCR/広域eval | default disabled。事前承認時のみ |

### 6.2 各jobの必須メタデータ

AWSへ投入する全jobは、job registryに次を持つ。

```json
{
  "job_id": "Jxx",
  "source_family": "official-public-source",
  "data_class": "public-only",
  "max_spend_usd": 100,
  "max_runtime_minutes": 120,
  "max_items": 10000,
  "max_retries": 2,
  "queue": "jpcite-source-expand-q",
  "accepted_artifact_definition": [
    "source_receipts.jsonl",
    "claim_refs.jsonl",
    "known_gaps.jsonl",
    "artifact_manifest.json"
  ],
  "start_allowed_states": ["RUNNING_STANDARD", "WATCH"],
  "stop_on_paid_exposure": true,
  "stop_on_no_hit_misuse": true,
  "stop_on_private_data": true
}
```

jobがこのメタデータを持たない場合、orchestratorは投入しない。

## 7. 1週間以内消化の修正版

「最速で使う」は、最初から最大並列にする意味ではない。最速で本番価値に変える順番にする。

### Day 0: guardrail and canary

- account/profile/region確認。
- credit balance/expiry/eligible services確認。
- Budget Actions、Deny policy、permission boundary、required tags、log retention、stop drillを準備。
- 外部export gateを通す。
- USD 100-300のcanaryだけ実行可能にする。

### Day 1-2: standard run acceleration

- J01-J04、J12/J13/J15/J16を優先。
- 会社同定、インボイス、法令、source receipt、known gaps、no-hit ledger、proof fixtureを最初に作る。
- 本体はRC1 productionに必要な3 packet、proof page、minimal MCP/APIへ進む。

### Day 3-4: revenue-first expansion

- 補助金、調達、業法、行政処分、gBizINFO、e-Stat、EDINET、官報/告示/パブコメ、自治体sourceを広げる。
- Playwright/1600px screenshotはsource_profile gate済みsourceだけ。
- accepted artifact per USDを見て、Band B/C/Dを自動配分する。

### Day 5: watch and slowdown preparation

- USD 17,000前後でlow-yieldを止める。
- USD 18,300到達前にOpenSearch、広域OCR、広いAthena scanを閉じる準備。
- 本番側はRC2 import候補を小さく切る。

### Day 6: no-new-work approach

- USD 18,300-18,900は、成果物化、QA、GEO eval、proof generation、exportを優先。
- 新しいsource探索はしない。
- 事前承認済みstretchがなければ、USD 18,900でdrainへ移る。

### Day 6-7: final stretch, export, teardown

- 条件が揃う場合のみ、USD 18,900-19,300の短命stretchを許可。
- `control_spend_usd >= 19,300` でK5。
- export/checksum確認後、zero-bill cleanup。
- 翌日、3日後、月末後にCost Explorer/Billingで新規日次費用が増えていないか確認。

## 8. 本番デプロイ計画とのマージ順

AWS runと本体productionは、次の順番で統合する。

```text
0. P0 contract freeze
1. AWS guardrail + autonomous controls
2. External export gate
3. AWS canary
4. RC1 static proof + minimal API/MCP staging
5. RC1 production
6. AWS standard run self-running
7. RC2/RC3 small bundle import
8. AWS slowdown/no-new-work
9. final export/checksum
10. zero-bill teardown
11. post-teardown billing checks
```

重要:

- productionはAWS S3/Batch/OpenSearch/Glue/Athenaをruntime dependencyにしない。
- AWS全量完了をproductionの前提にしない。
- AWS成果物は、validated bundleとしてrepo/static/dbへ取り込んでから公開する。
- AWSが自走している間も、本体側はRC1/RC2を進める。
- `runtime.aws_dependency.allowed=false` をproduction hard gateにする。

## 9. IAM/Budget Actionの修正

### 9.1 Deny policyはcleanupを壊してはいけない

`DenyNewWork` と `EmergencyDenyCreates` は、次をDenyする。

- new Batch submit
- new ECS task/service
- new EC2 instance/ASG
- new Glue/Athena/Step Functions execution
- new Textract/Bedrock/OpenSearch
- NAT Gateway/EIP/ELB
- Marketplace/Support/RI/Savings Plans/Route 53 domain

ただし、次は許可する。

- list/get/describe
- batch cancel/terminate
- queue disable
- ECS stop/delete
- EC2 terminate
- OpenSearch delete
- S3 get/list for export
- S3 delete after export
- CloudWatch Logs delete
- Glue/Athena cleanup
- IAM cleanup for run roles, after all resources are gone

cleanup roleまでDenyすると、請求停止ができなくなるため、Deny policyは「作成禁止」であり「停止削除禁止」ではない。

### 9.2 Budget Actionsの位置づけ

Budget Actionsは次に限定する。

| Threshold | Action |
|---:|---|
| USD 17,000 | notify + low-yield stop |
| USD 18,300 | apply `DenyStretchServices` |
| USD 18,900 | apply `DenyNewWork` |
| USD 19,300 | apply `EmergencyDenyCreates` + trigger kill switch |
| paid exposure USD 25 | apply `DenyNewWork` |
| paid exposure USD 100 | apply `EmergencyDenyCreates` |

Budget Actionが遅れても、sentinelとkill switchが同じstateを見て停止する二重化にする。

## 10. zero-bill cleanupの最終定義

`COMPLETE_ZERO_BILL` と呼べる条件:

- Batch queues disabled/deleted。
- Batch jobsにSUBMITTED/PENDING/RUNNABLE/STARTING/RUNNINGがない。
- Compute environments削除済み。
- ECS task/service/clusterなし。
- EC2 instance、EBS volume、snapshot、AMI、EIP、NAT Gateway、LB、OpenSearchなし。
- Glue database/table/crawler/job、Athena workgroup/query resultなし。
- CloudWatch log group/alarm/dashboard/metric filterなし。
- ECR repo/imageなし。
- S3 bucket/object/version/multipart uploadなし。
- EventBridge schedule/ruleなし。
- Step Functions execution/state machineなし。
- Lambda function/triggerなし。
- KMS key/aliasはrun専用なら削除スケジュール済み。
- IAM role/policy/instance profileはcleanup完了後に整理済み。
- Cost Explorer/Billingで翌日以降の新規日次費用増加がない。

S3を残す状態は`COMPLETE_ZERO_BILL`ではなく`MINIMAL_AWS_ARCHIVE`と呼ぶ。ユーザー要件では採用しない。

## 11. Go/No-Go checklist

### GO before full-speed run

- `bookyou-recovery` / `993693061769` / `us-east-1` がledgerに固定されている。
- credit balance、expiry、eligible servicesをBilling consoleで確認済み。
- Budget ActionsとDeny policyが作成済み。
- kill switchがdummyで動作確認済み。
- external export gateが通っている。
- job registryにmax spend/runtime/items/retryがある。
- Batch queue capとservice capが設定済み。
- source_profile gateが通ったsourceだけ大量処理対象。
- private CSV/raw会計rowをAWSへ送らない。
- production runtimeがAWSに依存しない。

### NO-GO

- 「S3に置いて後で取る」だけで外部exportが未確定。
- Budgetsをhard cap扱いしている。
- `ap-northeast-1` と `us-east-1` が混在している。
- cleanup roleがDeny policyで停止削除不能になる。
- paid exposureが説明不能。
- untagged spendが説明不能。
- Cost data staleが6時間超なのに新規workを続けようとしている。
- no-hitを不存在・安全・適格・問題なしへ変換している。
- request-time LLMで公的事実を生成しようとしている。

## 12. 本体計画へ反映すべき修正

次の5点を本体統合計画へ反映する。

1. Regionを `us-east-1` に統一する。既存の `ap-northeast-1` 記載は、今回runでは不採用または別承認扱いにする。
2. `G2.5 External Export Gate` を追加する。これが通るまでfull-speed run禁止。
3. USD 18,900以降のstretchは、事前承認トークン方式にする。Codex/Claude不在でも条件が揃えば進むが、条件未達ならdrain。
4. `control_spend_usd` にrunning/queued/service cap/stale/untagged/cleanup reserveを足す。
5. `COMPLETE_ZERO_BILL` の定義をS3削除まで含める。S3残置は別状態として明確に不採用にする。

## 13. 最終判断

このAWS計画は、以下の条件付きで実行可能。

- 実行目的は、AWS上の永続サービスを作ることではなく、日本の公的一次情報をsource-backed artifactへ変換すること。
- USD 19,493.94ぴったりは狙わず、USD 19,300を意図的上限にする。
- 1週間以内消化は、Day 0 guardrail、Day 1-4高速standard、Day 5-7controlled stretch/export/teardownで狙う。
- Codex/Claudeのrate limitに依存しない自走は、AWS内部control planeで実現する。
- ただし、zero-billと成果物保持を両立するため、外部export gateをfull-speed run前に必ず通す。

この修正後の主順序は次で固定する。

```text
contract freeze
-> AWS autonomous guardrails
-> external export gate
-> canary
-> RC1 production
-> self-running standard AWS run
-> controlled stretch to safe line
-> final export/checksum
-> zero-bill teardown
-> post-teardown billing verification
```

## 14. 参照した公式情報

- AWS Budgets Actions: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html
- AWS Batch overview: https://docs.aws.amazon.com/batch/latest/userguide/what-is-batch.html
- AWS Step Functions overview: https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html
- Amazon EventBridge Scheduler overview: https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html
- Cost Explorer `GetCostAndUsage`: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
- Amazon CloudWatch overview: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html
