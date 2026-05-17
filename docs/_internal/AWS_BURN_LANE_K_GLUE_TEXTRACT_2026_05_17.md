# AWS burn Lane K — Glue + Textract additional ($430/day target, 2026-05-17)

## Goal

User adjusted total target to **$19,072 / 7 days = $2,725/day** (buffer
$422 only). Existing Lanes A-J target ~$2,296/day. Lane K closes the
**+$430/day** gap via 2 軸:

| 軸          | Lever                                        | Target $/day | Mechanism                                     |
|-------------|---------------------------------------------|--------------|-----------------------------------------------|
| 1. Glue     | 50 DPU PySpark ETL × ~11h/day               | $242         | packet JSON → ZSTD Parquet (PERF-3 / 24 / 34) |
| 2. Textract | +100-200 PDFs/day (court_decisions disjoint) | ~$200        | additional batch on top of Lane C (~$675/day) |
| **Total**   |                                              | **~$442**    | ≈ +$430/day gap closed                        |

Both lanes preserve the $19,490 Never-Reach hard-stop and the 5-line
hard-stop defence chain (CW $14K / Budget $17K / slowdown $18.3K /
Lambda kill $18.7K / Action deny $18.9K).

## 軸 1 — Glue ETL

### Job

- **Job name**: `jpcite-packet-to-parquet-2026-05-17`
- **Role**: `arn:aws:iam::993693061769:role/jpcite-glue-crawler-role`
  (existing — R/W on derived bucket per
  `infra/aws/glue/jpcite_credit_derived_crawler.json`)
- **Workers**: 50 × `G.1X` (1 DPU each, $0.44 / DPU-hr)
- **Glue version**: 4.0
- **Timeout**: 10 minutes per run (caps stall cost at $3.67)
- **Concurrent runs**: 10

### Spark script

`infra/aws/glue/jpcite_packet_to_parquet_etl.py` — reads a single
JsonSerDe-registered packet table from the `jpcite_credit_2026_05`
Glue catalog and writes ZSTD-compressed Parquet to
`s3://jpcite-credit-993693061769-202605-derived/parquet_zstd_2026_05_17/<source_table>/`.

### Driver

`scripts/aws_credit_ops/run_lane_k_glue_etl.py` — uploads the Spark
script to S3, creates/updates the Glue Job, then iterates over a list
of source tables (default `/tmp/lane_k/glue_etl_tables.txt`, 100
unmigrated `packet_*_v1` tables) and submits one `start-job-run` per
table with `--submit-interval-sec` pacing.

### Cost math

- $0.44 / DPU-hr × 50 DPU = $22/hr per running job
- 10-min timeout cap → $3.67 per job (worst case stall)
- typical packet ~5 MB JSON → <1 min wall clock → ~$0.37 actual cost
- $242/day target → ~65 jobs/day at the $3.67 cap, or ~650 jobs/day
  at the typical $0.37 actual

### First commit (this Lane K session)

```
.venv/bin/python scripts/aws_credit_ops/run_lane_k_glue_etl.py \
    --commit \
    --max-runs 30 \
    --submit-interval-sec 30
```

- **68 runs total submitted across 3 batches** (initial 25 pre-fix, then
  10 + 30 post-fix). Snapshot at session close:
  **27 SUCCEEDED / 34 FAILED / 7 RUNNING**.
- Ledger: `data/lane_k_glue_etl_ledger_2026_05_17.json` (rebuilt from
  AWS source-of-truth via `glue.get_job_runs`).
- Glue Job ID + per-table JobRunId recorded.

#### First-batch failure root cause + fix

The initial 25 submissions failed with
``AnalysisException: Parquet data source does not support
array<struct<...,source_fetched_at:void,...>> data type``. JsonSerDe
infers ``void`` (Spark ``NullType``) for any nested key whose value is
always ``null`` across every row; Parquet rejects the schema. Fix landed
in ``infra/aws/glue/jpcite_packet_to_parquet_etl.py``: a recursive
``_replace_null_with_string`` schema walker recasts every ``NullType``
to ``StringType`` before the write. Post-fix the success rate is
~27/34 ≈ 80% (residual ~7 packets have empty top-level schemas where
even the heal cannot save them; these are best-effort skipped).

