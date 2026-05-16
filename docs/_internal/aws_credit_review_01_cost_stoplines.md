# AWS credit review 01: cost stoplines / overrun prevention

Date: 2026-05-15  
Reviewer: additional agent review 1/20  
Lane: cost stoplines / overrun prevention  
Credit face value: USD 19,493.94  
Status: review document only. No AWS execution, no implementation, no AWS resources created.

## 0. Scope and governing plan

This review finalizes the cost stoplines for the AWS credit run described in `aws_credit_unified_execution_plan_2026-05-15.md`.

The governing objective is to use almost all of the USD 19,493.94 credit while avoiding cash billing. The plan must not target the exact face value. The remaining USD 193.94-593.94 band is deliberate protection against billing lag, credit-ineligible charges, untagged spend, cleanup lag, taxes, support, Marketplace leakage, data transfer, Cost Explorer feature charges, and late-arriving metered usage.

If older lane documents mention USD 18,700, USD 19,000, or other intermediate values, treat them as conservative internal references. For final operator decisions in this lane, use the unified stopline model below.

## 1. Final stopline model

| Line | Gross eligible usage basis | Meaning | Required behavior |
|---|---:|---|---|
| Watch | USD 17,000 | Useful spend is high enough that low-value work can no longer be justified. | Stop launching low-value jobs. Continue only jobs with a written accepted-artifact definition and current good yield. |
| Slowdown | USD 18,300 | The run is entering the narrow control band. | Stop OCR expansion, OpenSearch, broad joins, load tests, exploratory Athena scans, and any job family without clear accepted artifacts. Reduce queue caps. |
| No-new-work | USD 18,900 | The remaining buffer is only USD 593.94 against the credit face value. | No new compute jobs, no new managed services, no new OCR batches. Only finish selected near-complete jobs, export, verify, and cleanup. |
| Manual stretch window | USD 18,900-19,300 | Optional drain/stretch only if telemetry is clean. | Requires explicit manual approval before any additional work. Work must be short-lived, tagged, stoppable, and tied to final packaging or high-value accepted artifacts. |
| Absolute safety line | USD 19,300 | Maximum intentional gross usage. | Emergency stop. Do not intentionally exceed this line. Disable queues, cancel/terminate running work, and delete or stop transient resources after export. |
| Credit face value | USD 19,493.94 | Accounting face value, not a target. | Never target this number. Keep the final USD 193.94+ as protection against delayed and ineligible charges. |

Stopline comparisons must use a conservative value:

```text
control_spend = max(
  Cost Explorer run-to-date UnblendedCost excluding credits,
  Budget gross-burn actual,
  operator ledger committed spend estimate,
  previous confirmed spend + still-running max exposure
)
```

`forecast` is a warning input, not a sole source of truth. If forecast is missing, stale, or obviously weak because the run is short, the operator must rely on actuals, service mix, resource inventory, and committed exposure.

## 2. Budget and Cost Explorer limitations

AWS Budgets is not a hard cap. It can notify and trigger selected actions after thresholds are crossed, but it does not stop every AWS service in real time and it does not reverse already incurred charges.

Cost Explorer and Budgets can lag by hours and sometimes into the next day. Cost allocation tags may also lag after activation and do not retroactively label earlier spend. Because of this:

- Budget alerts are guardrails, not permission to run until the next alert.
- Budget Actions are secondary brakes; primary stops are queue disablement, job cancellation, capacity reduction, and resource deletion.
- Tag-filtered Cost Explorer views are insufficient by themselves. Always compare tag-filtered run spend with unfiltered account/service/region spend.
- Forecast alerts are weak for a short 1-2 week run and must not be the only stop trigger.
- Hourly or resource-level Cost Explorer features can cost money and may have activation delay; use them only if pre-approved.

Required budget set:

| Budget | Purpose | Thresholds |
|---|---|---|
| Gross burn custom budget | Track credit-consuming usage before credits. | Notify at USD 17,000 and USD 18,300. Trigger stop workflow at USD 18,900. Absolute operator line USD 19,300. |
| Paid exposure custom budget | Track credit-after-cash exposure. | USD 1 investigate, USD 25 stop new work, USD 100 absolute stop. |
| Account-level backup budget | Catch tag miss, existing spend, and unsupported filter assumptions. | Low warning threshold plus manual daily review. |

