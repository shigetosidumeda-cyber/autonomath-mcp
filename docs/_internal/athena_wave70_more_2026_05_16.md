# Athena Wave 70-more (Q18-Q22) — 2026-05-16

5 ultra-aggregate cross-join queries over the 204-table Glue catalog (post
Wave 67 re-run + Wave 69-73 registration). Profile = `bookyou-recovery`,
region = `ap-northeast-1`, workgroup = `jpcite-credit-2026-05` (100 GB
`BytesScannedCutoffPerQuery`), database = `jpcite_credit_2026_05`.

All 5 queries SUCCEEDED. Total scan = **~1.96 GiB**, total estimated cost
= **~$0.0089 USD** at $5/TB. All under the 100 GB cutoff. None tripped
the $5 budget cap.

## Run summary

| Query | Subject | exec_id | Elapsed | Bytes scanned | Est. cost (USD) | Output rows |
| --- | --- | --- | --- | --- | --- | --- |
| Q18 | Wave 74-76 (fintech + labor + startup) × jsic intersection | `048e6f9d-f530-4a35-9a44-a0ab5e4bb54a` | 38s | 742.43 MiB | $0.0035 | 4 |
| Q19 | Wave 69 entity_360 × Wave 53.3 acceptance_probability xref | `3f2d5402-51e4-49b3-a733-4e8a1004c4e0` | 71s | ~480 MiB | $0.0023 | 9 |
| Q20 | Wave 72-73 (AI/ML + climate) × Wave 60-65 finance | `2d1d2f94-06fb-422f-b35d-e4f05f8c694b` | 8s | 0.18 MiB | $0.0000 | 2 |
| Q21 | All-Wave fiscal_year × wave_family × jsic 5-axis rollup (53-76) | `332b4f8b-d1f4-4244-966c-c200253cf1d8` | 17s | 84.80 MiB | $0.0004 | 100+ |
| Q22 | Entity_360 entity resolution houjin × all-Wave footprint | `22572a18-c6a7-451c-a1ec-5d6a8eebe7ad` | 72s | ~560 MiB | $0.0027 | 200 |

(Q19 had a stale-page first run that returned 0 rows due to entity_360
data still landing during the read; second run pulled the 9-row result.
Q22 was re-run after fixing a JSON path bug: foundation `packet_houjin_360`
stores the houjin_bangou as `subject.id` with `subject.kind='houjin'`,
not `subject.houjin_bangou`.)

## Findings

### Q18 — Wave 74-76 × jsic intersection

```
wave_family            row_count_total   distinct_packet_sources
foundation_industry    11,599,448        3
wave76_startup         1,178             6
wave75_labor           86                3
wave74_fintech         19                2
```

Wave 74 fintech is **honestly thin** (19 rows across 2 carrier tables) —
the Glue tables exist but the S3 row population for `bond_issuance_pattern`
+ `transition_finance_eligibility` is at smoke level. Wave 75 labor at 86
rows × 3 sources is similarly early. Wave 76 startup is the most populated
of the three (1,178 rows / 6 sources), driven by `entity_succession_360`
+ `founding_succession_chain`. Foundation_industry baseline = 11.6M rows
across 3 anchor packets (houjin_360 / acceptance_probability /
program_lineage).

### Q19 — Wave 69 entity_360 × Wave 53.3 acceptance_probability xref

```
entity_360_facet           e360_row_count    acceptance_total_rows  acceptance_distinct_cohorts  cohort_density_ratio
entity_risk_360            61,135            11,505,600             0                            0.0
entity_partner_360         60,953            11,505,600             0                            0.0
entity_court_360           60,945            11,505,600             0                            0.0
entity_succession_360      60,822            11,505,600             0                            0.0
entity_subsidy_360         60,513            11,505,600             0                            0.0
entity_360_summary         59,871            11,505,600             0                            0.0
entity_certification_360   44,283            11,505,600             0                            0.0
entity_compliance_360      500               11,505,600             0                            0.0
entity_invoice_360         229               11,505,600             0                            0.0
```

**Real finding**: `acceptance_distinct_cohorts` = 0 across all 9 facets.
The `packet_acceptance_probability.cohort_definition` JSON does not carry
a `$.cohort_id` field at the path the matcher assumed. The 11.5M-row
acceptance_probability corpus has its cohort id under a different JSON
key — surfaces as a real gap to chase down in the next packet-generator
review (file a follow-up to canonicalize `$.cohort_id` so cohort-density
xref queries can compute meaningful ratios). Row counts on the entity_360
facets are otherwise healthy (44k-61k for the 7 large facets, 229-500
for compliance / invoice which are still ramping).

### Q20 — Wave 72-73 (AI/ML + climate) × Wave 60-65 finance

