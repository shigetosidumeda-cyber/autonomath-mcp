# AWS credit review 06: network / data transfer / NAT risk

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 6/20  
担当: network / data transfer / NAT risk  
対象クレジット: USD 19,493.94  
状態: Markdown追加レビューのみ。実装、AWS CLI/API実行、Terraform/CDK作成、AWSリソース作成、ジョブ投入はしない。

## 0. 結論

今回のAWSクレジット消化では、network/data transfer系の副費用を「成果物を作らない支出」として厳しく扱う。とくに、NAT Gateway、public IPv4、cross-region、cross-AZ、S3 transfer、CloudWatch Logs、Athena scan、ECR pullsは、Batch/Spot/S3中心の計画に紛れて見落としやすい。

方針は次の通り。

| 判断 | 構成 |
|---|---|
| 避ける | NAT Gateway常駐、private subnetからの大量egress、cross-region S3/compute、Multi-Region Access Point、S3 Transfer Acceleration、cross-region ECR replication/pull、大量debug log、raw JSON/HTMLへのAthena直scan、public IPv4を大量に持つFargate/EC2/ALB構成 |
| 許容 | 単一Region固定、S3とcomputeを同一Region、ECRとcomputeを同一Region、S3 gateway endpoint利用、public subnetの短命Batch/FargateでNATなし、CloudWatch Logsは短期retention/要約のみ、AthenaはParquet+compression+partition+workgroup制限 |
| 条件付き | cross-AZ冗長化、VPC interface endpoint、NAT Gateway、cross-region copy、ECR public pull、CloudWatch Logs Insights。必要性、上限、停止/削除条件、Cost Explorer確認点が事前に明記される場合のみ |

このレビューの核心は、**クレジットはcomputeに使えても、転送・ログ・IPv4・scanの副費用が現金請求や低価値burnに化ける**という点にある。今回の主構成は「同一RegionのS3正本 + Batch/Spot短命compute + 最小CloudWatch + Athena QA」に寄せ、private networkingで見た目をきれいにするためのNAT-heavy構成は採用しない。

## 1. 課金リスクの前提

2026-05-15時点のAWS公式料金ページ確認に基づく運用前提:

- NAT Gatewayは、NAT Gateway-hour、NAT経由GB単位のdata processing、標準data transferが重なる。AWS公式例でも、S3同一Region向けであってもNAT Gateway data processing chargeは残る。
- Public IPv4は、in-use/idleのいずれも時間課金対象。EC2だけでなく、ECS/EKS/RDS/WorkSpacesなどVPC内でpublic IPv4を作るサービスも対象になり得る。
- S3は、internetからのdata in、同一Region内S3 bucket間、同一RegionのS3からAWS serviceへのtransferなどは例外がある一方、cross-regionやinternet out、Multi-Region Access Point/Transfer Accelerationは別の課金面を持つ。
- Athenaは「serverlessで安い」ではなく、scan bytes課金である。query resultのS3保存、S3 request/data transfer、Glue Data Catalog、federated queryのLambdaも副費用になる。
- CloudWatch Logsは、ingestion、archive/storage、Logs Insights scan、Live Tail、custom metrics、vended logsで費用化する。log groupはデフォルトで無期限保持になり得るため、retention未設定は事故。
- ECRはrepository storageとdata transferが課金面。ECRとcomputeが同一Regionならtransferは原則無料だが、異なるRegionでは両側のinternet data transfer rateで課金され得る。

参照したAWS公式ページ:

- Amazon VPC pricing: https://aws.amazon.com/vpc/pricing/
- Amazon S3 pricing: https://aws.amazon.com/s3/pricing/
- Amazon Athena pricing: https://aws.amazon.com/athena/pricing/
- Amazon CloudWatch pricing: https://aws.amazon.com/cloudwatch/pricing/
- CloudWatch Logs retention: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/WhatIsCloudWatchLogs.html
- Amazon ECR pricing: https://aws.amazon.com/ecr/pricing/

## 2. 今回避ける構成

### 2.1 NAT Gateway前提のprivate subnet batch

避ける:

- Batch/Fargate/EC2をprivate subnetに置き、S3/ECR/CloudWatch/外部web取得をNAT Gateway経由にする構成。
- AZごとにNAT Gatewayを置いたまま長時間稼働させる構成。
- NAT Gatewayを「一時的」と言いながら、cleanup対象・削除時刻・Cost Explorer確認点がない構成。
- S3向けtrafficをNAT Gatewayに流す構成。

理由:

- NAT Gatewayは時間課金とGB処理課金があり、成果物が残らない。
- 同一Region S3向けでもNAT Gateway data processing chargeは避けられない。
- cross-AZでNAT Gatewayへ流れると、NAT費用に加えてAZ間data transferが乗る。

