/// <reference types="@cloudflare/workers-types" />
/*
 * Catch-all .md proxy (Wave 45 — companion .md full propagation).
 *
 * Problem
 * -------
 * jpcite ships 10,282 companion `.md` files (laws/*.md, enforcement/*.md,
 * cases/*.md, root section md) that are the canonical citation surface for
 * LLM agents — every HTML page links its `.md` sibling as the cite-able
 * plain-text source. Wave 41 Agent F confirmed 100% of these returned 404
 * from CF Pages: the `pages-deploy-main.yml` workflow excludes `*.md`
 * (per `rsync --exclude '*.md'`) because the combined `site/` tree is
 * 32,356 files vs. the Free-plan CF Pages 20,000-file deployment limit
 * (verified via direct wrangler upload 2026-05-12, error code returned
 * by Cloudflare API).
 *
 * Strategy adopted (3 alternatives evaluated, see report attached to PR)
 * ---------------------------------------------------------------------
 *   (A) Direct upload all 32,356 files: BLOCKED by Free-plan 20k limit.
 *   (B) Drop `programs/*.html` (10,813 files) so the rest fits: still 21,543
 *       — over the 20k limit by 1,543. Drops cross-link surface.
 *   (C) [adopted] Keep `pages-deploy-main.yml` rsync exclusion of *.md,
 *       and serve all `.md` requests via this Pages Function. The Function
 *       transparently fetches the file from raw.githubusercontent.com
 *       (the file IS in the git repo at site/<path>.md) and caches it at
 *       the Cloudflare edge for 24h. Zero file-count impact on Pages.
 *
 * Operational properties
 * ----------------------
 *   - Coverage: all 10,282 companion .md become 200 immediately on first
 *     edge fetch (warm cache thereafter).
 *   - Cache: 24h edge TTL via Cache API, plus immutable git ref so stale
 *     reads after a content update are bounded by 24h.
 *   - Failure mode: if raw.githubusercontent.com is unreachable (CF
 *     egress block, GitHub outage), returns 502 with a JSON body that
 *     identifies the upstream — agents can fall back to the REST API.
 *   - Cost: GitHub raw is free for public repos; CF edge cache fetches
 *     count against the standard Pages bandwidth quota (effectively
 *     unmetered at our scale).
 *   - No origin dependency: api.jpcite.com being down (Wave 44) does not
 *     affect .md serving — content lives in git.
 *
 * Path routing
 * ------------
 * This Function MUST run as a catch-all because CF Pages Functions
 * cannot register multiple specific .md routes statically. The handler
 * filters by suffix: any request whose pathname does NOT end in `.md`
 * is passed through to ASSETS (the static site). Requests that DO end
 * in `.md` are proxied unless the file is already part of the static
 * surface (e.g. `press/*.md`, `security/policy.md`, which the deploy
 * workflow includes by name) — those are also passed through to ASSETS
 * first, and only if ASSETS returns 404 do we proxy from GitHub raw.
 *
 * This single-function design is necessary because /functions/[[path]].ts
 * intercepts ALL routes. Any new Pages Function added in this repo must
 * either be placed at a more-specific path (e.g. /functions/dpa_issue.ts
 * stays at /dpa/issue) or be merged into this handler. CF Pages routes
 * resolve longest-path-first, so existing specific functions still win.
 *
 * Memory references:
 *   * feedback_zero_touch_solo            — no operator routes per agent.
 *   * feedback_destruction_free_organization — adds, never removes.
 *   * feedback_no_user_operation_assumption  — verify before asking.
 */

export interface Env {
  ASSETS: Fetcher;
}

// GitHub raw host for the canonical site/ tree.
const GITHUB_RAW_BASE =
  "https://raw.githubusercontent.com/shigetosidumeda-cyber/autonomath-mcp/main/site";

// Edge cache TTL for proxied .md (24h). Content updates land in git and
// invalidate via the next deploy's cache-buster, so 24h is the right
// trade-off between staleness and origin egress.
const EDGE_CACHE_SECONDS = 86400;

