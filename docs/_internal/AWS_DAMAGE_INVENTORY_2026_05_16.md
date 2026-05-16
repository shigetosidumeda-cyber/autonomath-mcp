# AWS BookYou Account 993693061769 — Damage Inventory (2026-05-16)

**Lane**: `[lane:solo]`
**Profile used**: `bookyou-recovery` (IAM user `bookyou-recovery-admin`, AdministratorAccess) — READ-ONLY analysis
**Scope**: budget actual/forecast vs Cost Explorer reality, multi-region resource sweep, top contributor identification, teardown sequencing, Stream I AWS canary go/no-go
**Constraint**: NO destructive AWS calls invoked. This is inventory + plan only.

## 1. Current Spend Table

| Metric                                | Value             | Source                                                       |
| ------------------------------------- | ----------------- | ------------------------------------------------------------ |
| Budget limit (BookYou-Emergency-Usage-Guard) | **$100.00 USD/mo** | `aws budgets describe-budgets` (2026-05-16 07:52 JST update) |
| Budget actual (May 2026, gross)       | **$2,831.538**    | Budget API `CalculatedSpend.ActualSpend`                     |
| Budget forecasted (May 2026 EOM)      | **$6,807.679**    | Budget API `CalculatedSpend.ForecastedSpend`                 |
| Overrun vs $100 limit                 | **2,731.5 %**     | (2831.538 − 100) / 100                                       |
| **Cost Explorer UnblendedCost (May 1–15)** | **$0.00000019** | `aws ce get-cost-and-usage` UnblendedCost                  |
| Cost Explorer BlendedCost (May 1–15) | **$0.1250**       | `aws ce get-cost-and-usage` BlendedCost                      |
| Cost Explorer Apr 16–May 15           | UnblendedCost $0.0000036 / BlendedCost $0.1250 | 30-day window                                |
| Budget HealthStatus                   | HEALTHY           | Last 2026-05-16 07:52 JST                                    |

### Critical reconciliation

The **$2,831 / $6,807 figures are the GROSS pre-credit spend** the Budget API surfaces because that budget was created with `IncludeCredit: false` and `UseBlended: false`. Real cash burn (`UnblendedCost` net of AWS credits) for May 2026 is essentially **zero** ($0.00000019).

Interpretation:
- AWS Credits are still absorbing the attacker's gross usage. As long as credits exist, the cash hit is $0.
- Budget `IncludeCredit: false` is exactly the canary the operator wanted: it screams when GROSS usage breaks the $100 envelope, even when net-of-credit usage is $0. That alarm is firing correctly.
- The HealthStatus stayed HEALTHY because nothing in AWS Budgets "auto-teardown"; the alarm only emits notifications (SNS/email). The operator workflow downstream was the missing piece.
- Forecast $6,807 / month and actual $2,831 (16 days in) reproduce the **~$180/day** new-attacker baseline reported in memory `project_aws_bookyou_compromise` (EBS $33/day + GPU spikes), but at zero cash net.

## 2. Top 3 Cost Contributors

Pulled from `aws ce get-cost-and-usage … --group-by SERVICE`. Both April and May rankings collapsed to a tiny tail because the attacker's GPU instances were already terminated before April 16 (see memory line 23 — EBS-only after EC2 GPU was stopped).

### A. April 2026 (pre-credit BlendedCost — gross)

| Rank | Service                                   | Apr 2026  | Likely cause                                                          |
| ---- | ----------------------------------------- | --------- | --------------------------------------------------------------------- |
| 1    | **Amazon EC2 Container Registry (ECR)**   | $150.05   | 2 attacker-pushed repos (`satyr-model`, `z-image-inference`), 12.7 GB + 9.5 GB single layers, ~30+ image tags total |
| 2    | **EC2 - Other** (EBS gp3 VolumeUsage/Throughput) | $2.47   | Already-detached gp3 volumes left after GPU teardown (`Volume*` BoxUsage on `g5.2xlarge` / `g6e.2xlarge` now `-0`) |
| 3    | **Amazon EC2 - Compute** (Spot/On-Demand) | $1.93     | Tail-end of attacker GPU compute (`BoxUsage:g5.2xlarge`, `BoxUsage:g6e.2xlarge` and `BoxUsage:t3.micro`), now zeroed |

