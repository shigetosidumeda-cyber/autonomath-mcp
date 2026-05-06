// @bookyou/jpcite — minimal TypeScript client for the jpcite REST API.
//
// Coverage: 11,684 補助金/融資/税制/認定 programs + 13,801 invoice registrants +
// 9,484 laws (154 full-text indexed) + 181 排他/前提 rules.
//
// Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
// Pricing: ¥3/req metered (税込 ¥3.30). Anonymous tier = 3 req/day per IP, JST midnight reset.
//
// Zero runtime dependencies. Uses global `fetch` (Node 18+, Deno, Bun, browsers).
//
// Quickstart:
//
//   import { JpciteClient } from "@bookyou/jpcite";
//
//   const jp = new JpciteClient(process.env.JPCITE_API_KEY);
//   const res = await jp.searchPrograms("省エネ", { tier: ["S", "A"], limit: 5 });
//   for (const p of res.results) console.log(p.unified_id, p.primary_name);

// ────────────────────────────────────────────────────────────────────
// Errors
// ────────────────────────────────────────────────────────────────────

export class JpciteError extends Error {
  public readonly statusCode: number | undefined;
  public readonly body: string | undefined;

  constructor(
    message: string,
    options: { statusCode?: number; body?: string; cause?: unknown } = {},
  ) {
    super(message);
    this.name = "JpciteError";
    this.statusCode = options.statusCode;
    this.body = options.body;
    if (options.cause !== undefined) {
      (this as unknown as { cause: unknown }).cause = options.cause;
    }
  }
}

export class AuthError extends JpciteError {
  constructor(message: string, options: { statusCode?: number; body?: string } = {}) {
    super(message, options);
    this.name = "AuthError";
  }
}

export class NotFoundError extends JpciteError {
  constructor(message: string, options: { statusCode?: number; body?: string } = {}) {
    super(message, options);
    this.name = "NotFoundError";
  }
}

export class RateLimitError extends JpciteError {
  public readonly retryAfter: number | undefined;

  constructor(
    message: string,
    options: { statusCode?: number; body?: string; retryAfter?: number } = {},
  ) {
    super(message, { statusCode: options.statusCode ?? 429, body: options.body });
    this.name = "RateLimitError";
    this.retryAfter = options.retryAfter;
  }
}

// ────────────────────────────────────────────────────────────────────
// Types (minimal — mirror REST shapes, not full server Pydantic surface)
// ────────────────────────────────────────────────────────────────────

export type Tier = "S" | "A" | "B" | "C";

export interface SearchOptions {
  /** Tier filter. S = highest trust, C = lowest. */
  tier?: Tier[];
  /** 都道府県名 (e.g. "東京都"). */
  prefecture?: string;
  /** Result page size. Default 20, max 100. */
  limit?: number;
  /** Result offset. Default 0. */
  offset?: number;
}

export interface ProgramSummary {
  unified_id: string;
  primary_name: string;
  authority_name: string | null;
  prefecture: string | null;
  tier: Tier | null;
  amount_max_man_yen: number | null;
  official_url: string | null;
  excluded: boolean;
}

export interface SearchResult {
  total: number;
  limit: number;
  offset: number;
  results: ProgramSummary[];
}

export interface HoujinRecord {
  /** 13-digit T-number (法人番号). E.g. "8010001213708". */
  houjin_bangou: string;
  /** 法人名. */
  name: string;
  /** Registered HQ address. */
  address: string | null;
  /** Invoice registrant status (適格事業者). */
  invoice_registered: boolean;
  /** First registration date (YYYY-MM-DD). */
  invoice_registered_at: string | null;
  /** Source URL (NTA bulk download). */
  source_url: string | null;
}

export interface LawArticle {
  /** Unified law id (e.g. "LAW-jp-shotokuzeiho"). */
  law_unified_id: string;
  law_name: string;
  /** Article number (e.g. "第3条第1項"). */
  article_number: string;
  article_title: string | null;
  /** Article body text (CC-BY 4.0, e-Gov source). */
  body: string;
}

export interface ComplianceHit {
  rule_id: string;
  kind: string;
  severity: string | null;
  programs_involved: string[];
  description: string | null;
  source_urls: string[];
}

