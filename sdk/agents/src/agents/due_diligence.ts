// DueDiligenceAgent — DD 質問生成 reference agent (M&A cohort #1).
//
// Generates a tailored DD question deck (30-60 questions) for a target 法人
// based on:
//   * `match_due_diligence_questions` (Wave 22 MCP tool, 60-row template
//     library across 7 categories: credit / enforcement / invoice_compliance /
//     industry_specific / lifecycle / tax / governance).
//   * `v_houjin_360` (snapshot of NTA invoice + gBiz + adoption + enforcement).
//   * `cross_check_jurisdiction` (registered vs invoice vs operational
//     jurisdiction discrepancy detector).
//
// The rendered output is a checklist scaffold + 一次 URL — never a 申請書面.
// (行政書士法 §1 boundary; the agent must NOT generate filings.)
//
// LLM (optional): can rephrase the questions to match a specific buyer's
// internal doc style. If omitted, the raw template strings are returned.

import { JpciteClient, type EvidencePacket } from "../lib/jpcite_client.js";
import type { LlmQuery } from "../index.js";

export type DdCategory =
  | "credit"
  | "enforcement"
  | "invoice_compliance"
  | "industry_specific"
  | "lifecycle"
  | "tax"
  | "governance";

export interface DueDiligenceInput {
  /** Target corp 法人番号 13 桁. */
  houjin_bangou: string;
  /**
   * Severity floor (1-5). 1 = include trivia, 5 = only red-flag questions.
   * Default 2.
   */
  severity_min?: 1 | 2 | 3 | 4 | 5;
  /** Restrict to a subset of the 7 categories. Default = all. */
  categories?: DdCategory[];
  /** Hard ceiling on questions returned. Default 60, max 60. */
  limit?: number;
  /**
   * If true and `llm` was wired in the constructor options, rewrite each
   * question into the buyer's tone. The jpcite operator never invokes
   * Anthropic — the customer pays for these tokens.
   */
  rephrase?: boolean;
  /**
   * Optional buyer-side context passed verbatim to the LLM rephrase prompt.
   * Ignored when `rephrase` is false.
   */
  buyer_context?: string;
}

export interface DueDiligenceQuestion {
  template_id: string;
  category: DdCategory;
  /** 1-5; higher = redder flag. */
  severity: number;
  /** ja-JP question text. */
  question: string;
  /**
   * Why this question fired for this corp (e.g. "invoice_registered=false" or
   * "5 enforcement hits in past 5 years"). Pre-LLM, this is a server-side
   * reason string from `match_due_diligence_questions._meta.reasons[id]`.
   */
  trigger_reason: string;
  /** Suggested document(s) to request from the seller. */
  request_documents: string[];
  /** First-party URLs the buyer can cite if the question proves contentious. */
  source_urls: string[];
}

export interface DueDiligenceOutput {
  /** Header summary of the target corp. */
  target: {
    houjin_bangou: string;
    trade_name: string | null;
    prefecture: string | null;
    jsic_major: string | null;
    invoice_registered: boolean;
    /** True iff `cross_check_jurisdiction` reported any 不一致. */
    jurisdiction_mismatch: boolean;
  };
  /** Question deck, ordered severity DESC then category. */
  questions: DueDiligenceQuestion[];
  /** Total templates considered (before severity / limit filtering). */
  total_templates_considered: number;
  evidence: EvidencePacket;
}

export interface DueDiligenceAgentOptions {
  llm?: LlmQuery;
}

/**
 * DD 質問生成 reference agent. Returns a question deck + provenance, never
 * a draft 申請書面.
 */
export class DueDiligenceAgent {
  constructor(
    private readonly jpcite: JpciteClient,
    private readonly options: DueDiligenceAgentOptions = {},
  ) {}

