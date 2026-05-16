# Packet taxonomy expansion deep dive

Date: 2026-05-15  
Owner lane: pre-implementation planning, packet taxonomy expansion  
Scope: no implementation. This document only expands the deliverable packet catalog under `docs/_internal/`.

## 0. Executive decision

`packet` は cache ではない。jpcite の有料価値は、AI agent が公開資料、制度ページ、PDF、法人情報、請求/会計/顧問先メモを読む前に使える「生成済み/先回り成果物」である。

P0 は次の 6 種に固定する。

1. `evidence_answer`
2. `company_public_baseline`
3. `application_strategy`
4. `source_receipt_ledger`
5. `client_monthly_review`
6. `agent_routing_decision`

P1 は「顧問先・法人・申請・DD・監視」の定期運用に刺さる packet を優先する。P2 は領域別の専門 workflow と大規模/高度差分 packet を広げる。

優先順位の評価式:

```text
priority_score =
  0.25 * repeat_frequency
+ 0.20 * paid_workflow_closeness
+ 0.18 * source_join_complexity
+ 0.15 * agent_time_saved
+ 0.10 * freshness_or_delta_value
+ 0.07 * boundary_safety
+ 0.05 * demo_clarity
```

## 1. Common contract expectation

全 packet は少なくとも次を持つ。

| Block | Purpose |
|---|---|
| `input_echo` | 正規化した入力。private input は必要最小限に丸める。 |
| `summary` | agent が最初に読む 30 秒 summary。 |
| `sections[]` / `records[]` / `claims[]` | 使える成果物本体。claim は receipt に戻れること。 |
| `source_receipts[]` | 出典 URL、取得/確認時刻、hash、license boundary、used_in。 |
| `known_gaps[]` | 不足、古い、不明、未対応、専門判断境界。 |
| `quality` | coverage, freshness, human review flags。 |
| `billing_metadata` | unit type, units, cost preview, cap behavior, external cost caveat。 |
| `agent_guidance` | must preserve fields, do_not_claim, follow-up routing。 |

Hard rules:

- `request_time_llm_call_performed=false` を維持する。
- 外部回答で使える claim は 1 つ以上の `source_receipt_id` を持つ。
- receipt がない item は `known_gaps` に移す。
- `no_hit` は不存在証明ではなく `no_hit_not_absence` として扱う。
- 税務、法務、監査、与信、申請、補助金、労務、登記に近い packet は `human_review_required=true` を default にする。
- `billing_metadata.external_costs_included=false` を明示し、外部 LLM/search/tool/runtime 料金は含めない。

## 2. P0 role redefinition

### 2.1 `evidence_answer`

Role:

- AI が最終回答を書く前に読む、引用候補付きの根拠 packet。
- 「答えそのもの」ではなく、回答に使ってよい fact、使う前に caveat が必要な fact、使ってはいけない unsupported claim を分ける。
- 現行 Evidence Packet の agent-facing facade。`answer_not_included=true` を中核価値にする。

Primary inputs:

- `query`, `topic`, `jurisdiction`, `prefecture`, `municipality`, `limit`, `packet_profile`
- 任意: `source_tokens_basis`, `source_pdf_pages`, `source_token_count`

Output:

- `summary`: query, answer_not_included, record_count, citation_candidate_count, known_gap_count
- `sections`: `answer_facts`, `citation_candidates`, `review_notes`, `do_not_claim`
- `claims`: source-linked atomic claims
- `records`: program/law/houjin/source records
- `agent_guidance`: final answer drafting order, required citation fields, disallowed claims

Known gaps:

- `source_missing`, `source_stale`, `coverage_partial`, `document_unparsed`, `deadline_missing`
- `license_boundary_metadata_only`, `no_hit_not_absence`, `professional_interpretation_required`
- `final_judgment_out_of_scope` when the query asks for final advice

Source receipts:

- One receipt per externally usable claim.
- Required receipt fields: `source_url`, `source_fetched_at|last_verified_at`, `content_hash|source_checksum`, `corpus_snapshot_id`, `license`, `used_in`, `claim_refs`.
- Citation candidate rows must copy `source_url` and `source_fetched_at` from receipts, not invent a parallel citation shape.

