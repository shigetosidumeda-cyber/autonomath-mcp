# AWS Snapshot — 2026-05-17 AM (rate-limit-reset verify)

**Lane:** solo  
**Mode:** READ-ONLY (describe/list/get only — no `--unlock-live-aws-commands`)  
**Profile:** `bookyou-recovery` (UserId AIDA6OXFY2KEYSUNJDC63, Admin)  
**Account:** 993693061769  
**Region:** ap-northeast-1 (workload), us-east-1 (billing/Lambda/Budget)  
**Hard-stop:** $19,490 never-reach — current MTD < $0.10 → trivially safe.

---

## 1. Identity Confirmed

```
UserId : AIDA6OXFY2KEYSUNJDC63
Account: 993693061769
Arn    : arn:aws:iam::993693061769:user/bookyou-recovery-admin
```

PASS — matches SOT.

---

## 2. Cost Ledger (CE, 2026-05-15 → 2026-05-17)

| Day | Service | Gross | Net |
|---|---|---|---|
| 2026-05-15 → 16 | (none) | $0.00 | $0.0000 |
| 2026-05-16 → 17 | Amazon S3 | $0.02 | $0.0168 |
| 2026-05-16 → 17 | Amazon ECS | $0.00 | $0.0013 |
| 2026-05-16 → 17 | **TOTAL** | **$0.02** | **$0.0181** |

**MTD total: $0.02 gross / $0.018 net** — matches SOT exactly ($0.02 / $0.018). No drift.

---

## 3. Batch GPU Job Lifecycle (`jpcite-credit-ec2-spot-gpu-queue`, ap-northeast-1)

### RUNNING (4) — matches SOT "4 GPU jobs RUNNING"

| Job Name | createdAt (epoch ms) |
|---|---|
| jpcite-gpu-burn-faiss-programs-deep-20260516T071440Z | 1778915680261 |
| jpcite-gpu-burn-faiss-laws-deep-20260516T071440Z | 1778915680410 |
| jpcite-gpu-burn-faiss-cross-cohort-20260516T071440Z | 1778915680557 |
| jpcite-gpu-burn-finetune-minilm-programs-20260516T071440Z | 1778915680702 |

### SUCCEEDED (0)

### FAILED (3) — pre-existing from 2026-05-16 06:11 batch (not new)

| Job Name |
|---|
| jpcite-gpu-faiss-programs-20260516T061111Z |
| jpcite-gpu-faiss-laws-20260516T061117Z |
| jpcite-gpu-faiss-adoption-20260516T061120Z |

### RUNNABLE (2) — queued / waiting Spot capacity

| Job Name |
|---|
| jpcite-gpu-burn-finetune-minilm-laws-20260516T071440Z |
| jpcite-gpu-burn-finetune-minilm-adoption-20260516T071440Z |

### STARTING (0)

**Net:** 4 RUNNING (matches SOT) + 2 RUNNABLE queued (waiting on Spot) + 3 historic FAILED (legacy from yesterday morning). No unexpected new burst.

---

## 4. Hard-Stop Defense — 5-line State

### CloudWatch Billing Alarms (us-east-1)

| Alarm | State |
|---|---|
| jpcite-credit-billing-early-warning-13000 | **OK** |
| jpcite-credit-billing-warn-14000 | **OK** |
| jpcite-credit-billing-slowdown-17000 | **OK** |
| jpcite-credit-billing-stop-18700 | **OK** |

4× OK as expected per SOT.

### Budget Action (us-east-1)

Budget name: `jpcite-credit-run-stop-18900` (corrected from canonical `jpcite-credit-budget`).

| ActionId | Status | ApprovalModel |
|---|---|---|
| 36b0120b-99bd-47f1-a68a-622f16f1995b | **STANDBY** | AUTOMATIC |

1× STANDBY as expected per SOT.

**Hard-stop summary: 4× OK + 1× STANDBY = 5/5 ARMED**. No drift.