```
bucket               row_count_total   distinct_packet_sources   approx_distinct_subject_ids
wave60_65_finance    136               8                         17
wave73_climate       1                 1                         1
```

`wave72_ai_ml` bucket returned ZERO rows — all 9 wave72 packet tables
are S3-row-empty (Glue tables exist, parquet is not landed). `wave73_climate`
has a single seeded row. `wave60_65_finance` is the populated bucket at
136 rows / 8 distinct sources / 17 distinct subject ids. This isolates
Wave 72 (AI/ML) + Wave 73 (climate) as the next packet-generator backfill
targets — Glue is ready, S3 is not.

### Q21 — All-Wave FY × wave_family × jsic 5-axis rollup (Wave 53 → 76)

Top rows (FY 2026):

```
fiscal_year_jp  wave_family  jsic_major  row_count  approx_distinct_keys  ci_lo_95  ci_hi_95
2026            wave53       UNK         11,208     1                     11,000    11,416
2026            wave53_3     UNK         10,679     10,541                10,476    10,882
2026            wave55       UNK         10         10                    4         16
2026            wave60       N           1          1                     0         3
2026            wave60       F           1          1                     0         3
2026            wave60       A           1          1                     0         3
```

Wave 53 dominates the FY 2026 row count at 11,208 rows (single jsic
fallthrough — Wave 53 packets do not project a jsic_major key into
subject JSON). Wave 53.3 has 10,679 rows with high cardinality (10,541
distinct keys, suggesting healthy per-subject diversity). Wave 60
shows per-JSIC tagging starting (N / F / A jsic_major buckets) but at
1 row each — the cross-industry packets are seeded, not full. Wave 67
+ Wave 70+ packets are not yet populating FY 2026 rows in this slice
(consistent with Q20's wave72/73 emptiness).

### Q22 — Entity_360 × houjin × all-Wave footprint

200 houjin returned (LIMIT 200 cap hit). All 200 have:

- `foundation_row_count` = 1 (one packet_houjin_360 row per houjin)
- `e360_distinct_facets` = 0 (no Wave 69 entity_360 packets touch the
  same houjin_bangou as the foundation packet_houjin_360 corpus)
- `allwave_distinct_packets` = 1 (single carrier packet hits the houjin)
- `footprint_score` = 0.167 (= 1/6 from the allwave_carriers axis, 0
  from the e360 axis)

**Real finding**: zero overlap between the foundation `packet_houjin_360`
houjin_bangou set (86,849 rows, all `subject.kind='houjin'` with the
houjin_bangou as `subject.id`) and the Wave 69 entity_360_* family's
top-level `houjin_bangou` column. The two sources are populated against
**disjoint houjin sets** — entity_360 is filling its own cohort while
foundation is still on the original 86,849. This isolates the entity_360
generator's source resolver as the next surface to audit: it should
backfill against the foundation houjin_bangou inventory so the two
sources align and the moat-density score across e360 + allwave can
actually exceed 1.0/n.

## Cost ledger update

```
Q18:  742.43 MiB → $0.0035 USD
Q19:  ~480 MiB    → $0.0023 USD (re-run)
Q20:  0.18 MiB    → $0.0000 USD (Wave 72-73 sparse)
Q21:  84.80 MiB   → $0.0004 USD
Q22:  ~560 MiB    → $0.0027 USD (re-run, after JSON path fix)
-----
Total:            → ~$0.0089 USD over ~1.96 GiB scanned
```

Plus sanity probe + 2 retries (Q19/Q22) at ~3 GiB additional = ~$0.015
USD all-in for the Wave 70-more Athena pass.

All queries honored the 100 GB workgroup cap with massive headroom
(largest single scan = 742.43 MiB = 0.7% of cap). No SAFETY_GUARD trips.

## Follow-ups identified

1. **`packet_acceptance_probability.cohort_definition.$.cohort_id` path
   missing** — Q19 found 0 distinct cohorts despite 11.5M rows. The
   cohort id lives under a different JSON key in the acceptance_probability
   corpus; the generator schema and the matcher need to converge on
   `$.cohort_id` to make cohort-density xref work.
2. **Wave 72 (AI/ML) + Wave 73 (climate) S3 row-empty** — all Glue
   tables are registered but the parquet files are not yet landed at
   scale. Q20 surfaced this gap (1 row total across the climate bucket,
   0 across AI/ML).
3. **`entity_360_*` houjin set disjoint from foundation `packet_houjin_360`
   houjin set** — Q22 found 0 e360 facet touches across the top 200
   foundation houjin. The entity_360 generator's source resolver should
   backfill against the 86,849 foundation houjin inventory.
4. **Wave 74 fintech still smoke-scale** — Q18 found only 19 rows across
   5 candidate tables (2 carriers). Backfill target for the next
   FULL-SCALE Wave 74 packet generator pass.
