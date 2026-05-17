# CC4 — Real-time PDF detection + auto Textract + KG extract pipeline

> Landed 2026-05-17. Sustained-moat update loop. [lane:solo]

## Goal

Detect new public-sector PDF publications within 1-2h of release, run
Textract OCR, extract knowledge-graph entity/relation facts, and ingest
into `autonomath.db` — fully automated, no LLM API, no aggregators.

## Architecture

```
EventBridge rate(1 hour)
    -> Lambda jpcite-pdf-watch-detect
        -> SQS jpcite-pdf-textract-queue
            -> Lambda jpcite-pdf-watch-textract-submit
                -> Textract StartDocumentAnalysis (ap-southeast-1)
                    -> SNS jpcite-pdf-textract-completion
                        -> Lambda jpcite-pdf-watch-kg-extract
                            -> spaCy ja_core_news_lg NER (CPU, no LLM)
                            -> am_entity_facts / am_relation insert
                            -> am_pdf_watch_log row flip
```

## Watch sources (54 total)

| Category | Count | Examples |
|----------|------:|----------|
| 国 — 中央省庁 | 6 | NTA / FSA / MHLW / METI / MLIT / MOJ |
| e-Gov 法令 | 1 | https://elaws.e-gov.go.jp/ |
| 都道府県 | 47 | hokkaido / tokyo / osaka / okinawa ... |
| **total** | **54** | |

Aggregator ban: every source is a `*.go.jp` or `*.lg.jp` first-party
publication point. `robots.txt` honoured (1 req / 3 s per host floor).

## Cron schedule

- EventBridge rule: `jpcite-pdf-watch-hourly`
- Expression: `rate(1 hour)`
- Region: `ap-northeast-1`
- State on landing: **DISABLED** — operator flips ENABLED after one
  dry-run verification tick.

## Lambdas (3 total)

| Lambda | Trigger | Region | Memory | Timeout | Purpose |
|--------|---------|--------|-------:|--------:|---------|
| `jpcite-pdf-watch-detect` | EventBridge rate(1h) | ap-northeast-1 | 1024 MB | 600 s | Crawl 54 sources, hash PDFs, insert + enqueue |
| `jpcite-pdf-watch-textract-submit` | SQS | ap-northeast-1 | 1024 MB | 300 s | Drain queue, S3-stage, StartDocumentAnalysis |
| `jpcite-pdf-watch-kg-extract` | SNS | ap-southeast-1 | 2048 MB | 600 s | spaCy NER + relation, KG insert |

## SQS queue

- Primary: `jpcite-pdf-textract-queue` (ap-northeast-1)
  - VisibilityTimeout: 900 s
  - MessageRetention: 4 d
  - Batch size: 5, batching window 30 s
- DLQ: `jpcite-pdf-textract-dlq`
  - maxReceiveCount: 3, retention 14 d

## SNS topic

- `jpcite-pdf-textract-completion` (ap-southeast-1, co-located with Textract)
- Subscription target: `jpcite-pdf-watch-kg-extract` Lambda

## Sustained burn estimate

| Item | Daily | Monthly | 100-day window |
|------|------:|--------:|---------------:|
| Textract (100 PDF × $1.50) | $150 | $4,500 | $15,000 |
| Detect Lambda (24 ticks × $0.001) | $0.024 | $0.72 | $2.40 |
| SQS / SNS / S3 / data egress | ~$0.5 | ~$15 | ~$50 |
| **Total** | **~$150** | **~$4,515** | **~$15,050** |

Never-reach ceiling: **$19,490**. The CC4 sustained run consumes 77 %
of the budget envelope, leaving 23 % headroom against the 5-line hard
stop (CW $14K / Budget $17K / slowdown $18.3K / Lambda kill $18.7K +
Action deny $18.9K).

## Idempotency contract

1. `am_pdf_watch_log` UNIQUE (`source_url`, `content_hash`) — second
   detection of identical bytes is a DB no-op.
2. `am_entity_facts` UNIQUE (`content_hash`, `entity_label`, `entity_text`).
3. `am_relation` UNIQUE (`content_hash`, `subject`, `verb`, `object`).
4. Lambda `_process_record` re-emits the same JobTag (`jpcite-pdf-watch-<watch_id>`),
   making Textract retries safe.

## SAFETY model

- All resources land **DISABLED** / `JPCITE_PDF_WATCH_ENABLED=false`.
- Operator opt-in via:

```bash
aws scheduler update-schedule \
    --name jpcite-pdf-watch-hourly \
    --state ENABLED \
    --profile bookyou-recovery --region ap-northeast-1
```

- 5-line hard stop sentinels remain primary defence (memory:
  `feedback_aws_canary_hard_stop_5_line_defense`).
- No LLM API. spaCy ja_core_news_lg is a deterministic NER model
  (zero Anthropic / OpenAI calls).

## Files landed

| Path | Purpose |
|------|---------|
| `scripts/migrations/wave24_216_am_pdf_watch_log.sql` | DDL — ledger table |
| `scripts/migrations/wave24_216_am_pdf_watch_log_rollback.sql` | rollback |
| `scripts/cron/pdf_watch_detect_2026_05_17.py` | hourly detector |
| `infra/aws/lambda/jpcite_pdf_watch_textract_submit.py` | SQS → Textract Lambda |
| `infra/aws/lambda/jpcite_pdf_watch_kg_extract.py` | SNS → spaCy NER Lambda |
| `infra/aws/lambda/pdf_watch_pipeline_deploy.py` | boto3 declarative deploy |
| `infra/aws/eventbridge/jpcite_pdf_watch_schedule.json` | schedule + topology |
| `tests/test_cc4_pdf_watch.py` | 16 tests (migration / cron / Lambdas / deploy) |

## Operator playbook

```bash
# 1. Dry-run the detect cron locally
.venv/bin/python scripts/cron/pdf_watch_detect_2026_05_17.py --dry-run

# 2. Dry-run the deploy plan
AWS_PROFILE=bookyou-recovery \
  .venv/bin/python infra/aws/lambda/pdf_watch_pipeline_deploy.py --dry-run

# 3. Commit deploy (creates SQS + SNS + EventBridge rule, all DISABLED)
AWS_PROFILE=bookyou-recovery \
  .venv/bin/python infra/aws/lambda/pdf_watch_pipeline_deploy.py --commit

# 4. Tests
.venv/bin/python -m pytest tests/test_cc4_pdf_watch.py -v

# 5. Enable (operator decision)
aws scheduler update-schedule --name jpcite-pdf-watch-hourly --state ENABLED \
    --profile bookyou-recovery --region ap-northeast-1
```
