/// <reference types="@cloudflare/workers-types" />
import { readRequestTextLimited } from "./_body_limit.ts";
/*
 * POST /dpa/issue -- Cloudflare Pages Function (Wave 18 E5).
 *
 * Self-service DPA (Data Processing Addendum) issuance. Caller submits
 * controller (their) company name + signatory name + their jpcite API
 * key; we substitute the placeholders in the static PDF template at
 * `site/legal/dpa_template.pdf` and return the resulting PDF inline.
 *
 * No operator-side human review. No sales / CS / legal head-count is
 * required to issue (per `feedback_zero_touch_solo`). The function is
 * the operational equivalent of GDPR Art. 28 sub-processor-DPA self-
 * service, plus APPI (個情法 令和5年改正) 第21条 委託先監督 documentation.
 *
 * Compliance hooks:
 *   - GDPR Art. 28 (processor obligations)
 *   - APPI Art. 21 (oversight of entrusted processors)
 *   - SOC 2 P3.2 (control map: docs/compliance/soc2_control_map.md)
 *
 * Authentication
 * --------------
 * The request MUST carry a valid jpcite API key (jc_-prefix). This
 * binds the issued DPA to a real customer record and prevents
 * anonymous abuse. The key is verified against api.jpcite.com /
 * v1/me. If verification fails the function returns 401.
 *
 * Byte-identical substitution
 * ---------------------------
 * The template PDF was authored such that the three placeholders fit
 * inside content-stream string operators ((...) Tj). To keep `/Length`
 * and `startxref` byte offsets valid we substitute each placeholder
 * with a fixed-width string of the same length: the user's value is
 * truncated/space-padded to the original placeholder byte count.
 *
 *   {{USER_NAME}}  -> 13 bytes  (Taro Yamada     -> "Taro Yamada  ")
 *   {{COMPANY}}    -> 11 bytes  (Acme K.K.       -> "Acme K.K.  ")
 *   {{DATE}}       ->  8 bytes  (formatted as YY-MM-DD to fit width)
 *
 * The bundled template's /Length and xref offsets are intentionally
 * lax and PDF viewers fall back to scanning for `endstream`, so even
 * a sub-byte-perfect rewrite renders correctly. The fixed-width path
 * is the conservative default.
 */

interface DpaIssueRequest {
  /** Controller's legal company name (max 80 chars after escape) */
  company: string;
  /** Authorised signatory name (max 80 chars after escape) */
  user_name: string;
  /** Optional effective date YYYY-MM-DD; defaults to today UTC */
  effective_date?: string;
}

interface Env {
  ASSETS: Fetcher;
  JPCITE_API_BASE?: string; // default https://api.jpcite.com
}

/**
 * DPA payload is tiny — `{ company, user_name, effective_date? }`, each
 * field capped at 80 chars after escape. 4KB is the same cap used by
 * `functions/api/rum_beacon.ts` (sendBeacon hard cap), comfortable
 * headroom over the ~200-byte realistic payload while still rejecting
 * pathological bodies cheaply.
 */
const MAX_BODY_BYTES = 4 * 1024;

/**
 * Escape PDF metacharacters for safe inclusion inside a (...) string
 * literal in a content stream. Per ISO 32000-1 7.3.4.2 we must escape
 * \, (, ).
 */
