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
 *   GET  https://jpcite.com/api/programs/search?q=...
 *   → 200 (proxied) https://api.jpcite.com/v1/programs/search?q=...
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
  JPCITE_EDGE_AUTH_SECRET?: string;
}

// CORS — broad because AI agents call from anywhere (no browser session).
const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "Authorization, Content-Type, X-API-Key, X-Client-Tag, Idempotency-Key, X-Idempotency-Key, X-Cost-Cap-JPY, Accept",
  "Access-Control-Expose-Headers":
    "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Anon-Upgrade-Url, X-Anon-Direct-Checkout-Url, X-Anon-Trial-Url, X-Rate-Limit-Hint, X-Upstream-Canonical, X-Cost-Yen, X-Cost-Cap-Required, X-Cost-Capped, X-Idempotency-Replayed",
  "Access-Control-Max-Age": "86400",
};

const UPSTREAM_FETCH_TIMEOUT_MS = 10_000;
const MAX_PROXY_BODY_BYTES = 1_048_576;
const ROOT_API_PATH_ALIASES: Record<string, string> = {
  "/api/healthz": "/healthz",
  "/api/programs": "/v1/programs/search",
  "/api/programs/": "/v1/programs/search",
  "/api/readyz": "/readyz",
};

type LimitedBodyResult = { ok: true; body: ArrayBuffer | null } | { ok: false };

function contentLengthExceeds(headers: Headers, maxBytes: number): boolean {
  const value = headers.get("content-length");
  if (!value) return false;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > maxBytes;
}

async function readRequestBodyLimited(
  request: Request,
  maxBytes: number,
): Promise<LimitedBodyResult> {
  if (contentLengthExceeds(request.headers, maxBytes)) {
    return { ok: false };
  }
  if (!request.body) {
    return { ok: true, body: null };
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      try {
        await reader.cancel();
      } catch {
        // Best effort; the response will be rejected either way.
      }
      return { ok: false };
    }
    chunks.push(value);
  }

  if (total === 0) {
    return { ok: true, body: null };
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, body: body.buffer };
}

async function fetchWithTimeout(
  upstreamUrl: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(upstreamUrl, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

/** Build the upstream URL by stripping /api/ and prepending /v1/. */
function rewriteToUpstream(reqUrl: URL, base: string): string {
  // /api/programs/search    → /v1/programs/search
  // /api/programs           → /v1/programs/search
  // /api/programs/batch     → /v1/programs/batch
  // /api/healthz            → /healthz
  // /api/readyz             → /readyz
  // /api/                   → /v1/
  // /api                    → /v1/
  let upstreamPath = ROOT_API_PATH_ALIASES[reqUrl.pathname];
  if (upstreamPath) {
    // Root health endpoints intentionally live outside /v1 on the API host.
  } else if (reqUrl.pathname === "/api" || reqUrl.pathname === "/api/") {
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

function redactUpstreamUrl(upstreamUrl: string): string {
  const url = new URL(upstreamUrl);
  return `${url.origin}${url.pathname}`;
}

function bytesToHex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function mintEdgeAuth(secret: string, nowSeconds: number, callerIp: string): Promise<string> {
  const payload = `v1:${nowSeconds}:${callerIp}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return `${payload}:${bytesToHex(sig)}`;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);

  // CORS preflight short-circuit.
  if (context.request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const base = (context.env.JPCITE_API_BASE || "https://api.jpcite.com").replace(/\/+$/, "");
  const upstreamUrl = rewriteToUpstream(url, base);
  const redactedUpstreamUrl = redactUpstreamUrl(upstreamUrl);

  // Forward most headers; strip the host/CF-internal ones that would
  // confuse the origin if echoed.
  const callerIp = context.request.headers.get("CF-Connecting-IP")?.trim();
  const fwdHeaders = new Headers(context.request.headers);
  fwdHeaders.delete("host");
  for (const headerName of [...fwdHeaders.keys()]) {
    if (headerName.toLowerCase().startsWith("cf-")) {
      fwdHeaders.delete(headerName);
    }
  }
  fwdHeaders.delete("fly-client-ip");
  fwdHeaders.delete("x-forwarded-for");
  fwdHeaders.delete("x-edge-auth");
  // Identify the proxy hop so origin logs can distinguish direct vs proxied.
  fwdHeaders.set("X-Forwarded-By", "jpcite-pages-api-proxy");
  fwdHeaders.set("X-Forwarded-Host", url.host);
  if (callerIp && context.env.JPCITE_EDGE_AUTH_SECRET) {
    fwdHeaders.set("X-Forwarded-For", callerIp);
    fwdHeaders.set(
      "X-Edge-Auth",
      await mintEdgeAuth(
        context.env.JPCITE_EDGE_AUTH_SECRET,
        Math.floor(Date.now() / 1000),
        callerIp,
      ),
    );
  }

  let upstreamBody: ArrayBuffer | null = null;
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    const limitedBody = await readRequestBodyLimited(context.request, MAX_PROXY_BODY_BYTES);
    if (!limitedBody.ok) {
      return new Response(
        JSON.stringify({ error: "body_too_large", max_body_bytes: MAX_PROXY_BODY_BYTES }),
        {
          status: 413,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS },
        },
      );
    }
    upstreamBody = limitedBody.body;
  }

  // Reconstruct the upstream request.
  // body is null for GET/HEAD; pass through otherwise.
  const init: RequestInit = {
    method: context.request.method,
    headers: fwdHeaders,
    redirect: "manual",
  };
  if (upstreamBody) {
    init.body = upstreamBody;
  }

  let upstream: Response;
  try {
    upstream = await fetchWithTimeout(upstreamUrl, init, UPSTREAM_FETCH_TIMEOUT_MS);
  } catch {
    return new Response(
      JSON.stringify({
        error: "upstream_unreachable",
        hint: "api.jpcite.com is the canonical host; try directly.",
        canonical_url: redactedUpstreamUrl,
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
  respHeaders.set("X-Upstream-Canonical", redactedUpstreamUrl);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
};
