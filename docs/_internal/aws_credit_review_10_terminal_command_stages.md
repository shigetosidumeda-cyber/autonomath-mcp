# AWS credit review 10: terminal command stages runbook

作成日: 2026-05-15  
担当: 追加20エージェントレビュー 10/20, terminal execution stages  
対象AWS profile: `bookyou-recovery`  
対象AWS account: `993693061769`  
default / workload region: `us-east-1`  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、ジョブ投入、削除はこの文書作成時点では行わない。

## 0. このrunbookの位置づけ

この文書は、jpcite本体計画とAWS credit計画をターミナル操作に落とすための段階実行runbookである。目的は、USD 19,493.94 のAWS creditを1-2週間でほぼ価値ある成果物へ変えつつ、credit後にAWS請求が残らない状態へ戻すこと。

このrunbookは「最大消費」ではなく「最大成果物化」を優先する。AWSで作るべきものは、永続インフラではなく、jpciteへ取り込める次の成果物である。

- official source snapshots
- `source_profile` candidates
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- no-hit ledgers
- CSV synthetic/header-only/privacy fixture reports
- P0 packet examples
- proof page ledgers
- GEO / forbidden-claim / privacy / billing eval reports
- OpenAPI / MCP / `llms.txt` / `.well-known` discovery artifacts
- cost ledger
- cleanup ledger

## 1. 本体計画との実行順

AWSは本体計画を置き換えない。先にjpcite側の成果物契約を固定し、その契約に沿ってAWSを一時的なartifact factoryとして使う。

推奨順:

| Order | Lane | 実行内容 | AWSの役割 |
|---:|---|---|---|
| 1 | jpcite P0 contract freeze | packet envelope, source receipt fields, known gap enum, CSV privacy rule, no-hit wording, billing metadata, MCP/API route contractを固定 | まだ使わない |
| 2 | AWS preflight | credit, account, region, notification, billing visibility, existing spend, permissionsを確認 | read-onlyのみ |
| 3 | AWS guardrail setup | budgets, alarms, tags, S3 baseline, log retention, stop scripts, queue capsを用意 | write最小 |
| 4 | AWS stop drill | dummy/empty queueでdisable/cancel/terminate手順を確認 | 小さく停止練習 |
| 5 | AWS canary | USD 100-300以内でJ01/J03/J12/J15/J16の小片だけ実行 | 成果物契約の成立確認 |
| 6 | jpcite import gate | canary成果物をP0 packet/source receipt/known gaps/GEO gateへ当てる | 不合格ならscaleしない |
| 7 | AWS standard scale | J01-J16をartifact yieldで段階拡大 | credit消化の主戦場 |
| 8 | AWS stretch | J17-J24を選択実行。OCR/Bedrock/OpenSearchは条件付き | USD 18,300以降は厳格 |
| 9 | drain/export | no-new-work後、成果物をAWS外とrepoへ持ち帰る | 新規work禁止 |
| 10 | teardown | S3含む全credit-run resourceを削除 | zero ongoing bill |
| 11 | postmortem | cost/artifact/cleanup ledgerをjpcite docsへ保存 | 次回なしでも再現可能にする |

## 2. 絶対制約

- AWS Budgetsはhard capではない。実停止はqueue disable、job cancel/terminate、compute停止、managed service削除で行う。
- Credit face value `USD 19,493.94` は目標値にしない。
- 意図的利用の絶対安全線は `USD 19,300`。
- `USD 18,900` 以降は no-new-work。新規compute、OCR batch、OpenSearch、広いAthena scan、長時間jobは禁止。
- `USD 19,100-19,300` はmanual stretch。明示承認なしに入らない。
- credit対象外、Marketplace、Support upgrade、Reserved Instances、Savings Plans、Route 53 domain、upfront commitmentは禁止。
- AWSにraw private CSVを置かない。CSVはsynthetic/header-only/aggregate-only。
- request-time LLM化しない。`request_time_llm_call_performed=false` を壊さない。
- no-hitを「不存在」「安全」「問題なし」「適格」に変換しない。
- 禁止claim: `approved`, `eligible`, `safe`, `no risk`, `audit complete`, `tax correct`, `legal conclusion`, `creditworthy` 相当。
- credit消化後はAWS上に有料リソースを残さない。S3 bucketも、zero billを要求するなら削除する。

## 3. Stopline

| Line | USD | 操作 |
|---|---:|---|
| Watch | 17,000 | 低価値job停止。accepted artifactが増えるjobだけ継続 |
| Slowdown | 18,300 | OCR/OpenSearch/広いjoin/大きいAthena scan/探索jobを止める |
| No-new-work | 18,900 | 新規job投入禁止。finish, export, verify, cleanupのみ |
| Manual stretch | 19,100-19,300 | 明示承認がある短命artifact jobのみ |
| Absolute safety | 19,300 | emergency stop。意図的に超えない |
| Credit face value | 19,493.94 | 目標値ではない。lag/non-credit bufferとして残す |

制御に使う値:

```text
control_spend = max(
  Cost Explorer run-to-date UnblendedCost excluding credits,
  Budget gross-burn actual,
  operator ledger committed spend estimate,
  previous confirmed spend + still-running max exposure
)
```

## 4. 共通シェル前提

以下は、実行日になってからターミナルへ貼る前提の共通bootstrapである。ここでは実行しない。

