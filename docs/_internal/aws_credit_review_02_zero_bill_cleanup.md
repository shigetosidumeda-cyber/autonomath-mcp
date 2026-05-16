# AWS Credit Review 02: Zero-Bill Cleanup

作成日: 2026-05-15  
担当: zero-bill cleanup  
状態: 追加レビューのみ。実装、AWS CLI/API実行、Terraform/CDK作成、AWSリソース削除、AWSコンソール操作はしない。  
対象: AWSクレジット消化後に、AWS請求が二度と走らない状態へ落とすための棚卸し・削除順・検証方針。

## 0. 結論

クレジット消化後の正しい終了状態は、AWS上に「便利そうだから残す」リソースを置かないこと。jpciteに残す価値は、AWSリソースではなく、エクスポート済みの成果物、checksum、manifest、cost ledger、cleanup ledgerである。

ゼロ請求を本気で狙う場合、以下を原則にする。

1. 先に新規起動を止める。
2. 実行中のcomputeを止める。
3. 成果物をAWS外へ退避し、checksumを検証する。
4. 依存リソースを上位から削除する。
5. 最後にS3、ECR、CloudWatch、Glue/Athena、IAM/Budgetsの残骸を確認する。
6. Cost Explorer/Billing反映遅延を前提に、翌日・3日後・月末後に再確認する。

「S3だけ残す」はゼロ請求ではない。S3最終成果物の保管を許容する場合は、これは `Minimal AWS Archive` であり、ゼロビル完了とは別の終了状態として扱う。

## 1. Cleanup Scope

対象サービス:

- S3
- ECR
- AWS Batch
- ECS / Fargate
- EC2 / Spot / Auto Scaling
- EBS volumes
- EBS snapshots / AMIs
- OpenSearch domains / Serverless collections
- Glue Data Catalog / crawlers / jobs
- Athena workgroups / query result locations
- CloudWatch Logs / metrics / alarms / dashboards / EventBridge rules
- Lambda
- Step Functions
- VPC付帯: NAT Gateway, EIP, ENI, security groups, route tables, VPC endpoints
- Budgets / Budget Actions / Cost Anomaly monitors
- IAM / roles / policies / instance profiles / service-linked roles
- KMS keys and aliases if created only for the run
- CodeBuild or other auxiliary build resources if used

対象外だが確認だけ必要:

- Route 53 hosted zones / domains: ドメインやDNSをAWSで管理している場合は別会計。今回のcredit runが作ったものでなければ削除対象にしない。
- CloudFront / ACM / WAF: 今回のcredit runが作った場合だけ削除対象。既存本番配信と混ぜない。
- RDS / Redshift / SageMaker / EKS / EMR: 既存計画では非推奨または対象外だが、Cost Explorerに出た場合は即時棚卸し対象。

## 2. Zero-Bill Definition

`Zero-Bill Cleanup Done` と呼んでよい条件:

- `SpendProgram=aws-credit-batch-2026-05` または同等のタグが付いた有料リソースが残っていない。
- タグ漏れの疑いがあるリソースを、主要リージョンとグローバルサービスで確認済み。
- Batch queue、ECS service、EC2 instance、OpenSearch、NAT Gateway、EIP、Lambda trigger、Step Functions executionなど、継続課金または再起動し得るものが残っていない。
- S3 bucketsを残す場合は、ゼロビルではなく `Minimal AWS Archive` と明記している。ゼロビルならbucketごと削除済み。
- CloudWatch Logs、Athena query result、Glue crawler/job、ECR image、EBS volume/snapshot/AMIが残っていない。
- Budgets/Budget Actions/IAM deny guardrailは、必要なら短期残置してもよいが、課金リソースを作れない状態を保っている。
- 翌日以降のCost Explorerで新規日次コストが増えていないことを確認した。

## 3. Stop Before Delete

削除より先に新規課金の入口を閉じる。

順序:

1. `batch:SubmitJob`, `ecs:RunTask`, `ecs:CreateService`, `ec2:RunInstances`, `lambda:CreateFunction`, `states:StartExecution`, `glue:StartJobRun`, `athena:StartQueryExecution`, `es:Create*`, `aoss:Create*` をdenyするsoft brakeを維持する。
2. EventBridge schedule、Step Functions、Lambda trigger、CI/CD、operator cronなど、再投入元を止める。
3. Batch queuesを `DISABLED` にする。
4. ECS servicesのdesired countを0にする。
5. RUNNABLE/SUBMITTED/PENDING jobsをcancelし、RUNNING/STARTING jobsをterminateする。
6. OpenSearch、NAT Gateway、EC2、Fargate、Glue jobs、Athena queriesなど、時間課金・容量課金のものから止める。

理由: 先にS3やECRを消すと、まだ動いているjobが失敗retryし、CloudWatch Logsや再実行で追加費用を出す可能性がある。

## 4. Deletion Order

推奨削除順は以下。

| Order | Group | 消すもの | 理由 |
|---:|---|---|---|
| 1 | Ingress / scheduler | EventBridge rules, Step Functions triggers, CI/CD hooks, manual run scripts | 再投入を止める |
| 2 | Queue / orchestrator | Batch queues, Step Functions executions, Glue triggers | 新規実行を止める |
| 3 | Running compute | Batch jobs, ECS tasks/services, EC2 instances, Lambda provisioned concurrency | 時間課金を止める |
| 4 | Managed capacity | Batch compute environments, ECS clusters, Auto Scaling groups, launch templates | 再作成を止める |
| 5 | High-risk managed services | OpenSearch domains/collections, NAT Gateway, load balancers if any | 常駐課金が大きい |
| 6 | Network bill traps | EIP, ENI, NAT routes, VPC endpoints, unused public IPv4 | 忘れやすい継続課金 |
| 7 | Storage derivatives | EBS volumes, snapshots, AMIs, ECR images/repos | compute停止後に安全に消す |
| 8 | Data/query layer | Glue crawlers/jobs/databases/tables, Athena workgroups/results | S3 export確認後に消す |
| 9 | Logs/observability | CloudWatch log groups, alarms, dashboards, custom metrics, metric filters | ログ保管課金を止める |
| 10 | S3 | temp prefixes, query result buckets, final artifact buckets | export/checksum後に消す |
| 11 | Security/admin | IAM roles/policies/instance profiles, KMS keys/aliases, Budgets actions | 最後に権限と監視を整理 |
| 12 | Billing verification | Cost Explorer/Billing/Resource Explorer/Tag Editor | 残骸と遅延課金を確認 |

## 5. Service Checklist

### 5.1 S3

棚卸し:

- credit run用bucket
- raw/source lake prefixes
- normalized/parquet prefixes
- Athena query result buckets/prefixes
- CloudWatch export prefixes
- OpenSearch snapshot bucket if作成した場合
- incomplete multipart uploads
- versioned object / delete marker
- lifecycle rules
- replication / event notification / inventory / analytics

削除方針:

- ゼロビルなら全bucketを削除する。
- 削除前に `accepted_artifact_manifest`, `checksum_manifest`, `cleanup_ledger`, `cost_ledger` をAWS外へ退避する。
- versioning有効bucketは現行objectだけでなくnoncurrent versionsとdelete markersも消す。
- multipart uploadをabortする。
- S3 event notificationがLambdaやSQSを再起動しないよう先に外す。

残してよいもの:

- ゼロビルでは何も残さない。
- `Minimal AWS Archive` を明示する場合のみ、最終成果物bucket 1つ。public access block、lifecycle、budget alarm、versioning方針、storage class方針を必須にする。

残してはいけないもの:

- raw private CSV
- intermediate chunk
- debug dump
- Athena query result
- CloudWatch export
- failed job scratch
- replication設定付きbucket
- versioningで隠れている旧object

検証コマンド方針:

```bash
# read-only inventory template. Do not run until operator starts cleanup.
aws s3api list-buckets --query 'Buckets[].Name'
aws s3api get-bucket-tagging --bucket <bucket>
aws s3api list-object-versions --bucket <bucket> --max-items 20
aws s3api list-multipart-uploads --bucket <bucket>
aws s3 ls s3://<bucket>/<prefix>/ --recursive --summarize
```

### 5.2 ECR

棚卸し:

- repositories
- images/tags/digests
- lifecycle policies
- scan findings
- replication configuration

削除方針:

- image digest、SBOM、build manifestだけAWS外へ保存し、repoごと削除する。
- Batch job definitionがまだECR imageを参照していないことを先に確認する。

