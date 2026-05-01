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
