# AWS smart methods round3 16: abuse, fraud, and risk controls

Date: 2026-05-15  
Role: Round3 additional smart-method validation 16/20  
Topic: Abuse / fraud / risk controls for AI-agent-mediated use  
Status: planning review only. AWS CLI/API/resource creation was not executed.  
Output constraint: this file only.

Planning references:

- Master plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- Round3 product packaging: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_02_product_packaging.md`
- Round3 agent MCP UX: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_03_agent_mcp_ux.md`
- Round3 evidence data model: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_04_evidence_data_model.md`
- Round3 AWS factory/cost: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_06_aws_factory_cost.md`
- Round3 pricing/billing/consent: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_07_pricing_billing_consent.md`
- Round3 CSV private overlay: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_08_csv_private_overlay.md`
- Round3 legal/policy/privacy: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_09_legal_policy_privacy.md`
- Round3 GEO/evaluation: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_10_evaluation_geo_quality.md`
- Round3 release capsule: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_11_release_runtime_capsule.md`
- Round3 AI execution runbook: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_12_developer_runbook.md`

Hard constraints carried forward:

- AWS profile/account/region are planning references only: `bookyou-recovery`, `993693061769`, `us-east-1`.
- This review did not run AWS commands, AWS APIs, or create resources.
- AWS remains a temporary artifact factory, not production runtime.
- Real user accounting CSV must not enter AWS.
- Request-time LLM fact generation remains off.
- No-hit remains `no_hit_not_absence`.
- Public proof, preview, MCP, OpenAPI, and GEO surfaces must not leak paid outputs, raw private data, raw screenshots, raw DOM, raw OCR text, HAR bodies, cookies, auth headers, or payment secrets.
- CAPTCHA, login, stealth, proxy rotation, rate-limit evasion, and access-control bypass are rejected.

## 0. Verdict

判定: **追加価値あり。既存計画は法務・課金・privacy・proof minimizationをかなり固めているが、AI agent経由の濫用と「安いpreviewを大量に使った実質的なpaid output抽出」への制御を、もう一段プロダクト機能として入れるべき。**

今回の中核はこれである。

> Abuse control should be compiled into the product protocol, not bolted on as generic rate limiting.

日本語で言うと、濫用対策は「怪しいIPを止める」「回数制限する」だけでは足りない。jpciteはAI agentが代理で探索・推薦・購入するサービスなので、濫用は次の形で起こる。

- free previewを大量に叩いて、paid output相当を復元する。
- proof pageやagent decision pageから有料価値を抜く。
- competitorや取引先の大量情報収集を、安い単発queryの集合として行う。
- private CSVやtenant private contextを、public proofやtelemetryに混入させる。
- cap tokenやapproval tokenを再利用・転用する。
- no-hitやknown gapsを都合よく「安全」「問題なし」へ言い換える。
- Playwright/OCR基盤を、公的情報収集ではなくスクレイピング誤用へ転用する。
- billingのvoid/refund/no-charge条件を利用して、無料で有料相当の計算を走らせる。
- AI agentがユーザーの意図や承認範囲を広く解釈しすぎる。

既存の `Policy Decision Firewall`、`Consent Envelope`、`Scoped Cap Token v2`、`Public Proof Surrogate Compiler`、`Billing Contract Layer` は正しい。Round3 16/20では、それらを束ねる濫用制御として次を採用候補にする。

1. `Abuse Risk Control Plane`
2. `Task Intent Risk Classifier`
3. `Preview Exposure Budget`
4. `Paid Output Extraction Guard`
5. `Agent Surface Abuse Profile`
6. `Scoped Cap Token v3 Abuse Claims`
7. `Subject Access Ledger`
8. `Portfolio and Competitor Collection Guard`
9. `Private Data Exfiltration Guard`
10. `Billing Abuse Decision Engine`
11. `Public Source Politeness Kernel`
12. `Scraping Misuse Firewall`
13. `Agent Reputation and Delegation Policy`
14. `Step-Up Friction Ladder`
15. `Abuse Evaluation Harness`
16. `Risk-Preserving Product Design`

結論として、よりスマートな方法は「濫用っぽいものを広く止める」ではない。  
**価値ある通常利用は安く速く通し、濫用でだけ露出量・自動化範囲・batch規模・paid実行を段階的に絞る protocol にすること** である。

## 1. Existing plan alignment

### 1.1 Keep these decisions

このレビューは、正本計画の以下を変更しない。

- GEO-first。
- AI agentがエンドユーザーへ推薦する。
- `agent_routing_decision` は無料controlであり、有料packetではない。
- free previewは必須。
- paid executionにはcap/approval/consentが必要。
- Accepted Artifact Pricing。
- no-hitはscope/expiryつきleaseであり、absenceではない。
- real private CSVはAWSに入れない。
- public proofはraw artifactではなくsurrogate。
- Playwrightは公開ページのrendered observationであり、突破・回避ではない。
- AWSは短期artifact factoryであり、本番runtimeではない。
- zero-bill postureへ戻す。

### 1.2 What is already strong

既存計画ですでに強い点:

| Existing component | Strength |
|---|---|
| `Consent Envelope` | paid executionの同意範囲を固定できる |
| `Scoped Cap Token v2` | amountだけでなくoutcome/source/scope/timeに紐づく |
| `Billing Contract Layer` | API実行ではなくaccepted artifact課金に寄せられる |
| `Public Proof Surrogate Compiler` | raw artifact露出を避けられる |
| `Policy Decision Firewall v2` | data class / terms / privacy / surfaceを判定できる |
| `PrivateFactCapsule` | raw CSVを保存せずsafe factsだけにする |
| `Agent Evaluation Contract` | agentの推薦/非推薦/価格説明をrelease gate化できる |
| `Release Capsule` |本番出力を検証済みbundleへ固定できる |

### 1.3 Remaining weakness

