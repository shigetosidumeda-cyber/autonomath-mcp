# jpcite AWS credit CLI runbook agent

Date: 2026-05-15  
Operator credit balance: USD 19,493.94  
Target window: 1-2 weeks  
Scope: structure review and pasteable instructions for a separate AWS CLI operator  
Status: Markdown-only handoff. This document does not execute AWS commands.

## 0. Operating intent

Use the AWS credit for short-lived jpcite data/evidence acceleration work, not for permanent infrastructure. The practical target is **USD 18,300-18,700** of eligible usage, with **USD 800-1,200** left as a buffer for billing lag, non-credit-eligible spend, cleanup delay, taxes, support, and accidental small residual charges.

Treat **USD 18,900 actual or forecasted account spend** as the stop line. Do not try to consume the full USD 19,493.94.

The AWS CLI operator must create guardrails first, run only tagged short-lived resources, keep hourly spend reports, and be able to stop all new work within minutes.

## 1. Paste this instruction to the AWS CLI operator

```text
You are the AWS CLI operator for the jpcite credit run. Do not run workload jobs until the read-only audit, budgets, bucket setup, and stop commands are confirmed. Use only ap-northeast-1 for workload resources unless a service requires us-east-1 for billing/control APIs. Every created resource must be tagged Project=jpcite, CreditRun=2026-05, Purpose=evidence-acceleration, Owner=bookyou, Environment=credit-run, AutoStop=2026-05-29.

Your deliverables are:
1. safe first command output
2. pre-run audit output
3. budgets and alert confirmation
4. encrypted private S3 buckets
5. capped AWS Batch queues
6. tested stop scripts
7. hourly spend/status reports
8. final cost/resource ledger

Hard stop: if Cost Explorer actual+forecast approaches USD 18,900, or if untagged spend appears, disable queues, cancel pending jobs, terminate running jobs, and report.
```

## 2. Execution phases

| Phase | Goal | Allowed commands | Exit gate |
|---|---|---|---|
| Pre-run | Confirm identity, region, credits, billing access, and existing spend | read-only plus budget setup | budgets exist and alert email confirmed |
| Guardrail setup | Create private buckets, logs, and capped queues | S3, Budgets, Batch create/update | buckets private, queues capped, stop script tested on empty queues |
| Running | Submit workload jobs from the workload owner only after smoke test | Batch submit/list/describe, S3 write, Cost Explorer reports | hourly ledger remains below stop line |
| Stop | Stop new work and drain/terminate running work | Batch disable/cancel/terminate, service-specific stop commands | no RUNNING/RUNNABLE jpcite jobs |
| Post-run | Export reports, preserve artifacts, delete transient resources | reports, final audit, cleanup | final ledger and artifact manifest written |

## 3. Pre-run: safe first commands

These commands should be pasted first. They should not create spend-heavy resources.

```bash
set -euo pipefail

export AWS_PAGER=""
export REGION="ap-northeast-1"
export BILLING_REGION="us-east-1"
export RUN_ID="2026-05"
export RUN_ID_COMPACT="202605"
export PROJECT="jpcite"
export CREDIT_RUN="2026-05"
export OWNER="bookyou"
export ALERT_EMAIL="info@bookyou.net"

aws sts get-caller-identity
aws configure list
aws --version

export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "ACCOUNT_ID=${ACCOUNT_ID}"
echo "REGION=${REGION}"
echo "BILLING_REGION=${BILLING_REGION}"
```

Manual console check before continuing:

- Billing and Cost Management -> Credits: confirm credit amount, expiry, eligible services, and account scope.
- Billing and Cost Management -> Cost allocation tags: confirm whether `Project`, `CreditRun`, `Purpose`, `Owner`, `Environment`, and `AutoStop` are active or can be activated.
- IAM: confirm the CLI principal can read Cost Explorer and create Budgets.
- AWS Organizations: if this is a member account, confirm whether Budgets/SCP actions must be run from the management account.

Go/no-go rule: if credit scope or billing access is unclear, stop here.

## 4. Pre-run: audit commands