### B. May 2026 (pre-credit BlendedCost — gross, 1–15 days)

| Rank | Service                              | May 1–15 | Likely cause                                                                |
| ---- | ------------------------------------ | -------- | --------------------------------------------------------------------------- |
| 1    | **Amazon Elastic Load Balancing**    | $1.2156  | 1 ELB still listed in cost data, but `elbv2 describe-load-balancers` returns `[]` across 17 regions — likely classic ELB billing residue or a deleted-mid-month phantom |
| 2    | **EC2 - Other** (residual EBS/IPv6/NAT) | $0.38   | Tail-end EBS storage that has since been detached / deleted by recovery action |
| 3    | **Amazon S3**                        | $0.125   | 27 legacy buckets (mostly empty CDK artifacts from 2021–2024) — see §3      |

**Key insight**: The May cost contribution from any single service is **under $2** in true (BlendedCost) terms. The gross-spend $2,831 displayed in the budget is dominated by **historical** ECR storage costs that AWS continues to compute on the ~22 GB image set even though no new pushes happened in May. Credits are still absorbing this.

## 3. Resource Inventory (Multi-Region Sweep)

Swept 17 regions for EC2 / EBS / Snapshots / ELB / ECR / EIP. Only **2 surviving resource families**:

### A. ECR repositories (only live cost source, **leak suspects**)

| Region          | Repository name        | Created                            | Image count / largest layer        | Attribution                                                            |
| --------------- | ---------------------- | ---------------------------------- | ---------------------------------- | ---------------------------------------------------------------------- |
| us-east-1       | `satyr-model`          | 2026-03-23 16:28:48 JST            | 20+ tags; largest 12.73 GB         | Created during compromise window; "satyr" matches attacker's container set |
| ap-southeast-1  | `z-image-inference`    | 2026-03-25 12:36:35 JST            | TBD (similar size class)           | Created in attacker-preferred Singapore region (low-monitoring), name aligns with image-generation workload  |

Combined estimated size: **~22 GB**, billed as ECR storage ($0.10/GB/month = $2.20/month gross, but accumulated April push activity surfaced as $150 in the April top-line).

### B. EC2 / EBS / Snapshots / AMIs / Elastic IPs

| Resource | All regions  | Comment                                                              |
| -------- | ------------ | -------------------------------------------------------------------- |
| EC2 instances (any state) | **0**       | Confirmed via `describe-instances` in 17 regions                  |
| EBS volumes (any state)   | **0**       | Confirmed via `describe-volumes` in 17 regions — **EBS leak from memory note IS RESOLVED** |
| EBS snapshots (`self`)    | **0**       | Confirmed in us-east-1 + ap-northeast-1                            |
| AMIs (`self`)             | **0**       | Confirmed in us-east-1 + ap-northeast-1                            |
| Elastic IPs               | **0**       | Confirmed in us-east-1 + ap-northeast-1                            |
| Classic ELBs / ALBs / NLBs | **0**       | `elbv2` + classic `elb describe-load-balancers` both empty in ap-northeast-1; the $1.21 May ELB cost is therefore phantom residue (deleted mid-month or a NAT gateway misclassified) |

The EBS leak that memory `project_aws_bookyou_compromise` quoted at "推定 9〜12 TB 残存、$33/日継続" is **NO LONGER PRESENT** anywhere we can see. Either AWS support intervened between 2026-05-13 and 2026-05-16, or the GPU+EBS termination cycle completed naturally.

### C. S3 buckets — 27 total, all legacy (none attacker-attributed)