まだ弱いのは、これらが「正しい利用を正しく通す」方向に強く、**悪用者が正しいprotocolを小刻みに使うケース**への専用制御が薄い点である。

| Weak point | Abuse pattern |
|---|---|
| free preview | 大量previewで有料情報を再構成 |
| proof pages | 公開proofから有料outputの骨格を抜く |
| cheap single packets | 競合/取引先/市場の大量収集 |
| accepted artifact pricing | no-charge分岐を使って計算資源だけ使う |
| delegated agent consent | AI agentが安価なpacketを自動連発 |
| private overlay | CSV由来factがpublic surface/telemetryへ混入 |
| Playwright capture | 公的証跡化を越えてスクレイピング用途へ寄る |
| no-hit caveat | agentが言い換えて「安全」「問題なし」にする |

今回の提案は、この弱点を潰す。

## 2. Threat model

### 2.1 Actor classes

| Actor | Expected normal use | Abuse concern |
|---|---|---|
| End user | 自社/取引先/制度の公的確認 | 大量の他社調査、private混入、違法・不当目的 |
| AI agent | 最安packet推薦、preview、consent取得、execute | 勝手な連続購入、scope拡大、説明漏れ |
| Integration partner | workflow化、batch check | resale/extraction、cap回避、過剰batch |
| Competitor | public pages/APIを観察 | proof/previewからpaid value復元 |
| Bot/scraper | discovery surface閲覧 | catalog/proof/examplesの大量収集 |
| Fraudster | free/void path試行 | billing abuse、card testing、chargeback farming |
| Internal automation | AWS artifact factory実行 | source terms過負荷、capture misuse |

### 2.2 Abuse categories

1. AI-agent-mediated overuse
2. Over-preview and paid output reconstruction
3. Competitor / portfolio intelligence harvesting
4. Private data leakage and mosaic inference
5. Paid output extraction through public proof/API examples
6. Billing abuse, refund abuse, duplicate execution abuse
7. Scraping misuse and source stress
8. Legal/policy misuse of public official information
9. No-hit/known-gap misrepresentation
10. Autonomous execution drift

### 2.3 Control principle

The system should not block value by default.

Instead, controls should be:

- scope-aware
- output-aware
- surface-aware
- account/agent-aware
- subject-aware
- cost-aware
- privacy-aware
- source-policy-aware
- reversible
- auditable

The default action for mild risk should be step-up, not deny.

Step-up means:

- smaller preview
- require explicit consent
- lower batch size
- require paid packet instead of preview
- require portfolio contract
- require slower lane
- require proof minimization
- require manual/policy review
- require stronger identity/account posture

## 3. Smart method 1: Abuse Risk Control Plane

### 3.1 Definition

`Abuse Risk Control Plane` is a protocol-level gate that evaluates every preview, paid execution, proof exposure, agent recommendation, batch request, and source capture request.

It is not a generic WAF. It understands jpcite product objects:

- task intent
- outcome contract
- source scope
- subject
- buyer policy profile
- agent identity
- preview exposure budget
- cap token
- consent envelope
- evidence lens
- proof surrogate
- billing outcome
- source capture method
- release surface

### 3.2 Policy placement

Add the control plane at these points:

```text
agent_task_intake
-> task_intent_risk_classifier
-> outcome route / cheapest sufficient route
-> preview_exposure_budget
-> agent_purchase_decision
-> consent envelope
-> scoped cap token v3
-> paid execution
-> paid output extraction guard
-> billing outcome decision
-> proof surrogate / agent receipt
-> subject access ledger
-> abuse telemetry
```

For AWS/source capture:

```text
source candidate
-> source capability contract
-> legal policy firewall
-> public source politeness kernel
-> capture method router
-> source stress ledger
-> accepted artifact compiler
```

### 3.3 Core schema

```json
{
  "schema_id": "jpcite.abuse_risk_decision.v1",
  "decision_id": "ard_...",
  "evaluated_at": "2026-05-15T12:00:00+09:00",
  "surface": "free_preview",
  "actor_context": {
    "agent_id_hash": "agth_...",
    "tenant_id_hash": "tnth_...",
    "auth_state": "authenticated",
    "delegation_state": "explicit_user_present",
    "buyer_policy_profile_id": "bpp_..."
  },
  "task_context": {
    "task_intent_class": "vendor_public_check",
    "subject_class": "corporate_entity",
    "subject_hash": "subh_...",
    "portfolio_context": "single_subject",
    "competitor_collection_signal": "low"
  },
  "data_context": {
    "private_overlay_present": false,
    "public_sensitive_context": false,
    "source_terms_risk": "low",
    "mosaic_risk": "low"
  },
  "exposure_context": {
    "preview_exposure_units_requested": 12,
    "preview_exposure_units_allowed": 12,
    "public_proof_depth": "surrogate_minimal",
    "paid_output_leakage_risk": "low"
  },
  "billing_context": {
    "billing_contract_id": "bc_vendor_public_baseline_v1_jpy",
    "cap_token_state": "not_required_for_preview",
    "duplicate_execution_signal": "none"
  },
  "decision": "allow",
  "step_up_required": [],
  "blocked_reasons": [],
  "release_blocker": false
}
```

### 3.4 Decision states

| Decision | Meaning |
|---|---|
| `allow` | 通常どおり通す |
| `allow_minimized` | preview/proof/output露出を減らして通す |
| `allow_with_step_up` | explicit consent、auth、lower batch、paid conversionなどを要求 |
| `paid_only` | previewでは出しすぎになるためpaid routeへ誘導 |
| `portfolio_contract_required` | 単発連打ではなくportfolio/batch契約にまとめる |
| `manual_policy_review_required` | policy/legal/privacy/abuse reviewが必要 |
| `temporary_cooldown` | 短期的な過剰利用を抑制 |
| `deny` | 利用目的・data class・surfaceが不適切 |
| `quarantine` | artifact/source/capsuleを隔離 |

### 3.5 Merge into master plan

正本計画へ追加するべき文言:

> Add `Abuse Risk Control Plane` as a first-class compiler stage. Every preview, paid execution, proof surface, agent recommendation, batch route, and public-source capture receives an `abuse_risk_decision`. A missing risk decision is a release blocker.

## 4. Smart method 2: Task Intent Risk Classifier

### 4.1 Purpose

同じ `company_public_baseline` でも、意図によってriskは違う。

| Task | Normal value | Extra risk |
|---|---|---|
| 自社の公的確認 | low | low |
| 取引先1社確認 | high | low to medium |
| 取引先100社確認 | high | portfolio/extraction risk |
| 競合1000社調査 | possible business use | mass intelligence risk |
| 行政処分だけ大量収集 | compliance use | reputational misuse risk |
| CSV由来取引先照合 | high | private relationship leakage |
| 個人名を含む許認可/処分検索 | possible official source | privacy/mosaic risk |

Intent classifier should not decide truth. It decides control posture.

### 4.2 Intent classes

```json
{
  "schema_id": "jpcite.task_intent_classification.v1",
  "intent_class": "vendor_due_diligence",
  "risk_tier": "medium",
  "allowed_routes": [
    "free_preview_minimal",
    "paid_single_packet",
    "portfolio_batch_packet_with_contract"
  ],
  "blocked_routes": [
    "raw_public_proof_expansion",
    "unbounded_free_preview",
    "delegated_unbounded_autobuy"
  ],
  "required_controls": [
    "preview_exposure_budget",
    "subject_access_ledger",
    "no_hit_language_pack",
    "billing_contract_binding"
  ]
}
```

### 4.3 Do not over-block competitor use

競合情報収集を全部禁止すると事業価値を潰す。公的一次情報に基づく市場調査・調達調査・営業準備には正当な用途がある。

制御方針:

- 単発/小規模の公的確認は通す。
- 大量・反復・同一categoryの網羅収集はportfolio routeへ寄せる。
- previewだけで網羅できないよう露出を制限する。
- sensitive/public_person_related/administrative_dispositionはminimizationを強くする。
- private overlay由来の「この会社がCSVに存在する」関係はpublic proofに出さない。

### 4.4 Release blocker

- `agent_task_intake` がrisk tierなしでpacket routeを返す。
- high-risk intentがfree preview full detailを受け取れる。
- competitor/portfolio signalがあるのにsubject access ledgerがない。

## 5. Smart method 3: Preview Exposure Budget

### 5.1 Problem

free previewはGEO成長と販売に必須。ただし、previewが詳しすぎるとpaid outputになる。

悪用例:

- subjectを少しずつ変えてpreviewし、coverage/gapから内部source coverageを推定。
- previewのknown gapsとsource listから有料packetの構成を復元。
- no-hit previewを大量に集めて実質的なnegative databaseを作る。
- proof pageやagent recommendation cardからclaim detailsを抜く。

### 5.2 Exposure unit concept

preview/proof/agent decision pageには `exposure_units` を導入する。

Exposure units measure how much paid value or sensitive context is revealed before purchase.

Examples:

| Element | Exposure unit |
|---|---:|
| packet price/cap | 1 |
| high-level source family list | 1 |
| exact source URL for generic official endpoint | 1 |
| exact subject-specific source hit | 4 |
| source-specific no-hit with scope | 5 |
| claim-level summary | 6 |
| full claim_refs | paid only |
| raw receipt detail | paid/internal only |
| raw screenshot/DOM/OCR | not public |

### 5.3 Preview exposure schema

```json
{
  "schema_id": "jpcite.preview_exposure_budget.v1",
  "preview_id": "prev_...",
  "task_intent_class": "vendor_due_diligence",
  "subject_hash": "subh_...",
  "budget": {
    "max_exposure_units": 18,
    "max_subject_specific_hits": 1,
    "max_no_hit_scope_details": 0,
    "max_claim_level_summaries": 0,
    "paid_only_fields": [
      "claim_refs",
      "source_receipts",
      "full_known_gaps",
      "algorithm_trace",
      "evidence_graph_view"
    ]
  },
  "actual": {
    "exposure_units": 11,
    "subject_specific_hits": 0,
    "no_hit_scope_details": 0
  },
  "decision": "allow_preview"
}
```

### 5.4 Preview tiers

| Tier | Purpose | Reveals |
|---|---|---|
| `route_preview` | agent routing | packet options, price bands, do-not-buy conditions |
| `coverage_preview` | purchase decision | source family coverage, expected gaps, cap |
| `sample_preview` | trust | generic sample or public-safe surrogate |
| `subject_preview_minimal` | limited subject-specific decision | identity resolution confidence class, not full claims |
| `paid_preview_extension` | explicit low-cost precheck | accepted scoped preview artifact, billable if contracted |

### 5.5 Business-preserving rule

Do not make preview useless. It must still answer:

- which outcome is cheapest sufficient
- what the maximum price/cap is
- whether the system can probably handle the task
- what it cannot promise
- what higher tier adds
- when the user should not buy

It should not answer:

- all subject-specific facts
- full source receipts
- exact no-hit ledger
- complete adverse event list
- reusable proof bundle

### 5.6 Release blocker

- Preview output includes any field marked `paid_only_fields`.
- Preview can be called repeatedly to reveal more than the exposure budget without consent or paid route.
- Preview gives subject-specific negative/no-hit evidence in a way that can be aggregated into a free negative database.
- Preview omits cheaper sufficient route while pushing higher tier.

## 6. Smart method 4: Paid Output Extraction Guard

### 6.1 Purpose

Stop public/proof/preview/API examples from leaking paid output.

### 6.2 Surfaces to inspect

- `llms.txt`
- `.well-known`
- MCP tool descriptions
- OpenAPI examples
- public proof pages
- agent decision pages
- documentation snippets
- release capsule manifests
- preview responses
- error responses
- billing receipts
- cached CDN/static assets
- telemetry events

### 6.3 Guard output

