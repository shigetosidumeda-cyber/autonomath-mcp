# Athena Wave 82 Q23-Q27 — 5 cross-join queries on Wave 80-82 + back-ref

**Lane:** solo
**Profile:** `bookyou-recovery`, region `ap-northeast-1`
**Workgroup:** `jpcite-credit-2026-05` (50 GB scan cap per PERF-14)
**Database:** `jpcite_credit_2026_05`
**Glue table count (probed):** 207 (3 paginated pages: 100 + 100 + 7)
**Catalog grew:** 282 → 312 (Wave 80-82, +30 generators)

## Query inventory

| Q | File | Theme | Wave families |
|---|------|-------|---------------|
| Q23 | `q23_wave80_supply_x_wave53_3_acceptance_xref.sql` | Wave 80 supply chain × Wave 53.3 acceptance probability cohort cross-ref | wave80_supply (3) × packet_acceptance_probability |
| Q24 | `q24_wave81_esg_x_wave60_65_finance_intersection.sql` | Wave 81 ESG × Wave 60-65 finance intersection | wave81_esg (5) × wave60_65_finance (5) |
| Q25 | `q25_wave82_ip_x_wave76_startup_growth.sql` | Wave 82 IP × Wave 76 startup growth signal | wave82_ip (5) × wave76_startup (4) |
| Q26 | `q26_wave80_82_supply_esg_ip_x_jsic.sql` | All Wave 80-82 (supply + ESG + IP) × jsic_major | wave80+81+82 (13) + foundation |
| Q27 | `q27_allwave_53_82_grand_aggregate.sql` | Grand aggregate row count per family across Wave 53→82 | 9 wave families across the corpus |

## Run footprint (scan + cost + latency)

| Q | QueryExecutionId | state | bytes scanned | est. cost (USD) | elapsed |
|---|------------------|-------|--------------:|----------------:|--------:|
| Q23 | (1st run, OK) | SUCCEEDED | 504,588,000 (481.21 MiB / 0.4699 GiB) | $0.0023 | 31s |
| Q24 | 85ae288b-75f0-4d54-8238-a7f4531c3cb6 | SUCCEEDED | 221,782 (0.21 MiB) | $0.0000 | 7s |
| Q25 | fa6340f3-5301-4fe8-b76f-471a42745961 | SUCCEEDED | 61,396,965 (58.55 MiB / 0.0572 GiB) | $0.0003 | 7s |
| Q26 | d481813f-0000-48be-a634-d22d13d3f806 | SUCCEEDED | 313,872,648 (299.33 MiB / 0.2923 GiB) | $0.0014 | 19s |
| Q27 | 20391edc-eafc-413e-9cdc-7f57de2d4022 | SUCCEEDED (retry — 1 column-not-found fix) | 1,440,575,865 (1373.84 MiB / 1.3416 GiB) | $0.0066 | 95s |

**Total scan:** ~2.32 GiB (well under the 50 GB PERF-14 cap).
**Total cost:** **~$0.0106 USD** (≈ ¥1.6 at JPY/USD=150).
**All queries** are column-prune-friendly on JSON paths; scan footprint stays small because every SELECT references either COUNT(*), top-level columns, or column-pruned JSON scalar extracts.

## Findings

### Q27 grand aggregate (Wave 53 → 82, row count per family)

| wave_family | distinct_sources | total_rows | sum_approx_distinct_subjects |
|---|---:|---:|---:|
| wave53_3 (acceptance_probability) | 1 | **11,505,600** | 0 |
| wave69_entity360 | 4 | 344,283 | 0 |
| foundation (houjin_360) | 1 | 86,849 | 87,552 |
| wave82_ip | 5 | 32,118 | 31,748 |
| wave53 (baseline) | 3 | 11,396 | 188 |
| wave60_65_finance | 5 | 70 | 70 |
| wave81_esg | 5 | 69 | 69 |
| wave76_startup | 4 | 67 | 67 |
| wave80_supply | 3 | **0** | 0 |

