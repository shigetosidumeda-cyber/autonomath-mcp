# R21 (P0) — Agent Purchase Decision の作り方

> AI agent 向け recipe。jpcite の **billable=true 遷移** は `consent_envelope` + `scoped_cap_token` + `Idempotency-Key` の 3 要素が揃った execute_packet 呼出のみで発生する。各要素は `schemas/jpcir/*.schema.json` で contract 化され、Stripe metered billing への ledger 行は `billing_event_ledger` schema 経由で 1:1 で append-only に積まれる。

- **Audience**: AI agent builder (cohort: `agent_builder`)
- **Cost**: 受諾後 ¥3 / ¥300 / ¥600 / ¥900 (outcome の `accepted_artifact_pricing` rules による)
- **Sensitive**: 全 sensitive surface の disclaimer envelope は purchase decision 内に **inline で同梱**

## TL;DR

```
consent_envelope  ─┐
scoped_cap_token  ─┼─→ execute_packet → billing_event_ledger row (append-only)
Idempotency-Key   ─┘                  → packet (billable: true)
```

3 要素のどれが欠けても execute_packet は 403 / 402 で fail-closed、課金は発生しない。

## 3 要素 detail

### 1. `consent_envelope`

user (or agent on behalf of user) の **artifact 受諾意思** を contract 化したもの。agent UI で「¥XXX で artifact を受け取る」承認 dialog を経由した時点で生成する。

```json
{
  "consent_id": "consent_2026-05-16_user42_app_strategy",
  "consent_kind": "accepted_artifact",
  "outcome_contract_id": "application_strategy",
  "max_price_jpy": 900,
  "consenting_party": {"kind": "tenant", "tenant_id": "tnt_42"},
  "consent_at": "2026-05-16T14:23:11+09:00",
  "expires_at": "2026-05-16T15:23:11+09:00"
}
```

schema: `schemas/jpcir/consent_envelope.schema.json`

### 2. `scoped_cap_token`

consent_envelope を **暗号学的に bind** した cap token。jpcite が発行した JSON (or base64url-JSON) で、execute_packet header `X-Jpcite-Scoped-Cap-Token` に貼る。

```json
{
  "token_id": "cap_2026-05-16_7f3e9",
  "consent_id": "consent_2026-05-16_user42_app_strategy",
  "outcome_contract_id": "application_strategy",
  "execute_input_hash": "sha256:abc123...",
  "max_price_jpy": 900,
  "issued_at": "2026-05-16T14:23:11+09:00",
  "expires_at": "2026-05-16T15:23:11+09:00",
  "signature": "ed25519:..."
}
```

schema: `schemas/jpcir/scoped_cap_token.schema.json`

token の `execute_input_hash` は execute_packet body の sha256 と一致する必要がある (mismatch → 403 `token_input_scope_mismatch`)。

### 3. `Idempotency-Key`

execute_packet HTTP header に必須。重複 POST で billing 行が二重に積まれないよう、agent 側で **request 単位の unique key** (UUIDv7 / timestamp + nonce) を発番する。`mig 087 idempotency_cache` table に sha256(key) 単位で 24h cache される。

```
Idempotency-Key: 2026-05-16T14:23:11Z__tnt42__app_strategy__7f3e9
```

## billing_event_ledger との連動

execute_packet が 3 要素揃って accept されると、**billing_event_ledger** に append-only で 1 行入る:

```json
{
  "ledger_id": "ble_2026-05-16_7f3e9",
  "consent_id": "consent_2026-05-16_user42_app_strategy",
  "scoped_cap_token_id": "cap_2026-05-16_7f3e9",
  "idempotency_key_sha256": "sha256:def456...",
  "outcome_contract_id": "application_strategy",
  "billable_jpy": 900,
  "billable_jpy_taxin": 990,
  "client_tag": "tnt42:client_aichi_mfg",
  "stripe_usage_event_id": "ue_...",
  "occurred_at": "2026-05-16T14:23:11+09:00"
}
```

schema: `schemas/jpcir/billing_event_ledger.schema.json` (mig 085 `usage_events.client_tag` + mig 087 `idempotency_cache` double-entry contract)

## billable=true 遷移条件

agent は下記 4 条件 **全部** 揃った時点で `billable=true` packet を受け取る:

1. consent_envelope 有効 (expires_at > now)
2. scoped_cap_token signature 検証 OK + execute_input_hash 一致 + max_price_jpy ≥ outcome price
3. Idempotency-Key 24h cache miss (first call) または同 key で同 body の再送 (idempotent replay)
4. policy_decision.public_compile_allowed = True (deny / quarantine / blocked_* は事前に弾かれる)

どれか 1 つでも欠けると `billable=false` の preview-only response が返り、ledger 行は積まれない。

## accepted_artifact_pricing rules

outcome の `pricing_posture` ごとに price band が決まる。token の `max_price_jpy` はこの band 以上を要求:

| pricing_posture | jpy range | 対応 outcome |
|---|---|---|
| `accepted_artifact_low` | 300 | `invoice_registrant_public_check` |
| `accepted_artifact_standard` | 600 | `company_public_baseline` / `regulation_change_watch` / `court_enforcement_citation_pack` / `public_statistics_market_context` / `source_receipt_ledger` / `evidence_answer` / `healthcare_regulatory_public_check` |
| `accepted_artifact_premium` | 900 | `application_strategy` / `local_government_permit_obligation_map` / `client_monthly_review` / `foreign_investor_japan_public_entry_brief` |
| `accepted_artifact_csv_overlay` | 900 | `csv_overlay_public_check` / `cashbook_csv_subsidy_fit_screen` |

schema: `schemas/jpcir/accepted_artifact_pricing.schema.json`

## Sample (3 要素 chain)

```bash
# Step 1: consent (agent UI で user 承認 → 受領)
CONSENT_JSON='{"consent_id":"...","outcome_contract_id":"application_strategy","max_price_jpy":900,...}'

# Step 2: cap token を jpcite から発行
CAP_TOKEN=$(curl -sX POST https://api.jpcite.com/v1/jpcite/issue_cap_token \
  -H 'content-type: application/json' \
  -d "{\"consent_envelope\": $CONSENT_JSON, \"execute_input_hash\": \"sha256:...\"}" | jq -r .scoped_cap_token)

# Step 3: execute (3 要素 揃った)
curl -sX POST https://api.jpcite.com/v1/jpcite/execute_packet \
  -H 'content-type: application/json' \
  -H "Idempotency-Key: 2026-05-16T14:23:11Z__tnt42__app_strategy__7f3e9" \
  -H "X-Jpcite-Scoped-Cap-Token: $CAP_TOKEN" \
  -d '{"outcome_contract_id":"application_strategy"}' | jq '.billable'
# => true
```

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md)
- [R18 — 14 Outcome Contract の選び方](r18_14_outcome_contracts.md)
- [R19 — CSV intake preview](r19_csv_intake_preview.md)
- [R20 — 17 PolicyState の解釈](r20_policy_state.md)
- contract: `schemas/jpcir/agent_purchase_decision.schema.json` / `consent_envelope.schema.json` / `scoped_cap_token.schema.json` / `billing_event_ledger.schema.json` / `accepted_artifact_pricing.schema.json`
- implementation: `src/jpintel_mcp/agent_runtime/billing_contract.py` + `src/jpintel_mcp/api/jpcite_facade.py`
