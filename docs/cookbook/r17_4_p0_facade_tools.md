# R17 (P0) — 4 P0 Facade Tools の使い方

> AI agent 向け recipe (Claude / GPT / Gemini など)。jpcite RC1 の P0 facade は **4 tool** で構成され、各 tool は決定論的・request-time LLM 非依存・networkless で、agent の packet 計画フェーズを安全に駆動する。billing は execute_packet が `scoped_cap_token` 受領後に課金境界へ遷移し、それ以前は全て preview 扱い (`billable: false`)。

- **Audience**: AI agent builder (cohort: `agent_builder`)
- **Cost**: jpcite_route / preview_cost / get_packet は **¥0 (preview)** / execute_packet は **artifact 受諾後 ¥3-¥900** (outcome の `accepted_artifact_*` 帯による)
- **Sensitive surfaces**: 各 outcome の `disclaimer` envelope (§52 / §72 / §1 / §47条の2) は preview_cost / execute_packet 両 surface で同一文言

## TL;DR

```
1. jpcite_route   (query   → outcome_contract_id 候補)
2. preview_cost   (outcome → estimated_price_jpy + scoped_cap_token 要件)
3. execute_packet (outcome + Idempotency-Key + scoped_cap_token → packet_id)
4. get_packet     (packet_id → artifact body + citations + receipts)
```

各 endpoint は REST (`POST /v1/jpcite/{tool}`) と MCP (`jpcite.{tool}`) の 2 surface 同時公開。schema は `jpcite.rest_facade.p0.v1` に固定。

## Endpoint contracts

| tool | input (主要) | output (主要) | billable |
|---|---|---|---|
| `jpcite_route` | `query` (≤4000 chars) / `input_kind` | `candidate_outcomes[]` + `outcome_catalog_summary` packet (free inline) | false |
| `preview_cost` | `outcome_contract_id` / `max_price_jpy` | `estimated_price_jpy` / `pricing_posture` / `scoped_cap_token_required: true` | false |
| `execute_packet` | `outcome_contract_id` + header `Idempotency-Key` + header `X-Jpcite-Scoped-Cap-Token` | `packet_id` / `policy_state` / `billing_event` | true (artifact 受諾後) |
| `get_packet` | `packet_id` | `artifact_body` / `citations[]` / `source_receipts[]` | false (retrieval) |

## Sample (4-step chain)

```bash
# Step 1: route
curl -s https://api.jpcite.com/v1/jpcite/jpcite_route \
  -H 'content-type: application/json' \
  -d '{"query":"愛知県のものづくり補助金 候補を出して"}' | jq '.candidate_outcomes[0]'
# => {"outcome_contract_id":"application_strategy","estimated_price_jpy":900,...}

# Step 2: preview
curl -s https://api.jpcite.com/v1/jpcite/preview_cost \
  -H 'content-type: application/json' \
  -d '{"outcome_contract_id":"application_strategy","max_price_jpy":900}' | jq

# Step 3: execute (Idempotency-Key + scoped cap token 必須)
curl -s https://api.jpcite.com/v1/jpcite/execute_packet \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: 2026-05-16-agent-a-7f3e9' \
  -H 'X-Jpcite-Scoped-Cap-Token: <JSON token>' \
  -d '{"outcome_contract_id":"application_strategy"}' | jq '.packet_id'

# Step 4: retrieve
curl -s https://api.jpcite.com/v1/jpcite/get_packet/$PACKET_ID | jq '.citations | length'
```

## Error handling

| HTTP | reject reason | 意味 | agent 側の対処 |
|---|---|---|---|
| 400 | `blocked_unknown_outcome_contract` | route を経由せず手書き ID を渡した | jpcite_route で候補取り直し |
| 402 | `token_price_cap_exceeded` | scoped_cap_token の `max_price_jpy` 不足 | preview_cost の `estimated_price_jpy` に合わせ token 再発行 |
| 403 | `missing_idempotency_key` / `missing_scoped_cap_token` | execute_packet の header 抜け | header 2 本必須 |
| 403 | `token_outcome_scope_mismatch` | token の outcome scope と request body 不一致 | outcome に bind した token を再発行 |
| 409 | execute guard accepted, live artifact not wired | RC1 段階で artifact pipeline 未配線 | preview_cost + get_packet ベースで合成 |

## 関連

- [R18 — 14 Outcome Contract の選び方](r18_14_outcome_contracts.md)
- [R19 — CSV intake preview](r19_csv_intake_preview.md)
- [R20 — 17 PolicyState の解釈](r20_policy_state.md)
- [R21 — Agent Purchase Decision](r21_agent_purchase_decision.md)
- contract: `schemas/jpcir/agent_purchase_decision.schema.json`
- implementation: `src/jpintel_mcp/api/jpcite_facade.py`
