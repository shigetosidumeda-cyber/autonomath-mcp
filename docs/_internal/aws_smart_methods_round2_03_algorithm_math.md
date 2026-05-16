# AWS Smart Methods Round 2 - 03/06: Algorithm / Math / Output Quality

Date: 2026-05-15  
Role: Algorithm, mathematics, output quality, hallucination-resistance  
Scope: jpcite master plan, Proof-Carrying Packet Compiler, typed score, gap coverage, no-hit scope compiler  
AWS command/API/resource status: not executed  
Output constraint: this file only

## 0. Verdict

Conditional PASS with important additions.

The current plan is already directionally correct:

- public claims require `source_receipts[]` and `claim_refs[]`.
- every output needs `known_gaps[]` and `gap_coverage_matrix[]`.
- no-hit is always `no_hit_not_absence`.
- request-time LLM must not create factual public claims.
- generic `score` is forbidden; only typed `score_set[]` is allowed.
- `eligible`, `safe`, `no issue`, `permission not required`, and similar certainty language must not be exposed.
- `Output Composer` recommends what to buy or ask next, but factual claims come only from `Public Packet Compiler`.

However, the algorithm layer can be made materially smarter.

The strongest additional idea is:

> Make the Public Packet Compiler a proof-carrying, coverage-optimizing, contradiction-aware compiler, not just a serializer of receipts and claims.

That means the compiler should calculate:

- what is proven,
- what is only candidate evidence,
- what is in conflict,
- what was checked and returned no-hit,
- what was not checked,
- which source set is the minimal sufficient proof,
- which missing input/source would most improve the output,
- whether the packet should abstain, ask a follow-up, or emit a limited result.

This keeps the core concept intact: source-backed output with no hallucination, while making the generated packet much more reliable and easier for AI agents to recommend.

## 1. Existing assumptions retained

This review assumes the following are fixed and not reopened.

### 1.1 Proof-Carrying Packet Compiler

All public packet outputs must pass through a compiler that enforces:

- source receipt existence,
- claim reference binding,
- gap coverage,
- no-hit scope semantics,
- typed scores,
- forbidden phrase scanning,
- public/internal label separation,
- CSV privacy boundaries,
- OCR/LLM candidate quarantine.

### 1.2 Typed score only

External outputs must not expose generic fields such as:

```json
{ "score": 82 }
{ "risk_score": 71 }
{ "eligibility_score": 88 }
{ "safety_score": 95 }
```

Allowed:

```json
{
  "score_set": [
    {
      "score_name": "review_priority_score",
      "score_value": 72.4,
      "score_scale": "0_to_100",
      "score_meaning": "Priority for review within declared public-source scope.",
      "not_probability": true,
      "not_safety": true,
      "not_creditworthiness": true,
      "not_legal_or_tax_decision": true,
      "components": [],
      "claim_refs": [],
      "known_gap_refs": []
    }
  ]
}
```

### 1.3 Gap coverage

`known_gaps[]` alone is not enough.

Every packet needs a `gap_coverage_matrix[]` showing:

- required coverage category,
- source families checked,
- source families not checked,
- no-hit scope,
- blocked/terms/manual-review states,
- stale or partial coverage,
- user input gaps.

### 1.4 No-hit scope compiler

No-hit must be compiled as a scoped observation, not as absence.

Required meaning:

```json
{
  "result_state": "no_hit_not_absence",
  "meaning": "The declared source/query/time/normalization scope returned no matched record.",
  "does_not_mean": [
    "absence",
    "safety",
    "no_issue",
    "legal_compliance",
    "permission_not_required",
    "not_registered",
    "not_subject_to_rule"
  ]
}
```

## 2. Highest-value additions

Adopt the following as Round 2 smart methods.

### 2.1 Evidence support lattice

Adopt.

Instead of treating claims as simply true/false or supported/unsupported, define a support lattice.

Suggested states:

```text
rejected
unsupported
candidate_only
ocr_candidate
html_observed
api_observed
single_source_supported
multi_source_supported
conflicting
superseded
manual_review_required
out_of_scope
```

This is smarter than a numeric confidence score because it avoids pretending to know a probability of truth, legality, eligibility, or safety.

Use it for:

- claim compiler decisions,
- proof pages,
- agent-facing summaries,
- abstention logic,
- human-review flags,
- release gates.

