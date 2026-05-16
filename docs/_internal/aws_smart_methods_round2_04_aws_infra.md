# AWS smart methods round 2 review 04: AWS execution / infrastructure

Date: 2026-05-15
Role: additional smart-method validation 4/6
Topic: AWS execution, autonomous spend, safety stop, and cost-to-value maximization

Target context:

- Master plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- Existing assumptions:
  - AWS CLI/API/resource creation is prohibited in this review.
  - No AWS resources were created, changed, or deleted.
  - Planning account reference only:
    - profile: `bookyou-recovery`
    - account: `993693061769`
    - region: `us-east-1`
  - Credit face value is about `USD 19,493.94`.
  - Execution safety line remains `USD 19,300` `control_spend_usd`.
  - AWS is a short-lived artifact factory, not production runtime.
  - End state is zero ongoing AWS bill after external export and teardown.

This review writes only this file.

## 1. Verdict

Conditional PASS, with a stronger infrastructure concept.

The current smart-method plan already has the right primitives:

- `Budget Token Market v2`
- `control_spend_usd`
- `artifact value density`
- `source circuit breakers`
- checkpoint-first workers
- ROI-based stretch
- zero-bill teardown

The additional smart method is to turn those primitives into an explicit, disposable AWS execution operating system:

```text
AWS Artifact Factory Kernel
= deterministic run state
+ probabilistic budget leasing
+ canary economics
+ interruption-tolerant map-reduce
+ checkpoint compaction
+ service-mix firewall
+ teardown simulation
+ rolling external exit bundle
```

This is smarter than only "run Batch jobs under a budget" because it makes every dollar, worker, source, and service justify itself before the system scales.

The important shift:

```text
Spend fast, but only through bounded leases that produce accepted artifacts
or release-blocking evidence.
```

Do not let the AWS run become a crawler, OCR farm, or compute spender. It should behave like a market that buys durable jpcite assets.

## 2. Non-overlap with previous smart-method reviews

Previous review already established:

- jobs reserve budget before execution
- `control_spend_usd` is the stop metric
- P95 exposure must avoid double counting reservations
- accepted artifact value determines scheduling
- bad sources are circuit-broken
- final stretch should be short, high-value, low-abort-cost

This review adds methods that were not fully specified:

1. `Run Kernel`: a single authoritative finite-state controller for all AWS execution.
2. `Probabilistic Budget Leasing`: budget tokens as expiring leases with uncertainty margins, reclaim, and escrow.
3. `Canary Economics`: scale decisions based on measured accepted-artifact yield per dollar.
4. `Spot-Interruption-Tolerant MapReduce`: all expensive work made abortable, idempotent, and reducible.
5. `Checkpoint Compaction`: convert partial work into accepted artifacts continuously, not only at job end.
6. `Service-Mix Firewall`: service-level spend shapes and deny rules, not only global spend.
7. `Teardown Simulation`: every resource must have a deletion route before it can be created.
8. `Rolling External Exit Bundle`: valuable artifacts leave AWS throughout the run, not only at the end.
9. `Panic Snapshot`: emergency stop preserves ledgers, manifests, and accepted artifacts before deletion.
10. `Canary Economics Ledger`: pilot results become reusable estimates for future non-AWS operation.

## 3. Smart method 1: AWS Artifact Factory Kernel

### 3.1 Why this is needed

The plan currently describes many components:

- EventBridge
- Step Functions
- Batch
- SQS
- DynamoDB control table
- Budgets Actions
- kill switch
- export
- teardown

The smarter method is to define a small "kernel" that owns all state transitions.

Without a kernel, the system risks split-brain behavior:

- Step Functions thinks the run is active.
- Budget Actions have attached a deny policy.
- Batch still has runnable jobs.
- Export jobs are waiting behind compute jobs.
- Teardown starts while reducers still write artifacts.
- A local CLI resumes later and submits work into a draining run.

### 3.2 Kernel responsibilities

The kernel should be the only component allowed to:

- open or close budget leases
- submit new work
- advance run state
- change kill level
- authorize stretch jobs
- authorize export-only work
- authorize teardown
- mark the run closed

