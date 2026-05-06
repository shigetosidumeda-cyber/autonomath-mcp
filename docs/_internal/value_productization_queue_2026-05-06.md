# Value Productization Queue

- date: `2026-05-06`
- source: repo cleanup loop, value asset report, subagent audits
- rule: do not publish internal evidence directly; promote redacted product
  surfaces only

## Priority Order

1. `application_strategy_pack`
   - why: fastest path to paid practitioner value
   - users: BPO teams, tax advisors, administrative scriveners, subsidy
     consultants, finance desks
   - output: candidate programs, likely blockers, exclusion checks, required
     documents, next questions, source receipts
   - data assets: `programs`, `jpi_programs`, `am_amount_condition`,
     `am_application_round`, `am_law_article`, `adoption_records`
   - gate: no final application/legal/tax judgment; show known gaps
   - agent routing: `createApplicationStrategyPack` is an agent-safe first-hop
     call for subsidy, loan, and tax-incentive option work. Preserve
     `source_url`, `source_fetched_at`, `known_gaps`, and
     `human_review_required`; never claim approval, adoption probability, or
     final professional judgment.

2. `company_public_baseline` plus `houjin_dd_pack`
   - why: recurring use case when a company folder, CRM record, client file, or
     counterparty review starts
   - users: BPO/AI ops, M&A, finance, tax/accounting firms, AI agents
   - output: identity, invoice status, public programs, adoption history,
     source gaps, public risk signals, questions to ask the client
   - data assets: `houjin_master`, invoice registrants, adoption records,
     public source profiles, enforcement/case/adjudication surfaces
   - gate: not credit research, not anti-social-force screening, not a legal
     or audit opinion

3. `company_public_audit_pack`
   - why: higher perceived value for DD, audit prep, and internal approval
   - users: auditors, M&A, lenders, corporate planning, legal-adjacent ops
   - output: public evidence table, citation receipts, mismatch flags, DD
     questions, source freshness
   - data assets: source manifests, evidence packets, audit seal/provenance,
     law/case/enforcement/adoption tables
   - gate: must be framed as public-information prep, not completed audit

4. `agent_first_distribution`
   - why: makes jpcite the first hop before web search inside Claude, ChatGPT,
     Cursor, internal agents, and MCP clients
   - assets: `mcp-server*.json`, DXT, `.mcpb`, OpenAPI agent spec, SDKs,
     `sdk/agents`, `llms.txt`, integration docs
   - gate: manifest description drift, SDK package-name drift, version drift,
     and tool-count drift must be checked before promotion

5. `trust_quality_proof`
   - why: reduces buyer skepticism without overclaiming
   - assets: `jcrb_v1`, practitioner acceptance queries, composite benchmark,
     smoke reports, SLO design
   - gate: publish methodology and caveats; do not claim guaranteed savings,
     guaranteed accuracy, or contractual SLA from internal tests

## Do Not Publish Directly

- secret registries and environment setup
- incident, WAF, deploy, kill-switch, and recovery runbooks
- marketplace application drafts
- legal self-audits and lawyer consultation notes
- raw offline inboxes, WARC captures, PDF binaries, large DB files, and logs
- seed benchmark submissions labeled as unvalidated
- generated public artifacts without generator and drift verification

## Immediate Implementation Bundles

1. Product bundle:
   `application_strategy_pack` endpoint/docs/tests plus acceptance queries.

2. Company bundle:
   `company_public_baseline`, `houjin_dd_pack`, and `company_folder_brief`
   display preset.

3. Evidence bundle:
   citation/source receipt format, source freshness, and known-gaps envelope.

4. Distribution bundle:
   DXT/MCP/OpenAPI/SDK description parity and package-name normalization.

5. Proof bundle:
   public benchmark method page with conservative results and caveats.

## Implemented In This Loop

- Agent-safe OpenAPI now exposes `prescreenPrograms` and
  `getProgramEligibilityPredicate` alongside `createApplicationStrategyPack`.
  This gives AI callers a clean chain: company/profile -> prescreen ->
  predicate -> strategy pack -> evidence packet.
- `docs/openapi/agent.json`, `site/openapi.agent.json`, and
  `site/docs/openapi/agent.json` were regenerated from the app schema.
- `evidence.packet.batch` now uses strict metering, so a final monthly-cap
  rejection fails the paid batch instead of returning a silent unmetered 200.
- Production boot now requires `CLOUDFLARE_TURNSTILE_SECRET` when APPI intake
  is enabled. Development and disabled-APPI deployments remain exempt.
- Audit seal HMAC now binds the public `seal_id` and `corpus_snapshot_id`.
  Tampering either field makes public verification return `verified=false`.
- JCRB public benchmark publishing now separates verified submissions from
  unvalidated seed examples, enforces `questions_sha256`, `n=100`,
  5 domains x 20 questions, ISO UTC timestamps, and score ranges.
- Migration inventory now matches the migration runner's first-5-line directive
  behavior and has opt-in fail flags for unmarked target DB and dangerous
  forward SQL.
