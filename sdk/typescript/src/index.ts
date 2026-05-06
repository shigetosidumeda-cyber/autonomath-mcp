// jpcite TypeScript / JavaScript SDK. The npm package is currently published
// as @autonomath/sdk for compatibility.
//
// Zero runtime dependencies. Uses the global `fetch` (Node 20+, Deno, Bun, browsers).
// MCP usage: `import { spawnMcp } from "@autonomath/sdk/mcp"` (spawns the
// Python `autonomath-mcp` package as a child process; install via pip).
//
// Quickstart:
//
//   import { Jpcite } from "@autonomath/sdk";
//
//   const am = new Jpcite({ apiKey: process.env.JPCITE_API_KEY });
//
//   const programs = await am.searchPrograms({ q: "省エネ", tier: ["S", "A"], limit: 5 });
//   for (const p of programs.results) console.log(p.unified_id, p.primary_name);

import {
  AuthError,
  AutonoMathError,
  BadRequestError,
  CapReachedError,
  JpciteError,
  NotFoundError,
  RateLimitError,
  ServerError,
} from "./errors.js";
import type {
  CapResponse,
  ClientOptions,
  DashboardSummary,
  Enforcement,
  EnforcementSearchParams,
  EnforcementSearchResponse,
  EvidencePacketEnvelope,
  EvidencePacketOptions,
  EvidencePacketQueryBody,
  EvidencePacketSubjectKind,
  ExclusionCheckResponse,
  ExclusionRule,
  FundingStackCheckResponse,
  IntelBundleOptimalRequest,
  IntelBundleOptimalResponse,
  IntelEnvelope,
  IntelHoujinFullResponse,
  IntelListQuery,
  IntelMatchRequest,
  IntelMatchResponse,
  Law,
  LawArticle,
  Loan,
  LoanSearchParams,
  LoanSearchResponse,
  MeResponse,
  Meta,
  ProgramDetail,
  SearchParams,
  SearchResponse,
  TaxIncentiveSearchParams,
  TaxIncentiveSearchResponse,
  TaxRule,
} from "./types.js";

export const SDK_VERSION = "0.3.2";
const DEFAULT_BASE_URL = "https://api.jpcite.com";
const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RETRIES = 3;

/**
 * jpcite REST API client.
 *
 * One client instance covers all endpoints (programs, loans, tax incentives,
 * enforcement, laws, exclusions, dashboard, cap, me).
 */
export class Jpcite {
  public readonly baseUrl: string;
  private readonly apiKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    const suffix = options.userAgentSuffix ? ` ${options.userAgentSuffix}` : "";
    this.userAgent = `jpcite-sdk-typescript/${SDK_VERSION}${suffix}`;

