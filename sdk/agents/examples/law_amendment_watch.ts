// examples/law_amendment_watch.ts
//
// Run: JPCITE_API_KEY=jp_live_… npx tsx examples/law_amendment_watch.ts
//
// Polls for law amendment diffs since the last watermark. Persist
// `next_watermark` between runs to avoid re-processing the same diffs.

import { JpciteClient, LawAmendmentWatchAgent } from "@jpcite/agents";

async function main(): Promise<void> {
  const jpcite = new JpciteClient({
    apiKey: process.env["JPCITE_API_KEY"],
    userAgentSuffix: "example/law_amendment_watch",
  });

  const agent = new LawAmendmentWatchAgent(jpcite);

  // First-run watermark = 7 days ago. Production callers should persist
  // `next_watermark` to disk / DB and feed it back here.
  const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

  const out = await agent.run({
    since,
    limit: 50,
  });

  console.log(
    `Found ${out.diffs.length} of ${out.total} amendments since ${since}`,
  );
  for (const d of out.diffs.slice(0, 10)) {
    console.log(
      `[${d.diff_kind}] ${d.law_name} ` +
        (d.article_number ? `art.${d.article_number} ` : "") +
        `(captured ${d.captured_at}` +
        (d.effective_from ? `, effective ${d.effective_from}` : "") +
        ")",
    );
  }

  console.log(`\nNext watermark: ${out.next_watermark}`);
  console.log(`Source URLs: ${out.evidence.source_urls.length}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
