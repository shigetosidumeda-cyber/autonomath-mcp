# AWS smart methods round 3 review 06: AWS factory kernel / cost control

Date: 2026-05-15  
Role: Round3 additional smart-method validation 6/20  
Topic: AWS factory kernel, autonomous cost control, artifact value maximization, zero-bill guarantee  
Status: planning review only. AWS CLI/API/resource creation was not executed.  
Output constraint: this file only.

Planning references:

- Master plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- Round2 integrated review: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round2_integrated_2026-05-15.md`
- Round2 AWS infra review: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round2_04_aws_infra.md`
- Final 12 smart AWS review: `/Users/shigetoumeda/jpcite/docs/_internal/aws_final_12_review_07_smart_aws_execution.md`

Hard constraints carried forward:

- AWS account/profile/region are planning references only: `bookyou-recovery`, `993693061769`, `us-east-1`.
- Credit face value is `USD 19,493.94`; intentional absolute control line remains `USD 19,300`.
- Do not target exact credit-face usage.
- AWS is a short-lived artifact factory, not production runtime.
- Codex/Claude/local terminal unavailability must not pause AWS after launch.
- AWS must still stop itself before cash exposure.
- Public/private real accounting CSV must not enter AWS.
- No request-time LLM fact generation.
- Production must run without AWS after release.
- End state must be zero ongoing AWS bill, including no retained S3 archive.

## 0. Verdict

Conditional PASS, with a stronger cost/factory method.

The current plan is already directionally strong:

- `Budget Token Market v2`
- `Probabilistic Budget Leasing`
- `AWS Artifact Factory Kernel`
- `Service-Mix Firewall`
- `Panic Snapshot`
- `Rolling External Exit Bundle`
- `control_spend_usd`
- zero-bill teardown

The additional smarter method is:

```text
Do not allocate AWS spend to jobs.
Allocate AWS spend to accepted-artifact contracts.
```

In other words, the factory should not ask:

```text
Which crawler/OCR/Batch job should run next?
```

It should ask:

```text
Which accepted artifact contract can be bought now,
under probabilistic budget lease,
with bounded teardown debt,
and with enough value density to justify consuming scarce credit?
```

This reframes the AWS run as a temporary market for durable jpcite assets.

## 1. Main new concepts

Round2 already defined the kernel and budget lease primitives. Round3 adds these higher-level functions:

1. `Accepted Artifact Futures`
2. `Spend Corridor Controller`
3. `Factory Balance Sheet`
4. `Teardown Debt Pricing`
5. `Exit-First Artifact Classes`
6. `Salvageable Work Units`
7. `Failure Value Accounting`
8. `Service Risk Escrow`
9. `Autonomous Operator Silence Mode`
10. `Zero-Bill Proof Ledger`
11. `Marginal Value Frontier`
12. `Credit Exhaustion Without Cash Exposure Protocol`

These are not a different execution order. They are smarter control features that make the same execution plan safer and more valuable.

## 2. Smart method 1: Accepted Artifact Futures

### 2.1 Problem

Existing planning still talks in places as if AWS work units are jobs:

- fetch job
- OCR job
- Playwright job
- Athena QA job
- graph reduce job

That is operationally convenient but economically weak.

A job can spend money and still fail to produce a production-usable asset. The user wants to consume the credit quickly, but the product needs durable artifacts. Therefore the spend unit should be an accepted artifact, not a job.

### 2.2 Method

Before the kernel grants spend, the work requester must create an `accepted_artifact_future`.

Example:

```json
{
  "artifact_future_id": "aaf_20260515_company_public_baseline_ntainvoice_000123",
  "run_id": "aws-credit-2026-05",
  "target_packet_ids": [
    "company_public_baseline",
    "invoice_vendor_public_check"
  ],
  "source_family_id": "corporate_identity",
  "source_id": "nta_invoice_registry",
  "artifact_contract": {
    "must_produce_any_of": [
      "source_profile_candidate",
      "source_receipt_batch",
      "no_hit_lease_entries",
      "gap_coverage_matrix_delta",
      "packet_example_inputs"
    ],
    "must_include": [
      "content_hash",
      "retrieved_at",
      "terms_status",
      "license_boundary",
      "capture_method",
      "quality_gate_result"
    ],
    "must_not_include": [
      "private_csv_data",
      "raw_cookie",
      "auth_header",
      "public_raw_screenshot",
      "unsupported_eligibility_claim"
    ]
  },
  "acceptance_tests": [
    "schema_valid",
    "source_policy_pass",
    "packet_gap_reduction_positive",
    "export_manifest_ready",
    "teardown_recipe_exists"
  ],
  "value_points_floor": 25,
  "p95_cost_ceiling_usd": 18.0,
  "teardown_debt_ceiling_usd": 0.50,
  "exit_bundle_class": "hot_release_candidate"
}
```

The Budget Token Market should lease budget to this contract, not directly to the crawler/worker.

### 2.3 Benefit

This prevents false progress:

- "We rendered 1 million pages" is not enough.
- "We generated 80 GB of OCR text" is not enough.
- "We spent USD 3,000 on OpenSearch benchmark" is not enough.

Accepted progress becomes:

- "We reduced packet gaps by N."
- "We produced accepted receipts for a paid packet."
- "We generated release-candidate proof examples."
- "We created failure/gap evidence that prevents bad paid claims."
- "We exported assets outside AWS and can tear down safely."

## 3. Smart method 2: Spend Corridor Controller

### 3.1 Problem

The plan must satisfy two user constraints that are in tension:

1. Use the expiring credit quickly, ideally within about one week once execution starts.
2. Never create cash exposure beyond the credit.

The existing `USD 19,300` control line solves the safety side, but it does not by itself solve pacing.

### 3.2 Method

Add a `Spend Corridor Controller` above the Budget Token Market.

The controller maintains:

```text
lower_progress_band <= control_spend_usd + committed_value_backlog_usd <= upper_safety_band
```

Definitions:

- `control_spend_usd`: internal spend plus unsettled exposure, as already defined.
- `committed_value_backlog_usd`: leases granted to accepted-artifact futures that have not yet started.
- `upper_safety_band`: never above `USD 19,300 - protected_reserves`.
- `lower_progress_band`: target minimum pacing required to finish useful spend in the chosen run window.

The controller does not spend just to hit the lower band. If high-value work is unavailable, it converts unused capacity into:

- extra canaries for source discovery
- graph QA
- proof-page/golden-session evaluation
- export/checksum acceleration
- release blockers discovery
- teardown simulation

It must not create artificial compute/storage burn.

### 3.3 Suggested corridor for a one-week run

Use this as a planning model, not an AWS command:

```text
protected_reserves_usd:
  cleanup_reserve: 350
  external_export_reserve: 250
  post_teardown_audit_reserve: 100
  ineligible_charge_uncertainty_reserve: 300
  emergency_panic_snapshot_reserve: 150
  total: 1,150

market_allocatable_usd:
  19,300 - 1,150 = 18,150
```

For a seven-day useful run:

```text
daily useful-spend corridor:
  day 0: 500 - 1,500    preflight/canary only
  day 1: 2,000 - 4,000  source backbone and proof factory
  day 2: 4,500 - 7,000  high-yield accepted artifacts
  day 3: 7,000 - 10,500 release-critical expansion and RC assets
  day 4: 10,000 - 14,000 broad corpus and vertical packets
  day 5: 13,000 - 17,000 stretch only if value density holds
  day 6: 15,000 - 18,150 export/checksum/QA/teardown prep
  day 7: no new source spend; drain/export/teardown
```

Important:

- These are `control_spend_usd + committed_value_backlog_usd` corridors, not Billing Console numbers.
- Stop new accepted-artifact futures when `control_spend_usd >= 18,900`.
- Stop all non-export/non-cleanup work when `control_spend_usd >= 19,300`.

### 3.4 Why this is smarter

Without a corridor, the run can be too cautious and leave too much credit unused, or too aggressive and create cash exposure.

With a corridor, the factory can move fast while still rejecting low-value spend.

## 4. Smart method 3: Factory Balance Sheet

### 4.1 Problem