```bash
#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE="bookyou-recovery"
export EXPECTED_ACCOUNT_ID="993693061769"
export AWS_REGION="us-east-1"
export AWS_DEFAULT_REGION="us-east-1"
export BILLING_REGION="us-east-1"
export AWS_PAGER=""

export PROJECT="jpcite"
export RUN_ID="2026-05"
export CREDIT_RUN="2026-05"
export SPEND_PROGRAM="aws-credit-batch-2026-05"
export RUN_START_DATE="2026-05-15"
export RUN_END_EXCLUSIVE="2026-05-30"

export ARTIFACT_BUCKET="jpcite-credit-${EXPECTED_ACCOUNT_ID}-${RUN_ID//-/}-artifacts"
export LOG_GROUP="/jpcite/aws-credit/${RUN_ID}"
export LOCAL_RUN_DIR="$HOME/jpcite-aws-credit-run-${RUN_ID}"
export LEDGER_DIR="$LOCAL_RUN_DIR/ledgers"
export EXPORT_DIR="$LOCAL_RUN_DIR/exported-artifacts"
export RUN_LOG="$LEDGER_DIR/terminal-$(date -u +%Y%m%dT%H%M%SZ).log"

mkdir -p "$LEDGER_DIR" "$EXPORT_DIR"
exec > >(tee -a "$RUN_LOG") 2>&1

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required variable is empty: $name" >&2
    exit 20
  fi
}

require_no_placeholder() {
  local value="$1"
  local label="$2"
  if [[ "$value" == *"<"* || "$value" == *">"* || "$value" == "TODO"* || "$value" == "CHANGE_ME"* ]]; then
    echo "ERROR: placeholder remains in $label: $value" >&2
    exit 21
  fi
}

confirm_account_readonly() {
  require_var AWS_PROFILE
  require_var EXPECTED_ACCOUNT_ID
  local actual
  actual="$(aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --query Account \
    --output text)"
  echo "AWS account: $actual"
  if [[ "$actual" != "$EXPECTED_ACCOUNT_ID" ]]; then
    echo "ERROR: wrong account. expected=$EXPECTED_ACCOUNT_ID actual=$actual" >&2
    exit 90
  fi
}

confirm_write_gate() {
  local phase="$1"
  confirm_account_readonly
  echo "WRITE PHASE: $phase"
  echo "Profile: $AWS_PROFILE"
  echo "Account: $EXPECTED_ACCOUNT_ID"
  echo "Region: $AWS_REGION"
  read -r -p "Type EXACTLY 'I CONFIRM JPCITE AWS CREDIT RUN WRITE' to continue: " answer
  if [[ "$answer" != "I CONFIRM JPCITE AWS CREDIT RUN WRITE" ]]; then
    echo "Write gate rejected."
    exit 91
  fi
}

confirm_stop_gate() {
  local phase="$1"
  confirm_account_readonly
  echo "STOP PHASE: $phase"
  read -r -p "Type EXACTLY 'STOP JPCITE CREDIT RUN NOW' to continue: " answer
  if [[ "$answer" != "STOP JPCITE CREDIT RUN NOW" ]]; then
    echo "Stop gate rejected."
    exit 92
  fi
}

confirm_teardown_gate() {
  confirm_account_readonly
  echo "DESTRUCTIVE TEARDOWN PHASE"
  echo "This can delete S3 objects/buckets, ECR repositories, Batch queues, logs, and other run resources."
  read -r -p "Type EXACTLY 'DELETE JPCITE AWS CREDIT RUN RESOURCES' to continue: " answer
  if [[ "$answer" != "DELETE JPCITE AWS CREDIT RUN RESOURCES" ]]; then
    echo "Teardown gate rejected."
    exit 93
  fi
}

append_ledger() {
  local file="$1"
  shift
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LEDGER_DIR/$file"
}

confirm_account_readonly
aws configure list --profile "$AWS_PROFILE"
append_ledger run_decisions.md "bootstrap completed"
```

## 5. Stage A: preflight

Preflightはread-onlyだけで終える。ここで失敗する場合、guardrail setupへ進まない。

### A1. Manual console gate

CLIだけで完結させない。AWS Billing consoleで次を人間が確認し、ledgerへメモする。

- Account IDが `993693061769`
- credit balanceが `USD 19,493.94` 近辺
- credit expiry date
- credit eligible services
- paid exposureが現時点でない、または既知
- support plan / Marketplace / commitments / Route 53 domainが今回runに混ざっていない
- alert emailが受信可能
- このrun後にAWS resourceを削除してよい

記録テンプレート:

```bash
cat <<'EOF' | tee -a "$LEDGER_DIR/manual_console_gate.md"
# Manual console gate

Checked by:
Checked at JST:
AWS account:
Credit balance shown:
Credit expiry:
Eligible services reviewed:
Paid exposure before run:
Support / Marketplace / commitments checked:
Alert email:
Decision: PASS / FAIL
EOF
```

### A2. Read-only account and billing check

```bash
confirm_account_readonly

aws ce get-cost-and-usage \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --time-period Start="$RUN_START_DATE",End="$RUN_END_EXCLUSIVE" \
  --granularity DAILY \
  --metrics UnblendedCost AmortizedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | tee "$LEDGER_DIR/cost_by_service_initial.json"

aws budgets describe-budgets \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --account-id "$EXPECTED_ACCOUNT_ID" \
  --output json | tee "$LEDGER_DIR/budgets_initial.json"

aws resourcegroupstaggingapi get-resources \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --tag-filters "Key=SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/tagged_resources_initial.json"
```

### A3. Existing resource inventory

既存resourceがある場合、今回runのものと混ざらないようにする。削除対象は必ずタグで限定する。

```bash
aws s3api list-buckets \
  --profile "$AWS_PROFILE" \
  --query 'Buckets[].Name' \
  --output text | tee "$LEDGER_DIR/s3_buckets_initial.txt"

aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_queues_initial.json"

aws batch describe-compute-environments \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_compute_envs_initial.json"

aws ecs list-clusters \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/ecs_clusters_initial.json"

aws ec2 describe-instances \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --output json | tee "$LEDGER_DIR/ec2_instances_initial.json"

aws ec2 describe-nat-gateways \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/nat_gateways_initial.json"

aws ec2 describe-addresses \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/eip_initial.json"

aws opensearch list-domain-names \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/opensearch_initial.json"

aws glue get-databases \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/glue_databases_initial.json"

aws athena list-work-groups \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/athena_workgroups_initial.json"

aws logs describe-log-groups \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/log_groups_initial.json"
```

### A4. Preflight pass/fail

Preflight合格条件:

- `aws sts get-caller-identity` が `993693061769`
- Cost Explorer / Budgets readが成功
- alert emailが確定
- 既存resourceのうち、今回runで触らないものが識別済み
- `us-east-1` 単一regionで進める方針が確定
- NAT Gatewayを標準では使わない
- raw private CSVをAWSへ上げない
- P0成果物契約が固定済み、またはcanary範囲が契約検証に限定されている

