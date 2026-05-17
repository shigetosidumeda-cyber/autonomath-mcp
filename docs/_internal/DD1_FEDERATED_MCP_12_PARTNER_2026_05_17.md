# DD1 — Federated MCP recommendation 6 -> 12 partner expansion

- date: 2026-05-17
- task id: DD1
- mode: lane:solo (additive expansion, no SOT replacement)
- supersedes: nothing (additive over Wave 51 dim R)
- author: Bookyou株式会社 (operator: 梅田茂利)
- co-authored-by: Claude Opus 4.7

## 1. Goal

Wave 51 dim R federated MCP recommendation landed on 2026-05-16 with a
curated roster of 6 partners (freee / mf / notion / slack / github /
linear). DD1 broadens that roster to 12 by adding 6 new partners that
diversify the agent discovery surface across billing reconciliation,
CRM, enterprise messaging, document management, MCP federation, and
cross-promotion paths.

## 2. Non-goals

- Not replacing the Wave 51 dim R 6-partner shortlist. The Wave 51
  contract (`data/federated_partners.json`,
  `src/jpintel_mcp/federated_mcp/registry.py`,
  `tests/test_federated_mcp.py`, migration 278) is preserved verbatim.
- Not introducing any LLM API call. Recommendation remains a pure
  Python keyword + capability-tag substring match.
- Not adding aggregator MCP endpoints. Every URL is first-party.
- Not proxying partner traffic. Agents call partner endpoints
  themselves.

## 3. 12-partner roster

Alphabetical by partner_id. `tier=base` rows are unchanged from Wave 51
dim R; `tier=expansion` rows are new in DD1.

| # | partner_id | name | category | use_case_match | mcp_endpoint_status | discovery_priority | tier |
|---|---|---|---|---|---|---|---|
| 1 | aws_bedrock | AWS Bedrock Agents | mcp_federation_hub | agent_runtime_federation | none_official | 4 | expansion |
| 2 | claude_ai | Anthropic Claude.ai | cross_promotion | assistant_cross_promotion | none_official | 5 | expansion |
| 3 | freee | freee 会計 | accounting | jp_accounting_ledger | none_official | 1 | base |
| 4 | github | GitHub | developer | source_code_state | official | 2 | base |
| 5 | google_drive | Google Drive | document_management | doc_management | none_official | 4 | expansion |
| 6 | linear | Linear | product | product_tracker | official | 2 | base |
| 7 | mf | マネーフォワード クラウド | accounting | jp_accounting_ledger | none_official | 1 | base |
| 8 | ms_teams | Microsoft Teams | enterprise_messaging | enterprise_chat | none_official | 3 | expansion |
| 9 | notion | Notion | knowledge_base | team_doc_graph | official | 2 | base |
| 10 | salesforce | Salesforce | crm | crm_record_state | none_official | 3 | expansion |
| 11 | slack | Slack | chat | team_chat_state | none_official | 2 | base |
| 12 | stripe | Stripe | billing | billing_reconciliation | official | 3 | expansion |

Endpoints flagged `official` carry an https first-party-confirmed MCP
URL. Endpoints flagged `none_official` rely on the partner's REST /
GraphQL API via `official_url` — DD1 deliberately does not include
aggregator-hosted endpoints (pulsemcp / smithery.ai / glama.ai /
mcp.so) even when an aggregator advertises a partner relay.

### Verified endpoints (2026-05-17)

- `https://mcp.stripe.com` — Stripe official MCP endpoint, documented
  at `https://docs.stripe.com/mcp`.
- `https://api.githubcopilot.com/mcp/` — GitHub Copilot MCP endpoint,
  documented in `github/github-mcp-server`.
- `https://mcp.linear.app/sse` — Linear official MCP, SSE transport.
- `https://mcp.notion.com/mcp` — Notion official MCP.
- All other partners: no first-party MCP confirmed as of 2026-05-17, so
  `mcp_endpoint` is null and `mcp_endpoint_status` is `none_official`.

## 4. Artifacts landed in DD1

### 4.1 Config

- `data/federated_mcp_partners.yaml` (NEW, 257 lines) — human-editable
  YAML companion. Carries every DD1 field, including
  `discovery_priority`, `tier`, `category`, and `use_case_match`.
- `data/federated_partners_12.json` (NEW) — canonical 12-partner JSON
  consumed by `load_dd1_registry_12()`. Mirrors the schema at
  `schemas/jpcir/federated_partner.schema.json`. The
  `supersedes_via_addition` field declares that this artifact augments
  rather than replaces `data/federated_partners.json`.
- `data/federated_partners.json` — Wave 51 dim R canonical 6-partner
  JSON, UNCHANGED. The legacy contract continues to back
  `load_default_registry()` for callers that still expect exactly 6.

### 4.2 Source

- `src/jpintel_mcp/federated_mcp/registry_12.py` (NEW) — DD1 12-partner
  loader. Adds `DD1_PARTNER_IDS_12`, `DD1_BASE_6`, `DD1_EXPANSION_6`,
  `DD1_PARTNER_ALIASES_EXPANSION_6`, `DD1_PARTNER_ALIASES_12`,
  `load_dd1_registry_12()`, and `recommend_handoff_12()`.
- `src/jpintel_mcp/federated_mcp/registry.py` — Wave 51 dim R 6-partner
  registry, UNCHANGED.
- `src/jpintel_mcp/federated_mcp/recommend.py` — Wave 51 dim R 6-base
  alias map + matcher, UNCHANGED. The base-6 alias dict is imported by
  `registry_12.py` so any future edits propagate automatically.

### 4.3 Discovery surface

