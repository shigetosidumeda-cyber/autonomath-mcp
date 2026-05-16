# jpcite AWS Credit Cost Guardrails Plan

作成日: 2026-05-15  
担当範囲: Cost guardrails / AWS Budgets / Cost Explorer / stop policy  
対象クレジット: USD 19,493.94  
目的: 1-2週間でクレジットを安全に有効消化し、クレジット超過の現金請求リスクを抑える。

## 前提と重要制約

- AWS Budgets は hard cap ではない。AWS Budgets は支出・使用量を追跡し、閾値超過時に通知またはアクションを実行する仕組みであり、課金そのものをリアルタイムに止める上限機能ではない。
- AWS 公式ドキュメント上、Budgets の課金データは少なくとも日次で更新され、Budgets 情報・アラートはそのデータ更新間隔に従う。別ページでは Budgets 情報は最大で1日3回、通常8-12時間間隔で更新されると説明されている。したがって数時間から1日程度の遅延を前提に停止バッファを置く。
- Budget Actions は「閾値を超えた後」に動く。IAM policy / SCP の適用、特定の EC2 / RDS インスタンスの停止などは可能だが、既に発生済みまたは集計遅延中のコストを取り消すものではない。
- 予測アラートは約5週間の利用データがないと発火しない場合がある。短期消化では actual cost の閾値とCost Explorerの日次監視を主に使い、forecast は補助扱いにする。
- クレジット消化率を見るには、クレジットを除外した gross burn と、クレジットを含めた paid exposure を分ける。単一の予算だけでは「クレジットを使えているか」と「現金請求が出始めたか」を同時に安全に見られない。
- Marketplace、Support、税、ドメイン、RI/Savings Plans前払い、サブスクリプション等はクレジット適用対象外または短期消化に不向きな可能性がある。今回の計画では原則として除外または禁止する。

## 数値設計

クレジット全額 USD 19,493.94 に対し、課金反映遅延と停止漏れを考慮して、運用上の gross burn 上限は USD 19,000.00 とする。残り USD 493.94 はバッファであり、最後まで使い切り狙いにしない。

| レベル | 金額 | 対クレジット | 意味 | 自動/手動アクション |
|---|---:|---:|---|---|
| L1 observe | 9,746.97 | 50% | 進捗確認 | 通知のみ |
| L2 pace check | 15,595.15 | 80% | 消化速度確認、残日数再計算 | 通知、Cost Explorer確認 |
| L3 soft brake | 17,544.55 | 90% | 新規高額リソース作成を止める | Budget ActionでDeny IAM/SCPを適用 |
| L4 stop window | 18,519.24 | 95% | 停止準備、既存ジョブの縮退 | Budget ActionでEC2/RDS停止対象を実行 |
| L5 absolute stop | 19,000.00 | 97.47% | 現金請求防止の運用上限 | 全ワークロード停止、SCP維持、手動確認 |

推奨消化ペース:

| 期間 | 全額消化ペース | 安全上限 USD 19,000 ペース |
|---|---:|---:|
| 7日 | 2,784.85/day | 2,714.29/day |
| 10日 | 1,949.39/day | 1,900.00/day |
| 14日 | 1,392.42/day | 1,357.14/day |

## Budgets構成

### Budget A: gross burn monitor

目的: クレジット消化対象になるAWSサービス利用額を、クレジット控除前に把握する。

- 名前: `jpcite-credit-gross-burn-202605`
- Type: `COST`
- Time unit: `CUSTOM`
- Time period: 2026-05-15 00:00 UTC から 2026-05-30 00:00 UTC。終了日は計算から除外されるため、2026-05-29までを含める意図なら 2026-05-30 を指定する。
- Budget limit: USD 19,000.00
- Cost metric: `UnblendedCost` または同等の非ブレンドコスト
- Cost types:
  - Credits: exclude
  - Refunds: exclude
  - Taxes: exclude
  - Support charges: exclude
  - Upfront RI / Savings Plans / non-reservation subscription: exclude
- Filters:
  - `BillingEntity = AWS`
  - `RecordType` でCredit/Refund/Tax/Support相当を除外できる場合は除外
  - 消化対象アカウント・リージョン・タグが決まっている場合は `LinkedAccount` / `Region` / `Tag` で限定

Actual thresholds:

