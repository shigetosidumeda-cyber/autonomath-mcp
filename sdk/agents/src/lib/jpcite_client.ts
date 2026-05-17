// REST + MCP wrapper used by every reference agent.
//
// Wraps `@jpcite/sdk` (REST) and exposes a thin facade for the few endpoints
// the agents call. Also exposes optional MCP spawn helpers for hosts that
// want the 139-tool MCP surface instead of REST.
//
// Customer-side LLM cost: this client never invokes Anthropic; it only talks
// to https://api.jpcite.com (¥3/req metered). LLM reasoning happens on the
// `ClaudeAgent` instance the agent constructor receives, which is paid for
// by the customer directly with their Anthropic key.

// Inline types (no external @jpcite/sdk dep — uses raw fetch to api.jpcite.com).
// Schema follows OpenAPI spec at https://api.jpcite.com/v1/openapi.json.
// All types are intentionally permissive ([k: string]: any) so the SDK
// surface evolves with the API without forcing bumps here.
export interface SearchParams { q?: string; limit?: number; offset?: number; tier?: string; prefecture?: string; [k: string]: any; }
export interface SearchResponse { results: any[]; total: number; corpus_snapshot_id?: string; _disclaimer?: any; [k: string]: any; }
export interface ProgramDetail { id: string; primary_name: string; [k: string]: any; }
export interface Law { law_id: string; title: string; [k: string]: any; }
export interface LawArticle { law_id: string; article_number: string; body: string; [k: string]: any; }
export interface Enforcement { case_id: string; [k: string]: any; }
export interface EnforcementSearchParams { q?: string; limit?: number; offset?: number; [k: string]: any; }
export interface EnforcementSearchResponse { results: Enforcement[]; total: number; [k: string]: any; }
export interface ExclusionCheckResponse { excluded: boolean; reasons: any[]; hits?: any[]; [k: string]: any; }
export interface TaxIncentiveSearchParams { q?: string; limit?: number; effective_on?: string; [k: string]: any; }
export interface TaxIncentiveSearchResponse { results: any[]; total: number; [k: string]: any; }

interface JpciteOpts {
  apiKey?: string;
  baseUrl?: string;
  timeoutMs?: number;
  maxRetries?: number;
  userAgentSuffix?: string;
}

class Jpcite {
  constructor(private opts: JpciteOpts = {}) {}
  private get baseUrl() { return this.opts.baseUrl || "https://api.jpcite.com"; }
  async fetch<T = any>(methodOrPath: string, path?: string, body?: any): Promise<T> {
    // Overload: fetch(path) defaults to GET; fetch(method, path, body?)
    let method: string;
    let realPath: string;
    if (path === undefined) {
      method = "GET";
      realPath = methodOrPath;
    } else {
      method = methodOrPath;
      realPath = path;
    }
    const headers: Record<string, string> = {
      "Accept": "application/json",
      "User-Agent": `jpcite-agents-sdk/0.1.1 ${this.opts.userAgentSuffix ?? ""}`.trim(),
    };
    if (this.opts.apiKey) headers["Authorization"] = `Bearer ${this.opts.apiKey}`;
    if (body != null) headers["Content-Type"] = "application/json";
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.opts.timeoutMs ?? 30000);
    try {
      const r = await fetch(`${this.baseUrl}${realPath}`, {
        method,
        headers,
        body: body == null ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!r.ok) throw new Error(`jpcite ${r.status} ${method} ${realPath}: ${await r.text()}`);
      return await r.json() as T;
    } finally {
      clearTimeout(timer);
    }
  }
  searchPrograms(p: SearchParams = {}): Promise<SearchResponse> {
    return this.fetch<SearchResponse>("GET", `/v1/programs/search?${new URLSearchParams(p as any).toString()}`);
  }
  getProgram(id: string): Promise<ProgramDetail> {
    return this.fetch<ProgramDetail>("GET", `/v1/programs/${encodeURIComponent(id)}`);
  }
  getLaw(id: string): Promise<Law> {
    return this.fetch<Law>("GET", `/v1/laws/${encodeURIComponent(id)}`);
  }
  getLawArticle(lawId: string, art: string): Promise<LawArticle> {
    return this.fetch<LawArticle>("GET", `/v1/laws/${encodeURIComponent(lawId)}/articles/${encodeURIComponent(art)}`);
  }
  searchEnforcement(p: EnforcementSearchParams = {}): Promise<EnforcementSearchResponse> {
    return this.fetch<EnforcementSearchResponse>("GET", `/v1/enforcements/search?${new URLSearchParams(p as any).toString()}`);
  }
  getEnforcement(id: string): Promise<Enforcement> {
    return this.fetch<Enforcement>("GET", `/v1/enforcements/${encodeURIComponent(id)}`);
  }
  checkExclusions(houjinBangou: string, programId: string): Promise<ExclusionCheckResponse> {
    // Harness H6 (2026-05-17): canonical route is POST /v1/exclusions/check.
    return this.fetch<ExclusionCheckResponse>(
      "POST",
      `/v1/exclusions/check`,
      { program_ids: [programId], houjin_bangou: houjinBangou || undefined },
    );
  }
  searchTaxIncentives(p: TaxIncentiveSearchParams = {}): Promise<TaxIncentiveSearchResponse> {
    return this.fetch<TaxIncentiveSearchResponse>("GET", `/v1/tax-incentives/search?${new URLSearchParams(p as any).toString()}`);
  }
}
export { Jpcite };