Public copy should say:

```text
この主張は指定source receiptにより確認されています。
```

or:

```text
この主張は候補抽出に留まり、公開packetの断定claimには使っていません。
```

Do not say:

```text
95%正しい
安全です
問題ありません
```

### 2.2 Uncertainty propagation without legal probability

Adopt with strict naming.

Use uncertainty propagation internally, but do not expose it as:

- legal probability,
- eligibility probability,
- safety probability,
- creditworthiness probability,
- compliance probability.

The useful propagation is not "how likely is this legally true?"

The useful propagation is:

- how much of the declared evidence scope is covered,
- whether the required identifiers are normalized,
- whether the source receipt is stale,
- whether extraction method is weak,
- whether there is conflict,
- whether no-hit scope is narrow,
- whether OCR/HTML observation is enough for the claim type.

Use an `uncertainty_trace[]` or `support_trace[]`:

```json
{
  "uncertainty_trace": [
    {
      "claim_ref": "claim_001",
      "support_state": "single_source_supported",
      "uncertainty_sources": [
        {
          "type": "source_staleness",
          "severity": "low",
          "explanation": "Source was captured within the packet freshness window."
        },
        {
          "type": "identifier_ambiguity",
          "severity": "none",
          "explanation": "Corporate number normalized and matched."
        }
      ],
      "public_certainty_label": "source_scoped_supported",
      "not_probability": true
    }
  ]
}
```

Adopt this because it helps the AI agent explain limitations without hallucinating.

### 2.3 Coverage optimization

Adopt.

The current `gap_coverage_matrix[]` says what was checked. Add an optimizer that decides what should be checked under budget, latency, source terms, packet price, and expected value.

Use a weighted coverage model:

```text
maximize:
  sum(required_claim_area_weight_i * covered_i)
  + sum(reuse_value_j)
  + sum(agent_recommendation_gain_k)
  - lambda_cost * expected_cost
  - lambda_latency * expected_latency
  - lambda_staleness * staleness_penalty
  - lambda_terms * terms_risk_penalty
  - lambda_conflict * unresolved_conflict_penalty
```

Subject to:

```text
raw_csv_to_aws = false
source_terms_gate = pass
public_claim_requires_receipt = true
no_hit_not_absence = true
ocr_only_critical_claim = false
generic_score_external = false
forbidden_phrase_external = false
```

This should be used for:

- selecting sources for a packet,
- deciding whether to ask a user follow-up question,
- deciding whether to recommend a cheap packet or a higher bundle,
- deciding stretch jobs in AWS,
- prioritizing `output_gap_map`.

Adopt as P0/P1:

- P0: deterministic coverage calculation and gap matrix.
- P1: weighted optimization for source selection and question generation.
- P2: adaptive weights based on accepted-artifact yield.

### 2.4 Budgeted maximum coverage / set cover

Adopt.

Many jpcite tasks are set-cover problems.

Examples:

- Which minimum source set supports all claims in `company_public_baseline`?
- Which smallest question set unlocks enough information for `grant_candidate_shortlist`?
- Which source families cover most high-value packet gaps under remaining AWS budget?
- Which proof receipts should be shown so the proof page is useful but not overloaded?

Use greedy weighted set cover as the default implementation because it is explainable and easy to audit.

Source selection example:

```text
Universe U:
  required claim areas for packet

Candidate sets S:
  official source families and capture methods

Cost c(s):
  expected capture cost + latency + terms/manual-review penalty

Benefit b(s):
  weighted uncovered claim areas + receipt reuse + agent recommendation value

Pick source s maximizing:
  b(s) / c(s)
until:
  required minimum coverage reached
  or cost cap reached
  or no safe source remains
```

Question generation example:

```text
Ask the smallest number of questions that unlocks the largest number of blocked claims.
```

This is especially valuable for AI agents. It lets the preview say:

```text
法人番号または正式名称+所在地のどちらかがあれば、最安packetで確認できます。
```

### 2.5 Value-of-information

Adopt.

`Value of Information` should decide whether the system should:

- buy/run a packet,
- ask one more question,
- run an additional source,
- recommend a bundle,
- abstain,
- mark human review required.

Define:

```text
VOI(action) =
  expected_gap_reduction(action) * gap_weight
  + expected_claim_support_gain(action) * support_weight
  + receipt_reuse_gain(action) * reuse_weight
  + agent_decision_gain(action) * agent_weight
  - expected_cost(action)
  - expected_latency(action)
  - terms_or_privacy_penalty(action)
```

Important: `VOI` must not become an upsell engine.

Add these constraints:

```text
recommend_higher_packet_only_if_material_gap_reduction = true
show_cheaper_sufficient_option = true
show_reason_not_to_buy = true
respect_user_cap_token = true
do_not_optimize_for_revenue_alone = true
```

Adopt because it creates a smarter agent preview:

```text
この追加質問に答えると、許認可sourceの照合候補が2つ減ります。
未回答でも330円packetは実行できますが、known_gapsが残ります。
```

### 2.6 Contradiction calculus

Adopt.

The compiler should not silently choose one public source over another when they disagree.

Build a contradiction layer over normalized claims.

Claim identity:

```text
claim_key =
  subject_id
  + predicate_id
  + object_normalized
  + jurisdiction_scope
  + time_validity_scope
  + source_family_scope
```

Contradiction types:

- `exact_value_conflict`
- `date_conflict`
- `amount_conflict`
- `identifier_conflict`
- `status_conflict`
- `source_scope_conflict`
- `temporal_supersession`
- `no_hit_vs_hit`
- `ocr_vs_text_conflict`
- `html_vs_api_conflict`
- `user_input_vs_public_source_conflict`

Output:

```json
{
  "contradictions": [
    {
      "contradiction_id": "contr_001",
      "type": "status_conflict",
      "claim_refs": ["claim_011", "claim_019"],
      "source_receipt_refs": ["receipt_a", "receipt_b"],
      "compiler_action": "do_not_resolve_automatically",
      "public_handling": "human_review_required",
      "agent_summary": "公的source間で状態表現が一致しないため、断定せず確認事項として返します。"
    }
  ]
}
```

This is crucial for hallucination avoidance. A weaker system would hide contradiction by picking the latest-looking source. jpcite should instead expose the conflict safely.

### 2.7 Temporal validity calculus

Adopt.

Most public information is time-scoped.

Examples:

- law effective dates,
- application deadlines,
- public notice publication dates,
- invoice registration status dates,
- permit validity periods,
- administrative action periods,
- tax/labor rule effective dates,
- procurement deadlines.

Every claim should support:

```json
{
  "valid_time": {
    "observed_at": "2026-05-15T00:00:00+09:00",
    "source_published_at": "2026-05-01",
    "effective_from": "2026-04-01",
    "effective_to": null,
    "freshness_window_days": 30,
    "staleness_state": "within_window"
  }
}
```

Compiler rule:

```text
If two claims conflict but one is explicitly superseded by a later effective date,
mark the older claim as superseded, not false.
```

Public wording:

```text
この確認は取得日時とsource上の有効時点に依存します。
```

This is higher quality than just attaching a source URL.

### 2.8 Interval arithmetic for amounts, dates, and thresholds

Adopt.

Many outputs depend on thresholds:

- subsidy amount ranges,
- employee count ranges,
- revenue ranges,
- capital thresholds,
- tax deadlines,
- filing periods,
- permit scale thresholds,
- procurement date windows.

Use intervals rather than single values when source or input is approximate.

Example:

```json
{
  "derived_fact": {
    "name": "monthly_sales_range",
    "value_interval": {
      "lower": 1200000,
      "upper": 1500000,
      "currency": "JPY"
    },
    "source": "csv_derived_private_fact",
    "public_output_allowed": false
  }
}
```

Rule:

```text
If a threshold decision changes within the interval,
do not emit a decisive result.
Emit `boundary_case_requires_review`.
```

External label:

```text
境界条件に近いため、確認優先度が高い候補として扱います。
```

Do not emit:

```text
対象です
対象外です
```

### 2.9 Monotonic decision logic

Adopt.

The compiler should obey monotonic safety rules.

The key principle:

> Adding weak or no-hit evidence must not make the output look safer, more compliant, or more eligible.

Suggested monotonic rules:

```text
no_hit evidence can add checked scope.
no_hit evidence cannot reduce review priority by itself.
candidate evidence cannot become public claim without receipt support.
conflict evidence cannot be hidden by a higher score.
OCR evidence cannot upgrade a critical claim above candidate without validation.
more gap coverage can reduce "unknown" but cannot imply "safe".
```

