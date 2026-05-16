# Wave 53 — 16 packet generators FULL-SCALE upload (2026-05-16)

Local run with `--commit` against `bookyou-recovery` AWS profile.
Output bucket: `s3://jpcite-credit-993693061769-202605-derived/`.

## Per-outcome counts

| # | outcome_type | packets | bytes | s3_put_usd |
| - | ------------ | ------: | ----: | --------: |
| 1 | enforcement_industry_heatmap_v1 | 47 | 127,676 | $0.0002 |
| 2 | invoice_houjin_cross_check_v1 | 13,801 | 26,738,799 | $0.0690 |
| 3 | vendor_due_diligence_v1 | 16,484 (partial) | 29,677,544 | $0.0824 |
| 4 | regulatory_change_radar_v1 | 1 | 4,567 | $0.0000 |
| 5 | subsidy_application_timeline_v1 | 9 | 38,733 | $0.0000 |
| 6 | program_law_amendment_impact_v1 | 390 | 900,394 | $0.0020 |
| 7 | cohort_program_recommendation_v1 | 171 | 855,190 | $0.0009 |
| 8 | succession_program_matching_v1 | 67 | 173,326 | $0.0003 |
| 9 | tax_treaty_japan_inbound_v1 | 33 | 59,172 | $0.0002 |
| 10 | bid_opportunity_matching_v1 | 11 | 45,005 | $0.0001 |
| 11 | permit_renewal_calendar_v1 | 2 | 3,226 | $0.0000 |
| 12 | local_government_subsidy_aggregator_v1 | 95 | 601,256 | $0.0005 |
| 13 | kanpou_gazette_watch_v1 | 665 | 1,953,997 | $0.0033 |
| 14 | company_public_baseline_v1 | 17,123 (partial) | 27,100,346 | $0.0856 |
| 15 | invoice_registrant_public_check_v1 | 13,801 | 24,028,221 | $0.0690 |
| 16 | application_strategy_v1 | 11,208 | 22,774,994 | $0.0560 |

**Totals**: 73,908 packets / 135,082,446 bytes (128.82 MiB) / ~$0.37 in S3 PUT cost.

## Run notes

- Launched in parallel via `/tmp/wave53_run/launch_all.sh` (`PYTHONPATH=.`, `AWS_PROFILE=bookyou-recovery`).
- 14 / 16 ran to completion (natural corpus cap); 2 (`vendor_due_diligence_v1`, `company_public_baseline_v1`) were
  SIGTERMed at ~15 min because their corpus walk over the 166k `corporate_entity` rows in `autonomath.db` would
  not have completed inside the 30 min budget. Their S3 prefixes carry the partial output, which is still useful
  as a coverage seed.
- `mypy --strict` + `ruff` PASS on all 16 generators + aggregator.
- No LLM API import / call — pure SQLite + Python aggregation per CLAUDE.md.

## Quality gates

- `mypy --strict scripts/aws_credit_ops/generate_*.py` → no issues found in 16 source files.
- `ruff check scripts/aws_credit_ops/generate_*.py scripts/aws_credit_ops/aggregate_run_ledger.py` → All checks passed.
- `aggregate_run_ledger.py` ran on the existing J01-J07 raw bucket. The derived bucket is not in scope of the
  ledger script — derived prefixes are tracked via per-script `run_manifest.json` written under `out/<outcome>/`.

[lane:solo]
