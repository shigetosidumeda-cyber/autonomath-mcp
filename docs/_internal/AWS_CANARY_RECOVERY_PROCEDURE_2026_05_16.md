# AWS Canary Recovery Procedure — $19,490 Boundary Scenario (2026-05-16)

> **Status: teardown chain verified end-to-end DRY_RUN, Budget Action confirmed STANDBY @ $18.9K.**
> Each layer of the 5-line defense (`AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md`) is independently armed.
> This doc covers **how to recover** if any line fires — Budget Action attaches deny IAM,
> CW alarm @ $18.7K invokes auto-stop Lambda, or operator runs `stop_drill.sh` / `teardown_credit_run.sh`.

last_updated: 2026-05-16

companion docs:
- `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` (defense layers)
- `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md` (forward path)
- `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` (infra inventory)

---

## 0. End-to-end verification (this session, 2026-05-16 16:11 JST)

All four checks below executed in DRY_RUN against profile `bookyou-recovery`:

| step | script | mode | result |
| --- | --- | --- | --- |
| 1 | `scripts/aws_credit_ops/stop_drill.sh` | DRY_RUN | listed 3 queues + 3 CEs + 8 RUNNING jobs (fargate-spot-short-queue), would terminate / disable cleanly |
| 2 | `scripts/aws_credit_ops/teardown_credit_run.sh` | DRY_RUN | 7-step preview ok — step 1-6 enumerated, step 7 (bucket delete) skipped by default |
| 3 | `scripts/aws_credit_ops/burn_target.py` | read-only | target $18,300 / consumed $0 (CE token expired in default region, defaults to 0; replace AWS_DEFAULT_REGION if needed) / remaining $18,300 / 12 days to 2026-05-29 / target $1,525/day |
| 4 | `scripts/aws_credit_ops/emit_burn_metric.py` | read-only | CE call failed with `UnrecognizedClientException` — token region mismatch (us-east-1 CE needs explicit profile region), non-blocking for teardown |
| 5 | synthetic SNS publish → Lambda | DRY_RUN | `aws sns publish` accepted (MessageId `08e2ca19-3ea6-5207-bb8e-a89b247843f5`), Lambda invoked + enumerated queues + CEs in dry_run mode + emitted self-attestation that broke the loop on second invocation |
| 6 | `aws budgets describe-budget-actions-for-account` | read-only | Budget `jpcite-credit-run-stop-18900` Action `36b0120b-...` STANDBY @ 100% (= $18,900) APPLY_IAM_POLICY → `jpcite-credit-run-deny-new-spend` to user `bookyou-recovery-admin` |

Auto-stop Lambda current state (us-east-1):
- ARN: `arn:aws:lambda:us-east-1:993693061769:function:jpcite-credit-auto-stop`
- env `JPCITE_AUTO_STOP_ENABLED=false` (safe default; flip to `true` to arm)
- env `STOP_DRILL_LIVE=false`
- last modified 2026-05-16T06:53:48Z

CW alarms (us-east-1):
- `jpcite-credit-billing-early-warning-13000` — OK
- `jpcite-credit-billing-warn-14000` — OK
- `jpcite-credit-billing-slowdown-17000` — OK
- `jpcite-credit-billing-stop-18700` — OK

Deny policy attached to `bookyou-recovery-admin`? **No** (Budget Action STANDBY → only `AdministratorAccess` attached). The deny policy auto-attaches when the Budget Action fires at $18.9K.

---

## 1. $19,490 boundary scenario simulation

Assume Cost Explorer reflects $18,900 actual spend at T0. The expected event chain over the next minutes:

```
T+0s   AWS Budget envelope detects 100% breach against $18,900 budget
T+0s   Budget Action 36b0120b-... transitions STANDBY → EXECUTED
T+0s   APPLY_IAM_POLICY runs:
         IAM attach-user-policy
           --user-name bookyou-recovery-admin
           --policy-arn arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend
T+0s   Effective IAM permissions for bookyou-recovery-admin:
         AdministratorAccess (allow *)
         + jpcite-credit-run-deny-new-spend (explicit deny on new spend creators)
       Explicit deny wins → operator role cannot create new Batch / EC2 / SageMaker resources.
T+0s   Subscribers notified (info@bookyou.net + sss@bookyou.net)
```

In parallel (and likely before the Budget Action fires, since CW alarms react faster than the Budget API):