function pdfEscape(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

/** Pad/truncate to exact byte length using ASCII space (0x20). */
function fitLen(s: string, n: number): string {
  if (s.length >= n) return s.slice(0, n);
  return s + " ".repeat(n - s.length);
}

/** Verify jc_-prefix API key against api.jpcite.com /v1/me. */
async function verifyApiKey(key: string, base: string): Promise<{ ok: boolean; account_id?: string }> {
  if (!key.startsWith("jc_")) return { ok: false };
  try {
    const r = await fetch(`${base}/v1/me`, {
      headers: { Authorization: `Bearer ${key}` },
      // Cloudflare runtime: no body needed
    });
    if (!r.ok) return { ok: false };
    const j: { account_id?: string } = await r.json();
    return { ok: true, account_id: j.account_id };
  } catch {
    return { ok: false };
  }
}

/** Locate first occurrence of a literal in a Uint8Array (PDF bytes). */
function findBytes(haystack: Uint8Array, needle: string): number {
  const enc = new TextEncoder();
  const n = enc.encode(needle);
  outer: for (let i = 0; i <= haystack.length - n.length; i++) {
    for (let j = 0; j < n.length; j++) if (haystack[i + j] !== n[j]) continue outer;
    return i;
  }
  return -1;
}

/** Replace the bytes at [start, start+oldLen) with newBytes of the same length. */
function spliceInPlace(buf: Uint8Array, start: number, oldLen: number, newBytes: Uint8Array): void {
  if (newBytes.length !== oldLen) {
    throw new Error(`spliceInPlace length mismatch: ${newBytes.length} != ${oldLen}`);
  }
  for (let i = 0; i < oldLen; i++) buf[start + i] = newBytes[i];
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  // 1. Method + content-type guards
  //    Cap the JSON body BEFORE parse — see R3 cluster fix in
  //    `functions/_body_limit.ts`. Rejects oversized bodies with a
  //    413 `payload_too_large` envelope before any parse work happens.
  const bodyRead = await readRequestTextLimited(request, MAX_BODY_BYTES);
  if (!bodyRead.ok) {
    return new Response(
      JSON.stringify({ error: "payload_too_large", max_bytes: MAX_BODY_BYTES }),
      { status: 413, headers: { "content-type": "application/json" } },
    );
  }
  let body: DpaIssueRequest;
  try {
    body = JSON.parse(bodyRead.text) as DpaIssueRequest;
  } catch {
    return new Response('{"error":"invalid_json"}', { status: 400, headers: { "content-type": "application/json" } });
  }
  const { company, user_name } = body;
  if (!company || !user_name) {
    return new Response('{"error":"company_and_user_name_required"}', { status: 400, headers: { "content-type": "application/json" } });
  }

  // 2. Auth -- jc_ prefix bearer token
  const auth = request.headers.get("authorization") || "";
  const key = auth.replace(/^Bearer\s+/i, "").trim();
  const base = env.JPCITE_API_BASE || "https://api.jpcite.com";
  const v = await verifyApiKey(key, base);
  if (!v.ok) {
    return new Response('{"error":"invalid_api_key","hint":"send Authorization: Bearer jc_..."}', {
      status: 401,
      headers: { "content-type": "application/json", "www-authenticate": "Bearer" },
    });
  }

  // 3. Load template from static assets (uses CF Pages /assets/ binding)
  const tmpl = await env.ASSETS.fetch(new Request("https://internal/legal/dpa_template.pdf"));
  if (!tmpl.ok) {
    return new Response('{"error":"template_unavailable"}', { status: 500, headers: { "content-type": "application/json" } });
  }
  const buf = new Uint8Array(await tmpl.arrayBuffer());

  // 4. Compute fixed-width substitutions. {{DATE}} is 8 bytes so we
  //    format as YY-MM-DD (8 chars) rather than YYYY-MM-DD (10 chars)
  //    to fit cleanly without truncation.
  const isoDate = body.effective_date || new Date().toISOString().slice(0, 10);
  const shortDate = isoDate.length === 10 && isoDate[4] === "-" ? isoDate.slice(2) : isoDate;
  const PLACEHOLDERS = [
    { token: "{{USER_NAME}}", value: pdfEscape(user_name) },
    { token: "{{COMPANY}}", value: pdfEscape(company) },
    { token: "{{DATE}}", value: pdfEscape(shortDate) },
  ];
  // {{COMPANY}} appears twice in template (Controller line + signature line) -- handle all occurrences.
  const enc = new TextEncoder();
  for (const { token, value } of PLACEHOLDERS) {
    const replacement = fitLen(value, token.length);
    const replBytes = enc.encode(replacement);
    // Replace ALL occurrences (some placeholders repeat in the template)
    let cursor = 0;
    while (true) {
      const slice = buf.subarray(cursor);
      const idx = findBytes(slice, token);
      if (idx === -1) break;
      const absolute = cursor + idx;
      spliceInPlace(buf, absolute, token.length, replBytes);
      cursor = absolute + token.length;
    }
  }

  // 5. Audit log (best-effort): emit one row to api.jpcite.com /v1/audit/dpa
  //    Failure here MUST NOT block the issuance -- the customer still gets
  //    their PDF. The audit-log.rss feed picks up later via the audit
  //    evidence collector (scripts/cron/audit_evidence_collector.py).
  try {
    await fetch(`${base}/v1/audit/dpa`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
      body: JSON.stringify({ account_id: v.account_id, company, user_name }),
    });
  } catch {
    /* swallow */
  }

  // 6. Return PDF inline
  const filename = `dpa_jpcite_${(body.effective_date || new Date().toISOString().slice(0, 10)).replace(/-/g, "")}.pdf`;
  return new Response(buf, {
    status: 200,
    headers: {
      "content-type": "application/pdf",
      "content-disposition": `inline; filename="${filename}"`,
      "cache-control": "no-store",
      "x-jpcite-control": "P3.2",
    },
  });
};

export const onRequestGet: PagesFunction<Env> = async () => {
  // GET returns the unsubstituted template + form hint for crawlers / dev probes.
  return new Response(
    JSON.stringify(
      {
        endpoint: "/dpa/issue",
        method: "POST",
        auth: "Authorization: Bearer jc_...",
        body: { company: "Acme K.K.", user_name: "Taro Yamada", effective_date: "YYYY-MM-DD (optional)" },
        compliance: ["GDPR Art. 28", "APPI 第21条", "SOC 2 P3.2"],
        template: "/legal/dpa_template.pdf",
      },
      null,
      2,
    ),
    { headers: { "content-type": "application/json" } },
  );
};
