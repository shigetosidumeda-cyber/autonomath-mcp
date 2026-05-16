# EventBridge → Step Functions rate analysis (2026-05-16)

Decision artifact for the `jpcite-credit-orchestrator-schedule` EventBridge rate.

## TL;DR

- EventBridge schedule fires correctly every 10 minutes (ENABLED, target wired to `jpcite-credit-orchestrator`).
- 24 of 24 recent executions have **FAILED**; 1 still RUNNING. Zero SUCCEEDED executions across the entire state machine history (`list-executions --status-filter SUCCEEDED` returns empty).
- Post-fix (`manifest_env_missing` resolved in commit `d2fd49723`) the Batch jobs themselves now run to completion — the new failure surface is **in the state machine definition**, not in Batch.
- **Decision: HOLD rate at `rate(10 minutes)`.** Do NOT promote to `rate(5 minutes)`. Task rule #4 governs: success rate < 50% → investigate, don't accelerate.

## Evidence

### EventBridge schedule

```
jpcite-credit-orchestrator-schedule    rate(10 minutes)    ENABLED
target: arn:aws:states:ap-northeast-1:993693061769:stateMachine:jpcite-credit-orchestrator
```

Firing cadence verified by the 10-minute spacing on every scheduled execution name (`{uuid}_{uuid}` style, regularly at ~`HH:M5:32` JST).

### Step Functions execution sample (last 30, JST 2026-05-16 13:01 → 16:25)

| status  | count | notes                                                                |
| ------- | ----- | -------------------------------------------------------------------- |
| SUCCEEDED | 0   | none — entire SM history reports empty list                          |
| FAILED  | 22    | 18 schedule-triggered + 4 manually named (credit-run / smoke / postfix) |
| RUNNING | 2     | currently inflight, will fail at the same catch state                |

Success rate (last 30, excluding RUNNING) = **0 / 22 = 0%**.

### Failure root cause (new defect surfaced after manifest_env_missing fix)

Execution history of `156eee93-...` (representative — same path on every recent failure):

```
TaskStarted          → 7 Batch jobs SUCCEEDED (J01–J07 parallel branch)
PassStateEntered     Aggregate_Run_Manifest   (builds $.aggregate_payload)
TaskStateEntered     Write_Aggregate_Manifest (s3:putObject)
TaskFailed           → s3:putObject errored (catch branch entered)
TaskStateEntered     Aggregate_Write_Failed_Notify
TaskSucceeded        cloudwatch:putMetricData
TaskStateEntered     Final_Notify_Aggregation_Ready
ExecutionFailed      States.JsonToString($.aggregate_payload) — JsonPath not found in '{}'
```

### Bug location

`infra/aws/step_functions/jpcite_credit_orchestrator.json` lines 440–507.

- `Aggregate_Run_Manifest` (Pass) writes `$.aggregate_payload` and routes to `Write_Aggregate_Manifest`.
- `Write_Aggregate_Manifest` (Task, s3:putObject) catches `States.ALL` with `ResultPath: $.error` and routes to `Aggregate_Write_Failed_Notify`.
- `Aggregate_Write_Failed_Notify` (Task, cloudwatch:putMetricData) does **not** pass `aggregate_payload` through (`ResultPath` defaults to overwriting `$`, so the metric `PutMetricDataOutput` replaces the entire state).
- `Final_Notify_Aggregation_Ready` (Task, sns:publish) then reads `$.aggregate_payload` — which is gone — and the JsonPath resolution fails at runtime.

Two independent fixes are needed before increasing the rate:

1. **State machine bug** — add `ResultPath: "$.metric_result"` to `Aggregate_Write_Failed_Notify` so it preserves `aggregate_payload`. Or branch the failed-notify path to a separate SNS state that does not require the payload (recommended — the failure path should publish a "WRITE FAILED" subject, not the success-shape payload).
2. **s3:putObject root cause** — investigate why the s3:putObject Task is itself failing into the catch branch even when the upstream Batch jobs succeeded. The catch is firing on every run, which means the success path has never been exercised in production.

## Why not promote to rate(5 minutes)

- Task rule #4: success rate < 50% blocks rate increases. Current rate = 0%.
- Doubling cadence multiplies the Batch fan-out and SF transitions without producing aggregate manifests. Cost goes up, signal stays at zero.
- EventBridge firing at 10-minute intervals already produces 144 failed executions/day. At 5-minute cadence that becomes 288/day with no qualitative change.

## Recommended next steps (separate work)

- Fix `Aggregate_Write_Failed_Notify` `ResultPath` so the SNS final-notify state stops crashing on the failure path.
- Diagnose `Write_Aggregate_Manifest` s3:putObject failure (IAM permission to the `jpcite-credit-993693061769-202605-reports` bucket? Tagging policy mismatch on the `Project=jpcite&CreditRun=2026-05&AutoStop=2026-05-29` string?).
- Re-run smoke after fixes land; once a real SUCCEEDED execution exists and the next 6-12 scheduled runs come in green, revisit rate promotion to `rate(5 minutes)`.

## Append-only marker

- Schedule state at decision time: `rate(10 minutes)` ENABLED, target wired, no rate change applied.
- Profile used for verification: `bookyou-recovery`, region `ap-northeast-1`.
- Live confirmation timestamp: 2026-05-16 (JST), commit `d2fd49723` deployed.
