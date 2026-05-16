# AWS scope expansion 23/30: pricing, packaging, agent sales, and GEO billing route

Date: 2026-05-15  
Owner lane: expansion deep dive 23/30, pricing / packaging / agent sales  
Status: planning document only. No AWS CLI/API execution, no AWS resource creation, no deployment, no existing code changes.  
Output file: `docs/_internal/aws_scope_expansion_23_pricing_packaging_agent_sales.md`

## 0. Executive answer

jpcite should not sell "search." It should sell cheap, source-backed, AI-agent-callable outcomes.

The end-user concept is:

1. The user asks an AI agent for a practical result: "この会社を公的情報で確認して", "この補助金に近いものを探して", "この業法で何を確認すべきか", "このCSVから月次で注意点を出して".
2. The AI agent first calls a free jpcite preview.
3. Preview returns what can be checked, which official sources will be used, known gaps, price, cap, and why jpcite is appropriate.
4. The AI agent recommends either no paid call, a cheap one-shot packet, or an API/MCP metered execution with a cap.
5. Paid output returns `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata`, `human_review_required`, and `_disclaimer`.

The pricing design must preserve the existing P0 rule:

```text
visible_meter_unit_price = 3 JPY ex-tax per billable unit
unit_price_inc_tax = 3.30 JPY
free_preview = always free
paid_execution_requires = API key + hard cap + idempotency for broad/retry-sensitive work
```

At the same time, end users should see understandable packet prices. The reconciliation is:

```text
packet_display_price = fixed_or_estimated_billable_units * 3 JPY ex-tax
packet_display_price_inc_tax = fixed_or_estimated_billable_units * 3.30 JPY
```

So jpcite can show "99円の確認packet" or "3,300円の申請準備packet" without changing the canonical 3円/unit meter.

## 1. Non-negotiable constraints

These rules prevent contradiction with the main P0 plan.

| Area | Rule |
|---|---|
| Pricing source of truth | One runtime packet catalog/policy. Docs, OpenAPI, MCP, public pages, and frontend must be generated or drift-tested against it. |
| Free preview | Free preview does not consume anonymous 3 req/day/IP execution quota and does not create billable usage. |
| Unit price | P0 public unit remains 3 JPY ex-tax / 3.30 JPY inc-tax. |
| Packet price | Packet prices are fixed or estimated unit budgets multiplied by the 3 JPY unit price. |
| Paid execution | API key, cost cap, and idempotency key are required before billable broad/retry-sensitive work starts. |
| External costs | External LLM, agent runtime, web search, cloud, SaaS connector, and MCP client costs are not included. |
| No-hit | `no_hit_not_absence`; no-hit is not proof of absence, safety, compliance, eligibility, or no risk. |
| Professional fence | No legal/accounting/tax/investment/credit/fraud/safety final judgment. Outputs are evidence packets, checklists, candidates, ledgers, and handoff material. |
| Request-time LLM | Paid jpcite output does not depend on request-time LLM generation. |
| CSV privacy | Raw private CSV should not be persisted, logged, echoed, or uploaded to AWS in the production concept. |

## 2. Product thesis

The strongest commercial position is:

> AI agents can answer more safely and cheaply when they buy small, official-source evidence packets instead of asking an LLM to infer facts from memory or free-form browsing.

This is not normal SaaS pricing. The buyer is often an end user, but the recommender and caller is an AI agent. The pricing surface must therefore be machine-readable and recommendation-friendly.

An AI agent needs to know:

1. What exact outcome this packet produces.
2. What official source families are checked.
3. What the packet will not claim.
4. What information is still missing.
5. Whether the user should pay for it.
6. How much it will cost before execution.
7. How to cap the spend.
8. How to cite and preserve the returned receipts.

## 3. The pricing ladder

### 3.1 Canonical tiers

These are not discounts. They are understandable packet shapes built on the same 3 JPY/unit meter.

| Tier | Display price ex-tax | Display price inc-tax | Units | Best use | AI recommendation threshold |
|---|---:|---:|---:|---|---|
| Free preview | 0 JPY | 0 JPY | 0 | Can jpcite help? What sources and gaps? | Always before a paid call. |
| Nano receipt | 30 JPY | 33 JPY | 10 | Single source receipt or source availability proof. | Use when user only needs a citation anchor. |
| Micro check | 90 JPY | 99 JPY | 30 | One exact lookup or status confirmation. | Use when one identifier is known. |
| Starter packet | 300 JPY | 330 JPY | 100 | One subject baseline or one small checklist. | Use when a user asks a concrete business question. |
| Standard packet | 900 JPY | 990 JPY | 300 | Multi-source one-shot evidence packet. | Use when the answer would otherwise require manual source traversal. |
| Professional packet | 3,000 JPY | 3,300 JPY | 1,000 | Regulated workflow, grant readiness, DD lite, CSV-derived profile. | Use when the output saves professional review time. |
| Heavy packet | 9,000 JPY | 9,900 JPY | 3,000 | Broad CSV, portfolio, jurisdiction sweep, or proof binder. | Use only with explicit cap and clear user benefit. |
| Custom capped run | User cap | User cap | Derived | Large batch/API/MCP run. | Use only when preview shows exact units and cap. |

