# AWS Smart Methods Round3 15/20: Trust, Accountability, and UI

Date: 2026-05-15

Scope: Trust Receipt, Agent Trust Manifest, Release Legal Attestation, Zero-AWS Posture Attestation, agent_decision_page, trust/accountability UI, machine-readable trust surfaces, AI-executed implementation plan

AWS command status: **No AWS CLI/API/resource operation was executed.**

Output constraint: This document is the only intended output for this review.

## 1. Executive conclusion

The current plan has strong trust primitives, but they are still described as several separate artifacts:

- `Trust Receipt`
- `Agent Trust Manifest`
- `Release Legal Attestation`
- `Zero-AWS Posture Attestation`
- `agent_decision_page`
- `Capability Matrix Manifest`
- `Release Capsule`
- `Policy Decision Firewall`

The smarter method is to compile all of them from one canonical trust model.

Adopt:

> `Trust Surface Compiler`

This is a compiler that takes the active Release Capsule, policy decisions, evidence lenses, billing rules, evaluation reports, and zero-AWS state, then emits every human-facing and agent-facing trust surface from the same source.

This avoids the most dangerous failure mode:

> The UI says one thing, the MCP/OpenAPI manifest says another, and the legal/zero-AWS attestation says a third thing.

In Japanese:

> 信頼性を「画面上の説明」や「バッジ」にせず、Release Capsuleから自動生成される機械可読・人間可読の同一ソース由来のtrust surfaceにする。

## 2. Decision

判定: **追加価値あり。正本計画へマージ推奨。**

ただし、次の条件付きで採用する。

1. `trust score` という単一スコアは作らない。
2. 「安全」「問題なし」「公的に保証」などの誤認表現は禁止する。
3. Trust UIは有料成果物の中身を漏らさない。
4. Release Legal Attestationは法律意見ではなく、公開・利用ポリシーの判定結果として表示する。
5. Zero-AWS Posture AttestationはAWS factory teardown後だけ有効にする。
6. AIが実装実行する前提で、trust生成・検証・release gateは自動化する。
7. エンドユーザー向けUIとAI agent向けJSONは同一manifestから生成する。

## 3. Why another trust layer is needed

既存計画は、以下の点ではかなり強い。

- source receipt
- claim refs
- known gaps
- no-hit caveat
- release capsule
- legal attestation
- zero-bill cleanup
- agent decision page
- capability matrix
- golden agent replay

しかし、信頼機能が分散したままだと、本番で次の問題が起きる。

| Problem | Why it matters |
|---|---|
| UI drift | 画面表示とMCP/OpenAPIが違うことを言う |
| trust badge risk | 「信頼済み」「安全」などの誤認表現になりやすい |
| agent confusion | AI agentが何を推薦してよいか判断できない |
| paid leakage | proof pageが有料成果物を漏らす |
| stale legal status | 規約変更・撤回後も古い証跡が使われる |
| zero-AWS ambiguity | AWS削除済みなのか、まだfactoryが走っているのか曖昧 |
| accountability gap | 誰が、どのreleaseで、何を根拠に公開したか追えない |
| human-operation dependency | 人間が毎回読んで判断しないと公開できない |

The answer is not to add more warning text.

The answer is to compile trust.

## 4. New smart method: Trust Surface Compiler

### 4.1 Definition

`Trust Surface Compiler` is a deterministic compiler.

Input:

- Release Capsule manifest
- Evidence Lens manifests
- Trust Receipt records
- Agent Trust Manifest
- Release Legal Attestation
- Zero-AWS Posture Attestation
- Billing Contract Layer
- Policy Decision Firewall result
- Privacy Taint Lattice result
- Golden Agent Session Replay report
- Capability Matrix Manifest
- Surface Parity Contract result

Output:

- human-readable trust UI
- AI-readable trust JSON
- agent decision page
- packet trust card
- proof surrogate
- release attestation page
- `.well-known/jpcite-trust.json`
- MCP/OpenAPI trust metadata
- trust diff between releases
- release blocker report

### 4.2 Core principle

All trust surfaces must be generated from the same capsule-bound data.

No hand-written UI copy should be allowed to override:

- no-hit meaning
- source scope
- legal boundary
- privacy boundary
- price/cap
- release status
- zero-AWS status
- known gaps
- forbidden claims

### 4.3 Why this is smarter

It turns trust from a marketing layer into an executable contract.

The AI agent can verify:

- what is available
- what is paid
- what is preview-only
- what can be recommended
- what cannot be claimed
- what data is used
- which claims are supported
- which gaps remain
- whether AWS runtime is gone
- whether the release capsule passed gates

The end user can understand:

- why this packet is being recommended
- what it will and will not prove
- how much it can cost
- what source categories are covered
- whether private CSV is stored
- whether the output is a legal/tax/financial opinion
- how to verify the release state

## 5. Trust object hierarchy

The plan should define trust objects in this order:

1. `trust_policy`
2. `trust_receipt`
3. `agent_trust_manifest`
4. `release_legal_attestation`
5. `zero_aws_posture_attestation`
6. `agent_decision_page`
7. `trust_surface_bundle`

