/// <reference types="@cloudflare/workers-types" />
/*
 * SSR for /artifacts/{pack_id} - Cloudflare Pages Function.
 *
 * Renders the 7-section dataset artifact view server-side so that:
 *   1. Crawlers (Bing, Perplexity, Google Discover, OpenAI SearchGPT) see
 *      the full text content without executing JS.
 *   2. First-paint latency stays under one round-trip even when the client
 *      device is slow (the API fetch happens on the CF edge close to the
 *      origin, then we ship a fully-rendered HTML doc).
 *   3. The page degrades to a useful "demo" view when the upstream API
 *      cannot be reached - never a blank page.
 *
 * 7 sections (in render order):
 *   1. overview      - pack_id, headline, tier, created_at, billable_units
 *   2. programs      - top compatible programs (補助金・融資・税制 etc.)
 *   3. laws          - related law articles (e-Gov / cc_by_4.0)
 *   4. cases         - adoption / saiketsu case studies
 *   5. enforcement   - 行政処分 records that touch the cohort
 *   6. amendments    - 法改正 / 制度改正 diffs detected in the window
 *   7. provenance    - source_url + content_hash + fetched_at receipts
 *
 * The upstream API (api.jpcite.com/v1/artifacts/{pack_id}) is expected to
 * return a JSON body whose top-level keys match `overview`, `programs`,
 * `laws`, `cases`, `enforcement`, `amendments`, `provenance` - but each
 * section is rendered defensively so a missing key produces an empty
 * placeholder rather than a 500.
 *
 * Caching: 60s edge cache + stale-while-revalidate 1h. Artifacts evolve
 * (amendment cron can mutate the same pack_id) so we don't pin longer.
 */

interface Env {
  ASSETS: Fetcher;
  JPCITE_API_BASE: string;
}

interface ProgramRow {
  program_id?: string;
  title?: string;
  tier?: string;
  fit_pct?: number;
  amount_jpy?: number | null;
  deadline?: string | null;
  source_url?: string;
}

interface LawRow {
  law_id?: string;
  article?: string;
  title?: string;
  body_snippet?: string;
  source_url?: string;
  license?: string;
}

interface CaseRow {
  case_id?: string;
  headline?: string;
  industry?: string;
  amount_jpy?: number | null;
  adopted_year?: number | string;
  source_url?: string;
}

interface EnforcementRow {
  enforcement_id?: string;
  authority?: string;
  action_type?: string;
  houjin_name?: string;
  acted_at?: string;
  source_url?: string;
}

interface AmendmentRow {
  amendment_id?: string;
  subject?: string;
  detected_at?: string;
  effective_from?: string | null;
  diff_summary?: string;
  source_url?: string;
}

interface ProvenanceRow {
  source_url?: string;
  fetched_at?: string;
  content_hash?: string;
  license?: string;
}

interface ArtifactDataset {
  pack_id: string;
  headline?: string;
  tier?: string;
  created_at?: string;
  billable_units_consumed?: number;
  human_review_required?: boolean | { value: boolean; reason?: string };
  overview?: {
    description?: string;
    cohort?: string;
    coverage_summary?: string;
    snapshot_date?: string;
  };
  programs?: ProgramRow[];
  laws?: LawRow[];
  cases?: CaseRow[];
  enforcement?: EnforcementRow[];
  amendments?: AmendmentRow[];
  provenance?: ProvenanceRow[];
}

const PACK_ID_RE = /^[A-Za-z0-9_-]{3,128}$/;

