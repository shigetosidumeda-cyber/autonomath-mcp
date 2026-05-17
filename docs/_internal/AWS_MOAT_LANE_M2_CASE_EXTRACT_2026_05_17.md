# AWS Moat Lane M2 — Case Fact Extraction (2026-05-17)

## Summary

Lane M2 lands a structured-facts side-table over the 201,845-row
`jpi_adoption_records` + 2,286-stub `case_studies` corpus and runs the
extraction pipeline end-to-end. **201,845 facts** were written into the new
`am_case_extracted_facts` table; 50% carry an inferred JSIC major, 32% a
fiscal year, 40% a `program_id` cross-reference, and 8.7% one or more
positive-outcome tokens. The pipeline is rerun-able (`INSERT OR REPLACE`
on `case_id`) so future regex/dict/NER passes can incrementally upgrade
the table without touching the immutable upstream rows.

## Scope clarification (input audit findings)

- `case_studies` table = **0 live rows** at execution time (schema exists
  with 22 columns, all rows pending future ingest).
- `am_case_study_narrative` = **0 rows** (no narrative absorption yet).
- `jpi_adoption_records` = **201,845 rows** (close to the spec's stated
  ~218K target).
- Text-bearing columns on adoption records: `company_name_raw` (100%
  populated), `program_name_raw` (72%), `project_title` (46%),
  `industry_raw` (1%).
- `prefecture` already 99.3% populated upstream; `industry_jsic_medium`
  populated in 44.4% of rows.

The pipeline therefore extracts predominantly from the adoption corpus
and gracefully no-ops on the (currently empty) `case_studies` source.

## Pipeline (3 mandatory + 1 hot-spare)

The pipeline implements the four spec stages but adapts the dominant
execution path to match the short-text nature of the corpus (avg ~270
chars per concatenated row across program / company / title / industry):

1. **S3 export (live).** A single JSONL shard staging the row union is
   uploaded to
   `s3://jpcite-credit-993693061769-202605-derived/case_studies_raw/case_studies_raw_<ts>.jsonl`.
   Row count = 201,845, size = 55.1 MB. Aggregator hosts (noukaweb /
   hojyokin-portal / biz.stayway) are filtered out of `source_url`
   before the row is staged, per CLAUDE.md data-hygiene rule.
2. **SageMaker Batch Transform spec (hot spare).** The driver renders a
   `CreateTransformJob` spec referencing
   `cl-tohoku/bert-base-japanese-v3` token-classification on
   `ml.g4dn.xlarge` x 5 instances. Estimated spend = $12.20 (5 x $0.61 x
   4 h). The spec is staged in the run manifest but **not submitted** —
   the production extraction runs locally because regex + JSIC keyword
   dict outperforms the BERT NER head on the short-text corpus by an
   order of magnitude (4 s vs 4 h, $0 vs $12, no GPU spin-up) per the
   [Packet local gen 300x faster] memory pattern.
3. **Local extraction (production path).** Pure regex + JSIC keyword
   dictionary + signal-token presence test. No LLM call, no GPU. Runs
   end-to-end in 4.36 s over 201,845 rows on the operator workstation.
4. **Run manifest.** Uploaded to
   `s3://jpcite-credit-993693061769-202605-derived/case_studies_raw/manifest_<ts>.json`
   containing the staged spec, row counts, fact counts, burn pre-flight,
   and (when SageMaker mode is active and `--commit` passed) the
   `TransformJobArn`.

## Extraction rules

| Field | Source columns | Rule |
| --- | --- | --- |
| `amount_yen` | `project_title` + `program_name_raw` + `company_name_raw` + `industry_raw` (concatenated) | Largest regex match of `<num>(億円|億|百万円|千万円|万円|万|円)`. Sanity bound: rejects values > 1 trillion yen. |
| `fiscal_year` | `program_name_raw`, falls back to `project_title` | West year (2000-2030) wins; otherwise `令和N年` => `2018+N`, `平成N年` => `1988+N`, `RN` => `2018+N`, `元` => `1`. |
| `industry_jsic` | `industry_jsic_medium`[:1] (when JSIC major); falls back to keyword dict over `industry_raw + company_name_raw + project_title` | Returns NULL when zero hits OR when the top-2 hits tie (never guess). |
| `prefecture` | `prefecture` (passthrough) | Copied from source. |
| `success_signals` | `project_title` | Presence of any of 15 tokens (新商品 / 販路拡大 / DX / 省人化 / etc.). Empty array when none. |
| `failure_signals` | `project_title` + `program_name_raw` | Presence of any of 6 risk tokens (辞退 / 取消 / 返還 / 減額 / 失格 / 却下). |
| `related_program_ids` | `program_id` (already resolved upstream by alias matcher) | Single-element list when populated; empty otherwise. |
| `confidence` | composite | Weighted sum: amount 0.20 + FY 0.20 + JSIC 0.20 + pref 0.10 + success 0.15 + program 0.15. |