### 5.1 trust_policy

Global policy for trust language and display.

It defines:

- allowed labels
- prohibited labels
- no-hit wording
- legal disclaimer wording
- data handling wording
- CSV privacy wording
- paid output leakage limits
- proof minimization rules
- public/private field boundaries

### 5.2 trust_receipt

Per packet or per output trust record.

It explains the trust posture of one generated output.

### 5.3 agent_trust_manifest

Per Release Capsule trust index for AI agents.

It tells agents:

- which packets are available
- which packets are recommended only under conditions
- which surfaces are authoritative
- which wording is allowed
- which wording is forbidden
- where to fetch the trust receipts
- how to verify hashes

### 5.4 release_legal_attestation

Per Release Capsule policy/legal publication report.

It says:

- this capsule passed policy checks
- these source families were allowed
- these artifacts were blocked
- these areas require caveat
- these areas are not legal advice

It must not say:

- "legally approved"
- "lawyer reviewed"
- "compliant"
- "safe"

unless those facts are actually present and separately evidenced.

### 5.5 zero_aws_posture_attestation

Per teardown state.

It says:

- AWS factory resources were exported
- checksums were verified
- project-tagged resources were deleted
- production smoke passed without AWS
- no runtime dependency on AWS remains

It must also say the scope:

- scoped to `jpcite` planned AWS resources
- scoped to account `993693061769`
- scoped to region `us-east-1`, plus any explicit global service checks
- not a universal statement about unrelated AWS activity in the account

### 5.6 agent_decision_page

Human and AI-readable page for each outcome/packet.

It does not sell trust.

It explains whether the agent can recommend a purchase and why.

### 5.7 trust_surface_bundle

Compiled output inside Release Capsule.

Contains:

- JSON manifests
- static UI fragments
- page data
- schema files
- hash mesh
- parity reports
- replay reports

## 6. Trust Receipt v2

### 6.1 Purpose

`Trust Receipt v2` is the per-output accountability object.

It should be attached to:

- paid packet output
- free preview
- no-hit response
- bundle quote
- workflow recipe
- watch/delta output
- agent recommendation card

### 6.2 Design rule

Do not create a vague confidence score.

Use a typed trust vector.

### 6.3 trust_vector

Recommended fields:

```json
{
  "trust_vector": {
    "evidence_coverage": "partial|sufficient_for_preview|sufficient_for_packet|insufficient",
    "source_freshness": "fresh|acceptable|stale|unknown",
    "source_authority": "official_primary|official_secondary|public_reference|unknown",
    "legal_policy_status": "publish_allowed|publish_with_caveat|manual_policy_review_required|blocked",
    "privacy_status": "public_only|private_overlay_used|suppressed|blocked",
    "billing_status": "free|cap_token_required|accepted_artifact_billable|void",
    "no_hit_scope": "not_applicable|scoped_observation|expired|unknown",
    "evaluation_status": "passed|passed_with_warnings|failed|not_evaluated",
    "zero_aws_status": "not_applicable|factory_running|exported_pending_teardown|attested_zero_aws"
  }
}
```

### 6.4 Required receipt fields

```json
{
  "trust_receipt_id": "tr_company_public_baseline_2026_05_15_001",
  "release_capsule_id": "rc_2026_05_15_xxx",
  "packet_id": "company_public_baseline",
  "outcome_contract_id": "company_public_check.v1",
  "surface": "preview|paid_output|agent_decision_page|mcp_response",
  "generated_at": "2026-05-15T00:00:00Z",
  "source_scope_summary": {
    "covered_source_families": [],
    "excluded_source_families": [],
    "known_gaps": []
  },
  "claim_support_summary": {
    "supported_claim_count": 0,
    "unsupported_claim_count": 0,
    "conflict_count": 0,
    "no_hit_count": 0
  },
  "privacy_summary": {
    "raw_csv_used": false,
    "raw_csv_stored": false,
    "private_overlay_used": false,
    "suppression_applied": false
  },
  "billing_summary": {
    "is_billable": false,
    "cap_token_required": false,
    "accepted_artifact_required_for_charge": true
  },
  "legal_policy_summary": {
    "publication_allowed": true,
    "legal_advice": false,
    "tax_advice": false,
    "financial_advice": false
  },
  "trust_vector": {},
  "hashes": {
    "receipt_hash": "",
    "capsule_hash": "",
    "surface_parity_hash": ""
  }
}
```

### 6.5 UI wording

Good:

- "公的一次情報に基づく確認範囲"
- "このsourceではhitなし。ただし不存在の証明ではありません"
- "この成果物は判断材料です。法的助言ではありません"
- "CSVのraw行は保存されません"
- "有料成果物の一部ではなく、購入判断用のpreviewです"

Bad:

- "安全です"
- "問題ありません"
- "違反なし"
- "許可不要です"
- "公的に保証されています"
- "完全に調査済みです"
- "信用できます"

## 7. Agent Trust Manifest v2

### 7.1 Purpose

`Agent Trust Manifest v2` is the trust contract for AI agents.

