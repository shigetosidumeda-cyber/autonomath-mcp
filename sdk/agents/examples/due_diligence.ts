// examples/due_diligence.ts
//
// Run: JPCITE_API_KEY=jp_live_… npx tsx examples/due_diligence.ts
//
// Generates a DD question deck for an M&A target 法人. Outputs the deck
// scaffold + provenance — never a draft 申請書面 (行政書士法 §1 boundary).

import { DueDiligenceAgent, JpciteClient } from "@jpcite/agents";

async function main(): Promise<void> {
  const jpcite = new JpciteClient({
    apiKey: process.env["JPCITE_API_KEY"],
    userAgentSuffix: "example/due_diligence",
  });

  const agent = new DueDiligenceAgent(jpcite);

  const out = await agent.run({
    houjin_bangou: process.env["HOUJIN_BANGOU"] ?? "8010001213708",
    severity_min: 2,
    categories: ["credit", "tax", "invoice_compliance", "enforcement"],
    limit: 30,
  });

  console.log(`=== DD deck for ${out.target.trade_name ?? out.target.houjin_bangou} ===`);
  console.log(`Prefecture: ${out.target.prefecture}`);
  console.log(`JSIC: ${out.target.jsic_major}`);
  console.log(`Invoice registered: ${out.target.invoice_registered}`);
  console.log(`Jurisdiction mismatch: ${out.target.jurisdiction_mismatch}`);
  console.log(
    `\nQuestions: ${out.questions.length} of ${out.total_templates_considered} templates considered\n`,
  );

  for (const q of out.questions.slice(0, 10)) {
    console.log(`[sev ${q.severity}] (${q.category}) ${q.question}`);
    console.log(`  trigger: ${q.trigger_reason}`);
    if (q.request_documents.length > 0) {
      console.log(`  request: ${q.request_documents.join(", ")}`);
    }
  }

  console.log(`\nEvidence URLs: ${out.evidence.source_urls.length}`);
  for (const d of out.evidence.disclaimers) console.log(`  - ${d}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