残してよいもの:

- ゼロビルではなし。
- repo再利用が必要ならAWS外のcontainer registryへ移す。

残してはいけないもの:

- untagged images
- old build cache images
- cross-region replicated repo
- scan-on-pushだけ残ったrepo

検証コマンド方針:

```bash
aws ecr describe-repositories --region <region>
aws ecr describe-images --repository-name <repo> --region <region>
aws ecr get-lifecycle-policy --repository-name <repo> --region <region>
```

### 5.3 AWS Batch

棚卸し:

- job queues
- compute environments
- job definitions
- running jobs
- array parent jobs
- CloudWatch log groups
- ECS clusters created by Batch
- EC2 launch templates / instance profiles used by compute environments

削除方針:

1. queueをdisable。
2. waiting jobsをcancel。
3. running jobsをterminate。
4. compute environmentをdisableしてdelete。
5. job queueをdelete。
6. job definitionsをderegister。
7. Batch管理ECS/EC2/EBS/ENIが消えたことを確認。

残してよいもの:

- ゼロビルではなし。
- run manifestやjob summaryはAWS外のcleanup ledgerへ移す。

残してはいけないもの:

- enabled queue
- valid job definition
- managed compute environment
- Spot fleet/launch template/ASGの残骸
- RUNNABLE job

検証コマンド方針:

```bash
aws batch describe-job-queues --region <region>
aws batch describe-compute-environments --region <region>
aws batch describe-job-definitions --status ACTIVE --region <region>
for status in SUBMITTED PENDING RUNNABLE STARTING RUNNING; do
  aws batch list-jobs --job-queue <queue> --job-status "$status" --region <region>
done
```

### 5.4 ECS / Fargate

棚卸し:

- clusters
- services
- tasks
- task definitions
- capacity providers
- CloudWatch log groups
- ENIs attached to Fargate tasks
- service discovery / load balancer if作成した場合

削除方針:

- servicesはdesired count 0にしてからdelete。
- running tasksをstop。
- clusterをdelete。
- task definitionsをderegister。
- Fargate ENIが消えるまで確認する。

残してよいもの:

- ゼロビルではなし。

残してはいけないもの:

- desired count > 0のservice
- running task
- ACTIVE task definition
- orphan ENI
- public IPv4付きservice

検証コマンド方針:

```bash
aws ecs list-clusters --region <region>
aws ecs list-services --cluster <cluster> --region <region>
aws ecs list-tasks --cluster <cluster> --desired-status RUNNING --region <region>
aws ecs list-task-definitions --status ACTIVE --region <region>
```

### 5.5 EC2 / Spot / Auto Scaling

棚卸し:

- instances
- Spot instance requests / fleets
- launch templates
- Auto Scaling groups
- placement groups
- key pairs created only for the run
- security groups
- public IPv4 addresses

削除方針:

- ASG desired/min/maxを0にしてdelete。
- Spot requests/fleetsをcancel。
- instancesをterminate。
- launch templatesをdelete。
- security groupsはENI/ECS/Batch削除後にdelete。

残してよいもの:

- 既存本番や別用途のEC2は触らない。
- credit runタグのEC2は残さない。

残してはいけないもの:

- stopped instance。停止中でもEBSは課金される。
- active Spot request
- ASG
- launch template
- unattached but billable public IPv4

検証コマンド方針:

```bash
aws ec2 describe-instances --filters "Name=tag:SpendProgram,Values=aws-credit-batch-2026-05" --region <region>
aws ec2 describe-spot-instance-requests --region <region>
aws ec2 describe-spot-fleet-requests --region <region>
aws autoscaling describe-auto-scaling-groups --region <region>
aws ec2 describe-launch-templates --region <region>
```

### 5.6 EBS Volumes / Snapshots / AMIs

棚卸し:

- available volumes
- in-use volumes attached to soon-deleted instances
- snapshots owned by account
- AMIs owned by account
- Fast Snapshot Restore if有効化した場合

削除方針:

- instances終了後、available volumesをdelete。
- credit run用AMIをderegisterしてから関連snapshotをdelete。
- snapshotだけ残ると継続課金になるため、AMIとsnapshotを対で確認する。

残してよいもの:

- ゼロビルではなし。

残してはいけないもの:

- unattached volume
- snapshot
- AMI
- Fast Snapshot Restore
- default encryption keyだけを理由に作ったKMS key

検証コマンド方針:

```bash
aws ec2 describe-volumes --filters "Name=status,Values=available" --region <region>
aws ec2 describe-snapshots --owner-ids self --region <region>
aws ec2 describe-images --owners self --region <region>
aws ec2 describe-fast-snapshot-restores --region <region>
```

### 5.7 OpenSearch

棚卸し:

- managed domains
- Serverless collections
- indexes
- snapshots
- VPC endpoints
- log publishing to CloudWatch
- KMS keys

削除方針:

- benchmark report、index mapping、query set、relevance resultだけAWS外へ保存する。
- domain/collectionをdelete。
- snapshot bucket/prefix、CloudWatch logs、VPC endpoint、security group、KMS keyを後続で削除する。

残してよいもの:

- ゼロビルではなし。
- 長期検索基盤として残す判断は今回のcredit runとは別稟議にする。

残してはいけないもの:

- domain
- Serverless collection
- OCU/capacity設定
- snapshot repository
- CloudWatch slow log
- VPC endpoint

検証コマンド方針:

```bash
aws opensearch list-domain-names --region <region>
aws opensearchserverless list-collections --region <region>
aws opensearchserverless list-vpc-endpoints --region <region>
```

### 5.8 Glue

棚卸し:

- databases
- tables
- crawlers
- jobs
- triggers
- workflows
- connections
- dev endpoints / interactive sessions if作成した場合
- Data Catalog resource policies

削除方針:

- Athenaやreport生成が終わった後、crawler/job/trigger/workflowから消す。
- 最後にtables、databasesを消す。
- S3 dataを先に消すと、catalogだけが残って混乱するため、export manifest確定後にまとめて消す。

残してよいもの:

- ゼロビルではなし。
- schema定義はMarkdown/JSONとしてrepoまたはAWS外に保存する。

残してはいけないもの:

- crawler
- scheduled trigger
- Glue job
- interactive session
- database/tableだけの残骸

検証コマンド方針:

```bash
aws glue get-databases --region <region>
aws glue get-crawlers --region <region>
aws glue get-jobs --region <region>
aws glue get-triggers --region <region>
aws glue get-workflows --region <region>
aws glue list-sessions --region <region>
```

### 5.9 Athena

棚卸し:

- workgroups
- named queries
- prepared statements
- query executions still running
- query result S3 locations
- data usage controls

削除方針:

- running queriesをstop。
- QA SQLと結果サマリだけAWS外へ保存。
- named queries、prepared statements、workgroupをdelete。
- result bucket/prefixをS3 cleanup対象に入れる。

残してよいもの:

- ゼロビルではなし。

残してはいけないもの:

- workgroup
- query result prefix
- saved query
- prepared statement
- federated connector Lambda

検証コマンド方針:

```bash
aws athena list-work-groups --region <region>
aws athena list-query-executions --work-group <workgroup> --region <region>
aws athena list-named-queries --work-group <workgroup> --region <region>
aws athena list-prepared-statements --work-group <workgroup> --region <region>
```

### 5.10 CloudWatch / EventBridge

棚卸し:

- log groups
- log streams
- metric filters
- subscription filters
- alarms
- dashboards
- custom metrics namespace
- EventBridge rules/schedules
- CloudWatch Logs exports

削除方針:

- scheduler/rulesを先にdisable/delete。
- log groupは必要な要約だけAWS外へ保存し、groupごとdelete。
- alarms/dashboards/metric filters/subscriptionsをdelete。
- custom metricsは即時削除APIがないため、送信元を止め、将来の課金を止める。

残してよいもの:

- ゼロビルではなし。
- cleanup証跡はAWS外のledgerに残す。

残してはいけないもの:

- retention unlimitedのlog group
- active subscription filter
- EventBridge scheduled rule
- alarm action that starts anything
- dashboard