This prevents a common error:

```text
行政処分sourceで見つからなかったため問題なし
```

Correct:

```text
指定した行政処分sourceでは該当hitがありませんでした。
不存在・安全性・法令遵守を示すものではありません。
```

### 2.10 Proof minimality

Adopt.

Packets should include enough proof, but not redundant proof.

Use a minimal proof set:

```text
minimal_receipt_set =
  smallest receipt subset that supports all emitted public claims
  while preserving required source diversity and gap disclosure
```

Why it matters:

- cheaper proof page rendering,
- less noise for AI agents,
- easier audit,
- lower chance of leaking excessive free value,
- faster response,
- better paid/free boundary.

Important constraint:

Proof minimality must not hide gaps.

Therefore:

- emitted claims use `minimal_receipt_set`,
- `gap_coverage_matrix[]` still shows all checked/unavailable/out-of-scope areas,
- `no_hit_checks[]` remain visible as scoped checks,
- conflicts are not removed even if not part of the minimum support set.

Suggested schema:

```json
{
  "proof_certificate": {
    "certificate_id": "proof_001",
    "claim_refs": ["claim_001", "claim_002"],
    "minimal_receipt_refs": ["receipt_nta_corp", "receipt_invoice"],
    "excluded_receipt_refs": [
      {
        "receipt_ref": "receipt_gbiz",
        "reason": "not needed for emitted claim support, retained in coverage matrix"
      }
    ],
    "coverage_matrix_ref": "coverage_001",
    "contradiction_refs": []
  }
}
```

### 2.11 Active learning without private data

Adopt with privacy boundary.

Active learning can improve:

- source discovery,
- source capture method routing,
- OCR target selection,
- packet gap reduction,
- source freshness scheduling,
- question generation,
- proof page usefulness.

But it must not train on private user CSV or private user content.

Allowed signals:

- public source capture success/failure,
- source terms classification,
- accepted artifact rate,
- no-hit frequency by source/query shape,
- compiler rejection reason,
- synthetic CSV fixture outcome,
- redacted/header-only CSV format fixture outcome,
- agent preview decisions,
- source freshness drift,
- packet gap type frequency.

Forbidden signals:

- raw user CSV,
- private rows,
- private counterparties,
- private bank/payroll data,
- private identifiers,
- unredacted user prompts that contain sensitive facts,
- generated paid outputs containing private data.

Adopted learning loop:

```text
compiler gap/rejection -> public-safe feature -> source/action candidate
-> canary capture -> accepted artifact yield -> update routing policy
```

This is smarter than a static crawler, but remains compatible with the privacy promise.

### 2.12 Abstention and defer logic

Adopt.

The compiler needs a first-class ability to not answer.

Output states:

```text
emit_packet
emit_limited_packet
ask_follow_up
recommend_cheaper_free_guidance
recommend_human_review
abstain_no_safe_claim
abstain_terms_or_privacy_blocked
```

Abstention is not a product failure. For jpcite, abstention is trust.

Example:

```json
{
  "compiler_decision": "emit_limited_packet",
  "reason": "Required source families for permit status were partially unavailable. Public baseline claims can be emitted, permit conclusion cannot.",
  "agent_recommendation_card": {
    "recommended_message": "公的ベースラインは取得できますが、許認可の断定には不足sourceがあります。まず330円のベースライン確認に留めるのが安全です。"
  }
}
```

## 3. Methods to adopt only partially

### 3.1 Bayesian probability models

Partial adoption only.

Bayesian updating is useful internally for:

- source capture success probability,
- OCR failure probability,
- job cost-to-complete estimates,
- accepted artifact yield,
- question usefulness,
- canary expansion probability.

Do not use Bayesian models to expose:

- probability of legal compliance,
- probability of eligibility,
- probability of safety,
- probability of no issue,
- credit/default risk,
- regulatory permission probability.

Adopt for operations and routing. Do not adopt for public legal/eligibility certainty.

### 3.2 Machine-learned ranking

Partial adoption only.

Allowed:

- rank source candidates by accepted-artifact yield,
- rank questions by expected gap reduction,
- rank packets by cheapest sufficient match,
- rank proof views by agent usability,
- rank AWS stretch jobs by artifact value density.