A normal cost dashboard says how much has been spent. It does not say whether the spend has become product value, cleanup liability, or unrecoverable waste.

### 4.2 Method

Maintain a `factory_balance_sheet` with five ledgers:

1. `spend_ledger`
2. `artifact_value_ledger`
3. `liability_ledger`
4. `exit_ledger`
5. `zero_bill_ledger`

### 4.3 Ledger definitions

`spend_ledger`:

```json
{
  "observed_spend_usd": 7420.35,
  "unsettled_exposure_usd": 913.22,
  "service_tail_risk_usd": 180.00,
  "cleanup_reserve_usd": 350.00,
  "control_spend_usd": 8863.57
}
```

`artifact_value_ledger`:

```json
{
  "accepted_artifact_count": 28144,
  "packet_gap_reduction_points": 9183,
  "release_blockers_found": 42,
  "release_blockers_cleared": 31,
  "hot_release_candidate_artifacts": 3120,
  "evidence_replay_artifacts": 25024,
  "value_points_total": 143820
}
```

`liability_ledger`:

```json
{
  "open_resources_count": 118,
  "untagged_resource_count": 0,
  "teardown_debt_usd": 42.10,
  "resources_without_delete_recipe": 0,
  "resources_with_public_exposure": 0,
  "services_outside_allowlist": []
}
```

`exit_ledger`:

```json
{
  "external_exit_bundle_versions": 9,
  "accepted_artifacts_exported_pct": 87.4,
  "checksums_verified_pct": 86.9,
  "panic_snapshot_ready": true,
  "latest_exit_bundle_age_minutes": 41
}
```

`zero_bill_ledger`:

```json
{
  "s3_delete_ready": false,
  "ecr_delete_ready": true,
  "batch_delete_ready": false,
  "cloudwatch_delete_ready": false,
  "post_teardown_audit_plan_exists": true,
  "non_aws_attestation_bundle_ready": false
}
```

### 4.4 Control rule

The factory may continue scaling only when all are true:

```text
artifact_value_ledger.value_points_per_control_usd >= current_floor
liability_ledger.resources_without_delete_recipe == 0
exit_ledger.latest_exit_bundle_age_minutes <= max_exit_age
zero_bill_ledger.post_teardown_audit_plan_exists == true
service_mix_firewall.status == pass
```

This adds a value and cleanup dimension to cost control.

## 5. Smart method 4: Teardown Debt Pricing

### 5.1 Problem

Some resources are cheap to run but expensive or risky to clean up correctly.

Examples:

- many log groups
- unmanaged EBS snapshots
- public IPv4 addresses
- orphan ENIs
- OpenSearch domains
- ECR layers
- S3 multipart uploads
- Athena output buckets

### 5.2 Method

Every accepted-artifact future and job lease must include `teardown_debt_usd` and `teardown_complexity`.

```json
{
  "resource_plan": [
    {
      "resource_type": "batch_job",
      "teardown_recipe_id": "delete_batch_job_queue_compute_environment",
      "teardown_debt_usd": 0.05,
      "teardown_complexity": "low"
    },
    {
      "resource_type": "opensearch_domain",
      "teardown_recipe_id": "delete_opensearch_domain_wait_until_gone",
      "teardown_debt_usd": 25.00,
      "teardown_complexity": "high"
    }
  ]
}
```

Value density should include teardown debt:

```text
net_value_density =
  expected_value_points
  / (
      p95_cost_usd
      + teardown_debt_usd
      + service_tail_risk_usd
      + exit_bundle_cost_usd
    )
```

### 5.3 Resource creation gate

No resource may be created unless:

```text
delete_recipe_exists == true
delete_recipe_tested_in_simulation == true
resource_tag_policy_pass == true
zero_bill_ledger_can_track == true
```

This turns zero-bill teardown from a final cleanup activity into a precondition for creation.

## 6. Smart method 5: Exit-First Artifact Classes

### 6.1 Problem

The plan already has Rolling External Exit Bundle. The smarter version is to classify artifacts before they are produced so the exporter knows what must leave AWS first.

### 6.2 Artifact classes

