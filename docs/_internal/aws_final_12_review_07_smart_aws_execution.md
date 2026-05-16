# AWS final 12 review 07: smart AWS execution functions

Date: 2026-05-15
Role: final additional validation 7/12
Topic: smarter AWS execution features and methods, not execution order

Target documents:

- `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/aws_final_12_review_01_cost_autonomy.md`

Hard constraints:

- AWS CLI/API/resource creation was not executed.
- No AWS resources were created, changed, or deleted.
- This review writes only this file.
- AWS profile/account/region remain planning references only:
  - profile: `bookyou-recovery`
  - account: `993693061769`
  - region: `us-east-1`

## 1. Verdict

Conditional PASS, with one important upgrade.

The current master plan and `final_12_review_01` are directionally correct:

- stop at `USD 19,300`, not the visible credit face value `USD 19,493.94`
- make AWS self-running so Codex/Claude/local CLI rate limits do not pause the run
- use Step Functions/EventBridge/Batch/SQS/DynamoDB as a short-lived artifact factory
- treat Budget Actions as a backup brake, not a real-time hard cap
- use `control_spend_usd`, not Billing console visible spend, as the true stop metric
- keep jobs bounded, tagged, killable, and exportable
- end with zero-bill teardown

The smarter method is not merely a better schedule. It is a smarter control system:

> Turn AWS into an autonomous artifact-value optimizer: `Budget Token Market + P95 Exposure Model + Artifact Value Density Scheduler + Source Circuit Breakers + Cost Anomaly Quarantine + Monotonic Kill Switch`.

This makes the AWS run behave less like "spend the credit quickly" and more like:

> Buy the highest-value accepted artifacts with bounded spend tokens, stop low-yield or risky work automatically, and preserve the ability to export and tear down before cash exposure appears.

## 2. Main contradictions found

### 2.1 Master plan still says `Visible usage`

Status: wording contradiction.

The master stopline table has a column called `Visible usage`. `final_12_review_01` correctly says executable stoplines must be based on `control_spend_usd`.

Required correction before implementation:

```text
Visible usage -> control_spend_usd
```

Reason:

- Billing console and Cost Explorer can lag.
- Budgets can lag.
- queued/running jobs can create future exposure before billing shows it.
- cleanup/export/control-plane residuals can still cost money.
- some fees may not be eligible for promotional credit.

The implementation must never ask "what does the billing dashboard show right now?" as the primary stop question.

The implementation must ask:

```text
Can the currently observed spend, reserved spend, running tail risk,
queued tail risk, service cap risk, stale telemetry penalty,
untagged resource penalty, and cleanup reserve still fit below 19,300?
```

### 2.2 `control_spend_usd` formula can double count if implemented naively

Status: needs precision.

`final_12_review_01` uses:

```text
control_spend_usd =
  max(billing_actual, billing_forecast_floor, reservation_observed)
  + p95_running_cost_to_complete
  + p95_queued_cost_to_complete
  + p95_service_tail_risk
  + stale_cost_penalty
  + untagged_resource_penalty
  + cleanup_reserve
```

This is directionally right, but implementation must avoid double-counting reservations and P95 tails.

Better formula:

```text
observed_spend_usd =
  max(
    billing_actual_usd,
    budget_actual_or_forecast_floor_usd,
    internal_observed_job_spend_usd,
    resource_meter_observed_spend_usd
  )

unsettled_exposure_usd =
  sum(
    max(
      job.reservation_remaining_usd,
      job.p95_incremental_cost_to_finish_usd
    )
    for every running, starting, runnable, pending, submitted job
  )

control_spend_usd =
  observed_spend_usd
  + unsettled_exposure_usd
  + p95_service_tail_risk_usd
  + stale_cost_penalty_usd
  + untagged_resource_penalty_usd
  + ineligible_charge_uncertainty_reserve_usd
  + cleanup_reserve_usd
```

Important invariant:

```text
Do not add job reservation remaining and p95 remaining for the same job
if the reservation already covers the p95 tail.
Use max(), not sum(), per job.
```

Otherwise the controller may stop too early and fail to use enough credit.

### 2.3 Self-running versus zero-bill teardown

Status: coherent only if the controller is terminal-state aware.

