/// <reference types="@cloudflare/workers-types" />
/* SSR for /artifacts/{pack_id} - fetch artifact JSON from API, render HTML shell with SEO + JSON-LD. */

interface Env {
  ASSETS: Fetcher;
  JPCITE_API_BASE: string;  // default https://api.jpcite.com
}

interface ArtifactRow {
  pack_id: string;
  headline?: string;
  created_at?: string;
  tier?: string;
  billable_units_consumed?: number;
  company_public_baseline?: any;
  decision_insights?: any[];
  copy_paste_parts?: any;
  work_queue?: any[];
  source_receipts?: any[];
  known_gaps?: any[];
  recommended_followup?: any[];
  human_review_required?: { value: boolean; reason?: string };
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const { params, env, request } = context;
  const pack_id = String(params.pack_id || '');

  if (!/^jpcite-pack-\d{13}-\d{8}-\d{3}$/.test(pack_id)) {
    return new Response('410 Gone (invalid pack_id format)', { status: 410 });
  }

  // Fetch artifact JSON
  const api_base = env.JPCITE_API_BASE || 'https://api.jpcite.com';
  let artifact: ArtifactRow | null = null;
  try {
    const res = await fetch(`${api_base}/v1/artifacts/${pack_id}`, {
      cf: { cacheTtl: 60, cacheEverything: true },
    });
    if (res.ok) artifact = await res.json();
  } catch (e) {
    // fallback DEMO
  }

  // Demo fallback if not found
  if (!artifact) {
    artifact = {
      pack_id,
      headline: 'Demo Artifact (real artifact not found)',
      created_at: new Date().toISOString(),
      tier: 'free',
      billable_units_consumed: 0,
      company_public_baseline: { _demo: true },
      human_review_required: { value: false }
    };
  }

  const title = artifact.headline || pack_id;
  const desc = `${title} - jpcite artifact, ${artifact.billable_units_consumed || 0} billable units, tier ${artifact.tier || 'unknown'}`;

  const html = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${escapeHtml(title)} | jpcite artifact</title>
<meta name="description" content="${escapeHtml(desc)}">
<link rel="canonical" href="https://jpcite.com/artifacts/${pack_id}">
<meta property="og:type" content="article">
<meta property="og:title" content="${escapeHtml(title)}">
<meta property="og:description" content="${escapeHtml(desc)}">
<meta property="og:url" content="https://jpcite.com/artifacts/${pack_id}">
<meta property="og:image" content="https://jpcite.com/og/artifact.png">
<script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": ${JSON.stringify(title)},
  "datePublished": ${JSON.stringify(artifact.created_at || new Date().toISOString())},
  "author": {"@type": "Organization", "name": "Bookyou株式会社", "taxID": "T8010001213708", "url": "https://jpcite.com"},
  "publisher": {"@type": "Organization", "name": "jpcite", "url": "https://jpcite.com"},
  "mainEntityOfPage": "https://jpcite.com/artifacts/${pack_id}"
}</script>
<script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "jpcite", "item": "https://jpcite.com/"},
    {"@type": "ListItem", "position": 2, "name": "Artifacts", "item": "https://jpcite.com/artifacts/"},
    {"@type": "ListItem", "position": 3, "name": ${JSON.stringify(pack_id)}}
  ]
}</script>
<link rel="stylesheet" href="/styles.css">
</head>
<body data-pack-id="${pack_id}">
<script id="artifact-data" type="application/json">${JSON.stringify(artifact)}</script>
<div id="artifact-root"><p>Loading...</p></div>
<script src="/artifact.js" defer></script>
</body>
</html>`;

  return new Response(html, {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'public, max-age=60, stale-while-revalidate=3600',
      'X-Robots-Tag': 'index, follow',
    },
  });
};

function escapeHtml(s: string): string {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c] || c));
}