Use these classes:

| Class | Meaning | Export priority |
|---|---|---:|
| `hot_release_candidate` | Needed for RC/prod release | 1 |
| `billing_control_ledger` | Needed to prove spend and stop state | 1 |
| `zero_bill_teardown_ledger` | Needed to delete and audit resources | 1 |
| `policy_terms_ledger` | Needed to prove source boundaries | 2 |
| `evidence_replay_bundle` | Needed to regenerate/verify claims | 2 |
| `packet_fixture_bundle` | Needed for examples and tests | 2 |
| `geo_eval_bundle` | Needed for agent discovery/recommendation | 3 |
| `cold_source_snapshot` | Useful but not release critical | 4 |
| `failed_source_ledger` | Useful for gaps and future planning | 4 |

### 6.3 Export SLA

Every class gets an export SLA:

```text
hot_release_candidate: external export within 15 minutes of acceptance
billing_control_ledger: external export within 5 minutes of update
zero_bill_teardown_ledger: external export within 5 minutes of update
policy_terms_ledger: external export within 30 minutes
evidence_replay_bundle: external export within 60 minutes
cold_source_snapshot: best effort before drain
```

This makes Panic Snapshot smaller because the most important data is already outside AWS.

## 7. Smart method 6: Salvageable Work Units

### 7.1 Problem

If a large job is interrupted, killed, or circuit-broken, its partial output may be lost.

### 7.2 Method

Every expensive job must be decomposed into salvageable units:

```text
source_family -> source -> capture_method -> shard -> document/page -> claim_candidate -> accepted_artifact
```

Each unit must have:

- idempotency key
- checkpoint interval
- partial manifest
- acceptance gate
- export class
- teardown recipe

### 7.3 Required worker behavior

Workers must not hold useful value only in memory until the end.

Required loop:

```text
fetch/render/extract small unit
validate
write checkpoint
compact into candidate artifact
run acceptance tests
export if accepted
settle lease
```

This improves both credit utilization and emergency stopping.

## 8. Smart method 7: Failure Value Accounting

### 8.1 Problem

Some failures are valuable:

- terms blocked
- robots blocked
- source schema changed
- public page unavailable
- OCR too noisy
- no stable identifier
- repeated 429/403
- Playwright allowed but low yield

Currently, failures can look like wasted spend.

### 8.2 Method

Convert safe failures into accepted artifacts when they reduce uncertainty.

Failure artifacts:

- `failed_source_ledger_entry`
- `source_terms_block_entry`
- `capture_method_rejected_entry`
- `schema_evolution_block_entry`
- `known_gap_entry`
- `no_hit_scope_entry`
- `manual_review_required_entry`
- `do_not_retry_until_entry`

### 8.3 Acceptance criteria

A failure artifact is accepted only if it includes:

- source id
- attempted capture method
- timestamp
- reason code
- retry policy
- whether it can support public output
- affected packet ids
- known gap delta
- no prohibited private data

### 8.4 Why this matters

This makes the factory smarter because failed spend still improves the product by preventing unsupported claims and repeated waste.

## 9. Smart method 8: Service Risk Escrow

### 9.1 Problem

Global spend control is not enough. Some AWS services create tail risk or cleanup risk that differs from their immediate visible cost.

Examples:

- OpenSearch can continue billing if not deleted.
- NAT Gateway or public IPv4 can leak cost.
- CloudWatch logs can grow unexpectedly.
- Athena can scan too much data.
- Textract/Bedrock can scale faster than expected.

### 9.2 Method

Each service gets an escrow, not just a cap.

```json
{
  "service": "textract",
  "allowed": true,
  "service_allocatable_usd": 1800,
  "service_risk_escrow_usd": 250,
  "per_artifact_contract_limit_usd": 40,
  "requires_canary_economics_pass": true,
  "auto_quarantine_conditions": [
    "accepted_artifact_per_usd_below_floor",
    "unknown_cost_growth",
    "policy_terms_uncertain",
    "queue_tail_risk_above_escrow"
  ]
}
```

`service_risk_escrow_usd` is not spendable by that service. It is held to cover tail, cleanup, and ineligible-charge uncertainty.

