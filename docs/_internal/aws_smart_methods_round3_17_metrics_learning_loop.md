# Round3 追加スマート化 17/20: Metrics / Learning Loop

Date: 2026-05-15

Scope: Privacy-Preserving Product Telemetry, Golden Agent Session Replay, Canary Economics, Source Quality Learning

AWS: No AWS CLI/API/resource operation was executed.

Output file: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_17_metrics_learning_loop.md`

---

## 0. Executive Conclusion

Round3までの計画は、以下の部品をすでに持っている。

- `Privacy-Preserving Product Telemetry`
- `Golden Agent Session Replay v2`
- `Canary Economics`
- `Public Corpus Yield Compiler`
- `Source OS`
- `Outcome Contract Catalog`
- `Release Capsule`
- `Policy Decision Firewall`
- `JPCIR`

しかし、これらを横断して「AIが安全に学習し、次の改善を自動で決める」ための制御面は、まだ独立した実行単位として弱い。

追加採用すべき最上位機能は次である。

> `Privacy-Safe Learning Control Plane`

これは、raw prompt、raw CSV、private fact、raw source body、screenshot/OCR全文を保存せずに、サービス改善・価格改善・source優先度改善を行うための機械可読な学習制御面である。

この制御面は、以下の4つを束ねる。

1. `Telemetry Event Allowlist`
2. `Metric Contract Registry`
3. `Learning Proposal Engine`
4. `Autonomous Improvement Gate`

AIはこの4つを通じて、改善案を生成し、影響を評価し、release capsule候補へ反映し、Golden Agent Session Replayで検証し、条件を満たす場合だけ次の実装へ進む。

---

## 1. Design Goal

### 1.1 What this solves

jpciteは、AIエージェント向けに公的一次情報ベースの成果物を売るサービスである。

本番後に改善したい対象は多い。

- どの成果物がAI agentに推薦されやすいか
- どの成果物が実際に買われるか
- どの価格帯で止まるか
- どのknown gapが購入を妨げるか
- どのsourceを取ると有料成果物のcoverageが上がるか
- どのproof pageがagentに理解されやすいか
- どのno-hit表現が誤解されにくいか
- どのpacket bundleが最安十分になりやすいか
- どのsource取得方法がAWS費用対効果に優れるか
- どのrelease capsuleが推薦品質を落とすか

ただし、学習のために以下を保存してはいけない。

- raw user prompt
- raw CSV
- CSV row
- user/company-specific sensitive private fact
- raw packet payload
- raw source body
- raw screenshot body/text
- HAR body
- auth header/cookie
- LLM chain-of-thought
- legal/professional advice outcome label

したがって、jpciteの学習ループは「行動ログ」ではなく「許可された意思決定イベントと集計metric」のみで回す必要がある。

### 1.2 Core principle

> Learn from decisions, not from private content.

記録するのは、ユーザーやAI agentの生データではなく、以下のような状態遷移である。

- どのtask_familyとして分類されたか
- どのoutcome contractが候補になったか
- 最安十分routeは何だったか
- 高いtierを却下したか
- どのknown gapが購入前に出たか
- 購入/不購入/blocked/expiredのどれだったか
- accepted artifactが生成されたか
- Golden Replayで推薦が正しかったか
- source canaryの費用対効果はどうだったか
- release capsule候補がmetric gateを通ったか

---

## 2. New Smart Method: `Privacy-Safe Learning Control Plane`

### 2.1 Definition

`Privacy-Safe Learning Control Plane` is the machine-readable metrics and feedback layer that lets AI improve jpcite without storing private content.

It owns:

- telemetry event schemas
- metric definitions
- aggregation rules
- suppression rules
- learning proposal format
- automatic improvement gates
- rollback triggers
- source priority updates
- pricing/package experiments
- Golden Agent Session Replay update proposals

It does not own:

- raw user text
- raw CSV parsing
- source crawling execution
- packet generation itself
- billing itself
- production activation itself

### 2.2 Position in Evidence Product OS

```text
Demand Plane
  -> privacy-safe telemetry events
  -> Learning Control Plane
  -> improvement proposals

Evidence Plane
  -> source quality metrics
  -> Learning Control Plane
  -> source priority updates

Compilation Plane
  -> packet compiler metrics
  -> Learning Control Plane
  -> compiler/package/preview changes

Release Plane
  -> Golden Replay + capsule metrics
  -> Learning Control Plane
  -> release allow/block/downgrade

Build Loop on AWS
  -> canary economics + yield metrics
  -> Learning Control Plane
  -> budget token allocation suggestions