```bash
cat <<'EOF' | tee -a "$LEDGER_DIR/preflight_decision.md"
# Preflight decision

Account confirmed:
Billing read confirmed:
Budget read confirmed:
Existing resources reviewed:
Region decision: us-east-1
NAT decision: no NAT by default
Private CSV decision: no raw private CSV on AWS
P0 contract gate:
Decision: PASS / FAIL
EOF
```

## 6. Stage B: guardrail setup

Guardrail setupは最小write phase。目的は、creditを使い始める前に止める仕組みと証跡を作ること。

### B1. Required variables

```bash
export ALERT_EMAIL="<set-alert-email-before-running>"
require_no_placeholder "$ALERT_EMAIL" "ALERT_EMAIL"
```

### B2. Budget alerts

Budgetsはhard capではない。通知と補助ブレーキであり、主停止手段ではない。

```bash
confirm_write_gate "guardrail setup: budgets"

cat > "$LOCAL_RUN_DIR/budget-gross.json" <<JSON
{
  "BudgetName": "jpcite-credit-run-gross-${RUN_ID}",
  "BudgetLimit": {
    "Amount": "19300",
    "Unit": "USD"
  },
  "CostTypes": {
    "IncludeTax": true,
    "IncludeSubscription": true,
    "UseBlended": false,
    "IncludeRefund": false,
    "IncludeCredit": false,
    "IncludeUpfront": true,
    "IncludeRecurring": true,
    "IncludeOtherSubscription": true,
    "IncludeSupport": true,
    "IncludeDiscount": false,
    "UseAmortized": false
  },
  "TimeUnit": "MONTHLY",
  "TimePeriod": {
    "Start": "${RUN_START_DATE}T00:00:00Z",
    "End": "${RUN_END_EXCLUSIVE}T00:00:00Z"
  },
  "BudgetType": "COST"
}
JSON

cat > "$LOCAL_RUN_DIR/budget-paid-exposure.json" <<JSON
{
  "BudgetName": "jpcite-credit-run-paid-exposure-${RUN_ID}",
  "BudgetLimit": {
    "Amount": "100",
    "Unit": "USD"
  },
  "CostTypes": {
    "IncludeTax": true,
    "IncludeSubscription": true,
    "UseBlended": false,
    "IncludeRefund": false,
    "IncludeCredit": true,
    "IncludeUpfront": true,
    "IncludeRecurring": true,
    "IncludeOtherSubscription": true,
    "IncludeSupport": true,
    "IncludeDiscount": true,
    "UseAmortized": false
  },
  "TimeUnit": "MONTHLY",
  "TimePeriod": {
    "Start": "${RUN_START_DATE}T00:00:00Z",
    "End": "${RUN_END_EXCLUSIVE}T00:00:00Z"
  },
  "BudgetType": "COST"
}
JSON

cat > "$LOCAL_RUN_DIR/notifications-gross.json" <<JSON
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 17000,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 18300,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 18900,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  }
]
JSON

cat > "$LOCAL_RUN_DIR/notifications-paid.json" <<JSON
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 1,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 25,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "ABSOLUTE_VALUE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [
      {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
    ]
  }
]
JSON

aws budgets create-budget \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --account-id "$EXPECTED_ACCOUNT_ID" \
  --budget "file://$LOCAL_RUN_DIR/budget-gross.json" \
  --notifications-with-subscribers "file://$LOCAL_RUN_DIR/notifications-gross.json" \
  || echo "Budget may already exist. Review and update manually if needed."

aws budgets create-budget \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --account-id "$EXPECTED_ACCOUNT_ID" \
  --budget "file://$LOCAL_RUN_DIR/budget-paid-exposure.json" \
  --notifications-with-subscribers "file://$LOCAL_RUN_DIR/notifications-paid.json" \
  || echo "Budget may already exist. Review and update manually if needed."

aws budgets describe-budgets \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --account-id "$EXPECTED_ACCOUNT_ID" \
  --output json | tee "$LEDGER_DIR/budgets_after_create.json"

append_ledger run_decisions.md "budget guardrails attempted; verify email subscription in console before canary"
```

Manual gate: email subscription confirmationが終わるまでcanaryに進まない。

### B3. S3 artifact bucket baseline

S3は一時artifact置き場。zero billでは最後にbucketごと消す。

```bash
confirm_write_gate "guardrail setup: S3 artifact bucket"

aws s3api create-bucket \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  || echo "Bucket may already exist. Verify ownership and tags."

aws s3api put-public-access-block \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-ownership-controls \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --ownership-controls '{"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]}'

aws s3api put-bucket-encryption \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-tagging \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --tagging "TagSet=[{Key=Project,Value=$PROJECT},{Key=CreditRun,Value=$CREDIT_RUN},{Key=SpendProgram,Value=$SPEND_PROGRAM},{Key=Purpose,Value=evidence-acceleration},{Key=Owner,Value=bookyou},{Key=AutoStop,Value=2026-05-29},{Key=Environment,Value=credit-run}]"

cat > "$LOCAL_RUN_DIR/s3-lifecycle.json" <<'JSON'
{
  "Rules": [
    {
      "ID": "abort-incomplete-multipart",
      "Status": "Enabled",
      "Filter": {},
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 1
      }
    },
    {
      "ID": "expire-temp-prefix",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "temp/"
      },
      "Expiration": {
        "Days": 7
      }
    },
    {
      "ID": "expire-debug-prefix",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "debug/"
      },
      "Expiration": {
        "Days": 3
      }
    }
  ]
}
JSON

aws s3api put-bucket-lifecycle-configuration \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --lifecycle-configuration "file://$LOCAL_RUN_DIR/s3-lifecycle.json"

aws s3api get-public-access-block \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET" | tee "$LEDGER_DIR/s3_public_access_block.json"

append_ledger run_decisions.md "S3 artifact bucket baseline configured: s3://$ARTIFACT_BUCKET"
```

### B4. CloudWatch log retention