export interface JpciteClientOptions {
  /** jpcite API key. Optional — anonymous gets 3 req/日 per IP (JST 翌日 00:00 リセット). */
  apiKey?: string;
  /** Override base URL (self-host / staging). Default: https://api.jpcite.com */
  baseUrl?: string;
  /** Per-request timeout in ms. Default 30000. */
  timeoutMs?: number;
  /** Retry budget for 429/5xx + transport. Default 3. */
  maxRetries?: number;
  /** Optional User-Agent suffix (e.g. agent name). */
  userAgentSuffix?: string;
  /** Inject a pre-built Jpcite instance (test injection). */
  rest?: Jpcite;
}

/**
 * Houjin 360-degree snapshot — composite of NTA invoice registrant + gBiz
 * + adoption history + enforcement record. Backed by `v_houjin_360` view in
 * autonomath.db, surfaced via `/v1/am/houjin/{houjin_bangou}/snapshot`.
 *
 * Field set is intentionally narrow; agents that need the full view should
 * call `client.fetch("GET", "/v1/am/houjin/{houjin_bangou}/snapshot")` and
 * cast to a richer interface.
 */
export interface Houjin360Snapshot {
  houjin_bangou: string;
  trade_name: string | null;
  prefecture: string | null;
  municipality: string | null;
  jsic_major: string | null;
  invoice_registered: boolean;
  invoice_registered_at: string | null;
  capital_stock_jpy: number | null;
  employees: number | null;
  founded_at: string | null;
  /** Past 採択 (subsidies awarded). */
  adoption_history: Array<{
    program_unified_id: string;
    program_name: string;
    adopted_at: string | null;
    amount_jpy: number | null;
  }>;
  /** 行政処分 hits. */
  enforcement_history: Array<{
    case_id: string;
    authority: string | null;
    case_kind: string | null;
    decided_at: string | null;
    summary: string | null;
  }>;
}

/**
 * One row of `recommend_programs_for_houjin` (Wave 24 MCP tool, also exposed
 * at `GET /v1/am/recommend/{houjin_bangou}`).
 */