### 3.2 Why this ladder works

The ladder lets agents say:

> 無料で見積もれます。必要なら99円、330円、990円、3,300円のような小さい単位で、公的一次情報に基づく証跡packetを取れます。外部LLM費用は別で、jpcite側はcapを超えません。

The user does not need to understand unit metering first. The API still stays metered and precise.

### 3.3 What not to do

Do not launch with:

- Seat-based pricing as the main product.
- "Unlimited" claims.
- A hidden minimum monthly fee.
- Per-agent opaque subscription plans.
- "AI legal/accounting answer" packaging.
- "Safety/risk/compliance guaranteed" packaging.
- Pricing pages that drift from MCP/OpenAPI/catalog metadata.

## 4. Free preview design

Free preview is the conversion engine. It must be useful enough for the agent to recommend a paid call, but not leak the full paid output.

### 4.1 Free preview returns

| Field | Example | Purpose |
|---|---|---|
| `can_help` | `true`, `maybe`, `no` | Agent route decision. |
| `recommended_packet` | `counterparty_public_dd_packet` | Agent can name the paid packet. |
| `source_families` | `NTA法人番号`, `インボイス`, `gBizINFO`, `行政処分`, `業法` | Shows evidence basis. |
| `required_inputs` | corporate number, T-number, company name/address | Avoids bad paid calls. |
| `known_gaps_preview` | prefecture unknown, permit type unknown | Shows limits before payment. |
| `no_hit_policy` | `no_hit_not_absence` | Prevents overclaiming. |
| `price_quote` | 300 units, 990円税込 max | Enables user approval. |
| `cap_required` | true | Makes spend control explicit. |
| `agent_recommendation_text` | short Japanese sentence | Agent can quote to the user. |
| `do_not_use_when` | legal final judgment requested | Agent can skip jpcite when inappropriate. |

### 4.2 Free preview must not return

- Full `source_receipts[]` for all paid sources.
- Full hit details for high-value records.
- Export-ready JSON.
- Batch row-level full results.
- A professional final opinion.
- Any private raw CSV content.

### 4.3 Preview examples by buyer intent

| User request | Preview should say | Paid trigger |
|---|---|---|
| "この会社を調べて" | "法人同定、インボイス、gBizINFO、業界許認可/処分sourceを確認できます" | User needs evidence/citations. |
| "この補助金使える?" | " eligibility cannot be finalized; candidate programs and missing inputs can be returned" | User wants shortlist/checklist. |
| "この業法に触れる?" | "final legal judgment cannot be made; applicable source/checklist candidates can be returned" | User wants source-backed checklist. |
| "CSVから月次レビューして" | "raw CSVは保存せず、派生factsで対象数と価格を見積もれます" | User accepts cap after row reconciliation. |
| "契約先として大丈夫?" | "risk/safety cannot be guaranteed; public-evidence attention score can be returned" | User needs public evidence summary. |

## 5. Paid packet catalog for revenue

### 5.1 P0 and near-P0 packets

| Packet | Price tier | Units | Inc-tax | Primary buyer | Why agent recommends it | AWS artifacts needed |
|---|---:|---:|---:|---|---|---|
| `agent_routing_decision` | Free | 0 | 0 | Any AI agent | Decide whether jpcite should be used. | routing examples, skip reasons, cost preview fixtures |
| `source_receipt_ledger` | Nano/Starter | 10-100 | 33-330 | Agents, reviewers | Need citation/provenance without narrative. | receipt fixtures, receipt completeness tests |
| `evidence_answer` | Starter/Standard | 100-300 | 330-990 | General users | A question needs cited public facts. | sample questions, claim_ref graph |
| `company_public_baseline` | Starter | 100 | 330 | Sales, procurement, accounting | One company needs public baseline. |法人番号/インボイス/gBizINFO sample packets |
| `application_strategy` | Standard/Professional | 300-1,000 | 990-3,300 | SMB,士業,BPO | User needs candidate programs and missing info. | J-Grants/local program examples |
| `client_monthly_review` | Heavy/capped | 100-3,000+ | 330-9,900+ | Accountants, consultants | CSV turns into many cheap subject checks. | CSV privacy fixtures, row reconciliation examples |

### 5.2 Highest-revenue one-shot packets