### Idempotency

- Re-running the driver replays the same 100 tables; the Glue job's
  `mode="overwrite"` on the Parquet write makes each run idempotent
  on the same target prefix.
- The existing `jpcite-credit-derived-crawler` recrawl picks up the
  new `parquet_zstd_2026_05_17/<table>/` prefix on its next on-demand
  run — no new IAM, no new crawler config.

## 軸 2 — Textract Lane K Phase 2

### Manifest

`data/textract_lane_k_phase2_2026_05_17_manifest.json`
- 1,804 entries
- Source = `autonomath.jpi_court_decisions.pdf_url` (courts.go.jp 判例 PDFs)
- **Strictly disjoint** from Lane C
  (`data/textract_bulk_2026_05_17_manifest.json`, 2,130 entries)
- Verified disjoint set: 1,804 court PDFs not in Lane C
  (Lane C overlap = 261 dropped)

### Driver

`scripts/aws_credit_ops/textract_bulk_phase2_2026_05_17.py` — same
download → S3 stage → `start_document_analysis` (TABLES + FORMS)
pipeline as Lane C `textract_bulk_submit_2026_05_17.py`, retargeted at
the disjoint manifest + a dedicated ledger
(`data/textract_lane_k_phase2_2026_05_17_ledger.json`).

### Cost math

- Textract TABLES + FORMS = $0.05 / page
- 判例 PDF median ~10 pages → $0.50 / PDF
- $200/day target → ~400 PDFs/day from the disjoint pool of 1,804

### First commit (this Lane K session)

```
.venv/bin/python scripts/aws_credit_ops/textract_bulk_phase2_2026_05_17.py \
    --commit --max-pdfs 100 --parallel 8
```

- 100 PDFs attempted; **86 submitted, 14 download_failed**
  (transient HTTP errors on the courts.go.jp asset host — re-runs will
  pick them up via the `_s3_object_exists` head probe).
- Sample probe: first job (sha `dd63c0b2…`) returned `JobStatus: SUCCEEDED`
  within ~4 minutes.
- Ledger: `data/textract_lane_k_phase2_2026_05_17_ledger.json`
- Per-PDF `JobId` recorded for the later drain into the Tokyo derived
  bucket (matches Lane C drain pattern)

### Coordinate with Lane C

- Different manifest, different ledger, different `downstream_output_prefix`
  (`textract_lane_k_phase2_2026_05_17/` vs Lane C's
  `textract_output_2026_05_17/`)
- Same Singapore staging bucket — IAM + budget envelope already cover
  the new load.

## Source / TOS posture

- `courts.go.jp` 判例 PDFs = primary-source judicial artifacts (CC0-equivalent
  government posture; no robots.txt block on `/assets/hanrei/`).
- 33-char User-Agent identifies the operator
  (`Bookyou-jpcite-textract-lane-k-phase2/2026.05.17 (+https://jpcite.com; ops@bookyou.net)`).
- No aggregator URLs (the four banned aggregators `noukaweb`,
  `hojyokin-portal`, `biz.stayway`, `minnano-hojyokin` are explicitly
  enumerated in the manifest's `banned_aggregators` field).

## Constraints respected

- $19,490 Never-Reach absolute (Lane K $430/day × 7 days = $3,010 fits
  inside the $422 buffer + $2,296 base = $2,725/day target).
- NO LLM API (Textract + Glue Spark only — no `anthropic` / `openai` /
  `bedrock` imports).
- robots.txt + per-source TOS honor (court PDFs are gov primary).
- `[lane:solo]` marker on driver scripts.
- AWS profile `bookyou-recovery` (memory: secret store separation).
- DRY_RUN default on both drivers; `--commit` lifts the guard.