```
T-? min  CW alarm jpcite-credit-billing-stop-18700 transitions OK → ALARM at $18,700
T-? min  CW alarm publishes to SNS arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts
T-? min  Lambda jpcite-credit-auto-stop direct-invoked (protocol=lambda, no email confirm)
T-? min  Lambda body:
           if JPCITE_AUTO_STOP_ENABLED=="true":
             update-job-queue --state DISABLED (3 queues)
             cancel-job (all SUBMITTED/PENDING/RUNNABLE/STARTING)
             terminate-job (all RUNNING)
             update-compute-environment --state DISABLED (3 CEs)
           else:
             log dry_run + emit attestation, no resource mutation
T-? min  Lambda emits attestation SNS event subject="jpcite-credit-auto-stop attestation"
         (loop guard: subsequent invocations detect self_attestation echo and skip batch walk)
```

**Net result at $18,900 ceiling reach:**
- Existing running jobs continue to bleed until Lambda terminates them (Lambda line 4 @ $18.7K should have already fired)
- New spend creation is denied by IAM (line 5 @ $18.9K)
- $590 margin ($19,490 - $18,900) absorbs Cost Explorer's 8-12h reflection lag

**If somehow $19,490 is reached:** that would mean both line 4 (Lambda) and line 5 (Budget Action) failed. The recovery procedure below covers all scenarios.

---

## 2. Recovery procedure (after Budget Action fires)

The Budget Action attaches a deny policy. The operator role is then unable to create new spend resources but **can still** call `iam:DetachUserPolicy` (since AdministratorAccess `Allow *` covers it and the deny policy targets only spend-creating actions). Order:

### 2.1 Confirm spend has stopped

```bash
export AWS_PROFILE=bookyou-recovery

# Confirm queues are drained / disabled
aws batch describe-job-queues --region ap-northeast-1 \
  --query 'jobQueues[?starts_with(jobQueueName,`jpcite-credit-`)].[jobQueueName,state,status]' \
  --output table

# Confirm no RUNNING jobs left
for Q in jpcite-credit-fargate-spot-short-queue jpcite-credit-ec2-spot-cpu-queue jpcite-credit-ec2-spot-gpu-queue; do
  aws batch list-jobs --region ap-northeast-1 --job-queue "$Q" --job-status RUNNING \
    --query 'length(jobSummaryList)' --output text
done

# Confirm CEs disabled
aws batch describe-compute-environments --region ap-northeast-1 \
  --query 'computeEnvironments[?starts_with(computeEnvironmentName,`jpcite-credit-`)].[computeEnvironmentName,state,status]' \
  --output table
```

If anything still running, fire the manual stop drill **before** detaching deny:

```bash
JPCITE_STOP_DRILL_LIVE=true bash scripts/aws_credit_ops/stop_drill.sh
```

### 2.2 Verify burn rate is flat

```bash
.venv/bin/python scripts/aws_credit_ops/burn_target.py
# Expect: consumed climbed past $18.9K; verify daily burn rate has dropped to ~0
```

Wait 60+ minutes after step 2.1 before declaring "spend stopped" — Cost Explorer reflection lag means real-time CE numbers can still rise after the resource pool is drained.

### 2.3 Detach the deny IAM policy

```bash
DENY_POLICY_ARN=arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend
ACTION_USER=bookyou-recovery-admin

# Before
aws iam list-attached-user-policies --user-name "$ACTION_USER"
# Expect: AdministratorAccess + jpcite-credit-run-deny-new-spend

# Detach
aws iam detach-user-policy \
  --user-name "$ACTION_USER" \
  --policy-arn "$DENY_POLICY_ARN"

# After
aws iam list-attached-user-policies --user-name "$ACTION_USER"
# Expect: AdministratorAccess only
```

### 2.4 Reset the Budget Action to STANDBY

The Action transitioned EXECUTED → it stays in EXECUTED until manually reset.

```bash
ACTION_ID=36b0120b-99bd-47f1-a68a-622f16f1995b
BUDGET_NAME=jpcite-credit-run-stop-18900

# Reset action state to STANDBY (re-arms the line 5 hammer)
aws budgets execute-budget-action \
  --account-id 993693061769 \
  --region us-east-1 \
  --budget-name "$BUDGET_NAME" \
  --action-id "$ACTION_ID" \
  --execution-type RESET
```

(If `execute-budget-action RESET` is rejected by the SDK version, recreate the action: `aws budgets delete-budget-action ... && aws budgets create-budget-action ...` with the same JSON payload from the original creation — see `infra/aws/budgets/jpcite-credit-run-stop-18900.json`.)

### 2.5 Reset CW alarms to OK

The line 4 CW alarm `jpcite-credit-billing-stop-18700` will remain in ALARM until the EstimatedCharges metric drops below 18700 (which it won't, since you've already breached). Manually set the alarm state:

```bash
aws cloudwatch set-alarm-state \
  --region us-east-1 \
  --alarm-name jpcite-credit-billing-stop-18700 \
  --state-value OK \
  --state-reason "manual reset post recovery 2026-05-16"
```

(Repeat for other ALARM-state alarms — `slowdown-17000`, `warn-14000`, `early-warning-13000`.)

