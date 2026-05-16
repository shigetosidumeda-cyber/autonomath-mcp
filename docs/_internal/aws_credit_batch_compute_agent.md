# AWS credit batch compute plan for jpcite

作成日: 2026-05-15  
担当: AWS Batch / ECS / Fargate / Spot / CodeBuild / Step Functions 短期バッチ構成  
対象クレジット: USD 19,493.94  
期間: 1-2週間。安全側の標準案は14日、7日消化はquotaと日次監視が揃った場合だけ。  
Non-goals: 実装コード、AWSリソース作成、AWS CLI実行、LLM外部API消費、GPU浪費、意味のないCPU burnはしない。

## 0. 結論

このクレジットは、単なる負荷発生ではなく、jpciteの「AIが読む前の制度データ圧縮レイヤー」を厚くする短期前計算に使う。主戦場はAWS Batch on Fargate Spot / EC2 Spotで、成果物はS3に残るmanifest、source receipt、precomputed evidence packet、static proof page、benchmark resultに限定する。

推奨する上限は次の通り。

| Phase | 期間 | 目的 | 有効上限 | 1日Spend目安 | Gate |
|---|---:|---|---:|---:|---|
| P0 pilot | 0.5-1日 | queue、tag、TTL、停止手順、サンプル成果物を検証 | 128-256 vCPU | USD 100-300 | 成果物/Cost tag/stop動作が確認できる |
| P1 ramp | 2-3日 | 公式ソース・PDF・packet前計算を小さく回す | 512-1,024 vCPU | USD 700-1,400 | 失敗率10%未満、再実行率15%未満 |
| P2 full run | 4-10日 | 価値が残る並列バッチだけを投入 | 1,500-3,000 vCPU相当 | USD 1,200-2,200 | accepted artifactあたり原価が閾値内 |
| P3 drain | 最終1-2日 | 再実行、漏れ、S3 manifest固定、停止 | 256-512 vCPU | 残額に応じて調整 | queue空、CE disabled、Cost確認 |

USD 19,493.94を14日で使うなら平均USD 1,392/day、7日で使うなら平均USD 2,785/dayが必要になる。Fargate Linux/x86のUS East (N. Virginia)例では、AWS公式例の単価がvCPU秒USD 0.000011244、GB秒USD 0.000001235なので、1 vCPU + 2 GBで約USD 0.0494/hour、14日平均で約840 task-vCPU、7日平均で約1,680 task-vCPUが目安になる。実際はRegion、ARM/x86、Spot割引、EBS/S3/CloudWatch/NAT/Data Transfer、Credit適用対象で変わるため、初日にCost ExplorerとBillingのCredit utilizationで補正する。

## 1. 安全原則

1. `minvCpus=0`相当のゼロアイドル設計にする。クレジット消化のために常駐サービスを増やさない。
2. すべてのjobに`attemptDurationSeconds`を付ける。AWS Batchはtimeout未指定だとcontainerが終了するまで走るため、短期消化では禁止する。
3. queueは必ず`DISABLED`にできる形で分ける。止める時はECS clusterやBatch管理リソースを手で直接いじらず、Batch APIで止める。
4. Fargate Spot / EC2 Spotはinterrupt tolerantな作業だけに使う。checkpointなしの長時間単発処理はOn-Demandまたは小分けにする。
5. CodeBuildはbulk compute sinkにしない。build/test matrix、container image build、lint/security scanだけに使う。
6. Step Functions Distributed Mapはorchestratorに限定し、`MaxConcurrency`を明示する。未指定または0で10,000並列に寄る設計は禁止する。
7. CloudWatch Logsは成果物ではない。標準出力を大量に吐くjobは禁止し、要約、manifest、error sampleだけをS3に保存する。
8. 予算停止はBudgetだけに依存しない。Cost/Budget系は遅延するため、queue disable、job cancel/terminate、CE disableの手動runbookを先に固定する。
9. AWS creditsが対象外サービスに使われる可能性を考慮し、NAT Gateway、public IPv4、CloudWatch Logs、Data Transfer、KMS、ECR storageなどの副費用を日次で見る。
10. 価値gateを置く。accepted artifact率、dedupe率、source_receipt completion、known_gaps減少、static page生成数、benchmark coverageが伸びないバッチは止める。

