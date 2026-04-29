// 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
//
// 税務会計AI — JavaScript / Node.js quickstart
// ----------------------------------------------------------
// Run: `node quickstart.js`  (Node 18+; uses built-in fetch, zero deps)
// Set ZEIMU_KAIKEI_API_KEY=sk_xxx to use a paid key (¥3/req).
// Without a key, runs anonymous: 50 req/月 per IP, JST 月初リセット.

const BASE_URL = "https://api.zeimu-kaikei.ai/v1";
const API_KEY = process.env.ZEIMU_KAIKEI_API_KEY || null;

async function call(path, params = {}) {
  const url = new URL(BASE_URL + path);
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
    else if (v !== null && v !== undefined) url.searchParams.set(k, String(v));
  }
  const headers = { Accept: "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  const res = await fetch(url, { headers });
  if (res.status === 401) throw new Error("auth failed: check ZEIMU_KAIKEI_API_KEY");
  if (res.status === 429) {
    const retry = res.headers.get("retry-after") || "?";
    throw new Error(`rate limited; retry-after=${retry}s (anonymous tier = 50/月)`);
  }
  if (res.status >= 500) throw new Error(`server error ${res.status}: try again later`);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

async function main() {
  console.log("[1] Search programs: q=省エネ tier=S,A limit=3");
  const programs = await call("/programs/search", { q: "省エネ", tier: ["S", "A"], limit: 3 });
  console.log(`    total hits: ${programs.total}`);
  for (const p of programs.results) {
    console.log(`    - ${p.unified_id}  [${p.tier}]  ${p.primary_name}`);
  }

  console.log("\n[2] List tax incentives (中小企業税制): limit=3");
  const tax = await call("/tax_rulesets/search", { q: "中小企業", limit: 3 });
  console.log(`    total hits: ${tax.total}`);
  for (const r of tax.results) {
    console.log(`    - ${r.unified_id}  [${r.ruleset_kind}]  ${r.ruleset_name}`);
  }

  console.log("\nMode:", API_KEY ? "authenticated (¥3/req)" : "anonymous (50/月 free)");
}

main().catch((e) => {
  console.error("ERROR:", e.message);
  process.exit(1);
});