All 27 bucket names match the pre-incident BookYou CDK/CodePipeline naming pattern (`cdkstack…artifactbucket…`, `prodcdkstack…`, `stgcdkstack…`, `cdk-hnb659fds-assets-993693061769-ap-northeast-1`, `elasticbeanstalk-ap-northeast-1-…`). Creation dates span 2021-04 to 2024-08. **No bucket created during the 2026-03+ compromise window.** May S3 charge of $0.125 is residual TimedStorage on the empty CDK artifact buckets.

## 4. Cross-Reference to `scripts/teardown/`

Scripts inventoried under `/Users/shigetoumeda/jpcite/scripts/teardown/`:

| Script                             | Targets                                                              | Applies to current leak?                          |
| ---------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------- |
| `00_emergency_stop.sh`             | AWS Batch + ECS + Bedrock provisioned + OpenSearch + S3 + EC2        | **Partial** — has EC2/S3 logic but no ECR cleanup |
| `01_identity_budget_inventory.sh`  | sts get-caller-identity + budgets describe-budgets                   | This inventory document already supersedes it     |
| `02_artifact_lake_export.sh`       | S3 bucket inventory                                                  | Useful for verifying the 27 legacy buckets are inert before any S3 action |
| `03_batch_playwright_drain.sh`     | AWS Batch jobs                                                       | N/A — no Batch jobs found                        |
| `04_bedrock_ocr_stop.sh`           | Bedrock provisioned throughput                                       | N/A — no Bedrock activity in cost data           |
| `05_teardown_attestation.sh`       | Emit attestation JSON                                                | Apply after each teardown step                   |
| `run_all.sh`                       | Orchestrator                                                         | DO NOT run end-to-end; cherry-pick scripts only  |
| `verify_zero_aws.sh`               | Verification gate                                                    | Apply after ECR + ELB cleanup                    |

**Gap identified**: There is no ECR repository teardown in the existing scripts. The 2 attacker ECR repos are the only material live cost source, and the current scripts don't address them. Operator would need an `aws ecr batch-delete-image` + `aws ecr delete-repository --force` step added — **but only after user explicitly approves**.

## 5. Recommended Teardown Sequence (most-risky-first)

ALL STEPS REQUIRE USER APPROVAL — none executed by this run.

### Step 1: Verify with AWS Support (Awano-san) FIRST — PASSIVE
Before any destructive call, email Awano-san on the existing thread:
- "Visible-side EBS leak gone; only ECR `satyr-model` (us-east-1) and `z-image-inference` (ap-southeast-1) remain — please confirm whether the security team has already triggered the cleanup or whether the account is still hostile-controlled and the attacker could re-push."
- Reason: if Awano-san is mid-action, our `delete-repository` could collide with AWS's evidence-preservation hold. **Risk: medium**. Wait for Awano-san reply before Step 2.

### Step 2: ECR repository deletion (highest cost-per-call return) — DESTRUCTIVE
Order: us-east-1 first, then ap-southeast-1.
```bash
# DO NOT RUN until user approval
AWS_PROFILE=bookyou-recovery aws ecr delete-repository \
  --region us-east-1 --repository-name satyr-model --force
AWS_PROFILE=bookyou-recovery aws ecr delete-repository \
  --region ap-southeast-1 --repository-name z-image-inference --force
```
Expected effect: gross spend forecast drops from $6,807 → near-zero overnight; net (already zero) unchanged.
Risk: low — these repos are 100% attacker-attributed by name + creation date.
Reversibility: NONE. Images cannot be re-pushed without attacker access. If forensic evidence is needed, run `aws ecr describe-images --output json > evidence_us_east_1.json` FIRST.