export interface ProgramRecommendation {
  unified_id: string;
  primary_name: string;
  tier: "S" | "A" | "B" | "C" | "X" | null;
  score: number;
  reason: string;
  amount_max_man_yen: number | null;
  authority_level: string | null;
  prefecture: string | null;
  application_window: Record<string, unknown> | null;
  /** First-party citation (govt ministry / 公庫 / prefecture notice). */
  source_url: string | null;
}

/**
 * Recent law amendment row. Backed by `am_amendment_diff` (post-launch cron)
 * + `am_amendment_snapshot` (14,596 captures, 144 dated).
 */
export interface LawAmendmentDiff {
  law_unified_id: string;
  law_name: string;
  article_number: string | null;
  diff_kind: "added" | "removed" | "changed" | "renumbered";
  effective_from: string | null;
  captured_at: string;
  summary: string | null;
  source_url: string | null;
}

/**
 * Adoption stats row (Wave 24 `get_program_adoption_stats`).
 */
export interface ProgramAdoptionStats {
  program_unified_id: string;
  total_applications: number | null;
  total_adopted: number | null;
  adoption_rate: number | null;
  avg_amount_jpy: number | null;
  last_round_at: string | null;
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
  filters?: Record<string, any> | null;
  limit?: number;
}

export interface EvidencePacketEnvelope {
  packet_id: string;
  generated_at: string;
  api_version: string;
  corpus_snapshot_id: string;
  query: Record<string, any>;
  answer_not_included: boolean;
  records: Array<Record<string, any> & { entity_id: string }>;
  quality: Record<string, any> & { known_gaps?: string[] };
  verification: Record<string, any>;
  compression?: Record<string, any> | null;
  evidence_value?: Record<string, any> | null;
  agent_recommendation?: Record<string, any> | null;
  decision_insights?: Record<string, any> | null;
  [k: string]: any;
}

export interface IntelEnvelope {
  _disclaimer?: string;
  _billing_unit?: number;
  [k: string]: any;
}

export interface IntelProbabilityRadarRequest {
  program_id: string;
  houjin_bangou: string;
  effort_hours_override?: number | null;
  hourly_rate_yen_override?: number | null;
  [k: string]: any;
}

export interface IntelAuditChainRequest {
  evidence_packet_id: string;
  [k: string]: any;
}

export interface IntelMatchRequest {
  industry_jsic_major: string;
  prefecture_code: string;
  capital_jpy?: number | null;
  employee_count?: number | null;
  keyword?: string | null;
  limit?: number;
  [k: string]: any;
}

export interface IntelEntityRef {
  type: string;
  id: string;
  [k: string]: any;
}

export interface IntelDiffRequest {
  a: IntelEntityRef;
  b: IntelEntityRef;
  depth?: number;
  [k: string]: any;
}

export interface IntelPathRequest {
  from_entity: IntelEntityRef;
  to_entity: IntelEntityRef;
  max_hops?: number;
  relation_filter?: string[];
  [k: string]: any;
}

export interface IntelConflictRequest {
  program_ids: string[];
  houjin_id: string;
  [k: string]: any;
}

export interface IntelWhyExcludedRequest {
  program_id: string;
  houjin: Record<string, any>;
  [k: string]: any;
}

export interface IntelPeerGroupRequest {
  houjin_id?: string | null;
  houjin_attributes?: Record<string, any> | null;
  peer_count?: number;
  comparison_axes?: string[];
  [k: string]: any;
}

export interface IntelBundleOptimalRequest {
  houjin_id: string | Record<string, any>;
  bundle_size?: number;
  objective?: "max_amount" | "max_count" | "min_overlap";
  exclude_program_ids?: string[];
  prefer_categories?: string[];
  [k: string]: any;
}

export interface IntelRiskScoreRequest {
  houjin_id: string;
  include_axes?: string[] | null;
  weight_overrides?: Record<string, number> | null;
  [k: string]: any;
}

export interface IntelScenarioSimulateRequest {
  scenario: string | Record<string, any>;
  houjin_id?: string | null;
  program_ids?: string[];
  assumptions?: Record<string, any> | null;
  horizon_days?: number | null;
  [k: string]: any;
}

