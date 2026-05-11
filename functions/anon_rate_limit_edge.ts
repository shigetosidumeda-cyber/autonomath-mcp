/// <reference types="@cloudflare/workers-types" />
/*
 * Edge-side anonymous rate-limit pre-filter (Wave 24).
 *
 * The canonical anon-rate-limit (3 req/日 per IP, JST 翌日 00:00 reset)
 * lives in `src/jpintel_mcp/api/anon_limit.py` and is enforced at the
 * FastAPI router layer in Fly Tokyo. That is the source of truth — this
 * edge function does NOT replace it. It is a pre-filter: it counts
 * requests per IP in Workers KV at the Cloudflare edge and short-
 * circuits the request with a 429 *before* it traverses the
 * jpcite.com → api.jpcite.com → Fly origin → SQLite chain.
 *
 * Why pre-filter at the edge?
 *   1. Fly Tokyo p99 swap > 25s under burst; if a runaway agent loop
 *      sends 1000 anon requests in one second, all of them reach Fly
 *      origin and bottleneck the Tokyo machine before the FastAPI
 *      anon-limit returns 429. Edge pre-filter sheds 99%+ of those at
 *      the CF POP closest to the abuser, never touching Fly.
 *   2. Edge KV write latency (~1ms) is 100× cheaper than Fly SQLite
 *      write latency under contention (~100ms p99 during a burst).
 *   3. Anonymous traffic is by definition cookie-less and key-less —
 *      we can identify the visitor only by /64 IP, and KV lookup keyed
 *      on that is the canonical hot-path data structure.
 *
 * Behaviour:
 *   - Applies to every GET on /api/* and /v1/* that has NO authorization
 *     header and NO X-API-Key header.
 *   - Looks up `anon:{ip64}:{jst_date}` in KV (jpcite_rate_limit binding).
 *   - If count >= 3, returns 429 immediately with the JST reset header
 *     and X-Anon-Upgrade-Url. Caller never reaches origin.
 *   - If count < 3, increments and forwards. Origin still re-checks via
 *     anon_limit.py — edge is advisory, never authoritative on success.
 *   - Keys expire after 25h (JST day window + 1h skew margin).
 *
 * IP normalisation:
 *   - IPv4 → /24 (first 3 octets).
 *   - IPv6 → /64 (first 4 groups).
 *   This matches `anon_limit.py` and prevents per-host /32 abuse where a
 *   /64 sees the counter reset after every NAT hop.
 *
 * KV binding:
 *   - `JPCITE_ANON_KV` is the configured KV namespace.
 *   - If unbound (preview environment, dev), the function passes
 *     through without counting so local dev never hits a 429.
 *
 * Memory references:
 *   * project_autonomath_business_model — anon 3 req/日 (JST 翌日 00:00 reset)
 *   * feedback_zero_touch_solo          — no operator intervention.
 *   * feedback_autonomath_no_api_use    — abuse hits ¥, shed early.
 */

export interface Env {
  ASSETS: Fetcher;
  JPCITE_ANON_KV?: KVNamespace;
  JPCITE_API_BASE?: string;
  ANON_LIMIT_PER_DAY?: string;
}

const DEFAULT_DAILY_LIMIT = 3;
// KV TTL slightly longer than a JST calendar day so counters never time
// out mid-day under clock skew.
const KEY_TTL_SECONDS = 25 * 3600;

/** Returns true for paths that count against anon quota. */
function isMeteredPath(path: string): boolean {
  if (path.startsWith("/v1/")) return true;
  if (path.startsWith("/api/")) return true;
  return false;
}

/** Returns true for paths exempt even on /v1/* (health probes etc.). */
function isExemptPath(path: string): boolean {
  return (
    path === "/v1/healthz" ||
    path === "/v1/readyz" ||
    path === "/v1/openapi.json" ||
    path === "/v1/openapi.agent.json" ||
    path === "/v1/mcp-server.json" ||
    path === "/v1/mcp-server.full.json" ||
    path === "/api/healthz" ||
    path === "/api/readyz"
  );
}

/** Decide whether the caller is anonymous (no auth, no API key header). */
function isAnonymous(req: Request): boolean {
  const auth = req.headers.get("authorization");
  if (auth && /bearer\s+\S+/i.test(auth)) return false;
  const apiKey =
    req.headers.get("x-api-key") ||
    req.headers.get("X-API-Key") ||
    req.headers.get("X-Api-Key");
  if (apiKey && apiKey.trim().length > 0) return false;
  return true;
}

/** /24 for IPv4, /64 for IPv6. */
function normaliseIp(ip: string | null | undefined): string {
  if (!ip) return "unknown";
  if (ip.includes(":")) return ip.split(":").slice(0, 4).join(":");
  return ip.split(".").slice(0, 3).join(".");
}

/** YYYY-MM-DD in JST. JST is UTC+9, no DST. */
function jstDateKey(now: Date = new Date()): string {
  const jst = new Date(now.getTime() + 9 * 3600_000);
  return jst.toISOString().slice(0, 10);
}

/** Seconds until next JST midnight. */
function secondsUntilJstMidnight(now: Date = new Date()): number {
  const jst = new Date(now.getTime() + 9 * 3600_000);
  const nextMidnight = new Date(jst);
  nextMidnight.setUTCHours(24, 0, 0, 0);
  return Math.ceil((nextMidnight.getTime() - jst.getTime()) / 1000);
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);

  // Fast bypass paths: not metered, exempt, or non-anonymous.
  if (!isMeteredPath(url.pathname)) return context.next();
  if (isExemptPath(url.pathname)) return context.next();
  if (!isAnonymous(context.request)) return context.next();

  // No KV binding in dev / preview — pass through, origin still enforces.
  const kv = context.env.JPCITE_ANON_KV;
  if (!kv) return context.next();

  const ip = normaliseIp(context.request.headers.get("CF-Connecting-IP"));
  if (ip === "unknown") return context.next();

  const limit = Number.parseInt(context.env.ANON_LIMIT_PER_DAY || "", 10) || DEFAULT_DAILY_LIMIT;
  const day = jstDateKey();
  const key = `anon:${ip}:${day}`;

  // Read current count.
  let count = 0;
  try {
    const raw = await kv.get(key);
    if (raw) count = Number.parseInt(raw, 10) || 0;
  } catch {
    // KV read failure — fail open so a Cloudflare KV blip doesn't take
    // the site down. Origin still enforces.
    return context.next();
  }

  if (count >= limit) {
    const resetSec = secondsUntilJstMidnight();
    return new Response(
      JSON.stringify({
        error: "anon_quota_exceeded",
        limit_per_day: limit,
        reset_in_seconds: resetSec,
        reset_timezone: "JST (Asia/Tokyo)",
        upgrade_url: "https://jpcite.com/upgrade",
        hint: "Issue an API key at https://jpcite.com/upgrade for ¥3/req metered access.",
      }),
      {
        status: 429,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Retry-After": String(resetSec),
          "X-RateLimit-Limit": String(limit),
          "X-RateLimit-Remaining": "0",
          "X-RateLimit-Reset": String(resetSec),
          "X-Anon-Upgrade-Url": "https://jpcite.com/upgrade",
          "X-Edge-Rate-Limit": "anon-prefilter",
          "Cache-Control": "no-store",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }

  // Increment, then forward.
  try {
    await kv.put(key, String(count + 1), { expirationTtl: KEY_TTL_SECONDS });
  } catch {
    // Best-effort — never block the request on a write failure.
  }
  return context.next();
};