Billing metadata:

- `billable_unit_type=packet`
- `billable_units=1`
- `cost_preview_required=false` for single packet.
- Future batch or `limit > 20`: preview required before billable work.

### 2.2 `company_public_baseline`

Role:

- 日本企業調査の first-hop。法人番号/T番号/会社名から、公的情報で確認できる identity, invoice, enforcement, adoption, procurement/watch hints をまとめる。
- Web 検索や DD の代替ではなく、次に調べる範囲と質問を狭める baseline。

Primary inputs:

- `houjin_bangou` or `invoice_registration_number` or `company_name`
- 任意: `address`, `prefecture`, `include_sections`, `max_per_section`, `as_of`

Output:

- `sections`: `identity_resolution`, `invoice_status`, `public_event_timeline`, `enforcement_hits`, `adoption_history`, `jurisdiction`, `watch_suggestions`, `baseline_questions`
- `summary`: identity confidence, public-record coverage, unknown count
- `agent_guidance`: do not infer safety from no-hit; preserve identity confidence

Known gaps:

- `identity_ambiguity`, `identity_low_confidence`, `source_missing`, `no_hit_not_absence`
- `coverage_partial`, `source_stale`, `license_boundary_metadata_only`
- `final_judgment_out_of_scope` for credit, legal, audit, or safety verdicts

Source receipts:

- Positive receipts for identity, invoice status, enforcement/adoption/procurement hits.
- No-hit receipts for checked sources, paired with `no_hit_not_absence`.
- Receipt `used_in` must point to timeline rows and identity fields.

Billing metadata:

- `billable_unit_type=subject`
- `billable_units=1` per resolved company subject.
- Name-only ambiguous search should not bill multiple subjects unless user selects or explicitly requests fan-out.

### 2.3 `application_strategy`

Role:

- 事業者 profile から、補助金/助成金/融資/税制候補を「検索結果」ではなく申請前の検討材料に変換する。
- Candidate ranking, eligibility signals, exclusions, required facts, same-expense/compatibility notes, client/professional questions を返す。
- 「申請できます」「採択されます」ではなく、「候補」「要確認」「blocking risk」「質問」を返す。

Primary inputs:

- `profile`: location, industry, entity form, employee_count, capital, revenue band, investment plan, expense types, timing, certifications, past adoptions
- 任意: `target_program_ids`, `compatibility_top_n`, `budget_jpy`, `deadline_window`, `private_notes_minimized`

Output:

- `sections`: `normalized_applicant_profile`, `ranked_candidates`, `amount_rate_deadline_table`, `eligibility_signals`, `exclusion_or_caution_points`, `compatibility_screen`, `required_documents_hint`, `questions_for_client`, `questions_for_official_window`, `next_actions`
- `copy_paste_parts`: client email snippet, internal memo, question list

Known gaps:

- `private_input_unverified`, `deadline_missing`, `required_document_missing`, `compatibility_unknown`
- `same_expense_rule_unknown`, `numeric_unit_uncertain`, `source_stale`, `professional_interpretation_required`

Source receipts:

- Receipts for each candidate, deadline, amount/rate, eligibility/exclusion clause, required document hint, compatibility verdict.
- If compatibility is inferred/unknown, receipt status must reflect `inferred` or `unknown`, never `verified`.

Billing metadata:

- `billable_unit_type=packet`
- `billable_units=1` for standard top-N strategy.
- Batch multi-client strategy should use `billable_unit_type=row` and require cost preview/idempotency.

### 2.4 `source_receipt_ledger`

Role:

- A packet about evidence quality itself. It gives an audit-grade ledger of receipts, claim refs, freshness, license boundary, and missing fields for one subject, packet, or workflow.
- Useful for agent audits, customer trust, billing disputes, DD workpapers, and source refresh decisions.

Primary inputs:

- `subject_kind`, `subject_id` or `packet_id` or `source_url`
- 任意: `include_claim_refs`, `include_no_hit_checks`, `freshness_threshold_days`, `receipt_profile=audit|agent|brief`

Output:

- `sections`: `receipt_index`, `claim_to_receipt_map`, `freshness_status`, `license_boundary_table`, `missing_receipt_fields`, `no_hit_checks`, `refresh_recommendations`
- `records`: source receipt rows
- `quality`: receipt completion, stale count, missing hash count

Known gaps:

- `source_receipt_missing`, `source_receipt_missing_fields`, `source_stale`, `license_boundary_metadata_only`
- `api_auth_or_rate_limited`, `document_unparsed`, `claim_without_source_coverage`, `no_hit_not_absence`

Source receipts:

- The packet returns receipts as the product.
- Self-referential receipt is not required for each ledger row, but the ledger packet must include `corpus_snapshot_id` and `bundle_sha256`.

Billing metadata:

- `billable_unit_type=packet`
- `billable_units=1` for one subject/packet ledger.
- Large ledger export should be `billable_unit_type=receipt_batch` with preview.

### 2.5 `client_monthly_review`

Role:

- 税理士、会計士、診断士、行政書士、商工会、金融機関が毎月回す client/account review packet。
- 顧問先/会員/融資先ごとに、今月見る制度、期限、法改正、インボイス/処分/採択差分、顧客質問、所内タスクを返す。
- Repeat usage が高く、P0 の中で最も LTV に近い。

Primary inputs:

- `client_subjects[]`: houjin_bangou, profile hints, tags, fiscal_month, industry, location
- 任意: `review_month`, `include_private_overlay_minimized`, `watch_topics`, `max_items_per_client`, `delta_since_packet_id`

Output:

- `sections`: `client_priority_queue`, `this_month_watch_items`, `deadline_risks`, `changed_public_records`, `program_candidates`, `tax_or_system_change_notes`, `questions_for_client`, `office_tasks`, `copy_paste_client_messages`
- Per-client `known_gaps` and global `known_gaps`.

Known gaps:

- `private_input_unverified`, `csv_provider_unknown`, `csv_period_unknown`, `csv_mapping_required`
- `coverage_partial`, `source_stale`, `deadline_missing`, `no_hit_not_absence`, `manual_review_required`

Source receipts:

- Receipts for public facts and changed items.
- Private overlay facts must use private, non-persisted refs and should not be mixed into public source ledger.
- Delta rows must preserve previous packet id/hash when available.

Billing metadata:

- `billable_unit_type=row|subject`
- `billable_units=count(successful_client_subjects)` for batch review.
- Cost preview and idempotency required before commit.
- Failed validation/no resolved subject rows should be non-billable.

### 2.6 `agent_routing_decision`

Role:

- AI agent が「jpcite を呼ぶべきか、どの packet を呼ぶべきか、呼んではいけないか」を判断する routing packet。
- Public pages/GEO/Custom GPT/Claude/Codex integration の conversion layer。実データ成果物ではなく、次の packet へ安全に誘導する。

Primary inputs:

- `user_task`, `available_context`, `region`, `subject_hint`, `risk_domain`, `desired_output`
- 任意: `cost_cap_jpy`, `agent_platform`, `already_have_source_receipts`, `privacy_constraints`

Output:

- `sections`: `route_decision`, `recommended_packets`, `required_inputs`, `cost_preview`, `why_jpcite`, `fallback_if_not_available`, `do_not_route_reasons`
- `agent_guidance`: exact tool/endpoint name, required fields to preserve, disclaimer to show

Known gaps:

- `unsupported_task`, `out_of_scope`, `cost_preview_required`, `quota_or_auth_required`
- `legal_or_tax_interpretation_required`, `final_judgment_out_of_scope`, `private_input_minimized`

Source receipts:

- Usually none for routing itself unless referencing public packet catalog examples.
- If it recommends based on catalog metadata, include catalog/source receipts for endpoint metadata and examples.

Billing metadata:

- Prefer `_billing_unit=0` or free preview where used only for routing and conversion.
- If exposed as paid diagnostic for enterprise evals, `billable_unit_type=packet`, but default should be free to reduce adoption friction.

## 3. P1 packet candidates, prioritized

P1 should be implemented after P0 facade stability because these packets become paid repeat workflows. Each entry below includes minimum input/output/gaps/receipts/billing requirements.

