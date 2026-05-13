/// <reference types="@cloudflare/workers-types" />
/*
 * Shared body-size guard for Cloudflare Pages Functions (Wave 49 R3).
 *
 * Background
 * ----------
 * Several edge handlers parse `await request.json()` directly without a
 * cap on payload size. A misbehaving client (or attacker) can stream a
 * multi-MB body and inflate worker CPU + memory, or trigger Pages 1MB
 * request-body limits non-deterministically. The fix is a single helper
 * that:
 *
 *   1. Short-circuits via `content-length` when the client advertises a
 *      size > maxBytes (rejects without reading a byte).
 *   2. Streams the body chunk-by-chunk, aborting the reader as soon as
 *      total exceeds maxBytes (so the upper bound is hard, not
 *      content-length-dependent).
 *   3. Returns a discriminated union so the caller chooses the
 *      response shape (the various handlers want slightly different
 *      JSON envelopes / status semantics).
 *
 * Why a separate file (under `functions/_body_limit.ts`)
 * ------------------------------------------------------
 * Cloudflare Pages routes are derived from filenames; the leading `_`
 * keeps this module non-routable (Pages reserves `_*` prefixes for
 * non-route assets, same convention as `functions/api/_middleware.ts`).
 * Importing relative-up works because esbuild + Pages both resolve
 * relative TS imports inside the `functions/` tree.
 *
 * Pattern parallel
 * ----------------
 * The same `readRequestTextLimited` pattern appears (duplicated as
 * pre-share copies) in:
 *   - functions/webhook_router_v2.ts   (MAX_BODY_BYTES=64KB)
 *   - functions/webhook_router.ts      (MAX_BODY_BYTES=64KB)
 *   - functions/api/rum_beacon.ts      (MAX_BODY_BYTES=4KB)
 *   - functions/api_proxy.ts           (MAX_PROXY_BODY_BYTES=1MB; variant name)
 *   - functions/x402_handler.ts        (MAX_X402_JSON_BODY_BYTES=8KB; throws sentinel)
 * Those copies are intentionally left alone in R3 (separate refactor
 * scope); R3 wires only the two missing-guard handlers (dpa_issue,
 * ab_assign) onto this shared helper.
 */

export type LimitedTextResult =
  | { ok: true; text: string }
  | { ok: false };

export function contentLengthExceeds(headers: Headers, maxBytes: number): boolean {
  const value = headers.get("content-length");
  if (!value) return false;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > maxBytes;
}

export async function readRequestTextLimited(
  request: Request,
  maxBytes: number,
): Promise<LimitedTextResult> {
  if (contentLengthExceeds(request.headers, maxBytes)) {
    return { ok: false };
  }
  if (!request.body) {
    return { ok: true, text: "" };
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
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

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, text: new TextDecoder().decode(bytes) };
}
