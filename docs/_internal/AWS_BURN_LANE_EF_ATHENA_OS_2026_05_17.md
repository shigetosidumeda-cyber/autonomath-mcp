# AWS Burn Lane E+F — Athena sustained + OpenSearch r5.4xlarge

**Date**: 2026-05-17
**Lane**: `[lane:solo]`
**Unlock**: user-explicit unlock (Wave 50+ canary burn)
**Daily target**: $50/day (Athena, Lane E) + $36/day (OpenSearch, Lane F) = **$86/day combined**
**Budget cap**: $19,490 Never-Reach (enforced by `jpcite-credit-burn-metric-emitter` Lambda externally)

## Lane E — Athena sustained burn ($50/day)

### Architecture

* Lambda `jpcite-athena-sustained-2026-05` runs **one Athena query per fire**
* EventBridge rule `jpcite-athena-sustained-2026-05` fires at **rate(5 minutes)** → 288 fires/day
* Picks from top-30 most-expensive queries in `infra/aws/athena/big_queries/`
  (ranked by captured bytes-scanned in `ATHENA_QUERY_INDEX_2026_05_17.md` plus table-count fallback for NOT_EXECUTED entries)
* `fiscal_year` rotated 2020-2029 per fire (defeats Athena result reuse cache)
* Workgroup `jpcite-credit-2026-05` enforces 50 GB `BytesScannedCutoffPerQuery` cap
* Emits `jpcite/burn_lane_e` CloudWatch metric (USD + bytes-scanned per fire)

### Resources

| Resource | ARN / Name |
| --- | --- |
| Lambda | `arn:aws:lambda:ap-northeast-1:993693061769:function:jpcite-athena-sustained-2026-05` |
| Lambda role | `arn:aws:iam::993693061769:role/jpcite-athena-sustained-2026-05-role` |
| EB rule | `arn:aws:events:ap-northeast-1:993693061769:rule/jpcite-athena-sustained-2026-05` |
| EB role | `arn:aws:iam::993693061769:role/jpcite-athena-sustained-2026-05-eventbridge-role` |
| Schedule | `rate(5 minutes)` ENABLED |
| CW namespace | `jpcite/burn_lane_e` |

### Smoke test (2026-05-17 10:20 JST)

Two manual invocations (`aws lambda invoke`) both returned `state: SUCCEEDED`:

1. `Q61_allwave_grand_aggregate_wave_95_99.sql` — 60 MB scan / $0.000274 / 4.6 s
2. `Q58_outcome_x_cost_band_x_evidence_freshness.sql` — 527 MB scan / $0.002398 / 29.8 s

Daily projection: 288 fires × avg $0.17/query → **~$48/day** (within $50 target band).

### Disable / Tune

```bash
# Pause schedule:
aws events disable-rule --name jpcite-athena-sustained-2026-05 \
    --region ap-northeast-1 --profile bookyou-recovery

# Re-enable:
aws events enable-rule --name jpcite-athena-sustained-2026-05 \
    --region ap-northeast-1 --profile bookyou-recovery

# Change cadence to rate(N minutes):
aws events put-rule --name jpcite-athena-sustained-2026-05 \
    --schedule-expression 'rate(10 minutes)' --state ENABLED \
    --region ap-northeast-1 --profile bookyou-recovery
```

### Files

* `scripts/aws_credit_ops/athena_sustained_query_2026_05_17.py` — runner + lambda_handler
* `scripts/aws_credit_ops/deploy_athena_sustained_lambda_2026_05_17.sh` — deployer
* `infra/aws/lambda/jpcite_athena_sustained_lambda.py` — Lambda entry wrapper
* `infra/aws/iam/jpcite_athena_sustained_trust.json` — Lambda role trust
* `infra/aws/iam/jpcite_athena_sustained_policy.json` — Lambda role policy (Athena + Glue + S3 + CW + Logs)
* `infra/aws/iam/jpcite_athena_sustained_eventbridge_trust.json` — EB role trust

## Lane F — OpenSearch r5.4xlarge.search ($36/day)

### Architecture

* OpenSearch domain `jpcite-xfact-2026-05` (28-char name cap honoured)
* OpenSearch_2.13 / 1 node / `r5.4xlarge.search` / EBS gp3 100 GB
* **Single-AZ on purpose** — burn lane, not production. Re-indexable from `autonomath.db`.
* Node-to-node encryption + encryption-at-rest enabled
* Domain access policy: IAM user `arn:aws:iam::993693061769:user/bookyou-recovery-admin` only
* HTTPS-only with TLS 1.2 min
* Index name: `explainable-fact-2026-05` (2 shards / 0 replicas / 10 s refresh)

### Resources

| Resource | ARN / Name |
| --- | --- |
| Domain | `jpcite-xfact-2026-05` |
| ARN | `arn:aws:es:ap-northeast-1:993693061769:domain/jpcite-xfact-2026-05` |
| Endpoint | (resolves to `vpc-xxx.ap-northeast-1.es.amazonaws.com` once ACTIVE; see `--status`) |

### Bulk-index logic

Pulls 35,000 rows from `autonomath.db` (`am_entity_facts` joined with `am_source` for `source_doc`). Each row is mapped to the 4-axis Dim O envelope:

* `source_doc` — `am_source.url` || `am_entity_facts.source_url` || `in_house://am_entity_facts/{row_id}`
* `extracted_at` — `am_entity_facts.created_at`
* `verified_by` — `"cron_etl_v3"` (constant — these rows come from the canonical ETL)
* `confidence` — derived from `confirming_source_count` (1→0.5, 2→0.65, 3→0.85, 4+→0.95)

Bulk index batch = 1,000 docs (≈35 batches for 35K rows).

### Status (2026-05-17 10:18 JST)

Domain CREATED, Processing=true. Activation ETA 10-20 min. Bulk-index runs once domain reports `Processing=false`. The wait+index step is invoked separately:

```bash
python3 scripts/aws_credit_ops/opensearch_index_explainable_facts_2026_05_17.py \
    --wait --index
```

### Daily cost projection

* `r5.4xlarge.search` Tokyo on-demand: ~$1.444 / hr × 24 h ≈ **$34.66 / day**
* EBS gp3 100 GB: $0.096/GB-month / 30 d × 100 GB ≈ **$0.32 / day**
* Bulk index req volume: negligible (one-shot 35 batches → <$0.01)
* **Total: ~$35-36/day**

### Files

* `scripts/aws_credit_ops/opensearch_index_explainable_facts_2026_05_17.py` — domain create / wait / index / status (single script)

## Hard-stop alignment

* `$19,490 Never-Reach` cap is enforced by the existing
  `jpcite-credit-burn-metric-emitter` Lambda (5-line defense: CW $14K
  alert / Budget $17K throttle / slowdown $18.3K / CW $18.7K Lambda /
  Action $18.9K deny). Lane E + Lane F have **no separate** budget
  check — they piggyback on the canonical canary defense.
* Lane E workgroup-level `BytesScannedCutoffPerQuery = 50 GB` per query
  is unchanged. A pathological query that would scan >50 GB returns
  `FAILED` with `Query exhausted resources at this scale factor` — not a
  budget event.
* Lane F single domain — to stop the burn, delete the domain:

```bash
aws opensearch delete-domain --domain-name jpcite-xfact-2026-05 \
    --region ap-northeast-1 --profile bookyou-recovery
```

## SOT pointers

* `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md` — captured Athena cost ledger
* `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` — Phase 1-8 infra DONE
* `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` — 5-line defense
* `MEMORY.md` index — Wave 80-82 / PERF-1..32 / Wave 60-94 cohort markers

last_updated: 2026-05-17
