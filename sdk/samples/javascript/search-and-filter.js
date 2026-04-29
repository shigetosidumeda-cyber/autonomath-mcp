// 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
//
// 税務会計AI — Node.js paginated search + filter chain
// ----------------------------------------------------------
// Run: `node search-and-filter.js`  (Node 18+; zero deps)
// Demonstrates:
//   - paginating /v1/programs/search with limit/offset
//   - filtering by tier + prefecture + funding_purpose
//   - per-page error handling with HTTP 401/429/5xx coverage

const BASE_URL = "https://api.zeimu-kaikei.ai/v1";
const API_KEY = process.env.ZEIMU_KAIKEI_API_KEY || null;
const PAGE_SIZE = 20;
const MAX_PAGES = 3; // cap so anonymous tier doesn't burn all 50/月

function describeError(status, body) {
  if (status === 401) return "auth failed: ZEIMU_KAIKEI_API_KEY missing or invalid";
  if (status === 403) return "forbidden: key revoked or quota exhausted";
  if (status === 429) return "rate limited (anon = 50/月; auth = burst limit)";
  if (status === 404) return "not found: check unified_id or path";
  if (status >= 500) return `server error ${status}: try again later`;
  return `HTTP ${status}: ${body}`;
}

async function call(path, params = {}, attempt = 0) {
  const url = new URL(BASE_URL + path);
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
    else if (v !== null && v !== undefined) url.searchParams.set(k, String(v));
  }
  const headers = { Accept: "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  const res = await fetch(url, { headers });

  if (res.status === 429 && attempt < 2) {
    const retry = parseInt(res.headers.get("retry-after") || "1", 10);
    console.warn(`    retry in ${retry}s ...`);
    await new Promise((r) => setTimeout(r, retry * 1000));
    return call(path, params, attempt + 1);
  }
  if (res.status >= 500 && attempt < 2) {
    const wait = 0.5 * 2 ** attempt;
    console.warn(`    server ${res.status}, backing off ${wait}s`);
    await new Promise((r) => setTimeout(r, wait * 1000));
    return call(path, params, attempt + 1);
  }
  if (!res.ok) throw new Error(describeError(res.status, await res.text()));
  return res.json();
}

async function* paginate(path, baseParams) {
  let offset = 0;
  for (let page = 0; page < MAX_PAGES; page++) {
    const data = await call(path, { ...baseParams, limit: PAGE_SIZE, offset });
    yield data;
    if (data.results.length < PAGE_SIZE) return; // last page
    if (offset + PAGE_SIZE >= data.total) return;
    offset += PAGE_SIZE;
  }
}

async function main() {
  // Filter chain: keyword + tier S/A (broad enough that anonymous tier
  // sees pagination kick in; tighten with prefecture / funding_purpose
  // for narrower queries).
  const filters = {
    q: "省エネ",
    tier: ["S", "A"],
  };
  console.log("Filters:", JSON.stringify(filters));
  console.log("API base:", BASE_URL);
  console.log("Auth:", API_KEY ? "authenticated" : "anonymous");
  console.log("");

  let pageNum = 0;
  let totalSeen = 0;
  for await (const page of paginate("/programs/search", filters)) {
    pageNum++;
    console.log(`--- page ${pageNum} (offset=${(pageNum - 1) * PAGE_SIZE}, total=${page.total}) ---`);
    for (const p of page.results) {
      const amt = p.amount_max_man_yen ? `${p.amount_max_man_yen}万円` : "金額未定";
      console.log(`  ${p.unified_id} [${p.tier}] ${amt}  ${p.primary_name.slice(0, 50)}`);
    }
    totalSeen += page.results.length;
  }
  console.log(`\nFetched ${totalSeen} programs across ${pageNum} page(s).`);
  if (API_KEY) console.log(`Cost: ${pageNum} req × ¥3 = ¥${pageNum * 3} (税抜)`);
}

main().catch((e) => {
  console.error("ERROR:", e.message);
  process.exit(1);
});
