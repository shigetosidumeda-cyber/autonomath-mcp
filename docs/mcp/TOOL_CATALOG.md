---
title: jpcite MCP Tool Catalog
generated: 2026-04-30
tool_count_total: 98
tool_count_default_on: 93
tool_count_default_off: 5
source_of_truth: src/jpintel_mcp/mcp/server.py + src/jpintel_mcp/mcp/autonomath_tools/__init__.py
see_also: ../../CLAUDE.md (Architecture > MCP exposes 93 tools)
extraction_method: static AST grep (no MCP server boot)
---

# jpcite MCP Tool Catalog

Static-grep audit of every `@mcp.tool` registration in the codebase as of 2026-04-30. Authoritative tool count is **93 default-on / 5 default-off / 98 total** when AUTONOMATH_ENABLED=1, all opt-out gates left at defaults, and the 5 broken/regulated tools left disabled.

See [CLAUDE.md](../../CLAUDE.md) Architecture section for the live runtime narrative. This file is the static source-of-truth for "which tool, what gate, what disclaimer."

## Summary

| Category | Tools | Default | Notes |
|---|---|---|---|
| **jpintel_prod** | 39 | ON | jpintel.db core: programs / case_studies / loan_programs / enforcement_cases / laws / tax_rulesets / court_decisions / bids / invoice_registrants + cross-dataset glue |
| **audit_composition** | 3 | ON | jpintel.db; 公認会計士法 §47条の2 + 税理士法 §52 disclaimer-bearing audit pipeline |
| **autonomath_other** | 25 | ON | autonomath.db; legacy V1 + per-domain wrappers + lifecycle/graph/rule-engine/abstract/prerequisite/citations/source/evidence/funding |
| **v4_universal** | 4 | ON | autonomath.db; annotations / validate / provenance entity & fact (V4 absorption 2026-04-25) |
| **phase_a** | 5 | ON | autonomath.db; static taxonomy bundle + example profiles + deep_health (Phase A absorption 2026-04-25) |
| **nta_corpus** | 4 | ON | autonomath.db; 国税不服審判所 / 通達 / 質疑応答 / 文書回答 (税理士法 §52 disclaimer) |
| **wave21** | 5 | ON | autonomath.db; multi-step composition tools (apply_eligibility_chain → simulate → lineage etc.) |
| **wave22** | 5 | ON | autonomath.db; DD / 決算 / renewal / jurisdiction / kit composition (税理士法 §52 / §72 / 行政書士法 §1) |
| **wave23** | 3 | ON | autonomath.db; industry packs (建設 / 製造 / 不動産) — programs + saiketsu + 通達 in 1 call |
| **broken** | 3 | **OFF** | Gated by AUTONOMATH_SNAPSHOT_ENABLED + AUTONOMATH_REASONING_ENABLED; smoke test 2026-04-29 found them broken |
| **kyotei36** | 2 | **OFF** | Gated by AUTONOMATH_36_KYOTEI_ENABLED; 労基法 §36 + 社労士法 — requires legal review before flip |

Total **93 default-on** + **5 default-off** = **98 surface tools**.

Sensitive flag (`§52` / `§47条の2` / `§72` / `§1` / 専門士業法) means the tool body or disclaimer banner explicitly cites a 専門士業法 fence: tax adviser (税理士法 §52), CPA audit (公認会計士法 §47条の2), 司法書士法 §72, 行政書士法 §1, 社労士法/労基法 §36. Such tools surface a `_disclaimer` field on every response.

## jpintel.db core (39)

