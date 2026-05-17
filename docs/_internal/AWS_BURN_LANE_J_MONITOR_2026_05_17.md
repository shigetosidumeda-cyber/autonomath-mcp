# AWS Burn Lane J — Real-time burn monitor + ledger (2026-05-17)

Read-only burn-rate watchdog for the jpcite AWS credit run. Layered on top of
the existing 5-line defence ($14K CW / $17K Budget / $18.3K slowdown /
$18.7K CW Lambda / $18.9K Budget Action DenyAll IAM) — the Never-Reach line
is structurally enforced by those 5; this Lane J adds the **cadence layer**
that verifies pace ($2,000-$3,000/day × 7 days = exhaust $19,490 credit).

## Why Lane J

- `bash scripts/aws_credit_ops/cost_ledger.sh` is on-demand only.
- Cost Explorer + AWS Billing console carry 24-48-72h lag.
- Operator wants daily-rolling pace verification (not 5-min ramp gating —
  that's `jpcite-credit-burn-metric-emitter` already running rate(5 minutes)).

Lane J fills the **1-hour cadence + 24h-rolling burn rate** slot. It is
purely read-only (Cost Explorer + CloudWatch PutMetricData under the
`jpcite/credit` namespace + SNS publish for off-band ticks).

## Components

### 1. Local script — `scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py`

Append-only ledger at `docs/_internal/AWS_BURN_LEDGER_2026_05_17.md`. Each
tick emits a JSON block + human-readable preamble. Run manually:

```bash
.venv/bin/python scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py --now
# or JSON-only (skip ledger write):
.venv/bin/python scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py --json-only
```

Exit codes:
- `0` — `ON_TARGET` (inside $2,000-$3,000/day band)
- `1` — `OFF_TARGET` (outside band but inside $1,500-$3,500)
- `2` — `OVER_BUDGET` (>$3,500/day) or `UNDER_PACE` (<$1,500/day)

### 2. Lambda — `infra/aws/lambda/jpcite_credit_burn_rate_monitor.py`

Function name: `jpcite-credit-burn-rate-monitor` (ap-northeast-1).
Computes the same tick remotely; emits 2 CloudWatch metrics under
`jpcite/credit`:

- `BurnRateUSDPerDay` (USD/day, scalar)
- `CreditRemainingUSD` (USD, scalar)

Both carry a single `State` dimension for dashboard colour-coding.
Publishes SNS to `arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts`
when state is `OVER_BUDGET` or `UNDER_PACE`.

Safety gate: `JPCITE_BURN_RATE_MONITOR_ENABLED` env var defaults to `false`.
While unset/false, every invocation is dry-run (Cost Explorer is still polled
read-only, but PutMetricData + SNS Publish are skipped).

### 3. EventBridge rule — `jpcite-credit-burn-monitor-hourly`

Schedule: `rate(1 hour)`. Region: `ap-northeast-1`. Target: the Lambda
function above.

### 4. Deploy script — `scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh`

Idempotent — reuses the existing `jpcite-credit-burn-metric-role` IAM role
(same set of permissions: CE read / CW PutMetric on jpcite/credit namespace /
SNS Publish to cost-alerts topic / Logs).

```bash
# Dry-run (default — Lambda created in disabled mode):
AWS_PROFILE=bookyou-recovery \
  ./scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh

# Live (operator opts in explicitly):
AWS_PROFILE=bookyou-recovery JPCITE_BURN_RATE_MONITOR_ENABLED=true \
  ./scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh
```

## Pre-flight verification (2026-05-17 snapshot)

Verified before Lane J went live (read-only checks):

- Budgets: 4 budgets armed
  - `BookYou-Emergency-Usage-Guard` ($100 actual $3,101.80)
  - `jpcite-credit-run-watch-17000` ($17,000 actual $0.00)
  - `jpcite-credit-run-slowdown-18300` ($18,300 actual $0.00)
  - `jpcite-credit-run-stop-18900` ($18,900 actual $0.00)
- Budget Action attached to `jpcite-credit-run-stop-18900`: STANDBY
  (action_id `36b0120b-99bd-47f1-a68a-...`, type APPLY_IAM_POLICY)
- CloudWatch alarms (ap-northeast-1): 5 alarms total
  - `jpcite-credit-batch-job-failure-rate` — `OK`
  - `jpcite-credit-catch-invocations-alarm` — `OK`
  - `BookYou Error Count` — `INSUFFICIENT_DATA`
  - `ECS - High Memory Alert` — `INSUFFICIENT_DATA`
  - `bookyou-high-cpu-alert` — `INSUFFICIENT_DATA`

The Never-Reach $19,490 defence chain remains armed. Lane J does **not**
touch any of those alarms / budgets / actions.

## Initial burn snapshot (2026-05-17T01:10:55Z)

```text
state                : UNDER_PACE
burn 24h             : $270.22/day
usage MTD            : $3,101.92
credit applied MTD   : $3,101.80
credit remaining     : $16,388.20 / $19,490 Never-Reach
projection (linear)  : exhaust 2026-07-16 (60.6 days from now)
```

`UNDER_PACE` is the **expected initial state** because (a) the 5-line defence
held the past 24h burn far below target while testing the trip lines and
(b) Cost Explorer carries a 24-48h lag. The next 24-48 hours of monitor
ticks will reveal whether the actual sustained ramp lands inside the
$2,000-$3,000/day target band.

## Cadence

| layer | tool | cadence | scope |
| --- | --- | --- | --- |
| 1 — instant | CloudWatch alarms | 1 min | dollar-line triggers |
| 2 — short loop | `jpcite-credit-burn-metric-emitter` Lambda | 5 min | classifier (RAMP/SLOWDOWN/STOP) |
| 3 — **Lane J** | `jpcite-credit-burn-rate-monitor` Lambda | **1 hour** | **24h-rolling pace** |
| 4 — daily | `cost_ledger.sh` | on demand | full per-service breakdown |
| 5 — weekly | manual review | as needed | trajectory + adjustment |

## Constraints honoured

- READ-ONLY against AWS Usage data — no job submission, no budget mutation.
- Reuses existing IAM role + SNS topic; no new privileged surface.
- Default Lambda env var `JPCITE_BURN_RATE_MONITOR_ENABLED=false`; the
  operator must explicitly flip it on per the `live_aws_commands_allowed=false`
  policy.
- No LLM (Cost Explorer + boto3 only).
- `[lane:solo]`.

## Operator runbook — arm Lane J

1. (optional) `AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh`
   to land the function + EventBridge rule in DISABLED mode (dry-run).
2. Inspect 1-2 dry-run invocations in CloudWatch Logs
   (`/aws/lambda/jpcite-credit-burn-rate-monitor`).
3. Flip to live:
   `AWS_PROFILE=bookyou-recovery aws lambda update-function-configuration --region ap-northeast-1 --function-name jpcite-credit-burn-rate-monitor --environment 'Variables={JPCITE_BURN_RATE_MONITOR_ENABLED=true,...}'`
4. Watch CloudWatch dashboard widget for `BurnRateUSDPerDay`.
5. SNS alerts go to `jpcite-credit-cost-alerts` topic when state flips to
   `OVER_BUDGET` or `UNDER_PACE`.

## Files landed in this lane

- `scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py` — local CLI + ledger writer
- `infra/aws/lambda/jpcite_credit_burn_rate_monitor.py` — Lambda handler
- `scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh` — idempotent deploy
- `docs/_internal/AWS_BURN_LEDGER_2026_05_17.md` — append-only ledger (this lane writes)
- `docs/_internal/AWS_BURN_LANE_J_MONITOR_2026_05_17.md` — this doc

last_updated: 2026-05-17