- 50%: email + SNS通知
- 80%: email + SNS通知、手動Cost Explorer確認
- 90%: email + SNS通知、Budget Actionでsoft brake denyを自動適用
- 95%: email + SNS通知、Budget Actionでstop actionを自動実行または即時手動承認
- 100%: email + SNS通知、absolute stop runbookへ移行

Forecast thresholds:

- 80% forecast: 通知のみ
- 90% forecast: 通知のみ、actual閾値未達でも消化速度を落とす
- 注意: 予測アラートは短期・新規利用では約5週間の履歴不足により未発火の可能性があるため、停止判断の主軸にしない。

### Budget B: paid exposure monitor

目的: クレジット適用後の現金請求リスクを検知する。

- 名前: `jpcite-credit-paid-exposure-202605`
- Type: `COST`
- Time unit: `CUSTOM`
- Time period: Budget Aと同じ
- Budget limit: USD 100.00
- Cost metric: `NetUnblendedCost` またはクレジット控除後に近い指標
- Cost types:
  - Credits: include
  - Refunds: include
  - Taxes: include if taxes are real cash exposure
  - Support charges: include if support is billed outside credit coverage
- Actual thresholds:
  - USD 1: 通知、クレジット非適用コストの発生確認
  - USD 25: 新規リソース作成停止
  - USD 100: absolute stop

## Cost Explorer監視

短期消化中はBudgetsだけに依存しない。Cost Explorerで以下を1日2回、できれば開始・ピーク・停止前に確認する。

- Daily view:
  - Date range: 2026-05-15から当日+1日
  - Granularity: `DAILY`
  - Metric: `UnblendedCost`, `NetUnblendedCost`
  - Group by: `SERVICE`, `LINKED_ACCOUNT`, `REGION`
- Top drivers:
  - Group by `USAGE_TYPE`
  - 高額サービスは `RESOURCE_ID` が使える場合、resource-level daily dataを有効化して対象リソースを特定
- Hourly option:
  - Cost Explorerのhourly granularityは有料で、過去14日分の時間単位分析に使える。
  - EC2 resource-level hourly dataは有効化後、Cost Explorerで利用可能になるまで最大48時間かかるため、今回の1-2週間運用では早めに有効化する。
- 記録:
  - 09:00 JST: 前日分の確定傾向、Budget A/B、サービス別上位5件
  - 15:00 JST: 当日ペース、L3/L4到達見込み
  - 22:00 JST: 夜間停止判断、翌朝までの想定追加額

Cost Explorer確認用CLI例:

```bash
ACCOUNT_ID="<management-or-standalone-account-id>"
START_DATE="2026-05-15"
END_DATE="$(date -u -v+1d +%F)" # macOS例。Linuxでは date -u -d tomorrow +%F

aws ce get-cost-and-usage \
  --time-period Start="$START_DATE",End="$END_DATE" \
  --granularity DAILY \
  --metrics UnblendedCost NetUnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output table

aws ce get-cost-and-usage \
  --time-period Start="$START_DATE",End="$END_DATE" \
  --granularity DAILY \
  --metrics UnblendedCost NetUnblendedCost \
  --group-by Type=DIMENSION,Key=LINKED_ACCOUNT \
  --output table

aws ce get-cost-and-usage \
  --time-period Start="$START_DATE",End="$END_DATE" \
  --granularity DAILY \
  --metrics UnblendedCost NetUnblendedCost \
  --group-by Type=DIMENSION,Key=REGION \
  --output table
```

## Budget Actions設計

### Action role

Budget Actionsには、AWS Budgetsが代わりにIAM/SCP適用やEC2/RDS停止を実行するためのIAM roleが必要。AWS公式例では、trust policyに `budgets.amazonaws.com` を指定し、confused deputy対策として `aws:SourceArn` と `aws:SourceAccount` を条件に入れる。

Trust policy例:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "budgets.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "ArnLike": {
          "aws:SourceArn": "arn:aws:budgets::<ACCOUNT_ID>:budget/*"
        },
        "StringEquals": {
          "aws:SourceAccount": "<ACCOUNT_ID>"
        }
      }
    }
  ]
}
```

Permissions policy例:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstanceStatus",
        "ec2:StopInstances",
        "iam:AttachGroupPolicy",
        "iam:AttachRolePolicy",
        "iam:AttachUserPolicy",
        "iam:DetachGroupPolicy",
        "iam:DetachRolePolicy",
        "iam:DetachUserPolicy",
        "organizations:AttachPolicy",
        "organizations:DetachPolicy",
        "rds:DescribeDBInstances",
        "rds:StopDBInstance",
        "ssm:StartAutomationExecution"
      ],
      "Resource": "*"
    }
  ]
}
```