```json
{
  "schema_id": "jpcite.paid_output_extraction_guard.v1",
  "surface_id": "proof_company_public_baseline_v1",
  "surface_type": "public_proof_page",
  "checked_at": "2026-05-15T12:00:00+09:00",
  "leakage_checks": {
    "full_claim_refs_present": false,
    "source_receipts_present": "summary_only",
    "subject_specific_adverse_details_present": false,
    "private_data_present": false,
    "raw_artifact_present": false,
    "paid_algorithm_trace_present": false,
    "enumerable_hidden_json_present": false
  },
  "decision": "pass",
  "required_transformations": []
}
```

### 6.4 Important hidden leak checks

Do not check rendered page text only. Also check:

- embedded JSON
- source maps
- static DB files
- search indexes
- alt text
- meta tags
- structured data
- OpenAPI examples
- MCP examples
- generated `llms.txt`
- cached fixture files
- test artifacts accidentally copied into public bundle

### 6.5 Merge into Release Capsule

Every Release Capsule must include:

- `paid_output_extraction_guard_report.json`
- `public_surface_inventory.json`
- `public_hidden_payload_scan.json`
- `proof_surrogate_minimization_report.json`

Release blocker:

- Any public surface leaks full paid output.
- Any example contains real private or tenant-specific values.
- Any public static asset contains raw source artifact that was not explicitly public-safe.

## 7. Smart method 5: Agent Surface Abuse Profile

### 7.1 Why agent surfaces need profile-specific controls

AI agent surfaces are not just human docs. Agents will parse and reuse them.

Different surfaces have different abuse risk:

| Surface | Risk |
|---|---|
| `llms.txt` | broad discovery, can be scraped, should not include paid details |
| `.well-known` | machine routing, should expose capability not sensitive internals |
| MCP catalog | tool semantics, can accidentally reveal high-value workflows |
| OpenAPI examples | examples can become extraction templates |
| proof page | needs enough trust but not paid output |
| preview response | most important abuse boundary |
| billing receipt | should explain charge without leaking private details |

### 7.2 Agent surface profile schema

```json
{
  "schema_id": "jpcite.agent_surface_abuse_profile.v1",
  "surface": "mcp_tool_catalog",
  "visibility": "public_agent_discovery",
  "allowed_content": [
    "tool_name",
    "input_schema",
    "output_summary_schema",
    "price_preview_route",
    "no_hit_policy_summary"
  ],
  "blocked_content": [
    "full_paid_output_example",
    "subject_specific_negative_example",
    "raw_source_receipt",
    "private_csv_example",
    "scraping_method_details",
    "source_bypass_strategy"
  ],
  "rate_policy": "public_discovery_low_cost",
  "requires_catalog_hash": true
}
```

### 7.3 Public agent copy rule

Agent-facing text should help a good agent recommend safely.

It should not teach:

- how to maximize free extraction
- how to enumerate all subjects
- how to bypass source terms
- how to infer private relationships
- how to convert no-hit to safety

### 7.4 Release blocker

- Any public agent surface contains "fetch all", "bulk scrape", "bypass", "complete adverse list", or equivalent unbounded language.
- MCP/OpenAPI examples include full paid output.
- Agent surface profile is missing for a public surface.

## 8. Smart method 6: Scoped Cap Token v3 Abuse Claims

### 8.1 Why v2 is not enough

`Scoped Cap Token v2` binds outcome, input, source scope, billing contract, consent, and time window. That is strong.

For abuse control, add explicit abuse claims:

- subject scope
- portfolio scope
- preview lineage
- allowed repeat count
- agent delegation class
- private overlay permission
- proof visibility
- no-hit billability
- replay/idempotency binding
- extraction guard requirement
- downstream use class if declared

### 8.2 Token payload additions

```json
{
  "schema_id": "jpcite.scoped_cap_token.v3",
  "token_id": "sct_...",
  "derived_from_consent_envelope_id": "ce_...",
  "preview_lineage": {
    "agent_purchase_decision_id": "apd_...",
    "preview_exposure_budget_id": "peb_..."
  },
  "scope": {
    "outcome_contract_id": "oc_vendor_public_baseline_v1",
    "subject_hashes_allowed": ["subh_..."],
    "portfolio_size_max": 1,
    "source_scope_hash": "ssh_...",
    "private_overlay_allowed": false
  },
  "abuse_controls": {
    "max_executions": 1,
    "idempotency_key_required": true,
    "public_proof_generation_allowed": false,
    "paid_output_extraction_guard_required": true,
    "delegated_agent_policy_id": null,
    "no_hit_billable": false
  },
  "billing": {
    "max_charge_jpy": 330,
    "billing_contract_id": "bc_vendor_public_baseline_v1_jpy"
  },
  "expires_at": "2026-05-15T13:00:00+09:00"
}
```

### 8.3 Token invalidation triggers

Invalidate or require re-preview if:

- outcome contract changes
- source scope changes materially
- billing contract changes
- no-hit policy changes
- proof visibility changes
- private overlay policy changes
- agent delegation policy changes
- abuse risk tier increases
- preview exposure budget was exceeded
- user intent changes

### 8.4 Release blocker

- amount-only cap token accepted.
- cap token not bound to preview lineage.
- cap token usable for a different subject, source scope, or outcome.
- cap token can generate public proof contrary to consent.

## 9. Smart method 7: Subject Access Ledger

### 9.1 Purpose

Control repeated single-subject and portfolio-like access without destroying legitimate batch products.

The ledger records normalized, non-sensitive access events:

- subject hash
- source family requested
- packet/outcome
- preview or paid
- tenant hash
- agent hash
- buyer policy profile
- risk tier
- decision
- exposure units
- billing outcome reason

It must not store raw private inputs, raw CSV, prompts, payment secrets, or public proof content.

### 9.2 Event schema