| Rank | Packet | Price tier | Units | Inc-tax | Revenue logic | Required source foundation |
|---:|---|---:|---:|---:|---|---|
| 1 | `counterparty_public_dd_packet` | Standard | 300 | 990 | High frequency, clear business value, agent can recommend often. |法人番号, インボイス, gBizINFO, EDINET,行政処分,許認可 |
| 2 | `grant_candidate_shortlist_packet` | Professional | 1,000 | 3,300 | Saves manual research time; strong willingness to pay. | J-Grants,自治体,厚労省,中小企業庁,ミラサポplus |
| 3 | `permit_scope_checklist_packet` | Professional | 1,000 | 3,300 | Regulated work has high pain; output is a checklist, not legal judgment. | e-Gov,省庁,自治体,業法,通達,手引き |
| 4 | `regulation_change_impact_packet` | Standard/Professional | 300-1,000 | 990-3,300 | Recurring and GEO-friendly. | 法令XML,官報,パブコメ,告示,通達 |
| 5 | `vendor_public_risk_attention_packet` | Standard | 300 | 990 | Procurement and sales teams ask this repeatedly. |法人番号,処分,登録,調達,官報,EDINET |
| 6 | `invoice_vendor_public_check` | Starter | 100 | 330 | Cheap, exact, high-volume accounting use. | インボイス,法人番号 |
| 7 | `public_procurement_opportunity_packet` | Standard/Professional | 300-1,000 | 990-3,300 | B2B users pay for leads and fit evidence. | 調達ポータル,自治体,官報,省庁 |
| 8 | `privacy_vendor_checklist_packet` | Professional | 1,000 | 3,300 | SaaS/vendor review has budget and repeat use. | PPC, e-Gov, ISMAP/PMark/ISMS public data |
| 9 | `construction_license_scope_packet` | Professional | 1,000 | 3,300 | Construction licensing is concrete and valuable. | 国交省,建設業者検索,ネガティブ情報,e-Gov |
| 10 | `csv_monthly_public_review_packet` | Heavy/capped | variable | variable | Multi-row recurring revenue. | CSV derived facts + all public sources |

### 5.3 Vertical packet prices

These prices are launch defaults. They should be generated from the packet catalog and exposed consistently.

| Vertical | Packet | Launch tier | Units | Inc-tax | Free preview hook |
|---|---|---:|---:|---:|---|
| 建設 | `construction_license_scope_packet` | Professional | 1,000 | 3,300 | 工事種別と地域から確認sourceを提示 |
| 不動産 | `real_estate_public_context_packet` | Standard | 300 | 990 | 物件地域/用途で公的context sourceを提示 |
| 運輸 | `transport_operator_public_check` | Standard | 300 | 990 | 事業区分と登録/処分sourceを提示 |
| 人材 | `labor_dispatch_public_check` | Standard | 300 | 990 | 許可/届出/処分sourceを提示 |
| 産廃 | `waste_vendor_permit_check` | Professional | 1,000 | 3,300 | 廃棄物種類/地域/許可区分を提示 |
| 医療/介護 | `care_provider_public_check` | Standard | 300 | 990 | 施設/事業者sourceを提示 |
| 食品 | `food_business_public_checklist` | Standard | 300 | 990 | 営業許可/表示/回収sourceを提示 |
| 金融 | `financial_registration_warning_packet` | Standard | 300 | 990 | 登録/注意喚起sourceを提示 |
| IT/個人情報 | `privacy_vendor_checklist_packet` | Professional | 1,000 | 3,300 | PPC/e-Gov/認証sourceを提示 |
| 輸出入 | `trade_control_source_navigation_packet` | Professional/Heavy | 1,000-3,000 | 3,300-9,900 | HS/用途/相手国/制度sourceを提示 |

## 6. Bundles

P0 should avoid discounted complex plans. Bundles should be "workflow cap presets" and "prepaid usage envelopes," not separate pricing rules.

### 6.1 Launch bundles

| Bundle | Target user | Included behavior | Price display | Implementation rule |
|---|---|---|---|---|
| Agent free route | AI agents | unlimited-ish cost previews subject to abuse controls | 0 JPY | No billable usage. |
| Trial evidence pack | first-time users | small number of nano/micro/starter executions | 300-1,000 JPY cap | Same 3 JPY units; no discount needed. |
| SMB monthly pack | small business/accountant | CSV monthly review cap preset | 3,300-9,900 JPY cap | User sets cap; bills actual units. |
| Professional review pack |士業/BPO | grant/permit/vendor packets | 9,900-33,000 JPY cap | Multiple packet executions under one cap. |
| Portfolio API pack | larger agent workflows | batch/API/MCP cap and daily limits | custom cap | Metered units, not unlimited. |
| Watchlist pilot | recurring workflows | monthly delta checks | monthly cap | Bill only successful configured checks. |

### 6.2 Why cap presets are better than discounts

Cap presets are safer for agents:

- The agent can ask: "この上限で実行してよいですか?"
- The user understands maximum spend.
- The system can reject before work starts.
- Stripe/invoice can reconcile actual units.
- It avoids a second pricing source of truth.

### 6.3 Future volume discounts

If volume discounts are introduced later, they must be represented as `effective_unit_price` with a `pricing_version` and drift tests. They should not be part of P0 because they create catalog, billing, docs, and agent explanation complexity.

## 7. Usage caps

Usage caps are a product feature, not just a billing control.

### 7.1 Required cap levels

| Cap | Required for | Example |
|---|---|---|
| Per-request cap | all paid broad work | `max_jpy_inc_tax=990` |
| Per-batch cap | CSV/batch/API fanout | `max_jpy_inc_tax=9900` |
| Per-day cap | API key protection | `daily_max_jpy_inc_tax=33000` |
| Per-month cap | budget safety | `monthly_max_jpy_inc_tax=99000` |
| Per-packet cap | prevent expensive packet class | `deny_heavy_packet=true` |
| Per-agent cap | connector safety | `agent_id=claude_code,max=3300/day` |
| Per-source cap | expensive OCR/screenshot derived packets later | `max_receipts=100` |

### 7.2 Cap response fields

