# Round3 追加スマート化 14/20: Data freshness / watch products

Date: 2026-05-15

Scope:

- Watch Delta Product
- Watch Statement Product
- No-Hit Lease Ledger
- Bitemporal Claim Graph
- Update Frontier Planner
- zero-bill after AWS teardown
- AI-executed implementation plan

AWS CLI/API/resource operation: not executed.

Output file: `docs/_internal/aws_smart_methods_round3_14_freshness_watch.md`

## 1. 結論

さらにスマートにする余地はある。

既存計画はすでに、

- `watch_delta_product`
- `watch_statement_packet`
- `freshness_buyup`
- `No-Hit Lease Ledger`
- `Bitemporal Claim Graph`
- `Update Frontier Planner`
- `Release Capsule`
- zero-bill teardown

まで入っている。

ただし、まだ「更新されているかを見る機能」と「継続課金できる商品」が少し分かれている。

よりスマートにするなら、継続更新を次の上位機能にまとめるべきである。

```text
Freshness and Watch Operating Layer
  = freshness contract
  + watch intent ledger
  + update frontier planner
  + material delta compiler
  + no-hit lease renewal engine
  + watch statement compiler
  + zero-AWS renewal runtime
```

要するに、単なるcronや定期fetchではなく、

```text
この成果物を継続価値として売るには、
どのclaim/source/no-hit leaseを、いつ、どれくらいの費用で、
どの深さまで再検査すればよいか
```

を機械的に決める層を作る。

## 2. 最重要の修正方針

### 2.1 Watch productは「変化通知」ではなく「更新済み証跡statement」

`watch_delta_product` だけだと、変化がない月に価値を説明しにくい。

既存のRound3 product packagingで出た `watch_statement_packet` を正本にする。

つまり売るものは、

```text
変化があったかどうか
```

ではなく、

```text
契約範囲を再検査し、
更新済みのreceipt / claim / no-hit lease / known gapを反映したstatement
```

である。

これなら「変化なし」でも成果物になる。

ただし外部表現は必ず、

```text
契約範囲・観測時点・対象sourceでは、material changeを観測していません。
不存在、安全、問題なしの証明ではありません。
```

にする。

### 2.2 Freshnessはsourceではなくclaim単位で持つ

source全体が新しいかどうかだけでは不十分。

同じsourceから出るclaimでも、鮮度要求が違う。

例:

| claim kind | freshness need |
|---|---|
| grant deadline | very high |
| current application eligibility page | high |
| invoice registration status | medium |
| administrative disposition listing | medium |
| law XML text | medium to low, but effective date sensitive |
| static historical receipt | low |

よって `freshness_contract` はsourceだけでなく、claim kind / packet / buyer use caseへ紐づける。

### 2.3 zero-bill後にAWS常駐watchはしない

Watch商品は継続更新を要するが、AWSを残すとzero-billと矛盾する。

採用する設計:

```text
AWS credit run:
  baseline corpus, evidence graph assets, source twins, freshness rules, watch fixturesを作る

After teardown:
  production runtime and/or non-AWS scheduled runner reads Release Capsule assets
  lightweight refresh jobs run outside AWS
  new Release Capsule is compiled and pointer-switched
  AWS S3/Lambda/EventBridge/Batch/OpenSearch/etc. remain deleted
```

禁止:

- AWS EventBridgeをwatch schedulerとして残す
- AWS Lambdaをwatch refreshとして残す
- S3 final archiveをwatch正本として残す
- OpenSearch/Neptune/RDSをlive graphとして残す
- AWS Cost Explorer/Budgetsをpost-teardown watch制御に使う

## 3. 採用すべき追加スマート機能

## 3.1 `freshness_contract.v1`

### Purpose

各claimがどれくらい新しくないと、どのpacket/商品に使ってよいかを機械可読にする。

### Schema sketch

```json
{
  "schema_id": "jpcite.freshness_contract.v1",
  "freshness_contract_id": "fc_grant_deadline_v1",
  "claim_kind": "grant_deadline",
  "source_family": "grant_program_page",
  "packet_ids": ["grant_watch_statement_v1", "grant_candidate_shortlist_v1"],
  "default_max_age": "P1D",
  "stale_after": "P3D",
  "requires_refresh_before_paid_use": true,
  "bitemporal_fields_required": [
    "observed_at",
    "source_published_at",
    "effective_from",
    "effective_to"
  ],
  "allowed_if_stale": "preview_only_with_refresh_quote",
  "public_stale_statement": "この情報は再確認期限を過ぎています。購入前に再検査が必要です。"
}
```