export interface IntelCompetitorLandscapeRequest {
  houjin_id?: string | null;
  industry_jsic_major?: string | null;
  prefecture_code?: string | null;
  program_id?: string | null;
  peer_count?: number;
  include_axes?: string[];
  [k: string]: any;
}

export interface IntelPortfolioHeatmapRequest {
  houjin_ids?: string[];
  program_ids?: string[];
  axes?: string[];
  segment_by?: string | null;
  [k: string]: any;
}

export interface IntelNewsBriefRequest {
  subject_type?: "program" | "houjin" | "law" | "jurisdiction" | string;
  subject_id?: string | null;
  since_date?: string | null;
  max_items?: number;
  include_sources?: boolean;
  [k: string]: any;
}

export interface IntelOnboardingBriefRequest {
  houjin_id: string;
  program_ids?: string[];
  include_sections?: string[];
  [k: string]: any;
}

export interface IntelRefundRiskRequest {
  houjin_id: string;
  program_id?: string | null;
  amount_jpy?: number | null;
  include_axes?: string[];
  [k: string]: any;
}

export interface IntelCrossJurisdictionRequest {
  topic?: string | null;
  program_id?: string | null;
  houjin_id?: string | null;
  source_jurisdiction?: string | null;
  target_jurisdictions?: string[];
  [k: string]: any;
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
  [k: string]: any;
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
  [k: string]: any;
}

export interface IntelMatchProgram {
  program_id: string;
  primary_name: string;
  tier: string | null;
  match_score: number;
  score_components: Record<string, any>;
  authority_name: string | null;
  prefecture: string | null;
  program_kind: string | null;
  source_url: string | null;
  eligibility_predicate: Record<string, any>;
  required_documents: Array<Record<string, any>>;
  next_questions: Array<Record<string, any>>;
  eligibility_gaps: Array<Record<string, any>>;
  document_readiness: Record<string, any>;
  similar_adopted_companies: Array<Record<string, any>>;
  applicable_laws: Array<Record<string, any>>;
  applicable_tsutatsu: Array<Record<string, any>>;
  audit_proof: Record<string, any>;
  [k: string]: any;
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
  [k: string]: any;
}

export interface IntelBundleTotal {
  expected_amount_min: number;
  expected_amount_max: number;
  eligibility_avg: number;
  [k: string]: any;
}

export interface IntelBundleDecisionSupport {
  schema_version: string;
  generated_from: string[];
  why_this_matters: IntelDecisionSupportEntry[];
  decision_insights: IntelDecisionSupportEntry[];
  next_actions: IntelDecisionSupportEntry[];
  [k: string]: any;
}

export interface IntelBundleOptimalResponse extends IntelEnvelope {
  houjin_id: string | Record<string, any>;
  bundle: IntelBundleProgram[];
  bundle_total: IntelBundleTotal;
  conflict_avoidance: {
    conflict_pairs_avoided: number;
    alternative_considered: number;
    [k: string]: any;
  };
  optimization_log: {
    algorithm: string;
    iterations: number;
    time_ms: number;
    [k: string]: any;
  };
  runner_up_bundles: Array<{
    bundle: string[];
    total_amount: number;
    why_not_chosen: string;
    [k: string]: any;
  }>;
  data_quality: Record<string, any>;
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
  [k: string]: any;
}

export interface IntelHoujinFullDecisionSupport {
  risk_summary: Record<string, any>;
  decision_insights: IntelDecisionSupportEntry[];
  next_actions: IntelDecisionSupportEntry[];
  known_gaps: IntelDecisionSupportEntry[];
  [k: string]: any;
}

