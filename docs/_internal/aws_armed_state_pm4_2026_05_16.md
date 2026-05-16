# AWS ARMED State SOT — PM4 2026-05-16

**Snapshot time**: 2026-05-16 PM4
**Profile**: `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`)
**Operation**: state verify only — NO flip / NO write

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

5/5 ARMED. **0 alarms in ALARM state.** No red flags.

## 3. Budget Action — STANDBY confirmed

- Budget: `jpcite-credit-run-stop-18900`
- ActionId: `36b0120b-99bd-47f1-a68a-622f16f1995b`
- ActionType: `APPLY_IAM_POLICY` (deny-new-spend)
- PolicyArn: `arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend`
- Target users: `bookyou-recovery-admin`
- ApprovalModel: `AUTOMATIC`
- Status: **STANDBY** (correct — fires at 100% of $18,900)
- Subscribers: `info@bookyou.net`, `sss@bookyou.net`

## 4. Lambdas LIVE (region-split)

### us-east-1
| Function | Runtime | Auto-stop / Live env |
|---|---|---|
| jpcite-credit-auto-stop | python3.12 | `JPCITE_AUTO_STOP_ENABLED=false`, `STOP_DRILL_LIVE=false` |

### ap-northeast-1
| Function | Runtime | Live env |
|---|---|---|
| jpcite-cf-loadtest | python3.12 | — |
| jpcite-credit-burn-metric-emitter | python3.12 | `JPCITE_BURN_METRIC_ENABLED=false`, target `$18300`, hourly stop `$500` |
| jpcite-credit-canary-attestation-emitter | python3.12 | `JPCITE_CANARY_ATTESTATION_ENABLED=false`, `JPCITE_CANARY_LIVE_UPLOAD=false` |

All emitter flags are `false` (correct default — hard-stop only fires under explicit promote).

## 5. Compute capacity (real-time)

- Batch jobs RUNNING on `jpcite-credit-ec2-spot-gpu-queue` (ap-northeast-1): **4**
- SageMaker transform jobs InProgress (ap-northeast-1): **2**

## 6. S3 derived corpus

- Bucket: `jpcite-credit-993693061769-202605-derived`
- Objects: **524,290**
- Total size: **236,852,076,024 bytes** (~220.58 GB)

## 7. Cost trajectory (Cost Explorer 8-12hr lag)

```
2026-05-15 -> 2026-05-16   gross=$0.00  net=$0.0000
2026-05-16 -> 2026-05-17   gross=$0.00  net=$0.0000
```

CE delay holds; real burn pending Phase 6/7/8 ramp settlement.

## 8. Drift findings — NONE

- [x] All 5 alarms `OK` (none in `ALARM`)
- [x] Budget Action `STANDBY` (correct armed state — fires only at 100%)
- [x] Lambda env defaults `false` (no premature enablement)
- [x] Profile `bookyou-recovery` LIVE (admin, ARN matched)

No red flags. System is in expected ARMED + idle posture pending controlled promote.

## 9. Next 30 min monitor plan

- Re-poll alarms every 5 min via `aws cloudwatch describe-alarms`
- Cost ledger re-run at +30 min (still expected $0 due to CE lag)
- Batch + SageMaker counts monitor
- Stop on any `ALARM` state or Budget Action != `STANDBY`

## 10. Lane marker

`[lane:solo]` — single-actor SOT capture, no concurrent flip.