| Priority | packet_type | Why P1 | input | output | known_gaps | source_receipts | billing_metadata |
|---:|---|---|---|---|---|---|---|
| P1-01 | `funding_stack_compatibility_matrix` | High-value join; avoids unsafe併用 claims. | `program_ids[]`, expense categories, applicant profile, as_of | pairwise matrix, blockers, same-expense risks, timing constraints, official questions | `compatibility_unknown`, `same_expense_rule_unknown`, `source_stale`, `professional_interpretation_required` | per pair verdict, rule clause, inferred/unknown status | `compatibility_pair`; preview if >10 pairs |
| P1-02 | `subsidy_application_checklist` | Converts search into preparation work. | program_id or candidate set, applicant profile, target round | document checklist, facts needed, evidence to keep, form/source links, client questions | `required_document_missing`, `deadline_missing`, `document_unparsed`, `source_stale` | program docs, forms, deadlines, FAQ clauses | `packet`; 1 unit per program/profile |
| P1-03 | `houjin_dd_pack` | Already adjacent to existing artifact; buyer pain is clear. | houjin/T/name, context, as_of, max timeline rows | identity, invoice, public money, enforcement, procurement, DD questions | `identity_ambiguity`, `no_hit_not_absence`, `coverage_partial`, `source_stale` | positive and no-hit receipts for every checked source | `subject`; 1 unit per resolved entity |
| P1-04 | `invoice_compliance_evidence` | Accounting/BPO recurring utility. | T-number/houjin/name, counterparty list optional, as_of | registration status, history, name/address match, caution windows, accounting questions | `identity_low_confidence`, `no_hit_not_absence`, `source_stale`, `period_mismatch` | invoice registry, houjin master, no-hit checks | `subject` or `row`; batch preview |
| P1-05 | `supplier_invoice_enforcement_screen` | Practical AP/vendor onboarding packet. | suppliers[], T/houjin/name/address, screening date | identity match, invoice registration, enforcement hits, watch recommendations | `csv_mapping_required`, `identity_ambiguity`, `no_hit_not_absence`, `coverage_partial` | per supplier source and no-hit receipts | `row`; preview/idempotency required |
| P1-06 | `deadline_matrix` | Easy agent-visible value; stale deadlines are costly. | query/profile/program_ids, jurisdiction, date window | deadline table, confidence, source freshness, calendar export hints | `deadline_missing`, `source_stale`, `document_unparsed`, `period_mismatch` | each deadline source with fetched_at/hash | `packet`; export may stay same unit |
| P1-07 | `monitoring_delta_digest` | Repeat revenue; converts snapshots to action. | watchlist_id or subjects[], since_packet_id/date, topics | changed items, unchanged coverage, regenerate recommendations, outreach tasks | `source_stale`, `coverage_partial`, `no_hit_not_absence`, `private_input_unverified` | current and previous source hashes/receipts | `subject` or `watchlist`; preview for batches |
| P1-08 | `tax_cliff_calendar` | Strong for accounting offices, but boundary-sensitive. | client segments, fiscal months, tax topics, date window | upcoming cliffs, affected segments, action window, source confidence, questions | `legal_or_tax_interpretation_required`, `source_stale`, `coverage_partial` | laws/tax rules/source docs per cliff | `packet`; human review required |
| P1-09 | `certification_leverage` | Good bridge from company profile to funding strategy. | houjin/profile, current certifications, target investments | certification status, linked programs, missing certifications, timing dependencies | `private_input_unverified`, `source_missing`, `timing_dependency_unknown` | certification sources and program references | `packet`; 1 unit |
| P1-10 | `eligibility_question_list` | Safe alternative to eligibility verdict. | program_id/query, profile, question depth | questions, why_asked, source fields, answer_type, blocking facts | `private_input_unverified`, `required_document_missing`, `compatibility_unknown` | each question linked to rule/source | `packet`; 1 unit |
| P1-11 | `adoption_case_benchmark` | Useful for consultants without promising success. | industry, region, theme, program_id optional | similar cases, theme patterns, investment keywords, public limits | `coverage_partial`, `license_boundary_metadata_only`, `source_stale` | adoption case sources per pattern | `packet`; result cap independent |
| P1-12 | `enforcement_clawback_risk` | DD and grant compliance value. | houjin/name, period, program context optional | timeline, red/yellow flags, entity confidence, DD questions | `identity_ambiguity`, `no_hit_not_absence`, `source_stale`, `coverage_partial` | enforcement, return/cancel, public docs | `subject`; 1 unit |
| P1-13 | `public_funding_traceback` | Journalist/DD/audit differentiator. | houjin/entity, period, include procurement/adoption/enforcement | money/public event timeline, source links, open questions | `identity_low_confidence`, `coverage_partial`, `no_hit_not_absence` | each event receipt plus entity resolution | `subject`; higher cap for long periods |
| P1-14 | `auditor_evidence_binder` | Receipts as workpaper; defensible enterprise use. | packet_ids[] or subjects[], binder profile | binder index, evidence items, hashes, review queue | `source_receipt_missing_fields`, `source_stale`, `license_boundary_metadata_only` | all underlying receipts, deduped | `receipt_batch`; preview required |
| P1-15 | `counterparty_public_dd` | Same market as houjin DD, broader wording. | counterparty identifiers, use context, as_of | public DD memo, red/yellow flags, unknowns, questions | `identity_ambiguity`, `no_hit_not_absence`, `final_judgment_out_of_scope` | all checked public sources | `subject`; 1 unit |
| P1-16 | `loan_portfolio_watchlist_delta` | Repeat financial-institution workflow. | borrower list, since date, topics, RM tags | changed entities, public funding hits, enforcement hits, RM actions | `csv_provider_unknown`, `identity_ambiguity`, `source_stale` | per changed row and no-hit summary | `row`; preview/idempotency |
| P1-17 | `company_folder_brief` | Already adjacent; turns baseline into CRM/file artifact. | company_public_baseline packet_id or houjin | folder README, CRM note, questions, source receipt summary | inherits baseline gaps, `source_receipt_missing` | references baseline receipts | `packet`; 1 unit |
| P1-18 | `ai_answer_guard` | Enables agent builders; reduces misuse. | domain, user persona, allowed endpoints, risk tolerance | allowed claims, must_not_claim, disclaimer, citation rules | `unsupported_task`, `final_judgment_out_of_scope`, `quota_or_auth_required` | catalog/docs receipts if public-facing | free or `packet` for enterprise eval |