export const onRequest: PagesFunction<Env> = async (context) => {
  const { params, env } = context;
  const pack_id = String(params.pack_id || "").replace(/\.json$/, "");

  // Defensive validation - refuse anything that doesn't look like a pack_id.
  // The pattern is intentionally loose (we don't pin the legacy
  // `jpcite-pack-...` format because Wave 8 onwards uses shorter IDs for
  // the dataset artifact family).
  if (!PACK_ID_RE.test(pack_id)) {
    return new Response("410 Gone (invalid pack_id format)", { status: 410 });
  }

  const api_base = env.JPCITE_API_BASE || "https://api.jpcite.com";
  let artifact: ArtifactDataset | null = null;
  let fetch_error: string | null = null;
  try {
    const res = await fetch(`${api_base}/v1/artifacts/${encodeURIComponent(pack_id)}`, {
      cf: { cacheTtl: 60, cacheEverything: true },
      headers: { Accept: "application/json" },
    });
    if (res.ok) {
      artifact = (await res.json()) as ArtifactDataset;
    } else {
      fetch_error = `upstream HTTP ${res.status}`;
    }
  } catch (e) {
    fetch_error = `upstream fetch threw: ${e instanceof Error ? e.message : String(e)}`;
  }

  // Demo fallback. Mirrors the canonical 7-section shape so the SSR path
  // exercises every section even when the API is unreachable. Marked
  // explicitly so the UI shows the demo banner.
  let is_demo = false;
  if (!artifact) {
    is_demo = true;
    artifact = buildDemo(pack_id, fetch_error);
  }

  const html = renderHtml(artifact, is_demo, fetch_error);

  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=60, stale-while-revalidate=3600",
      "X-Robots-Tag": "index, follow",
      "X-Frame-Options": "SAMEORIGIN",
    },
  });
};

// ---------------------------------------------------------------------------
// HTML render - single string concat, no template engine. Keeps the bundle
// small for the CF Pages Function runtime and avoids a runtime dependency.
// ---------------------------------------------------------------------------