    const providedFetch = options.fetch;
    if (providedFetch) {
      this.fetchImpl = providedFetch;
    } else if (typeof fetch === "function") {
      this.fetchImpl = fetch.bind(globalThis);
    } else {
      throw new AutonoMathError(
        "no fetch implementation available; pass options.fetch (Node 20+ has fetch built-in)",
      );
    }
  }

  // ─── 1. Health & Meta ────────────────────────────────────────────────

  /** Health check. Returns `{ status: "ok" }`. Free, no API key required. */
  async healthz(): Promise<{ status: string }> {
    return (await this.request("GET", "/healthz")) as { status: string };
  }

  /** Catalog metadata: total_programs, tier_counts, last_ingested_at, etc. */
  async meta(): Promise<Meta> {
    return (await this.request("GET", "/v1/meta")) as Meta;
  }

  // ─── 2. Programs (補助金 / 助成金 / 認定制度) ─────────────────────────

  /**
   * Search the 11,684-row searchable programs catalog (補助金・助成金・融資・税制・認定制度, S/A/B/C tiers).
   * Filters: tier, prefecture, authority_level, funding_purpose, target_type, etc.
   */
  async searchPrograms(params: SearchParams = {}): Promise<SearchResponse> {
    const qs = buildSearchQuery(params);
    const path = qs ? `/v1/programs/search?${qs}` : "/v1/programs/search";
    return (await this.request("GET", path)) as SearchResponse;
  }

  /** Get one program with full enriched detail (a_to_j coverage, source mentions). */
  async getProgram(unifiedId: string): Promise<ProgramDetail> {
    if (!unifiedId) throw new TypeError("unifiedId is required");
    return (await this.request(
      "GET",
      `/v1/programs/${encodeURIComponent(unifiedId)}`,
    )) as ProgramDetail;
  }

  // ─── 3. Loans (融資 — 三軸: 担保 / 個人保証人 / 第三者保証人) ─────────

  /**
   * Search the 108-row loans catalog (日本政策金融公庫 / 信用保証協会 etc.).
   * Filter by collateral / personal_guarantor / third_party_guarantor independently.
   */
  async searchLoans(params: LoanSearchParams = {}): Promise<LoanSearchResponse> {
    const qs = buildLoanQuery(params);
    const path = qs ? `/v1/loan-programs/search?${qs}` : "/v1/loan-programs/search";
    return (await this.request("GET", path)) as LoanSearchResponse;
  }

  /** Get one loan program by id. */
  async getLoan(loanId: string | number): Promise<Loan> {
    if (loanId === undefined || loanId === null || loanId === "") {
      throw new TypeError("loanId is required");
    }
    return (await this.request(
      "GET",
      `/v1/loan-programs/${encodeURIComponent(String(loanId))}`,
    )) as Loan;
  }

  // ─── 4. Tax incentives ───────────────────────────────────────────────

  /** Search 税制 rulesets (インボイス / 電帳法 / 省エネ税制 etc.). */
  async searchTaxIncentives(
    params: TaxIncentiveSearchParams = {},
  ): Promise<TaxIncentiveSearchResponse> {
    const qs = buildTaxQuery(params);
    const path = qs ? `/v1/tax_rulesets/search?${qs}` : "/v1/tax_rulesets/search";
    return (await this.request("GET", path)) as TaxIncentiveSearchResponse;
  }

  /** Get one tax ruleset. */
  async getTaxIncentive(unifiedId: string): Promise<TaxRule> {
    if (!unifiedId) throw new TypeError("unifiedId is required");
    return (await this.request(
      "GET",
      `/v1/tax_rulesets/${encodeURIComponent(unifiedId)}`,
    )) as TaxRule;
  }

  // ─── 5. Enforcement (行政処分) ───────────────────────────────────────

  /** Search 行政処分 1,185 件 (FSA / METI etc.). */
  async searchEnforcement(
    params: EnforcementSearchParams = {},
  ): Promise<EnforcementSearchResponse> {
    const qs = buildEnforcementQuery(params);
    const path = qs ? `/v1/enforcement-cases/search?${qs}` : "/v1/enforcement-cases/search";
    return (await this.request("GET", path)) as EnforcementSearchResponse;
  }

  /** Get one 行政処分 case. */
  async getEnforcement(caseId: string): Promise<Enforcement> {
    if (!caseId) throw new TypeError("caseId is required");
    return (await this.request(
      "GET",
      `/v1/enforcement-cases/${encodeURIComponent(caseId)}`,
    )) as Enforcement;
  }

  // ─── 6. Laws (e-Gov, CC-BY) ──────────────────────────────────────────

  /** Get one law (top-level metadata). */
  async getLaw(unifiedId: string): Promise<Law> {
    if (!unifiedId) throw new TypeError("unifiedId is required");
    return (await this.request("GET", `/v1/laws/${encodeURIComponent(unifiedId)}`)) as Law;
  }

  /**
   * Get one article of a law (e.g. 第3条第1項).
   * `lawNameOrCanonicalId` accepts a unified law id (`LAW-jp-shotokuzeiho`) or
   * a canonical law name (`所得税法`). Backed by `/v1/am/law_article`.
   */
  async getLawArticle(
    lawNameOrCanonicalId: string,
    articleNumber: string,
  ): Promise<LawArticle> {
    if (!lawNameOrCanonicalId) throw new TypeError("lawNameOrCanonicalId is required");
    if (!articleNumber) throw new TypeError("articleNumber is required");
    const qs = new URLSearchParams({
      law_name_or_canonical_id: lawNameOrCanonicalId,
      article_number: articleNumber,
    }).toString();
    return (await this.request("GET", `/v1/am/law_article?${qs}`)) as LawArticle;
  }

  // ─── 7. Exclusion rules (排他ルール) ────────────────────────────────

  /** List all 181 排他/前提 rules. */
  async listExclusionRules(): Promise<ExclusionRule[]> {
    return (await this.request("GET", "/v1/exclusions/rules")) as ExclusionRule[];
  }

  /** Check whether a set of program ids violates any exclusion rule. */
  async checkExclusions(programIds: string[]): Promise<ExclusionCheckResponse> {
    if (!Array.isArray(programIds) || programIds.length === 0) {
      throw new TypeError("programIds must be a non-empty array");
    }
    return (await this.request("POST", "/v1/exclusions/check", {
      program_ids: programIds,
    })) as ExclusionCheckResponse;
  }

  // ─── 8. Evidence Packet / composite intelligence ───────────────────

  /** Get a source-linked Evidence Packet for one program or houjin. */
  async getEvidencePacket(
    subjectKind: EvidencePacketSubjectKind,
    subjectId: string,
    options: EvidencePacketOptions = {},
  ): Promise<EvidencePacketEnvelope> {
    if (subjectKind !== "program" && subjectKind !== "houjin") {
      throw new TypeError("subjectKind must be 'program' or 'houjin'");
    }
    if (!subjectId) throw new TypeError("subjectId is required");
    return (await this.request(
      "GET",
      withQuery(
        `/v1/evidence/packets/${encodeURIComponent(subjectKind)}/${encodeURIComponent(subjectId)}`,
        options,
      ),
    )) as EvidencePacketEnvelope;
  }

  /** Build a multi-record Evidence Packet from a query and optional filters. */
  async queryEvidencePacket(
    body: EvidencePacketQueryBody,
  ): Promise<EvidencePacketEnvelope> {
    if (!body || !body.query_text) throw new TypeError("body.query_text is required");
    return (await this.request(
      "POST",
      "/v1/evidence/packets/query",
      body,
    )) as EvidencePacketEnvelope;
  }

  /** Low-level typed helper for `/v1/intel/*` surfaces. */
  async intel<T extends IntelEnvelope = IntelEnvelope>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    return this.fetch<T>(method, path, body);
  }

  /** POST `/v1/intel/match` — deterministic top-N program matching. */
  async intelMatch<T extends IntelEnvelope = IntelMatchResponse>(
    body: IntelMatchRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/match", body);
  }

  /** POST `/v1/intel/bundle/optimal` — select a conflict-aware program bundle. */
  async intelBundleOptimal<T extends IntelEnvelope = IntelBundleOptimalResponse>(
    body: IntelBundleOptimalRequest,
  ): Promise<T> {
    return this.intel<T>("POST", "/v1/intel/bundle/optimal", body);
  }

  /** GET `/v1/intel/houjin/{houjin_id}/full` — composite houjin 360 bundle. */
  async getIntelHoujinFull<T extends IntelEnvelope = IntelHoujinFullResponse>(
    houjinId: string,
    options: Pick<IntelListQuery, "include_sections" | "max_per_section"> = {},
  ): Promise<T> {
    if (!houjinId) throw new TypeError("houjinId is required");
    return this.intel<T>(
      "GET",
      withQuery(`/v1/intel/houjin/${encodeURIComponent(houjinId)}/full`, options),
    );
  }

  /** POST `/v1/funding_stack/check` — program stack compatibility check. */
  async checkFundingStack(programIds: string[]): Promise<FundingStackCheckResponse> {
    if (!Array.isArray(programIds) || programIds.length < 2) {
      throw new TypeError("programIds must contain at least two program ids");
    }
    return this.fetch<FundingStackCheckResponse>("POST", "/v1/funding_stack/check", {
      program_ids: programIds,
    });
  }

  // ─── 9. Account / dashboard / cap ───────────────────────────────────

  /** Per-account info: api key prefix, email, plan, cap. Requires auth. */
  async me(): Promise<MeResponse> {
    return (await this.request("GET", "/v1/me")) as MeResponse;
  }

  /** Current month charges, daily usage, rate-limit. Requires auth. */
  async dashboard(): Promise<DashboardSummary> {
    return (await this.request("GET", "/v1/me/dashboard")) as DashboardSummary;
  }

  /**
   * Set or clear the monthly ¥-cap (税抜) for this API key.
   * Pass `null` to remove the cap. Reaching the cap returns 402 (CapReachedError).
   */
  async setCap(monthlyCapJpy: number | null): Promise<CapResponse> {
    if (monthlyCapJpy !== null && (typeof monthlyCapJpy !== "number" || monthlyCapJpy < 0)) {
      throw new TypeError("monthlyCapJpy must be a non-negative number or null");
    }
    return (await this.request("POST", "/v1/me/cap", {
      monthly_cap_jpy: monthlyCapJpy,
    })) as CapResponse;
  }

  // ─── low-level helper ───────────────────────────────────────────────

  /**
   * Low-level request helper. Public for advanced use cases (custom endpoints,
   * preview features, etc.). Path is appended to `baseUrl`. Returns parsed JSON.
   */
  async fetch<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    return (await this.request(method, path, body)) as T;
  }

  private async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const url = `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const headers: Record<string, string> = {
      Accept: "application/json",
      "User-Agent": this.userAgent,
    };
    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }

    let init: RequestInit = { method, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init = { ...init, body: JSON.stringify(body) };
    }

    let attempt = 0;
    while (true) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);

      let response: Response;
      try {
        response = await this.fetchImpl(url, { ...init, signal: controller.signal });
      } catch (err) {
        clearTimeout(timer);
        if (attempt >= this.maxRetries) {
          throw new AutonoMathError(`transport error: ${(err as Error).message}`, {
            cause: err,
          });
        }
        await sleep(backoffMs(attempt));
        attempt += 1;
        continue;
      }
      clearTimeout(timer);

      if (shouldRetry(response.status) && attempt < this.maxRetries) {
        await sleep(retryDelayMs(response, attempt));
        attempt += 1;
        continue;
      }

      if (!response.ok) {
        await throwForStatus(response);
      }

      const contentLength = response.headers.get("content-length");
      if (contentLength === "0") return null;
      const text = await response.text();
      if (!text) return null;
      try {
        return JSON.parse(text);
      } catch {
        throw new AutonoMathError("invalid JSON response", {
          statusCode: response.status,
          body: text,
        });
      }
    }
  }
}

/** Compatibility alias for older @autonomath/sdk imports. Prefer Jpcite. */
export class AutonoMath extends Jpcite {}

// ────────────────────────────────────────────────────────────────────
// Query string builders
// ────────────────────────────────────────────────────────────────────

function buildSearchQuery(params: SearchParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.append("q", params.q);
  for (const t of params.tier ?? []) qs.append("tier", t);
  if (params.prefecture !== undefined) qs.append("prefecture", params.prefecture);
  if (params.authority_level !== undefined) qs.append("authority_level", params.authority_level);
  for (const fp of params.funding_purpose ?? []) qs.append("funding_purpose", fp);
  for (const tt of params.target_type ?? []) qs.append("target_type", tt);
  if (params.amount_min !== undefined) qs.append("amount_min", String(params.amount_min));
  if (params.amount_max !== undefined) qs.append("amount_max", String(params.amount_max));
  qs.append("include_excluded", params.include_excluded ? "true" : "false");
  qs.append("limit", String(params.limit ?? 20));
  qs.append("offset", String(params.offset ?? 0));
  return qs.toString();
}

function buildLoanQuery(params: LoanSearchParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.append("q", params.q);
  if (params.authority !== undefined) qs.append("authority", params.authority);
  for (const lp of params.loan_purpose ?? []) qs.append("loan_purpose", lp);
  if (params.amount_min !== undefined) qs.append("amount_min", String(params.amount_min));
  if (params.amount_max !== undefined) qs.append("amount_max", String(params.amount_max));
  if (params.collateral !== undefined) qs.append("collateral", params.collateral);
  if (params.personal_guarantor !== undefined) {
    qs.append("personal_guarantor", params.personal_guarantor);
  }
  qs.append("limit", String(params.limit ?? 20));
  qs.append("offset", String(params.offset ?? 0));
  return qs.toString();
}

function buildTaxQuery(params: TaxIncentiveSearchParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.append("q", params.q);
  if (params.rule_kind !== undefined) qs.append("rule_kind", params.rule_kind);
  if (params.authority !== undefined) qs.append("authority", params.authority);
  if (params.effective_on !== undefined) qs.append("effective_on", params.effective_on);
  qs.append("limit", String(params.limit ?? 20));
  qs.append("offset", String(params.offset ?? 0));
  return qs.toString();
}

function buildEnforcementQuery(params: EnforcementSearchParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.append("q", params.q);
  if (params.authority !== undefined) qs.append("authority", params.authority);
  if (params.case_kind !== undefined) qs.append("case_kind", params.case_kind);
  if (params.decided_from !== undefined) qs.append("decided_from", params.decided_from);
  if (params.decided_to !== undefined) qs.append("decided_to", params.decided_to);
  qs.append("limit", String(params.limit ?? 20));
  qs.append("offset", String(params.offset ?? 0));
  return qs.toString();
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

// ────────────────────────────────────────────────────────────────────
// Retry / error helpers
// ────────────────────────────────────────────────────────────────────

function shouldRetry(status: number): boolean {
  return status === 429 || (status >= 500 && status < 600);
}

function backoffMs(attempt: number, baseMs = 500, capMs = 8_000): number {
  return Math.min(capMs, baseMs * 2 ** attempt);
}

function retryDelayMs(response: Response, attempt: number): number {
  if (response.status === 429) {
    const raw = response.headers.get("Retry-After");
    if (raw) {
      const seconds = Number(raw);
      if (Number.isFinite(seconds) && seconds >= 0) {
        return seconds * 1000;
      }
    }
  }
  return backoffMs(attempt);
}

async function throwForStatus(response: Response): Promise<never> {
  const status = response.status;
  const text = await response.text().catch(() => "");
  let message = text || `HTTP ${status}`;
  let parsed: Record<string, unknown> | null = null;
  try {
    const data = JSON.parse(text);
    if (data && typeof data === "object") {
      parsed = data as Record<string, unknown>;
      message =
        (parsed["detail"] as string) ?? (parsed["message"] as string) ?? message;
    }
  } catch {
    // not JSON
  }

  const opts = { statusCode: status, body: text };

  if (status === 400 || status === 422) {
    throw new BadRequestError(String(message), opts);
  }
  if (status === 401 || status === 403) throw new AuthError(String(message), opts);
  if (status === 402 || (parsed && parsed["cap_reached"] === true)) {
    const capJpy = parsed && typeof parsed["monthly_cap_jpy"] === "number"
      ? (parsed["monthly_cap_jpy"] as number)
      : undefined;
    const charges = parsed && typeof parsed["current_month_charges_jpy"] === "number"
      ? (parsed["current_month_charges_jpy"] as number)
      : undefined;
    throw new CapReachedError(String(message), {
      statusCode: status,
      body: text,
      capJpy,
      currentMonthChargesJpy: charges,
    });
  }
  if (status === 404) throw new NotFoundError(String(message), opts);
  if (status === 429) {
    const retryAfterRaw = response.headers.get("Retry-After");
    const retryAfter =
      retryAfterRaw !== null && Number.isFinite(Number(retryAfterRaw))
        ? Number(retryAfterRaw)
        : undefined;
    throw new RateLimitError(String(message), {
      statusCode: status,
      body: text,
      retryAfter,
    });
  }
  if (status >= 500 && status < 600) throw new ServerError(String(message), opts);
  throw new AutonoMathError(String(message), opts);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ────────────────────────────────────────────────────────────────────
// Public re-exports
// ────────────────────────────────────────────────────────────────────

export {
  AuthError,
  AutonoMathError,
  BadRequestError,
  CapReachedError,
  JpciteError,
  NotFoundError,
  RateLimitError,
  ServerError,
} from "./errors.js";

export type {
  CapResponse,
  ClientOptions,
  DashboardSummary,
  Enforcement,
  EnforcementSearchParams,
  EnforcementSearchResponse,
  EvidencePacketCompression,
  EvidencePacketDecisionInsights,
  EvidencePacketEnvelope,
  EvidencePacketEvidenceValue,
  EvidencePacketInsightItem,
  EvidencePacketOptions,
  EvidencePacketProfile,
  EvidencePacketQuality,
  EvidencePacketQueryBody,
  EvidencePacketRecord,
  EvidencePacketSourceTokensBasis,
  EvidencePacketSubjectKind,
  EvidencePacketVerification,
  ExclusionCheckResponse,
  ExclusionHit,
  ExclusionRule,
  FundingStackCheckResponse,
  FundingStackNextAction,
  FundingStackPair,
  FundingStackStructuredNextAction,
  FundingStackVerdict,
  IntelBundleDecisionSupport,
  IntelBundleOptimalRequest,
  IntelBundleOptimalResponse,
  IntelDecisionSupportItem,
  IntelDocumentReadiness,
  IntelEligibilityGap,
  IntelEnvelope,
  IntelHoujinDecisionSupport,
  IntelHoujinFullResponse,
  IntelListQuery,
  IntelMatchRequest,
  IntelMatchResponse,
  IntelMatchedProgram,
  IntelQuestion,
  Law,
  LawArticle,
  Loan,
  LoanSearchParams,
  LoanSearchResponse,
  MeResponse,
  Meta,
  Program,
  ProgramDetail,
  SearchParams,
  SearchResponse,
  TaxIncentiveSearchParams,
  TaxIncentiveSearchResponse,
  TaxRule,
  Tier,
} from "./types.js";

// Test-only helpers.
export const __internals = {
  buildSearchQuery,
  buildLoanQuery,
  buildTaxQuery,
  buildEnforcementQuery,
  withQuery,
  shouldRetry,
  backoffMs,
};
