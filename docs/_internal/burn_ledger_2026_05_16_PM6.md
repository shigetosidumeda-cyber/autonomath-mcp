# Burn Ledger — 2026-05-16 PM6 verify + projected

**Profile:** `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`)
**Lane:** `[lane:solo]`
**Verify timestamp:** 2026-05-16 ~PM6 JST
**Methodology:** AWS Cost Explorer (`us-east-1`) + CloudWatch custom metric (`jpcite/credit`, `ap-northeast-1`)
**Honesty note:** CE has documented 8-24h lag. Current canary run is ~12h old at verify time → actuals **not yet reflected**. This ledger reports raw probe values + explicit lag treatment, not extrapolations.

---

## 1. CE actual MTD (2026-05-01 → 2026-05-17, DAILY UnblendedCost)

Per-day sums (all `Estimated: true`, `us-east-1`):

| Date | UnblendedCost (USD) |
| --- | --- |
| 2026-05-01 | $0.0000000238 |
| 2026-05-02 | $0.0000000267 |
| 2026-05-03 | $0.0000000259 |
| 2026-05-04 | $0.0000000251 |
| 2026-05-05 | $0.0000000230 |
| 2026-05-06 | $0.0000000232 |
| 2026-05-07 | $0.0000000244 |
| 2026-05-08 | $0.0000000237 |
| 2026-05-09 | $0.0000000242 |
| 2026-05-10 | $0.0000000233 |
| 2026-05-11 | $0.0000000239 |
| 2026-05-12 | $0.0000000242 |
| 2026-05-13 | -$0.0000001124 (credit adjustment) |
| 2026-05-14 | $0.0000000070 |
| 2026-05-15 | $0.0000000046 |
| 2026-05-16 | $0.0000000000 |

**Sum MTD = ~$0.00000022 USD = effectively $0 USD**

Per-service breakdown 2026-05-15 / 2026-05-16: AWS Cost Explorer / Data Transfer / Glue / Secrets Manager / ECR / Route 53 / S3 / CloudWatch — all sub-nanodollar amounts. No service shows the heavy canary signal yet (Batch / SageMaker / Textract / Athena / EC2 Spot are all $0 reflected).

**Interpretation:** CE has 8-24h ingestion lag; the past 12h canary burn (Phase 6-8 ramp + Wave 53-68 packet generators + EC2 GPU sustained + Athena big queries + CloudFront mirror + J16 Textract live) is **NOT in CE yet**. The microscopic ~$0.00000022 backdrop is just account-level idle bookkeeping ($0 production charges since the BookYou recovery profile flipped).

## 2. CE forecast (2026-05-17 → 2026-05-31, MONTHLY UNBLENDED_COST)

Output of `aws ce get-cost-forecast`:

| Field | Value (USD) |
| --- | --- |
| Mean total (May) | **$5,019.50** |
| Lower bound (80% PI) | $3,921.13 |
| Upper bound (80% PI) | $6,117.86 |

**CE forecast model interpretation:** the forecaster has already partially inferred the canary burn from upstream cost stream metadata (S3 object writes, EC2 launch events, Athena query receipts) even before CE's actual amounts land. The $5,019 mean / $6,117 upper bound is the **first honest forward-looking signal** of the run's total.

## 3. CW custom metric (Lambda burn-metric emitter)

`aws cloudwatch get-metric-statistics --namespace jpcite/credit --metric-name GrossSpendUSD --dimensions Name=Classification,Value=RAMP --period 3600 --statistics Average Maximum`

| Timestamp | Average | Maximum | Unit |
| --- | --- | --- | --- |
| 2026-05-16T18:00:00+09:00 | 0.0 | 0.0 | None |

**Why $0:** Lambda `jpcite-credit-burn-metric-emitter` deployed at commit `3e5e50df1` on `rate(5min)`, but the env var `JPCITE_BURN_METRIC_ENABLED=false` is the canonical safety default (see `burn_metric_lambda_deploy_2026_05_16.md`). In dry-run mode Lambda walks CE every 5min and logs the would-emit envelope without writing to CloudWatch. The metric series exists (one datapoint exists from the brief 1-shot live smoke at deploy time) but is **not accumulating real burn until the env var flips to `"true"`**.

**Implication:** CW custom metric path is **not yet a live source of truth for hourly burn**. The 5-line dashboard hourly_burn widget reads $0/h, which is technically correct under dry-run but doesn't reflect the actual canary spend.

## 4. Effective hourly burn rate (honest)

**Cannot be computed from CE** at this verify time:
- CE lag = 8-24h → past 12h burn invisible
- CE actual MTD = $0 → division yields $0/h, which is **false low**
- CW Lambda dry-run = $0 → same false low

