// examples/kessan_brief.ts
//
// Run: JPCITE_API_KEY=jp_live_… npx tsx examples/kessan_brief.ts
//
// Builds a 月次/四半期 決算 briefing for a given 法人番号 + FY window.

import { JpciteClient, KessanBriefAgent } from "@jpcite/agents";

async function main(): Promise<void> {
  const jpcite = new JpciteClient({
    apiKey: process.env["JPCITE_API_KEY"],
    userAgentSuffix: "example/kessan_brief",
  });

  const agent = new KessanBriefAgent(jpcite);

  const out = await agent.run({
    houjin_bangou: process.env["HOUJIN_BANGOU"] ?? "8010001213708",
    fy_start: "2025-04-01",
    fy_end: "2026-03-31",
  });

  console.log(`=== Kessan briefing for ${out.houjin.trade_name ?? out.houjin.houjin_bangou} ===`);
  console.log(`Prefecture: ${out.houjin.prefecture}`);
  console.log(`Invoice registered: ${out.houjin.invoice_registered}`);

  console.log(`\nProgram changes (${out.program_changes.length}):`);
  for (const c of out.program_changes.slice(0, 5)) {
    console.log(`  [${c.change_kind}] ${c.program_name}`);
  }

  console.log(`\nLaw amendments in window (${out.law_amendments.length}):`);
  for (const d of out.law_amendments.slice(0, 5)) {
    console.log(`  ${d.law_name} (${d.diff_kind})`);
  }

  console.log(`\nSunset alerts (${out.sunset_alerts.length}):`);
  for (const t of out.sunset_alerts.slice(0, 5)) {
    console.log(`  ${t.rule_name} → sunset ${t.sunset_date}`);
  }

  console.log(`\nEnforcement hits in window: ${out.enforcement_hits.length}`);

  console.log(`\nEvidence:`);
  console.log(`  source_urls: ${out.evidence.source_urls.length}`);
  if (out.evidence.corpus_snapshot_id) {
    console.log(`  snapshot:    ${out.evidence.corpus_snapshot_id}`);
  }
  for (const d of out.evidence.disclaimers) console.log(`  - ${d}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