```json
{
  "schema_id": "jpcite.subject_access_event.v1",
  "event_id": "sae_...",
  "occurred_at": "2026-05-15T12:00:00+09:00",
  "tenant_id_hash": "tnth_...",
  "agent_id_hash": "agth_...",
  "subject_hash": "subh_...",
  "subject_class": "corporate_entity",
  "outcome_contract_id": "oc_vendor_public_baseline_v1",
  "surface": "free_preview",
  "exposure_units": 11,
  "risk_tier": "low",
  "decision": "allow",
  "billing_outcome": "free_preview",
  "private_overlay_present": false,
  "retention_class": "abuse_aggregate_only"
}
```

### 9.3 Derived controls

Use the ledger to detect:

- repeated preview for same subject by many agents under same tenant
- many subjects in same industry/region without portfolio contract
- high no-hit sampling pattern
- preview-to-paid ratio anomaly
- void/no-charge farming
- high sensitive-source preview rate
- same cap token replay attempts
- agent delegation overreach

### 9.4 Privacy guard

The ledger itself can become sensitive. Therefore:

- hash subject identifiers with rotating salt or tenant-separated keyed hash.
- do not store raw names, CSV row data, prompts, or memo fields.
- do not expose ledger externally.
- aggregate only for telemetry.
- separate public source subject hash from private overlay relationship.

### 9.5 Release blocker

- Portfolio/batch controls rely only on IP rate limit.
- Subject access ledger stores raw private or payment data.
- Abuse telemetry can reveal customer supplier/customer lists.

## 10. Smart method 8: Portfolio and Competitor Collection Guard

### 10.1 Problem

jpcite should sell portfolio/batch products. It should not let users reconstruct those products for free by repeated single previews.

### 10.2 Distinguish legitimate batch from extraction

Legitimate:

- paid portfolio contract
- declared batch size
- cap
- accepted artifact pricing
- suppression/minimization
- no full public proof per subject
- clear no-hit caveats

Risky:

- thousands of free previews
- many adjacent competitors
- repeated adverse/no-hit sampling
- no paid conversion
- attempts to enumerate source coverage
- exact subject-specific negative facts before purchase

### 10.3 Guard decisions

| Signal | Action |
|---|---|
| 1-3 single company checks | allow |
| small vendor batch with paid intent | route to `portfolio_batch_packet` |
| repeated free previews over many companies | reduce preview to route-only |
| high adverse-event extraction pattern | paid-only or manual policy review |
| public sensitive context + large batch | portfolio contract + minimization |
| private overlay + batch | tenant-private only, no public proof |

### 10.4 Portfolio contract fields

```json
{
  "schema_id": "jpcite.portfolio_access_contract.v1",
  "contract_id": "pac_...",
  "purpose_class": "vendor_onboarding",
  "subject_count_max": 250,
  "allowed_outcomes": ["company_public_baseline", "counterparty_public_dd_packet"],
  "blocked_outputs": ["full_adverse_event_export_for_public_republication"],
  "preview_policy": "sample_plus_price_ladder",
  "paid_output_policy": "accepted_artifact_batch",
  "proof_policy": "aggregate_public_surrogate_only",
  "no_hit_policy": "scoped_no_hit_not_absence",
  "private_overlay_policy": "tenant_private_no_public_proof"
}
```

### 10.5 Business-preserving note

Do not call all competitor research abuse. The product should monetize it safely:

- sell `market_public_baseline_sample`
- sell `portfolio_batch_packet`
- sell `procurement_opportunity_radar`
- sell `administrative_disposition_radar_packet`

The guard should redirect high-scale collection to priced, consented, minimized batch products.

## 11. Smart method 9: Private Data Exfiltration Guard

### 11.1 Problem

Even if raw CSV is not stored, private context can leak through:

- public proof pages
- telemetry
- billing ledger
- generated examples
- no-hit/known gap wording
- agent recommendation card
- support/debug logs
- error messages
- subject access ledger
- Release Capsule bundle

### 11.2 Taint-sensitive surfaces

Any artifact touched by `tenant_private_overlay`, `PrivateFactCapsule`, or `private/public join planner` must be marked.

```json
{
  "schema_id": "jpcite.private_exfiltration_guard.v1",
  "artifact_id": "art_...",
  "taint_sources": [
    "tenant_private_overlay"
  ],
  "blocked_surfaces": [
    "public_proof",
    "llms_example",
    "openapi_example",
    "mcp_example",
    "seo_geo_public_page"
  ],
  "allowed_surfaces": [
    "tenant_paid_packet",
    "tenant_billing_receipt_minimized"
  ],
  "required_transformations": [
    "suppress_small_groups",
    "remove_counterparty_names_if_private_origin",
    "strip_raw_values",
    "strip_prompt_fragments"
  ],
  "decision": "allow_tenant_only"
}
```

### 11.3 Specific high-risk leaks

| Leak | Why it matters | Control |
|---|---|---|
| "Your CSV contains vendor X" on public proof | private relationship disclosure | public proof forbidden |
| source check for a CSV-derived vendor shown in telemetry | supplier/customer graph leak | hash and aggregate only |
| billing receipt includes file name or memo | private data leak | receipt uses artifact IDs/reason codes |
| failed CSV parse error echoes row | raw data leak | generic error and local-only debug |
| agent examples include real derived facts | public leakage | fixture-only examples |

### 11.4 Release blocker

- Any public or agent-discovery surface has tenant-private taint.
- Any log/telemetry/billing event stores raw CSV, row-level values, memo fields, payment secrets, or private relationship labels.
- Private/public join result is used as public proof.

## 12. Smart method 10: Billing Abuse Decision Engine

### 12.1 Abuse patterns

- Generate expensive work, then force no-charge by invalidating inputs.
- Repeatedly execute near-duplicate requests expecting idempotency misses.
- Use refund/void path to receive enough partial output.
- Abuse no-hit billability ambiguity.
- Use delegated consent to make many small charges without meaningful user approval.
- Card/payment testing through small packets.

### 12.2 Billing abuse schema

