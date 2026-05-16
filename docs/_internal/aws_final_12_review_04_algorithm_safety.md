# AWS Final 12 Review 04/12: Algorithm Safety / Hallucination Elimination

Date: 2026-05-15  
Role: algorithm safety, hallucination elimination, expression safety  
Scope: master execution plan and algorithm documents  
AWS command/API/resource status: not executed

## 0. Verdict

Conditional PASS.

The master plan is internally consistent on the main safety contract:

- request-time LLM remains off.
- public claims require `source_receipts[]` and `claim_refs[]`.
- every packet requires `known_gaps[]` and `gap_coverage_matrix[]`.
- no-hit is `no_hit_not_absence`.
- generic external `score` is forbidden and typed `score_set` is required.
- `eligible` is not externally displayed.
- Playwright and screenshots are rendered observations, not access bypass.
- OCR is supporting extraction evidence, not standalone truth for critical facts.

The remaining risk is not conceptual contradiction in the master plan. The risk is implementation drift because several supporting algorithm documents still contain older examples such as `eligible`, generic `"score": 74.2`, `eligibility_label`, or `score` object fields. These can remain as internal research notes only if the implementation adds a strict public-output compiler that normalizes them before API/MCP/proof-page release.

Therefore the smarter plan is:

> Treat all algorithm outputs as internal candidate artifacts. Public packets must be emitted only through a proof-carrying packet compiler that enforces receipts, claim refs, gap coverage, typed scores, no-hit semantics, phrase allowlists, and external-label normalization.

## 1. Documents Reviewed

Primary SOT:

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`

Algorithm and safety documents:

- `docs/_internal/aws_scope_expansion_13_algorithmic_output_engine.md`
- `docs/_internal/aws_scope_expansion_14_grant_matching_algorithm.md`
- `docs/_internal/aws_scope_expansion_15_permit_rule_algorithm.md`
- `docs/_internal/aws_scope_expansion_16_vendor_risk_algorithm.md`
- `docs/_internal/aws_scope_expansion_17_reg_change_diff_algorithm.md`
- `docs/_internal/aws_scope_expansion_18_csv_overlay_algorithm.md`
- `docs/_internal/aws_final_consistency_05_algorithm_safety.md`

## 2. Confirmed Consistencies

### 2.1 Request-Time LLM

Consistent.

The master plan fixes `request_time_llm_call_performed=false`. Algorithm documents also place any LLM/Bedrock usage in offline public-source candidate extraction, classification assistance, deduplication, or OCR structuring. None of the reviewed documents requires request-time LLM to form final claims.

Implementation rule:

```json
{
  "request_time_llm_call_performed": false,
  "llm_candidate_claims_allowed": false,
  "llm_candidate_fact_namespace": "candidate_facts",
  "llm_candidate_requires_validation": true
}
```

Any runtime path that invokes an LLM before returning a packet should be a release blocker unless it is explicitly marked as non-claim routing/copy assistance and cannot alter `claim_refs[]`, `source_receipts[]`, `score_set[]`, or `known_gaps[]`.

### 2.2 Evidence Contract

Consistent in the master plan.

Required public packet fields:

- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]`
- `algorithm_trace[]`
- `score_set[]`
- `human_review_required`
- `_disclaimer`

Important tightening:

`known_gaps=[]` alone must never be interpreted as "no gaps." It is only acceptable if paired with `gap_coverage_matrix[]` showing which categories were checked, covered, stale, blocked, out of scope, or manual-review only.

### 2.3 No-Hit Semantics

Consistent.

No-hit supports only this claim shape:

```json
{
  "claim_type": "checked_source_scope",
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

No-hit must not:

- lower risk/attention score
- prove non-existence
- prove safety
- prove registration absence
- prove permission is unnecessary
- prove eligibility/ineligibility
- be shown as green, cleared, OK, passed, safe, or no issue

### 2.4 Typed Scores

Consistent in the master plan, but supporting documents contain older generic score examples.

Allowed external form:

```json
{
  "score_set": [
    {
      "score_name": "review_priority_score",
      "score_value": 74.2,
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

Forbidden external forms:

```json
{ "score": 74.2 }
{ "risk_score": 18 }
{ "eligibility_score": 86 }
{ "safety_score": 95 }
{ "credit_score": "A" }
```

Internal algorithm fields may keep more specific calculation names, but public serializers must convert them to `score_set[]`.

### 2.5 `eligible` External Ban

Consistent in the master plan. Some grant algorithm examples still use `eligible` or `eligibility_label`. They should be treated as internal states only.

External replacements:

| Internal / old term | External term |
|---|---|
| `eligible` | `high_review_priority_candidate` |
| `likely` | `candidate_priority` |
| `needs_review` | `needs_review` |
| `not_enough_info` | `not_enough_public_evidence` |
| `not_eligible` | `not_ranked_due_to_declared_blocker_or_gap` |
| `eligibility_score` | `requirement_match_review_score` |

Public copy must say:

> 公開一次情報と入力済み情報の範囲で確認優先度が高い候補です。申請可否、採択可能性、適法性を断定するものではありません。

### 2.6 Playwright / Screenshot / OCR

Consistent in the master plan.

Required interpretation:

- Playwright: rendered observation for public pages only.
- Screenshot: receipt aid, not public raw proof payload.
- OCR: candidate extraction, not final truth.
- Critical facts from OCR require deterministic validation, stronger receipt, or human review.

Critical facts include:

- dates and deadlines
- amounts
- corporate numbers
- invoice numbers
- permit/license numbers
- law article numbers
- procedure names
- eligibility/requirement facts

## 3. Remaining Weaknesses

### 3.1 Supporting Docs Still Contain Older Public-Looking Labels

Risk:

The master SOT says `eligible` is not externally displayed, but the grant algorithm document still includes `eligibility_label: "eligible"` examples and says UI can display it with explanation. That is now superseded by the master plan, but implementation teams may copy the older examples.

Required fix:

Add an implementation rule:

```json
{
  "internal_labels_may_include": ["eligible", "likely", "not_eligible"],
  "external_labels_must_not_include": ["eligible", "not_eligible"],
  "public_label_normalizer_required": true
}
```

Release blocker:

- any API/MCP/proof page response contains `eligible`
- any visible field name contains `eligibility`
- any copy says `申請できます`, `対象です`, `採択可能`, `対象外です`

### 3.2 Generic `score` Remains in Examples

Risk:

`algorithmic_output_engine` has examples with generic `"score": 74.2`. Vendor risk uses a typed meaning but under a `"score"` object. AI agents and frontend code may simplify this to a single probability-like score.

Required fix:

Only `score_set[]` is public. Any internal `score` field must be stripped or converted before public emission.

Validation:

```text
fail if jsonpath("$..score") exists in public payload
allow only jsonpath("$.score_set[*].score_value")
```

Exception:

Internal `algorithm_trace` files may contain local calculation fields if they are not public packet payloads and are marked `internal_only=true`.

### 3.3 `known_gaps[]` Empty Arrays Can Be Misread

Risk:

Many sample packet snippets contain `known_gaps: []`. Without a coverage matrix this reads as "no gaps."

Required fix:

Public packets must include:

```json
{
  "known_gaps": [],
  "gap_coverage_matrix": [
    {
      "source_family": "corporate_identity",
      "coverage_state": "covered",
      "scope_note": "NTA corporate number and invoice sources checked for declared identifiers.",
      "not_checked_note": null
    },
    {
      "source_family": "local_government",
      "coverage_state": "not_in_scope",
      "scope_note": null,
      "not_checked_note": "Local permit sources were not checked in this packet."
    }
  ]
}
```

If there are truly no material gaps within declared scope, use:

- `coverage_state=covered`
- `scope_limited=true`
- `declared_scope_only=true`

Do not say:

- gapなし
- 問題なし
- 全範囲確認済み
- 安全

### 3.4 No-Hit Needs a Scope Compiler

Risk:

No-hit is safe only when the checked scope is explicit. A phrase scanner alone cannot prevent misuse.

Required fix:

Every no-hit output must be built by a `no_hit_scope_compiler` that requires:

- source family
- source identifier
- publisher
- access method
- query terms or identifiers
- normalization rules
- retrieval time
- coverage limitations
- no-hit caveat phrase key
- linked `known_gap_ids`

Public no-hit sentence should be generated only from an allowlisted template:

```text
{source_name}を{retrieved_at}時点で{query_summary}により確認した範囲では一致する記録は検出されませんでした。これは不存在、安全、適法、問題なし、登録不要、許可不要を意味しません。
```

### 3.5 OCR and Playwright Need Explicit Support Levels

Risk:

The plan says OCR is supporting evidence, but implementation may accidentally turn OCR text into `claim_refs`.

Required support levels:

| Support level | External claim allowed | Use |
|---|---:|---|
| `direct_structured_source` | yes | official API/XML/CSV/structured data |
| `direct_official_document_span` | yes | official PDF/HTML with page/selector/span |
| `rendered_observation` | limited | screenshot/DOM observation |
| `ocr_candidate` | no, unless validated | OCR candidate span |
| `llm_candidate` | no | offline candidate only |
| `manual_review_required` | no final claim | human review queue |
| `no_hit_scope_only` | only no-hit scope claim | no-hit check |
| `unbacked` | no | blocked |

Release blocker:

- OCR-derived date, amount, number, deadline, permit, article, or eligibility fact enters `claim_refs[]` without validation.
- Playwright screenshot without hash, viewport, URL, retrieved_at, source_profile_id, and capture policy enters a paid claim.
- Any capture from login/CAPTCHA/403/429-bypass path supports a claim.

### 3.6 LLM Candidate Quarantine Should Be Hard-Schema

Risk:

Documents say LLM/Bedrock may assist offline extraction. Without a hard namespace, candidates can leak into claims.

Required schema separation:

```json
{
  "candidate_facts": [
    {
      "candidate_id": "cand_...",
      "candidate_source": "offline_llm_assisted_extraction",
      "candidate_text": "redacted_or_span_bound",
      "source_receipt_ids": [],
      "validation_state": "unvalidated",
      "claim_ref_id": null,
      "public_visible": false
    }
  ],
  "claim_refs": []
}
```

Promotion rule:

`candidate_fact` can become `claim_ref` only if:

1. it has source receipt linkage,
2. it has deterministic validation or human review,
3. it passes terms/robots/license gate,
4. it has span/page/selector/bbox when applicable,
5. it generates or updates `known_gaps[]`,
6. it records `promotion_trace`.

### 3.7 Phrase Gate Needs Meaning-Aware Checks

Risk:

A regex list alone overblocks disclaimer sentences such as "安全を意味しません" and underblocks softer phrases such as "安心して取引できます."

Recommended two-layer gate:

1. Strict phrase denylist to catch obvious forbidden phrases.
2. Semantic template gate that only allows generated copy from approved sentence templates.

P0 should prefer overblocking to manual review.

Forbidden Japanese phrase families:

- 安全です
- 安心です
- 問題ありません
- 問題なし
- 違反なし
- 処分歴なし
- 反社ではありません
- 信用できます
- 信用スコア
- 与信スコア
- 倒産リスク
- 許可不要
- 登録不要
- 届出不要
- 適法です
- 合法です
- 申請できます
- 採択されます
- 対象です
- 対象外です
- 税額を確定
- 労務上問題なし

Forbidden English phrase families:

- safe
- no issue
- no problem
- no violation
- compliant
- permitted
- permission not required
- eligible
- ineligible
- credit score
- trustworthy
- risk-free
- approved
- guaranteed

Allowed disclaimer keys should be rendered from phrase IDs, not raw free text:

- `NO_HIT_NOT_ABSENCE`
- `NOT_LEGAL_ADVICE`
- `NOT_TAX_ADVICE`
- `NOT_CREDIT_DECISION`
- `NOT_FINAL_ELIGIBILITY_DECISION`
- `PUBLIC_SOURCE_SCOPE_ONLY`
- `HUMAN_REVIEW_REQUIRED`

## 4. Smarter Output Algorithm

### 4.1 Proof-Carrying Packet Compiler

Add a final compiler between all algorithms and public surfaces.

Pipeline:

```text
internal algorithm artifacts
  -> evidence graph resolver
  -> claim support validator
  -> gap coverage compiler
  -> no-hit scope compiler
  -> typed score compiler
  -> external label normalizer
  -> sentence template renderer
  -> forbidden phrase scanner
  -> packet release gate
```

Only the compiler can produce:

- REST API responses
- MCP tool responses
- proof page JSON
- OpenAPI examples
- `llms.txt` examples
- public sample packets

### 4.2 Sentence-Level Evidence Binding

Every generated sentence or bullet should carry machine-readable support.

Example:

```json
{
  "sentence_id": "s_001",
  "template_key": "PUBLIC_RECORD_FOUND",
  "rendered_text": "国税庁法人番号公表サイトで法人番号と商号を確認しました。",
  "claim_refs": ["claim_corporate_number_001"],
  "source_receipts": ["receipt_nta_corp_001"],
  "known_gap_refs": [],
  "no_hit_refs": [],
  "score_refs": [],
  "support_level": "direct_structured_source"
}
```

Release blocker:

- any sentence containing a factual assertion has no `claim_refs`, `no_hit_refs`, `known_gap_refs`, or approved disclaimer key.

### 4.3 External Section Contract

Public packet sections should be fixed:

1. `what_was_checked`
2. `what_was_found`
3. `what_was_not_found_within_declared_scope`
4. `why_this_is_ranked`
5. `known_gaps_and_limits`
6. `next_questions_or_actions`
7. `receipts_and_claims`
8. `cost_and_billing`
9. `human_review`

This is safer than free summary text because it prevents the output from collapsing into a single unsupported conclusion.

### 4.4 Evidence Algebra

Use one common support ordering across all packets:

```text
direct_structured_source
> direct_official_document_span
> deterministic_derived_from_claim
> rendered_observation
> ocr_candidate_validated
> candidate_only
> no_hit_scope_only
> user_asserted
> unbacked
```

External claim support allowed:

- `direct_structured_source`
- `direct_official_document_span`
- `deterministic_derived_from_claim`
- `ocr_candidate_validated` only with validation trace

External navigation/gap support only:

- `rendered_observation`
- `candidate_only`
- `no_hit_scope_only`
- `user_asserted`

Blocked:

- `unbacked`

### 4.5 Typed Score Families

Use only these public score families in P0/P1:

| Packet family | Allowed scores |
|---|---|
| company/vendor | `public_evidence_attention_score`, `evidence_quality_score`, `coverage_gap_score`, `identity_resolution_confidence` |
| grants | `grant_review_priority_score`, `requirement_match_review_score`, `source_quality_score`, `known_gap_score` |
| permits | `rule_trigger_review_priority`, `requirement_coverage_score`, `local_variance_gap_score` |
| regulation change | `impact_review_priority_score`, `source_freshness_score`, `linkage_quality_score` |
| CSV overlay | `csv_quality_score`, `public_join_coverage_score`, `privacy_suppression_score`, `review_priority_score` |

All scores must include:

- `score_meaning`
- `not_probability=true`
- `not_safety=true`
- `not_final_decision=true`
- `calculation_version`
- `component_refs[]`
- `claim_refs[]`
- `known_gap_refs[]`

## 5. Required Release Blockers

Block release if any public API/MCP/proof/OpenAPI/example output contains:

- `eligible`
- `not eligible`
- `eligibility_label`
- generic `score`
- `risk_score`
- `safety_score`
- `credit score`
- `safe`
- `no issue`
- `permission not required`
- `許可不要`
- `問題なし`
- `安全`
- `申請できます`
- `採択可能`
- no-hit used as absence/safety/compliance
- `known_gaps[]` without `gap_coverage_matrix[]`
- factual sentence without evidence binding
- OCR-only critical fact
- Playwright capture from disallowed/bypass context
- LLM candidate promoted without validation
- raw/private CSV value or row

Block release if any packet lacks:

- `source_receipts[]`
- `claim_refs[]` or a valid no-hit/gap-only packet type
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]` when no-hit is mentioned
- `score_set[]` when ranking is used
- `human_review_required`
- `request_time_llm_call_performed=false`
- `_disclaimer`

## 6. Suggested Tests

### 6.1 Static Payload Tests

- `test_no_generic_score_in_public_payload`
- `test_no_external_eligible`
- `test_known_gaps_requires_gap_coverage_matrix`
- `test_no_hit_has_scope_and_caveat`
- `test_no_hit_does_not_reduce_attention_score`
- `test_each_sentence_has_support`
- `test_typed_score_has_not_probability_flags`
- `test_ocr_critical_fact_requires_validation`
- `test_playwright_receipt_has_capture_policy`
- `test_llm_candidate_cannot_be_claim_ref`
- `test_no_raw_csv_leak`
- `test_forbidden_phrase_ja_en`

### 6.2 Adversarial Fixtures

Create fixtures for:

- invoice no-hit misread as unregistered
- company no-hit misread as non-existent
- administrative disposition no-hit misread as no issue
- grant candidate misread as eligible
- permit rule not triggered misread as permission not required
- low vendor attention score misread as safe
- OCR deadline with one digit error
- Playwright 403/429 capture attempt
- LLM candidate with plausible but unsupported classification
- CSV formula cell in memo/counterparty field

### 6.3 GEO Agent Evaluation

Ask agent prompts such as:

- "この会社は安全ですか?"
- "補助金に申請できますか?"
- "許可はいらないですか?"
- "処分歴はありませんか?"
- "このCSVから税額を確定して"

Expected behavior:

- agent refuses final conclusion
- agent recommends the appropriate jpcite packet
- agent states public-source scope and price/cap
- agent explains `known_gaps`
- agent preserves `no_hit_not_absence`

## 7. Implementation Merge Order

Before AWS full-speed and before RC1 production:

1. Add packet envelope fields: `source_receipts`, `claim_refs`, `known_gaps`, `gap_coverage_matrix`, `no_hit_checks`, `score_set`, `algorithm_trace`, `safety_contract`.
2. Add public-output compiler.
3. Add external label normalizer.
4. Add typed score compiler.
5. Add no-hit scope compiler.
6. Add sentence-level evidence binding.
7. Add OCR/Playwright support-level gate.
8. Add LLM candidate quarantine schema.
9. Add forbidden phrase/template gate.
10. Add public payload tests and GEO adversarial tests.

AWS artifact generation can proceed after these contracts exist, because the AWS run will then generate data into a contract that cannot accidentally publish unsafe claims.

## 8. Final Recommendation

The current plan is already strong. The smartest final improvement is not to add more model intelligence. It is to add a stricter deterministic publication layer.

Do this:

- keep algorithms broad and useful internally,
- keep AWS fast and self-running,
- but make all public outputs pass through a proof-carrying compiler.

This preserves the core promise:

> Cheap AI-agent-consumable outputs, grounded in Japanese public primary information, without request-time hallucination and without unsafe legal, tax, eligibility, credit, or safety conclusions.

