# R26 (P0) — x402 USDC + Credit Wallet (¥ topup) の使い方

> AI agent 向け recipe。jpcite は **3 決済経路** を並行配備する (memory: agent_monetization_3_payment_rails)。本 recipe は agent 経済 dim の 2 経路 — **x402 (USDC on Base L2)** と **Credit Wallet (¥ Stripe topup + webhook auto-topup)** を扱う。Stripe metered (R21 + R24) は API-key 顧客の primary、x402 は anonymous agent の micropayment、Wallet は CFO/CIO 予算予測軸のために併存。

- **Audience**: agent 自走 micropayment + 予算管理 CFO/CIO cohort
- **Cost**: x402 = ¥3 相当の USDC (Base L2), Wallet topup = Stripe Checkout で ¥1,000 / ¥5,000 / ¥10,000 / ¥50,000 4 段
- **Sensitive**: x402 は API-key 不要、IP rate limit 3 req/day と同位置で anonymous tier 上の課金経路

## TL;DR

```
[x402 path]                                       [Wallet path]
agent ──GET /v1/jpcite/execute_packet──┐          agent ──POST /v1/me/wallet/topup──┐
                                       │                                              │
                                  HTTP 402                                       Stripe Checkout
                                       │                                              │
                          { challenge: HMAC quote }                          user pays ¥ → webhook
                                       │                                              │
        agent ──pay 0.02 USDC on Base L2──┐                          wallet_topup_credit row append (R24)
                                          │                                              │
                              settlement verify (~2s)                      Credit balance + ¥ (auto-topup eligible)
                                          │                                              │
                                  packet billed=true                        execute_packet 消費 → Wallet decrement
```

## x402: HTTP 402 challenge + settlement verify

### 1. challenge 発行

API-key を持たない agent が `execute_packet` を呼ぶと:

```http
POST /v1/jpcite/execute_packet HTTP/1.1
Content-Type: application/json

{ "outcome_contract_id": "invoice_registrant_public_check" }

HTTP/1.1 402 Payment Required
Content-Type: application/json
X-Jpcite-X402-Challenge: <base64url JSON>

{
  "x402": {
    "version": "x402-0.1",
    "network": "base-mainnet",
    "asset": "USDC",
    "amount": "0.02",
    "recipient": "0xJpciteRecipientAddress...",
    "quote_id": "q_2026-05-16_7f3e9",
    "expires_at": "2026-05-16T14:25:11+09:00",
    "hmac_signature": "sha256:def...",
    "callback_url": "https://api.jpcite.com/v1/x402/settle"
  }
}
```

quote_id + amount + recipient + expires_at が **HMAC で sign** されており、agent が値を改ざんすると settle 段で reject。

### 2. agent: USDC 送金 (Base L2)

agent は自分の wallet から `recipient` に `amount` USDC を送る (Base L2、決済 < 2 秒)。送金 tx_hash を取得。

```python
# pseudo (agent 側)
tx_hash = base_l2_client.send_usdc(
    to=challenge["recipient"],
    amount=challenge["amount"],   # "0.02"
    memo=challenge["quote_id"],
)
# tx_hash = "0xabc123..."
```

### 3. settle verify

agent は settle endpoint に tx_hash を post:

```http
POST /v1/x402/settle HTTP/1.1
Content-Type: application/json

{
  "quote_id": "q_2026-05-16_7f3e9",
  "tx_hash": "0xabc123...",
  "hmac_signature": "<echo>"
}

HTTP/1.1 200 OK
{
  "settled": true,
  "scoped_cap_token": "<JSON>",  // R21 cap token, jpcite が発行
  "ledger_id": "bdle_..."         // R24 ledger row
}
```

jpcite は on-chain で tx_hash を verify (block confirmation 1 で OK)、settle 成立後 R21 scoped_cap_token を返す。agent はそれを使って **同一 execute_packet を再 POST** して packet 受領。

### 4. ledger row (R24 連動)

settle 成立で billing_event_ledger に row が入る:

```json
{
  "ledger_id": "bdle_x402_a1b2",
  "charge_status": "paid",
  "billable_jpy": 300,
  "billable_jpy_taxin": 330,
  "outcome_contract_id": "invoice_registrant_public_check",
  "scoped_cap_token_id": "cap_x402_...",
  "stripe_usage_event_id": null,
  "x402_tx_hash": "0xabc123...",
  "x402_quote_id": "q_2026-05-16_7f3e9",
  "occurred_at": "2026-05-16T14:23:13+09:00"
}
```

`charge_status: pending_settlement` (settle 待ち) → `paid` (settle 成立) で 2 row、もしくは settle 即時の場合 `paid` 1 row。

## Credit Wallet: ¥ topup via Stripe + webhook auto-topup

### 1. topup 開始