All other components are workers or reporters.

### 3.3 Required run states

Use a monotonic state machine:

```text
PLANNED
-> PREFLIGHT
-> CANARY
-> STANDARD_RUN
-> VALUE_STRETCH
-> DRAIN
-> EXPORT_ONLY
-> TEARDOWN_SIMULATION
-> TEARDOWN
-> POST_TEARDOWN_AUDIT
-> CLOSED
```

Rules:

- No state may move backward.
- `DRAIN` and later may not submit source acquisition or OCR jobs.
- `EXPORT_ONLY` may not create expensive compute resources except bounded export/checksum workers.
- `TEARDOWN` may not create resources at all.
- `CLOSED` is terminal.

### 3.4 Single-writer invariant

There must be exactly one logical writer for the run state.

Required invariant:

```text
run_state_update.allowed_writer == kernel
```

Workers may report:

- progress
- spend estimate
- artifact count
- failure
- checkpoint
- lease usage

Workers may not decide:

- "continue"
- "scale"
- "stretch"
- "restart"
- "teardown complete"

This is important because the user explicitly wants AWS to continue when local agents are unavailable, but not to continue after the run should be stopped.

## 4. Smart method 2: Probabilistic Budget Leasing

### 4.1 Problem with plain budget tokens

Plain budget tokens can be too static.

Example failure modes:

- A job reserves `USD 50`, uses `USD 3`, and leaves unused budget locked.
- A job reserves `USD 20`, but spot interruption/retry pushes p95 exposure to `USD 70`.
- A queue has many small jobs that collectively create high tail risk.
- A late-stage stretch job starts with enough average budget, but not enough p99 stop safety.

### 4.2 Lease model

Replace plain reservations with expiring budget leases.

Each job must request:

```json
{
  "job_id": "Jxx-shard-000123",
  "job_class": "playwright_capture|ocr_extract|athena_qa|graph_reduce|export",
  "source_id": "official-source-id",
  "accepted_artifact_target": "company_public_baseline|grant_radar|permit_check",
  "expected_value_points": 12.5,
  "p50_cost_usd": 0.18,
  "p95_cost_usd": 0.71,
  "p99_cost_usd": 1.10,
  "max_cost_usd": 1.35,
  "abort_cost_usd": 0.05,
  "lease_ttl_seconds": 900,
  "checkpoint_interval_seconds": 120,
  "teardown_delete_recipe_id": "delete-batch-array-child"
}
```

The market grants:

```json
{
  "lease_id": "lease-...",
  "granted_budget_usd": 0.85,
  "risk_margin_usd": 0.25,
  "expires_at": "2026-05-15T10:15:00Z",
  "renewable": true,
  "kill_level_required_on_expiry": "checkpoint_then_stop"
}
```

### 4.3 Lease lifecycle

```text
REQUESTED -> GRANTED -> RUNNING -> CHECKPOINTED -> SETTLED
                         |              |
                         |              -> RENEWED
                         -> EXPIRED -> CHECKPOINT_THEN_STOP
                         -> REVOKED -> CHECKPOINT_THEN_STOP
```

No job should run without a valid lease.

### 4.4 Refund and reclaim

If a job finishes under budget:

```text
refund_usd = granted_budget_usd - observed_incremental_cost_usd - settlement_margin_usd
```

Refunds return to the market only while state is before `DRAIN`.

After `DRAIN`, refunds may be used only for:

- export
- checksum
- compaction
- teardown verification
- post-teardown audit reserve

### 4.5 Risk-adjusted lease admission

Admission should use the stricter of cost and tail risk:

```text
lease_exposure_usd =
  max(
    requested_grant_usd,
    p95_cost_to_complete_usd,
    observed_cost_so_far_usd + p95_incremental_remaining_usd
  )
```

For risky services, use p99:

```text
if job_class in ["opensearch_benchmark", "large_playwright", "textract_ocr"]:
  lease_exposure_usd = max(lease_exposure_usd, p99_cost_to_complete_usd)
```

### 4.6 Why this is smarter

This lets AWS spend quickly without making global stop decisions too blunt.