The gross burn budget should exclude credits, refunds, taxes, support, and other non-run adjustments where the aim is to see pre-credit usage. The paid exposure budget should include credits and cash-like charges so non-credit-eligible spend is visible.

## 3. Untagged spend policy

Untagged spend is a stop condition because it breaks attribution and can hide cash exposure.

Every created run resource must use the agreed tags where the service supports them:

```text
Project=jpcite
CreditRun=2026-05
Purpose=evidence-acceleration
Owner=bookyou
AutoStop=2026-05-29
Environment=credit-run
```

Policy:

| Detection | Action |
|---|---|
| Any untagged spend in a service used by the run | Pause scale-up. Reconcile with inventory before continuing. |
| Untagged spend above USD 25 or any untagged managed compute/storage/search resource | Stop new work in that service family. |
| Untagged spend cannot be explained within 30 minutes | Move to No-new-work behavior even if the gross line is below USD 18,900. |
| Untagged spend appears in Marketplace, Support, commitments, NAT/data transfer, or unexpected regions | Immediate emergency stop and manual investigation. |

Because tag activation can lag, the operator must keep a resource inventory ledger in parallel with Cost Explorer. Missing tag visibility is not an excuse to run blind.

## 4. Paid exposure policy

Paid exposure means credit-after-cost, credit-ineligible cost, or cash-like billing risk. It is more important than gross credit consumption.

| Paid exposure signal | Required action |
|---|---|
| USD 1 or any non-credit-eligible service appears | Investigate immediately. Do not increase queue caps until explained. |
| USD 25 | Stop new work. Disable exploratory or stretch jobs. |
| USD 100 | Absolute stop. Disable queues, cancel/terminate running work, preserve ledgers, and cleanup after export. |
| Marketplace, Support upgrade, RI/Savings Plans/upfront commitment, Route 53 domain registration/transfer, tax-only cash charge, or subscription charge | Immediate stop regardless of amount. |

The operator must confirm credit eligibility in the Billing console before spend-heavy work. Credit eligibility is contractual and may differ by promotion, service, region, and charge type.

## 5. Service mix drift policy

The expected spend mix is short-lived artifact generation: S3, Batch, EC2 Spot, Fargate Spot, ECR, Glue Data Catalog, Athena, minimal CloudWatch, and selected conditional services such as Textract, Bedrock batch, CodeBuild, Step Functions, Lambda, or temporary OpenSearch only when explicitly approved.

Any service mix drift must be treated before the next scale-up:

| Drift | Action |
|---|---|
| Expected service exceeds its planned band but accepted artifacts are rising | Hold cap increases and require operator note. |
| Expected service exceeds planned band and accepted artifacts are flat for 2 hours | Stop that job family. |
| Unexpected service reaches USD 25 | Pause all new work using that service family and reconcile. |
| Unexpected service reaches USD 100 | Stop new work account-wide until explained. |
| NAT Gateway, data transfer, public IPv4, EBS snapshot growth, CloudWatch log ingestion spike, Athena raw scan spike | Stop the causing workload and correct design before continuing. |
| Marketplace, Support, commitments, domain charges, unmanaged long-lived database/search/GPU cluster | Immediate emergency stop. |

Service mix review cadence during active spend:

- Start of day JST: previous-day actuals by service, region, account, and tag.
- Midday JST: current pace, running resource inventory, and expected end-of-day exposure.
- Before night/unattended window: disable scale-up and stop any job that cannot be stopped within 30 minutes.
- Before entering USD 18,300, USD 18,900, or manual stretch: save Cost Explorer/Budgets screenshots or ledger snapshots.

## 6. Manual approval conditions

Manual approval is required before any action that could push gross usage beyond USD 18,900, and before any stretch work in the USD 18,900-19,300 window.

Approval is valid only when all conditions are true:

- Latest Cost Explorer and Budgets views are captured, even if known to lag.
- Gross burn, paid exposure, service mix, region mix, and untagged spend have been reconciled against the operator ledger.
- Paid exposure is USD 0, or every nonzero amount is explained and accepted in writing.
- Untagged spend is USD 0, or every item is explained by tag activation lag and matched to inventory.
- No Marketplace, Support upgrade, RI, Savings Plans, upfront commitment, domain, NAT drift, or unexpected long-lived managed service is present.
- Stop scripts have been tested in preview mode and the operator can stop within 30 minutes.
- Workload has a max additional exposure estimate, timeout, retry cap, queue cap, output prefix, accepted-artifact definition, and cleanup path.
- The work is not CPU burn, GPU training, broad load testing, external LLM spend, private CSV persistence, or long-lived infrastructure.

