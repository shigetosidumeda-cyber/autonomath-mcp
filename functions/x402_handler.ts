/// <reference types="@cloudflare/workers-types" />
/*
 * ============================================================================
 * SECURITY DECISION — EIP-191/EIP-712 payer signature verification (residual P1)
 * ============================================================================
 *
 *   Status:    FAIL-CLOSED (documented residual P1, not resolved).
 *   Decision:  This handler does NOT implement off-chain EIP-191 / EIP-712
 *              secp256k1 signature recovery on the Cloudflare Workers edge.
 *              Any `/x402/verify` request that carries a `payer_signature`
 *              field is rejected with HTTP 402 + reason
 *              `payer_signature_verification_unavailable` (see `verifyTx`).
 *   Rationale: Cloudflare Workers' WebCrypto surface does NOT expose
 *              secp256k1 ECDSA verify / public-key recovery. The only safe
 *              implementations bundle audited libraries (e.g. `@noble/secp256k1`
 *              or `ethers/utils/computeAddress`), which we have not vetted +
 *              size-budgeted on the edge yet. Shipping a hand-rolled curve
 *              recovery would violate the "do not fake cryptographic
 *              verification" rule (packet A5 risk note) and the project rule
 *              "no LLM / no unreviewed crypto in production" — a forged or
 *              partially-validated signature would mint metered API keys
 *              without USDC settlement.
 *   Substitute auth path that IS verified end-to-end:
 *              Settlement is authenticated by the conjunction of
 *                (1) HMAC-signed `quote_id` (binds amount + recipient +
 *                    payer_address + agent_id + token + chain + expiry,
 *                    constant-time compared in `parseQuoteId`),
 *                (2) on-chain ERC20 Transfer log (matches token contract,
 *                    `keccak256("Transfer(address,address,uint256)")` topic
 *                    `0xddf252ad...`, payer in topics[1], recipient in
 *                    topics[2], amount >= quoted micro-USDC) probed via
 *                    `eth_getTransactionReceipt`,
 *                (3) replay defence: `tx_hash` is recorded in
 *                    `JPCITE_X402_KV` for `NONCE_TTL_SECONDS` (25 h) after
 *                    the origin `/v1/billing/x402/issue_key` accepts the
 *                    redemption,
 *                (4) origin-side `am_x402_payment_log` UNIQUE(txn_hash) gate
 *                    is the authoritative duplicate-mint guard (the edge
 *                    treats the origin 409 `tx_already_redeemed` as the only
 *                    case that burns the edge replay key).
 *              The four together bind a settled, non-replayed USDC transfer
 *              to a specific agent + quote without ever needing a payer-side
 *              off-chain signature.
 *   Residual P1 exit criteria (to flip from FAIL-CLOSED to REAL VERIFICATION):
 *              (a) Vetted `@noble/secp256k1` (or equivalent) bundled in the
 *                  Worker, size-budget verified, audited dependency.
 *              (b) EIP-191 (`personal_sign`) + EIP-712 typed-data domain
 *                  separator pinned to the same fields the HMAC-signed
 *                  quote already carries (chain_id, recipient, token, amount,
 *                  payer, agent_id, expires_at).
 *              (c) Constant-time hash + recovery comparison; reject any
 *                  signature whose recovered address mismatches the quoted
 *                  `payer_address` (no normalization shortcuts).
 *              (d) Tests covering: valid signature happy path, replay,
 *                  mutated payload, wrong chain_id, mismatched payer.
 *              (e) Security review sign-off recorded in this comment block.
 *
 *   DO NOT remove the FAIL-CLOSED branch in `verifyTx` without all of (a)-(e).
 *   The `test_x402_edge_verify_rejects_unverified_payer_signature_without_rpc`
 *   test + `test_x402_edge_quote_binds_agent_and_payer` source-grep guard
 *   enforce this.
 *
 * x402 USDC HTTP 402 Payment Required handler.
 *
 * x402 is the cryptocurrency-native AI-agent payment rail. Instead of the
 * Stripe/JCB rails used by ACP (file `src/jpintel_mcp/billing/acp_integration.py`),
 * an agent on the x402 rail receives a HTTP 402 response with a USDC payment
 * quote, signs a USDC transfer on-chain, and re-submits the request with the
 * settled transaction hash in the `X-Payment` header. The Cloudflare Pages
 * Function in this file handles the 402 challenge + the post-payment verify.
 *
 * Endpoint shape (mounted at `/x402/*` via project `_routes.json`):
 *
 *   GET  /x402/discovery
 *     -> 200 JSON with chain id + USDC token address + ¥3/req quote shape.
 *
 *   POST /x402/quote
 *     body: { "path": "/v1/...", "method": "GET", "req_count": 1,
 *             "agent_id": "...", "payer_address": "0x..." }
 *     -> 200 JSON quote with USDC amount + payment address.
 *
 *   POST /x402/verify
 *     body: { "tx_hash": "0x...", "quote_id": "...", "agent_id": "..." }
 *     -> 200 { "api_key": "am_...", "expires_at": "..." }
 *     -> 402 if tx not settled / wrong amount / wrong recipient
 *
 *   * any other path *  -> 402 HTTP Payment Required with a quote bundle
 *     matching the anonymous rate-limit edge 402 challenge format.
 *
 * Settlement target:
 *   - Network:   Base mainnet (Coinbase L2, chosen for sub-second finality
 *                and the lowest gas fee among USDC-native L2s).
 *   - Token:     USDC (Native, Circle issuance, 6-decimal).
 *   - Recipient: `JPCITE_X402_ADDRESS` (Pages secret).
 *   - Price:     ¥3 / req converted to USDC at the rolling 5-min JPY/USD
 *                rate the function caches in `JPCITE_X402_KV`. The
 *                marketing copy is "~$0.02 / req"; the actual quote is
 *                always computed live, never hard-coded.
 *
 * Latency target:
 *   - quote creation     < 50 ms (KV read + sign)
 *   - settlement check   < 2 s   (1 confirm on Base ≈ 200 ms × 3 retries)
 *
 * Edge payment alignment:
 *   The existing `functions/anon_rate_limit_edge.ts` already returns 402
 *   on anon-quota exhaustion. x402_handler.ts extends that pattern by
 *   shipping a `WWW-Payment` quote header in the 402 body so an agent
 *   honoring x402-spec can settle and retry without a human round trip.
 *
 * Memory refs:
 *   - feedback_zero_touch_solo : self-serve cryptocurrency rail, no operator review.
 *   - feedback_no_priority_question : 1 currency / 1 unit price / no tier.
 *   - feedback_autonomath_no_api_use : no LLM call inside settlement code.
 *   - project_autonomath_business_model : ¥3/req metered, anon 3 req/日 IP.
 */

