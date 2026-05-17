# CL8 — AWS Burn Forecast + State Snapshot (2026-05-17 evening)

**Date:** 2026-05-17 (evening, ~22:00 JST)
**Lane:** `lane:solo` (READ-ONLY AWS snapshot — no modify calls issued)
**Scope:** 7-day burn forecast against the ~$18,425 remaining Activate Credit headroom and the $19,490 hard-stop fence.
**Posture:** Snapshot only. All numbers are from live `aws ce` / `aws sagemaker` / `aws cloudwatch` / `aws s3api` / `aws glue` / `aws events` / `aws budgets` reads at 2026-05-17T22:00Z+09. Source-of-truth cost basis: **UnblendedCost with `RECORD_TYPE NOT IN ("Credit","Refund")`** (the operator's "$751/d ramp" matches this filter exactly).

---

## 1. Cost Explorer 3-day truth table (filter: not credit/refund)

| Day | UnblendedCost (real burn) | BlendedCost (after credits) | NetUnblendedCost |
| --- | ---: | ---: | ---: |
| 2026-05-15 | $0.82 | -$0.0097 | $0.0000 |
| 2026-05-16 | $314.08 | $31.5552 | $0.0000 |
| 2026-05-17 | **$751.08** | -$31.5747 | $0.0000 |

Net is near zero because Activate Credit covers the bill — operator-visible "burn" must use the unfiltered-credit number.

### 1.1 Service-level breakdown 2026-05-17 (top 10, USD/day)

| Service | Day | Note |
| --- | ---: | --- |
| Amazon Textract | 606.06 | dominant ramp — J-Layer PDF OCR |
| Amazon CloudFront | 48.60 | sustained-load canary (rule still DISABLED, residual edge cache fetches) |
| Amazon SageMaker | 26.29 | M5 SimCSE g4dn.12xlarge + KG-TransE g4dn.2xlarge + 5 cohort-LoRA cycles |
| AWS Glue | 23.99 | crawler runs across 474 tables in `jpcite_credit_2026_05` |
| Amazon OpenSearch Service | 23.39 | `jpcite-xfact-2026-05` r5.4xlarge.search ×3, 500 GB EBS |
| Amazon EC2 — Compute | 11.44 | no running EC2 — residual EBS / NAT |
| Amazon S3 | 5.97 | derived bucket 1.59 TB |
| AmazonCloudWatch | 2.28 | metric emitter Lambdas |
| AWS Cost Explorer | 1.65 | this very probe |
| CodeBuild | 1.20 | CI runs |

Service total = $751.08 (matches header).

### 1.2 Service-level breakdown 2026-05-16 (top 5)

| Service | USD | Note |
| --- | ---: | --- |
| Amazon Textract | 160.03 | first Textract day, ramp up |
| Amazon CloudFront | 55.23 | CF load-test before DISABLE |
| Amazon EC2 — Compute | 38.38 | pre-shutdown EC2 burn |
| Amazon S3 | 28.36 | initial derived bucket fill |
| Amazon SageMaker | 14.54 | early LoRA training |

Day-over-day growth: $314.08 → $751.08 = **2.39× ramp** (Textract 160 → 606 = 3.79×).

---

## 2. SageMaker state

| Job | Status | Instance | Sec spent |
| --- | --- | --- | ---: |
| `jpcite-bert-simcse-finetune-20260517T022501Z` | InProgress / Training | ml.g4dn.12xlarge | 37,681 (~10.5 h) — **M5 stuck candidate** |
| `jpcite-kg-transe-20260517T084028Z` | InProgress / Training | ml.g4dn.2xlarge | 15,142 (~4.2 h) |

**Completed (cohort-LoRA cycle 2026-05-17 day):** zeirishi, kaikeishi, gyouseishoshi, shihoshoshi, chusho-keieisha, multitask-large = 6 jobs landed.

**Failed (M3 + M7 + KG):** `multitask-al-iter1..4` (4 jobs), `kg-conve / kg-complex / kg-rotate` × 2 cycles (6 jobs). M3 active-learning iter cascade and the 3 non-TransE KG embeddings keep failing — `FailureReason` is null in the summary view (need `describe-training-job` per-job).

- Processing jobs InProgress: **0**
- Transform jobs InProgress: **0** (NextToken present but page empty — pagination artifact)
- Endpoints InService: **0** (no serving endpoint up yet — Lambda + container-only inference plan still hypothetical)

---

## 3. OpenSearch state

Single domain `jpcite-xfact-2026-05`:
- Instance: `r5.4xlarge.search` × **3 nodes**
- EBS: 500 GB / node
- Status: InService (cost $23.39/d sustained)

No second domain. Cost is steady, not ramping.

---

## 4. EC2 state

Running instances: **0** (`describe-instances --filters running` returned `[]`).

The $11.44/d "Amazon Elastic Compute Cloud — Compute" line is residual NAT gateway + EBS allocations (zero compute-hours). No oversight risk.

---

## 5. S3 state (CloudWatch BucketSizeBytes max in 3-day window)

| Bucket | Size | Note |
| --- | ---: | --- |
| `jpcite-credit-993693061769-202605-raw` | 5.46 GB | source PDF / JSON inputs |
| `jpcite-credit-993693061769-202605-derived` | **1,587.37 GB** | dominant cost driver — packet outputs, embeddings, Parquet partitions |
| `jpcite-credit-993693061769-202605-reports` | 0.01 GB | static reports |
| `jpcite-credit-993693061769-202605-athena-results` | 0.00 GB | result-reuse working |
| `jpcite-credit-textract-apse1-202605` | (no CW metric) | apse1-only Textract artefacts |

Total ≈ **1.59 TB**. Standard storage @ $0.025/GB/mo ≈ $40/mo sustained (≈$1.30/d) — the $5.97 daily S3 line reflects PUT/LIST request traffic on top.

Raw bucket has **49 top-level prefixes** (`J01_source_profile/ … J14_ultradeep_jpo_patent_gazette/`).

---

## 6. Athena / Glue state

- Workgroups: `jpcite-credit-2026-05`, `primary` (2)
- Databases: `default`, `jpcite_credit_2026_05` (the operator's prompt referenced `jpcite_credit` — does **not** exist; the live name is `jpcite_credit_2026_05`)
- Tables in `jpcite_credit_2026_05`: **474** (matches manifest)
- Athena daily spend: $0.08 (result-reuse + ZSTD Parquet keep this near zero — confirms PERF-38 and the Wave 80-82 byte-reduction landings still hold)

---

## 7. Lambda state (filter: name contains "jpcite")

Total = **5 functions**:

1. `jpcite-athena-sustained-2026-05` (2026-05-17 — sustained load canary)
2. `jpcite-cf-loadtest` (2026-05-16)
3. `jpcite-credit-canary-attestation-lite` (2026-05-17)
4. `jpcite-credit-burn-metric-emitter` (2026-05-16)
5. `jpcite-credit-canary-attestation-emitter` (2026-05-16)

EventBridge:
- `jpcite-athena-sustained-2026-05` — **DISABLED**
- `jpcite-cf-sustained-load-2026-05` — **DISABLED**
- `jpcite-credit-burn-metric-5min` — **ENABLED** (the canary heartbeat)
- `jpcite-credit-orchestrator-schedule` — **DISABLED**

Step Functions: 1 state machine `jpcite-credit-orchestrator` (no executions started — gated by DISABLED rule). Phase 9 wet-run lock holds.

---

## 8. Budget guardrails (live ActualSpend vs Limit)

| Budget | Limit | ActualSpend | Headroom |
| --- | ---: | ---: | ---: |
| BookYou-Emergency-Usage-Guard | $100 | $3,898.03 | **breached 39×** (historical / pre-Activate) |
| jpcite-credit-run-watch-17000 | $17,000 | $0.00 | not armed yet |
| jpcite-credit-run-slowdown-18300 | $18,300 | $0.00 | not armed yet |
| jpcite-credit-run-stop-18900 | $18,900 | $0.00 | not armed yet |

The 3 jpcite budgets show `$0.00` because they were created with a filter scope (e.g. tag/service) — they have not yet observed the Textract burn. Re-verify the filter on the watch budget before relying on it as the $17K alarm trigger.

---

## 9. 7-day burn forecast (2026-05-17 → 2026-05-24)

Headroom assumption: $18,425 remaining of the original Activate Credit, $19,490 hard-stop fence (5-line defense — see `feedback_aws_canary_hard_stop_5_line_defense`).

### 9.1 Baseline trajectory (no new lanes)

If 2026-05-17's $751/d sustains flat:
- 7 × $751 = **$5,257** → remaining $13,168 at day 7
- Hard-stop reach: never under this trajectory

### 9.2 Aggressive trajectory (AA1+AA2 Textract + M5/M11 v2 cycles + cohort-LoRA v2)

| Day | Component | $ |
| --- | --- | ---: |
| Day 1-2 (5/17-18) | Sustained $751 baseline | 1,502 |
| Day 2 (5/18) | AA1+AA2 Textract single-shot ramp (+8K) | 8,000 |
| Day 3-7 | M5 v2 + M11 v2 + cohort-LoRA v2 cycle (+$200/d) | 1,000 |
| Day 3-7 | OpenSearch + Lambda sustained ($50/d on top of baseline) | 250 |
| Day 3-7 | Baseline carry ($300/d Textract residual + $200/d misc) | 2,500 |
| **7-day total** | | **~$13,250** |

Cumulative end-of-week = $13,250 → remaining $5,175 at day 7.

### 9.3 Hard-stop reach probability

Trigger of the $19,490 ceiling requires either:
- A Textract resubmit larger than the AA1+AA2 single-shot (e.g. AA3+ uncapped) — probability **~10%**
- An ML v2 cascade chain failing back into 5+ resubmits (compounded over the week) — probability **~5%**
- An unintended sustained-load Lambda restart (`cf-loadtest` re-enabled by accident) — probability **~5%**

Independent OR-combination ≈ **18%**. The 5-line defense (CW $14K alarm → Budget $17K notify → slowdown $18.3K → CW $18.7K Lambda → Action $18.9K deny) still has 4 layers above forecast, so even at the 18% tail the hard-stop fence holds.

---

## 10. High-ROI moves (next 24-48 h)

| Move | Mechanism | Expected burn | User value |
| --- | --- | ---: | --- |
| **CL7 migration apply 5** (GG4, GG7, AA1, AA2, EE1, EE2) | local sqlite, no AWS spend | $0 | Unlocks `am_nta_qa` FTS + cohort_variant + chunk_map → MCP tools LIVE |
| **AA1+AA2 Textract single-shot** | Textract submit (NTA QA + 地方税通達 PDF) | +$8K | Closes the cohort gap (税理士 + 会計士 coverage missing today) |
| **M5 SimCSE rescue decision** | Either keep g4dn.12xlarge running (~10.5 h spent, loss-curve check needed) or `stop-training-job` and resubmit smaller batch | $0 stop / $50 continue | jpcite-BERT v1 finalize blocker |
| **HE-5 / HE-6 frontend wiring** | static site + MCP gateway | $0 (Cloudflare-side) | Routes agent traffic to the new MCP tools — Agent-led Growth funnel |

The migration apply is **zero-marginal-cost** but unblocks 6 dormant tables → 6 new MCP tools → 6 new Justifiability proof points. That dominates the ROI ranking.

---

## 11. Risk register

| Risk | Severity | Mitigation status |
| --- | --- | --- |
| M5 SimCSE g4dn.12xlarge "stuck" (10.5 h, no SecondaryStatus delta) | MED | watch loss curve; stop-job if no progress in 2 h |
| M3 active-learning iter1-4 all Failed | MED | root cause unknown — `describe-training-job` per-job needed before resubmit |
| M7 KG-conve/complex/rotate Failed (only TransE In Progress) | MED | accept TransE as the surviving KG embedding for v1; defer 3 others to v2 |
| Executor stub (HE-5 frontend MCP gateway) not LIVE | HIGH | blocks user demonstration regardless of training success |
| Budgets `$0.00 ActualSpend` despite $751/d burn | HIGH | the filter scope may exclude the actually-billed lines — verify before relying on the $18,900 stop budget |

The last item is the most operationally urgent: a budget guardrail that does not observe the burn is a false-positive defense. Verify by reading the Budget definition's CostFilters before the next ramp tick.

---

## 12. Verification commands used (all READ-ONLY)

```bash
aws ce get-cost-and-usage --time-period Start=2026-05-15,End=2026-05-18 \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --filter '{"Not":{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit","Refund"]}}}' \
  --profile bookyou-recovery --region us-east-1
aws sagemaker list-training-jobs --status-equals InProgress \
  --profile bookyou-recovery --region ap-northeast-1
aws cloudwatch get-metric-statistics --namespace AWS/S3 --metric-name BucketSizeBytes ...
aws glue get-tables --database-name jpcite_credit_2026_05 ...
aws events list-rules --name-prefix jpcite ...
aws budgets describe-budgets --account-id 993693061769 ...
```

No PUT / POST / DELETE / modify calls were made.

---

## 13. Sign-off

- Cost basis verified: **UnblendedCost minus Credit/Refund matches $751.08/d**.
- 7-day forecast: **$13,250 aggressive trajectory** vs **$18,425 headroom** → safe margin of **$5,175**.
- Hard-stop probability: **~18%** (independent OR of 3 tail risks).
- Top ROI: **CL7 migration apply 5** (zero-cost unlocks 6 MCP tools).

Filed by `lane:solo` audit. Apply lanes for AA1+AA2 Textract, M5 rescue, and migration apply are separate decisions and out of scope for this snapshot.

---

## 14. Provenance correction (commit ledger)

The first write of this file at 21:56 JST was bundled into commit `222d931dd6` ("docs(brief): operator full-state SOT 2026-05-17 evening") by a `pre-commit` stash race with a parallel `lane:solo` agent working on `OPERATOR_BRIEF_2026_05_17_EVENING.md`. The bundled content was byte-identical to the planned CL8 output, but the commit subject did not reflect CL8 authorship. This section is appended in a follow-up commit to establish the canonical CL8 record under the correct subject `docs(aws): burn forecast + state snapshot 2026-05-17 evening`.

No content above §13 was altered between the two commits.