## 2. 何をバッチ化するか

優先順位は「消費額」ではなく「クレジットが切れても残る資産」で決める。

| Priority | Workload | 入力 | 出力 | 推奨queue | Stop/resume性 | 価値指標 |
|---|---|---|---|---|---|---|
| P0 | official source profile sweep | P0/P1公式ソース、terms URL、API spec URL | `source_profile.jsonl`, license/freshness/no_hit policy | `jpcite-credit-fargate-spot-short` | 高い。source単位で再実行可能 | profile complete率、license unknown減少 |
| P0 | source receipt ledger precompute | existing evidence sources, official URLs | `source_receipts/*.jsonl`, checksum manifest | `jpcite-credit-ec2-spot-cpu` | 高い。URL/hash単位で冪等 | required receipt field欠損率 |
| P0 | public PDF extraction | prefecture/city/program PDFs, court/law/public docs | extracted facts, content hash, parse failure ledger | `jpcite-credit-ec2-spot-cpu` | 中。PDF単位checkpoint必須 | extracted_fact accepted率 |
| P0 | evidence packet precompute | program IDs, houjin IDs, invoice IDs, packet templates | precomputed evidence packets, known gaps | `jpcite-credit-fargate-spot-short` | 高い。subject単位で再実行可能 | packet_tokens_estimate、source_count |
| P1 | cross-source join expansion | houjin, invoice, gBizINFO, JGrants, EDINET, enforcement | join candidates, mismatch ledger | `jpcite-credit-ec2-spot-memory` | 高い。key range単位 | identity_confidence改善 |
| P1 | no-hit semantics regression | source profiles + synthetic absent queries | no_hit receipts, user-facing safe messages | `jpcite-credit-fargate-spot-short` | 高い | false absence claim 0 |
| P1 | static proof/public pages | packets, source receipts, sitemap shards | HTML/MD pages, sitemap shards, proof index | `jpcite-credit-ec2-spot-cpu` | 高い | generated pages、valid sitemap率 |
| P1 | GEO/SEO benchmark preprocessing | 100 query set, endpoint fixtures, pages | bench CSV/JSON, coverage deltas | `jpcite-credit-codebuild-batch` | 高い | reproducible benchmark rows |
| P2 | dependency/test matrix | Python 3.11/3.12, extras, OS images | test reports, coverage, SBOM, container scan | `jpcite-credit-codebuild-batch` | 高い | failures found per USD |
| P2 | archive normalization | `_archive` legacy embedding/reasoning outputs | normalized fixtures or deletion candidates | `jpcite-credit-ec2-spot-cpu` | 高い | migration candidates |

禁止する作業:

- 外部LLM APIをAWS Batchから大量に叩くこと。AWS creditでは外部token代は消えない。
- 有料/非公開/規約未確認データをbulk取得すること。
- CPUを空回しするベンチ、暗号採掘、無意味なrender、不要なGPU学習。
- Batch管理下のECS clusterに独自ECS serviceや手動taskを載せること。
- 失敗時に同じ巨大jobを無限retryすること。

## 3. Queue設計

命名は短期運用で grep しやすいように固定する。

| Queue | Compute environment | 用途 | 初期max vCPU | 最大max vCPU | Retry | Timeout | 備考 |
|---|---|---|---:|---:|---:|---:|---|
| `jpcite-credit-control-ondemand` | Fargate On-Demand | coordinator、manifest集約、小さい必須job | 32 | 128 | 1 | 15-60分 | 常時少量。止める時の最後まで残す |
| `jpcite-credit-fargate-spot-short` | Fargate Spot | 1-30分のstateless parser/packet job | 256 | 1,024 | 1-2 | 30分 | interruption前提。小粒array向き |
| `jpcite-credit-ec2-spot-cpu` | EC2 Spot, `SPOT_PRICE_CAPACITY_OPTIMIZED` | CPU heavy PDF parse、static generation、joins | 512 | 3,000 | 1-2 | 2-6時間 | c/m/r系、ARM/x86はCEを分ける |
| `jpcite-credit-ec2-spot-memory` | EC2 Spot memory families | large join、dedupe、parquet/jsonl compaction | 256 | 1,024 | 1 | 2-4時間 | memory OOMを見て増減 |
| `jpcite-credit-ec2-ondemand-rescue` | EC2 On-Demand | Spotで詰まる小数の再実行 | 0 | 256 | 0-1 | 1-2時間 | 普段は0。deadline前のdrainだけ |
| `jpcite-credit-codebuild-batch` | CodeBuild On-Demand | test/build/security matrix | project別quota内 | project別quota内 | 0-1 | 30-90分 | batch restrictions必須 |