### Related Budgets (info)

| Budget | Limit ($) |
|---|---|
| BookYou-Emergency-Usage-Guard | 100.0 |
| jpcite-credit-run-slowdown-18300 | 18,300.0 |
| jpcite-credit-run-stop-18900 | 18,900.0 |
| jpcite-credit-run-watch-17000 | 17,000.0 |

---

## 5. SageMaker InProgress Transform Jobs (ap-northeast-1)

(no rows returned) — **0 InProgress**.

PM10 monitor closed cleanly per existing task #251. No active transform burn.

---

## 6. S3 Canary Buckets — Verified Reachable

Canonical SOT names corrected (no `jpcite-canary-derived-993693061769-ap-northeast-1` exists; real names below):

| Bucket | Reachable |
|---|---|
| jpcite-credit-993693061769-202605-athena-results | yes |
| jpcite-credit-993693061769-202605-derived | yes (KeyCount probe OK) |
| jpcite-credit-993693061769-202605-raw | yes (KeyCount probe OK) |
| jpcite-credit-993693061769-202605-reports | yes |
| jpcite-credit-textract-apse1-202605 | yes |

(Full recursive sizing skipped to avoid List cost — CloudWatch daily metric not yet populated for these prefixes.)

---

## 7. Step Functions Health (ap-northeast-1)

| State Machine | Status |
|---|---|
| jpcite-credit-orchestrator | **ACTIVE** |

### EventBridge Rules (ap-northeast-1)

| Rule | State |
|---|---|
| jpcite-credit-burn-metric-5min | **ENABLED** (CW emitter, expected) |
| jpcite-credit-orchestrator-schedule | **DISABLED** (Phase 9 plan gate, expected) |

EB DISABLED gate intact — wet-run requires user explicit + UNLOCK token, neither granted. Compliant.

---

## 8. Lambda Inventory

### us-east-1

| Function | Runtime | LastModified |
|---|---|---|
| jpcite-credit-auto-stop | python3.12 | 2026-05-16T06:53:48Z |

### ap-northeast-1

| Function | Runtime | LastModified |
|---|---|---|
| jpcite-cf-loadtest | python3.12 | 2026-05-16T10:03:50Z |
| jpcite-credit-burn-metric-emitter | python3.12 | 2026-05-16T09:43:57Z |
| jpcite-credit-canary-attestation-emitter | python3.12 | 2026-05-16T09:44:51Z |

3 Lambdas in ap-northeast-1 + 1 in us-east-1 (auto-stop). All LastModified = 2026-05-16 (pre-pause), no surprise post-rate-limit deployment. Matches SOT "burn-metric + attestation LIVE".

---

## Drift Detection — Summary

| Dimension | SOT | Observed | Drift |
|---|---|---|---|
| Identity | bookyou-recovery-admin | confirmed | none |
| 5-line alarms | 4× OK | 4× OK | none |
| Budget Action | STANDBY | STANDBY | none |
| RUNNING GPU jobs | 4 | 4 | none |
| CE MTD | $0.02 gross / $0.018 net | $0.02 / $0.018 | none |
| SageMaker InProgress | 0 (PM10 closed) | 0 | none |
| EB orchestrator schedule | DISABLED | DISABLED | none |
| Lambda count | 3 ap-ne-1 + 1 us-east-1 | 3 + 1 | none |

**No drift detected. All systems nominal. Hard-stop 5-line armed.**

### Side note (not drift, name correction needed in SOT)

- SOT references budget name `jpcite-credit-budget` — actual canonical name is **`jpcite-credit-run-stop-18900`**.
- SOT references S3 bucket `jpcite-canary-derived-993693061769-ap-northeast-1` — actual is **`jpcite-credit-993693061769-202605-derived`** (`-credit-` not `-canary-`, with `-202605-` date prefix).

Recommend updating runbook canonical names on next SOT pass.