### L3 soft brake action

Trigger: Budget A actual 90%。

Action:

- 単独アカウント: ワークロード実行者のIAM user/group/roleに `jpcite-deny-new-spend-soft-brake` をattach。
- AWS Organizations利用時: 対象OUまたは対象アカウントに `jpcite-scp-deny-new-spend-soft-brake` をattach。SCP適用はmanagement accountのみ可能。
- 自動実行: Yes。
- 通知: email + SNS。

### L4 stop action

Trigger: Budget A actual 95%。

Action:

- 事前に列挙したEC2 instance IDsを停止。
- 事前に列挙したRDS DB instancesを停止。ただしRDS停止の制約、Multi-AZ/engine制約、停止後の自動再起動条件を別途確認する。
- ASG/ECS/EKS/Batch/SageMaker等の再起動系は、Budget ActionsのEC2/RDS停止だけでは復活する可能性があるため、L3のdeny policyと各サービス側のdesired count / queue / scheduler停止を併用する。
- 自動実行: 原則Yes。事業上どうしても停止前承認が必要ならNoにし、L4通知後30分以内の承認SLAを置く。

## IAM/SCP deny policy

### Soft brake IAM policy

新規の高額支出につながる作成・起動・購入を止める。既存リソースの参照、ログ確認、Cost Explorer/Budgets、停止操作は残す。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNewComputeAndManagedCapacity",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances",
        "ec2:CreateFleet",
        "ec2:CreateLaunchTemplate",
        "ec2:RequestSpotFleet",
        "autoscaling:CreateAutoScalingGroup",
        "autoscaling:UpdateAutoScalingGroup",
        "eks:CreateCluster",
        "eks:CreateNodegroup",
        "ecs:CreateService",
        "ecs:UpdateService",
        "batch:SubmitJob",
        "batch:CreateComputeEnvironment",
        "sagemaker:CreateTrainingJob",
        "sagemaker:CreateProcessingJob",
        "sagemaker:CreateEndpoint",
        "rds:CreateDBInstance",
        "rds:CreateDBCluster",
        "redshift:CreateCluster",
        "elasticmapreduce:RunJobFlow",
        "lambda:CreateFunction",
        "lambda:UpdateFunctionConfiguration"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyCommitmentsAndMarketplace",
      "Effect": "Deny",
      "Action": [
        "savingsplans:CreateSavingsPlan",
        "ec2:PurchaseReservedInstancesOffering",
        "rds:PurchaseReservedDBInstancesOffering",
        "redshift:PurchaseReservedNodeOffering",
        "aws-marketplace:Subscribe",
        "aws-marketplace:AcceptAgreementRequest"
      ],
      "Resource": "*"
    }
  ]
}
```

### Organization SCP variant

SCPは権限を付与せず、対象アカウント/OUで利用可能な最大権限を制限する。明示Denyは下位のAllowより優先される。Budget ActionでSCPをattachする場合はmanagement accountから実行する。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNewSpendAfterCreditThreshold",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances",
        "ec2:CreateFleet",
        "ec2:RequestSpotFleet",
        "autoscaling:CreateAutoScalingGroup",
        "autoscaling:UpdateAutoScalingGroup",
        "eks:CreateCluster",
        "eks:CreateNodegroup",
        "ecs:CreateService",
        "ecs:UpdateService",
        "batch:SubmitJob",
        "sagemaker:CreateTrainingJob",
        "sagemaker:CreateProcessingJob",
        "sagemaker:CreateEndpoint",
        "rds:CreateDBInstance",
        "rds:CreateDBCluster",
        "redshift:CreateCluster",
        "elasticmapreduce:RunJobFlow",
        "savingsplans:CreateSavingsPlan",
        "ec2:PurchaseReservedInstancesOffering",
        "rds:PurchaseReservedDBInstancesOffering",
        "aws-marketplace:Subscribe",
        "aws-marketplace:AcceptAgreementRequest"
      ],
      "Resource": "*"
    }
  ]
}
```