Queue priority:

| Priority | Queue |
|---:|---|
| 100 | `jpcite-credit-control-ondemand` |
| 80 | `jpcite-credit-ec2-ondemand-rescue` |
| 60 | `jpcite-credit-fargate-spot-short` |
| 50 | `jpcite-credit-ec2-spot-cpu` |
| 40 | `jpcite-credit-ec2-spot-memory` |
| 20 | `jpcite-credit-codebuild-batch` |

Batch array job方針:

- array sizeは初期100-500、安定後でも2,000以内を標準にする。AWS Batch array jobの上限は10,000 childだが、1親jobで巨大化すると失敗時の再送単位が粗くなる。
- `AWS_BATCH_JOB_ARRAY_INDEX`でmanifest shardを引き、1 child = 1 source/subject/file rangeにする。
- parent arrayをcancel/terminateするとchildも止まる前提で、workloadごとにparent job IDをrun manifestに記録する。
- child timeoutは作業別に短くする。PDF parse 30-60分、join 2-4時間、static generation 15-30分、benchmark 30-90分。

## 4. max vCPUと消化ペース

上限は「1日で止め忘れた時の最大損失」を先に決める。

### 4.1 安全側14日案

| Day | max vCPU目安 | 主workload | Spend目標 |
|---:|---:|---|---:|
| 1 | 128-256 | pilot, stop drill, tag verification | USD 100-300 |
| 2 | 512 | source profile, receipt pilot, PDF sample | USD 500-900 |
| 3 | 1,024 | packet precompute first shard | USD 900-1,400 |
| 4-10 | 1,500-3,000 | full useful batch | USD 1,200-2,200/day |
| 11-12 | 1,000-1,500 | failed shard replay, joins, static/proof pages | 残額に応じる |
| 13 | 512 | final replay only | 残額に応じる |
| 14 | 0-256 | drain, report, disable/delete | 最小 |

### 4.2 7日案

7日で全額に寄せる場合は平均USD 2,785/dayが必要になる。以下を満たす時だけ採用する。

- Applied Service QuotasでFargate/EC2 Spot/On-Demand vCPUが十分にある。
- Cost allocation tagsが有効化済み。
- Budget/Anomaly alertに加えて、queue disable runbookを人間が実行できる。
- S3 output manifestを1-3時間おきに確認し、accepted artifactが増えている。
- EC2 Spotのcapacity不足でRUNNABLEが詰まったら、別Region/別instance familyではなくmax vCPUを下げる。短期で複雑化しない。

7日案の暫定上限:

| Queue | max vCPU |
|---|---:|
| `jpcite-credit-control-ondemand` | 128 |
| `jpcite-credit-fargate-spot-short` | 1,500 |
| `jpcite-credit-ec2-spot-cpu` | 4,000 |
| `jpcite-credit-ec2-spot-memory` | 1,500 |
| `jpcite-credit-ec2-ondemand-rescue` | 512 |

## 5. Tags / TTL

すべてのBatch job queue、compute environment、job definition、ECS task、CodeBuild project/build、Step Functions execution、S3 prefix、CloudWatch log groupに可能な範囲で同じtagを付ける。