```json
{
  "cap_check": {
    "cap_required_for_paid_execution": true,
    "provided_cap_jpy_inc_tax": 990,
    "estimate_jpy_inc_tax_max": 990,
    "would_execute_under_cap": true,
    "reject_if_estimate_exceeds_cap": true,
    "actual_bill_may_be_lower": true,
    "external_costs_included": false
  }
}
```

### 7.3 Cap copy for agents

Use this exact style:

> jpciteの無料previewでは、このpacketは最大300 units、税込990円の見込みです。実行する場合は税込990円のhard capを付けます。外部LLMやエージェント実行環境の費用は含まれません。

Avoid:

- "だいたい安いです"
- "必要なら勝手に実行します"
- "追加料金はありません"
- "無制限"
- "法的に安全です"

## 8. Agent-facing sales route

### 8.1 The route

```text
GEO discovery page
  -> agent reads packet catalog / llms.txt / .well-known
  -> agent calls free routing decision or cost preview
  -> agent receives price, cap, sources, known gaps, and sample output
  -> agent asks user for paid execution approval
  -> user approves cap
  -> agent calls REST/MCP with API key, cap, idempotency
  -> jpcite returns source-backed packet
  -> agent cites receipts and preserves known gaps
```

### 8.2 Agent recommendation rules

An agent should recommend jpcite when all are true:

1. The user asks for a result involving Japanese public official information.
2. The answer would benefit from citations, source timestamps, IDs, or no-hit boundaries.
3. The request can be expressed as a packet, checklist, candidate list, ledger, or evidence binder.
4. The user is likely to value paying 99-3,300 JPY more than doing manual source work.
5. The agent can set a cap before paid execution.

An agent should not recommend jpcite when:

1. The user needs a final legal/accounting/tax/investment/credit judgment.
2. The user asks for private or non-public data that jpcite does not have.
3. The required source family is outside coverage and no meaningful preview can be given.
4. The user will not accept known gaps or human review requirement.
5. The request is purely conversational and does not need evidence packets.

### 8.3 MCP tool description pattern

Each MCP tool should include:

```text
Use this tool when the user needs a Japanese official-source evidence packet for {outcome}.
Always call cost preview first unless the user already supplied an explicit cap.
The tool returns source_receipts, claim_refs, known_gaps, billing_metadata, and a no-hit boundary.
It does not provide legal/accounting/tax/investment/credit final judgments.
External LLM/agent costs are not included in jpcite pricing.
```

### 8.4 OpenAPI operation description pattern

Each REST operation should include:

```text
Creates a source-backed packet for {outcome}. Paid execution requires an API key,
Idempotency-Key, and X-Cost-Cap-JPY for broad/retry-sensitive workflows.
Use /v1/cost/preview first to estimate units and price.
```

## 9. GEO surfaces

### 9.1 Required public pages

| Page | Purpose | Must include |
|---|---|---|
| `/packets` | Agent-readable catalog | packet names, use cases, preview link, price tier |
| `/packets/{packet}` | Packet-specific proof | sample input/output, source receipts, known gaps, price/cap |
| `/pricing` | Pricing contract | 3 JPY/unit, packet examples, caps, external costs excluded |
| `/docs/mcp` | Agent integration | tool names, cost preview, auth, cap examples |
| `/docs/openapi` | REST integration | operation IDs, examples, pricing fields |
| `/proof` | Trust evidence | receipt examples, claim_refs, no-hit examples |
| `/llms.txt` | Agent discovery | packet catalog, pricing, MCP/OpenAPI links |
| `/.well-known/ai-plugin.json` or equivalent | machine discovery | API/MCP endpoints, auth, docs |

### 9.2 GEO page copy should emphasize

- "Japanese public official information."
- "Free preview before paid execution."
- "Metered at 3 JPY ex-tax per billable unit."
- "Small packet examples: 99円, 330円, 990円, 3,300円."
- "Hard caps before paid execution."
- "Source receipts and known gaps."
- "No request-time LLM hallucination in jpcite output."
- "No final professional judgment."

### 9.3 GEO eval prompts to generate

AWS should generate and test prompts like:

| Prompt | Desired agent behavior |
|---|---|
| "日本の法人番号とインボイスを公的情報で確認したい" | Recommend free preview then `company_public_baseline` or `invoice_vendor_public_check`. |
| "建設会社に発注する前に許可や処分を確認したい" | Recommend `construction_license_scope_packet` or `counterparty_public_dd_packet`. |
| "補助金候補をAIで安く探したい" | Recommend `grant_candidate_shortlist_packet`; explain no eligibility guarantee. |
| "CSVで取引先の月次レビューをしたい" | Recommend CSV preview; explain raw CSV privacy and cap. |
| "この会社は安全ですか" | Do not promise safety; recommend public evidence attention packet if appropriate. |

## 10. Revenue model

### 10.1 Formula

For a GEO-first product:

```text
monthly_revenue =
  agent_discovery_sessions
  * preview_call_rate
  * paid_conversion_rate
  * average_paid_units
  * 3 JPY
```

Where:

```text
agent_discovery_sessions = visits or agent reads of GEO/llms/OpenAPI/MCP surfaces
preview_call_rate = share that call free preview
paid_conversion_rate = share of previews that execute paid packets
average_paid_units = weighted units per paid execution
```