export interface ComplianceResult {
  program_ids: string[];
  hits: ComplianceHit[];
  checked_rules: number;
}

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

export interface EvidencePacketEnvelope {
  packet_id: string;
  generated_at: string;
  api_version: string;
  corpus_snapshot_id: string;
  query: Record<string, unknown>;
  answer_not_included: boolean;
  records: Array<Record<string, unknown> & { entity_id: string }>;
  quality: Record<string, unknown> & { known_gaps?: string[] };
  verification: Record<string, unknown>;
  compression?: Record<string, unknown> | null;
  evidence_value?: Record<string, unknown> | null;
  agent_recommendation?: Record<string, unknown> | null;
  decision_insights?: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface IntelEnvelope {
  _disclaimer?: string;
  _billing_unit?: number;
  [k: string]: unknown;
}

export interface IntelProbabilityRadarRequest {
  program_id: string;
  houjin_bangou: string;
  effort_hours_override?: number | null;
  hourly_rate_yen_override?: number | null;
  [k: string]: unknown;
}

export interface IntelAuditChainRequest {
  evidence_packet_id: string;
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

export interface IntelEntityRef {
  type: string;
  id: string;
  [k: string]: unknown;
}

export interface IntelDiffRequest {
  a: IntelEntityRef;
  b: IntelEntityRef;
  depth?: number;
  [k: string]: unknown;
}

export interface IntelPathRequest {
  from_entity: IntelEntityRef;
  to_entity: IntelEntityRef;
  max_hops?: number;
  relation_filter?: string[];
  [k: string]: unknown;
}

export interface IntelConflictRequest {
  program_ids: string[];
  houjin_id: string;
  [k: string]: unknown;
}

export interface IntelWhyExcludedRequest {
  program_id: string;
  houjin: Record<string, unknown>;
  [k: string]: unknown;
}

export interface IntelPeerGroupRequest {
  houjin_id?: string | null;
  houjin_attributes?: Record<string, unknown> | null;
  peer_count?: number;
  comparison_axes?: string[];
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

export interface IntelRiskScoreRequest {
  houjin_id: string;
  include_axes?: string[] | null;
  weight_overrides?: Record<string, number> | null;
  [k: string]: unknown;
}

export interface IntelScenarioSimulateRequest {
  scenario: string | Record<string, unknown>;
  houjin_id?: string | null;
  program_ids?: string[];
  assumptions?: Record<string, unknown> | null;
  horizon_days?: number | null;
  [k: string]: unknown;
}

export interface IntelCompetitorLandscapeRequest {
  houjin_id?: string | null;
  industry_jsic_major?: string | null;
  prefecture_code?: string | null;
  program_id?: string | null;
  peer_count?: number;
  include_axes?: string[];
  [k: string]: unknown;
}

export interface IntelPortfolioHeatmapRequest {
  houjin_ids?: string[];
  program_ids?: string[];
  axes?: string[];
  segment_by?: string | null;
  [k: string]: unknown;
}

export interface IntelNewsBriefRequest {
  subject_type?: "program" | "houjin" | "law" | "jurisdiction" | string;
  subject_id?: string | null;
  since_date?: string | null;
  max_items?: number;
  include_sources?: boolean;
  [k: string]: unknown;
}

export interface IntelOnboardingBriefRequest {
  houjin_id: string;
  program_ids?: string[];
  include_sections?: string[];
  [k: string]: unknown;
}

export interface IntelRefundRiskRequest {
  houjin_id: string;
  program_id?: string | null;
  amount_jpy?: number | null;
  include_axes?: string[];
  [k: string]: unknown;
}

export interface IntelCrossJurisdictionRequest {
  topic?: string | null;
  program_id?: string | null;
  houjin_id?: string | null;
  source_jurisdiction?: string | null;
  target_jurisdictions?: string[];
  [k: string]: unknown;
}

export interface IntelListQuery {
  include_sections?: string[];
  include_types?: string[];
  include?: string[];
  year?: number;
  max_per_section?: number;
  max_per_type?: number;
  max_citations?: number;
  since_date?: string | null;
  format?: "markdown" | "json" | string;
  include_adoptions?: boolean;
  citation_style?: "footnote" | "inline" | string;
  [k: string]: unknown;
}

export interface IntelDecisionSupportEntry {
  signal?: string;
  action?: string;
  insight_id?: string;
  section?: string;
  priority?: string;
  message?: string;
  message_ja?: string;
  reason?: string;
  basis?: string[];
  source_fields?: string[];
  [k: string]: unknown;
}

export interface IntelMatchProgram {
  program_id: string;
  primary_name: string;
  tier: string | null;
  match_score: number;
  score_components: Record<string, unknown>;
  authority_name: string | null;
  prefecture: string | null;
  program_kind: string | null;
  source_url: string | null;
  eligibility_predicate: Record<string, unknown>;
  required_documents: Array<Record<string, unknown>>;
  next_questions: Array<Record<string, unknown>>;
  eligibility_gaps: Array<Record<string, unknown>>;
  document_readiness: Record<string, unknown>;
  similar_adopted_companies: Array<Record<string, unknown>>;
  applicable_laws: Array<Record<string, unknown>>;
  applicable_tsutatsu: Array<Record<string, unknown>>;
  audit_proof: Record<string, unknown>;
  [k: string]: unknown;
}

export interface IntelMatchResponse extends IntelEnvelope {
  matched_programs: IntelMatchProgram[];
  total_candidates: number;
  applied_filters: string[];
  corpus_snapshot_id?: string;
}

export interface IntelBundleProgram {
  program_id: string;
  name: string | null;
  eligibility_score: number;
  expected_amount_min: number;
  expected_amount_max: number;
  conflict_with_others_in_bundle: string[];
  [k: string]: unknown;
}

export interface IntelBundleTotal {
  expected_amount_min: number;
  expected_amount_max: number;
  eligibility_avg: number;
  [k: string]: unknown;
}

export interface IntelBundleDecisionSupport {
  schema_version: string;
  generated_from: string[];
  why_this_matters: IntelDecisionSupportEntry[];
  decision_insights: IntelDecisionSupportEntry[];
  next_actions: IntelDecisionSupportEntry[];
  [k: string]: unknown;
}

export interface IntelBundleOptimalResponse extends IntelEnvelope {
  houjin_id: string | Record<string, unknown>;
  bundle: IntelBundleProgram[];
  bundle_total: IntelBundleTotal;
  conflict_avoidance: {
    conflict_pairs_avoided: number;
    alternative_considered: number;
    [k: string]: unknown;
  };
  optimization_log: {
    algorithm: string;
    iterations: number;
    time_ms: number;
    [k: string]: unknown;
  };
  runner_up_bundles: Array<{
    bundle: string[];
    total_amount: number;
    why_not_chosen: string;
    [k: string]: unknown;
  }>;
  data_quality: Record<string, unknown>;
  decision_support: IntelBundleDecisionSupport;
  corpus_snapshot_id?: string;
}

export interface IntelHoujinMeta {
  houjin_bangou: string;
  name: string | null;
  capital: number | null;
  employees: number | null;
  founded: string | null;
  jsic: string | null;
  address: string | null;
  corporation_type?: string | null;
  total_adoptions?: number;
  total_received_yen?: number;
  [k: string]: unknown;
}

export interface IntelHoujinFullDecisionSupport {
  risk_summary: Record<string, unknown>;
  decision_insights: IntelDecisionSupportEntry[];
  next_actions: IntelDecisionSupportEntry[];
  known_gaps: IntelDecisionSupportEntry[];
  [k: string]: unknown;
}

export interface IntelHoujinFullResponse extends IntelEnvelope {
  houjin_bangou: string;
  sections_returned: string[];
  max_per_section: number;
  houjin_meta?: IntelHoujinMeta | null;
  adoption_history?: Array<Record<string, unknown>>;
  enforcement_records?: Array<Record<string, unknown>>;
  invoice_status?: Record<string, unknown>;
  peer_summary?: Record<string, unknown>;
  jurisdiction_breakdown?: Record<string, unknown>;
  watch_status?: Record<string, unknown>;
  data_quality?: Record<string, unknown>;
  decision_support: IntelHoujinFullDecisionSupport;
  corpus_snapshot_id?: string;
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

export interface FundingStackRuleChainEntry {
  source: string;
  rule_text: string;
  weight: number;
  rule_id?: string;
  kind?: string;
  severity?: string | null;
  compat_status?: string;
  inferred_only?: number;
  source_url?: string | null;
  source_urls?: string[];
  note?: string;
  [k: string]: unknown;
}

export interface FundingStackPair {
  program_a: string;
  program_b: string;
  verdict: FundingStackVerdict;
  confidence: number;
  rule_chain: FundingStackRuleChainEntry[];
  next_actions: FundingStackNextAction[];
  _disclaimer: string;
  [k: string]: unknown;
}

export interface FundingStackCheckResponse extends IntelEnvelope {
  program_ids: string[];
  all_pairs_status: FundingStackVerdict;
  pairs: FundingStackPair[];
  blockers: Array<{
    program_a: string;
    program_b: string;
    rule_chain: FundingStackRuleChainEntry[];
    next_actions: FundingStackNextAction[];
    [k: string]: unknown;
  }>;
  warnings: Array<{
    program_a: string;
    program_b: string;
    rule_chain: FundingStackRuleChainEntry[];
    next_actions: FundingStackNextAction[];
    [k: string]: unknown;
  }>;
  next_actions: FundingStackNextAction[];
  total_pairs: number;
}

// ────────────────────────────────────────────────────────────────────
// Client
// ────────────────────────────────────────────────────────────────────

export const SDK_VERSION = "0.1.0";
const DEFAULT_BASE_URL = "https://api.jpcite.com";
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Minimal jpcite REST client.
 *
 * Four methods cover the 80% use case for AI agent / RAG integrations:
 *  - `searchPrograms` — full-text + filter search across 11,684 programs
 *  - `getHoujin` — 法人番号 lookup (13-digit T-number)
 *  - `getLawArticle` — 法令条文取得 (e-Gov CC-BY 4.0)
 *  - `checkCompliance` — 排他/前提ルール検証 (181 rules)
 *
 * For broader coverage (loans, tax incentives, enforcement, dashboard),
 * use `@autonomath/sdk` (60+ methods, same API).
 */
export class JpciteClient {
  public readonly baseUrl: string;
  private readonly apiKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly userAgent: string;

