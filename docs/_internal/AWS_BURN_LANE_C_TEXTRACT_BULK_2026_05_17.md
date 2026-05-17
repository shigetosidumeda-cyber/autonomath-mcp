# AWS Burn Lane C — Textract bulk OCR (2026-05-17)

User-explicit unlock. Target: drain the jpcite catalog public-PDF corpus through
Amazon Textract for moat construction (一次資料 fact extraction). Daily burn
target ≈ $700/day, well inside the $19,490 hard-stop, well inside Lane J's
$2,000-$3,000/day band when stacked with Lane A/B/D/E/F/G/H/I.

## Why Lane C

- J06 ministry/municipality PDF Textract was aborted previously (0 real PDFs
  captured by the HTML-index crawler; `data/aws_credit_jobs/J06_*` manifest set).
- J16 canonical PDF corpus runner (`scripts/aws_credit_ops/j16_textract_apse1.py`)
  reads from a pre-staged Singapore bucket only — it does not walk the
  jpcite source_url corpus.
- Lane C closes that gap: walk **every** `programs / enforcement_cases /
  am_source` row whose `source_url` is `*.pdf`, stage into Singapore Textract
  bucket, submit `start_document_analysis` (TABLES + FORMS) at 4-8 way parallel.

## Geography contract

- Textract endpoint: **ap-southeast-1** (Singapore). Textract is NOT offered
  in ap-northeast-1 (Tokyo) — j16 runner established this; we reuse the same
  Singapore staging bucket so the IAM role + budget envelope already cover
  Lane C.
- Staging bucket: `jpcite-credit-textract-apse1-202605` under `in/<sha256[:2]>/`.
- Textract output `S3Prefix`: same bucket, `out/<sha256[:2]>/<sha256>/`.
- Downstream Tokyo derived bucket (ETL target): `jpcite-credit-993693061769-
  202605-derived/textract_output_2026_05_17/`.

## Components

### 1. Manifest — `data/textract_bulk_2026_05_17_manifest.json`

Built by an inline SQL walk against both DBs (no aggregator URLs):

```sql
-- jpintel.db
SELECT source_url FROM programs        WHERE source_url LIKE '%.pdf';  -- 1,412
SELECT source_url FROM enforcement_cases WHERE source_url LIKE '%.pdf'; -- 476

-- autonomath.db
SELECT source_url FROM am_source       WHERE source_url LIKE '%.pdf';  -- 1,630
```

After dedup + banned-aggregator filter (`noukaweb`, `hojyokin-portal`,
`biz.stayway`, `minnano-hojyokin`):

- **2,130 unique public PDFs**
- Top domains: `courts.go.jp` (470), `mhlw.go.jp` (198), `maff.go.jp` (133),
  `mlit.go.jp` (125), `meti.go.jp` (75), `it-shien.smrj.go.jp` (73),
  `soumu.go.jp` (41), `cao.go.jp / cfa.go.jp / fsa.go.jp`, plus 47 都道府県.

Each entry carries `sha256(source_url)` as the stable S3 key, so re-runs are
idempotent (HEAD probe in the submit script short-circuits already-staged
PDFs).

### 2. Bulk submit — `scripts/aws_credit_ops/textract_bulk_submit_2026_05_17.py`

DRY_RUN default. `--commit` lifts the guard. Default knobs:

- `--profile bookyou-recovery`
- `--textract-region ap-southeast-1`
- `--stage-bucket jpcite-credit-textract-apse1-202605`
- `--max-pdfs 200` per invocation (operator's spend governor)
- `--parallel 4` (Textract async quota is 600 concurrent jobs; 4-8 parallel
  + exponential backoff on `LimitExceededException` keeps the steady-state
  job count well under quota even when other lanes share the account)
- `--per-page-usd 0.05` / `--budget-usd 700`

Per-PDF flow:
1. HEAD probe `s3://stage_bucket/in/<sha[:2]>/<sha>.pdf` → skip if already staged.
2. HTTP GET `source_url` (User-Agent identifies operator) → check `%PDF-`
   magic bytes → 25 MB cap.
3. `put_object` into stage bucket.
4. `start_document_analysis` (TABLES + FORMS) with `OutputConfig` pointing at
   `out/<sha[:2]>/<sha>/`. Retry on `LimitExceededException` / Throttling with
   exponential backoff (2s → 128s, 6 attempts).
5. Append per-PDF record to ledger.

Ledger output: `data/textract_bulk_2026_05_17_ledger.json` — per-PDF
`status` ∈ {submitted, dry_run, download_failed, s3_put_failed,
textract_submit_failed, worker_exception}. Includes `job_id` for every
submitted PDF so a later drain step can poll `get_document_analysis` without
re-walking S3.

### 3. Bug-fix history (this commit's prior wet-run discoveries)

1. **`UnicodeEncodeError`** on Japanese PDF filenames — urllib's ASCII-only
   HTTP encoder crashed mid-batch and lost the ledger. Fixed by percent-
   encoding `path` + `query` via `urllib.parse.quote` before `Request(...)`.
2. **`LimitExceededException`** from Textract concurrent-job quota — the
   first 200-PDF burst hit the quota on the back half. Fixed by adding
   exponential backoff retry inside `_submit_textract` (6 attempts, 2s base,
   doubles each retry). Dropped default `--parallel` from 8 to 4.
3. **Lost partial progress on crash** — added `_s3_object_exists` HEAD probe
   so a re-run skips the 185 PDFs the first wet-run already staged. Idempotent.

## Cost contract

- $0.05 / page (TABLES + FORMS) in ap-southeast-1.
- Median ministry PDF ≈ 30 pages; conservative cap is `--max-pdfs 200`
  per invocation × 30 pages × $0.05 ≈ **$300 / invocation**.
- Daily target $700 is reached at ~466 PDFs/day with the same page assumption;
  the full 2,130-PDF corpus drains in ~5 days at the conservative rate, or in
  ~3 days at the +30% headroom 600-PDF/day rate (still inside $700/day).
- Hard stops still primary: $14K CW alarm / $17K Budget / $18.3K slowdown
  / $18.7K Lambda kill / $18.9K Action DenyAll IAM.

## Monitor

```bash
# How many jobs currently in flight? (Textract get_document_analysis polls per-job;
# easiest aggregate is the staged S3 in/ count vs out/ count.)
aws s3 ls s3://jpcite-credit-textract-apse1-202605/in/  --recursive --profile bookyou-recovery --region ap-southeast-1 | wc -l
aws s3 ls s3://jpcite-credit-textract-apse1-202605/out/ --recursive --profile bookyou-recovery --region ap-southeast-1 | wc -l

# Ledger inspection
python3 -c "import json; d=json.load(open('data/textract_bulk_2026_05_17_ledger.json')); from collections import Counter; print(Counter(r['status'] for r in d['records']))"
```

## Constraints honoured

- AWS profile `bookyou-recovery` (memory: secret store separation).
- No LLM API calls (Textract is pure OCR + structured extraction).
- Aggregator URLs banned at manifest build time (`noukaweb`, `hojyokin-portal`,
  `biz.stayway`, `minnano-hojyokin`).
- `[lane:solo]` marker.
- Stays well inside $19,490 Never-Reach via `--budget-usd 700` per-day cap
  + the 5-line GHA defence stack.