### 9.3 Service-specific rules

`OpenSearch`:

- use only as a temporary benchmark or retrieval evaluation tool
- require high teardown debt pricing
- require short TTL
- never production dependency
- no retained domain after export

`Textract`:

- use only after cheap extraction fails
- require source-policy pass
- require page count estimate
- stop on OCR confidence/yield failure

`Bedrock batch`:

- public source metadata/candidate classification only
- no request-time factual claims
- no private CSV
- LLM candidate output must enter quarantine until deterministic support exists

`Athena`:

- require partition pruning
- require scan estimate
- require per-query cap
- accepted artifact target required

`CloudWatch`:

- short retention
- log sampling
- metric aggregation
- no verbose page bodies

`NAT/Public IPv4`:

- default forbidden unless explicit exception
- exception must include time-bound deletion recipe

## 10. Smart method 9: Autonomous Operator Silence Mode

### 10.1 Problem

The user wants AWS to continue if Codex/Claude/local terminals are rate-limited or inactive.

But autonomous continuation must not become autonomous runaway.

### 10.2 Method

Add `operator_silence_mode`.

When no external operator heartbeat is present, AWS may continue only if:

```text
run_state in [CANARY, STANDARD_RUN, VALUE_STRETCH, DRAIN, EXPORT_ONLY]
kill_level == 0
control_spend_usd below state limit
spend corridor healthy
service risk escrow healthy
exit bundle fresh
teardown simulation pass
no policy firewall critical failure
```

When silence mode is active, disallow:

- new source families not already approved
- new AWS services not already approved
- OpenSearch creation
- NAT exception creation
- increase to service caps
- manual stretch expansion
- policy overrides

Allowed:

- continue already-approved artifact futures
- renew leases within existing ceilings
- checkpoint and compact
- export accepted artifacts
- drain and teardown
- panic snapshot

### 10.3 Operator return

When a local operator returns, the operator must not directly submit work into AWS. The operator can only:

- inspect ledgers
- request a new artifact future
- request a state transition
- request a stop

The kernel remains the single writer.

## 11. Smart method 10: Zero-Bill Proof Ledger

### 11.1 Problem

Zero-bill teardown cannot rely on "we deleted things" as a narrative. It needs a ledger.

### 11.2 Method

Create `zero_bill_proof_ledger`.

Required records:

```json
{
  "run_id": "aws-credit-2026-05",
  "resource_inventory_started_at": "2026-05-22T00:00:00Z",
  "resource_inventory_finished_at": "2026-05-22T00:20:00Z",
  "tagged_resource_count_before": 642,
  "tagged_resource_count_after": 0,
  "untagged_resource_findings": [],
  "s3_buckets_retained": 0,
  "ecr_repositories_retained": 0,
  "batch_compute_environments_retained": 0,
  "opensearch_domains_retained": 0,
  "cloudwatch_log_groups_retained": 0,
  "eips_retained": 0,
  "nat_gateways_retained": 0,
  "external_exit_bundle_checksum_verified": true,
  "production_smoke_without_aws": "pass",
  "runtime_dependency_firewall": "pass",
  "post_teardown_cost_observation_required": true
}
```

### 11.3 Non-AWS attestation

The final proof bundle must be outside AWS and must include:

- final resource inventory summary
- deletion manifest
- external export checksums
- production smoke without AWS
- runtime dependency scan proving no AWS URLs/S3/env/SDK dependency
- post-teardown cost observation checklist
- list of AWS services that should show zero active resources

No S3 retained archive is allowed if the user requires no further AWS billing.

## 12. Smart method 11: Marginal Value Frontier

### 12.1 Problem

`artifact_value_density` is useful, but it can over-favor easy artifacts and under-favor release-critical work.

### 12.2 Method

Use a frontier, not a single score.

Each artifact future is plotted on dimensions:

- `packet_revenue_linkage`
- `release_criticality`
- `gap_reduction`
- `agent_recommendation_value`
- `freshness_value`
- `reuse_value`
- `policy_safety_value`
- `failure_value`
- `p95_cost`
- `teardown_debt`
- `time_to_accepted_artifact`
- `abort_cost`