### Why smarter

「sourceの更新日」だけではなく、「このclaimをこの商品に使えるか」を判定できる。

これにより、古い情報で有料成果物を出す事故を防ぐ。

## 3.2 `watch_intent_ledger.v1`

### Purpose

ユーザーやAI agentが何を継続監視したいのかを、sourceではなく成果物目的で記録する。

### Schema sketch

```json
{
  "schema_id": "jpcite.watch_intent.v1",
  "watch_id": "watch_...",
  "buyer_policy_profile_id": "bpp_...",
  "outcome_contract_id": "vendor_watch_statement_v1",
  "subjects": [
    {
      "subject_kind": "company",
      "subject_entity_id": "houjin:..."
    }
  ],
  "watch_scope": {
    "source_families": [
      "corporate_number",
      "invoice_registry",
      "administrative_disposition",
      "public_procurement"
    ],
    "jurisdictions": ["JP"],
    "materiality_profile_id": "vendor_standard_v1"
  },
  "period": "monthly",
  "cap": {
    "monthly_cap_jpy_inc_tax": 330,
    "requires_reconsent_above_cap": true
  },
  "delivery": {
    "artifact_only": true,
    "push_channel": null
  },
  "status": "active"
}
```

### Why smarter

監視対象を「URL」ではなく「買い手の目的」に寄せられる。

sourceが変わっても、Outcome Contractが同じなら代替sourceで継続できる。

## 3.3 `material_delta_compiler.v1`

### Purpose

生diffをそのまま売らない。

売るのは、packetに意味がある差分だけ。

### Delta levels

| level | meaning | external output |
|---|---|---|
| raw_delta | HTML/PDF/API raw changed | never sold directly |
| structural_delta | table row/field changed | internal evidence |
| semantic_delta | deadline/status/requirement changed | packet candidate |
| material_delta | buyer action may change | watch statement |
| action_delta | next action can be suggested | follow-up offer |

### Example

```json
{
  "schema_id": "jpcite.material_delta.v1",
  "delta_id": "md_...",
  "watch_id": "watch_...",
  "source_receipt_refs": ["sr_..."],
  "claim_delta": {
    "claim_kind": "grant_deadline",
    "old_value": "2026-06-30",
    "new_value": "2026-07-15",
    "support_state": "supported_by_primary_source"
  },
  "materiality": {
    "is_material": true,
    "reason_code": "deadline_extension",
    "affected_outcome_contracts": ["grant_watch_statement_v1"]
  },
  "action_hint": {
    "allowed": true,
    "text_block_id": "grant_deadline_extended_followup_v1"
  }
}
```

### Why smarter

Watch商品が「差分の山」ではなく、「買い手に意味のある更新statement」になる。

## 3.4 `no_hit_lease_renewal_engine`

### Purpose

No-hitは期限切れする。

期限切れ時に毎回深い再調査をするのではなく、source/claim/商品に応じてrenewal methodを選ぶ。

### Renewal ladder

| renewal level | method | use case |
|---|---|---|
| L0 reuse | valid lease reuse | same/narrower scope |
| L1 metadata heartbeat | sitemap/RSS/API update feed/Last-Modified/ETag | low-cost check |
| L2 targeted query | same query re-run | company/vendor no-hit |
| L3 rendered check | Playwright public render | HTML dynamic pages |
| L4 OCR/PDF extraction | PDF or image-heavy official docs | only if needed |
| L5 defer | known gap + refresh quote | terms/cost/blocked |

### Rule

```text
if no_hit_lease.valid_for(packet_as_of, subject, scope):
  reuse
elif low_cost_heartbeat proves source unchanged within lease scope:
  extend_lease_with_heartbeat_receipt
elif paid packet requires no-hit:
  run targeted renewal
else:
  output preview_only_refresh_required
```

### Why smarter

No-hitの安全性を保ちながら、毎回重いfetch/OCRを避けられる。

## 3.5 `update_frontier_queue.v1`

### Purpose

固定cronではなく、次に再検査すべきsource/claim/watchを価値順に並べる。

### Inputs