Not allowed:

- rank users by willingness to pay,
- hide cheaper sufficient packet,
- recommend a more expensive packet without material gap reduction,
- train on private CSV,
- output unexplained risk/eligibility scores.

### 3.3 Graph inference / transitive reasoning

Partial adoption only.

Graph reasoning is useful for:

- entity resolution candidates,
- source family relationships,
- law/regulation hierarchy,
- source lineage,
- evidence graph display,
- receipt reuse,
- detecting conflicts across sources.

Do not use graph transitivity to create public legal conclusions.

Forbidden:

```text
A is related to B, B has a permit, therefore A has a permit.
```

Allowed:

```text
関連候補があるため、追加確認候補として提示します。
```

### 3.4 Formal verification

Partial adoption.

Full theorem proving is not necessary for RC1.

But lightweight formal properties should be implemented as tests:

- no external claim without receipt or explicit gap,
- no generic `score`,
- no forbidden public labels,
- no-hit never implies absence/safety,
- OCR-only critical facts are blocked,
- public output cannot include real CSV-derived data,
- source terms unknown blocks public claim,
- contradictions trigger limited output or human review,
- compiler can rollback/abstain safely.

Adopt property-based tests and invariant tests before production.

## 4. Methods to reject

### 4.1 Public eligibility probability

Reject.

Do not expose:

```text
採択確率 82%
許認可不要確率 91%
法令適合確率 95%
安全度 98%
```

This conflicts with the source-backed, no-hallucination concept and creates legal/compliance risk.

Use:

```text
公開一次情報と入力済み条件の範囲で、確認優先度が高い候補です。
```

### 4.2 LLM-as-judge as final truth

Reject for public claims.

LLM/Bedrock may be used offline for:

- candidate classification,
- extraction assistance,
- OCR cleanup candidates,
- source grouping candidates,
- summarization candidates for human review.

But it must not:

- create final facts,
- resolve contradictions,
- assign public legal status,
- emit final packet claims,
- validate OCR critical facts by itself.

All LLM-derived candidates must be quarantined:

```json
{
  "candidate_origin": "llm_offline_assist",
  "public_claim_allowed": false,
  "requires_deterministic_validation": true
}
```

### 4.3 Revenue-only optimization

Reject.

The system should increase revenue by being trusted and easy to buy, not by pushing expensive packets.

Forbidden optimizer objective:

```text
maximize expected revenue per user
```

Allowed constrained objective:

```text
maximize user task resolution and source-backed value
subject to cheapest sufficient packet, cap token, reason-not-to-buy, and safety gates.
```

### 4.4 Generic confidence score

Reject.

Generic confidence is too easily misread.

Do not expose:

```json
{ "confidence": 0.91 }
```

Use typed support:

```json
{
  "support_state": "single_source_supported",
  "coverage_state": "partial",
  "human_review_required": true
}
```

or typed score:

```json
{
  "score_name": "review_priority_score",
  "not_probability": true
}
```

## 5. Proposed compiler architecture

### 5.1 Pipeline

Adopt this compiler pipeline:

```text
1. Input normalization
2. Source receipt normalization
3. Candidate fact extraction
4. Entity and identifier normalization
5. Claim graph construction
6. Support lattice assignment
7. No-hit scope compilation
8. Gap coverage matrix construction
9. Contradiction calculus
10. Coverage optimization / set cover
11. Proof minimality selection
12. Typed score calculation
13. Value-of-information decision
14. Forbidden meaning/phrase gate
15. Public packet serialization
16. Agent-facing preview/proof generation
```

### 5.2 Internal namespaces

Separate namespaces clearly.

```text
source_receipts        official/public evidence observations
candidate_facts        extracted but not yet public-claim safe
claim_graph            normalized claims and relationships
public_claims          compiler-approved public claims only
no_hit_checks          scoped no-hit observations
known_gaps             missing/blocked/partial coverage
gap_coverage_matrix    declared coverage by category and source family
contradictions         unresolved or superseded conflicts
proof_certificate      minimal support set for emitted public claims
score_set              typed non-legal, non-safety scores
algorithm_trace        compiler steps and deterministic decisions
agent_decision         buy/ask/skip/abstain recommendation
```

### 5.3 Public claim admission rule