## 4. P2 packet candidates, prioritized

P2 expands domain coverage and advanced workflows after P1 repeat loops are proven. Keep these behind catalog entries until source coverage and buyer demand justify implementation.

| Priority | packet_type | Why P2 | input | output | known_gaps | source_receipts | billing_metadata |
|---:|---|---|---|---|---|---|---|
| P2-01 | `application_kit` | Deeper than checklist; needs form/document parsing. | target program/round, profile, desired submission date | requirement table, form list, submission order, client request letter | `document_unparsed`, `required_document_missing`, `source_stale` | forms, guidelines, FAQ, deadlines | `packet`; may be >1 unit if doc fanout |
| P2-02 | `subsidy_strategy_report` | Consultant-facing premium output; boundary risk. | company profile, project plan, candidate set | ranked top 3-5, fit reasons, weak points, proposal order | `professional_interpretation_required`, `coverage_partial`, `compatibility_unknown` | candidates, adoption cases, rule clauses | `packet`; 1 unit initially |
| P2-03 | `tax_client_impact_memo` | Valuable but tax-boundary heavy. | client profile, fiscal month, investments, tax topics | client memo, affected rules, questions, review flags | `legal_or_tax_interpretation_required`, `source_stale`, `private_input_unverified` | tax rules, laws, official notices | `packet`; human review required |
| P2-04 | `labor_grant_question_packet` | Clear specialist use; needs labor-specific source model. | employer profile, employment changes, grant topic | labor facts needed, document questions, risk words | `professional_interpretation_required`, `required_document_missing`, `source_missing` | grant/labor official sources | `packet`; 1 unit |
| P2-05 | `ip_subsidy_evidence_pack` | Narrow but high-value for R&D/IP support. | R&D/IP plan, region, company profile | IP/R&D candidates, timing risks, expense questions | `coverage_partial`, `publication_timing_unknown`, `source_stale` | program and IP-related source docs | `packet`; 1 unit |
| P2-06 | `member_program_watchlist` | Association recurring workflow; similar to monthly review. | member list, association tags, review window | segments, changed programs, outreach copy | `csv_mapping_required`, `coverage_partial`, `source_stale` | per segment/program receipts | `row` or `watchlist`; preview |
| P2-07 | `ma_target_public_risk_memo` | Good DD narrative; needs strict no-verdict fence. | target identifiers, deal context, period | baseline, public money exposure, compliance history, DD questions | `identity_ambiguity`, `no_hit_not_absence`, `final_judgment_out_of_scope` | entity/event/source receipts | `subject`; 1 unit |
| P2-08 | `journalist_public_interest_brief` | GEO/public citation value, but buyer path less direct. | entity/topic, period, public interest angle | known facts, timeline, docs to request, reply questions | `coverage_partial`, `license_boundary_metadata_only`, `identity_ambiguity` | event/source receipts, no long excerpts | `packet`; 1 unit |
| P2-09 | `lender_public_risk_sheet` | Enterprise value; needs compliance/legal review. | borrower profile, loan purpose, identifiers | risk notes, support candidates, required docs,稟議 notes | `final_judgment_out_of_scope`, `coverage_partial`, `source_stale` | public risk/support receipts | `subject`; 1 unit |
| P2-10 | `executive_funding_roadmap` | Planning artifact; depends on many volatile deadlines. | 12-month plan, investment/certification roadmap | quarterly actions, certification prep, monitoring targets | `deadline_missing`, `compatibility_unknown`, `private_input_unverified` | program/tax/certification receipts | `packet`; 1 unit |
| P2-11 | `procurement_opportunity_fit` | Useful for bids users; source freshness high. | company profile, region, CPV/category hints | bid fit list, eligibility questions, deadlines | `source_stale`, `document_unparsed`, `coverage_partial` | bid notices and requirements | `packet`; 1 unit |
| P2-12 | `public_contract_counterparty_map` | Advanced public money/contract graph. | entity, period, hop depth | counterparty graph, contract timeline, unknowns | `identity_low_confidence`, `coverage_partial`, `license_boundary_metadata_only` | procurement/source receipts | `subject_graph`; preview for hops |
| P2-13 | `law_change_impact_brief` | Useful for agents; needs robust law update chain. | law/topic, industry/profile, date window | change summary, affected workflows, questions | `legal_or_tax_interpretation_required`, `source_stale`, `coverage_partial` | laws, amendments, notices | `packet`; 1 unit |
| P2-14 | `regulatory_horizon_scan` | Watch product for upcoming changes. | topics, industries, jurisdictions, window | upstream signals, stage, recommended watch | `coverage_partial`, `source_stale`, `signal_not_rule` | kokkai/shingikai/pubcomment/law sources | `packet`; 1 unit |
| P2-15 | `program_successor_revision_watch` | Strong data advantage if snapshots exist. | old program_id/topic, region, since date | successor candidates, revision deltas, confidence | `successor_unknown`, `coverage_partial`, `source_stale` | old/new program receipts | `packet`; 1 unit |
| P2-16 | `historical_snapshot_replay` | Useful for disputes and audits. | subject/query, as_of date, fields | as-of facts, changed since, source snapshot refs | `period_mismatch`, `source_missing`, `coverage_partial` | historical snapshot receipts | `packet`; 1 unit |
| P2-17 | `industry_pack_digest` | Broad marketing/demo use; less individualized. | industry, region, period | relevant programs, risks, deadlines, examples | `coverage_partial`, `deadline_missing`, `source_stale` | source receipts per item | `packet`; 1 unit |
| P2-18 | `municipality_program_gap_scan` | GEO/SEO useful; data coverage uneven. | municipality/prefecture, theme | local programs, missing source notes, crawl targets | `source_missing`, `coverage_unknown`, `document_unparsed` | municipality source receipts | `packet`; possibly internal first |
| P2-19 | `source_refresh_trigger_packet` | Operational value; not direct buyer output. | source_id/packet_id, freshness policy | refresh reason, affected packets, priority | `source_stale`, `api_auth_or_rate_limited`, `source_missing` | source profile/freshness ledger receipts | internal/free or ops unit 0 |
| P2-20 | `schema_contract_assertion_packet` | Helps agent integrators/evals. | endpoint/tool/schema version, sample payload | compatibility report, required fields, breaking risks | `unsupported_task`, `schema_mismatch`, `source_receipt_missing_fields` | docs/openapi receipts | free for catalog; paid enterprise eval |
| P2-21 | `billing_reconciliation_packet` | Supports trust and disputes. | api key/account, billing cycle, usage IDs | unit ledger, packet IDs, no-charge rows, dispute refs | `usage_event_missing`, `idempotency_unknown`, `period_mismatch` | usage/billing internal receipts, not public source receipts | account metadata; `_billing_unit=0` |
| P2-22 | `data_correction_workorder` | Turns user correction into source-backed queue. | reported issue, source URL, affected packet | triage, required proof, affected claims | `source_missing`, `license_boundary_metadata_only`, `manual_review_required` | submitted source + current corpus receipt | free intake; no bill |
| P2-23 | `customer_webhook_payload_packet` | Integration-friendly, not core evidence. | event type, packet id, webhook target profile | normalized payload, retry/cap metadata | `unsupported_task`, `quota_or_auth_required` | references source packet receipts | included in webhook product |
| P2-24 | `redline_between_packets` | Useful for monitoring and audits. | old_packet_id, new_packet_id | changed claims, changed receipts, stale-to-fresh changes | `period_mismatch`, `source_receipt_missing`, `coverage_partial` | old/new receipt pairs | `packet_pair`; 1 unit |
| P2-25 | `multi_packet_answer_brief` | Agent convenience; risk of seeming like LLM answer. | packet_ids[], desired brief type | stitched outline, citation map, unresolved gaps | `final_judgment_out_of_scope`, `source_receipt_missing` | inherited receipts only | `packet_batch`; preview if many |
| P2-26 | `professional_handoff_packet` | Useful for legal/tax/application referrals. | source packet_id, profession, issue type | handoff memo, facts, gaps, questions, disclaimers | `professional_interpretation_required`, `private_input_minimized` | inherited and handoff receipts | `packet`; 1 unit |
| P2-27 | `watchlist_onboarding_packet` | Helps convert CSV import to recurring workflow. | CSV metadata, columns, sample rows, desired topics | mapping plan, identity match preview, billing preview | `csv_mapping_required`, `csv_provider_unknown`, `private_input_minimized` | no public receipts until commit | free preview; commit bills rows |
| P2-28 | `coverage_gap_market_map` | Internal/product-led growth insight. | domain/source family/jurisdiction | missing sources, impact, packet candidates | `coverage_unknown`, `source_missing`, `license_boundary_metadata_only` | source profile receipts | internal only, unit 0 |