Run these before any resource creation.

```bash
aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

aws ce get-cost-forecast \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u -v+1d +%Y-%m-%d)",End="$(date -u -v+15d +%Y-%m-%d)" \
  --metric UNBLENDED_COST \
  --granularity DAILY

aws budgets describe-budgets \
  --region "$BILLING_REGION" \
  --account-id "$ACCOUNT_ID" || true

aws resourcegroupstaggingapi get-resources \
  --region "$REGION" \
  --tag-filters Key=Project,Values=jpcite Key=CreditRun,Values=2026-05 \
  --query 'ResourceTagMappingList[].ResourceARN' \
  --output text || true
```

If the Cost Explorer commands are denied, fix IAM before continuing. If existing untagged high-cost services appear, identify them before starting the credit run.

## 5. Pre-run: budgets

Create three account-level budgets. Account-level budgets are intentional: they catch tag misses and delayed charges better than tag-scoped budgets. Use tag-filtered Cost Explorer reports separately for run attribution.

```bash
cat > /tmp/jpcite-budget-subscribers.json <<EOF
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}" }
    ]
  },
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}" }
    ]
  }
]
EOF

for NAME_AMOUNT in \
  "jpcite-credit-run-watch-17000 17000" \
  "jpcite-credit-run-slowdown-18300 18300" \
  "jpcite-credit-run-stop-18900 18900"
do
  set -- $NAME_AMOUNT
  BUDGET_NAME="$1"
  BUDGET_AMOUNT="$2"

  cat > "/tmp/${BUDGET_NAME}.json" <<EOF
{
  "BudgetName": "${BUDGET_NAME}",
  "BudgetLimit": { "Amount": "${BUDGET_AMOUNT}", "Unit": "USD" },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
EOF

  aws budgets create-budget \
    --region "$BILLING_REGION" \
    --account-id "$ACCOUNT_ID" \
    --budget "file:///tmp/${BUDGET_NAME}.json" \
    --notifications-with-subscribers "file:///tmp/jpcite-budget-subscribers.json"
done

aws budgets describe-budgets \
  --region "$BILLING_REGION" \
  --account-id "$ACCOUNT_ID" \
  --query 'Budgets[?starts_with(BudgetName, `jpcite-credit-run`)].{Name:BudgetName,Limit:BudgetLimit.Amount,Unit:BudgetLimit.Unit,Type:BudgetType}'
```

Optional strong stop: create a Budgets Action only after the operator confirms the execution role and target IAM role. Use `MANUAL` approval first so it does not unexpectedly attach a deny policy.

```bash
# Placeholder only. Fill these after IAM review.
export BUDGET_ACTION_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/<budget-action-execution-role>"
export TARGET_OPERATOR_ROLE_NAME="<role-to-restrict-on-stop>"
export DENY_POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/jpcite-credit-run-deny-new-spend"

aws budgets create-budget-action \
  --region "$BILLING_REGION" \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-run-stop-18900" \
  --notification-type ACTUAL \
  --action-type APPLY_IAM_POLICY \
  --action-threshold ActionThresholdValue=100,ActionThresholdType=PERCENTAGE \
  --definition "IamActionDefinition={PolicyArn=${DENY_POLICY_ARN},Roles=[${TARGET_OPERATOR_ROLE_NAME}]}" \
  --execution-role-arn "$BUDGET_ACTION_ROLE_ARN" \
  --approval-model MANUAL \
  --subscribers SubscriptionType=EMAIL,Address="$ALERT_EMAIL"
```

## 6. Guardrail setup: create buckets

Use S3 for durable artifacts and logs. Buckets must be private, encrypted, tagged, versioned where useful, and lifecycle-managed.