function renderHtml(a: ArtifactDataset, is_demo: boolean, fetch_error: string | null): string {
  const title = a.headline || `Artifact ${a.pack_id}`;
  const desc = `${title} - jpcite artifact (${a.tier || "unknown tier"}, ${a.billable_units_consumed ?? 0} billable units)`;

  const sections = [
    renderOverviewSection(a),
    renderProgramsSection(a.programs || []),
    renderLawsSection(a.laws || []),
    renderCasesSection(a.cases || []),
    renderEnforcementSection(a.enforcement || []),
    renderAmendmentsSection(a.amendments || []),
    renderProvenanceSection(a.provenance || []),
  ].join("\n");

  const human_review =
    typeof a.human_review_required === "object"
      ? Boolean(a.human_review_required && a.human_review_required.value)
      : Boolean(a.human_review_required);

  return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${esc(title)} | jpcite artifact</title>
<meta name="description" content="${esc(desc)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://jpcite.com/artifacts/${esc(a.pack_id)}">
<meta property="og:type" content="article">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="https://jpcite.com/artifacts/${esc(a.pack_id)}">
<meta property="og:image" content="https://jpcite.com/assets/og.png">
<script type="application/ld+json">${jsonLdArticle(a, title, desc)}</script>
<script type="application/ld+json">${jsonLdBreadcrumb(a.pack_id)}</script>
<style>
  :root { --text:#111; --muted:#666; --border:#e5e5e5; --bg:#fafafa; --warn-bg:#fff7e6; --warn-bd:#f5b94a; --accent:#0a4d8c; --ok:#2a7a2a; --ng:#b13a3a; --radius:8px; }
  * { box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Noto Sans JP", "Hiragino Sans", sans-serif; color:var(--text); margin:0; line-height:1.6; background:#fff; }
  header.site { border-bottom:1px solid var(--border); padding:12px 24px; font-size:14px; }
  header.site a { color:var(--muted); text-decoration:none; }
  main { max-width:980px; margin:0 auto; padding:24px; }
  h1 { font-size:24px; margin:0 0 6px; font-weight:700; }
  h2 { font-size:17px; margin:24px 0 12px; padding:6px 0; border-bottom:2px solid var(--text); }
  .meta { color:var(--muted); font-size:13px; margin-bottom:14px; }
  .badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; color:#fff; margin-right:6px; background:var(--accent); }
  .badge.warn { background:var(--warn-bd); color:#3a2a00; }
  .demo-banner { background:#eef; border-left:3px solid #88a; padding:10px 14px; font-size:13px; margin:0 0 14px; border-radius:4px; }
  .warn-banner { background:var(--warn-bg); border:1px solid var(--warn-bd); border-radius:var(--radius); padding:12px 16px; margin:0 0 14px; font-size:14px; }
  section.artifact-section { background:var(--bg); border:1px solid var(--border); border-radius:var(--radius); padding:16px 20px; margin-bottom:16px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td, th { padding:6px 8px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
  th { color:var(--muted); font-weight:500; }
  .empty { color:var(--muted); font-style:italic; font-size:13px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }
  .card { background:#fff; border:1px solid var(--border); border-radius:var(--radius); padding:12px 14px; font-size:13px; }
  .card h3 { font-size:14px; margin:0 0 6px; font-weight:600; }
  .card .row { color:var(--muted); font-size:12px; margin:2px 0; }
  .card a.src { color:var(--accent); font-size:12px; }
  .receipt { font-family:"JetBrains Mono", ui-monospace, monospace; font-size:11px; word-break:break-all; margin:4px 0; padding:4px 8px; background:#fff; border:1px solid var(--border); border-radius:4px; }
  footer.site { margin-top:32px; padding:16px 24px; border-top:1px solid var(--border); font-size:12px; color:var(--muted); }
  footer.site a { color:var(--accent); }
  .actions { margin-top:18px; }
  .actions a { display:inline-block; padding:6px 14px; font-size:13px; background:#fff; border:1px solid var(--border); border-radius:var(--radius); margin-right:6px; color:var(--text); text-decoration:none; }
  .actions a:hover { background:var(--bg); }
</style>
</head>
<body data-pack-id="${esc(a.pack_id)}">

<header class="site"><a href="/">jpcite</a> &rsaquo; <a href="/artifacts">Artifacts</a> &rsaquo; <span>${esc(a.pack_id)}</span></header>

<main>
  ${is_demo ? `<div class="demo-banner">upstream に到達できなかったため demo data を表示しています (pack_id=${esc(a.pack_id)}${fetch_error ? `, reason=${esc(fetch_error)}` : ""})。</div>` : ""}
  ${human_review ? `<div class="warn-banner">human_review_required = true - 本 artifact は士業 (税理士・行政書士・社労士・弁護士) の確認が必要です。最終判断は士業へ。</div>` : ""}

  <h1>${esc(title)}</h1>
  <p class="meta">
    <span class="badge">${esc(a.tier || "unknown")}</span>
    <span>pack_id: ${esc(a.pack_id)}</span>
    &middot;
    <span>created_at: ${esc(a.created_at || "—")}</span>
    &middot;
    <span>billable_units: ${a.billable_units_consumed ?? 0}</span>
  </p>

${sections}

  <div class="actions">
    <a href="/v1/artifacts/${esc(a.pack_id)}.json" rel="noopener">JSON</a>
    <a href="/v1/artifacts/${esc(a.pack_id)}.pdf" rel="noopener">PDF</a>
    <a href="/artifacts/${esc(a.pack_id)}/embed" rel="noopener">embed</a>
    <a href="/artifacts">← 一覧へ</a>
  </div>
</main>

<footer class="site">
  発行: <a href="https://jpcite.com/about" rel="noopener">Bookyou株式会社</a> (T8010001213708) &middot;
  本 artifact は一次資料の取得時点情報を機械的に集約したもので、税理士法・弁護士法・行政書士法の業法に抵触する助言ではありません。最終判断は士業へ。
</footer>

</body>
</html>`;
}

// ---------------------------------------------------------------------------
// 7 section renderers (overview / programs / laws / cases / enforcement /
// amendments / provenance). Each returns a complete <section> element.
// ---------------------------------------------------------------------------

function renderOverviewSection(a: ArtifactDataset): string {
  const ov = a.overview || {};
  const rows: [string, string][] = [
    ["headline", a.headline || "—"],
    ["tier", a.tier || "—"],
    ["created_at", a.created_at || "—"],
    ["billable_units_consumed", String(a.billable_units_consumed ?? 0)],
    ["snapshot_date", ov.snapshot_date || "—"],
    ["cohort", ov.cohort || "—"],
    ["coverage_summary", ov.coverage_summary || "—"],
    ["description", ov.description || "—"],
  ];
  return `<section class="artifact-section" id="section-overview">
    <h2>1. overview</h2>
    <table>${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table>
  </section>`;
}

function renderProgramsSection(rows: ProgramRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-programs"><h2>2. programs</h2><p class="empty">対象 programs はこの artifact には含まれていません。</p></section>`;
  }
  const cards = rows
    .map(
      (r) => `<div class="card">
      <h3>${esc(r.title || r.program_id || "(untitled)")}</h3>
      <div class="row">program_id: ${esc(r.program_id || "—")}</div>
      <div class="row">tier: ${esc(r.tier || "—")} · fit_pct: ${r.fit_pct != null ? esc(String(r.fit_pct)) + "%" : "—"}</div>
      <div class="row">amount: ${yen(r.amount_jpy)} · deadline: ${esc(r.deadline || "—")}</div>
      ${r.source_url ? `<a class="src" href="${esc(r.source_url)}" target="_blank" rel="noopener">一次資料 ↗</a>` : ""}
    </div>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-programs">
    <h2>2. programs <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    <div class="cards">${cards}</div>
  </section>`;
}

function renderLawsSection(rows: LawRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-laws"><h2>3. laws</h2><p class="empty">関連法令はこの artifact には含まれていません。</p></section>`;
  }
  const items = rows
    .map(
      (r) => `<div class="card">
      <h3>${esc(r.title || r.law_id || "(untitled)")} ${r.article ? `· 第${esc(r.article)}条` : ""}</h3>
      <div class="row">law_id: ${esc(r.law_id || "—")} · license: ${esc(r.license || "—")}</div>
      <div>${esc((r.body_snippet || "").slice(0, 240))}${r.body_snippet && r.body_snippet.length > 240 ? "…" : ""}</div>
      ${r.source_url ? `<a class="src" href="${esc(r.source_url)}" target="_blank" rel="noopener">e-Gov ↗</a>` : ""}
    </div>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-laws">
    <h2>3. laws <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    <div class="cards">${items}</div>
  </section>`;
}

function renderCasesSection(rows: CaseRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-cases"><h2>4. cases</h2><p class="empty">採択事例 / 判例はこの artifact には含まれていません。</p></section>`;
  }
  const items = rows
    .map(
      (r) => `<div class="card">
      <h3>${esc(r.headline || r.case_id || "(untitled)")}</h3>
      <div class="row">case_id: ${esc(r.case_id || "—")} · 業種: ${esc(r.industry || "—")}</div>
      <div class="row">採択年: ${esc(String(r.adopted_year ?? "—"))} · 金額: ${yen(r.amount_jpy)}</div>
      ${r.source_url ? `<a class="src" href="${esc(r.source_url)}" target="_blank" rel="noopener">一次資料 ↗</a>` : ""}
    </div>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-cases">
    <h2>4. cases <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    <div class="cards">${items}</div>
  </section>`;
}

function renderEnforcementSection(rows: EnforcementRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-enforcement"><h2>5. enforcement</h2><p class="empty">行政処分はこの artifact には記録されていません。</p></section>`;
  }
  const tableRows = rows
    .map(
      (r) => `<tr>
      <td>${esc(r.acted_at || "—")}</td>
      <td>${esc(r.authority || "—")}</td>
      <td>${esc(r.action_type || "—")}</td>
      <td>${esc(r.houjin_name || "—")}</td>
      <td>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">一次資料 ↗</a>` : "—"}</td>
    </tr>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-enforcement">
    <h2>5. enforcement <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    <table>
      <thead><tr><th>acted_at</th><th>authority</th><th>action_type</th><th>houjin</th><th>source</th></tr></thead>
      <tbody>${tableRows}</tbody>
    </table>
  </section>`;
}

function renderAmendmentsSection(rows: AmendmentRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-amendments"><h2>6. amendments</h2><p class="empty">対象期間の 法改正 は検出されていません。</p></section>`;
  }
  const items = rows
    .map(
      (r) => `<div class="card">
      <h3>${esc(r.subject || r.amendment_id || "(untitled)")}</h3>
      <div class="row">detected_at: ${esc(r.detected_at || "—")} · effective_from: ${esc(r.effective_from || "—")}</div>
      <div>${esc((r.diff_summary || "").slice(0, 320))}${r.diff_summary && r.diff_summary.length > 320 ? "…" : ""}</div>
      ${r.source_url ? `<a class="src" href="${esc(r.source_url)}" target="_blank" rel="noopener">一次資料 ↗</a>` : ""}
    </div>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-amendments">
    <h2>6. amendments <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    <div class="cards">${items}</div>
  </section>`;
}

function renderProvenanceSection(rows: ProvenanceRow[]): string {
  if (!rows || rows.length === 0) {
    return `<section class="artifact-section" id="section-provenance"><h2>7. provenance</h2><p class="empty">provenance receipts はこの artifact には含まれていません。</p></section>`;
  }
  const items = rows
    .map(
      (r) => `<div class="receipt">
      ${esc(r.source_url || "—")}
      &middot; fetched_at=${esc(r.fetched_at || "—")}
      &middot; hash=${esc(r.content_hash || "—")}
      &middot; license=${esc(r.license || "—")}
    </div>`,
    )
    .join("");
  return `<section class="artifact-section" id="section-provenance">
    <h2>7. provenance <span style="font-size:13px;color:#666;font-weight:400;">(${rows.length})</span></h2>
    ${items}
  </section>`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(s: unknown): string {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) =>
    (
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }) as Record<string, string>
    )[c] || c,
  );
}

function yen(n: number | null | undefined): string {
  if (n == null) return "—";
  try {
    return "¥" + Number(n).toLocaleString("ja-JP");
  } catch {
    return "¥" + String(n);
  }
}

function jsonLdArticle(a: ArtifactDataset, title: string, desc: string): string {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "Article",
    headline: title,
    description: desc,
    datePublished: a.created_at || new Date().toISOString(),
    author: {
      "@type": "Organization",
      name: "Bookyou株式会社",
      taxID: "T8010001213708",
      url: "https://jpcite.com",
    },
    publisher: { "@type": "Organization", name: "jpcite", url: "https://jpcite.com" },
    mainEntityOfPage: `https://jpcite.com/artifacts/${a.pack_id}`,
  });
}

function jsonLdBreadcrumb(pack_id: string): string {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "jpcite", item: "https://jpcite.com/" },
      { "@type": "ListItem", position: 2, name: "Artifacts", item: "https://jpcite.com/artifacts" },
      { "@type": "ListItem", position: 3, name: pack_id },
    ],
  });
}

