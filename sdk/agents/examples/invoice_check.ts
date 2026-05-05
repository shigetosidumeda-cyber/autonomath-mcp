// examples/invoice_check.ts
//
// Run: JPCITE_API_KEY=jp_live_… npx tsx examples/invoice_check.ts
//
// Bulk-verifies a small set of 法人番号 against the NTA 適格事業者 corpus.
// Pure data; no Claude / LLM calls anywhere.

import { InvoiceCheckAgent, JpciteClient } from "@jpcite/agents";

async function main(): Promise<void> {
  const jpcite = new JpciteClient({
    apiKey: process.env["JPCITE_API_KEY"],
    userAgentSuffix: "example/invoice_check",
  });

  const agent = new InvoiceCheckAgent(jpcite);

  const out = await agent.run({
    rows: [
      {
        row_id: "INV-2026-001",
        houjin_bangou: "8010001213708",
        invoice_date: "2026-04-30",
      },
      {
        row_id: "INV-2026-002",
        houjin_bangou: "0000000000000", // unknown
        invoice_date: "2026-04-30",
      },
      {
        row_id: "INV-2026-003",
        houjin_bangou: "abc-not-a-number", // malformed
      },
    ],
  });

  for (const r of out.results) {
    console.log(
      `${r.row_id} (${r.houjin_bangou}) → ${r.verdict}` +
        (r.registration_no ? ` [${r.registration_no}]` : ""),
    );
  }

  console.log("\nSummary:", out.summary);
  console.log(`Source URLs: ${out.evidence.source_urls.length}`);
  for (const d of out.evidence.disclaimers) console.log(`  - ${d}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
