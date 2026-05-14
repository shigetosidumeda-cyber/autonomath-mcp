/// <reference types="@cloudflare/workers-types" />
/*
 * Edge-side anonymous rate-limit pre-filter.
 *
 * ─────────────────────────────────────────────────────────────────────────
 *  RESIDUAL P1 — Workers KV read-modify-write is NOT atomic.
 *
 *  This function does `kv.get()` then `kv.put(count + 1)`. Two concurrent
 *  requests landing on the same CF POP within the same KV propagation
 *  window can read the same `count`, both increment to `count + 1`, and
 *  the second write overwrites the first — letting one extra request slip
 *  through per concurrent batch. Across all global POPs the window is
 *  larger (eventual consistency), so a sufficiently concurrent agent can
 *  burst N × (POPs) requests before the counter catches up.
 *
 *  We accept this residual P1 deliberately. Strict atomic burst control
 *  needs one of:
 *
 *    (a) **Durable Object** keyed on `{ip_bucket}:{jst_date}` — single
 *        global serialiser per bucket, transactional storage, ~5ms
 *        cold-hop latency. Right answer if/when concurrent-burst abuse
 *        crosses a measurable revenue threshold.
 *
 *    (b) **Origin-authoritative** — drop edge counting entirely and let
 *        `src/jpintel_mcp/api/anon_limit.py` carry the full load. Has
 *        the Fly Tokyo p99-swap-> bottleneck during a burst (see below)
 *        but is the canonical correctness anchor.
 *
 *  Today we run (b) for correctness and use this edge layer as a burst-
 *  shedding pre-filter only. The origin is **always** consulted on
 *  success and is the only path that records a definitive quota
 *  decision against `anon_rate_limit.call_count`. Treat any state held
 *  in `JPCITE_ANON_KV` as advisory — never authoritative on grant.
 * ─────────────────────────────────────────────────────────────────────────
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
 *      we can identify the visitor only by IP bucket, and KV lookup keyed
 *      on that is the canonical hot-path data structure.
 *
 * Behaviour:
 *   - Applies to every GET on /api/* and /v1/* without a plausible API
 *     key in Authorization: Bearer or X-API-Key. Junk auth headers
 *     (random strings, malformed bearer tokens) do NOT exempt the
 *     caller — `looksLikeApiKey()` shape-checks before trusting.
 *   - Looks up `anon:{ip_bucket}:{jst_date}` in KV (jpcite_rate_limit binding).
 *   - If count >= 3, returns 429 immediately with the JST reset header
 *     and X-Anon-Upgrade-Url. Caller never reaches origin.
 *   - If count < 3, increments and forwards. Origin still re-checks via
 *     anon_limit.py — edge is advisory, never authoritative on success.
 *   - Keys expire after 25h (JST day window + 1h skew margin).
 *
 * IP normalisation (MUST stay aligned with `anon_limit._normalize_ip_to_prefix`):
 *   - IPv4 → exact address (/32).
 *   - IPv6 → /64 (first 4 hextet groups).
 *   Missing `CF-Connecting-IP` or "unknown" normalisation result → 503
 *   `edge_ip_unavailable`. We do NOT pass through to origin: a pass-through
 *   with no IP either (a) bypasses the edge burst-shedding entirely or
 *   (b) lets an attacker who stripped/forged the header skip counting
 *   against their /32 bucket. Refusing makes the failure visible instead
 *   of silently inflating the anonymous quota for one caller.
 *
 * KV binding:
 *   - `JPCITE_ANON_KV` is the configured KV namespace.
 *   - If unbound (preview environment, dev), the function passes
 *     through without counting so local dev never hits a 429.
 *
 * Implementation note:
 *   Edge KV is advisory burst shedding only. Origin anon_limit.py remains
 *   the authoritative quota decision. Do NOT introduce client-visible
 *   side-effects (cookies, signed tokens) here — the edge must remain
 *   replaceable by a Durable Object without surface-area breakage.
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
    path === "/healthz" ||
    path === "/v1/readyz" ||
    path === "/v1/openapi.json" ||
    path === "/v1/openapi.agent.json" ||
    path === "/v1/mcp-server.json" ||
    path === "/v1/mcp-server.full.json" ||
    path === "/api/healthz" ||
    path === "/api/readyz" ||
    path === "/api/openapi.json" ||
    path === "/api/openapi.agent.json" ||
    path === "/api/mcp-server.json" ||
    path === "/api/mcp-server.full.json" ||
    path === "/api/rum_beacon"
  );
}

/** Edge-only syntax check; origin remains authoritative for real auth. */
function looksLikeApiKey(raw: string | null | undefined): boolean {
  const key = (raw || "").trim();
  return /^(jc|am|sk)_[A-Za-z0-9_-]{24,}$/.test(key);
}

/** Decide whether the caller is anonymous for edge prefiltering. */
function isAnonymous(req: Request): boolean {
  const auth = req.headers.get("authorization");
  if (auth) {
    const match = auth.match(/^\s*bearer\s+(.+?)\s*$/i);
    if (match && looksLikeApiKey(match[1])) return false;
  }
  const apiKey =
    req.headers.get("x-api-key") ||
    req.headers.get("X-API-Key") ||
    req.headers.get("X-Api-Key");
  if (looksLikeApiKey(apiKey)) return false;
  return true;
}

