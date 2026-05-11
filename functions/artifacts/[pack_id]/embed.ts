/// <reference types="@cloudflare/workers-types" />
interface Env { JPCITE_API_BASE: string; }
export const onRequest: PagesFunction<Env> = async ({ params, env }) => {
  const pack_id = String(params.pack_id || '');
  const api_base = env.JPCITE_API_BASE || 'https://api.jpcite.com';
  const res = await fetch(`${api_base}/v1/artifacts/${pack_id}`, { cf: { cacheTtl: 3600 } });
  const artifact: any = res.ok ? await res.json() : { headline: 'Not found', pack_id };
  const html = `<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(artifact.headline || pack_id)}</title><style>body{font-family:-apple-system,sans-serif;margin:0;padding:16px;color:#0f172a;font-size:14px}.brand{font-weight:600;color:#0a4d8c;margin:0 0 12px;border-bottom:1px solid #e2e8f0;padding:0 0 8px}h1{font-size:18px;margin:0 0 12px;line-height:1.4}.units{color:#64748b;font-size:12px;margin:8px 0}a.powered{display:block;margin:16px 0 0;color:#64748b;font-size:11px;text-decoration:none;border-top:1px solid #e2e8f0;padding:8px 0 0;text-align:right}a.powered:hover{color:#0a4d8c}</style></head><body><p class="brand">jpcite artifact (embed)</p><h1>${esc(artifact.headline || pack_id)}</h1><p class="units">tier: ${esc(artifact.tier || 'unknown')} / units: ${artifact.billable_units_consumed || 0} / ${esc(artifact.created_at || '')}</p><a class="powered" href="https://jpcite.com/artifacts/${pack_id}?ref=embed" target="_top" rel="noopener">powered by jpcite ↗</a></body></html>`;
  return new Response(html, {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
      'X-Frame-Options': 'ALLOWALL',
      'Content-Security-Policy': 'frame-ancestors *',
    },
  });
};
function esc(s: string): string { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c)); }
