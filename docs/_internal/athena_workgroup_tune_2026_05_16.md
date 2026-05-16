# Athena Workgroup Tuning — 2026-05-16 (PERF-14)

**Lane:** solo
**Workgroup:** `jpcite-credit-2026-05`
**Profile:** `bookyou-recovery`, region `ap-northeast-1`
**Predecessor:** PERF-3 Parquet ZSTD landing
  (`docs/_internal/athena_parquet_perf_2026_05_16.md`), 99.94% scan reduction.

## Goal

Tighten workgroup safety rails now that Parquet-backed top-tier packet
tables scan <1 GB per typical query, and enable query result reuse so
re-runs within 24h are free.

## Before → After config diff

| Setting | Before | After |
|---------|-------:|------:|
| `BytesScannedCutoffPerQuery` | 107,374,182,400 (100 GB) | **50,000,000,000 (50 GB)** |
| `EnforceWorkGroupConfiguration` | true | true (unchanged) |
| `PublishCloudWatchMetricsEnabled` | true | true (unchanged) |
| `RequesterPaysEnabled` | false | false (explicit) |
| `ResultConfiguration.OutputLocation` | `s3://jpcite-credit-993693061769-202605-reports/athena-results/` | unchanged (verified) |
| `EncryptionConfiguration` | SSE_S3 | unchanged (verified) |
| `EngineVersion.Effective` | Athena v3 | unchanged (Athena v3 supports result reuse) |
| Query result reuse (per-query opt-in) | not requested | enabled by callers via `ResultReuseByAgeConfiguration` (24h TTL) |

**Note on the cache control surface.** Athena v3 does not expose
`EnableQueryCachedResults` at workgroup level. Result reuse is a
per-`StartQueryExecution` parameter (`ResultReuseByAgeConfiguration =
{Enabled=true, MaxAgeInMinutes=1440}`). The workgroup tuning here
keeps the cap; the cache is unlocked by callers passing the
result-reuse flag — the helper at
`infra/aws/athena/big_queries/run_query.sh` (and the JPCIR Athena
client) is the canonical caller and now defaults to `Enabled=true,
MaxAgeInMinutes=1440`.

## Why 50 GB and not lower

Parquet-backed Wave 53–67 queries scan **<5 GB** in practice
(`athena_wave67_rerun_2026_05_16.md` total = 4.08 GiB across 7 queries).
50 GB cap = **10× headroom** for legacy JSON-on-S3 sources that have
not yet been migrated (e.g. some Wave 56–58 raw bundles). Going below
50 GB would risk false aborts on those legacy queries.

## Smoke test — cache miss → hit cycle

Q14 variant (`LIMIT 501` instead of 500 — forces fresh execution to
demonstrate miss state):

| Run | QueryExecutionId | DataScanned | WallMs | ReusedPreviousResult |
|-----|------------------|------------:|-------:|----------------------|
| Miss (first exec) | `3aec3491-2164-4a67-83cb-9fe11b600569` | 12,624,140 B (12.04 MiB) | 3,673 | **false** |
| Hit (same SQL re-exec) | `acfd2e6e-bdef-4c6e-a202-99c5705f7645` | **0 B** | **329** | **true** |

Cache hit = **11.2× wall-time speedup**, **0-byte scan (zero cost)**.

Also verified canonical Q14 (`LIMIT 500`) re-exec:

| Run | QueryExecutionId | DataScanned | WallMs | ReusedPreviousResult |
|-----|------------------|------------:|-------:|----------------------|
| Hit (Wave 67 cache) | `01cb71f4-0d18-48fc-a464-c63a980d153c` | 0 B | 365 | **true** |

The Wave 67 re-run from earlier in the day was already cached, so
identical SQL within the 24h TTL window comes back in <400 ms at
zero scan cost.

## Operational impact

- Re-running the Wave 67 7-query battery within 24h = **$0 cost,
  ~2.5 s total wall** (vs ~166 s wall + $0.02 for first run).
- The 50 GB cap leaves >40 GB headroom on every Parquet query we've
  run (peak observed = 4 GiB for the 7-query battery total).
- Legacy JSON queries that previously hit 100 GB are now flagged at
  50 GB — these need explicit PERF-3-style migration before re-enable.

## Verify command

```bash
aws athena get-work-group --region ap-northeast-1 \
  --profile bookyou-recovery \
  --work-group jpcite-credit-2026-05 \
  --query 'WorkGroup.Configuration.{BytesScannedCutoffPerQuery:BytesScannedCutoffPerQuery,OutputLocation:ResultConfiguration.OutputLocation,Enforce:EnforceWorkGroupConfiguration,RequesterPays:RequesterPaysEnabled}'
```

Expected:
```json
{
  "BytesScannedCutoffPerQuery": 50000000000,
  "OutputLocation": "s3://jpcite-credit-993693061769-202605-reports/athena-results/",
  "Enforce": true,
  "RequesterPays": false
}
```
