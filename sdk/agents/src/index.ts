// @jpcite/agents — reference Claude Agent SDK agents for the jpcite REST + MCP API.
//
// Five fork-and-customize agents:
//   * SubsidyMatchAgent       (subsidy_match.ts)       — 補助金マッチング
//   * InvoiceCheckAgent       (invoice_check.ts)       — 適格請求書発行事業者照合
//   * LawAmendmentWatchAgent  (law_amendment_watch.ts) — 法令改正監視
//   * KessanBriefAgent        (kessan_brief.ts)        — 月次/四半期 決算 briefing
//   * DueDiligenceAgent       (due_diligence.ts)       — DD 質問生成
//
// Each agent:
//   - Owns its prompt + JSON schema + tool budget.
//   - Talks to https://api.jpcite.com via JpciteClient (REST + optional MCP spawn).
//   - Optionally delegates LLM reasoning to a customer-supplied `LlmQuery` callable
//     (typically `query` from `@anthropic-ai/claude-agent-sdk`). The jpcite operator
//     pays ¥0 LLM cost — every Claude token is billed to the customer's Anthropic key.
//
// Quickstart:
//
//   import { JpciteClient, SubsidyMatchAgent } from "@jpcite/agents";
//
//   const jpcite = new JpciteClient({ apiKey: process.env.JPCITE_API_KEY });
//   const agent = new SubsidyMatchAgent(jpcite);
//   const out = await agent.run({ houjin_bangou: "8010001213708" });
//   console.log(out.programs.length, out.evidence.source_urls.length);

export { JpciteClient } from "./lib/jpcite_client.js";
export type {
  EvidencePacket,
  Houjin360Snapshot,
  JpciteClientOptions,
  LawAmendmentDiff,
  ProgramAdoptionStats,
  ProgramRecommendation,
} from "./lib/jpcite_client.js";

export {
  SubsidyMatchAgent,
  type SubsidyMatchInput,
  type SubsidyMatchOutput,
} from "./agents/subsidy_match.js";

export {
  InvoiceCheckAgent,
  type InvoiceCheckInput,
  type InvoiceCheckOutput,
} from "./agents/invoice_check.js";

export {
  LawAmendmentWatchAgent,
  type LawAmendmentWatchInput,
  type LawAmendmentWatchOutput,
} from "./agents/law_amendment_watch.js";

export {
  KessanBriefAgent,
  type KessanBriefInput,
  type KessanBriefOutput,
} from "./agents/kessan_brief.js";

export {
  DueDiligenceAgent,
  type DueDiligenceInput,
  type DueDiligenceOutput,
} from "./agents/due_diligence.js";

/**
 * Minimal callable shape for an LLM query. Compatible with `query` exported
 * by `@anthropic-ai/claude-agent-sdk`:
 *
 *   import { query } from "@anthropic-ai/claude-agent-sdk";
 *   new SubsidyMatchAgent(jpcite, { llm: query });
 *
 * Kept structural so the agents do not hard-depend on the Claude Agent SDK
 * at compile time. Agents that do not need free-form LLM reasoning (e.g.
 * `InvoiceCheckAgent`) ignore this.
 */
export type LlmQuery = (params: {
  prompt: string;
  options?: Record<string, unknown>;
}) => AsyncIterable<unknown>;