```bash
export RAW_BUCKET="jpcite-credit-${ACCOUNT_ID}-${RUN_ID_COMPACT}-raw"
export DERIVED_BUCKET="jpcite-credit-${ACCOUNT_ID}-${RUN_ID_COMPACT}-derived"
export REPORTS_BUCKET="jpcite-credit-${ACCOUNT_ID}-${RUN_ID_COMPACT}-reports"

for B in "$RAW_BUCKET" "$DERIVED_BUCKET" "$REPORTS_BUCKET"; do
  aws s3api create-bucket \
    --region "$REGION" \
    --bucket "$B" \
    --create-bucket-configuration LocationConstraint="$REGION"

  aws s3api put-public-access-block \
    --bucket "$B" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

  aws s3api put-bucket-encryption \
    --bucket "$B" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

  aws s3api put-bucket-versioning \
    --bucket "$B" \
    --versioning-configuration Status=Enabled

  aws s3api put-bucket-tagging \
    --bucket "$B" \
    --tagging "TagSet=[{Key=Project,Value=${PROJECT}},{Key=CreditRun,Value=${CREDIT_RUN}},{Key=Purpose,Value=evidence-acceleration},{Key=Owner,Value=${OWNER}},{Key=Environment,Value=credit-run},{Key=AutoStop,Value=2026-05-29}]"

  cat > "/tmp/${B}-lifecycle.json" <<EOF
{
  "Rules": [
    {
      "ID": "abort-incomplete-multipart-uploads",
      "Status": "Enabled",
      "Filter": {},
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 3 }
    },
    {
      "ID": "expire-noncurrent-versions-after-30-days",
      "Status": "Enabled",
      "Filter": {},
      "NoncurrentVersionExpiration": { "NoncurrentDays": 30 }
    }
  ]
}
EOF

  aws s3api put-bucket-lifecycle-configuration \
    --bucket "$B" \
    --lifecycle-configuration "file:///tmp/${B}-lifecycle.json"
done

aws s3api list-buckets \
  --query "Buckets[?starts_with(Name, 'jpcite-credit-${ACCOUNT_ID}-${RUN_ID_COMPACT}')].Name"
```

Bucket use:

| Bucket | Contents | Retention posture |
|---|---|---|
| raw | official source payloads, checksums, fetch metadata | preserve until final review |
| derived | JSONL, Parquet, source receipt candidates, proof artifacts | preserve useful outputs |
| reports | cost reports, Batch status, manifests, final ledger | preserve as audit trail |

Do not make any bucket public. Published outputs should be copied to the existing public distribution path only after separate privacy and claim review.

## 7. Guardrail setup: create Batch queues

Use AWS Batch managed Fargate Spot compute environments for interruptible work so there are no EC2 instances or Auto Scaling groups to clean up. The workload owner may later register job definitions and submit jobs, but this runbook only creates capped queues.

Required operator inputs:

```bash
export BATCH_SUBNET_IDS="subnet-aaa,subnet-bbb"
export BATCH_SECURITY_GROUP_IDS="sg-aaa"
export BATCH_SUBNET_IDS_JSON='["subnet-aaa","subnet-bbb"]'
export BATCH_SECURITY_GROUP_IDS_JSON='["sg-aaa"]'
```

Confirm the subnets are private enough for the workload and that egress paths will not create runaway NAT Gateway spend. If NAT Gateways are involved, include NAT hourly and data processing costs in the hourly report.

Create capped compute environments and queues:

```bash
create_batch_queue() {
  local name="$1"
  local max_vcpus="$2"
  local priority="$3"
  local ce_name="${name}-ce"

  cat > "/tmp/${ce_name}-compute-resources.json" <<EOF
{
  "type": "FARGATE_SPOT",
  "maxvCpus": ${max_vcpus},
  "subnets": ${BATCH_SUBNET_IDS_JSON},
  "securityGroupIds": ${BATCH_SECURITY_GROUP_IDS_JSON}
}
EOF

  aws batch create-compute-environment \
    --region "$REGION" \
    --compute-environment-name "$ce_name" \
    --type MANAGED \
    --state ENABLED \
    --compute-resources "file:///tmp/${ce_name}-compute-resources.json" \
    --tags Project="$PROJECT",CreditRun="$CREDIT_RUN",Purpose=evidence-acceleration,Owner="$OWNER",Environment=credit-run,AutoStop=2026-05-29

  aws batch create-job-queue \
    --region "$REGION" \
    --job-queue-name "$name" \
    --state ENABLED \
    --priority "$priority" \
    --compute-environment-order "order=1,computeEnvironment=${ce_name}" \
    --tags Project="$PROJECT",CreditRun="$CREDIT_RUN",Purpose=evidence-acceleration,Owner="$OWNER",Environment=credit-run,AutoStop=2026-05-29
}

create_batch_queue "jpcite-source-crawl" 64 60
create_batch_queue "jpcite-pdf-parse" 96 50
create_batch_queue "jpcite-parquet-build" 48 40
create_batch_queue "jpcite-packet-precompute" 64 30
create_batch_queue "jpcite-geo-eval" 32 20
create_batch_queue "jpcite-load-test" 16 10

aws batch describe-job-queues \
  --region "$REGION" \
  --job-queues jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test \
  --query 'jobQueues[].{name:jobQueueName,state:state,status:status,priority:priority,computeEnvironmentOrder:computeEnvironmentOrder}'

aws batch describe-compute-environments \
  --region "$REGION" \
  --compute-environments jpcite-source-crawl-ce jpcite-pdf-parse-ce jpcite-parquet-build-ce jpcite-packet-precompute-ce jpcite-geo-eval-ce jpcite-load-test-ce \
  --query 'computeEnvironments[].{name:computeEnvironmentName,state:state,status:status,type:computeResources.type,maxvCpus:computeResources.maxvCpus}'
```

Initial caps are deliberately conservative. Raise caps only after Cost Explorer shows the expected service mix and the USD 100-300 smoke test is reviewed.

Queue ownership:

| Queue | Purpose | Initial cap | Stop priority |
|---|---|---:|---|
| jpcite-source-crawl | official source mirroring and checksums | 64 vCPU | stop after current small batches |
| jpcite-pdf-parse | CPU/OCR PDF extraction candidate generation | 96 vCPU | stop early if OCR service cost spikes |
| jpcite-parquet-build | JSONL/Parquet normalization and compaction | 48 vCPU | safe to resume later |
| jpcite-packet-precompute | proof pages and packet examples | 64 vCPU | stop after artifact checkpoint |
| jpcite-geo-eval | GEO/OpenAPI/MCP evals | 32 vCPU | stop anytime |
| jpcite-load-test | bounded load tests | 16 vCPU | stop first on any anomaly |

## 8. Running: smoke test gate

Before scaling, the workload owner may submit a tiny known-safe job to one queue. The CLI operator should not submit production workload payloads without the workload owner. After the smoke job:

```bash
aws batch describe-job-queues \
  --region "$REGION" \
  --job-queues jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test \
  --query 'jobQueues[].{name:jobQueueName,state:state,status:status}'

aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE Type=TAG,Key=CreditRun
```

Go/no-go rule after smoke:

- Continue only if spend appears in the expected services and tags.
- Pause if spend appears as untagged, EC2-Other, NAT Gateway, Marketplace, Support, or a service outside the run plan.
- Pause if forecast exceeds USD 18,300 before the main run is even started.

## 9. Running: hourly audit commands

Run this block hourly while jobs are active and after every scale-up.