| Tag | Value例 | 必須 | 用途 |
|---|---|---|---|
| `Project` | `jpcite` | yes | Cost allocation |
| `SpendProgram` | `aws-credit-batch-2026-05` | yes | 今回の切り出し |
| `Owner` | `shigetoumeda` | yes | escalation |
| `Environment` | `credit-batch` | yes | prodと分離 |
| `Purpose` | `precompute-evidence-packets` | yes | 無駄遣い判定 |
| `Workload` | `source-receipt-ledger` | yes | 成果物別原価 |
| `RunId` | `credit-20260515-001` | yes | manifest結合 |
| `Queue` | `jpcite-credit-ec2-spot-cpu` | yes | 運用停止 |
| `DataClass` | `public-only` | yes | private data混入防止 |
| `NoSecrets` | `true` | yes | secret禁止 |
| `TTL` | `2026-05-29T14:59:59Z` | yes | UTC推奨 |
| `DeleteAfter` | `2026-05-31` | yes | cleanup |
| `CostCapUSD` | `19500` | yes | 監査用 |
| `CreditSafeStop` | `required` | yes | runbook対象 |

TTLルール:

- job definition timeoutはTTLではない。TTLはresource cleanupとqueue disableの期限。
- run manifestに`planned_stop_at`, `hard_stop_at`, `delete_after`を入れる。
- `hard_stop_at`を過ぎたら新規submitを止め、queueを`DISABLED`、RUNNABLEをcancel、RUNNINGをterminateする。
- S3 output prefixはすぐ消さない。manifest、accepted artifacts、failure samples、cost reportは残す。中間chunk、temporary extraction、debug logsは`DeleteAfter`で消す。

## 6. Stop commands runbook

以下は実行しない。緊急停止時にoperatorが確認して使うテンプレート。

### 6.1 Submit停止

```bash
aws batch update-job-queue \
  --job-queue jpcite-credit-fargate-spot-short \
  --state DISABLED \
  --region <region>

aws batch update-job-queue \
  --job-queue jpcite-credit-ec2-spot-cpu \
  --state DISABLED \
  --region <region>
```

全queue:

```bash
for q in \
  jpcite-credit-control-ondemand \
  jpcite-credit-fargate-spot-short \
  jpcite-credit-ec2-spot-cpu \
  jpcite-credit-ec2-spot-memory \
  jpcite-credit-ec2-ondemand-rescue
do
  aws batch update-job-queue --job-queue "$q" --state DISABLED --region <region>
done
```

### 6.2 RUNNABLE / SUBMITTEDをcancel

```bash
for status in SUBMITTED PENDING RUNNABLE; do
  aws batch list-jobs \
    --job-queue jpcite-credit-ec2-spot-cpu \
    --job-status "$status" \
    --query 'jobSummaryList[].jobId' \
    --output text \
    --region <region> | tr '\t' '\n' | while read job_id; do
      [ -n "$job_id" ] && aws batch cancel-job \
        --job-id "$job_id" \
        --reason "credit batch emergency stop" \
        --region <region>
    done
done
```

### 6.3 STARTING / RUNNINGをterminate

AWS CLIの`terminate-job`はSTARTING/RUNNINGをFAILEDへ移し、それ以前の状態はcancel扱いになる。

```bash
for status in STARTING RUNNING; do
  aws batch list-jobs \
    --job-queue jpcite-credit-ec2-spot-cpu \
    --job-status "$status" \
    --query 'jobSummaryList[].jobId' \
    --output text \
    --region <region> | tr '\t' '\n' | while read job_id; do
      [ -n "$job_id" ] && aws batch terminate-job \
        --job-id "$job_id" \
        --reason "credit batch emergency stop" \
        --region <region>
    done
done
```

### 6.4 Compute environmentをdisable

```bash
for ce in \
  jpcite-credit-ce-fargate-spot-short \
  jpcite-credit-ce-ec2-spot-cpu \
  jpcite-credit-ce-ec2-spot-memory \
  jpcite-credit-ce-ec2-ondemand-rescue
do
  aws batch update-compute-environment \
    --compute-environment "$ce" \
    --state DISABLED \
    --region <region>
done
```

EC2 compute environmentはdrain後にmax vCPUを0へ寄せる。ただしAWS Batchの状態遷移、job残存、resource update制約に依存するため、まずqueue disableとjob terminateを優先する。

```bash
aws batch update-compute-environment \
  --compute-environment jpcite-credit-ce-ec2-spot-cpu \
  --compute-resources minvCpus=0,desiredvCpus=0,maxvCpus=0 \
  --region <region>
```

### 6.5 CodeBuildを止める

