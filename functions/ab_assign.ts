/// <reference types="@cloudflare/workers-types" />
/*
 * H5: A/B test infrastructure for jpcite — CF Pages Function that assigns
 * a deterministic bucket (a|b) to each anonymous visitor and persists the
 * choice in the `jpcite_ab_bucket` cookie for 30 days.
 *
 * Why a CF Pages Function (not client-side JS)?
 *   1. The bucket needs to be readable BEFORE any meaningful paint so
 *      LCP-critical hero copy / CTA / pricing presentation can vary
 *      without a hydration flash.
 *   2. Edge-issued cookies survive third-party-cookie disablement, ad
 *      blockers, and Safari ITP truncation (ITP only truncates JS-set
 *      cookies, not edge-set ones).
 *   3. The CF Pages runtime gives us `crypto.randomUUID()` + headers
 *      without pulling in any runtime dependency.
 *
 * Endpoints
 * ---------
 *   GET  /ab/assign?test=<test_id>[&force=a|b]
 *        Reads (or sets) the cookie, returns the assigned bucket as
 *        JSON: { test: "...", bucket: "a"|"b", new: bool }.
 *        Used by the landing page header script for client-side variant
 *        rendering after first paint and by analytics for conversion
 *        joining.
 *
 *   POST /ab/conversion
 *        Records a conversion event keyed on the visitor's current bucket.
 *        The Stripe webhook fires this server-to-server when a checkout
 *        completes. Payload: { test_id, event, value, cookie_bucket }.
 *        Forwards to the upstream API for warehouse persistence.
 *
 * Cookie semantics
 * ----------------
 *   name        jpcite_ab_bucket
 *   value       <test_id>:<bucket>[;<test_id>:<bucket>...]
 *               Multiple concurrent tests are stored in one cookie to keep
 *               under the 4KB header budget.
 *   max-age     2_592_000 (30 days)
 *   domain      .jpcite.com (apex + subdomains)
 *   path        /
 *   secure      true
 *   sameSite    Lax
 *   httpOnly    false (we need client-side JS to flip CTA copy without RTT)
 *
 * Assignment algorithm
 * --------------------
 *   1. Read existing cookie. If `<test_id>:<a|b>` is present, return it.
 *   2. Otherwise hash a stable identity (CF-Connecting-IP + UA tail) into
 *      a 32-bit unsigned integer and mod-2. This gives a deterministic,
 *      stateless bucket so a visitor without cookies still lands on the
 *      same variant on every request — important for crawlers that drop
 *      cookies between fetches.
 *   3. Persist the new assignment by appending to the cookie.
 *
 * The `force` query param overrides assignment (operator QA channel).
 *
 * Sticky bucket guarantee
 * -----------------------
 * Once a visitor is in bucket A, they stay in bucket A for the full 30
 * day window, regardless of UA / IP changes — the cookie wins over the
 * hash. This is the contract conversion-aggregator expects: every Stripe
 * webhook fire carries the cookie bucket, not a re-derived one.
 *
 * Confidence aggregator
 * ---------------------
 * The companion `scripts/ops/ab_test_results.py` (not shipped here)
 * computes a 95% confidence two-proportion z-test on the conversion
 * jsonl. The math is intentionally kept off-edge to avoid bundling
 * statistics into the function.
 *
 * Privacy note
 * ------------
 * No PII is stored in the cookie. The hash takes only the truncated IP
 * (first 3 octets) + UA fingerprint, never a full identifier. The cookie
 * is first-party + scoped to the jpcite.com apex; we do not share or
 * sell the bucket value.
 */

export interface Env {
  ASSETS: Fetcher;
  JPCITE_API_BASE?: string;
}

const COOKIE_NAME = "jpcite_ab_bucket";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days
const COOKIE_DOMAIN = ".jpcite.com";

const KNOWN_TESTS = new Set<string>([
  // landing page copy variant
  "landing_copy_v1",
  // CTA color/word variant
  "cta_variant_v1",
  // pricing presentation (per-req vs monthly cap)
  "pricing_presentation_v1",
]);

type Bucket = "a" | "b";

function parseCookie(req: Request): Map<string, string> {
  const out = new Map<string, string>();
  const raw = req.headers.get("Cookie");
  if (!raw) return out;
  for (const part of raw.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const k = part.slice(0, eq).trim();
    const v = part.slice(eq + 1).trim();
    if (k) out.set(k, decodeURIComponent(v));
  }
  return out;
}

function parseAssignments(raw: string | undefined): Map<string, Bucket> {
  const map = new Map<string, Bucket>();
  if (!raw) return map;
  for (const pair of raw.split(";")) {
    const trimmed = pair.trim();
    if (!trimmed) continue;
    const colon = trimmed.indexOf(":");
    if (colon < 0) continue;
    const test = trimmed.slice(0, colon).trim();
    const b = trimmed.slice(colon + 1).trim().toLowerCase();
    if (test && (b === "a" || b === "b")) {
      map.set(test, b);
    }
  }
  return map;
}