  constructor(apiKey?: string, baseUrl: string = DEFAULT_BASE_URL) {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = DEFAULT_TIMEOUT_MS;
    this.userAgent = `@bookyou/jpcite/${SDK_VERSION} (Node)`;
  }

  /**
   * Generic REST escape hatch for newly shipped endpoints.
   */
  async fetch<T = unknown>(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    body?: unknown,
  ): Promise<T> {
    return (await this.request(method, path, body)) as T;
  }

  /**
   * Full-text search across 11,684 補助金 / 助成金 / 認定制度 / 融資 / 税制 programs.
   * Returns a paginated `SearchResult`.
   */
  async searchPrograms(query: string, opts: SearchOptions = {}): Promise<SearchResult> {
    if (typeof query !== "string") {
      throw new TypeError("query must be a string");
    }
    const qs = new URLSearchParams();
    if (query) qs.append("q", query);
    for (const t of opts.tier ?? []) qs.append("tier", t);
    if (opts.prefecture !== undefined) qs.append("prefecture", opts.prefecture);
    qs.append("limit", String(opts.limit ?? 20));
    qs.append("offset", String(opts.offset ?? 0));
    const path = `/v1/programs/search?${qs.toString()}`;
    return (await this.request("GET", path)) as SearchResult;
  }