The user wants AWS to keep running even when local development agents are unavailable. That is correct.

But self-running must not mean self-restarting after stop.

Required implementation rule:

```text
KILL_LEVEL and RUN_STATE are monotonic unless a pre-signed,
pre-approved, expiring operator token exists before launch.
```

Terminal states:

- `DRAIN`
- `EXPORT_ONLY`
- `TEARDOWN`
- `POST_TEARDOWN_AUDIT`
- `CLOSED`

Once `TEARDOWN` starts:

- no market clearing
- no new job submission
- no stretch
- no source expansion
- no automatic downgrade
- only list/read/export/verify/delete actions remain

### 2.4 Fast credit burn versus artifact value

Status: potential product contradiction.

The product goal is not "burn USD 19,300." The product goal is "turn the expiring AWS credit into durable jpcite value."

Therefore a pure spend-burner job is invalid, even if it uses credit quickly.

Invalid jobs:

- artificial compute loops
- artificial storage inflation
- long OpenSearch just to consume node-hours
- wide Playwright/OCR on sources with no paid output target
- broad crawling without `accepted_artifact_target`
- large Athena scans without a bounded QA/product outcome

Valid high-spend jobs:

- source receipts that close paid packet gaps
- proof/packet/example generation that improves agent recommendation
- Playwright/OCR on approved public official sources with clear packet targets
- GEO eval that catches release blockers
- graph QA and dedupe that prevents paid packet errors
- export/checksum/assetization jobs needed before zero-bill teardown

### 2.5 Budget Token Market versus cleanup reserve

Status: needs hard invariant.

The budget market must never be allowed to spend the cleanup/export/control reserve.

Required invariant:

```text
market_allocatable_usd =
  19300
  - cleanup_reserve_usd
  - ineligible_charge_uncertainty_reserve_usd
  - post_teardown_audit_reserve_usd
```

The market may reallocate within `market_allocatable_usd`.

The market may not borrow from:

- cleanup reserve
- export reserve
- kill switch reserve
- post-teardown audit reserve
- ineligible charge uncertainty reserve

This prevents the failure mode:

> The run successfully spends the credit, but cannot afford to export, verify, and delete.

## 3. Smarter feature 1: Budget Token Market v2

`final_12_review_01` already proposes token buckets. That is strong. The smarter version is a market, not just static buckets.

### 3.1 Core concept

A token is not money. A token is permission to create bounded future AWS exposure.

Every job must acquire spend permission before submission.

Token states:

| State | Meaning |
|---|---|
| `planned` | job wants budget but cannot submit |
| `reserved` | budget escrowed, job may submit |
| `launched` | AWS job id exists |
| `observing` | job running, cost estimates update |
| `settling` | job finished, artifacts and cost reconcile |
| `refunded` | unused budget returned |
| `forfeited` | used or unsafe budget cannot return |
| `quarantined` | token/job/source held by anomaly manager |

Required fields:

```json
{
  "token_id": "btm_...",
  "run_id": "aws-credit-2026-05",
  "queue_id": "revenue_sources",
  "job_id": "job_...",
  "source_id": "source_...",
  "reserved_usd": 25.0,
  "reservation_remaining_usd": 25.0,
  "p95_incremental_cost_to_finish_usd": 18.5,
  "state": "reserved",
  "ttl_at": "2026-05-16T03:00:00Z",
  "idempotency_key": "..."
}
```

### 3.2 Two-phase job submission

Use a two-phase submit.

Phase 1: reserve token.

```text
if global_state allows new work
and bucket has enough tokens
and source breaker allows method
and service cap allows job class
and accepted_artifact_target is present:
  reserve tokens with DynamoDB conditional write
else:
  do not submit
```

Phase 2: launch job.

```text
if token.state == reserved
and token.ttl_at not expired
and kill_level <= token.allowed_kill_level
and source state still allowed:
  submit Batch job
  attach token_id to job env/manifest
else:
  refund or quarantine token
```

This prevents queued work from outrunning the spend line.

### 3.3 Market clearing

Every 5-15 minutes, the controller should clear the market.

Inputs:

- candidate jobs
- current control spend
- remaining bucket tokens
- source health
- service caps
- artifact value estimates
- P95 cost-to-complete estimates
- run pace error
- current kill level
- manual review backlog
- export/cleanup reserve status

