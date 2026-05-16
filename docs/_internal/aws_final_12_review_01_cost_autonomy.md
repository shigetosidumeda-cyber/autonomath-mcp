# AWS final 12 review 01: cost autonomy and stop conditions

Date: 2026-05-15
Role: final additional validation 1/12
Scope:

- `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- related `aws_credit_*`, `aws_scope_*`, and `aws_final_*` planning documents

Hard constraint:

- AWS CLI/API/resource creation was not executed.
- This review only writes this new file.
- The target account/profile/region remain planning references only:
  - AWS CLI profile: `bookyou-recovery`
  - AWS account ID: `993693061769`
  - Region: `us-east-1`

## 1. Verdict

Conditional PASS.

The current plan is directionally sound and has already corrected the biggest contradiction:

> Do not try to consume the visible `USD 19,493.94` face value exactly. Treat cash-charge avoidance as the higher-order requirement and stop useful AWS work at an intentional control line of `USD 19,300`.

The self-running design is also basically right:

- EventBridge Scheduler starts/checks the run.
- Step Functions Standard owns auditable run state.
- AWS Batch does bounded worker execution.
- SQS provides backpressure.
- DynamoDB holds the control state.
- Budgets Actions/IAM deny policies provide a backup brake.
- Lambda sentinel / kill switch applies active stop actions.
- The whole AWS run is disposable and ends in zero-bill teardown.

However, the master plan still has one wording-level ambiguity that should be removed before implementation:

> Stoplines must not be interpreted as "visible usage from Cost Explorer/Billing." They must be based on `control_spend_usd`, which includes delayed billing, running exposure, queued exposure, service-cap exposure, stale telemetry penalties, untagged spend penalty, and cleanup reserve.

If that correction is made, the cost/autonomy/zero-bill design is coherent.

## 2. Main contradiction check

### 2.1 `USD 19,493.94` credit versus zero cash billing

Status: resolved, but must stay explicit.

The plan correctly says that exact consumption of `USD 19,493.94` conflicts with "no more AWS charges." The safer statement is:

> Maximize useful artifact generation up to `USD 19,300` control spend, then stop, export, and teardown.

Reason:

- AWS Promotional Credit only offsets eligible fees. Some charges can be ineligible or outside the promotional credit scope.
- Taxes and certain categories, such as Marketplace, some Support, Professional Services, Training, Certifications, Route 53 domain registration/transfer, upfront Savings Plans/Reserved Instances, and other ineligible services are explicitly outside or may be outside promotional credit coverage.
- Billing data is delayed and can be estimated.
- Running and queued work can keep incurring before dashboards reflect it.
- Teardown itself can generate small residual logs/storage/network/control-plane charges.

Recommendation:

- Keep `USD 19,300` as the absolute control line.
- Do not add a "try to use the remaining USD 193.94" phase.
- If the user asks for "just enough to exactly use it," answer that exact burn is incompatible with the zero-cash-bill constraint.

### 2.2 One-week fast spend versus Cost Explorer delay

Status: conditionally coherent.

The one-week goal is possible only if the scheduler does not rely on Cost Explorer as its real-time speedometer.

AWS Cost Explorer data can be delayed; current-period data is generally updated at least daily and can be updated later depending on upstream billing data. Therefore, a one-week burn plan must be governed primarily by local run accounting:

- job reservations
- queue caps
- runtime caps
- item caps
- retry caps
- service allowlists
- launched-resource inventory
- recent burn-rate estimates

Cost Explorer/Budgets should be reconciliation inputs and brake signals, not the only throttle.

Recommendation:

- Rename every "visible usage" stop table in executable specs to `control_spend_usd`.
- Treat Cost Explorer as one input:

```text
control_spend_usd =
  max(
    cost_explorer_unblended_actual_usd,
    budget_actual_or_forecast_usd,
    internal_operator_ledger_usd
  )
  + estimated_running_exposure_usd
  + estimated_queued_exposure_usd
  + estimated_service_cap_exposure_usd
  + stale_cost_penalty_usd
  + untagged_spend_penalty_usd
  + cleanup_reserve_usd
