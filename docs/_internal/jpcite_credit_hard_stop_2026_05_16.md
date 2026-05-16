# jpcite AWS credit hard-stop — Budget Action @ $18,900 (2026-05-16)

**Status:** LIVE — third-line defense armed for the $19,490 burn cap.
**Owner:** Bookyou株式会社 (AWS account 993693061769, profile `bookyou-recovery`).

## Three-line defense recap

| Line | Budget                              | Limit ($) | Action                                                                                       |
|------|-------------------------------------|-----------|----------------------------------------------------------------------------------------------|
| 1    | jpcite-credit-run-watch-17000       | 17,000    | Email-only notifications (info / sss) — early warning.                                       |
| 2    | jpcite-credit-run-slowdown-18300    | 18,300    | Email-only notifications + manual throttle of cron / Batch concurrency.                      |
| 3    | jpcite-credit-run-stop-18900        | **18,900**| **Budget Action `APPLY_IAM_POLICY` — auto-attaches deny policy to operator user.**           |

The credit envelope ceiling is **$19,490** (BookYou AWS Activate credit grant + small reserve). Line 3 fires **before** the cap is breached and freezes the only path that can spend new money: the operator user `bookyou-recovery-admin`.

## Components landed

### 1. IAM deny policy `jpcite-credit-run-deny-new-spend`

- ARN: `arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend`
- PolicyId: `ANPA6OXFY2KEQ2QE2JMMH`
- Source: `infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json`

Denies the spend-creating actions:

- `batch:SubmitJob`, `batch:CreateComputeEnvironment`, `batch:UpdateComputeEnvironment`, `batch:CreateJobQueue`
- `ec2:RunInstances`
- `sagemaker:CreateTransformJob`, `sagemaker:CreateTrainingJob`, `sagemaker:CreateProcessingJob`, `sagemaker:CreateEndpoint`, `sagemaker:CreateEndpointConfig`
- `states:StartExecution`, `events:PutRule`, `events:EnableRule`

Explicitly **allows** the stop / teardown / observe path so the operator can still clean up:

- Batch: `UpdateJobQueue` (disable), `CancelJob`, `TerminateJob`, `DescribeJobs`, `DescribeJobQueues`, `DescribeComputeEnvironments`, `ListJobs`, `DeleteJobQueue`, `DeleteComputeEnvironment`
- EC2: `TerminateInstances`, `StopInstances`, `DescribeInstances`
- SageMaker: `StopTransformJob`, `StopTrainingJob`, `StopProcessingJob`, `DeleteEndpoint`
- Step Functions: `StopExecution`, `DescribeExecution`
- EventBridge: `DisableRule`, `DeleteRule`, `ListRules`
- Logs / CloudWatch / SNS: read + alarm-disable + Publish

Because IAM evaluation is **explicit-deny-always-wins**, this denies the spend axis **without removing AdministratorAccess** — the operator stays administrator-grade everywhere except the listed spend verbs.

### 2. Budget Action execution role `jpcite-budget-action-role`

- ARN: `arn:aws:iam::993693061769:role/jpcite-budget-action-role`
- RoleId: `AROA6OXFY2KEUGP6KBC5N`
- Trust: `budgets.amazonaws.com` only.
- Inline policy `jpcite-budget-action-exec`: `iam:AttachUserPolicy` / `iam:DetachUserPolicy` (+ Role / Group variants), `sns:Publish` against `arn:aws:sns:*:993693061769:jpcite-credit-*`, and CloudWatch Logs write.
- Sources: `infra/aws/iam/jpcite_budget_action_trust.json`, `infra/aws/iam/jpcite_budget_action_role_policy.json`.

### 3. Budget Action wired to `jpcite-credit-run-stop-18900`

- ActionId: `36b0120b-99bd-47f1-a68a-622f16f1995b`
- BudgetName: `jpcite-credit-run-stop-18900`
- NotificationType: `ACTUAL`
- ActionThreshold: `100% PERCENTAGE` of $18,900 → fires at $18,900 ACTUAL.
- ApprovalModel: `AUTOMATIC` (no manual confirmation needed — armed for the worst case).
- ActionType: `APPLY_IAM_POLICY` attaching `jpcite-credit-run-deny-new-spend` to user `bookyou-recovery-admin`.
- ExecutionRoleArn: `jpcite-budget-action-role`.
- Subscribers (email): `info@bookyou.net`, `sss@bookyou.net`.
- Current Status: `STANDBY` (healthy — waiting for breach).

## Live verification (2026-05-16)

A controlled live test was run to confirm the deny path enforces correctly without leaving residue:

```text
attach jpcite-credit-run-deny-new-spend → bookyou-recovery-admin
  ↳ probe batch:CreateComputeEnvironment
      AccessDeniedException — "explicit deny in an identity-based policy"
detach jpcite-credit-run-deny-new-spend
  ↳ verify: only AdministratorAccess remains attached
```

`infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json`'s explicit-deny is enforced by IAM as expected; the detach restores the operator user to clean Administrator state. The dry-run / live simulation harness is at `scripts/aws_credit_ops/simulate_budget_action_attach.sh` (default dry-run, `--commit` to live-test).

## When this fires in production

1. `ACTUAL` cost crosses $18,900 in the monthly window.
2. AWS Budgets assumes `jpcite-budget-action-role`, calls `iam:AttachUserPolicy` to put `jpcite-credit-run-deny-new-spend` on `bookyou-recovery-admin`, and sends email to both subscribers.
3. The operator user can still: cancel running Batch jobs, terminate EC2 instances, stop SageMaker jobs, disable EventBridge rules, read Logs, publish SNS.
4. The operator user cannot: start new Batch jobs / compute envs, run new EC2 instances, start new SageMaker jobs, start new Step Functions, create new EventBridge rules.

## How to reverse the action (after teardown is verified safe)

```bash
# Detach the deny policy
aws --profile bookyou-recovery iam detach-user-policy \
  --user-name bookyou-recovery-admin \
  --policy-arn arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend

# Verify clean state
aws --profile bookyou-recovery iam list-attached-user-policies \
  --user-name bookyou-recovery-admin

# Confirm Budget Action returned to STANDBY when ACTUAL cost retreats below threshold
aws --profile bookyou-recovery budgets describe-budget-action \
  --account-id 993693061769 \
  --budget-name jpcite-credit-run-stop-18900 \
  --action-id 36b0120b-99bd-47f1-a68a-622f16f1995b
```

## Cross-references

- `infra/aws/iam/jpcite_credit_run_deny_new_spend_policy.json`
- `infra/aws/iam/jpcite_budget_action_trust.json`
- `infra/aws/iam/jpcite_budget_action_role_policy.json`
- `scripts/aws_credit_ops/simulate_budget_action_attach.sh`
- `docs/_internal/aws_credit_review_07_iam_budget_policy.md` (master IAM + Budget Action plan)
- `docs/_internal/aws_credit_acceleration_plan_2026-05-15.md` (overall $19,490 cap framework)

last_updated: 2026-05-16
