# jpcite Request Cost Examples

**Last updated**: 2026-05-12
**Brand**: jpcite (Bookyou株式会社)

This page gives simple request-count examples for planning jpcite usage. The
numbers are estimates for typical workflows; actual usage depends on the
endpoint, filters, batch size, and retry behavior.

## Pricing Inputs

- Standard metered price: ¥3 / billable unit, tax excluded
- Tax-included reference: ¥3.30 / billable unit
- Anonymous trial: 3 requests / day per IP, reset at 00:00 JST

## Example Workflows

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

## Planning Notes

- Use `/v1/cost/preview` before broad POST, batch, or export workflows.
- Use `X-Client-Tag` for customer, matter, or folder-level allocation.
- Use `Idempotency-Key` on retryable POST requests.
- Use `X-Cost-Cap-JPY` when a workflow should stop before a planned budget is exceeded.

## Calculator

For a quick estimate, use `/tools/cost_saving_calculator.html` and enter the
expected billable unit count.

## API Fee Delta Baseline

When this site shows a provider comparison, the number is only an API fee delta
under the stated baseline: external provider token fee plus web-search tool fee
using the selected model, selected search vendor, USD/JPY rate, and the listed
token/search counts, compared with jpcite billable units at ¥3 tax excluded.

The default public baseline is Claude Sonnet 4.5, Anthropic web search,
USD/JPY=150, and the six calculator use cases. It excludes labor, business outcome, revenue, profit, business-risk estimates, and professional
judgment. Actual external provider invoices depend on model, cache, tool
settings, prompt shape, exchange rate, and provider billing rules.

These examples are planning references only. jpcite returns public-source
evidence and workflow artifacts; final professional review remains with the
qualified user.