  /**
   * Lookup a 法人 by 法人番号 (13-digit number, with or without leading T).
   * Surfaces NTA invoice registrant status when applicable.
   */
  async getHoujin(houjinBangou: string): Promise<HoujinRecord> {
    if (!houjinBangou) throw new TypeError("houjinBangou is required");
    const normalized = String(houjinBangou).replace(/^[Tt]/, "").trim();
    if (!/^\d{13}$/.test(normalized)) {
      throw new TypeError(
        `houjinBangou must be a 13-digit T-number (got: ${houjinBangou})`,
      );
    }
    return (await this.request(
      "GET",
      `/v1/houjin/${encodeURIComponent(normalized)}`,
    )) as HoujinRecord;
  }

  /**
   * Get one law article (e.g. 所得税法 第3条第1項).
   * `lawId` accepts a unified law id (`LAW-jp-shotokuzeiho`) or a canonical
   * law name (`所得税法`). `articleNumber` is required separately.
   *
   * Backed by `/v1/am/law_article` — e-Gov source, CC-BY 4.0.
   */
  async getLawArticle(lawId: string, articleNumber: string): Promise<LawArticle> {
    if (!lawId) throw new TypeError("lawId is required");
    if (!articleNumber) throw new TypeError("articleNumber is required");
    const qs = new URLSearchParams({
      law_name_or_canonical_id: lawId,
      article_number: articleNumber,
    }).toString();
    return (await this.request("GET", `/v1/am/law_article?${qs}`)) as LawArticle;
  }

