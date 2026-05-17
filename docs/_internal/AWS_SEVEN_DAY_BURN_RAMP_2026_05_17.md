# AWS 7-Day Continuous Moat-Burn Ramp (2026-05-17)

**Lane:** solo
**Mode:** LIVE — user explicit unlock `--unlock-live-aws-commands` AUTHORIZED
**Profile:** `bookyou-recovery`
**Region:** `ap-northeast-1`
**Hard-stop:** $18,300 MTD gross trigger / $18,900 Budget Action / $19,490 never-reach absolute
**Goal:** drain remaining ~$13K of AWS credit envelope in 7 days via moat-bearing burn

## Starting state (verified 2026-05-17 PM)

| Metric | Value | Source |
|---|---|---|
| MTD gross spend | $3,101.80 | `aws ce get-cost-and-usage` with Credit filter |
| Credit remaining vs $19,490 | $16,388.20 | derived |
| Quota request `177898005900961` (G+VT Spot vCPU) | CASE_CLOSED at 256 | `list-requested-service-quota-change-history` |
| Live GPU vCPU quota `L-3819A6DF` | 64 (account-level) | `get-service-quota` |
| Batch GPU compute env `jpcite-credit-ec2-spot-gpu` maxvCpus | **256 (scaled LIVE this session)** | `update-compute-environment` |
| Running GPU Batch jobs | 0 (queue ready) | `list-jobs RUNNING` |
| In-progress SageMaker training jobs | 5 (multitask + simcse + kg-rotate + kg-transe + kg-complex) | `list-training-jobs InProgress` |
| OpenSearch `jpcite-xfact-2026-05` | r5.4xlarge×3 + ultrawarm1×3 + master×3 — LIVE | `describe-domain` |
| Burn-metric Lambda | LIVE @ 12/hr | CloudWatch Invocations |

## 7-day burn plan

Daily target: **$2,020/day** (band $1,800-$2,800). Total 7d: **$14,140**.
Final projected MTD post-ramp: **$17,241** — safely under $18,300 hard-stop.

| Sub-lane | $/day | 7-day total | Moat contribution |
|---|---:|---:|---|
| Batch GPU sustained (5x g4dn.12xlarge spot) | $1,000 | $7,000 | M5/M6/M11 model improvement; FAISS shard re-build |
| OpenSearch sustained (already LIVE) | $130 | $910 | entity-fact serving substrate |
| Athena moat queries (5 queries × 30 min × 7d) | $80 | $560 | cohort + lineage traversal outputs |
| Textract OCR continuous | $300 | $2,100 | ministry PDF corpus expansion |
| Batch transform PM12 cycle (20 jobs × 7) | $250 | $1,750 | embedding refresh post-M5/M6 v2 |
| Storage burn (S3 + Glue + EBS) | $260 | $1,820 | embeddings + Parquet shards |
| **Total** | **$2,020** | **$14,140** | — |

### Cycle cadence (EventBridge schedules)

| Cycle | Cadence | Cycles/7d | Notes |
|---|---|---:|---|
| SageMaker training | `rate(6 hours)` | 4×7=28 | per-axis; 6 axes -> 119 sub-runs over 7d |
| Batch transform PM12 | `rate(24 hours)` | 7 | 20 jobs per cycle |
| Textract OCR | `rate(4 hours)` | 42 | 200 PDFs × 30 pages × $0.05 = $300/cycle |
| Athena moat | `rate(30 minutes)` | 336 | 5 query templates rotating |
| Burn monitor | `rate(5 minutes)` | LIVE | unchanged |

### SageMaker training cycles (6 axes)

1. **M5 v2 SimCSE iter** — `sagemaker_simcse_finetune_2026_05_17.py`, ml.g4dn.12xlarge, 12h, $70/cycle × 28 = $1,960
2. **M6 Cross-encoder iter** — `sagemaker_cross_encoder_finetune_2026_05_17.py`, ml.g4dn.12xlarge, 12h, $70/cycle × 28 = $1,960
3. **M11 Active learning iter** — `sagemaker_m11_al_iter_2026_05_17.py`, ml.g4dn.4xlarge, 6h, $30/cycle × 28 = $840
4. **M11 Distill v2** — `sagemaker_m11_distill_2026_05_17.py`, ml.g4dn.12xlarge, 12h, $60/cycle × 14 = $840
5. **M11 KG completion iter** — `sagemaker_kg_completion_submit_2026_05_17.py`, ml.g4dn.4xlarge, 6h, $25/cycle × 14 = $350
6. **M11 Multitask v2 finetune** — `sagemaker_multitask_finetune_2026_05_17.py`, ml.g4dn.12xlarge, 24h, $95/cycle × 7 = $665

