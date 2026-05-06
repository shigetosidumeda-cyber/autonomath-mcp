# @jpcite/agents

Reference [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) agents
for the [jpcite](https://jpcite.com) Japanese institutional-program API.

Five fork-and-customize starter agents:

| Agent                     | File                                | Purpose                           |
| ------------------------- | ----------------------------------- | --------------------------------- |
| `SubsidyMatchAgent`       | `src/agents/subsidy_match.ts`       | 補助金マッチング                  |
| `InvoiceCheckAgent`       | `src/agents/invoice_check.ts`       | 適格事業者照合                    |
| `LawAmendmentWatchAgent`  | `src/agents/law_amendment_watch.ts` | 法令改正監視                      |
| `KessanBriefAgent`        | `src/agents/kessan_brief.ts`        | 月次/四半期 決算 briefing         |
| `DueDiligenceAgent`       | `src/agents/due_diligence.ts`       | DD 質問生成 (M&A scaffold)        |

## Cost model

These agents call the **customer's** Claude key for any LLM reasoning. The
jpcite operator (Bookyou株式会社, T8010001213708) does **not** proxy LLM
calls and does **not** charge for LLM tokens. You pay:

- **Anthropic** — for Claude tokens, billed to the API key on your `LlmQuery`.
- **jpcite** — ¥3/req (税込 ¥3.30) for the underlying data API. Anonymous
  callers get 3 req/day per IP (JST 翌日 00:00 リセット).

Two of the five agents (`InvoiceCheckAgent`, `LawAmendmentWatchAgent`) work
without any LLM at all — they are pure data orchestrators.

## Install

```bash
npm install @jpcite/agents @jpcite/sdk @anthropic-ai/claude-agent-sdk
```

`@jpcite/sdk` is required. `@anthropic-ai/claude-agent-sdk` is optional —
only needed if you wire the `llm` callable into one of the three agents that
support optional LLM reasoning (`SubsidyMatchAgent`, `LawAmendmentWatchAgent`,
`KessanBriefAgent`, `DueDiligenceAgent`).

Node.js `>=20` required (relies on global `fetch`).

## Quickstart — SubsidyMatchAgent

```ts
import { JpciteClient, SubsidyMatchAgent } from "@jpcite/agents";

const jpcite = new JpciteClient({ apiKey: process.env.JPCITE_API_KEY });
const agent = new SubsidyMatchAgent(jpcite);

const out = await agent.run({
  houjin_bangou: "8010001213708", // Bookyou株式会社 (test fixture)
  amount_min_man_yen: 100,
  tier: ["S", "A"],
  limit: 10,
});

console.log(`Matched ${out.programs.length} programs`);
for (const p of out.programs.slice(0, 3)) {
  console.log(`- [${p.tier}] ${p.primary_name} (score ${p.score.toFixed(2)})`);
  console.log(`  source: ${p.source_url}`);
  if (p.adoption_stats) {
    console.log(
      `  採択率 ${(p.adoption_stats.adoption_rate ?? 0) * 100}% ` +
        `(${p.adoption_stats.total_adopted}/${p.adoption_stats.total_applications})`,
    );
  }
}
console.log("Disclaimers:", out.evidence.disclaimers);
```

## Plugging in Claude Agent SDK

Three of the five agents (`SubsidyMatchAgent`, `LawAmendmentWatchAgent`,
`KessanBriefAgent`, `DueDiligenceAgent`) accept an optional `llm` callable so
they can rerank, summarize, or rephrase. The expected shape matches `query`
from `@anthropic-ai/claude-agent-sdk`:

```ts
import { query } from "@anthropic-ai/claude-agent-sdk";
import { JpciteClient, KessanBriefAgent } from "@jpcite/agents";

const jpcite = new JpciteClient({ apiKey: process.env.JPCITE_API_KEY });
const agent = new KessanBriefAgent(jpcite, { llm: query });

const brief = await agent.run({
  houjin_bangou: "8010001213708",
  fy_start: "2025-04-01",
  fy_end: "2026-03-31",
  narrate: true, // → triggers customer-side LLM call
});
```

## Examples

The `examples/` directory has one runnable script per agent:

- `examples/subsidy_match.ts`
- `examples/invoice_check.ts`
- `examples/law_amendment_watch.ts`
- `examples/kessan_brief.ts`
- `examples/due_diligence.ts`

```bash
npx tsx examples/subsidy_match.ts
```

## Forking

Every agent file is < 250 lines and all jpcite calls go through `JpciteClient`
in `src/lib/jpcite_client.ts`. Recommended fork pattern:

1. Copy the agent file under your own namespace.
2. Adjust the `Input` / `Output` types to your domain.
3. Swap or remove the LLM stub (the `if (this.options.llm) { … }` block).
4. Keep the `EvidencePacket` contract — it's load-bearing for §52 / 行政書士法
   §1 compliance and is consumed by audit-log dashboards downstream.

`JpciteClient` also exposes the REST Evidence Packet, composite intel, and
`funding_stack` helpers for custom agents. `funding_stack.next_actions` values
are action objects (`action_id`, `label_ja`, `detail_ja`, `reason`,
`source_fields`).

## Publishing (operator)

`@jpcite/agents` is published to npm by the
[`sdk-publish-agents.yml`](../../.github/workflows/sdk-publish-agents.yml)
GitHub Actions workflow. Triggered by:

- **tag push** matching `agents-v*` (canonical release event), e.g.
  ```bash
  git tag agents-v0.1.0 && git push --tags
  ```
- **manual** `workflow_dispatch` from the Actions UI (re-run on demand).

The workflow uses npm **OIDC trusted publishing** (no long-lived token
required) plus `--provenance` for a SLSA supply-chain attestation. If the
`NPM_TOKEN` secret is configured it is consumed as a fallback; otherwise the
OIDC path is auto-selected by the npm CLI.

Local smoke test (does not publish):

```bash
cd sdk/agents
npm ci && npm run build && npm pack --dry-run
```

## License

MIT — see `LICENSE`. Program metadata returned by the underlying API is
governed separately by Bookyou株式会社's terms at
<https://jpcite.com/tos.html>.