## 5. Candidate grouping by buyer workflow

Near-term commercial grouping:

| Workflow | P0/P1/P2 packets |
|---|---|
| Agent answer with citations | `agent_routing_decision`, `evidence_answer`, `source_receipt_ledger`, `ai_answer_guard` |
| Tax/accounting monthly operation | `client_monthly_review`, `tax_cliff_calendar`, `tax_client_impact_memo`, `invoice_compliance_evidence` |
| Grant/application preparation | `application_strategy`, `funding_stack_compatibility_matrix`, `subsidy_application_checklist`, `application_kit`, `adoption_case_benchmark` |
| Public company DD | `company_public_baseline`, `houjin_dd_pack`, `counterparty_public_dd`, `public_funding_traceback`, `enforcement_clawback_risk` |
| AP/vendor onboarding | `supplier_invoice_enforcement_screen`, `invoice_compliance_evidence`, `monitoring_delta_digest` |
| Finance/M&A/audit | `lender_public_risk_sheet`, `ma_target_public_risk_memo`, `auditor_evidence_binder`, `public_contract_counterparty_map` |
| Data/ops trust | `source_receipt_ledger`, `source_refresh_trigger_packet`, `redline_between_packets`, `billing_reconciliation_packet` |

## 6. Packets not to adopt now