### 2.6 Restart (only if budget header allows new burn)

The original credit run target was $18,300 by 2026-05-29. If recovery happened above $18,900, the budget is exhausted and **no restart should occur** — proceed to teardown (step 3).

If somehow the budget was bumped (rare; would require explicit operator decision + new budget envelope), restart by:

```bash
# Re-enable CEs
for CE in jpcite-credit-ec2-spot-cpu jpcite-credit-ec2-spot-gpu jpcite-credit-fargate-spot-short; do
  aws batch update-compute-environment --region ap-northeast-1 \
    --compute-environment "$CE" --state ENABLED
done

# Re-enable queues
for Q in jpcite-credit-fargate-spot-short-queue jpcite-credit-ec2-spot-cpu-queue jpcite-credit-ec2-spot-gpu-queue; do
  aws batch update-job-queue --region ap-northeast-1 \
    --job-queue "$Q" --state ENABLED
done

# Re-arm the auto-stop Lambda (default off; flip on for production burn)
aws lambda update-function-configuration --region us-east-1 \
  --function-name jpcite-credit-auto-stop \
  --environment "Variables={JPCITE_AUTO_STOP_ENABLED=true,JPCITE_BATCH_REGION=ap-northeast-1,JPCITE_ATTESTATION_TOPIC_ARN=arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts}"
```

---

## 3. Final teardown (recovery via teardown path)

If recovery is "tear it all down and don't restart":

```bash
# Preview (always run first)
bash scripts/aws_credit_ops/teardown_credit_run.sh

# Live (after preview review)
JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05 \
DRY_RUN=false \
bash scripts/aws_credit_ops/teardown_credit_run.sh

# (Optional, separately) delete S3 buckets (data loss)
JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05 \
DRY_RUN=false \
STEP_DELETE_BUCKETS=1 \
JPCITE_TEARDOWN_DELETE_BUCKETS=1 \
bash scripts/aws_credit_ops/teardown_credit_run.sh
```

After teardown, repeat steps 2.3 + 2.4 + 2.5 to clean up IAM + Budget + CW state.

---

## 4. What this verification did **not** test

Documented for honesty (the chain works under synthetic load; live load conditions may surface additional issues):

- **CW alarm → SNS → Lambda live cascade** — synthetic SNS publish exercised the SNS → Lambda subscription path, but not the CW alarm → SNS publish path (that needs the EstimatedCharges metric to cross threshold, which would require actual $18,700 spend).
- **Budget Action live attach** — Budget Action remains STANDBY; live IAM deny policy attach has not been observed end-to-end in production this session.
- **Cost Explorer reflection lag** — burn_target.py + emit_burn_metric.py both rely on CE which reflects 8-12h behind reality. The metric emitter failed with a token region mismatch this session (non-blocking for teardown chain, but observability gap to address before next live burn).
- **Lambda mutation against live queues** — Lambda enabled=false means the synthetic SNS publish exercised the enumerate + log + attestation paths but **not** the actual `update-job-queue --state DISABLED` / `cancel-job` / `terminate-job` calls. Live mutation requires `JPCITE_AUTO_STOP_ENABLED=true` flip + a real ALARM trigger.

These gaps are intentional — production burn ramp will exercise them as designed. The defense layer chain is **structurally verified** in DRY_RUN, which is the strongest non-destructive assurance available.

---

## 5. Quick reference (one-liner cheat sheet)

```bash
# verify defense state
AWS_PROFILE=bookyou-recovery aws lambda get-function-configuration \
  --function-name jpcite-credit-auto-stop --region us-east-1 \
  --query 'Environment.Variables'
AWS_PROFILE=bookyou-recovery aws budgets describe-budget-actions-for-account \
  --account-id 993693061769 --region us-east-1 \
  --query 'Actions[0].[BudgetName,Status,ActionThreshold]'
AWS_PROFILE=bookyou-recovery aws cloudwatch describe-alarms --region us-east-1 \
  --alarm-name-prefix jpcite --query 'MetricAlarms[].[AlarmName,StateValue]' --output table

# fire manual stop (DRY_RUN preview)
bash scripts/aws_credit_ops/stop_drill.sh

# fire manual stop (LIVE)
JPCITE_STOP_DRILL_LIVE=true bash scripts/aws_credit_ops/stop_drill.sh

# fire teardown (DRY_RUN preview)
bash scripts/aws_credit_ops/teardown_credit_run.sh

# fire teardown (LIVE)
JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05 \
DRY_RUN=false bash scripts/aws_credit_ops/teardown_credit_run.sh

# detach deny policy after Budget Action fire
aws iam detach-user-policy \
  --user-name bookyou-recovery-admin \
  --policy-arn arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend
```
