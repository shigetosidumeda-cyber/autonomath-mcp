# MCP agent-first catalog deep dive 2026-05-15

Status: pre-implementation planning only  
Owner lane: MCP tool naming / backward compatibility / agent-first catalog  
Scope: P0 MCP tool names, descriptions, inputs, outputs, alias/compatibility policy, forbidden claims, routing rules  
Non-scope: runtime implementation, production code edits, package rename, deprecation execution

## 0. Executive contract

現行 MCP surface は `mcp-server.full.json` で 155 tools。これは power user / SDK parity / legacy compatibility には必要だが、AI agent の初回 tool selection には大きすぎる。

P0 は 8-12 本の agent-first catalog を default 推奨面に置き、既存 155 tools は `full_catalog` として維持する。既存 tool 名、snake_case API、PyPI/package/CLI の legacy `autonomath-mcp` 名、`AUTONOMATH_*` env vars、`jpintel_mcp.mcp.autonomath_tools` 実装 namespace は壊さない。

推奨する分離:

| Layer | Default exposure | Target size | Purpose |
|---|---:|---:|---|
| `p0_agent_catalog` | default / registry / docs first view | 10 tools | AI が最初に選ぶ facade。routing, cost, packet, usage, narrow search only。 |
| `core_catalog` | explicit opt-in | 30-40 tools | search/detail/provenance primitives。developer quickstart 用。 |
| `composition_catalog` | explicit opt-in | about 50 tools | domain workflow, industry packs, rule/compliance chains。 |
| `full_catalog` | explicit opt-in / compatibility | 155 tools | 既存全 surface。既存 MCP clients と advanced users を壊さない。 |
| `legacy_or_expert_catalog` | docs / gated | variable | broken/off/regulated/experimental/old aliases。default recommendation から外す。 |

P0 catalog の基本姿勢:

- Agent には「どの 155 tools を組み合わせるか」ではなく「どの packet/facade を最初に呼ぶか」を選ばせる。
- P0 tool は agent が読める `use_when`, `do_not_use_when`, `billing`, `must_preserve_fields`, `professional_fence`, `failure_codes` を説明に持つ。
- Full tool list は削らない。P0 tool は alias/facade として追加し、既存 tool は同じ動作を維持する。
- 新 canonical P0 名は lower snake_case に寄せる。REST/OpenAPI operationId や docs では camelCase alias を併記してよいが、MCP tool 名は既存文化に合わせる。

## 1. P0 MCP tool一覧

P0 は 10 本を推奨する。うち control 3 本、packet 5 本、primitive 2 本。

| # | P0 MCP tool | Type | One-line description |
|---:|---|---|---|
| 1 | `jpcite_route` | control | User task が jpcite の対象か、どの tool chain を使うべきか、費用 class と安全 fence を返す。 |
| 2 | `jpcite_cost_preview` | control | 有料/broad/batch/packet 実行前に billable units, estimated JPY, cap requirement を返す。 |
| 3 | `jpcite_usage_status` | control | 匿名/paid quota, monthly usage, reset, cap 状態を確認する。既存 `get_usage_status` の agent-first alias。 |
| 4 | `jpcite_answer_packet` | packet | AI が回答を書く前に、source-linked evidence, supported claims, known gaps を取得する。 |
| 5 | `jpcite_company_packet` | packet | 法人番号/会社名から公的 baseline、invoice、採択、行政処分、source receipts をまとめる。 |
| 6 | `jpcite_application_packet` | packet | 事業者 profile から制度候補、要件、締切、排他/併用注意、質問事項をまとめる。 |
| 7 | `jpcite_source_ledger` | packet | packet/artifact/entity/fact の source receipts, content hashes, fetched timestamps を再取得する。 |
| 8 | `jpcite_monthly_review` | packet | 顧問先/取引先 list の月次公的変化レビューを cap/idempotency 前提で作る。 |
| 9 | `jpcite_program_search` | primitive | 軽量な公的制度 candidate discovery。既存 `search_programs` の agent-first alias。 |
| 10 | `jpcite_evidence_packet` | primitive/packet | resolved subject の既存 Evidence Packet を取得する。既存 `get_evidence_packet` の agent-first alias。 |