### 10.2 Scenario table

These are planning scenarios, not forecasts.

| Scenario | Agent discovery sessions/mo | Preview call rate | Paid conversion | Avg units | Revenue ex-tax/mo |
|---|---:|---:|---:|---:|---:|
| Very early | 5,000 | 5% | 8% | 150 | 90,000 JPY |
| Base organic | 50,000 | 8% | 10% | 250 | 3,000,000 JPY |
| Strong GEO | 200,000 | 10% | 12% | 300 | 21,600,000 JPY |
| Vertical breakout | 500,000 | 12% | 15% | 450 | 121,500,000 JPY |

Formula check for base organic:

```text
50,000 * 0.08 * 0.10 * 250 * 3 = 3,000,000 JPY
```

The sensitivity is obvious: GEO discovery and conversion matter more than raising prices.

### 10.3 Revenue by packet family

| Packet family | Expected frequency | Avg units | Inc-tax display | Conversion strength | Revenue priority |
|---|---:|---:|---:|---|---|
| Exact lookup / receipt | High | 10-30 | 33-99 | Medium | Good for trust and habit. |
| Company/vendor baseline | Very high | 100-300 | 330-990 | High | P0 commercial core. |
| Grant/program shortlist | Medium | 1,000 | 3,300 | High | High value, strong willingness to pay. |
| Permit/industry checklist | Medium | 1,000 | 3,300 | High | Strong vertical monetization. |
| Regulation change impact | Medium/recurring | 300-1,000 | 990-3,300 | Medium-high | Good for watchlists later. |
| CSV monthly review | Lower users, high units | variable | cap-based | High when CSV works | Strong expansion path. |
| Proof/audit binder | Medium | 300-3,000 | 990-9,900 | Medium | Useful for professional handoff. |
| Watchlist delta | Recurring | 30-300/item/mo | cap-based | Medium | P1/P2 recurring revenue. |

### 10.4 What to optimize first

Do not optimize for the highest one-shot price first. Optimize for:

1. Agent trust.
2. Free preview conversion.
3. Low-friction 99-990 JPY first purchases.
4. Repeatable 3,300 JPY professional packets.
5. CSV/batch cap-based multi-unit workflows.
6. Recurring watchlist deltas after proof of demand.

## 11. AWS artifacts to create

AWS credit should be used to produce pricing and sales assets that survive after AWS is shut down.

### 11.1 Pricing artifacts

| Artifact | File shape | Why it matters |
|---|---|---|
| `pricing_matrix.json` | packet -> tier -> units -> price -> cap | Runtime/docs/OpenAPI/MCP consistency. |
| `packet_price_examples.jsonl` | example input, estimate, cap, output summary | Public examples and tests. |
| `cost_preview_fixtures.jsonl` | request/response pairs | CI tests and agent docs. |
| `billing_reconciliation_fixtures.jsonl` | preview vs actual units | Prevent billing disputes. |
| `cap_policy_matrix.json` | endpoint/tool -> cap required | Release gate. |
| `no_charge_reason_codes.json` | preflight reject reasons | Agents can explain why no bill occurred. |
| `unit_formula_registry.json` | billable unit formulas | One source for pricing math. |
| `pricing_copy_blocks.json` | approved Japanese/English snippets | Prevents unsafe frontend/docs copy. |

### 11.2 Sales and GEO artifacts

| Artifact | Purpose |
|---|---|
| `agent_recommendation_examples.jsonl` | Shows when an AI agent should recommend paid jpcite. |
| `agent_skip_examples.jsonl` | Shows when jpcite should not be used. |
| `geo_pricing_query_set.jsonl` | Prompts for GEO eval around pricing and caps. |
| `packet_landing_page_inputs.jsonl` | Generated packet pages with prices and examples. |
| `pricing_faq_generated.md` | User and agent pricing explanation. |
| `mcp_tool_pricing_snippets.json` | Tool descriptions and cap examples. |
| `openapi_pricing_examples.json` | Operation examples with `billing_metadata`. |
| `llms_pricing_manifest.txt` | Agent discovery text. |

### 11.3 Sample paid-output artifacts

For each high-priority packet, AWS should generate:

1. Free preview sample.
2. Paid packet sample.
3. No-hit sample.
4. Known-gaps-heavy sample.
5. Cap-exceeded reject sample.
6. Idempotency retry sample.
7. Agent recommendation sentence.
8. Agent skip sentence.

Priority packets:

```text
agent_routing_decision
source_receipt_ledger
evidence_answer
company_public_baseline
counterparty_public_dd_packet
invoice_vendor_public_check
grant_candidate_shortlist_packet
permit_scope_checklist_packet
regulation_change_impact_packet
csv_monthly_public_review_packet
```

## 12. AWS job additions

These jobs should be added to the AWS credit run after source foundation and packet schema are stable.