### Region guardrail SCP

消化ワークロードを少数リージョンに限定する。リージョン非依存のグローバルサービスは `NotAction` で例外化する。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyOutsideApprovedRegions",
      "Effect": "Deny",
      "NotAction": [
        "account:*",
        "billing:*",
        "budgets:*",
        "ce:*",
        "cloudfront:*",
        "cur:*",
        "iam:*",
        "organizations:*",
        "route53:*",
        "support:*",
        "sts:*"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": [
            "us-east-1",
            "us-west-2"
          ]
        }
      }
    }
  ]
}
```

## Stop policy

### 停止条件

次のいずれかを満たしたら新規消化を止める。

- Budget A actual >= USD 18,519.24
- Budget A forecast >= USD 19,000.00 かつ当日残り時間でUSD 300以上の追加発生が見込まれる
- Budget B actual >= USD 25.00
- Cost Explorerでクレジット対象外サービス、Marketplace、税、Support、予約前払い、予期しないリージョンが検出された
- Cost Explorerのサービス別上位に、停止できない継続課金サービスが出た

### 停止手順

1. L3 soft brake IAM/SCPがattach済みであることを確認。
2. ワークロードのscheduler、queue、CI/CD、Step Functions、Batch queue、ECS service、EKS node scaler、SageMaker endpoint/training jobを停止またはdesired count 0にする。
3. Budget Actionまたは手動でEC2/RDS停止対象を停止。
4. 30-60分後にCost Explorer、Budgets、サービスコンソールで新規起動がないことを確認。
5. 翌日09:00 JSTにBudgetsとCost Explorerを再確認し、反映遅延分込みでUSD 19,000未満に収まるか判定。
6. USD 19,000を超えた、またはBudget BがUSD 100へ近づく場合、Deny SCPを維持したまま全非必須リソースを削除または停止する。

## CLIに貼る順序

実行前に `<ACCOUNT_ID>`, `<SNS_TOPIC_ARN>`, `<BUDGET_ACTION_ROLE_ARN>`, `<TARGET_OU_OR_ACCOUNT_ID>`, `<POLICY_ARN>` を置換する。以下は順序確認用であり、この文書作成時点では実行していない。

### 1. 変数を置く

```bash
export AWS_REGION="us-east-1"
export ACCOUNT_ID="<ACCOUNT_ID>"
export SNS_TOPIC_ARN="<SNS_TOPIC_ARN>"
export BUDGET_ACTION_ROLE_ARN="<BUDGET_ACTION_ROLE_ARN>"
```

### 2. gross burn budgetを作る

```bash
cat > /tmp/jpcite-credit-gross-burn-budget.json <<'JSON'
{
  "BudgetName": "jpcite-credit-gross-burn-202605",
  "BudgetLimit": {
    "Amount": "19000.00",
    "Unit": "USD"
  },
  "CostTypes": {
    "IncludeTax": false,
    "IncludeSubscription": false,
    "UseBlended": false,
    "IncludeRefund": false,
    "IncludeCredit": false,
    "IncludeUpfront": false,
    "IncludeRecurring": false,
    "IncludeOtherSubscription": false,
    "IncludeSupport": false,
    "IncludeDiscount": true,
    "UseAmortized": false
  },
  "TimeUnit": "CUSTOM",
  "TimePeriod": {
    "Start": 1778803200,
    "End": 1780099200
  },
  "BudgetType": "COST"
}
JSON

aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget file:///tmp/jpcite-credit-gross-burn-budget.json
```

TimePeriodはUnix epoch seconds。`Start=2026-05-15T00:00:00Z`, `End=2026-05-30T00:00:00Z`。

### 3. gross burn通知を作る

```bash
for THRESHOLD in 50 80 90 95 100; do
  aws budgets create-notification \
    --account-id "$ACCOUNT_ID" \
    --budget-name "jpcite-credit-gross-burn-202605" \
    --notification "NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=$THRESHOLD,ThresholdType=PERCENTAGE" \
    --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
done

for THRESHOLD in 80 90; do
  aws budgets create-notification \
    --account-id "$ACCOUNT_ID" \
    --budget-name "jpcite-credit-gross-burn-202605" \
    --notification "NotificationType=FORECASTED,ComparisonOperator=GREATER_THAN,Threshold=$THRESHOLD,ThresholdType=PERCENTAGE" \
    --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
