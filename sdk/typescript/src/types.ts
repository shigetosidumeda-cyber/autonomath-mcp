// Types for jpcite REST API responses.
// Hand-written to mirror server Pydantic models. Will switch to OpenAPI codegen
// post-launch (see sdk/README.md).

// ────────────────────────────────────────────────────────────────────
// Shared
// ────────────────────────────────────────────────────────────────────

export type Tier = "S" | "A" | "B" | "C" | "X";

export interface ClientOptions {
  /** API key issued from https://jpcite.com/dashboard. Optional; anonymous gets 3 req/day per IP. */
  apiKey?: string;
  /** Override base URL (self-host / staging). Default: https://api.jpcite.com */
  baseUrl?: string;
  /** Per-request timeout in ms. Default 30000. */
  timeoutMs?: number;
  /** Retry budget for 429/5xx + transport. Default 3. */
  maxRetries?: number;
  /** Override fetch (test injection / undici). Default: global fetch. */
  fetch?: typeof fetch;
  /** Optional User-Agent suffix. */
  userAgentSuffix?: string;
}

export interface SearchParams {
  q?: string;
  tier?: Tier[];
  prefecture?: string;
  authority_level?: string;
  funding_purpose?: string[];
  target_type?: string[];
  amount_min?: number;
  amount_max?: number;
  include_excluded?: boolean;
  limit?: number;
  offset?: number;
}

// ────────────────────────────────────────────────────────────────────
// Programs (補助金 / 助成金 / 認定制度 など)
// ────────────────────────────────────────────────────────────────────

export interface Program {
  unified_id: string;
  primary_name: string;
  aliases: string[];
  authority_level: string | null;
  authority_name: string | null;
  prefecture: string | null;
  municipality: string | null;
  program_kind: string | null;
  official_url: string | null;
  amount_max_man_yen: number | null;
  amount_min_man_yen: number | null;
  subsidy_rate: number | null;
  trust_level: string | null;
  tier: Tier | null;
  coverage_score: number | null;
  gap_to_tier_s: string[];
  a_to_j_coverage: Record<string, unknown>;
  excluded: boolean;
  exclusion_reason: string | null;
  crop_categories: string[];
  equipment_category: string | null;
  target_types: string[];
  funding_purpose: string[];
  amount_band: string | null;
  application_window: Record<string, unknown> | null;
}

export interface ProgramDetail extends Program {
  enriched: Record<string, unknown> | null;
  source_mentions: Record<string, unknown>[];
}

export interface SearchResponse {
  total: number;
  limit: number;
  offset: number;
  results: Program[];
}

// ────────────────────────────────────────────────────────────────────
// Loans (日本政策金融公庫 / 信用保証協会 / 商工中金 etc.)
// ────────────────────────────────────────────────────────────────────

export interface Loan {
  loan_id: string;
  loan_name: string;
  authority: string | null;
  authority_url: string | null;
  target_business_types: string[];
  loan_purpose: string[];
  amount_max_man_yen: number | null;
  amount_min_man_yen: number | null;
  interest_rate_min: number | null;
  interest_rate_max: number | null;
  loan_term_months_max: number | null;
  /** 担保 (collateral) - "required" / "negotiable" / "not_required" */
  collateral: string | null;
  /** 個人保証人 (personal guarantor) */
  personal_guarantor: string | null;
  /** 第三者保証人 (third-party guarantor) */
  third_party_guarantor: string | null;
  source_url: string | null;
  source_fetched_at: string | null;
}

export interface LoanSearchParams {
  q?: string;
  authority?: string;
  loan_purpose?: string[];
  amount_min?: number;
  amount_max?: number;
  collateral?: string;
  personal_guarantor?: string;
  limit?: number;
  offset?: number;
}

export interface LoanSearchResponse {
  total: number;
  limit: number;
  offset: number;
  results: Loan[];
}

// ────────────────────────────────────────────────────────────────────
// 行政処分 (Enforcement actions)
// ────────────────────────────────────────────────────────────────────

export interface Enforcement {
  case_id: string;
  authority: string | null;
  case_kind: string | null;
  party_name: string | null;
  decided_at: string | null;
  summary: string | null;
  source_url: string | null;
  source_fetched_at: string | null;
  cited_law_articles: string[];
}

export interface EnforcementSearchParams {
  q?: string;
  authority?: string;
  case_kind?: string;
  decided_from?: string;
  decided_to?: string;
  limit?: number;
  offset?: number;
}