function buildDemo(pack_id: string, fetch_error: string | null): ArtifactDataset {
  return {
    pack_id,
    headline: `Demo Artifact - ${pack_id}`,
    tier: "demo",
    created_at: new Date().toISOString(),
    billable_units_consumed: 0,
    human_review_required: false,
    overview: {
      description: fetch_error
        ? `upstream fetch failed (${fetch_error}); rendering demo dataset.`
        : "demo dataset for layout verification.",
      cohort: "demo",
      coverage_summary: "1 program · 1 law · 1 case · 1 enforcement · 1 amendment · 2 receipts",
      snapshot_date: new Date().toISOString().slice(0, 10),
    },
    programs: [
      {
        program_id: "demo-prog-001",
        title: "IT導入補助金 2026 通常枠 (demo)",
        tier: "A",
        fit_pct: 78,
        amount_jpy: 4500000,
        deadline: "2026-06-30",
        source_url: "https://www.it-hojo.jp/2026/",
      },
    ],
    laws: [
      {
        law_id: "demo-law-001",
        article: "10",
        title: "中小企業等経営強化法 (demo)",
        body_snippet: "経営力向上計画の認定を受けた事業者は、税制優遇措置の適用を受けることができる。",
        license: "cc_by_4.0",
        source_url: "https://elaws.e-gov.go.jp/document?lawid=411AC0000000060",
      },
    ],
    cases: [
      {
        case_id: "demo-case-001",
        headline: "デモ採択事例 - 製造業 設備投資 (demo)",
        industry: "製造業",
        amount_jpy: 12000000,
        adopted_year: 2025,
        source_url: "https://example.invalid/case",
      },
    ],
    enforcement: [
      {
        enforcement_id: "demo-enf-001",
        authority: "公正取引委員会 (demo)",
        action_type: "排除措置命令",
        houjin_name: "デモ合同会社",
        acted_at: "2025-12-15",
        source_url: "https://example.invalid/enforcement",
      },
    ],
    amendments: [
      {
        amendment_id: "demo-amd-001",
        subject: "IT導入補助金 2026 通常枠 採択要件 改定 (demo)",
        detected_at: "2026-04-01",
        effective_from: "2026-05-01",
        diff_summary: "売上要件が ¥10,000 → ¥30,000 に引き上げ。 (demo)",
        source_url: "https://example.invalid/amendment",
      },
    ],
    provenance: [
      {
        source_url: "https://www.it-hojo.jp/2026/",
        fetched_at: new Date().toISOString(),
        content_hash: "sha256:demo-aa00",
        license: "gov_standard",
      },
      {
        source_url: "https://elaws.e-gov.go.jp/document?lawid=411AC0000000060",
        fetched_at: new Date().toISOString(),
        content_hash: "sha256:demo-bb11",
        license: "cc_by_4.0",
      },
    ],
  };
}