```

### 2.3 AWS self-running versus uncontrolled spend

Status: coherent if the state machine is monotonic.

The plan says AWS should keep running even when Codex/Claude/local CLI are rate-limited. That is correct. The risk is that "self-running" becomes "self-spending."

The current plan has the right pieces, but the implementation should enforce monotonic kill states:

- `K0`: normal
- `K1`: watch, freeze scale-up
- `K2`: slowdown, stop large expensive categories
- `K3`: no-new-work, cancel queued non-critical work
- `K4`: drain/export only
- `K5`: emergency stop, teardown

Once the run enters a higher kill level, it should not automatically downgrade. A downgrade should require a pre-written approval token with expiry and job whitelist, or a new explicit operator action before launch. This keeps unattended AWS running without creating an unattended override loop.

Recommendation:

- Put `kill_level` in DynamoDB as a monotonic integer.
- Use conditional writes so two schedulers cannot race and lower the state.
- Every submitter and every worker checks:

```text
allow_new_work == true
state in {CANARY, RUNNING_STANDARD, WATCH, SLOWDOWN, RUNNING_STRETCH}
kill_level <= allowed_kill_level_for_this_queue
control_spend_usd + job_reserved_usd <= queue_cap_usd
control_spend_usd + job_reserved_usd <= max_control_spend_usd
```

### 2.4 Budget Actions versus kill switch

Status: wording needs tightening.

Budget Actions are useful, but they are not a true hard cap and should not be described as the thing that directly stops every cost source in real time.

AWS Budgets Actions can apply IAM policies, SCPs, or run SSM documents depending on configuration and account setup. They are suitable as a backup deny layer, for example:

- `DenyNewWork`
- `DenyStretchServices`
- `EmergencyDenyCreates`

But the active stop procedure should be the sentinel/kill-switch path:

1. Sentinel observes `control_spend_usd`, drift, stale telemetry, or paid exposure.
2. Sentinel writes `kill_level` and `state` to DynamoDB.
3. Submitters stop creating new jobs.
4. Batch queues are disabled.
5. Queued jobs are cancelled.
6. Running jobs are terminated or bounded-drained.
7. Compute environments are set to zero and then deleted.
8. Export/cleanup proceeds only under cleanup role permissions.

Recommendation:

- Keep Budget Actions as defense-in-depth.
- Do not make Budget Actions the primary controller.
- Do not depend on Budget Actions to invoke arbitrary custom logic unless mediated by an explicit supported route.

### 2.5 Batch queue disable versus actual charge stop

Status: master plan is mostly correct, but implementation must be strict.

Disabling an AWS Batch queue or compute environment does not necessarily stop already running jobs or all charges. AWS Batch documentation warns that disabled compute environments can still incur charges if jobs are still executing or `minvCpus` is non-zero.

Therefore the emergency stop sequence must be:

1. Disable submitters/EventBridge schedules.
2. Disable Batch queues.
3. Cancel `SUBMITTED`, `PENDING`, and `RUNNABLE` jobs.
4. Terminate `STARTING` and `RUNNING` jobs unless they are inside a very short bounded export/cleanup window.
5. Set managed compute environment desired/max/min capacity effectively to zero where supported.
6. Delete compute environments after disassociation from queues.
7. Verify no ECS tasks, EC2 instances, Spot requests, EBS volumes, EIPs, ENIs, NAT Gateways, or Load Balancers remain.

Recommendation:

- The kill switch should have separate modes:
  - `K3_CANCEL_QUEUED`
  - `K4_TERMINATE_RUNNING`
  - `K5_DELETE_COMPUTE`
- `K5` must not rely on "disable only."

### 2.6 Queued exposure

Status: concept is present, but should be made enforceable.

The plan says "queued exposure can exceed USD 19,300" is a stop condition. That is correct, but the implementation must define queued exposure without relying on AWS billing.

Recommended formula:

```text
estimated_queued_exposure_usd =
  sum(
    min(job.max_spend_usd, job.max_runtime_hours * job.max_hourly_cost_usd)
    for every queued or runnable job
  )