**SageMaker re-train subtotal $6,615 over 7d** (separate from Batch GPU env burn).

### Athena moat queries (5 templates)

- `industry_x_geo_cohort_aggregation` — JSIC × prefecture × program tier
- `program_x_law_lineage_traverse` — 9,484 laws × 11,601 programs
- `case_cohort_match_at_scale` — 採択 × adoption × 4,935 N7 segments
- `amendment_diff_temporal_join` — 14,596 snapshots × as_of × 5yr
- `ma_target_pool_full_corpus` — houjin_watch × M&A signal

Output: S3 derived bucket `jpcite-credit-993693061769-202605-derived/athena_moat_queries/`. Result Reuse enabled (per memory `feedback_athena_workgroup_50gb_result_reuse`).

## Forbidden (per goal)

- CloudFront sustained load (pure burn, no moat)
- CodeBuild burst (pure burn)
- Lambda mass-invoke (pure burn)
- LLM API calls (OPERATOR-LLM API banned)

## 5-line hard-stop defense (active)

Per memory `feedback_aws_canary_hard_stop_5_line_defense`:

1. CloudWatch alarm at $14K
2. AWS Budget alarm at $17K
3. Slowdown action at $18,300 (this orchestrator's preflight aborts)
4. CloudWatch Lambda + log auto-pause at $18,700
5. Budget Action deny at $18,900

`$19,490` is **absolute never-reach**.

## Execution log

### Step 1: Scale Batch GPU compute env 64 -> 256 vCPU (COMPLETED LIVE)

```bash
.venv/bin/python -m scripts.aws_credit_ops.seven_day_burn_ramp_2026_05_17 \
  --commit --unlock-live-aws-commands
```

`jpcite-credit-ec2-spot-gpu` `maxvCpus` updated 64 -> 256 (verified VALID/ENABLED).

### Step 2: Submit GPU job waves (operator follow-on)

```bash
# Cross-encoder finetune (M6)
.venv/bin/python -m scripts.aws_credit_ops.sagemaker_cross_encoder_finetune_2026_05_17 \
  --commit --unlock-live-aws-commands

# SimCSE finetune (M5)
.venv/bin/python -m scripts.aws_credit_ops.sagemaker_simcse_finetune_2026_05_17 \
  --commit --unlock-live-aws-commands

# M11 distill / multitask / KG completion
.venv/bin/python -m scripts.aws_credit_ops.sagemaker_m11_distill_2026_05_17 \
  --commit --unlock-live-aws-commands
.venv/bin/python -m scripts.aws_credit_ops.sagemaker_multitask_finetune_2026_05_17 \
  --commit --unlock-live-aws-commands
.venv/bin/python -m scripts.aws_credit_ops.sagemaker_kg_completion_submit_2026_05_17 \
  --commit --unlock-live-aws-commands
```

### Step 3: Deploy cron orchestrator (follow-on)

Reuse existing patterns:

```bash
bash scripts/aws_credit_ops/deploy_athena_sustained_lambda_2026_05_17.sh
aws events enable-rule --name jpcite-athena-sustained-2026-05 \
  --profile bookyou-recovery --region ap-northeast-1
```

(SageMaker training cron, Textract OCR cron, batch transform cron — analogous deploy scripts to be added per pattern.)

## Ledger

Append-only ledger at `docs/_internal/SEVEN_DAY_BURN_LEDGER_2026_05_17.md`. Each orchestrator run appends a tick with MTD gross/net + sub-plan breakdown.

JSON plan snapshot at `docs/_internal/SEVEN_DAY_BURN_PLAN_2026_05_17.json`.

## Re-affirmed absolute constraints

- `$19,490` is absolute never-reach
- live AWS authorized via `--unlock-live-aws-commands` operator token
- NO LLM API
- `[lane:solo]`
- `safe_commit.sh` used for git commit (no `--no-verify`)
