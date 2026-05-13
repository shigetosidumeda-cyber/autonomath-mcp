# jpcite API Fee Delta Examples

**Status**: canonical public-pricing safety SOT
**Last updated**: 2026-05-13
**Brand**: jpcite (Bookyou株式会社)

This document defines the public-safe language for jpcite pricing comparisons.
Any public comparison must describe an API fee delta under a stated baseline
only. It must not present revenue, profit, labor reduction, business
outcome, or professional-judgment value as a calculated result.

## Pricing Inputs

- Standard metered price: ¥3 / billable unit, tax excluded
- Tax-included reference: ¥3.30 / billable unit
- Anonymous trial: 3 requests / day per IP, reset at 00:00 JST

## Provider Comparison Baseline

Default public baseline for the calculator and pricing page:

- External model: Claude Sonnet 4.5
- External token price: $3 input / $15 output per million tokens
- External web-search tool price: Anthropic web search at $10 / 1,000 searches
- FX reference: USD/JPY=150
- jpcite price: ¥3 / billable unit, tax excluded
- Workload: the six calculator use cases and their listed token/search/request counts

The comparison formula is:

```text
external_api_fee =
  input_tokens  * input_usd_per_mtok  / 1,000,000 * usd_jpy
+ output_tokens * output_usd_per_mtok / 1,000,000 * usd_jpy
+ searches      * search_usd_per_1k    / 1,000     * usd_jpy

jpcite_fee = jpcite_billable_units * ¥3

api_fee_delta = external_api_fee - jpcite_fee
```

## Six Use Case Reference

| # | Use case | Input tokens | Output tokens | Searches | External API fee | jpcite units | jpcite fee | API fee delta |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | M&A DD: company permissions, adoption, enforcement check | 120,000 | 20,000 | 25 | ¥136.50 | 4 | ¥12 | ¥124.50 |
| 2 | Subsidy requirements, source URL, compatibility extraction | 80,000 | 15,000 | 18 | ¥96.75 | 2 | ¥6 | ¥90.75 |
| 3 | Tax advisor: measure applicability and circular cross-reference | 60,000 | 12,000 | 15 | ¥76.50 | 2 | ¥6 | ¥70.50 |
| 4 | Admin scrivener: permit basis, circular, form walk-through | 90,000 | 15,000 | 20 | ¥104.25 | 2 | ¥6 | ¥98.25 |
| 5 | Shinkin: borrower program candidates and compatibility check | 40,000 | 8,000 | 10 | ¥51.00 | 2 | ¥6 | ¥45.00 |
| 6 | Developer: prototype endpoint check across public datasets | 50,000 | 10,000 | 12 | ¥63.00 | 5 | ¥15 | ¥48.00 |

Total for one run of all six use cases under this baseline:

- External API fee: ¥528.00
- jpcite fee: ¥51
- API fee delta: ¥477.00

Monthly and annual examples may be shown only as repeated applications of the
same API fee delta baseline. Example: use case #3 repeated 100 times is
external API fee ¥7,650, jpcite fee ¥600, monthly API fee delta ¥7,050, and
annualized reference ¥84,600.

## Request-Count Examples

These examples are jpcite usage planning references, not provider comparisons:

| Workflow | Typical units | Tax-excluded estimate |
|---|---:|---:|
| Single program search | 1 | ¥3 |
| Evidence Packet for one question | 1-3 | ¥3-¥9 |
| Company public baseline | 1 | ¥3 |
| Company folder brief | 1 | ¥3 |
| Compatibility check for a small program set | 2-5 | ¥6-¥15 |
| Monthly review for 100 companies, light profile | about 1,800 | about ¥5,400 |
| Invoice status check for 500 counterparties | about 500 | about ¥1,500 |
| Public DD pack for 10 companies | about 280 | about ¥840 |

## Public-Copy Rules

- Say "API fee delta" or "API 料金差額" when comparing external provider fees with jpcite fees.
- State the model, provider tool price, FX rate, token/search counts, and jpcite unit price near the comparison.
- State that actual external invoices depend on model, cache, tool settings, prompt shape, exchange rate, and provider billing rules.
- Do not calculate or imply revenue, profit, business outcome, labor reduction, business-risk, or professional-judgment value.
- Do not use ratio shorthand, certainty language, or zero-error language for public pricing claims.

## Planning Notes

- Use `/v1/cost/preview` before broad POST, batch, or export workflows.
- Use `X-Client-Tag` for customer, matter, or folder-level allocation.
- Use `Idempotency-Key` on retryable POST requests.
- Use `X-Cost-Cap-JPY` when a workflow should stop before a planned budget is exceeded.

jpcite returns public-source evidence and workflow artifacts. Final
professional review remains with the qualified user.