export interface Env {
  // KV cache for FX + nonce dedup.
  JPCITE_X402_KV?: KVNamespace;
  // Pages secret: receiving wallet address (Base mainnet USDC).
  JPCITE_X402_ADDRESS?: string;
  // Pages secret: shared HMAC secret used to sign quote_ids so a leaked
  // quote cannot be replayed on a different deployment.
  JPCITE_X402_QUOTE_SECRET?: string;
  // Pages secret: Base RPC URL (Alchemy / Quicknode / public).
  JPCITE_X402_RPC_URL?: string;
  // Fallback static JPY->USDC rate when KV cache is cold.
  JPCITE_X402_FALLBACK_JPY_PER_USDC?: string;
  // Forwarding target for verified-paid requests.
  JPCITE_API_BASE?: string;
  // Shared edge -> origin secret required by /v1/billing/x402/issue_key.
  JPCITE_X402_ORIGIN_SECRET?: string;
  // Deployment markers. In production, x402 requires KV for replay and
  // amplification guards instead of silently degrading to an unbounded edge.
  JPCITE_ENV?: string;
  JPINTEL_ENV?: string;
  ENVIRONMENT?: string;
  CF_PAGES_BRANCH?: string;
}

// USDC contract addresses by chain. We pin Base mainnet by default but
// keep the map open for future expansion (Optimism, Arbitrum, etc.) once
// settlement primitives exist on those chains for the operator.
const USDC_BY_CHAIN: Record<string, { address: string; decimals: number; name: string }> = {
  "8453": {
    address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", // Native USDC on Base
    decimals: 6,
    name: "USDC",
  },
};