export interface IntelHoujinFullResponse extends IntelEnvelope {
  houjin_bangou: string;
  sections_returned: string[];
  max_per_section: number;
  houjin_meta?: IntelHoujinMeta | null;
  adoption_history?: Array<Record<string, any>>;
  enforcement_records?: Array<Record<string, any>>;
  invoice_status?: Record<string, any>;
  peer_summary?: Record<string, any>;
  jurisdiction_breakdown?: Record<string, any>;
  watch_status?: Record<string, any>;
  data_quality?: Record<string, any>;
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
  [k: string]: any;
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
  [k: string]: any;
}

export interface FundingStackPair {
  program_a: string;
  program_b: string;
  verdict: FundingStackVerdict;
  confidence: number;
  rule_chain: FundingStackRuleChainEntry[];
  next_actions: FundingStackNextAction[];
  _disclaimer: string;
  [k: string]: any;
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
    [k: string]: any;
  }>;
  warnings: Array<{
    program_a: string;
    program_b: string;
    rule_chain: FundingStackRuleChainEntry[];
    next_actions: FundingStackNextAction[];
    [k: string]: any;
  }>;
  next_actions: FundingStackNextAction[];
  total_pairs: number;
}

/**
 * Evidence packet attached to every agent output. Agents are forbidden from
 * surfacing claims without a citation set; this struct enforces that
 * contract at the type level.
 */
export interface EvidencePacket {
  /** First-party URLs (gov ministry / 公庫 / prefecture / NTA). */
  source_urls: string[];
  /** jpcite corpus snapshot id (from `_meta.corpus_snapshot_id`). */
  corpus_snapshot_id?: string;
  /** SHA-256 of the corpus slice that produced this answer. */
  corpus_checksum?: string;
  /** ISO 8601 of when jpcite was queried. */
  queried_at: string;
  /** Disclaimers (§52 sensitive surfaces, 行政書士法 §1, etc.). */
  disclaimers: string[];
}

/**
 * Thin REST + MCP facade used by the reference agents. Wraps `@jpcite/sdk`'s
 * `Jpcite` class and adds composition helpers (houjin 360, recommendation,
 * amendment diff). All methods return raw API payloads; callers attach the
 * `EvidencePacket` themselves.
 */
export class JpciteClient {
  public readonly rest: Jpcite;

  constructor(options: JpciteClientOptions = {}) {
    if (options.rest) {
      this.rest = options.rest;
    } else {
      this.rest = new Jpcite({
        apiKey: options.apiKey,
        baseUrl: options.baseUrl,
        timeoutMs: options.timeoutMs,
        maxRetries: options.maxRetries,
        userAgentSuffix: options.userAgentSuffix ?? "jpcite-agents",
      });
    }
  }

  fetch<T = any>(methodOrPath: string, path?: string, body?: any): Promise<T> {
    return this.rest.fetch<T>(methodOrPath, path, body);
  }

  // ─── Programs / loans / tax / enforcement / law (delegates to @jpcite/sdk) ───

  searchPrograms(params: SearchParams = {}): Promise<SearchResponse> {
    return this.rest.searchPrograms(params);
  }

  getProgram(unifiedId: string): Promise<ProgramDetail> {
    return this.rest.getProgram(unifiedId);
  }

  searchTaxIncentives(
    params: TaxIncentiveSearchParams = {},
  ): Promise<TaxIncentiveSearchResponse> {
    return this.rest.searchTaxIncentives(params);
  }

  searchEnforcement(
    params: EnforcementSearchParams = {},
  ): Promise<EnforcementSearchResponse> {
    return this.rest.searchEnforcement(params);
  }

  getEnforcement(caseId: string): Promise<Enforcement> {
    return this.rest.getEnforcement(caseId);
  }

  getLaw(unifiedId: string): Promise<Law> {
    return this.rest.getLaw(unifiedId);
  }

  getLawArticle(
    lawNameOrCanonicalId: string,
    articleNumber: string,
  ): Promise<LawArticle> {
    return this.rest.getLawArticle(lawNameOrCanonicalId, articleNumber);
  }

