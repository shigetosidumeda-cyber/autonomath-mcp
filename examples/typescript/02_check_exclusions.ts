/**
 * 02_check_exclusions.ts
 * -----------------------
 * Given 4 program IDs, detect which cannot be co-applied and why. Matches
 * the Python 02 example 1:1 so you can compare idiomatic Node vs Python.
 *
 * When the TS SDK is published, replace the `fetch` call with:
 *
 *     import { Client } from "@autonomath/client";
 *     const c = new Client({ apiKey: process.env.AUTONOMATH_API_KEY });
 *     const data = await c.checkExclusions(candidates);
 *
 * env vars:
 *   JPINTEL_API_KEY   (optional)
 *   JPINTEL_API_BASE  (default: http://localhost:8080)
 *
 * run:
 *   npm install
 *   npx tsx 02_check_exclusions.ts
 *
 * expected output:
 *
 *   Checking 4 programs: keiei-kaishi-shikin, koyo-shuno-shikin, seinen-shuno-shikin, super-L-shikin
 *
 *   [1] absolute  (critical)  rule=excl-keiei-kaishi-vs-koyo-shuno-absolute
 *       programs: keiei-kaishi-shikin + koyo-shuno-shikin
 *       reason:   経営開始資金は、雇用就農資金や他の雇用就農者を対象とした実践研修支援事業による助成金との併用不可。...
 *   [2] prerequisite  (critical)  rule=excl-seinen-requires-cert-new-farmer
 *       programs: seinen-shuno-shikin
 *       reason:   青年等就農資金を借りるには、市町村から認定新規就農者の認定を受けていることが前提。認定前に融資申請しても審査は開始されない。...
 *   [3] prerequisite  (critical)  rule=excl-super-L-requires-cert-farmer
 *       programs: super-L-shikin
 *       reason:   スーパーL資金を借りるには、市町村から認定農業者の認定を受けていることが前提。認定新規就農者では申請不可 (別制度)。...
 *   [4] entity_scope_restriction  (critical)  rule=excl-corp-established-vs-new-farmer-programs
 *       programs: keiei-kaishi-shikin + koyo-shuno-shikin + seinen-shuno-shikin
 *       reason:   経営開始から5年以上経過した100ha級の法人農家は、新規就農者向け制度 (経営開始資金・青年等就農資金・就農準備資金・新規就農チャレンジ等...
 *
 *   total hits: 4 / rules_checked: 35
 */

const API_BASE = process.env.JPINTEL_API_BASE ?? "http://localhost:8080";
const API_KEY = process.env.JPINTEL_API_KEY;

type ExclusionHit = {
  rule_id: string;
  kind: string;
  severity: string | null;
  programs_involved: string[];
  description: string | null;
  source_urls: string[];
};

type CheckResponse = {
  program_ids: string[];
  hits: ExclusionHit[];
  checked_rules: number;
};

async function checkExclusions(programIds: string[]): Promise<CheckResponse> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/v1/exclusions/check`, {
      method: "POST",
      headers,
      body: JSON.stringify({ program_ids: programIds }),
    });
  } catch (err) {
    console.error(`ERROR: transport failure: ${(err as Error).message}`);
    process.exit(2);
  }

  if (resp.status === 401) {
    console.error("ERROR: 401 — invalid key");
    process.exit(1);
  }
  if (resp.status === 429) {
    console.error(`ERROR: 429 rate limit, retry after ${resp.headers.get("Retry-After") ?? "?"}s`);
    process.exit(1);
  }
  if (resp.status >= 500) {
    console.error(`ERROR: server ${resp.status}`);
    process.exit(1);
  }
  if (!resp.ok) {
    const body = await resp.text();
    console.error(`ERROR: ${resp.status} ${body}`);
    process.exit(1);
  }

  return (await resp.json()) as CheckResponse;
}

async function main(): Promise<void> {
  const candidates = [
    "keiei-kaishi-shikin",
    "koyo-shuno-shikin",
    "seinen-shuno-shikin",
    "super-L-shikin",
  ];

  console.log(`Checking ${candidates.length} programs: ${candidates.join(", ")}`);
  console.log();

  const data = await checkExclusions(candidates);
  data.hits.forEach((h, i) => {
    const progs = h.programs_involved.join(" + ");
    const reason = (h.description ?? "").replaceAll("\n", " ").slice(0, 70);
    console.log(`[${i + 1}] ${h.kind}  (${h.severity ?? "-"})  rule=${h.rule_id}`);
    console.log(`    programs: ${progs}`);
    console.log(`    reason:   ${reason}...`);
  });

  console.log();
  console.log(`total hits: ${data.hits.length} / rules_checked: ${data.checked_rules}`);
}

main().catch((err) => {
  console.error("unhandled error:", err);
  process.exit(2);
});

// Marker to force TS to treat this as a module.
export {};