```http
POST /v1/me/wallet/topup HTTP/1.1
Authorization: Bearer <api_key>
Content-Type: application/json

{ "amount_jpy": 10000, "auto_topup_threshold_jpy": 2000, "auto_topup_amount_jpy": 10000 }

HTTP/1.1 200 OK
{
  "checkout_url": "https://checkout.stripe.com/c/pay/...",
  "topup_id": "tup_2026-05-16_7f3e9"
}
```

agent は user に `checkout_url` を渡して Stripe Checkout 完了 → Stripe → jpcite webhook (`/webhook/stripe`)。

### 2. webhook auto-topup (Stream J G5)

Stream J G5 で実装された webhook handler は Stripe `checkout.session.completed` を受けて:

```
1. Stripe event verify (signature)
2. wallet.balance_jpy += amount_jpy
3. billing_event_ledger に charge_status='wallet_topup_credit' row append
4. user に notify (email)
```

`auto_topup_threshold_jpy` を下回ると次回 execute_packet 時に **自動再 topup** (Stripe customer.balance + saved card 経由)。

### 3. execute_packet 消費 (Wallet 優先)

API-key 顧客の execute_packet は下記優先順で課金:

```
1. Wallet balance >= outcome.estimated_price_jpy → Wallet decrement
                                                   ledger row charge_status='paid' + wallet_consumed=true
2. Wallet balance < outcome.estimated_price_jpy + auto_topup 設定済
                                                 → Stripe customer.balance + saved card topup
                                                   → Wallet 補充後 1 の path
3. Wallet 0 + auto_topup 未設定 → Stripe metered (R21 + R24 通常 path)
4. anonymous (API-key 無し) → x402 challenge (上記)
```

ledger row には `wallet_consumed` boolean が付き、Wallet decrement と Stripe usage_event 投入は **排他** (1 row につき 1 経路)。

### 4. spending alert 50%/80%/100% throttle

memory: feedback_agent_credit_wallet_design — Wallet 残高が初回 topup の 50% / 80% / 100% を切ると agent に下記 hint を返す:

```json
{
  "packet": { ... },
  "rate_limit_hint": {
    "wallet_balance_jpy": 1200,
    "wallet_balance_pct_of_initial_topup": 12,
    "alert_level": "spending_alert_100",   // _50 / _80 / _100
    "next_throttle_at": "2026-05-16T14:30:00+09:00",
    "topup_url": "https://api.jpcite.com/v1/me/wallet/topup"
  }
}
```

`_100` で次回 execute_packet は 1 つだけ通し、それ以降は 402 Payment Required (Wallet 経由でも) で hold。

## 3 経路の住み分け

| 経路 | 認証 | 主 cohort | 課金粒度 | 予算可視 |
|---|---|---|---|---|
| Stripe metered (R21) | API-key | 税理士 / 会計士 / consultant | per-call (¥3-¥900) | 月末請求 |
| **x402 (R26)** | 不要 | anonymous agent / agent-led growth | per-call (USDC) | tx 単位 |
| **Credit Wallet (R26)** | API-key | CFO/CIO 予算予測 | 前払い + auto-topup | balance ダッシュボード |

3 経路は **billing_event_ledger** (R24) に **同一 schema で** row 化される (`stripe_usage_event_id` / `x402_tx_hash` / `wallet_consumed` のどれが set かで経路判別)。

## Error handling

| HTTP | reject reason | 意味 |
|---|---|---|
| 402 | `x402_challenge_required` | API-key 無し anonymous + Wallet 残高 0 |
| 400 | `x402_hmac_invalid` | challenge 改ざん |
| 400 | `x402_quote_expired` | expires_at 超過 (再 challenge 要求) |
| 402 | `x402_settlement_pending` | tx_hash on-chain 未 confirm |
| 422 | `x402_amount_mismatch` | 送金 USDC が quote と一致しない |
| 402 | `wallet_insufficient_funds` | Wallet 残高不足 + auto_topup 未設定 |
| 422 | `wallet_topup_amount_invalid` | ¥1,000 / 5,000 / 10,000 / 50,000 4 段以外 |

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md) (execute_packet が 3 経路の合流点)
- [R21 — Agent Purchase Decision](r21_agent_purchase_decision.md) (Stripe metered 経路の 3 要素)
- [R24 — billing_event_ledger](r24_billing_event_ledger.md) (3 経路すべて同一 ledger schema)
- [R22 — Release Capsule Manifest](r22_release_capsule_manifest.md)
- memory: `feedback_agent_monetization_3_payment_rails` / `feedback_agent_x402_protocol` / `feedback_agent_credit_wallet_design`
- contract: `schemas/jpcir/billing_event_ledger.schema.json` (3 経路 union)
- implementation: `src/jpintel_mcp/billing/x402.py` + `src/jpintel_mcp/billing/wallet.py`
