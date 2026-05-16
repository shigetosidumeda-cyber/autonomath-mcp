# Wave 71 — wave57 geographic fill attempt (2026-05-16)

Honest outcome of re-running the 10 wave57 geographic packet generators at
"full-scale" (no `--limit`). Athena `wave57` family row count is **unchanged
at 404**; the structural row ceiling is one packet per cohort_id, not one
per (cohort × program). True scaling to 5K+ rows is a **generator redesign**
task (cardinality lift), not a re-run task. This document records the gap
and the next concrete step.

## Setup

- Repo: `/Users/shigetoumeda/jpcite`
- Output prefix (local stage): `out/wave71_geo/`
- S3 buckets:
  - Stage path: `s3://jpcite-credit-993693061769-202605-derived/wave71_geo/`
  - Canonical Athena-bound paths (Glue table `Location`):
    `s3://jpcite-credit-993693061769-202605-derived/<kind>_v1/`
- Profile: `bookyou-recovery`, region: `ap-northeast-1`
- Database: `jpcite_credit_2026_05` (Glue + Athena)
- Wave 67 reference: `infra/aws/athena/big_queries/wave67/q11_allwave_53_67_row_count_by_family.sql`

## Per-generator packet counts (honest)

| # | Generator (PACKAGE_KIND)                | Packets seen | Packets written |
|---|------------------------------------------|--------------|-----------------|
| 1 | prefecture_program_heatmap_v1           | 48           | 48              |
| 2 | municipality_subsidy_inventory_v1       | 47           | 47              |
| 3 | region_industry_match_v1                | 50           | 50              |
| 4 | cross_prefecture_arbitrage_v1           | 17           | 17              |
| 5 | city_size_subsidy_propensity_v1         | 51           | 51              |
| 6 | regional_enforcement_density_v1         | 47           | 47              |
| 7 | prefecture_court_decision_focus_v1      | 5            | 5               |
| 8 | city_jct_density_v1                     | 47           | 47              |
| 9 | rural_subsidy_coverage_v1               | 9            | 9               |
| 10| prefecture_environmental_compliance_v1  | 45           | 45              |
|   | **TOTAL**                                | **366**      | **366**         |

These 366 packets were produced this session and overwrite (same packet_id =
same S3 key) packets from the prior wave57 run. S3 object inventory in the
canonical Athena-bound paths sums to **404** because three generators carry
older objects beyond the current cohort enumeration (notably
`rural_subsidy_coverage_v1` = 47 objects on S3 vs 9 packets re-emitted).

## Athena re-verify (Q11)

Re-ran `q11_allwave_53_67_row_count_by_family.sql`:

```
wave_family       row_count_total  distinct_packet_sources
foundation        11,599,448       3
wave55                 61,419     10
wave53                 42,864      7
wave60                 38,164     12
wave53_3               21,996      4
wave54                 16,443      3
wave56                  6,100     10
wave58                  4,270     10
wave57                    404     10   <-- UNCHANGED
```

`wave57` row_count_total = **404** (target was 5,000+). Re-run did **not**
move the number.

## Root cause (honest)

Each of the 10 generators iterates over a **single cohort axis** and emits
**one envelope per cohort_id**:

- `prefecture_program_heatmap_v1` — one packet per prefecture (47 + 不明 =
  48). Inside the envelope, the per-prefecture program distribution is a
  rolled-up histogram (`tier_distribution` / `authority_distribution`) — it
  is **not** materialized as a row per (prefecture, program).
- `municipality_subsidy_inventory_v1` — one packet per municipality
  available in `jpi_programs` (47 emitted, mostly prefecture-level
  fallbacks; the 782 unique municipalities envisioned in the task brief
  would require a different driver query that walks
  `jpi_programs.target_municipality` rather than `prefecture`).
- `region_industry_match_v1` — 50 packets (cohort = region × industry pair,
  thinned by what is actually present in source tables).
- ... etc.

The Athena Q11 query measures **one row per packet** (`SELECT 1 FROM <table>`
UNION ALL ... GROUP BY wave_family). With 1 packet per cohort_id, the
ceiling is the number of distinct cohort_ids — and that ceiling is
~50/generator, totalling 404 across the 10 wave57 tables.

To grow the row count to 5K+, the generators must emit **finer-grained
packets** — for example one packet per (prefecture, program) tuple
(47 × ~150 programs ≈ 7K) or per (prefecture, JSIC major) etc. That is a
**code change** (`scripts/aws_credit_ops/generate_*_packets.py:_aggregate`
yield-shape), not a re-run flag.

## What this re-run did achieve

- Refreshed packet `generated_at` / metric snapshots on all 366 current
  cohorts (envelope content is now timestamped 2026-05-16T19:xx UTC).
- Confirmed no schema validation regressions — `validate_jpcir_header`
  returned OK for every emitted envelope (0 schema_violation, 0
  empty-skip).
- Confirmed S3 sync path works with `bookyou-recovery` profile against
  `s3://jpcite-credit-993693061769-202605-derived/<kind>_v1/`.
- Run manifests landed at `out/wave71_geo/<kind>/run_manifest.json` for
  each generator (audit trail).

## Operational gotchas observed

1. **Modules require `.venv/bin/python -m scripts.aws_credit_ops.<mod>`**
   invocation. System `/usr/bin/python3` is 3.9 on this Mac and the
   `_packet_base.py` import of `datetime.UTC` requires ≥3.11. Direct
   `python3 path/to/file.py` also fails with
   `ModuleNotFoundError: No module named 'scripts'`.
2. **Athena table `Location` is per-table at `s3://...-derived/<kind>_v1/`**,
   not under `wave71_geo/`. Glue catalogue paths are pinned by the table
   `StorageDescriptor.Location`. Syncing to a side prefix is invisible to
   Athena.

## Next step (out of scope for this task)

- Wave 70 / Wave 72-style cardinality lift: redesign the 10 generators to
  yield one packet per (prefecture, program) or per (municipality, program)
  — see also the canonical "moat hole" note in
  `docs/_internal/athena_wave67_mega_2026_05_16.md` § "wave57 cohort_ids
  need to be re-keyed to share houjin_bangou with wave60 industry packets".
- After redesign, re-run with `--limit` for smoke, then full-scale + S3
  sync to canonical `<kind>_v1/` paths, then re-run Q11.

`[lane:solo]`
