# PERF-14 Athena Workgroup Tuning — 2026-05-17 PROPOSAL

**Lane:** `[lane:solo]`  ·  **Mode:** PROPOSAL-ONLY (no AWS mutation applied)
**Workgroup:** `jpcite-credit-2026-05`  ·  **Profile:** `bookyou-recovery`  ·  **Region:** `ap-northeast-1`
**Predecessor:** `docs/_internal/athena_workgroup_tune_2026_05_16.md` (PERF-14 initial 100GB → 50GB landing)
**Predecessor audit:** `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md` (Q1-Q47 captured-run cost telemetry)

## TL;DR

PERF-14 already landed 100GB→**50GB** cap + caller-side `ResultReuseByAgeConfiguration` on 2026-05-16. Empirical data (47 captured Athena runs across Wave 53-94, 9.20 GiB scanned total, $0.0451 total spend) supports a further tightening to **10GB cap** (5.3× safety margin over the largest captured query) without breaking any executed workload. Workgroup-default result-reuse is **NOT** technically available in Athena v3 (per Athena release notes — confirmed in predecessor doc §"Note on the cache control surface"); reuse stays at per-`StartQueryExecution` level via canonical caller `infra/aws/athena/big_queries/run_query.sh`.

**Decision gate:** `live_aws_commands_allowed=false` is held at **150+ tick absolute堅守**. This document is **PROPOSAL-ONLY**. No AWS mutation will be executed without an explicit operator unlock token. See §"Apply procedure (when unlocked)" for the gated runbook.

## Current state (snapshot 2026-05-17)

`aws athena get-work-group --work-group jpcite-credit-2026-05 --profile bookyou-recovery --region ap-northeast-1`:

```json
{
  "ResultConfiguration": {
    "OutputLocation": "s3://jpcite-credit-993693061769-202605-reports/athena-results/",
    "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"}
  },
  "EnforceWorkGroupConfiguration": false,
  "PublishCloudWatchMetricsEnabled": true,
  "BytesScannedCutoffPerQuery": 50000000000,
  "RequesterPaysEnabled": false,
  "EngineVersion": {
    "SelectedEngineVersion": "AUTO",
    "EffectiveEngineVersion": "Athena engine version 3"
  },
  "EnableMinimumEncryptionConfiguration": false
}
```

`aws athena list-work-groups`: 2 workgroups (`jpcite-credit-2026-05` ENABLED, `primary` ENABLED).

## Why 50GB is now over-provisioned

From `ATHENA_QUERY_INDEX_2026_05_17.md` (47 captured runs across Wave 53-94):

| metric                                   | value                              |
|------------------------------------------|------------------------------------|
| Total captured runs                      | 47 SUCCEEDED                       |
| Total bytes scanned                      | 9.20 GiB across all 47 runs        |
| Total spend                              | $0.0451 (4.51 cents)               |
| Max single-query scan                    | **1.90 GiB** (Q47 grand-aggregate) |
| Max single-query cost                    | **$0.0093** (Q47)                  |
| Median single-query scan                 | ≤500 MiB                           |
| Cap headroom utilization at 50GB         | **3.8%** of cap (1.90 / 50)        |

