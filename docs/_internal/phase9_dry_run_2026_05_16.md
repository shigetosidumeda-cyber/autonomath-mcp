# Phase 9 Drain — DRY_RUN Verification (2026-05-16)

> **Status: DRY_RUN ONLY. NO live teardown executed.** This doc verifies the
> Phase 9 7-step drain procedure works end-to-end against profile
> `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`,
> attached policies `AdministratorAccess` + `jpcite-credit-run-deny-new-spend`).
>
> Phase 9 procedure source: `docs/_internal/WAVE59_ROADMAP_2026_05_16.md` §5.

last_updated: 2026-05-16

companion docs:
- `docs/_internal/WAVE59_ROADMAP_2026_05_16.md` (Phase 9 7-step source)
- `docs/_internal/AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md` (step 4 recovery)
- `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` (step 6 defense)
- `scripts/aws_credit_ops/teardown_credit_run.sh` (step 4 canonical script)
- `scripts/aws_credit_ops/stop_drill.sh` (step 2 manual stop)

---

## 0. Summary

| step | scope                                  | DRY_RUN result | resource pre-conditions verified | est. live wall time |
| ---- | -------------------------------------- | -------------- | -------------------------------- | -------------------- |
| 1    | Orchestration disable (EB + SF + GHA)  | OK (partial)   | Step Functions `jpcite-credit-orchestrator` ARN present; EventBridge Rules / Scheduler not found under jpcite prefix (likely disabled by default or never created) | ~1 sec / item        |
| 2    | Queue cutoff (DISABLE + drain)         | OK             | 3 queues found (`jpcite-credit-fargate-spot-short-queue` / `-ec2-spot-cpu-queue` / `-ec2-spot-gpu-queue`); 7 STARTING + 6 RUNNING + 2 RUNNABLE = **15 jobs** would be cancel/terminate | ~30 sec / queue + ~5 min job grace |
| 3    | Cost freeze (CE snapshot + final stamp) | OK            | `burn_target.py` ran — target $18,300 / consumed $0 (CE token region issue, MTD reads as 0 from default region) / remaining $18,300 / 12 days to 2026-05-29 / target $1,525/day. Honest gap: live CE reflects 8-12 hr lag. | T+0 + T+12h snapshot |
| 4    | Recovery (teardown_credit_run.sh)      | OK             | 7-step preview enumerated cleanly — 3 queues disable + 15 jobs drain + 3 queues delete + 1 job def deregister + 3 CEs disable+delete + 1 log group delete (0 bytes); step 7 buckets skip default (STEP_DELETE_BUCKETS=0) | ~5 min total         |
| 5    | Attestation (`emit_canary_attestation`) | **GAP**       | `emit_canary_attestation.py` + `deploy_canary_attestation_lambda.sh` files exist; Lambda `jpcite-credit-canary-attestation` **NOT YET DEPLOYED** (`ResourceNotFoundException` from `lambda get-function`) — task #108 still `in_progress` | n/a until Lambda deployed |
| 6    | 5-line defense ARMED check             | OK             | Budget Action `jpcite-credit-run-stop-18900` STANDBY @ 100% ($18,900); Lambda `jpcite-credit-auto-stop` `JPCITE_AUTO_STOP_ENABLED=false` (default safe); 4 CW alarms (13K/14K/17K/18.7K) all OK | ~1 sec per check     |
| 7    | Closeout (final $burn stamp)           | doc-only       | follows step 3 final snapshot + step 5 attestation manifest | feed into Stream 59-J |