- watch revenue and cap
- freshness contract
- no-hit lease expiry
- claim volatility
- source twin update rhythm
- recent agent task demand
- material delta probability
- accepted artifact probability
- refresh cost
- terms/robots/policy state
- customer-visible gap severity

### Scoring

```text
frontier_priority =
  watch_contract_value
  * claim_materiality_weight
  * freshness_urgency
  * lease_expiry_urgency
  * change_probability
  * accepted_artifact_probability
  * demand_coalescing_factor
  * gap_closure_value
  / max(expected_refresh_cost, cost_floor)
```

Stop rules:

```text
if terms_status in blocked: quarantine
if robots_status in blocked: quarantine
if source_twin.capture_contract_broken: canary_only
if no active watch and no packet demand: suppress
if stale output would require forbidden wording: suppress
if refresh would need AWS after teardown: route_to_non_aws_or_defer
```

### Why smarter

AWS中もAWS後も、同じ価値関数で「何を次に確認するか」を決められる。

## 3.6 `source_heartbeat_router`

### Purpose

重い取得の前に、軽い変化検知を行う。

### Method ladder

```text
official API metadata
-> official update feed / RSS
-> sitemap / index page hash
-> HEAD / ETag / Last-Modified
-> normalized DOM hash
-> targeted table extraction
-> Playwright rendered snapshot
-> OCR/PDF extraction
```

Rule:

```text
Use the cheapest method that can support the contracted claim.
Do not use screenshot/OCR only because it is available.
```

### Why smarter

PlaywrightとOCRを使える計画になっているが、全部をrender/OCRすると費用とノイズが増える。

heartbeat routerにより、安く、速く、説明可能にする。

## 3.7 `demand_coalescing_refresh`

### Purpose

同じsource/subject/scopeを複数のwatchが必要とする場合、再検査を1回にまとめる。

### Example

```text
10社が同じ補助金sourceをwatch
5つのagent taskが同じ行政処分sourceを必要とする
```

この場合、source refreshは1回でよい。

成果物への配賦は、

```text
one source refresh
-> many source_receipt refs
-> many watch_statement_packets
```

とする。

### Privacy rule

共有できるのはpublic source refreshだけ。

ユーザーのprivate watch intentやCSV-derived factsは共有しない。

## 3.8 `watch_statement_compiler.v1`

### Purpose

各期間のwatch成果物を、accepted artifactとしてコンパイルする。

### Output

```json
{
  "schema_id": "jpcite.watch_statement_packet.v1",
  "packet_id": "pkt_watch_...",
  "watch_id": "watch_...",
  "period": {
    "from": "2026-06-01",
    "to": "2026-06-30"
  },
  "scope_checked": [
    {
      "source_family": "invoice_registry",
      "source_profile_id": "sp_invoice_...",
      "claim_kinds": ["registration_status"],
      "freshness_contract_id": "fc_invoice_status_v1"
    }
  ],
  "statement_state": "accepted_no_material_delta_within_scope",
  "material_deltas": [],
  "renewed_claim_refs": ["cr_..."],
  "renewed_no_hit_lease_refs": ["nhl_..."],
  "known_gaps": [
    {
      "gap_id": "gap_...",
      "impact": "one municipality source blocked by terms review"
    }
  ],
  "billing_metadata": {
    "charge_basis": "accepted_scoped_refresh_statement",
    "cap_token_id": "cap_...",
    "accepted_artifact": true
  },
  "allowed_agent_summary": "契約範囲ではmaterial changeを観測していません。ただし不存在や安全の証明ではありません。"
}
```

### Why smarter

「今月は変化なし」でも、支払い対象の成果物が明確になる。

## 3.9 `watch_conversion_offer.v2`

### Purpose

One-shot成果物から自然にwatch商品へ移行する。

### Rule

すべての対象one-shot packetは、次を返せるようにする。

```json
{
  "watch_conversion_offer": {
    "recommended": true,
    "watch_contract_id": "vendor_watch_statement_v1",
    "why_text_block_id": "vendor_public_status_changes_are_time_sensitive_v1",
    "monthly_cap_jpy_inc_tax": 330,
    "first_period_reuses_existing_receipts": true,
    "next_refresh_due": "2026-06-15",
    "agent_can_recommend": true,
    "requires_consent_envelope": true
  }
}
```

### Why smarter

単発売上から継続売上への変換が、AI agentの会話内で自然に起きる。

## 3.10 `stale_safe_response_mode`

### Purpose