  /**
   * Check whether a set of program ids violates any 排他/前提 rule.
   * `programIds` must be a non-empty array of unified program ids.
   */
  async checkCompliance(programIds: string[]): Promise<ComplianceResult> {
    if (!Array.isArray(programIds) || programIds.length === 0) {
      throw new TypeError("programIds must be a non-empty array");
    }
    return (await this.request("POST", "/v1/exclusions/check", {
      program_ids: programIds,
    })) as ComplianceResult;
  }

  // ─── Evidence Packet surfaces ──────────────────────────────────────

  async getEvidencePacket(
    subjectKind: EvidencePacketSubjectKind,
    subjectId: string,
    opts: EvidencePacketOptions = {},
  ): Promise<EvidencePacketEnvelope> {
    if (subjectKind !== "program" && subjectKind !== "houjin") {
      throw new TypeError("subjectKind must be 'program' or 'houjin'");
    }
    if (!subjectId) throw new TypeError("subjectId is required");
    return this.fetch<EvidencePacketEnvelope>(
      "GET",
      withQuery(
        `/v1/evidence/packets/${encodeURIComponent(subjectKind)}/${encodeURIComponent(subjectId)}`,
        opts,
      ),
    );
  }

  async queryEvidencePacket(
    body: EvidencePacketQueryBody,
  ): Promise<EvidencePacketEnvelope> {
    if (!body || !body.query_text) throw new TypeError("body.query_text is required");
    return this.fetch<EvidencePacketEnvelope>(
      "POST",
      "/v1/evidence/packets/query",
      body,
    );
  }

  // ─── Composite intel surfaces (Wave 30/31 + W32-3) ─────────────────

  async intel<T extends IntelEnvelope = IntelEnvelope>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    return this.fetch<T>(method, path, body);
  }

  async getIntelProgramFull<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    opts: Pick<IntelListQuery, "include_sections" | "max_per_section"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/program/${encodeURIComponent(programId)}/full`, opts),
    );
  }

  async getIntelHoujinFull<T extends IntelEnvelope = IntelHoujinFullResponse>(
    houjinId: string,
    opts: Pick<IntelListQuery, "include_sections" | "max_per_section"> = {},
  ): Promise<T> {
    if (!houjinId) throw new TypeError("houjinId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/houjin/${encodeURIComponent(houjinId)}/full`, opts),
    );
  }

