# jpcite F5 — Agent Funnel 6-Stage Alignment Audit (2026-05-17)

**Framework**: `feedback_agent_funnel_6_stages` (Discoverability → Justifiability → Trustability → Accessibility → Payability → Retainability)
**Scope**: read-only, no LLM call, no network probe. Grep + file probes over /Users/shigetoumeda/jpcite.
**Lane**: solo. Companion of `docs/audit/agent_journey_6step_audit_2026_05_17.md` (AX runner) but framed against the 6-stage **monetisation** funnel, not the 6-step **journey**.

## 1. Stage-by-stage state

| # | Stage | State | Headline evidence | Gap |
| - | --- | --- | --- | --- |
| 1 | Discoverability | **LIVE** | `site/llms.txt` 64 paths + `site/llms-full.txt` + `site/llms.en.txt` + 12 sitemap files (`sitemap-{cases,cities,laws,programs,prefectures,industries,enforcement,facts,qa,structured,pages,cross}.xml`) + `site/.well-known/{agents,mcp,llms,openapi-discovery}.json` + `smithery.yaml` (qualified name `@bookyou/jpcite`) + `server.json` + 7 registry submission stubs in `scripts/registry_submissions/` + `site/.well-known/jpcite-federation.json` (federated MCP) | `scripts/registry_submissions/{mcp_so,pulsemcp,mcp_hunt,cline_pr,cursor,anthropic_directory}.md` are **draft text only** — no evidence of accepted listings on Smithery/Glama/mcp-list landing pages (Wave 49 organic axis still escalation-draft per CLAUDE.md tick 7) |
| 2 | Justifiability | **LIVE** | `src/jpintel_mcp/api/calculator.py` (`/v1/calculator/savings`, JCRB-v1 50q means per model, USD-saved per query) + `site/calculator.html` (¥3/req monthly simulator) + `site/tools/cost_saving_calculator.html` 263 lines (Evidence-Packet break-even calc, 6 use-cases per `feedback_cost_saving_v2_quantified`) + `site/pricing.html` justification table + `site/audiences/{cpa_firm,construction,manufacturing,real_estate}.html` industry-specific use-cases | ROI/ARR framing is correctly removed (`feedback_cost_saving_not_roi`), but break-even per-1000 req comparison vs raw LLM cost is buried; not surfaced on `/llms.txt` or `/.well-known/agents.json` |
| 3 | Trustability | **LIVE (partial)** | §52/§47条の2 disclaimer envelope on 11 sensitive tools (Wave 30) + `schemas/jpcir/policy_decision_catalog.schema.json` (7 sensitive surface × disclaimer matrix) + 14 outcome contracts with `Citation`/`Evidence` Pydantic envelope (`agent_runtime/contracts.py` 19 models) + `site/.well-known/trust.json` 11428B + `audit_log.rss` + `recurring_engagement` (mig 099) + 一次出典 100% on S/A tier programs | **No Wikipedia page**, no third-party Consensus surface (called out in memory). Audit log RSS is live but agent-side discoverability of it is weak (no `.well-known/audit-log.json` index) |
| 4 | Accessibility | **LIVE** | MCP 139–155 tools at default gates (manifest hold) + `mcp-server.json` 230 KB + REST OpenAPI `docs/openapi/v1.json` 307 paths (`agent.json` slim 34 paths) + WebMCP polyfill on 2 site roots (4 tools) + Streamable HTTP transport + A2A skill negotiation (9 skills) + `sdk/{freee,mf,kintone,slack,google-sheets,excel,email}-plugin/` + cookbook `docs/cookbook/r01..r10` 5+ recipes + Wave 51 tick 15 cookbook +5 (r22..r26 = 10 total) | Cookbook is **English / Markdown only**; no curl-paste quick-start on `/` home; no Postman / OpenAI plugin manifest beyond `ai-plugin.json` |
| 5 | Payability | **LIVE (partial)** | Stripe metered (live, ¥3/req), Stripe Customer Portal, child API keys (mig 086), idempotency cache (mig 087), credit-pack ledger (mig 215 + 281), x402 micropayment handler (`functions/x402_handler.ts` + `src/jpintel_mcp/api/x402_payment.py` + 8 tests), credit wallet API (`src/jpintel_mcp/api/credit_wallet.py` + `tests/test_dim_u_credit_wallet.py` + `tests/test_credit_wallet_rest.py`), G5 ledger schema (`schemas/jpcir/billing_event_ledger.schema.json`) | x402 + Wallet **schema-ready, first real txn pending** (per CLAUDE.md tick 5 — "Wave 49 G4/G5 first real txn 未到来で metric flip 待機"). Per-call ¥3 only — no per-outcome bundle pricing surfaced beyond the 14 outcome contracts |
| 6 | Retainability | **PARTIAL** | `src/jpintel_mcp/api/{amendment_alerts,saved_searches,courses,recurring_quarterly,client_profiles,personalization_v2,audit_workpaper_v2}.py` all wired + `scripts/cron/{amendment_alert,amendment_alert_fanout,run_saved_searches,recurring_quarterly,send_daily_kpi_digest,predictive_billing_alert}.py` cron live + `scripts/cron/track_funnel_6stage_daily.py` (the locked KPI tracker) + `site/alerts.html` + `site/alerts-unsubscribe.html` + Slack/email digest course router + `houjin_watch` (mig 088) + webhook dispatch | **No D30 retention number** in any public surface. `site/alerts.html` only has 18 hits of subscribe/amendment language — UX is bare. `track_funnel_6stage_daily.py` exists but its output `analytics/funnel_6stage_daily.jsonl` is not surfaced on `/facts` or `/status`. Saved-search seeds (`data/sample_saved_searches.json`) only 9 entries × weekly cadence |