export interface EnforcementSearchResponse {
  total: number;
  limit: number;
  offset: number;
  results: Enforcement[];
}

// ────────────────────────────────────────────────────────────────────
// 税制 (Tax incentives / rulesets)
// ────────────────────────────────────────────────────────────────────

export interface TaxRule {
  unified_id: string;
  rule_name: string;
  rule_kind: string | null;
  authority: string | null;
  effective_from: string | null;
  effective_to: string | null;
  /** Sunset alert date (廃止 / 期限切れ). */
  sunset_date: string | null;
  applicable_to: string[];
  amount_basis: string | null;
  rate: number | null;
  source_url: string | null;
  source_fetched_at: string | null;
  description: string | null;
}

export interface TaxIncentiveSearchParams {
  q?: string;
  rule_kind?: string;
  authority?: string;
  effective_on?: string;
  limit?: number;
  offset?: number;
}

export interface TaxIncentiveSearchResponse {
  total: number;
  limit: number;
  offset: number;
  results: TaxRule[];
}

// ────────────────────────────────────────────────────────────────────
// 法令 (Laws / e-Gov CC-BY)
// ────────────────────────────────────────────────────────────────────

export interface Law {
  unified_id: string;
  law_name: string;
  law_number: string | null;
  authority: string | null;
  promulgated_at: string | null;
  effective_from: string | null;
  source_url: string | null;
  source_fetched_at: string | null;
}

export interface LawArticle {
  law_unified_id: string;
  article_number: string;
  article_title: string | null;
  body: string;
}

// ────────────────────────────────────────────────────────────────────
// 排他ルール (Exclusion rules)
// ────────────────────────────────────────────────────────────────────

export interface ExclusionRule {
  rule_id: string;
  kind: string;
  severity: string | null;
  program_a: string | null;
  program_b: string | null;
  program_b_group: string[];
  description: string | null;
  source_notes: string | null;
  source_urls: string[];
  extra: Record<string, unknown>;
}

export interface ExclusionHit {
  rule_id: string;
  kind: string;
  severity: string | null;
  programs_involved: string[];
  description: string | null;
  source_urls: string[];
}

export interface ExclusionCheckResponse {
  program_ids: string[];
  hits: ExclusionHit[];
  checked_rules: number;
}

// ────────────────────────────────────────────────────────────────────
// Evidence Packet / composite intelligence
// ────────────────────────────────────────────────────────────────────

export type EvidencePacketSubjectKind = "program" | "houjin";
export type EvidencePacketProfile =
  | "full"
  | "brief"
  | "verified_only"
  | "changes_only";
export type EvidencePacketSourceTokensBasis =
  | "unknown"
  | "pdf_pages"
  | "token_count";

export interface EvidencePacketOptions {
  include_facts?: boolean;
  include_rules?: boolean;
  include_compression?: boolean;
  fields?: string;
  packet_profile?: EvidencePacketProfile;
  input_token_price_jpy_per_1m?: number | null;
  source_tokens_basis?: EvidencePacketSourceTokensBasis;
  source_pdf_pages?: number | null;
  source_token_count?: number | null;
}

export interface EvidencePacketQueryBody extends EvidencePacketOptions {
  query_text: string;
  filters?: Record<string, unknown> | null;
  limit?: number;
}