A claim can enter `public_claims[]` only if:

```text
has_claim_ref = true
has_source_receipt_ref = true
source_terms_gate = pass
support_state in [single_source_supported, multi_source_supported, api_observed, html_observed]
critical_fact_ocr_only = false
llm_candidate_only = false
contradiction_state not in [unresolved_blocking_conflict]
time_scope_present = true
gap_coverage_matrix_present = true
forbidden_public_label_absent = true
```

If not, the compiler should move it to:

- `candidate_facts[]`,
- `known_gaps[]`,
- `contradictions[]`,
- or `human_review_required`.

## 6. Packet-specific applications

### 6.1 `company_public_baseline`

Adopt:

- set cover for minimum source set,
- entity resolution with conservative support states,
- contradiction calculus for name/address/status conflicts,
- no-hit scope compiler for invoice/gBizINFO/other lookups,
- proof minimality for agent proof page.

Do not:

- lower risk because no administrative action was found,
- expose a company as safe,
- infer creditworthiness.

### 6.2 `grant_candidate_shortlist`

Adopt:

- interval arithmetic for thresholds,
- value-of-information for follow-up questions,
- monotonic logic for missing input,
- typed `requirement_match_review_score`,
- boundary-case detection.

Do not:

- expose `eligible`,
- expose adoption probability,
- claim application success.

External wording:

```text
公開一次情報と入力済み条件の範囲で、確認優先度が高い制度候補です。
```

### 6.3 `permit_rule_check`

Adopt:

- monotonic decision logic,
- contradiction calculus,
- temporal validity calculus,
- gap coverage by jurisdiction/source family,
- abstention if local ordinance coverage is missing.

Do not:

- say permission is unnecessary,
- say legal compliance is satisfied,
- use no-hit as permission absence.

External wording:

```text
許認可要否を断定せず、確認が必要な制度・窓口・source範囲を示します。
```

### 6.4 `vendor_public_risk_attention`

Adopt:

- typed `public_evidence_attention_score`,
- no-hit as scoped check only,
- contradiction and source freshness handling,
- evidence quality score and coverage gap score displayed together.

Do not:

- call it credit score,
- call it safety score,
- mark as safe/unsafe,
- infer absence of issues from no-hit.

### 6.5 `reg_change_impact`

Adopt:

- temporal validity calculus,
- delta-to-action,
- proof minimality,
- contradiction handling for old/new versions,
- set cover over source hierarchy.

Do not:

- claim legal obligation without sufficient source support,
- hide effective date uncertainty.

### 6.6 CSV overlay outputs

Adopt:

- interval arithmetic,
- group suppression,
- value-of-information for follow-up questions,
- local/private derived fact boundary,
- no AWS handling of raw/private CSV.

Do not:

- send raw CSV to AWS,
- persist raw rows,
- expose private derived facts on public proof pages,
- train active learning on private content.

## 7. New schema additions

### 7.1 `support_trace[]`

```json
{
  "support_trace": [
    {
      "claim_ref": "claim_001",
      "support_state": "single_source_supported",
      "support_basis": ["receipt_001"],
      "extraction_method": "official_api",
      "critical_fact": true,
      "ocr_only": false,
      "llm_candidate_only": false,
      "time_scope_present": true
    }
  ]
}
```

### 7.2 `coverage_optimization_trace`

```json
{
  "coverage_optimization_trace": {
    "packet_type": "company_public_baseline",
    "objective": "cheapest_sufficient_source_coverage",
    "selected_source_families": ["nta_corporate_number", "nta_invoice"],
    "not_selected_source_families": [
      {
        "source_family": "administrative_actions",
        "reason": "outside cheapest sufficient packet scope"
      }
    ],
    "constraints_applied": [
      "no_hit_not_absence",
      "source_terms_gate",
      "cost_cap"
    ]
  }
}
```

### 7.3 `contradiction_record`

```json
{
  "contradictions": [
    {
      "contradiction_id": "contr_001",
      "type": "date_conflict",
      "claim_refs": ["claim_004", "claim_009"],
      "receipt_refs": ["receipt_a", "receipt_b"],
      "resolution_state": "unresolved",
      "compiler_action": "emit_limited_packet",
      "human_review_required": true
    }
  ]
}
```

### 7.4 `proof_certificate`