```

### 2.3 Why this is smarter

Without this layer, the plan has many useful metrics but no single safe loop to act on them.

With this layer:

- product packaging improves based on purchase decisions, not private prompts
- pricing improves based on accepted artifact economics, not guesswork
- source priority improves based on packet impact, not source volume
- Golden Replay expands from observed decision failures
- AWS spend is reallocated toward high-yield source/method pairs
- release capsules can be rejected due to recommendation regression
- AI can execute improvements under explicit policy and metric gates

---

## 3. Privacy Boundary

### 3.1 Allowed telemetry classes

Only these telemetry classes are allowed.

| Class | Allowed examples | Notes |
| --- | --- | --- |
| `decision_event` | route selected, preview shown, cap accepted, packet skipped | No raw prompt |
| `product_metric` | conversion by task_family, tier acceptance, gap blocker rate | Aggregated |
| `source_metric` | accepted artifacts, source receipt yield, canary cost | Public-source only |
| `compiler_metric` | claim support coverage, proof minimality, known gap count | No raw source text |
| `agent_eval_metric` | Golden Replay pass/fail, forbidden wording hit | Synthetic or redacted sessions |
| `billing_metric` | accepted artifact billed, void reason, cap utilization | No payment details |
| `release_metric` | capsule activation pass/fail, rollback event, drift block | No packet payload |
| `aws_factory_metric` | budget token used, p95 exposure, yield per dollar | No AWS credentials |

### 3.2 Forbidden telemetry classes

The following are release blockers.

| Forbidden class | Reason |
| --- | --- |
| `raw_prompt` | may contain private facts |
| `raw_csv` | explicitly prohibited |
| `csv_row` | row-level private data |
| `private_fact_value` | can re-identify user/business |
| `raw_packet_payload` | may contain user inputs and paid output |
| `raw_source_body` | terms/copyright/privacy risk |
| `raw_screenshot_text` | may include personal or source-restricted content |
| `har_body` | cookie/auth/body leakage risk |
| `legal_outcome_label` | can imply unauthorized legal judgment |
| `trust_score_label` | conflicts with no credit/safety judgment |

### 3.3 Suppression rules

All aggregate metrics must pass the suppression lattice.

```json
{
  "schema_id": "jpcite.telemetry_suppression_policy.v1",
  "k_min_default": 20,
  "k_min_counterparty": 50,
  "k_min_sensitive_task": 100,
  "min_distinct_tenants": 5,
  "min_distinct_days": 3,
  "dominance_threshold_max_share": 0.40,
  "delta_release_min_group_size": 30,
  "forbid_single_tenant_slice": true,
  "forbid_raw_values": true,
  "forbid_free_text_dimensions": true
}
```

For internal AI improvement, non-public aggregates may use smaller thresholds only if:

- no raw/private value is present
- tenant IDs are salted and rotated
- output is not shown in public proof/API/MCP
- proposal cannot target a named customer
- audit record marks `internal_only=true`

---

## 4. Machine-Readable Metrics Model

### 4.1 Metric contract

Every metric must have a contract.

```json
{
  "schema_id": "jpcite.metric_contract.v1",
  "metric_id": "conversion.preview_to_paid.by_task_family",
  "owner_plane": "Demand Plane",
  "purpose": "Detect which task families need packaging or price improvements.",
  "unit": "ratio",
  "dimensions_allowlist": [
    "task_family",
    "outcome_contract_id",
    "cheapest_sufficient_tier",
    "agent_surface",
    "budget_sensitivity_bucket",
    "known_gap_bucket",
    "release_capsule_id"
  ],
  "forbidden_dimensions": [
    "raw_prompt",
    "company_name",
    "customer_id",
    "csv_column_value",
    "free_text"
  ],
  "aggregation_window": "daily",
  "suppression_policy_id": "telemetry_suppression_policy.v1",
  "allowed_consumers": [
    "learning_proposal_engine",
    "pricing_optimizer",
    "source_priority_optimizer",
    "release_gate"
  ],
  "release_blocker_if_missing": false,
  "privacy_review_required": false
}
```

### 4.2 Telemetry event envelope

Every event uses a strict envelope.

```json
{
  "schema_id": "jpcite.telemetry_event.v1",
  "event_id": "evt_01J...",
  "occurred_at": "2026-05-15T09:00:00Z",
  "release_capsule_id": "rc_20260515_001",
  "agent_surface": "mcp | openapi | llms_txt | well_known | proof_page | web",
  "event_type": "preview_decision",
  "privacy_class": "decision_event",
  "task_family": "vendor_check",
  "outcome_contract_id": "company_public_baseline_v1",
  "packet_ids": [
    "company_public_baseline"
  ],
  "decision_state": "recommended | skipped | blocked | approved | executed | completed",
  "safe_dimensions": {
    "budget_sensitivity_bucket": "cheapest",
    "jurisdiction_bucket": "prefecture_level",
    "data_available_bucket": "corporate_number_present",
    "risk_level_bucket": "medium"
  },
  "metric_values": {
    "preview_price_cap_jpy": 330,
    "known_gap_count": 2,
    "coverage_ladder_level": 1
  },
  "privacy_guards": {
    "raw_prompt_stored": false,
    "raw_csv_stored": false,
    "raw_packet_payload_stored": false,
    "raw_source_body_stored": false,
    "tenant_reversible_id_stored": false
  }
}
```

### 4.3 Learning dataset manifest

Aggregates are compiled into a learning dataset. The dataset is not raw logs.

```json
{
  "schema_id": "jpcite.learning_dataset_manifest.v1",
  "dataset_id": "learn_20260515_demand_p0",
  "window": {
    "start": "2026-05-15",
    "end": "2026-05-16"
  },
  "input_event_classes": [
    "decision_event",
    "product_metric",
    "source_metric",
    "agent_eval_metric"
  ],
  "raw_event_retention": "ephemeral_or_none",
  "aggregation_level": "task_family_x_contract_x_capsule",
  "suppression_policy_id": "telemetry_suppression_policy.v1",
  "suppression_report": {
    "rows_in": 1842,
    "rows_suppressed": 317,
    "dominance_suppressed": 12,
    "single_tenant_suppressed": 41
  },
  "allowed_actions": [
    "propose_price_change",
    "propose_source_priority_change",
    "propose_golden_session",
    "propose_copy_change",
    "propose_packet_bundle"
  ],
  "forbidden_actions": [
    "target_named_user",
    "infer_private_attribute",
    "change_legal_disclaimer",
    "change_policy_gate",
    "increase_autopay_cap_without_explicit_policy"
  ]
}
```

---

## 5. Product Learning Loop

### 5.1 Purpose

Improve service packaging and end-user conversion without storing private user prompts.

### 5.2 Inputs

- `preview_decision`
- `route_selected`
- `cap_accepted`
- `purchase_skipped`
- `accepted_artifact_completed`
- `void_or_refund_reason`
- `known_gap_disclosed`
- `agent_recommendation_card_rendered`
- Golden Replay failures

### 5.3 Product metrics

| Metric | Meaning | Smart action |
| --- | --- | --- |
| `preview_to_paid_rate` | previewから有料実行へ進む率 | product/price改善 |
| `agent_recommendation_acceptance_rate` | agent推薦後に承認された率 | recommendation card改善 |
| `cheapest_route_sufficiency_rate` | 最安tierで十分だった率 | tier再設計 |
| `buy_up_justification_success_rate` | 高tierの理由が承認された率 | coverage ladder改善 |
| `gap_blocker_rate` | known gapで購入停止した率 | source優先度へ送る |
| `void_rate_by_contract` | 課金void率 | packet contract修正 |
| `accepted_artifact_rate` | 実行が受入成果物に到達した率 | composer/source改善 |
| `bundle_savings_acceptance_rate` | bundle提案の承認率 | workflow kit改善 |
| `watch_conversion_rate` | 単発からwatchへ移行した率 | watch product強化 |
| `preview_confusion_rate` | preview後の非推薦/脱落率 | copy/surface改善 |

### 5.4 Product learning proposal

```json
{
  "schema_id": "jpcite.learning_proposal.product.v1",
  "proposal_id": "lp_prod_20260515_001",
  "proposal_type": "price_packaging_change",
  "target": {
    "outcome_contract_id": "company_public_baseline_v1",
    "tier": "starter_330"
  },
  "observed_metrics": {
    "preview_to_paid_rate": 0.18,
    "gap_blocker_rate": 0.41,
    "cheapest_route_sufficiency_rate": 0.77,
    "void_rate_by_contract": 0.03
  },
  "hypothesis": "Users accept starter tier when no additional region-specific gap is present; gap disclosure is causing skips for prefecture-level tasks.",
  "proposed_change": {
    "change_type": "add_coverage_ladder_explanation",
    "new_preview_field": "what_extra_tier_adds",
    "do_not_change_base_price": true
  },
  "expected_impact": {
    "preview_to_paid_rate_delta": 0.04,
    "refund_risk_delta": 0.00,
    "policy_risk_delta": 0.00
  },
  "privacy_report": {
    "raw_prompt_used": false,
    "raw_csv_used": false,
    "min_group_size": 52,
    "dominance_passed": true
  },
  "required_gates": [
    "golden_agent_replay",
    "pricing_matrix_consistency",
    "policy_decision_firewall",
    "surface_parity"
  ],
  "auto_apply_allowed": true,
  "auto_apply_scope": "release_capsule_candidate_only"
}
```

### 5.5 Auto-apply rules

AI may auto-apply product improvements only if all conditions hold.

- The change modifies packaging, explanation, ordering, or preview fields only.
- No legal disclaimer is weakened.
- No no-hit language is changed except through approved language pack.
- No price increase is applied without explicit `pricing_policy.auto_increase_allowed=true`.
- No cap/autopay limit is increased.
- Golden Replay does not regress.
- The proposal is applied to a release capsule candidate, not directly to active production.

---

## 6. Pricing Learning Loop

### 6.1 Purpose

Improve revenue while preserving the user promise: cheap, sufficient, evidence-backed outputs.

### 6.2 Inputs

- preview price cap
- cap acceptance
- paid execution result
- accepted artifact count
- void/refund reason
- receipt reuse
- source cost contribution
- tier selected
- tier rejected
- workflow bundle selected

### 6.3 Pricing metrics

| Metric | Meaning |
| --- | --- |
| `cap_acceptance_rate` | price cap承認率 |
| `price_skip_rate` | price理由でskipした率 |
| `accepted_artifact_margin_proxy` | accepted artifact単位の粗利proxy |
| `receipt_reuse_dividend_rate` | receipt再利用による原価低下 |
| `tier_buyup_rate` | 高tierへの移行率 |
| `overbuy_regret_signal` | 高tier後に追加価値が薄かった兆候 |
| `underbuy_gap_signal` | 安tier後にgapが残って不満になった兆候 |
| `watch_retention_proxy` | watch継続意向proxy |
| `void_cost_rate` | void/failedにかかった実行コスト |

### 6.4 Pricing policy guard

Pricing learning must be constrained by policy.

```json
{
  "schema_id": "jpcite.pricing_learning_policy.v1",
  "default_mode": "recommend_only",
  "auto_decrease_allowed": true,
  "auto_bundle_discount_allowed": true,
  "auto_price_increase_allowed": false,
  "auto_cap_increase_allowed": false,
  "requires_explicit_consent_for": [
    "price_increase",
    "autopay_cap_increase",
    "watch_subscription_start",
    "higher_tier_default"
  ],
  "must_preserve": [
    "cheapest_sufficient_route",
    "known_gaps_before_purchase",
    "accepted_artifact_pricing",
    "void_on_policy_block"
  ]
}
```

### 6.5 Smart pricing improvements

Adopt these if metrics support them.

| Improvement | Why smart | Gate |
| --- | --- | --- |
| `coverage_ladder_quote` tuning | Users see what higher tier adds | Golden Replay |
| `receipt_reuse_dividend` | Lower price when prior receipts can be reused | Billing ledger |
| `workflow_bundle_quote` | Cheaper multi-step job for agent tasks | Consent envelope |
| `watch_delta_product` pricing | Charge for ongoing change detection | Cancel/renewal clarity |
| `portfolio_sampling_ladder` | Cheap first pass across many companies | No false safety claim |
| `void_reason_refinement` | Reduce paid failures | Billing event ledger |

### 6.6 Non-adopted pricing automation

Reject:

- automatic price increase based solely on conversion
- dark pattern tier ordering
- hiding cheapest sufficient route
- charging for blocked source/policy failure
- charging for no-hit as proof of absence
- increasing cap without explicit consent

---

## 7. Source Quality Learning Loop

### 7.1 Purpose

Improve source priority, capture method, and AWS spend allocation based on product impact, not source volume.

### 7.2 Inputs

- source canary result
- capture method result
- source terms decision
- accepted source receipts
- claim refs generated
- known gaps reduced
- no-hit leases created
- packet coverage change
- agent recommendability change
- cost per accepted artifact
- replay improvement after source import

### 7.3 Source metrics

| Metric | Meaning | Use |
| --- | --- | --- |
| `source_capture_success_rate` | API/HTML/PDF/Playwright/OCR取得成功率 | capture method選択 |
| `terms_pass_rate` | terms/robots/policy gate通過率 | source可否 |
| `accepted_receipt_rate` | 取得物がreceiptへ変換された率 | source優先度 |
| `claim_support_yield` | claim_refs生成数/品質 | packet coverage |
| `known_gap_reduction_rate` | known gap解消率 | source priority |
| `no_hit_lease_quality` | no-hit範囲/失効の妥当性 | no-hit freshness |
| `packet_impact_score` | packetごとのcoverage/recommendability改善 | AWS allocation |
| `cost_per_gap_reduced` | gap解消単価 | canary economics |
| `manual_review_burden` | 人間ではなくAI review gateの負荷proxy | scale抑制 |
| `staleness_risk_score` | 更新頻度/期限切れリスク | refresh schedule |

### 7.4 Source quality record

```json
{
  "schema_id": "jpcite.source_quality_learning_record.v1",
  "source_candidate_id": "sc_mlit_negative_info",
  "source_profile_id": "sp_mlit_negative_info_v1",
  "capture_method": "html_table_with_playwright_canary",
  "canary_run_id": "canary_20260515_007",
  "terms_decision": "allowed_public_observation",
  "cost": {
    "cost_usd": 12.84,
    "budget_token_id": "bt_...",
    "p95_cost_to_complete_usd": 18.20
  },
  "yield": {
    "source_receipts": 214,
    "claim_refs": 603,
    "known_gaps_reduced": 47,
    "no_hit_leases_created": 31,
    "accepted_artifact_rate": 0.82
  },
  "packet_impact": [
    {
      "outcome_contract_id": "vendor_public_risk_attention_v1",
      "coverage_delta": 0.21,
      "agent_recommendability_delta": 0.14,
      "preview_to_paid_expected_delta": 0.03
    }
  ],
  "quality_scores": {
    "capture_reliability_score": 0.86,
    "schema_stability_score": 0.74,
    "claim_support_strength_score": 0.81,
    "staleness_risk_score": 0.33,
    "manual_review_burden_score": 0.18
  },
  "decision": "expand | suppress | retry_with_method | replace_source | watch_only",
  "decision_reason_codes": [
    "high_packet_impact",
    "low_cost_per_gap_reduced",
    "terms_passed"
  ]
}
```

### 7.5 Source priority update

```json
{
  "schema_id": "jpcite.source_priority_update.v1",
  "update_id": "spu_20260515_001",
  "generated_by": "source_quality_learning_loop",
  "input_records": [
    "jpcite.source_quality_learning_record.v1"
  ],
  "changes": [
    {
      "source_candidate_id": "sc_mlit_negative_info",
      "old_priority": "P1",
      "new_priority": "P0-B",
      "reason": "high vendor_check packet impact and low cost per gap reduced",
      "budget_allocation_hint": {
        "increase_budget_token_share": true,
        "max_increment_usd": 500
      }
    },
    {
      "source_candidate_id": "sc_low_yield_local_pdf_set",
      "old_priority": "P0-B",
      "new_priority": "P1-watch",
      "reason": "low accepted receipt rate and high OCR cost",
      "budget_allocation_hint": {
        "increase_budget_token_share": false,
        "stop_full_scale": true
      }
    }
  ],
  "policy_gate_required": true,
  "auto_apply_allowed": true,
  "auto_apply_scope": "factory_scheduler_config_only"
}
```

### 7.6 Conflict with broad public corpus expansion

Potential conflict:

- The user wants broad Japanese public-information acquisition while the learning loop may suppress low-yield sources early.

Resolution:

- Keep a separate `exploration_budget_floor`.
- Do not let product conversion alone decide public-information scope.
- Use three budget buckets:
  - `exploit_high_yield`
  - `explore_public_corpus`
  - `compliance_mandatory`

Machine-readable rule:

```json
{
  "schema_id": "jpcite.source_budget_bucket_policy.v1",
  "buckets": {
    "exploit_high_yield": {
      "target_share": 0.60,
      "optimizer": "packet_impact_per_dollar"
    },
    "explore_public_corpus": {
      "target_share": 0.25,
      "optimizer": "gap_discovery_per_dollar",
      "minimum_share": 0.15
    },
    "compliance_mandatory": {
      "target_share": 0.15,
      "optimizer": "policy_and_coverage_obligation",
      "minimum_share": 0.10
    }
  }
}
```

---

## 8. Golden Agent Session Learning Loop

### 8.1 Purpose

Use production-safe aggregate signals and failed eval cases to expand Golden Agent Session Replay, without storing raw user conversations.

### 8.2 Inputs

- synthetic golden sessions
- redacted agent transcript state sequence
- capability matrix mismatch
- price consent failure
- no-hit forbidden wording detection
- known gap misunderstanding
- over-recommendation
- do-not-recommend failure
- proof page confusion
- blocked capability recommendation

### 8.3 Replay metrics

| Metric | Meaning | Release action |
| --- | --- | --- |
| `recommendation_correctness_rate` | 推薦/非推薦が正しい率 | release gate |
| `price_consent_pass_rate` | cap/consent説明が通る率 | billing gate |
| `cheapest_route_pass_rate` | 最安十分routeを選ぶ率 | product gate |
| `no_hit_language_pass_rate` | no-hit誤表現なし率 | hard blocker |
| `known_gap_explanation_pass_rate` | gap説明ができる率 | release gate |
| `capability_matrix_alignment_rate` | surfaceと実能力が一致する率 | hard blocker |
| `private_data_non_leak_rate` | private漏洩なし率 | hard blocker |
| `proof_page_understanding_rate` | agentがproofから正しく判断できる率 | GEO gate |

### 8.4 Golden session generation proposal

```json
{
  "schema_id": "jpcite.golden_session_proposal.v1",
  "proposal_id": "gsp_20260515_001",
  "source_signal": {
    "signal_type": "aggregate_failure_pattern",
    "metric_id": "known_gap_explanation_pass_rate",
    "affected_task_family": "grant_search",
    "affected_surface": "mcp"
  },
  "failure_summary": "Agents often recommend paid grant shortlist before explaining that region and employee-count gaps reduce confidence.",
  "new_golden_session": {
    "session_family": "known_gap",
    "task_family": "grant_search",
    "budget_sensitivity": "cheapest",
    "data_available": "company_name_only",
    "expected_state_sequence": [
      "task_intake",
      "ask_followup_or_preview",
      "known_gap_disclosure",
      "cheapest_route",
      "consent_required"
    ],
    "must_include": [
      "known_gaps_before_purchase",
      "cheapest_sufficient_route",
      "not_eligibility_judgment"
    ],
    "must_not_include": [
      "採択されます",
      "対象です",
      "必ず使えます"
    ]
  },
  "privacy_report": {
    "raw_transcript_used": false,
    "derived_from_aggregate": true,
    "min_group_size": 84
  },
  "auto_add_allowed": true
}
```

### 8.5 Replay learning rules

AI may add or update Golden Sessions if:

- source signal is aggregate or synthetic
- no raw user transcript is embedded
- forbidden wording list is not weakened
- expected state sequence remains compatible with Agent Decision Protocol
- new test is generated before product/release change is accepted

AI must not:

- create tests from a private user's exact prompt
- include company names from private interactions
- encode sensitive customer facts as fixtures
- change pass criteria to fit current behavior

---

## 9. Canary Economics Learning Loop

### 9.1 Purpose

Allocate AWS build-loop budget to source/method pairs that produce the most accepted, reusable, policy-safe product value.

### 9.2 Metrics

| Metric | Meaning |
| --- | --- |
| `accepted_artifact_per_usd` | accepted artifact効率 |
| `packet_coverage_delta_per_usd` | packet coverage改善効率 |
| `known_gap_reduction_per_usd` | gap解消効率 |
| `agent_recommendability_delta_per_usd` | agent推薦しやすさ改善効率 |
| `receipt_reuse_score_per_usd` | receipt再利用効率 |
| `terms_block_rate` | terms gateで止まる率 |
| `capture_method_failure_rate` | method別失敗率 |
| `teardown_debt_usd` | 後片付け負債 |
| `tail_cost_risk_p95` | p95コストリスク |

### 9.3 Budget allocation record

```json
{
  "schema_id": "jpcite.canary_economics_allocation.v1",
  "allocation_id": "cea_20260515_001",
  "control_spend_window": {
    "target_usd": 19300,
    "reserved_usd": 8200,
    "spent_control_usd": 5400,
    "tail_risk_p95_usd": 600
  },
  "candidate_actions": [
    {
      "action_id": "expand_mlit_negative_info_html",
      "source_candidate_id": "sc_mlit_negative_info",
      "capture_method": "html_table",
      "expected_cost_usd": 300,
      "p95_cost_usd": 420,
      "expected_packet_impact": 0.18,
      "teardown_debt_usd": 4,
      "decision": "fund"
    },
    {
      "action_id": "ocr_low_yield_local_pdf_bulk",
      "source_candidate_id": "sc_local_pdf_unknown",
      "capture_method": "textract_ocr",
      "expected_cost_usd": 900,
      "p95_cost_usd": 1800,
      "expected_packet_impact": 0.02,
      "teardown_debt_usd": 80,
      "decision": "suppress_or_canary_only"
    }
  ],
  "allocation_policy": {
    "reserve_before_run": true,
    "reclaim_unused_lease": true,
    "forbid_new_service_after_silence_mode": true,
    "respect_service_risk_escrow": true
  }
}
```

### 9.4 Smart AWS spend implication

This loop keeps the user's objective intact:

- spend quickly
- stay below credit-safe boundary
- produce durable assets
- keep AWS running without Codex/Claude
- avoid wasteful low-value jobs
- preserve broad exploration budget
- teardown cleanly

The important change is that AWS budget is not assigned to jobs; it is assigned to expected accepted product value.

---

## 10. Autonomous Improvement Engine

### 10.1 Purpose

AI executes improvements, so the improvement loop must be explicit, machine-readable, reversible, and gated.

### 10.2 Improvement proposal common schema

```json
{
  "schema_id": "jpcite.learning_proposal.v1",
  "proposal_id": "lp_20260515_017",
  "proposal_family": "product | pricing | source | golden_replay | compiler | release | aws_factory",
  "created_by": "ai_learning_control_plane",
  "input_dataset_manifest_id": "learn_20260515_demand_p0",
  "hypothesis": "Adding a cheapest-route explanation improves consent without increasing price.",
  "target_files_or_manifests": [
    "outcome_contract_catalog",
    "agent_surface_compiler",
    "golden_session_manifest"
  ],
  "proposed_diff_summary": [
    "add coverage ladder explanation to preview decision object",
    "add new golden session for known gap before purchase"
  ],
  "risk_class": "low | medium | high",
  "auto_apply_allowed": true,
  "auto_apply_scope": "candidate_capsule_only",
  "required_verification": [
    "schema_validation",
    "policy_decision_firewall",
    "golden_agent_session_replay",
    "pricing_policy_guard",
    "surface_parity",
    "privacy_leak_scan",
    "production_smoke_without_aws"
  ],
  "rollback_plan": {
    "method": "pointer_switch",
    "target": "previous_release_capsule",
    "requires_aws": false
  }
}
```

### 10.3 Autonomous action levels

| Level | AI may do | Examples |
| --- | --- | --- |
| `L0_measure` | compute metrics only | aggregate conversion |
| `L1_propose` | write proposal only | pricing recommendation |
| `L2_candidate` | modify candidate capsule | preview copy, bundle suggestion |
| `L3_shadow` | run shadow replay/eval | Golden Replay on candidate |
| `L4_activate` | activate if all gates pass | pointer switch |
| `L5_paid_policy_change` | not automatic by default | cap increase, price increase |

Default:

- L0-L3 auto-allowed for low/medium risk.
- L4 only if release policy allows.
- L5 requires explicit policy object and prior consent model.

### 10.4 Stop conditions

AI must stop and mark `manual_policy_review_required=true` if:

- telemetry schema includes a forbidden field
- group suppression fails
- proposal uses revenue-only optimization for source priority
- proposal weakens no-hit or known-gap language
- proposal hides cheapest sufficient route
- proposal increases price/cap without explicit pricing policy
- Golden Replay fails any hard blocker
- private CSV/public source taint separation fails
- Release Capsule requires AWS runtime dependency
- zero-bill posture would be weakened

---

## 11. Feedback Loop Map

### 11.1 Loop A: Product conversion to packaging

```text
preview_decision events
  -> aggregate conversion/gap/skip metrics
  -> product learning proposal
  -> candidate outcome catalog diff
  -> Golden Replay
  -> Release Capsule candidate
  -> shadow exposure
  -> activate or reject