done
```

### 4. paid exposure budgetを作る

```bash
cat > /tmp/jpcite-credit-paid-exposure-budget.json <<'JSON'
{
  "BudgetName": "jpcite-credit-paid-exposure-202605",
  "BudgetLimit": {
    "Amount": "100.00",
    "Unit": "USD"
  },
  "CostTypes": {
    "IncludeTax": true,
    "IncludeSubscription": true,
    "UseBlended": false,
    "IncludeRefund": true,
    "IncludeCredit": true,
    "IncludeUpfront": true,
    "IncludeRecurring": true,
    "IncludeOtherSubscription": true,
    "IncludeSupport": true,
    "IncludeDiscount": true,
    "UseAmortized": false
  },
  "TimeUnit": "CUSTOM",
  "TimePeriod": {
    "Start": 1778803200,
    "End": 1780099200
  },
  "BudgetType": "COST"
}
JSON

aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget file:///tmp/jpcite-credit-paid-exposure-budget.json
```

### 5. paid exposure通知を作る

```bash
for AMOUNT in 1 25 100; do
  aws budgets create-notification \
    --account-id "$ACCOUNT_ID" \
    --budget-name "jpcite-credit-paid-exposure-202605" \
    --notification "NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=$AMOUNT,ThresholdType=ABSOLUTE_VALUE" \
    --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
done
```

### 6. Budget Actionを作る

Budget ActionのCLI入力は対象IAM/SCP/EC2/RDSにより形が変わる。以下は公式CLIの `create-budget-action` 形式に合わせたテンプレート。作成後、`describe-budget-actions-for-budget` で必ず確認する。

L3 IAM soft brake:

```bash
export SOFT_BRAKE_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/jpcite-deny-new-spend-soft-brake"
export TARGET_ROLE_NAME="<workload-role-name>"

aws budgets create-budget-action \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-gross-burn-202605" \
  --notification-type ACTUAL \
  --action-type APPLY_IAM_POLICY \
  --action-threshold ActionThresholdValue=90,ActionThresholdType=PERCENTAGE \
  --definition "IamActionDefinition={PolicyArn=$SOFT_BRAKE_POLICY_ARN,Roles=[$TARGET_ROLE_NAME]}" \
  --execution-role-arn "$BUDGET_ACTION_ROLE_ARN" \
  --approval-model AUTOMATIC \
  --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
```

L3 SCP soft brake:

```bash
export SOFT_BRAKE_SCP_ID="<p-xxxxxxxx>"
export TARGET_ORG_ID="<12-digit-account-id-or-ou-id>"

aws budgets create-budget-action \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-gross-burn-202605" \
  --notification-type ACTUAL \
  --action-type APPLY_SCP_POLICY \
  --action-threshold ActionThresholdValue=90,ActionThresholdType=PERCENTAGE \
  --definition "ScpActionDefinition={PolicyId=$SOFT_BRAKE_SCP_ID,TargetIds=[$TARGET_ORG_ID]}" \
  --execution-role-arn "$BUDGET_ACTION_ROLE_ARN" \
  --approval-model AUTOMATIC \
  --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
```

L4 EC2 stop:

```bash
export STOP_REGION="us-east-1"
export STOP_INSTANCE_IDS="i-xxxxxxxxxxxxxxxxx,i-yyyyyyyyyyyyyyyyy"

aws budgets create-budget-action \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-gross-burn-202605" \
  --notification-type ACTUAL \
  --action-type RUN_SSM_DOCUMENTS \
  --action-threshold ActionThresholdValue=95,ActionThresholdType=PERCENTAGE \
  --definition "SsmActionDefinition={ActionSubType=STOP_EC2_INSTANCES,Region=$STOP_REGION,InstanceIds=[$STOP_INSTANCE_IDS]}" \
  --execution-role-arn "$BUDGET_ACTION_ROLE_ARN" \
  --approval-model AUTOMATIC \
  --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
```

L4 RDS stop:

```bash
export STOP_REGION="us-east-1"
export STOP_RDS_IDS="jpcite-db-1,jpcite-db-2"