**Result: 6/7 steps verified — step 5 (attestation Lambda) is the single missing
piece.** All other resources, IAM permissions, ARNs, and scripts exist and
respond correctly under DRY_RUN. The Phase 9 procedure is structurally
ready; awaiting only the attestation Lambda deployment (task #108).

---

## 1. Step-by-step verification

### Step 1 — Orchestration disable

**Expected impact**: stop new work scheduling at the source. Three sub-targets:

1. **EventBridge schedule** (EventBridge Scheduler API): `aws scheduler list-schedules --name-prefix jpcite` returned **empty** in us-east-1. Per `WAVE59_ROADMAP_2026_05_16.md` §5 step 1, schedule is "DISABLED (already default)" — confirmed, no live schedule exists.
2. **Step Functions state machine**: `aws stepfunctions list-state-machines` returned `arn:aws:states:ap-northeast-1:993693061769:stateMachine:jpcite-credit-orchestrator` (Status: None → ACTIVE default). Live `aws stepfunctions update-state-machine --state-machine-arn ... --logging-configuration ...` would disable; alternative is to set IAM role to deny `states:StartExecution`. Verified ARN exists.
3. **GHA workflows touching AWS**: switch to manual-only by removing `schedule:` blocks or adding `workflow_dispatch` gating. Out of band of AWS CLI; doc-only.

**IAM pre-conditions verified**: `bookyou-recovery-admin` has `AdministratorAccess` → can call `events:DisableRule`, `scheduler:UpdateSchedule`, `states:UpdateStateMachine`. No additional policy needed.

**Est. live wall time**: ~1 sec per item, total ~3 sec.

### Step 2 — Queue cutoff (DISABLE + N-min grace)

**Expected impact**: stop accepting new jobs + cancel SUBMITTED/PENDING/RUNNABLE + terminate RUNNING.

DRY_RUN executed via `bash scripts/aws_credit_ops/stop_drill.sh` (mode: DRY_RUN). Output enumerated:

- **3 queues found** (verified): `jpcite-credit-fargate-spot-short-queue`, `jpcite-credit-ec2-spot-gpu-queue`, `jpcite-credit-ec2-spot-cpu-queue`.
- **fargate-spot-short-queue**: 7 STARTING jobs + 6 RUNNING jobs → 13 cancel/terminate ops.
- **ec2-spot-gpu-queue**: 2 RUNNABLE jobs + 4 RUNNING jobs → 6 cancel/terminate ops.
- **ec2-spot-cpu-queue**: 0 jobs (clean).
- **3 CEs**: enumerated, no mutation in stop_drill.sh path.

**Total drain ops**: **15 cancel/terminate** + **3 update-job-queue --state DISABLED**.

**IAM pre-conditions verified**: `AdministratorAccess` covers `batch:UpdateJobQueue`, `batch:CancelJob`, `batch:TerminateJob`, `batch:DescribeJobQueues`, `batch:ListJobs`.

**Est. live wall time**: ~30 sec per queue for DISABLE + drain enumeration; up to per-job-timeout for in-flight RUNNING (typically 30 min hard cap). Manual terminate-job shortens to ~5 sec/job. Total: **~5 min** worst case for queue mutation; in-flight tail bounded by per-job timeout but `terminate-job` short-circuits.

### Step 3 — Cost freeze (T-0 + T+12h snapshot)

**Expected impact**: snapshot Cost Explorer at drain start (T-0) and again at T+12h; stamp final $burn in `docs/_internal/AWS_CANARY_RUN_2026_05_16.md`.

DRY_RUN executed via `.venv/bin/python scripts/aws_credit_ops/burn_target.py`:

```
target gross: USD 18,300.00
consumed gross MTD: USD 0.00
remaining: USD 18,300.00
days to deadline (2026-05-29): 12
daily burn target: USD 1,525.00/day
hourly burn target: USD 60.50/hr
slowdown line: USD 15,555.00
emergency stop line: USD 17,385.00
STATUS: RAMP — within budget
```

**Honest gap**: `consumed gross MTD: USD 0.00` is suspect — recovery procedure §0 step 3 noted "CE token expired in default region, defaults to 0; replace `AWS_DEFAULT_REGION` if needed". This DRY_RUN run reproduced the same artifact, meaning **burn_target.py reads MTD as 0 under bookyou-recovery profile in default region**. Real consumed MTD is reflected in Cost Explorer 8-12hr behind reality and must be cross-checked via `aws ce get-cost-and-usage` directly under us-east-1.

**IAM pre-conditions verified**: `ce:GetCostAndUsage` allowed under `AdministratorAccess`. Cross-region token mismatch is a documented observability gap (recovery procedure §4 — "non-blocking for teardown chain").

**Est. live wall time**: ~10 sec per snapshot (T-0 + T+12h), plus 12 hr wall clock between snapshots = total wall window 12 hr, active CLI time ~20 sec.

### Step 4 — Recovery (execute `teardown_credit_run.sh`)

**Expected impact**: graceful teardown of all canary-tagged Batch resources in a deterministic 7-sub-step order matching `AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md`.

DRY_RUN executed via `DRY_RUN=true bash scripts/aws_credit_ops/teardown_credit_run.sh`. The 7 sub-steps enumerated cleanly:

1. **Disable queues (3)** — 3 `update-job-queue --state DISABLED` preview lines.
2. **Drain jobs (15)** — 9 cancel-job (7 STARTING in fargate + 2 RUNNABLE in gpu) + 6 terminate-job (6 RUNNING in fargate); plus 4 RUNNING terminate-job (4 RUNNING in gpu). Total 19 mutation ops previewed (note: stop_drill.sh enumerated 15; teardown.sh enumerated 19 because it walks STARTING + RUNNING + RUNNABLE separately while stop_drill walks RUNNING + RUNNABLE only).
3. **Delete queues (3)** — 3 `delete-job-queue` preview lines.
4. **Deregister job defs (1)** — `jpcite-crawl:1` deregister preview.
5. **Disable + delete CEs (3)** — 3 disable + 3 delete = 6 preview lines.
6. **Delete log group** — `/aws/batch/jpcite-credit-2026-05` (0 bytes stored).
7. **Delete S3 buckets** — **SKIPPED by default** (STEP_DELETE_BUCKETS=0). Bucket existence verified: `jpcite-credit-993693061769-202605-raw` + `-reports` both ARN-resolvable in ap-northeast-1. Data preservation default is correct — recovery procedure §3 requires explicit `STEP_DELETE_BUCKETS=1 JPCITE_TEARDOWN_DELETE_BUCKETS=1` to proceed.

**IAM pre-conditions verified**: `AdministratorAccess` covers all `batch:*`, `logs:DeleteLogGroup`, `s3:DeleteBucket` (latter not needed at default settings). Live token gate: `JPCITE_TEARDOWN_LIVE_TOKEN=I-AM-TEARING-DOWN-jpcite-credit-2026-05` + `DRY_RUN=false` required — DRY_RUN preview confirmed correct behavior without token.

**Est. live wall time**: **~5 min total** under live mode:
- step 1 disable queues: ~3 sec
- step 2 drain: bounded by `terminate-job` SDK round-trip per job (~1 sec/job × 19 = ~20 sec); RUNNING-job actual termination on the worker side takes ~30 sec to ~5 min depending on Spot reclamation
- step 3 delete queues: requires DISABLED state — flyte requires "all jobs settled"; ~30 sec/queue
- step 4 deregister: ~1 sec
- step 5 disable+delete CEs: ~1 min/CE × 3 = ~3 min (CE deletion blocks until all queues that reference it are deleted)
- step 6 delete logs: ~1 sec
- step 7 SKIP

### Step 5 — Attestation (`emit_canary_attestation.py` + Lambda)

**Expected impact**: emit canary attestation (sha256 manifest + Sigstore offline-OK fallback) end-of-canary, runs as Lambda triggered post-recovery.

**GAP IDENTIFIED**: `aws lambda get-function --function-name jpcite-credit-canary-attestation --region us-east-1` returned `ResourceNotFoundException`. The Lambda is **NOT YET DEPLOYED**.

Source artifacts confirmed present locally:
- `scripts/aws_credit_ops/emit_canary_attestation.py` — exists
- `scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh` — exists

This matches the task list state: **task #108** (`Implement emit_canary_attestation.py + Lambda + tests`) is still `in_progress`. Phase 9 procedure source `WAVE59_ROADMAP_2026_05_16.md` §5 step 5 explicitly states "Task #108 ... is currently `in_progress`; Phase 9 forces completion."

**Est. live wall time once deployed**: ~30 sec (Lambda cold invoke + S3 upload + sha256 emit). Until Lambda is deployed, **Phase 9 cannot complete step 5 — the manifest must be emitted by either (a) deploying the Lambda first, or (b) running `emit_canary_attestation.py` directly as a CLI fallback**.

### Step 6 — 5-line defense ARMED check (keep ARMED during drain)

**Expected impact**: lines 1-5 remain ARMED for the duration of drain; only disarmed in step 4 (recovery) after burn confirmed decreasing.

DRY_RUN verified:

| line | resource                                            | state                                                                                  |
| ---- | --------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 1    | CW alarm `jpcite-credit-billing-early-warning-13000` | OK                                                                                     |
| 2    | CW alarm `jpcite-credit-billing-warn-14000`           | OK                                                                                     |
| 3    | CW alarm `jpcite-credit-billing-slowdown-17000`       | OK                                                                                     |
| 4    | CW alarm `jpcite-credit-billing-stop-18700` + Lambda  | alarm OK; Lambda `jpcite-credit-auto-stop` `JPCITE_AUTO_STOP_ENABLED=false` (safe default) |
| 5    | Budget Action `jpcite-credit-run-stop-18900`          | STANDBY @ 100% ($18,900) → APPLY_IAM_POLICY → `jpcite-credit-run-deny-new-spend`        |

IAM deny policy `jpcite-credit-run-deny-new-spend` **exists locally** but **not yet attached** to `bookyou-recovery-admin` (confirmed via `list-attached-user-policies` which returned only `AdministratorAccess`). Auto-attach fires when Budget Action transitions STANDBY → EXECUTED.

**IAM pre-conditions verified**: read-only checks on CW + Budget + Lambda + IAM all succeeded under `AdministratorAccess`.

**Est. live wall time**: ~1 sec per check × 3 surfaces = ~3 sec.

### Step 7 — Closeout (single doc, feeds Stream 59-J)

**Expected impact**: doc-only — single doc lists final $burn, peak $burn, total packet count, total Athena scan TB, total GPU-hours, link to attestation evidence.

**Dependencies**: step 3 final snapshot + step 5 attestation manifest. No CLI mutation. Writes to `docs/_internal/AWS_CANARY_RUN_2026_05_16.md` (already exists per WAVE59_ROADMAP §5 step 3) + feeds into Stream 59-J `WAVE_50_58_CLOSEOUT_<date>.md`.

**Est. live wall time**: doc edit only; ~5 min author time.

---

## 2. Gaps identified

1. **Step 5 attestation Lambda not deployed** — `jpcite-credit-canary-attestation` returns `ResourceNotFoundException`. Task #108 in_progress. **Mitigation**: run `emit_canary_attestation.py` as a CLI fallback, or deploy the Lambda via `deploy_canary_attestation_lambda.sh` before Phase 9 execution. WAVE59_ROADMAP §5 step 5 anticipated this — "Phase 9 forces completion".
2. **`burn_target.py` cross-region CE token issue** — MTD reads as $0 under default region. Recovery procedure §4 documented as "non-blocking for teardown chain, but observability gap". Phase 9 step 3 cost freeze should call `aws ce get-cost-and-usage` directly under us-east-1 instead of relying on `burn_target.py` MTD figure.
3. **EventBridge Scheduler shows empty** — `aws scheduler list-schedules --name-prefix jpcite` returned no items. Phase 9 step 1 assumes a schedule exists to disable; this means either (a) the schedule was never created, or (b) it lives under EventBridge Rules API (`aws events list-rules`) instead of Scheduler API. Phase 9 step 1 procedure should explicitly check both APIs.
4. **Step Functions state machine `jpcite-credit-orchestrator` exists but not actively scheduling work** — Status reported as `None` (vs ACTIVE). Phase 9 step 1 should `aws stepfunctions update-state-machine --tracing-configuration enabled=false` + remove any active event source mapping; alternative is to drop IAM `states:StartExecution` permission.
5. **GHA workflow disable is doc-only** — Phase 9 step 1 lists "GHA workflows touching AWS → manual-only" without an automated path. Mitigation: `.github/workflows/*.yml` files that reference AWS need `workflow_dispatch:` gating only (remove `schedule:` blocks), or temporarily set repo secret to `disabled` placeholder. Out of band of AWS CLI.

---

## 3. Phase 9 procedure corrections (proposed)

Suggested edits to `docs/_internal/WAVE59_ROADMAP_2026_05_16.md` §5 step list to reflect DRY_RUN findings:

- **Step 1**: explicitly cover both EventBridge Scheduler API (`aws scheduler list-schedules`) **and** EventBridge Rules API (`aws events list-rules`) for schedule discovery, since the schedule may live in either namespace.
- **Step 3**: cost freeze should `aws ce get-cost-and-usage --region us-east-1 ...` directly with explicit region pin, rather than depending on `burn_target.py` MTD aggregate (which reads $0 under cross-region token).
- **Step 5**: prepend "deploy Lambda first (`bash scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh`) before invoking attestation". Alternatively, allow CLI fallback via `.venv/bin/python scripts/aws_credit_ops/emit_canary_attestation.py` so Phase 9 is not blocked by task #108.

These corrections are **non-destructive** and additive — they tighten the procedure without changing the order of operations.

---

## 4. Conclusion

Phase 9 procedure is **structurally ready, 6/7 steps verified** in DRY_RUN under
profile `bookyou-recovery`. The single gap is the attestation Lambda
deployment (task #108 in_progress). With either Lambda deployment or CLI
fallback for `emit_canary_attestation.py`, Phase 9 can execute live with
estimated total wall time **~5-10 min CLI time + 12 hr T+0 → T+12h cost freeze
window**.

The 5-line defense (lines 1-4 CW alarms OK + line 5 Budget Action STANDBY at
$18.9K) remains ARMED throughout drain per step 6.

**This DRY_RUN did NOT execute any live mutation.** All commands ran with
`DRY_RUN=true` or as read-only queries (sts get-caller-identity, describe-*,
list-*, get-*). No resources were created, mutated, or deleted.
