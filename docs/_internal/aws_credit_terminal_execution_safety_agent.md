# jpcite AWS Credit Terminal Execution Safety Agent

Date: 2026-05-15  
Scope: terminal safety design for a later AWS CLI execution session  
Status: planning-only safety review. This document does not implement scripts, create AWS resources, or execute AWS commands.  
Related docs:

- `docs/_internal/aws_credit_acceleration_plan_2026-05-15.md`
- `docs/_internal/aws_credit_cli_runbook_agent.md`
- `docs/_internal/aws_credit_cost_guardrails_agent.md`
- `docs/_internal/aws_credit_security_privacy_agent.md`
- `docs/_internal/aws_credit_batch_compute_agent.md`
- `docs/_internal/aws_credit_data_foundation_agent.md`
- `docs/_internal/aws_credit_outputs_agent.md`

## 0. Executive Contract

This document defines the safety envelope for the terminal where the AWS credit run may later be executed. It is intentionally stricter than a normal runbook because the account has a large expiring credit balance and a real cash-overrun risk.

The terminal must be treated as a controlled execution environment:

- No AWS command is run until identity, region, billing visibility, budgets, logging, dry-run posture, stop path, and rollback path are confirmed.
- No pasteable command block may mix read-only audit, resource creation, workload launch, and cleanup in one sequence.
- No command may depend on an implicit AWS profile, implicit region, or hidden shell state.
- No high-cost resource may be created without a matching stop command and rollback note already written in the run ledger.
- No destructive cleanup may run until artifacts are exported and the operator has confirmed the exact resources that will be deleted.
- The operator must be able to answer "what did this terminal do, when, as whom, in which account, in which region, and how much can it still spend?" from local logs and AWS logs.

Hard stop:

- If account identity is unexpected, stop.
- If billing or Cost Explorer access is unavailable, stop.
- If the active region is not explicitly set, stop.
- If command logging is not active, stop.
- If an intended command is not classified in this document or the workload runbook, stop and classify it before execution.
- If Cost Explorer actual+forecast approaches the configured stop line, stop all new work and run the stop path.

## 1. Safety Principles

### 1.1 One terminal, one run identity

The AWS credit execution terminal should be bound to one explicit run:

- `PROJECT=jpcite`
- `CREDIT_RUN=2026-05`
- `RUN_ID=2026-05`
- `RUN_PURPOSE=evidence-acceleration`
- `ENVIRONMENT=credit-run`
- `OWNER=bookyou`

Do not reuse a terminal that has unrelated AWS environment variables, production deployment variables, or personal default profiles in scope.

### 1.2 Read, prepare, launch, stop, cleanup are separate gates

The execution sequence must be split into gates:

| Gate | Purpose | Allowed command class | Exit condition |
|---|---|---|---|
| G0 terminal setup | Start logging and freeze environment | local shell only | log path, run id, operator, timestamp recorded |
| G1 identity | Confirm account/profile/region | AWS read-only identity/config | account id and principal match expected values |
| G2 billing visibility | Confirm credit/budget/cost visibility | AWS billing read-only | Cost Explorer/Budgets can be read |
| G3 guardrail readiness | Confirm budgets, tags, stop commands, dry-run posture | read-only plus approved guardrail setup in separate runbook | all guardrails visible |
| G4 workload preflight | Confirm resource plan and dry-run/smoke test | read-only, validate, dry-run, small smoke only | expected resource count/cost ceiling accepted |
| G5 workload execution | Run approved workload | allowlisted workload commands only | hourly ledger remains under stop line |
| G6 stop | Disable new work and terminate active jobs | stop commands only | no runnable/running workload remains |
| G7 cleanup/export | Preserve artifacts and remove transient resources | export/read/list/delete by approved manifest | final ledger and cleanup evidence complete |

No gate may be skipped because a prior document contains commands. The terminal operator must explicitly record the gate transition in the command log.

### 1.3 Default deny for unclassified commands