```

For array jobs:

```text
array_job_reserved_usd =
  child_count
  * max_child_runtime_hours
  * max_child_hourly_cost_usd
  * retry_multiplier
```

For retry:

```text
retry_multiplier = 1 + max_retries
```

For expensive service jobs:

```text
service_cap_exposure_usd =
  configured_service_batch_cap_usd
  - already_observed_service_spend_usd
```

Recommendation:

- Do not submit any job without `max_spend_usd`, `max_runtime_minutes`, `max_items`, `max_retries`, `queue_id`, `accepted_artifact_target`, and `kill_level_allowed`.
- Make `job_reserved_usd` an atomic debit from a queue token bucket before submission.
- Refund unused reservation to the queue ledger after completion.

## 3. Smarter design proposal

The plan is already strong. The smartest improvement is to turn cost control into a token-bucket scheduler instead of threshold-only monitoring.

### 3.1 Token bucket model

Create DynamoDB rows:

```json
{
  "pk": "run#jpcite-aws-credit-2026-05",
  "sk": "budget#global",
  "max_control_spend_usd": 19300,
  "reserved_usd": 0,
  "observed_usd": 0,
  "cleanup_reserve_usd": 100,
  "stale_penalty_usd": 0,
  "untagged_penalty_usd": 0,
  "allow_new_work": true,
  "kill_level": 0
}
```

Queue buckets:

```json
[
  {
    "queue_id": "control_export_cleanup",
    "cap_usd": 600,
    "hard_stop_line_usd": 19300,
    "survives_until": "TEARDOWN"
  },
  {
    "queue_id": "p0_backbone_receipts",
    "cap_usd": 4300,
    "new_work_stop_line_usd": 18300
  },
  {
    "queue_id": "revenue_sources",
    "cap_usd": 4700,
    "new_work_stop_line_usd": 18900
  },
  {
    "queue_id": "render_ocr_playwright",
    "cap_usd": 3200,
    "new_work_stop_line_usd": 18300
  },
  {
    "queue_id": "qa_graph_proof_geo",
    "cap_usd": 2600,
    "new_work_stop_line_usd": 18900
  },
  {
    "queue_id": "stretch_preapproved_only",
    "cap_usd": 2500,
    "new_work_stop_line_usd": 19300
  },
  {
    "queue_id": "misc_reserve",
    "cap_usd": 1400,
    "new_work_stop_line_usd": 18300
  }
]
```

The exact allocation can change, but the invariant should not:

```text
sum(queue_cap_usd) <= 19300 - cleanup_reserve_usd
```

This is safer than "spend fast until dashboard approaches 19,300."

### 3.2 Atomic submit gate

Before a job is submitted:

1. Read global state.
2. Read queue state.
3. Compute `job_reserved_usd`.
4. Conditional-write:

```text
global.reserved_usd + global.observed_usd + global.penalties + job_reserved_usd
  <= global.max_control_spend_usd

queue.reserved_usd + queue.observed_usd + job_reserved_usd
  <= queue.cap_usd

