# jpcite AWS credit unified execution plan

> Superseded execution SOT: `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`.
> This file remains as the earlier unified AWS plan, but the master execution plan incorporates the later 20-agent AWS review, 30-agent public-source/output expansion, and 10-agent consistency review.

Date: 2026-05-15  
Credit balance: USD 19,493.94  
Window: 1-2 weeks  
Mode: plan only. Do not run commands until the operator explicitly starts the run.

## 0. One-Line Goal

Turn the expiring AWS credit into durable jpcite assets:

- official source lake snapshots
- `source_profile` registry candidates
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- no-hit ledgers
- CSV private overlay safety fixtures
- P0 packet examples
- proof pages
- GEO evaluation reports
- OpenAPI/MCP/llms/.well-known release evidence

The goal is not to keep AWS infrastructure running. After the credit run, AWS should have **no spend-heavy resources left**. If the operator requires zero ongoing AWS bill, export the final artifacts away from AWS and delete the S3 buckets too.

## 1. Spend Strategy

The operator wants to use essentially all of the USD 19,493.94 credit.

Because AWS credits may not apply to every charge, and billing/Cost Explorer can lag, do not aim for exactly USD 19,493.94 of visible usage. Use this control model:

| Line | USD | Meaning |
|---|---:|---|
| Watch | 17,000 | Stop launching new low-value jobs. Continue only high-yield artifact jobs. |
| Slowdown | 18,300 | Stop OCR/OpenSearch/large joins unless they are producing accepted artifacts. |
| No-new-work | 18,900 | No new compute jobs. Only finish, export, verify, and cleanup. |
| Stretch only with manual approval | 19,100-19,300 | Use only if Cost Explorer, untagged spend, and paid exposure are clean. |
| Absolute safety line | 19,300 | Emergency stop. Do not intentionally go beyond this. |
| Credit face value | 19,493.94 | Never target this exact number. Keep the remainder for lag/non-eligible charges. |

This is still a "use almost all credit" plan. The small remainder is not waste; it is the safety margin that prevents cash billing after credits expire.

## 2. What AWS Will Do

AWS will run a short artifact factory. The factory has four layers.

### Layer A: Guardrails First

Before any workload:

1. Confirm credit balance, expiry, account scope, and eligible services in AWS Billing console.
2. Confirm IAM permissions for Cost Explorer, Budgets, S3, Batch, ECS, EC2, Glue, Athena, CloudWatch, ECR, and cleanup operations.
3. Create budgets/alerts.
4. Activate/verify cost allocation tags.
5. Create stop scripts.
6. Run a stop drill before spend-heavy jobs.
7. Run only a USD 100-300 smoke test first.

Budgets are not a hard cap. The real stop mechanism is disabling queues, cancelling jobs, terminating compute, deleting transient services, and eventually deleting S3 after export.

### Layer B: Public Source Lake

AWS will mirror and normalize public/official sources only.

Target source families:

1. NTA法人番号
2. NTAインボイス
3. e-Gov法令
4. J-Grants / public program data where terms allow
5. gBizINFO
6. e-Stat
7. EDINET metadata
8. JPO metadata
9. p-portal / JETRO procurement
10. courts / enforcement / ministry notices
11. selected local government subsidy/procurement pages where robots/terms allow

For each source family, produce:

- `source_profile_delta.jsonl`
- `source_document_manifest.parquet`
- `object_manifest.parquet`
- `normalized/*.parquet`
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `known_gaps.jsonl`
- `no_hit_checks.jsonl`
- `freshness_report.md`
- `license_boundary_report.md`

### Layer C: Extraction and QA

AWS will spend compute on work that produces source-backed evidence:

- PDF/HTML extraction
- public table parsing
- deadline extraction
- eligibility predicate candidates
- required document candidates
- exclusion rule candidates
- legal basis references
- amount caveats
- company identity joins
- invoice no-hit checks
- source receipt completeness scans
- claim graph conflict detection

Any extracted fact remains a candidate until it is connected to a source receipt or moved to `known_gaps[]`.

### Layer D: Product Assets

AWS will generate the assets that directly raise jpcite product value:

- six P0 packet fixtures:
  - `evidence_answer`
  - `company_public_baseline`
  - `application_strategy`
  - `source_receipt_ledger`
  - `client_monthly_review`
  - `agent_routing_decision`
- public packet example JSON
- proof page ledgers
- safe JSON-LD blocks
- agent-safe OpenAPI examples
- MCP agent-first examples
- llms/.well-known discovery artifacts
- GEO eval results
- CSV provider fixture reports
- forbidden-claim scan reports
- no-hit safety audit
- release gate evidence

## 3. Mapping To The Existing jpcite Plan