It should be exposed at:

- `/.well-known/jpcite-trust.json`
- `/agent/trust/manifest.json`
- Release Capsule static asset path
- MCP metadata
- OpenAPI extension fields

### 7.2 Required fields

```json
{
  "schema": "jpcite.agent_trust_manifest.v2",
  "release_capsule_id": "rc_2026_05_15_xxx",
  "capsule_hash": "",
  "generated_at": "2026-05-15T00:00:00Z",
  "authoritative_surfaces": {
    "capability_matrix": "/agent/capabilities.json",
    "packet_catalog": "/agent/packets.json",
    "pricing_catalog": "/agent/pricing.json",
    "trust_manifest": "/.well-known/jpcite-trust.json"
  },
  "agent_allowed_actions": [
    "route_task",
    "preview_cost",
    "explain_known_gaps",
    "request_consent",
    "execute_with_scoped_cap_token",
    "retrieve_trust_receipt"
  ],
  "agent_forbidden_actions": [
    "claim_no_hit_as_absence",
    "claim_legal_compliance",
    "claim_creditworthiness",
    "claim_zero_risk",
    "quote_paid_output_from_preview",
    "store_raw_csv"
  ],
  "trust_receipt_schema_url": "/schemas/trust_receipt.v2.json",
  "release_legal_attestation_url": "/release/legal-attestation.json",
  "zero_aws_posture_attestation_url": "/release/zero-aws-posture.json",
  "language_packs": {
    "no_hit": "/agent/language/no-hit.json",
    "billing": "/agent/language/billing.json",
    "legal_caveat": "/agent/language/legal-caveat.json"
  }
}
```

### 7.3 Why this matters for GEO

GEO is not only about being discoverable.

For this product, GEO means:

1. AI finds jpcite.
2. AI understands what jpcite can do.
3. AI can explain price and limitations.
4. AI can safely recommend or decline.
5. AI can obtain consent.
6. AI can execute through MCP/API.
7. AI can show trust receipt afterward.

The Agent Trust Manifest is the trust layer for steps 2 through 7.

## 8. Release Legal Attestation v2

### 8.1 Positioning

Release Legal Attestation is not a legal opinion.

It is a release-time policy attestation.

UI label:

> 公開ポリシー確認

Avoid label:

> 法務承認済み

### 8.2 Required additions

The attestation should include:

- source terms check status
- blocked source list
- blocked artifact list
- proof minimization status
- privacy taint status
- mosaic risk status
- public/private boundary status
- terms recheck TTL
- revocation graph hash
- agent language pack hash
- prohibited wording test result

### 8.3 Machine-readable object

```json
{
  "schema": "jpcite.release_legal_attestation.v2",
  "release_capsule_id": "rc_2026_05_15_xxx",
  "policy_decision": "publish_allowed|publish_with_caveat|blocked",
  "not_legal_advice": true,
  "source_terms": {
    "checked_source_count": 0,
    "blocked_source_count": 0,
    "manual_review_required_count": 0,
    "terms_recheck_ttl_days": 30
  },
  "privacy": {
    "raw_csv_in_release_capsule": false,
    "public_personal_data_minimized": true,
    "mosaic_risk_checked": true
  },
  "proof": {
    "raw_screenshot_public": false,
    "proof_surrogate_compiled": true,
    "paid_output_leakage_check": "passed"
  },
  "language_policy": {
    "forbidden_claims_check": "passed",
    "no_hit_language_pack_hash": ""
  }
}
```

## 9. Zero-AWS Posture Attestation v2

### 9.1 Positioning

Zero-AWS posture is a release/runtime claim.

It should never be shown while the AWS factory is still running.

States:

1. `not_started`
2. `factory_running`
3. `export_verified`
4. `teardown_in_progress`
5. `attested_zero_aws`
6. `attestation_failed`

### 9.2 UI wording

During AWS run:

> AWS成果物工場が稼働中です。本番runtimeはAWS非依存に設計されていますが、Zero-AWS状態はまだ確定していません。

After teardown:

> このreleaseはAWS外へexport済みで、本番runtimeはAWSに依存しないことを検証済みです。

Do not say:

> AWS料金は絶対に発生しません。

Better:

> このreleaseに紐づくjpcite用AWS resourceについて、export・削除・AWS非依存production smokeを検証済みです。

### 9.3 Required fields

```json
{
  "schema": "jpcite.zero_aws_posture_attestation.v2",
  "aws_account_id": "993693061769",
  "region": "us-east-1",
  "profile_name": "bookyou-recovery",
  "release_capsule_id": "rc_2026_05_15_xxx",
  "state": "attested_zero_aws",
  "export": {
    "external_export_completed": true,
    "checksum_verified": true,
    "export_manifest_hash": ""
  },
  "teardown": {
    "tagged_resource_inventory_empty": true,
    "s3_deleted": true,
    "ecr_deleted": true,
    "batch_deleted": true,
    "logs_deleted_or_expired": true
  },
  "runtime": {
    "production_smoke_without_aws": "passed",
    "aws_sdk_runtime_dependency": false,
    "s3_url_runtime_dependency": false
  },
  "scope_caveat": "Attestation is scoped to jpcite planned AWS resources, not unrelated account activity."
}
```