It also solves a real contradiction:

- The user wants credit consumed fast.
- The user also wants absolutely no spending beyond credit.

Leases allow aggressive parallelism while bounding each unit of future exposure.

## 5. Smart method 3: Canary Economics

### 5.1 Problem

A source can look valuable on paper but be bad in practice:

- HTML is unstable.
- PDFs are scanned.
- OCR quality is poor.
- Playwright is slow.
- terms require manual review.
- many pages produce no accepted claims.
- the source does not close paid packet gaps.

Scaling such a source burns credit without durable value.

### 5.2 Canary economics profile

Every source and capture method pair should create a small economics profile before scale:

```json
{
  "source_id": "mlit-negative-info",
  "capture_method": "api|bulk|html|pdf|playwright|ocr",
  "canary_items": 100,
  "canary_cost_usd": 7.42,
  "accepted_artifacts": 61,
  "accepted_claim_refs": 214,
  "packet_gap_reductions": 37,
  "manual_review_required_rate": 0.08,
  "ocr_low_confidence_rate": 0.02,
  "http_403_429_rate": 0.00,
  "avg_seconds_per_item": 2.4,
  "artifact_value_points": 183.5,
  "value_per_usd": 24.73,
  "scale_recommendation": "scale|limited_scale|suppress|manual_review"
}
```

### 5.3 Canary pass rules

Scale only if:

```text
value_per_usd >= class_min_value_per_usd
accepted_artifact_rate >= class_min_accept_rate
manual_review_required_rate <= class_max_manual_review_rate
terms_status in ["approved", "approved_with_limits"]
http_403_429_rate <= threshold
estimated_scale_cost fits inside market_allocatable_usd
teardown_delete_recipe exists
```

### 5.4 Canary economics is not only cost control

It creates reusable knowledge:

- which sources are cheap to maintain after AWS ends
- which sources need manual review
- which sources are bad targets for Playwright
- which sources produce high-value packet receipts
- which sources should become static prebuilt assets

This helps jpcite after the credit is gone.

## 6. Smart method 4: Spot-interruption-tolerant MapReduce

### 6.1 Why this matters

To spend quickly without waste, the run should use cheap, interruptible compute where possible.

But interruption tolerance must be designed in.

If a 2-hour Playwright/OCR worker loses all progress on interruption, spot savings are fake savings.

### 6.2 Required worker shape

Every expensive job should be split into:

```text
map shard -> checkpoint -> local validate -> emit candidate artifact
reduce -> dedupe -> canonicalize -> accepted artifact -> manifest
```

Shard rules:

- small enough to finish quickly
- idempotent
- deterministic input range
- deterministic output prefix
- checkpoint every N items or every few minutes
- no hidden local state
- can be retried without duplicate public claims

### 6.3 Idempotency key

Use:

```text
idempotency_key =
  hash(run_id, source_id, capture_method, normalized_input_locator, content_hash_or_version)
```

No reducer should accept two artifacts with the same idempotency key unless the newer one is explicitly a superseding version.

### 6.4 Worker termination behavior

On lease expiry, kill signal, or interruption notice:

1. stop taking new input items
2. flush current item if safe
3. write checkpoint
4. emit partial candidate artifact manifest
5. release unused lease budget
6. exit with a classified status

Classified statuses:

```text
SUCCESS_ACCEPTED
SUCCESS_NO_ACCEPTED_ARTIFACT
CHECKPOINTED_RETRYABLE
CHECKPOINTED_NOT_WORTH_RETRYING
SUPPRESSED_BY_SOURCE_BREAKER
SUPPRESSED_BY_SERVICE_FIREWALL
FAILED_TERMS
FAILED_PRIVACY
FAILED_COST_EXPOSURE
```

### 6.5 MapReduce by job class

| Job class | Map unit | Reduce unit | Checkpoint target |
| --- | --- | --- | --- |
| API/bulk source | page/date/shard | source dataset manifest | raw response hash, parsed records |
| PDF extraction | document | extracted text + layout | document receipt |
| Playwright | URL/render state | rendered observation receipt | screenshot metadata, DOM digest |
| OCR/Textract | page/image | candidate text spans | OCR confidence ledger |
| claim graph | source family | deduped claim refs | canonical entity/source IDs |
| packet examples | packet type/entity | proof fixture | packet manifest |
| GEO eval | prompt case | eval result | decision trace |
| export | prefix/chunk | external bundle manifest | checksum ledger |