許容する代替:

- public subnetの短命Batch/Fargate/EC2で、NAT Gatewayを作らない。
- private subnetが必要な場合は、S3 gateway endpointを使い、S3 trafficをNAT Gatewayに流さない。
- ECR/CloudWatch/STS等のinterface endpointは、NAT削減効果が明確で、endpoint hourly/data processing費用を上回る場合だけ使う。

### 2.2 public IPv4を大量に持つ構成

避ける:

- Fargate taskにpublic IPv4を大量付与して長時間走らせる。
- EC2 Spot fleetでpublic IPv4を各instanceに付ける。
- ALB/NLB/Global Acceleratorなど、今回の短期batchに不要なpublic endpointを作る。
- idle Elastic IPを残す。

理由:

- public IPv4はin-use/idleとも時間課金される。
- 大量並列batchでは、task/instance単価よりpublic IPv4の副費用が見えにくい。
- 今回の成果物はS3/Parquet/manifestであり、常時公開endpointは不要。

許容する代替:

- EC2 Batch computeは可能ならpublic IPv4なしで、S3 gateway endpointまたは限定された同一Region AWS endpointへ寄せる。
- public subnetを使う場合でも、public IPv4付与の有無をjob queue別に固定し、短命で削除する。
- operator用の一時踏み台や公開APIは今回のcredit runから分離する。

### 2.3 cross-region前提

避ける:

- S3 bucketを複数Regionに置く。
- computeを`us-east-1`、S3を`ap-northeast-1`のように分ける。
- ECR imageを別Regionからpullする。
- S3 Cross-Region Replication、Multi-Region Access Point、Transfer Accelerationを使う。
- Bedrock/Textract/OpenSearchなど、Region都合だけでdata lakeを別Regionへ動かす。

理由:

- cross-regionはdata transfer outが発生しやすい。
- ECRは同一Region内transferは無料扱いでも、異Regionでは両側でinternet data transfer rateが発生し得る。
- Multi-Region Access PointやTransfer Accelerationは、便利さと引き換えにrouting/acceleration費用が増える。
- 短期成果物生成では、低遅延・冗長より、単一Regionでの原価可視化が重要。

許容する代替:

- 原則`ap-northeast-1`など単一workload Regionに固定する。
- Billing/Cost Explorer/Budgets等のglobal/control APIは別として、S3/ECR/Batch/EC2/Fargate/CloudWatch/Glue/Athenaは同一Regionに寄せる。
- cross-region copyは最終export/backupで必要な場合だけ、GB見積、対象prefix、回数、削除方針を明記する。

### 2.4 cross-AZを無制御に起こす構成

避ける:

- EC2/Fargateは複数AZ、NAT Gatewayは1 AZだけ、という経路。
- ALB cross-zoneやmulti-AZ serviceをbatch用途に使う。
- RDS/ElastiCache/EFS/OpenSearchなど、今回不要なmulti-AZ managed serviceを置く。
- S3以外のstateful storageをAZまたぎで読ませる。

理由:

- cross-AZ private trafficはサービス・経路によりdata transfer chargeが出る。
- Batch/Spotの短期jobでは、multi-AZ高可用性よりshard再実行のほうが安く制御しやすい。
- NAT GatewayとcomputeのAZ不一致は、NAT費用とAZ間転送の二重リスクになる。

許容する代替:

- Batch compute environmentは複数AZを許容しても、NAT/endpoint/storageのAZ整合を取る。
- AZ障害対策は常駐冗長ではなく、S3 checkpoint + shard再実行で持つ。
- OpenSearch等を使う場合は短期benchmarkに限定し、single-AZ/最小構成/TTL/delete after exportを明記する。

### 2.5 CloudWatch Logsを成果物扱いする構成

避ける:

- job stdoutにraw HTML/PDF text/JSONL全量を吐く。
- debug logを無制限に出す。
- log group retention未設定。
- CloudWatch Logs Insightsを巨大log groupへ雑に投げる。
- CloudWatch vended logs、Container Insights、detailed/custom metricsを一括有効化する。

理由:

- CloudWatch Logsはingestionと保存で費用化する。
- デフォルト無期限保持は、短期credit run後の継続課金になり得る。
- logsは成果物ではない。成果物はS3 manifest、Parquet、report、proofで残すべき。

許容する代替:

- stdoutはjob start/end、input shard id、output URI、count、error summary、cost tags程度。
- raw failure sampleやlarge debug payloadはS3の短期prefixに置き、lifecycleで削除。
- log retentionは3-14日。長期監査が必要なsummaryだけS3 reportへ。
- CloudWatch metricsはqueue depth、failed job count、timeout count、log bytes、cost alarmに限定。