const X402_CHAIN_ID = "8453"; // Base mainnet
const PER_REQ_JPY = 3; // ¥3/req (税別); 税込 ¥3.30 — tax is collected separately via Stripe ACP
const QUOTE_TTL_SECONDS = 5 * 60; // 5-minute quote window — matches FX cache TTL
const NONCE_TTL_SECONDS = 25 * 60 * 60; // 25h replay-defence window for tx hashes
const MAX_X402_JSON_BODY_BYTES = 8 * 1024;
const RPC_FETCH_TIMEOUT_MS = 1200;
const NEGATIVE_TX_CACHE_SETTLE_TTL_SECONDS = 15;
const NEGATIVE_TX_CACHE_FAILURE_TTL_SECONDS = 5 * 60;
const X402_GUARD_BUCKET_TTL_SECONDS = 90;
const MAX_QUOTE_ATTEMPTS_PER_BUCKET = 30;
const MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET = 6;
const MAX_VERIFY_RPC_ATTEMPTS_PER_SOURCE_BUCKET = 6;
const ERC20_TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const X402_KV_HEALTH_KEY = "health:x402_kv_required";

// Anonymous agents that hit a metered path without a key get the x402 challenge.
function isMeteredPath(path: string): boolean {
  if (path.startsWith("/v1/")) return true;
  if (path.startsWith("/api/")) return true;
  return false;
}

function isExemptPath(path: string): boolean {
  return (
    path === "/v1/healthz" ||
    path === "/v1/readyz" ||
    path === "/v1/openapi.json" ||
    path === "/x402/discovery" ||
    path === "/x402/quote" ||
    path === "/x402/verify"
  );
}

function isProductionEnv(env: Env): boolean {
  const values = [env.JPCITE_ENV, env.JPINTEL_ENV, env.ENVIRONMENT]
    .map((value) => String(value ?? "").trim().toLowerCase())
    .filter(Boolean);
  if (values.some((value) => value === "prod" || value === "production")) return true;
  return String(env.CF_PAGES_BRANCH ?? "").trim().toLowerCase() === "main";
}

async function requireProductionKvHealthy(env: Env): Promise<boolean> {
  if (!isProductionEnv(env)) return true;
  const kv = env.JPCITE_X402_KV;
  if (!kv) return false;
  try {
    await kv.get(X402_KV_HEALTH_KEY);
    await kv.put(X402_KV_HEALTH_KEY, "1", { expirationTtl: 60 });
    return true;
  } catch {
    return false;
  }
}

// HMAC-SHA256 helper. CF Workers expose WebCrypto natively; we never pull
// in a node-crypto polyfill.
async function hmacSign(secret: string, payload: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) {
    out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return out === 0;
}