```bash
echo "===== COST BY SERVICE ====="
aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

echo "===== COST BY CREDITRUN TAG ====="
aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --filter '{"Tags":{"Key":"CreditRun","Values":["2026-05"],"MatchOptions":["EQUALS"]}}' \
  --group-by Type=DIMENSION,Key=SERVICE

echo "===== 15-DAY FORECAST ====="
aws ce get-cost-forecast \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u -v+1d +%Y-%m-%d)",End="$(date -u -v+15d +%Y-%m-%d)" \
  --metric UNBLENDED_COST \
  --granularity DAILY

echo "===== BUDGET STATUS ====="
aws budgets describe-budget-performance-history \
  --region "$BILLING_REGION" \
  --account-id "$ACCOUNT_ID" \
  --budget-name "jpcite-credit-run-stop-18900"

echo "===== BATCH QUEUES ====="
aws batch describe-job-queues \
  --region "$REGION" \
  --job-queues jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test \
  --query 'jobQueues[].{name:jobQueueName,state:state,status:status,priority:priority}'

echo "===== JOB COUNTS ====="
for Q in jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test; do
  for S in SUBMITTED PENDING RUNNABLE STARTING RUNNING SUCCEEDED FAILED; do
    COUNT="$(aws batch list-jobs --region "$REGION" --job-queue "$Q" --job-status "$S" --query 'length(jobSummaryList)' --output text)"
    echo "${Q} ${S} ${COUNT}"
  done
done

echo "===== TAGGED RESOURCES ====="
aws resourcegroupstaggingapi get-resources \
  --region "$REGION" \
  --tag-filters Key=Project,Values=jpcite Key=CreditRun,Values=2026-05 \
  --query 'ResourceTagMappingList[].{arn:ResourceARN,tags:Tags}'
```

Stop triggers:

- actual or forecasted account cost reaches USD 18,900
- Cost Explorer shows unexpected service spend above USD 100
- any Marketplace, Savings Plans, Reserved Instance, support upgrade, or commitment-like charge appears
- untagged run resources are found
- queue caps are changed without an hourly report
- NAT Gateway or data transfer costs are materially higher than expected
- public S3 exposure check fails

## 10. Stop: fast stop script

The operator must keep this ready before any workload starts. It disables new Batch work first, then cancels queued jobs, then terminates running jobs.

```bash
set -euo pipefail
export AWS_PAGER=""
export REGION="${REGION:-ap-northeast-1}"

QUEUES="jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test"
COMPUTE_ENVS="jpcite-source-crawl-ce jpcite-pdf-parse-ce jpcite-parquet-build-ce jpcite-packet-precompute-ce jpcite-geo-eval-ce jpcite-load-test-ce"

echo "Disabling Batch job queues..."
for Q in $QUEUES; do
  aws batch update-job-queue \
    --region "$REGION" \
    --job-queue "$Q" \
    --state DISABLED || true
done

echo "Cancelling non-running jobs..."
for Q in $QUEUES; do
  for S in SUBMITTED PENDING RUNNABLE STARTING; do
    aws batch list-jobs \
      --region "$REGION" \
      --job-queue "$Q" \
      --job-status "$S" \
      --query 'jobSummaryList[].jobId' \
      --output text | tr '\t' '\n' | while read -r JOB_ID; do
        if [ -n "$JOB_ID" ] && [ "$JOB_ID" != "None" ]; then
          aws batch cancel-job \
            --region "$REGION" \
            --job-id "$JOB_ID" \
            --reason "jpcite credit run stop"
        fi
      done
  done
done

echo "Terminating running jobs..."
for Q in $QUEUES; do
  aws batch list-jobs \
    --region "$REGION" \
    --job-queue "$Q" \
    --job-status RUNNING \
    --query 'jobSummaryList[].jobId' \
    --output text | tr '\t' '\n' | while read -r JOB_ID; do
      if [ -n "$JOB_ID" ] && [ "$JOB_ID" != "None" ]; then
        aws batch terminate-job \
          --region "$REGION" \
          --job-id "$JOB_ID" \
          --reason "jpcite credit run emergency stop"
      fi
    done
done

echo "Reducing compute environment caps where supported..."
for CE in $COMPUTE_ENVS; do
  aws batch update-compute-environment \
    --region "$REGION" \
    --compute-environment "$CE" \
    --state DISABLED \
    --compute-resources maxvCpus=0 || true
done

echo "Post-stop queue status..."
aws batch describe-job-queues \
  --region "$REGION" \
  --job-queues $QUEUES \
  --query 'jobQueues[].{name:jobQueueName,state:state,status:status}'
```

Do not delete S3 buckets during emergency stop. Preserve artifacts and reports first.

## 11. Stop: service audit commands

Run these immediately after the fast stop script to catch non-Batch spend.

