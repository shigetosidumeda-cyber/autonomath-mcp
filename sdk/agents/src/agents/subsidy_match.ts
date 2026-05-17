// SubsidyMatchAgent — 補助金マッチング reference agent.
//
// Input: 法人番号 (13 桁) + optional industry / amount / purpose hints.
// Output: ranked list of matching programs + evidence packet (first-party
//         source URLs + jpcite corpus snapshot id + sensitive-surface
//         disclaimers).
//
// Pipeline (routes migrated under Harness H6, 2026-05-17):
//   1. GET  /v1/houjin/{法人番号}/360                            -> 法人 360
//   2. POST /v1/am/recommend                                     -> top-N programs
//   3. POST /v1/exclusions/check                                 -> drop combo-banned hits
//   4. GET  /v1/am/programs/{program_id}/adoption_stats (top 3)  -> success rate context
//
// Customer-side LLM: optional `llm` callable can be passed to ask Claude to
// rerank, summarize, or filter the recommendation set. The jpcite operator
// itself never invokes an LLM — see `_disclaimer` in step 2 response.
//
// Sensitive surface (envelope_wrapper.SENSITIVE_TOOLS): `recommend_programs_for_houjin`
// emits `_disclaimer` (§52 — not 税理士 advice / 行政書士法 §1 — not 申請書面). The
// agent propagates that string verbatim into `evidence.disclaimers`.

import type { ProgramRecommendation } from "../lib/jpcite_client.js";
import { JpciteClient, type EvidencePacket } from "../lib/jpcite_client.js";
import type { LlmQuery } from "../index.js";

export interface SubsidyMatchInput {
  /** 法人番号 13 桁 (国税庁 corporate number). */
  houjin_bangou: string;
  /** Optional minimum amount in 万円 used to drop tiny programs. */
  amount_min_man_yen?: number;
  /** Optional tier filter; defaults to ["S", "A", "B"]. Excludes tier C and X (quarantine). */
  tier?: Array<"S" | "A" | "B" | "C">;
  /** Optional cap. Default 10. Hard ceiling 50 to bound ¥3/req fan-out. */
  limit?: number;
  /**
   * If true, also enrich the top-3 hits with 採択率 + 平均額 stats. Costs
   * up to 3 extra ¥3 requests. Default true.
   */
  enrich_top_3?: boolean;
}

export interface SubsidyMatchProgramHit extends ProgramRecommendation {
  /** Filled when `enrich_top_3` is true and the ranking position is < 3. */
  adoption_stats?: {
    total_applications: number | null;
    total_adopted: number | null;
    adoption_rate: number | null;
    avg_amount_jpy: number | null;
    last_round_at: string | null;
  };
}

export interface SubsidyMatchOutput {
  /** Ranked, exclusion-filtered programs. Order: highest score first. */
  programs: SubsidyMatchProgramHit[];
  /** Provenance packet — propagate to UI / logs. */
  evidence: EvidencePacket;
  /**
   * Compound-call hints from the underlying jpcite envelope (`_next_calls`).
   * Surfaced raw so agent operators can decide whether to follow up.
   */
  evidence_packets: Array<{ tool: string; args: Record<string, unknown> }>;
}

export interface SubsidyMatchAgentOptions {
  /**
   * Optional LLM callable (e.g. `query` from `@anthropic-ai/claude-agent-sdk`).
   * If supplied, the agent may use it to dedupe / rerank / synthesize a
   * narrative summary. Customer pays for those tokens, not jpcite.
   */
  llm?: LlmQuery;
}

/**
 * 補助金マッチング reference agent. Stateless; safe to reuse across requests.
 */
export class SubsidyMatchAgent {
  constructor(
    private readonly jpcite: JpciteClient,
    private readonly options: SubsidyMatchAgentOptions = {},
  ) {}

