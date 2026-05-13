/* jpcite Service Worker (service worker cache policy).
 *
 * Goal: keep llms.txt / llms-full.txt / openapi / mcp manifests + a small set
 * of key /docs/* pages reachable when the agent's network is flaky.
 *
 * Cache policy:
 *   - Pre-cache the static-AI-discovery surface on install
 *   - Stale-while-revalidate for /docs/* pages
 *   - Network-only for /v1/* (API calls must not be served from cache)
 *   - Cache-first for static assets (/assets/*, /favicon.ico)
 *
 * Versioned cache name lets us blow the cache on each deploy.
 *
 * Browser scope: any page on jpcite.com that includes
 *   <script>navigator.serviceWorker.register('/sw.js')</script>
 *
 * Agent benefit: a headless browser running Cline / Cursor / Claude Desktop /
 * Anthropic CLA can fetch llms.txt + key /docs/* from cache when the upstream
 * link is throttled or down. */

const CACHE_VERSION = "jpcite-v19-2026-05-11";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const DOCS_CACHE = `${CACHE_VERSION}-docs`;

/* Pre-cached AI-discovery surface. These are the entrypoints every agent
 * touches first, so we want them to be reachable instantly even offline. */
const PRECACHE_URLS = [
  "/llms.txt",
  "/llms.en.txt",
  "/llms-full.txt",
  "/llms-full.en.txt",
  "/openapi.agent.json",
  "/openapi.agent.gpt30.json",
  "/openapi/v1.json",
  "/openapi/agent.json",
  "/mcp-server.json",
  "/server.json",
  "/.well-known/mcp.json",
  "/.well-known/openapi-discovery.json",
  "/.well-known/trust.json",
  "/.well-known/security.txt",
  "/.well-known/sbom.json",
  "/.well-known/ai-plugin.json",
  "/.well-known/agents.json",
  "/robots.txt",
  "/facts.html",
  "/en/facts.html",
  "/pricing.html",
  "/error_handling.html",
  "/docs/agents.md",
  "/docs/getting-started.html",
  "/docs/api-reference.md",
  "/docs/cookbook/index.md",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      await Promise.allSettled(
        PRECACHE_URLS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn(`[sw] precache miss for ${url}:`, err);
          })
        )
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => !n.startsWith(CACHE_VERSION))
          .map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

/* Route classifier. Returns one of:
 *   "api"    → network only, never cache
 *   "static" → cache-first
 *   "docs"   → stale-while-revalidate
 *   "skip"   → bypass SW entirely
 */
function classify(url) {
  if (url.pathname.startsWith("/v1/")) return "api";
  if (url.pathname.startsWith("/admin/")) return "skip";
  if (url.pathname.startsWith("/dashboard")) return "skip";
  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.startsWith("/favicon") ||
    url.pathname.startsWith("/robots.txt") ||
    url.pathname.startsWith("/sitemap") ||
    url.pathname.startsWith("/llms") ||
    url.pathname.startsWith("/openapi") ||
    url.pathname.startsWith("/mcp-server") ||
    url.pathname.startsWith("/server.json") ||
    url.pathname.startsWith("/.well-known/")
  ) {
    return "static";
  }
  if (url.pathname.startsWith("/docs/") || url.pathname.endsWith(".html") || url.pathname === "/") {
    return "docs";
  }
  return "skip";
}

async function networkOnly(request) {
  return fetch(request);
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const fresh = await fetch(request);
    if (fresh.ok) {
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (err) {
    if (cached) return cached;
    return new Response("offline: cache miss", { status: 503, statusText: "offline" });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(DOCS_CACHE);
  const cached = await cache.match(request);
  const revalidate = fetch(request)
    .then((fresh) => {
      if (fresh && fresh.ok) cache.put(request, fresh.clone());
      return fresh;
    })
    .catch(() => null);
  return cached || (await revalidate) || new Response("offline", { status: 503 });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  /* Only handle GET on our origin */
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  const klass = classify(url);
  if (klass === "skip") return;
  if (klass === "api") {
    event.respondWith(networkOnly(event.request));
    return;
  }
  if (klass === "static") {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  if (klass === "docs") {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }
});

/* Optional message channel: pages can post {type: "PURGE"} to drop caches
 * after public discovery files are updated. */
self.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "PURGE") return;
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
      const clients = await self.clients.matchAll();
      clients.forEach((c) => c.postMessage({ type: "PURGED" }));
    })()
  );
});