期限切れ情報を使って有料断定を出さない。

### Behavior

```text
if required claim is stale:
  free preview returns:
    - stale reason
    - refresh price/cap
    - expected added coverage
    - what can be answered without refresh
  paid execution blocks until refresh succeeds or buyer accepts lower coverage
```

### Why smarter

「古いが安い」「新しいが少し高い」をAI agentが説明できる。

ただし過剰アップセルを避けるため、anti-upsell gateを入れる。

```text
if refresh does not materially improve answer:
  do not recommend freshness buyup
```

## 3.11 `watch_gap_to_source_backcaster`

### Purpose

watch statementで繰り返し出るknown gapから、次に取るべきsourceを発見する。

### Example

```text
vendor watchで「自治体の指名停止sourceが未取得」が頻出
-> local government source candidate registryへ追加
-> canary acquisition
-> accepted artifact rateを測定
-> source capability contractへ昇格
```

### Why smarter

source拡張が思いつきではなく、売れているwatch商品の不足から決まる。

## 3.12 `watch_portfolio_batching`

### Purpose

1件ずつ監視すると高い。

AI agentが複数社・複数制度・複数地域をまとめて見る場合、portfolio watchとして安くする。

### Products

| product | buyer |
|---|---|
| vendor_portfolio_watch | SMB, procurement, accounting office |
| grant_portfolio_watch | SMB, consultant, local business support |
| regulation_portfolio_watch | legal/compliance, regulated vertical |
| permit_portfolio_watch | construction, transport, food, waste |
| procurement_portfolio_watch | sales, bidding teams |

### Why smarter

公的source refreshを共有できるので、単価を下げつつ粗利を上げられる。

## 4. Zero-bill compatible architecture

## 4.1 AWS credit runで作るもの

AWSを使う期間に、watchの継続基盤を作っておく。

```text
AWS credit run outputs:
  source_twin_registry
  source_capability_contracts
  freshness_contracts
  no_hit_lease_index
  bitemporal_claim_graph snapshot
  material_delta fixtures
  watch_statement fixtures
  update_frontier simulation reports
  source heartbeat method catalog
  release capsule watch assets
```

これらはAWS外へexportし、Release Capsuleまたはreplay bundleへ入れる。

## 4.2 AWS teardown後に残すもの

AWSには残さない。

残すのは非AWSの成果物。

```text
Release Capsule:
  public-safe watch packet schemas
  freshness contract index
  current public evidence lens
  no-hit lease public-safe index
  capability matrix
  agent surface bundle

Evidence Replay Bundle:
  source twin registry
  source capability contracts
  refresh method recipes
  update frontier test fixtures
  material delta compiler fixtures
  checksum manifest
```

## 4.3 継続更新の実行場所

zero-billとは「AWSで追加請求が走らない」という意味。

したがって、継続更新は次のどれかで行う。

1. 既存の本番runtime内の軽量refresh endpoint
2. AWSではない既存CI/scheduler
3. AI executorが起動するローカル/非AWS batch
4. agent/user request時のpull-triggered refresh

いずれも、AWS S3/Lambda/EventBridge/Batch/CloudWatch/OpenSearchに依存しない。

## 4.4 Pull-triggered watch fallback

スケジューラがない状態でもwatchが死なないようにする。

```text
agent/user requests watch status
-> runtime sees lease expired
-> returns refresh_required preview
-> scoped cap token already exists
-> AI executor or runtime runs allowed non-AWS refresh
-> new watch statement compiled
```

これにより、AWS終了後も最低限の継続価値が残る。

## 5. Product design

## 5.1 Watch product types

| product | output | important freshness |
|---|---|---|
| vendor_watch_statement | invoice, corporate number, enforcement, procurement, gazette | medium |
| grant_watch_statement | program open/close, deadline, eligibility, required docs | very high |
| regulation_watch_statement | law/guideline/public comment delta | medium/high |
| permit_watch_statement | license/permit requirements, forms, processing period | medium |
| tax_labor_watch_statement | tax/labor/social insurance events | high around deadlines |
| procurement_watch_statement | tenders, awards, qualification, suspension | high |
| local_policy_watch_statement | municipality programs, ordinances, notices | high/medium |
| standard_cert_watch_statement | JIS, safety, labeling, certification updates | medium |

## 5.2 Pricing posture

Charge for accepted scoped statements, not for vague monitoring.

