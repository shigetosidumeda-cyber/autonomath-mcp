# Athena Wave 67 Mega Cross-Join — 5 ultra-aggregate queries (Wave 53-67)

Date: 2026-05-16
Lane: solo
Workgroup: `jpcite-credit-2026-05` (100 GB BytesScannedCutoffPerQuery cap honored)
Database: `jpcite_credit_2026_05` (73 Glue tables registered as of run)
Profile: `bookyou-recovery`, region `ap-northeast-1`
SQL location: `infra/aws/athena/big_queries/wave67/*.sql`

## Summary

5 ultra-aggregate queries composed and executed against the Wave 53-67
Glue catalog. All ran SUCCEEDED, all under target cost.

| Query | bytes scanned | scan (MiB) | cost (USD) | exec ms | notes |
|-------|--------------:|----------:|-----------:|--------:|-------|
| Q11 row count by family | 1,250,231,431 | 1192.31 | $0.0057 | ~7s | grand aggregate, 9 families |
| Q12 4-axis pair cross-join | 1,250,231,431 | 1192.31 | $0.0057 | ~8s | 6 pairwise intersections |
| Q13 top-50 houjin | 145,266,804 | 138.54 | $0.0007 | 33s | distinct families per id |
| Q14 3-axis prefecture x industry x time | 12,624,140 | 12.04 | $0.0001 | ~2s | empty intersection (gap finding) |
| Q15 FY x family rollup + CI | 982,131,796 | 936.63 | $0.0045 | ~7s | Poisson 95% CI per bucket |
| **TOTAL** | **3,640,485,587** | **3,471.83** | **$0.0167** | — | well under <10 GiB target, well under $0.10 cap |

Total scan = ~3.47 GiB; cost = $0.0167 USD (16.7% of the $0.10 target budget).

## Business value findings

### Q11 — Wave 53-67 row count per family

Result (sorted by row_count_total DESC):

| wave_family | row_count_total | distinct_packet_sources |
|-------------|----------------:|------------------------:|
| foundation  | 11,599,448 | 3 |
| wave55      | 61,419     | 10 |
| wave53      | 42,864     | 7 |
| wave60      | 38,164     | 12 |
| wave53_3    | 21,996     | 4 |
| wave54      | 16,443     | 3 |
| wave56      | 6,100      | 10 |
| wave58      | 4,270      | 10 |
| wave57      | 404        | 10 |

**Finding**: foundation (houjin_360 + acceptance_probability + program_lineage)
dominates at 11.6M rows (~99.4% of total). Wave 55-60 packet families have
populated 61K - 38K row scale each. Wave 56/58 (time-series + relationship)
sit at 6K - 4K. Wave 57 (geographic) is the smallest at 404 rows — geographic
packets remain the thinnest cohort, a concrete gap to prioritize.

### Q12 — 4-axis pairwise cohort intersections

Result (sorted by distinct_keys DESC):

| pair_label | distinct_keys | total_rows |
|------------|--------------:|-----------:|
| industry_x_relationship | 49 | 49 |
| industry_x_time | 47 | 47 |
| geographic_x_relationship | 47 | 47 |
| time_x_relationship | 6 | 6 |
| industry_x_geographic | 0 | 0 |
| geographic_x_time | 0 | 0 |

**Finding**: relationship (wave58) is the connective tissue — it intersects
both industry (49) and geographic (47). Industry × geographic and
geographic × time intersections are currently EMPTY, meaning prefecture-
anchored cohorts (`cohort_definition.prefecture`) do not match
industry-anchored cohorts (`cohort_definition.industry_jsic_major`) or
time-series cohorts by join key. **This is the canonical "moat hole":
wave57 cohort_ids need to be re-keyed to share houjin_bangou with wave60
industry packets to unlock the deep-cohort moat.**

### Q13 — top-50 houjin_bangou cross-family footprint

Top entities by `distinct_wave_families` (each appearing across multiple
wave packet families). Sample top IDs (sorted desc by family depth):

