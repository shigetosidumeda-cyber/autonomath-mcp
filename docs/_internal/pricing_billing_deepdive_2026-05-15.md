# Pricing / billing / cost preview / unit economics deep dive

Date: 2026-05-15

Owner lane: pricing / billing / cost preview / unit economics

Status: implementation planning only. Do not treat this as shipped API behavior until the implementation plan is explicitly accepted.

Related source-of-truth constraints:

- Public baseline price: 3 JPY ex-tax / 3.30 JPY inc-tax per billable unit.
- Cost preview is free and must not consume the anonymous 3 req/day/IP quota.
- Anonymous use remains 3 req/day/IP for free discovery.
- Paid execution requires an API key.
- Paid fanout, batch, CSV, watchlist, and packet execution require a hard cost cap (`X-Cost-Cap-JPY` or request body equivalent) before billable work starts.
- External LLM, agent runtime, web search, cloud, MCP client, and integration costs are never included in jpcite price.
- Pricing transparency is a product surface: AI agents should be able to recommend or skip jpcite based on explicit cost, cap, known gaps, and caller baseline fields.

## 1. Executive decision

jpcite should keep a single visible unit price, but define clear billable unit types per workflow:

```text
unit_price_ex_tax_jpy = 3
unit_price_inc_tax_jpy = 3.30
pricing_model = metered_units
no tiers, no seats, no minimum, no bundled external LLM cost
```

The visible promise is not "cheap search." The promise is:

> jpcite charges only for successful evidence/packet units it returns, and shows the predicted unit count before execution.

This matters for AI agents. An agent should be able to say:

> I can preview this workflow for free. If executed, jpcite will charge N billable units at 3 JPY ex-tax each, excluding external LLM or agent costs. I will set a hard cap before running it.

## 2. Billing principles

| Principle | Rule |
|---|---|
| Preview is free | `/v1/cost/preview` and `/v1/packets/preview` return estimates only and never record usage. |
| Charge after success | Record usage only after a successful billable output exists. |
| Reject before billable work | Missing API key, missing cap, validation error, quota exceeded, auth failure, cap exceeded, unsupported task, and final-judgment requests must fail before metering. |
| No double charge on retry | Paid POST/fanout/batch/CSV/watchlist requires `Idempotency-Key`; same key + same normalized payload maps to same billable execution. |
| Conservative cap estimate | Cap checks use worst-case billable units before execution. Final billed units may be lower when no-hit/not-found rows are not billable. |
| Billable means useful output | `not_found`, `no_hit_not_absence`, validation rejects, and gap-only unsupported output should not be billed unless a specific paid "proof of no-hit check" packet is introduced later and explicitly priced. |
| External cost separation | All responses and UI must state that external LLM, search, cloud, agent runtime, and integration costs are not included. |
| Tax clarity | API fields carry both ex-tax and inc-tax values. Stripe remains final tax/invoice authority. |

## 3. Packet別課金単位

