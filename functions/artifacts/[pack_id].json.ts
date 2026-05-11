/// <reference types="@cloudflare/workers-types" />
interface Env { JPCITE_API_BASE: string; }
export const onRequest: PagesFunction<Env> = async ({ params, env }) => {
  const pack_id = String(params.pack_id || '').replace(/\.json$/, '');
  const api_base = env.JPCITE_API_BASE || 'https://api.jpcite.com';
  const res = await fetch(`${api_base}/v1/artifacts/${pack_id}`, {
    cf: { cacheTtl: 300, cacheEverything: true },
  });
  if (!res.ok) return new Response(JSON.stringify({ error: 'not_found', pack_id }), {
    status: 410, headers: { 'Content-Type': 'application/json' }
  });
  const data = await res.json();
  return new Response(JSON.stringify(data, null, 2), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=300, stale-while-revalidate=3600',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
