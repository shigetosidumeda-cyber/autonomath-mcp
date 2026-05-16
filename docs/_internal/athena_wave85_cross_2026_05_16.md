# Athena Wave 85 cross-join run report

**Date:** 2026-05-16 (executed late, 2026-05-17 ledger)
**Author:** jpcite ops (solo)
**Profile:** `bookyou-recovery` / region `ap-northeast-1`
**Workgroup:** `jpcite-credit-2026-05`
**Database:** `jpcite_credit_2026_05`
**Glue catalog state:** 237 tables (verified via `aws glue get-tables` paginated walk)

## Scope

5 new cross-join queries that leverage Wave 83-85 generators on top of the
existing Wave 53-82 corpus. Successor cohort to the wave82 Q23-Q27 family
(supply / ESG / IP) — adds climate-physical / demographics / cybersec axes
+ a refreshed grand aggregate that now covers Wave 53 → 85.

- **Q28** Wave 83 climate physical × Wave 81 ESG materiality (climate × ESG)
- **Q29** Wave 84 demographics × Wave 57 geographic (demographic × geo)
- **Q30** Wave 85 cybersec × Wave 67 tech infra (cybersec × tech)
- **Q31** Wave 83-85 × jsic_major intersection (5 wave_family + foundation)
- **Q32** All-Wave grand aggregate (53 → 85) row count per family

All queries land in `infra/aws/athena/big_queries/wave85/`. Result reuse
on `jpcite-credit-2026-05` workgroup is enabled so the per-run scan is the
delta on top of cached results.

## Run summary

| Query | exec_id | wall | bytes scanned | cost USD |
| --- | --- | --- | --- | --- |
| Q28 climate × ESG | `9c347ea0-74ee-4b39-b1ef-5e9e5a6e7460` | 8s | 187.43 KiB (191,924 B) | $0.0000 (result reuse hit) |
| Q29 demographic × geo | `b7a84d1a-fc6a-4328-80ea-581d7e3b4910` | 71s | 423.91 MiB (444,502,576 B) | $0.0020 |
| Q30 cybersec × tech | `d40bbe35-4700-4dc3-aa4f-c6d8737b7d01` | 7s | 351.79 KiB (360,239 B) | $0.0000 (result reuse hit) |
| Q31 wave83-85 × jsic | `f89411cc-f050-4019-bb64-32a507b05769` | 31s | 433.35 MiB (454,402,529 B) | $0.0021 |
| Q32 grand aggregate (53-85) | `0daa7c55-106d-4ddd-8d84-ab410f63181a` | 79s | 1684.21 MiB (1,766,021,904 B) | $0.0080 |
| **TOTAL** | — | 196s wall | **~2,665 MB (2.60 GiB)** | **$0.0121** |

50 GB PERF-14 cap honored on every query (largest = Q32 at 1.65 GiB, ~3% of
cap). All 5 queries SUCCEEDED on first call.

## Findings

- **Result reuse pays off**: Q28 + Q30 came back at 8s / 7s wall with effectively
  zero bytes scanned because the wave82 Q23-Q27 lineage warmed the same source
  files. Bytes scanned of 188-352 KiB is the metadata + manifest envelope, not
  data. This is the canonical wave-on-wave incremental cost pattern — each new
  wave only pays scan on the genuinely new tables it touches.
- **Q29 + Q31 hit ~430 MiB each** because the Wave 84 demographic proxy tables
  (`city_industry_diversification`, `prefecture_industry_inbound`,
  `city_size_subsidy_propensity`, `rural_subsidy_coverage`) and the Wave 57
  geographic family had not been touched together before. First-touch on these
  pairs scans the underlying Parquet. Subsequent re-runs will hit result reuse.
- **Q32 = 1.65 GiB** because it touches every wave family from 53 → 85 in one
  pass. This is the "footprint of everything" query — the cohort + foundation
  table joined under one UNION ALL grand. Even so, $0.0080 per run is trivial
  vs the 50 GB cap budget.
- **Wave 84 is intentionally proxy-only** in these queries: the FULL-SCALE
  Wave 84 demographics/population generators (task #230 in the operator ledger)
  have completed S3 sync (task #232) but Glue catalog registration for the
  Wave 83/84/85 new tables (task #234) and Wave 84-specific tables (population
  pyramid, household composition, etc.) are still pending Athena smoke
  (task #235). Q29 + Q31 use the city/prefecture proxies already in Glue —
  the contract is column-prune-friendly so the queries can be re-pointed to
  the new tables without rewrites once Glue smoke completes.
- **JSIC axis bucket `UNK`**: most tables do not have `jsic_major` populated
  at the subject envelope; Q31 honestly buckets these as `UNK` rather than
  fabricating. This is consistent with wave82/q26.
- **Foundation anchor**: Q31 + Q32 both include `packet_houjin_360` so the
  baseline JSIC distribution / total houjin row count is observable in the
  same output — gives the consumer a denominator to read the Wave 8x signal
  density against.

## Back-ref to wave82 Q27 (grand aggregate evolution)

- wave82 Q27 covered Wave 53 → 82 (8 wave_family buckets + foundation).
- wave85 Q32 extends to Wave 53 → 85 (11 wave_family buckets + foundation):
  adds wave57_geographic / wave67_tech / wave83_climate / wave84_demographic /
  wave85_cybersec as new buckets.
- The 1.65 GiB scan on Q32 vs ~600 MiB on Q27 (historical) reflects the new
  Wave 83-85 + Wave 57/67 buckets — incremental scan = the new families.

## Result S3 locations

All five `<exec_id>.csv` files land under:

```
s3://jpcite-credit-993693061769-202605-derived/athena-results/
```

(per `scripts/aws_credit_ops/run_big_athena_query.sh:48` default
`OUTPUT_S3`). They are usable as immediate input for downstream MCP
composition (e.g. `composed_tools/` cohort visualizers).

## Cap + budget

- 50 GB PERF-14 BytesScannedCutoffPerQuery cap: ALL 5 ≪ cap.
- Athena rate: $5.00/TB scanned (US-East ≡ ap-northeast-1 standard tier).
- Total cost: **$0.0121** for the 5-query batch.
- Operator budget cap: $50 (default). Under budget by ~4000×.

## Next steps (out of scope here)

- Re-run Q29 / Q31 once Wave 84 FULL-SCALE Glue tables register (task #234 + #235)
  — they should hit result reuse and pay incremental scan only for the new
  population/demographic tables.
- Consider promoting Q32 to a daily cron once Wave 86-88 generators land so
  the "show me the footprint of everything" view stays current at $0.0080/day.