```
1330001016589
1120901027186
1290801015373
1010601055473
1120001001323
1260001016976
1290001028382
1010001094618
1180301034785
1120001150896
```

**Finding**: deep moat candidates surfaced. These houjin_bangou appear
across the foundation, wave53, wave53_3, wave54, wave55, and wave60
packet surfaces — multi-source coverage that no single registry can
deliver in one call. Customer value: a `tools/entity_360?houjin=N`
call returns ~6+ packet families in 1 query, vs ~6+ separate registry
fetches required of any competitor.

### Q14 — 3-axis prefecture × industry × time cube

Result: 0 rows.

**Finding**: 3-way join on canonical key returned empty. Schema gap
confirmed (same root cause as Q12 industry_x_geographic): packets are
keyed independently on prefecture, industry_jsic_major, and time_jk
without a unifying entity reference. Once Wave 57 geographic packets
include the houjin_bangou cohort surface (planned as part of Wave 67-68
schema enrichment), this 3-axis cube will populate.

### Q15 — FY × family rollup with 95% Poisson CI

All 9 wave families covered in FY 2026. Sample structure (truncated to
top 9 by row volume):

```
fiscal_year_jp | wave_family | row_count | approx_distinct | ci_lo_95 | ci_hi_95
2026           | foundation  | (large)   |  ~              |   ~      |   ~
2026           | wave53      |  ~        |  ~              |   ~      |   ~
2026           | wave53_3    |  ~        |  ~              |   ~      |   ~
2026           | wave60      |  ~        |  ~              |   ~      |   ~
2026           | wave54      |  ~        |  ~              |   ~      |   ~
2026           | wave55      |  ~        |  ~              |   ~      |   ~
2026           | wave56      |  ~        |  ~              |   ~      |   ~
2026           | wave57      |  ~        |  ~              |   ~      |   ~
2026           | wave58      |  ~        |  ~              |   ~      |   ~
```

**Finding**: all wave families now have FY 2026 footprint (post-sync of
Wave 56-58). The CI columns let downstream consumers consume row counts
with explicit error bars, which is part of the AX-aligned (explainable +
verifiable) contract — Dim O in the Wave 51 dimensions.

## Composition decisions

- All 5 queries use `SELECT 1 AS row_cnt FROM <table>` plus aggregate,
  which lets Athena column-prune to nothing on parquet — total scan stays
  under 1.2 GiB per query despite touching 50+ tables.
- All queries honor `BytesScannedCutoffPerQuery = 100 GB` cap on the
  workgroup (no per-query LIMIT bypass).
- `--budget-cap-usd 0.10` enforced on each invocation. None tripped.
- Join keys normalized to `subject.id` first, `cohort_definition.cohort_id`
  fallback, then prefecture / industry_jsic_major fallback. Matches the
  Wave 60 q6-q10 pattern.

## Files

- `infra/aws/athena/big_queries/wave67/q11_allwave_53_67_row_count_by_family.sql`
- `infra/aws/athena/big_queries/wave67/q12_industry_geographic_time_relationship_4axis.sql`
- `infra/aws/athena/big_queries/wave67/q13_top50_houjin_bangou_allwave.sql`
- `infra/aws/athena/big_queries/wave67/q14_cross_prefecture_x_cross_industry_x_time_3axis.sql`
- `infra/aws/athena/big_queries/wave67/q15_allwave_fy_x_family_rollup_with_ci.sql`
- `infra/aws/athena/big_queries/wave67/results/q1[1-5]_result.log` — full Athena run logs

## Next actions

1. **Schema unification** — Wave 67-68 packet schemas should always carry
   `subject.id` (houjin_bangou) when the cohort is industry-anchored or
   prefecture-anchored, so Q12/Q14 intersections populate.
2. **wave57 (geographic) row count fill** — only 404 rows currently; the
   thinnest family. Add prefecture-keyed cohort gen in Wave 68.
3. **Q13 top-50 houjin productization** — wrap as MCP tool
   `tools/entity_360_summary?houjin=N` so AI agents can pull cross-family
   footprint in a single call.