## 10. agent_decision_page v2

### 10.1 Purpose

The `agent_decision_page` is not a marketing landing page.

It is a decision surface.

It helps:

- AI agent decide whether to recommend
- AI agent explain price and gaps
- end user understand what they are buying
- release gate test whether the product is safely describable

### 10.2 Page structure

Recommended sections:

1. Task this packet solves
2. Cheapest sufficient route
3. What the free preview can tell
4. What the paid packet adds
5. Covered public source families
6. Known gaps
7. No-hit meaning
8. Price and cap
9. Data handling
10. Trust receipt preview
11. Legal/tax/financial caveat
12. Release capsule status
13. Zero-AWS state
14. Machine-readable decision bundle

### 10.3 Human UI copy style

Use short, concrete labels:

- "確認範囲"
- "不足情報"
- "費用上限"
- "保存されないデータ"
- "この結果で言えること"
- "この結果で言えないこと"
- "AI向け推薦メモ"

Avoid:

- vague reassurance
- oversized badges
- compliance-style green checkmarks for complex legal states
- "safe", "clean", "approved", "guaranteed"

### 10.4 Agent-visible JSON

Every page should have a paired JSON endpoint:

- `/packets/{packet_id}/decision`
- `/packets/{packet_id}/decision.json`

Example:

```json
{
  "schema": "jpcite.agent_decision_page.v2",
  "packet_id": "company_public_baseline",
  "recommendation_policy": {
    "agent_may_recommend": true,
    "recommended_when": [
      "user wants low-cost public source baseline",
      "user accepts no-hit caveat",
      "user has not requested legal opinion"
    ],
    "agent_should_not_recommend_when": [
      "user needs guaranteed absence of risk",
      "user asks for professional legal judgment",
      "user requires private credit bureau data"
    ]
  },
  "cheapest_sufficient_route": {
    "free_preview_first": true,
    "paid_packet_id": "company_public_baseline",
    "upgrade_path": ["vendor_risk_public_evidence", "permit_scope_review"]
  },
  "known_gaps": [],
  "no_hit_language": {
    "canonical": "no_hit_not_absence"
  },
  "trust_receipt_url": "/trust/receipts/company_public_baseline.preview.json"
}
```

## 11. New smart feature: Trust Diff

### 11.1 Problem

Users and agents need to know what changed between releases.

Without trust diff:

- a source can be removed silently
- a no-hit lease can expire silently
- a packet can become weaker without a clear UI signal
- a legal caveat can change without agent awareness

### 11.2 Feature

Add `trust_diff.json` per Release Capsule.

It compares:

- previous active capsule
- candidate capsule

Diff categories:

- source coverage added
- source coverage removed
- known gaps increased
- known gaps decreased
- no-hit leases expired
- legal policy downgraded
- privacy exposure changed
- price/cap changed
- packet recommendation policy changed
- zero-AWS status changed

### 11.3 Agent use

AI agent can say:

> 前回より自治体制度sourceが追加されました。ただし官報公告sourceの一部がterms確認待ちになったため、このpacketではknown gapとして表示されています。

### 11.4 Release blocker

Block release if:

- trust_diff exists but UI does not expose material downgrade
- MCP/OpenAPI manifest does not expose material downgrade
- price increased but decision page still says old cap
- no-hit lease expired but output still treats it as current

## 12. New smart feature: Trust Replay

### 12.1 Problem

Golden Agent Session Replay tests recommendation behavior, but users also need accountability after the fact.

### 12.2 Feature

Add `trust_replay_bundle`.

It stores a minimal replayable decision trace:

- task intent
- route decision
- preview decision
- consent envelope
- cap token scope
- executed packet
- accepted artifact status
- trust receipt
- final agent-facing summary

It must not store:

- raw CSV
- private user message body beyond minimized intent
- paid output text in public replay
- screenshots or HAR bodies

### 12.3 UI

In the paid output:

> この成果物が生成された判断経路

But expose only:

- packet chosen
- price cap
- source families used
- known gaps
- caveats

## 13. New smart feature: Trust Envelope for agent consent

### 13.1 Problem

Consent and trust are currently related but separate.

AI agent needs one object that explains:

- what will be bought
- why this is the cheapest sufficient path
- what is not covered
- max cost
- what data is used
- what trust caveats apply

### 13.2 Feature

Add `trust_consent_envelope`.

It wraps:

- `agent_purchase_decision`
- `billing_contract`
- `trust_receipt_preview`
- `known_gap_choice_model`
- `no_hit_language_pack`
- `privacy_boundary`

### 13.3 Example

