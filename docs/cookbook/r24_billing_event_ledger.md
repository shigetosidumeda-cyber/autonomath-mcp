# R24 (P0) — billing_event_ledger の構造と契約

> AI agent 向け recipe。jpcite の **課金 ledger** は append-only contract で、execute_packet が `accepted_artifact_*` 帯に遷移した瞬間に 1 行追記される。各 row は **`scoped_cap_token_id` + `idempotency_key_sha256` + `artifact_id`** の triple を unique key として持ち、二重課金・空課金・整合不能 row を schema 段で fail-closed。Stripe metered の usage_event とは 1:1 対応で、`mig 085` (usage_events.client_tag) + `mig 087` (idempotency_cache) の double-entry contract と整合する。

- **Audience**: AI agent builder + 運用者 (税理士 fan-out cohort では特に重要)
- **Cost**: ledger 書込は ¥0 (artifact 受諾後の課金値 ¥3-¥900 は row の `billable_jpy` に記録)
- **Sensitive**: ledger row 自体は internal artifact、公開 surface には出ない (請求書 PDF 経由のみ)

## TL;DR

```
billing_event_ledger.append({
  ledger_id,
  consent_id,                  // R21 consent_envelope.consent_id
  scoped_cap_token_id,         // R21 scoped_cap_token.token_id
  idempotency_key_sha256,      // sha256(HTTP header Idempotency-Key)
  artifact_id,                 // get_packet で返す packet_id
  outcome_contract_id,         // 14 outcome のいずれか
  charge_status,               // 8 enum (下記)
  billable_jpy,                // 300 / 600 / 900 のいずれか
  billable_jpy_taxin,          // billable_jpy × 1.10
  client_tag,                  // X-Client-Tag header (顧問先 fan-out)
  stripe_usage_event_id,       // Stripe metered usage_event id
  occurred_at,
})
```

**append-only**: 既存 row の UPDATE / DELETE は schema 段で禁止。状態変更は **新規 row 追加** (例: `paid` → `refunded` は refund row を別途 append) で表現。

## append-only contract

schema (`schemas/jpcir/billing_event_ledger.schema.json`) は下記を強制:

1. `ledger_id` は `bdle_<sha256-prefix>` 形式で primary key、insert のみ
2. `(scoped_cap_token_id, idempotency_key_sha256, artifact_id)` の triple は **unique** (重複は INSERT 段で 409 conflict)
3. `occurred_at` は `now()` 固定、agent / client が値指定する余地なし
4. row 削除は **物理的に不可能** (table に DELETE trigger なし、`schema_guard` が DROP TABLE を弾く)
5. 状態変更系 (refund / void / dispute) は **新規 row** で表現、対象 row の `parent_ledger_id` に元 row の ledger_id を bind

## triple unique key の意味

```
unique_key = sha256(scoped_cap_token_id || idempotency_key_sha256 || artifact_id)
```

3 要素のうち **どれが欠けても unique にならない**:

| triple state | 起きうる重複 | 防御 |
|---|---|---|
| scoped_cap_token_id 同じ + idempotency 同じ + artifact 同じ | 同一 execute_packet を 2 回 POST | unique constraint で 409、idempotent replay |
| scoped_cap_token_id 同じ + idempotency 異なる | token を 2 回別 idempotency で焼き直し | execute_packet 側で token expire 後拒否 (R21) |
| scoped_cap_token_id 異なる + artifact 同じ | 同一 artifact を別 token で再販 | artifact_id は packet 単位 unique, 再販不可 |

triple のいずれかが NULL を許す row は **schema 段で reject** (`required: [scoped_cap_token_id, idempotency_key_sha256, artifact_id]`)。

## charge_status 8 enum

| status | 意味 | 後続 row |
|---|---|---|
| `paid` | 正常課金、Stripe usage_event 投入済 | (terminal) |
| `pending_settlement` | x402 USDC challenge 発行済、settle 待ち (R26) | settle 後 `paid` row append |
| `void` | execute_packet 受理直前で abort (policy / cap 越え等) | (terminal) |
| `refunded` | 全額返金、対象 row の `parent_ledger_id` に元 ledger_id | (terminal) |
| `partial_refunded` | 一部返金 | refund 額分の row を `parent_ledger_id` 付きで append |
| `disputed` | chargeback / Stripe dispute 発生 | dispute 解決後 `refunded` or `paid_resolved` |
| `paid_resolved` | dispute 棄却 + 元課金維持 | (terminal) |
| `wallet_topup_credit` | Credit Wallet 経由 topup (R26) | topup 元 row、消費時に通常 `paid` row append |