## 7. Smart method 5: Checkpoint Compaction

### 7.1 Problem

Checkpointing alone can create a large pile of partial outputs.

If compaction waits until the end, emergency stop can leave many "almost useful" artifacts.

### 7.2 Continuous compaction

Run reducers continuously:

```text
raw/checkpoints -> candidate artifacts -> accepted artifacts -> packet fixtures -> export bundle
```

The system should aim to keep the distance between work performed and durable accepted artifacts small.

### 7.3 Compaction priority

Compaction should outrank new source expansion when:

```text
pending_checkpoint_value_points > new_source_expected_value_points
or
control_spend_usd >= 17000
or
run_state in ["VALUE_STRETCH", "DRAIN"]
```

### 7.4 Compaction ratio

Track:

```text
compaction_ratio =
  accepted_artifact_value_points
  / max(1, checkpointed_candidate_value_points)
```

If compaction ratio is low:

- stop expanding that source
- inspect schema mismatch
- inspect parser quality
- inspect terms/license gate
- inspect duplicate rate

### 7.5 Why this is smarter

It increases the chance that even a mid-run stop leaves useful product assets.

It also avoids the classic failure:

```text
We spent money collecting data, but the data never became product-ready artifacts.
```

## 8. Smart method 6: Service-Mix Firewall

### 8.1 Problem

Global spend control is not enough.

A single service can create bad spend shape:

- NAT Gateway
- public IPv4
- OpenSearch left running
- CloudWatch log explosion
- unbounded Athena scans
- large Textract OCR
- cross-AZ/cross-region transfer
- ECR storage/pulls

### 8.2 Service spend shape

Define allowed spend bands by service category:

```json
{
  "compute_batch_spot": {"target_share": 0.35, "hard_max_share": 0.55},
  "playwright_compute": {"target_share": 0.15, "hard_max_share": 0.30},
  "ocr_textract": {"target_share": 0.10, "hard_max_share": 0.20},
  "s3_storage_requests": {"target_share": 0.08, "hard_max_share": 0.15},
  "athena_glue_qa": {"target_share": 0.08, "hard_max_share": 0.15},
  "bedrock_batch_public_only": {"target_share": 0.05, "hard_max_share": 0.12},
  "opensearch_benchmark": {"target_share": 0.00, "hard_max_share": 0.08},
  "network_nat_public_ipv4": {"target_share": 0.00, "hard_max_share": 0.01},
  "cloudwatch_logs": {"target_share": 0.02, "hard_max_share": 0.05},
  "control_plane": {"target_share": 0.02, "hard_max_share": 0.05}
}
```

This is not a pricing promise. It is a control shape.

### 8.3 Firewall actions

If a service exceeds its band:

```text
WARN -> QUARANTINE_SERVICE -> DENY_NEW_LEASES_FOR_SERVICE -> DRAIN_SERVICE -> KILL_SERVICE
```

Examples:

- OpenSearch exceeds pilot budget: delete benchmark cluster after export.
- CloudWatch logs exceed log budget: lower log level, shorten retention, stop noisy worker class.
- Athena scans exceed expected bytes: deny new scan leases until partition/index fixed.
- NAT/Public IPv4 appears unexpectedly: immediate quarantine and resource inventory.
- Textract low confidence and high cost: stop OCR and route to manual review/metadata-only.

### 8.4 Unknown service tax

Any unplanned service usage should add a penalty:

```text
control_spend_usd += unknown_service_penalty_usd
```

And trigger:

```text
deny_new_work_for_unknown_service = true
```

Unknown service spend is more dangerous than known high spend.

## 9. Smart method 7: Teardown Simulation

### 9.1 Problem

Zero-bill teardown cannot be an afterthought.

If deletion is designed after resources exist, the run can end with:

- orphaned ENIs
- EBS snapshots
- ECR images
- CloudWatch log groups
- Athena outputs
- Glue catalogs
- S3 multipart uploads
- OpenSearch domains
- Batch compute environments
- Step Functions histories
- EventBridge schedules

### 9.2 Create-time deletion contract

Every planned resource class must have a deletion contract before canary:

```json
{
  "resource_class": "aws_batch_compute_environment",
  "create_allowed": true,
  "required_tags": ["jpcite_run_id", "jpcite_owner", "jpcite_teardown_group"],
  "delete_recipe_id": "batch-compute-env-delete-v1",
  "delete_dependencies": ["job_queue", "jobs_drained"],
  "post_delete_probe": "list_compute_environments_by_tag_returns_empty",
  "max_delete_minutes": 30,
  "orphan_risk": "medium"
}
```

No delete recipe, no create.

### 9.3 Teardown simulation phases

Before scale:

1. build expected resource graph
2. verify every node has delete recipe
3. verify dependency order
4. verify required tags
5. verify deny-create policies will not block delete
6. verify export paths are outside delete dependency
7. verify post-delete inventory checks

After canary:

1. run a canary teardown on canary resources
2. verify no tagged resources remain
3. verify no untagged jpcite-like resources remain
4. verify external export exists
5. only then allow standard run

### 9.4 Teardown readiness score

```text
teardown_readiness_score =
  resource_classes_with_delete_recipe
  / max(1, resource_classes_created)
```

Scale is blocked unless:

```text
teardown_readiness_score == 1.0
```

This is stricter but necessary because the user requires no ongoing AWS charges.

## 10. Smart method 8: Rolling External Exit Bundle

### 10.1 Problem

If all export happens at the end, late failures are dangerous.

Failure modes:

- AWS credit line reached before export.
- S3 deletion is delayed because export is incomplete.
- local agents are unavailable when export is needed.
- a cleanup policy deletes intermediate data before assetization.
- final bundle is large and slow.

### 10.2 Rolling export

Export product-ready artifacts throughout the run:

```text
accepted artifacts -> compacted manifests -> external exit bundle -> checksum receipt
```

The system should have a recent external bundle at all times after canary.

### 10.3 Exit bundle tiers

Use two bundles:

1. `minimum_exit_bundle`
   - run manifest
   - cost ledger
   - accepted artifact manifests
   - source profiles
   - source receipts
   - claim refs
   - known gaps
   - packet fixtures
   - release gate reports
   - teardown manifest

2. `full_exit_bundle`
   - all of the above
   - raw public snapshots allowed by terms
   - rendered observation receipts
   - OCR candidate ledgers
   - GEO eval traces
   - duplicate/conflict ledgers
   - canary economics profiles

### 10.4 Export heartbeat

Track:

```text
latest_minimum_exit_bundle_age_minutes
latest_full_exit_bundle_age_minutes
external_checksum_verified
production_smoke_without_aws_passed
```

If minimum exit bundle age is too old:

- deny new source expansion
- prioritize export and compaction

If full exit bundle age is too old near stopline:

- move to `DRAIN`

## 11. Smart method 9: Panic Snapshot

### 11.1 Problem

Emergency stop can destroy value if it kills workers before ledgers are saved.

### 11.2 Panic snapshot behavior

At high kill level:

1. deny all new leases
2. freeze run state
3. stop source expansion
4. ask workers to checkpoint
5. snapshot control tables
6. snapshot budget lease table
7. snapshot resource ledger
8. snapshot accepted artifact manifest
9. snapshot teardown manifest
10. export minimum bundle
11. start teardown

### 11.3 Maximum panic snapshot duration

Panic snapshot must be bounded:

```text
panic_snapshot_max_minutes = 20
```

If snapshot fails:

```text
proceed_to_teardown_with_last_known_minimum_exit_bundle
```

The run must not keep spending to save perfect artifacts.

## 12. Smart method 10: Delta-first corpus acquisition

### 12.1 Problem

Broad source expansion can waste credit on duplicate or unchanged material.

### 12.2 Use hash-led acquisition

Before expensive extraction:

```text
locator -> metadata fetch -> content hash/digest -> change classification -> extraction decision
```

Extraction decisions:

```text
UNCHANGED_SKIP
METADATA_CHANGED_LIGHT_PARSE
CONTENT_CHANGED_PARSE
NEW_HIGH_VALUE_PARSE
NEW_LOW_VALUE_CANARY_ONLY
TERMS_CHANGED_MANUAL_REVIEW
```

### 12.3 Duplicate suppression

Use:

- normalized URL hash
- document content hash
- PDF text hash
- visual screenshot perceptual hash
- source version timestamp
- entity/date/source composite key

Do not run OCR/Playwright twice on equivalent material unless the previous artifact failed quality gates.

### 12.4 Why this is smarter

Credit should be spent on closing output gaps, not rediscovering unchanged pages.

This is especially important for:

- law/regulation updates
- local government pages
- procurement pages
- notices
- PDFs with repeated templates
- ministry guideline pages

## 13. Smart method 11: Conservative auction between job classes

### 13.1 Why not pure multi-armed bandit

Multi-armed bandits are tempting, but a naive bandit can be unsafe:

- it may over-explore expensive sources
- it may chase noisy early wins
- it may ignore teardown/export reserve
- it may optimize artifact count instead of paid packet unlock
- it may shift too much into OCR/Playwright

### 13.2 Use constrained auctions instead

Each job class bids for leases:

```text
bid_score =
  expected_artifact_value_points
  * quality_pass_probability
  * packet_unlock_multiplier
  * freshness_multiplier
  / p95_cost_to_complete_usd
```

Then apply constraints:

```text
service_mix_within_firewall
source_terms_approved
teardown_recipe_exists
minimum_exit_bundle_recent
reserve_not_borrowed
kill_level_allows_job_class
```

Only after constraints pass may high bid jobs receive leases.

### 13.3 Exploration budget

Exploration should be capped:

```text
exploration_budget_usd <= min(500, 0.03 * market_allocatable_usd)
```

Exploration must not include:

- unknown terms
- CAPTCHA/login/blocked pages
- private CSV
- production runtime dependency
- long-lived service benchmarks without teardown recipe

### 13.4 Practical result

This gives most of the benefit of adaptive allocation without letting the algorithm gamble with the credit.

## 14. Smart method 12: Source-aware capture economics

### 14.1 Capture method ladder

For each source, choose the cheapest reliable method:

```text
official API
-> official bulk file
-> official structured download
-> static HTML
-> PDF text extraction
-> Playwright rendered observation
-> OCR/Textract candidate extraction
-> metadata-only/manual review
```

### 14.2 Capture economics score

```text
capture_economics_score =
  accepted_artifact_rate
  * claim_support_strength
  * packet_gap_reduction
  / (p95_capture_cost_usd + p95_reduce_cost_usd)
```

If Playwright or OCR has a lower score than metadata-only plus manual-review flag, do not scale it.

### 14.3 Render-only before OCR

For hard pages:

1. render screenshot/DOM digest
2. classify if there is extractable text
3. run OCR only if it can close a known packet gap
4. otherwise store rendered observation as non-claim-support receipt

This prevents OCR from becoming the default expensive path.

## 15. Smart method 13: Failure-value ledger

### 15.1 Why failures can be valuable

Not every failed source is wasted.

Useful failures:

- terms unclear
- source unstable
- no stable identifier
- OCR low confidence
- source not suitable for no-hit
- Playwright blocked by legitimate access limitation
- source duplicates a better source

### 15.2 Failure artifact

Emit a structured failure artifact:

```json
{
  "source_id": "example",
  "failure_type": "terms_unclear|unstable_dom|low_ocr_confidence|duplicate|blocked|no_stable_id",
  "cost_usd": 3.12,
  "prevents_future_waste": true,
  "recommended_future_action": "manual_terms_review|suppress|metadata_only|use_alternate_source",
  "affected_packet_ids": ["permit_check", "vendor_risk"],
  "known_gap_ids": ["gap-..."]
}
```

This turns bad canaries into planning assets.

### 15.3 Scheduling impact

If a source has high failure value but low product value:

- stop scaling it
- preserve the failure artifact
- update source registry
- update proof page caveats
- update future source discovery rules

## 16. Smart method 14: Cost-to-release critical path

### 16.1 Problem

The highest-value AWS job is not always the highest artifact-value job.

Sometimes the most valuable job is the one that unlocks production release:

- release gate report
- packet fixture
- public proof page render
- OpenAPI/MCP consistency check
- no-hit forbidden phrase scan
- AWS-free production smoke
- export checksum

### 16.2 Release-critical multiplier

Add:

```text
release_critical_multiplier =
  3.0 if job unblocks RC1
  2.0 if job unblocks RC2
  1.5 if job reduces release rollback risk
  1.0 otherwise
```

Then:

```text
artifact_value_density =
  base_value_density
  * release_critical_multiplier
```

This keeps AWS focused on production deployment, not only corpus scale.

## 17. Smart method 15: Teardown-first resource architecture

### 17.1 Principle

Prefer resources that are:

- tagged
- short-lived
- stateless
- exportable
- deleteable by prefix/run id
- not externally coupled
- not needed by production after AWS ends

Avoid resources that are:

- hard to enumerate
- hard to delete
- prone to hidden dependent resources
- long-lived
- stateful without export
- expensive while idle

### 17.2 Architecture choice implications

Prefer:

- Batch/Fargate/EC2 Spot for bounded jobs
- S3 temporary buckets with run id prefixes
- DynamoDB control table only during run
- Step Functions for bounded orchestration
- CloudWatch short retention
- Athena/Glue only with partitioned bounded scans

Conditional:

- Textract only after canary economics pass
- Bedrock batch only for public-only classification/eval with strict output boundaries
- OpenSearch only as a benchmark, never default runtime

Avoid:

- NAT Gateway unless there is no workable alternative
- long-lived OpenSearch
- broad unpartitioned Athena
- unbounded CloudWatch logs
- final S3 archive if zero-bill is mandatory
- any AWS service that production requires after teardown

## 18. Final recommended infrastructure design

### 18.1 Control plane

Minimal short-lived control plane:

```text
EventBridge schedule
-> kernel state machine
-> budget lease market
-> queue admission
-> Batch/SQS workers
-> reducers/compactors
-> export heartbeat
-> teardown manager
```

The control plane must be cheap enough that it does not matter, but strict enough that it owns state.

### 18.2 Worker plane

Workers are disposable.

They receive:

- lease
- shard
- source profile
- capture method
- accepted artifact target
- checkpoint location
- delete recipe reference

They emit:

- checkpoint
- candidate artifacts
- accepted artifacts
- cost estimate update
- failure artifact
- lease settlement

### 18.3 Data plane

Data is staged by maturity:

```text
raw_public_observation
-> parsed_candidate
-> accepted_artifact
-> packet_fixture
-> external_exit_bundle
-> repo/static asset import
```

Only `accepted_artifact` and later should be considered product value.

## 19. Required schema additions before AWS canary

Add these schemas or tables before any AWS resource creation.

### 19.1 `run_kernel_state`

Fields:

- `run_id`
- `run_state`
- `kill_level`
- `max_control_spend_usd`
- `market_allocatable_usd`
- `cleanup_reserve_usd`
- `export_reserve_usd`
- `post_teardown_audit_reserve_usd`
- `state_updated_at`
- `state_update_reason`
- `single_writer_id`

### 19.2 `budget_lease`

Fields:

- `lease_id`
- `job_id`
- `job_class`
- `source_id`
- `accepted_artifact_target`
- `granted_budget_usd`
- `risk_margin_usd`
- `p50_cost_usd`
- `p95_cost_usd`
- `p99_cost_usd`
- `observed_cost_usd`
- `lease_state`
- `expires_at`
- `settled_at`
- `refund_usd`

### 19.3 `canary_economics_profile`

Fields:

- `source_id`
- `capture_method`
- `canary_cost_usd`
- `accepted_artifacts`
- `accepted_claim_refs`
- `packet_gap_reductions`
- `manual_review_rate`
- `ocr_low_confidence_rate`
- `http_block_rate`
- `value_per_usd`
- `scale_recommendation`

