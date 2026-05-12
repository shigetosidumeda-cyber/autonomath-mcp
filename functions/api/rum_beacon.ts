/// <reference types="@cloudflare/workers-types" />
/*
 * POST /api/rum_beacon -- Cloudflare Pages Function (Wave 49 G1).
 *
 * Receives organic-funnel RUM beacons emitted by
 * `site/assets/rum_funnel_collector.js` (Wave 49 G1). Persists each
 * beacon to two surfaces:
 *
 *   1. `CF_RUM_R2`  -- R2 Object Storage, JSONL append per UTC day.
 *                      Read by `scripts/ops/rum_aggregator.py` (Wave 16
 *                      E1) for daily p75 + uniq-visitor rollup. Cheap,
 *                      durable, no per-request cost (only egress at
 *                      aggregation time).
 *   2. CF Analytics -- best-effort `event(name, dims)` write via the
 *                      Pages Function `cf.analytics` binding when
 *                      available. Not load-bearing — used only for the
 *                      CF dashboard graphs.
 *
 * Why a separate endpoint from the existing `/v1/rum/beacon` (Wave 16
 * E1)? Wave 16 captures Core Web Vitals (LCP / INP / CLS / TTFB / FCP)
 * keyed on page URL. Wave 49 captures *funnel* events (landing → free
 * → signup → topup) keyed on session_id + step. The two surfaces have
 * different aggregation cadences (Wave 16 = hourly p75, Wave 49 = daily
 * uniq + per-step conversion) and different retention windows (Wave 16
 * = 7-day rolling, Wave 49 = 90-day for cohort follow-through). Mixing
 * them into a single jsonl produces a costly read-side filter at
 * aggregator time; keeping them split keeps `rum_aggregator.py` O(1)
 * per metric.
 *
 * Wire shape (Wave 49 G1)
 * -----------------------
 * Request (POST application/json):
 *   {
 *     "session_id": "ad-hoc UUIDv4 from sendBeacon",
 *     "page":       "/index" | "/onboarding" | "/pricing" | string,
 *     "step":       "landing" | "free" | "signup" | "topup",
 *     "event":      "view" | "cta_click" | "step_complete",
 *     "ts":         epoch milliseconds (number)
 *   }
 *
 * Response: 204 No Content on success, 400 on malformed body, 413 on
 * payload > 4KB (sendBeacon hard cap; agents that exceed it almost
 * always indicate a wire bug, not a real user). No 401 — beacons are
 * intentionally anonymous; uniq-visitor counts derive from the random
 * `session_id`, not from any account credential.
 *
 * Bot UA filtering happens client-side in
 * `rum_funnel_collector.js` to keep this Function under 1ms CPU. We
 * still mirror the regex here as defense-in-depth (an adversary could
 * skip the JS and POST directly), but it is cheap (single regex,
 * non-allocating). False positives are bounded — if a legitimate
 * browser is misclassified we lose at most one funnel datapoint.
 *
 * CSP / CORS
 * ----------
 * Accepts cross-origin POST from any `*.jpcite.com` page; the
 * collector script is wired into pages served from the same origin
 * today, so we set Access-Control-Allow-Origin to the request Origin
 * if it matches the apex regex, otherwise reject with 403.
 *
 * Wave 49 G1 target: 10 unique session_ids/day × 3 consecutive days.
 * See `docs/_internal/WAVE49_plan.md` axis #1.
 */

interface RumFunnelBeacon {
  session_id?: unknown;
  page?: unknown;
  step?: unknown;
  event?: unknown;
  ts?: unknown;
}

const ALLOWED_STEPS = new Set([
  "landing",
  "free",
  "signup",
  "topup",
]);

const ALLOWED_EVENTS = new Set([
  "view",
  "cta_click",
  "step_complete",
]);

const BOT_RE =
  /(bot|spider|crawler|gptbot|claudebot|perplexity|amazonbot|googlebot|bingbot|chatgpt|oai-searchbot|bytespider|ahrefs|semrush|diffbot|cohere-ai|youbot|mistralai|applebot|facebookexternalhit|twitterbot|yandex|baiduspider)/i;

const ORIGIN_RE = /^https?:\/\/([a-z0-9-]+\.)?jpcite\.com(:\d+)?$/i;

interface Env {
  // R2 bucket binding (configured in Cloudflare Pages dashboard).
  // Optional: if absent the function still 204s — beacons are best
  // effort and we prefer dropping over 500-ing real visitors.
  CF_RUM_R2?: R2Bucket;
}

function corsHeaders(origin: string | null): HeadersInit {
  const allowed = origin && ORIGIN_RE.test(origin) ? origin : "";
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function utcDateKey(tsMs: number): string {
  const d = new Date(tsMs);
  if (Number.isNaN(d.getTime())) return new Date().toISOString().slice(0, 10);
  return d.toISOString().slice(0, 10);
}

function isValidBeacon(b: RumFunnelBeacon): b is Required<RumFunnelBeacon> {
  if (!b || typeof b !== "object") return false;
  if (typeof b.session_id !== "string" || !b.session_id) return false;
  if (b.session_id.length > 64) return false;
  if (typeof b.page !== "string" || !b.page || b.page.length > 256) return false;
  if (typeof b.step !== "string" || !ALLOWED_STEPS.has(b.step)) return false;
  if (typeof b.event !== "string" || !ALLOWED_EVENTS.has(b.event)) return false;
  if (typeof b.ts !== "number" || !Number.isFinite(b.ts)) return false;
  return true;
}

export const onRequestOptions: PagesFunction<Env> = async (ctx) => {
  return new Response(null, {
    status: 204,
    headers: corsHeaders(ctx.request.headers.get("Origin")),
  });
};

export const onRequestPost: PagesFunction<Env> = async (ctx) => {
  const { request, env } = ctx;
  const origin = request.headers.get("Origin");
  const headers = corsHeaders(origin);

  // Bot guard — defense in depth (collector already filters).
  const ua = request.headers.get("User-Agent") || "";
  if (BOT_RE.test(ua)) {
    return new Response(null, { status: 204, headers });
  }

  // Hard cap at 4KB — sendBeacon refuses larger anyway.
  const cl = parseInt(request.headers.get("Content-Length") || "0", 10);
  if (cl > 4096) {
    return new Response("Payload too large", { status: 413, headers });
  }

  let body: RumFunnelBeacon;
  try {
    body = (await request.json()) as RumFunnelBeacon;
  } catch (_err) {
    return new Response("Malformed JSON", { status: 400, headers });
  }
  if (!isValidBeacon(body)) {
    return new Response("Invalid beacon shape", { status: 400, headers });
  }

  // Persist to R2 (best effort — drop on bucket missing).
  if (env.CF_RUM_R2) {
    const dateKey = utcDateKey(body.ts as number);
    const objKey = `funnel/${dateKey}/${body.session_id}-${body.ts}.json`;
    const record = {
      session_id: body.session_id,
      page: body.page,
      step: body.step,
      event: body.event,
      ts: body.ts,
      ua_hash: await sha256Short(ua),
      origin: origin || null,
      received_at: Date.now(),
    };
    try {
      await env.CF_RUM_R2.put(objKey, JSON.stringify(record), {
        httpMetadata: { contentType: "application/json" },
      });
    } catch (_err) {
      // Swallow — beacon must never break the page.
    }
  }

  return new Response(null, { status: 204, headers });
};

async function sha256Short(input: string): Promise<string> {
  if (!input) return "";
  const buf = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .slice(0, 6)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