検証コマンド方針:

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/ --region <region>
aws logs describe-metric-filters --log-group-name <log-group> --region <region>
aws cloudwatch describe-alarms --region <region>
aws cloudwatch list-dashboards --region <region>
aws events list-rules --region <region>
aws scheduler list-schedules --region <region>
```

### 5.11 Lambda

棚卸し:

- functions
- versions/aliases
- provisioned concurrency
- event source mappings
- function URLs
- layers
- CloudWatch log groups
- IAM roles

削除方針:

- event source mappingとtriggerを先にdisable/delete。
- provisioned concurrencyを削除。
- function、layer、log group、roleを削除。

残してよいもの:

- ゼロビルではなし。

残してはいけないもの:

- S3/EventBridge/SQS trigger付きfunction
- provisioned concurrency
- function URL
- layer versions
- execution role

検証コマンド方針:

```bash
aws lambda list-functions --region <region>
aws lambda list-event-source-mappings --region <region>
aws lambda list-layers --region <region>
aws lambda list-provisioned-concurrency-configs --function-name <function> --region <region>
```

### 5.12 Step Functions

棚卸し:

- state machines
- running executions
- Express workflows
- Map runs
- CloudWatch log destinations
- IAM roles

削除方針:

- running executionsをstop。
- state machine definitionとexecution summaryをAWS外へ保存。
- state machineをdelete。
- log groupとIAM roleを後続削除。

残してよいもの:

- ゼロビルではなし。

残してはいけないもの:

- active state machine
- running execution
- scheduled trigger
- Express workflow logs

検証コマンド方針:

```bash
aws stepfunctions list-state-machines --region <region>
aws stepfunctions list-executions --state-machine-arn <arn> --status-filter RUNNING --region <region>
aws stepfunctions list-map-runs --execution-arn <execution-arn> --region <region>
```

### 5.13 NAT / EIP / ENI / VPC付帯

棚卸し:

- NAT Gateways
- Elastic IPs
- ENIs
- VPC endpoints
- load balancers if作成した場合
- security groups
- route tables with NAT routes
- public IPv4 assignment

削除方針:

- NAT Gatewayは最優先削除対象。
- EIPは関連付け解除後にrelease。
- ENIは依存リソース削除後に消えるのを確認し、orphanが残れば依存元を調べる。
- VPC endpoint、security group、route table変更は既存ネットワークとの境界を確認してから削除する。

残してよいもの:

- 既存VPC本体は今回作成でなければ触らない。
- credit run用NAT/EIP/endpoint/ENIは残さない。

残してはいけないもの:

- NAT Gateway
- unassociated EIP
- orphan ENI
- VPC endpoint
- load balancer
- public IPv4 associated with stopped resources

検証コマンド方針:

```bash
aws ec2 describe-nat-gateways --region <region>
aws ec2 describe-addresses --region <region>
aws ec2 describe-network-interfaces --region <region>
aws ec2 describe-vpc-endpoints --region <region>
aws elbv2 describe-load-balancers --region <region>
```

### 5.14 Budgets / Cost / IAM

棚卸し:

- Budgets
- Budget Actions
- Cost Anomaly monitors/subscriptions
- IAM roles/policies/users/groups created for the run
- instance profiles
- service-linked roles
- SCP attachments if Organizations利用
- KMS keys/aliases/grants created for the run

削除方針:

- cleanupが完了するまではdeny guardrailを残す。
- cleanup完了後、credit run専用のBudget Actions、IAM roles/policies、instance profiles、KMS aliasesを削除する。
- Budgetsはゼロ確認のため月末まで残してもよいが、これは課金リソースではなく監視。不要なら削除する。
- Organizations SCPは他アカウント影響を確認してからdetach/deleteする。

残してよいもの:

- ゼロ確認用のBudget/Cost Anomaly monitorは短期残置可。
- 汎用のread-only billing roleは既存運用で使うなら残置可。

残してはいけないもの:

- compute作成権限を持つcredit run role
- stale instance profile
- Budget Action role that can stop/attach policies broadly without用途
- KMS key with scheduled deletion未設定かつcredit run専用
- access key

検証コマンド方針:

```bash
aws budgets describe-budgets --account-id <account-id> --region us-east-1
aws budgets describe-budget-actions-for-account --account-id <account-id> --region us-east-1
aws ce get-cost-and-usage --time-period Start=<start>,End=<end> --granularity DAILY --metrics UnblendedCost NetUnblendedCost --group-by Type=DIMENSION,Key=SERVICE --region us-east-1
aws iam list-roles
aws iam list-policies --scope Local
aws iam list-instance-profiles
aws kms list-keys --region <region>
aws kms list-aliases --region <region>
```

## 6. Residual Resource Sweep

タグだけに依存しない。タグ漏れはcleanup事故の主因になる。

確認レイヤー:

1. Cost Explorer: service / region / usage type別の日次コスト。
2. Resource Groups Tagging API: tagged resources。
3. AWS Resource Explorer if有効: free-textで `jpcite`, `credit`, `202605`, `batch`, `source-lake` を検索。
4. リージョン横断read-only sweep: `ap-northeast-1`, `us-east-1`, `us-west-2` と、実際に使ったリージョン。
5. グローバルサービス: IAM, Budgets, Cost Explorer, Route 53, CloudFront, Organizations。

read-only sweep方針:

```bash
for region in ap-northeast-1 us-east-1 us-west-2; do
  echo "REGION=$region"
  aws ec2 describe-instances --region "$region"
  aws ec2 describe-volumes --region "$region"
  aws ec2 describe-snapshots --owner-ids self --region "$region"
  aws ecs list-clusters --region "$region"
  aws batch describe-job-queues --region "$region"
  aws ecr describe-repositories --region "$region"
  aws opensearch list-domain-names --region "$region"
  aws opensearchserverless list-collections --region "$region"
  aws glue get-databases --region "$region"
  aws athena list-work-groups --region "$region"
  aws lambda list-functions --region "$region"
  aws stepfunctions list-state-machines --region "$region"
  aws ec2 describe-nat-gateways --region "$region"
  aws ec2 describe-addresses --region "$region"
  aws logs describe-log-groups --region "$region"