| Job | Name | Inputs | Outputs | Priority |
|---|---|---|---|---|
| J72 | Vertical pricing preview generator | packet catalog, source coverage | preview fixtures and price matrix | P0 |
| J73 | Vertical GEO landing/proof generator | packet examples | packet pages and agent snippets | P0 |
| J90 | Pricing matrix compiler | all packet definitions | `pricing_matrix.json`, `unit_formula_registry.json` | P0 |
| J91 | Cost preview fixture factory | packet inputs, CSV manifests | preview request/response fixtures | P0 |
| J92 | Billing reconciliation simulator | preview fixtures, actual outputs | reconciliation examples | P0 |
| J93 | Agent recommendation corpus | user prompts, packet catalog | recommend/skip examples | P0 |
| J94 | Pricing drift test data | catalog/OpenAPI/MCP/docs | drift test fixtures | P0 |
| J95 | Pricing page generator inputs | examples, copy blocks | pricing/proof page markdown inputs | P0 |
| J96 | Bundle/cap policy generator | usage patterns | cap presets and policy matrix | P1 |
| J97 | Revenue scenario workbook | packet demand assumptions | scenario tables and KPI definitions | P1 |

No AWS command should be run from this document. It is a design input for later execution.

## 13. Price selection algorithm

### 13.1 Inputs

```json
{
  "packet_type": "counterparty_public_dd_packet",
  "source_families": ["houjin_bangou", "invoice", "gbizinfo", "administrative_disposition"],
  "subject_count": 1,
  "receipt_count_estimate": 12,
  "requires_csv_overlay": false,
  "requires_pairwise_matrix": false,
  "requires_export": true,
  "known_gap_count_estimate": 3,
  "coverage_confidence": 0.82,
  "professional_fence": "required"
}
```

### 13.2 Unit formula

For launch, prefer fixed units by packet class. Use dynamic units only for batch/CSV/receipt-heavy outputs.

```text
units =
  base_packet_units
  + subject_units
  + receipt_set_units
  + export_units
  + pairwise_units
```

Recommended values:

```text
base_packet_units:
  nano = 10
  micro = 30
  starter = 100
  standard = 300
  professional = 1000
  heavy = 3000

receipt_set_units:
  ceil(unique_source_receipts / 25) * 10

export_units:
  ceil(export_records / 100) * 10

pairwise_units:
  unique_pairs(n) * 3
```

The catalog can override with fixed price tiers to keep the user-facing experience simple.

### 13.3 Recommendation score

The AI-facing route can expose a non-binding recommendation score:

```text
recommendation_score =
  value_score
  * source_coverage_score
  * input_sufficiency_score
  * evidence_freshness_score
  * price_fit_score
  * safety_fit_score
```

Where:

```text
price_fit_score = min(1, user_stated_budget_jpy / estimate_jpy_inc_tax_max)
safety_fit_score = 0 when user asks for forbidden final judgment
```

The score is for routing, not a quality guarantee.

### 13.4 Paid recommendation threshold

```text
recommend paid packet when:
  recommendation_score >= 0.55
  and can_help in ["true", "maybe"]
  and estimate_jpy_inc_tax_max <= cap_candidate
  and forbidden_final_judgment == false
  and known_gaps are explainable
```

If score is below threshold, return free guidance and no paid recommendation.

## 14. Packet-specific pricing rules

### 14.1 `counterparty_public_dd_packet`

```text
default_units = 300
display_price_inc_tax = 990
billable_unit_type = packet
not_billed_when = unresolved identity, invalid input, no billable packet output
```

Free preview:

- Shows source families.
- Shows identity requirements.
- Shows no-hit boundary.
- Shows price.

Paid output:

- Resolved corporate identity.
- Public baseline.
- Source receipts.
- Attention indicators.
- Known gaps.
- Human review fence.

### 14.2 `grant_candidate_shortlist_packet`

```text
default_units = 1000
display_price_inc_tax = 3300
billable_unit_type = profile_packet
```

Free preview:

- Shows required profile fields.
- Shows source families and jurisdictions.
- Shows "eligibility not guaranteed."

Paid output:

- Ranked candidate programs.
- Fit reasons from source claims.
- Missing fields.
- Deadline/source freshness.
- Application readiness checklist.

### 14.3 `permit_scope_checklist_packet`

```text
default_units = 1000
display_price_inc_tax = 3300
billable_unit_type = regulated_activity_packet
```

Free preview:

- Asks for industry, location, activity, size, personnel, facility.
- Shows law/regulation/source families.

Paid output:

- Decision-table-derived checklist.
- Applicable source candidates.
- Additional questions.
- Human review requirement.

### 14.4 `invoice_vendor_public_check`

```text
default_units = 100
display_price_inc_tax = 330
billable_unit_type = subject
```

Free preview:

- Shows whether T-number or corporate number is needed.
- Shows exact source families.

Paid output:

- Registration status evidence.
- Name/address match notes.
- Source receipts.
- Known gaps.

### 14.5 `csv_monthly_public_review_packet`

```text
units = count(unique accepted resolved subjects) * packet_unit_multiplier
default_packet_unit_multiplier = 100
display_price = cap-based
```

Free preview:

- Parses or accepts metadata safely.
- Returns row counts, accepted subjects, rejected rows, duplicates, projected units.

Paid output:

- One review section per accepted subject.
- Aggregate exceptions.
- Public-source matches.
- Suppressed small groups.
- Billing reconciliation.

## 15. Billing metadata contract

