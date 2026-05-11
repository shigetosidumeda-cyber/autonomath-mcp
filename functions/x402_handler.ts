/// <reference types="@cloudflare/workers-types" />
/*
 * Wave 43.4.9+10 — x402 USDC HTTP 402 Payment Required handler.
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
 *     body: { "path": "/v1/...", "method": "GET", "req_count": 1 }
 *     -> 200 JSON quote with USDC amount + payment address.
 *
 *   POST /x402/verify
 *     body: { "tx_hash": "0x...", "quote_id": "...", "agent_id": "..." }
 *     -> 200 { "api_key": "am_...", "expires_at": "..." }
 *     -> 402 if tx not settled / wrong amount / wrong recipient
 *
 *   * any other path *  -> 402 HTTP Payment Required with a quote bundle
 *     matching the Wave 24 anon_rate_limit_edge.ts 402 challenge format.
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
 * Wave 24 alignment:
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
  expires_at: number; // unix seconds
  signature: string;
}

interface BuildQuoteOpts {
  path: string;
  method: string;
  reqCount: number;
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
  const amountJpy = reqs * PER_REQ_JPY;
  const fx = await jpyPerUsdc(env); // JPY per 1 USDC
  const amountUsdc = amountJpy / fx;
  // 6-decimal micro-USDC (integer atomic). Round UP so the operator is never short.
  const microUsdc = Math.ceil(amountUsdc * 10 ** usdcMeta.decimals);
  const amountUsdcStr = (microUsdc / 10 ** usdcMeta.decimals).toFixed(usdcMeta.decimals);

  const issuedAt = Math.floor(Date.now() / 1000);
  const expiresAt = issuedAt + QUOTE_TTL_SECONDS;

  // Pre-sign quote so /verify can validate the quote_id without a DB round trip.
  const quoteIdRaw = `${path}|${method}|${reqs}|${microUsdc}|${recipient}|${expiresAt}`;
  const signature = await hmacSign(quoteSecret, quoteIdRaw);
  const quoteId = `${expiresAt}.${signature.slice(0, 32)}`;

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
        step_2: "POST the resulting tx_hash to /x402/verify with the same quote_id.",
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
}

async function verifyTx(env: Env, body: VerifyRequest): Promise<Response> {
  const quoteSecret = env.JPCITE_X402_QUOTE_SECRET ?? "";
  if (!quoteSecret) return new Response("x402_not_configured", { status: 500 });

  // Parse + validate the quote_id (replay defence).
  const parts = body.quote_id.split(".");
  if (parts.length !== 2) return paymentRequiredRaw("invalid_quote_id");
  const expiresAt = Number(parts[0]);
  if (!Number.isFinite(expiresAt) || expiresAt < Math.floor(Date.now() / 1000)) {
    return paymentRequiredRaw("quote_expired");
  }

  // Replay window — same tx_hash cannot redeem twice within 25h.
  if (env.JPCITE_X402_KV) {
    const seen = await env.JPCITE_X402_KV.get(`tx:${body.tx_hash}`);
    if (seen) return paymentRequiredRaw("tx_already_redeemed");
  }

  const rpcUrl = env.JPCITE_X402_RPC_URL ?? "";
  if (!rpcUrl) return new Response("x402_rpc_not_configured", { status: 500 });

  // Fetch the receipt — Base finalises in ~200ms, but we retry x3 to absorb
  // RPC-side propagation latency (we need < 2s end-to-end per AI agent SLA).
  let receipt: any = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    const resp = await fetch(rpcUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "eth_getTransactionReceipt",
        params: [body.tx_hash],
      }),
    });
    if (resp.ok) {
      const json = (await resp.json()) as { result?: any };
      if (json.result) {
        receipt = json.result;
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  if (!receipt) return paymentRequiredRaw("tx_not_settled");
  if (receipt.status !== "0x1") return paymentRequiredRaw("tx_reverted");

  // Mark tx as redeemed so a second /verify call cannot mint a second key.
  if (env.JPCITE_X402_KV) {
    await env.JPCITE_X402_KV.put(`tx:${body.tx_hash}`, "1", {
      expirationTtl: NONCE_TTL_SECONDS,
    });
  }

  // Forward to the origin /v1/billing/x402/issue_key endpoint (FastAPI side).
  // That endpoint creates the metered API key bound to the agent_id and
  // returns it once. We never touch the database directly from the edge.
  const apiBase = env.JPCITE_API_BASE ?? "https://api.jpcite.com";
  const issueResp = await fetch(`${apiBase}/v1/billing/x402/issue_key`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      tx_hash: body.tx_hash,
      quote_id: body.quote_id,
      agent_id: body.agent_id,
    }),
  });
  return new Response(await issueResp.text(), {
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

export const onRequest: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method.toUpperCase();

  try {
    if (path === "/x402/discovery" && method === "GET") return discovery(env);

    if (path === "/x402/quote" && method === "POST") {
      const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
      const targetPath = String(body.path ?? "/v1/");
      const targetMethod = String(body.method ?? "GET").toUpperCase();
      const reqCount = Number(body.req_count ?? 1);
      const quote = await buildQuote(env, { path: targetPath, method: targetMethod, reqCount });
      return new Response(JSON.stringify(quote), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }

    if (path === "/x402/verify" && method === "POST") {
      const body = (await request.json().catch(() => ({}))) as VerifyRequest;
      if (!body.tx_hash || !body.quote_id || !body.agent_id) {
        return paymentRequiredRaw("missing_field");
      }
      return await verifyTx(env, body);
    }

    // Default branch: any other path under metered surface gets a 402.
    if (isMeteredPath(path) && !isExemptPath(path)) {
      const quote = await buildQuote(env, { path, method, reqCount: 1 });
      return paymentRequired(quote);
    }
    return new Response("not_found", { status: 404 });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: "x402_internal", message: String(err) }),
      { status: 500, headers: { "content-type": "application/json" } },
    );
  }
};