ログは成果物ではない。raw HTML/PDF text/CSV rowをstdoutに出さない。

```bash
confirm_write_gate "guardrail setup: CloudWatch log group"

aws logs create-log-group \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --log-group-name "$LOG_GROUP" \
  --tags Project="$PROJECT",CreditRun="$CREDIT_RUN",SpendProgram="$SPEND_PROGRAM",Purpose="evidence-acceleration",Owner="bookyou",AutoStop="2026-05-29",Environment="credit-run" \
  || echo "Log group may already exist."

aws logs put-retention-policy \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --log-group-name "$LOG_GROUP" \
  --retention-in-days 7

aws logs describe-log-groups \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --log-group-name-prefix "$LOG_GROUP" \
  --output json | tee "$LEDGER_DIR/log_group_after_create.json"
```

### B5. Soft brake policy draft

これは貼り付け即attachしない。budget action role / operator role / Organizations scopeが確定してから使う。停止操作までdenyしないよう、新規作成・scale upを中心にする。

```bash
cat > "$LOCAL_RUN_DIR/soft-brake-deny-draft.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNewExpensiveCreditRunWorkloads",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances",
        "ec2:CreateNatGateway",
        "ec2:AllocateAddress",
        "elasticloadbalancing:CreateLoadBalancer",
        "ecs:CreateService",
        "ecs:RunTask",
        "batch:SubmitJob",
        "glue:StartJobRun",
        "glue:StartCrawler",
        "athena:StartQueryExecution",
        "es:CreateElasticsearchDomain",
        "es:CreateDomain",
        "aoss:CreateCollection",
        "lambda:CreateFunction",
        "states:StartExecution",
        "codebuild:StartBuild",
        "textract:StartDocumentTextDetection",
        "textract:StartExpenseAnalysis",
        "bedrock:CreateModelInvocationJob"
      ],
      "Resource": "*"
    }
  ]
}
JSON

echo "Draft only. Do not attach until target role/SCP scope and stop-operation exceptions are reviewed."
```

### B6. Guardrail pass/fail

Guardrail合格条件:

- Budgets作成または既存budget確認済み
- alert email subscription confirmed
- S3 public block/encryption/lifecycle/tagging confirmed
- CloudWatch retention 7 days
- soft brake policy draft reviewed
- stop scripts are ready before canary

## 7. Stage C: canary

Canary予算は `USD 100-300`。ここで成果物契約、タグ、請求、停止操作、privacy scanを確認する。

### C1. Canary manifest contract

Canary jobは次のmanifestを持つ。wrapper未実装なら、このmanifestだけ先にjpcite repoへ作る。

```json
{
  "run_id": "2026-05",
  "profile": "bookyou-recovery",
  "account_id": "993693061769",
  "region": "us-east-1",
  "spend_program": "aws-credit-batch-2026-05",
  "data_class": "public-only-or-synthetic-only",
  "max_expected_gross_usd": 300,
  "jobs": [
    {
      "job_id": "J01-canary",
      "name": "official_source_profile_sweep_canary",
      "accepted_artifacts": ["source_profile_delta.jsonl", "license_boundary_report.md"]
    },
    {
      "job_id": "J03-canary",
      "name": "nta_invoice_no_hit_shape_canary",
      "accepted_artifacts": ["source_receipts.jsonl", "no_hit_checks.jsonl"]
    },
    {
      "job_id": "J12-canary",
      "name": "source_receipt_completeness_canary",
      "accepted_artifacts": ["receipt_completeness_report.md"]
    },
    {
      "job_id": "J15-canary",
      "name": "single_packet_fixture_canary",
      "accepted_artifacts": ["packet_examples/evidence_answer.json"]
    },
    {
      "job_id": "J16-canary",
      "name": "small_forbidden_claim_scan_canary",
      "accepted_artifacts": ["forbidden_claim_scan_report.md"]
    }
  ],
  "forbidden": [
    "raw_private_csv",
    "request_time_llm_call",
    "no_hit_as_absence",
    "approved_or_eligible_claim"
  ]
}
```

### C2. Canary submit gate

Batch queue/job definitionがまだない場合は、この段階で止める。無理に手作業submitしない。

```bash
export BATCH_QUEUE_CANARY="<set-existing-or-created-canary-queue>"
export BATCH_JOB_DEFINITION_CANARY="<set-canary-job-definition>"
require_no_placeholder "$BATCH_QUEUE_CANARY" "BATCH_QUEUE_CANARY"
require_no_placeholder "$BATCH_JOB_DEFINITION_CANARY" "BATCH_JOB_DEFINITION_CANARY"

confirm_write_gate "canary submit"

aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --job-queues "$BATCH_QUEUE_CANARY" \
  --output json | tee "$LEDGER_DIR/canary_queue_before_submit.json"

aws batch describe-job-definitions \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --job-definitions "$BATCH_JOB_DEFINITION_CANARY" \
  --status ACTIVE \
  --output json | tee "$LEDGER_DIR/canary_job_definition.json"

read -r -p "Type EXACTLY 'SUBMIT CANARY ONLY' to submit the canary: " answer
if [[ "$answer" != "SUBMIT CANARY ONLY" ]]; then
  echo "Canary submit rejected."
  exit 94
fi

aws batch submit-job \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --job-name "jpcite-${RUN_ID}-canary" \
  --job-queue "$BATCH_QUEUE_CANARY" \
  --job-definition "$BATCH_JOB_DEFINITION_CANARY" \
  --parameters run_id="$RUN_ID",artifact_bucket="$ARTIFACT_BUCKET",mode="canary",max_expected_gross_usd="300" \
  --tags Project="$PROJECT",CreditRun="$CREDIT_RUN",SpendProgram="$SPEND_PROGRAM",Purpose="evidence-acceleration",Owner="bookyou",AutoStop="2026-05-29",Environment="credit-run" \
  --output json | tee "$LEDGER_DIR/canary_submit_result.json"

append_ledger run_decisions.md "canary submitted"
```

### C3. Canary verify

