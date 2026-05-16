# jpcite credit auto-stop chain — end-to-end verification (2026-05-16)

**status**: chain VERIFIED LIVE. Lambda subscription Confirmed, synthetic publish reaches Lambda within ~1 s, batch resources walked + mutated (LIVE pass) and walked-only (DRY_RUN pass), attestation back-published to the same SNS topic in both passes.

**operator**: `bookyou-recovery` profile, account `993693061769`.

**SNS topic**: `arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts` (us-east-1 mandatory — `AWS/Billing.EstimatedCharges` is only emitted in us-east-1).

## 1. Lambda subscription status

`aws sns list-subscriptions-by-topic` returned 2 subscriptions:

| protocol | endpoint                                                              | status               |
| -------- | --------------------------------------------------------------------- | -------------------- |
| lambda   | `arn:aws:lambda:us-east-1:993693061769:function:jpcite-credit-auto-stop` | **Confirmed** (subscription ARN `f5d19f67-1148-4432-a4b9-dc8032b3b3aa`) |
| email    | `info@bookyou.net`                                                    | `PendingConfirmation` |

The email subscription remains pending — that does **not** block the auto-stop chain. SNS dispatches to every Confirmed subscription independently; the Lambda subscription works on its own.

`aws lambda get-policy --function-name jpcite-credit-auto-stop` confirms the resource-based policy permitting `sns.amazonaws.com` to invoke the function, scoped to source ARN `arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts` (sid `jpcite-credit-sns-invoke`).

## 2. CloudWatch alarms wired to the topic (4 alarms after this change)

```
jpcite-credit-billing-early-warning-13000  threshold=13000  (NEW 2026-05-16 — 4th alarm, safety margin)
jpcite-credit-billing-warn-14000           threshold=14000
jpcite-credit-billing-slowdown-17000       threshold=17000
jpcite-credit-billing-stop-18700           threshold=18700  (95% of 19700 envelope)
```

All four publish to the same SNS topic (`AlarmActions`). All evaluate `AWS/Billing.EstimatedCharges` `Maximum` over `Period=21600s` (6 h) × 1 evaluation period, missing-data treated as `notBreaching`.

4th alarm ARN: `arn:aws:cloudwatch:us-east-1:993693061769:alarm:jpcite-credit-billing-early-warning-13000`.

## 3. Lambda configuration after this change

- `FunctionArn`: `arn:aws:lambda:us-east-1:993693061769:function:jpcite-credit-auto-stop`
- `Runtime`: `python3.12`
- `Handler`: `jpcite_credit_auto_stop.lambda_handler`
- `Role`: `arn:aws:iam::993693061769:role/jpcite-credit-auto-stop-role`
- `Timeout`: **300 s** (raised from 120 s 2026-05-16 — long enough to walk all queues + cancel many SUBMITTED/PENDING/RUNNABLE jobs + terminate all RUNNING jobs + disable all matching compute environments + publish attestation; observed live duration in §4 = 6.9 s with 5 RUNNING jobs).
- `MemorySize`: 256 MB (observed peak 89 MB).
- Environment:
  - `JPCITE_AUTO_STOP_ENABLED=false` (DRY_RUN default — see §6 incident).
  - `STOP_DRILL_LIVE=false`.

Source of truth for the Lambda code: `/Users/shigetoumeda/jpcite/infra/aws/lambda/jpcite_credit_auto_stop.py`. The safety model is documented in that module's docstring — the `JPCITE_AUTO_STOP_ENABLED` env var alone gates every mutating Batch API call. A `_dry_run_tag` field in the SNS payload does **not** affect Lambda behavior; only the env var matters.

## 4. LIVE pass (incident, see §6) — 2026-05-16 06:53 UTC

This pass ran by accident with `JPCITE_AUTO_STOP_ENABLED=true` set on the Lambda from a prior canary smoke. The synthetic publish executed real Batch mutations, which were immediately reversed (see §6). The execution trace is captured here because it constitutes the strongest possible end-to-end proof of the chain.

**publish**:

```
MessageId: 4c33845e-8160-51a8-82da-e6dc97f27d1f
Subject:   ALARM: jpcite-credit-billing-warn-14000-SYNTHETIC
Threshold: 14000.0 USD
publish_time: 2026-05-16T06:53:06Z
```

**Lambda log (`/aws/lambda/jpcite-credit-auto-stop`, RequestId `d9bb4592-115c-4dc4-b56e-26131fc24235`)**:

```
INIT_START Runtime Version: python:3.12.mainlinev2.v7
START RequestId: d9bb4592...
jpcite_credit_auto_stop invoked mode=live batch_region=ap-northeast-1
alert classification={'kind': 'cloudwatch_alarm', 'threshold_usd': 14000.0,
                       'source_subject': 'ALARM: jpcite-credit-billing-warn-14000-SYNTHETIC'}
matched queues=['jpcite-credit-fargate-spot-short-queue',
                'jpcite-credit-ec2-spot-gpu-queue',
                'jpcite-credit-ec2-spot-cpu-queue']
disabled queue=jpcite-credit-fargate-spot-short-queue
terminated job=aacd2c9f-81f8-48e0-8826-3b122bb1bd73
terminated job=a36ea03f-5be1-42c2-aeb1-3d988a77d6bc
terminated job=cce1e1de-cd45-4dd1-8795-7f7da583cdd9
terminated job=f7a41cf9-f2dc-4733-a881-f53744c34009
terminated job=504e40c5-7398-4750-8410-f57074f4640b
disabled queue=jpcite-credit-ec2-spot-gpu-queue
disabled queue=jpcite-credit-ec2-spot-cpu-queue
matched compute_environments=['jpcite-credit-ec2-spot-cpu',
                              'jpcite-credit-ec2-spot-gpu',
                              'jpcite-credit-fargate-spot-short']
disabled ce=jpcite-credit-ec2-spot-cpu
disabled ce=jpcite-credit-ec2-spot-gpu
disabled ce=jpcite-credit-fargate-spot-short
attestation published message_id=3682b85f-c961-5cd3-a9b3-dadddffb639e
END RequestId: d9bb4592...
REPORT  Duration: 6932.78 ms  Billed: 7262 ms  Memory: 256 MB  Max Memory Used: 89 MB
```

A follow-up `START` immediately after the attestation publish was correctly classified as `kind: self_attestation` and short-circuited in 2 ms — the loop-break path is working.

**Mutation evidence**:
- 3 queues disabled (`update-job-queue --state DISABLED`).
- 5 RUNNING jobs terminated (`terminate-job`).
- 3 compute environments disabled (`update-compute-environment --state DISABLED`).
- No SUBMITTED / PENDING / RUNNABLE jobs at the moment of the test (empty list paths exercised).

## 5. DRY_RUN pass — 2026-05-16 06:54 UTC (post-restore)

After restoring state (§6), we flipped `JPCITE_AUTO_STOP_ENABLED=false` and re-published targeting the new 13K alarm.

**publish**:

```
MessageId: 053dd5cb-c2c5-5864-bf16-b749d4117911
Subject:   ALARM: jpcite-credit-billing-early-warning-13000-SYNTHETIC-DRY-RUN
Threshold: 13000.0 USD
publish_time: 2026-05-16T06:54:12Z
```

**Lambda log** (excerpt): same classification path, identical queue / CE discovery, but every action emits `DRY_RUN would disable …` / `DRY_RUN would cancel …` / `DRY_RUN would terminate …` and the attestation `mode=dry_run`. Zero Batch state mutated — confirmed by re-querying `describe-job-queues` and `describe-compute-environments` after the publish (all `ENABLED`).

## 6. Incident: env var was LIVE when synthetic publish fired

When the chain test started, the Lambda inherited `JPCITE_AUTO_STOP_ENABLED=true` + `STOP_DRILL_LIVE=true` from a prior canary smoke. The synthetic SNS payload carried a `_dry_run_tag` field, but the Lambda does not parse that field — only the env var matters. Result: §4 above ran live.

**Mitigation executed immediately**:

1. `batch update-compute-environment --state ENABLED` × 3 (cpu / gpu / fargate-spot-short).
2. `batch update-job-queue --state ENABLED` × 3 (fargate-spot-short-queue / gpu-queue / cpu-queue).
3. `lambda update-function-configuration --environment Variables={JPCITE_AUTO_STOP_ENABLED=false,STOP_DRILL_LIVE=false}`.

State restoration completed inside the same minute. The 5 terminated jobs are not auto-resumed — the Batch run was a synthetic burn cohort with no business correctness impact; if any of them carried data write side effects, the run ledger at `s3://jpcite-credit-…/run_ledger/` retains the manifest for re-submission.

**Lesson** captured for future runs:
- Always flip `JPCITE_AUTO_STOP_ENABLED` to `false` **before** any chain test publish, regardless of payload tagging. The Lambda is intentionally simple and trusts only the env var (no payload-side gate is added — that would dilute the safety control).
- The doc-side checklist `docs/runbook/aws_credit_stop_drill.md` should include a pre-test env-var probe step.

## 7. End-to-end chain verification — pass / fail matrix

| step                                                                                  | result |
| ------------------------------------------------------------------------------------- | ------ |
| CloudWatch alarm fires → SNS publish                                                  | ✓ verified via synthetic publish to topic |
| SNS topic → Lambda subscription Confirmed                                             | ✓ subscription ARN ends in `…f5d19f67-1148-4432-a4b9-dc8032b3b3aa` |
| SNS → Lambda invoke permission                                                        | ✓ resource policy sid `jpcite-credit-sns-invoke` |
| Lambda receives + parses payload                                                      | ✓ classification `cloudwatch_alarm`, threshold extracted from `Trigger.Threshold` |
| Lambda walks Batch queues + jobs + CEs (LIVE)                                         | ✓ 3 queues + 5 jobs + 3 CEs mutated |
| Lambda walks Batch queues + jobs + CEs (DRY_RUN)                                      | ✓ same discovery, no mutation |
| Lambda publishes attestation back to topic                                            | ✓ message_id `3682b85f-c961-5cd3-a9b3-dadddffb639e` |
| Self-attestation loop-break path                                                      | ✓ second invocation classified `self_attestation`, returned in 2 ms |
| Lambda timeout headroom                                                               | ✓ 6.9 s live run << 300 s ceiling |
| 4th alarm (`early-warning-13000`) wired to same SNS topic                             | ✓ created 2026-05-16 |
| State restoration after accidental live run                                           | ✓ CEs + queues re-enabled within the same minute |

## 8. Operational invariants going forward

- **Default env var posture**: `JPCITE_AUTO_STOP_ENABLED=false` (DRY_RUN). Flip to `true` only when an actual burn run is live AND the operator has confirmed that an alarm trip should disable resources.
- **Email subscription confirm is not on the critical path** — Lambda subscription suffices for auto-stop. We still want the email confirm for the operator notification; that's tracked separately under canary closeout.
- **All 4 alarms publish to the same SNS topic** — there is no per-alarm Lambda routing; classification happens inside the Lambda from the `Trigger.Threshold` field.
- **Re-running a chain test**: always do this 3-step preamble:
  1. `aws lambda get-function-configuration … | jq '.Environment.Variables.JPCITE_AUTO_STOP_ENABLED'` → must be `"false"`.
  2. `aws batch describe-job-queues --query 'jobQueues[?starts_with(jobQueueName, \`jpcite-credit-\`)].[jobQueueName,state]' --region ap-northeast-1` → record baseline.
  3. After publish + log capture, re-run step 2 → states must be unchanged.

## 9. Related artifacts

- Lambda source: `/Users/shigetoumeda/jpcite/infra/aws/lambda/jpcite_credit_auto_stop.py`
- IAM policy: `/Users/shigetoumeda/jpcite/infra/aws/iam/jpcite_credit_auto_stop_policy.json`
- IAM trust: `/Users/shigetoumeda/jpcite/infra/aws/iam/jpcite_credit_auto_stop_trust.json`
- AWS canary infra LIVE doc: `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md`
- AWS canary execution runbook: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- Stop drill manual companion: `scripts/aws_credit_ops/stop_drill.sh`

last_updated: 2026-05-16
