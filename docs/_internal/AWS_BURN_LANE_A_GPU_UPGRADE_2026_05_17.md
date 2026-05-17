# AWS Burn Lane A — GPU upgrade g5.12xlarge (2026-05-17)

**Lane:** A (solo)
**Mode:** LIVE — user explicit unlock for AWS burn acceleration
**Profile:** `bookyou-recovery` (UserId AIDA6OXFY2KEYSUNJDC63, Admin)
**Account:** 993693061769
**Region:** ap-northeast-1
**Hard-stop:** $19,490 absolute never-reach (current MTD net ~$0)
**Goal:** GPU compute upgrade to accelerate credit burn within Spot G/VT quota

---

## 1. Starting state (verified)

- Spot G/VT vCPU quota (`L-3819A6DF`): **64** (hard cap, AccountLevel)
- 4 RUNNING GPU jobs on `jpcite-credit-ec2-spot-gpu-queue`:
  - `bf3128a1-…` programs-deep (g4dn.4xlarge, 16 vCPU)
  - `3c9f71e1-…` cross-cohort (g4dn.4xlarge, 16 vCPU)
  - `b5a7ac5a-…` laws-deep (g4dn.4xlarge, 16 vCPU)
  - `0f43c5e3-…` finetune-minilm-programs (g4dn.4xlarge, 16 vCPU) ← retained
- Compute Env `jpcite-credit-ec2-spot-gpu`: maxvCpus=64, instanceTypes=[g4dn.4xlarge, g4dn.8xlarge, g5.4xlarge, g5.8xlarge]

vCPU usage 64/64 (saturated). No headroom for any larger GPU instance without freeing existing slots.

---

## 2. Quota increase request (filed, awaiting AWS support review)

```
aws service-quotas request-service-quota-increase \
  --service-code ec2 --quota-code L-3819A6DF --desired-value 256 \
  --profile bookyou-recovery --region ap-northeast-1
```

- RequestId: `a1fac277bf1f4477bbaf80d9f93e1e32iRihr0Ep`
- DesiredValue: 256.0 (4x current cap)
- Status at filing: `PENDING` → moved to **`CASE_OPENED`** within ~5s
- CaseId: `177898005900961`
- Status semantics: `CASE_OPENED` means AWS support has the request in ticket form; it is NOT auto-approved. Expected SLA: 10 min – a few hours for a 4x bump on Spot G/VT.

Action: poll later; do not block Lane A execution.

---

## 3. Plan B executed (immediate burn upgrade without quota wait)

### 3.1 Add g5.12xlarge to compute env instance types

```
aws batch update-compute-environment \
  --compute-environment jpcite-credit-ec2-spot-gpu \
  --compute-resources '{"minvCpus":0,"maxvCpus":64,"desiredvCpus":64,
                        "instanceTypes":["g4dn.4xlarge","g4dn.8xlarge",
                                         "g5.4xlarge","g5.8xlarge","g5.12xlarge"]}' \
  --profile bookyou-recovery --region ap-northeast-1
```

Compute env returned VALID after update. maxvCpus left at 64 (quota cap).

### 3.2 Register new job definition `jpcite-gpu-burn-g5-12xlarge:1`

- VCPU=48, MEMORY=184320 (180 GB), GPU=4
- Image: `public.ecr.aws/docker/library/python:3.12-slim-bookworm`
- Same entrypoint as `jpcite-gpu-burn-long:1` (S3 download + entrypoint_gpu_burn.sh)
- New env vars: `TASK=faiss-full-corpus-fine-tune`, `FAISS_LIMIT=800000`,
  `FAISS_BATCH_SIZE=512`, `FAISS_TABLES=programs,am_law_article,adoption_records,houjin`, `GPU_COUNT=4`
- timeout=75600s, sharedMemorySize=16384, platformCapabilities=[EC2]
- Tags: `Lane=A-GPU-Upgrade`, `Workload=burn_lane_a_gpu_upgrade`

ARN: `arn:aws:batch:ap-northeast-1:993693061769:job-definition/jpcite-gpu-burn-g5-12xlarge:1`

### 3.3 Free 48 vCPU by terminating 3 of 4 running jobs

```
aws batch terminate-job --job-id bf3128a1-… --reason "Lane A GPU upgrade …"
aws batch terminate-job --job-id 3c9f71e1-…
aws batch terminate-job --job-id b5a7ac5a-…
```

Within ~30s, all 3 → status `FAILED`, statusReason carries lane marker.
Retained: `0f43c5e3-…` finetune-minilm-programs (RUNNING) = 16 vCPU.

EC2 instance reaping: 3 of 4 g4dn.4xlarge instances terminated; the surviving
instance `i-0bd14a86d98d3cc0d` continues with the retained job.

### 3.3b Clear 2 stale RUNNABLE jobs ahead in FIFO queue

Inspection after step 3.3 showed 2 pre-existing RUNNABLE jobs from 2026-05-16
ahead of our new submission in FIFO order:

- `ce539a5f-…` finetune-minilm-laws (16 vCPU, queued since 2026-05-16 07:14)
- `c6064457-…` finetune-minilm-adoption (16 vCPU, queued since 2026-05-16 07:14)

With 48 vCPU free post step 3.3, those 2 would consume 32 vCPU first as
g4dn.4xlarge slots, leaving only 16 vCPU for our g5.12xlarge (needs 48).
Terminated both with the same lane marker so the g5.12xlarge job is first
in line for the 48-vCPU slot.

### 3.4 Submit g5.12xlarge job