- `site/.well-known/jpcite-federated-mcp-12-partners.json` (NEW) —
  agent-funnel Discoverability artifact. Includes
  `discovery_priority_legend` + `tier_legend` + per-partner
  `category` / `use_case_match` / `discovery_priority` / `tier`.
  Cross-links the canonical JSON, YAML companion, schema, and design
  doc.
- `site/.well-known/jpcite-federation.json` — Wave 50 federation
  discovery doc, UNCHANGED. The DD1 artifact declares
  `supersedes.via = "addition_not_replacement"` so legacy crawlers
  keep consuming the original.

### 4.4 Tests

- `tests/test_dd1_federated_12_partner.py` (NEW, 9 bundles, 30+ tests)
  covers: registry shape, non-regression vs Wave 51 base 6, 12-partner
  gap-keyword matcher (English + Japanese), alias-map shape, JSON +
  YAML data files, `.well-known` discovery artifact, no-LLM /
  no-legacy-brand hardening, schema parity, custom-registry injection.
- `tests/test_federated_mcp.py` — Wave 51 dim R base-6 unit tests,
  UNCHANGED. The base-6 contract continues to be exercised
  independently.
- `tests/test_dim_r_federated_mcp.py` — Wave 47 migration-278 storage
  tests, UNCHANGED.

### 4.5 Docs

- `docs/_internal/DD1_FEDERATED_MCP_12_PARTNER_2026_05_17.md` (THIS
  FILE) — DD1 design + change log.
- `site/llms.txt` — single-line additive marker noting the 12-partner
  hub for organic Discoverability (agent-funnel stage 1).

## 5. Recommendation algorithm (unchanged in spirit)

Pure-Python deterministic match. No LLM call. No HTTP call.

1. Lowercase + collapse whitespace on the input gap.
2. Extract ascii word tokens for capability-tag exact match.
3. For each partner row:
   - +1 for each capability tag that appears as an ascii word token.
   - +1 for each tag whose underscore-to-space variant appears as a
     substring of the normalised gap.
   - +1 for each Japanese / English alias hit (substring match).
4. Drop score-0 partners, sort by score DESC then partner_id ASC for
   stable output, return up to `max_results` rows.

The alias map for the 12-partner matcher is the merge of the Wave 51
dim R base-6 aliases (imported verbatim from
`jpintel_mcp.federated_mcp.recommend._PARTNER_ALIASES`) and the new
`DD1_PARTNER_ALIASES_EXPANSION_6` for the 6 expansion partners.

## 6. Constraints honoured

- **No LLM API** — registry_12.py imports nothing from `anthropic`,
  `openai`, `google.generativeai`, or `claude_agent_sdk`. CI guard
  (`tests/test_no_llm_in_production.py`) continues to enforce this.
- **Aggregator ban** — first-party endpoints only. Aggregator hosts
  (`pulsemcp`, `smithery.ai`, `glama.ai`, `mcp.so`) are rejected by a
  dedicated unit test.
- **No self-reference** — `jpcite`, `jpintel`, `autonomath` slugs are
  rejected by `FederatedRegistry.__init__` (Wave 51 contract retained).
- **https only** — every `official_url` and non-null `mcp_endpoint` is
  https; tests enforce this in both the JSON and the `.well-known`
  artifact.
- **mypy strict** — registry_12.py uses the same Pydantic v2 model and
  TYPE_CHECKING guards as the Wave 51 dim R modules.
- **ruff** — module shape follows the Wave 51 dim R conventions
  (docstring, `from __future__ import annotations`, alphabetical
  `__all__`, no `cast` or `Any`).
- **Co-Authored-By** — every DD1 commit carries
  `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **safe_commit.sh** — DD1 commits go through `scripts/safe_commit.sh`
  with `[lane:solo]` in the subject line.

## 7. Why an additive layer instead of in-place replacement

Wave 51 dim R was landed with extensive coverage:

- `tests/test_federated_mcp.py` pins `len(reg) == 6` and the canonical
  partner_ids set.
- migration 278 + `am_federated_mcp_partner` SQLite table were seeded
  with exactly 6 rows.
- `site/.well-known/jpcite-federation.json` references the 6-partner
  contract.
- Audit logs and outcome contracts hash the 6-partner registry
  fingerprint.

A naive 6 -> 12 in-place rewrite would break all of the above. DD1
therefore ships as an **additive** layer: the Wave 51 contract is
preserved verbatim, and the DD1 12-partner roster + matcher live in
parallel under `registry_12.py`. Consumers opt in by importing
`load_dd1_registry_12` / `recommend_handoff_12` from the new module;
legacy callers continue to import `load_default_registry` /
`recommend_handoff` and get the original 6-partner shortlist.

## 8. Open follow-ups (non-blocking)

- Migration 279 to mirror the 6 expansion partners into
  `am_federated_mcp_partner` once the storage layer migrates from
  fixed-6 to dynamic length. Out of scope for DD1.
- REST + MCP surface flip from `recommend_handoff` to
  `recommend_handoff_12` once Wave 52+ promotes the 12-roster as
  canonical. Out of scope for DD1.
- Periodic `mcp_endpoint` reverify cron — Stripe / GitHub / Linear /
  Notion already in the curated refresh; Wave 52 will fold the rest in
  when first-party MCP endpoints land for those partners.

## 9. References

- Memory: `feedback_federated_mcp_recommendation`
- Memory: `feedback_agent_funnel_6_stages` (Discoverability stage 1)
- Memory: `feedback_dual_cli_lane_atomic`
- Schema: `schemas/jpcir/federated_partner.schema.json`
- Wave 51 dim K-S closeout: `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md`
- Wave 51 plan: `docs/_internal/WAVE51_plan.md`