```json
{
  "schema": "jpcite.trust_consent_envelope.v1",
  "task_id": "task_123",
  "recommended_contract": "company_public_check.v1",
  "why_this_route": "lowest_cost_public_baseline",
  "max_charge": {
    "amount": 300,
    "currency": "JPY"
  },
  "will_use": [
    "public corporate number data",
    "public invoice registration data",
    "public source receipts"
  ],
  "will_not_use": [
    "private credit bureau data",
    "legal professional judgment",
    "raw CSV storage"
  ],
  "known_gaps_user_must_accept": [],
  "canonical_caveats": [
    "no_hit_not_absence",
    "not_legal_advice"
  ]
}
```

## 14. New smart feature: Trust Language Pack

### 14.1 Problem

Even if the API returns safe structured fields, AI agents may explain them badly.

### 14.2 Feature

Add machine-readable language packs.

Files:

- `/agent/language/no-hit.json`
- `/agent/language/billing.json`
- `/agent/language/legal-caveat.json`
- `/agent/language/csv-privacy.json`
- `/agent/language/zero-aws.json`
- `/agent/language/known-gaps.json`

### 14.3 Fields

```json
{
  "schema": "jpcite.trust_language_pack.v1",
  "topic": "no_hit",
  "allowed_phrases_ja": [
    "このsourceではhitしませんでした。ただし不存在の証明ではありません。"
  ],
  "forbidden_phrases_ja": [
    "存在しません",
    "問題ありません",
    "リスクはありません"
  ],
  "agent_instruction": "Always include scope and timestamp when explaining no-hit."
}
```

### 14.4 Release gate

Golden Agent Replay must test whether agents follow the language pack.

## 15. New smart feature: Public Proof Surrogate UI

### 15.1 Problem

Users want proof, but raw screenshots, DOM, HAR, OCR text, and paid output can leak too much.

### 15.2 Feature

Compile proof surrogate views.

They show:

- source family
- source URL domain
- observation timestamp
- content hash
- extraction status
- screenshot thumbnail only if allowed
- claim support count
- redacted citation snippet if allowed

They do not show:

- raw HTML
- full OCR text
- full screenshot when not necessary
- cookie/header/HAR body
- paid output content
- private CSV-derived details

### 15.3 UI label

Use:

> 証跡サマリー

Avoid:

> 原本コピー

## 16. New smart feature: Accountability Timeline

### 16.1 Purpose

Make the release and output lifecycle understandable.

Timeline events:

1. source observed
2. source policy checked
3. evidence lens compiled
4. packet preview generated
5. consent envelope accepted
6. accepted artifact generated
7. trust receipt issued
8. release capsule activated
9. AWS export verified
10. zero-AWS posture attested
11. source terms changed
12. capsule superseded

### 16.2 UI

For end users:

> この成果物の確認履歴

For agents:

`accountability_timeline[]`

### 16.3 Why it is smart

It reduces support burden.

Instead of explaining internals manually, the UI and JSON show:

- when this was checked
- what changed
- what is stale
- what is still valid

## 17. New smart feature: Trust Dependency Graph

### 17.1 Problem

When a source is revoked, terms change, or a privacy issue is found, the system must know what to withdraw.

### 17.2 Feature

Add `trust_dependency_graph`.

Nodes:

- source profile
- source receipt
- evidence lens
- claim ref
- trust receipt
- agent decision page
- proof surrogate
- packet catalog entry
- MCP tool response example
- OpenAPI example
- Release Capsule

Edges:

- supports
- derived_from
- displayed_on
- exposed_to_agent
- priced_by
- blocked_by
- superseded_by

### 17.3 Release gate

No public surface may be generated unless its dependencies are known.

## 18. New smart feature: Trust State Machine

### 18.1 States

For every packet/output trust receipt:

1. `draft`
2. `compiled`
3. `policy_checked`
4. `eval_passed`
5. `release_candidate`
6. `active`
7. `superseded`
8. `withdrawn`
9. `expired`

### 18.2 Agent behavior by state

| State | Agent may recommend? | Public UI |
|---|---:|---|
| draft | no | hidden |
| compiled | no | hidden |
| policy_checked | no | hidden or internal |
| eval_passed | preview only | staging |
| release_candidate | limited | RC banner |
| active | yes | public |
| superseded | no new recommendation | historical |
| withdrawn | no | withdrawn notice |
| expired | no | stale notice |

## 19. New smart feature: Trust UI Compiler

### 19.1 Components

Generate reusable UI components:

- `TrustSummaryPanel`
- `KnownGapsPanel`
- `NoHitScopePanel`
- `SourceCoveragePanel`
- `PriceCapPanel`
- `DataHandlingPanel`
- `LegalCaveatPanel`
- `ZeroAwsPanel`
- `ReleaseCapsulePanel`
- `MachineReadableLinksPanel`

### 19.2 Constraint

The UI components must receive typed props from compiled manifests.

They must not contain free-form claims hardcoded in React/HTML.

### 19.3 Example prop

```json
{
  "component": "NoHitScopePanel",
  "props": {
    "no_hit_type": "no_hit_not_absence",
    "source_family": "invoice_registry",
    "observed_at": "2026-05-15T00:00:00Z",
    "expires_at": "2026-06-14T00:00:00Z",
    "display_text_key": "no_hit.scoped_not_absence.ja"
  }
}
```

