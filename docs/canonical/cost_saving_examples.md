# jpcite API Fee Delta Examples

**Status**: canonical public-pricing safety SOT
**Last updated**: 2026-05-13
**Brand**: jpcite (Bookyou株式会社)
**Lineage**: Wave 46 tick#4 audience migration + Wave 48 API fee delta v2

Former public label: jpcite Cost Saving Examples.

This document defines the public-safe language for jpcite pricing comparisons.
Any public comparison must describe an API fee delta under a stated baseline
only. It must not present revenue, profit, labor reduction, business
outcome, or professional-judgment value as a calculated result.

For legacy audience and recipe parity, the allowed Japanese shorthand is
`API fee delta` when, and only when, it refers to the API
fee delta between a stated external model/search baseline and jpcite's
¥3/req metered fee. The shorthand does not claim certain invoice
reduction or business outcome.

## Pricing Inputs

- Standard metered price: ¥3/billable unit, tax excluded
- Tax-included reference: ¥3.30 / billable unit
- Anonymous trial: 3 requests / day per IP, reset at 00:00 JST

## Wave 46 tick#4 Audience Cost Saving References

These 14 entries are the canonical page-level examples used by
`site/audiences/*.html`. They are planning references only under stated
assumptions, not business outcome, revenue, profit, labor-reduction, or
outcome claims.

| Audience page | Workload label | jpcite price basis | Reference delta |
|---|---|---|---:|
| admin-scrivener | Permit prep | ¥3/billable unit | ¥34,995 |
| construction | Construction subsidy / permit pre-check | ¥3/billable unit | ¥31,994 |
| dev | Public-data API prototype | ¥3/billable unit | ¥19,985 |
| index | Weighted audience average | ¥3/billable unit | ¥26,991 |
| journalist | Source-backed public-interest check | ¥3/billable unit | ¥11,991 |
| manufacturing | Equipment subsidy source check | ¥3/billable unit | ¥31,994 |
| real_estate | Real-estate compliance pre-check | ¥3/billable unit | ¥27,994 |
| shihoshoshi | Commercial-registration source check | ¥3/billable unit | ¥29,994 |
| shinkin | Borrower support program scan | ¥3/billable unit | ¥7,194 |
| shokokai | Member consultation pre-check | ¥3/billable unit | ¥3,994 |
| smb | Owner-facing public program scan | ¥3/billable unit | ¥9,991 |
| subsidy-consultant | Subsidy requirement extraction | ¥3/billable unit | ¥11,991 |
| tax-advisor | Tax measure applicability pre-check | ¥3/billable unit | ¥9,994 |
| vc | M&A / investment public DD pre-check | ¥3/billable unit | ¥39,988 |

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
| UC-1 | M&A DD: company permissions, adoption, enforcement check | 120,000 | 20,000 | 25 | ¥136.50 | 4 | ¥12 | ¥124.50 |
| UC-2 | Subsidy requirements, source URL, compatibility extraction | 80,000 | 15,000 | 18 | ¥96.75 | 2 | ¥6 | ¥90.75 |
| UC-3 | Tax advisor: measure applicability and circular cross-reference | 60,000 | 12,000 | 15 | ¥76.50 | 2 | ¥6 | ¥70.50 |
| UC-4 | Admin scrivener: permit basis, circular, form walk-through | 90,000 | 15,000 | 20 | ¥104.25 | 2 | ¥6 | ¥98.25 |
| UC-5 | Shinkin: borrower program candidates and compatibility check | 40,000 | 8,000 | 10 | ¥51.00 | 2 | ¥6 | ¥45.00 |
| UC-6 | Developer: prototype endpoint check across public datasets | 50,000 | 10,000 | 12 | ¥63.00 | 5 | ¥15 | ¥48.00 |

Total for one run of all six use cases under this baseline:

- External API fee: ¥528.00
- jpcite fee: ¥51
- API fee delta: ¥477.00

Monthly and annual examples may be shown only as repeated applications of the
same API fee delta baseline. Example: use case #3 repeated 100 times is
external API fee ¥7,650, jpcite fee ¥600, monthly API fee delta ¥7,050, and
annualized reference ¥84,600.

## v2 — 「普通に AI を使う」vs jpcite MCP

This v2 section is the calculator SOT for comparing external model + web
search fees with fixed jpcite MCP billable units. It intentionally measures
only API fee delta. It does not value professional review, business outcome,
or downstream commercial impact.

Reference price sources:

- Anthropic Pricing: https://www.anthropic.com/pricing
- OpenAI API Pricing: https://openai.com/api/pricing
- jpcite public pricing: https://jpcite.com/pricing.html

### § C. 6 use case side-by-side calculator

| # | Use case | Input tokens | Output tokens | Web searches | jpcite req | Pure model/search fee | jpcite fee | API fee delta |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | M&A DD | 120,000 | 20,000 | 25 | 4 | ¥136.50 | ¥12 | ¥124.50 |
| 2 | 補助金 | 80,000 | 15,000 | 18 | 2 | ¥96.75 | ¥6 | ¥90.75 |
| 3 | 措置法 | 60,000 | 12,000 | 15 | 2 | ¥76.50 | ¥6 | ¥70.50 |
| 4 | 行政書士 | 90,000 | 15,000 | 20 | 2 | ¥104.25 | ¥6 | ¥98.25 |
| 5 | 信金 | 40,000 | 8,000 | 10 | 2 | ¥51.00 | ¥6 | ¥45.00 |
| 6 | dev | 50,000 | 10,000 | 12 | 5 | ¥63.00 | ¥15 | ¥48.00 |

### § E. 再現可能な計算スクリプト

```python
USD_JPY = 150
JPCITE_PER_REQ_JPY = 3
MODEL_IN_USD_PER_MTOK = 3.00
MODEL_OUT_USD_PER_MTOK = 15.00
SEARCH_USD_PER_1K = 10.00

def pure_llm_jpy(input_tokens, output_tokens, searches):
    return (
        input_tokens * MODEL_IN_USD_PER_MTOK / 1_000_000 * USD_JPY
        + output_tokens * MODEL_OUT_USD_PER_MTOK / 1_000_000 * USD_JPY
        + searches * SEARCH_USD_PER_1K / 1_000 * USD_JPY
    )

def jpcite_jpy(requests):
    return requests * JPCITE_PER_REQ_JPY
```

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