```bash
echo "Tagged resources still present:"
aws resourcegroupstaggingapi get-resources \
  --region "$REGION" \
  --tag-filters Key=Project,Values=jpcite Key=CreditRun,Values=2026-05 \
  --query 'ResourceTagMappingList[].ResourceARN'

echo "ECS clusters and tasks:"
aws ecs list-clusters --region "$REGION" || true

echo "EC2 instances tagged for this run:"
aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Project,Values=jpcite" "Name=tag:CreditRun,Values=2026-05" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].{id:InstanceId,state:State.Name,type:InstanceType,az:Placement.AvailabilityZone,tags:Tags}' || true

echo "NAT gateways:"
aws ec2 describe-nat-gateways \
  --region "$REGION" \
  --filter "Name=tag:Project,Values=jpcite" "Name=tag:CreditRun,Values=2026-05" \
  --query 'NatGateways[].{id:NatGatewayId,state:State,subnet:SubnetId}' || true

echo "OpenSearch domains:"
aws opensearch list-domain-names --region "$REGION" || true

echo "Glue crawlers:"
aws glue list-crawlers --region "$REGION" || true
```

If any ECS tasks, EC2 instances, NAT Gateways, OpenSearch domains, or Glue crawlers were created by the run, stop/delete them only after confirming their artifacts are exported to S3.

## 12. Post-run: reporting commands

Create final reports after the stop line or planned completion. These commands collect billing, resource, Batch, and S3 evidence. The `aws s3 cp` uploads preserve the run ledger in the reports bucket.

```bash
export REPORT_DIR="/tmp/jpcite-credit-run-${RUN_ID_COMPACT}-reports"
mkdir -p "$REPORT_DIR"

aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  > "${REPORT_DIR}/cost_by_service.json"

aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --filter '{"Tags":{"Key":"CreditRun","Values":["2026-05"],"MatchOptions":["EQUALS"]}}' \
  --group-by Type=DIMENSION,Key=SERVICE \
  > "${REPORT_DIR}/cost_by_service_creditrun_2026_05.json"

aws budgets describe-budgets \
  --region "$BILLING_REGION" \
  --account-id "$ACCOUNT_ID" \
  > "${REPORT_DIR}/budgets.json"

aws batch describe-job-queues \
  --region "$REGION" \
  --job-queues jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test \
  > "${REPORT_DIR}/batch_job_queues.json"

aws batch describe-compute-environments \
  --region "$REGION" \
  --compute-environments jpcite-source-crawl-ce jpcite-pdf-parse-ce jpcite-parquet-build-ce jpcite-packet-precompute-ce jpcite-geo-eval-ce jpcite-load-test-ce \
  > "${REPORT_DIR}/batch_compute_environments.json"

aws resourcegroupstaggingapi get-resources \
  --region "$REGION" \
  --tag-filters Key=Project,Values=jpcite Key=CreditRun,Values=2026-05 \
  > "${REPORT_DIR}/tagged_resources.json"

for B in "$RAW_BUCKET" "$DERIVED_BUCKET" "$REPORTS_BUCKET"; do
  aws s3api get-bucket-encryption --bucket "$B" > "${REPORT_DIR}/${B}_encryption.json"
  aws s3api get-public-access-block --bucket "$B" > "${REPORT_DIR}/${B}_public_access_block.json"
  aws s3api get-bucket-lifecycle-configuration --bucket "$B" > "${REPORT_DIR}/${B}_lifecycle.json"
  aws s3 ls "s3://${B}/" --recursive --summarize > "${REPORT_DIR}/${B}_s3_summary.txt"
done

aws s3 cp "$REPORT_DIR" "s3://${REPORTS_BUCKET}/final-ledger/" --recursive
```

Final ledger checklist:

- actual spend and forecasted residual spend
- credit remaining per Billing console
- service-level spend table
- tag-filtered spend table and known tag gaps
- created buckets and retained prefixes
- Batch queues, compute environments, and final state
- deleted transient resources
- artifacts worth preserving
- artifacts that must not be published
- follow-up cleanup date

## 13. Post-run: cleanup sequence

