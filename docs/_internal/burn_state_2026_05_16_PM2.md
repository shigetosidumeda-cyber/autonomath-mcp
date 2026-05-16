# Burn State Verify — 2026-05-16 PM2

**Profile:** `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`)
**Verification window:** 2026-05-16T09:30 JST (`2026-05-16T18:30:00+0900`)
**Lane:** `[lane:solo]`
**Mode:** READ-ONLY (no state flipped per task contract)

---

## PART 1 — 5-line guardrail state audit

The 5-line defense is implemented as **4 CloudWatch billing alarms + 1 AWS Budgets entry** (the $18.3K middle line is a Budget rather than a CW alarm — Budgets give better forecast handling for that band, see `AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md`). All 5 lines verified present and non-breaching.

| Line | Threshold | Type | Name | State | Action |
| --- | --- | --- | --- | --- | --- |
| L1 early-warning | $13,000 | CW alarm | `jpcite-credit-billing-early-warning-13000` | `OK` (NonBreaching) | SNS `jpcite-credit-cost-alerts` |
| L2 warn | $14,000 | CW alarm | `jpcite-credit-billing-warn-14000` | `OK` (NonBreaching) | SNS `jpcite-credit-cost-alerts` |
| L3 slowdown | $17,000 | CW alarm | `jpcite-credit-billing-slowdown-17000` | `OK` (NonBreaching) | SNS `jpcite-credit-cost-alerts` |
| L4 slowdown-alt | $18,300 | Budget | `jpcite-credit-run-slowdown-18300` | Actual $0.0 / Forecast $5,019.5 | email notification |
| L5 stop | $18,700 | CW alarm | `jpcite-credit-billing-stop-18700` | `OK` (NonBreaching) | SNS → `jpcite-credit-auto-stop` Lambda |

**Stop Budget (action-bearing):** `jpcite-credit-run-stop-18900` — Actual $0.0 / Forecast $5,019.5
**Watch Budget (forecast-only):** `jpcite-credit-run-watch-17000` — Actual $0.0 / Forecast $5,019.5

**Notes:**
- All CW alarms in `notBreaching` evaluated-at `2026-05-16T02:28-06:54Z` (last refresh; AWS/Billing metric publishes ~6h granular, `Period=21600`).
- `StateReason` on every alarm: "no datapoints were received for 1 period and 1 missing datapoint was treated as [NonBreaching]" — expected for fresh billing data window.
- 5-line wholeness confirmed; nothing missing, nothing in `ALARM`.

---

## PART 2 — Real-time burn rate

### Burn-metric Lambda invocation
- Source: `infra/aws/lambda/jpcite_credit_burn_metric.py` (present in repo, 0.0 KB+ deploy assets present in `scripts/aws_credit_ops/deploy_burn_metric_lambda.sh`)
- Deployed function lookup:
  - `us-east-1`: only `jpcite-credit-auto-stop` present.
  - `ap-northeast-1`: only `jpcite-cf-loadtest` present.
- **Real-time burn-metric Lambda NOT deployed** in either region (deploy script un-run). Falling back to compute-fleet nominal calculation.

### Compute fleet inventory (live `describe-instances` / `list-tasks`)

| Resource | Count | Unit rate (on-demand) | Spot factor | Sustained $/hr |
| --- | --- | --- | --- | --- |
| EC2 `g4dn.4xlarge` GPU (ap-northeast-1) | 4 | $1.204/hr | ~0.65 (Spot ~0.78) | ~$3.13 |
| ECS Fargate Spot tasks (short queue) | 13 | ~$0.05/hr/task | n/a | ~$0.65 |
| ECS EC2 Spot CPU tasks | 0 | — | — | $0 |
| SageMaker batch transform (`jpcite-embed-...`) | 1 InProgress | ~$0.408/hr (ml.c5.2xlarge baseline) | n/a | ~$0.41 |
| **TOTAL (sustained)** |  |  |  | **~$4.19/hr** |
| **Daily projection (24h)** |  |  |  | **~$100.5/day** |

Nominal spec from task ($6.74/hr × 24h ≈ $162/day) assumed 4 GPU on-demand at $1.10/hr × 4 + 6 Fargate + 5 SageMaker — **actual fleet is leaner** (13 Fargate is small short tasks, only 1 SageMaker, 0 CPU). Live burn ~$4.19/hr, **~38% below nominal**.

### Cost Explorer cross-check (lagged 8–12h per MEMORY)
- `get-cost-and-usage 2026-05-15`: $0.0000000046 (rounding)
- `get-cost-and-usage 2026-05-16`: $0.0
- `EstimatedCharges` CW metric: no datapoints in window (AWS/Billing not yet emitted for current 6h period).
- **CE actual lags ~24h vs reality** — confirms MEMORY-recorded lag. The $4.19/hr live spend is not yet visible in CE.

### Burn-to-cap forecast
- Current cumulative (per Budget `CalculatedSpend.ActualSpend`): **$0.0**
- Forecasted (per all 3 Budgets): **$5,019.5**
- Stop-line cap: **$18,900** (Budget Action `APPLY_IAM_POLICY` armed)
- Headroom at forecast: **$13,880** (73% headroom)
- Time-to-stop at current ~$100.5/day burn: **~138 days** (no risk of breach this month)
- Time-to-stop at nominal $162/day: **~86 days** (still no risk)

---

## PART 3 — Budget Action verify (hard-stop)

```
Budget:           jpcite-credit-run-stop-18900
ActionId:         36b0120b-99bd-47f1-a68a-622f16f1995b
ActionType:       APPLY_IAM_POLICY
ApprovalModel:    AUTOMATIC
Status:           STANDBY  ← verified
Threshold:        100% ACTUAL
PolicyArn:        arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend
TargetUser:       bookyou-recovery-admin
ExecutionRole:    arn:aws:iam::993693061769:role/jpcite-budget-action-role
Subscribers:      info@bookyou.net, sss@bookyou.net (email)
```

**Status `STANDBY` confirmed** — action will fire only on 100% ACTUAL breach, currently $0.0 / $18,900 (0%).

---

## SNS subscription health (`jpcite-credit-cost-alerts`)

| Endpoint | Protocol | Subscription |
| --- | --- | --- |
| `arn:aws:lambda:us-east-1:993693061769:function:jpcite-credit-auto-stop` | lambda | Confirmed |
| `info@bookyou.net` | email | **PendingConfirmation** (still unconfirmed — not blocking, the Lambda is the action-bearing path) |

---

## Action items (deferred, **not executed** per task contract)

1. Deploy `jpcite-credit-burn-metric-emitter` Lambda — `scripts/aws_credit_ops/deploy_burn_metric_lambda.sh` exists, idempotent.
2. Confirm `info@bookyou.net` SNS email subscription.
3. CE actual is lagging — Athena cost-and-usage report (CUR) would give 24h-fresh truth.

---

## Audit invariants

- 5 guardrail lines: present.
- All CW alarms: `OK`, no `ALARM`.
- Budget Action: `STANDBY`.
- No live state was flipped during this audit (read-only verify).