The captured largest = Q47 `q47_allwave_53_94_grand_aggregate.sql` UNION-ALL grand-aggregate at 77 packet tables; this is the most expensive query the catalog has produced post Wave 53-94. The next-largest tier (Q42 / Q53 / Q57) are NOT_EXECUTED in the audit log but, by structural similarity, are not expected to exceed 3-4 GiB (each adds at most ~5-10 tables to Q47's 77-table UNION).

## Proposed tuning

| Setting                              | Current (post 2026-05-16 PERF-14) | Proposed (this doc)             |
|--------------------------------------|----------------------------------:|---------------------------------:|
| `BytesScannedCutoffPerQuery`         | 50,000,000,000 (50 GB)            | **10,737,418,240 (10 GiB)**     |
| `EnforceWorkGroupConfiguration`      | false                             | **true** (force cap on callers) |
| `PublishCloudWatchMetricsEnabled`    | true                              | true (unchanged)                |
| `RequesterPaysEnabled`               | false                             | false (unchanged)               |
| `ResultConfiguration.OutputLocation` | unchanged                         | unchanged                       |
| `EncryptionConfiguration`            | SSE_S3                            | unchanged                       |
| `EngineVersion`                      | Athena v3                         | unchanged                       |
| Per-query result reuse (caller-side) | enabled by caller, 24h TTL        | unchanged (PERF-14 originalist) |

### Rationale per setting

- **10 GiB cap = 5.3× safety margin over Q47 (1.90 GiB).** Captures all 47 historical successful runs without false-aborting any of them. Still allows up to ~5 GiB grand-aggregates yet-to-execute (Q42 / Q53 / Q57). Going below 5 GiB would risk false-abort on Q47-class grand-aggregates — see CONSTRAINTS.
- **`EnforceWorkGroupConfiguration=true`** prevents caller-side `BytesScannedCutoffPerQuery` overrides via `StartQueryExecution.ResultConfigurationOverride`. Today `false` means a misconfigured caller could blow the cap by passing a higher value at submit-time. Flipping `true` makes the workgroup cap binding regardless of caller. Trade-off: callers that legitimately need a smaller cap (e.g. dev smoke jobs) cannot tighten further per-query — they would need a separate workgroup. Given solo-ops cadence + 1 active workgroup, this is acceptable.
- **No change to result-reuse mechanism.** Athena v3 still does not expose `EnableQueryCachedResults` at workgroup level (verified again 2026-05-17). The canonical caller `infra/aws/athena/big_queries/run_query.sh` already passes `ResultReuseByAgeConfiguration={Enabled=true, MaxAgeInMinutes=1440}` (24 h TTL) → 11.2× wall-time speedup on hit + $0 scan cost (per predecessor doc smoke run). The proposal here does not touch this.
- **Result-reuse pricing model verified safe.** Athena charges $5/TB on bytes scanned; cache HIT returns 0 bytes scanned → $0. There is no per-cache-hit fee. The cache lives in `OutputLocation` (S3) and accrues only S3 storage cost at $0.023/GB-month for results bucket — current results bucket is in single-digit GB scale, so cache storage cost is <$0.25/month. No surprise cost path.

## Constraints (per task brief)

1. **DO NOT enable result-cache if pricing is unpredictable** — verified above ($0 per hit, marginal S3 storage). Caller-side reuse is already live; no workgroup-level toggle exists. ✓ SAFE.
2. **DO NOT tighten cap below 5 GiB** — would risk false-abort on Q42 / Q47 / Q53 / Q57 grand-aggregate family. Proposal = 10 GiB sits well above this floor. ✓ SAFE.
3. **`live_aws_commands_allowed=false`** is the absolute non-negotiable. Workgroup config IS a live mutation. Apply only on explicit operator unlock. ✓ DEFERRED.

## Apply procedure (when unlocked)

DO NOT run any of the following without an explicit user "unlock live AWS commands" instruction. When unlocked:

```bash
# 1. Snapshot current config for rollback evidence
aws athena get-work-group \
  --work-group jpcite-credit-2026-05 \
  --profile bookyou-recovery \
  --region ap-northeast-1 \
  --output json \
  > /tmp/wg_before_perf14_tighten.json

# 2. Apply tuning
aws athena update-work-group \
  --work-group jpcite-credit-2026-05 \
  --profile bookyou-recovery \
  --region ap-northeast-1 \
  --configuration-updates '{
    "BytesScannedCutoffPerQueryUpdate": 10737418240,
    "EnforceWorkGroupConfiguration": true,
    "RequesterPaysEnabled": false,
    "PublishCloudWatchMetricsEnabled": true
  }'

# 3. Verify
aws athena get-work-group \
  --work-group jpcite-credit-2026-05 \
  --profile bookyou-recovery \
  --region ap-northeast-1 \
  --query 'WorkGroup.Configuration.{
    BytesScannedCutoffPerQuery: BytesScannedCutoffPerQuery,
    Enforce: EnforceWorkGroupConfiguration,
    OutputLocation: ResultConfiguration.OutputLocation,
    RequesterPays: RequesterPaysEnabled
  }'

# Expected:
# {
#   "BytesScannedCutoffPerQuery": 10737418240,
#   "Enforce": true,
#   "OutputLocation": "s3://jpcite-credit-993693061769-202605-reports/athena-results/",
#   "RequesterPays": false
# }

# 4. Smoke — re-run a captured cheap query (Q43 = 0.42 MiB) under new cap
bash infra/aws/athena/big_queries/run_query.sh \
  wave94/q43_wave92_product_safety_x_wave81_esg_materiality.sql
# Expect: SUCCEEDED, scan ≤ 0.5 MiB, cache HIT 0 bytes on second invocation
```

## Rollback procedure

```bash
aws athena update-work-group \
  --work-group jpcite-credit-2026-05 \
  --profile bookyou-recovery \
  --region ap-northeast-1 \
  --configuration-updates '{
    "BytesScannedCutoffPerQueryUpdate": 50000000000,
    "EnforceWorkGroupConfiguration": false
  }'
```

(Restores pre-2026-05-17 state per snapshot file above.)

## Expected impact

- **Cost ceiling per query**: $5/TB × 10 GiB = **$0.0500 max per query** (down from $0.250 max under 50 GB cap).
- **False-abort risk**: 0% on captured 47 runs (max captured = 1.90 GiB ≪ 10 GiB). Forward-projected on Q42 / Q53 / Q57 = expected 2-4 GiB, still ≪ 10 GiB.
- **Caller surface**: callers that previously could submit up to 50 GiB queries via override are now hard-capped at 10 GiB workgroup default. Today no caller does this — all run via `run_query.sh` which inherits workgroup default.
- **No change to result-reuse, output location, encryption, engine version, CloudWatch metrics publication.**

## Acceptance criteria

This document is **proposal-only**. The acceptance criterion for applying it is: a user message containing an explicit live-AWS unlock token (e.g. `--unlock-live-aws-commands`, "apply PERF-14 tuning", or equivalent). Until then this doc is the SOT for what would change.

last_updated: 2026-05-17