kill_level <= job.kill_level_allowed
allow_new_work == true
```

If the conditional write fails, the job is not submitted.

This gives AWS autonomous execution without letting queued work outrun the credit.

### 3.3 Spend pace controller

To consume credit quickly without overshooting:

```text
target_control_spend_by_day:
Day 0:   300
Day 1:  3500
Day 2:  7500
Day 3: 11500
Day 4: 15000
Day 5: 17300
Day 6: 18900
Day 7: 19300 max, export/teardown
```

If actual control spend is below target:

- expand only pre-approved, high-yield source families
- increase shard count, not per-job blast radius
- prefer artifact-generation jobs with known output targets
- avoid new terms-risk sources just to burn spend

If actual control spend is above target:

- reduce render/OCR/OpenSearch/large Athena first
- preserve QA/export/control queues
- never accelerate after `NO_NEW_WORK`

### 3.4 Small shards over huge jobs

Fast spend should come from many bounded shards, not a few unbounded jobs.

Recommended per-job limits:

| Job class | Max runtime | Max reserved USD | Max retries |
|---|---:|---:|---:|
| source profile/API/bulk fetch | 15-30 min | 5-20 | 1 |
| normal public HTML/PDF fetch | 15-30 min | 10-30 | 1 |
| Playwright render | 10-20 min | 15-40 | 1 |
| OCR/Textract feeder | 15-30 min | 25-75 | 0-1 |
| proof/packet generation | 15-30 min | 5-25 | 1 |
| OpenSearch benchmark | 1-2 h | 100-300 | 0 |
| final export/checksum | 1-2 h | 20-100 | 1 |

This makes emergency stop meaningful.

### 3.5 Pre-approved stretch token

Because Codex/Claude may be unavailable, the stretch decision must be made before launch.

Control table field:

```json
{
  "preapproved_manual_stretch": true,
  "stretch_token_id": "stretch-2026-05-jpcite-v1",
  "stretch_token_expires_at": "2026-05-22T00:00:00Z",
  "stretch_allowed_queues": [
    "qa_graph_proof_geo",
    "stretch_preapproved_only"
  ],
  "stretch_forbidden_services": [
    "Marketplace",
    "Support",
    "Route53Domains",
    "SavingsPlans",
    "ReservedInstances"
  ],
  "stretch_max_reserved_usd": 2500,
  "stretch_max_single_job_usd": 100
}
```

Stretch should only run if:

- `external_export_gate_passed=true`
- `control_spend_usd < 19300`
- Cost data stale < 60 minutes, or local ledger confidence is high and service inventory is clean
- paid exposure = 0
- untagged spend = 0 or explained
- accepted artifact yield remains positive
- every stretch job is under 2 hours and can be killed

If any condition fails, automatic state becomes `DRAIN`.

## 4. Revised stopline behavior

Use `control_spend_usd`, not visible spend.

| Line | Control spend | State | Required automatic behavior |
|---|---:|---|---|
| Canary | 100-300 | `CANARY` | no scale, prove tagging/cost/kill/export |
| Watch | 17,000 | `WATCH` | freeze scale-up, stop low-yield, shrink render/OCR |
| Slowdown | 18,300 | `SLOWDOWN` | stop new expensive categories, finish only high-yield bounded jobs |
| No-new-work | 18,900 | `NO_NEW_WORK` | no new source/render/OCR jobs, cancel noncritical queued work |
| Stretch | 18,900-19,300 | `RUNNING_STRETCH` or `DRAIN` | only preapproved, bounded, high-yield jobs |
| Safety | 19,300 | `TEARDOWN` | deny creates, stop submitters, cancel/terminate compute, export/check/delete |

Additional immediate `DRAIN` or `TEARDOWN` triggers:

- Cost Explorer/Budgets unavailable beyond configured stale threshold
- Cost data stale > 12 hours
- untagged spend unexplained for 30 minutes
- paid exposure >= USD 25
- paid exposure >= USD 100: emergency
- unexpected service spend > USD 100
- any ineligible-service spend appears
- cleanup dry-run cannot enumerate resources
- `external_export_gate_passed=false` after full-run deadline
- source terms/robots gate turns blocked
- private data leak signal
- AWS resource inventory does not match tagged ledger

## 5. Zero-bill teardown validation

Status: coherent, with one implementation guard.

The master plan correctly says S3 must not remain if zero ongoing AWS bill is required. It also correctly says AWS is not a production runtime dependency.

Implementation guard:

- Do not delete the cleanup/control role too early.
- Emergency deny policies must block creation and expensive execution, but must not block list/delete/tag-read/export-verification operations needed for cleanup.
- The cleanup role should be explicitly exempted from create-deny policies only for deletion/list/read operations.

Zero-bill teardown should be declared complete only after:

1. `external_export_gate_passed=true`
2. checksum manifest verified outside AWS
3. production smoke passes with `runtime.aws_dependency.allowed=false`
4. all tagged resources deleted
5. untagged resource inventory checked for common residuals
6. Cost Explorer/Billing checked same day, next day, 3 days later, and month-end
7. no S3 buckets, object versions, multipart uploads, ECR repos, CloudWatch logs, OpenSearch domains, NAT Gateways, EIPs, EBS volumes/snapshots, Batch compute environments, Step Functions, EventBridge schedules, Lambda functions, SQS queues, or DynamoDB control tables remain for the run

## 6. Direct improvement requests for the master plan

These are not edits made here, but should be applied before implementation.

1. Replace "Visible usage" in the master stopline table with `control_spend_usd`.
2. Add the token-bucket scheduler as the execution primitive.
3. Require atomic budget reservation before every job submission.
4. Make `kill_level` monotonic and not self-downgradable.
5. Split Budget Actions from kill switch responsibility:
   - Budget Actions: IAM/SCP/SSM backup brake.
   - Sentinel/kill switch: active stop/drain/delete orchestration.
6. Add `run_deadline_at` and `teardown_deadline_at` to the control table.
7. Add `job_reserved_usd` and `reservation_refund_usd` to every job manifest.
8. Add `queue_cap_usd` and `queue_new_work_stop_line_usd` to every queue manifest.
9. Require per-job `accepted_artifact_target`; no target means no spend.
10. Treat Cost Explorer stale telemetry as a spend penalty, not as missing data to ignore.
11. Treat AWS Batch disable as insufficient; K5 must terminate/delete compute.
12. Keep cleanup permissions available after emergency deny is applied.

## 7. Final answer to the validation question

There is no fatal contradiction if the plan is implemented as a control-spend/token-reservation system.

The current plan is already close. The smarter final form is:

1. Do not run AWS based on dashboard spend.
2. Pre-allocate the `USD 19,300` control budget into queue token buckets.
3. Reserve cost before every job submission.
4. Keep jobs small and killable.
5. Let AWS self-run through EventBridge/Step Functions/Batch only while the control table allows it.
6. Use Budget Actions as a backup brake, not the steering wheel.
7. Stop new work at `18,900` unless a preapproved stretch token exists.
8. At `19,300` control spend, terminate compute and shift to export/teardown.
9. Export outside AWS and delete S3/all run resources.
10. Verify zero-bill after teardown on same day, next day, 3 days later, and month-end.

This gives the user what they want: fast credit value conversion in roughly one week, AWS continuing without Codex/Claude being active, and a disciplined stop path that avoids ongoing AWS billing.

## 8. Addendum: smarter method/function/design review

追加指摘を反映する。

ここで検証すべき「スマート」は、実行順ではなく、AWSをどう賢く制御し、どう成果物価値を最大化し、どう現金請求を避けるかである。

結論:

> 最もスマートな方法は、AWS Batchを単なる大量実行基盤として扱わず、`budget token market + P95 cost forecast + artifact value density scheduler + monotonic kill switch` として動かすことである。

この方式なら、Codex/Claudeが止まってもAWSは自走し、ただし価値の低いジョブ・請求リスクが高いジョブ・停止しづらいジョブは自動的に落とせる。

### 8.1 Four-ledger cost brain

単一の請求数字を信じない。

AWS制御面は、少なくとも4つの台帳を持つべきである。

| Ledger | 役割 | 信頼性 | 更新頻度 |
|---|---|---|---|
| `billing_ledger` | Cost Explorer / Budgets actual/forecast | 遅いが公式 | 15-60分poll、ただしデータ自体は遅延前提 |
| `reservation_ledger` | submit前に確保したjob予算 | 速い | job submit/finishごと |
| `resource_ledger` | 実在するAWS resource inventory | 中程度 | 5-15分ごと |
| `artifact_value_ledger` | accepted artifact / packet価値 / coverage増分 | 速い | artifact生成ごと |

停止判定は次を使う。

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

重要:

- `billing_ledger`は遅いため、操舵ではなく監査寄り。
- `reservation_ledger`がリアルタイム制御の主役。
- `resource_ledger`は「請求されうる実体が残っているか」を見る。
- `artifact_value_ledger`は「使った分が価値に変わっているか」を見る。

### 8.2 P95 cost-to-complete forecast

ジョブごとに、平均ではなくP95の完了コストで制御する。

```text
p95_job_cost_to_complete =
  max(
    job_reserved_usd_remaining,
    observed_hourly_burn_rate_p95 * remaining_runtime_hours_p95,
    unit_cost_p95 * remaining_items_p95
  )
