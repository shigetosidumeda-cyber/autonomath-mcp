# AWS ARMED State SOT — AM2 2026-05-17

**Snapshot time**: 2026-05-17 AM2
**Profile**: `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`)
**Operation**: state verify only — NO flip / NO write
**Lane marker**: `[lane:solo]`

## 1. AWS Identity LIVE

```json
{
  "UserId": "AIDA6OXFY2KEYSUNJDC63",
  "Account": "993693061769",
  "Arn": "arn:aws:iam::993693061769:user/bookyou-recovery-admin"
}
```

Status: LIVE / admin / `InvalidClientTokenId` resolved.

## 2. 5-line CloudWatch alarms (us-east-1, jpcite-credit-billing-*)

| Alarm | StateValue | Expected |
|---|---|---|
| jpcite-credit-billing-early-warning-13000 | OK | OK (under threshold) |
| jpcite-credit-billing-warn-14000 | OK | OK |
| jpcite-credit-billing-slowdown-17000 | OK | OK |
| jpcite-credit-billing-stop-18700 | OK | OK |
| jpcite-credit-billing-stop-18900 (Budget Action) | STANDBY | STANDBY |

5/5 ARMED. **0 alarms in ALARM state.** No red flags. No drift vs PM4 2026-05-16 snapshot.

## 3. Budget Action — STANDBY confirmed

- Budget: `jpcite-credit-run-stop-18900`
- ActionId: `36b0120b-99bd-47f1-a68a-622f16f1995b`
- ActionType: `APPLY_IAM_POLICY` (deny-new-spend)
- PolicyArn: `arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend`
- Target users: `bookyou-recovery-admin`
- ApprovalModel: `AUTOMATIC`
- Status: **STANDBY** (correct — fires at 100% of $18,900)
- Subscribers: `info@bookyou.net`, `sss@bookyou.net`

No drift.

## 4. Lambdas LIVE (region-split)

### us-east-1
| Function |
|---|
| jpcite-credit-auto-stop |

### ap-northeast-1
| Function |
|---|
| jpcite-cf-loadtest |
| jpcite-credit-burn-metric-emitter |
| jpcite-credit-canary-attestation-emitter |

3 functions present in ap-northeast-1, 1 in us-east-1. All expected functions LIVE. No drift vs PM4.

## 5. Compute capacity (real-time)

- Batch jobs RUNNING on `jpcite-credit-ec2-spot-gpu-queue` (ap-northeast-1): **4**
- SageMaker transform jobs InProgress (ap-northeast-1): **6**

SageMaker transform job count **drifted upward 2 → 6** vs PM4 snapshot — consistent with PM5/PM6/PM7 GPU saturate + FAISS embedding waves landed since (`Wave 67`/`PM5-7`/`Stream FAISS`). Within expected band.

## 6. CW custom metric — HourlyBurnRate

```
namespace=jpcite/credit
metric=HourlyBurnRate
window=2026-05-17T00:00:00Z .. 2026-05-17T01:00:00Z
datapoints=[]
```

No emission this window. Consistent with emitter `JPCITE_BURN_METRIC_ENABLED=false` default (no LIVE flip). Hard-stop ARMED path remains the 5-line alarms + Budget Action, not custom metric.

## 7. Cost trajectory (Cost Explorer 8-12hr lag)

```
2026-05-01 -> 2026-05-18  UnblendedCost=$0.0000001931  Estimated=true
```

CE reports effectively $0.00 MTD. Two readings:

- CE lag holds (8-12hr) — recent Phase 6/7/8 ramp + Wave 53-90 packet generation + Athena burn + SageMaker / EC2 Spot GPU burn not yet visible in CE rollup.
- Forecasted $6,807 + actual $2,831.538 markers in MEMORY (`project_aws_bookyou_compromise`) reference the broader BookYou account history, not this MTD CE window. Cross-check via Cost Explorer Daily granularity + CW custom emitter once live ramp settles.

**No flip recommended on the basis of CE alone — wait for 8-12hr propagation.**

## 8. Drift findings

| axis | PM4 2026-05-16 | AM2 2026-05-17 | drift |
|---|---|---|---|
| Identity | bookyou-recovery-admin LIVE | bookyou-recovery-admin LIVE | none |
| 5-line alarms | 4/4 OK + 1 STANDBY | 4/4 OK + 1 STANDBY | none |
| Budget Action | STANDBY | STANDBY | none |
| Lambdas us-east-1 | 1 (auto-stop) | 1 (auto-stop) | none |
| Lambdas ap-northeast-1 | 3 | 3 | none |
| Batch RUNNING | 4 | 4 | none |
| SageMaker InProgress | 2 | **6** | +4 (Wave 67/PM5-7/FAISS expand) |
| CE MTD | $0.00 | $0.0000001931 | within CE lag |

**Net: no ARMED drift, no policy regression, no flag flip detected.** The +4 SageMaker delta is workload-side, not control-plane-side.

## 9. Lane marker

`[lane:solo]` — single-actor SOT capture, no concurrent flip.

last_updated: 2026-05-17