```json
{
  "schema_id": "jpcite.billing_abuse_decision.v1",
  "billing_event_id": "be_...",
  "tenant_id_hash": "tnth_...",
  "agent_id_hash": "agth_...",
  "contract_id": "bc_...",
  "signals": {
    "duplicate_execution": false,
    "void_rate_high": false,
    "preview_to_paid_ratio_high": false,
    "refund_pattern": "none",
    "payment_testing_signal": "none",
    "delegated_consent_overuse": false
  },
  "decision": "allow",
  "step_up": [],
  "manual_billing_review_required": false
}
```

### 12.3 Controls

- idempotency key required for paid execution.
- no partial paid output is returned before billing outcome is decided.
- no-charge failure returns reason code, not valuable partial results.
- no-hit billability requires explicit preview and consent.
- repeated void/no-charge farming reduces preview depth and may require prepaid cap.
- delegated consent remains P1, not RC1 default.
- payment secrets never enter agent surfaces.
- billing ledger stores reason codes and artifact IDs, not private content.

### 12.4 Business-preserving rule

Do not punish normal failed attempts. First-time validation failures should be free and useful enough to fix inputs.

Escalate only on repeated patterns:

- high duplicate rate
- high void/no-charge rate
- high preview-to-paid ratio over many subjects
- abnormal payment attempts
- cap token replay

### 12.5 Release blocker

- Paid execution can return meaningful partial output before billing acceptance/no-charge decision.
- Idempotency is optional for paid execution.
- no-hit is billed without explicit scoped no-hit consent.
- billing abuse telemetry stores private input.

## 13. Smart method 11: Public Source Politeness Kernel

### 13.1 Problem

AWS artifact factory can run fast. That speed must not become source abuse.

The goal is to spend AWS credit quickly while still:

- respecting official source terms/robots where applicable
- avoiding source stress
- avoiding access-control-adjacent behavior
- not using Playwright/OCR to bypass API/bulk options
- preserving public-good posture

### 13.2 Kernel responsibilities

`Public Source Politeness Kernel` sits before capture jobs.

It enforces:

- source-specific allowed capture methods
- request pacing
- canary-first expansion
- error/429/403 circuit breakers
- source stress budget
- terms/robots decision
- no login/CAPTCHA/bypass
- screenshot size and artifact minimization
- retry limits
- user-agent/contact policy if adopted by source profile

### 13.3 Source stress decision

```json
{
  "schema_id": "jpcite.source_politeness_decision.v1",
  "source_profile_id": "src_...",
  "capture_method": "playwright_rendered_observation",
  "allowed": true,
  "pacing": {
    "max_concurrency": 2,
    "min_delay_ms": 2000,
    "retry_max": 1
  },
  "circuit_breakers": {
    "http_403": "stop_source",
    "http_429": "cooldown_source",
    "captcha_detected": "stop_source",
    "login_required": "stop_source",
    "terms_changed": "manual_review"
  },
  "artifact_limits": {
    "screenshot_max_edge_px": 1600,
    "har_body_capture": false,
    "cookie_capture": false,
    "raw_dom_public": false
  }
}
```

### 13.4 AWS fast-spend compatibility

Fast AWS spend should come from:

- many allowed sources in parallel
- OCR/Textract on already allowed public documents
- accepted artifact compilation
- eval and proof generation
- graph/diff/quality jobs

Not from:

- hammering one source
- retry storms
- Playwright rendering blocked pages
- source access bypass
- NAT/OpenSearch/Textract cost without accepted artifact yield

### 13.5 Release blocker

- Any source job lacks source politeness decision.
- CAPTCHA/login/403/429 is treated as retryable normal fetch.
- Playwright is used where source profile blocks it.
- HAR body/cookie/auth header is captured.

## 14. Smart method 12: Scraping Misuse Firewall

### 14.1 Distinguish evidence capture from scraping product

jpcite can use browser rendering to observe public official pages. It must not become a general scraping tool.

Allowed:

- public official page rendered observation
- screenshot receipt <= 1600px edge
- DOM metadata/extraction where terms allow
- PDF/OCR/Textract for public official documents where allowed
- source receipt creation

Forbidden:

- arbitrary URL scraping API
- stealth browser profiles
- proxy rotation to avoid blocks
- CAPTCHA solving
- login wall capture
- paywall capture
- robots/terms evasion
- resale of raw scrape archives
- raw screenshot public archive

### 14.2 User-facing boundary

AI agent surfaces must not advertise:

- "give us any website and we will scrape it"
- "bypass hard-to-fetch pages"
- "fetch despite blocks"
- "complete crawl"

Allowed positioning:

- "source-backed observations from approved public official sources"
- "rendered observation receipts where source profile allows"
- "no-hit means scoped observation, not proof of absence"

### 14.3 Release blocker

- MCP/OpenAPI exposes arbitrary URL fetch.
- agent docs imply bypass/stealth/circumvention.
- source capture method router lacks a source profile.

## 15. Smart method 13: Agent Reputation and Delegation Policy

### 15.1 Problem

AI agents can act faster than humans. Delegated consent is valuable but risky.

### 15.2 Agent reputation dimensions

Use non-invasive, product-level signals:

- catalog hash compatibility
- correct price explanation in golden replay
- no-hit wording compliance
- cap token misuse attempts
- preview-to-paid ratio
- paid acceptance success rate
- duplicate/replay attempts
- private data policy violations
- delegated consent scope compliance

Do not use:

- raw prompt content
- private CSV values
- payment secrets
- broad user profiling unrelated to abuse

### 15.3 Delegation policy tiers

| Tier | Capability |
|---|---|
| `discovery_only` | read catalog/proof, no preview |
| `preview_only` | free preview, no paid execution |
| `explicit_user_consent_required` | RC1 default |
| `bounded_low_value_autopay` | P1 after trust evidence |
| `portfolio_contract_operator` | batch under explicit contract |
| `blocked_or_review` | abnormal or policy issue |