function base64UrlEncode(input: string): string {
  const bytes = new TextEncoder().encode(input);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(input: string): string {
  const pad = "=".repeat((4 - (input.length % 4)) % 4);
  const binary = atob((input + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// Live JPY -> USDC rate, cached 5 minutes in KV. Falls back to static env.
async function jpyPerUsdc(env: Env): Promise<number> {
  const fallback = Number(env.JPCITE_X402_FALLBACK_JPY_PER_USDC ?? "150");
  if (!env.JPCITE_X402_KV) return fallback;
  try {
    const cached = await env.JPCITE_X402_KV.get("fx:jpy_per_usdc");
    if (cached) {
      const n = Number(cached);
      if (Number.isFinite(n) && n > 0) return n;
    }
  } catch {
    // KV outage: fall through to static fallback.
  }
  return fallback;
}

interface Quote {
  quote_id: string;
  path: string;
  method: string;
  req_count: number;
  amount_jpy: number;
  amount_usdc: string; // string-form to preserve 6-decimal precision
  amount_usdc_micro: string; // integer micro-USDC (atomic units)
  chain_id: string;
  token_address: string;
  recipient: string;
  agent_id: string;
  payer_address: string;
  expires_at: number; // unix seconds
  signature: string;
}

interface BuildQuoteOpts {
  path: string;
  method: string;
  reqCount: number;
  agentId: string;
  payerAddress: string;
}

interface QuoteIdPayload {
  v: 1;
  u: string; // micro-USDC atomic amount
  r: string; // normalized recipient
  p: string; // normalized payer address
  a: string; // opaque agent id
  e: number; // unix expiry
  c: string; // chain id
  t: string; // normalized token address
}

async function buildQuote(env: Env, opts: BuildQuoteOpts): Promise<Quote> {
  const { path, method, reqCount } = opts;
  const recipient = env.JPCITE_X402_ADDRESS ?? "";
  const quoteSecret = env.JPCITE_X402_QUOTE_SECRET ?? "";
  if (!recipient || !quoteSecret) {
    throw new Error("x402_not_configured");
  }

  const usdcMeta = USDC_BY_CHAIN[X402_CHAIN_ID];
  if (!usdcMeta) {
    throw new Error(`unknown_chain:${X402_CHAIN_ID}`);
  }

  const reqs = Math.max(1, Math.min(10000, reqCount | 0));
  const agentId = normalizeAgentId(opts.agentId);
  const payerAddress = normalizeAddress(opts.payerAddress);
  if (!agentId) {
    throw new Error("invalid_agent_id");
  }
  if (!payerAddress) {
    throw new Error("invalid_payer_address");
  }
  const amountJpy = reqs * PER_REQ_JPY;
  const fx = await jpyPerUsdc(env); // JPY per 1 USDC
  const amountUsdc = amountJpy / fx;
  // 6-decimal micro-USDC (integer atomic). Round UP so the operator is never short.
  const microUsdc = Math.ceil(amountUsdc * 10 ** usdcMeta.decimals);
  const amountUsdcStr = (microUsdc / 10 ** usdcMeta.decimals).toFixed(usdcMeta.decimals);

  const issuedAt = Math.floor(Date.now() / 1000);
  const expiresAt = issuedAt + QUOTE_TTL_SECONDS;

  // Embed only settlement-critical fields in quote_id and sign them so /verify
  // can validate amount/recipient/token binding without a DB round trip.
  const quoteIdPayload: QuoteIdPayload = {
    v: 1,
    u: String(microUsdc),
    r: recipient.toLowerCase(),
    p: payerAddress,
    a: agentId,
    e: expiresAt,
    c: X402_CHAIN_ID,
    t: usdcMeta.address.toLowerCase(),
  };
  const quoteIdPayloadEncoded = base64UrlEncode(JSON.stringify(quoteIdPayload));
  const signature = await hmacSign(quoteSecret, quoteIdPayloadEncoded);
  const quoteId = `${quoteIdPayloadEncoded}.${signature.slice(0, 32)}`;

  return {
    quote_id: quoteId,
    path,
    method,
    req_count: reqs,
    amount_jpy: amountJpy,
    amount_usdc: amountUsdcStr,
    amount_usdc_micro: String(microUsdc),
    chain_id: X402_CHAIN_ID,
    token_address: usdcMeta.address,
    recipient,
    agent_id: agentId,
    payer_address: payerAddress,
    expires_at: expiresAt,
    signature,
  };
}

function discovery(env: Env): Response {
  const usdcMeta = USDC_BY_CHAIN[X402_CHAIN_ID];
  return new Response(
    JSON.stringify({
      protocol: "x402",
      version: "1.0",
      chain: { id: X402_CHAIN_ID, name: "Base" },
      token: {
        address: usdcMeta.address,
        symbol: "USDC",
        decimals: usdcMeta.decimals,
      },
      recipient: env.JPCITE_X402_ADDRESS ?? null,
      pricing: {
        model: "metered_per_request",
        unit_price_jpy: PER_REQ_JPY,
        approx_unit_price_usdc: "0.02",
        currency_native: "JPY",
        currency_settle: "USDC",
        latency_target_seconds: 2,
      },
      endpoints: {
        quote: "/x402/quote",
        verify: "/x402/verify",
      },
      operator: {
        name: "Bookyou株式会社",
        invoice_number: "T8010001213708",
        email: "info@bookyou.net",
      },
    }),
    {
      status: 200,
      headers: { "content-type": "application/json" },
    },
  );
}

function paymentRequired(quote: Quote): Response {
  // The x402 spec defines a body shape + the `WWW-Payment` response header
  // so a spec-aware client can settle and retry without parsing free-text.
  const wwwPayment = `usdc chain_id=${quote.chain_id} token=${quote.token_address} amount=${quote.amount_usdc_micro} recipient=${quote.recipient} quote_id=${quote.quote_id} expires=${quote.expires_at}`;
  return new Response(
    JSON.stringify({
      error: "payment_required",
      message: "Settlement in USDC required to access this resource.",
      quote,
      instructions: {
        step_1: "Sign a USDC transfer for `amount_usdc_micro` to `recipient` on chain `chain_id`.",
        step_2: "POST the resulting tx_hash to /x402/verify with the same quote_id and agent_id.",
        step_3: "Use the returned api_key in subsequent requests as `Authorization: Bearer am_...`.",
      },
    }),
    {
      status: 402,
      headers: {
        "content-type": "application/json",
        "www-payment": wwwPayment,
        "cache-control": "no-store",
      },
    },
  );
}

interface VerifyRequest {
  tx_hash: string;
  quote_id: string;
  agent_id: string;
  payer_signature?: string;
}

function normalizeAgentId(value: string | undefined | null): string {
  return String(value ?? "").trim().slice(0, 200);
}

function normalizeAddress(value: string | undefined | null): string {
  const v = String(value ?? "").toLowerCase();
  return /^0x[0-9a-f]{40}$/.test(v) ? v : "";
}

function addressFromTopic(topic: string): string {
  const v = String(topic ?? "").toLowerCase();
  if (!/^0x[0-9a-f]{64}$/.test(v)) return "";
  return `0x${v.slice(-40)}`;
}

function parseHexUint(value: string | undefined | null): bigint {
  const v = String(value ?? "0x0").toLowerCase();
  if (!/^0x[0-9a-f]+$/.test(v)) return 0n;
  return BigInt(v);
}

function shortStableHash(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function guardBucketKey(kind: "quote" | "verify", parts: string[]): string {
  const minute = Math.floor(Date.now() / 60000);
  return `guard:${kind}:${minute}:${shortStableHash(parts.join("|"))}`;
}

function clientSourceBucket(request: Request): string {
  const cfIp = String(request.headers.get("CF-Connecting-IP") ?? "").trim().toLowerCase();
  return cfIp ? `cf-ip:${cfIp}` : "cf-ip:missing";
}

async function kvIncrementGuard(env: Env, key: string, limit: number): Promise<boolean> {
  const kv = env.JPCITE_X402_KV;
  if (!kv) return !isProductionEnv(env);
  try {
    const currentRaw = await kv.get(key);
    const current = Number(currentRaw ?? "0");
    if (Number.isFinite(current) && current >= limit) return false;
    await kv.put(key, String((Number.isFinite(current) ? current : 0) + 1), {
      expirationTtl: X402_GUARD_BUCKET_TTL_SECONDS,
    });
  } catch {
    if (isProductionEnv(env)) return false;
    // KV guard outages must not block paid users outside production; RPC/origin
    // checks still fail closed.
  }
  return true;
}

async function kvGuardAllows(env: Env, key: string, limit: number): Promise<boolean> {
  const kv = env.JPCITE_X402_KV;
  if (!kv) return !isProductionEnv(env);
  try {
    const current = Number(await kv.get(key));
    return !Number.isFinite(current) || current < limit;
  } catch {
    return !isProductionEnv(env);
  }
}

async function cacheNegativeTx(env: Env, txHash: string, reason: string, ttl: number): Promise<boolean> {
  if (!env.JPCITE_X402_KV) return !isProductionEnv(env);
  try {
    await env.JPCITE_X402_KV.put(`tx_fail:${txHash}`, reason, { expirationTtl: ttl });
    return true;
  } catch {
    return !isProductionEnv(env);
  }
}

async function readJsonBodyCapped(request: Request): Promise<Record<string, unknown> | null> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && Number(contentLength) > MAX_X402_JSON_BODY_BYTES) {
    throw new Error("x402_body_too_large");
  }
  if (!request.body) return {};

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        total += value.byteLength;
        if (total > MAX_X402_JSON_BODY_BYTES) {
          await reader.cancel().catch(() => undefined);
          throw new Error("x402_body_too_large");
        }
        chunks.push(value);
      }
    }
  } finally {
    reader.releaseLock();
  }

  try {
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function bodyTooLargeResponse(): Response {
  return new Response(
    JSON.stringify({ error: "request_body_too_large", max_bytes: MAX_X402_JSON_BODY_BYTES }),
    { status: 413, headers: { "content-type": "application/json" } },
  );
}

async function fetchRpcReceipt(rpcUrl: string, txHash: string): Promise<{ receipt: any; timedOut: boolean }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RPC_FETCH_TIMEOUT_MS);
  try {
    const resp = await fetch(rpcUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "eth_getTransactionReceipt",
        params: [txHash],
      }),
    });
    if (!resp.ok) return { receipt: null, timedOut: false };
    const json = (await resp.json()) as { result?: any };
    return { receipt: json.result ?? null, timedOut: false };
  } catch (err) {
    return { receipt: null, timedOut: err instanceof DOMException && err.name === "AbortError" };
  } finally {
    clearTimeout(timer);
  }
}