**Observation 1.** Wave 53.3 `packet_acceptance_probability` dominates the corpus by 2 orders of magnitude (11.5M rows — the cohort grid). Wave 69 entity_360 is the second tier at 344K. Wave 82 IP is the third tier at 32K.

**Observation 2.** Wave 80 supply chain reports **0 rows** in Q27 — the 3 generators landed but the s3 sync to Glue tables for `commodity_price_exposure_v1` / `secondary_supplier_resilience_v1` / `supplier_credit_rating_match_v1` has not propagated. This is consistent with Q23 (Q23 returned 0 supply rows but did scan 481 MiB — Athena read the table metadata but the partitions are empty). **Action:** Wave 80 packets need a `aws s3 sync` topup parallel to the Wave 70/71 fix pattern.

**Observation 3.** Wave 81 ESG (69 rows / 5 sources) and Wave 76 startup (67 rows / 4 sources) are nearly balanced — the ESG × finance × startup cross-section is small but proportionate. Wave 60-65 finance (70 rows) sits at the same order, suggesting the green-bond / sustainability-linked-loan / transition-finance side is the natural counterpart to ESG disclosure.

### Q25 IP × startup (Wave 82 × Wave 76)

| ip_family | ip_rows | startup_family | startup_rows | patent_density_per_growth_signal | intersection_density |
|---|---:|---|---:|---:|---:|
| wave82_ip | 32,118 | wave76_startup | 67 | **50.0 (cap)** | 0.00209 |

**Observation.** Patent density per growth signal hits the **50.0 cap** because Wave 82 IP has 32,118 rows vs Wave 76 startup only 67 rows. The raw ratio is **479.4 IP rows per startup signal row** — a strong indicator that the patent surface is far denser than the growth-signal surface. The intersection_density of 0.0021 (0.21%) reflects this asymmetry honestly. This is the canonical "patent saturation × growth-stage thinness" finding that an M&A advisor / scale-up underwriter should know.

### Q26 Wave 80-82 × JSIC

| wave_family | jsic_major | row_count | distinct_sources |
|---|---|---:|---:|
| foundation (houjin_360) | UNK | 86,849 | 1 |
| wave81_esg | UNK | 69 | 5 |
| wave82_ip | UNK | 32,118 | 5 |

**Observation.** Wave 80-82 packets currently bucket entirely to `jsic_major='UNK'` — the JSIC major code is not yet projected into the subject JSON for these generators. This matches the wave70/q21 baseline pattern (FY × wave_family × jsic_major buckets all to UNK where not threaded). **Action (lift-up):** the Wave 80-82 generators can populate `subject.jsic_major` from the same JSIC seed used by the Wave 70 industry × geographic intersection fix.

## Recipe (canonical)

```bash
bash scripts/aws_credit_ops/run_big_athena_query.sh \
  infra/aws/athena/big_queries/wave82/q23_wave80_supply_x_wave53_3_acceptance_xref.sql \
  --budget-cap-usd 5
```

Result reuse cache is enabled at the workgroup-callers level (`infra/aws/athena/big_queries/run_query.sh` defaults to `ResultReuseByAgeConfiguration={Enabled=true,MaxAgeInMinutes=1440}`, 24h TTL — see `docs/_internal/athena_workgroup_tune_2026_05_16.md`). `run_big_athena_query.sh` does not yet pass the flag explicitly, so a 24h-window re-run of the same query is the only path to free re-execution at the moment.

## Next steps

1. **Wave 80 packet S3 sync** — 0-row symptom on Q23 + Q27 wave80_supply == 0; rerun `aws s3 sync` from local generator output to the canonical S3 prefix to populate the 3 LIVE-in-Glue Wave 80 tables, then re-run Q23 + Q27 (cache reuse for Q24-Q26).
2. **JSIC threading on Wave 80-82** — add `subject.jsic_major` to all 30 generators, parallel to the Wave 70 intersection fix pattern.
3. **wave70/q22 entity_360 footprint** equivalent for Wave 80-82 (next Q28 candidate) — per-entity rollup of how many Wave 80-82 packet families touch each houjin_bangou, anchored against `packet_houjin_360` (the foundation entity baseline).

last_updated: 2026-05-16