Objective:

```text
maximize total_expected_marginal_artifact_value
subject to:
  global_control_spend_limit
  queue_token_caps
  service_caps
  source_circuit_breakers
  terms/robots/privacy gates
  per-job max runtime
  manual review capacity
  export/cleanup reserve
  kill_level constraints
```

This can be implemented with a simple greedy constrained knapsack first:

1. discard forbidden jobs
2. score remaining jobs by risk-adjusted value density
3. reserve tokens from highest density down
4. stop when global/bucket/service caps bind

No complex ML is required for v1.

### 3.4 Shadow prices for scarce constraints

To make the market smarter, assign a shadow price to scarce resources.

Examples:

| Constraint | Shadow price effect |
|---|---|
| remaining spend low | raises value threshold |
| Playwright pool saturated | penalizes render jobs |
| manual review backlog high | penalizes manual-review-heavy sources |
| terms confidence medium | penalizes source expansion |
| export reserve underfunded | blocks new non-export work |
| near `SLOWDOWN` | favors short, abortable, high-yield jobs |

Adjusted density:

```text
adjusted_value_density =
  expected_marginal_artifact_value
  / p95_incremental_cost_to_finish_usd
  - spend_shadow_price
  - service_shadow_price
  - source_risk_shadow_price
  - manual_review_shadow_price
  - teardown_risk_shadow_price
```

This is smarter than static priority because it adapts when the run state changes.

## 4. Smarter feature 2: Artifact Value Density v2

The current plan already says jobs need `accepted_artifact_target`. Good. The next improvement is to use marginal product value, not just static priority.

### 4.1 Value should be marginal

The 1st accepted `company_public_baseline` proof fixture is highly valuable.

The 10,000th near-duplicate proof fixture is much less valuable.

Therefore value must include diminishing returns:

```text
marginal_value =
  base_packet_value
  * gap_closure_value
  * proof_reuse_value
  * geo_recommendation_value
  * freshness_value
  * novelty_value
  * release_blocker_reduction_value
  * quality_pass_probability
  * terms_confidence_multiplier
  * importability_multiplier
  * diminishing_returns_multiplier
```

Density:

```text
artifact_value_density =
  marginal_value / max(p95_incremental_cost_to_finish_usd, minimum_cost_floor_usd)
```

### 4.2 Required value dimensions

Every candidate job should declare or derive:

| Field | Meaning |
|---|---|
| `primary_paid_output_ids[]` | which sellable packets this improves |
| `output_gap_ids[]` | which known product gaps this closes |
| `source_family_ids[]` | which source families are improved |
| `proof_reuse_count_estimate` | how many pages/packets can reuse the artifact |
| `agent_recommendation_gain` | does this make AI agents more likely to recommend jpcite |
| `accepted_artifact_target` | exact artifact class expected |
| `quality_pass_probability` | estimated chance artifact passes gates |
| `terms_confidence` | legal/robots confidence |
| `importability` | can this fit the repo/static runtime path |
| `manual_review_load` | expected human review burden |

### 4.3 Value score should prefer packet unlocks

Recommended packet unlock weights:

| Artifact outcome | Suggested multiplier |
|---|---:|
| unlocks RC1 paid packet | 5.0 |
| unlocks RC2 paid packet | 3.5 |
| closes high-frequency GEO question | 3.0 |
| improves free preview -> paid conversion | 2.5 |
| improves proof page trust | 2.0 |
| broad source corpus only, no packet target | 0.3 |
| unclear source, no immediate accepted artifact | 0 |

This prevents broad data collection from crowding out sellable outputs.

## 5. Smarter feature 3: P95 queued exposure v2

### 5.1 Cold-start priors

At the beginning, there is no enough historical cost data.

Use conservative priors by job class:

| Job class | P95 prior basis |
|---|---|
| API/bulk fetch | max items, response bytes, retry cap |
| HTML/PDF fetch | page count, bytes, retries |
| Playwright | render seconds, screenshot count, browser startup overhead |
| OCR/Textract | pages, document type, retry cap |
| Athena/Glue | scanned bytes, partition miss risk |
| OpenSearch benchmark | node hours, index size, delete delay risk |
| proof/packet generation | artifact count, validation retries |
| export/checksum | object count, bytes, retry cap |