done
```

この文書では実行しない。実行時は出力を保存し、`cleanup_ledger` に「残置理由」「削除対象」「削除済み」「再確認日」を記録する。

## 7. Keep / Do Not Keep Matrix

| Resource | Zero-Billで残してよいか | Minimal Archiveで残してよいか | 判断 |
|---|---:|---:|---|
| Final artifacts in S3 | No | Yes, one locked-down bucket only | S3はゼロ請求ではない |
| S3 raw/intermediate/debug | No | No | 再配布/保管/容量リスク |
| ECR repo/images | No | No | digestだけ外部保存 |
| Batch queues/CE/job definitions | No | No | 再投入/管理残骸リスク |
| ECS cluster/services/tasks | No | No | 実行課金/ENI残骸 |
| EC2 stopped instances | No | No | EBS課金が残る |
| EBS volumes/snapshots/AMIs | No | No | 忘れやすい継続課金 |
| OpenSearch domain/collection | No | No | 常駐課金が大きい |
| Glue catalog only | No | Usually no | schemaは外部保存 |
| Athena workgroup/results | No | No | result S3が残りがち |
| CloudWatch logs/alarms | No | Usually no | cleanup証跡は外部保存 |
| Lambda functions/layers | No | No | trigger再実行リスク |
| Step Functions state machines | No | No | 定義は外部保存 |
| NAT Gateway | No | No | 最優先削除 |
| EIP | No | No | unassociated課金リスク |
| ENI | No | No | 依存残骸のシグナル |
| Budgets | Yes, short-term | Yes | 課金リソースではなく監視 |
| IAM deny policy | Yes, short-term | Yes | cleanup完了後に整理 |
| IAM workload role | No | No | 新規課金の入口 |
| Cost ledger / cleanup ledger | Outside AWS | Outside AWS | repoまたはローカル保管 |

## 8. Verification Gates

### Gate A: Compute Zero

- Batch queues disabled/deleted。
- Batch running/waiting jobs 0。
- ECS running tasks 0。
- ECS services 0 or desired count 0 and deletion済み。
- EC2 running/stopped credit-run instances 0。
- Lambda provisioned concurrency 0。
- Step Functions running executions 0。
- Glue running jobs 0。
- Athena running queries 0。

### Gate B: Capacity Zero

- Batch compute environments 0。
- ASG 0。
- Launch templates 0 for run。
- OpenSearch domains/collections 0。
- NAT Gateways 0。
- Load balancers 0。
- VPC endpoints 0 for run。

### Gate C: Storage Zero

- EBS available volumes 0。
- snapshots/AMIs for run 0。
- ECR repositories for run 0。
- S3 buckets for run 0 in zero-bill mode。
- Athena result prefixes 0。
- CloudWatch log groups for run 0。

### Gate D: Admin Closed

- workload IAM roles/policies removed。
- instance profiles removed。
- KMS keys scheduled for deletion where run-only。
- EventBridge rules/schedules removed。
- Budget Actions either removed or documented as temporary guardrail。
- Budgets remain only if intentionally monitoring zero spend.

### Gate E: Billing Quiet

- Cost Explorer shows no new daily cost after cleanup date, allowing normal reporting lag。
- `NetUnblendedCost` does not rise after credits are depleted。
- Service-by-service view has no unexplained line items。
- Region view has no unexpected region。
- Usage type view has no NAT, EIP, EBS, Snapshot, OpenSearch, CloudWatch Logs, S3 request/storage drift。

## 9. Cleanup Ledger Template

Cleanup時にAWS外で保存するledger。

```markdown
# AWS Credit Cleanup Ledger