```

ジョブタイプ別の予測入力:

| Job type | Primary predictor |
|---|---|
| API/bulk fetch | item count, response size, retry rate |
| HTML/PDF fetch | item count, bytes, source throttle |
| Playwright | pages, render seconds, screenshot count |
| OCR/Textract | page count, document class, retry count |
| Athena/Glue | scanned bytes, partition pruning ratio |
| OpenSearch benchmark | node-hours, index size, query rounds |
| proof/packet generation | artifact count, validation failures |
| export/checksum | bytes, object count, retry rate |

平均値で動かすと、数個の重いジョブで超過する。P95で制御すれば、19,300線に近づいても止めやすい。

### 8.3 Artifact value density scheduler

「AWSクレジットを使う」ではなく「1ドルあたりの将来売上・GEO価値が高い成果物から買う」と考える。

各ジョブに価値密度を付ける。

```text
artifact_value_density =
  (
    paid_packet_revenue_weight
    * source_coverage_gain
    * proof_reusability_score
    * geo_discovery_gain
    * uniqueness_score
    * freshness_score
    * quality_pass_probability
    * terms_confidence
  )
  / p95_cost_to_complete_usd
```

推奨の重み:

| Factor | Meaning | Suggested weight |
|---|---|---:|
| `paid_packet_revenue_weight` | 有料packetに直結するか | 3.0 |
| `source_coverage_gain` | 未カバーsource familyを埋めるか | 2.0 |
| `proof_reusability_score` | 複数packet/proofで使い回せるか | 2.0 |
| `geo_discovery_gain` | AI agentが推薦しやすくなるか | 1.5 |
| `uniqueness_score` | 他で簡単に得られないか | 1.5 |
| `freshness_score` | 更新価値があるか | 1.0 |
| `quality_pass_probability` | gate通過見込み | multiplier |
| `terms_confidence` | terms/robots安全性 | multiplier |

キュー投入ルール:

```text
submit if:
  artifact_value_density >= threshold_for_current_state
  and p95_cost_to_complete_usd <= remaining_queue_tokens
  and accepted_artifact_target is not null
