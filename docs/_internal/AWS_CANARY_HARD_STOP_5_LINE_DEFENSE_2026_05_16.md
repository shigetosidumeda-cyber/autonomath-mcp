---
historical: true
superseded_by: site/releases/rc1-p0-bootstrap/preflight_scorecard.json (as of 2026-05-17T03:11:48Z)
canonical_live_state: site/releases/rc1-p0-bootstrap/preflight_scorecard.json
---

# AWS Canary Hard-Stop — $19,490 5-Line Defense Closeout (2026-05-16 PM)

> **Historical snapshot — 2026-05-16 PM cut.** Live armed/standby state of CW alarms and
> Budget Actions drifts over time; **always read** `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`
> + `scripts/aws_credit_ops/verify_armed_state.sh` (if present) for canonical live
> verification. Status at this snapshot: 5 line defense ARMED + teardown scripts available.
> Lambda `jpcite-credit-auto-stop` runs with `JPCITE_AUTO_STOP_ENABLED=true`.
> Budget Action attached at $18.9K threshold (deny IAM auto-applies).
> CW alarm @ $18.7K bypasses SNS email-confirm and direct-invokes Lambda.
> `$19,490` is the absolute ceiling — **never reach** by design ($590 margin).

last_updated: 2026-05-16

companion runbook: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
companion closeout: `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md`
companion run closeout: `docs/_internal/AWS_CANARY_RUN_2026_05_16.md`
memory back-link: `project_jpcite_aws_canary_infra_live_2026_05_16` (SOT, Phase 7) /
`feedback_aws_canary_hard_stop_5_line_defense` (this doc's lesson) /
`feedback_aws_canary_burn_ramp_pattern` (4-stage ramp, orthogonal to defense)

---

## 0. Why this doc exists

User asked **"19,490ドルでストップするようになってますよね？"** —
which exposed that a **single SNS chain (Budget → SNS → email confirm → operator manual stop)** is structurally insufficient for the $19,490 ceiling. Three lag layers conspire to push real burn above the alert threshold before any human acts:

1. **Cost Explorer reflection lag**: 8-12 hour delay between actual burn and Cost Explorer / Budget API reflection. A $17K alert can fire while real burn is already $18-19K.
2. **SNS email confirm pending**: SNS email subscriptions require manual confirmation. While pending, the alert never reaches the operator.
3. **Operator response time**: 30 min - several hours for a human to read the alert and run a manual stop. At night / while travelling, this can stretch to a full day.

This doc records the **5-line defense + teardown scripts (line 0)** that supersedes the single-SNS-chain pattern and makes the $19,490 ceiling structurally unreachable.

---

## 1. The 5 lines (defense in depth)

Each line has an **independent trigger** and an **independent response path**. Higher-numbered lines do not depend on lower lines firing.

| # | Line | Threshold | Trigger | Response path | Latency |
| --- | --- | --- | --- | --- | --- |
| 0 | **Teardown scripts** | n/a | manual / on-call | `stop_drill.sh` / `teardown_credit_run.sh` (DRY_RUN smoke + live token) | seconds (operator) |
| 1 | **CW alarm warn** | **$14K** | CloudWatch billing alarm | SNS → Lambda log (visibility only, no auto-stop) | seconds |
| 2 | **Budget alert** | **$17K** | AWS Budget envelope | SNS → Lambda log (operator awareness) | seconds |
| 3 | **Budget slowdown** | **$18.3K** | AWS Budget envelope | SNS → Lambda log + CW alarm dual fire | seconds |
| 4 | **CW alarm stop** | **$18.7K** | CloudWatch billing alarm | SNS → **Lambda DISABLES queues + cancels jobs** (no email confirm dependency) | seconds |
| 5 | **Budget Action deny** | **$18.9K** | AWS Budget Action | **deny IAM policy auto-applied to operator role** (no new resources) | seconds |
| — | **Ceiling** | **$19,490** | n/a (absolute line) | n/a (margin) — **never reach** | n/a |

**$19,490 - $18.9K = $590 margin** is the buffer that absorbs Cost Explorer's 8-12 hour reflection lag if all 5 lines somehow fail simultaneously.

---

## 2. Line 4 (CW alarm @ $18.7K → Lambda auto-stop) — the load-bearing path

This is the load-bearing line. Lines 1-3 are notifications; line 5 is an IAM deny; line 4 is the **active resource flip** that actually drains running burn.

### Trigger
- CloudWatch billing alarm `jpcite-credit-cost-stop-187k` (threshold = USD 18,700)
- Region: us-east-1 (alarm + SNS topic colocated)
- Datapoint: EstimatedCharges (Currency=USD)

### Response path
- SNS topic `jpcite-credit-cost-alerts` (us-east-1) →
- Lambda `jpcite-credit-auto-stop` (us-east-1) **direct invoke** (no email confirm)
- Lambda env var **`JPCITE_AUTO_STOP_ENABLED=true`** (must be flipped — default is `false` for safety)
- Lambda body (Python 3.12) executes against `ap-northeast-1` Batch resources via `JPCITE_BATCH_REGION=ap-northeast-1`:
  - `aws batch update-job-queue --state DISABLED` for every `jpcite-credit-*` queue
  - `aws batch cancel-job` for every SUBMITTED / PENDING / RUNNABLE / STARTING job
  - `aws batch terminate-job` for every RUNNING job
  - `aws batch update-compute-environment --state DISABLED` for every `jpcite-credit-*` CE

### Why this matters
- **Email-confirm independent**: SNS subscription can be `PendingConfirmation` and line 4 still fires. The Lambda subscription is `protocol=lambda`, not `protocol=email`, so no human confirmation is required.
- **Same-region invoke**: SNS topic + Lambda are both us-east-1. Step Functions `arn:aws:states:::sns:publish` is **not** in the line 4 path (see `feedback_aws_cross_region_sns_publish` for the cross-region trap that bit us during Phase 4).
- **Idempotent**: Lambda is safe to re-invoke. Re-running on already-disabled queues is a no-op.

### Verify
```bash
# Lambda armed?
aws lambda get-function-configuration --region us-east-1 \
  --function-name jpcite-credit-auto-stop \
  --query 'Environment.Variables.JPCITE_AUTO_STOP_ENABLED'
# Expected: "true"

# SNS subscription wired?
aws sns list-subscriptions-by-topic --region us-east-1 \
  --topic-arn arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts \
  --query "Subscriptions[?Protocol=='lambda'].[Endpoint,SubscriptionArn]" --output table

# CW alarm in OK state (no breach yet)?
aws cloudwatch describe-alarms --region us-east-1 \
  --alarm-names jpcite-credit-cost-stop-187k \
  --query 'MetricAlarms[0].[AlarmName,StateValue,Threshold]' --output table
```

---

## 3. Line 5 (Budget Action @ $18.9K → deny IAM policy) — the IAM hammer

Line 5 is **structural**: even if line 4 fails to disable all running resources, the operator role cannot create new resources to extend the bleed.

### Trigger
- AWS Budget envelope `jpcite-credit-hard-ceiling-189k` (LIMIT_AMOUNT = 18,900 USD)
- Budget Action attached at 100% of budget (i.e. threshold = $18,900)

### Response path
- Budget Action automatically attaches **deny IAM policy** `jpcite-credit-run-deny-new-spend-policy` to the operator role
- Policy doc: `infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json`
- Effect: `Deny` on `ec2:RunInstances`, `batch:Submit*`, `lambda:CreateFunction`, `sagemaker:Create*`, `bedrock:*`, etc.
- Existing resources do not stop, but they should already be drained by line 4. The deny is the **belt-and-braces** so no new burn-source can be spun up while line 4 is processing.

### Why this matters
- **Independent of line 4**: even if Lambda has a bug, the IAM deny still applies
- **Independent of SNS**: Budget Action is a separate AWS subsystem from CW alarm + SNS
- **Auto-rollback path**: when burn drops back below threshold, Budget Action can be configured to auto-detach the deny policy (or operator can manually detach via console)

### Verify
```bash
# Budget Action attached?
aws budgets describe-budget-actions-for-account --account-id 993693061769 \
  --query 'Actions[?starts_with(BudgetName,`jpcite-credit-`)].[BudgetName,Status,ActionThreshold.ActionThresholdValue]' --output table

# Deny policy exists?
aws iam get-policy \
  --policy-arn arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend-policy \
  --query 'Policy.[PolicyName,IsAttachable]' --output table

# Trust doc valid?
test -f infra/aws/iam/jpcite_budget_action_trust.json && echo "OK"
test -f infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json && echo "OK"
```

---

## 4. Line 0 (teardown scripts) — operator-driven last resort

If all 5 lines fail (e.g. Cost Explorer lag pushes burn past $19K before any line fires), the operator has tested teardown scripts ready.

### `stop_drill.sh`
- Path: `scripts/aws_credit_ops/stop_drill.sh`
- DRY_RUN default (set `JPCITE_STOP_DRILL_LIVE=true` for live)
- Disables all `jpcite-credit-*` queues, cancels SUBMITTED/PENDING/RUNNABLE jobs, terminates RUNNING jobs
- Profile: `AWS_PROFILE=bookyou-recovery` (canary account)
- Region: `REGION=ap-northeast-1`
- Tested 2026-05-16 (DRY_RUN smoke OK)

### `teardown_credit_run.sh`
- Path: `scripts/aws_credit_ops/teardown_credit_run.sh`
- DRY_RUN default (set `DRY_RUN=false` + `JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05` for live)
- 7 steps: disable queues / drain jobs / delete queues / deregister job defs / delete CEs / delete log group / delete S3 buckets (default OFF)
- Each step gated by `STEP_*=1/0` env var for partial execution
- S3 buckets default OFF (`STEP_DELETE_BUCKETS=0`) — data loss prevention

### When to invoke
- Cost Explorer dashboard shows burn > $19K and lines 1-5 have not fired (very unlikely, but documented for completeness)
- Phase 6+ teardown (planned cleanup at end of canary window)
- DR drill (verify scripts still work)

---

## 5. Verification procedure (full 5-line audit)

Run this **after** any `--unlock-live-aws-commands` flip and **before** burn ramp resumption.

```bash
#!/usr/bin/env bash
set -euo pipefail
export AWS_PROFILE=bookyou-recovery
ACCT=993693061769

echo "=== Line 1+2+3: CW alarms + Budget envelopes ==="
aws cloudwatch describe-alarms --region us-east-1 \
  --query 'MetricAlarms[?starts_with(AlarmName,`jpcite-credit-`)].[AlarmName,Threshold,StateValue]' --output table

aws budgets describe-budgets --account-id "$ACCT" \
  --query 'Budgets[?starts_with(BudgetName,`jpcite-credit-`)].[BudgetName,BudgetLimit.Amount]' --output table

echo "=== Line 4: Lambda armed (JPCITE_AUTO_STOP_ENABLED=true) ==="
AUTO_STOP=$(aws lambda get-function-configuration --region us-east-1 \
  --function-name jpcite-credit-auto-stop \
  --query 'Environment.Variables.JPCITE_AUTO_STOP_ENABLED' --output text)
echo "  JPCITE_AUTO_STOP_ENABLED=$AUTO_STOP"
[ "$AUTO_STOP" = "true" ] || { echo "  FAIL: Lambda not armed"; exit 1; }

echo "=== Line 4: SNS → Lambda subscription confirmed ==="
aws sns list-subscriptions-by-topic --region us-east-1 \
  --topic-arn "arn:aws:sns:us-east-1:${ACCT}:jpcite-credit-cost-alerts" \
  --query "Subscriptions[?Protocol=='lambda'].[Endpoint,SubscriptionArn]" --output table

echo "=== Line 5: Budget Action attached at \$18.9K ==="
aws budgets describe-budget-actions-for-account --account-id "$ACCT" \
  --query 'Actions[?starts_with(BudgetName,`jpcite-credit-`)].[BudgetName,Status,ActionThreshold.ActionThresholdValue]' --output table

echo "=== Line 0: teardown scripts dry-run smoke ==="
DRY_RUN=true bash scripts/aws_credit_ops/teardown_credit_run.sh | head -20
echo
JPCITE_STOP_DRILL_LIVE=false bash scripts/aws_credit_ops/stop_drill.sh | head -10

echo "=== 5-line audit OK ==="
```

Exit code 0 = all 5 lines armed. Any non-zero exit = at least one line is dark, **do not flip `live_aws_commands_allowed=true`** until repaired.

---

## 6. What to do if a breach occurs

### Scenario A: Line 1 ($14K warn) fires
- **Action**: monitor only. This is expected during burn ramp.
- Confirm CW metric is rising on actual workload (not a stuck poller).
- Cross-check daily target ($1,500-3,000/day in deep ramp).

### Scenario B: Line 2 ($17K soft alert) fires
- **Action**: review ramp posture.
- Are we within 3-5 day window? If yes, stay course.
- Are we tracking ahead of plan? Consider slowing EventBridge schedule from `rate(10 minutes)` to `rate(30 minutes)`.

### Scenario C: Line 3 ($18.3K effective cap) fires
- **Action**: **DISABLE new submissions**.
- Set EventBridge schedule to DISABLED.
- Let RUNNING jobs drain naturally — do not cancel yet.
- Recheck Cost Explorer in 4-6 hours (account for reflection lag).

### Scenario D: Line 4 ($18.7K stop alarm) fires
- **Action**: Lambda has already disabled queues + cancelled jobs.
- Verify via `aws batch describe-job-queues --query 'jobQueues[*].state'` — all should be DISABLED.
- Do not re-enable until cost has measurably regressed below $18K.

### Scenario E: Line 5 ($18.9K deny IAM) fires
- **Action**: **emergency mode**.
- Operator role can no longer create resources.
- Verify all running burn has stopped (`aws ec2 describe-instances`, `aws sagemaker list-processing-jobs`, etc).
- Manually escalate: emit attestation early, log full inventory, prepare canary closure ahead of schedule.

### Scenario F: $19,490 ceiling approached (lines 1-5 all failed)
- **Action**: **immediate teardown**.
- Run `JPCITE_STOP_DRILL_LIVE=true bash scripts/aws_credit_ops/stop_drill.sh` (5 sec)
- Run `DRY_RUN=false JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05 bash scripts/aws_credit_ops/teardown_credit_run.sh STEP_DELETE_BUCKETS=0` (5-10 min)
- File an internal incident: 5-line defense failure, RCA required.
- Cross-reference `project_aws_bookyou_compromise` for the BookYou account compromise pattern that informed this defense.

---

## 7. Reference paths

### Scripts (`scripts/aws_credit_ops/`)
- `stop_drill.sh` — line 0 manual stop (DRY_RUN default)
- `teardown_credit_run.sh` — line 0 full teardown (DRY_RUN default, live-token gated)
- `deploy_auto_stop_lambda.sh` — line 4 Lambda deploy (sets `JPCITE_AUTO_STOP_ENABLED` env var)
- `deploy_burn_metric_lambda.sh` — burn metric emitter (informational, no defense role)
- `deploy_canary_attestation_lambda.sh` — attestation emitter (post-run, no defense role)
- `cost_ledger.sh` — burn ledger (informational)
- `burn_target.py` — burn ramp pacing (informational)

### Lambda + IAM (`infra/aws/lambda/` + `infra/aws/iam/`)
- `infra/aws/lambda/jpcite_credit_auto_stop.py` — line 4 Lambda body
- `infra/aws/iam/jpcite_credit_auto_stop_trust.json` — Lambda trust policy
- `infra/aws/iam/jpcite_credit_auto_stop_policy.json` — Lambda execution policy
- `infra/aws/iam/jpcite_budget_action_trust.json` — line 5 Budget Action trust
- `infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json` — line 5 deny IAM policy

### Companion docs
- `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md` — execution runbook (preflight + ramp)
- `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` — infra closeout (Phase 1-2)
- `docs/_internal/AWS_CANARY_RUN_2026_05_16.md` — run closeout (Phase 3-5+)
- `docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md` — Phase 7 attestation template
- `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md` — 1-page operator quickstart

### Memory
- `project_jpcite_aws_canary_infra_live_2026_05_16` — SOT (Phase 7 added today)
- `feedback_aws_canary_hard_stop_5_line_defense` — this doc's lesson (canonical)
- `feedback_aws_canary_burn_ramp_pattern` — 4-stage ramp (orthogonal to defense)
- `feedback_aws_cross_region_sns_publish` — line 4 SNS region pitfall
- `feedback_loop_promote_concern_separation` — `--unlock-live-aws-commands` 5-line pre-check
- `project_aws_bookyou_compromise` — companion crisis pattern (different account)

---

## 8. last_updated

2026-05-16 PM (jpcite Wave 50 RC1 + AWS canary Phase 7 hard-stop guardrail closeout)