```json
{
  "proof_certificate": {
    "certificate_id": "proof_001",
    "compiler_version": "public_packet_compiler_v1",
    "claim_refs": ["claim_001", "claim_002"],
    "minimal_receipt_refs": ["receipt_001", "receipt_002"],
    "gap_coverage_matrix_ref": "gapcov_001",
    "no_hit_check_refs": ["nohit_001"],
    "contradiction_refs": [],
    "public_claims_admission_passed": true
  }
}
```

### 7.5 `value_of_information_decision`

```json
{
  "value_of_information_decision": {
    "decision": "ask_follow_up_before_paid_packet",
    "question": "法人番号が分かりますか。分からない場合は正式名称と所在地でも確認できます。",
    "expected_gap_reduction": "high",
    "expected_cost_change": "lower_or_same",
    "reason": "法人番号があると会社同定の曖昧性が下がり、最安packetで足ります。",
    "not_an_upsell": true
  }
}
```

## 8. Quality gates

Add these gates before production.

### G-A1 Claim admission gate

Every external claim must have:

- receipt support,
- claim ref,
- time scope,
- source scope,
- support state,
- gap coverage reference.

### G-A2 No-hit monotonicity gate

Test:

```text
Adding a no-hit check must not produce "safe", "no issue", "absent", "permission not required", or lower review priority by itself.
```

### G-A3 Contradiction gate

If a contradiction exists:

- packet must emit limited result,
- or mark human review,
- or explain supersession by time/source hierarchy.

It must not silently choose a convenient value.

### G-A4 OCR/LLM quarantine gate

OCR/LLM-only critical facts must not enter public claims.

### G-A5 Typed score gate

External output must fail if it contains:

- `score`,
- `risk_score`,
- `eligibility_score`,
- `confidence`,
- `safe`,
- `信用スコア`,
- `採択確率`,
- `適法`,
- `問題なし`.

Allowed only through `score_set[]` with explicit `not_probability` and `not_legal_or_tax_decision`.

### G-A6 Proof minimality gate

Every public packet should be able to produce:

- proof certificate,
- minimal receipt set,
- full coverage matrix reference.

### G-A7 VOI anti-upsell gate

If a higher-priced packet is recommended:

- cheaper sufficient option must be shown,
- material gap reduction must be stated,
- reason not to buy must be present,
- user cap must be respected.

### G-A8 Active learning privacy gate

Training/routing features must not include private CSV content, private rows, private counterparties, or sensitive user text.

## 9. Metrics to track

Track these as product quality metrics.

### 9.1 Evidence quality metrics

- `claim_receipt_binding_rate`
- `public_claim_admission_pass_rate`
- `ocr_candidate_quarantine_rate`
- `llm_candidate_quarantine_rate`
- `unsupported_claim_block_count`
- `contradiction_detection_count`
- `human_review_trigger_rate`

### 9.2 Coverage metrics

- `required_coverage_ratio`
- `weighted_coverage_ratio`
- `gap_coverage_matrix_completeness`
- `no_hit_scope_count`
- `stale_source_claim_count`
- `manual_review_gap_count`

### 9.3 Output quality metrics

- `abstention_rate`
- `limited_packet_rate`
- `question_before_purchase_rate`
- `cheapest_sufficient_packet_match_rate`
- `proof_certificate_generation_rate`
- `forbidden_phrase_block_count`

### 9.4 Agent/GEO metrics

- `agent_decision_card_acceptance_rate`
- `reason_not_to_buy_present_rate`
- `agent_preview_to_purchase_rate`
- `bundle_recommendation_material_gap_rate`
- `proof_page_agent_parse_success_rate`

### 9.5 AWS/source value metrics

- `accepted_artifact_yield`
- `coverage_gain_per_usd`
- `proof_reuse_per_receipt`
- `source_circuit_breaker_trigger_count`
- `output_gap_reduction_per_source_family`

## 10. Implementation priority

### P0

Implement before RC1 paid packet release:

1. `support_state` and `support_trace[]`.
2. strict public claim admission rule.
3. `gap_coverage_matrix[]` required in packet envelope.
4. `no_hit_scope_compiler`.
5. typed `score_set[]` validator.
6. forbidden phrase/meaning gate.
7. OCR/LLM candidate quarantine.
8. basic contradiction detection.
9. proof certificate skeleton.
10. property tests for no-hit monotonicity and forbidden output.