```bash
aws batch list-jobs \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --job-queue "$BATCH_QUEUE_CANARY" \
  --job-status RUNNING \
  --output json | tee "$LEDGER_DIR/canary_running_jobs.json"

aws s3 ls "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/canary/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive --summarize | tee "$LEDGER_DIR/canary_s3_listing.txt"

aws ce get-cost-and-usage \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --time-period Start="$RUN_START_DATE",End="$RUN_END_EXCLUSIVE" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | tee "$LEDGER_DIR/cost_after_canary.json"
```

Canary pass条件:

- Cost Explorer/Budgetsに想定serviceだけが出る
- `SpendProgram` tagでresource inventoryできる
- S3 output prefixにmanifest/checksumがある
- `source_receipts[]`, `known_gaps[]`, `claim_refs[]` のshapeがP0 contractに合う
- raw private CSVがない
- request-time LLM callがない
- no-hit誤用がない
- forbidden claimがない
- stop drillをcanary後にも実行できる

## 8. Stage D: scale

Scaleは「creditを使う」ではなく「accepted artifact countを増やす」ために行う。

### D1. Scale order

1. J01 official source profile sweep
2. J02 NTA法人番号 mirror/diff
3. J03 NTA invoice registrants/no-hit
4. J04 e-Gov law snapshot
5. J05 J-Grants/public program acquisition
6. J07 gBizINFO join
7. J08 EDINET metadata
8. J09 procurement/tender acquisition
9. J10 enforcement/public notice sweep
10. J11 e-Stat enrichment
11. J12 source receipt completeness audit
12. J13 claim graph dedupe/conflict analysis
13. J14 CSV synthetic/privacy safety analysis
14. J15 packet/proof fixture materialization
15. J16 GEO/no-hit/forbidden-claim eval
16. J06 ministry/local PDF extraction only after receipt lanes show yield

OCR, Bedrock batch, OpenSearchはstandard scaleではなくstretch候補として扱う。

### D2. Hourly scale ledger

```bash
cat <<'EOF' | tee -a "$LEDGER_DIR/hourly_scale_ledger.md"
| Time JST | control_spend | CE gross | paid exposure | untagged | top service | running exposure | accepted artifacts | failure rate | decision |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|
EOF
```

### D3. Scale-up command template

このtemplateは、manifestとqueue capが確定したjobだけに使う。placeholderが残る場合は停止する。

```bash
export BATCH_QUEUE_STANDARD="<set-standard-queue>"
export BATCH_JOB_DEFINITION_STANDARD="<set-standard-job-definition>"
export AWS_CREDIT_JOB_ID="<J01-J16>"
export AWS_CREDIT_JOB_MANIFEST_S3="s3://$ARTIFACT_BUCKET/runs/$RUN_ID/manifests/<job-manifest>.json"
export AWS_CREDIT_JOB_MAX_GROSS_USD="<set-number>"

require_no_placeholder "$BATCH_QUEUE_STANDARD" "BATCH_QUEUE_STANDARD"
require_no_placeholder "$BATCH_JOB_DEFINITION_STANDARD" "BATCH_JOB_DEFINITION_STANDARD"
require_no_placeholder "$AWS_CREDIT_JOB_ID" "AWS_CREDIT_JOB_ID"
require_no_placeholder "$AWS_CREDIT_JOB_MANIFEST_S3" "AWS_CREDIT_JOB_MANIFEST_S3"
require_no_placeholder "$AWS_CREDIT_JOB_MAX_GROSS_USD" "AWS_CREDIT_JOB_MAX_GROSS_USD"

confirm_write_gate "scale submit $AWS_CREDIT_JOB_ID"

aws batch submit-job \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --job-name "jpcite-${RUN_ID}-${AWS_CREDIT_JOB_ID}" \
  --job-queue "$BATCH_QUEUE_STANDARD" \
  --job-definition "$BATCH_JOB_DEFINITION_STANDARD" \
  --parameters run_id="$RUN_ID",artifact_bucket="$ARTIFACT_BUCKET",manifest_s3="$AWS_CREDIT_JOB_MANIFEST_S3",max_expected_gross_usd="$AWS_CREDIT_JOB_MAX_GROSS_USD" \
  --tags Project="$PROJECT",CreditRun="$CREDIT_RUN",SpendProgram="$SPEND_PROGRAM",Purpose="evidence-acceleration",Owner="bookyou",AutoStop="2026-05-29",Environment="credit-run",Job="$AWS_CREDIT_JOB_ID" \
  --output json | tee "$LEDGER_DIR/submit_${AWS_CREDIT_JOB_ID}_$(date -u +%Y%m%dT%H%M%SZ).json"
```

### D4. Scale continue/stop checks

Scale継続条件:

- accepted artifact countが増えている
- failure rate < 10%
- retry rate < 15%
- no private leak
- no forbidden claim
- no no-hit misuse
- no paid exposure beyond accepted explanation
- no untagged spend beyond tag activation lag explanation
- no NAT/data transfer drift
- no unexpected service above USD 25 without explanation
- operator can stop within 30 minutes

Scale停止条件:

- accepted artifact countが2時間増えない
- review backlogだけが増える
- parse failuresが主要成果物より多い
- raw/debug/log費用が増える
- Athena scanがParquet/partition設計外に広がる
- OpenSearch/Textract/Bedrockが承認前に出る

## 9. Stage E: slowdown

Slowdownは `USD 18,300` またはそれ以前のartifact yield低下で開始する。

```bash
confirm_stop_gate "slowdown: reduce new work"

aws ce get-cost-and-usage \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --time-period Start="$RUN_START_DATE",End="$RUN_END_EXCLUSIVE" \
  --granularity DAILY \
  --metrics UnblendedCost AmortizedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | tee "$LEDGER_DIR/cost_at_slowdown.json"

aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_queues_at_slowdown.json"
```

Slowdownで止めるもの:

- J17 OCR expansion
- J18 Bedrock batch classification
- J19 OpenSearch benchmark
- broad join jobs
- large Athena exploratory queries
- load tests
- proof page scale generation if leak scan is not clean
- any job without accepted-artifact definition

Slowdown後に許容されるもの:

- near-complete source receipt output finalize
- known gaps/no-hit ledgers finalize
- packet/proof fixture completion
- GEO/forbidden-claim report completion
- checksum/export preparation

