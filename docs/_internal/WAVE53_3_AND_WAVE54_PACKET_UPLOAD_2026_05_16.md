# Wave 53.3 + Wave 54 — 20 generator FULL-SCALE upload (2026-05-16)

Local run with `--commit` against `bookyou-recovery` AWS profile.
Output bucket: `s3://jpcite-credit-993693061769-202605-derived/`.

## Per-outcome counts

| Wave | # | outcome_type | packets | bytes | s3_put_usd | elapsed_s | source |
| ---- | -:| ------------ | ------: | ----: | --------- | --------: | ------ |
| 53.3 | 1 | patent_corp_360_v1 | 10,679 | 18,684,891 | $0.0534 | 0.0 | s3_partial (partial — SIGTERM) |
| 53.3 | 2 | environmental_compliance_radar_v1 | 499 | 1,220,452 | $0.0025 | 27.0 | manifest |
| 53.3 | 3 | statistical_cohort_proxy_v1 | 50 | 155,844 | $0.0003 | 5.0 | manifest |
| 53.3 | 4 | diet_question_program_link_v1 | 10,867 | 22,431,694 | $0.0543 | 0.0 | s3_partial (partial — SIGTERM) |
| 53.3 | 5 | edinet_finance_program_match_v1 | 10,768 | 26,382,381 | $0.0538 | 0.0 | s3_partial (partial — SIGTERM) |
| 53.3 | 6 | trademark_brand_protection_v1 | 10,647 | 20,556,027 | $0.0532 | 0.0 | s3_partial (partial — SIGTERM) |
| 53.3 | 7 | statistics_market_size_v1 | 50 | 80,701 | $0.0003 | 4.0 | manifest |
| 53.3 | 8 | cross_administrative_timeline_v1 | 10,685 | 17,626,073 | $0.0534 | 0.0 | s3_partial (partial — SIGTERM) |
| 53.3 | 9 | public_procurement_trend_v1 | 9 | 17,978 | $0.0000 | 2.0 | manifest |
| 53.3 | 10 | regulation_impact_simulator_v1 | 10,753 | 18,642,134 | $0.0538 | 0.0 | s3_partial (partial — SIGTERM) |
| 54 | 11 | patent_environmental_link_v1 | 10,783 | 22,032,866 | $0.0539 | 0.0 | s3_partial (partial — SIGTERM) |
| 54 | 12 | diet_question_amendment_correlate_v1 | 10,517 | 121,689,872 | $0.0526 | 0.0 | s3_partial (partial — SIGTERM) |
| 54 | 13 | edinet_program_subsidy_compounding_v1 | 10,732 | 25,681,698 | $0.0537 | 0.0 | s3_partial (partial — SIGTERM) |
| 54 | 14 | kanpou_program_event_link_v1 | 4,205 | 8,385,556 | $0.0210 | 219.0 | manifest |
| 54 | 15 | kfs_saiketsu_industry_radar_v1 | 10 | 31,243 | $0.0001 | 1.0 | manifest |
| 54 | 16 | municipal_budget_match_v1 | 55 | 148,970 | $0.0003 | 12.0 | manifest |
| 54 | 17 | trademark_industry_density_v1 | 6 | 19,983 | $0.0000 | 11.0 | manifest |
| 54 | 18 | environmental_disposal_radar_v1 | 41 | 237,822 | $0.0002 | 3.0 | manifest |
| 54 | 19 | regulatory_change_industry_impact_v1 | 17 | 61,365 | $0.0001 | 12.0 | manifest |
| 54 | 20 | gbiz_invoice_dispatch_match_v1 | 5,605 | 11,411,939 | $0.0280 | 289.0 | manifest |

**Totals**: 106,978 packets / 315,499,489 bytes (300.88 MiB) / ~$0.5350 S3 PUT cost / cumulative 585.0s wall on the manifest-clean subset.

## Run notes

- Launched in parallel via `/tmp/wave_run/launch_all.py` (Python driver). Prior bash launcher had a macOS bash 3.2 `declare -A` regression that misrouted 7,269 packets into one prefix; the misrouted objects were deleted before the corrected re-run.
- Each generator emits a `run_manifest.json` summarizing per-outcome counts; this doc aggregates the 20 manifests. Generators SIGTERMed at the 30 min wall budget did not write a manifest — for those, counts are derived by `aws s3 ls --summarize --recursive` over their prefix (`source = s3_partial`).
- NO LLM API import — pure SQLite + Python aggregation per CLAUDE.md.
- `mypy --strict` + `ruff` PASS on all 20 generators (gate enforced by `release.yml`).
- AWS profile = `bookyou-recovery`; local Python subprocess fanout (no Batch — would be wasteful for sub-30 min walks).

[lane:solo]