```

状態が進むほどthresholdを上げる。

| State | Value threshold behavior |
|---|---|
| `RUNNING_STANDARD` | 中程度でも許可 |
| `WATCH` | 低密度ジョブ停止 |
| `SLOWDOWN` | 高密度だけ継続 |
| `NO_NEW_WORK` | 新規投入なし |
| `RUNNING_STRETCH` | 最高密度・短時間・低リスクだけ |

### 8.4 Queue allocation as a portfolio

固定順ではなく、portfolioとして予算を配る。

初期配分例:

| Bucket | Cap | Rationale |
|---|---:|---|
| control/export/cleanup | 600 | 止める・退避するための予算 |
| P0 identity/law/source backbone | 4,300 | 全packetの土台 |
| revenue-first sources | 4,700 | 補助金、取引先、許認可、行政処分、調達 |
| Playwright/OCR/Textract | 3,200 | APIで取れない公開一次情報 |
| QA/graph/proof/GEO | 2,600 | 売れる形・agent推薦形へ変換 |
| stretch preapproved | 2,500 | 価値密度が高い追加分 |
| misc/risk reserve | 1,200 | 予測外・cleanup・ログ等 |

合計: `USD 19,100`

残り約`USD 200`は、クレジット額面との差分だけでなく、現金請求回避の最終バッファとして扱う。

より賢い点:

- 低価値な広域収集が高価値なproof/packet生成を食いつぶさない。
- OCR/renderのような高コスト系に上限がある。
- 退避/cleanup予算を最初から確保する。
- stretchは「余ったから使う」ではなく「価値密度が高いものだけに使う」。

### 8.5 Dynamic rebalancing

固定capだけではもったいない。毎時、使われていないbucketを再配分する。

再配分ルール:

```text
if bucket.accepted_artifact_yield < floor for 2 windows:
  freeze bucket
  move 50% of remaining tokens to reserve