After enough completed shards, update priors with observed P50/P75/P95.

### 5.2 Use P99 near the safety line

P95 is reasonable in normal run.

Near the spend line, use stricter quantiles:

| State | Exposure quantile |
|---|---:|
| `CANARY` | P95 |
| `RUNNING_STANDARD` | P95 |
| `WATCH` | P95/P97 |
| `SLOWDOWN` | P97 |
| `NO_NEW_WORK` | P99 |
| `RUNNING_STRETCH` | P99 |
| `TEARDOWN` | no new exposure |

Rationale:

- early in the run, underuse is acceptable but should not be extreme.
- late in the run, overshoot is unacceptable.

### 5.3 Exposure must be per-token and per-resource

Queued exposure is not enough. Resource exposure must also be counted.

Examples:

- Batch job token exists but job not launched yet: token exposure
- Batch job running: token + running tail exposure
- OpenSearch domain exists: resource hourly tail exposure until deleted
- ECR image exists: storage tail exposure
- S3 bucket with objects exists: storage/request/delete tail exposure
- CloudWatch log group exists: log ingestion/storage exposure
- NAT Gateway exists: hourly + data processing exposure

This should be represented as:

```text
control_spend_usd =
  observed_spend_usd
  + unsettled_job_exposure_usd
  + live_resource_tail_exposure_usd
  + service_cap_tail_risk_usd
  + penalties_and_reserves_usd
```

## 6. Smarter feature 4: Source Circuit Breaker v2

The current plan correctly includes source-aware circuit breakers. The smarter version makes each source a governed asset with state, method routing, and token recovery.

### 6.1 Source states

```text
CANDIDATE
PROFILED
CANARY_ALLOWED
HEALTHY
THROTTLED
DEGRADED
QUARANTINED
BLOCKED
MANUAL_REVIEW_REQUIRED
RETIRED
```

Only these states can receive normal tokens:

- `CANARY_ALLOWED`
- `HEALTHY`
- limited `THROTTLED`

These states cannot receive new normal tokens:

- `DEGRADED`
- `QUARANTINED`
- `BLOCKED`
- `MANUAL_REVIEW_REQUIRED`
- `RETIRED`

### 6.2 Capture method router

Method escalation must be allowed only if terms/robots/source profile allow it.

Preferred order:

1. official API
2. official bulk download
3. official file download
4. direct HTML fetch
5. Playwright rendered observation
6. OCR/Textract support

Rules:

- Playwright is rendered observation, not bypass.
- 403/login/CAPTCHA/bot challenge means stop supporting claims from that path.
- OCR cannot alone support dates, money, corporate numbers, permit numbers, article numbers, or deadlines.
- screenshot receipts are internal evidence aids, not raw public proof payloads.

### 6.3 Trip conditions

Trip the breaker if any of these occur:

- terms/robots drift to blocked or unknown
- 403
- CAPTCHA/login/bot challenge
- repeated 429 beyond source-specific threshold
- duplicate/no-new-information ratio too high
- accepted artifact yield below floor for 2 consecutive windows
- cost per accepted artifact above ceiling
- OCR confidence collapse
- Playwright render error rate above threshold
- privacy leak signal
- manual review queue exceeds capacity
- source produces claims that fail receipt/claim/gap gates repeatedly

### 6.4 Token recovery after trip

When a source trips:

1. freeze new submissions for that source
2. cancel queued jobs for that source
3. allow running jobs only to checkpoint and stop, unless emergency
4. quarantine partial outputs
5. return unused tokens to reserve
6. mark remaining jobs as lower priority or blocked
7. add a `known_gap` reason for product packets

This converts a failing source into a structured gap instead of wasting money.

## 7. Smarter feature 5: Self-running controller v2

### 7.1 Required control-plane roles

The self-running system should be divided into small functions:

| Component | Responsibility |
|---|---|
| `orchestrator_tick` | owns state transitions and market clearing |
| `sentinel_tick` | checks spend, resources, anomalies, kill state |
| `submitter` | reserves tokens and submits jobs |
| `worker` | executes bounded shard, checkpoints, emits artifacts |
| `settler` | reconciles job cost, refunds/forfeits tokens |
| `source_health_manager` | updates source breakers |
| `anomaly_quarantine_manager` | freezes bad queues/resources |
| `export_manager` | packages verified artifacts |
| `teardown_manager` | deletes resources and verifies zero-bill posture |

The important point is separation:

- submitter cannot override sentinel
- worker cannot create unbounded jobs
- market cannot spend cleanup reserve
- teardown cannot be blocked by deny-create policies

### 7.2 Deadman and heartbeat

Self-running must include a deadman:

```text
if controller_heartbeat_missing > threshold:
  state = DRAIN
  kill_level = max(kill_level, K3)
```

Worker heartbeat:

```text
if worker_heartbeat_missing:
  count remaining reservation as full exposure
  prevent token refund until reconciled
```

This handles local rate limit, Step Functions failure, Lambda failure, and stuck workers.

### 7.3 Monotonic kill state

Use a monotonic integer:

| Level | Meaning |
|---:|---|
| K0 | normal |
| K1 | watch |
| K2 | slowdown |
| K3 | no new work, cancel queued noncritical |
| K4 | export/drain only |
| K5 | terminate compute and teardown |

Conditional write rule:

```text
new_kill_level >= current_kill_level
```

Any downgrade requires a pre-approved token created before launch.

## 8. Smarter feature 6: Adaptive Queue Controller

The current plan says increase shard count when spend is behind. That is good. The smarter version adjusts queue concurrency based on value, risk, and pace.

### 8.1 Desired parallelism formula

```text
desired_parallelism =
  clamp(
    base_parallelism
    + pace_gain * positive_pace_error
    + value_gain * normalized_value_density
    - risk_penalty * normalized_risk
    - manual_review_penalty * backlog_ratio
    - source_health_penalty
    - service_tail_penalty,
    min_parallelism,
    max_parallelism
  )
```

Where:

```text
pace_error = target_control_spend_now - control_spend_usd
```

Important:

- if pace is behind, only expand safe/high-value queues
- never expand a blocked or unknown-terms source
- never expand by creating longer jobs
- expand by adding small killable shards

### 8.2 Conservative bandit is optional but useful

For v1, greedy value density is enough.

For v2, a conservative contextual bandit can allocate a small exploration budget:

```text
exploration_budget_usd <= min(300, 0.02 * remaining_market_allocatable_usd)
```

Constraints:

- no unknown terms
- no private CSV
- no bypass-like Playwright
- no long-lived services
- no Marketplace/Support/RI/Savings Plans
- every exploratory job still needs `accepted_artifact_target`

This can discover high-yield sources without letting exploration consume the run.

## 9. Smarter feature 7: ROI-based stretch

The existing stretch idea is correct. The smarter implementation is a precompiled stretch catalog of micro-jobs.

### 9.1 Stretch is not a new source discovery phase

After `18,900`, stretch should not:

- add new source families
- add unknown terms sources
- create long-lived services
- start large OpenSearch benchmarks
- start broad Playwright/OCR
- start large Athena scans
- depend on manual review

Stretch should:

- finish short accepted artifacts
- generate proof pages from already accepted receipts
- close small high-value gap rows
- run GEO/adversarial checks
- package/export/verify assets
- create additional agent recommendation examples

### 9.2 Stretch job criteria

```text
job_reserved_usd <= min(100, safe_residual_usd * 0.25)
job_max_runtime_minutes <= 60
abort_cost_usd <= 10
terms_confidence == high
quality_pass_probability >= 0.8
artifact_value_density >= stretch_threshold
manual_review_load == low
accepted_artifact_target is not null
```

### 9.3 Safe residual

```text
safe_residual_usd =
  19300
  - observed_spend_usd
  - unsettled_job_exposure_usd
  - live_resource_tail_exposure_usd
  - cleanup_reserve_usd
  - ineligible_charge_uncertainty_reserve_usd
```

If `safe_residual_usd <= 0`, stretch must stop.

## 10. Smarter feature 8: Cost Anomaly Quarantine

This is the most important missing named feature.

Do not wait for total spend to approach the stopline. Quarantine specific bad behavior early.