```bash
aws codebuild list-build-batches-for-project \
  --project-name jpcite-credit-codebuild \
  --filter status=IN_PROGRESS \
  --region <region>

aws codebuild stop-build-batch \
  --id <build-batch-id> \
  --region <region>
```

個別build:

```bash
aws codebuild stop-build \
  --id <build-id> \
  --region <region>
```

### 6.6 Step Functionsを止める

```bash
aws stepfunctions list-executions \
  --state-machine-arn <state-machine-arn> \
  --status-filter RUNNING \
  --region <region>

aws stepfunctions stop-execution \
  --execution-arn <execution-arn> \
  --cause "credit batch emergency stop" \
  --region <region>
```

### 6.7 ECS standalone taskが存在した場合

原則としてBatch管理外のECS taskは使わない。もし手動taskを作った場合だけ、cluster単位で止める。

```bash
aws ecs list-tasks \
  --cluster jpcite-credit-ecs \
  --desired-status RUNNING \
  --region <region>

aws ecs stop-task \
  --cluster jpcite-credit-ecs \
  --task <task-arn> \
  --reason "credit batch emergency stop" \
  --region <region>
```

## 7. Step Functions設計

Step Functionsは「大量並列実行」ではなく「manifestを分割し、Batch jobを投入し、結果を集約する制御面」に使う。

標準workflow:

1. `PrepareManifest`: S3 manifestを読み、workload/run_id/shard_countを検証する。
2. `PreflightCostGate`: planned shard数、vCPU、timeout、expected artifact数をチェックする。
3. `DistributedMap`: shard単位でBatch submit。`MaxConcurrency`はqueue max vCPUから逆算して明示する。
4. `WaitAndCollect`: Batch job statusとS3 output manifestを集約する。
5. `QualityGate`: accepted artifact率、known_gaps、parse failure率、log volumeを評価する。
6. `ContinueOrStop`: gate未達なら後続shardを投入しない。
7. `Finalize`: run summary、cost tag report、cleanup listをS3へ書く。

`MaxConcurrency`目安:

```text
MaxConcurrency = floor(queue_max_vcpu / per_job_vcpu / safety_factor)
safety_factor = 1.25-2.0
```

例:

| Workload | per job vCPU | queue max vCPU | MaxConcurrency |
|---|---:|---:|---:|
| source profile sweep | 1 | 256 | 128-200 |
| evidence packet precompute | 1-2 | 1,024 | 400-800 |
| PDF extraction | 2-4 | 2,000 | 250-700 |
| large join | 4-8 | 1,024 | 64-180 |

## 8. CodeBuildの使い道

CodeBuild batch buildsは同時・協調buildに使えるが、build roleに`StartBuild`等を持たせるとbuildspecから制限を迂回できるため、batch service roleとbuild roleを分ける。

使う対象:

- Python 3.11/3.12 test matrix。
- `dev`, `site`, `e2e` extrasの依存解決確認。
- Docker image build / vulnerability scan / SBOM。
- static site generatorのdry-run。
- API schema / OpenAPI / docs link validation。

使わない対象:

- 数千時間のCPU sink。
- public source crawling本体。
- long-running PDF extraction。
- 大規模join。

CodeBuild restrictions:

| 制約 | 設定 |
|---|---|
| `maximumBuildsAllowed` | 初期10、安定後25-50 |
| `computeTypesAllowed` | small/medium/large相当まで。2XLargeは必要時だけ |
| batch type | build matrix / graph。fanoutはbounded |
| timeout | 30-90分 |
| artifact | test report、coverage、scan summaryだけ |

## 9. 成果物manifest

各jobはS3に以下の最小manifestを残す。CloudWatch Logsから復元する設計にしない。

```json
{
  "run_id": "credit-20260515-001",
  "workload": "source_receipt_ledger",
  "shard_id": "000123",
  "job_id": "aws-batch-job-id",
  "queue": "jpcite-credit-ec2-spot-cpu",
  "started_at": "2026-05-15T00:00:00Z",
  "finished_at": "2026-05-15T00:21:00Z",
  "status": "succeeded",
  "input_count": 1000,
  "accepted_count": 943,
  "rejected_count": 57,
  "known_gap_count": 12,
  "source_receipt_complete_count": 931,
  "output_uri": "s3://<bucket>/credit-batch/run_id/workload/shard.jsonl",
  "content_sha256": "sha256:...",
  "estimated_vcpu_seconds": 2520,
  "estimated_memory_gb_seconds": 5040,
  "log_bytes": 8192
}
```