async function parseQuoteId(env: Env, quoteId: string): Promise<QuoteIdPayload | null> {
  const quoteSecret = env.JPCITE_X402_QUOTE_SECRET ?? "";
  if (!quoteSecret) return null;

  const parts = quoteId.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;

  const expected = (await hmacSign(quoteSecret, parts[0])).slice(0, 32);
  if (!constantTimeEqual(parts[1], expected)) return null;

  let payload: Partial<QuoteIdPayload>;
  try {
    payload = JSON.parse(base64UrlDecode(parts[0])) as Partial<QuoteIdPayload>;
  } catch {
    return null;
  }

  const usdcMeta = USDC_BY_CHAIN[X402_CHAIN_ID];
  const recipient = normalizeAddress(env.JPCITE_X402_ADDRESS);
  const token = normalizeAddress(usdcMeta.address);
  const payer = normalizeAddress(payload.p);
  const agentId = normalizeAgentId(payload.a);
  const amount = Number(payload.u);
  const expires = Number(payload.e);
  const now = Math.floor(Date.now() / 1000);
  if (
    !recipient ||
    !token ||
    payload.v !== 1 ||
    payload.c !== X402_CHAIN_ID ||
    normalizeAddress(payload.t) !== token ||
    normalizeAddress(payload.r) !== recipient ||
    !payer ||
    !agentId ||
    !Number.isSafeInteger(amount) ||
    amount <= 0 ||
    !Number.isFinite(expires) ||
    expires < now
  ) {
    return null;
  }

  return {
    v: 1,
    u: String(payload.u),
    r: recipient,
    p: payer,
    a: agentId,
    e: expires,
    c: X402_CHAIN_ID,
    t: token,
  };
}