Name rules:

- Public P0 MCP canonical: `jpcite_<noun_or_verb>` lower snake_case。
- Existing runtime tool aliases: legacy snake_case を残す。
- REST/OpenAPI operationId: `jpciteRoute`, `jpciteCostPreview` のような camelCase 可。ただし MCP では snake_case を SOT にする。
- `am`, `autonomath`, `jpintel` suffix は P0 名に出さない。互換層と内部 implementation のみで維持する。

## 2. P0 tool input/output contract

P0 tool は共通 envelope を返す。最低限、`request_id`, `schema_version`, `generated_at`, `tool`, `billing_metadata`, `known_gaps`, `human_review_required`, `_disclaimer` を含める。source-bearing tool は `source_receipts` を必ず返す。

### 2.1 `jpcite_route`

| Field | Contract |
|---|---|
| Description | User task を読んで、jpcite を使うべきか、使うなら P0 tool と chain を返す free control tool。 |
| Use when | agent が「この質問で jpcite を呼ぶべきか」迷う、または user intent が補助金/法人/公的根拠/制度/税務/監査/申請に触れている。 |
| Do not use when | user が既に具体的な P0 tool 実行を指示した、または純粋な一般会話/創作/コード作業で日本公的データが不要。 |
| Inputs | `user_task` string required; `locale` default `ja-JP`; `known_subjects` array optional; `desired_output` enum optional; `cost_sensitivity` enum optional; `auth_state` enum optional. |
| Outputs | `recommended` bool; `reason`; `primary_tool`; `secondary_tools`; `route_class` enum; `cost_class` enum `free/low/medium/high/unknown`; `requires_cost_preview`; `requires_api_key`; `requires_human_review`; `do_not_claim`; `next_call`. |
| Billing | Free. Should not consume anonymous execution quota. |
| Legacy mapping | New facade. Can internally map to no-op rules/config; no existing 155 tool should be required. |

### 2.2 `jpcite_cost_preview`

| Field | Contract |
|---|---|
| Description | Paid or broad execution before run: units, estimated JPY, cap, idempotency, auth need を返す。 |
| Use when | packet/batch/monthly/CSV/fanout/watchlist/composition を実行する前、または user が費用を聞いたとき。 |
| Do not use when | single free control call、already previewed same idempotency scope、明らかに無料の `jpcite_route`。 |
| Inputs | `planned_tool` string required; `subjects` array or `subject_count`; `packet_type`; `max_units`; `client_tag`; `include_tax` bool default true; `currency` default `JPY`. |
| Outputs | `billable_units_estimate`; `unit_price_jpy_ex_tax`; `estimated_total_jpy_ex_tax`; `estimated_total_jpy_inc_tax`; `cap_required`; `recommended_cost_cap_jpy`; `api_key_required`; `idempotency_key_required`; `not_charged_for_preview`; `warnings`. |
| Billing | Free. Separate low-abuse rate limit. No usage recording as billable work. |
| Legacy mapping | New facade. REST equivalent `/v1/cost/preview` if/when available. Existing usage/cap endpoints can supply auth/cap state. |

### 2.3 `jpcite_usage_status`

| Field | Contract |
|---|---|
| Description | Quota/cap/current usage を確認する control tool。 |
| Use when | anonymous user near quota, batch 前、429 後、agent が API key/cap 状態を確認する必要がある。 |
| Do not use when | every turn. Session 内で値を reuse できる。 |
| Inputs | `api_key_ref` optional; `client_tag` optional; `include_monthly_breakdown` bool default false. MCP stdio では exact anonymous IP bucket 不明であることを返す。 |
| Outputs | `tier`; `limit`; `remaining`; `used`; `reset_at`; `reset_timezone`; `monthly_cap_jpy`; `monthly_used_jpy`; `cap_remaining_jpy`; `upgrade_url`; `note`. |
| Billing | Free/meta. Should not consume billable unit. |
| Legacy mapping | Existing `get_usage_status` remains valid alias. |