aws budgets create-budget-action \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-gross-burn-202605" \
  --notification-type ACTUAL \
  --action-type RUN_SSM_DOCUMENTS \
  --action-threshold ActionThresholdValue=95,ActionThresholdType=PERCENTAGE \
  --definition "SsmActionDefinition={ActionSubType=STOP_RDS_INSTANCES,Region=$STOP_REGION,InstanceIds=[$STOP_RDS_IDS]}" \
  --execution-role-arn "$BUDGET_ACTION_ROLE_ARN" \
  --approval-model AUTOMATIC \
  --subscribers "SubscriptionType=SNS,Address=$SNS_TOPIC_ARN"
```

確認:

```bash
aws budgets describe-budget-actions-for-budget \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-gross-burn-202605"
```

## 運用注意点

- SNS email subscriberは確認メールを承認しないと通知を受け取れない。
- Budgetsのactual alertは、同一budget period内で閾値に初めて到達したときのみ送られる。繰り返し通知が必要ならSNS側または外部監視でリマインドする。
- Custom period budgetは自動更新されず、終了日に期限切れとなる。今回の短期消化後は削除または次期間へ作り直す。
- AWS OrganizationsのSCPは、アカウント/OU/rootへのattach位置により影響範囲が大きく変わる。root attachは避け、対象OUまたは対象アカウントに限定する。
- SCPのDenyは管理者権限より優先される。break-glass roleが必要な場合でも、停止・請求確認・SCP解除に必要な最小操作がDenyに巻き込まれていないか事前確認する。
- Budget ActionsでEC2/RDSを止めても、Auto Scaling、ECS、EKS、Batch、SageMaker、外部CIが再作成・再起動する場合がある。L3 soft brake denyを先に入れる。
- Cost Explorerのhourly/resource-level dataは有料かつ反映に最大48時間かかる機能がある。短期運用では「詳細分析用」であり、即時停止の根拠にはしない。
- クレジット条件は契約・プロモーションごとに異なる。消化対象サービス、期限、Marketplace/Support/税/前払いの扱いはAWS Creditsページまたは契約条件で必ず確認する。

## 公式仕様メモ

- AWS Budgetsはコスト・使用量を追跡し、予算超過時に通知やアクションを実行できる。Budget ActionsはIAM policy、SCP、EC2/RDS対象アクションに対応し、SCP適用はmanagement accountのみ可能。  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-action-configure.html
- Budgetsの更新は課金データ更新に依存し、課金データは少なくとも日次更新。Budgets情報は最大で1日3回、通常8-12時間間隔で更新される。  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html
- Cost budgetsは、クレジット、返金、税、サポート、前払い、予約関連費用などを含める/除外する設定ができる。  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html
- Cost Explorerの `get-cost-and-usage` は `DAILY` / `MONTHLY` / `HOURLY` granularity、`UnblendedCost` / `NetUnblendedCost` 等のmetrics、`SERVICE` / `LINKED_ACCOUNT` / `REGION` 等のgroup-byに対応する。  
  https://docs.aws.amazon.com/cli/latest/reference/ce/get-cost-and-usage.html
- Cost Explorerのhourly/resource-level dataは過去14日分の詳細分析に使えるが、EC2 resource-level hourly dataは有効化後に利用可能になるまで最大48時間かかる。  
  https://docs.aws.amazon.com/cost-management/latest/userguide/ce-granular-data.html  
  https://docs.aws.amazon.com/cost-management/latest/userguide/ce-ec2-hourly.html
- SCPは権限を付与せず、対象アカウント/OU/rootの最大権限を制限する。明示Denyは下位のAllowに優先する。SCPのJSON構文はIAM policyに近いが、SCP固有の制約がある。  
  https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scp.html  
  https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_evaluation.html  
  https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_syntax.html
- AWS BudgetsがIAM/SCP適用やEC2/RDS停止を行うroleには、`budgets.amazonaws.com` trust policyと対象操作のpermissions policyが必要。  
  https://docs.aws.amazon.com/cost-management/latest/userguide/billing-example-policies.html
- AWS CLI `create-budget-action` は `APPLY_IAM_POLICY` / `APPLY_SCP_POLICY` / `RUN_SSM_DOCUMENTS` をaction typeとして受け、threshold、definition、execution role、approval model、subscriberを指定する。  
  https://docs.aws.amazon.com/cli/latest/reference/budgets/create-budget-action.html