The existing jpcite implementation plan remains the source of truth. AWS supports it; AWS does not replace it.

| jpcite P0 epic | AWS contribution |
|---|---|
| P0-E1 Packet contract/catalog | Generate catalog fixtures, packet examples, route/tool/pricing matrices |
| P0-E2 Source receipts/claims/gaps | Build receipt/claim/no-hit/freshness/source profile datasets |
| P0-E3 Pricing/cost preview | Produce cost ledger, billing risk reports, eval cases; do not implement billing by AWS spend |
| P0-E4 CSV privacy/intake | Generate synthetic freee/MF/Yayoi fixture matrix and leak scans |
| P0-E5 Packet composers | Provide source-backed fixture inputs and expected packet outputs |
| P0-E6 REST facade | Generate OpenAPI example payloads and error/cap/no-hit examples |
| P0-E7 MCP agent-first tools | Generate MCP example args/outputs and catalog drift reports |
| P0-E8 Public proof/discovery | Generate packet pages, proof ledgers, llms/.well-known content candidates |
| P0-E9 Release gates | Run GEO, forbidden-claim, privacy, receipt completion, drift, and cost scans |

## 4. Job Plan

### Base Jobs J01-J16

| Job | Name | Standard USD | Stretch USD | Main output |
|---|---|---:|---:|---|
| J01 | Official source profile sweep | 600 | 900 | source profile / license boundary |
| J02 | NTA法人番号 mirror and diff | 900 | 1,300 | company identity receipts |
| J03 | NTA invoice registrants and no-hit | 700 | 1,100 | invoice receipts / no-hit checks |
| J04 | e-Gov law snapshot | 800 | 1,200 | legal basis receipts |
| J05 | J-Grants/public program acquisition | 1,600 | 2,300 | program requirements |
| J06 | Ministry/local PDF extraction | 2,000 | 3,200 | extracted facts from PDFs |
| J07 | gBizINFO public business signal join | 1,000 | 1,600 | business public signals |
| J08 | EDINET metadata snapshot | 700 | 1,100 | filing metadata bridge |
| J09 | Procurement/tender acquisition | 1,000 | 1,700 | public tender notices |
| J10 | Enforcement/sanction/public notice sweep | 1,100 | 1,800 | notice/no-hit ledger |
| J11 | e-Stat regional statistics enrichment | 600 | 1,000 | regional/stat facts |
| J12 | Source receipt completeness audit | 400 | 800 | completeness gates |
| J13 | Claim graph dedupe/conflict analysis | 700 | 1,200 | conflict and dedupe reports |
| J14 | CSV private overlay safety analysis | 600 | 1,000 | safe join candidates |
| J15 | Packet/proof fixture materialization | 1,200 | 2,000 | P0 packet fixtures |
| J16 | GEO/no-hit/forbidden-claim evaluation | 600 | 1,000 | release evidence |
|  | Base subtotal | 14,500 | 23,200 | Stretch is not all-run |

### Stretch Jobs J17-J24

Use these to push useful spend toward USD 19,000+ only when base jobs are producing accepted artifacts.

| Job | Name | Target USD | Use only if | Output |
|---|---|---:|---|---|
| J17 | Local government PDF OCR expansion | 1,200-2,000 | J06 accepted extraction rate is good | local program facts + OCR confidence ledger |
| J18 | Public-only Bedrock batch classification | 700-1,400 | Model pricing/credit eligibility is confirmed | public claim candidates + review queue |
| J19 | Temporary OpenSearch retrieval benchmark | 700-1,200 | Search quality benchmark has defined questions | retrieval eval + exported index config |
| J20 | GEO adversarial eval expansion | 500-900 | J16 core eval passes | 300-400 query eval report |
| J21 | Proof page scale generation | 600-1,000 | J15 fixture quality is acceptable | more proof pages + leak scan |
| J22 | Athena/Glue QA reruns and compaction | 400-700 | Parquet datasets exist | optimized datasets + QA reports |
| J23 | Static site crawl/render/load check | 300-700 | public pages are generated | crawl/render report |
| J24 | Final artifact packaging/checksum/export | 300-600 | drain window starts | export manifest and checksum ledger |

Target combined spend:

- Base useful run: USD 14,500
- Selective stretch: USD 4,500-4,800
- Total intended useful usage: USD 19,000-19,300
- Do not exceed the absolute safety line.

## 5. AWS Service Plan