### 2.4 `jpcite_answer_packet`

| Field | Contract |
|---|---|
| Description | AI が最終回答を書く前に、根拠付き claim set と gaps を取得する packet facade。 |
| Use when | 日本の公的制度/法人/法令/税務/監査/申請に関する回答で、source URL, fetched_at, known gaps, human review flag が必要。 |
| Do not use when | user wants final legal/tax/audit/credit/application judgment; use as evidence support only. Quick keyword-only discoveryなら `jpcite_program_search`。 |
| Inputs | `question` string required; `subject_hints` array optional; `jurisdiction` default `JP`; `output_style` enum `brief/standard/audit`; `max_records` default 8 max 25; `as_of` date optional; `cost_cap_jpy` required if paid; `idempotency_key` required if paid. |
| Outputs | `packet_id`; `answer_not_included=true`; `supported_claims[]`; `records[]`; `source_receipts[]`; `known_gaps[]`; `freshness`; `human_review_required`; `professional_fences[]`; `next_questions[]`; `billing_metadata`; `_disclaimer`. |
| Billing | Packet unit if successful; preview recommended when broad/uncertain. |
| Legacy mapping | Facade over `semantic_search_am`, `search_programs`, `search_laws`, `search_tax_rules`, `get_evidence_packet`, `get_source_manifest`, `verify_citations` depending on route. |

### 2.5 `jpcite_company_packet`

| Field | Contract |
|---|---|
| Description | 法人番号/会社名の public baseline packet。公的確認可能範囲をまとめ、与信判断にしない。 |
| Use when | counterparty check, DD prep, audit/account research, company folder first hop, invoice/adoption/enforcement public facts. |
| Do not use when | private credit score, anti-social-force judgment, non-public financials, bank/payment data, personal data lookup. |
| Inputs | `company_name` or `houjin_bangou` required; `prefecture` optional; `include_invoice` bool default true; `include_adoption_history` bool default true; `include_enforcement` bool default true; `as_of` date optional; `cost_cap_jpy`; `idempotency_key`. |
| Outputs | `packet_id`; `subject_resolution`; `master_info`; `invoice_status`; `adoption_summary`; `enforcement_summary`; `jurisdiction_signals`; `source_receipts[]`; `known_gaps[]`; `no_hit_not_absence` bool; `human_review_required`; `billing_metadata`; `_disclaimer`. |
| Billing | Per resolved subject or packet. Cost preview required for list/batch. |
| Legacy mapping | `dd_profile_am`, `get_houjin_360_am`, `houjin_invoice_status`, `invoice_risk_lookup`, `search_invoice_registrants`, `check_enforcement_am`, `get_houjin_subsidy_history` where available. |

### 2.6 `jpcite_application_packet`

| Field | Contract |
|---|---|
| Description | Applicant profile から候補制度、排他/併用注意、必要確認事項、source receipts をまとめる。 |
| Use when | SMB/subsidy/loan/tax incentive candidate discovery, advisor pre-screen, user asks "使える制度は?" with profile. |
| Do not use when | 採択保証、申請書作成代行、税額確定、行政書士/税理士/弁護士/社労士領域の最終判断。 |
| Inputs | `applicant_profile` object required; `prefecture`; `industry_jsic`; `employees`; `revenue_yen`; `planned_investment_yen`; `purpose`; `desired_support_types`; `as_of`; `max_candidates` default 10; `cost_cap_jpy`; `idempotency_key`. |
| Outputs | `packet_id`; `normalized_profile`; `candidate_programs[]`; `eligibility_signals[]`; `exclusion_or_compatibility_warnings[]`; `deadlines[]`; `required_follow_up_questions[]`; `source_receipts[]`; `known_gaps[]`; `human_review_required`; `billing_metadata`; `_disclaimer`. |
| Billing | Packet unit; preview required for broad fanout or large candidate count. |
| Legacy mapping | `prescreen_programs`, `smb_starter_pack`, `search_programs`, `search_loan_programs`, `search_tax_rules`, `check_exclusions`, `subsidy_combo_finder`, `get_program`, `batch_get_programs`. |