Acceptance gate:

| Workload | accepted条件 | 止める条件 |
|---|---|---|
| source profile | official URL、terms/license/freshness/no_hit欄が埋まる | `license=unknown`が70%超で改善しない |
| source receipt | URL、fetched_at、checksum、license、used_inが揃う | required fields欠損30%超 |
| PDF extraction | text hash、page refs、extract confidence、source URLが揃う | parse failure50%超またはlog過多 |
| packet precompute | `source_count`, `known_gaps`, `human_review_required`, `corpus_snapshot_id`保持 | sourceなしpacketが増える |
| static page | HTML valid、sitemap entry、canonical、source linksあり | 404/source missingが5%超 |
| benchmark | query、expected surface、response fixture、scoreが揃う | 再現不能/flake20%超 |

## 10. 無駄遣いを避ける方法

### 10.1 Cost gate

1. 初日だけ小さく回す。タグがCost Explorerに出るまで本番量にしない。
2. 日次で`SpendProgram=aws-credit-batch-2026-05`のNet unblended cost、credit applied、cash chargeを確認する。
3. `CostCapUSD`はUSD 18,000でsoft stop、USD 19,000でhard stop。USD 493.94は副費用・遅延請求・drain用のbuffer。
4. Fargate/EC2以外の副費用が10%を超えたら停止して原因を見る。
5. queue max vCPUの変更は1日2回まで。細かく増減して原因を見失わない。

### 10.2 Work gate

1. 価値が残るoutput URIを持たないjobは失敗扱い。
2. 同じinput hashで同じoutputがある場合はskipする。
3. manifestに`accepted_count=0`が続くshardはworkloadごと停止する。
4. retryは原則1回。Spot interruptionだけ2回まで。
5. log volumeが成果物サイズを超えるjobは修正対象。CloudWatch Logsに金を使わない。
6. public source側のrate limitや規約に抵触しそうな取得は止める。クレジット消化よりsource trustを優先する。

### 10.3 Data gate

1. `DataClass=public-only`を固定する。
2. private customer data、Stripe data、API keys、secrets、personal notesをjob inputへ入れない。
3. source termsが未確認ならmetadata/hashだけにする。本文転載や全文保存を成果物にしない。
4. `no_hit`はabsence証明として扱わない。checked scope、query、source version、timestampを残す。

## 11. AWS service別の使い分け

| Service | 使う理由 | 使いすぎ注意 |
|---|---|---|
| AWS Batch | queue、retry、array job、compute env分離、Spot活用 | timeout未指定、巨大array、RUNNABLE詰まり |
| ECS/Fargate | serverless container、短いstateless job | per-second課金だがpublic IPv4/Logs/NAT副費用あり |
| Fargate Spot | interrupt tolerant jobの単価圧縮 | Windows不可、capacity interruption |
| EC2 Spot via Batch | CPU/memory heavyを安く大量処理 | `maxvCpus`を単一instance分超える可能性、capacity不足 |
| EC2 On-Demand via Batch | rescue/drain/小数の確実な完走 | 消化は速いが無駄になりやすい |
| CodeBuild batch | build/test/security matrix | bulk CPU用途には割高・成果が薄い |
| Step Functions | bounded orchestration, Distributed Map | `MaxConcurrency`未指定、state transition膨張 |
| S3 | manifest/output/checkpoint | 小ファイル過多、不要中間物 |
| CloudWatch | metrics/error sample | debug log垂れ流し |