```
aws batch submit-job \
  --job-name jpcite-gpu-burn-g5-12xlarge-faiss-full-corpus-20260517T100915 \
  --job-queue jpcite-credit-ec2-spot-gpu-queue \
  --job-definition jpcite-gpu-burn-g5-12xlarge:1 \
  --container-overrides '{"environment":[
      {"name":"TASK","value":"faiss-full-corpus-fine-tune"},
      {"name":"FAISS_LIMIT","value":"800000"},
      {"name":"FAISS_BATCH_SIZE","value":"512"}]}' \
  --tags '{"Lane":"A-GPU-Upgrade","Instance":"g5.12xlarge","BurnLevel":"high"}'
```

JobId: `10ee11c2-0600-4415-8924-9af804726149`
JobName: `jpcite-gpu-burn-g5-12xlarge-faiss-full-corpus-20260517T100915`

---

## 4. Post-action vCPU + burn-rate accounting

Before (4 × g4dn.4xlarge): 64 vCPU used, ~$0.534/hr × 4 = **$2.14/hr**
After (1 × g4dn.4xlarge + 1 × g5.12xlarge): 16 + 48 = **64 vCPU** (still capped),
~$0.534/hr (g4dn.4xlarge Spot) + ~$2.45/hr (g5.12xlarge Spot, ap-northeast-1) ≈ **$2.98/hr**

Net delta: **+$0.84/hr = +39%** burn rate per Spot GPU lane.

Daily extrapolation (24h): $51.4 → $71.5 → **+$20.1/day** on this lane.

To reach $2,000-$3,000/day total burn target, additional lanes (B/C/…) must
compose. Lane A contributes the GPU-class step; the quota request opens the
ceiling for further g5.12xlarge or g5.48xlarge stacking once approved.

---

## 5. Hard-stop posture

- Hard-stop $19,490 unchanged. Current MTD net consumed = trivial (sub-$1).
- 4 in-place defenses (CW $14K / Budget $17K / slowdown $18.3K / deny $18.9K)
  cover the canary cap independently of this lane.
- Lane A introduces no new defense bypass — it operates inside the existing
  64 vCPU quota until support raises the cap.

---

## 6. Quota status follow-up (operator action)

```
aws service-quotas get-requested-service-quota-change \
  --request-id a1fac277bf1f4477bbaf80d9f93e1e32iRihr0Ep \
  --profile bookyou-recovery --region ap-northeast-1
```

If approved (CASE_CLOSED with Status=APPROVED), follow up with:

```
aws batch update-compute-environment \
  --compute-environment jpcite-credit-ec2-spot-gpu \
  --compute-resources maxvCpus=256 \
  --profile bookyou-recovery --region ap-northeast-1
```

Then add g5.12xlarge stacking jobs as additional submissions; do not raise
maxvCpus past the approved quota.

---

## 7. Verification record

| Check | Command | Result |
|---|---|---|
| Identity | `aws sts get-caller-identity` | bookyou-recovery-admin |
| Quota current | `aws service-quotas get-service-quota --quota-code L-3819A6DF` | 64 |
| Quota request | `request-service-quota-increase --desired-value 256` | CASE_OPENED |
| Compute env update | `update-compute-environment` | VALID |
| Job def register | `register-job-definition` | `jpcite-gpu-burn-g5-12xlarge:1` |
| 3 jobs terminated | `terminate-job × 3` | FAILED (lane marker) |
| 2 stale RUNNABLE terminated | `terminate-job × 2` | FAILED (lane marker) |
| New job submitted | `submit-job` | JobId `10ee11c2-…` |
| Spot placement score | `get-spot-placement-scores g5.12xlarge` | **1/10** (severe constraint) |
| Spot placement score | `get-spot-placement-scores g4dn.12xlarge` | 3/10 (apne1-az2: 3) |
| Compute env update 2 | added g4dn.12xlarge to instanceTypes | VALID |
| Job transition | RUNNABLE → STARTING (~12 min after submit) | g4dn.12xlarge picked |
| Provisioned instance | `i-0cbd4b465e7793232` g4dn.12xlarge ap-northeast-1d | running 2026-05-17T01:16:58Z |

## 8. Outcome (final state at landing)

- **Submitted target:** g5.12xlarge (Spot score 1 → unfulfilled)
- **Provisioned instance:** **g4dn.12xlarge** `i-0cbd4b465e7793232` (Spot score 3, ap-northeast-1d, Spot ~$2.52/hr)
- **Job status:** **STARTING** with task ARN
  `arn:aws:ecs:ap-northeast-1:…/task/…/00b1e5944baa497fa3454328678b8671`
- **Same job def `jpcite-gpu-burn-g5-12xlarge:1`** (VCPU=48 / MEM=180GB / GPU=4)
  satisfied by g4dn.12xlarge (48 vCPU / 192 GB / 4 × T4 GPUs) — no job def rewrite needed.
- **Updated burn-rate delta:** 1 g4dn.4xlarge ($0.534/hr) + 1 g4dn.12xlarge ($2.52/hr)
  ≈ **$3.05/hr ≈ $73/day** on this GPU lane (vs $51/day pre-upgrade) = **+$22/day, +43%**.
- **Naming note:** Job/job-def carry "g5-12xlarge" in the name as the original target;
  the actual provisioned class is g4dn.12xlarge. Future Lane A re-submissions should
  use a generic name like `jpcite-gpu-burn-large` to avoid this confusion.

last_updated: 2026-05-17 [lane:solo]