## 20. Smart UI layout for agent_decision_page

### 20.1 First viewport

The first viewport should show:

- packet/outcome name
- task it solves
- free preview button or MCP action
- maximum cost/cap
- "what this can say"
- "what this cannot say"
- machine-readable JSON link

### 20.2 Second section

Coverage ladder:

| Tier | Adds | Use when |
|---|---|---|
| Free preview | route, price, known gaps | user deciding whether to buy |
| Basic packet | public source baseline | low-cost check |
| Expanded packet | additional source families | higher uncertainty tolerance |
| Watch product | future delta | ongoing monitoring |

### 20.3 Third section

Evidence and trust:

- source families covered
- last observed
- legal policy status
- privacy status
- no-hit caveat
- zero-AWS state

### 20.4 Final section

Agent copy block:

- safe recommendation sentence
- safe non-recommendation sentence
- caveat sentence
- billing sentence

This block should be generated from language packs.

## 21. Smart trust for end users

End users do not care about every manifest.

They care about:

- Can I use this result?
- What does it cost?
- What is the basis?
- What is missing?
- Is my private data stored?
- Is this legal/tax/financial advice?
- Can I show this to someone else?

The UI should answer these directly.

### 21.1 End-user trust summary

Use a compact summary:

```text
この成果物は、公的一次情報の確認範囲・不足情報・費用上限を明示して生成されます。
hitなしは不存在の証明ではありません。
法務・税務・金融の専門判断ではありません。
CSVを使う場合、raw行は保存されません。
```

### 21.2 Do not overexplain internal architecture

Do not show:

- JPCIR internals
- full DAG internals
- AWS control tables
- budget token internals
- raw manifest noise

Instead show:

- "検証用JSON"
- "Release Capsule"
- "Trust Receipt"
- "Source coverage"

## 22. Smart trust for AI agents

AI agents need more structure than humans.

They need:

- exact allowed claims
- exact forbidden claims
- price cap
- consent requirements
- known gaps
- machine-readable trust receipt URL
- retry/upgrade path
- no-hit wording
- privacy handling
- professional review caveat

### 22.1 Agent recommendation card

Add trust fields:

```json
{
  "agent_recommendation_card": {
    "may_recommend": true,
    "recommended_action": "run_free_preview_first",
    "paid_action_after_consent": "execute_company_public_baseline",
    "trust_summary_for_user_ja": "",
    "must_include_caveats": [
      "no_hit_not_absence",
      "not_legal_advice",
      "source_scope_limited"
    ],
    "must_not_claim": [
      "safe",
      "no_problem",
      "legally_compliant",
      "creditworthy"
    ],
    "trust_receipt_url": ""
  }
}
```

## 23. Machine-readable trust endpoints

Add endpoints/static paths:

- `/.well-known/jpcite-trust.json`
- `/agent/trust/manifest.json`
- `/agent/trust/language/no-hit.json`
- `/agent/trust/language/billing.json`
- `/agent/trust/language/legal-caveat.json`
- `/agent/trust/language/csv-privacy.json`
- `/releases/{release_capsule_id}/trust-bundle.json`
- `/releases/{release_capsule_id}/legal-attestation.json`
- `/releases/{release_capsule_id}/zero-aws-posture.json`
- `/releases/{release_capsule_id}/trust-diff.json`
- `/packets/{packet_id}/decision.json`
- `/trust/receipts/{trust_receipt_id}.json`

All should be static outputs of the Release Capsule when possible.

## 24. Release Capsule additions

Add to Release Capsule:

```text
trust/
  agent_trust_manifest.json
  trust_policy.json
  trust_receipt.schema.json
  trust_receipts.index.json
  release_legal_attestation.json
  zero_aws_posture_attestation.json
  trust_diff.json
  trust_dependency_graph.json
  trust_language_packs/
    no_hit.ja.json
    billing.ja.json
    legal_caveat.ja.json
    csv_privacy.ja.json
  agent_decision_pages/
    index.json
    company_public_baseline.json
    source_receipt_ledger.json
  surface_parity_report.json
  golden_agent_replay_report.json
```

## 25. Integration with AI-only execution

User correction:

> 実装実行に人間はやらない。AIが全てやる。

Trust/accountability design must respect this.

### 25.1 Replace manual implementation checks

Do not require human operators to manually inspect every trust page.

Use:

- schema validation
- snapshot tests
- golden agent replay
- forbidden language linter
- surface parity checker
- paid leakage detector
- privacy taint checker
- zero-AWS dependency scanner
- release gate automata

### 25.2 Keep human-facing accountability

Even if AI implements, the product must still expose:

- what was generated
- which release capsule is active
- what policy gates passed
- what is blocked
- what changed

### 25.3 "human_review_required" semantics

`human_review_required` in outputs should not mean "human developer must implement this."

It should mean:

- professional review recommended
- user should consult qualified specialist
- policy state blocks automatic public claim
- this output should not be treated as final judgment

Recommended rename for UI:

- internal field: `professional_review_recommended`
- policy field: `manual_policy_review_required`
- product output field: `human_review_required`