The terminal policy is default-deny:

- If a command is not read-only, not a dry-run, not a pre-approved guardrail setup, not a pre-approved workload launch, not a stop command, and not a manifest-based cleanup command, it is not executable.
- If the cost profile is unknown, classify as "do not execute".
- If the rollback path is unclear, classify as "do not execute".
- If a service can create persistent public exposure, classify as "do not execute" until security review approves it.

## 2. Terminal Setup Gate

### 2.1 Required environment variables

The operator must set and print these variables before any AWS CLI call:

| Variable | Required value pattern | Reason |
|---|---|---|
| `AWS_PROFILE` | explicit named profile, never empty | prevents accidental default profile use |
| `AWS_REGION` | `ap-northeast-1` unless billing/control API requires otherwise | avoids cross-region drift |
| `AWS_DEFAULT_REGION` | same as `AWS_REGION` | keeps SDK/CLI consistent |
| `AWS_PAGER` | empty string | prevents paged output hiding prompts |
| `PROJECT` | `jpcite` | tag/log correlation |
| `CREDIT_RUN` | `2026-05` | tag/log correlation |
| `RUN_ID` | `2026-05` | local ledger correlation |
| `RUN_ID_COMPACT` | `202605` | resource names |
| `OWNER` | `bookyou` | ownership |
| `ENVIRONMENT` | `credit-run` | non-production boundary |
| `BILLING_REGION` | `us-east-1` | Cost Explorer/Budgets convention |
| `STOP_LINE_USD` | approved stop amount, e.g. `18900` | explicit financial stop |
| `ALERT_EMAIL` | approved monitored address | budget notifications |
| `COMMAND_LOG` | local append-only log path | audit trail |

Forbidden terminal state:

- Empty `AWS_PROFILE`.
- Unset `AWS_REGION` or `AWS_DEFAULT_REGION`.
- Any production deployment secret in the environment.
- Any raw CSV path or customer data path exported as a shell variable.
- Any shell alias that rewrites `aws`, `rm`, `xargs`, `parallel`, `kubectl`, `terraform`, `pulumi`, `cdk`, or `sam`.

### 2.2 Local-only setup command shape

The setup gate may use local shell commands to start logging and inspect environment. It must not call AWS until the log has started.

Required local checks:

- `pwd`
- `date -u`
- `whoami`
- shell version
- AWS CLI version
- print selected environment variables with secrets redacted
- confirm `aws` resolves to the expected binary path
- confirm no dangerous aliases/functions override AWS or deletion commands

The log must include:

- run id
- operator
- machine hostname
- current working directory
- git status of the runbook repository, if applicable
- exact command text or command digest
- UTC timestamp
- local timezone timestamp
- exit code

### 2.3 Command logging modes

Use two logs:

| Log | Contents | Storage |
|---|---|---|
| local terminal transcript | command text, stdout/stderr, timestamps, exit codes | local `docs/_internal/exec_logs/` or operator-approved private path |
| run ledger | summarized decisions, gate transitions, resource ids, cost readings, stop actions | Markdown or JSONL under internal docs or private artifact bucket |

Rules:

- Secrets must never be echoed into either log.
- Raw CSV values, customer names, row-level data, prompt text containing private data, and credentials are forbidden in logs.
- Full AWS responses may be logged only when they do not include secrets, signed URLs, private payloads, or raw document text.
- If a command may return sensitive fields, use AWS CLI `--query` to restrict output before running it.
- If log capture fails, pause the run. Do not continue on memory.

## 3. Confirmation Prompts

### 3.1 Prompt standard

Every non-read-only command group requires a manual confirmation prompt with the exact gate, account, principal, region, command class, expected maximum spend, and rollback/stop path.

The prompt must require typing an exact phrase, not `y` or Enter.

Required phrase format:

```text
EXECUTE <GATE> <PROJECT> <CREDIT_RUN> <ACCOUNT_ID> <REGION>
```

Example phrase:

```text
EXECUTE G3 jpcite 2026-05 123456789012 ap-northeast-1
```

The operator must copy the phrase from a generated prompt after visually confirming all fields. If any field is unexpected, the correct action is to stop, not to edit the phrase.

### 3.2 Prompt fields

Each prompt must display:

| Field | Required |
|---|---|
| Gate | `G3`, `G4`, `G5`, `G6`, or `G7` |
| Command class | guardrail, smoke, workload, stop, cleanup |
| AWS account id | from `sts get-caller-identity` |
| Principal ARN | from `sts get-caller-identity` |
| Region | explicit |
| Billing region | explicit for CE/Budgets |
| Resource tags | full required tag set |
| Resource count | expected create/update/delete count |
| Estimated maximum incremental spend | amount and time window |
| Stop command | named stop path available before launch |
| Rollback command | named rollback path or reason no rollback is possible |
| Log path | local transcript and ledger path |
| Dry-run result | pass/fail or "service has no dry-run; smoke test used" |

### 3.3 Commands that do not need a typed prompt

Typed prompt is not required for:

- local shell inspection that cannot affect AWS or delete local files
- AWS identity read-only commands
- AWS cost/budget read-only commands
- AWS resource describe/list/get commands that do not return sensitive payloads

Even these commands must still be logged.

## 4. Dry-Run and Smoke Test Policy

### 4.1 Dry-run hierarchy

Use the strongest available safety check:

| Level | Meaning | Examples |
|---|---|---|
| L0 parse only | validate JSON/YAML/CLI shape locally | `jq`, schema validation |
| L1 IAM dry-run | AWS evaluates permission without creating resource | EC2 APIs with `--dry-run` where supported |
| L2 service validate | service validates config without launch | service-specific validate APIs where available |
| L3 no-op create/update | idempotent check that makes no change | describe-before-create, compare desired/current |
| L4 tiny smoke | create the smallest reversible resource/job | one small Batch job, one small object, one small query |
| L5 full run | approved workload | only after L0-L4 pass as applicable |

If a service has no dry-run support, do not pretend it is safe. Record: "No native dry-run; using describe + quota + tiny smoke + stop path."

### 4.2 Dry-run required before these classes

Dry-run or smoke is required before:

- EC2, Batch, ECS, Fargate, Lambda concurrency, Step Functions, Glue, Athena, Textract, OpenSearch, Bedrock, SageMaker, RDS, Redshift, Kinesis, SQS high-volume producers, DataSync, and any service with scalable spend.
- S3 bulk copy, sync, inventory, lifecycle changes, replication, or cross-region movement.
- IAM/SCP/Budget Actions that could deny future access or affect non-run workloads.
- Any cleanup command with deletion or lifecycle policy changes.

### 4.3 Smoke test budget

The smoke test budget should be capped separately from the main run:

- Target: USD 100-300 maximum incremental spend.
- No more than one service family is scaled during smoke.
- Smoke output must prove logging, tagging, artifact path, stop path, and cost visibility.
- If smoke spend does not appear in Cost Explorer by tag/service when expected, do not scale.

## 5. Rollback Design

### 5.1 Rollback scope

Rollback means "return the account to the pre-run safety posture and preserve audit evidence." It does not mean AWS will refund already incurred charges or undo completed compute work.

Rollback must cover:

- newly created budgets/actions
- IAM deny policies/SCP attachments
- Batch queues and compute environments
- ECS services/tasks
- EC2 instances/launch templates/Auto Scaling groups
- Step Functions executions
- Glue crawlers/jobs/workflows
- Athena workgroups/query outputs
- S3 replication/lifecycle/public access settings
- OpenSearch domains or serverless collections
- CloudWatch log groups/alarms
- KMS grants created for run roles
- temporary roles, policies, and instance profiles

### 5.2 Rollback preconditions

Before launching any workload, the run ledger must contain:

- resource name pattern
- required tags
- creation command reference
- stop command reference
- rollback command reference
- expected data retention action
- delete eligibility
- owner
- deadline

If a resource cannot be rolled back without risk, it must be marked as "preserve and disable" instead of "delete".

### 5.3 Rollback order

Rollback should follow this order:

1. Disable new work: queues, schedules, event rules, submitters, auto scaling.
2. Stop running work: terminate jobs/tasks/executions according to the stop path.
3. Export evidence: final Cost Explorer snapshots, resource lists, logs, artifact manifests.
4. Preserve required artifacts: source receipts, reports, checksums, run ledger.
5. Remove public exposure risk: verify S3 Block Public Access, policies, OpenSearch access, IAM trust.
6. Delete or downscale transient compute.
7. Remove temporary IAM grants/policies only after no workload needs them.
8. Confirm no tagged resources remain except intentionally retained buckets/logs/artifacts.

### 5.4 Rollback confirmation prompt

Rollback prompt phrase:

```text
ROLLBACK <PROJECT> <CREDIT_RUN> <ACCOUNT_ID> <REGION>
```

Rollback must print a manifest of candidate resources before any deletion. The operator must confirm the manifest count and the exact tag filter used.

## 6. Stop Scripts Design

This section defines required stop script behavior. It does not create script files.

### 6.1 Stop script contract

Every stop script must:

- require explicit `AWS_PROFILE`, `AWS_REGION`, `PROJECT`, and `CREDIT_RUN`
- call `sts get-caller-identity` and print account/principal before action
- use tag filters or explicit manifests, never broad account-wide deletion by service
- default to preview mode
- require a typed confirmation phrase for action mode
- disable new submissions before terminating running work
- write a stop ledger entry with timestamp, account, region, resource ids, command class, and exit code
- be idempotent
- tolerate "not found" for already stopped resources
- avoid deleting durable artifacts unless run in cleanup mode after export

### 6.2 Required stop paths

| Stop path | Purpose | Required first action | Required final check |
|---|---|---|---|
| `stop-batch` | AWS Batch queues/jobs | disable queues or set desired capacity to zero | no `SUBMITTED`, `PENDING`, `RUNNABLE`, `STARTING`, `RUNNING` jobs with run tags |
| `stop-ecs` | ECS services/tasks | set service desired count to zero | no running tasks for run cluster/service |
| `stop-ec2` | EC2/ASG workers | suspend scale-out or set desired capacity zero | no running tagged instances unless preserved |
| `stop-stepfunctions` | workflow fanout | stop executions | no running executions for run state machines |
| `stop-glue-athena` | analytics spend | stop Glue jobs/crawlers and Athena queries | no active jobs/queries in run workgroups |
| `stop-opensearch` | search/index spend | disable ingest clients, downscale/delete only by approved plan | no ingest jobs and no unbounded domain scaling |
| `stop-textract` | document extraction spend | stop producers and queue consumers | no active submitted extraction workload |
| `stop-schedules` | recurring triggers | disable EventBridge schedules/rules | no enabled run-tagged schedules |

### 6.3 Stop mode levels

| Mode | Use when | Behavior |
|---|---|---|
| preview | before any workload launch and before every stop | list target resources and planned actions |
| brake | cost pace too high but below hard stop | disable new submissions; allow selected running jobs to finish |
| stop | stop line reached or untagged spend appears | disable submissions and terminate/cancel running work |
| isolate | credential, public exposure, or data leak concern | deny new spend, revoke submitter access, preserve logs, stop compute |
| cleanup | after final export | delete transient resources by approved manifest |

### 6.4 Stop script pseudo-interface

Stop scripts should share a common interface:

```bash
./stop-<service>.sh \
  --project jpcite \
  --credit-run 2026-05 \
  --profile <explicit-profile> \
  --region ap-northeast-1 \
  --mode preview|brake|stop|isolate|cleanup \
  --ledger <path> \
  --require-confirmation
```

The script must refuse to run action modes unless:

- `--mode` is not `preview`
- confirmation phrase is typed exactly
- account id matches expected account id
- tag filter resolves to at least one expected resource or an explicit "nothing to stop" decision is logged

## 7. Command Log and Run Ledger

### 7.1 Minimum local log format

Use JSONL for machine-readable command events where possible:

```json
{
  "ts_utc": "2026-05-15T00:00:00Z",
  "run_id": "2026-05",
  "gate": "G1",
  "operator": "bookyou",
  "account_id": "123456789012",
  "principal_arn": "arn:aws:iam::123456789012:user/example",
  "region": "ap-northeast-1",
  "command_class": "read-only",
  "command_digest": "sha256:<digest>",
  "command_redacted": "aws sts get-caller-identity",
  "exit_code": 0,
  "notes": "identity confirmed"
}
```

Do not rely only on terminal scrollback.

### 7.2 Decision ledger entries

The human-readable ledger should include:

- gate entered
- gate exit decision
- confirmation phrase used, with account id visible
- cost reading at decision time
- resource count before/after
- exception approvals
- stop line status
- any denied/refused commands
- rollback readiness
- final cleanup state

### 7.3 Redaction rules

Never log:

- AWS access keys, session tokens, secret access keys
- signed URLs
- customer CSV values, row values, memo fields, counterparty names
- raw PDF/text payloads if terms/privacy are unclear
- private bucket object keys that include customer labels
- KMS plaintext material
- webhook secrets or API tokens

Prefer logging:

- resource ARN without secret query strings
- tag sets
- counts
- byte sizes
- hashes
- job ids
- status codes
- durations
- service names and usage types

## 8. Permission Confirmation

### 8.1 Identity checks

Before any non-read-only action:

- `sts get-caller-identity` account id must match the approved account.
- Principal ARN must match the approved run operator role/user.
- The terminal must not be using a production deploy role.
- MFA/session age requirements must match the organization's policy.
- If using AWS Organizations, management-account-only operations must not be attempted from a member account.

### 8.2 Required permission categories

The execution principal should have the minimum necessary permissions for the current gate:

| Gate | Permission category |
|---|---|
| G1 | `sts:GetCallerIdentity`, config inspection |
| G2 | Cost Explorer read, Budgets read |
| G3 | approved Budgets/alarms/tag setup, IAM/SCP only if explicitly scoped |
| G4 | describe/list/validate/dry-run plus tiny smoke permissions |
| G5 | workload submit/update only for run resources |
| G6 | stop/cancel/terminate only for run resources |
| G7 | export/read/delete only by manifest |

Do not use administrator access for the full run unless there is no practical alternative. If admin access is temporarily needed, record the reason, time-box it, and remove it after the gate.

### 8.3 Permission boundary expectations

Preferred controls:

- require `aws:RequestTag/Project = jpcite`
- require `aws:RequestTag/CreditRun = 2026-05`
- require `aws:ResourceTag/Project = jpcite` for stop/update/delete
- deny untagged create where service supports tag-on-create
- deny regions outside the approved set
- deny public S3 policies and public ACLs
- deny Marketplace subscriptions and commitment purchases
- deny support plan changes
- deny RI/Savings Plans purchases
- deny IAM user access key creation except approved break-glass

## 9. Command Classification

### 9.1 Allowed without typed prompt, but logged

Read-only, low-sensitivity:

- `aws sts get-caller-identity`
- `aws configure list`
- `aws --version`
- Cost Explorer read commands with safe grouping
- Budgets describe/list commands
- resource describe/list commands scoped by region/tag
- Service Quotas get/list commands
- CloudWatch metric/stat read commands

Constraints:

- Use `--query` when output may include sensitive payloads.
- Do not run broad `get-object`, `logs get-log-events`, or query-result download unless sensitivity is reviewed.

### 9.2 Allowed with typed prompt and prior dry-run/smoke

Guardrail/resource setup:

- Budgets create/update for approved names.
- CloudWatch alarms/log groups for run resources.
- S3 run buckets/prefixes with private, encrypted, tagged, lifecycle-managed settings.
- KMS grants/keys only if approved by security plan.
- AWS Batch/ECS/Glue/Athena/OpenSearch resources only within approved cost envelope and tags.
- IAM policies/roles only from reviewed templates and scoped to run tags.

Workload:

- Batch job submissions from approved job definitions.
- ECS tasks/services with bounded desired count.
- Glue/Athena jobs/queries in dedicated workgroups.
- Textract/OCR jobs from approved manifest and queue size.
- S3 sync/copy only within approved buckets/prefixes and manifests.

Stop/cleanup:

- cancel/terminate/stop/update actions scoped by tags or explicit manifest.
- delete transient resources only after final export and cleanup prompt.

### 9.3 Do-not-execute command classes

These are prohibited for the AWS credit run unless a separate written exception is approved:

| Class | Examples | Reason |
|---|---|---|
| Commitment purchases | Reserved Instances, Savings Plans, Capacity Reservations, Marketplace subscriptions | credit eligibility/cash exposure/long-lived obligation risk |
| Support/account changes | support plan changes, account closure, billing contact edits | non-workload, cash or account risk |
| Public exposure | public S3 bucket policy, public ACL, unauthenticated OpenSearch/API exposure | data/security risk |
| Production mutation | Route 53 production DNS, production CloudFront, production RDS, production secrets | credit run must not alter production behavior |
| Broad IAM mutation | admin policy attachment, access key creation, wildcard trust changes | privilege escalation and persistence risk |
| Broad deletion | unscoped `delete-*`, empty bucket, recursive S3 delete outside manifest | data loss risk |
| Cross-region fanout | replication, copy, compute, or queue creation in unapproved regions | cost/control drift |
| Unbounded autoscaling | ASG/ECS/Batch/Glue/OpenSearch with no max or budget stop | runaway spend risk |
| Untagged create | any resource creation without required tags where tagging is supported | attribution and stop failure |
| Raw private data persistence | upload raw CSV/customer records to S3/logs/Athena/OpenSearch | privacy boundary violation |
| Crypto/mining/benchmark burn | spend-for-spend workloads unrelated to jpcite evidence outputs | waste and policy risk |
| Long-lived databases | RDS/Redshift/OpenSearch intended to stay beyond run window | cleanup and cash exposure risk |
| IaC broad apply | `terraform apply`, `pulumi up`, `cdk deploy`, `sam deploy` without targeted plan review | large hidden blast radius |
| Shell destructive shortcuts | `xargs rm`, recursive delete, unquoted variable deletes | local or remote data loss |

### 9.4 Commands requiring additional human review

Pause and get a second review before:

- attaching or detaching SCPs
- applying Budget Actions that deny IAM
- creating KMS key policies
- creating cross-account access
- changing lifecycle expiration on artifact buckets
- deleting buckets, log groups, KMS grants, or IAM roles
- enabling resource-level hourly Cost Explorer data with paid implications
- running service-specific APIs that do not support tags or cost attribution

## 10. Resource Tagging and Naming

Every AWS resource created for the run must include, where supported:

| Tag | Value |
|---|---|
| `Project` | `jpcite` |
| `CreditRun` | `2026-05` |
| `Purpose` | `evidence-acceleration` |
| `Owner` | `bookyou` |
| `Environment` | `credit-run` |
| `AutoStop` | `2026-05-29` |
| `DataClass` | `public-source`, `private-overlay`, `artifact`, or `logs` |

Naming convention:

```text
jpcite-credit-202605-<service>-<purpose>
```

Names must not include customer names, raw source titles that may be sensitive, private CSV filenames, or secrets.

## 11. Cost Stop Conditions

The terminal operator must stop new work if any condition appears:

- actual+forecast spend reaches the approved stop line
- paid exposure appears where credit coverage was expected
- untagged spend appears
- spend appears in an unapproved region
- a service appears that is not in the approved workload plan
- Cost Explorer/Budgets cannot be read during the run
- budget alert email/SNS is not confirmed
- logs are incomplete
- stop script preview fails
- any public exposure or private data persistence concern is found

Stop decision must be logged before action unless there is an active security incident. In a security incident, isolate first, then complete the ledger.

## 12. Gate Checklists

### G0 terminal setup checklist

- [ ] Local transcript path created.
- [ ] Run ledger path created.
- [ ] AWS CLI version captured.
- [ ] `aws` binary path captured.
- [ ] dangerous aliases/functions absent.
- [ ] required environment variables set.
- [ ] secrets not printed.

### G1 identity checklist

- [ ] account id matches approved account.
- [ ] principal ARN matches approved operator.
- [ ] region and billing region are explicit.
- [ ] no default profile ambiguity.
- [ ] session/MFA posture acceptable.

### G2 billing checklist

- [ ] Cost Explorer read works.
- [ ] Budgets read works.
- [ ] credit amount/scope/expiry confirmed manually in Billing console.
- [ ] current month actual spend captured.
- [ ] forecast captured or noted unavailable.
- [ ] non-credit-eligible spend reviewed.

### G3 guardrail checklist

- [ ] budgets exist at approved thresholds.
- [ ] alerts confirmed by monitored address.
- [ ] Budget Actions reviewed before activation.
- [ ] stop scripts have preview output.
- [ ] required tags activated or activation gap recorded.
- [ ] service quotas checked for planned scale.

### G4 workload preflight checklist

- [ ] workload manifest reviewed.
- [ ] max resource count reviewed.
- [ ] max incremental spend reviewed.
- [ ] dry-run/smoke result logged.
- [ ] stop path tested in preview or empty-state mode.
- [ ] artifact/log destination verified.

### G5 execution checklist

- [ ] typed confirmation captured.
- [ ] command class is allowlisted.
- [ ] resources are tagged.
- [ ] hourly cost/status ledger updated.
- [ ] no unapproved services/regions appear.
- [ ] stop line remains safe.

### G6 stop checklist

- [ ] stop reason logged.
- [ ] new work disabled.
- [ ] running work canceled/terminated or explicitly allowed to drain.
- [ ] no runnable/running jobs remain.
- [ ] schedules disabled.
- [ ] spend watch continues until delayed costs stabilize.

### G7 cleanup checklist

- [ ] final artifacts exported.
- [ ] final cost/resource ledger written.
- [ ] cleanup manifest reviewed.
- [ ] durable artifacts preserved.
- [ ] transient compute removed.
- [ ] temporary IAM/KMS grants removed after no longer needed.
- [ ] remaining resources are intentional and documented.

## 13. Operator Refusal Rules

The terminal operator must refuse to execute when:

- the user asks to "just run it" without gate completion
- an AWS command is pasted without account/region/profile confirmation
- a command creates spend but lacks a stop path
- a command deletes resources without a manifest
- a command may expose public data without security review
- a command persists raw CSV/customer data
- a command depends on a hidden default profile or region
- a command is copied from a different account, different region, or older run id
- a command is an IaC apply/deploy without a reviewed plan
- a command attempts to use all remaining credit as a target

Refusal should be logged as a safety event with the reason and proposed classification path.

## 14. Final Readiness Criteria

The AWS credit terminal is ready for later execution only when all are true:

- Gate checklist G0-G3 is complete.
- The expected AWS account, principal, profile, and region are written in the ledger.
- Command logging is active and tested.
- Budgets and alerts are visible.
- Stop script previews exist for every service that may create recurring or scalable spend.
- Rollback order is documented for every resource family.
- Workload commands are classified before paste.
- Do-not-execute classes are visible to the operator.
- The operator has an explicit stop line and will not try to consume the full credit balance.

Until then, the only acceptable actions are local documentation edits and read-only planning.
