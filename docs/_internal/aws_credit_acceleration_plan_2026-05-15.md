# AWS credit acceleration plan for jpcite

Date: 2026-05-15  
Credit balance provided by operator: USD 19,493.94  
Time window: 1-2 weeks  
Status: planning/runbook, no AWS resources created by this document

## 0. Decision

Use the expiring AWS credit for a short, controlled "data and evidence acceleration" run, not for long-lived infrastructure.

The target is to consume **USD 18,300-18,700** of eligible AWS usage and keep **USD 800-1,200** as a safety buffer for billing delay, non-credit-eligible items, taxes, support, data transfer, Cost Explorer API charges, and cleanup lag.

Do not attempt to spend the full USD 19,493.94. AWS Budgets and Cost Explorer are monitoring/control tools, not a guaranteed hard cap across every service and delayed charge.

## 1. Hard rules before any spend

The AWS operator CLI must complete these controls before launching compute-heavy work:

1. Verify the account and credit scope in the Billing console Credits tab.
2. Confirm the IAM user can read Cost Explorer and create Budgets.
3. Create actual and forecast budgets at USD 17,000 / 18,300 / 18,900.
4. Configure an emergency stop policy/action for new spend.
5. Restrict the run to tagged resources only: `Project=jpcite`, `CreditRun=2026-05`, `AutoStop=2026-05-29`.
6. Use only short-lived resources with explicit TTL.
7. Avoid Marketplace, Reserved Instances, Savings Plans, upfront commitments, support upgrades, and anything whose credit eligibility is unclear.
8. Keep production request-time behavior unchanged: jpcite packet outputs still carry `request_time_llm_call_performed=false`.

## 2. Spending envelope

Use this as the budget ledger.

| Bucket | Target USD | Purpose | Stop condition |
|---|---:|---|---|
| Guardrail / buffer | 800-1,200 | billing lag, non-eligible charges, cleanup | never intentionally consume |
| Data lake and storage | 1,000-1,800 | S3 raw official docs, Parquet snapshots, checksums, source registry artifacts | storage complete or daily cost drift |
| Batch ETL compute | 4,000-5,500 | AWS Batch/ECS Spot/Fargate jobs for crawlers, parsers, Parquet builds, static generation | source coverage target reached |
| OCR / document extraction | 2,500-4,500 | Textract or CPU PDF extraction for public PDFs, forms, tables | source_receipt usable fields extracted |
| Analytics / catalog | 1,200-2,500 | Glue Data Catalog, Athena, compaction, source/gap QA queries | tables validate |
| Search / retrieval index | 1,500-3,000 | time-boxed OpenSearch or equivalent index build/evaluation, export artifacts after | quality baseline reached |
| Offline packet generation | 2,000-3,000 | P0/P1 packet examples, proof pages, source receipt ledgers, CSV output fixtures | generated pages pass tests |
| GEO / eval / load testing | 1,000-2,000 | agent-safe OpenAPI/MCP eval, benchmark, load tests, dashboards | release gate evidence collected |

The operator should treat USD 18,700 actual+forecast as the effective stop line.

## 3. Work products to buy with the credit

### 3.1 Source lake

Create a reproducible S3-backed source lake:

- raw official payloads/documents with SHA-256 and fetch metadata
- normalized JSONL and Parquet
- source profile registry candidates
- source receipt candidates
- no-hit check logs
- freshness ledgers
- license boundary review queue

Priority source families:

- NTA法人番号
- NTAインボイス
- e-Gov law/API/documents
- J-Grants / program data where permitted
- gBizINFO
- e-Stat
- EDINET
- JPO
- p-portal / JETRO procurement
- courts / enforcement / ministry notices
- local government subsidy and procurement pages where robots/terms allow

### 3.2 PDF/OCR extraction

Use compute/OCR budget to convert public PDFs into structured source candidates:

- application windows
- eligibility predicates
- exclusion rules
- required documents
- amount caveats
- legal basis references
- deadline/source freshness
- source URL and content hash

All extracted facts remain candidates until tied to `source_receipts[]` and `known_gaps[]`.