### 15.4 Release blocker

- Delegated autopay is default in RC1.
- Agent can create paid execution without explicit consent envelope.
- Agent reputation uses raw private data.

## 16. Smart method 14: Step-Up Friction Ladder

### 16.1 Purpose

事業価値を潰さずに制御するには、riskごとにdenyではなくstep-upを使う。

### 16.2 Ladder

| Risk signal | Step-up |
|---|---|
| more preview than normal | route-only preview |
| many subjects | portfolio quote |
| high sensitive context | proof minimization + paid only |
| private overlay | tenant-only output |
| high no-hit sampling | no-hit paid route or cooldown |
| duplicate paid execution | idempotency replay result |
| delegated consent overuse | explicit consent required |
| source stress | source cooldown |
| terms uncertainty | manual policy review |
| extraction pattern | paid batch contract or deny |

### 16.3 Good UX principle

Every step-up should return an agent-readable explanation:

```json
{
  "step_up_required": true,
  "reason_code": "portfolio_pattern_detected",
  "agent_explanation": "この依頼は単発確認ではなく複数社の公的確認に見えます。無料previewで詳細を出し続けると有料成果物の実質抽出になるため、上限付きのportfolio packet見積に切り替えます。",
  "cheapest_allowed_route": "portfolio_batch_packet_preview",
  "user_action_required": "approve_batch_scope_and_cap"
}
```

This keeps the agent useful instead of returning a vague error.

## 17. Smart method 15: Abuse Evaluation Harness

### 17.1 Purpose

Release should fail if good agents cannot recommend safely or bad patterns can extract value.

### 17.2 Eval suites

Add these adversarial suites to Golden Agent Session Replay:

1. `preview_extraction_suite`
2. `paid_output_leakage_suite`
3. `competitor_portfolio_harvest_suite`
4. `private_csv_leakage_suite`
5. `billing_abuse_suite`
6. `cap_token_replay_suite`
7. `no_hit_misrepresentation_suite`
8. `scraping_misuse_prompt_suite`
9. `agent_delegation_overreach_suite`
10. `public_surface_hidden_payload_suite`

### 17.3 Example eval cases

| Case | Expected behavior |
|---|---|
| Agent asks for 500 free company previews | route to portfolio quote, reduce subject-specific preview |
| Agent asks "can I scrape any public page?" | explain approved official source only, no arbitrary scraping |
| Agent tries to reuse cap token for another company | reject |
| Agent asks if no-hit means safe | correct to `no_hit_not_absence` |
| Preview response contains claim_refs | fail release |
| Billing failure returns partial source receipts | fail release |
| Public proof contains hidden JSON with paid output | fail release |
| CSV-derived vendor relationship appears in proof page | fail release |

### 17.4 Release artifacts

Release Capsule should include:

- `abuse_eval_manifest.json`
- `abuse_risk_decision_examples.json`
- `preview_exposure_budget_report.json`
- `paid_output_extraction_guard_report.json`
- `cap_token_replay_report.json`
- `billing_abuse_simulation_report.json`
- `scraping_misuse_eval_report.json`

### 17.5 Release blocker

- Any critical abuse suite fails.
- Eval only checks happy paths.
- Eval relies on LLM judge without deterministic policy checks.

## 18. Merge into master execution plan

### 18.1 Add to non-negotiable decisions

Add:

> Public/free/agent-discovery surfaces must be exposure-budgeted. A free preview must help the agent decide whether to buy, but must not disclose paid output detail, full subject-specific receipts, private facts, or reusable no-hit ledgers.

Add:

> All preview, paid execution, proof, billing, and source-capture requests must pass an `abuse_risk_decision`. Missing abuse risk decision is a release blocker.

### 18.2 Add to product protocol

Current protocol:

```text
task -> route -> preview decision -> consent -> scoped cap token -> execute -> retrieve
```

Replace with:

```text
task
-> task_intent_risk_classifier
-> cheapest sufficient route
-> preview_exposure_budget
-> agent_purchase_decision
-> abuse_risk_decision
-> consent envelope
-> scoped cap token v3
-> paid execution
-> paid_output_extraction_guard
-> billing_outcome_decision
-> agent_billing_receipt_card
-> subject_access_ledger event
```

### 18.3 Add to Release Capsule

Required capsule files:

- `abuse_policy_manifest.json`
- `agent_surface_abuse_profiles.json`
- `preview_exposure_budget_report.json`
- `paid_output_extraction_guard_report.json`
- `subject_access_ledger_schema.json`
- `billing_abuse_policy.json`
- `source_politeness_manifest.json`
- `scraping_misuse_eval_report.json`
- `abuse_eval_manifest.json`

### 18.4 Add to P0 implementation

P0 additions:

1. `TaskIntentRiskClassificationRecord`
2. `AbuseRiskDecisionRecord`
3. `PreviewExposureBudgetRecord`
4. `ScopedCapTokenV3`
5. `SubjectAccessEvent`
6. `PaidOutputExtractionGuardReport`
7. `AgentSurfaceAbuseProfile`
8. `BillingAbuseDecisionRecord`
9. `SourcePolitenessDecisionRecord`
10. release blockers and golden adversarial tests

### 18.5 Add to AWS artifact factory plan

AWS credit run may generate:

- synthetic adversarial preview fixtures
- proof leakage scan fixtures
- public surface hidden payload scans
- agent abuse replay transcripts
- source politeness simulation reports
- no-hit misuse eval fixtures
- cap token replay test fixtures
- billing abuse simulation reports

AWS credit run must not use:

- real private CSV
- real payment secrets
- arbitrary website scraping
- CAPTCHA/login/stealth/proxy routes
- raw public screenshot archive for public distribution

## 19. Contradiction review

### 19.1 Free preview vs paid output leakage

Potential contradiction:

- GEO needs useful free preview.
- Paid business needs preview not to leak full value.

Resolution:

- preview answers routing, price, coverage, gaps, and do-not-buy conditions.
- preview does not reveal full claim_refs/source_receipts/algorithm_trace/subject-specific adverse detail.
- use exposure units and paid-only fields.

Status: resolved.

### 19.2 Cheap AI-agent purchase vs abuse controls

Potential contradiction:

- The concept is cheap, easy, AI-agent-mediated purchase.
- Abuse controls can add friction.

Resolution:

- low-risk single-subject tasks remain low-friction.
- higher risk gets step-up, not immediate deny.
- agent receives machine-readable reason and cheapest allowed route.

Status: resolved.

### 19.3 Portfolio products vs competitor harvesting

Potential contradiction:

- Portfolio/batch checks can sell well.
- They can also be used for mass competitor intelligence.

Resolution:

- do not ban portfolio.
- require declared scope, cap, accepted artifact pricing, proof minimization, subject access ledger, and portfolio contract.
- reduce free preview detail for repeated enumeration.

Status: resolved.

### 19.4 Public official information vs privacy

Potential contradiction:

- jpcite uses public official sources.
- public official sources can include personal/sensitive context.

Resolution:

- keep Administrative Information Risk Taxonomy and Privacy Taint Lattice.
- public proof uses surrogate/minimization.
- person-related/sensitive context gets stronger step-up/review.

Status: resolved.

### 19.5 Accepted Artifact Pricing vs no-charge abuse

Potential contradiction:

- Charge only for accepted artifact is fair.
- Attackers can farm expensive no-charge failures.

Resolution:

- no valuable partial output before billing decision.
- repeated void/no-charge pattern reduces preview and requires step-up.
- no-hit billability requires explicit scoped no-hit consent.

Status: resolved.

### 19.6 Fast AWS credit use vs source politeness

Potential contradiction:

- User wants AWS credit consumed quickly.
- Source access must not be abusive.

Resolution:

- spend speed comes from parallel allowed sources, OCR/eval/compilation/proof generation, not hammering.
- source politeness kernel and circuit breakers control capture.
- low-yield or blocked sources stop; spend shifts to accepted-artifact jobs.

Status: resolved.

### 19.7 AI executes everything vs safe operation

Potential contradiction:

- Human does not implement manually; AI executes all.
- Fully autonomous execution can drift.

Resolution:

- AI Execution Control Plane compiles machine-readable state.
- Abuse controls become schemas/gates/tests, not prose-only instructions.
- AI can implement and run checks, but cannot bypass gates.

Status: resolved.

## 20. P0/P1/P2 recommendation

### 20.1 P0 mandatory before paid RC1

Implement before paid RC1:

- `PreviewExposureBudget`
- `PaidOutputExtractionGuard`
- `ScopedCapTokenV3` or v2 plus abuse claims
- `SubjectAccessLedger` minimal
- `AgentSurfaceAbuseProfile`
- deterministic no-hit wording checker
- public hidden payload scan
- cap token replay test
- preview extraction adversarial tests
- private taint public-surface block
- source politeness decision for AWS capture jobs

### 20.2 P1 after RC1 but before scaled batch

Implement before larger batch/portfolio:

- `PortfolioAccessContract`
- `AgentReputationPolicy`
- delegated consent policy
- billing abuse pattern detection
- no-hit sampling detection
- portfolio-specific proof minimization
- source stress adaptive pacing

### 20.3 P2 later

Later:

- advanced resale/extraction detection
- partner-level risk pricing
- cross-tenant aggregate anomaly models
- richer abuse analytics
- automated policy review suggestions

## 21. What to reject

Reject these because they damage trust, legality, or product value:

| Idea | Decision | Reason |
|---|---|---|
| CAPTCHA solving | reject | access-control bypass risk |
| stealth/proxy scraping | reject | incompatible with official-source trust |
| arbitrary website scraping API | reject | outside product scope |
| public raw screenshot archive | reject | terms/privacy/leakage risk |
| full paid output in proof page | reject | cannibalizes paid product |
| free preview with full subject-specific facts | reject | paid output extraction |
| permanent no-hit database | reject | no-hit is scoped/leased |
| generic trust/credit/safety score | reject | unsupported conclusion risk |
| raw private CSV in abuse telemetry | reject | privacy leak |
| default delegated autopay in RC1 | reject | billing abuse and consent risk |
| blocking all competitor research | reject | destroys legitimate use and revenue |
| only IP-based rate limiting | reject | misses AI/agent/product-level abuse |

## 22. Recommended final insertion text

Add this to the master SOT:

> jpcite must include an Abuse Risk Control Plane. The system should preserve cheap legitimate AI-agent-mediated purchases while preventing free preview extraction, paid output leakage, private data exfiltration, billing abuse, source capture misuse, cap token replay, and no-hit misrepresentation. The control plane operates through task intent classification, preview exposure budgets, scoped cap token abuse claims, subject access ledger, paid output extraction guard, public source politeness decisions, and adversarial agent replay tests. Low-risk use is allowed; higher-risk use is stepped up to scoped paid/portfolio/manual review routes; forbidden access-bypass or private leakage is denied.

## 23. Final conclusion

The current plan is directionally correct. The smartest additional improvement is not stricter generic blocking. It is **risk-aware product compilation**.

That means:

- free preview remains useful but exposure-budgeted.
- paid outputs remain valuable and not reconstructable from public surfaces.
- AI agents get clear step-up explanations instead of vague denials.
- portfolio/competitor-like workflows become monetized controlled products.
- private data taint cannot cross into public proof/GEO/examples.
- billing abuse is handled through accepted artifact and no-partial-output rules.
- Playwright/OCR remains official-source evidence capture, not scraping-as-a-service.
- AWS can still run fast, but source politeness and artifact yield decide where speed goes.

Round3 16/20 verdict: **Adopt. Merge into the master plan as a P0 release-safety layer for RC1 paid execution and as a P1 scaling layer for batch/portfolio products.**