  checkExclusions(programIdsOrHoujin: string[] | string, programId?: string): Promise<ExclusionCheckResponse> {
    if (Array.isArray(programIdsOrHoujin)) {
      // Compat shim: SDK old signature took an id list. Map to first id check.
      const id = programIdsOrHoujin[0] ?? "";
      return this.rest.checkExclusions("", id);
    }
    return this.rest.checkExclusions(programIdsOrHoujin, programId ?? "");
  }

  // ─── Composition surfaces (autonomath.db unified primary DB) ───

  /**
   * GET /v1/am/houjin/{houjin_bangou}/snapshot — composite view across
   * NTA invoice registrant + gBiz + adoption + enforcement.
   *
   * @throws NotFoundError if 法人番号 13 桁 is not registered.
   */
  async getHoujin360(houjinBangou: string): Promise<Houjin360Snapshot> {
    if (!houjinBangou) throw new TypeError("houjinBangou is required");
    // Harness H6 (2026-05-17): legacy /v1/am/houjin/{id}/snapshot -> /v1/houjin/{bangou}/360.
    const path = `/v1/houjin/${encodeURIComponent(houjinBangou)}/360`;
    return this.rest.fetch<Houjin360Snapshot>("GET", path);
  }

  /**
   * GET /v1/am/recommend/{houjin_bangou} — Wave 24 `recommend_programs_for_houjin`
   * REST surface. Returns top-N programs ranked by tier × jurisdictional fit
   * × industry match × past adoption signal.
   *
   * Sensitive surface (envelope_wrapper.SENSITIVE_TOOLS), so the response
   * carries `_disclaimer` — propagate it into the EvidencePacket.
   */
  async recommendProgramsForHoujin(
    houjinBangou: string,
    options: { limit?: number; tier?: Array<"S" | "A" | "B" | "C"> } = {},
  ): Promise<{ results: ProgramRecommendation[]; _disclaimer?: string }> {
    if (!houjinBangou) throw new TypeError("houjinBangou is required");
    // Harness H6 (2026-05-17): legacy GET /v1/am/recommend/{id} -> POST /v1/am/recommend.
    const body: Record<string, unknown> = {
      houjin_bangou: houjinBangou,
      limit: options.limit ?? 10,
    };
    if (options.tier && options.tier.length > 0) body.tier = options.tier;
    return this.rest.fetch<{
      results: ProgramRecommendation[];
      _disclaimer?: string;
    }>("POST", "/v1/am/recommend", body);
  }

  /**
   * GET /v1/am/program/{unified_id}/adoption_stats — Wave 24
   * `get_program_adoption_stats`. Used by DD + kessan briefing agents.
   */
  async getProgramAdoptionStats(unifiedId: string): Promise<ProgramAdoptionStats> {
    if (!unifiedId) throw new TypeError("unifiedId is required");
    // Harness H6 (2026-05-17): singular "program" -> plural "programs".
    const path = `/v1/am/programs/${encodeURIComponent(unifiedId)}/adoption_stats`;
    return this.rest.fetch<ProgramAdoptionStats>("GET", path);
  }

  /**
   * GET /v1/am/amendments/recent — paged feed of recent law amendment diffs.
   * Backed by `am_amendment_diff` (cron-populated) + `am_amendment_snapshot`.
   *
   * @param sinceIso ISO 8601 lower bound (inclusive).
   */
  async listRecentAmendments(
    sinceIso: string,
    options: { limit?: number; offset?: number } = {},
  ): Promise<{
    total: number;
    limit: number;
    offset: number;
    results: LawAmendmentDiff[];
  }> {
    if (!sinceIso) throw new TypeError("sinceIso is required");
    const qs = new URLSearchParams();
    qs.append("since", sinceIso);
    qs.append("limit", String(options.limit ?? 50));
    qs.append("offset", String(options.offset ?? 0));
    // Harness H6 (2026-05-17): legacy /v1/am/amendments/recent -> /v1/me/amendment_alerts/feed.
    const path = `/v1/me/amendment_alerts/feed?${qs.toString()}`;
    return this.rest.fetch<{
      total: number;
      limit: number;
      offset: number;
      results: LawAmendmentDiff[];
    }>("GET", path);
  }