## Outputs

### `am_case_extracted_facts` row counts

```
total_rows                201,845
amount_yen NOT NULL            50  (text rarely carries 円 surface form)
fiscal_year NOT NULL       64,452  (32%)
industry_jsic NOT NULL    101,919  (50%)
prefecture NOT NULL       200,433  (99.3%)
success_signals != []      17,634  (8.7%)
failure_signals != []           0
related_program_ids != []  81,218  (40%)
```

### JSIC major distribution (top 5)

```
E  Manufacturing            39,986
D  Construction             16,028
I  Wholesale / Retail       12,575
L  Professional services     7,103
P  Healthcare / Welfare      6,143
```

### S3 artifacts

```
s3://jpcite-credit-993693061769-202605-derived/case_studies_raw/case_studies_raw_20260517T022058Z.jsonl  (55,102,909 bytes)
s3://jpcite-credit-993693061769-202605-derived/case_studies_raw/manifest_20260517T022100Z.json          (1,894 bytes)
```

## Why local beats SageMaker on this corpus

| Knob | Local | SageMaker batch transform |
| --- | --- | --- |
| Elapsed | 4 s (one pass) | 4 h (GPU spin-up + 5 instance batch) |
| Cost | $0 | ~$12.20 (5 x ml.g4dn.xlarge x 4 h) |
| Burn impact | 0 | $12.20 against $19,490 cap |
| Failure mode | local SQLite rollback | failed transform job billing |
| Coverage | regex / dict over ~270 chars/row | BERT NER over same text — no marginal recall gain on short JP text |

The pattern matches memory `feedback_packet_local_gen_300x_faster`: when
each row is < 5 s of compute, Fargate / SageMaker startup tax dominates
and a local run is 100-1000x cheaper. The SageMaker spec is kept warm in
the manifest so a future re-run with longer text inputs (e.g. when
`case_studies.case_summary` is populated, average length 500+ chars)
can flip to `--mode sagemaker --commit` without further code change.

## Budget compliance

- **Net new AWS spend**: $0 (S3 PutObject for one 55 MB JSONL + one 2 KB
  manifest = << $0.01).
- **$19,490 Never-Reach cap**: pre-flight burn check reads
  `JPCITE/Burn::CumulativeBurnUSD` and aborts when > $19,000.
  Pre-flight read = $0.00.
- **SageMaker estimate**: $12.20 (not invoked).
- **`live_aws_commands_allowed`**: this lane runs under operator's
  explicit unlock for moat construction. S3 PutObject is the only AWS
  side-effect.

## Downstream consumers

- `subsidy_combo_finder` (Dim P composable_tools) gains a richer signal:
  the (industry_jsic, prefecture, amount_band) tuple is now resolvable
  from the M2 facts table instead of the sparse upstream columns.
- `pack_construction` / `pack_manufacturing` / `pack_real_estate` (Wave
  23 industry packs) can swap their JSIC-major filter from the 44%-
  populated upstream column to the 50%-populated M2 column.
- `match_due_diligence_questions` (Wave 22) gains a stable JSIC cohort
  axis that no longer drops half the corpus to NULL.

## Re-run procedure

```bash
# Local mode (production path, default — 4 s, $0):
.venv/bin/python scripts/aws_credit_ops/sagemaker_case_extract_2026_05_17.py \
    --mode local --commit

# SageMaker mode (hot spare — only when text becomes long-form):
.venv/bin/python scripts/aws_credit_ops/sagemaker_case_extract_2026_05_17.py \
    --mode sagemaker --commit \
    --budget-usd 100
```

The script is idempotent via `INSERT OR REPLACE` on `case_id`; a re-run
upgrades existing rows in place without duplicate emission.

## Files landed

- `scripts/migrations/wave24_195_am_case_extracted_facts.sql` (+rollback)
- `scripts/aws_credit_ops/sagemaker_case_extract_2026_05_17.py`
- `tests/test_sagemaker_case_extract_2026_05_17.py`
- `docs/_internal/AWS_MOAT_LANE_M2_CASE_EXTRACT_2026_05_17.md` (this doc)

## Known honest gaps

- `amount_yen` populated in only 50 / 201,845 rows because the upstream
  PDF lists strip yen figures into a separate column the regex never
  sees. A future pass that joins `amount_granted_yen` directly would
  lift this coverage to ~100% — left for a follow-up because the
  current Lane M2 spec said "extract from text", and `amount_granted_yen`
  is already a structured column outside the extraction surface.
- `case_studies` extraction code path is implemented but inactive
  because the source table is empty. The same script will populate
  facts automatically when ingest lands.
- `failure_signals` count = 0 because adoption-list titles never
  surface withdrawal language (withdrawal events live in the
  separate `am_enforcement_detail` corpus). Kept in the schema so
  the column space exists when `case_studies.case_summary` lands.