Backed by `data/jpintel.db` (~352 MB FTS5). Search/get over programs (11,684) / case_studies (2,286) / loan_programs (108) / enforcement_cases (1,185) + meta + 7 one-shot composition + expansion datasets (laws / tax_rulesets / court_decisions / bids / invoice_registrants) + cross-dataset glue. All ungated.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `batch_get_programs` | jpintel.db | — | `—` | ON | DETAIL: 複数の制度を 1 コールで一括取得する (batch fetch up to 50 補助金 / 助成金 / 融資 / 税制 / 認定 programs). Use after search_programs returns a candidate list and the user wants full detail for comparison ("この3つの補助金を詳しく比較して") — 50 round-trips collapse to one. |
| `bid_eligible_for_profile` | jpintel.db | — | `—` | ON | SCREEN-BID: compare a business profile against bid.eligibility_conditions. Honest substring scan — not a structured eligibility engine. Returns `possibly_eligible` (bool, True unless a hard mismatch is found) + matched_signals + unmatched_s |
| `check_exclusions` | jpintel.db | — | `—` | ON | COMPLIANCE: 併給可否を機械的に判定する — 候補制度セットに対して 181 本の併給禁止 / 前提要件ルールを走らせ、違反するものだけ返す (given a candidate set of program IDs, run all 181 補助金 exclusion / prerequisite rules and return only the violations). This answers the core "can I combine A and B? |
| `combined_compliance_check` | jpintel + autonomath | — | `—` | ON | OMNIBUS-COMPLIANCE: one-shot compliance report combining (a) exclusion_rules check for the named program, (b) tax_rulesets evaluation against business_profile, (c) top-N relevant bids (filtered by program_id_hint when program_unified_id is  |
| `dd_profile_am` | jpintel.db | — | `—` | ON | ONE-SHOT DD: 法人番号 → 公表コンプライアンス + 採択実績 + インボイス登録 を 1 call. |
| `deadline_calendar` | jpintel.db | — | `—` | ON | ONE-SHOT CALENDAR: 今後 N ヶ月 (1..6) の締切を月別グルーピングで 1 call。 |
| `enum_values` | jpintel.db | — | `—` | ON | UTILITY: 他ツールのフィルタ値を先に検証する (probe which filter values actually exist for target_type / funding_purpose / program_kind / authority_level / event_type / ministry / loan_type / provider — call this *before* a search when unsure whether a value |
| `evaluate_tax_applicability` | jpintel.db | — | `—` | ON | JUDGE-TAX: evaluate eligibility predicates for tax rulesets against a caller business_profile. Walks `eligibility_conditions_json` per row and returns per-ruleset `applicable` + reasons + matched / unmatched predicate lists. Does NOT interp |
| `find_cases_by_law` | jpintel.db | — | `—` | ON | TRACE-LAW-CASES: given a LAW-<10 hex>, return (court_decisions citing it) + optionally (enforcement_cases linked to those decisions via enforcement_decision_refs). Essential for "which rulings + 会計検査院 findings interpret 補助金適正化法 第22条" in one |
| `find_precedents_by_statute` | jpintel.db | — | `—` | ON | TRACE-STATUTE: given a LAW-<10 hex> unified_id, return 判例 citing that statute via related_law_ids_json. Ordered by precedent_weight → court_level → decision_date. When `article_citation` is set, we additionally require the article string to |
| `get_bid` | jpintel.db | — | `—` | ON | DETAIL-BID: fetch a single 入札案件 (procurement notice / 落札結果). Returns bid_title, bid_kind, procuring_entity + houjin_bangou, ministry, prefecture, program_id_hint, all deadline + amount + winner fields, eligibility_conditions, classification |
| `get_case_study` | jpintel.db | — | `—` | ON | DETAIL: 採択事例 1 件の収録済みフィールドの詳細を取得する (fetch one case study). Returns recipient profile (company_name, 法人番号, prefecture, industry_jsic, employees, founded_year, capital_yen), case_title / case_summary, programs_used (list of 受給した補助金), sub |
| `get_court_decision` | jpintel.db | — | `—` | ON | DETAIL-CASE: fetch a single 判例 with full source lineage (courts.go.jp primary). Returns case_name, court, decision_date, key_ruling, impact_on_business, related_law_ids, precedent_weight, source_url + source_excerpt + fetched_at. |
| `get_enforcement_case` | jpintel.db | — | `—` | ON | DETAIL: 会計検査院 不正・不当請求事例 1 件の詳細を取得する (fetch one enforcement case). Returns full record: event_type, ministry, recipient (name + 法人番号 + kind), bureau, prefecture, occurred_fiscal_years, all amount_* fields (improper_grant / project_cost / gra |
| `get_law` | jpintel.db | — | `—` | ON | DETAIL-LAW: fetch a single 法令 row by LAW-<10 hex> unified_id. Returns full record with summary, article_count, ministry, enforced_date, superseded_by_law_id lineage, plus source_url + fetched_at. Provenance: e-Gov 法令 API V2 (CC-BY 4.0). |
| `get_loan_program` | jpintel.db | — | `—` | ON | DETAIL: 融資プログラム 1 件の詳細を取得する (fetch one 融資 program by numeric id). Returns full record including three-axis risk (担保 / 個人保証人 / 第三者保証人), interest rates (base + special), loan period, grace period, target_conditions, official_url + fetched_at  |
| `get_meta` | jpintel.db | — | `—` | ON | UTILITY: データの鮮度・網羅件数を確認する (verify dataset freshness and scope). Returns visible program count (excluded=0 AND tier != X), canonical vs external-source split, 採択事例 / 融資 / 行政処分 / rule counts, tier distribution (S/A/B/C/X), prefecture distribu |
| `get_program` | jpintel.db | — | `—` | ON | DETAIL: 1 制度の収録済みフィールドの詳細を unified_id で取得する (fetch one 補助金 / 助成金 / 融資 / 税制 / 認定 program detail). Returns application window, required documents, exclusion notes, statistics (J_*), plus source_url + fetched_at lineage. |
| `get_tax_rule` | jpintel.db | — | `—` | ON | DETAIL-TAX: fetch a single 税務判定ルールセット by TAX-<10 hex>. Returns ruleset_name, tax_category, ruleset_kind, effective_from / effective_until (watch cliff dates), related_law_ids, narrative eligibility_conditions, predicate JSON, rate_or_amount |
| `get_usage_status` | jpintel.db | — | `—` | ON | META: 現在のクォータ残量を確認する (probe current API quota state without consuming a slot). |
| `list_exclusion_rules` | indexed corpus | — | `—` | ON | COMPLIANCE: 補助金の併給禁止 / 前提要件ルールを列挙する (181 subsidy exclusion + prerequisite rules across sectors). Extracted from 公募要領 PDF footnotes — not available as structured data on Jグランツ 公開 API or any ministry site. |
| `list_law_revisions` | jpintel.db | — | `—` | ON | LINEAGE-LAW: trace the revision chain for a 法令 — walks `superseded_by_law_id` forward and backward to reconstruct (predecessors → this → successors → current). Essential for diachronic legal analysis ("which law was in force on 2023-06-01?" |
| `prescreen_programs` | jpintel.db | — | `—` | ON | DISCOVER-JUDGE: profile → ranked eligible programs (fit-based discovery, NOT keyword search). |
| `regulatory_prep_pack` | jpintel.db | — | `—` | ON | ONE-SHOT DISCOVERY: 業種 + 都道府県 (+ 規模) で「コンプラ pack」を 1 call で。 |
| `search_bids` | jpintel.db | — | `—` | ON | DISCOVER-BID: search 入札 (GEPS 政府電子調達 CC-BY 4.0 + self-gov top-7 JV flows + ministry *.go.jp). Primary-source only — NJSS-style aggregators are banned at ingest. Headline query: "vendors that won 5000万円+ 公募型補助 in 2025". |
| `search_case_studies` | jpintel.db | — | `—` | ON | EVIDENCE: 採択事例 (recipient profiles paired with programs actually received) を検索する — 2,286 records covering Jグランツ 採択結果 + mirasapo 事業事例 + 都道府県 事例集. The Jグランツ 公開 API does not expose adoption history; cross-ministry aggregation here normally req |
| `search_court_decisions` | jpintel.db | — | `—` | ON | DISCOVER-CASE: search 判例 (courts.go.jp hanrei_jp primary source). Ordered by precedent_weight (binding > persuasive > informational), then court_level (supreme > high > district …), then most-recent decision_date. Commercial aggregators (D1 |
| `search_enforcement_cases` | jpintel.db | — | `—` | ON | RISK: 会計検査院 (Board of Audit) の不正・不当請求事例を検索する — 1,185 historical findings of improper 補助金 handling (over-payment / 目的外使用 / eligibility failure / documentation defects). Spread across METI / MAFF / 国交省 / 厚労省; not available as a queryable list |
| `search_invoice_registrants` | jpintel.db | — | `—` | ON | LOOKUP-INVOICE: search 適格請求書発行事業者 (国税庁 bulk, PDL v1.0). Returns {total, limit, offset, results, attribution} — every response carries the mandatory 出典明記 + 編集・加工注記 block per PDL v1.0. |
| `search_laws` | jpintel.db | — | `—` | ON | DISCOVER-LAW: search e-Gov 法令 catalog (~3,400 憲法 / 法律 / 政令 / 勅令 / 府省令 / 規則 / 告示 / ガイドライン harvested under CC-BY 4.0). Primary surface for "what is the 根拠法 of 補助金 X" and "which statute does this article cite" questions. Returns law_title + nu |
| `search_loan_programs` | jpintel.db | — | `—` | ON | DISCOVER: 無担保・無保証 の融資を 1 クエリで抽出する — 108 日本の融資プログラム (日本政策金融公庫 / 自治体融資 / 信用金庫 etc.) with three-axis risk filters. Headline feature: 担保 (collateral) / 個人保証人 (personal guarantor) / 第三者保証人 (third-party guarantor) are each a **separate enum axis* |
| `search_programs` | jpintel.db | — | `—` | ON | DISCOVER: Search 11,684 searchable Japanese public programs (subsidies/loans/tax incentives/certifications) with Tier-graded data quality. |
| `search_tax_rules` | jpintel.db | — | `—` | ON | DISCOVER-TAX: search 税務判定ルールセット (国税庁 タックスアンサー + 電帳法一問一答 + インボイス Q&A). Each row pairs narrative `eligibility_conditions` with a machine-readable predicate tree for `evaluate_tax_applicability`. |
| `similar_cases` | jpintel.db | — | `—` | ON | CASE-STUDY-LED DISCOVERY: 採択事例 を seed に「似た事例 + その制度」を返す。 |
| `smb_starter_pack` | jpintel.db | — | `—` | ON | ONE-SHOT DISCOVERY: 1 call で SMB 経営者が「今日何できる?」を返す。 |
| `subsidy_combo_finder` | jpintel.db | — | `—` | ON | ONE-SHOT COMBO: 補助金+融資+税制 の 非衝突組合せ TOP N を 1 call で。 |
| `subsidy_roadmap_3yr` | jpintel.db | — | `—` | ON | ONE-SHOT 3-YEAR ROADMAP: industry × prefecture × size × purpose で |
| `trace_program_to_law` | jpintel.db | — | `—` | ON | TRACE-PROGRAM-LAW: given a program unified_id, return its 根拠法 / 関連法 chain — joins `program_law_refs` → `laws`. Each entry reports ref_kind (authority / eligibility / exclusion / reference / penalty), article_citation, law title, and (when f |
| `upcoming_deadlines` | jpintel.db | — | `—` | ON | DISCOVER-CALENDAR: list 補助金 / 助成金 / 融資 / 税制 programs whose application deadline (application_window.end_date) falls within the next N days. |

## 監査ワークペーパー / 会計士 fan-out (3)

Backed by `jpintel.db` (+ NTA corpus on autonomath.db for `resolve_citation_chain`). Carry 公認会計士法 §47条の2 + 税理士法 §52 disclaimers. Pricing: ¥3 × N profiles batch + ¥30 export fee for `compose_audit_workpaper`.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `audit_batch_evaluate` | jpintel.db | §47条の2, §52 | `—` | ON | Batch evaluation across an audit firm's client population. ¥3 × N profiles billing (K=10 fan-out → 5,000×100=50,000 units / ¥150,000). Returns per-profile results + anomalies (population-deviation flags) + kaikei_fields (調書記載要否 / 重要性閾値 / 監査 |
| `compose_audit_workpaper` | jpintel.db | §47条の2, §52 | `—` | ON | 監査ワークペーパー (PDF/CSV/MD/DOCX) を 1 件の client + ruleset セットに対して生成する。corpus_snapshot_id + sha256 + §47条の2 wording を全 surface に埋め込む。WeasyPrint レンダ → data/workpapers/ に cache、再 pull は無料。¥3 × N + ¥30 export fee。§47条の2 + §52 sensitive — 監査意見の代替ではない。 |
| `resolve_citation_chain` | jpintel + autonomath | §47条の2, §52 | `—` | ON | tax_ruleset → 法令 article → 通達 → 質疑応答 → 文書回答 の citation chain を auto-resolve する。NTA primary source corpus (autonomath.db migration 103: 通達 3,221 / 質疑応答 286 / 文書回答 278) + jpintel.db laws + court_decisions を walk。出力 tree は監査調書 索引にそのまま貼付可。¥3 /  |

## autonomath.db generic (25)

Backed by `autonomath.db` (8.29 GB unified primary DB). Includes the legacy V1 surface (search_tax_incentives / search_certifications / list_open_programs / enum_values_am / search_by_law / active_programs_at / search_acceptance_stats_am + related_programs gated-on), the 5 per-domain wrappers (gx / loans / enforcement / mutual / law_article), 1 tax_rule, 1 sunset, plus standalone tools (graph_traverse / unified_lifecycle_calendar / program_lifecycle / program_abstract_structured / prerequisite_chain / rule_engine_check / get_source_manifest / get_evidence_packet / check_funding_stack_am / verify_citations).

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `active_programs_at` | autonomath.db | — | `—` | ON | 任意の ISO 日付 pivot で **effective window (施行〜廃止) が及ぶ** 制度 + 税制を列挙する — `list_open_programs` が 募集窓口 を、本 tool は 制度の **存在期間** を見る (歴史的 "XX年時点で有効だった制度" の効力期間 lookup 用途). |
| `check_enforcement_am` | autonomath.db | — | `—` | ON | Returns 行政処分 records from am_enforcement_detail for a 法人番号 or 企業名, including currently_excluded flag (active 排除期間 at as_of_date) and 5-year history. Coverage is the 1,185-row corpus only — absence of records does NOT prove a clean record. V |
| `check_funding_stack_am` | autonomath.db | — | `AUTONOMATH_FUNDING_STACK_ENABLED` | ON | Returns a deterministic 制度併用可否 verdict (compatible / incompatible / requires_review / unknown) per pair + aggregate, by joining am_compat_matrix with exclusion_rules. NO LLM. Each response carries `_disclaimer`. Verify primary source. |
| `enum_values_am` | autonomath.db | — | `—` | ON | Returns the canonical enum values + row counts for filter arguments used by other tools (target_type / authority_level / funding_purpose / prefecture / program_kind 等), so callers can avoid typos that cause 0-hit searches. |
| `get_am_tax_rule` | autonomath.db | — | `—` | ON | Returns structured tax rule rows for a 税制措置 (rate / cap / 根拠条文 / 適用期限) from am_tax_rule. One measure can return multiple rows when both 特別償却 and 税額控除 exist. Output is search-derived; verify primary source (source_url) for filing decisions. |
| `get_evidence_packet` | autonomath.db | — | `AUTONOMATH_EVIDENCE_PACKET_ENABLED` | ON | Returns a single Evidence Packet envelope: primary metadata + per-fact provenance + compat-matrix rule verdicts (program only). NO LLM. 1 ¥3 unit per call. SAME composer as REST /v1/evidence/packets/{subject_kind}/{subject_id}. |
| `get_law_article_am` | autonomath.db | — | `—` | ON | Returns the article text from am_law_article for a (law name, article number) pair. Accepts natural notation like '租税特別措置法 第41条の19' and normalizes to canonical form. Includes last_amended + source_url. Output is search-derived; verify prima |
| `get_source_manifest` | autonomath.db | — | `—` | ON | Returns the full source manifest for one program: per-fact provenance (where source_id is populated) + entity-level rollup (am_entity_source) + license set + publisher count + first/last fetched_at. Honest sparse signal — empty fact_provena |
| `graph_traverse` | autonomath.db | — | `AUTONOMATH_GRAPH_TRAVERSE_ENABLED` | ON | O7 — Returns paths from a 1-3 hop heterogeneous BFS over am_relation (24,004 edges / 15 relation types). Pure SQL traversal (no LLM). Output is graph-derived; edges with confidence < 0.5 (graph_rescue origin) are noisy — verify primary sour |
| `list_open_programs` | autonomath.db | — | `—` | ON | Returns programs whose application window covers the given date (default=今日 JST), sorted by days-until-close ascending. Output is search-derived; verify primary source (source_url) for the actual deadline before submission. |
| `list_tax_sunset_alerts` | autonomath.db | — | `—` | ON | Returns tax measures whose effective_until falls within the next N days, plus 大綱 cliff date buckets. Output is search-derived from am_tax_rule (57 rows with effective_until); verify primary source (source_url) for sunset confirmation. |
| `prerequisite_chain` | autonomath.db | — | `AUTONOMATH_PREREQUISITE_CHAIN_ENABLED` | ON | Returns curated prerequisite chain for a program (認定 / 計画 / 登録) with preparation_time_days + preparation_cost_yen. Coverage is partial (135/8,203 programs = 1.6%); empty chain ≠ no prerequisites — verify primary source (公募要領 / obtain_url). |
| `program_abstract_structured` | autonomath.db | — | `—` | ON | R7 — Returns audience-targeted, closed-vocab Japanese abstract for a single program. Translation is the customer LLM's job; we never call Anthropic API. official_name_ja + legal_id must stay verbatim (i18n_hints.official_name_must_keep_ja=t |
| `program_lifecycle` | autonomath.db | — | `AUTONOMATH_LIFECYCLE_ENABLED` | ON | Returns schema-level snapshot of program status (abolished / superseded / sunset_imminent / sunset_scheduled / amended / active / not_yet / unknown). Most rows lack historical diffs (eligibility_hash chain partial); use effective_from for f |
| `related_programs` | autonomath.db | — | `AUTONOMATH_GRAPH_ENABLED` | ON | Returns related programs along 6 relation axes (prerequisite / compatible / incompatible / successor / predecessor / similar), 1-2 hops from a seed program / tax / cert. Walks am_relation (18,489 edges / ~13K nodes). Output is search-derive |
| `rule_engine_check` | autonomath.db | — | `AUTONOMATH_RULE_ENGINE_ENABLED` | ON | Returns rule evaluation result + applicable law citations across 6 corpora (49,247 rows): exclusion + compat_matrix (48,815 rows, of which 4,849 are 'unknown' status) + combo + subsidy + tax + validation. Output is search-derived; verify pr |
| `search_acceptance_stats_am` | autonomath.db | — | `—` | ON | Returns adoption statistics (応募件数 / 採択件数 / 採択率 / 予算額) per (program × fiscal_year × round). Aggregated from METI / MAFF published sources. Output is search-derived; verify primary source for figures cited in business decisions. |
| `search_by_law` | autonomath.db | — | `—` | ON | Returns programs / tax_measures / certifications / law rows linked to a given law name (canonical or colloquial). Uses `am_alias` + `am_law.short_name` for alias resolution. Output is search-derived; verify primary source (source_url) for l |
| `search_certifications` | autonomath.db | — | `—` | ON | DISCOVER (Certifications): Search 66 Japanese certification programs (経営革新等支援機関認定 / 経営力向上計画 / 中小企業等経営強化法 etc.). |
| `search_gx_programs_am` | autonomath.db | — | `—` | ON | DISCOVER (GX/Green): Search Green Transformation subsidies — emissions reduction, renewable energy, EV adoption, ZEB/ZEH (net-zero buildings), carbon credits. Returns curated programs with eligibility summaries. |
| `search_loans_am` | autonomath.db | — | `—` | ON | Returns matching loan products from am_loan_product, filtered by 3 independent axes (担保 / 個人保証 / 第三者保証). Spans 公庫 / 自治体制度融資 / 商工中金. Output is search-derived; verify primary source (source_url) for the actual lending terms. |
| `search_mutual_plans_am` | autonomath.db | — | `—` | ON | Returns matching 共済 / 年金 / 労災 records (小規模企業共済 / 倒産防止共済 / iDeCo+ / DB / DC / 労災特別加入 等) from am_insurance_mutual, filtered by plan_kind × premium range × tax_deduction_type × provider. Output is search-derived; verify primary source (source_ |
| `search_tax_incentives` | autonomath.db | — | `—` | ON | DISCOVER (Tax): Search 35 Japanese tax incentives — corporate deductions (減価償却/試験研究費), tax credits (雇用/エネルギー/DX), special measures (租税特別措置). |
| `unified_lifecycle_calendar` | autonomath.db | — | `AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED` | ON | Returns merged calendar of tax sunset + program sunset + application close + law cliff events. Output is search-derived from public-source data; verify primary source (source_url) for business decisions. |
| `verify_citations` | autonomath.db | — | `AUTONOMATH_CITATIONS_ENABLED` | ON | Substantiate verification_status="verified" by deterministic substring + Japanese numeric-form match against the cited primary source. Pure no-LLM. Per-citation verdict ∈ {verified, inferred, unknown}; SHA256 checksum returned for re-checks |

## V4 universal (4)

Backed by `autonomath.db`. Landed via migrations 046–049 (V4 absorption 2026-04-25). Generic over every entity_id / fact_id in the EAV schema.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `get_annotations` | autonomath.db | — | `—` | ON | Returns annotation rows from am_entity_annotation for a given entity_id (examiner feedback / quality score / validation failure / ML inference). Default visibility='public' returns 0 rows for currently-ingested data (16,474 rows are all 'in |
| `get_provenance` | autonomath.db | — | `—` | ON | Returns source attribution for the entity at point-in-time of last fetch — all rows from am_entity_source × am_source JOIN with license_summary. include_facts=True adds per-fact provenance via am_entity_facts.source_id where set. |
| `get_provenance_for_fact` | autonomath.db | — | `—` | ON | Returns source attribution for a single fact_id at point-in-time of last fetch. Resolves am_entity_facts.source_id → am_source. When source_id is NULL (legacy fact pre-2026-04-25), falls back to entity-level am_entity_source candidate list. |
| `validate` | autonomath.db | — | `—` | ON | applicant_data を am_validation_rule の active 述語で評価し、 |

## Phase A absorption (5)

Backed by `autonomath.db` + `data/autonomath_static/` static bundle. 4 static-resource readers + `deep_health_am` (10-check aggregate over both DBs). The Phase A landing also shipped 2 36協定 tools — those are catalogued separately below as `kyotei36` since they are default-OFF.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `deep_health_am` | jpintel + autonomath | — | `—` | ON | Aggregate health: 10 checks across both DBs + static bundle. |
| `get_example_profile_am` | autonomath.db | — | `—` | ON | Return one canonical client profile JSON as a complete-payload example. |
| `get_static_resource_am` | autonomath.db | — | `—` | ON | Load one curated taxonomy / lookup file. Returns full JSON + license. |
| `list_example_profiles_am` | autonomath.db | — | `—` | ON | Manifest of canonical client-intake example payloads (PII-clean). |
| `list_static_resources_am` | autonomath.db | — | `—` | ON | Manifest of curated AutonoMath taxonomies (制度 / 用語 / 助成区分 / 義務 etc.). |

## NTA primary-source corpus (4)

Backed by `autonomath.db` (migration 103 — nta_saiketsu / nta_tsutatsu_index / nta_shitsugi / nta_bunsho_kaitou). Sources: 国税不服審判所 (kfs.go.jp) + 国税庁 (nta.go.jp). Every tool emits a `_disclaimer` (税理士法 §52) declaring the output retrieval-only.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `cite_tsutatsu` | autonomath.db | §52, 税理士法 | `AUTONOMATH_NTA_CORPUS_ENABLED` | ON | Lookup a 通達 article by code. Returns title + body excerpt + source_url. 出力は citation のみで税務助言 (税理士法 §52) ではない。 |
| `find_bunsho_kaitou` | autonomath.db | §52, 税理士法 | `AUTONOMATH_NTA_CORPUS_ENABLED` | ON | 国税庁 文書回答事例 (事前照会回答) を全文検索。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。 |
| `find_saiketsu` | autonomath.db | §52, 税理士法 | `AUTONOMATH_NTA_CORPUS_ENABLED` | ON | 国税不服審判所 (KFS) 公表裁決事例 を全文検索 (FTS5 trigram on nta_saiketsu)。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。 |
| `find_shitsugi` | autonomath.db | §52, 税理士法 | `AUTONOMATH_NTA_CORPUS_ENABLED` | ON | 国税庁 質疑応答事例 を全文検索 (FTS5 trigram on nta_shitsugi)。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。 |

## Wave 21 composition (5)

Backed by `autonomath.db`. Multi-step orchestration that joins prerequisite_chain → rule_engine_check → exclusion_rules → am_compat_matrix per program; outputs reasoning_steps + cite chain. 税理士法 §52 / 行政書士法 §1 disclaimer-bearing. AUTONOMATH_COMPOSITION_ENABLED gate (default ON).

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `apply_eligibility_chain_am` | autonomath.db | §52 | `AUTONOMATH_COMPOSITION_ENABLED` | ON | Multi-step eligibility orchestration over prerequisite_chain → rule_engine_check → exclusion_rules → am_compat_matrix per program. Returns per-program verdict (eligible / partial / ineligible) + reasoning_steps + cite chain. Heuristic; veri |
| `find_complementary_programs_am` | autonomath.db | §52 | `AUTONOMATH_COMPOSITION_ENABLED` | ON | Seed program → am_compat_matrix compatible edges → portfolio with combined_ceiling_yen + conflicts. authoritative_share_pct surfaced. inferred_only=true edges are heuristic. §52 sensitive — verify 経費重複 + 適正化法 17 条 before stacking. |
| `program_active_periods_am` | autonomath.db | — | `AUTONOMATH_COMPOSITION_ENABLED` | ON | am_application_round (1,256 rows) per-program rounds + days_to_close + sunset_warning. Returns open_count / upcoming_count / closed_count + soonest_close_date. sunset_warning fires when only closed rounds exist OR close < 14 days away. |
| `simulate_application_am` | autonomath.db | §1, §52 | `AUTONOMATH_COMPOSITION_ENABLED` | ON | Pure-SQL mock walkthrough: am_application_steps + am_prerequisite_bundle + am_application_round + am_law_article. Returns document_checklist + certifications + est_review_days + completeness_score. NO LLM. §52 sensitive — not a substitute f |
| `track_amendment_lineage_am` | autonomath.db | — | `AUTONOMATH_COMPOSITION_ENABLED` | ON | am_amendment_snapshot time-series for a target (14,596 rows; only 140 carry effective_from). Returns timeline + strict_count (with effective_from) + hash_only_count + warnings. eligibility_hash is uniform sha256-of-empty on 82.3% — time-ser |

## Wave 22 composition (5)

Backed by `autonomath.db` (+ migration 104 `dd_question_templates` = 60 seeded DD questions). Compounds Wave 21 with DD deck / 決算 briefing / renewal forecast / jurisdiction cross-check / kit assembly. NO LLM. AUTONOMATH_WAVE22_ENABLED gate (default ON).

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `bundle_application_kit` | autonomath.db | §1 | `AUTONOMATH_WAVE22_ENABLED` | ON | Complete downloadable kit assembly: program metadata + cover letter scaffold + 必要書類 checklist + similar 採択例 list. Pure file assembly, NO LLM, NO DOCX generation. §1 sensitive — 申請書面作成は行政書士の独占業務、当社は scaffold + 一次 URL のみ提供. |
| `cross_check_jurisdiction` | autonomath.db | §52, §72 | `AUTONOMATH_WAVE22_ENABLED` | ON | Registered (法務局) vs invoice (NTA) vs operational (交付) jurisdiction breakdown. Detects 不一致 for 税理士 onboarding — flags prefecture mismatches between houjin_master / invoice_registrants / adoption_records. §52/§72 sensitive — heuristic detecti |
| `forecast_program_renewal` | autonomath.db | — | `AUTONOMATH_WAVE22_ENABLED` | ON | Probability + window of program renewal in next FY based on historical am_application_round cadence + am_amendment_snapshot density. 4-signal weighted average (frequency / recency / pipeline / snapshot). NOT sensitive — statistical, not adv |
| `match_due_diligence_questions` | autonomath.db | §52, §72 | `AUTONOMATH_WAVE22_ENABLED` | ON | DD question deck (30-60 items) tailored to industry × program portfolio × 与信 risk by joining dd_question_templates (60 rows, migration 102) with houjin / adoption / enforcement / invoice corpora. Pure pattern-match, NO LLM. §52/§72 sensitiv |
| `prepare_kessan_briefing` | autonomath.db | §52 | `AUTONOMATH_WAVE22_ENABLED` | ON | 月次 / 四半期 summary of program-eligibility changes since last 決算 by joining am_amendment_diff + jpi_tax_rulesets within the FY window. Compounds saved_searches digest cadence. §52 sensitive — 決算 territory, briefing only, not 税務代理. |

## Wave 23 industry packs (3)

Backed by `autonomath.db`. JSIC-keyed cohort packs that bundle top 10 programs + up to 5 国税不服審判所 裁決事例 + up to 3 通達 references in 1 ¥3/req call. Sensitive: 税理士法 §52 + 公認会計士法 §47条の2. AUTONOMATH_INDUSTRY_PACKS_ENABLED gate (default ON).

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `pack_construction` | autonomath.db | §47条の2, §52 | `AUTONOMATH_INDUSTRY_PACKS_ENABLED` | ON | 建設業 (JSIC D) cohort pack: top 10 programs (建設・住宅・耐震・改修 fence) + up to 5 国税不服審判所 裁決事例 (法人税・消費税) + up to 3 通達 references (法基通・消基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言. Compounds via _next_calls. |
| `pack_manufacturing` | autonomath.db | §47条の2, §52 | `AUTONOMATH_INDUSTRY_PACKS_ENABLED` | ON | 製造業 (JSIC E) cohort pack: top 10 programs (ものづくり・設備投資・省エネ・GX・事業再構築 fence) + up to 5 国税不服審判所 裁決事例 (法人税・所得税) + up to 3 通達 references (法基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言. |
| `pack_real_estate` | autonomath.db | §47条の2, §52 | `AUTONOMATH_INDUSTRY_PACKS_ENABLED` | ON | 不動産業 (JSIC K) cohort pack: top 10 programs (不動産・空き家・住宅・賃貸 fence) + up to 5 国税不服審判所 裁決事例 (所得税・相続税・法人税) + up to 3 通達 references (所基通・相基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言. |

## Broken tools (gated OFF — 3)

**Default OFF** until fix. Smoke test 2026-04-29 confirmed each returns `subsystem_unavailable` / `no such column` on every invocation. Source code retained so tests stay importable; only `@mcp.tool` registration is suppressed.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `intent_of` | autonomath.db | — | `AUTONOMATH_REASONING_ENABLED` | **OFF** | Returns classification of a JP natural-language query into one of 10 intent clusters (i01_filter / i02_deadline / i03_successor / i04_tax_sunset / i05_cert_howto / i06_compat / i07_adoption / i08_peer_compare / i09_succession / i10_wage_dx_ |
| `query_at_snapshot` | autonomath.db | — | `AUTONOMATH_SNAPSHOT_ENABLED` | **OFF** | R8 — pin programs query to historical dataset state. Returns rows + 3-axis reference (source_url + fetched_at + valid_from) so the caller can re-run the same query against the same snapshot. Output is search-derived; legal admissibility req |
| `reason_answer` | autonomath.db | — | `AUTONOMATH_REASONING_ENABLED` | **OFF** | Runs intent classification + slot extraction + DB bind + skeleton render in one call. Returns an answer_skeleton with verifiable values (URL / 日付 / 金額 / 制度名 / 先行制度) bound from DB, plus a missing_data list of slots that could not be filled.  |

## 36協定 template (gated OFF — 2)

**Default OFF** until legal review (社労士 supervision arrangement + customer-facing disclaimer alignment). 36協定 (時間外労働協定届) is regulated by 労基法 §36 + 社労士法; mis-rendered output exposes the operator to 社労士法 liability. Even when enabled, every render response carries a `_disclaimer` declaring the output a draft requiring 社労士 confirmation.

| Tool | DB | Sensitive | Gate | Default | Description |
|---|---|---|---|---|---|
| `get_36_kyotei_metadata_am` | autonomath.db | 労基法, 社労士法 | `AUTONOMATH_36_KYOTEI_ENABLED` | **OFF** | ⚠️ DRAFT template metadata — render output MUST be reviewed by 社労士 before submission. 労基法 §36 + 社労士法 regulated. |
| `render_36_kyotei_am` | autonomath.db | 労基法, 社労士法 | `AUTONOMATH_36_KYOTEI_ENABLED` | **OFF** | ⚠️ DRAFT ONLY: 36協定 template — output MUST be reviewed by 社労士 before submission. 労基法 §36 + 社労士法 regulated. |

## Default-on / default-off matrix

### Default ON (93 tools)

All `@mcp.tool` registrations are default-ON unless an explicit env flag suppresses them. The on-by-default ENV gates below give operators a one-flag rollback per subsystem if a regression surfaces:

| Gate | Default | Tool count |
|---|---|---|
| `AUTONOMATH_ENABLED` | `1` | 50 (all autonomath_tools) |
| `AUTONOMATH_GRAPH_ENABLED` | `1` | 1 (related_programs) |
| `AUTONOMATH_GRAPH_TRAVERSE_ENABLED` | `1` | 1 (graph_traverse) |
| `AUTONOMATH_LIFECYCLE_ENABLED` | `1` | 1 (program_lifecycle) |
| `AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED` | `1` | 1 (unified_lifecycle_calendar) |
| `AUTONOMATH_PREREQUISITE_CHAIN_ENABLED` | `1` | 1 (prerequisite_chain) |
| `AUTONOMATH_RULE_ENGINE_ENABLED` | `1` | 1 (rule_engine_check) |
| `AUTONOMATH_NTA_CORPUS_ENABLED` | `1` | 4 (find_saiketsu, cite_tsutatsu, find_shitsugi, find_bunsho_kaitou) |
| `AUTONOMATH_COMPOSITION_ENABLED` | `1` | 5 (Wave 21) |
| `AUTONOMATH_WAVE22_ENABLED` | `1` | 5 (Wave 22) |
| `AUTONOMATH_INDUSTRY_PACKS_ENABLED` | `1` | 3 (Wave 23) |
| `AUTONOMATH_CITATIONS_ENABLED` | `1` | 1 (verify_citations) |
| `AUTONOMATH_EVIDENCE_PACKET_ENABLED` | `1` | 1 (get_evidence_packet) |
| `AUTONOMATH_FUNDING_STACK_ENABLED` | `1` | 1 (check_funding_stack_am) |

Setting any of these to `0` / `false` removes the corresponding tools from `tools/list` at server-start time without touching call sites.

### Default OFF (5 tools)

Five tools are gated OFF by default. Flipping each gate to `1` exposes the tool but does **not** fix the underlying defect — operator must verify before flipping.

| Tool | Gate | Reason | Fix prerequisite |
|---|---|---|---|
| `query_at_snapshot` | `AUTONOMATH_SNAPSHOT_ENABLED` | Migration 067 referenced but never written; every call → `no such column: valid_from` | Land migration 067 adding `valid_from` / `valid_until` to programs / laws / tax_rulesets |
| `intent_of` | `AUTONOMATH_REASONING_ENABLED` | `_reasoning_import()` ModuleNotFoundError — `reasoning` package missing from install | Bundle `reasoning` package into install or place on resolvable sys.path |
| `reason_answer` | `AUTONOMATH_REASONING_ENABLED` | Same root cause as `intent_of` (shared `_reasoning_import()`) | Same as intent_of |
| `render_36_kyotei_am` | `AUTONOMATH_36_KYOTEI_ENABLED` | 労基法 §36 + 社労士法 regulated; mis-render → 社労士法 liability + brand damage | 社労士 supervision arrangement + customer-facing disclaimer alignment + legal review (see `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md`) |
| `get_36_kyotei_metadata_am` | `AUTONOMATH_36_KYOTEI_ENABLED` | Same gate as `render_36_kyotei_am` (paired surface) | Same as render_36_kyotei_am |

## Verification

```bash
# Authoritative runtime count (boots MCP, lists tools, prints len):
.venv/bin/python -c "from jpintel_mcp.mcp.server import mcp; import asyncio; print(len(asyncio.run(mcp.list_tools())))"
# Expect: 93 (with AUTONOMATH_ENABLED=1, all opt-out gates default, broken/36協定 OFF)
```

Static grep used to build this catalog:

```bash
grep -nE '^@mcp\.tool|mcp\.tool\(.*\)\([a-z_]+\)' src/jpintel_mcp/mcp/server.py src/jpintel_mcp/mcp/autonomath_tools/*.py
```