### 2.7 `jpcite_source_ledger`

| Field | Contract |
|---|---|
| Description | packet/entity/fact の source receipt ledger を返す。引用・監査・再現性用。 |
| Use when | downstream answer に receipts を添付する、artifact の根拠を再検証する、source_fetched_at/content_hash/corpus_snapshot_id が必要。 |
| Do not use when | user only needs business summary and already has packet receipts; program discoveryなら `jpcite_program_search`。 |
| Inputs | `packet_id` or `entity_id` or `fact_ids[]` required; `include_fact_level` bool default true; `include_content_hash` bool default true; `format` enum `json/markdown`. |
| Outputs | `ledger_id`; `subject`; `corpus_snapshot_id`; `source_receipts[]` with `source_url`, `publisher`, `source_fetched_at`, `content_hash`, `license`, `fact_ids`; `coverage_score`; `known_gaps[]`; `replay_hint`. |
| Billing | Receipt-set unit if broad; free/low for already-returned packet replay can be considered. |
| Legacy mapping | `get_source_manifest`, `get_provenance`, `get_provenance_for_fact`, `verify_citations`, `fact_signature_verify_am`. |

### 2.8 `jpcite_monthly_review`

| Field | Contract |
|---|---|
| Description | 複数 client/subject の月次公的変化 review。cost cap と idempotency 必須。 |
| Use when | advisor/accounting/backoffice recurring review, client population CSV, watchlist refresh, "今月変わったこと" summary. |
| Do not use when | one company lookup; use `jpcite_company_packet`. One question answer; use `jpcite_answer_packet`。 |
| Inputs | `subjects[]` or `csv_artifact_id` required; `review_window_start`; `review_window_end`; `review_types[]`; `client_tag`; `cost_cap_jpy` required; `idempotency_key` required; `max_subjects` default cap. |
| Outputs | `review_id`; `accepted_subjects`; `skipped_subjects`; `changes[]`; `per_subject_packets[]`; `source_receipts[]`; `known_gaps[]`; `human_review_required`; `billing_metadata`; `reconciliation`. |
| Billing | Per accepted subject / packet. Must reject before billable work if cap missing or too low. |
| Legacy mapping | `prepare_kessan_briefing`, `match_due_diligence_questions`, `forecast_program_renewal`, `cross_check_jurisdiction`, `get_houjin_360_am`, `program_active_periods_am`, plus CSV/accounting surfaces where available. |

### 2.9 `jpcite_program_search`

| Field | Contract |
|---|---|
| Description | Lightweight candidate discovery over Japanese public programs. |
| Use when | user wants candidate programs by keyword/prefecture/industry/purpose and does not need full packet yet. |
| Do not use when | user gives full applicant profile and expects strategy/gaps; use `jpcite_application_packet`. Enforcement/cases/laws/invoice-specific questions should route to packet or specialized full catalog. |
| Inputs | `q`; `prefecture`; `industry_jsic`; `target_type`; `funding_purpose`; `authority_level`; `program_kind`; `amount_max_man_yen_lte`; `as_of`; `limit` default 10 max 50; `fields` enum `minimal/standard/full`. |
| Outputs | `results[]` with `unified_id`, `primary_name`, `program_kind`, `authority`, `prefecture`, `amount`, `application_window`, `tier`, `source_url`, `source_fetched_at`; `total`; `known_gaps`; `retry_with`; `next_calls`. |
| Billing | Same as existing search policy. May consume anonymous quota. |
| Legacy mapping | Existing `search_programs` remains valid alias. |

### 2.10 `jpcite_evidence_packet`