  /**
   * GET /v1/am/invoice_registrants/{houjin_bangou} — direct lookup of
   * 適格請求書発行事業者番号 status. Backed by `invoice_registrants` (NTA
   * PDL v1.0; monthly 4M-row zenken bulk wired 2026-04-29).
   */
  async getInvoiceRegistrant(houjinBangou: string): Promise<{
    houjin_bangou: string;
    registered: boolean;
    registration_no: string | null;
    registered_at: string | null;
    revoked_at: string | null;
    trade_name: string | null;
    address: string | null;
    source_url: string;
    source_fetched_at: string | null;
  }> {
    if (!houjinBangou) throw new TypeError("houjinBangou is required");
    // Harness H6 (2026-05-17): canonical lookup-by-houjin-bangou route.
    const path = `/v1/houjin/${encodeURIComponent(houjinBangou)}/invoice_status`;
    return this.rest.fetch("GET", path);
  }

  // ─── Evidence Packet REST surfaces ──────────────────────────────────

  getEvidencePacket(
    subjectKind: EvidencePacketSubjectKind,
    subjectId: string,
    options: EvidencePacketOptions = {},
  ): Promise<EvidencePacketEnvelope> {
    if (subjectKind !== "program" && subjectKind !== "houjin") {
      throw new TypeError("subjectKind must be 'program' or 'houjin'");
    }
    if (!subjectId) throw new TypeError("subjectId is required");
    return this.rest.fetch<EvidencePacketEnvelope>(
      "GET",
      withQuery(
        `/v1/evidence/packets/${encodeURIComponent(subjectKind)}/${encodeURIComponent(subjectId)}`,
        options,
      ),
    );
  }

  queryEvidencePacket(body: EvidencePacketQueryBody): Promise<EvidencePacketEnvelope> {
    if (!body || !body.query_text) throw new TypeError("body.query_text is required");
    return this.rest.fetch<EvidencePacketEnvelope>(
      "POST",
      "/v1/evidence/packets/query",
      body,
    );
  }

  // ─── Composite intel surfaces (Wave 30/31 + W32-3) ─────────────────────

  intel<T extends IntelEnvelope = IntelEnvelope>(
    method: "GET" | "POST",
    path: string,
    body?: any,
  ): Promise<T> {
    return this.rest.fetch<T>(method, path, body);
  }