function hasSufficientUsdcTransfer(receipt: any, quote: QuoteIdPayload): boolean {
  const logs = Array.isArray(receipt?.logs) ? receipt.logs : [];
  const minAmount = BigInt(quote.u);
  // D8 hardening (2026-05-13): bind every accepted log to the parent receipt's
  // (blockHash, transactionHash). A malicious RPC could otherwise splice a
  // Transfer log from a different block/tx into a receipt that itself reverted
  // or settled a different amount. parent fields are themselves authenticated
  // by `receipt.status === "0x1"` upstream and by `eth_getTransactionReceipt`'s
  // own (txHash -> blockHash) binding on a non-byzantine RPC.
  const receiptBlockHash = String(receipt?.blockHash ?? "").toLowerCase();
  const receiptTxHash = String(receipt?.transactionHash ?? "").toLowerCase();
  if (!/^0x[0-9a-f]{64}$/.test(receiptBlockHash)) return false;
  if (!/^0x[0-9a-f]{64}$/.test(receiptTxHash)) return false;
  for (const log of logs) {
    // R2 P2 (2026-05-13): some RPC providers return logs with `removed: true`
    // for entries that were emitted on an orphaned chain branch and later
    // re-orged out. Treat them as if they were never observed. Base reorgs
    // are rare but the guard is cheap and matches geth/eth-rpc semantics:
    // see https://geth.ethereum.org/docs/interacting-with-geth/rpc/objects#log-object
    if (log?.removed === true) continue;
    // D8 hardening: every log must self-attest as belonging to the same block
    // AND the same transaction as the enclosing receipt. Mismatch => spliced.
    const logBlockHash = String(log?.blockHash ?? "").toLowerCase();
    const logTxHash = String(log?.transactionHash ?? "").toLowerCase();
    if (logBlockHash !== receiptBlockHash) continue;
    if (logTxHash !== receiptTxHash) continue;
    const topics = Array.isArray(log?.topics) ? log.topics : [];
    if (normalizeAddress(log?.address) !== quote.t) continue;
    if (String(topics[0] ?? "").toLowerCase() !== ERC20_TRANSFER_TOPIC) continue;
    if (addressFromTopic(String(topics[1] ?? "")) !== quote.p) continue;
    if (addressFromTopic(String(topics[2] ?? "")) !== quote.r) continue;
    if (parseHexUint(log?.data) >= minAmount) return true;
  }
  return false;
}