| Field | Contract |
|---|---|
| Description | Resolved subject の既存 Evidence Packet を取得する lower-level packet primitive。 |
| Use when | agent already has `subject_kind` and `subject_id` and wants evidence envelope, not route/search. |
| Do not use when | user only has natural language question; use `jpcite_answer_packet` or `jpcite_route` first. |
| Inputs | `subject_kind` enum `program/houjin/law/tax_rule/case/...`; `subject_id` required; `include_rules` bool default true; `include_source_receipts` bool default true; `as_of` optional. |
| Outputs | `packet_id`; `subject`; `records[]`; `facts[]`; `rules[]`; `source_receipts[]`; `corpus_snapshot_id`; `known_gaps[]`; `human_review_required`; `billing_metadata`; `_disclaimer`. |
| Billing | Existing evidence packet unit. |
| Legacy mapping | Existing `get_evidence_packet` remains valid alias. |

## 3. Existing tool alias and compatibility policy

Compatibility principle: P0 names are additive aliases/facades. Existing tools keep their names, parameters, descriptions, and package-level entrypoints until an explicit deprecation window is completed.

### 3.1 P0 alias map

| P0 canonical | Existing compatible tool(s) | Compatibility decision |
|---|---|---|
| `jpcite_route` | none | New free control facade. Does not replace any existing tool. |
| `jpcite_cost_preview` | none / future REST cost preview | New free control facade. Required before paid broad execution. |
| `jpcite_usage_status` | `get_usage_status` | Register P0 alias; keep `get_usage_status` indefinitely or at least through v1.x. |
| `jpcite_answer_packet` | `get_evidence_packet`, `semantic_search_am`, `search_programs`, `search_laws`, `get_source_manifest`, `verify_citations` | New facade. Existing primitives remain callable in core/full catalogs. |
| `jpcite_company_packet` | `dd_profile_am`, `get_houjin_360_am`, `houjin_invoice_status`, `invoice_risk_lookup`, `search_invoice_registrants`, `check_enforcement_am` | New facade. Do not rename existing company tools. |
| `jpcite_application_packet` | `prescreen_programs`, `smb_starter_pack`, `search_programs`, `search_loan_programs`, `search_tax_rules`, `check_exclusions`, `subsidy_combo_finder` | New facade for profile-to-strategy. Existing discovery tools remain. |
| `jpcite_source_ledger` | `get_source_manifest`, `get_provenance`, `get_provenance_for_fact`, `verify_citations`, `fact_signature_verify_am` | New facade or alias with broader input resolution. Existing provenance tools remain. |
| `jpcite_monthly_review` | `prepare_kessan_briefing`, `match_due_diligence_questions`, `forecast_program_renewal`, `cross_check_jurisdiction` | New batch/review facade with cost cap and idempotency. Existing composition tools remain expert catalog. |
| `jpcite_program_search` | `search_programs` | Agent-first alias. Existing `search_programs` remains core/full canonical for backward compatibility. |
| `jpcite_evidence_packet` | `get_evidence_packet` | Agent-first alias. Existing `get_evidence_packet` remains stable. |

### 3.2 Catalog publication behavior

| Surface | Recommended behavior |
|---|---|
| `.well-known/mcp.json` | Advertise P0 catalog first. Link `full_catalog_url` for 155 tools. |
| `mcp-server.json` | Prefer P0 default once migration is accepted. Include `x-jpcite-catalog-layer=p0_agent_catalog`. |
| `mcp-server.full.json` | Keep all 155 tools. Hard drift checks compare full/DXT registry where relevant. |
| `mcp-server.core.json` | Keep search/detail/provenance primitives, not packet facade only. |
| DXT/desktop bundle | Default install should teach P0 routes first. Expert mode can expose full catalog. |
| Docs | First page shows 10 P0 tools and routing rules. Full 151 list moves behind "advanced/full catalog". |

### 3.3 Package and import compatibility

Do not use P0 catalog work as a package rename.