`charge_status` の **遷移は新 row append のみ**。既存 row の status 書換は schema validator (`scripts/check_schema_contract_parity.py`) が round-trip 段で reject。

## ledger row 例

```json
{
  "ledger_id": "bdle_a1b2c3d4",
  "consent_id": "consent_2026-05-16_tnt42_app_strategy",
  "scoped_cap_token_id": "cap_2026-05-16_7f3e9",
  "idempotency_key_sha256": "sha256:def456...",
  "artifact_id": "pkt_2026-05-16_application_strategy_7f3e9",
  "outcome_contract_id": "application_strategy",
  "charge_status": "paid",
  "billable_jpy": 900,
  "billable_jpy_taxin": 990,
  "client_tag": "tnt42:client_aichi_mfg",
  "stripe_usage_event_id": "ue_1OabcdEFGHijkl",
  "parent_ledger_id": null,
  "occurred_at": "2026-05-16T14:23:11+09:00"
}
```

返金 row (元 row を refunded 化) は別 row として:

```json
{
  "ledger_id": "bdle_refund_e5f6g7h8",
  "parent_ledger_id": "bdle_a1b2c3d4",
  "charge_status": "refunded",
  "billable_jpy": -900,
  "billable_jpy_taxin": -990,
  "stripe_usage_event_id": "ue_1Oabcd_refund",
  ...
}
```

## 4 要素の整合性 (R21 と double-entry)

billing_event_ledger は R21 の 3 要素 (consent_envelope / scoped_cap_token / Idempotency-Key) に **artifact_id** を加えた 4 要素整合契約:

```
R21 (3 要素 入口) ─┐
                  ├─→ execute_packet ─→ artifact_id ─→ ledger row 4 要素
                  │                       (R17 packet_id)    triple unique
                  └─ accepted_artifact_pricing band 一致
```

`mig 085 usage_events.client_tag` (顧問先 fan-out) + `mig 087 idempotency_cache` (24h cache) の SQLite-side double-entry と ledger の triple unique key が **整合する** ことを Gate 2 (R23) が preflight で確認。

## Sample (agent 側 query)

```python
# 当月 ledger row 集計 (税理士 fan-out, client_tag 別)
SELECT client_tag, COUNT(*) AS billed_calls, SUM(billable_jpy) AS subtotal_jpy
FROM billing_event_ledger
WHERE occurred_at >= '2026-05-01'
  AND occurred_at < '2026-06-01'
  AND charge_status IN ('paid', 'paid_resolved')
GROUP BY client_tag
ORDER BY subtotal_jpy DESC;
```

agent は ledger を **読み取り専用** で参照可能 (REST: `GET /v1/me/billing/events`, MCP: `list_billing_events`)。書込は execute_packet 経由のみ。

## Error handling

| HTTP | reject reason | 意味 |
|---|---|---|
| 409 | `ledger_triple_conflict` | triple unique 衝突、idempotent replay |
| 400 | `ledger_missing_triple_field` | scoped_cap_token_id / idempotency / artifact のどれか欠 |
| 403 | `ledger_write_via_non_execute_packet` | execute_packet 以外から書込試行 |
| 422 | `ledger_status_transition_invalid` | charge_status の append-only 規則違反 |

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md) (artifact_id = packet_id の発行点)
- [R21 — Agent Purchase Decision](r21_agent_purchase_decision.md) (3 要素 + 本 ledger triple = 4 要素)
- [R22 — Release Capsule Manifest](r22_release_capsule_manifest.md) (gate_artifacts[] に ledger schema bind)
- [R23 — 5 Preflight Gate](r23_5_preflight_gates.md) (Gate 2: accepted_artifact_billing_contract)
- [R26 — x402 + Credit Wallet](r26_x402_wallet_payment.md) (wallet_topup_credit row との連動)
- contract: `schemas/jpcir/billing_event_ledger.schema.json`
- migrations: `scripts/migrations/085_usage_events_client_tag.sql` + `087_idempotency_cache.sql`
- implementation: `src/jpintel_mcp/billing/event_ledger.py`