async function verifyTx(env: Env, body: VerifyRequest, request: Request): Promise<Response> {
  if (body.payer_signature) {
    // Do not accept or ignore an off-chain payer signature until this edge
    // has a reviewed EIP-191/EIP-712 secp256k1 recovery verifier. The
    // restored path below authenticates settlement by signed quote_id plus a
    // settled USDC Transfer from the quoted payer to our recipient.
    return paymentRequiredRaw("payer_signature_verification_unavailable");
  }

  const quoteId = String(body.quote_id ?? "");
  const txHash = String(body.tx_hash ?? "").toLowerCase();

  const quote = await parseQuoteId(env, quoteId);
  if (!quote) return paymentRequiredRaw("invalid_quote_id");
  const agentId = normalizeAgentId(body.agent_id);
  if (!agentId || agentId !== quote.a) return paymentRequiredRaw("agent_mismatch");

  if (!/^0x[0-9a-f]{64}$/.test(txHash)) return paymentRequiredRaw("invalid_tx_hash");
  const clientBucket = clientSourceBucket(request);

  // Replay window — same tx_hash cannot redeem twice within 25h.
  if (env.JPCITE_X402_KV) {
    try {
      const seen = await env.JPCITE_X402_KV.get(`tx:${txHash}`);
      if (seen) return paymentRequiredRaw("tx_already_redeemed");
      const failed = await env.JPCITE_X402_KV.get(`tx_fail:${txHash}`);
      if (failed) return paymentRequiredRaw(String(failed));
    } catch {
      if (isProductionEnv(env)) return publicX402Unavailable();
    }
  } else if (isProductionEnv(env)) {
    return publicX402Unavailable();
  }

  const rpcUrl = env.JPCITE_X402_RPC_URL ?? "";
  if (!rpcUrl) return publicX402Unavailable();

  const failureBucketKey = guardBucketKey("verify", [clientBucket, agentId, quoteId]);
  if (!(await kvGuardAllows(env, failureBucketKey, MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET))) {
    return paymentRequiredRaw("verify_attempts_limited");
  }
  const rpcSourceBucketKey = guardBucketKey("verify", [clientBucket]);
  if (!(await kvIncrementGuard(env, rpcSourceBucketKey, MAX_VERIFY_RPC_ATTEMPTS_PER_SOURCE_BUCKET))) {
    return paymentRequiredRaw("verify_rpc_attempts_limited");
  }

  // Fetch the receipt — Base finalises in ~200ms, but we retry x3 to absorb
  // RPC-side propagation latency (we need < 2s end-to-end per AI agent SLA).
  let receipt: any = null;
  let timedOut = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    const result = await fetchRpcReceipt(rpcUrl, txHash);
    timedOut ||= result.timedOut;
    if (result.receipt) {
      receipt = result.receipt;
      break;
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  if (!receipt) {
    if (!(await kvIncrementGuard(env, failureBucketKey, MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET))) {
      return publicX402Unavailable();
    }
    if (!timedOut) {
      if (!(await cacheNegativeTx(env, txHash, "tx_not_settled", NEGATIVE_TX_CACHE_SETTLE_TTL_SECONDS))) {
        return publicX402Unavailable();
      }
    }
    return paymentRequiredRaw(timedOut ? "rpc_timeout" : "tx_not_settled");
  }
  if (receipt.status !== "0x1") {
    if (!(await kvIncrementGuard(env, failureBucketKey, MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET))) {
      return publicX402Unavailable();
    }
    if (!(await cacheNegativeTx(env, txHash, "tx_reverted", NEGATIVE_TX_CACHE_FAILURE_TTL_SECONDS))) {
      return publicX402Unavailable();
    }
    return paymentRequiredRaw("tx_reverted");
  }
  if (!hasSufficientUsdcTransfer(receipt, quote)) {
    if (!(await kvIncrementGuard(env, failureBucketKey, MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET))) {
      return publicX402Unavailable();
    }
    if (!(await cacheNegativeTx(env, txHash, "wrong_amount_or_recipient", NEGATIVE_TX_CACHE_FAILURE_TTL_SECONDS))) {
      return publicX402Unavailable();
    }
    return paymentRequiredRaw("wrong_amount_or_recipient");
  }

  // Forward to the origin /v1/billing/x402/issue_key endpoint (FastAPI side).
  // That endpoint creates the metered API key bound to the agent_id and
  // returns it once. We never touch the database directly from the edge.
  const apiBase = env.JPCITE_API_BASE ?? "https://api.jpcite.com";
  const originSecret = env.JPCITE_X402_ORIGIN_SECRET ?? "";
  if (!originSecret) return publicX402Unavailable();
  const issueResp = await fetch(`${apiBase}/v1/billing/x402/issue_key`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-JPCITE-X402-Origin-Secret": originSecret,
    },
    body: JSON.stringify({
      tx_hash: txHash,
      quote_id: quoteId,
      agent_id: agentId,
    }),
  });
  // Mark as redeemed only after the origin has accepted the transaction.
  // Otherwise a transient origin failure strands a paid user by burning the
  // edge replay key before the API key exists. Origin-side transaction
  // reservation remains the authoritative duplicate-mint guard.
  const issueText = await issueResp.text();
  let terminalDuplicate = false;
  if (issueResp.status === 409) {
    try {
      const issueJson = JSON.parse(issueText);
      terminalDuplicate = issueJson?.detail === "tx_already_redeemed";
    } catch {
      terminalDuplicate = false;
    }
  }
  if (issueResp.ok || terminalDuplicate) {
    if (!env.JPCITE_X402_KV) {
      if (isProductionEnv(env)) return publicX402Unavailable();
    } else {
      try {
        await env.JPCITE_X402_KV.put(`tx:${txHash}`, "1", {
          expirationTtl: NONCE_TTL_SECONDS,
        });
      } catch {
        if (isProductionEnv(env)) return publicX402Unavailable();
      }
    }
  }
  return new Response(issueText, {
    status: issueResp.status,
    headers: { "content-type": issueResp.headers.get("content-type") ?? "application/json" },
  });
}

