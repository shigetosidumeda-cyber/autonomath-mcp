// LawAmendmentWatchAgent — 法令改正監視 reference agent.
//
// Polls `am_amendment_diff` (post-launch cron) + `am_amendment_snapshot`
// (14,596 captures, 144 dated) for amendments effective since a watermark,
// optionally narrowed to a watch list of law canonical ids and/or article
// numbers. Useful for:
//   - 税理士 monthly digest (joined with `dispatch_webhooks` cron).
//   - DD lawyers tracking effective_from on cited articles.
//   - 信金 / 商工会 weekly newsletter (organic acquisition cohort #7).
//
// Customer LLM (optional): summarize the diff stream into a 1-page brief for
// non-lawyers. Stub demonstrates how to wire `query` without forcing the dep.
//
// Sensitive surface: 法令改正 surfacing is itself non-sensitive (CC-BY e-Gov
// distribution), but consequential downstream advice (申請 / 税務処理 への
// 影響) is. The agent therefore returns the diffs raw and only adds a
// disclaimer if `summarize: true` was requested.

import { JpciteClient, type EvidencePacket } from "../lib/jpcite_client.js";
import type { LawAmendmentDiff } from "../lib/jpcite_client.js";
import type { LlmQuery } from "../index.js";

export interface LawAmendmentWatchInput {
  /**
   * ISO 8601 lower bound (inclusive). Typical use: persist the highest
   * `captured_at` seen on the previous run and pass it back in here.
   */
  since: string;
  /**
   * Optional. If set, only diffs whose `law_unified_id` matches one of these
   * canonical ids are returned. Saves compute when the customer cares about
   * a fixed set (e.g. 法人税法 + 消費税法 + 中小企業等経営強化法).
   */
  law_unified_ids?: string[];
  /** Page size. Default 50. Hard cap 200. */
  limit?: number;
  /** Pagination offset. Default 0. */
  offset?: number;
  /**
   * If true and an `llm` was passed to the constructor, the agent will ask
   * Claude to write a 200-character ja-JP summary of each diff_kind cohort.
   * Adds a §52 disclaimer to the evidence packet when used.
   */
  summarize?: boolean;
}

export interface LawAmendmentWatchOutput {
  /** Raw diff rows newest-first by `captured_at`. */
  diffs: LawAmendmentDiff[];
  /** Total available; use to decide whether to page again. */
  total: number;
  limit: number;
  offset: number;
  /**
   * Highest `captured_at` returned. Persist this client-side and feed it back
   * as `since` on the next run. Empty string when no diffs returned.
   */
  next_watermark: string;
  /**
   * Optional Claude-generated narrative summary, present iff `summarize` was
   * requested and an `llm` was wired into the constructor.
   */
  summary?: string;
  evidence: EvidencePacket;
}

export interface LawAmendmentWatchAgentOptions {
  /**
   * Customer LLM callable. See `LlmQuery` in `index.ts`. Without this, the
   * `summarize` flag becomes a no-op (the agent never invokes Anthropic on
   * the operator side).
   */
  llm?: LlmQuery;
}

/**
 * 法令改正監視 reference agent. Idempotent given the same `since` watermark.
 */
export class LawAmendmentWatchAgent {
  constructor(
    private readonly jpcite: JpciteClient,
    private readonly options: LawAmendmentWatchAgentOptions = {},
  ) {}

  async run(input: LawAmendmentWatchInput): Promise<LawAmendmentWatchOutput> {
    if (!input?.since) throw new TypeError("since is required (ISO 8601)");
    const limit = Math.min(input.limit ?? 50, 200);
    const offset = input.offset ?? 0;

    const page = await this.jpcite.listRecentAmendments(input.since, {
      limit,
      offset,
    });

    let diffs = page.results;
    if (input.law_unified_ids && input.law_unified_ids.length > 0) {
      const watch = new Set(input.law_unified_ids);
      diffs = diffs.filter((d) => watch.has(d.law_unified_id));
    }

    const next_watermark = diffs.reduce(
      (acc, d) => (d.captured_at > acc ? d.captured_at : acc),
      "",
    );

    const sourceUrls = diffs
      .map((d) => d.source_url)
      .filter((u): u is string => Boolean(u));

    let summary: string | undefined;
    const disclaimers: string[] = [];

    if (input.summarize && this.options.llm && diffs.length > 0) {
      // Reference stub — a production fork would batch the diffs into a
      // single prompt and stream the summary back. Customer pays Anthropic
      // for these tokens; jpcite operator does NOT proxy.
      //
      //   const prompt = renderDiffPrompt(diffs);
      //   const stream = this.options.llm({ prompt });
      //   for await (const msg of stream) summary = collect(msg);
      //
      // The disclaimer is appended unconditionally when summarize is on, so
      // downstream UIs render it even if the LLM call yielded an empty string.
      disclaimers.push(
        "本要約は法令本文の機械要約であり、§52 に基づく税理士助言・行政書士法 §1 に基づく書面作成では" +
          "ありません。最終判断は専門家にご相談ください。",
      );
    }

    const evidence = this.jpcite.buildEvidence(sourceUrls, { disclaimers });

    const out: LawAmendmentWatchOutput = {
      diffs,
      total: page.total,
      limit: page.limit,
      offset: page.offset,
      next_watermark,
      evidence,
    };
    if (summary !== undefined) out.summary = summary;
    return out;
  }
}