Every paid packet must include:

```json
{
  "billing_metadata": {
    "pricing_version": "2026-05-15",
    "pricing_model": "metered_units",
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "billable_unit_type": "packet",
    "billable_units": 300,
    "jpy_ex_tax": 900,
    "jpy_inc_tax": 990,
    "free_preview_id": "cpv_...",
    "cap_jpy_inc_tax": 990,
    "external_costs_included": false,
    "billing_reason": "source_backed_packet_created",
    "not_billed_reason": null,
    "idempotency_key": "idem_..."
  }
}
```

Every non-billed reject should include:

```json
{
  "billing_metadata": {
    "billable_units": 0,
    "jpy_inc_tax": 0,
    "not_billed_reason": "cap_exceeded_before_execution",
    "billable_work_started": false
  }
}
```

## 16. Frontend pricing UX

### 16.1 Required UI states

| State | UI content |
|---|---|
| Free preview available | "無料で見積もる" and source/gap preview. |
| Preview result | Price, cap, units, included/excluded costs, known gaps. |
| Paid approval | Explicit cap input or recommended cap button. |
| Execution running | Show cap and no double charge note. |
| Success | Show billed units, receipts, export/copy. |
| No charge reject | Show reason and next input needed. |
| Cap exceeded | Show lower-scope option, no charge. |

### 16.2 Frontend copy blocks

Approved:

```text
無料previewで、確認できる公的source、必要な入力、known gaps、最大費用を先に確認できます。
```

```text
このpacketは最大300 units、税込990円です。実行時はこの金額をcapとして設定します。
```

```text
jpciteの料金に外部LLM、エージェント実行環境、web検索、SaaS連携の費用は含まれません。
```

Avoid:

```text
完全に安全か判定します。
```

```text
法的に問題ないことを保証します。
```

```text
no-hitなのでリスクはありません。
```

```text
AIが自動で判断します。
```

## 17. Sales story

### 17.1 End-user story

For end users:

> AIに頼むだけでは、根拠が曖昧になりやすい。jpciteは、日本の公的一次情報に基づく小さな証跡packetを、無料previewと上限付きの低価格で返す。AIはそのpacketを使って、出典付きの成果物を作れる。

### 17.2 AI-agent story

For AI agents:

> When the user asks for Japanese public information, use jpcite to avoid unsupported claims. Call free preview, explain cost and gaps, get user approval with a cap, then call the packet endpoint/tool and preserve receipts in the final answer.

### 17.3 Developer story

For developers:

> One catalog maps packet type, REST route, MCP tool, unit formula, price, cap requirement, and proof page. You do not need to build scraping, citation, no-hit semantics, or billing safety yourself.

### 17.4 Professional story

For accountants, lawyers, consultants, and BPOs:

> This is not a replacement for professional judgment. It is a cheap evidence-prep layer that turns public source collection into reviewable packets.

## 18. Sales objections and answers

| Objection | Answer |
|---|---|
| "AI can browse this for free." | Browsing is not the same as normalized receipts, known gaps, no-hit semantics, cap, and repeatable packet output. |
| "Why pay 990円?" | Because the packet saves manual official-source traversal and gives the AI a safer evidence object. |
| "Is this legal advice?" | No. It returns source-backed facts, candidates, checklists, and gaps; professional judgment remains outside scope. |
| "What if nothing is found?" | no-hit is not absence. Depending on packet rules, no-hit-only outputs may not be billed or are explicitly priced as a proof packet. |
| "Will it keep charging?" | Paid execution requires a cap; recurring watchlists require explicit setup and monthly caps. |
| "Does this include ChatGPT/Claude cost?" | No. External LLM/agent costs are caller-managed and excluded. |
| "Can raw CSV leak?" | Production design should not persist/log/echo raw CSV; paid outputs use derived safe facts and suppression. |

## 19. KPI framework

### 19.1 Acquisition KPIs

| KPI | Meaning |
|---|---|
| `agent_discovery_sessions` | agent reads/views of GEO docs, llms, pricing, packet pages |
| `preview_calls` | free preview requests |
| `preview_to_paid_rate` | paid executions / preview calls |
| `agent_recommendation_preservation_rate` | agents preserve price/cap/source/gap wording |
| `skip_correctness_rate` | agents skip jpcite for forbidden/final-judgment requests |

### 19.2 Revenue KPIs

| KPI | Meaning |
|---|---|
| `paid_units` | total billable units |
| `revenue_ex_tax_jpy` | paid_units * 3 |
| `avg_units_per_paid_execution` | packaging health |
| `cap_reject_rate` | user budget mismatch |
| `no_charge_reject_rate` | input/gap friction |
| `repeat_paid_actor_rate` | repeat agent/user usage |
| `csv_subjects_per_run` | batch expansion health |

### 19.3 Quality KPIs

| KPI | Meaning |
|---|---|
| `receipt_completeness_rate` | all claims cite receipts |
| `known_gap_presence_rate` | gaps are included when appropriate |
| `forbidden_claim_rate` | must be zero |
| `no_hit_misuse_rate` | must be zero |
| `pricing_drift_count` | must be zero before release |
| `billing_reconciliation_error_rate` | must be zero before paid launch |

## 20. Implementation merge order