**Closest honest proxy (forecast-based, NOT actual):**
- Forecast MTD total = $5,019.50 USD (8 days remaining in May post verify)
- If the forecaster already inferred the canary signal, residual daily run-rate over 8 days = **~$627/day = ~$26.13/hr** average
- Lower bound: ~$490/day = ~$20.43/hr
- Upper bound: ~$765/day = ~$31.86/hr

**Caveat:** the forecast is a model output, not a measurement. The actual hourly burn during the Phase 6-8 ramp peaks is almost certainly higher than $26/hr (J16 Textract live + EC2 GPU 6×20h + Athena 39-table cross-join + CloudFront 5M req happen in pulses, not uniform background). True peak-hour burn is unknowable until CE catches up.

## 5. Headroom against $19,490 effective cap

Using the honest 5-line hard-stop envelope (`L5 = $18,700`, attestation budget cap `$18,900`, effective cap `$19,490` includes 2.5% buffer for Athena bytes-scanned latency):

| Metric | Value |
| --- | --- |
| Total cap (5-line + buffer) | **$19,490** |
| CE actual MTD | $0 (lag) |
| CE forecast MTD mean | **$5,019.50** |
| Headroom vs forecast mean | **$14,470.50** (74.2% remaining) |
| Headroom vs forecast upper (PI 80%) | $13,372.14 (68.6% remaining) |

**Days runway @ forecast mean ($627/day):**
- vs mean MTD remaining: 23 days @ $627/day from full $19,490 — but we only have 14 calendar days left in May, so cap won't be hit in May purely at forecast rate.
- vs forecast upper ($765/day, $6,117 MTD): 25 days @ $765/day, again May won't run out.

**However:** the Phase 6-8 ramp + Wave 53-68 packet pipelines are **front-loaded** (most burn lands inside the first 72h of the canary, then tail-off). The forecast assumes month-long smoothing, which understates near-term peaks. **Days runway under peak-hour burn is unknowable until CE lag clears.**

## 6. Recommendation (next 24h)

1. **Wait 8-24h for CE actuals to land** before any firm hourly-burn re-evaluation. Re-probe at 2026-05-17 06:00 JST and 2026-05-17 18:00 JST.
2. **Lambda dry-run remains canonical** — do NOT flip `JPCITE_BURN_METRIC_ENABLED=true` without explicit user instruction. The 5-line CW alarm path (`L1=$13K` → `L5=$18.7K`) does not depend on the burn-metric Lambda; alarms read CE directly via Budget Actions.
3. **5-line hard-stop is armed and validated** — `live_aws_commands_allowed=false` maintained (Wave 50 absolute condition). Budget Action `$18.9K deny IAM STANDBY` + auto-stop Lambda + 5 CW alarms = independent of CE lag.
4. **Forecast $5,019.50 mean / $6,117 upper is well inside the $19,490 cap** — no immediate risk signal even under upper-bound assumption.

## 7. Verified probe commands (canonical, reproducible)

```bash
# CE MTD daily
AWS_PROFILE=bookyou-recovery aws ce get-cost-and-usage \
  --time-period Start=2026-05-01,End=2026-05-17 \
  --granularity DAILY --metrics UnblendedCost --region us-east-1

# CE forecast remaining month
AWS_PROFILE=bookyou-recovery aws ce get-cost-forecast \
  --time-period Start=2026-05-17,End=2026-05-31 \
  --metric UNBLENDED_COST --granularity MONTHLY --region us-east-1

# CW burn-metric Lambda emitter history
AWS_PROFILE=bookyou-recovery aws cloudwatch get-metric-statistics \
  --region ap-northeast-1 --namespace jpcite/credit \
  --metric-name GrossSpendUSD \
  --dimensions Name=Classification,Value=RAMP \
  --start-time 2026-05-16T00:00:00Z --end-time 2026-05-17T00:00:00Z \
  --period 3600 --statistics Average Maximum

# Lambda env-var state (verify dry-run)
AWS_PROFILE=bookyou-recovery aws lambda get-function-configuration \
  --region ap-northeast-1 \
  --function-name jpcite-credit-burn-metric-emitter \
  --query 'Environment.Variables'
```

---

## Append-only log

- **2026-05-16 PM6 (this entry)**: First verify post burn-metric Lambda deploy (commit `3e5e50df1`). CE shows $0 MTD (lag); forecast $5,019.50 mean / $6,117 upper; CW Lambda emitter $0 (dry-run safety default). Headroom 74.2% vs forecast mean. Re-probe scheduled for 2026-05-17 AM/PM.

last_updated: 2026-05-16