### 10.1 Anomaly classes

| Class | Example | Default action |
|---|---|---|
| `service_drift` | unexpected service spend appears | freeze service, investigate, maybe K3 |
| `tagless_resource` | untagged EC2/EBS/S3/OpenSearch | quarantine, deny new work, enumerate/delete if run-related |
| `source_runaway` | one source consumes tokens with poor yield | trip source breaker |
| `cost_per_artifact_spike` | accepted artifacts per USD collapses | freeze queue, reallocate tokens |
| `telemetry_stale` | cost/resource data unavailable | add penalty, possible K2/K3 |
| `long_lived_resource_tail` | OpenSearch/NAT/EIP/logs remain | kill/delete path |
| `privacy_signal` | possible private data in output/log | emergency quarantine |
| `terms_signal` | robots/terms drift or challenge page | source quarantine |
| `manual_review_overflow` | outputs pile up unreviewed | freeze manual-heavy sources |
| `export_gate_risk` | export/checksum falling behind | move tokens to export/cleanup |

### 10.2 Quarantine actions

Quarantine should be scoped first, global second.

Source quarantine:

- freeze source submissions
- cancel queued source jobs
- checkpoint/stop running source jobs
- mark affected artifacts `quarantine`
- create `known_gap` entries
- recover unused tokens

Queue quarantine:

- freeze queue
- stop new tokens
- cancel low-value queued jobs
- move remaining tokens to reserve/export

Service quarantine:

- deny new jobs requiring that service
- delete or scale down live resources if safe
- raise service tail risk in `control_spend_usd`

Global quarantine:

- set K3/K4/K5 depending on severity
- preserve only export/cleanup work

### 10.3 Quarantine must not create hidden spend

Quarantine itself must be cheap and bounded.

Allowed:

- DynamoDB state writes
- cancellation/termination/delete/list operations
- bounded manifest export
- short log/ledger write

Forbidden:

- launching analysis clusters
- creating new OpenSearch
- broad Athena scans
- broad re-rendering
- copying large screenshots without export target

## 11. Smarter feature 9: Checkpoint-first workers

To spend quickly and still stop safely, workers must produce partial value.

Required worker behavior:

1. write shard manifest before processing
2. process in small batches
3. checkpoint every N items or every few minutes
4. write candidate receipts incrementally
5. check kill signal between items
6. exit cleanly on K3/K4
7. support idempotent restart
8. produce `partial_candidate` artifacts that can be validated or quarantined
9. never require one huge job to finish before any value appears

This improves:

- stop safety
- value capture
- retry cost
- export readiness
- anomaly isolation

## 12. Smarter feature 10: Product-aware spend governance

The AWS controller should understand product gaps, not just source jobs.

### 12.1 Output gap map

Create an `output_gap_map` before full run:

```json
{
  "paid_output_id": "company_public_baseline",
  "required_artifact_classes": [
    "source_profile",
    "corporate_identity_receipt",
    "invoice_registration_receipt",
    "gbizinfo_receipt",
    "known_gap"
  ],
  "missing_gap_ids": [
    "company_public_baseline.gbizinfo.coverage",
    "company_public_baseline.no_hit.wording"
  ],
  "release_tier": "RC1",
  "revenue_weight": 5.0
}
```

The market should fund jobs that close these gaps first.

### 12.2 Agent recommendation value

Because the business route is GEO, value is not only data coverage.

A job has extra value if it improves:

- free preview quality
- cost preview clarity
- proof page trust
- MCP example quality
- agent-safe OpenAPI examples
- agent recommendation cards
- no-hit caveat clarity
- known gaps clarity
- billing cap clarity

This matters because AI agents need to explain to the end user why buying the packet is reasonable.

## 13. Suggested DynamoDB control model

This is not an AWS execution instruction. It is an implementation design.

### 13.1 `run_control`

```json
{
  "pk": "run#aws-credit-2026-05",
  "sk": "control",
  "state": "RUNNING_STANDARD",
  "kill_level": 0,
  "max_control_spend_usd": 19300,
  "market_allocatable_usd": 18750,
  "cleanup_reserve_usd": 300,
  "ineligible_charge_uncertainty_reserve_usd": 150,
  "post_teardown_audit_reserve_usd": 100,
  "allow_new_work": true,
  "allow_stretch": false,
  "runtime_aws_dependency_allowed": false,
  "last_sentinel_at": "2026-05-15T00:00:00Z",
  "controller_heartbeat_at": "2026-05-15T00:00:00Z"
}
```