The scheduler selects from a Pareto frontier, then applies state-specific weights.

### 12.3 State-specific weights

`CANARY`:

- favor learning, cheap failure, source method validation

`STANDARD_RUN`:

- favor release-critical accepted artifacts and high-value packet gaps

`VALUE_STRETCH`:

- favor short, low-abort-cost, high-reuse artifacts

`DRAIN`:

- favor compaction, export, checksum, teardown ledgers

`EXPORT_ONLY`:

- no source acquisition, no OCR, no Playwright

This prevents a low-cost but non-strategic job from crowding out release-critical work.

## 13. Smart method 12: Credit Exhaustion Without Cash Exposure Protocol

### 13.1 Problem

The user wants to use the credit as close to fully as possible, quickly, but absolutely no further AWS billing.

### 13.2 Method

Use four spend zones:

| Zone | `control_spend_usd` | Allowed behavior |
|---|---:|---|
| `green_market` | `< 17,000` | normal accepted-artifact futures |
| `yellow_selective` | `17,000 - 18,300` | only high-value, canary-proven futures |
| `orange_exit_bias` | `18,300 - 18,900` | short, low-abort, export-friendly futures |
| `red_drain` | `18,900 - 19,300` | no new source expansion; compaction/export/QA/stretch only with kernel approval |
| `closed` | `>= 19,300` | stop all non-cleanup work |

### 13.3 Final stretch catalog

Final stretch work must be pre-approved before launch. Examples:

- proof page compile expansion
- golden agent replay expansion
- source receipt completeness audit
- evidence graph consistency audit
- checksums and external export redundancy
- static bundle compression/validation
- packet fixture expansion for already-accepted sources
- no-hit lease ledger QA
- policy firewall regression suite

Not allowed:

- new source families
- new services
- OpenSearch creation
- wide Playwright crawl
- wide OCR
- broad Athena scans
- storage inflation
- artificial compute burn

## 14. Merge differences for the master plan

These are the exact deltas that should be merged into the execution plan.

### 14.1 Section 18.4 replacement/extension

Extend `AWS artifact factory kernel` with:

- `Accepted Artifact Futures`
- `Spend Corridor Controller`
- `Factory Balance Sheet`
- `Teardown Debt Pricing`
- `Exit-First Artifact Classes`
- `Salvageable Work Units`
- `Failure Value Accounting`
- `Service Risk Escrow`
- `Autonomous Operator Silence Mode`
- `Zero-Bill Proof Ledger`
- `Marginal Value Frontier`
- `Credit Exhaustion Without Cash Exposure Protocol`

### 14.2 Job schema addition

All AWS work must add:

```json
{
  "artifact_future_id": "required",
  "accepted_artifact_contract": "required",
  "target_packet_ids": ["required"],
  "value_points_floor": "required",
  "p95_cost_ceiling_usd": "required",
  "teardown_debt_ceiling_usd": "required",
  "exit_bundle_class": "required",
  "failure_artifact_policy": "required",
  "service_risk_escrow_class": "required",
  "operator_silence_allowed": "required"
}
```

### 14.3 Control formula update

Keep the previous `control_spend_usd` concept, but add:

```text
control_spend_usd =
  observed_spend_usd
  + unsettled_exposure_usd
  + service_tail_risk_usd
  + teardown_debt_usd
  + stale_cost_penalty_usd
  + untagged_resource_penalty_usd
  + ineligible_charge_uncertainty_reserve_usd
  + cleanup_reserve_usd
  + external_export_reserve_usd
  + panic_snapshot_reserve_usd
```

Do not double-count per-job reservation and p95 tail. Use `max(reservation_remaining, p95_remaining)` at job level.

### 14.4 New gates

Add these gates:

| Gate | Name | Blocks |
|---|---|---|
| `AF-1` | accepted artifact future exists | job submission |
| `AF-2` | acceptance tests defined | budget lease |
| `BT-1` | probabilistic lease granted | AWS job launch |
| `TD-1` | teardown debt priced | resource creation |
| `EX-1` | exit bundle class assigned | artifact acceptance |
| `SV-1` | service risk escrow available | service use |
| `OS-1` | operator silence constraints pass | unattended continuation |
| `ZB-1` | zero-bill proof ledger active | run launch |
| `PS-1` | panic snapshot ready | scale-up |
| `CR-1` | spend corridor healthy | new future creation |

### 14.5 Release-plan impact

This review does not change the release sequence. It changes what qualifies as ready to move through it:

- RC1 can still ship early.
- AWS can still self-run.
- AWS can still spend quickly.
- Production remains AWS-independent.
- Zero-bill teardown remains mandatory.

But AWS work is no longer "job complete" until:

```text
accepted artifact contract pass
exit bundle export pass
teardown debt tracked
policy decision pass
zero-bill ledger updated
```

## 15. Contradictions found and resolutions

### 15.1 "Use all credit" vs "no further AWS bill"

Status: resolved by spend corridor plus `USD 19,300` hard control line.

Do not target `USD 19,493.94`. The smarter target is:

```text
maximize accepted artifact value under USD 19,300 control spend
```

### 15.2 "AWS keeps running without local agents" vs "AWS must stop safely"

Status: resolved by `Autonomous Operator Silence Mode`.

AWS may continue without Codex/Claude only inside pre-approved ceilings. It may not invent new services, new source families, or new spend caps while unattended.

### 15.3 "Fast credit burn" vs "valuable product assets"

Status: resolved by `Accepted Artifact Futures`.

Fast spending is allowed only through accepted-artifact contracts. Pure burn is invalid.

### 15.4 "Rolling export" vs "privacy and terms safety"

Status: resolved by exit classes plus Policy Decision Firewall.

Exporting outside AWS does not mean public release. It means preserving accepted artifacts in controlled non-AWS storage after policy classification. Public proof still goes through minimization.

### 15.5 "Service-level caps" vs "high-value stretch"

Status: resolved by Service Risk Escrow.

Stretch can use expensive services only if the service escrow remains intact and canary economics passed.

### 15.6 "Failure artifacts" vs "bad/noisy evidence"

Status: resolved by failure acceptance criteria.

Failed attempts become product value only if they produce structured gap/blocked/retry evidence. Random errors are not accepted artifacts.

### 15.7 "Teardown simulation" vs "quick launch"

Status: resolved by making deletion recipe a creation precondition.

This slightly slows preflight but prevents a larger end-state failure where resources remain billable.

## 16. Implementation notes for the future execution plan

This review does not execute AWS commands. If implemented later, the minimum control-plane objects should be:

- `run_state`
- `artifact_future`
- `budget_lease`
- `service_escrow`
- `resource_liability`
- `artifact_manifest`
- `exit_bundle_manifest`
- `zero_bill_proof_ledger`
- `panic_snapshot_manifest`

Minimal state machine:

```text
PLANNED
PREFLIGHT
CANARY
STANDARD_RUN
VALUE_STRETCH
DRAIN
EXPORT_ONLY
TEARDOWN_SIMULATION
TEARDOWN
POST_TEARDOWN_AUDIT
CLOSED
```

Terminal behavior:

- `DRAIN` and later: no new source acquisition.
- `EXPORT_ONLY` and later: no OCR/render/search expansion.
- `TEARDOWN` and later: no new resource creation.
- `CLOSED`: no AWS control-plane activity remains.

## 17. Final recommendation

Adopt the Round3 cost/factory upgrade.

The smarter version of the AWS plan is:

```text
AWS is not a batch cluster.
AWS is a short-lived artifact market.

Budget leases buy accepted artifact futures.
The kernel chooses futures on a marginal value frontier.
Every future carries teardown debt and exit obligations.
Failures can become structured gap artifacts.
Spend is paced through a corridor, not a dashboard.
Resources are created only if deletion is pre-proven.
Important artifacts exit AWS continuously.
The final state is proven by a zero-bill proof ledger outside AWS.
```

This improves the master plan without changing its core constraints.

No fatal contradictions remain for the AWS factory / cost-control layer if the merge deltas in section 14 are applied.
