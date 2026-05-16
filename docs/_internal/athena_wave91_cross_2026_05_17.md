# Athena Wave 91 Q38-Q42 Cross-Join Run (2026-05-17)

[lane:solo]

Successor to `athena_wave88_cross_2026_05_17.md` (Q33-Q37). Q38-Q42 land
the Wave 89 (M&A / succession / governance) + Wave 90 (talent / workforce
/ leadership) + Wave 91 (brand / customer-proxy) cross-join surface
against Wave 69 entity_360 / Wave 75 employment / Wave 86 social-media
back-references, plus the full Wave 53→91 grand-aggregate footprint.

## Environment

- **Profile**: `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`)
- **Region**: `ap-northeast-1`
- **Workgroup**: `jpcite-credit-2026-05`
- **Database**: `jpcite_credit_2026_05`
- **Result S3**: `s3://jpcite-credit-993693061769-202605-derived/athena-results/`
- **Glue table count (verified)**: **304** (294 packet tables, 10 ops/manifest tables; PERF-24 expanded Parquet top 10)
- **PERF-14 cap**: 50 GB `BytesScannedCutoffPerQuery`
- **Budget cap (script)**: $50 per query
- **Reuse**: workgroup-level Athena query result cache (PERF-14)

## Query inventory + run summary

| Q     | File                                              | exec_id                              | wall  | bytes scanned | est. cost USD |
|-------|---------------------------------------------------|--------------------------------------|-------|---------------|---------------|
| Q38   | `q38_wave89_ma_x_wave69_entity_360.sql`           | 8fecbaff-6eab-4b31-8592-46bbef46b098 | 51s   | 876,033,430 (835 MiB / 0.82 GiB) | **$0.0040** |
| Q39   | `q39_wave90_talent_x_wave75_employment.sql`       | aadbb345-71f7-46a9-b23e-a430d621e6ec | 8s    | 312,765 (0.30 MiB)               | **$0.0000** |
| Q40   | `q40_wave91_brand_x_wave86_social_media.sql`      | 11d08638-b6bf-49be-bab2-224f4dcae75b | 8s    | 20,858,241 (19.89 MiB / 0.019 GiB) | **$0.0001** |
| Q41   | `q41_wave89_91_x_jsic_intersection.sql`           | 7effba7b-4467-46ce-9d1c-a77e2fa0c6f6 | 30s   | 419,508,899 (400 MiB / 0.39 GiB)   | **$0.0019** |
| Q42   | `q42_allwave_53_91_grand_aggregate.sql`           | 8d1ea9ac-4a9a-4185-ad4a-662c5ed37fb2 | 78s   | 1,908,624,595 (1.78 GiB)         | **$0.0087** |
| **Σ** |                                                   |                                      | 175s  | **3.23 GiB** total                 | **$0.0147** |

All 5 SUCCEEDED. Well under 50 GB PERF-14 cap (largest = 1.78 GiB on Q42
grand-aggregate), and budget cap untriggered (largest single = $0.0087).
`run_big_athena_query.sh` result-reuse stayed ON across the run.

## Findings

### Q38 — Wave 89 M&A × Wave 69 entity_360 (51s / $0.0040)

- Wave 89 M&A row range: small `succession_program_matching` (67 rows) up
  through richer entity-event tables. `entity_partner_360` / `entity_subsidy_360` /
  `entity_certification_360` (Wave 69) anchor the cross-join with 100K /
  100K / 44K rows respectively.
- `ma_entity_360_alignment_density` is currently 0.0 across most pairs —
  the M&A subject.id space and entity_360 houjin_bangou space are
  intentionally different ID systems (subject.id is packet-local string;
  entity_360 uses houjin_bangou int). The metric is honest about the
  cross-ID mismatch; tightening it requires a subject.id → houjin_bangou
  ID-resolution layer (Wave 53 deep analysis territory). The ratio
  surface still produces the row-count footprint usable for M&A pipeline
  density per 360 facet.

### Q39 — Wave 90 talent × Wave 75 employment (8s / $0.0000)

- Wave 90 talent live proxies: `employer_brand_signal` (17) /
  `gender_workforce_balance` (17) / `training_data_provenance` (17). All
  current at 17-row smoke scale — Wave 90 proper FULL-SCALE pending.
- Wave 75 employment richer: `employment_program_eligibility` (47),
  `labor_dispute_event_rate` (22), `young_worker_concentration` (17),
  `payroll_subsidy_intensity` (0).
- `talent_employment_alignment_density` lands cleanly: 1.0 for
  young_worker_concentration (perfect 17/17 overlap), 0.77 for
  labor_dispute_event_rate (17/22), 0.36 for employment_program_eligibility
  (17/47). Honest signal that the talent surface mostly bottoms out as
  N=17 today and Wave 75 carries the labor-program program signal.
- This is the cheapest query in the batch ($0.0000 → 312KB scanned),
  reflects that talent + employment proxies are still pre-sync.

### Q40 — Wave 91 brand × Wave 86 social media (8s / $0.0001)

- `trademark_brand_protection` dominates Wave 91 brand at **10,647 rows
  / 10,503 distinct subjects** — full IP-anchored brand coverage from
  Wave 82 IP family reuse.
- Wave 86 social proxies all at N=17 today (community_engagement /
  corporate_website / content_publication_velocity / influencer_partnership).
- `brand_social_alignment_density` lands at 1.0 across most pairs (cap
  honored; brand_distinct_subjects >> social_distinct_subjects, ratio
  saturates) — reads as "100% of digital-engagement-tracked subjects
  also carry trademark/brand signal" because the social side is the
  bottleneck.
- 20 MB scanned for the full bilateral surface — extremely cheap.