But the UI must explain the meaning.

## 26. Master plan merge diff

### 26.1 Add new architecture block

Add after the current `Release Capsule`, `Agent Surface Compiler`, and trust-related sections:

```text
Trust Surface Compiler

All trust/accountability surfaces are compiled from the active Release Capsule.
The compiler emits Trust Receipts, Agent Trust Manifest, Release Legal
Attestation, Zero-AWS Posture Attestation, agent_decision_page data,
trust language packs, trust diff, and surface parity reports.

No human-authored UI copy may override no-hit, legal, privacy, billing, or
zero-AWS meanings.
```

### 26.2 Add P0 implementation items

Add:

| ID | Item | Output |
|---|---|---|
| T-P0-01 | Trust schema package | `trust_receipt.schema.json`, `agent_trust_manifest.schema.json` |
| T-P0-02 | Trust Policy and Language Pack | no-hit, billing, legal, CSV privacy |
| T-P0-03 | Trust Surface Compiler | compiled JSON + UI props |
| T-P0-04 | agent_decision_page v2 | human page + JSON endpoint |
| T-P0-05 | Release Capsule trust bundle | trust folder in capsule |
| T-P0-06 | Surface Parity Checker | UI/MCP/OpenAPI consistency |
| T-P0-07 | Forbidden Language Linter | blocks unsafe claims |
| T-P0-08 | Zero-AWS Posture UI | stateful attestation display |
| T-P0-09 | Trust Diff | release-to-release changes |
| T-P0-10 | Trust Replay | minimized decision trace |

### 26.3 Add P1 implementation items

| ID | Item | Output |
|---|---|---|
| T-P1-01 | Trust Dependency Graph | revocation impact tracking |
| T-P1-02 | Public Proof Surrogate UI | minimized proof pages |
| T-P1-03 | Accountability Timeline | output lifecycle timeline |
| T-P1-04 | Trust Consent Envelope | consent + billing + trust object |
| T-P1-05 | Agent trust endpoint suite | `.well-known` and packet trust endpoints |

### 26.4 Add release gates

Block release if:

- `agent_trust_manifest.json` missing
- trust receipt schema missing
- agent decision page JSON missing for active paid packet
- UI and JSON disagree on price/cap
- UI and JSON disagree on no-hit caveat
- forbidden phrase appears in public UI
- proof page leaks paid output
- proof page leaks raw CSV/private info
- release legal attestation missing
- zero-AWS state says attested while AWS factory is still running
- trust diff shows material downgrade but UI does not show it
- golden agent replay uses forbidden trust wording

### 26.5 Add to AI Execution Control Plane

Add trust tasks to the execution graph:

```json
{
  "node_id": "compile_trust_surfaces",
  "depends_on": [
    "compile_release_capsule",
    "run_policy_firewall",
    "run_golden_agent_replay",
    "compile_capability_matrix"
  ],
  "outputs": [
    "trust/agent_trust_manifest.json",
    "trust/trust_receipts.index.json",
    "trust/release_legal_attestation.json",
    "trust/agent_decision_pages/index.json",
    "trust/surface_parity_report.json"
  ],
  "release_blockers": [
    "missing_trust_manifest",
    "surface_parity_failure",
    "forbidden_language_failure",
    "paid_leakage_failure"
  ]
}
```

## 27. Contradictions found and fixes

### 27.1 Trust UI vs no overpromising

Contradiction:

Trust UI can become a set of green badges that imply safety.

Fix:

Use typed trust vector and caveat-first language. No generic "trusted" badge.

### 27.2 Zero-AWS attestation vs running AWS factory

Contradiction:

The plan wants AWS to keep running autonomously, but also wants zero-AWS posture.

Fix:

Zero-AWS state is release/runtime specific and only becomes `attested_zero_aws` after export, teardown, and production smoke without AWS.

### 27.3 Release Legal Attestation vs legal advice

Contradiction:

The word "legal attestation" may look like legal opinion.

Fix:

UI label should be `公開ポリシー確認`. Machine object can remain `release_legal_attestation`, but always includes `not_legal_advice: true`.

### 27.4 agent_decision_page vs paid leakage

Contradiction:

Agent needs enough information to recommend, but public page must not leak paid output.

Fix:

Show coverage, price, source families, caveats, example structure, and proof surrogate. Do not show final paid conclusions.

### 27.5 AI-only execution vs human_review_required

Contradiction:

The output contract includes `human_review_required`, while user says AI performs all implementation.

Fix:

Clarify semantics. Implementation is AI-executed. `human_review_required` means professional/end-user review caveat for the generated result, not developer operation.

### 27.6 Agent Trust Manifest vs stale source terms

Contradiction:

Agent manifest could continue recommending packets after source terms change.

Fix:

Tie manifest to Release Capsule hash and Source Terms Revocation Graph. Material revocation withdraws or supersedes affected surfaces.

### 27.7 Trust score vs evidence nuance

Contradiction:

A single score could hide gaps and create false confidence.

Fix:

No global trust score. Use `trust_vector`, `known_gaps`, `coverage_ladder`, and explicit caveats.