## 10. Stage F: stop

Stopは、No-new-work、absolute safety、paid exposure、private leak、forbidden claim、operator不在などで即時実行する。

### F1. Disable Batch queues

```bash
confirm_stop_gate "disable batch queues"

aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_queues_before_disable.json"

# Replace with the actual queue names after reviewing batch_queues_before_disable.json.
export BATCH_QUEUES_TO_DISABLE="<queue-1> <queue-2>"
require_no_placeholder "$BATCH_QUEUES_TO_DISABLE" "BATCH_QUEUES_TO_DISABLE"

for q in $BATCH_QUEUES_TO_DISABLE; do
  aws batch update-job-queue \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --job-queue "$q" \
    --state DISABLED
done

append_ledger run_decisions.md "batch queues disabled: $BATCH_QUEUES_TO_DISABLE"
```

### F2. Cancel/terminate queued and running Batch jobs

`terminate-job` はdry-runがないため、必ずqueue inventoryを確認してから実行する。

```bash
confirm_stop_gate "cancel and terminate batch jobs"

for q in $BATCH_QUEUES_TO_DISABLE; do
  for status in SUBMITTED PENDING RUNNABLE STARTING RUNNING; do
    aws batch list-jobs \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION" \
      --job-queue "$q" \
      --job-status "$status" \
      --output json | tee "$LEDGER_DIR/jobs_${q}_${status}_before_stop.json"
  done
done

read -r -p "Type EXACTLY 'TERMINATE LISTED BATCH JOBS' to terminate jobs in listed queues: " answer
if [[ "$answer" != "TERMINATE LISTED BATCH JOBS" ]]; then
  echo "Batch termination rejected."
  exit 95
fi

for q in $BATCH_QUEUES_TO_DISABLE; do
  for status in SUBMITTED PENDING RUNNABLE STARTING RUNNING; do
    aws batch list-jobs \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION" \
      --job-queue "$q" \
      --job-status "$status" \
      --query 'jobSummaryList[].jobId' \
      --output text | tr '\t' '\n' | while read -r job_id; do
        [[ -z "$job_id" || "$job_id" == "None" ]] && continue
        aws batch terminate-job \
          --profile "$AWS_PROFILE" \
          --region "$AWS_REGION" \
          --job-id "$job_id" \
          --reason "jpcite credit run stop gate reached"
      done
  done
done

append_ledger run_decisions.md "batch jobs termination attempted"
```

### F3. Stop non-Batch managed services

Inventory first, then stop only resources tagged for this run.

```bash
confirm_stop_gate "inventory non-batch services before stop"

aws resourcegroupstaggingapi get-resources \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --tag-filters "Key=SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/tagged_resources_before_stop.json"

aws ecs list-clusters \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/ecs_clusters_before_stop.json"

aws ec2 describe-instances \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --filters "Name=tag:SpendProgram,Values=$SPEND_PROGRAM" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --output json | tee "$LEDGER_DIR/ec2_credit_run_before_stop.json"

aws opensearch list-domain-names \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/opensearch_before_stop.json"

aws stepfunctions list-executions \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --state-machine-arn "<only-if-state-machine-exists>" \
  --status-filter RUNNING \
  --output json || echo "No state machine checked or placeholder not set."
```

For EC2 termination, use dry-run first:

```bash
export EC2_INSTANCE_IDS_TO_TERMINATE="<i-... i-...>"
require_no_placeholder "$EC2_INSTANCE_IDS_TO_TERMINATE" "EC2_INSTANCE_IDS_TO_TERMINATE"

aws ec2 terminate-instances \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --instance-ids $EC2_INSTANCE_IDS_TO_TERMINATE \
  --dry-run || true

read -r -p "Type EXACTLY 'TERMINATE CREDIT RUN EC2' to terminate the dry-run checked instances: " answer
if [[ "$answer" != "TERMINATE CREDIT RUN EC2" ]]; then
  echo "EC2 termination rejected."
  exit 96
fi

aws ec2 terminate-instances \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --instance-ids $EC2_INSTANCE_IDS_TO_TERMINATE
```

## 11. Stage G: export

Exportは削除の前に行う。zero billにするには、S3の最終成果物もAWS外へ退避してchecksum検証後に削除する。

### G1. Export manifest

```bash
mkdir -p "$EXPORT_DIR"

aws s3 ls "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive --summarize | tee "$LEDGER_DIR/final_s3_listing_before_export.txt"

aws s3 sync "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/" "$EXPORT_DIR/runs/$RUN_ID/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --only-show-errors

find "$EXPORT_DIR/runs/$RUN_ID" -type f -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  | tee "$LEDGER_DIR/exported_artifacts_sha256.txt"

find "$EXPORT_DIR/runs/$RUN_ID" -type f \
  | sort \
  | tee "$LEDGER_DIR/exported_artifacts_file_manifest.txt"

append_ledger run_decisions.md "artifacts exported to $EXPORT_DIR/runs/$RUN_ID"
```

### G2. Required exported files

Exportが完了したと言える最低条件:

- `source_profile_delta.jsonl` or equivalent
- `source_document_manifest.parquet` or equivalent manifest
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `known_gaps.jsonl`
- `no_hit_checks.jsonl`
- `freshness_report.md`
- `license_boundary_report.md`
- `packet_examples/*.json`
- `proof_pages/**` or proof sidecar ledgers
- `geo_eval_*.md/json`
- `forbidden_claim_scan_report.md`
- `csv_fixture_privacy_report.md`
- `billing_metadata` / cost ledger
- `cleanup_ledger`
- checksum manifest

### G3. Repo import staging

この段階ではAWSではなくlocal/repoへの反映準備。AWS成果物をpublic化する前に、privacy/claim reviewを通す。