```text
monthly watch fee
  = contracted scope
  + accepted refresh statement
  + renewed receipts/leases
  + material delta summary
  + gap summary
```

If refresh cannot be completed:

| condition | billing |
|---|---|
| accepted statement compiled | charge |
| partial scope accepted with buyer policy | partial charge or lower tier |
| source blocked/terms conflict | no charge for blocked scope, output known gap |
| internal failure | no charge |
| stale evidence only | preview only, no paid statement |

## 5.3 Agent-facing copy

Approved copy for AI agent:

```text
このwatchは、契約範囲の公的一次情報を定期的に再確認し、
変化があれば差分を、変化が観測されなければ範囲付きの更新済みstatementを返します。
不存在・安全・問題なしの証明ではありません。
月額上限は指定され、受入可能なstatementが生成された場合のみ課金されます。
```

Forbidden copy:

```text
常に最新です
問題がないことを保証します
変更がないことを証明します
全sourceを監視します
行政処分が存在しないことを確認済みです
```

## 6. Algorithm details

## 6.1 Claim freshness state

```text
fresh
stale_soft
stale_hard
expired_no_hit
blocked_by_terms
blocked_by_schema_drift
unknown_freshness
```

External behavior:

| state | paid packet |
|---|---|
| fresh | allowed |
| stale_soft | allowed only if contract permits and stated |
| stale_hard | refresh required |
| expired_no_hit | no-hit renewal required |
| blocked_by_terms | blocked + known gap |
| blocked_by_schema_drift | blocked + source evolution event |
| unknown_freshness | preview only |

## 6.2 Temporal envelope

Every watch claim must distinguish:

```text
observed_at
source_published_at
source_updated_at
effective_from
effective_to
expires_at
lease_expires_at
packet_as_of
```

Do not collapse these into one `date`.

## 6.3 Material delta decision

```text
material_delta =
  claim_value_changed
  AND support_state in accepted_support_states
  AND affected_outcome_contract exists
  AND not merely cosmetic/source_layout change
```

Examples:

| raw change | material? |
|---|---|
| application deadline changed | yes |
| eligibility threshold changed | yes |
| PDF filename changed only | no |
| agency page layout changed | no, unless capture contract broken |
| law effective date changed | yes |
| no-hit lease expired | yes for freshness, not substantive fact |

## 6.4 Watch update frontier scoring

Recommended scoring:

```text
priority =
  revenue_weight
  * materiality_weight
  * urgency_weight
  * lease_expiry_weight
  * volatility_weight
  * demand_weight
  * coalescing_weight
  * gap_closure_weight
  * policy_allowance
  / cost_weight
```

Where:

```text
policy_allowance = 0 if terms/robots/policy blocked
coalescing_weight > 1 if many watches share same refresh
cost_weight includes render/OCR penalty
```

## 6.5 Update frontier anti-upsell gate

Freshness buyup is useful, but can become aggressive upsell.

Rule:

```text
recommend refresh only if:
  freshness improvement changes support_state
  OR materially reduces known_gap
  OR required by paid packet contract
  OR buyer_policy_profile requires recent evidence
```

Otherwise:

```text
reuse existing receipt and disclose as_of
```

## 7. AI execution design

The user has clarified that implementation execution is done by AI, not by a human operator.

Therefore, this watch/freshness plan must become machine-executable.

## 7.1 `freshness_execution_graph`

Add an execution graph that AI executors can run.

```json
{
  "schema_id": "jpcite.freshness_execution_graph.v1",
  "nodes": [
    {
      "id": "define_freshness_contract_schema",
      "type": "code_change",
      "outputs": ["freshness_contract.v1 validator"]
    },
    {
      "id": "compile_watch_statement_fixture",
      "type": "test_fixture",
      "requires": ["watch_statement_packet.v1"]
    },
    {
      "id": "run_no_hit_lease_expiry_tests",
      "type": "verification",
      "requires": ["no_hit_lease.v2 validator"]
    }
  ],
  "stop_gates": [
    "forbidden_no_hit_wording",
    "aws_dependency_detected_after_teardown",
    "stale_paid_claim_allowed",
    "watch_statement_without_scope"
  ]
}
```

## 7.2 AI executor invariants