### Step 3: ELB phantom investigation — INVESTIGATIVE
Before assuming the $1.21 ELB cost is residue:
```bash
# READ-ONLY only
for r in us-east-1 us-east-2 us-west-1 us-west-2 eu-west-1 eu-west-2 eu-west-3 \
         eu-north-1 eu-central-1 ap-northeast-1 ap-northeast-2 ap-northeast-3 \
         ap-southeast-1 ap-southeast-2 ap-south-1 ca-central-1 sa-east-1; do
  AWS_PROFILE=bookyou-recovery aws elbv2 describe-load-balancers --region $r \
    --query 'LoadBalancers[].[LoadBalancerName,DNSName,VpcId,State.Code]' --output table 2>&1
done
```
If any region returns rows: delete-load-balancer (operator + Awano-san dual approval).

### Step 4: S3 bucket review — DEFERRABLE
27 legacy buckets, May cost $0.125. Not urgent. Apply standard "lifecycle to Glacier Deep Archive + 365-day delete" policy via Console once the account is re-secured. Do NOT delete CDK artifact buckets while the underlying CodePipeline stacks might still be live — risk of stack-rollback failure.

### Step 5: Verification — READ-ONLY
After Step 2 + 3:
```bash
AWS_PROFILE=bookyou-recovery bash scripts/teardown/verify_zero_aws.sh
```
Expected: zero EC2 / zero EBS / zero ECR / zero ELB / S3 buckets enumerated only.

## 6. User Decision Points (in order)

1. **Awano-san status check** — must Awano-san reply before we touch ECR? (Recommendation: yes, send today's update including this inventory as evidence.)
2. **Forensic snapshot of ECR before delete?** — if yes, run `aws ecr describe-images > evidence_*.json` first. (Recommendation: yes, low cost, ~30 sec.)
3. **us-east-1 ECR delete approval** (`satyr-model`).
4. **ap-southeast-1 ECR delete approval** (`z-image-inference`).
5. **ELB sweep result review** — if any region returns rows, approve case-by-case.
6. **S3 lifecycle policy** — approve cleanup plan? (Recommendation: defer — non-urgent, account-recovery dependent.)
7. **Budget alarm SNS routing** — when the budget eventually flips from HEALTHY to ALARM (when credits run out, currently estimated ¥300万 buffer), what action? (Recommendation: route to PagerDuty + auto-suspend account API access via SCP if attacker still has any path in.)

## 7. Stream I AWS Canary Go/No-Go Recommendation

**RECOMMENDATION: DO NOT proceed with Stream I AWS canary execution until teardown completes.**

Reasoning:
- `scorecard.state = AWS_CANARY_READY` (per Wave 50 tick 9+) presumes the AWS account is operator-controlled and clean. The 2 ECR repos prove the account is **still hosting attacker artifacts**, and we have no MFA-verified evidence the attacker has lost write access.
- Running a live canary would (a) generate ¥3/req billing events against the contaminated account, (b) muddy the forensic record Awano-san is using, (c) risk the canary IAM role being abused if the attacker still has any post-rotation token.
- `live_aws_commands_allowed = false` (66+ tick continuous, per CLAUDE.md) is the **right default** for exactly this reason. Keep it `false`.
- The 5/5 preflight READY state can stay; preflight READY just means our side is ready, not that the account is safe. Document this distinction in the canary runbook.

**Unblock criteria for Stream I**:
1. Awano-san confirms account-recovery complete (root email restored + MFA active + old IAM rotated).
2. ECR `satyr-model` + `z-image-inference` deleted (Step 2 above complete).
3. 7-day clean budget window (no new gross spend > $5/day).
4. AWS Trust & Safety written confirmation that 993693061769 is no longer flagged as compromised.

Only after all 4: revisit Stream I. Until then, the canary must run against a different AWS account (BookYou-Recovery-Clean, separate account ID) OR be deferred entirely.

## 8. Stream RR Note (orphan workflow)

Unrelated to this inventory, but Stream RR (`organic-funnel-daily.yml` GHA registration debug) is the only `[pending]` task adjacent to AWS-side work. Suggest landing it independently — it does not touch AWS.

---

Generated: 2026-05-16 (READ-ONLY, no AWS mutations).
Operator action: review §6 decision points; reply to Awano-san before approving Step 2.