  async run(input: SubsidyMatchInput): Promise<SubsidyMatchOutput> {
    if (!input?.houjin_bangou || !/^\d{13}$/.test(input.houjin_bangou)) {
      throw new TypeError("houjin_bangou must be a 13-digit string");
    }
    const limit = Math.min(input.limit ?? 10, 50);
    const tier = input.tier ?? ["S", "A", "B"];

    // Step 1 — 360-degree snapshot (used for industry / amount context).
    const houjin = await this.jpcite.getHoujin360(input.houjin_bangou);

    // Step 2 — primary recommendation surface (sensitive — emits _disclaimer).
    const recs = await this.jpcite.recommendProgramsForHoujin(input.houjin_bangou, {
      limit,
      tier,
    });

    let programs: SubsidyMatchProgramHit[] = recs.results;
    if (input.amount_min_man_yen != null) {
      programs = programs.filter(
        (p) => (p.amount_max_man_yen ?? 0) >= input.amount_min_man_yen!,
      );
    }

    // Step 3 — exclusion-rule check (drop combos that would auto-reject 申請).
    const sourceUrls: string[] = [];
    if (programs.length > 0) {
      const ids = programs.map((p) => p.unified_id);
      const ex = await this.jpcite.checkExclusions(ids);
      const dropped = new Set<string>();
      for (const hit of (ex.hits ?? [])) {
        for (const url of hit.source_urls) sourceUrls.push(url);
        if ((hit.severity ?? "").toLowerCase() === "absolute") {
          for (const id of hit.programs_involved) dropped.add(id);
        }
      }
      programs = programs.filter((p) => !dropped.has(p.unified_id));
    }

    // Step 4 — enrich top 3 with adoption stats (skipped if disabled / empty).
    if (input.enrich_top_3 !== false && programs.length > 0) {
      const head = programs.slice(0, 3);
      const stats = await Promise.allSettled(
        head.map((p) => this.jpcite.getProgramAdoptionStats(p.unified_id)),
      );
      for (let i = 0; i < head.length; i++) {
        const s = stats[i];
        if (s && s.status === "fulfilled") {
          // Fill in non-mutating way for callers that diff via JSON.
          head[i] = {
            ...head[i]!,
            adoption_stats: {
              total_applications: s.value.total_applications,
              total_adopted: s.value.total_adopted,
              adoption_rate: s.value.adoption_rate,
              avg_amount_jpy: s.value.avg_amount_jpy,
              last_round_at: s.value.last_round_at,
            },
          };
        }
      }
      programs = [...head, ...programs.slice(3)];
    }

    // Collect first-party citations from the program hits + houjin snapshot.
    for (const p of programs) if (p.source_url) sourceUrls.push(p.source_url);
    for (const a of houjin.adoption_history) {
      // Adoption history rows may not carry URLs; only the program ids.
      void a;
    }

    const disclaimers: string[] = [];
    if (recs._disclaimer) disclaimers.push(recs._disclaimer);

    const evidence = this.jpcite.buildEvidence(sourceUrls, { disclaimers });

    // Surface compound-call hints — the customer agent loop may want to follow
    // them up (e.g. fetch program detail, calendar, application_documents).
    const evidence_packets = programs.flatMap<{
      tool: string;
      args: Record<string, unknown>;
    }>((p) => [
      { tool: "get_program", args: { unified_id: p.unified_id } },
      { tool: "get_program_calendar_12mo", args: { unified_id: p.unified_id } },
    ]);

    // Optional LLM rerank — only invoked if the caller passed an `llm` and at
    // least 5 hits remain. Skipped quietly otherwise (no jpcite-side LLM cost).
    if (this.options.llm && programs.length >= 5) {
      // NOTE: Reference stub. A production fork would build a structured
      // prompt that asks Claude to rerank by stated business goal, returning
      // a JSON list of unified_ids. Keep the request side-effect-free so the
      // agent stays idempotent. Example shape:
      //
      //   const stream = this.options.llm({ prompt: rerankPrompt, options: { ... } });
      //   for await (const _msg of stream) { /* collect */ }
    }

    return { programs, evidence, evidence_packets };
  }
}