### 3.3 Packet/proof generation

Generate source-backed public and private-safe outputs:

- P0 packet examples:
  - `evidence_answer`
  - `source_receipt_ledger`
  - `agent_routing_decision`
  - `company_public_baseline`
  - `application_strategy`
  - `client_monthly_review`
- proof pages with receipt ledgers
- safe JSON-LD blocks
- agent-safe OpenAPI examples
- MCP agent-first catalog examples
- CSV intake quality packets for freee/MF/Yayoi fixture variants

Do not publish raw CSV values, private names, row-level normalized records, or support/debug detail.

### 3.4 CSV-derived private overlay

Use the provided freee/MF/Yayoi fixture patterns to harden:

- provider fingerprinting
- official/legacy/variant/unknown detection
- date/amount/tax/counterparty aliases
- privacy suppression
- small-cell aggregate suppression
- formula injection detection
- client monthly review aggregate packet

### 3.5 GEO and release evidence

Run large, repeatable checks:

- 100 existing GEO questions
- 100 CSV/accounting/public-data GEO questions
- OpenAPI/MCP drift tests
- public page forbidden-claim scans
- proof page receipt completeness checks
- cost preview/cap/idempotency tests
- CSV leak scans
- load tests for packet endpoints and static pages

## 4. Short schedule

### Day 0

- Verify credit applicability and expiry.
- Create budgets and emergency controls.
- Create tagged S3 buckets and log groups.
- Run a small USD 100-300 smoke test.
- Confirm Cost Explorer shows spend by tag/service.

### Days 1-3

- Crawl and mirror public sources.
- Build source metadata and checksum manifests.
- Convert first source families to Parquet.
- Run Glue/Athena schema checks.
- Export a first receipt coverage report.

### Days 4-8

- Scale Batch/Spot jobs.
- Run OCR/PDF extraction and rule candidate extraction.
- Build ranking/evidence candidate datasets.
- Generate packet example JSON.
- Build proof pages and source receipt ledgers.

### Days 9-12

- Run GEO/eval/load tests.
- Build OpenAPI agent-safe and MCP first-call catalog outputs.
- Run release gate scans.
- Re-run high-value extraction gaps.

### Days 13-14

- Stop spend-heavy compute.
- Export all S3 manifests, Parquet datasets, reports, and generated pages.
- Delete or scale down transient OpenSearch/ECS/Batch/Glue resources.
- Leave only low-cost S3 artifacts and documentation.
- Write final credit-run ledger.

## 5. Operator CLI command plan

These commands are for the separate AWS-managing CLI. Do not launch spend-heavy resources until the read-only and budget steps pass.

### 5.1 Read-only account and cost audit

```bash
aws sts get-caller-identity
aws configure list

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGION="ap-northeast-1"
BILLING_REGION="us-east-1"

aws ce get-cost-and-usage \
  --region "$BILLING_REGION" \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

aws budgets describe-budgets --account-id "$ACCOUNT_ID" --region "$BILLING_REGION" || true
```

If `ce:GetCostAndUsage` is denied, stop and fix IAM before running any workload.

### 5.2 Required tags

Every resource created by this run should carry:

```text
Project=jpcite
CreditRun=2026-05
Purpose=evidence-acceleration
Owner=bookyou
AutoStop=2026-05-29
Environment=credit-run
```

### 5.3 Budget controls

Create at least these budgets:

| Budget | Threshold | Action |
|---|---:|---|
| `jpcite-credit-run-watch` | USD 17,000 actual or forecast | notify operator |
| `jpcite-credit-run-slowdown` | USD 18,300 actual or forecast | pause new jobs |
| `jpcite-credit-run-stop` | USD 18,900 actual or forecast | attach deny policy / stop tagged compute |

Budget actions should deny new spend-heavy provisioning and/or stop targeted EC2/RDS where used. For Batch/ECS/Fargate/Bedrock/Textract/OpenSearch, add an hourly operator script because Budgets Actions are not a universal hard stop.

### 5.4 Hourly spend poll

Run this from the operator CLI or a small scheduled Lambda:

```bash
aws ce get-cost-and-usage \
  --region us-east-1 \
  --time-period Start="$(date -u +%Y-%m-01)",End="$(date -u -v+1d +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --filter '{"Tags":{"Key":"CreditRun","Values":["2026-05"]}}' \
  --group-by Type=DIMENSION,Key=SERVICE
```

If tag filtering does not capture all charges, also query unfiltered service-level spend and manually reconcile.

### 5.5 S3 source lake skeleton

```bash
RUN_ID="2026-05"
RAW_BUCKET="jpcite-credit-${ACCOUNT_ID}-${RUN_ID}-raw"
DERIVED_BUCKET="jpcite-credit-${ACCOUNT_ID}-${RUN_ID}-derived"

aws s3api create-bucket \
  --region "$REGION" \
  --bucket "$RAW_BUCKET" \
  --create-bucket-configuration LocationConstraint="$REGION"

aws s3api create-bucket \
  --region "$REGION" \
  --bucket "$DERIVED_BUCKET" \
  --create-bucket-configuration LocationConstraint="$REGION"

for B in "$RAW_BUCKET" "$DERIVED_BUCKET"; do
  aws s3api put-bucket-versioning \
    --bucket "$B" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption \
    --bucket "$B" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block \
    --bucket "$B" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
done
```

### 5.6 Workload queues

Create separate queues so spend can be stopped by category:

- `jpcite-source-crawl`
- `jpcite-pdf-parse`
- `jpcite-parquet-build`
- `jpcite-packet-precompute`
- `jpcite-geo-eval`
- `jpcite-load-test`

Use AWS Batch managed compute environments with Spot where interruption is acceptable. Keep `maxvCpus` capped per queue and raise it only after cost telemetry is visible.

### 5.7 Stop commands

The operator CLI should keep a tested stop script:

```bash
# Disable new Batch work.
aws batch update-job-queue --job-queue jpcite-source-crawl --state DISABLED --region "$REGION" || true
aws batch update-job-queue --job-queue jpcite-pdf-parse --state DISABLED --region "$REGION" || true
aws batch update-job-queue --job-queue jpcite-parquet-build --state DISABLED --region "$REGION" || true
aws batch update-job-queue --job-queue jpcite-packet-precompute --state DISABLED --region "$REGION" || true

# Cancel runnable jobs.
aws batch list-jobs --job-queue jpcite-source-crawl --job-status RUNNABLE --region "$REGION"
aws batch list-jobs --job-queue jpcite-pdf-parse --job-status RUNNABLE --region "$REGION"

# Scale down ECS services if used.
aws ecs list-clusters --region "$REGION"
```

Do not delete S3 output buckets until exported artifacts are copied and verified.

## 6. Do not spend credit on these

- Reserved Instances, Savings Plans, upfront commitments.
- Marketplace subscriptions or third-party models unless credit eligibility is confirmed.
- Long-lived GPU clusters without a concrete dataset/output.
- NAT Gateways left running by accident.
- Large EBS volumes without TTL/snapshots policy.
- Public crawls without robots/terms review.
- LLM-generated claims that cannot be tied back to public source receipts.

## 7. Success criteria

The credit run is successful if it produces:

- source lake with checksums and metadata
- Parquet/Glue/Athena tables for official sources
- expanded source profile registry
- source receipt candidates with known gaps
- public-safe packet examples
- proof pages and JSON-LD examples
- CSV provider fixture test matrix
- GEO eval reports
- release gate evidence
- final cost ledger below USD 19,493.94

## 8. References

- AWS Budgets Actions: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS Cost Explorer API: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-explorer-api.html/
- GetCostAndUsage API: https://docs.aws.amazon.com/en_us/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
- AWS Batch overview: https://aws.amazon.com/documentation-overview/batch/
- AWS Glue Data Catalog: https://docs.aws.amazon.com/glue/latest/dg/catalog-and-crawler.html
- Athena with Glue Data Catalog: https://docs.aws.amazon.com/athena/latest/ug/data-sources-glue.html
- S3 Intelligent-Tiering: https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html
- AWS promotional credits: https://aws.amazon.com/awscredits/