function serializeAssignments(map: Map<string, Bucket>): string {
  return Array.from(map.entries())
    .map(([t, b]) => `${t}:${b}`)
    .join(";");
}

function buildCookie(value: string): string {
  const safe = encodeURIComponent(value);
  return [
    `${COOKIE_NAME}=${safe}`,
    `Max-Age=${COOKIE_MAX_AGE}`,
    `Domain=${COOKIE_DOMAIN}`,
    "Path=/",
    "Secure",
    "SameSite=Lax",
  ].join("; ");
}

function truncIp(ip: string | null | undefined): string {
  if (!ip) return "";
  // IPv4 — keep /24, IPv6 — keep first 4 groups.
  if (ip.includes(":")) {
    return ip.split(":").slice(0, 4).join(":");
  }
  return ip.split(".").slice(0, 3).join(".");
}

async function deterministicBucket(test: string, req: Request): Promise<Bucket> {
  const ip = truncIp(req.headers.get("CF-Connecting-IP"));
  const ua = (req.headers.get("User-Agent") || "").slice(-32);
  const fingerprint = `${test}|${ip}|${ua}`;
  const data = new TextEncoder().encode(fingerprint);
  const buf = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(buf);
  // Take the first 4 bytes as a uint32 and mod-2.
  const u32 = (bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
  return (u32 >>> 0) % 2 === 0 ? "a" : "b";
}

function jsonResponse(body: unknown, init: ResponseInit = {}, setCookie?: string): Response {
  const headers: HeadersInit = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...(init.headers || {}),
  };
  if (setCookie) {
    (headers as Record<string, string>)["Set-Cookie"] = setCookie;
  }
  return new Response(JSON.stringify(body), { ...init, headers });
}

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);
  const test = (url.searchParams.get("test") || "").trim();
  if (!test || !KNOWN_TESTS.has(test)) {
    return jsonResponse({ error: "unknown_test", known: Array.from(KNOWN_TESTS) }, { status: 400 });
  }
  const cookies = parseCookie(context.request);
  const assignments = parseAssignments(cookies.get(COOKIE_NAME));

  const forced = (url.searchParams.get("force") || "").toLowerCase();
  let bucket: Bucket;
  let isNew = false;
  if (forced === "a" || forced === "b") {
    bucket = forced;
    assignments.set(test, bucket);
    isNew = true;
  } else if (assignments.has(test)) {
    bucket = assignments.get(test) as Bucket;
  } else {
    bucket = await deterministicBucket(test, context.request);
    assignments.set(test, bucket);
    isNew = true;
  }

  return jsonResponse(
    {
      test,
      bucket,
      new: isNew,
      issued_at: new Date().toISOString(),
    },
    { status: 200 },
    isNew ? buildCookie(serializeAssignments(assignments)) : undefined,
  );
};

interface ConversionPayload {
  test_id?: string;
  event?: string;
  value?: number;
  cookie_bucket?: Bucket;
  external_ref?: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);
  if (!url.pathname.endsWith("/conversion")) {
    return jsonResponse({ error: "method_not_allowed" }, { status: 405 });
  }
  let payload: ConversionPayload;
  try {
    payload = (await context.request.json()) as ConversionPayload;
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }
  const test_id = (payload.test_id || "").trim();
  if (!test_id || !KNOWN_TESTS.has(test_id)) {
    return jsonResponse({ error: "unknown_test", known: Array.from(KNOWN_TESTS) }, { status: 400 });
  }
  const cookies = parseCookie(context.request);
  const assignments = parseAssignments(cookies.get(COOKIE_NAME));
  const cookie_bucket = payload.cookie_bucket || assignments.get(test_id);
  if (cookie_bucket !== "a" && cookie_bucket !== "b") {
    return jsonResponse({ error: "no_bucket" }, { status: 400 });
  }

  // Forward to the upstream API for warehouse persistence. We don't store on
  // the edge — the analytics warehouse is the SOT.
  const api_base = context.env.JPCITE_API_BASE || "https://api.jpcite.com";
  const event_record = {
    test_id,
    event: (payload.event || "conversion").trim() || "conversion",
    value: typeof payload.value === "number" ? payload.value : null,
    bucket: cookie_bucket,
    external_ref: payload.external_ref || null,
    occurred_at: new Date().toISOString(),
    user_agent: context.request.headers.get("User-Agent") || null,
  };

  let upstream_ok = false;
  try {
    const res = await fetch(`${api_base}/v1/ab/conversion`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(event_record),
    });
    upstream_ok = res.ok;
  } catch {
    upstream_ok = false;
  }

  return jsonResponse({ ok: true, upstream_ok, recorded: event_record }, { status: 200 });
};

export const onRequest: PagesFunction<Env> = async (context) => {
  if (context.request.method === "GET") {
    return onRequestGet(context);
  }
  if (context.request.method === "POST") {
    return onRequestPost(context);
  }
  return jsonResponse({ error: "method_not_allowed", method: context.request.method }, { status: 405 });
};