### P1

Implement after RC1, before broader AWS corpus release:

1. weighted coverage optimizer.
2. greedy set cover for source selection.
3. value-of-information question generation.
4. proof minimality.
5. temporal validity calculus.
6. interval arithmetic for threshold outputs.
7. richer contradiction calculus.
8. agent-facing explanation of abstention/limited output.

### P2

Implement after stable packet sales:

1. active learning from public-safe signals.
2. adaptive source routing.
3. learned artifact-yield priors.
4. agent recommendation quality optimization.
5. source freshness scheduling.
6. proof graph simplification.

## 11. Contradictions found and fixes

### 11.1 "Uncertainty" can be misunderstood as probability

Risk:

Users may read uncertainty as legal probability or eligibility probability.

Fix:

Use `support_state`, `coverage_state`, and `review_priority_score`, not `probability`.

### 11.2 "Optimization" can become upsell

Risk:

VOI and packet selection may optimize revenue over user value.

Fix:

Constrain optimization with:

- cheapest sufficient packet,
- reason not to buy,
- cap token,
- material gap reduction,
- no forced upsell.

### 11.3 "Proof minimality" can hide gaps

Risk:

Minimal proof set may omit no-hit checks or unavailable sources.

Fix:

Minimal proof only applies to emitted claim support. Gaps, no-hit checks, and conflicts remain in packet metadata.

### 11.4 "Active learning" can violate CSV privacy

Risk:

Learning from user CSV or private outputs would violate the product promise.

Fix:

Use only public-safe operational features, synthetic fixtures, redacted/header-only format signals, and compiler rejection categories.

### 11.5 "Contradiction calculus" can over-resolve

Risk:

The system may choose a winner between public sources without sufficient basis.

Fix:

Default action for unresolved contradiction is limited output or human review. Auto-resolution is allowed only for explicit temporal supersession or source hierarchy rules.

## 12. Final adoption table

| Method | Decision | Reason |
|---|---:|---|
| Evidence support lattice | Adopt | Better than generic confidence and fits receipt-backed claims |
| Uncertainty propagation | Adopt with naming guard | Useful for limitations, not legal probability |
| Coverage optimization | Adopt | Turns gap matrix into smarter source/question selection |
| Budgeted set cover | Adopt | Minimizes sources/questions/proofs under cap |
| Value-of-information | Adopt with anti-upsell constraints | Makes preview smarter and cheaper |
| Contradiction calculus | Adopt | Prevents silent false certainty |
| Temporal validity calculus | Adopt | Public information is time-scoped |
| Interval arithmetic | Adopt | Handles thresholds and boundary cases safely |
| Monotonic decision logic | Adopt | Prevents no-hit from implying safety |
| Proof minimality | Adopt | Produces compact proof without hiding gaps |
| Active learning without private data | Adopt | Improves source routing while respecting privacy |
| Abstention/defer logic | Adopt | Trust feature, not failure |
| Bayesian routing/cost models | Partial | Good for operations, not public legal claims |
| Machine-learned ranking | Partial | Good for routing; constrained for recommendations |
| Graph inference | Partial | Good for candidates/proof graph; not transitive legal claims |
| Formal verification | Partial | Use property/invariant tests first |
| Public eligibility probability | Reject | Too risky and contradicts concept |
| LLM-as-final-judge | Reject | Violates proof-carrying output |
| Revenue-only optimizer | Reject | Conflicts with cheapest sufficient packet |
| Generic confidence score | Reject | Too ambiguous externally |

## 13. Final conclusion

There is a smarter method beyond the current plan:

> jpcite should compile outputs using a proof-carrying, coverage-optimizing, contradiction-aware packet compiler.

The compiler should not merely attach sources. It should calculate support state, coverage, gaps, no-hit scope, contradictions, proof minimality, and value-of-information before deciding whether to emit a packet, ask a question, recommend a cheaper option, or abstain.

This strengthens the core business concept:

- AI agents can recommend outputs more confidently.
- End users can buy cheaper, narrower, safer packets.
- Public claims stay tied to first-party public evidence.
- Known gaps become explicit product value rather than weakness.
- The service avoids hallucination not by saying less, but by compiling only what can be proven within declared scope.