| Rejected packet | Reason |
|---|---|
| `final_eligibility_verdict` | Crosses into application/legal/tax judgment. Should be expressed as `eligibility_question_list` or `application_strategy` with gaps. |
| `grant_award_probability_score` | Too easy to overstate; public data may be biased/incomplete. Use fit signals and adoption benchmark caveats instead. |
| `credit_approval_packet` | Would imply lending/credit decision. Use public DD/risk sheet with no-verdict fence. |
| `tax_savings_recommendation` | Tax advice boundary. Use tax cliff/client impact memo with professional review. |
| `legal_opinion_packet` | Legal opinion is out of scope. Use evidence/handoff packet. |
| `audit_opinion_packet` | Audit assurance is out of scope. Use evidence binder with source receipts. |
| `compliance_clearance_certificate` | "No risk" or "clear" cannot be proven from public corpus/no-hit checks. |
| `no_enforcement_certificate` | No-hit is not absence. Use enforcement screen with `no_hit_not_absence`. |
| `auto_application_submission_packet` | Moves from information support to application代理/regulated workflow. Keep preparation/checklist only. |
| `docx_filled_application_form_packet` as generic packet | High liability and source/form volatility. Per-program export may exist, but not taxonomy-level P0/P1 packet. |
| `private_company_financial_health_score` | Requires private financial data and may imply credit/investment advice. |
| `employee_labor_compliance_verdict` | Labor/legal judgment. Use labor grant question packet. |
| `news_sentiment_risk_packet` | Current jpcite value is public official evidence; news sentiment requires live web/news licensing and drift controls. |
| `social_media_reputation_packet` | Not aligned with official-source evidence layer; high noise and privacy risk. |
| `web_search_summary_packet` | Too close to generic browsing/RAG. jpcite should return source-linked public corpus outputs, not generic search summaries. |
| `llm_generated_final_answer_packet` | Violates no-LLM/product boundary and weakens the "evidence before answer" positioning. |
| `raw_cache_packet` | No added value beyond caller cache. Only adopt when transformed into receipt-backed, action-ready output. |
| `all_sources_dump_packet` | Bloats context; opposite of compression. Use source receipt ledger or binder with filters. |
| `unbounded_bulk_company_report` | Cost/cap and quality controls would be unclear. Use row-billed batch packets with preview/idempotency. |
| `personal_data_enrichment_packet` | Not core to public corporate/legal/program corpus; privacy and terms risk. |