### 13.2 `budget_bucket`

```json
{
  "pk": "run#aws-credit-2026-05",
  "sk": "bucket#revenue_sources",
  "cap_usd": 4700,
  "reserved_usd": 0,
  "observed_usd": 0,
  "quarantined_usd": 0,
  "refunded_usd": 0,
  "value_density_p50": 0,
  "accepted_artifacts_per_usd": 0,
  "state": "open"
}
```

### 13.3 `job_ledger`

```json
{
  "pk": "run#aws-credit-2026-05",
  "sk": "job#...",
  "queue_id": "revenue_sources",
  "source_id": "nta_invoice",
  "accepted_artifact_target": "source_receipt",
  "output_gap_ids": ["invoice_vendor_public_check.invoice_registration"],
  "reserved_usd": 12,
  "p95_incremental_cost_to_finish_usd": 8,
  "max_runtime_minutes": 30,
  "max_retries": 1,
  "state": "running",
  "token_id": "btm_...",
  "quality_status": "candidate"
}
```

### 13.4 `source_health`

```json
{
  "pk": "run#aws-credit-2026-05",
  "sk": "source#nta_invoice",
  "state": "HEALTHY",
  "terms_status": "pass",
  "robots_status": "pass",
  "allowed_methods": ["api", "bulk"],
  "blocked_methods": ["playwright"],
  "failure_rate": 0.01,
  "accepted_artifact_yield": 0.92,
  "cost_per_accepted_artifact_usd": 0.03,
  "manual_review_required": false
}
```

### 13.5 `anomaly_event`

```json
{
  "pk": "run#aws-credit-2026-05",
  "sk": "anomaly#...",
  "class": "cost_per_artifact_spike",
  "severity": "medium",
  "scope": "source#example",
  "action": "source_quarantine",
  "created_at": "2026-05-15T00:00:00Z",
  "resolved": false
}
```

## 14. Merge requests for the master plan

Before implementation, merge these functional changes into the master SOT:

1. Rename stopline column from `Visible usage` to `control_spend_usd`.
2. Add `Budget Token Market v2` as the only job submission path.
3. Add two-phase token reserve/launch/settle flow.
4. Lock cleanup/export/post-teardown reserves outside the market.
5. Define `control_spend_usd` with no double counting between reservation and P95 tails.
6. Add P95/P97/P99 quantile switching by run state.
7. Add source states and source circuit breaker trip rules.
8. Add `Cost Anomaly Quarantine` as a named control-plane feature.
9. Add adaptive queue concurrency based on pace, value density, risk, and manual review capacity.
10. Add product-aware `output_gap_map` as an input to AWS job value.
11. Add `agent_recommendation_gain` to artifact value density.
12. Add checkpoint-first worker requirements to every worker class.
13. Require every stretch job to come from a precompiled micro-job catalog.
14. Forbid pure spend-burner jobs even if credit remains.
15. Require deadman behavior: missing controller heartbeat moves to `DRAIN` or higher.

## 15. Final answer to this review question

Yes, there is a smarter method than the current plan, but it is an extension of the current plan, not a replacement.

The master plan already has the right architecture pieces. The smarter version is to make AWS decide what to run through a product-aware value market:

- budget tokens are reserved before jobs launch
- every job must close a known product/output gap
- P95/P99 exposure is counted before billing catches up
- source breakers stop unproductive or risky sources
- adaptive queues move spend toward accepted artifacts per dollar
- cost anomalies quarantine only the bad source/queue/service first
- terminal kill states guarantee export and teardown
- stretch is micro-job based, not a late-stage broad crawl

This gives the desired behavior:

- AWS keeps running without Codex/Claude/local CLI.
- It spends quickly, but not blindly.
- It uses the credit on artifacts that help sell packets through AI agents.
- It stops low-value, risky, or unbounded work automatically.
- It preserves export and zero-bill teardown.

No fatal contradiction remains if these functional controls are merged before AWS execution.