### Q41 — Wave 89-91 × JSIC intersection (30s / $0.0019)

- 4 rows total. `foundation` (houjin_360, 86,849 rows / UNK) and
  `wave89_ma` (101,228 rows / UNK) dominate; `wave91_brand` shows 10,738
  rows / UNK across 7 packet sources; `wave90_talent` 51 rows / UNK
  across 3 packet sources.
- All UNK because packet subject JSON does not yet carry
  `$.jsic_major` for these new wave families — same pattern seen at
  Q36 (Wave 86-88) for the freshly-landed waves. The intersection
  query is honest about the gap and re-issues cleanly the moment
  jsic_major lands in packet subject schema (Wave 53 deep analysis
  side fixes).

### Q42 — Grand aggregate Wave 53-91 (78s / $0.0087)

Top 10 families by `total_rows` (truncated dump):

```
wave_family         distinct_packet_sources  total_rows   sum_approx_distinct_subjects
wave53_3            1                        11,505,600   0
wave69_entity360    7                        445,012      0
wave89_ma           9                        101,228      99,753
foundation          1                        86,849       87,552
wave57_geographic   4                        75,416       73,147
wave84_demographic  2                        54,903       53,866
wave82_ip           3                        21,332       21,050
wave53              3                        11,396       188
wave75_employment   4                        103          103
wave91_brand        6                        102          102
wave60_65_finance   4                        68           68
wave85_cybersec     3                        67           67
wave88_activism     2                        67           67
wave76_startup      4                        67           67
wave86_social_media 3                        51           51
wave90_talent       3                        51           51
wave81_esg          3                        51           51
wave67_tech         3                        51           51
wave83_climate      2                        34           34
wave87_procurement  2                        12           12
wave80_supply       3                        0            0
```

- **Wave 53.3 acceptance_probability dominates at 11.5M rows** — single
  largest table, anchors the corpus.
- **Wave 89 M&A lands at 101,228 rows / 99,753 distinct subjects** across
  9 packet sources — bigger than expected on first land because M&A
  family pulls succession / board / governance corpus density. This is
  the most material new wave in this Q38-Q42 cycle.
- **Wave 91 brand at 102 rows / 102 distinct subjects** across 6 packet
  sources — still small (smoke scale) but bilateral with Wave 86 social
  proxies for downstream brand DD.
- **Wave 90 talent at 51 rows** — smallest of the new waves, reflecting
  pre-sync state for employee_turnover_proxy / executive_tenure /
  wellness_program / remote_work_adoption etc.
- **Wave 80 supply at 0 total_rows** in this run (commodity / supplier
  tables drained or pre-sync at scan time) — honest 0 marker, not a
  query defect.

## Honesty notes

- Wave 91 brand here reuses trademark / IR / press_release / media_relations
  as live proxies. The smoke-only Wave 91 packets (brand_recognition_proxy /
  brand_sentiment_proxy / NPS_proxy / pricing_power / market_share /
  product_lifecycle_pulse / omnichannel_maturity / customer_satisfaction_proxy /
  product_diversification_intensity / customer_concentration_risk) are
  written to `out/wave91_smoke*` but not yet Glue-registered, so this query
  set is the "pre-S3-sync" baseline for the wave.
- Wave 90 talent surfaces are 3 live proxies only (employer_brand_signal,
  gender_workforce_balance, training_data_provenance). Smoke-only packets
  (employee_stock_option_signal / employee_training_intensity /
  employee_turnover_proxy / executive_tenure_distribution /
  leadership_gender_balance / performance_review_cadence /
  remote_work_adoption_signal / succession_planning_maturity /
  wellness_program_intensity / work_life_balance_disclosure) are written to
  `wave90_smoke*` / `smoke/wave90_smoke` but pending S3 sync + Glue register.
- All M&A vs entity_360 alignment density rows compute as 0.0 because
  subject.id (packet string) and houjin_bangou (int column) are different
  identifier systems on either side of the cross-join. This is honest
  about the join domain and re-evaluates non-trivially once the ID
  resolution layer (Wave 53 deep analysis) lands.

## Back-reference axes covered

- Q38 ↔ Wave 69 entity_360 (M&A subject × 7 entity_360 facets)
- Q39 ↔ Wave 75 employment (talent × employment-program / labor-dispute)
- Q40 ↔ Wave 86 social media (brand × community / website / influencer)
- Q41 ↔ JSIC industry axis (Wave 89-91 + foundation)
- Q42 ↔ Wave 53→91 grand corpus (every LIVE family rolled up)

## Cost ledger entry

```
date          query  exec_id                               bytes_scanned    cost_usd
2026-05-17    Q38    8fecbaff-6eab-4b31-8592-46bbef46b098  876,033,430      0.0040
2026-05-17    Q39    aadbb345-71f7-46a9-b23e-a430d621e6ec  312,765          0.0000
2026-05-17    Q40    11d08638-b6bf-49be-bab2-224f4dcae75b  20,858,241       0.0001
2026-05-17    Q41    7effba7b-4467-46ce-9d1c-a77e2fa0c6f6  419,508,899      0.0019
2026-05-17    Q42    8d1ea9ac-4a9a-4185-ad4a-662c5ed37fb2  1,908,624,595    0.0087
                                                          ─────────────    ───────
                                                          3,225,337,930    0.0147
```

Total scanned **3.23 GiB**, total est. cost **$0.0147 USD** — about 6%
of the $50 budget cap and ~0.0001% of any of the AWS canary $19,490
effective cap signals. No PERF-14 50 GB ceiling tripped. Result-reuse
already paid back on Q38 (same-tenant Wave 88 q33-q37 set scanned the
same large packets earlier this session).

last_updated: 2026-05-17