## 12. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| creditsが対象外サービスに適用されない | 現金請求 | 初日にBilling credit appliedを確認。副費用10%閾値 |
| Cost data遅延 | stop遅れ | queue/CE/job停止runbookを先に準備 |
| Spot capacity不足 | RUNNABLE滞留、期限内未消化 | On-Demand rescueは小さく、workloadを小粒化 |
| `maxvCpus`超過 | 想定以上のEC2起動 | EC2 Spot CEは単一instance分の超過をbufferに入れる |
| timeout未設定 | runaway | `attemptDurationSeconds`必須 |
| Step Functions過並列 | downstream throttling | `MaxConcurrency`明示、queue max vCPUから逆算 |
| Batch管理ECSを手動変更 | INVALID CE、unexpected cost | Batch APIだけで管理 |
| source規約違反 | trust毀損 | P0 source profile/terms checkを先行 |
| 成果物が使えない | クレジット浪費 | accepted artifact gate、manifest必須 |
| CloudWatch Logs肥大 | 副費用 | log_bytes gate、S3 manifest中心 |

## 13. Operator checklist

実行前:

- [ ] Billing creditの対象、期限、残額、cash charge状態を確認する。
- [ ] Cost allocation tagsを有効化する。
- [ ] Budget alert、Cost Anomaly Detection、SNS/email通知を作る。
- [ ] queue/CE/job/Step Functions/CodeBuild停止runbookをdry readする。
- [ ] S3 output prefix、lifecycle、manifest schemaを固定する。
- [ ] `DataClass=public-only`のinput manifestだけを使う。
- [ ] 初回runはmax 128-256 vCPUで始める。

日次:

- [ ] Credit applied / cash charge / unblended costを見る。
- [ ] `SpendProgram`別、`Workload`別原価を見る。
- [ ] accepted artifact数、failure率、retry率、log bytesを見る。
- [ ] RUNNABLE滞留とSpot interruptionを見る。
- [ ] 残額と残日数から翌日のmax vCPUを決める。

停止時:

- [ ] 全queueを`DISABLED`。
- [ ] SUBMITTED/PENDING/RUNNABLEをcancel。
- [ ] STARTING/RUNNINGをterminate。
- [ ] compute environmentを`DISABLED`。
- [ ] CodeBuild build batchをstop。
- [ ] Step Functions running executionをstop。
- [ ] S3 manifestとcost summaryを固定。
- [ ] 一時S3 prefix、ECR temp image、CloudWatch debug log groupのcleanup対象を列挙。

## 14. 推奨初回投入順

1. `source_profile_sweep`: 20-100 source。1 vCPU、timeout 15分、Fargate Spot。
2. `source_receipt_ledger_sample`: 1,000 URL/hash。1-2 vCPU、timeout 30分、Fargate Spot。
3. `pdf_extract_sample`: 100 PDF。2 vCPU、timeout 60分、EC2 Spot CPU。
4. `packet_precompute_sample`: 1,000 subject。1 vCPU、timeout 30分、Fargate Spot。
5. `static_proof_sample`: 1,000 pages。2 vCPU、timeout 30分、EC2 Spot CPU。
6. `codebuild_matrix`: Python/test/doc validation。CodeBuild batch max 10。
7. Gate通過後にmanifestを10xずつ増やす。いきなり全量submitしない。

## 15. 参考AWS公式情報

- AWS Fargate Pricing: https://aws.amazon.com/fargate/pricing/
- AWS Batch managed compute environments: https://docs.aws.amazon.com/batch/latest/userguide/managed_compute_environments.html
- AWS Batch job queues: https://docs.aws.amazon.com/batch/latest/userguide/job_queues.html
- AWS Batch array jobs: https://docs.aws.amazon.com/batch/latest/userguide/array_jobs.html
- AWS Batch compute resources / `maxvCpus`: https://docs.aws.amazon.com/batch/latest/APIReference/API_ComputeResource.html
- AWS Batch job timeouts: https://docs.aws.amazon.com/batch/latest/userguide/job_timeouts.html
- AWS CLI `batch terminate-job`: https://docs.aws.amazon.com/cli/latest/reference/batch/terminate-job.html
- AWS CodeBuild batch builds: https://docs.aws.amazon.com/codebuild/latest/userguide/batch-build.html
- AWS CodeBuild pricing: https://aws.amazon.com/codebuild/pricing/
- Step Functions Distributed Map: https://docs.aws.amazon.com/step-functions/latest/dg/state-map-distributed.html
- AWS Cost Anomaly Detection: https://docs.aws.amazon.com/cost-management/latest/userguide/getting-started-ad.html