| Item | Keep | Additive alias allowed |
|---|---|---|
| PyPI package | `autonomath-mcp` | Future `jpcite-mcp` only if it wraps or depends on existing package; no forced rename. |
| CLI command | `autonomath-mcp`, `autonomath-api`, `autonomath-ingest` | Existing `jpcite-api`, `jpcite-ingest`; future `jpcite-mcp` optional. |
| Python package | `jpintel_mcp` | None required. |
| MCP implementation namespace | `jpintel_mcp.mcp.autonomath_tools` | Existing `jpintel_mcp.mcp.jpcite_tools` re-export alias stays additive. |
| Env vars | `AUTONOMATH_*` | Optional `JPCITE_*` mirrors only if both are supported and precedence is documented. |
| DB/table names | `am_*`, existing migrations | No rename for P0. Public output may avoid exposing internal table names. |

### 3.4 Deprecation policy

- No existing MCP tool name should be removed for P0.
- A tool can be hidden from P0 without being deprecated.
- If a legacy alias is ever deprecated, publish docs + changelog + manifest `deprecated=true` at least 90 days before behavior change.
- Breaking parameter rename requires dual-acceptance first. Example: accept both `q` and `query`; canonical wins when both are set.
- Alias behavior must be idempotent: alias registration must not double-bill, double-log, or double-register identical tools.
- Description drift matters. P0 alias and existing tool descriptions must not make contradictory claims about counts, pricing, limitations, or professional fences.

## 4. Tool description rules

P0 descriptions must be short enough for agents but complete enough to route safely. Recommended shape:

```text
Purpose: ...
Use when: ...
Do not use when: ...
Inputs: ...
Returns: ...
Billing: ...
Must preserve: source_receipts, known_gaps, human_review_required, billing_metadata, _disclaimer.
Not final judgment: ...
Common failures: ...
```

### 4.1 Mandatory description fields

| Field | Requirement |
|---|---|
| `Purpose` | One business-task sentence. Avoid table names and implementation history. |
| `Use when` | Closed list of 3-6 situations. |
| `Do not use when` | Closed list including final professional judgment and better-tool alternatives. |
| `Inputs` | Required vs optional fields, with max counts and defaults. |
| `Returns` | Top-level fields only. Do not paste full schemas into description. |
| `Billing` | Free/paid, preview/cap/idempotency requirement, anonymous quota effect. |
| `Must preserve` | Fields downstream agent must carry into final answer or artifact. |
| `Professional fence` | Tax/legal/audit/credit/application boundaries where relevant. |
| `Failure handling` | `no_hit_not_absence`, validation, auth, quota, cap, idempotency conflict. |

### 4.2 Claims to prohibit in tool descriptions

Never allow descriptions, manifest metadata, or examples to claim:

| Forbidden claim | Safer wording |
|---|---|
| "all Japanese subsidies/programs" | "public-searchable records in the current jpcite corpus" |
| "latest/current/real-time" | "source_fetched_at indicates when jpcite fetched the source; verify primary source for current filing/submission decisions" |
| "officially verified by government" | "source-linked to public/government sources where available" |
| "guarantees eligibility" | "screens eligibility signals and gaps; final eligibility must be confirmed with source/operator" |
| "guarantees adoption/approval" | "adoption/approval is not predicted or guaranteed" |
| "adoption probability" for similarity score | "similarity score / statistical signal; not a probability unless calibrated and documented" |
| "clean record" on no hit | "no matching record in the searched public corpus; absence is not proof of no record" |
| "credit safe / low risk / anti-social-force cleared" | "public-data signal only; not a credit, compliance, or anti-social-force determination" |
| "legal advice / tax advice / audit opinion" | "evidence support / citation retrieval / screening aid; human professional review required" |
| "application document completed" | "scaffold/checklist only; regulated drafting/submission may require qualified professional" |
| "source receipts prove legal admissibility" | "receipts support reproducibility; admissibility depends on context and reviewer" |
| "no external costs ever" | "jpcite billing excludes external LLM/agent/cloud costs unless a contract explicitly says otherwise" |
| "NO LLM" as broad product claim | Use only when the specific tool path truly performs no request-time LLM call; otherwise say `request_time_llm_call_performed` accurately. |
| "exhaustive graph/relationship coverage" | "known graph edges in the current corpus; sparse/noisy edges are marked" |
| "exact remaining anonymous quota over stdio" | "MCP stdio cannot resolve per-IP anonymous bucket; HTTP usage endpoint can report exact value" |

