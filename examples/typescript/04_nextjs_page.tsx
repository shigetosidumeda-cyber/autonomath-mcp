/**
 * 04_nextjs_page.tsx
 * ------------------
 * Next.js 14 app-router **server component** that fetches jpintel top
 * matches server-side and renders them. The key never reaches the browser.
 *
 * Placement in a real app:
 *     app/subsidies/aomori/page.tsx
 *
 * Why a server component: the API key MUST NOT be exposed in client JS.
 * With `"use server"` files / RSC, the fetch runs on the Node runtime,
 * the HTML streams to the browser, the key stays in the server env.
 *
 * When the TS SDK is published, swap the `fetch` for:
 *     import { Client } from "@autonomath/client";
 *     const c = new Client({ apiKey: process.env.JPCITE_API_KEY });
 *     const data = await c.searchPrograms({ prefecture: "青森県", tier: ["S","A"], limit: 10 });
 *
 * env vars (set in .env.local; do NOT prefix with NEXT_PUBLIC_):
 *   JPINTEL_API_KEY     (required in production, optional for dev)
 *   JPINTEL_API_BASE    (default: https://api.jpcite.com)
 *
 * run (inside a Next 14+ project):
 *   npm install next react react-dom
 *   # copy this file to app/subsidies/aomori/page.tsx
 *   npm run dev
 *   # open http://localhost:3000/subsidies/aomori
 *
 * This file is self-contained — it typechecks against `next` + `react` types
 * (declared as optional peerDeps in package.json).
 *
 * expected rendered HTML (abridged):
 *
 *   <h1>青森県 — S/A-tier 補助金 Top 10</h1>
 *   <p>全 3 件 (最終更新: 2026-04-22T...)</p>
 *   <ul>
 *     <li><strong>S</strong> 経営発展支援事業 — 最大 1000 万円
 *         <a href="https://www.city.tsugaru.aomori.jp/...">公式</a></li>
 *     <li><strong>A</strong> PREF-02-101_青森_所得向上プログラム実践支援事業 — 最大 1000 万円</li>
 *     <li><strong>A</strong> 青森 スマート農業機械導入支援事業 — 最大 1250 万円</li>
 *   </ul>
 */

// Next.js app-router directive — tells the runtime this file is React 19 RSC.
// When `next` isn't installed in this examples/ sandbox, this file still
// typechecks as standard TSX under ES2022.
export const dynamic = "force-dynamic";

type Program = {
  unified_id: string;
  primary_name: string;
  tier: string | null;
  amount_max_man_yen: number | null;
  official_url: string | null;
  authority_name: string | null;
};

type SearchResponse = {
  total: number;
  results: Program[];
};

async function searchAomori(): Promise<SearchResponse | { error: string }> {
  const base = process.env.JPINTEL_API_BASE ?? "https://api.jpcite.com";
  const key = process.env.JPINTEL_API_KEY;

  const qs = new URLSearchParams();
  qs.append("prefecture", "青森県");
  qs.append("tier", "S");
  qs.append("tier", "A");
  qs.append("amount_min", "500");
  qs.append("limit", "10");

  const headers: Record<string, string> = { Accept: "application/json" };
  if (key) headers["X-API-Key"] = key;

  try {
    // `cache: 'no-store'` so each request re-fetches — tune to your retention
    // SLA. Switch to `next: { revalidate: 3600 }` for ISR with 1h freshness.
    const resp = await fetch(`${base}/v1/programs/search?${qs.toString()}`, {
      headers,
      cache: "no-store",
    });

    if (resp.status === 401) return { error: "401: JPINTEL_API_KEY invalid or revoked" };
    if (resp.status === 429) {
      const retry = resp.headers.get("Retry-After") ?? "?";
      return { error: `429: rate limit exceeded, retry in ${retry}s` };
    }
    if (resp.status >= 500) return { error: `${resp.status}: upstream server error` };
    if (!resp.ok) return { error: `${resp.status}: ${await resp.text()}` };

    return (await resp.json()) as SearchResponse;
  } catch (err) {
    return { error: `transport: ${(err as Error).message}` };
  }
}

export default async function AomoriSubsidiesPage(): Promise<JSX.Element> {
  const data = await searchAomori();

  if ("error" in data) {
    return (
      <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
        <h1>青森県 — S/A-tier 補助金 Top 10</h1>
        <p style={{ color: "crimson" }}>データ取得失敗: {data.error}</p>
      </main>
    );
  }

  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui", maxWidth: 800 }}>
      <h1>青森県 — S/A-tier 補助金 Top 10</h1>
      <p>全 {data.total} 件</p>
      <ul>
        {data.results.map((r) => (
          <li key={r.unified_id} style={{ marginBottom: "0.5rem" }}>
            <strong>{r.tier}</strong> {r.primary_name}
            {r.amount_max_man_yen ? ` — 最大 ${r.amount_max_man_yen} 万円` : ""}
            {r.official_url ? (
              <>
                {" "}
                <a href={r.official_url} target="_blank" rel="noreferrer">
                  公式
                </a>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </main>
  );
}

// Minimal JSX namespace for sandbox typecheck (delete when dropped into a real
// Next 14 project — `@types/react` provides this automatically).
declare global {
  namespace JSX {
    interface Element {}
    interface IntrinsicElements {
      [elem: string]: unknown;
    }
  }
}
