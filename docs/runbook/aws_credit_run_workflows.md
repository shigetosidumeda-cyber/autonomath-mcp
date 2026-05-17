---
title: AWS credit run — GHA workflows
updated: 2026-05-16
operator_only: true
category: ETL
---

# AWS credit run — GHA workflows

Operator runbook for the 4 GitHub Actions workflows that orchestrate the
jpcite-credit AWS Batch run (2026-05-16..2026-05-29 window).

Status: 2026-05-16, **live_aws_commands_allowed=false** preserved — every
mutating workflow defaults to DRY_RUN and requires confirm-by-input plus
operator-set secrets before any side-effect lands.

## Required GitHub repository secrets

Set with `gh secret set <NAME>` from the operator workstation. These
secrets live in the **GHA secret store**, which is namespace-separate
from the Fly secret store (see memory `feedback_secret_store_separation`).

| Secret | Used by | Notes |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | all 4 workflows | IAM principal scoped to jpcite-credit-* resources |
| `AWS_SECRET_ACCESS_KEY` | all 4 workflows | matching secret |
| `AWS_REGION` (optional) | all 4 workflows | defaults to `ap-northeast-1` |
| `JPCITE_TEARDOWN_LIVE_TOKEN` | `aws-credit-teardown.yml` | literal: `I-AM-TEARING-DOWN-jpcite-credit-2026-05` |

Minimum IAM policy actions (combined across the 4 workflows):

* `states:StartExecution` on
  `arn:aws:states:ap-northeast-1:993693061769:stateMachine:jpcite-credit-orchestrator`
* `ce:GetCostAndUsage`, `ce:GetCostForecast`
* `batch:DescribeJobQueues`, `batch:UpdateJobQueue`, `batch:DeleteJobQueue`,
  `batch:ListJobs`, `batch:CancelJob`, `batch:TerminateJob`
* `batch:DescribeComputeEnvironments`, `batch:UpdateComputeEnvironment`,
  `batch:DeleteComputeEnvironment`
* `batch:DescribeJobDefinitions`, `batch:DeregisterJobDefinition`
* `logs:DescribeLogGroups`, `logs:DeleteLogGroup`
* `s3:ListBucket`, `s3:DeleteObject`, `s3:DeleteBucket`
  (last two only for the teardown bucket-delete branch — fenced)

## 1. `aws-credit-orchestrator.yml`

Kicks off the Step Functions state machine that runs
J01 → J02/J03/J04 (parallel) → J05 → J06 → J07 → aggregate.

| Field | Value |
| --- | --- |
| Trigger | `schedule` (every 6h: `0 */6 * * *`) + `workflow_dispatch` |
| Calendar guard | `JPCITE_CREDIT_RUN_START..END` env (default 2026-05-16..2026-05-29). Outside window → skip start-execution. |
| Confirm-by-input | none (read-only `states:StartExecution`; the state machine itself stays within budget via CloudWatch alarms + budget canary) |
| Job timeout | 15 min (workflow only kicks off; state machine runs hours-to-days) |
| Workflow inputs | `execution_name` (override), `input_json` (default `{}`), `force_outside_window` |

Operator usage:

```bash
# Manual kick off (within window)
gh workflow run aws-credit-orchestrator.yml

# Manual kick off OUTSIDE window (e.g. dry probe before 2026-05-16)
gh workflow run aws-credit-orchestrator.yml -f force_outside_window=true

# Inspect last 5 runs
gh run list --workflow aws-credit-orchestrator.yml --limit 5
```

## 2. `aws-credit-cost-monitor.yml`

Hourly cost guard. Read-only against Cost Explorer; opens GitHub issues
on budget breach so the operator gets a fresh notification.

| Field | Value |
| --- | --- |
| Trigger | `schedule` (`7 * * * *`, hourly at :07) + `workflow_dispatch` |
| Pipeline | `burn_target.py` (exit 0/1/2 → RAMP/STOP/SLOWDOWN) → `cost_ledger.sh` (24h) → comment on sticky issue + open breach issue on SLOWDOWN/STOP |
| Confirm-by-input | none (read-only) |
| Job timeout | 15 min |
| Workflow inputs | `target_usd` (default 18300), `deadline` (default 2026-05-29) |

Issues:

* **Sticky tracking issue** — label `aws-credit-cost-monitor`. Auto-created
  on first run, every subsequent run appends a comment. Search:
  `gh issue list --label aws-credit-cost-monitor`.
* **Breach issue** — label `aws-credit-breach` plus `aws-credit-STOP` or
  `aws-credit-SLOWDOWN`. Created only when burn_target.py status flips
  out of RAMP. Operator deliberately resolves by running
  `aws-credit-stop-drill.yml` if appropriate, then closes the issue.

This workflow does **NOT** auto-stop. Auto-stop is the operator's
explicit action via the stop-drill workflow below — matching the
project's destruction-free organization rule.

## 3. `aws-credit-stop-drill.yml`