### 4.3 Required negative examples

Tool descriptions should explicitly teach agents these interpretations:

- Empty `results[]` means "no matching record in this corpus/query", not "does not exist".
- Missing `source_fetched_at` or sparse fact provenance is a known gap, not a license to hallucinate.
- `source_fetched_at` is fetch time, not official update time.
- `human_review_required=true` must be surfaced, not silently ignored.
- `known_gaps[]` must be copied into user-facing caveats when answer quality depends on them.
- Cost preview is not execution and should not be described as a charged result.

## 5. Tool selection and routing rules

These rules should be embedded in docs, manifests, examples, and P0 descriptions.

### 5.1 First-call rule

| User situation | First tool |
|---|---|
| Agent is unsure whether jpcite is relevant | `jpcite_route` |
| User asks a source-sensitive Japanese public data question | `jpcite_answer_packet` |
| User asks "which subsidies/programs might fit me?" with business profile | `jpcite_application_packet` |
| User asks simple keyword search for public programs | `jpcite_program_search` |
| User asks about a Japanese company/counterparty | `jpcite_company_packet` |
| User has existing packet/artifact and needs citations/receipts | `jpcite_source_ledger` |
| User wants recurring client list review | `jpcite_cost_preview` then `jpcite_monthly_review` |
| User is anonymous or quota/cap matters | `jpcite_usage_status` |
| Agent already has subject_kind + subject_id | `jpcite_evidence_packet` |

### 5.2 Cost and cap rule

- Always call `jpcite_cost_preview` before paid broad execution, batch, CSV, watchlist, monthly review, or uncertain fanout.
- Reject paid broad execution before billable work when `cost_cap_jpy` is missing or below estimate.
- Require `idempotency_key` for paid POST-like packet/batch/monthly operations.
- Do not charge failed validation, auth rejection, cap rejection, or preview.
- Do not silently split a broad request into multiple paid calls to bypass a cap.

### 5.3 Packet-vs-primitive rule

Use packet tools when the user needs an answer-ready evidence bundle:

- source receipts
- known gaps
- human review flags
- professional fences
- billing metadata
- multiple corpora joined into one envelope

Use primitives only when:

- the user is exploring and wants a small candidate list;
- the agent already has a specific ID;
- the task is a narrow lookup;
- cost must stay minimal and user will choose next step.

### 5.4 Professional boundary rule

When output touches tax, legal, audit, credit, grant approval, application drafting, labor/social insurance, or regulated professional acts:

- Prefer packet/facade that includes `_disclaimer` and `human_review_required`.
- Do not route directly to a raw expert tool unless the agent has enough context to preserve the fence.
- Do not let "score", "risk", "eligibility", "compatible", or "verified" become final judgment language.

### 5.5 No-hit rule

For every P0 tool:

- No hit must return `no_hit_not_absence=true` or equivalent wording.
- Agent should say "jpcite の検索対象では見当たりません" rather than "存在しません".
- Suggest `retry_with` when filters may be too narrow, aliases uncertain, or source coverage sparse.

### 5.6 Full catalog escape hatch

Agent may move from P0 to full catalog only when at least one condition holds:

- P0 packet returns `next_calls` naming a specific full-catalog tool.
- User explicitly asks for a specialized dataset, e.g. 裁決, 通達, 36協定, shihoshoshi DD, graph path.
- The agent already has canonical IDs and needs a precise primitive.
- The P0 facade declares unsupported scope but recommends an expert tool.

Agent should not scan all 155 tools opportunistically. It should route through P0, then follow explicit `next_calls`.

## 6. Manifest and schema recommendations

### 6.1 P0 manifest fields

Each P0 tool entry should carry machine-readable metadata in addition to human description:

```json
{
  "name": "jpcite_application_packet",
  "x-jpcite-catalog-layer": "p0_agent_catalog",
  "x-jpcite-aliases": ["createApplicationStrategyPacket"],
  "x-jpcite-compatible-tools": ["prescreen_programs", "smb_starter_pack", "search_programs"],
  "x-jpcite-billing": {
    "free": false,
    "cost_preview_required": true,
    "cap_required": true,
    "idempotency_key_required": true,
    "external_costs_included": false
  },
  "x-jpcite-agent": {
    "must_preserve_fields": [
      "source_receipts",
      "known_gaps",
      "human_review_required",
      "_disclaimer",
      "billing_metadata"
    ],
    "no_hit_not_absence": true,
    "forbidden_claims": [
      "guarantees eligibility",
      "guarantees adoption",
      "tax/legal/audit advice"
    ]
  }
}
```

### 6.2 Input schema discipline

P0 tools should use explicit JSON schemas. Avoid untyped `dict` descriptions where possible.

- Strings: length limits and examples.
- Arrays: max count and item type.
- Enums: closed lists for route class, output style, review type, subject kind.
- Dates: ISO `YYYY-MM-DD`, with timezone note when relative dates are interpreted.
- Money: integer yen fields; if using `man_yen`, field name must include unit.
- Company identifiers: validate 法人番号 as 13 digits where applicable.
- Idempotency: explicit `idempotency_key` field for MCP stdio plus REST header equivalent.
- Cost cap: explicit `cost_cap_jpy` field for MCP stdio plus REST header equivalent.

### 6.3 Output schema discipline

Every P0 output should make downstream agent behavior obvious:

| Field | Required in |
|---|---|
| `request_id` | all P0 |
| `schema_version` | all P0 |
| `generated_at` | all P0 |
| `billing_metadata` | all P0, including free control tools with `charged=false` |
| `source_receipts` | all source-bearing packet/primitive tools |
| `known_gaps` | all packet/source/search tools |
| `human_review_required` | all packet tools and sensitive primitives |
| `_disclaimer` | all sensitive/professional-boundary tools |
| `next_calls` | routing/search/packet tools where a safe follow-up exists |
| `retry_with` | no-hit/validation-narrowing cases |
| `request_time_llm_call_performed` | all P0 tools if used in public claims |

## 7. Migration sequence

Recommended P0 rollout without breaking existing clients:

1. Add P0 catalog docs and manifest metadata only. No runtime behavior change.
2. Add aliases/facades behind feature flag or separate `mcp-server.p0.json`.
3. Publish `.well-known/mcp.json` with P0 first and `full_catalog_url`.
4. Update DXT/desktop resources to teach P0 routing first.
5. Add description drift check: P0 alias and legacy tool cannot contradict billing, counts, limitations, or professional fences.
6. Observe agent selection logs: if agents still choose raw full tools first, tighten descriptions and hide full catalog from default.
7. Only after adoption, consider making P0 `mcp-server.json` default while preserving `mcp-server.full.json`.

Non-goals during migration:

- Do not rename `autonomath-mcp` package.
- Do not remove `search_programs`, `get_evidence_packet`, `get_usage_status`, or any existing 155 tool.
- Do not rewrite DB/table/env names for branding.
- Do not expose broken/off/regulated tools in P0.

## 8. Acceptance criteria

P0 catalog is acceptable when:

- Agent sees 10 recommended tools, not 151, on first contact.
- Existing full catalog remains available and name-compatible.
- At least one safe route exists for each primary business story: evidence answer, company baseline, application strategy, source ledger, monthly review, quick search, usage/cost.
- Every P0 tool states when not to use it.
- Every paid broad path requires preview, cap, and idempotency.
- Every sensitive output carries professional fence and no-hit caveat.
- `source_receipts`, `known_gaps`, `human_review_required`, `_disclaimer`, and `billing_metadata` are mandatory where relevant.
- Legacy package/import/CLI/env compatibility remains documented and untouched.