  getIntelProgramFull<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    options: Pick<IntelListQuery, "include_sections" | "max_per_section"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/program/${encodeURIComponent(programId)}/full`, options),
    );
  }

  getIntelHoujinFull<T extends IntelEnvelope = IntelHoujinFullResponse>(
    houjinId: string,
    options: Pick<IntelListQuery, "include_sections" | "max_per_section"> = {},
  ): Promise<T> {
    if (!houjinId) throw new TypeError("houjinId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/houjin/${encodeURIComponent(houjinId)}/full`, options),
    );
  }

  getIntelTimeline<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    options: Pick<IntelListQuery, "year" | "include_types"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/timeline/${encodeURIComponent(programId)}`, options),
    );
  }

  getIntelRegulatoryContext<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    options: Pick<IntelListQuery, "include" | "max_per_type" | "since_date"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/regulatory_context/${encodeURIComponent(programId)}`, options),
    );
  }

  getIntelCitationPack<T extends IntelEnvelope = IntelEnvelope>(
    programId: string,
    options: Pick<IntelListQuery, "format" | "max_citations" | "include_adoptions" | "citation_style"> = {},
  ): Promise<T> {
    if (!programId) throw new TypeError("programId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/citation_pack/${encodeURIComponent(programId)}`, options),
    );
  }

  intelProbabilityRadar<T extends IntelEnvelope = IntelEnvelope>(body: IntelProbabilityRadarRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/probability_radar", body);
  }

  intelAuditChain<T extends IntelEnvelope = IntelEnvelope>(body: IntelAuditChainRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/audit_chain", body);
  }

  intelMatch<T extends IntelEnvelope = IntelMatchResponse>(body: IntelMatchRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/match", body);
  }

  intelDiff<T extends IntelEnvelope = IntelEnvelope>(body: IntelDiffRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/diff", body);
  }

  intelPath<T extends IntelEnvelope = IntelEnvelope>(body: IntelPathRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/path", body);
  }

  intelConflict<T extends IntelEnvelope = IntelEnvelope>(body: IntelConflictRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/conflict", body);
  }

  intelWhyExcluded<T extends IntelEnvelope = IntelEnvelope>(body: IntelWhyExcludedRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/why_excluded", body);
  }

  intelPeerGroup<T extends IntelEnvelope = IntelEnvelope>(body: IntelPeerGroupRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/peer_group", body);
  }

  intelBundleOptimal<T extends IntelEnvelope = IntelBundleOptimalResponse>(body: IntelBundleOptimalRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/bundle/optimal", body);
  }

  checkFundingStack(programIds: string[]): Promise<FundingStackCheckResponse> {
    if (!Array.isArray(programIds) || programIds.length < 2) {
      throw new TypeError("programIds must contain at least two program ids");
    }
    return this.rest.fetch<FundingStackCheckResponse>("POST", "/v1/funding_stack/check", {
      program_ids: programIds,
    });
  }

  intelRiskScore<T extends IntelEnvelope = IntelEnvelope>(body: IntelRiskScoreRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/risk_score", body);
  }

  intelScenarioSimulate<T extends IntelEnvelope = IntelEnvelope>(body: IntelScenarioSimulateRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/scenario/simulate", body);
  }

  intelCompetitorLandscape<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelCompetitorLandscapeRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/competitor_landscape", body);
  }

  intelPortfolioHeatmap<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelPortfolioHeatmapRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/portfolio_heatmap", body);
  }

  intelNewsBrief<T extends IntelEnvelope = IntelEnvelope>(body: IntelNewsBriefRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/news_brief", body);
  }

  intelOnboardingBrief<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelOnboardingBriefRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/onboarding_brief", body);
  }

  intelRefundRisk<T extends IntelEnvelope = IntelEnvelope>(body: IntelRefundRiskRequest): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/refund_risk", body);
  }

  intelCrossJurisdiction<T extends IntelEnvelope = IntelEnvelope>(
    body: IntelCrossJurisdictionRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/cross_jurisdiction", body);
  }

  // ─── Evidence packet helpers ─────────────────────────────────────────

  /**
   * Build an EvidencePacket from a set of source URLs + optional disclaimers.
   * The `queried_at` field is auto-populated.
   */
  buildEvidence(
    sourceUrls: string[],
    options: {
      disclaimers?: string[];
      corpusSnapshotId?: string;
      corpusChecksum?: string;
    } = {},
  ): EvidencePacket {
    return {
      source_urls: dedupe(sourceUrls.filter((u): u is string => Boolean(u))),
      ...(options.corpusSnapshotId !== undefined && {
        corpus_snapshot_id: options.corpusSnapshotId,
      }),
      ...(options.corpusChecksum !== undefined && {
        corpus_checksum: options.corpusChecksum,
      }),
      queried_at: new Date().toISOString(),
      disclaimers: options.disclaimers ?? [],
    };
  }
}

function dedupe<T>(arr: T[]): T[] {
  return Array.from(new Set(arr));
}

function withQuery(path: string, params: Record<string, any>): string {
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
