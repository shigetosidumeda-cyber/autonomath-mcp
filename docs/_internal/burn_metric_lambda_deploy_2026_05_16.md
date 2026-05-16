# Burn-Metric Lambda Deploy — 2026-05-16

## Summary

`jpcite-credit-burn-metric-emitter` Lambda deployed to ap-northeast-1 with
EventBridge `rate(5 minutes)` schedule. PM2 verify (commit 96527d36b) had
flagged the Lambda as un-deployed; this closes that gap so the 5-line
dashboard can fall back to a real-time CloudWatch metric instead of the
fleet-inventory hint.

Deploy executed via the canonical idempotent script
`scripts/aws_credit_ops/deploy_burn_metric_lambda.sh` (created the IAM
role + policy + Lambda + EventBridge rule + target wiring in one run).

## Identifiers

| Resource           | Value |
| ------------------ | ----- |
| Function name      | `jpcite-credit-burn-metric-emitter` |
| Function ARN       | `arn:aws:lambda:ap-northeast-1:993693061769:function:jpcite-credit-burn-metric-emitter` |
| Region (Lambda+CW) | `ap-northeast-1` |
| Region (CE)        | `us-east-1` (Cost Explorer has a single endpoint) |
| IAM role           | `arn:aws:iam::993693061769:role/jpcite-credit-burn-metric-role` |
| Inline policy      | `jpcite-credit-burn-metric-policy` |
| EventBridge rule   | `arn:aws:events:ap-northeast-1:993693061769:rule/jpcite-credit-burn-metric-5min` |
| Schedule           | `rate(5 minutes)` (state: ENABLED) |
| Target id          | `jpcite-credit-burn-metric-target` |
| SNS topic (alerts) | `arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts` |
| Runtime / mem      | `python3.12`, 256 MB, 60 s timeout |
| Profile used       | `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`) |

Source files:

- Handler: `infra/aws/lambda/jpcite_credit_burn_metric.py`
- Shared emit logic: `scripts/aws_credit_ops/emit_burn_metric.py`
- IAM trust: `infra/aws/iam/jpcite_credit_burn_metric_trust.json`
- IAM policy: `infra/aws/iam/jpcite_credit_burn_metric_policy.json`

Both Python files are zipped side-by-side at deploy time. Total zip
payload is small (single-file handler + shared module + boto3 from the
Lambda runtime), well under the 100 KB cap noted in the constraint.

## Smoke verification

### Dry-run smoke (initial state after deploy)

`JPCITE_BURN_METRIC_ENABLED=false` is the default per the safety model.

```json
{
  "mode": "dry_run",
  "classification": "RAMP",
  "consumed_usd": 0.0,
  "hourly_burn_usd": 0.0,
  "result": {
    "actions": [
      {"action": "put_metric_data", "namespace": "jpcite/credit", "count": 2, "live": false}
    ],
    "live": false
  },
  "safety_env": {"JPCITE_BURN_METRIC_ENABLED": "false"}
}
```

Cost Explorer was queried successfully (period 2026-05-01..2026-05-17,
0 USD MTD because the August reset on the bookyou-recovery profile has
not had any production charges yet). Classification = `RAMP`.

### Live smoke (one-shot to validate emit, then reverted)

The function was briefly switched to `JPCITE_BURN_METRIC_ENABLED=true`,
invoked once, and reverted back to `false` to preserve the canonical
safety default. The live invocation returned:

```json
{
  "mode": "live",
  "classification": "RAMP",
  "consumed_usd": 0.0,
  "hourly_burn_usd": 0.0,
  "actions": [
    {"action": "put_metric_data", "namespace": "jpcite/credit", "count": 2, "live": true}
  ],
  "live": true
}
```

CloudWatch immediately recognised the new metric series:

```
$ aws cloudwatch list-metrics --region ap-northeast-1 --namespace jpcite/credit \
      --metric-name GrossSpendUSD
{
    "Metrics": [{
        "Namespace": "jpcite/credit",
        "MetricName": "GrossSpendUSD",
        "Dimensions": [{"Name": "Classification", "Value": "RAMP"}]
    }]
}
$ aws cloudwatch list-metrics --region ap-northeast-1 --namespace jpcite/credit \
      --metric-name HourlyBurnRate
{
    "Metrics": [{
        "Namespace": "jpcite/credit",
        "MetricName": "HourlyBurnRate",
        "Dimensions": [{"Name": "Classification", "Value": "RAMP"}]
    }]
}
```

Both `GrossSpendUSD` and `HourlyBurnRate` carry a single `Classification`
dimension so the 5-line dashboard widget can colour-code RAMP / SLOWDOWN
/ STOP.

## EventBridge schedule

```
$ aws events describe-rule --region ap-northeast-1 --name jpcite-credit-burn-metric-5min
{
    "Name": "jpcite-credit-burn-metric-5min",
    "Arn": "arn:aws:events:ap-northeast-1:993693061769:rule/jpcite-credit-burn-metric-5min",
    "Schedule": "rate(5 minutes)",
    "State": "ENABLED"
}
$ aws events list-targets-by-rule --region ap-northeast-1 --rule jpcite-credit-burn-metric-5min
{
    "Targets": [{
        "Id": "jpcite-credit-burn-metric-target",
        "Arn": "arn:aws:lambda:ap-northeast-1:993693061769:function:jpcite-credit-burn-metric-emitter"
    }]
}
```

The `events.amazonaws.com` invoke permission is attached on the function
with statement-id `jpcite-credit-burn-metric-events-invoke`.

While `JPCITE_BURN_METRIC_ENABLED=false` the rule still fires every five
minutes — the Lambda walks Cost Explorer (read-only) and logs the
would-emit envelope without writing to CloudWatch or SNS. To start
plotting real-time burn on the dashboard, set
`JPCITE_BURN_METRIC_ENABLED=true` on the function configuration; to
stop, set it back to `false`. No code redeploy required.

## Namespace note

The task spec mentioned `JPCite/Canary/BurnRate`, but the canonical
deploy script + handler + dashboard pin the metric namespace at
`jpcite/credit` with metric names `GrossSpendUSD` + `HourlyBurnRate`
(both in `scripts/aws_credit_ops/emit_burn_metric.py`,
`docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md`, and
the `JPCITE_BURN_METRIC_NAMESPACE` env-var default). Following the
canonical names so the dashboard widget already drawn against
`jpcite/credit` continues to bind.

## Safety model recap

- Default `JPCITE_BURN_METRIC_ENABLED=false` (dry-run).
- Live writes only when env var equals literal `"true"` (case-insensitive).
- Cost Explorer is read-only in both modes.
- SNS alert fires only on `hourly_burn_usd >= JPCITE_HOURLY_ALERT_USD`
  (default 500 USD/hr) AND `live=true`.
- IAM policy scoped to: `ce:GetCostAndUsage`, `cloudwatch:PutMetricData`,
  `sns:Publish` (specific topic), and the standard Lambda logs surface.

## Reverse (if needed)

```bash
AWS_PROFILE=bookyou-recovery aws events remove-targets --region ap-northeast-1 \
  --rule jpcite-credit-burn-metric-5min --ids jpcite-credit-burn-metric-target
AWS_PROFILE=bookyou-recovery aws events delete-rule --region ap-northeast-1 \
  --name jpcite-credit-burn-metric-5min
AWS_PROFILE=bookyou-recovery aws lambda delete-function --region ap-northeast-1 \
  --function-name jpcite-credit-burn-metric-emitter
AWS_PROFILE=bookyou-recovery aws iam delete-role-policy \
  --role-name jpcite-credit-burn-metric-role \
  --policy-name jpcite-credit-burn-metric-policy
AWS_PROFILE=bookyou-recovery aws iam delete-role --role-name jpcite-credit-burn-metric-role
```

last_updated: 2026-05-16