### 27.8 Public proof vs copyright/privacy

Contradiction:

Showing proof can expose too much source content or personal data.

Fix:

Use Public Proof Surrogate Compiler. Raw artifacts stay internal/exported only where allowed, not public proof.

### 27.9 CSV private overlay vs public trust surfaces

Contradiction:

Trust receipt may reveal that a private CSV contained a specific counterparty or category.

Fix:

Public trust receipt only says `private_overlay_used: true/false` and suppression status. Detailed private receipt is tenant-scoped and never in public proof or `.well-known`.

### 27.10 Accountability timeline vs user privacy

Contradiction:

A replay/timeline can accidentally expose user task details.

Fix:

Use minimized task intent and public source lifecycle only. Private replay is tenant-scoped.

## 28. Test plan

### 28.1 Schema tests

- validate `trust_receipt.v2`
- validate `agent_trust_manifest.v2`
- validate `release_legal_attestation.v2`
- validate `zero_aws_posture_attestation.v2`
- validate `agent_decision_page.v2`

### 28.2 Surface parity tests

For every active packet:

- UI price equals JSON price
- MCP price equals JSON price
- OpenAPI examples match trust caveats
- decision page caveats match language pack
- no-hit wording is canonical
- known gaps count matches trust receipt

### 28.3 Forbidden language tests

Fail if public surfaces contain:

- `安全`
- `問題なし`
- `違反なし`
- `許可不要`
- `信用スコア`
- `完全`
- `保証`
- `法務承認`

Context-aware exceptions must be allowlisted only when used as forbidden examples.

### 28.4 Paid leakage tests

Fail if public preview includes:

- paid output final conclusion
- full source extraction text
- raw screenshot
- raw CSV detail
- private counterparty list

### 28.5 Agent replay tests

Golden Agent Session Replay must test:

- recommendation
- non-recommendation
- price explanation
- no-hit explanation
- known gaps explanation
- CSV privacy explanation
- zero-AWS explanation
- legal caveat explanation

### 28.6 Zero-AWS tests

Before `attested_zero_aws`:

- production smoke without AWS
- no AWS SDK runtime dependency
- no S3 URL runtime dependency
- no unresolved export checksum
- tagged resource inventory empty

## 29. UX copy examples

### 29.1 Company public baseline

```text
このpacketは、法人番号・インボイス・公開source receiptを使って、取引先の公的一次情報ベースの確認材料を作ります。

hitなしは不存在の証明ではありません。
信用力や法令遵守を保証するものではありません。
```

### 29.2 Grant shortlist

```text
このpacketは、公開されている制度情報と入力条件から、候補になり得る制度を整理します。

採択可能性や受給可否を保証するものではありません。
```

### 29.3 CSV overlay

```text
CSVを使う場合、raw行は保存されません。
成果物には、安全に集計された派生情報だけを使います。
```

### 29.4 Zero-AWS

```text
このreleaseは、AWS外へexportされた検証済みasset bundleから配信されています。
本番runtimeがAWSに依存しないことをproduction smokeで確認済みです。
```

## 30. Recommended final architecture statement

Add this to the master plan:

> jpciteのtrust/accountabilityは、手書き説明や曖昧な信頼バッジではなく、Release Capsuleから生成されるTrust Surface Compilerで提供する。Trust Receipt、Agent Trust Manifest、Release Legal Attestation、Zero-AWS Posture Attestation、agent_decision_page、language pack、trust diff、surface parity reportを同一manifestから生成し、AI agentとエンドユーザーが同じ事実・同じ制限・同じ費用上限を見られるようにする。実装・検証・release gateはAI Execution Control Planeが自動実行し、人間の手作業確認に依存しない。

## 31. Implementation priority

P0:

1. Trust schemas
2. Trust language packs
3. Trust Surface Compiler
4. agent_decision_page JSON
5. UI components from typed trust props
6. Surface parity checker
7. Forbidden language linter
8. Release Capsule trust folder

P1:

1. Trust Diff
2. Trust Replay
3. Accountability Timeline
4. Trust Dependency Graph
5. Public Proof Surrogate UI

P2:

1. advanced revocation UI
2. buyer trust preference profile
3. portfolio trust dashboard
4. agent-side trust negotiation

## 32. Final verdict

The smarter trust/accountability/UI method is:

> Build a Trust Surface Compiler, not a collection of trust badges.

This makes the service more credible to AI agents and end users because:

- every recommendation has a trust receipt
- every release has a trust manifest
- every public page has matching JSON
- every caveat is generated from policy
- every price/cap is consistent across UI/MCP/OpenAPI
- every no-hit is scoped and non-absolute
- every zero-AWS claim is stateful and attested
- every release can be replayed and diffed

This is compatible with:

- AI-only implementation execution
- Release Capsule
- Agent Decision Protocol
- Legal Policy Firewall v2
- PrivateFactCapsule
- AWS Artifact Factory Kernel
- Zero-bill teardown
- GEO-first growth

No blocking contradiction remains if the merge diff above is applied.