Cleanup should be deliberate, not rushed during emergency stop.

1. Confirm all useful outputs are in `s3://${DERIVED_BUCKET}/` or `s3://${REPORTS_BUCKET}/`.
2. Confirm no Batch jobs are `SUBMITTED`, `PENDING`, `RUNNABLE`, `STARTING`, or `RUNNING`.
3. Disable queues and compute environments.
4. Delete job queues only after they are disabled and drained.
5. Delete compute environments only after job queues no longer reference them.
6. Delete transient OpenSearch/ECS/EC2/NAT/Glue resources if they were created.
7. Keep S3 buckets until privacy and publication review is complete.
8. Tighten S3 lifecycle after review if long-term retention is needed.

Suggested cleanup commands after artifact verification:

```bash
for Q in jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test; do
  aws batch update-job-queue --region "$REGION" --job-queue "$Q" --state DISABLED || true
done

# Delete queues only after describe-job-queues shows VALID and no active jobs.
for Q in jpcite-source-crawl jpcite-pdf-parse jpcite-parquet-build jpcite-packet-precompute jpcite-geo-eval jpcite-load-test; do
  aws batch delete-job-queue --region "$REGION" --job-queue "$Q" || true
done

for CE in jpcite-source-crawl-ce jpcite-pdf-parse-ce jpcite-parquet-build-ce jpcite-packet-precompute-ce jpcite-geo-eval-ce jpcite-load-test-ce; do
  aws batch update-compute-environment --region "$REGION" --compute-environment "$CE" --state DISABLED || true
  aws batch delete-compute-environment --region "$REGION" --compute-environment "$CE" || true
done
```

Do not delete the S3 buckets until the final ledger is reviewed.

## 14. Spending envelope

| Category | Target USD | Operational control |
|---|---:|---|
| Safety buffer | 800-1,200 | never intentionally spend |
| S3 source lake and reports | 1,000-1,800 | bucket lifecycle, private buckets, no accidental public serving |
| Batch ETL compute | 4,000-5,500 | Fargate Spot queues, max vCPU caps, hourly queue report |
| OCR/PDF extraction | 2,500-4,500 | bounded batches, early stop if per-page cost spikes |
| Glue/Athena/catalog | 1,200-2,500 | query limits, table validation, no open-ended scans |
| Search/index experiments | 1,500-3,000 | short-lived domain only, export then delete |
| Packet/proof generation | 2,000-3,000 | checkpoint artifacts to S3 |
| GEO/eval/load tests | 1,000-2,000 | capped load-test queue, stop first on anomaly |

## 15. Do-not-spend list

- Savings Plans, Reserved Instances, Capacity Reservations, or upfront commitments
- Marketplace subscriptions unless credit eligibility is explicitly confirmed
- support plan upgrades
- long-lived GPU or OpenSearch resources
- NAT Gateways left idle
- EBS volumes or snapshots without TTL
- public S3 buckets
- untagged resources
- production request-time LLM calls
- crawls that violate robots, terms, or license boundaries
- publication of raw private CSV data or row-level customer data

## 16. References

- AWS CLI `budgets create-budget`: https://docs.aws.amazon.com/cli/latest/reference/budgets/create-budget.html
- AWS CLI `budgets create-budget-action`: https://docs.aws.amazon.com/en_us/cli/latest/reference/budgets/create-budget-action.html
- AWS Budgets Actions overview: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS CLI `ce get-cost-and-usage`: https://docs.aws.amazon.com/cli/latest/reference/ce/get-cost-and-usage.html
- AWS Cost Explorer overview: https://aws.amazon.com/documentation-overview/cost-explorer/
- Amazon S3 AWS CLI getting started: https://docs.aws.amazon.com/AmazonS3/latest/userguide/GettingStartedS3CLI.html
- AWS Batch CLI command reference: https://docs.aws.amazon.com/cli/latest/reference/batch/
- AWS CLI Resource Groups Tagging API `get-resources`: https://docs.aws.amazon.com/en_us/cli/latest/reference/resourcegroupstaggingapi/get-resources.html
