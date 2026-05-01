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
