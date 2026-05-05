// REST + MCP wrapper used by every reference agent.
//
// Wraps `@jpcite/sdk` (REST) and exposes a thin facade for the few endpoints
// the agents call. Also exposes optional MCP spawn helpers for hosts that
// want the 120-tool MCP surface instead of REST.
//
// Customer-side LLM cost: this client never invokes Anthropic; it only talks
// to https://api.jpcite.com (¥3/req metered). LLM reasoning happens on the
// `ClaudeAgent` instance the agent constructor receives, which is paid for
// by the customer directly with their Anthropic key.

import { Jpcite } from "@jpcite/sdk";
import type {
  Enforcement,
  EnforcementSearchParams,
  EnforcementSearchResponse,
  ExclusionCheckResponse,
  Law,
  LawArticle,
  ProgramDetail,
  SearchParams,
  SearchResponse,
  TaxIncentiveSearchParams,
  TaxIncentiveSearchResponse,
} from "@jpcite/sdk";

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

  checkExclusions(programIds: string[]): Promise<ExclusionCheckResponse> {
    return this.rest.checkExclusions(programIds);
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
    const path = `/v1/am/houjin/${encodeURIComponent(houjinBangou)}/snapshot`;
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
    const qs = new URLSearchParams();
    qs.append("limit", String(options.limit ?? 10));
    for (const t of options.tier ?? []) qs.append("tier", t);
    const path = `/v1/am/recommend/${encodeURIComponent(houjinBangou)}?${qs.toString()}`;
    return this.rest.fetch<{
      results: ProgramRecommendation[];
      _disclaimer?: string;
    }>("GET", path);
  }

  /**
   * GET /v1/am/program/{unified_id}/adoption_stats — Wave 24
   * `get_program_adoption_stats`. Used by DD + kessan briefing agents.
   */
  async getProgramAdoptionStats(unifiedId: string): Promise<ProgramAdoptionStats> {
    if (!unifiedId) throw new TypeError("unifiedId is required");
    const path = `/v1/am/program/${encodeURIComponent(unifiedId)}/adoption_stats`;
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
    const path = `/v1/am/amendments/recent?${qs.toString()}`;
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
    const path = `/v1/am/invoice_registrants/${encodeURIComponent(houjinBangou)}`;
    return this.rest.fetch("GET", path);
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