## 2. Bottleneck identify (薄い 2 stage)

### Bottleneck A — Retainability (Stage 6)

**Diagnosis**: All substrate is built (cron, tables, REST, Slack/email surfaces), but the **engagement loop is invisible to a new agent**. There is no public retention number, no `/.well-known/retention.json`, no "how many times agents come back" surface. `feedback_agent_new_kpis_8` calls out ARC (Agent Re-call rate) and Retention as required — neither is exposed.

### Bottleneck B — Payability live-flow (Stage 5)

**Diagnosis**: x402 + Credit Wallet are 100% schema-ready (migrations 281, ledger schema, tests, edge handlers), but **no first real txn has flowed**. Without one paid x402 trade, "Payability" is theoretical — agents that prefer x402 (Coinbase Commerce-class) cannot confirm the rail. Stripe is live so the stage is not zero, but the multi-rail story called out in `feedback_agent_monetization_3_payment_rails` is single-rail in practice.

## 3. 3-5 concrete actions per bottleneck

### Retainability lift actions

1. **Surface D30 retention publicly**. Add `site/.well-known/retention.json` emitting last-30-day D7/D30 numbers from `analytics/funnel_6stage_daily.jsonl`. Bind to `track_funnel_6stage_daily.py` output, regenerate via existing `analytics-cron.yml`.
2. **`/alerts` UX expand**. Current `site/alerts.html` is 1-call-to-action. Add: (a) 4 amendment-watch examples (税法・補助金・行政処分・適格事業者), (b) sample webhook payload, (c) curl-paste subscribe snippet, (d) Slack/email/RSS triple-rail picker.
3. **Saved-search seeds widen**. `data/sample_saved_searches.json` 9 → 30+, covering all 8 cohorts (M&A / 税理士 / 会計士 / FDI / 補助金 consultant / LINE / 信金 / industry packs). Each seed = a re-engagement loop for an agent operator.
4. **Agent retention KPI on `/facts`**. Add ARC + D30 as honest numbers on `site/facts.html` (already lists 12 cross-reference axes). Bind to `funnel_6stage_daily.jsonl` so the number is non-fake.
5. **Recurring-quarterly opt-in surface**. `recurring_quarterly` router is mounted but no public landing-page lists it as a benefit; add a `/recurring` page or a `/qa/retainability/` subtree.

### Payability lift actions

1. **First real x402 txn**. Drive 1 end-to-end x402 micropayment using `functions/x402_handler.ts` against `api.jpcite.com`. Record the txn hash in `analytics/x402_first_txn.json` so the "first txn" claim is verifiable.
2. **`/.well-known/jpcite-federation.json` advertise x402**. Already exists at 5162B; add explicit `payment_rails: ["stripe","x402","credit_wallet"]` and link to operator-facing how-to.
3. **Credit-Wallet topup UX live first-trade**. Schema for `credit_wallet` is migration 281 + 281_rollback; surface a `/wallet` minimal HTML for prepaid agents (per `feedback_agent_credit_wallet_design`: pre-pay + auto-topup + 50/80/100% alert throttle).
4. **Outcome-bundle pricing publish**. `agent_runtime/contracts.py` carries 14 outcome contracts with `estimated_price_jpy` ¥300-¥900. Today's surfacing is per-req ¥3 only. Add a `/pricing/outcomes` page listing the 14 bundles so agents can pick outcome > req.

## 4. Conversion-rate funnel target (希望値)

Linear funnel from a Japanese-tax / 補助金 question posed to an agent operator:

| Step | Action | Target conversion | Notes |
| --- | --- | ---: | --- |
| Entry | Agent (LLM/Claude/GPT) is asked a Japan public-program / 補助金 / 税 question; the agent looks up discovery surface | 100% input | baseline = agent-impressionable query volume |
| Step 1 | Agent reaches `jpcite.com` (or `llms.txt` / `agents.json` / Smithery / Glama) | **20%** | most agents still answer from training data; lift drives Discoverability |
| Step 2 | Agent downloads `llms.txt` + reads `cost_saving_calculator` justification | **60%** | of those that arrived; Justifiability is already strong |
| Step 3 | Agent connects MCP (or hits anonymous REST 3/day) | **40%** | of those justified; MCP install friction + WebMCP polyfill |
| Step 4 | Agent (or operator) makes first ¥3 paid spend | **15%** | of those connected; Stripe checkout / API-key issue / x402 first txn |
| Step 5 | Agent crosses 100 req/month threshold | **30%** | of paid; Payability + Accessibility combined |
| Step 6 | Agent operator returns at month+30 (D30 retention) | **45%** | of 100 req/month users; Retainability target |

End-to-end multiplicative rate (Entry → Repeat user at D30):
**20% × 60% × 40% × 15% × 30% × 45% ≈ 0.097%** of impressionable agent queries become repeat-user revenue at month-2.

Agent-volume-multiplier shape: per `feedback_agent_funnel_6_stages`, "1 段でも欠ければ売上ゼロ" — so the 6 multiplicative factors are the audit's main lens. The two thin stages (Retainability + Payability live-flow) lift the largest absolute revenue per +1pt (last 2 factors are 45% × 30% — moving either by +5pt has 25-30% revenue effect).

## 5. Audit summary

- **Discoverability / Justifiability / Trustability / Accessibility**: LIVE (8/10+ across surfaces). AX 5-pillar audit 2026-05-12 already scored 60/60 on the parallel Biilmann framing.
- **Payability**: LIVE (Stripe), schema-ready (x402 + Wallet), but multi-rail story is theoretical until first real x402 txn.
- **Retainability**: substrate LIVE, public-facing surface and KPI are thin — biggest near-term lift.

last_updated: 2026-05-17
