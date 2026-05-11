# MPP (Managed Provider Plan) — naming-only brand layer

**Status**: brand layer over existing wired primitives. **No new code**, no
schema change, no tier. This document is the canonical reference that
external buyers, accountants, and 税理士事務所 procurement use to map
their internal procurement vocabulary ("annual contract", "credit pack",
"volume rebate") onto the actual jpcite billing primitives that have
been live since Wave 21.

> Why this document exists: enterprise buyers expect a "plan" page they
> can paste into 稟議書. They do NOT want to see "¥3/req metered" alone —
> 稟議 culture requires a named bundle. MPP is that name. It is **not** a
> tier and does **not** change the price-per-call, the contract shape,
> or the operator's zero-touch posture.

## Three component primitives stacked under the MPP name

| Wave 21 primitive          | Wired surface                                     | What MPP positions it as          |
| -------------------------- | ------------------------------------------------- | --------------------------------- |
| D4 — Volume rebate         | `am_volume_rebate` + `dispatch_webhooks.py` cron  | "Volume rebate component"         |
| D5 — Credit pack prepay    | `am_credit_pack_purchase` + `credit_pack.py`      | "Credit pack component"           |
| D6 — Yearly prepay         | `am_yearly_prepay` + `keys.subscription_yearly`   | "Yearly prepay component"         |

MPP is the **stack** of all three, not a fourth SKU. The customer buys the
three components in one signed PO; underneath, the system records three
independent rows that the operator can audit, refund, or true-up
without renegotiation.

## What MPP is NOT

- **NOT a tier.** ¥3/req is the only rate. Volume rebate is a
  back-of-the-book adjustment posted at the end of the period; credit
  pack is a customer-balance entry; yearly prepay is a discount on the
  first month's invoice paid up front. None of these create a SKU.
- **NOT a feature gate.** Every endpoint MPP customers reach is the same
  endpoint anonymous + ¥3/req customers reach. No "MPP-only" tool, no
  "premium" annotation.
- **NOT a contract term that changes ToS.** Customers continue under the
  default jpcite ToS. The MPP component values (rebate %, credit amount,
  yearly months) are line items on the invoice, not contract clauses.

These NOT-clauses are non-negotiable. They match the Non-negotiable
constraints in `CLAUDE.md` and the memory entries
`feedback_no_priority_question` / `feedback_zero_touch_solo`.

## Target customer profile

MPP exists for 税理士事務所 / 会計士事務所 / 上場補助金コンサル / 中堅シンクタンク —
operators who consume the API at sustained ¥30,000 〜 ¥100,000/月 levels
across 顧問先 fan-out (Wave 21 D2 `client_profiles` / D1 `usage_events.client_tag`).
A typical MPP stack:

| 月平均使用量    | Volume rebate (D4) | Credit pack (D5) | Yearly prepay (D6) | 想定 月額    |
| --------------- | ------------------ | ---------------- | ------------------ | ----------- |
| 10,000 req/月   | 5% rebate          | ¥300,000 prepay  | none               | ¥30,000     |
| 20,000 req/月   | 7% rebate          | ¥300,000 prepay  | 1 月 free          | ¥60,000     |
| 33,000 req/月   | 10% rebate         | ¥1,000,000 prepay| 1 月 free          | ¥100,000    |

Numbers are illustrative — the customer mixes-and-matches the three
components freely. The operator never quotes a "Plan A / Plan B / Plan
C" page; instead, the buyer arrives at their stack via a simple
arithmetic conversation pinned to their actual call volume.

## Procurement script

When a 税理士 / 会計士 procurement officer asks for a "plan PDF", reply with
this 3-bullet pattern:

1. Base rate is ¥3/req metered (税込 ¥3.30), one Stripe invoice per month.
2. Reduce effective rate via **volume rebate** (back-of-period adjustment
   to the next invoice).
3. Reduce cash-flow friction via **credit pack** (sign one 稟議 for the
   year, ¥300K / ¥1M / ¥3M lump-sum) and/or **yearly prepay** (pay 12
   months up front for a 1-month discount).

The buyer signs **one** PO that itemises (a) the metered rate, (b) the
rebate %, (c) the credit pack amount, (d) the yearly prepay flag. The
operator does not chase, negotiate, or upsell — the buyer self-selects.

## Operator-side audit surface

MPP customers are visible in the admin dashboard via the same `client_profiles`
+ `usage_events.client_tag` keys used for individual customers. There is
no separate "MPP customer" table. To answer "is this MPP?", join:

```sql
SELECT
  c.customer_id,
  vr.rebate_percent,
  cp.amount_jpy AS credit_pack_amount,
  yp.months_paid AS yearly_months
FROM api_keys c
LEFT JOIN am_volume_rebate vr ON vr.customer_id = c.customer_id
LEFT JOIN am_credit_pack_purchase cp ON cp.customer_id = c.customer_id AND cp.status='paid'
LEFT JOIN am_yearly_prepay yp ON yp.customer_id = c.customer_id AND yp.status='active'
WHERE c.customer_id = ?;
```

A row with at least 2 of the 3 components non-NULL is an MPP customer for
analytics / 稟議書 confirmation purposes.

## Discovery + REST endpoint

A single read-only discovery endpoint exists at `/v1/billing/mpp/discovery`
(`src/jpintel_mcp/api/billing_v2.py`) so an agent or 稟議書 generator can
fetch the canonical naming + component list without scraping this Markdown.

The endpoint returns:

```json
{
  "plan_name": "Managed Provider Plan",
  "is_tier": false,
  "components": [
    { "id": "volume_rebate", "wave": "21-D4", "table": "am_volume_rebate" },
    { "id": "credit_pack",   "wave": "21-D5", "table": "am_credit_pack_purchase" },
    { "id": "yearly_prepay", "wave": "21-D6", "table": "am_yearly_prepay" }
  ],
  "base_rate_jpy": 3,
  "base_rate_tax_inclusive_jpy": 3.30,
  "intended_monthly_jpy_range": [30000, 100000],
  "target_buyer": ["税理士事務所", "会計士事務所", "補助金コンサル", "シンクタンク"]
}
```

## Cross-reference

- Code paths: `src/jpintel_mcp/billing/credit_pack.py`, Wave 21 D4/D5/D6.
- Memory: `feedback_no_priority_question`, `feedback_zero_touch_solo`,
  `feedback_autonomath_no_ui`, `project_autonomath_business_model`.
- Wave 43.4.9+10 sibling files: `acp_integration.py` (ACP), `x402_handler.ts`
  (USDC), `api/billing_v2.py` (REST surface), `tests/test_payment_rail_3.py`.

## License

This document is content licensed under the same terms as the rest of
`docs/` (CC-BY 4.0). Operator: Bookyou株式会社 (T8010001213708).
