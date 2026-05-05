// examples/subsidy_match.ts
//
// Run: JPCITE_API_KEY=jp_live_… npx tsx examples/subsidy_match.ts
//
// Prints the top-10 subsidy candidates for a given 法人番号. Demonstrates
// passing the SubsidyMatchAgent without an LLM (pure data orchestration).

import { JpciteClient, SubsidyMatchAgent } from "@jpcite/agents";

async function main(): Promise<void> {
  const jpcite = new JpciteClient({
    apiKey: process.env["JPCITE_API_KEY"],
    userAgentSuffix: "example/subsidy_match",
  });

  const agent = new SubsidyMatchAgent(jpcite);

  const out = await agent.run({
    houjin_bangou: process.env["HOUJIN_BANGOU"] ?? "8010001213708",
    tier: ["S", "A", "B"],
    limit: 10,
    enrich_top_3: true,
  });

  console.log(`Matched ${out.programs.length} programs`);
  for (const p of out.programs) {
    const stats = p.adoption_stats
      ? ` 採択率 ${((p.adoption_stats.adoption_rate ?? 0) * 100).toFixed(1)}%`
      : "";
    console.log(
      `[${p.tier}] (${p.score.toFixed(2)}) ${p.primary_name}${stats}`,
    );
    if (p.source_url) console.log(`  ${p.source_url}`);
  }

  console.log("\nEvidence:");
  console.log(`  queried_at: ${out.evidence.queried_at}`);
  console.log(`  source_urls: ${out.evidence.source_urls.length}`);
  for (const d of out.evidence.disclaimers) console.log(`  - ${d}`);

  console.log(`\nNext-call hints: ${out.evidence_packets.length}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