function paymentRequiredRaw(reason: string): Response {
  return new Response(
    JSON.stringify({ error: "payment_required", reason }),
    { status: 402, headers: { "content-type": "application/json" } },
  );
}

function publicX402Unavailable(): Response {
  return new Response(
    JSON.stringify({ error: "x402_unavailable" }),
    { status: 503, headers: { "content-type": "application/json" } },
  );
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method.toUpperCase();

  try {
    if (path === "/x402/discovery" && method === "GET") return discovery(env);

    if (path === "/x402/quote" && method === "POST") {
      if (!(await requireProductionKvHealthy(env))) return publicX402Unavailable();
      let body: Record<string, unknown> | null;
      try {
        body = await readJsonBodyCapped(request);
      } catch (err) {
        if (err instanceof Error && err.message === "x402_body_too_large") return bodyTooLargeResponse();
        throw err;
      }
      body ??= {};
      const targetPath = String(body.path ?? "/v1/");
      const targetMethod = String(body.method ?? "GET").toUpperCase();
      const reqCount = Number(body.req_count ?? 1);
      const agentId = normalizeAgentId(String(body.agent_id ?? ""));
      const payerAddress = normalizeAddress(String(body.payer_address ?? ""));
      if (!agentId || !payerAddress) return paymentRequiredRaw("quote_identity_required");
      const clientBucket = clientSourceBucket(request);
      const quoteBucketKey = guardBucketKey("quote", [clientBucket]);
      if (!(await kvIncrementGuard(env, quoteBucketKey, MAX_QUOTE_ATTEMPTS_PER_BUCKET))) {
        return paymentRequiredRaw("quote_attempts_limited");
      }
      const quote = await buildQuote(env, {
        path: targetPath,
        method: targetMethod,
        reqCount,
        agentId,
        payerAddress,
      });
      return new Response(JSON.stringify(quote), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }

    if (path === "/x402/verify" && method === "POST") {
      if (!(await requireProductionKvHealthy(env))) return publicX402Unavailable();
      let bodyRaw: Record<string, unknown> | null;
      try {
        bodyRaw = await readJsonBodyCapped(request);
      } catch (err) {
        if (err instanceof Error && err.message === "x402_body_too_large") return bodyTooLargeResponse();
        throw err;
      }
      const body = (bodyRaw ?? {}) as unknown as VerifyRequest;
      if (!body.tx_hash || !body.quote_id || !body.agent_id) {
        return paymentRequiredRaw("missing_field");
      }
      return await verifyTx(env, body, request);
    }

    // Default branch: any other path under metered surface gets a 402.
    if (isMeteredPath(path) && !isExemptPath(path)) {
      if (!(await requireProductionKvHealthy(env))) return publicX402Unavailable();
      const agentId = request.headers.get("X-JPCITE-Agent-ID") ?? "";
      const payerAddress = request.headers.get("X-Payment-Payer") ?? "";
      if (!agentId || !payerAddress) return paymentRequiredRaw("quote_identity_required");
      const quote = await buildQuote(env, {
        path,
        method,
        reqCount: 1,
        agentId,
        payerAddress,
      });
      return paymentRequired(quote);
    }
    return new Response("not_found", { status: 404 });
  } catch {
    return new Response(
      JSON.stringify({ error: "x402_internal" }),
      { status: 500, headers: { "content-type": "application/json" } },
    );
  }
};