Run ID:
Account ID:
Cleanup operator:
Cleanup start:
Cleanup end:
Regions checked:
Zero-bill target: yes/no
Minimal archive exception: yes/no

## Export Verification

| Artifact group | Source S3 prefix | External destination | Checksum manifest | Verified by | Time |
|---|---|---|---|---|---|

## Resource Deletion

| Service | Resource ID/name | Region | Tag match | Action | Result | Verification command output ref | Notes |
|---|---|---|---|---|---|---|---|

## Residual Exceptions

| Resource | Reason kept | Expected monthly cost | Owner | Delete/review date |
|---|---|---:|---|---|

## Billing Follow-up

| Date | CE daily cost | Net cost | Unexpected services | Action |
|---|---:|---:|---|---|
```

## 10. Risks and Countermeasures

| Risk | Typical cause | Countermeasure |
|---|---|---|
| S3を消したつもりで課金継続 | versioning, multipart upload, query result bucket | object versionsとmultipartを明示確認 |
| EC2停止後も課金 | EBS volume, EIP, snapshot | EC2ではなくEBS/EIP/snapshotを別Gateで確認 |
| Batch停止後に再投入 | EventBridge, Step Functions, CI/CD, manual script | schedulerを最初に止める |
| OpenSearch課金継続 | domain/collection削除忘れ | 高リスクmanaged serviceとして先に削除 |
| NAT課金継続 | private subnet構成の残骸 | NAT Gateway/EIP/routeを専用Gateにする |
| CloudWatchログ課金 | verbose job logs, unlimited retention | log group削除。必要要約は外部ledgerへ |
| IAM削除でcleanup不能 | roleを先に消す | IAM/Budgetsは最後に整理 |
| タグ漏れリソース | 手動作成、AWS managed side resources | タグ検索とサービス別read-only sweepを併用 |
| Cost Explorer遅延で誤判定 | 反映に時間差 | 翌日・3日後・月末後の再確認を必須化 |

## 11. Operator Decision

cleanup開始前に、operatorは次のどちらかを明示する。

### A. Zero Ongoing AWS Bill

選択条件:

- AWSに成果物を残さない。
- S3 bucketも削除する。
- Budgets/IAM deny以外のcredit runリソースを全削除する。

完了表現:

```text
I choose Zero Ongoing AWS Bill.
All valuable artifacts must be exported outside AWS before S3 deletion.
No AWS storage, compute, managed service, log, snapshot, image, NAT, EIP, or ENI from this run may remain.
```

### B. Minimal AWS Archive

選択条件:

- 月額小額のS3保管課金を許容する。
- ゼロビルとは呼ばない。
- 1 bucket、final artifacts only、public access block、lifecycle、near-zero budgetを必須にする。

完了表現:

```text
I choose Minimal AWS Archive, not zero bill.
I accept that S3 storage/request charges may continue.
Only the final artifact bucket may remain.
```

## 12. Final Recommendation

今回のcredit runの目的は、AWSインフラを持つことではなく、jpciteの公的source receipt、packet fixture、proof/eval成果物を短期で増やすこと。したがって標準終了状態は `A. Zero Ongoing AWS Bill` とする。

実行時の最後の一手は、サービス別に消したことではなく、Billingで静かになったことを確認するところまで含める。削除当日に緑でも、Cost Explorer/Billingの遅延を踏まえて、翌日、3日後、月末締め後に再確認する。
