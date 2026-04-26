/**
 * 01_search_subsidies_by_prefecture.ts
 * -------------------------------------
 * Top-10 S / A tier programs in 青森県 with amount_max_man_yen >= 500,
 * printed as a markdown table. TypeScript / ESM / Node 20+.
 *
 * When the TS SDK is published, replace the `fetch` call with:
 *
 *     import { Client } from "@autonomath/client";
 *     const c = new Client({ apiKey: process.env.AUTONOMATH_API_KEY });
 *     const data = await c.searchPrograms({ prefecture: "青森県", tier: ["S", "A"], amount_min: 500, limit: 10 });
 *
 * env vars:
 *   JPINTEL_API_KEY   (optional)
 *   JPINTEL_API_BASE  (default: http://localhost:8080)
 *
 * run:
 *   npm install
 *   npx tsx 01_search_subsidies_by_prefecture.ts
 *
 * expected output (real, against live stub):
 *
 *   | tier | 制度名 | 上限 (万円) | 所轄 |
 *   | ---- | ------ | ----------- | ---- |
 *   | S | 経営発展支援事業 | 1000 | 青森県つがる市 |
 *   | A | PREF-02-101_青森_所得向上プログラム実践支援事業 | 1000 |  |
 *   | A | 青森 スマート農業機械導入支援事業 | 1250 | 都道府県 |
 *   total matches: 3
 */

const API_BASE = process.env.JPINTEL_API_BASE ?? "http://localhost:8080";
const API_KEY = process.env.JPINTEL_API_KEY;

type ProgramRow = {
  unified_id: string;
  primary_name: string;
  tier: string | null;
  authority_name: string | null;
  amount_max_man_yen: number | null;
};

type SearchResponse = {
  total: number;
  limit: number;
  offset: number;
  results: ProgramRow[];
};

async function fetchTopPrograms(
  prefecture: string,
  amountMin: number,
  limit = 10,
): Promise<ProgramRow[]> {
  const qs = new URLSearchParams();
  qs.append("prefecture", prefecture);
  qs.append("tier", "S");
  qs.append("tier", "A");
  qs.append("amount_min", String(amountMin));
  qs.append("limit", String(limit));

  const headers: Record<string, string> = { Accept: "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/v1/programs/search?${qs.toString()}`, { headers });
  } catch (err) {
    console.error(`ERROR: transport failure contacting ${API_BASE}: ${(err as Error).message}`);
    process.exit(2);
  }

  if (resp.status === 401) {
    console.error("ERROR: 401 Unauthorized — set JPINTEL_API_KEY or omit for free tier");
    process.exit(1);
  }
  if (resp.status === 429) {
    console.error(`ERROR: 429 rate limit — retry after ${resp.headers.get("Retry-After") ?? "?"}s`);
    process.exit(1);
  }
  if (resp.status >= 500) {
    console.error(`ERROR: server ${resp.status} — try again or check ${API_BASE}/healthz`);
    process.exit(1);
  }
  if (!resp.ok) {
    const body = await resp.text();
    console.error(`ERROR: ${resp.status} ${body}`);
    process.exit(1);
  }

  const data = (await resp.json()) as SearchResponse;
  return data.results;
}

function toMarkdown(rows: ProgramRow[]): string {
  const lines = ["| tier | 制度名 | 上限 (万円) | 所轄 |", "| ---- | ------ | ----------- | ---- |"];
  for (const r of rows) {
    const name = (r.primary_name ?? "").replaceAll("|", "/");
    const authority = (r.authority_name ?? "").replaceAll("|", "/");
    lines.push(`| ${r.tier} | ${name} | ${r.amount_max_man_yen ?? ""} | ${authority} |`);
  }
  return lines.join("\n");
}

async function main(): Promise<void> {
  const rows = await fetchTopPrograms("青森県", 500, 10);
  console.log(toMarkdown(rows));
  console.log(`total matches: ${rows.length}`);
}

main().catch((err) => {
  console.error("unhandled error:", err);
  process.exit(2);
});

// Marker to force TS to treat this as a module (no cross-file symbol collisions).
export {};