## 7. Recommended implementation order after P0

1. P1-01 `funding_stack_compatibility_matrix`
2. P1-03 `houjin_dd_pack`
3. P1-04 `invoice_compliance_evidence`
4. P1-06 `deadline_matrix`
5. P1-07 `monitoring_delta_digest`
6. P1-02 `subsidy_application_checklist`
7. P1-05 `supplier_invoice_enforcement_screen`
8. P1-10 `eligibility_question_list`
9. P1-14 `auditor_evidence_binder`
10. P1-18 `ai_answer_guard`

Reasoning:

- These reuse existing evidence/artifact/source receipt foundations.
- They avoid final judgment while creating immediate agent-usable artifacts.
- They are easy to demo: "before agent answers, get receipt-backed facts, questions, and next actions."
- They support repeat usage or batch usage, not one-off search curiosity.

## 8. Open design questions

1. Should `agent_routing_decision` always be free, or should enterprise eval/routing diagnostics be paid separately?
2. Should `client_monthly_review` bill only changed clients or every successfully reviewed client? Recommendation: every successfully reviewed client, with changed/unchanged status in output.
3. Should P1 packet public examples be generated before endpoints exist? Recommendation: yes, but mark as schema examples and route through catalog/preview.
4. Should `company_public_baseline` and `houjin_dd_pack` remain separate? Recommendation: yes. Baseline is first-hop and low-friction; DD pack is a richer memo/workpaper.
5. Should packet taxonomy use `packet_type=application_strategy` or existing `artifact_type=application_strategy_pack`? Recommendation: facade type can be `application_strategy`; compatibility alias should preserve existing artifact type.

