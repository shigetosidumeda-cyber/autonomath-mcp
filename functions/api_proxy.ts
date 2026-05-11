/// <reference types="@cloudflare/workers-types" />
/*
 * Short-path API proxy (Wave 24 — CDN routing optimization).
 *
 * Reverse-proxies `jpcite.com/api/*` → `api.jpcite.com/v1/*` so that AI
 * agents and SDKs can call the REST API using the shorter, more
 * memorable host+path combination they tend to guess first. Many MCP
 * clients ship hard-coded `https://jpcite.com/api/programs` URLs because
 * /api/ is the universal REST root convention; without this proxy
 * they 404 and the SDK requires reading docs to find /v1/.
 *
 * Concretely the rewrite is:
 *
 *   GET  https://jpcite.com/api/programs?q=...
 *   → 200 (proxied) https://api.jpcite.com/v1/programs?q=...
 *
 *   POST https://jpcite.com/api/programs/batch
 *   → 200 (proxied) https://api.jpcite.com/v1/programs/batch
 *
 * Behaviour:
 *   - Path prefix `/api/` is stripped and `/v1/` is prepended.
 *   - Method + body + query string + Authorization header are forwarded.
 *   - CORS headers are injected so browser clients on third-party hosts
 *     can call /api/* without the API host having to advertise their
 *     origin.
 *   - X-Rate-Limit-Hint is injected to point clients at /v1/me for the
 *     authoritative quota state.
 *   - Origin-side response status + body are passed through unchanged.
 *
 * Memory references:
 *   * feedback_ax_4_pillars        — Layer 1 Access (short path provided).
 *   * feedback_zero_touch_solo     — no operator routes per-customer.
 *   * project_autonomath_business_model — anon 3 req/日 cap enforced upstream.
 */

export interface Env {
  ASSETS: Fetcher;
  JPCITE_API_BASE?: string;
}

// CORS — broad because AI agents call from anywhere (no browser session).
const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "Authorization, Content-Type, X-API-Key, X-Client-Tag, X-Idempotency-Key, Accept",
  "Access-Control-Expose-Headers":
    "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Anon-Upgrade-Url",
  "Access-Control-Max-Age": "86400",
};

/** Build the upstream URL by stripping /api/ and prepending /v1/. */
function rewriteToUpstream(reqUrl: URL, base: string): string {
  // /api/programs           → /v1/programs
  // /api/programs/batch     → /v1/programs/batch
  // /api/                   → /v1/
  // /api                    → /v1/
  let upstreamPath: string;
  if (reqUrl.pathname === "/api" || reqUrl.pathname === "/api/") {
    upstreamPath = "/v1/";
  } else if (reqUrl.pathname.startsWith("/api/")) {
    upstreamPath = "/v1/" + reqUrl.pathname.slice("/api/".length);
  } else {
    // Defensive — should not happen because routing already matched.
    upstreamPath = reqUrl.pathname;
  }
  // Normalise: collapse accidental double slashes; preserve trailing.
  upstreamPath = upstreamPath.replace(/\/{2,}/g, "/");
  return `${base}${upstreamPath}${reqUrl.search}`;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);

  // CORS preflight short-circuit.
  if (context.request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const base = (context.env.JPCITE_API_BASE || "https://api.jpcite.com").replace(/\/+$/, "");
  const upstreamUrl = rewriteToUpstream(url, base);

  // Forward most headers; strip the host/CF-internal ones that would
  // confuse the origin if echoed.
  const fwdHeaders = new Headers(context.request.headers);
  fwdHeaders.delete("host");
  fwdHeaders.delete("cf-connecting-ip");
  fwdHeaders.delete("cf-ipcountry");
  fwdHeaders.delete("cf-ray");
  // Identify the proxy hop so origin logs can distinguish direct vs proxied.
  fwdHeaders.set("X-Forwarded-By", "jpcite-pages-api-proxy");
  fwdHeaders.set("X-Forwarded-Host", url.host);

  // Reconstruct the upstream request.
  // body is null for GET/HEAD; pass through otherwise.
  const init: RequestInit = {
    method: context.request.method,
    headers: fwdHeaders,
    redirect: "manual",
  };
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    init.body = context.request.body;
  }

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, init);
  } catch {
    return new Response(
      JSON.stringify({
        error: "upstream_unreachable",
        hint: "api.jpcite.com is the canonical host; try directly.",
        canonical_url: upstreamUrl,
      }),
      {
        status: 502,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      },
    );
  }

  // Re-emit headers with CORS + rate-limit hint injected.
  const respHeaders = new Headers(upstream.headers);
  for (const [k, v] of Object.entries(CORS_HEADERS)) {
    respHeaders.set(k, v);
  }
  respHeaders.set("X-Rate-Limit-Hint", "GET /v1/me for quota state");
  respHeaders.set("X-Upstream-Canonical", upstreamUrl);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
};