export interface EvidencePacketCompression {
  packet_tokens_estimate: number;
  source_tokens_estimate?: number | null;
  avoided_tokens_estimate?: number | null;
  compression_ratio?: number | null;
  input_context_reduction_rate?: number | null;
  estimate_method?: string | null;
  estimate_disclaimer?: string | null;
  source_tokens_basis: EvidencePacketSourceTokensBasis;
  source_tokens_input_source?: string | null;
  source_pdf_pages?: number | null;
  source_token_count?: number | null;
  estimate_scope?: string;
  savings_claim?: string;
  provider_billing_not_guaranteed?: boolean;
  cost_savings_estimate?: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface EvidencePacketRecord {
  entity_id: string;
  primary_name?: string | null;
  record_kind?: string | null;
  source_url?: string | null;
  source_fetched_at?: string | null;
  source_health?: Record<string, unknown> | null;
  fact_provenance_coverage_pct?: number | null;
  authority_name?: string | null;
  prefecture?: string | null;
  tier?: string | null;
  aliases?: Array<Record<string, unknown>> | null;
  pdf_fact_refs?: Array<Record<string, unknown>> | null;
  facts?: Array<Record<string, unknown>> | null;
  rules?: Array<Record<string, unknown>> | null;
  short_summary?: Record<string, unknown> | null;
  precomputed?: Record<string, unknown> | null;
  recent_changes?: Array<Record<string, unknown>> | null;
  [k: string]: unknown;
}

export interface EvidencePacketQuality {
  freshness_bucket?: string | null;
  coverage_score?: number | null;
  known_gaps: string[];
  human_review_required?: boolean | null;
  [k: string]: unknown;
}

export interface EvidencePacketVerification {
  replay_endpoint?: string | null;
  provenance_endpoint?: string | null;
  freshness_endpoint?: string | null;
  [k: string]: unknown;
}

export interface EvidencePacketEvidenceValue {
  records_returned: number;
  source_linked_records: number;
  precomputed_records: number;
  pdf_fact_refs: number;
  known_gap_count: number;
  fact_provenance_coverage_pct_avg?: number | null;
  web_search_performed_by_jpcite?: boolean;
  request_time_llm_call_performed?: boolean;
  [k: string]: unknown;
}

export interface EvidencePacketInsightItem {
  signal: string;
  message_ja: string;
  source_fields: string[];
  severity?: string | null;
  [k: string]: unknown;
}

export interface EvidencePacketDecisionInsights {
  schema_version: string;
  generated_from: string[];
  why_review: EvidencePacketInsightItem[];
  next_checks: EvidencePacketInsightItem[];
  evidence_gaps: EvidencePacketInsightItem[];
  [k: string]: unknown;
}

export interface EvidencePacketEnvelope {
  packet_id: string;
  generated_at: string;
  api_version: string;
  corpus_snapshot_id: string;
  query: Record<string, unknown>;
  answer_not_included: boolean;
  records: EvidencePacketRecord[];
  quality: EvidencePacketQuality;
  verification: EvidencePacketVerification;
  compression?: EvidencePacketCompression | null;
  evidence_value?: EvidencePacketEvidenceValue | null;
  agent_recommendation?: Record<string, unknown> | null;
  decision_insights?: EvidencePacketDecisionInsights | null;
  [k: string]: unknown;
}

export interface IntelEnvelope {
  _disclaimer?: string;
  _billing_unit?: number;
  corpus_snapshot_id?: string;
  [k: string]: unknown;
}

export interface IntelMatchRequest {
  industry_jsic_major: string;
  prefecture_code: string;
  capital_jpy?: number | null;
  employee_count?: number | null;
  keyword?: string | null;
  limit?: number;
  [k: string]: unknown;
}

export interface IntelQuestion {
  id?: string | null;
  field?: string | null;
  question?: string | null;
  reason?: string | null;
  kind?: string | null;
  impact?: string | null;
  blocking?: boolean | null;
  [k: string]: unknown;
}

export interface IntelEligibilityGap {
  field?: string | null;
  gap_type?: string | null;
  reason?: string | null;
  required_by?: string | null;
  impact?: string | null;
  blocking?: boolean | null;
  expected?: unknown;
  [k: string]: unknown;
}

export interface IntelDocumentReadiness {
  required_document_count: number;
  forms_with_url_count: number;
  signature_required_count: number;
  signature_unknown_count: number;
  needs_user_confirmation: boolean;
  [k: string]: unknown;
}

export interface IntelMatchedProgram {
  program_id?: string | null;
  primary_name?: string | null;
  tier?: string | null;
  match_score?: number | null;
  score_components: Record<string, unknown>;
  authority_name?: string | null;
  prefecture?: string | null;
  program_kind?: string | null;
  source_url?: string | null;
  eligibility_predicate: Record<string, unknown>;
  required_documents: Array<Record<string, unknown>>;
  next_questions: IntelQuestion[];
  eligibility_gaps: IntelEligibilityGap[];
  document_readiness: IntelDocumentReadiness;
  similar_adopted_companies: Array<Record<string, unknown>>;
  applicable_laws: Array<Record<string, unknown>>;
  applicable_tsutatsu: Array<Record<string, unknown>>;
  audit_proof?: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface IntelMatchResponse extends IntelEnvelope {
  matched_programs: IntelMatchedProgram[];
  total_candidates: number;
  applied_filters: string[];
}

export interface IntelDecisionSupportItem {
  signal?: string | null;
  insight_id?: string | null;
  action?: string | null;
  section?: string | null;
  message?: string | null;
  message_ja?: string | null;
  basis?: string[];
  source_fields?: string[];
  metrics?: Record<string, unknown>;
  priority?: string | null;
  reason?: string | null;
  [k: string]: unknown;
}

export interface IntelBundleOptimalRequest {
  houjin_id: string | Record<string, unknown>;
  bundle_size?: number;
  objective?: "max_amount" | "max_count" | "min_overlap";
  exclude_program_ids?: string[];
  prefer_categories?: string[];
  [k: string]: unknown;
}

export interface IntelBundleDecisionSupport {
  schema_version: string;
  generated_from: string[];
  why_this_matters: IntelDecisionSupportItem[];
  decision_insights: IntelDecisionSupportItem[];
  next_actions: IntelDecisionSupportItem[];
  [k: string]: unknown;
}

export interface IntelBundleOptimalResponse extends IntelEnvelope {
  houjin_id?: string | null;
  bundle: Array<Record<string, unknown>>;
  bundle_total: Record<string, unknown>;
  conflict_avoidance: Record<string, unknown>;
  optimization_log: Record<string, unknown>;
  runner_up_bundles: Array<Record<string, unknown>>;
  data_quality: Record<string, unknown>;
  decision_support: IntelBundleDecisionSupport;
}

export interface IntelHoujinDecisionSupport {
  risk_summary: Record<string, unknown>;
  decision_insights: IntelDecisionSupportItem[];
  next_actions: IntelDecisionSupportItem[];
  known_gaps: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface IntelHoujinFullResponse extends IntelEnvelope {
  houjin_bangou?: string | null;
  sections_returned: string[];
  max_per_section?: number | null;
  houjin_meta?: Record<string, unknown> | null;
  adoption_history: Array<Record<string, unknown>>;
  enforcement_records: Array<Record<string, unknown>>;
  invoice_status: Record<string, unknown>;
  peer_summary: Record<string, unknown>;
  jurisdiction_breakdown: Record<string, unknown>;
  watch_status: Record<string, unknown>;
  data_quality: Record<string, unknown>;
  decision_support: IntelHoujinDecisionSupport;
}

export interface IntelListQuery {
  include_sections?: string[];
  max_per_section?: number;
  [k: string]: unknown;
}

export type FundingStackVerdict =
  | "compatible"
  | "incompatible"
  | "requires_review"
  | "unknown";

export interface FundingStackNextAction {
  action_id: string;
  label_ja: string;
  detail_ja: string;
  reason: string;
  source_fields?: string[];
  [k: string]: unknown;
}

export type FundingStackStructuredNextAction = FundingStackNextAction;

export interface FundingStackPair {
  program_a: string;
  program_b: string;
  verdict: FundingStackVerdict;
  confidence: number;
  rule_chain: Array<Record<string, unknown>>;
  next_actions: FundingStackNextAction[];
  _disclaimer?: string;
  [k: string]: unknown;
}

export interface FundingStackCheckResponse extends IntelEnvelope {
  program_ids: string[];
  all_pairs_status: FundingStackVerdict;
  pairs: FundingStackPair[];
  blockers: Array<Record<string, unknown> & { next_actions?: FundingStackNextAction[] }>;
  warnings: Array<Record<string, unknown> & { next_actions?: FundingStackNextAction[] }>;
  next_actions: FundingStackNextAction[];
  total_pairs: number;
}

// ────────────────────────────────────────────────────────────────────
// Meta / dashboard / cap
// ────────────────────────────────────────────────────────────────────

export interface Meta {
  total_programs: number;
  tier_counts: Record<string, number>;
  prefecture_counts: Record<string, number>;
  exclusion_rules_count: number;
  last_ingested_at: string | null;
  data_as_of: string | null;
}

export interface DashboardSummary {
  /** 当月の従量請求 (¥, 税抜). */
  current_month_charges_jpy: number;
  /** 当月のリクエスト数. */
  current_month_requests: number;
  /** 直近 30 日の月別/日別使用量. */
  daily_usage: Array<{ date: string; requests: number; charges_jpy: number }>;
  /** ¥ cap 設定 (上限到達時 503). */
  monthly_cap_jpy: number | null;
  rate_limit: {
    requests_per_minute: number;
    burst: number;
  };
}

export interface CapResponse {
  monthly_cap_jpy: number | null;
  /** Effective from this UTC date. */
  effective_from: string;
}

export interface MeResponse {
  api_key_prefix: string;
  email: string | null;
  plan: "metered";
  monthly_cap_jpy: number | null;
  created_at: string;
}