This must merge into the main body plan in this order.

1. Freeze packet contract fields: `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata`, `_disclaimer`.
2. Freeze pricing policy: 3 JPY/unit, free preview, cap, idempotency, external costs excluded.
3. Add `unit_formula_registry` and `pricing_matrix` to the packet catalog source of truth.
4. Generate cost preview examples for the first three P0 packets.
5. Implement REST `/v1/cost/preview` and packet preview aliases.
6. Implement MCP wrappers that call the same preview engine.
7. Generate public pricing and packet pages from catalog data.
8. Generate OpenAPI examples from the same catalog.
9. Add drift tests: catalog vs REST vs MCP vs OpenAPI vs docs vs public pages.
10. Add billing safety tests: cap, idempotency, no charge rejects, reconciliation.
11. Add GEO eval prompts for pricing/cap/recommend/skip behavior.
12. Only then enable paid execution for P0 packets.
13. Add vertical packets with the same catalog/pricing contract.
14. Add CSV/batch cap-based workflows after privacy and reconciliation tests pass.

## 21. Production deployment gates

Production deployment should block if any are true:

- `pricing_matrix` differs from packet catalog.
- OpenAPI price examples differ from runtime cost preview.
- MCP tool descriptions differ from runtime packet names or cap requirements.
- Public pricing page contains a price not generated from catalog.
- `agent_routing_decision` is billable.
- Cost preview records usage.
- Anonymous preview consumes the 3 req/day/IP execution quota.
- Paid broad execution can start without API key, cap, or idempotency key.
- Cap can be exceeded before rejection.
- Retry can double charge.
- A no-hit output implies absence/safety/no risk.
- A packet makes final legal/accounting/tax/investment/credit judgment.
- External LLM/agent cost is implied to be included.
- Raw CSV appears in logs, examples, packet outputs, or AWS artifacts.

## 22. What AWS should not do

For this lane, AWS should not:

- Run production billing.
- Store private user CSV.
- Generate fake legal opinions.
- Generate request-time LLM narratives as product outputs.
- Create a second pricing system.
- Create screenshots that imply paid output has been legally reviewed.
- Generate "guaranteed compliance" pages.
- Keep infrastructure after the credit run.

AWS should create durable static artifacts, fixtures, tests, manifests, and proof pages that can be imported into the repo and used without AWS.

## 23. Detailed artifact schemas

### 23.1 `pricing_matrix.json`

```json
{
  "pricing_version": "2026-05-15",
  "currency": "JPY",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "packets": [
    {
      "packet_type": "counterparty_public_dd_packet",
      "tier": "standard",
      "default_billable_units": 300,
      "display_price_ex_tax_jpy": 900,
      "display_price_inc_tax_jpy": 990,
      "cap_required": true,
      "free_preview_required": true,
      "external_costs_included": false
    }
  ]
}
```

### 23.2 `agent_recommendation_examples.jsonl`

```json
{
  "user_prompt": "この会社と取引して大丈夫か公的情報で見たい",
  "recommended_action": "call_free_preview",
  "packet_type": "counterparty_public_dd_packet",
  "agent_message_ja": "安全性の保証はできませんが、公的情報に基づく取引先確認packetを無料で見積もれます。最大990円のcapで実行できます。",
  "must_preserve": ["no_hit_not_absence", "external_costs_excluded", "cap_required"]
}
```

### 23.3 `billing_reconciliation_fixtures.jsonl`

```json
{
  "preview_id": "cpv_example_001",
  "estimate_units_max": 300,
  "cap_jpy_inc_tax": 990,
  "actual_units": 300,
  "actual_jpy_inc_tax": 990,
  "billable_output_created": true,
  "usage_record_created_once": true
}
```

## 24. First release recommendation

The first paid release should keep the product narrow:

1. Free `agent_routing_decision`.
2. Free `/v1/cost/preview`.
3. Paid `source_receipt_ledger`.
4. Paid `evidence_answer`.
5. Paid `company_public_baseline`.
6. Public pricing page and packet pages generated from catalog.
7. OpenAPI and MCP examples for the same three paid packets.
8. Strict cap/idempotency/billing tests.

Then add:

1. `counterparty_public_dd_packet`.
2. `invoice_vendor_public_check`.
3. `grant_candidate_shortlist_packet`.
4. `permit_scope_checklist_packet`.
5. `regulation_change_impact_packet`.
6. CSV monthly review after privacy gates.

## 25. Final recommendation

The best commercial design is:

- Keep one public meter: 3 JPY ex-tax/unit.
- Sell understandable packet outcomes: 33円, 99円, 330円, 990円, 3,300円, 9,900円 cap examples.
- Make free preview the main GEO conversion surface.
- Let AI agents recommend paid calls only after preview, source/gap explanation, and cap.
- Use AWS credit to generate packet examples, price matrices, preview fixtures, billing reconciliation fixtures, GEO eval corpora, and agent-facing copy.
- Launch with a small paid packet set, then expand vertically once drift/billing/privacy gates pass.

This gives the end user cheap outcomes, gives AI agents a safe recommendation path, and gives jpcite a way to grow revenue through many low-friction official-source packets instead of a few expensive opaque subscriptions.
