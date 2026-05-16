# Final 12-agent integrated smart-method review

Date: 2026-05-15  
Status: integrated review, no AWS execution  
Input: `aws_final_12_review_01-12`, `aws_jpcite_master_execution_plan_2026-05-15.md`

## 0. Verdict

The master plan remains coherent. The final review did not find a fatal contradiction.

The important correction is conceptual:

> The smarter plan is not mainly a better order. It is a better set of control, source-discovery, output-generation, agent-recommendation, and release/assetization functions.

The strongest additions to adopt are:

1. `Budget Token Market v2`
2. `control_spend_usd`
3. `Artifact Value Density Scheduler`
4. `Source Operating System`
5. `Output Composer + Public Packet Compiler`
6. `agent_purchase_decision` free preview
7. `agent_recommendation_card`
8. `Proof-Carrying Packet Compiler`
9. `Transactional Artifact Import`
10. `Pointer Rollback`
11. `Static DB Manifest`
12. `Zero-Bill Guarantee Ledger`

## 1. Adopted smart methods

### 1.1 AWS execution brain

Adopt:

- `control_spend_usd`, not dashboard visible usage, as the primary stop metric.
- `Budget Token Market v2`: every job reserves budget before it can be submitted.
- P95/P99 cost-to-complete for running and queued work.
- artifact value density for budget allocation.
- source circuit breakers.
- cost anomaly quarantine.
- checkpoint-first workers.
- adaptive queue controller.
- ROI-based stretch jobs only.

This is smarter because AWS can keep running when Codex/Claude are unavailable, while still preventing uncontrolled spend.

Key correction:

Do not double count reserved tokens and P95 queued tail. Implementation must define one authoritative exposure formula.

### 1.2 Source operating system

Adopt:

- `output_gap_map`
- `source_candidate_registry`
- `capture_method_router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`
- `source_freshness_monitor`
- `source_terms_classifier`
- `Playwright canary router`
- `failed_source_ledger`

This is smarter than listing more sources. The system should discover and expand sources from sellable packet gaps.

Core loop:

```text
paid output -> required claims -> output gap -> source candidate -> source profile gate
-> capture method router -> canary -> accepted artifact yield -> expand / suppress
```

### 1.3 Output generation

Adopt:

- `Output Composer`
- `Public Packet Compiler`
- `decision_object`
- `agent_recommendation_card`
- `workflow_recipe`
- `question_generation`
- `multi_packet_bundle`
- `bundle_quote`
- `receipt_reuse_plan`
- `delta_to_action`
- `evidence_graph_view`
- `agent_facing_summary`
- `cheapest_sufficient_packet_selector`
- `gap_to_question_minimizer`

Important boundary:

`Output Composer` can recommend what to buy or ask next, but it must not create final public claims. Public claims must come only from `Public Packet Compiler` after receipt/gap checks.

### 1.4 Agent/GEO selling layer

Adopt:

- free preview as `agent_purchase_decision`
- proof pages as `agent_decision_page`
- `.well-known` decision bundle
- `cheaper_option_explainer`
- MCP small facade for agent-first flow
- recommendation-quality GEO eval

This makes AI agents able to say:

```text
This packet is worth buying because it answers the user's task cheaply,
uses public source receipts, has a cap, and shows known gaps.
```

### 1.5 Algorithm safety

Adopt:

- proof-carrying packet compiler
- sentence-level evidence binding
- no-hit scope compiler
- explicit support levels for API, HTML, screenshot, OCR, and LLM candidates
- hard-schema quarantine for LLM candidates
- meaning-aware forbidden phrase gate
- typed score families only

Do not expose:

- `eligible`
- generic `score`
- `safe`
- `no issue`
- `permission not required`
- `信用スコア`

### 1.6 Release and assetization

Adopt:

- release control plane
- transactional artifact import
- shadow release
- pointer rollback
- assetization tiers
- static DB manifest
- external export gate
- production smoke without AWS
- zero-bill guarantee ledger
- post-teardown cost attestations
- catalog drift firewall

This shifts production from "deploy AWS output" to "switch pointer to a verified immutable asset bundle."

## 2. Changes to master plan

The master plan should be amended with these rules:

1. Replace any `Visible usage` wording with `control_spend_usd`.
2. Make `Budget Token Market v2` the only AWS job submission path.
3. Add `artifact_value_density` and `agent_recommendation_gain` to AWS scheduling.
4. Add source circuit breakers and capture method routing.
5. Add `Output Composer + Public Packet Compiler` as the product architecture.
6. Make free preview return `agent_purchase_decision`, not only a price estimate.
7. Add `agent_recommendation_card` to preview/proof assets.
8. Add `Receipt Wallet` / `receipt_reuse_plan` to reduce cost and latency.
9. Add `Transactional Artifact Import`, `Static DB Manifest`, and `Pointer Rollback`.
10. Add `Zero-Bill Guarantee Ledger`.
11. Add meaning-aware forbidden phrase tests.
12. Add `no_hit_scope_compiler`.

## 3. Not adopted

Do not adopt:

- Exact visible spend target of `USD 19,493.94`.
- S3 final archive as default.
- AWS-managed post-teardown scheduled checks.
- Playwright as default source acquisition.
- OCR-only paid claims.
- Broad crawl without `output_gap_map`.
- Packet output directly from an LLM candidate.
- Public proof pages that leak full raw screenshots, DOM, OCR text, HAR, or real CSV-derived facts.

## 4. Remaining risks

Remaining risks are implementation risks, not plan contradictions:

- Budget token accounting can be implemented incorrectly and double count or undercount queued exposure.
- Agent preview can become too verbose unless a compact schema is enforced.
- Proof pages can reveal too much free value unless they are decision pages rather than full outputs.
- Source expansion can still become broad crawling if `output_gap_map` is bypassed.
- Pointer rollback needs a real deploy/static path decision before implementation.
- Zero-bill guarantee requires final AWS resource inventory and delayed billing checks from outside AWS.

## 5. Final conclusion

After this final 12-agent review, the smarter product concept is:

> jpcite should be an agent-first public-information output compiler. It uses AWS once to build verified public-source assets, uses a self-budgeting AWS controller to spend safely, uses source gaps to discover data, uses a compiler to generate proof-carrying packets, lets AI agents preview and recommend the cheapest sufficient output, then releases verified immutable asset bundles and tears AWS down to zero-bill.

This is materially smarter than a broad crawler, a cache, or a collection of packet endpoints.