Canonical billing metadata:

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "metered_units",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "billable_unit_type": "packet",
  "billable_units": 1,
  "jpy_ex_tax": 3,
  "jpy_inc_tax": 3.3,
  "external_costs_included": false,
  "cost_preview_required": false,
  "cap_required_for_paid_execution": true
}
```

### 3.1 P0 packet units

| packet_type | Endpoint / tool | billable_unit_type | Unit formula | Billed only when | Not billed when |
|---|---|---:|---|---|---|
| `evidence_answer` | `POST /v1/packets/evidence-answer` / `createEvidenceAnswerPacket` | `packet` | 1 successful packet | At least one sourced record/claim/section is returned | query invalid, final judgment request, zero sourced output, auth/cap failure |
| `company_public_baseline` | `POST /v1/packets/company-public-baseline` / `createCompanyPublicBaselinePacket` | `subject` | 1 resolved company subject | identity resolution reaches billable threshold and a baseline packet is returned | unknown company, ambiguous identity below threshold, no-hit without usable packet |
| `application_strategy` | `POST /v1/packets/application-strategy` / `createApplicationStrategyPacket` | `profile_packet` | 1 normalized applicant profile | ranked candidates/questions/source receipts are returned | profile too incomplete to screen, validation reject, final eligibility request |
| `source_receipt_ledger` | `POST /v1/packets/source-receipt-ledger` / `getSourceReceiptLedgerPacket` | `source_receipt_set` | `ceil(unique_source_receipts / 25)`, min 1 | receipt ledger is returned | packet/artifact id not found, caller lacks access, zero receipts |
| `client_monthly_review` | `POST /v1/packets/client-monthly-review` / `createClientMonthlyReviewPacket` | `billable_subject` | count of accepted client subjects | per client/company subject with review sections or known-gaps review packet | rejected CSV rows, duplicate rows, unresolved identity rows, no accepted subjects |
| `agent_routing_decision` | `POST /v1/packets/agent-routing-decision` / `decideAgentRouteForJpcite` | `free_control` | 0 | Never; this is routing/control | Always free, rate-limited separately if needed |

### 3.2 Artifact / domain packet units

| packet_type | billable_unit_type | Unit formula | Notes |
|---|---|---|---|
| `application_strategy_pack` | `profile_packet` | 1 per normalized applicant profile | Same unit semantics as P0 `application_strategy`. |
| `funding_stack_compatibility_matrix` | `compatibility_pair` | count of unique unordered program pairs evaluated | For N unique program IDs: `N*(N-1)/2`; cap estimate uses this full pair count. |
| `company_public_baseline` | `subject` | 1 per resolved corporate entity | `houjin_bangou` preferred. T-number/name/address flows bill after identity resolution succeeds. |
| `counterparty_public_dd_packet` | `subject` | 1 per resolved counterparty | If the same normalized subject appears twice in one request, dedupe before billing. |
| `invoice_counterparty_check_pack` | `subject` | 1 per resolved T-number or corporate entity | Status history/name-address match included in the same unit. |
| `public_funding_traceback` | `funding_record` | count of returned funding/adoption/subsidy records, capped by requested limit | No-hit is not billable. |
| `reviewer_handoff_packet` | `source_packet` | 1 per source packet/artifact converted to handoff | Should not re-bill underlying evidence units if generated from a same-request artifact. |
| `saved_search_delta_packet` | `delta_subject` | count of accepted saved searches evaluated | Optionally discount to changed-only later, but MVP should bill evaluated saved searches for clarity. |
| `cost_and_token_roi_packet` | `roi_scenario` | count of caller scenarios evaluated | Pure preview variant remains free; paid packet only when persisted/exportable ROI artifact is returned. |
| `auditor_evidence_binder` | `source_receipt_set` | `ceil(unique_source_receipts / 25)`, min 1 | Binder value scales with receipt count, not narrative length. |
| `member_program_watchlist` | `billable_subject` | count of accepted member/company subjects | Same CSV intake subject definition as monthly review. |
| `loan_portfolio_watchlist_delta` | `billable_subject` | count of accepted borrower/counterparty subjects | Monthly/periodic watchlist billing; duplicates deduped per run. |

### 3.3 Existing API / MCP unit mapping

| Endpoint family | billable_unit_type | Unit formula |
|---|---|---|
| Simple search/detail/check/provenance | `request` | 1 successful response |
| `GET /v1/evidence/packets/{subject_kind}/{subject_id}` | `packet` | 1 packet if subject resolves and evidence is returned |
| `POST /v1/evidence/packets/query` | `packet` | 1 packet per successful query result envelope |
| `POST /v1/evidence/packets/batch` | `subject` | count of returned packets; no-hit/not-found subjects not billed |
| `POST /v1/programs/batch` | `record` | count of returned program details after dedupe; not_found not billed |
| Export/download endpoints | `export_bundle` | `ceil(records_exported / 100)`, min 1, if export is successfully created |

## 4. CSV intake時の `billable_subject` 定義

CSV is the highest-risk billing surface because users think in files while jpcite meters subjects. The UI and API must therefore show both:

```text
uploaded_rows -> accepted_rows -> unique_billable_subjects -> predicted_units -> cap check -> execution -> billed_units
```

### 4.1 Definition

`billable_subject` is one normalized, deduped real-world target accepted for packet execution.

Canonical shape:

```json
{
  "billable_subject_id": "bsj_...",
  "subject_kind": "corporate_entity",
  "normalized_subject_key": "corporate_entity:1234567890123",
  "input_row_numbers": [2, 18],
  "input_identifiers": {
    "houjin_bangou": "1234567890123",
    "invoice_registration_number": "T1234567890123",
    "name": "Example K.K.",
    "address_hint": "Tokyo"
  },
  "resolution_status": "resolved",
  "identity_confidence": 0.98,
  "billable": true,
  "billable_reason": "resolved_unique_subject",
  "predicted_units": 1
}
```

### 4.2 Subject kinds

| subject_kind | Primary key | Fallback key | Billable when |
|---|---|---|---|
| `corporate_entity` | 13-digit corporate number | normalized name + address + confidence threshold | resolved to one entity above threshold |
| `invoice_registration` | T-number | corporate number from T-number | invoice/T-number status can be checked against a resolved subject |
| `program` | `UNI-*` / canonical program ID | normalized program title + jurisdiction | one program is resolved |
| `saved_search` | saved search id | normalized query + filter hash | query/filter is accepted and executable |
| `watchlist_item` | normalized subject key + watchlist id | row hash only for non-entity watchlists | accepted for periodic evaluation |
| `funding_record` | adoption/funding record id | source URL + recipient + amount/date hash | record is resolved and included |

### 4.3 Row states

| row_state | Billable? | Meaning |
|---|---:|---|
| `accepted_resolved` | yes | Row maps to a unique subject. |
| `accepted_manual_review_packet` | yes only if explicitly requested | Caller asked for a packet explaining ambiguity/needed follow-up. MVP should default to not bill. |
| `duplicate_of_prior_row` | no | Dedupe by normalized subject key within the same request. |
| `invalid_format` | no | Bad corporate number, bad T-number, missing required columns, malformed CSV. |
| `unresolved_identity` | no | Name/address not enough to resolve. |
| `ambiguous_identity` | no | Multiple candidates below confidence threshold. |
| `unsupported_subject_kind` | no | Column mix does not match any supported subject kind. |
| `private_input_minimized` | no by itself | Private note columns are ignored for billing; they may appear in profile normalization if allowed. |

### 4.4 CSV lifecycle

1. `POST /v1/csv/intake/preview` or `/v1/cost/preview` with `input_mode=csv`.
2. Server parses headers, validates rows, normalizes identifiers, dedupes candidate subjects, and returns `billable_subjects[]`.
3. Preview response shows rejected rows and the exact predicted units.
4. Paid execution requires API key, `Idempotency-Key`, and a hard cap.
5. Execution bills only `accepted_resolved` subjects that produce a successful packet/result.
6. Response includes `billing.reconciliation`: predicted vs actual units, rejected rows, duplicates, no-hit rows, and billed subjects.

### 4.5 CSV cap math

Pre-execution cap uses:

```text
projected_units = count(unique accepted_resolved subjects) * packet_unit_multiplier
projected_ex_tax_jpy = projected_units * 3
projected_inc_tax_jpy = projected_units * 3.30
```

For pairwise compatibility CSV:

```text
projected_units = sum over groups of unique_pairs(program_ids)
unique_pairs(n) = n * (n - 1) / 2
```

For source receipt binder CSV:

```text
projected_units = ceil(unique_source_receipts / 25)
```

### 4.6 CSV response fields

```json
{
  "csv_intake": {
    "input_file_id": "csv_...",
    "row_count": 120,
    "accepted_row_count": 96,
    "rejected_row_count": 18,
    "duplicate_row_count": 6,
    "billable_subject_count": 84,
    "billable_subject_definition": "one normalized, deduped real-world target accepted for packet execution",
    "billable_subjects": [],
    "rejected_rows": [
      {
        "row_number": 14,
        "row_state": "invalid_format",
        "reason_code": "invalid_houjin_bangou",
        "message_ja": "法人番号が13桁ではありません。"
      }
    ]
  }
}
```

## 5. Cost previewレスポンス設計

Cost preview must be an agent-readable contract, not a marketing estimate.

### 5.1 Request shape

```json
{
  "workflow_id": "wf_2026_05_monthly_review",
  "input_mode": "packet|endpoint_stack|csv|mcp_tools",
  "currency": "JPY",
  "tax_mode": "ex_tax_and_inc_tax",
  "calls": [
    {
      "endpoint": "POST /v1/packets/client-monthly-review",
      "packet_type": "client_monthly_review",
      "quantity": 84
    }
  ],
  "csv_file_id": "csv_...",
  "caller_baseline": {
    "source_tokens_basis": "pdf_pages",
    "source_pdf_pages": 30,
    "input_token_price_jpy_per_1m": 300
  },
  "cap": {
    "max_jpy_inc_tax": 300,
    "reject_if_estimate_exceeds_cap": true
  }
}
```

### 5.2 Response shape

```json
{
  "estimate_id": "est_01J...",
  "pricing_version": "2026-05-15",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "expires_at": "2026-05-15T12:15:00+09:00",
  "free_preview": true,
  "preview_consumes_anonymous_quota": false,
  "anonymous_free_quota": {
    "applies_to_preview": false,
    "execution_limit_req_per_day_per_ip": 3,
    "resets_at_jst": "2026-05-16T00:00:00+09:00"
  },
  "currency": "JPY",
  "unit_price": {
    "ex_tax_jpy": 3,
    "inc_tax_jpy": 3.3,
    "tax_rate": 0.1,
    "tax_authority_note": "Stripe invoice is final for tax calculation."
  },
  "predicted": {
    "billable_units_min": 84,
    "billable_units_max": 84,
    "billable_units_expected": 84,
    "jpy_ex_tax_min": 252,
    "jpy_ex_tax_max": 252,
    "jpy_ex_tax_expected": 252,
    "jpy_inc_tax_min": 277.2,
    "jpy_inc_tax_max": 277.2,
    "jpy_inc_tax_expected": 277.2
  },
  "line_items": [
    {
      "line_item_id": "li_001",
      "packet_type": "client_monthly_review",
      "billable_unit_type": "billable_subject",
      "unit_formula": "count(unique accepted_resolved subjects)",
      "quantity": 84,
      "unit_price_ex_tax_jpy": 3,
      "unit_price_inc_tax_jpy": 3.3,
      "predicted_jpy_ex_tax": 252,
      "predicted_jpy_inc_tax": 277.2,
      "confidence": "exact_after_csv_preview"
    }
  ],
  "cap_check": {
    "cap_required_for_paid_execution": true,
    "provided_cap_jpy_inc_tax": 300,
    "would_execute_under_cap": true,
    "required_header": "X-Cost-Cap-JPY",
    "recommended_cap_jpy_inc_tax": 278
  },
  "execution_requirements": {
    "api_key_required": true,
    "idempotency_key_required": true,
    "cost_cap_required": true,
    "recommended_headers": {
      "X-API-Key": "required for paid execution",
      "Idempotency-Key": "required for paid POST/fanout/batch/CSV",
      "X-Cost-Cap-JPY": "required; use at least predicted.jpy_inc_tax_max rounded up"
    }
  },
  "not_included": [
    "external LLM input/output/reasoning/cache costs",
    "external web search or tool-use billing",
    "agent runtime or SaaS platform costs",
    "customer integration, storage, or cloud costs"
  ],
  "billing_safety": {
    "no_charge_for_preview": true,
    "no_charge_for_auth_failure": true,
    "no_charge_for_validation_error": true,
    "no_charge_for_cap_reject": true,
    "no_charge_for_no_hit": true,
    "idempotency_prevents_double_charge": true
  },
  "agent_recommendation": {
    "decision": "can_execute_under_cap",
    "recommend_for_cost_savings": null,
    "cost_savings_decision": "needs_caller_baseline_for_llm_cost_claim",
    "recommended_message_ja": "見積もりは税込約277.2円です。外部LLM費用は含みません。上限300円を設定すれば実行できます。"
  },
  "csv_intake": {
    "billable_subject_count": 84,
    "rejected_row_count": 18,
    "duplicate_row_count": 6
  }
}
```

### 5.3 Preview confidence levels

| confidence | Meaning | Example |
|---|---|---|
| `exact` | Quantity is known without execution. | Single packet, fixed 1 unit. |
| `exact_after_csv_preview` | CSV has been parsed/deduped and accepted subjects are known. | Monthly review CSV. |
| `upper_bound` | Final units may be lower after no-hit/not-found rows. | Batch subject lookup. |
| `range` | Query fanout or compatibility expansion depends on resolved records. | Search-to-packet workflow. |
| `requires_input` | Missing fields prevent useful estimate. | CSV not uploaded, unknown packet type. |

### 5.4 Error design

| HTTP | code | Billing effect | Meaning |
|---:|---|---|---|
| 400 | `cost_cap_required` | not billed | Paid execution request omitted cap. |
| 401 | `api_key_required` / `invalid_api_key` | not billed | Paid execution cannot start. |
| 402 | `cost_cap_exceeded` | not billed | Predicted max exceeds provided cap. |
| 409 | `idempotency_conflict` | not billed again | Same idempotency key with different normalized payload. |
| 422 | `invalid_intake` | not billed | Validation rejected before billable work. |
| 428 | `idempotency_key_required` | not billed | Paid retry-sensitive POST omitted idempotency key. |
| 429 | `anonymous_quota_exceeded` | not billed | Free execution quota exceeded; cost preview remains separately rate-limited. |
| 503 | `monthly_cap_reached` | not billed | Customer monthly cap would be exceeded. |

## 6. 課金誤解を避けるUI/文言

### 6.1 Required labels

Use these labels consistently:

| Surface | Label |
|---|---|
| Pricing page | `3円/課金単位 (税別)・税込3.30円。完全従量、最低料金なし。` |
| Cost preview button | `無料で見積もる` |
| Execute button | `上限を設定して実行` |
| Cap input | `今回の上限額 (税込円)` |
| CSV summary | `課金対象: 重複除外後の対象数` |
| External cost notice | `外部LLM・検索・エージェント実行費用は含みません` |
| No-hit notice | `該当なしは「存在しない証明」ではありません。課金対象外です。` |
| Known gaps notice | `未接続・未確認の根拠があります。安全判定ではありません。` |

### 6.2 Pre-execution copy

Recommended Japanese copy:

```text
この見積もりは無料です。見積もりは匿名3回/日の実行枠を消費しません。
実行にはAPIキー、Idempotency-Key、税込上限額が必要です。
jpciteの料金は3円/課金単位 (税別、税込3.30円) です。
外部LLM、検索、エージェント実行、クラウド、連携先SaaSの費用は含みません。
```

For CSV:

```text
アップロード行: 120
重複除外後の課金対象: 84
除外行: 24 (重複6、形式エラー18)
予測料金: 252円 (税別) / 277.2円 (税込)
今回の上限額を設定してから実行します。
```

For AI agent:

```text
jpciteの無料見積もりでは、この実行は84課金単位、税込約277.2円です。
外部LLM費用は含まれません。上限300円を設定して実行できます。
```

### 6.3 Avoid these phrases

| Avoid | Replace with |
|---|---|
| `AI費用を削減します` | `caller baseline条件下の入力文脈量削減見込みを表示します` |
| `無料で3回使えます` | `匿名実行は3 req/日/IP。cost previewは別枠で無料です` |
| `CSV 1ファイルいくら` | `重複除外後の課金対象数で見積もります` |
| `該当なしなので安全` | `no-hitは不存在証明ではありません` |
| `補助金に申請できます` | `候補・確認質問・根拠URLを返します。最終判断は専門家確認です` |
| `税込3円` | `税別3円、税込3.30円` |
| `LLM費用込み` | `外部LLM費用は含みません` |
| `無制限` | `従量課金。月次capと実行capで制御できます` |

### 6.4 Billing reconciliation UI

After execution, show:

```text
見積もり: 84 units / 税込277.2円
実績: 82 units / 税込270.6円
差分: no-hit 2件は課金対象外
Idempotency-Key: 01J...
Stripe使用量反映: scheduled
```

Do not hide rejected/duplicate/no-hit rows. Billing trust depends on visible reconciliation.

## 7. Metering and ledger design

### 7.1 Usage event

Every billable output emits one immutable usage event.

```json
{
  "usage_event_id": "uev_...",
  "customer_id": "cus_...",
  "api_key_id": "key_...",
  "idempotency_key": "01J...",
  "estimate_id": "est_...",
  "request_id": "req_...",
  "endpoint": "POST /v1/packets/client-monthly-review",
  "packet_type": "client_monthly_review",
  "billable_unit_type": "billable_subject",
  "billable_units": 82,
  "unit_price_ex_tax_jpy": 3,
  "jpy_ex_tax": 246,
  "jpy_inc_tax_estimate": 270.6,
  "external_costs_included": false,
  "client_tag": "client_folder_123",
  "subject_keys_hash": "sha256:...",
  "created_at": "2026-05-15T12:02:00+09:00",
  "stripe_meter_event_status": "pending"
}
```

### 7.2 Reconciliation fields in API response

```json
{
  "billing": {
    "estimate_id": "est_...",
    "usage_event_id": "uev_...",
    "pricing_version": "2026-05-15",
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "billable_unit_type": "billable_subject",
    "billable_units_predicted": 84,
    "billable_units_actual": 82,
    "jpy_ex_tax_actual": 246,
    "jpy_inc_tax_estimate_actual": 270.6,
    "cap_jpy_inc_tax": 300,
    "cap_was_enforced_before_work": true,
    "not_billed_counts": {
      "duplicates": 6,
      "rejected_rows": 18,
      "no_hit": 2,
      "auth_or_validation_failures": 0
    },
    "external_costs_included": false
  }
}
```

## 8. Unit economics

### 8.1 Revenue model

jpcite is a metered evidence infrastructure product:

- Price: 3 JPY ex-tax / 3.30 JPY inc-tax per billable unit.
- Buyer mental model: per successful evidence/packet subject, not per seat.
- Use cases that create recurring volume:
  - accounting firm monthly client review
  - bank/VC/M&A counterparty watchlists
  - SaaS agent integrations checking Japanese public data
  - invoice/enforcement/funding monitoring
  - audit/evidence binders
- Expansion driver: more subjects, more periodic reviews, more integrations, not more users.

### 8.2 Gross margin model

Core assumption: jpcite does not perform request-time LLM calls and does not bundle external provider costs. Therefore COGS is dominated by:

- database/API hosting
- precompute and ETL
- source retrieval and checksum storage
- observability/logging
- Stripe/payment overhead
- support/refund operations

Illustrative per-unit model:

| Component | Directional cost per unit | Notes |
|---|---:|---|
| Serving/database/cache | low | Packet lookup should be mostly local/precomputed. |
| ETL/precompute amortization | low to medium | Higher for volatile sources; improves with reuse. |
| Storage/receipts | low | Source receipt metadata is compact. |
| Payment processing | medium at very low invoices | Stripe fixed/percentage fees hurt tiny monthly invoices; less relevant as usage aggregates. |
| Support/refunds | variable | Clarity in preview/reconciliation reduces support cost. |
| External LLM | 0 inside jpcite unit | Explicitly excluded. |

Gross margin should improve with:

- cache hit rate on common packets
- source receipt reuse across packets
- batch execution reducing HTTP/orchestration overhead
- fewer billing disputes via preview + cap + reconciliation
- agent integrations that produce repeat usage without sales labor

### 8.3 Break-even framing for customers

Do not say "jpcite always saves LLM cost."

Say:

```text
jpcite costs 3 JPY ex-tax per billable unit. It may reduce the input context a caller sends to an external LLM when the caller would otherwise pass large PDFs, search results, or source pages. The cost preview and packet metrics expose the comparison, but external provider billing is not guaranteed or included.
```

Customer break-even fields:

```text
avoided_input_cost_jpy = avoided_input_tokens * input_token_price_jpy_per_1m / 1_000_000
break_even_met = avoided_input_cost_jpy >= jpcite_cost_jpy
```

Only set `recommend_for_cost_savings=true` when caller supplied:

- source token/page baseline
- input token price
- packet token estimate
- jpcite unit cost

Otherwise use:

- `needs_caller_baseline`
- `needs_input_token_price`
- `not_supported_by_caller_baseline`

### 8.4 VC narrative skeleton

Positioning:

> jpcite is metered evidence infrastructure for AI agents working with Japanese public institutional data. It packages official-source facts, receipts, known gaps, and review fences into small machine-readable packets before the model answers.

Why pricing works:

- Single low unit price removes procurement friction.
- No seats means agent/SaaS workflows can scale usage without account redesign.
- Free cost preview lets agents self-budget before execution.
- Hard caps and idempotency make autonomous agent spending governable.
- External LLM cost is excluded, so gross margin is not tied to model inference pricing.

Why it can compound:

- Same source receipts feed many packets.
- Same normalized subjects recur monthly across accounting, banking, SaaS, and audit workflows.
- Packet outputs become the citation layer agents preserve in downstream answers.
- Usage grows with monitored entities and workflows, not sales headcount.

Investor metric candidates:

| Metric | Why it matters |
|---|---|
| Billable units/month | Core metered revenue volume. |
| Preview-to-execution conversion | Trust and agent recommendation quality. |
| Units per customer per month | Expansion without seat pricing. |
| Repeat subject rate | Evidence of recurring workflow, not one-off search. |
| Packet cache hit rate | Gross margin lever. |
| Gross margin after Stripe/support | True unit economics. |
| Dispute/refund rate per 10k units | Pricing clarity and billing trust. |
| Cost-cap rejection rate | Shows customers are governing autonomous spend. |
| Agent-sourced executions | Measures distribution through AI agents/MCP/OpenAPI. |

### 8.5 Pricing risks and mitigations

| Risk | Mitigation |
|---|---|
| 3 JPY feels too cheap to support high-touch users | Keep product self-serve; charge for usage, not support-heavy bespoke work. |
| Tiny invoices hurt Stripe economics | Encourage monthly workflows and CSV/watchlists; consider minimum payout threshold operationally, not a public minimum fee. |
| Users confuse jpcite cost with LLM cost | Repeat `external_costs_included=false` in preview, execution, UI, docs, and agent guidance. |
| CSV users expect per-file billing | Always show row/subject reconciliation before execution. |
| Agents overcall because unit price is low | Require caps for paid execution and expose `agent_routing_decision` free control tool. |
| No-hit billing disputes | MVP: no-hit not billed; if paid no-hit certificate is added later, make it a separate explicit packet. |
| Pairwise compatibility explodes | Preview pair count, require cap, reject above default pair limit unless explicit override. |

## 9. Implementation acceptance checklist

Before coding, the implementation plan should answer:

- Does every paid POST/fanout/batch/CSV endpoint require API key, idempotency key, and hard cap?
- Does preview avoid anonymous 3 req/day/IP consumption?
- Does every billable response include `billing_metadata` or `billing` with ex-tax/inc-tax, unit type, formula, units, and external-cost exclusion?
- Does CSV preview show uploaded rows, rejected rows, duplicates, accepted subjects, predicted units, and exact formula?
- Are no-hit/not-found rows excluded from billing in MVP?
- Are idempotency conflicts rejected without double usage events?
- Can an AI agent make a recommendation from `agent_recommendation`, `cap_check`, and `not_included` without scraping prose?
- Do UI labels avoid `AI費用削減保証`, `税込3円`, `CSV 1ファイル`, and `該当なしなので安全`?
- Does the ledger support reconciliation from estimate -> execution -> Stripe meter event -> invoice/refund review?

## 10. Recommended defaults

| Setting | Default |
|---|---|
| `pricing_version` | `2026-05-15` |
| Unit price | 3 JPY ex-tax / 3.30 JPY inc-tax |
| Cost preview TTL | 15 minutes |
| Paid execution cap | required |
| Paid POST idempotency | required |
| CSV unresolved identity billing | not billed |
| CSV duplicate billing | not billed |
| No-hit billing | not billed |
| External LLM cost included | false |
| Anonymous execution quota | 3 req/day/IP |
| Cost preview quota relationship | separate free estimator, does not consume anonymous execution quota |