| Service | Use | Status |
|---|---|---|
| S3 | temporary source lake, artifacts, reports | Core, but delete after export if zero future bill required |
| AWS Batch | primary job orchestration | Core |
| EC2 Spot | CPU-heavy parsing/join/compaction | Core |
| Fargate Spot | short stateless parsing/control jobs | Core |
| ECR | job images | Core, delete images/repos at end |
| Glue Data Catalog | schema/catalog for Parquet | Core, delete databases/tables at end if zero bill posture |
| Athena | QA queries over Parquet | Core, cleanup query result buckets |
| CloudWatch | minimal logs/alarms | Core, short retention, delete log groups at end |
| CodeBuild | validation/test/report jobs | Conditional |
| Step Functions | orchestration only if Batch manifests are not enough | Conditional |
| Textract | selected public PDF OCR only | Conditional |
| Bedrock batch | public-only classification/extraction candidate generation only | Conditional |
| OpenSearch | temporary retrieval benchmark only | Conditional, delete after export |
| Lambda | small control/stop/report helpers only | Conditional |
| QuickSight | avoid; static reports are enough | Avoid |
| NAT Gateway | avoid unless absolutely necessary | Avoid |
| Marketplace / RI / Savings Plans / Support upgrade | prohibited | Do not use |

## 6. Detailed Execution Phases

### AWS-F0: Manual Preflight

Do not run spend-heavy commands until these are manually confirmed:

- AWS Billing console shows credit balance and expiry.
- Credit eligibility is understood.
- IAM user/role can read billing/Cost Explorer/Budgets.
- The account is the correct account.
- The workload region is fixed, preferably `ap-northeast-1`; billing/control APIs use `us-east-1`.
- Notification email/SNS is confirmed.
- Cost allocation tags are active or the operator understands tag reporting lag.
- No existing expensive resources are already running.
- There is a break-glass way to stop/delete resources.

### AWS-F1: Guardrail Setup

Create:

- budget alerts
- emergency stop policy/action
- S3 buckets with public access blocked
- minimal log groups with short retention
- ECR repo with lifecycle
- Batch compute environments and queues with conservative caps
- Athena workgroup with query limits
- stop scripts

Then run a stop drill with empty/dummy resources.

### AWS-F2: Smoke Run

Budget: USD 100-300.

Run tiny slices of:

- J01 source profile sweep
- J02 or J03 receipt shape test
- J12 receipt completeness audit
- J15 one packet fixture generation
- J16 small forbidden-claim scan

Proceed only if:

- Cost Explorer/Billing visibility works.
- Service mix is expected.
- Outputs land in the expected S3 prefix.
- Stop script works.
- No private/raw values appear.
- No forbidden claims appear.

### AWS-F3: Standard Run

Run J01-J16 in controlled queues.

Scale only when:

- accepted artifact count increases
- failure rate is low
- no private leak
- no unexpected service spend
- no untagged spend
- no no-hit misuse
- no forbidden professional claim

### AWS-F4: Stretch Run

Run J17-J24 only if standard run is healthy and the actual+forecast spend is below slowdown lines.

The best stretch spend is:

1. more useful OCR on public PDFs
2. more proof pages
3. larger GEO/adversarial eval
4. claim graph conflict analysis reruns
5. final packaging/export

Do not stretch with CPU burn or long-lived infrastructure.

### AWS-F5: Drain and Cleanup

At `No-new-work` or on Day 13:

1. Disable all Batch queues.
2. Cancel queued jobs.
3. Terminate running nonessential jobs.
4. Export all S3 artifacts to local/non-AWS destination.
5. Verify checksums.
6. Delete transient compute.
7. Delete OpenSearch/Glue crawlers/Athena outputs/CloudWatch logs/ECR images.
8. Delete S3 buckets if zero ongoing AWS bill is required.
9. Delete budgets/actions if no longer needed.
10. Run final cost/resource audit.

## 7. Mandatory Stop Conditions

Stop new work immediately if any condition appears:

- actual+forecast reaches USD 18,900
- actual+forecast enters USD 19,100-19,300 without manual approval
- paid exposure appears for non-credit-eligible services
- untagged spend appears and cannot be explained
- unexpected service exceeds USD 100
- Marketplace, Support, Savings Plans, RI, or commitment spend appears
- NAT/data transfer drift appears
- private CSV/raw values appear in AWS artifacts/logs
- no-hit is converted into absence/safety/eligibility
- forbidden claims appear: approved, eligible, safe, no risk, audit complete, tax correct, legal conclusion, creditworthy
- accepted artifact count stagnates for 2 hours while compute keeps running
- job failure rate exceeds 10%
- retry rate exceeds 15%
- review backlog grows but accepted receipts do not
- operator cannot be available to stop within 30 minutes

## 8. Terminal Execution Safety

When running from this terminal later:

- Start with read-only commands.
- Print account ID and region before every write phase.
- Use explicit environment variables.
- Log every command.
- Do not paste destructive cleanup commands until artifacts are exported and checksums verified.
- Never run commands with placeholder values.
- Use small smoke jobs before raising queue caps.
- Keep stop commands in the terminal scrollback and as a separate local file.