### 2.6 Athena scanを無制御に増やす構成

避ける:

- raw JSON/CSV/HTML/PDF extracted textをAthenaで横断scanする。
- workgroup bytes scanned limitなし。
- partitionなし、compressionなし、Parquetなし。
- query result bucketにlifecycleなし。
- federated queryでLambdaや外部sourceを巻き込む。
- Provisioned Capacityを短期用途で予約する。

理由:

- Athenaはscan bytesが直接課金になる。
- 失敗queryでもS3 read/request等の周辺費用が出る。
- query resultもS3 storage/requestの対象になる。

許容する代替:

- Parquet + compression + partitionを標準にする。
- queryは`coverage`, `freshness`, `known_gaps`, `private_leak`, `forbidden_claim`, `cost_manifest`に限定。
- Athena workgroupにbytes scanned limitを置く。
- query result bucket/prefixに短期lifecycleを設定する。
- raw探索はまずsample subsetで行い、accepted schemaに落としてから全量QAする。

### 2.7 ECR pullsを見落とす構成

避ける:

- compute RegionとECR repository Regionが違う。
- jobごとに巨大imageをpullする。
- 毎回latest tagでpullし、cacheやdigest固定が効かない。
- cross-region replicationを有効化する。
- 不要なscan/signing/古いtagを残す。

理由:

- ECR repository storageは継続課金になる。
- 同一RegionのECR->EC2/Fargate等はtransfer無料扱いでも、異Regionはdata transferが乗る。
- imageが巨大だと、pull時間がFargate/Batch実行時間とCloudWatch log量にも波及する。

許容する代替:

- ECR repositoryとBatch/Fargate/EC2は同一Region。
- imageは小さく、digest固定、tag immutability、lifecycle policyあり。
- base imageは事前に絞り、workload別に無駄な依存を入れない。
- run終了時にtemp image/tagを削除し、final digest/SBOM/provenanceだけ残す。

## 3. 許容する構成の基準

今回のnetwork/data transfer観点で許容する構成は、次の条件をすべて満たす。

| 項目 | 基準 |
|---|---|
| Region | workloadは単一Region固定。S3/ECR/Batch/CloudWatch/Glue/Athenaを同一Regionに置く |
| Network | NAT Gatewayなしを標準。private subnetが必要な場合はS3 gateway endpointを優先 |
| Public IPv4 | 原則なし。必要な場合は短命、数、削除時刻、Cost Explorer確認点を明記 |
| AZ | cross-AZはBatchのcapacity目的だけ。NAT/storage/service経路のAZ不一致を作らない |
| S3 | source lake正本。Transfer Acceleration/MRAP/CRRは原則使わない |
| Logs | CloudWatchは最小監視。成果物はS3へ。retention 3-14日 |
| Athena | Parquet/compression/partition/workgroup limit/query result lifecycle必須 |
| ECR | same-region pull、small image、digest固定、lifecycleあり |
| Stop | queue disable、job cancel/terminate、log retention、ECR cleanup、S3 temp lifecycleが明記済み |

## 4. Cost Explorer / CURで見るべきUsageType

実行前後に見るべき観点。ここにある項目が上位に出る場合、compute成果物ではなくnetwork/log/scan副費用が膨らんでいる可能性が高い。

| リスク | Cost Explorer / CURでの見方 |
|---|---|
| NAT Gateway | Service=`Amazon Virtual Private Cloud`、UsageTypeに`NatGateway`, `NatGateway-Bytes`相当 |
| Public IPv4 | Service=`Amazon Virtual Private Cloud`、UsageTypeにpublic IPv4 address hour相当 |
| Cross-region | Group by `REGION`, `USAGE_TYPE`。`DataTransfer-Regional-Bytes`, inter-region transfer相当 |
| Cross-AZ | EC2/VPC/ELB系のregional data transfer、AZ間data transfer相当 |
| S3 transfer | Service=`Amazon Simple Storage Service`、DataTransfer-Out、Requests、Replication、MRAP/Acceleration相当 |
| CloudWatch Logs | Service=`AmazonCloudWatch`、Logs ingestion/storage/Insights/Live Tail/custom metrics/vended logs |
| Athena scan | Service=`Amazon Athena`、DataScanned、query count、workgroup別cost |
| ECR pulls/storage | Service=`Amazon Elastic Container Registry`、repository storage、data transfer out、replication |

運用上の赤信号:

- `Amazon Virtual Private Cloud`が上位サービスに出る。
- `AmazonCloudWatch`がBatch/EC2/Fargate compute費用に近づく。
- Athena costが成果物QAの価値に対して高い。
- S3 data transfer/cross-region/replicationがS3 storage/requestより目立つ。
- ECR transferやstorageが、container build回数に比べて大きい。

## 5. ジョブ設計への具体反映

### Batch / Fargate

- `assignPublicIp`を使う場合はqueue単位で明示し、public IPv4 chargeを見積対象に入れる。
- private subnet + NAT Gatewayをdefaultにしない。
- S3 input/outputは同一Region bucket。
- large download/uploadはS3 gateway endpointまたはsame-region AWS service pathを使う。
- stdoutは1 shardあたり数KBから数十KBに抑える。
- image pull削減のため、imageを小さくし、digest固定にする。

### S3 / Glue / Athena

- raw zoneは取得/保管可否をsource profileで判定し、長期raw保持を当然視しない。
- Athena対象は`normalized/parquet/*`に寄せる。
- `tmp/`, `athena-results/`, `debug/`, `scratch/`はlifecycle短期削除。
- MRAP、CRR、Transfer Acceleration、Requester Paysは今回の標準構成に入れない。

### CloudWatch

- log group命名に`jpcite-credit-202605`を含める。
- retention未設定を禁止する。
- Logs Insightsは障害調査だけ。QA集計はAthena/S3 report側で行う。
- Container Insightsやenhanced observabilityは、短期credit runでは原則無効。

### ECR

- repositoryはworkload Regionに1つまたは少数。
- `latest`運用を避け、digestをrun manifestに記録する。
- image lifecycleで古いtagを削除する。
- cross-region replicationは使わない。

## 6. 許容/禁止の早見表

| 領域 | 禁止/回避 | 許容 |
|---|---|---|
| NAT | 常駐NAT、S3 trafficのNAT経由、AZ不一致NAT | NATなし、または短期・上限・削除条件付き |
| IPv4 | 大量public IPv4、idle EIP、public ALB | なし。必要時は短命・少数 |
| Region | S3/ECR/compute分散、CRR/MRAP/Acceleration | 単一Region |
| AZ | NAT 1 AZ + compute複数AZ、stateful multi-AZ | shard再実行、S3 checkpoint |
| S3 | transfer機能乱用、temp prefix放置 | same-region正本、lifecycle |
| Logs | raw全量stdout、retention無期限 | 要約log、3-14日retention、S3 manifest |
| Athena | raw scan、limitなし、federated query | Parquet、partition、workgroup limit |
| ECR | cross-region pull、巨大image、tag放置 | same-region pull、小型image、digest固定 |

## 7. Go / No-Go条件

Go条件:

- Workload Regionが1つに決まっている。
- NAT Gatewayを作らない構成、または例外理由と削除時刻が明記されている。
- S3/ECR/Batch/Fargate/EC2/CloudWatch/Glue/Athenaが同一Regionに寄っている。
- CloudWatch Logs retentionが事前に決まっている。
- Athena workgroupのscan上限とresult lifecycleが決まっている。
- ECR lifecycleとsame-region pullが決まっている。
- Cost ExplorerでVPC/DataTransfer/CloudWatch/Athena/ECRを日次確認する担当と時刻が決まっている。

No-Go条件:

- 「private subnetなので安全」という理由だけでNAT Gatewayを置く。
- Regionをまたぐほうが速そう、という理由だけでcross-region化する。
- CloudWatch Logsを成果物保管場所にする。
- Athenaでraw lakeを直接全量scanする。
- public IPv4の数を見積に入れていない。
- ECR imageが巨大で、pull回数・Region・lifecycleが決まっていない。

## 8. このレビューの統合先

このレビューは、既存のAWSクレジット計画に次の制約として差し込む。

- `aws_credit_services_matrix_agent.md`: VPC/NAT/Data Transferを「D for spend」とした判断の詳細根拠。
- `aws_credit_cost_guardrails_agent.md`: Cost Explorerのservice/usage type確認に、VPC/DataTransfer/CloudWatch/Athena/ECRを明示する補助。
- `aws_credit_batch_compute_agent.md`: Batch/Fargate queue設計に、NATなし、same-region ECR/S3、log抑制、public IPv4見積を追加する補助。
- `aws_credit_unified_execution_plan_2026-05-15.md`: Layer A guardrailsとAWS Service Planの「NAT Gateway avoid」「CloudWatch minimal」「Athena controlled」を強化する補助。

最終判断: network/data transferは、今回のクレジットを消化する主役ではない。主役はS3に残るsource receipt、Parquet、proof、eval、manifestであり、networkはそれらを同一Region内で安く動かすための制約として扱う。