```

### 11.2 Loop B: Known gaps to source priority

```text
known_gap disclosed before purchase
  -> gap blocker metric
  -> output_gap_map update
  -> source_candidate_registry query
  -> source canary
  -> Public Corpus Yield Compiler
  -> source priority update
  -> AWS factory budget lease
```

### 11.3 Loop C: Source canary to pricing

```text
source canary accepted artifacts
  -> receipt reuse score
  -> expected marginal cost per packet
  -> pricing learning proposal
  -> receipt reuse dividend
  -> pricing matrix candidate
  -> price consent replay
```

### 11.4 Loop D: Agent eval to surface compiler

```text
Golden Replay failure
  -> failure class
  -> agent surface compiler proposal
  -> decision bundle / MCP / OpenAPI / proof page diff
  -> surface parity check
  -> replay again
```

### 11.5 Loop E: Production capsule to rollback

```text
runtime aggregate telemetry
  -> anomaly or regression metric
  -> rollback trigger proposal
  -> pointer switch to previous capsule
  -> post-rollback replay
  -> learning proposal for failed capsule
```

---

## 12. Required JPCIR Extensions

Add the following JPCIR record families.

### 12.1 `JPCIRTelemetryEvent`

Purpose:

- privacy-safe event emitted by agent surfaces, preview, billing, and runtime.

Required invariants:

- no free text dimensions
- no raw prompt
- no raw CSV
- no packet payload
- no raw source body
- all dimensions allowlisted

### 12.2 `JPCIRMetricAggregate`

Purpose:

- suppressed and aggregated metric row.

Required invariants:

- suppression policy applied
- min group size recorded
- dominance check recorded
- no single tenant slice

### 12.3 `JPCIRLearningDatasetManifest`

Purpose:

- manifest for metric datasets AI may use.

Required invariants:

- input event classes enumerated
- forbidden fields scan passed
- allowed action classes declared

### 12.4 `JPCIRLearningProposal`

Purpose:

- AI-generated proposal for product/source/pricing/release improvement.

Required invariants:

- hypothesis present
- supporting metrics present
- privacy report present
- required gates present
- rollback plan present

### 12.5 `JPCIRSourceQualityLearningRecord`

Purpose:

- source canary/yield learning result.

Required invariants:

- terms decision present
- capture method present
- packet impact present
- cost and p95 tail risk present

### 12.6 `JPCIRGoldenSessionProposal`

Purpose:

- proposed new eval session from aggregate failure pattern.

Required invariants:

- no raw transcript
- must_include/must_not_include present
- expected state sequence compatible with Agent Decision Protocol

---

## 13. Release Gates

### 13.1 New gate: `learning_privacy_gate`

Blocks release if:

- telemetry contains forbidden field
- event schema has free-text dimension
- aggregate lacks suppression report
- raw prompt/CSV/source/payload appears in metrics artifact
- metric can identify a named customer or transaction

### 13.2 New gate: `learning_action_gate`

Blocks auto-application if:

- proposal lacks metric support
- proposal lacks rollback
- proposal weakens policy language
- proposal touches price/cap beyond allowed scope
- proposal modifies active production directly

### 13.3 New gate: `learning_regression_gate`

Blocks release capsule if:

- recommendation correctness regresses
- price consent pass rate regresses materially
- no-hit language pass rate below 100% on hard cases
- private leak test fails
- capability matrix alignment fails
- source priority update reduces coverage for active paid products without downgrade notice

### 13.4 New gate: `source_learning_gate`

Blocks source scaling if:

- terms decision is missing or blocked
- packet impact is unknown
- accepted artifact rate is below threshold
- p95 cost-to-complete exceeds reserved budget token
- teardown debt is high
- source canary produces raw data that cannot be policy-approved into JPCIR

---

## 14. Master Plan Merge Difference

### 14.1 Add to smart method section

Add:

```text
Privacy-Safe Learning Control Plane:
All product, pricing, source, Golden Replay, and AWS factory improvements are driven by machine-readable aggregate metrics and learning proposals. No raw prompt, raw CSV, raw packet payload, raw source body, screenshot text, HAR body, or private user fact may enter the learning dataset. AI may auto-apply only low-risk changes to candidate release capsules after policy, privacy, pricing, Golden Replay, and rollback gates pass.
```

### 14.2 Add to implementation order

Insert after `JPCIR schemas` and before large AWS factory scale-out:

```text
JPCIR schemas
  -> telemetry event allowlist
  -> metric contract registry
  -> suppression policy
  -> learning dataset manifest
  -> learning proposal schema
  -> product/source/pricing metric aggregators
  -> Golden Session proposal generator
  -> learning gates
  -> candidate-capsule-only auto-apply
  -> AWS full artifact factory scale-out