```text
INV-FRESH-001 paid watch statement has scope_checked
INV-FRESH-002 paid watch statement has period
INV-FRESH-003 paid watch statement has source_receipt_refs or renewed_no_hit_lease_refs
INV-FRESH-004 no-hit lease is not used after expiry
INV-FRESH-005 stale_hard claim cannot support paid assertion
INV-FRESH-006 material delta is not raw diff
INV-FRESH-007 Release Capsule contains no AWS runtime dependency
INV-FRESH-008 post-teardown watch path has no AWS endpoint/env/sdk dependency
INV-FRESH-009 agent copy uses approved no-hit language
INV-FRESH-010 watch charge requires accepted artifact
```

## 8. Merge diff into master execution plan

## 8.1 Add to smart-method section

Add a new subsection:

```text
Round3 14: Freshness and Watch Operating Layer

Adopt:
- freshness_contract.v1
- watch_intent_ledger.v1
- material_delta_compiler.v1
- no_hit_lease_renewal_engine
- update_frontier_queue.v1
- source_heartbeat_router
- demand_coalescing_refresh
- watch_statement_compiler.v1
- watch_conversion_offer.v2
- stale_safe_response_mode
- watch_gap_to_source_backcaster
- watch_portfolio_batching

Reject:
- permanent AWS watch runtime
- watch billing without accepted statement
- no-hit as absence proof
- raw diff as paid output
- stale hard claim in paid packet
```

## 8.2 Add to immediate implementation order

Insert after contract/catalog and before AWS full canary:

```text
1. Define `freshness_contract.v1`, `watch_intent.v1`, `watch_statement_packet.v1`, `material_delta.v1`.
2. Update packet contract so every claim has temporal envelope and freshness state.
3. Convert internal no-hit正本 to `no_hit_lease.v2`; keep `no_hit_checks[]` only as external view.
4. Add stale-safe response mode to free preview.
5. Add watch conversion offer to one-shot packets.
6. Add watch statement compiler fixtures.
7. Add Update Frontier simulation using local fixtures.
8. Add source heartbeat router method selection.
9. Add Release Capsule watch asset manifest.
10. Add post-teardown no-AWS dependency test for watch paths.
```

## 8.3 Add to Release Capsule manifest

```json
{
  "watch_assets": {
    "freshness_contract_index": "freshness_contracts.public.json",
    "watch_contract_catalog": "watch_contract_catalog.public.json",
    "watch_statement_examples": "watch_statement_examples.public.json",
    "no_hit_lease_index": "no_hit_lease_index.public_safe.json",
    "source_heartbeat_catalog": "source_heartbeat_catalog.public.json",
    "update_frontier_policy_hash": "sha256:..."
  }
}
```

## 8.4 Add to Capability Matrix

Each watch product should expose:

```json
{
  "capability_id": "vendor_watch_statement_v1",
  "state": "recommendable",
  "billing_mode": "accepted_statement",
  "requires_consent_envelope": true,
  "supports_free_preview": true,
  "supports_freshness_buyup": true,
  "zero_aws_after_teardown": true,
  "stale_behavior": "preview_only_refresh_required"
}
```

## 8.5 Add to AWS credit run

During AWS credit run, add jobs:

| job | output |
|---|---|
| J-W01 Freshness Contract Compiler | source/claim freshness contracts |
| J-W02 Watch Fixture Generator | watch statement examples |
| J-W03 No-Hit Lease Expiry Simulator | expiry/renewal fixtures |
| J-W04 Update Frontier Simulator | priority queue reports |
| J-W05 Source Heartbeat Catalog | cheapest safe refresh method per source |
| J-W06 Material Delta Fixture Builder | grant/reg/vendor/tax examples |
| J-W07 Zero-AWS Watch Path Test | no AWS dependency report |

These jobs are planning additions only. No AWS command was run here.

## 9. Conflict check

## 9.1 Watch products vs zero-bill

Conflict:

Watch implies ongoing monitoring; AWS must be deleted after credit run.

Resolution:

AWS builds baseline and fixtures only. Ongoing watch runs in existing non-AWS runtime, non-AWS scheduler, local AI executor, or pull-triggered refresh. No AWS EventBridge/Lambda/S3/OpenSearch remains.

Status: resolved if post-teardown dependency test is mandatory.

## 9.2 No-hit lease vs "no change" wording

Conflict:

Watch statements might imply absence or safety.

Resolution:

Use `accepted_no_material_delta_within_scope` and `no_hit_not_absence`. Require `scope_checked`, `period`, `known_gaps`, `lease_expires_at`, and approved copy blocks.