Operator-only emergency stop drill. Disables jpcite-credit-* queues,
cancels SUBMITTED/PENDING/RUNNABLE jobs, terminates RUNNING jobs,
disables compute environments.

| Field | Value |
| --- | --- |
| Trigger | `workflow_dispatch` ONLY (no schedule) |
| Confirm-by-input | `mode=live` + `confirm_live=I-CONFIRM-STOP` (both required, else DRY_RUN) |
| Default | DRY_RUN — surface what would be cancelled/terminated, no side effects |
| Job timeout | 20 min |

Operator usage:

```bash
# DRY_RUN preview (safe — surfaces queues/jobs/CEs that would be touched)
gh workflow run aws-credit-stop-drill.yml -f mode=dry_run

# LIVE — requires confirm input verbatim
gh workflow run aws-credit-stop-drill.yml \
  -f mode=live \
  -f confirm_live=I-CONFIRM-STOP
```

When to fire:

1. `aws-credit-cost-monitor.yml` opened an `aws-credit-breach` issue
   with `aws-credit-STOP` label.
2. Out-of-band signal (Slack page, AWS budget SNS alarm) suggests
   runaway burn that the auto-stop Lambda did not catch.
3. Operator wants to drain ahead of teardown (see workflow 4).

## 4. `aws-credit-teardown.yml`

Operator-only final teardown. Deletes the entire jpcite-credit-* AWS
Batch infrastructure (queues + compute environments + job definitions +
log group + optionally S3 buckets).

| Field | Value |
| --- | --- |
| Trigger | `workflow_dispatch` ONLY (no schedule) |
| Confirm-by-input | `mode=live` + `confirm_live=I-CONFIRM-TEARDOWN` AND `JPCITE_TEARDOWN_LIVE_TOKEN` GHA secret set |
| Bucket deletion | additional `delete_buckets=yes` input + secret token; data loss is irreversible |
| Default | DRY_RUN — surface what would be deleted, no side effects |
| Job timeout | 30 min |

Operator usage:

```bash
# DRY_RUN preview (safe)
gh workflow run aws-credit-teardown.yml -f mode=dry_run

# LIVE teardown (keeps S3 buckets)
gh workflow run aws-credit-teardown.yml \
  -f mode=live \
  -f confirm_live=I-CONFIRM-TEARDOWN

# LIVE teardown WITH bucket deletion (data loss)
gh workflow run aws-credit-teardown.yml \
  -f mode=live \
  -f confirm_live=I-CONFIRM-TEARDOWN \
  -f delete_buckets=yes
```

When to fire:

1. Credit run window closed (after 2026-05-29) and aggregate ledger is
   verified persisted to R2.
2. Step Functions execution(s) all in `SUCCEEDED` state and
   `aggregate_run_ledger.py` has exported the run summary.
3. `stop_drill` has run cleanly so no jobs are in-flight.

Bucket deletion (`delete_buckets=yes`) is a separate decision — keep
buckets if anyone (consumer, auditor) might still need to read raw
crawl output. Default `no` preserves data.

## Concurrency

Each workflow has a unique `concurrency.group` so two manual fires of
the same workflow serialize (no `cancel-in-progress`). Different
workflows can run in parallel — e.g. cost-monitor keeps running while a
stop-drill is in flight.

## Auto-PR / auto-merge

None of these workflows open pull requests or auto-merge. They are
imperative ops workflows, not CI gates.

## Anti-patterns to avoid

* **Do NOT** schedule `aws-credit-stop-drill.yml` or
  `aws-credit-teardown.yml`. Operator intent is the gate.
* **Do NOT** weaken the confirm-by-input checks. The whole point is
  that a malicious push or accidental click can never trigger LIVE
  side-effects without typing the exact phrase.
* **Do NOT** put `JPCITE_TEARDOWN_LIVE_TOKEN` in workflow YAML or commit
  it. It MUST live in the GHA secret store only.
* **Do NOT** add an auto-merge step. Workflow output stays on the
  Actions tab + the sticky tracking issue — operator reads + acts.

## See also

* `scripts/aws_credit_ops/submit_job.sh` — single-job submitter
* `scripts/aws_credit_ops/submit_all.sh` — J01..J07 sequential submitter (local CLI)
* `scripts/aws_credit_ops/monitor_jobs.sh` — periodic job status probe
* `scripts/aws_credit_ops/aggregate_run_ledger.py` — per-job artifact aggregator
* `scripts/aws_credit_ops/burn_target.py` — hourly burn calculator
* `scripts/aws_credit_ops/cost_ledger.sh` — daily service breakdown
* `scripts/aws_credit_ops/stop_drill.sh` — emergency stop primitive
* `scripts/aws_credit_ops/teardown_credit_run.sh` — final teardown primitive
* `scripts/aws_credit_ops/export_to_r2.sh` — post-run R2 export
* `docs/runbook/ghta_r2_secrets.md` — GHA secret-store guidance