```

Reason:

- AWS full scale should not run blind.
- Even if initial metrics are synthetic/canary-only, the factory scheduler should already understand source yield and packet impact.

### 14.3 Add P0 items

| ID | Item | Output |
| --- | --- | --- |
| ML-P0-01 | Telemetry Event Allowlist | `telemetry_event.schema.json` |
| ML-P0-02 | Metric Contract Registry | `metric_contracts/*.json` |
| ML-P0-03 | Suppression Policy | `telemetry_suppression_policy.json` |
| ML-P0-04 | Learning Dataset Manifest | `learning_dataset_manifest.schema.json` |
| ML-P0-05 | Learning Proposal Schema | `learning_proposal.schema.json` |
| ML-P0-06 | Product Metric Aggregator | aggregate tables only |
| ML-P0-07 | Source Quality Learning Record | source canary metric output |
| ML-P0-08 | Golden Session Proposal Schema | eval expansion |
| ML-P0-09 | Learning Privacy Gate | leak/suppression validator |
| ML-P0-10 | Candidate Capsule Auto-Apply Guard | no active direct mutation |

### 14.4 Add P1 items

| ID | Item | Output |
| --- | --- | --- |
| ML-P1-01 | Pricing Learning Recommender | recommend-only price proposals |
| ML-P1-02 | Source Priority Optimizer | source priority update proposals |
| ML-P1-03 | Product Packaging Optimizer | preview/bundle/catalog proposal |
| ML-P1-04 | Golden Replay Auto-Expansion | synthetic session generation |
| ML-P1-05 | Canary Economics Allocator | budget token recommendation |
| ML-P1-06 | Capsule Regression Monitor | rollback proposals |

### 14.5 Add P2 items

| ID | Item | Output |
| --- | --- | --- |
| ML-P2-01 | Safe Autopay Performance Monitor | watch/cap safety |
| ML-P2-02 | Longitudinal Source Freshness Learning | refresh schedule optimizer |
| ML-P2-03 | Outcome Contract Evolution Engine | new contract proposals |
| ML-P2-04 | Agent Surface Experiment Framework | non-dark-pattern A/B style surface variants |

---

## 15. Contradiction Review

### 15.1 Privacy telemetry vs service improvement

Status: PASS with strict allowlist.

Risk:

- Improving product based on user demand can tempt raw prompt logging.

Resolution:

- Learn from decision states and safe buckets.
- No free text dimensions.
- Suppression policy mandatory.
- Raw prompt/CSV/private fact is release blocker.

### 15.2 AI executes everything vs safety

Status: PASS with action levels.

Risk:

- AI might apply revenue-optimizing changes directly to production.

Resolution:

- L0-L3 auto allowed.
- L4 only through Release Capsule activation gates.
- L5 price/cap/autopay changes require explicit policy object.
- Active production is changed only by pointer activation.

### 15.3 Canary Economics vs broad public-information collection

Status: PASS with exploration budget floor.

Risk:

- Optimizer might over-focus on immediate revenue and suppress valuable public corpus.

Resolution:

- Split budget into `exploit_high_yield`, `explore_public_corpus`, and `compliance_mandatory`.
- Product impact is one signal, not the only objective.
- Policy and public corpus coverage remain hard constraints.

### 15.4 Golden Replay learning vs raw transcript privacy

Status: PASS if session proposals are synthetic/aggregate.

Risk:

- Failed real conversations may leak private facts into tests.

Resolution:

- Golden proposals use aggregate failure patterns.
- Synthetic examples only.
- No named company/customer from telemetry.
- Privacy leak scan on fixture files.

### 15.5 Pricing optimization vs cheapest sufficient promise

Status: PASS with pricing policy guard.

Risk:

- Optimizer may raise prices or hide cheaper routes.

Resolution:

- `cheapest_sufficient_route` is invariant.
- Auto price increases disabled by default.
- Cap increases forbidden without explicit consent.
- High-tier recommendation must explain added coverage.

### 15.6 Source quality learning vs no-hit misuse

Status: PASS.

Risk:

- Better source metrics may be misread as proof of safety or absence.

Resolution:

- No-hit remains lease-scoped observation.
- Source quality metrics are operational, not legal/trust scores.
- Public wording remains `no_hit_not_absence`.

### 15.7 Runtime telemetry vs zero-AWS posture

Status: PASS.

Risk:

- Telemetry infrastructure could become a new persistent AWS dependency.

Resolution:

- Production telemetry must not require AWS after teardown unless explicitly accepted.
- Telemetry sink must be outside AWS or disabled with local/static operation preserved.
- Zero-AWS posture manifest includes telemetry dependency check.

### 15.8 Metric-driven release vs human manual review

Status: PASS with AI gates.

User clarified: implementation execution is done by AI, not humans.

Resolution:

- Replace "manual review" with `manual_policy_review_required` only for policy/legal/business owner decisions.
- AI performs schema validation, leak scanning, replay, proposal generation, and rollback readiness.
- If human decision is unavailable and policy gate requires it, AI must not bypass; it marks the feature blocked or candidate-only.

---

## 16. What Not To Adopt

Reject these methods.

| Rejected method | Reason |
| --- | --- |
| raw prompt analytics | privacy risk |
| session replay using real transcripts | private fact leakage |
| raw CSV telemetry | explicitly prohibited |
| source text embedding into telemetry | copyright/terms/privacy risk |
| generic trust score learning | conflicts with no safety/credit judgment |
| revenue-only source prioritization | undermines public-information mission |
| automatic price increase | conflicts with consent/cheap route promise |
| dark-pattern bundle defaults | harms agent trust |
| permanent AWS telemetry archive | conflicts with zero-bill posture |
| LLM-only policy approval | policy gate must be deterministic or attested |

---

## 17. Final Recommendation

Adopt `Privacy-Safe Learning Control Plane` as Round3 method 17.

This is a meaningful improvement over the existing plan because it turns isolated metrics into a safe autonomous learning system.

The strongest merged architecture becomes:

```text
Evidence Product OS
  -> JPCIR
  -> Policy Decision Firewall
  -> Outcome Contract Catalog
  -> Official Evidence Ledger / Evidence Lens
  -> Output Composer / Public Packet Compiler
  -> Agent Decision Protocol
  -> Release Capsule
  -> Privacy-Safe Learning Control Plane
  -> AWS Artifact Factory Kernel
  -> Zero-Bill Guarantee Ledger
```

The learning control plane should be implemented before full AWS scale-out and before production auto-improvement.

Minimum P0:

1. event allowlist
2. metric contract registry
3. suppression policy
4. learning dataset manifest
5. proposal schema
6. product/source/pricing metric aggregators
7. Golden Session proposal format
8. learning privacy gate
9. candidate-capsule-only auto-apply
10. regression gates

This gives jpcite a safe way to learn:

- what sells
- what agents recommend
- what users reject
- what sources matter
- what prices are acceptable
- what gaps block purchase
- what release changes regress quality

without storing the private content that would break the product promise.