  async getIntelTimeline<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    opts: Pick<IntelListQuery, "year" | "include_types"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/timeline/${encodeURIComponent(programId)}`, opts),
    );
  }

  async getIntelRegulatoryContext<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    opts: Pick<IntelListQuery, "include" | "max_per_type" | "since_date"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/regulatory_context/${encodeURIComponent(programId)}`, opts),
    );
  }

  async getIntelCitationPack<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    opts: Pick<IntelListQuery, "format" | "max_citations" | "include_adoptions" | "citation_style"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/citation_pack/${encodeURIComponent(programId)}`, opts),
    );
  }

  async intelProbabilityRadar<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelProbabilityRadarRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/probability_radar", body);
  }

  async intelAuditChain<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelAuditChainRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/audit_chain", body);
  }

  async intelMatch<T extends IntelEnvelope = IntelMatchResponse>(
    body: IntelMatchRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/match", body);
  }

  async intelDiff<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelDiffRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/diff", body);
  }

  async intelPath<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelPathRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/path", body);
  }

  async intelConflict<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelConflictRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/conflict", body);
  }

  async intelWhyExcluded<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelWhyExcludedRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/why_excluded", body);
  }

  async intelPeerGroup<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelPeerGroupRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/peer_group", body);
  }

  async intelBundleOptimal<T extends IntelEnvelope = IntelBundleOptimalResponse>(
    body: IntelBundleOptimalRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/bundle/optimal", body);
  }

  async checkFundingStack(
    programIds: string[],
  ): Promise<FundingStackCheckResponse> {
    if (!Array.isArray(programIds) || programIds.length < 2) {
      throw new TypeError("programIds must contain at least two program ids");
    }
    return this.fetch<FundingStackCheckResponse>("POST", "/v1/funding_stack/check", {
      program_ids: programIds,
    });
  }

  async intelRiskScore<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelRiskScoreRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/risk_score", body);
  }

  async intelScenarioSimulate<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelScenarioSimulateRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/scenario/simulate", body);
  }

  async intelCompetitorLandscape<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelCompetitorLandscapeRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/competitor_landscape", body);
  }

  async intelPortfolioHeatmap<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelPortfolioHeatmapRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/portfolio_heatmap", body);
  }

  async intelNewsBrief<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelNewsBriefRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/news_brief", body);
  }

  async intelOnboardingBrief<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelOnboardingBriefRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/onboarding_brief", body);
  }

  async intelRefundRisk<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelRefundRiskRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/refund_risk", body);
  }

  async intelCrossJurisdiction<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelCrossJurisdictionRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/cross_jurisdiction", body);
  }

  // ─── internals ──────────────────────────────────────────────────────

  private async request(method: string, path: string, body?: unknown): Promise<unknown> {
    if (typeof fetch !== "function") {
      throw new JpciteError(
        "no fetch implementation available; Node 18+ has fetch built-in",
      );
    }
    const url = `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const headers: Record<string, string> = {
      Accept: "application/json",
      "User-Agent": this.userAgent,
    };
    if (this.apiKey) headers["X-API-Key"] = this.apiKey;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    const init: RequestInit = {
      method,
      headers,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    let response: Response;
    try {
      response = await fetch(url, { ...init, signal: controller.signal });
    } catch (err) {
      clearTimeout(timer);
      throw new JpciteError(`transport error: ${(err as Error).message}`, { cause: err });
    }
    clearTimeout(timer);

    if (!response.ok) {
      await throwForStatus(response);
    }

    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      throw new JpciteError("invalid JSON response", {
        statusCode: response.status,
        body: text,
      });
    }
  }
}

// ────────────────────────────────────────────────────────────────────
// Error mapping
// ────────────────────────────────────────────────────────────────────

async function throwForStatus(response: Response): Promise<never> {
  const status = response.status;
  const text = await response.text().catch(() => "");
  let message = text || `HTTP ${status}`;
  try {
    const data = JSON.parse(text);
    if (data && typeof data === "object") {
      message = data.detail ?? data.message ?? message;
    }
  } catch {
    // not JSON
  }

  const opts = { statusCode: status, body: text };

  if (status === 401 || status === 403) throw new AuthError(String(message), opts);
  if (status === 404) throw new NotFoundError(String(message), opts);
  if (status === 429) {
    const retryAfterRaw = response.headers.get("Retry-After");
    const retryAfter =
      retryAfterRaw !== null && Number.isFinite(Number(retryAfterRaw))
        ? Number(retryAfterRaw)
        : undefined;
    throw new RateLimitError(String(message), { ...opts, retryAfter });
  }
  throw new JpciteError(String(message), opts);
}

function withQuery(path: string, params: object): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) qs.append(key, String(item));
    } else {
      qs.append(key, String(value));
    }
  }
  const suffix = qs.toString();
  return suffix ? `${path}?${suffix}` : path;
}