Approval phrase to record in the run ledger:

```text
I approve entering the AWS credit manual stretch window for jpcite run 2026-05.
I understand the absolute safety line is USD 19,300, AWS Budgets is not a hard cap, Cost Explorer can lag, and the full USD 19,493.94 credit face value is not a target.
Approved max additional gross exposure: USD <amount>.
Approved job family: <job family>.
Approval expires at: <timestamp JST>.
```

Manual approval expires after 2 hours, after any stopline change, or immediately when paid exposure, untagged spend, unexpected service drift, private leakage, forbidden claims, or artifact stagnation appears.

## 7. Stop behavior by line

### USD 17,000 Watch

- Freeze low-value job families.
- Continue only high-yield J01-J16 work with accepted artifacts.
- Review planned stretch list but do not launch stretch solely to consume credit.
- Confirm stop scripts, notifications, and operator availability.

### USD 18,300 Slowdown

- Disable expansion for OCR, OpenSearch, broad joins, load tests, and exploratory scans.
- Reduce Batch/ECS/Fargate queue caps.
- Require per-job expected gross exposure before launch.
- Prefer finishing already productive source receipt, proof page, packet, and eval jobs.
- Begin final export and checksum planning.

### USD 18,900 No-new-work

- Disable new submissions for all compute queues.
- Cancel queued work that has not started.
- Allow only explicitly approved near-complete jobs to finish if the additional exposure is bounded and useful.
- Start drain/export/verification/cleanup.
- Do not create new managed services, new indexes, new crawlers, new OCR batches, or new datasets.

### USD 18,900-19,300 Manual stretch

Allowed only with the approval conditions in section 6. Preferred uses are final artifact packaging, checksum verification, small proof/eval completion jobs, or high-yield receipt completion. The stretch window is not a license to run broad compute.

### USD 19,300 Absolute safety line

- Apply emergency stop.
- Disable Batch queues and schedulers.
- Cancel queued jobs and terminate nonessential running jobs.
- Stop/scale down ECS, EC2/ASG, Glue, Athena, Step Functions, CodeBuild, Textract producers, OpenSearch ingestion, Lambda schedules, and other run-tagged compute.
- Preserve logs and manifests needed for audit.
- Export verified artifacts before destructive cleanup.
- Delete or stop transient resources after export.
- Keep deny policy/SCP or equivalent brake in place until final Cost Explorer and resource inventory checks are clean.

## 8. Operator ledger requirements

The cost ledger must be able to answer:

- Current control spend and which source produced it.
- Gross burn excluding credits.
- Paid exposure after credits.
- Service/account/region/tag top drivers.
- Untagged spend reconciliation.
- Running resources and estimated max additional exposure.
- Accepted artifacts produced per USD by job family.
- Manual approvals and expiry times.
- Stop actions taken and verification results.

Minimum ledger rows:

| Time JST | Gross CE | Gross budget | Paid exposure | Untagged | Top service | Running exposure | Line | Decision |
|---|---:|---:|---:|---:|---|---:|---|---|
|  |  |  |  |  |  |  |  |  |

Accepted artifact tracking is part of cost control. If compute is spending but `source_receipts[]`, `known_gaps[]`, packet examples, proof pages, GEO/eval reports, OpenAPI/MCP/discovery artifacts, or final ledgers are not increasing, stop the causing job family.

## 9. Final recommendation

Use USD 18,900-19,300 as the manual stretch and completion band only if telemetry is clean. In normal operation, the best outcome is not the largest Cost Explorer number; it is the largest set of durable jpcite assets produced before the no-new-work and cleanup gates.

The safe final posture is:

- USD 17,000: value triage starts.
- USD 18,300: slowdown and drain planning starts.
- USD 18,900: no new work.
- USD 18,900-19,300: manual stretch only with clean telemetry.
- USD 19,300: emergency stop.
- USD 19,493.94: never targeted.