Minimum shell behavior:

```bash
set -euo pipefail
export AWS_PAGER=""
export RUN_ID="2026-05"
export PROJECT="jpcite"
export CREDIT_RUN="2026-05"
export REGION="ap-northeast-1"
export BILLING_REGION="us-east-1"
```

Before write commands:

```bash
aws sts get-caller-identity
aws configure list
```

The operator must verbally confirm:

```text
I confirm this is the intended AWS account for the jpcite credit run.
I understand the absolute stop line is USD 19,300.
I understand AWS Budgets is not a hard cap.
I will not leave AWS resources running after the credit run.
```

## 9. End-State: No Further AWS Charges

This is mandatory.

At the end of the credit run, choose one of two end states.

### End State A: Zero Ongoing AWS Bill

Use this if the operator means absolutely no further AWS charges.

Required:

- export all valuable artifacts from S3 to local storage or non-AWS storage
- verify checksums
- delete all S3 objects and buckets
- delete ECR repositories/images
- delete Batch queues and compute environments
- terminate EC2 instances
- delete EBS volumes/snapshots made by the run
- delete ECS services/tasks/clusters made by the run
- delete OpenSearch domains/collections
- delete Glue crawlers/databases/tables created for the run
- delete Athena query result buckets/prefixes/workgroups if created only for the run
- delete CloudWatch log groups/alarms/dashboards created for the run
- delete Step Functions state machines/executions created for the run
- delete Lambda functions created for the run
- delete NAT Gateways, load balancers, EIPs, ENIs if any were created
- delete budgets/budget actions if no longer needed
- run final resource inventory until no tagged resources remain

This is the recommended end state.

### End State B: Minimal AWS Archive

Use only if the operator explicitly accepts a small ongoing AWS bill.

Allowed to keep:

- one S3 bucket with final artifacts only
- no raw private CSV
- no transient intermediate prefixes
- lifecycle policy
- public access blocked
- storage class policy
- monthly budget alarm near zero

This is not zero bill. If the user requires no further billing, do not use this.

## 10. Final Artifacts To Bring Back To The Repo

After export, copy or summarize these into jpcite:

- source profile registry candidates
- source receipt ledger samples
- claim graph and known gaps reports
- no-hit safety report
- CSV fixture/provider alias reports
- packet example JSON
- proof page sidecars
- GEO eval reports
- OpenAPI/MCP drift reports
- cost ledger
- cleanup ledger

Repo-facing output paths should eventually map to:

- `data/source_profile_registry.jsonl`
- `data/packet_examples/*.json`
- `docs/_internal/aws_credit_run_ledger_2026-05.md`
- `docs/_internal/source_receipt_coverage_report_2026-05.md`
- `docs/_internal/geo_eval_aws_credit_run_2026-05.md`
- `docs/_internal/aws_cleanup_zero_bill_report_2026-05.md`

## 11. Plain-English Explanation

This AWS run buys four things:

1. More official facts.
   - AWS fetches and normalizes public official sources.
   - It records where each fact came from.

2. Better evidence.
   - Every reusable claim gets a `source_receipt`.
   - Unsupported claims become `known_gaps`.
   - No-hit stays "not found in this check", not "does not exist".

3. Better product surfaces.
   - Packet examples, proof pages, OpenAPI examples, MCP examples, and llms/.well-known files become grounded in real source ledgers.

4. Better safety.
   - CSV privacy fixtures, forbidden-claim scans, no-hit tests, billing/cap/idempotency checks, and GEO evaluations prove that agents can recommend jpcite safely.

The run should not create a permanent AWS dependency. It should leave behind exported datasets, reports, and generated artifacts, then shut down.

## 12. References

Use official AWS docs before execution:

- AWS credits: https://aws.amazon.com/awscredits/
- AWS Budgets Actions: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS Budgets best practices: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html
- Cost Explorer API: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-explorer-api.html/
- GetCostAndUsage API: https://docs.aws.amazon.com/en_us/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
- AWS Batch: https://docs.aws.amazon.com/batch/latest/userguide/what-is-batch.html
- AWS Batch managed compute environments: https://docs.aws.amazon.com/batch/latest/userguide/managed_compute_environments.html
- Fargate pricing: https://aws.amazon.com/fargate/pricing/
- S3 pricing: https://aws.amazon.com/s3/pricing/
- Athena pricing: https://aws.amazon.com/athena/pricing/
- Glue pricing: https://aws.amazon.com/glue/pricing/
- Textract pricing: https://aws.amazon.com/textract/pricing/
- Bedrock pricing: https://aws.amazon.com/bedrock/pricing/
- OpenSearch pricing: https://aws.amazon.com/opensearch-service/pricing/