### 19.4 `service_mix_firewall_state`

Fields:

- `service_category`
- `target_share`
- `hard_max_share`
- `observed_share`
- `observed_cost_usd`
- `firewall_state`
- `action_taken`

### 19.5 `teardown_contract`

Fields:

- `resource_class`
- `delete_recipe_id`
- `delete_dependencies`
- `required_tags`
- `post_delete_probe`
- `max_delete_minutes`
- `orphan_risk`
- `canary_delete_passed`

### 19.6 `exit_bundle_heartbeat`

Fields:

- `bundle_id`
- `bundle_type`
- `artifact_count`
- `value_points`
- `checksum`
- `external_location`
- `verified_at`
- `age_minutes`

## 20. Go / No-Go changes

### 20.1 GO for AWS canary

Go only if:

- kernel state machine exists
- budget lease schema exists
- canary economics schema exists
- service-mix firewall config exists
- teardown contracts exist for all planned resource classes
- minimum exit bundle format exists
- panic snapshot procedure exists
- workers are checkpoint-first
- no AWS production dependency exists

### 20.2 NO-GO for AWS canary

No-go if:

- any planned resource lacks delete recipe
- any worker cannot checkpoint
- any job class lacks p95/p99 estimate
- service mix has no hard max
- export heartbeat is not implemented
- raw/private CSV is in scope
- production would depend on AWS resources after teardown

### 20.3 GO for standard run

Go only if canary proves:

- accepted artifact yield is real
- canary teardown works
- service mix stayed inside firewall
- export heartbeat works
- panic snapshot can produce minimum exit bundle
- `control_spend_usd` formula is not double-counting leases

## 21. Contradictions or risks found

### 21.1 "Use credit fast" can conflict with "highest value"

Resolution:

- spend fast through leases
- prioritize high value density
- reserve final stretch for short, low-abort-cost jobs
- never run artificial spenders

### 21.2 "Self-running" can conflict with "zero-bill"

Resolution:

- monotonic run states
- terminal states cannot self-restart
- teardown simulation before scale
- rolling external exit bundle

### 21.3 "Broad source acquisition" can conflict with "accepted artifact value"

Resolution:

- canary economics before scale
- output-gap source targeting
- failure-value ledger
- source suppression

### 21.4 "Spot/cheap compute" can conflict with "not wasting work"

Resolution:

- small shards
- idempotency keys
- checkpoint compaction
- reducers running continuously

### 21.5 "Playwright can fetch hard pages" can conflict with costs and terms

Resolution:

- rendered observation only
- no bypass
- terms gate before scale
- screenshot <= 1600px each side
- OCR only when packet gap justifies it
- Playwright canary economics required

## 22. Recommended edits to master plan

These are not applied in this review, because this review writes only this file.

Add a new subsection under the smart-method addendum:

```text
AWS Artifact Factory Kernel
```

Include:

- monotonic run state machine
- probabilistic budget leases
- canary economics profiles
- service-mix firewall
- teardown simulation
- rolling external exit bundle
- panic snapshot

Update AWS canary gate:

```text
No AWS canary until delete recipes, service mix firewall, lease schema,
checkpoint worker contract, and minimum exit bundle heartbeat exist.
```

Update worker contract:

```text
No worker may run without a lease, checkpoint path, idempotency key,
accepted_artifact_target, and delete recipe reference.
```

## 23. Final answer for this review

The plan is directionally strong, but the smarter infrastructure method is:

```text
Do not merely schedule AWS jobs.
Run a disposable artifact factory kernel where every job leases budget,
proves canary economics, survives interruption, compacts checkpoints into
accepted artifacts, stays inside a service-mix firewall, continuously exports
exit bundles, and can prove teardown before it scales.
```

This gives the user what they want:

- Codex/Claude can stop and AWS still runs.
- Credit can be consumed quickly.
- Spending stays bounded by `control_spend_usd`.
- Jobs that do not create durable jpcite value are suppressed.
- Partial progress becomes product assets.
- Final state can return to zero ongoing AWS bill.