/** RFC 5952 canonical text form of the IPv6 /64 network containing `ip`.
 *
 * Mirrors `canonical_ipv6_64` in `src/jpintel_mcp/api/anon_limit.py`
 * (Python's `str(IPv6Network((addr, 64), strict=False).network_address)`).
 * Both sides MUST emit byte-identical output for the same input so the
 * advisory edge pre-filter and the authoritative origin bucket never split.
 *
 * Examples (input -> output):
 *   "::1"                                    -> "::"
 *   "2001:db8::1"                            -> "2001:db8::"
 *   "2001:db8:0:1::ffff"                     -> "2001:db8:0:1::"
 *   "2001:db8:1234:5678:abcd:ef01:2345:6789" -> "2001:db8:1234:5678::"
 *   "fe80::1"                                -> "fe80::"
 *
 * Returns null for anything not parseable as IPv6. Caller is expected to
 * fall through to the "unknown" bucket (i.e. bypass the edge pre-filter).
 */
export function canonicalIpv6Slash64(ip: string): string | null {
  // Reject scoped literals ("fe80::1%eth0") and anything obviously not v6.
  if (!ip || ip.indexOf(":") < 0 || ip.indexOf("%") >= 0) return null;
  // Expand to 8 hextet groups. RFC 4291: a single "::" stands for one or
  // more all-zero groups; only one "::" may appear.
  const doubleColonCount = ip.split("::").length - 1;
  if (doubleColonCount > 1) return null;
  let groups: string[];
  if (doubleColonCount === 1) {
    const [left, right] = ip.split("::");
    const leftParts = left === "" ? [] : left.split(":");
    const rightParts = right === "" ? [] : right.split(":");
    const missing = 8 - leftParts.length - rightParts.length;
    if (missing < 0) return null;
    groups = [...leftParts, ...Array(missing).fill("0"), ...rightParts];
  } else {
    groups = ip.split(":");
  }
  if (groups.length !== 8) return null;
  // Validate every group is 1..4 hex chars and normalise to a number.
  const nums: number[] = [];
  for (const g of groups) {
    if (!/^[0-9a-fA-F]{1,4}$/.test(g)) return null;
    nums.push(parseInt(g, 16));
  }
  // /64: first 4 groups preserved, last 4 groups forced to zero.
  const net: number[] = [nums[0], nums[1], nums[2], nums[3], 0, 0, 0, 0];
  // RFC 5952: collapse the longest run of zero groups (length >= 2) into
  // "::". When two runs tie, the leftmost wins (matches Python's
  // ipaddress.IPv6Address.__str__).
  let bestStart = -1;
  let bestLen = 0;
  let curStart = -1;
  let curLen = 0;
  for (let i = 0; i < 8; i++) {
    if (net[i] === 0) {
      if (curStart < 0) curStart = i;
      curLen++;
      if (curLen > bestLen) {
        bestStart = curStart;
        bestLen = curLen;
      }
    } else {
      curStart = -1;
      curLen = 0;
    }
  }
  const hex = net.map((n) => n.toString(16));
  if (bestLen < 2) {
    return hex.join(":");
  }
  const head = hex.slice(0, bestStart).join(":");
  const tail = hex.slice(bestStart + bestLen).join(":");
  if (head === "" && tail === "") return "::";
  if (head === "") return "::" + tail;
  if (tail === "") return head + "::";
  return head + "::" + tail;
}

/** Exact IPv4, /64 for IPv6. Keep aligned with origin anon_limit. */
export function normaliseIp(ip: string | null | undefined): string {
  const trimmed = (ip || "").trim();
  if (!trimmed) return "unknown";
  if (trimmed.includes(":")) {
    const v6 = canonicalIpv6Slash64(trimmed);
    return v6 ?? "unknown";
  }
  return trimmed;
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
  if (context.request.method === "OPTIONS") return context.next();
  if (!isMeteredPath(url.pathname)) return context.next();
  if (isExemptPath(url.pathname)) return context.next();
  if (!isAnonymous(context.request)) return context.next();

  // No KV binding in dev / preview — pass through, origin still enforces.
  const kv = context.env.JPCITE_ANON_KV;
  if (!kv) return context.next();

  // CF-Connecting-IP is set by Cloudflare's edge for every request that
  // traverses CF. Absence here means one of: (a) a misconfigured route
  // that bypassed CF entirely, (b) a stripped/forged header chain, or
  // (c) a CF outage that fell back to a non-edge code path. None of these
  // are safe pass-throughs — letting the request reach origin would
  // either (i) bypass edge burst-shedding (case a) or (ii) let an attacker
  // who suppressed the header skip counting toward their /32 bucket
  // (case b). Return 503 `edge_ip_unavailable` so the caller retries via
  // a properly-routed path and origin never sees an un-bucketed anon
  // request. This is intentionally NOT a 429 — we don't know if they're
  // over quota, we just refuse to make a quota decision without an IP.
  const cfIp = context.request.headers.get("CF-Connecting-IP");
  if (!cfIp || !cfIp.trim()) {
    return new Response(
      JSON.stringify({
        error: "edge_ip_unavailable",
        detail:
          "Cloudflare edge could not determine the caller IP. " +
          "Retry the request through https://jpcite.com or https://api.jpcite.com.",
      }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "X-Edge-Rate-Limit": "anon-prefilter-ip-missing",
          "Cache-Control": "no-store",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }
  const ip = normaliseIp(cfIp);
  if (ip === "unknown") {
    // normaliseIp returned "unknown" despite a non-empty header — same
    // reasoning as above: refuse to make a quota decision without a
    // usable bucket key.
    return new Response(
      JSON.stringify({
        error: "edge_ip_unavailable",
        detail:
          "Cloudflare edge could not determine the caller IP. " +
          "Retry the request through https://jpcite.com or https://api.jpcite.com.",
      }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "X-Edge-Rate-Limit": "anon-prefilter-ip-missing",
          "Cache-Control": "no-store",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }

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
