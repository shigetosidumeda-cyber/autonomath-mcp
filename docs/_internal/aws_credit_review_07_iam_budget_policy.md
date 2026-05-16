# AWS credit review 07: IAM / Budgets / permission boundary

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 7/20  
担当: IAM・Budgets・権限境界・明示的Deny・タグ強制  
対象アカウント: `993693061769`  
AWS CLI profile: `bookyou-recovery`  
Region default: `us-east-1`  
状態: 計画レビューのみ。AWS CLI/API実行、AWSリソース作成、Terraform/CDK作成、既存変更の巻き戻しはしない。

## 0. 結論

今回のAWSクレジット消化は、`Budgets` だけでは止まらない。安全にほぼ全額を価値ある成果物へ変えるには、次の5層を実行前に揃える必要がある。

1. **人間用実行権限とBatch実行権限を分ける。**
2. **全runロールにpermission boundaryを付け、境界なしロール作成・PassRole・リージョン逸脱・禁止サービスを止める。**
3. **Budget Actionsは通知ではなく、`DenyNewWork` と `EmergencyDenyCreates` を貼る補助ブレーキとして使う。**
4. **タグなし作成を原則Denyし、タグ非対応サービスは作成直後のinventory gateで止める。**
5. **終了時はcleanup roleだけが停止・削除できる状態にし、export後にAWS上の有料リソースを消す。**

このレビューで統合計画へ入れるべき最重要修正は、**アカウント/リージョンの統一**である。ユーザーから与えられた実行環境は `bookyou-recovery` / account `993693061769` / default region `us-east-1` なので、実行計画の環境変数は原則次へ寄せる。

```bash
export AWS_PROFILE="bookyou-recovery"
export AWS_ACCOUNT_ID="993693061769"
export REGION="us-east-1"
export BILLING_REGION="us-east-1"
```

既存統合計画には `REGION="ap-northeast-1"` の例がある。混在はcross-region、ECR pull、S3/Athena/CloudWatch分散、region deny誤爆の原因になる。日本関連sourceを扱うこととAWS workload regionは別問題なので、短期artifact factoryは `us-east-1` 単一で揃えるのが安全で安い可能性が高い。もし `ap-northeast-1` を使うなら、S3/ECR/Batch/CloudWatch/Glue/Athena/OpenSearch/Textract/Bedrockをすべて同じregionへ明示的に切り替える。

## 1. 既存計画との接続

この文書は以下の計画・レビューを前提にする。

- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_01_cost_stoplines.md`
- `aws_credit_review_02_zero_bill_cleanup.md`
- `aws_credit_review_03_repo_script_mapping.md`
- `aws_credit_review_04_source_priority.md`
- `aws_credit_review_05_ocr_bedrock_opensearch.md`
- `aws_credit_review_06_network_transfer_risk.md`

既存計画の良い点:

- USD `17,000 / 18,300 / 18,900 / 19,300` の停止線が明確。
- Budgetsがhard capではないと明記済み。
- zero-bill cleanupの削除順が整理済み。
- NAT、public IPv4、cross-region、CloudWatch Logs、Athena scanの副費用リスクが整理済み。
- AWSは本番依存基盤ではなく、source receipts、packet examples、proof pages、GEO eval、cleanup ledgerを残す一時artifact factoryと位置付けられている。

不足している点:

- どのIAM principalが何を作れるかが未固定。
- `iam:PassRole` の境界が未固定。
- Budget ActionsでどのDeny policyをどのprincipalへ貼るかが未固定。
- タグ必須化のIAM条件と、タグ非対応リソースのinventory gateが未固定。
- リージョン方針が `us-east-1` と `ap-northeast-1` で割れている。
- 終了時にcleanup roleへどう権限を寄せ、operatorの新規作成権限をどう閉じるかが未固定。

## 2. Recommended IAM Principal Model

### 2.1 役割分離

最小構成は次の7ロール。既存の `bookyou-recovery` profileは、まずread-only確認とsetup/assume-role起点に使う。長時間のAWS credit runは専用roleで行い、既存IAM userへ直接広い権限を足さない。

| Role | 用途 | 作成/更新権限 | 実行権限 | 削除権限 | 常時必要か |
|---|---|---:|---:|---:|---|
| `JpciteCreditRunSetupRole` | 初回guardrail、IAM、Budgets、S3/ECR/Batch骨格作成 | あり | なし | 限定 | 初日だけ |
| `JpciteCreditRunOperatorRole` | queue cap変更、job投入、進捗確認、artifact確認 | 限定 | あり | 限定 | 実行中 |
| `JpciteCreditRunBatchExecutionRole` | ECS/BatchがECR pull、CloudWatch Logsへ書く | なし | 最小 | なし | 実行中 |
| `JpciteCreditRunBatchJobRole` | job内でS3入出力、必要最小API呼び出し | なし | public-only処理 | なし | 実行中 |
| `JpciteCreditRunBudgetActionRole` | BudgetsがDeny policyを貼る | なし | policy attachのみ | なし | 実行中 |
| `JpciteCreditRunCleanupRole` | drain/export後の停止・削除 | なし | 停止/削除 | あり | 終了時 |
| `JpciteCreditRunReadOnlyAuditRole` | Cost Explorer、Budgets、Resource inventory確認 | なし | read-only | なし | 実行中/終了後 |

重要な分離:

- `BatchJobRole` には `iam:*`, `budgets:*`, `ce:*`, `organizations:*`, `support:*`, `aws-marketplace:*`, `savingsplans:*` を持たせない。
- `OperatorRole` は `iam:PassRole` できるroleを `BatchExecutionRole` と `BatchJobRole` に限定する。
- `SetupRole` は便利だが危険なので、AWS-F1後に実行者から外すか、`DenyNewWork` の対象に入れる。
- `CleanupRole` は新規compute作成ではなく停止・削除・export検証用。emergency denyが貼られても cleanup はできるよう、Deny policyの設計で `Delete*`, `Stop*`, `Terminate*`, `Cancel*`, `Describe*`, `List*`, `Get*` を潰さない。

### 2.2 break-glass

Budget Actionや明示Denyが強すぎると、cleanupまで止めてしまう可能性がある。そのため、break-glassは1つだけ定義する。

| Principal | 目的 | 制約 |
|---|---|---|
| `JpciteCreditRunBreakGlassAdmin` または既存管理者 | Deny誤適用時の復旧、cleanup実行不能時の救済 | MFA必須。通常実行に使わない。run ledgerに使用理由、時刻、実行内容を記録。新規workload投入には使わない。 |

break-glassを「追加で仕事を流すための抜け道」にしてはいけない。用途は停止、削除、権限誤設定の復旧だけ。

## 3. Permission Boundary Design

全runロールと、run中に作る可能性がある新規IAM roleには、同じpermission boundaryを必須にする。

推奨名:

```text
JpciteCreditRunPermissionBoundary-2026-05
```

このboundaryは「許可を与える」ものではなく、identity policyが広すぎても超えられない最大権限を定義するものとして扱う。AWS IAMでは、identity policyとpermissions boundaryの交差が有効権限になり、明示Denyは常に優先される。

### 3.1 Boundaryに入れるDeny

| Deny | 目的 | 対象例 |
|---|---|---|
| `DenyCreateRoleWithoutBoundary` | 境界なしrole作成を防ぐ | `iam:CreateRole`, `iam:PutRolePermissionsBoundary` |
| `DenyPassUnapprovedRole` | 任意roleをBatch/ECS/EC2へ渡す事故を防ぐ | `iam:PassRole` |
| `DenyOutsideWorkloadRegion` | cross-region誤作成を防ぐ | `aws:RequestedRegion` |
| `DenyUnsupportedServices` | クレジット対象外/長期/高リスクサービスを防ぐ | Marketplace, Support upgrade, RI, Savings Plans, Route53 domain, RDS, Redshift, SageMaker, EKS, EMR等 |
| `DenyNetworkBillTraps` | 成果物にならない副費用を防ぐ | NAT Gateway, Elastic IP, ELB, Global Accelerator等 |
| `DenyMissingRequiredTags` | untagged spendを止める | tag-on-create対応サービス |
| `DenyBudgetGuardrailMutationByOperator` | operatorがBudget/Denyを外せないようにする | `budgets:Delete*`, `budgets:Update*`, `iam:Detach*`, `iam:DeletePolicy` |
| `DenyPublicS3` | artifact/data leakを防ぐ | public ACL/policy、public access block解除 |
| `DenyPrivateDataPrefixes` | private CSV/raw upload事故を防ぐ | S3 `private/*`, `csv/raw/*`, `uploads/raw/*` |

### 3.2 Region Deny

今回の推奨は `us-east-1` 単一regionである。Billing/Cost Explorer/Budgets/IAMなどglobal/control planeは例外が必要。

方針:

- workload resourceは `us-east-1` に固定。
- `aws:RequestedRegion` で `us-east-1` 以外のcreate/run/start系をDeny。
- IAM、Budgets、Cost Explorer、Organizationsなどglobal/control serviceは例外にする。
- 例外にしたglobal serviceでも、Marketplace、Support upgrade、commitment購入は別Denyで止める。

注意:

- `aws:RequestedRegion` Denyは、それ単体ではAllowを与えない。
- CloudFront、IAM、Route53、Supportなどglobal endpoint系を雑にDenyすると管理操作や請求確認まで壊れる。
- ただし今回CloudFront/Route53/Supportは基本不要なので、read-onlyを除き作成・購入・変更はDeny寄りにする。

### 3.3 PassRole Boundary

`iam:PassRole` は今回最も危険な穴になりやすい。Operatorが強いroleをBatchやECSへ渡せると、BatchJobRoleの境界が意味を失う。

必須条件:

- `OperatorRole` がPassRoleできるのは次だけ。
  - `arn:aws:iam::993693061769:role/JpciteCreditRunBatchExecutionRole-*`
  - `arn:aws:iam::993693061769:role/JpciteCreditRunBatchJobRole-*`
- `iam:PassedToService` を `ecs-tasks.amazonaws.com`, `batch.amazonaws.com` など必要サービスへ限定する。
- `BatchJobRole` から `iam:PassRole` は完全Deny。
- `SetupRole` から作成するroleには必ず `JpciteCreditRunPermissionBoundary-2026-05` を付ける。

### 3.4 Tag Enforcement

タグはCost Explorerだけでなく、cleanupとIAM条件の制御軸になる。既存レビューで使われているタグを統合し、次をcanonical tagsにする。

```text
Project=jpcite
SpendProgram=aws-credit-batch-2026-05
CreditRun=2026-05
Owner=bookyou
Environment=credit-run
Purpose=evidence-acceleration
AutoStop=2026-05-29T23:59:00+09:00
DataClass=public-only|synthetic-only|derived-aggregate-only
Workload=J01|J02|...|J24|guardrail|cleanup
```

タグ強制方針:

| Resource type | 方針 |
|---|---|
| tag-on-create対応 | `aws:RequestTag/Project=jpcite`, `aws:RequestTag/CreditRun=2026-05`, `aws:RequestTag/SpendProgram=aws-credit-batch-2026-05` を必須 |
| tag-on-create不完全 | 作成直後にtaggingし、tag確認が終わるまでqueue投入禁止 |
| tag非対応 | `resource_inventory_untagged_exception.csv` に明記し、Cost Explorerではservice/region/nameで追跡 |
| 既存本番resource | `CreditRun=2026-05` を付けない。credit runから触らない |

`DataClass` は特に重要。今回AWSに入れてよいのは以下だけ。

- `public-only`: 公的一次情報、公式source、public metadata
- `synthetic-only`: CSVヘッダや合成fixture
- `derived-aggregate-only`: ユーザーCSV由来でもrow-levelを含まない集計・安全な派生値

禁止:

- raw private CSV
- 会計摘要row
- 支払先/顧客名row
- free-form uploaded document
- user-specific ledger dump

## 4. Budget Actions Design

### 4.1 Budgetsの役割

Budgetsはhard capではない。今回のBudgets Actionsは、停止線を超えたあとに「追加作成権限を落とす」補助ブレーキとして使う。

AWS Budgets Actionsで使える方向性:

- IAM policyをユーザー/グループ/ロールへ適用
- SCPを適用。ただしOrganizations管理アカウント側の権限が必要
- 特定EC2/RDS instanceを対象にする

今回の主戦は、**IAM policy attachによる新規作成Deny**。SCPは使えるなら強いが、`bookyou-recovery` がOrganizations管理アカウント権限を持つ前提にしない。

### 4.2 Budget Set

既存レビュー01の3予算をIAM実装に接続する。

| Budget | Threshold | Action |
|---|---:|---|
| `jpcite-credit-gross-burn-2026-05` | USD 17,000 | 通知。low-value job停止を人間が判断 |
| `jpcite-credit-gross-burn-2026-05` | USD 18,300 | 通知 + `DenyStretchServices` をOperatorへ貼る候補 |
| `jpcite-credit-gross-burn-2026-05` | USD 18,900 | `DenyNewWork` を自動適用 |
| `jpcite-credit-gross-burn-2026-05` | USD 19,300 | `EmergencyDenyCreates` を自動適用 |
| `jpcite-credit-paid-exposure-2026-05` | USD 1 | 通知、scale-up禁止 |
| `jpcite-credit-paid-exposure-2026-05` | USD 25 | `DenyNewWork` を自動適用 |
| `jpcite-credit-paid-exposure-2026-05` | USD 100 | `EmergencyDenyCreates` を自動適用 |
| `jpcite-credit-account-backstop-2026-05` | low warning | account-level予期しない費用の通知 |

### 4.3 Deny Policies

#### `JpciteCreditRunDenyStretchServices-2026-05`

目的: Slowdown以降に、費用対成果がぶれやすいstretch系だけ止める。

Deny候補:

- `textract:*`
- `bedrock:*`
- `es:*`, `aoss:*`
- `ec2:CreateNatGateway`
- `ec2:AllocateAddress`
- `elasticloadbalancing:*`
- `athena:StartQueryExecution` ただしQA専用workgroupだけ例外にするなら別policyで限定

#### `JpciteCreditRunDenyNewWork-2026-05`

目的: No-new-work以降、新規computeや新規managed serviceを作らせない。cleanup/exportは残す。

Deny候補:

- `batch:SubmitJob`
- `ecs:RunTask`, `ecs:CreateService`, `ecs:UpdateService`
- `ec2:RunInstances`, `ec2:CreateLaunchTemplate`, `autoscaling:CreateAutoScalingGroup`, `autoscaling:UpdateAutoScalingGroup`
- `glue:StartJobRun`, `glue:CreateCrawler`, `glue:StartCrawler`
- `athena:StartQueryExecution`
- `states:StartExecution`
- `codebuild:StartBuild`
- `lambda:CreateFunction`, `lambda:InvokeFunction` for run-created functions
- `textract:*`, `bedrock:*`
- `es:Create*`, `aoss:Create*`
- `ecr:PutImage` except final image provenance, if needed

許可したいもの:

- `Get*`, `List*`, `Describe*`
- `batch:CancelJob`, `batch:TerminateJob`
- `ecs:StopTask`, `ecs:DeleteService`
- `ec2:TerminateInstances`
- `glue:Delete*`, `athena:Get*`, `athena:List*`
- `s3:GetObject`, `s3:ListBucket`, `s3:PutObject` to final report/checksum prefixes only, `s3:DeleteObject`
- `cloudwatch:DeleteAlarms`, `logs:DeleteLogGroup`

#### `JpciteCreditRunEmergencyDenyCreates-2026-05`

目的: Absolute safety lineやpaid exposure時に、追加費用につながる入口をほぼ全部閉じる。

注意: これを「全Deny」にしてはいけない。全Denyはcleanup不能を招く。止めるのはcreate/run/submit/start/update/put-scale系であり、read/export/delete/stopは残す。

対象:

- `JpciteCreditRunOperatorRole`
- `JpciteCreditRunSetupRole`
- `JpciteCreditRunBatchJobRole`
- `JpciteCreditRunBatchExecutionRole`

除外:

- `JpciteCreditRunCleanupRole`
- break-glass principal

ただしCleanupRoleにも新規作成系Denyは境界で残す。

### 4.4 Budget Action Role

`JpciteCreditRunBudgetActionRole` は、Budget Actionsが指定policyを指定roleへ貼るためだけに使う。

許可:

- `iam:AttachRolePolicy` / `iam:DetachRolePolicy` は指定Deny policyと指定roleだけ。
- `iam:ListAttachedRolePolicies`, `iam:GetPolicy`, `iam:GetPolicyVersion`
- `budgets:DescribeBudgetAction*`, `budgets:ExecuteBudgetAction`

禁止:

- 任意policy作成
- 任意role作成
- boundary削除
- billing設定変更
- Marketplace/Support/commitment購入

Budget Action作成時は `iam:PassRole` が依存権限になるため、`SetupRole` だけが `JpciteCreditRunBudgetActionRole` をBudgetsへpassできるようにする。

## 5. Cost Explorer / Billing Visibility

### 5.1 Read権限

`ReadOnlyAuditRole` と `OperatorRole` には最低限次を許可する。

- `ce:GetCostAndUsage`
- `ce:GetCostForecast`
- `ce:GetDimensionValues`
- `budgets:ViewBudget`
- `budgets:DescribeBudget*`
- `budgets:DescribeBudgetAction*`
- `billing:GetBillingViewData` if required by current Budgets permission model
- `account:GetAccountInformation` if available/needed
- resource inventory用の各service `List*`, `Describe*`, `Get*`

### 5.2 見るべきCost Views

毎回、tag-filteredだけで判断しない。タグ遅延やタグ漏れがある。

| View | 目的 |
|---|---|
| account unfiltered by service | account全体の想定外費用を拾う |
| account unfiltered by region | region逸脱を拾う |
| account unfiltered by usage type | NAT, Public IPv4, data transfer, Athena scan, CloudWatch Logsを拾う |
| `Project=jpcite` filtered | run成果物の主費用を見る |
| `SpendProgram=aws-credit-batch-2026-05` filtered | cleanup対象と費用を対応させる |
| untagged/resource inventory | タグ漏れ・既存resource混入を拾う |

Cost Explorer/Budgetsは遅延する。実行中の制御値は次で見る。

```text
control_spend = max(
  Cost Explorer run-to-date UnblendedCost excluding credits,
  Budget gross-burn actual,
  operator ledger committed spend estimate,
  previous confirmed spend + still-running max exposure
)
```

## 6. S3 And Data Boundary

IAMだけではデータ内容を理解できない。S3 bucket policyとprefix設計で事故を減らす。

推奨bucket:

```text
jpcite-credit-run-2026-05-993693061769-us-east-1
jpcite-credit-run-athena-2026-05-993693061769-us-east-1
```

prefix:

```text
raw-public/
normalized/
receipts/
claim_refs/
known_gaps/
packet_examples/
proof_pages/
geo_eval/
reports/
quarantine-public/
final_export/
```

作らないprefix:

```text
private/
csv/raw/
uploads/raw/
customer/
debug/full_payload/
```

bucket policy方針:

- public access block必須。
- `aws:SecureTransport=false` をDeny。
- public ACL / public policyをDeny。
- allowed principalsをrun rolesに限定。
- `private/*`, `csv/raw/*`, `uploads/raw/*`, `customer/*` へのPutをDeny。
- `DataClass` tagなしPutをDenyできる範囲ではDeny。S3 object tag enforcementが複雑な場合はwrapperで必須化し、manifest gateで止める。
- SSE-S3を標準。KMSを使う場合はKMS key削除・課金・権限をcleanup planへ含める。

## 7. SCP相当の考え方

### 7.1 Organizations SCPが使える場合

もし `993693061769` がAWS Organizations配下で、管理アカウント側からSCP適用できるなら、SCPで次をaccount-levelに止める。

- `aws-marketplace:*`
- Savings Plans作成
- RI購入
- Support plan変更
- Route53 domain登録/移管
- workload region外のcreate/run/start
- NAT Gateway / Elastic IP / ELBなど今回不要なnetwork trap
- RDS/Redshift/SageMaker/EKS/EMRなど今回範囲外の高額・長期サービス

ただしSCPは強力なので、cleanupに必要なdelete/stop/readまで潰さない。SCPは「作れない・始められない」方向に寄せる。

### 7.2 Organizations SCPが使えない場合

SCPが使えない場合は、次の組み合わせでSCP相当に近づける。

1. Permission boundary
2. Operator/Batch roleへの明示Deny policy
3. Budget ActionsによるDeny policy attach
4. S3 bucket policy
5. account-level S3 Block Public Access
6. Cost Explorer/Budgets/resource inventoryの頻回確認
7. stop scriptとmanual stop drill

この場合もrootや既存adminには完全なSCP制約が効かない。運用ルールとして、credit run中にroot/既存adminで新規AWS resourceを作らないことをrun ledgerへ明記する。

## 8. Merged Execution Order With Main jpcite Plan

本体計画とAWS計画は、次の順番で統合するのがよい。

### Phase 0: jpcite contract freeze

AWSに投げる前に、jpcite側で成果物contractを固定する。

- packet envelope
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `request_time_llm_call_performed=false`
- packet catalog
- CSV privacy allowlist
- artifact manifest schema
- GEO/forbidden-claim rubric

理由: contractがないままAWSで大量処理すると、S3に大きな中間物だけ残り、サービス価値に変換しにくい。

### Phase 1: AWS guardrail/IAM setup

このレビューの内容を先に作る。

- profile/account/region確認
- canonical tags確定
- permission boundary作成
- run roles作成
- S3 public block/bucket policy
- Budget Actions
- Deny policies
- Cost Explorer/Budgets read visibility
- stop drill

### Phase 2: wrapper dry-run

既存ingest/cronをそのまま投げず、S3 artifact contractへ出すthin wrapperを小さく試す。

- DB直接write禁止
- public-only/synthetic-only/derived-aggregate-only
- source_document / source_receipt / claim_ref / known_gap / manifest 出力
- CloudWatchは短いsummaryのみ

### Phase 3: USD 100-300 smoke run

IAM・Budget・Deny・tag・S3・cleanupが効くかを見る。

- J01 source profile small shard
- J03 invoice no-hit shape
- J12 completeness audit
- J15 one packet fixture
- J16 forbidden-claim small scan

合格条件:

- tag-filtered/unfiltered cost visibilityが両方見える
- untagged spendなし、または説明済み
- stop scriptが効く
- Budget Actionが指定Denyを貼れる
- private dataなし
- no-hit misuseなし

### Phase 4: standard source receipt run

J01-J16を、accepted artifact countを見ながら拡大する。

IAM条件:

- Operatorはqueue capとjob投入だけ。
- BatchJobRoleはS3指定prefixだけ。
- Stretch系serviceはまだ開放しない。

### Phase 5: controlled stretch

USD 18,300前後で価値が出ている場合のみ、J17-J24を選択実行する。

IAM条件:

- `DenyStretchServices` を外す場合は2時間以内のmanual approval。
- Textract/Bedrock/OpenSearchはpilot capとapproved job familyをrun ledgerへ記録。
- `EmergencyDenyCreates` を貼ってもcleanupできることを再確認。

### Phase 6: no-new-work / drain

USD 18,900、Day 13、または異常時に移行する。

- `DenyNewWork` を貼る。
- Batch queue disable。
- queued jobs cancel。
- nonessential running jobs terminate。
- final_export/checksum。
- repo取り込み用artifact manifest作成。

### Phase 7: zero-bill cleanup

ユーザー要件は「これ以上請求が走らない状態」なので、End State Aを標準にする。

- S3成果物をAWS外へexport。
- checksum確認。
- compute/managed service/log/storage/networkを削除。
- S3 bucketも削除。
- IAM/Budgets/Denyのうち、再作成防止に必要なものだけ短期残置するか、accountを完全に空にする。
- 翌日、3日後、月末後にCost Explorer/Billingで新規日次費用が増えていないことを確認する。

## 9. Go / No-Go Checklist

AWS書き込み前のGo条件:

- `AWS_PROFILE=bookyou-recovery`
- `aws sts get-caller-identity` のaccountが `993693061769`
- `REGION=us-east-1` に統一済み
- `BILLING_REGION=us-east-1`
- canonical tags確定
- permission boundary作成済み
- run roles作成済み
- `iam:PassRole` が指定roleだけに限定済み
- Budget ActionsがDeny policyを貼れる
- `DenyNewWork` と `EmergencyDenyCreates` を手動でも貼れる
- Cost Explorer/Budgets read visibilityあり
- S3 public access blockあり
- private/raw CSV prefixが存在しない
- stop drill成功
- cleanup roleで停止・削除できることを確認済み

No-Go条件:

- account IDが違う
- region方針が混在
- boundaryなしroleを作れる
- Operatorが任意roleをPassRoleできる
- Budget Action roleが任意policy/roleを操作できる
- タグなしで主要resourceを作れる
- NAT Gateway / EIP / Marketplace / Support / Savings Plans / RI / Route53 domain が作れる
- S3 public化が可能
- private CSV/raw upload先がある
- `DenyNewWork` 後にcleanupできない

## 10. 統合計画へ入れるべき具体的な修正点

- `AWS-F0` と `Terminal Execution Safety` の環境変数を、ユーザー指定に合わせて `AWS_PROFILE=bookyou-recovery`, `AWS_ACCOUNT_ID=993693061769`, `REGION=us-east-1`, `BILLING_REGION=us-east-1` に修正する。
- `ap-northeast-1` を使う可能性は「明示的に全workloadを同一regionへ切り替える場合のみ」として、混在禁止を追記する。
- `AWS-F1: Guardrail Setup` に `JpciteCreditRunPermissionBoundary-2026-05` 作成を最初の作業として追加する。
- `AWS-F1` に7ロール構成を追加する: Setup, Operator, BatchExecution, BatchJob, BudgetAction, Cleanup, ReadOnlyAudit。
- `iam:PassRole` は `BatchExecutionRole` と `BatchJobRole` だけ、かつ `iam:PassedToService` 条件付きに限定する。
- canonical tagsを統一する: `Project`, `SpendProgram`, `CreditRun`, `Owner`, `Environment`, `Purpose`, `AutoStop`, `DataClass`, `Workload`。
- タグ強制は `aws:RequestTag/*`, `aws:TagKeys`, resource inventory gateの三段構えにする。
- Budget Actionsは `DenyStretchServices`, `DenyNewWork`, `EmergencyDenyCreates` の3段policyを貼る設計にする。
- `DenyNewWork` と `EmergencyDenyCreates` はcleanup/export/delete/stop/readを潰さないようにする。
- `BudgetActionRole` の権限は、指定Deny policyを指定roleへattach/detachする範囲に限定する。
- `ReadOnlyAuditRole` に `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:GetDimensionValues`, `budgets:ViewBudget`, `budgets:Describe*`, `billing:GetBillingViewData` を明記する。
- Cost Explorer確認は tag-filtered と unfiltered account/service/region/usage-type の両方を必須にする。
- S3 bucket policyに public deny、TLS必須、allowed principal限定、private/raw prefix denyを追加する。
- SCPが使える場合のaccount-level Denyと、使えない場合のpermission boundary + IAM deny + Budget Action代替を明記する。
- 本体P0計画との順番を `contract freeze -> IAM guardrails -> wrapper dry-run -> smoke -> standard run -> controlled stretch -> drain -> zero-bill cleanup` に固定する。
- zero-bill要件に合わせ、End State Aを標準、End State Bを例外扱いに変更する。

## 11. References

- AWS Budgets Actions: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html
- AWS Budget Service IAM actions: https://docs.aws.amazon.com/service-authorization/latest/reference/list_awsbudgetservice.html
- IAM permissions boundaries: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html
- IAM tag-based access control: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_tags.html
- AWS global condition keys: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html
- Region deny example with `aws:RequestedRegion`: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_examples_aws_deny-requested-region.html
- AWS Organizations SCP examples: https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_examples.html
- Cost Explorer `GetCostAndUsage`: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