if bucket.value_density_p50 > global.value_density_p75
  and terms_confidence == high
  and kill_level <= K1:
    grant extra tokens from reserve

if state >= SLOWDOWN:
  only transfer tokens to qa/proof/export or short high-density jobs
```

これにより、「計画したからそのsourceに使う」のではなく、「成果物に変わっているsourceへ寄せる」設計になる。

### 8.6 Smart spend pacing

1週間で使うには、急ぎつつも過走しない制御が必要。

単純な日別順序ではなく、pace errorで制御する。

```text
pace_error = target_control_spend_now - control_spend_usd
```

制御:

| Condition | Action |
|---|---|
| `pace_error > 3000` | high-density safe queuesの並列を増やす |
| `pace_error 1000-3000` | normal safe expansion |
| `pace_error -1000 to 1000` | keep steady |
| `pace_error < -1000` | expensive queuesを止める |
| `pace_error < -2000` | force WATCH/SLOWDOWN early |

ただし、paceが遅くても次は禁止:

- terms未確認sourceを広げる
- private CSVをAWSへ入れる
- Marketplace/Support/RI/Savings Plans/upfront系へ使う
- NAT Gateway常設
- 長時間OpenSearch放置
- 大きなAthena full scanを雑に回す

### 8.7 Source-aware circuit breakers

sourceごとに回路遮断を持つ。

```json
{
  "source_id": "example-official-source",
  "allowed_methods": ["api", "bulk", "html", "playwright"],
  "max_requests_per_hour": 120,
  "max_render_jobs_per_hour": 20,
  "max_ocr_pages": 5000,
  "terms_status": "pass",
  "robots_status": "pass",
  "failure_rate_trip": 0.2,
  "http_429_trip": 5,
  "http_403_trip": 1,
  "manual_review_required": false
}
```

遮断条件:

- 403
- repeated 429
- CAPTCHA/login/bot challenge
- robots/terms drift
- OCR confidence collapse
- duplicate/no-new-information ratio too high
- artifact gate fail rate too high

遮断後は、そのsourceの残予算を回収して別bucketへ戻す。

### 8.8 Checkpoint-first workers

停止しやすさを上げるには、workerを「途中成果物を残す」設計にする。

各worker:

- shard開始時にmanifestを書く
- N件ごとにcheckpointを書く
- source receipt候補を小分けでS3 stagingへ出す
- kill signalを見たら現在itemだけ完了して終了
- unfinished shardは再キュー可能にする
- partial artifactでも`candidate`として価値化できるようにする

これにより、K3/K4で止めても「全部無駄」にならない。

### 8.9 Billing avoidance guardrails

より賢い請求回避は、監視より前に「使えない構成」を作ること。

Preflightで固定すべきdeny:

- allowed regionは原則`us-east-1`だけ
- Marketplace禁止
- Support plan変更禁止
- Savings Plans / RI購入禁止
- Route53 domain registration/transfer禁止
- NAT Gateway作成はdenyまたはmanual exception
- EIP作成はdenyまたはTTL付き
- Load Balancer作成は原則deny
- OpenSearchはTTL/最大node-hours必須
- CloudWatch Logs retention必須
- S3 lifecycleは必須、ただし最終的にはbucket削除
- required tagsなしのcreateは禁止
- run tagがないresourceは即incident

Budget Actionsはこれらの後段に置く。最初から作れない方が強い。

### 8.10 Cost Explorer polling cost

Cost Explorer API自体にも課金がある。高頻度pollは避ける。

推奨:

- internal ledger: 1-5分ごと
- resource inventory: 5-15分ごと
- Cost Explorer API: 15-60分ごと、ページ数上限あり
- Budget status/action history: 15-60分ごと
- emergency時だけ追加poll

これで、請求監視そのものがノイズになることを避ける。

### 8.11 Smart residual allocator

`USD 18,900`以降は「残額を使う」のではなく「残余リスク内で価値密度最高の短命jobだけ買う」。

残余計算:

```text
safe_residual_usd =
  19300
  - control_spend_usd
  - p95_running_cost_to_complete
  - p95_queued_cost_to_complete
  - cleanup_reserve