  async run(input: DueDiligenceInput): Promise<DueDiligenceOutput> {
    if (!input?.houjin_bangou || !/^\d{13}$/.test(input.houjin_bangou)) {
      throw new TypeError("houjin_bangou must be a 13-digit string");
    }
    const severity_min = input.severity_min ?? 2;
    const limit = Math.min(input.limit ?? 60, 60);

    // Step 1 — houjin snapshot for header + enforcement context.
    const houjin = await this.jpcite.getHoujin360(input.houjin_bangou);

    // Step 2 + 3 — DD batch composition (Harness H6, 2026-05-17).
    // Legacy GET /v1/am/houjin/{id}/jurisdiction_check + POST
    // /v1/am/dd/match_questions had no FastAPI counterpart; both rolled
    // into POST /v1/am/dd_batch (ma_dd.py) which composes 5 atomic tools.
    type DdBatchProfile = {
      houjin_bangou: string;
      jurisdiction_check?: {
        registered_prefecture?: string | null;
        invoice_prefecture?: string | null;
        operational_prefecture?: string | null;
        mismatch?: boolean;
      };
      dd_questions?: Array<{
        template_id: string;
        category: DdCategory;
        severity: number;
        question: string;
        trigger_reason: string;
        request_documents: string[];
        source_urls: string[];
      }>;
      total_templates_considered?: number;
      _disclaimer?: string;
    };
    type DdBatchResp = {
      batch_size: number;
      profiles: DdBatchProfile[];
      _disclaimer?: string;
    };
    const batch = await this.jpcite.rest.fetch<DdBatchResp>(
      "POST",
      "/v1/am/dd_batch",
      {
        houjin_bangou_list: [input.houjin_bangou],
        severity_min,
        categories: input.categories,
        limit,
      },
    );
    const profile: DdBatchProfile = batch.profiles[0] ?? {
      houjin_bangou: input.houjin_bangou,
    };
    const cross = {
      registered_prefecture: profile.jurisdiction_check?.registered_prefecture ?? null,
      invoice_prefecture: profile.jurisdiction_check?.invoice_prefecture ?? null,
      operational_prefecture: profile.jurisdiction_check?.operational_prefecture ?? null,
      mismatch: profile.jurisdiction_check?.mismatch ?? false,
      _disclaimer: profile._disclaimer,
    };
    const matched = {
      results: profile.dd_questions ?? [],
      total_templates_considered: profile.total_templates_considered ?? 0,
      _disclaimer: batch._disclaimer ?? profile._disclaimer,
    };

    let questions: DueDiligenceQuestion[] = matched.results;

    // Optional LLM rephrase. Stub only — production fork batches into a single
    // prompt to keep customer Anthropic spend down.
    if (input.rephrase && this.options.llm && questions.length > 0) {
      // const stream = this.options.llm({
      //   prompt: renderRephrasePrompt(questions, input.buyer_context),
      // });
      // for await (const _msg of stream) { /* parse + reassign question text */ }
      void input.buyer_context;
    }

    // Stable ordering: severity DESC, then category alpha.
    questions = [...questions].sort((a, b) => {
      if (b.severity !== a.severity) return b.severity - a.severity;
      return a.category.localeCompare(b.category);
    });

    const sourceUrls = questions.flatMap((q) => q.source_urls);
    const disclaimers = [
      "本リストは jpcite データに基づく DD チェックリストの足場 (scaffold) であり、" +
        "申請書面・契約書面の作成 (行政書士法 §1 / 司法書士法 §3) は行いません。" +
        "個別案件の最終判断は弁護士・税理士・行政書士にご相談ください (§52)。",
    ];
    if (matched._disclaimer) disclaimers.push(matched._disclaimer);
    if (cross._disclaimer) disclaimers.push(cross._disclaimer);

    const evidence = this.jpcite.buildEvidence(sourceUrls, { disclaimers });

    return {
      target: {
        houjin_bangou: houjin.houjin_bangou,
        trade_name: houjin.trade_name,
        prefecture: houjin.prefecture,
        jsic_major: houjin.jsic_major,
        invoice_registered: houjin.invoice_registered,
        jurisdiction_mismatch: cross.mismatch,
      },
      questions,
      total_templates_considered: matched.total_templates_considered,
      evidence,
    };
  }
}