Status: resolved.

## 9.3 Freshness buyup vs manipulative upsell

Conflict:

AI agent might recommend refresh just to increase revenue.

Resolution:

Anti-upsell gate: recommend buyup only when freshness changes support state, closes material gap, is required by paid contract, or buyer policy requires it.

Status: resolved.

## 9.4 Bitemporal claim graph vs simple UX

Conflict:

Bitemporal fields can make outputs too complex for end users.

Resolution:

Internal claims retain full temporal envelope. Public packet compiler shows concise `as_of`, `effective_period`, and `refresh_required` fields.

Status: resolved.

## 9.5 Shared refresh vs privacy

Conflict:

Demand coalescing could leak that multiple buyers watch the same subject/source.

Resolution:

Coalesce only public source refresh. Do not expose buyer counts, private watch intents, CSV-derived facts, or tenant-specific subjects across tenants.

Status: resolved.

## 9.6 Immutable Release Capsule vs continuous updates

Conflict:

Release Capsule is immutable, but watch updates need change.

Resolution:

Each accepted update produces a new small watch capsule or capsule delta, then pointer switch. Old capsules remain reproducible.

Status: resolved.

## 9.7 Expired lease vs paid packet reuse

Conflict:

Receipt reuse improves cost, but stale no-hit is unsafe.

Resolution:

Paid use blocks when no-hit lease expired unless renewal succeeds. Preview can show refresh_required.

Status: resolved.

## 9.8 Source terms revocation vs recurring product

Conflict:

A source can become blocked after a watch contract is sold.

Resolution:

Source terms revocation graph invalidates affected source capability contracts. Watch statement outputs known gap and skips/partials billing by contract policy.

Status: resolved.

## 9.9 AI-only execution vs safety gates

Conflict:

User wants AI to execute all implementation, but AWS and production need safety.

Resolution:

Use machine-verifiable gates, no-op AWS command compiler before execution phase, action ledger, rollback state machine, invariant tests. AI performs execution; gates are code, not manual checklists.

Status: resolved for implementation planning. Real AWS execution still must enter the explicit AWS execution phase, not this planning file.

## 10. Release blockers to add

Add these as hard release blockers:

```text
RB-FRESH-001 paid watch statement lacks scope_checked
RB-FRESH-002 paid watch statement lacks period
RB-FRESH-003 paid output uses stale_hard claim
RB-FRESH-004 paid output uses expired no-hit lease
RB-FRESH-005 watch statement says or implies absence/safety/no problem
RB-FRESH-006 material delta is raw diff without claim support
RB-FRESH-007 watch path depends on AWS after teardown
RB-FRESH-008 watch billing event exists without accepted artifact
RB-FRESH-009 freshness buyup recommended without material value
RB-FRESH-010 source terms revoked but watch still uses source
RB-FRESH-011 shared refresh leaks tenant/watch demand
RB-FRESH-012 Release Capsule contains watch asset without checksum/hash
```

## 11. Recommended P0/P1/P2 split

## P0

- `freshness_contract.v1`
- `watch_statement_packet.v1`
- `no_hit_lease.v2` paid reuse blocker
- stale-safe response mode
- watch conversion offer for `company_public_baseline`
- no-AWS dependency test for post-teardown watch path
- watch statement fixture examples

## P1

- `watch_intent_ledger.v1`
- `material_delta_compiler.v1`
- `source_heartbeat_router`
- `update_frontier_queue.v1`
- demand coalescing for public source refresh
- vendor/grant/regulation watch products

## P2

- portfolio watch batching
- advanced local-government watch
- standard/certification watch
- full agent-driven watch renewal optimization
- watch gap to source backcaster

## 12. Final adoption recommendation

Adopt the Freshness and Watch Operating Layer.

This is smarter than adding a simple recurring cron because it:

- monetizes no-change periods as scoped accepted statements
- avoids absence/safety overclaiming
- uses freshness by claim and packet, not just source update time
- keeps AWS disposable and zero-bill compatible
- lets AI agent explain the cheapest sufficient watch option
- turns one-shot packet users into recurring watch users
- coalesces public refresh work across many buyers without leaking private demand
- blocks stale evidence from paid outputs
- uses known gaps to discover the next high-value source

This should be merged into the master plan as a product/runtime capability, not just as an operational schedule.