```

stretch job条件:

```text
job_reserved_usd <= min(100, safe_residual_usd * 0.25)
job_max_runtime_minutes <= 60
artifact_value_density >= stretch_threshold
abort_cost_usd <= 10
terms_confidence == high
quality_pass_probability >= 0.8
```

これなら、最後の数百ドルを雑に消化するのではなく、請求リスクを増やさず価値に変えやすい。

### 8.12 Artifact value maximization loop

価値最大化は、収集量ではなくaccepted artifactで見る。

毎時出すべき指標:

| Metric | Meaning |
|---|---|
| `accepted_artifacts_per_usd` | 1ドルあたり本体投入可能な成果物 |
| `paid_packet_coverage_gain_per_usd` | 有料packetのcoverage増分 |
| `proof_pages_generated_per_usd` | proof/GEO表面の増分 |
| `source_family_gap_closed_per_usd` | gapを閉じた効率 |
| `no_hit_ledger_quality_per_usd` | no-hitの安全性向上 |
| `rejected_artifacts_per_usd` | 無駄打ち率 |
| `manual_review_queue_growth` | human review詰まり |

停止/移管:

```text
if rejected_artifacts_per_usd rises
  or manual_review_queue_growth rises
  or accepted_artifacts_per_usd falls:
    freeze that source/queue
    move tokens to QA/proof/export or better source family
```

### 8.13 Better than the current plan

現在の計画に足すべき「よりスマートな機能」は次である。

1. `control_spend_usd`を唯一の停止指標にする。
2. Token bucketでsubmit前に予算を予約する。
3. P95 cost-to-completeでrunning/queued exposureを見る。
4. Artifact value densityでキュー優先度を決める。
5. 毎時のdynamic rebalancingで低価値bucketから高価値bucketへ移す。
6. Source-aware circuit breakerで無駄なfetch/render/OCRを止める。
7. Checkpoint-first workerで途中停止しても成果物候補を残す。
8. Smart residual allocatorで終盤のstretchを小さく高密度にする。
9. Billing avoidance guardrailsをpreflightで作り、Budget Actionsは二重ブレーキにする。
10. Cost Explorer APIは低頻度にし、内部台帳を主制御にする。

この10点を入れると、「順番が良い計画」から「AWSが自律的に価値密度を見て、賢くクレジットを成果物へ変換し、危険になったら自分で止まる計画」になる。

## 9. Official references checked

- AWS Promotional Credit terms: https://aws.amazon.com/awscredits/
- AWS Budgets Actions: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html
- AWS Budgets Action API: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_Action.html
- AWS Cost Explorer overview / refresh timing: https://docs.aws.amazon.com/console/billing/costexplorer
- AWS Cost Explorer `GetCostAndUsage`: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
- EventBridge Scheduler overview: https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html
- EventBridge Scheduler starting Step Functions: https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html
- AWS Batch compute environments: https://docs.aws.amazon.com/batch/latest/userguide/compute_environments.html
- AWS Batch update compute environment behavior: https://docs.aws.amazon.com/batch/latest/APIReference/API_UpdateComputeEnvironment.html