```bash
cat <<EOF | tee "$LEDGER_DIR/repo_import_plan.md"
# Repo import plan

Source export dir: $EXPORT_DIR/runs/$RUN_ID

Candidate repo paths:
- data/source_profile_registry.jsonl
- data/packet_examples/*.json
- docs/_internal/aws_credit_run_ledger_2026-05.md
- docs/_internal/source_receipt_coverage_report_2026-05.md
- docs/_internal/geo_eval_aws_credit_run_2026-05.md
- docs/_internal/aws_cleanup_zero_bill_report_2026-05.md

Required gates before public release:
- privacy leak scan
- forbidden claim scan
- no-hit wording scan
- source receipt completeness check
- billing metadata check
- request_time_llm_call_performed=false check
EOF
```

## 12. Stage H: teardown

Teardownは破壊的操作。必ずexportとchecksum確認後に実行する。削除対象はタグ、bucket名、ledgerで特定した今回runのresourceに限定する。

### H1. Dry-run inventory

```bash
confirm_teardown_gate

aws resourcegroupstaggingapi get-resources \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --tag-filters "Key=SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/tagged_resources_before_teardown.json"

aws s3 ls "s3://$ARTIFACT_BUCKET/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive --summarize | tee "$LEDGER_DIR/s3_before_teardown.txt"

aws s3 rm "s3://$ARTIFACT_BUCKET/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive \
  --dryrun | tee "$LEDGER_DIR/s3_delete_dryrun.txt"
```

### H2. Delete high-risk running/capacity resources

実行前に個別resource idをledgerから人間が確認する。

```bash
# Batch queues must already be disabled and jobs terminated.
aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_queues_before_delete.json"

aws batch describe-compute-environments \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/batch_compute_envs_before_delete.json"

export BATCH_COMPUTE_ENVS_TO_DELETE="<compute-env-1> <compute-env-2>"
export BATCH_QUEUES_TO_DELETE="<queue-1> <queue-2>"
require_no_placeholder "$BATCH_COMPUTE_ENVS_TO_DELETE" "BATCH_COMPUTE_ENVS_TO_DELETE"
require_no_placeholder "$BATCH_QUEUES_TO_DELETE" "BATCH_QUEUES_TO_DELETE"

read -r -p "Type EXACTLY 'DELETE BATCH CREDIT RUN RESOURCES' to delete listed Batch resources: " answer
if [[ "$answer" != "DELETE BATCH CREDIT RUN RESOURCES" ]]; then
  echo "Batch delete rejected."
  exit 97
fi

for ce in $BATCH_COMPUTE_ENVS_TO_DELETE; do
  aws batch update-compute-environment \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --compute-environment "$ce" \
    --state DISABLED || true
done

for q in $BATCH_QUEUES_TO_DELETE; do
  aws batch delete-job-queue \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --job-queue "$q" || true
done

for ce in $BATCH_COMPUTE_ENVS_TO_DELETE; do
  aws batch delete-compute-environment \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --compute-environment "$ce" || true
done
```

OpenSearch, NAT Gateway, EIPは高リスク。もし作っていなければ「なし」とledgerに書く。作っていたら、個別idを確認して削除する。

```bash
aws opensearch list-domain-names \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/opensearch_before_delete.json"

aws ec2 describe-nat-gateways \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --filter "Name=tag:SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/nat_gateways_before_delete.json"

aws ec2 describe-addresses \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --filters "Name=tag:SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/eip_before_release.json"
```

### H3. Delete storage derivatives

```bash
aws ecr describe-repositories \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/ecr_before_delete.json"

export ECR_REPOS_TO_DELETE="<repo-1> <repo-2>"
require_no_placeholder "$ECR_REPOS_TO_DELETE" "ECR_REPOS_TO_DELETE"

read -r -p "Type EXACTLY 'DELETE ECR CREDIT RUN REPOS' to delete listed ECR repositories: " answer
if [[ "$answer" != "DELETE ECR CREDIT RUN REPOS" ]]; then
  echo "ECR delete rejected."
  exit 98
fi

for repo in $ECR_REPOS_TO_DELETE; do
  aws ecr delete-repository \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --repository-name "$repo" \
    --force || true
done

aws ec2 describe-volumes \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --filters "Name=tag:SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/ebs_volumes_before_delete.json"

aws ec2 describe-snapshots \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --owner-ids self \
  --filters "Name=tag:SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/snapshots_before_delete.json"
```

### H4. Delete Glue/Athena/CloudWatch artifacts

```bash
aws glue get-databases \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/glue_before_delete.json"

aws athena list-work-groups \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/athena_before_delete.json"

aws logs describe-log-groups \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --log-group-name-prefix "$LOG_GROUP" \
  --output json | tee "$LEDGER_DIR/log_groups_before_delete.json"

read -r -p "Type EXACTLY 'DELETE CLOUDWATCH CREDIT RUN LOGS' to delete $LOG_GROUP: " answer
if [[ "$answer" == "DELETE CLOUDWATCH CREDIT RUN LOGS" ]]; then
  aws logs delete-log-group \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --log-group-name "$LOG_GROUP" || true
else
  echo "CloudWatch log deletion skipped. This is not zero-bill-complete until reviewed."
fi
```

### H5. Delete S3 bucket

Zero ongoing billを目指す場合、S3 bucketも削除する。まずdry-run、次に確認、最後に削除。

```bash
aws s3 rm "s3://$ARTIFACT_BUCKET/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive \
  --dryrun | tee "$LEDGER_DIR/s3_final_delete_dryrun.txt"

read -r -p "Type EXACTLY 'DELETE S3 ARTIFACT BUCKET AFTER EXPORT VERIFIED' to empty and delete $ARTIFACT_BUCKET: " answer
if [[ "$answer" != "DELETE S3 ARTIFACT BUCKET AFTER EXPORT VERIFIED" ]]; then
  echo "S3 delete rejected."
  exit 99
fi

aws s3 rm "s3://$ARTIFACT_BUCKET/" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --recursive \
  --only-show-errors

aws s3api delete-bucket \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --bucket "$ARTIFACT_BUCKET"

append_ledger cleanup_ledger.md "S3 artifact bucket deleted: $ARTIFACT_BUCKET"
```

### H6. Final zero-bill inventory