// Charset is forced to UTF-8 because raw.githubusercontent.com returns
// text/plain without a charset, which breaks Japanese rendering in some
// LLM citation pipelines.
const MD_CONTENT_TYPE = "text/markdown; charset=utf-8";

export const onRequest: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const url = new URL(request.url);

  // Fast-path: anything that is not a GET/HEAD or does not end in `.md`
  // is delegated to the static Pages surface.
  if (request.method !== "GET" && request.method !== "HEAD") {
    return env.ASSETS.fetch(request);
  }
  if (!url.pathname.endsWith(".md")) {
    return env.ASSETS.fetch(request);
  }
  if (
    url.pathname.length > 300 ||
    url.pathname.includes("/_internal/") ||
    url.pathname.includes("/.git/") ||
    url.pathname.includes("..")
  ) {
    return new Response("# 404\nNot found.\n", {
      status: 404,
      headers: { "content-type": MD_CONTENT_TYPE },
    });
  }

  // Pages static surface MAY include some .md files (press/*.md,
  // security/policy.md per the deploy rsync include list). Try ASSETS
  // first; only proxy on 404.
  const staticResp = await env.ASSETS.fetch(request);
  if (staticResp.status !== 404) {
    return staticResp;
  }

  // Cache lookup at edge.
  const cacheUrl = new URL(url.toString());
  cacheUrl.search = "";
  const cacheKey = new Request(cacheUrl.toString(), request);
  const cache = (caches as unknown as { default: Cache }).default;
  const cached = await cache.match(cacheKey);
  if (cached) {
    return cached;
  }

  // Build the raw.githubusercontent.com URL. CF Pages always normalises
  // the request to `/foo/bar.md`; we splice that onto the canonical base.
  const upstream = `${GITHUB_RAW_BASE}${url.pathname}`;
  let upstreamResp: Response;
  try {
    upstreamResp = await fetch(upstream, {
      cf: {
        // Allow the CF edge to keep its own server-side copy of the
        // raw.githubusercontent.com response for 24h; this prevents a
        // thundering-herd if the per-PoP cache evicts.
        cacheEverything: true,
        cacheTtl: EDGE_CACHE_SECONDS,
      },
      headers: {
        // GitHub raw rate-limits anonymous IPs; identifying ourselves
        // increases the bucket size.
        "User-Agent": "jpcite-pages-function/1.0 (+https://jpcite.com)",
      },
    });
  } catch {
    return new Response(
      JSON.stringify({
        error: "upstream_unreachable",
        message: "markdown_source_unavailable",
      }),
      {
        status: 502,
        headers: { "content-type": "application/json; charset=utf-8" },
      },
    );
  }

  if (upstreamResp.status === 404) {
    // True 404 — neither the static surface nor the git tree has it.
    // Pass through GitHub's body but normalise content-type so the
    // client sees a clean error.
    return new Response(`# 404 — ${url.pathname}\nNot found.\n`, {
      status: 404,
      headers: { "content-type": MD_CONTENT_TYPE },
    });
  }

  if (!upstreamResp.ok) {
    // 5xx or rate-limit. Do NOT cache; surface to client.
    return new Response(
      JSON.stringify({
        error: "upstream_error",
        message: "markdown_source_unavailable",
      }),
      {
        status: 502,
        headers: { "content-type": "application/json; charset=utf-8" },
      },
    );
  }

  // 200 — wrap response with content-type override + cache headers, then
  // store in edge cache.
  const body = await upstreamResp.text();
  const resp = new Response(body, {
    status: 200,
    headers: {
      "content-type": MD_CONTENT_TYPE,
      "cache-control": `public, max-age=${EDGE_CACHE_SECONDS}`,
      "x-jpcite-md-source": "github-raw-proxy",
      // CORS so browser fetch() and LLM citation pipelines can pull
      // these as text/markdown without preflight grief.
      "access-control-allow-origin": "*",
    },
  });

  // Edge cache write is fire-and-forget — do not block the response.
  context.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
};