```bash
aws resourcegroupstaggingapi get-resources \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --tag-filters "Key=SpendProgram,Values=$SPEND_PROGRAM" \
  --output json | tee "$LEDGER_DIR/tagged_resources_after_teardown.json"

aws ce get-cost-and-usage \
  --profile "$AWS_PROFILE" \
  --region "$BILLING_REGION" \
  --time-period Start="$RUN_START_DATE",End="$RUN_END_EXCLUSIVE" \
  --granularity DAILY \
  --metrics UnblendedCost AmortizedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | tee "$LEDGER_DIR/cost_after_teardown.json"

cat <<EOF | tee "$LEDGER_DIR/zero_bill_teardown_report.md"
# Zero bill teardown report

Run ID: $RUN_ID
Account: $EXPECTED_ACCOUNT_ID
Region: $AWS_REGION
Artifact export dir: $EXPORT_DIR/runs/$RUN_ID
S3 artifact bucket deleted:
Batch queues deleted:
Batch compute envs deleted:
ECR repos deleted:
EC2 instances terminated:
EBS volumes/snapshots deleted:
OpenSearch deleted:
Glue/Athena deleted:
CloudWatch logs deleted:
NAT/EIP deleted or confirmed absent:
Tagged resources remaining:
Cost Explorer checked:
Follow-up checks required: next day, 3 days later, month close
EOF
```

## 13. Stage I: postmortem

Postmortemは、AWSを止めた後にjpcite側へ取り込むための整理。ここでもAWS new workは禁止。

```bash
cat <<EOF | tee "$LEDGER_DIR/postmortem.md"
# jpcite AWS credit run postmortem

Date:
Account: $EXPECTED_ACCOUNT_ID
Region: $AWS_REGION
Credit face value: USD 19,493.94
Intentional safety line: USD 19,300

## Spend

- Final Cost Explorer gross:
- Paid exposure:
- Untagged spend:
- Unexpected services:
- Stopline reached:

## Artifacts

- source_profile candidates:
- source_receipts:
- claim_refs:
- known_gaps:
- no_hit ledgers:
- packet examples:
- proof pages:
- GEO evals:
- CSV privacy fixtures:
- OpenAPI/MCP/discovery artifacts:

## Quality gates

- privacy leak scan:
- forbidden claim scan:
- no-hit wording scan:
- source receipt completeness:
- request_time_llm_call_performed=false:
- billing metadata:

## Cleanup

- S3 deleted:
- ECR deleted:
- Batch/ECS/EC2 deleted:
- OpenSearch deleted:
- Glue/Athena deleted:
- CloudWatch deleted:
- NAT/EIP absent:
- Follow-up billing checks:

## jpcite next actions

1. Import accepted source profiles.
2. Import source receipt/claim/gap fixtures.
3. Update P0 packet examples.
4. Update proof/discovery pages after privacy and claim review.
5. Update GEO eval report.
6. Update release gate evidence.
EOF
```

## 14. Emergency shortcuts

Operatorが30分以内に止められない状況になったら、scale判断ではなくstopを優先する。

Minimum emergency sequence:

```bash
confirm_stop_gate "minimum emergency stop"

aws batch describe-job-queues \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --output json | tee "$LEDGER_DIR/emergency_batch_queues.json"

echo "Manually set BATCH_QUEUES_TO_DISABLE from emergency_batch_queues.json, then run F1 and F2."
echo "After Batch is stopped, inventory tagged resources and stop EC2/OpenSearch/NAT/EIP if present."
```

If a private leak or forbidden claim appears:

1. Disable public/proof/static generation queues.
2. Stop all jobs that read the affected prefix.
3. Move affected S3 prefix to quarantine if needed.
4. Do not publish.
5. Record source, job id, artifact path, and leak class.
6. Only resume after a new manifest excludes the affected input.

If paid exposure appears:

1. Stop new work immediately.
2. Check service, region, usage type, and credit eligibility.
3. If paid exposure >= USD 25, enter no-new-work behavior.
4. If paid exposure >= USD 100, emergency stop and teardown after export.

## 15. Final operator checklist

Before canary:

- [ ] AWS account is `993693061769`.
- [ ] Profile is `bookyou-recovery`.
- [ ] Region is `us-east-1`.
- [ ] Credit balance and expiry are manually confirmed.
- [ ] Budgets and alerts are created or reviewed.
- [ ] Email subscription is confirmed.
- [ ] S3 bucket has public block, encryption, lifecycle, tags.
- [ ] CloudWatch retention is 7 days.
- [ ] Stop commands are ready.
- [ ] P0 output contract is fixed.
- [ ] No raw private CSV will go to AWS.
- [ ] No request-time LLM calls will be made.

Before scale:

- [ ] Canary cost is within USD 100-300.
- [ ] Canary artifacts match contract.
- [ ] No private leak.
- [ ] No forbidden claim.
- [ ] No no-hit misuse.
- [ ] Cost Explorer/Budgets/resource inventory are visible.
- [ ] Stop drill succeeded.

Before stretch:

- [ ] Gross spend is below `USD 18,900`.
- [ ] Paid exposure is clean.
- [ ] Untagged spend is explained.
- [ ] Artifact yield is strong.
- [ ] Stretch job has max exposure, timeout, stop path, and accepted artifacts.
- [ ] Manual approval text is recorded.

Before teardown:

- [ ] No-new-work is active.
- [ ] Queues are disabled.
- [ ] Running jobs are terminated or explicitly allowed to finish.
- [ ] Artifacts are exported.
- [ ] Checksums are verified.
- [ ] Repo import plan exists.
- [ ] Deletion target lists are reviewed.

Zero-bill done:

- [ ] S3 bucket deleted, or explicitly marked as non-zero-bill Minimal AWS Archive.
- [ ] ECR deleted.
- [ ] Batch/ECS/EC2/ASG deleted.
- [ ] EBS volumes/snapshots/AMIs deleted.
- [ ] OpenSearch deleted.
- [ ] Glue/Athena cleaned.
- [ ] CloudWatch logs/alarms/dashboards cleaned.
- [ ] NAT Gateway/EIP/ENI absent.
- [ ] Tagged resource inventory empty.
- [ ] Next-day, 3-day, and month-close billing checks scheduled.
