"""Focused behavior tests for the Cloudflare x402 edge verify path.

These run the Pages Function directly in Node with mocked RPC/origin fetches.
No real chain, origin, or Stripe calls are made.
"""

from __future__ import annotations

from pathlib import Path

from tests.edge_ts_runner import run_edge_node

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> None:
    run_edge_node(script, timeout=20)


EDGE_TEST_HELPERS = r"""
import assert from "node:assert/strict";

const { onRequest } = await import("./functions/x402_handler.ts");

const TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const recipient = "0x" + "2".repeat(40);
const payer = "0x" + "1".repeat(40);
const token = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const rpcUrl = "https://rpc.local";
const apiBase = "https://origin.local";

function topicFor(address) {
  return "0x" + "0".repeat(24) + address.slice(2).toLowerCase();
}

function hexAmount(amount) {
  return "0x" + BigInt(amount).toString(16);
}

function makeKv() {
  const store = new Map();
  return {
    putCalls: [],
    store,
    async get(key) {
      return store.get(key) ?? null;
    },
    async put(key, value, options) {
      this.putCalls.push({ key, value, options });
      store.set(key, value);
    },
  };
}

const kv = makeKv();
const env = {
  JPCITE_X402_KV: kv,
  JPCITE_X402_ADDRESS: recipient,
  JPCITE_X402_QUOTE_SECRET: "quote-secret",
  JPCITE_X402_RPC_URL: rpcUrl,
  JPCITE_X402_ORIGIN_SECRET: "origin-secret",
  JPCITE_API_BASE: apiBase,
  JPCITE_X402_FALLBACK_JPY_PER_USDC: "150",
};

async function invoke(path, body) {
  return await onRequest({
    request: new Request("https://jpcite.test" + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
    env,
  });
}

async function invokeRaw(path, bodyText) {
  return await onRequest({
    request: new Request("https://jpcite.test" + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: bodyText,
    }),
    env,
  });
}

async function issueQuote(agentId = "agent_1") {
  const resp = await invoke("/x402/quote", {
    path: "/v1/programs/search",
    method: "GET",
    req_count: 1,
    agent_id: agentId,
    payer_address: payer,
  });
  if (resp.status !== 200) {
    throw new Error(await resp.text());
  }
  return await resp.json();
}

const DEFAULT_BLOCK_HASH = "0x" + "f".repeat(64);
const DEFAULT_TX_HASH_BINDING = "0x" + "a".repeat(64);

function usdcTransferLog({
  from = payer,
  to = recipient,
  amount,
  address = token,
  topic0 = TRANSFER_TOPIC,
  blockHash = DEFAULT_BLOCK_HASH,
  transactionHash = DEFAULT_TX_HASH_BINDING,
}) {
  return {
    address,
    topics: [topic0, topicFor(from), topicFor(to)],
    data: hexAmount(amount),
    blockHash,
    transactionHash,
  };
}

function receiptWith(logs, {
  blockHash = DEFAULT_BLOCK_HASH,
  transactionHash = DEFAULT_TX_HASH_BINDING,
  status = "0x1",
} = {}) {
  return { status, blockHash, transactionHash, logs };
}

async function responseJson(resp) {
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`status=${resp.status} non-json body=${text}`);
  }
}
"""


def test_x402_edge_verify_restores_settlement_to_origin_issue_key() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
const normalizedTx = "0x" + "a".repeat(64);
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  const headers = new Headers(init.headers ?? {});
  const body = init.body ? JSON.parse(init.body) : null;
  calls.push({ url: String(url), headers, body });
  if (String(url) === rpcUrl) {
    return Response.json({
      result: receiptWith([usdcTransferLog({ amount: quote.amount_usdc_micro })]),
    });
  }
  if (String(url) === `${apiBase}/v1/billing/x402/issue_key`) {
    assert.equal(headers.get("x-jpcite-x402-origin-secret"), "origin-secret");
    return new Response(
      JSON.stringify({
        api_key: "jc_x402_test",
        expires_at: "2099-01-01T00:00:00Z",
        metering: { request_cap: 1 },
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }
  throw new Error(`unexpected fetch ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "A".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 200, JSON.stringify(body));
assert.equal(body.api_key, "jc_x402_test");
assert.equal(calls.length, 2);
assert.equal(calls[0].url, rpcUrl);
assert.deepEqual(calls[0].body.params, [normalizedTx]);
assert.equal(calls[1].url, `${apiBase}/v1/billing/x402/issue_key`);
assert.equal(calls[1].body.tx_hash, normalizedTx);
assert.equal(calls[1].body.quote_id, quote.quote_id);
assert.equal(calls[1].body.agent_id, "agent_1");
const redemptionPuts = kv.putCalls.filter((call) => call.key.startsWith("tx:"));
assert.equal(redemptionPuts.length, 1);
assert.equal(redemptionPuts[0].key, `tx:${normalizedTx}`);
"""
    )


def test_x402_edge_prod_requires_kv_before_quote_or_verify_work() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  throw new Error("RPC/origin must not run when production KV is unavailable");
};

env.JPCITE_ENV = "production";
env.JPCITE_X402_KV = null;

const quoteResp = await invoke("/x402/quote", {
  path: "/v1/programs/search",
  method: "GET",
  req_count: 1,
  agent_id: "agent_1",
  payer_address: payer,
});
assert.equal(quoteResp.status, 503);
assert.deepEqual(await responseJson(quoteResp), { error: "x402_unavailable" });

const verifyResp = await invoke("/x402/verify", {
  tx_hash: "0x" + "a".repeat(64),
  quote_id: "stub.quote",
  agent_id: "agent_1",
});
assert.equal(verifyResp.status, 503);
assert.deepEqual(await responseJson(verifyResp), { error: "x402_unavailable" });
assert.equal(fetchCalls, 0);
"""
    )


def test_x402_edge_prod_fails_closed_when_kv_health_check_throws() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  throw new Error("RPC/origin must not run when production KV health check fails");
};

env.JPCITE_ENV = "production";
env.JPCITE_X402_KV = {
  async get() {
    throw new Error("kv read failed");
  },
  async put() {
    throw new Error("kv write failed");
  },
};

const resp = await invoke("/x402/quote", {
  path: "/v1/programs/search",
  method: "GET",
  req_count: 1,
  agent_id: "agent_1",
  payer_address: payer,
});
assert.equal(resp.status, 503);
assert.deepEqual(await responseJson(resp), { error: "x402_unavailable" });
assert.equal(fetchCalls, 0);
"""
    )


def test_x402_edge_prod_does_not_silently_ignore_redeemed_tx_kv_write_failure() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
const normalizedTx = "0x" + "a".repeat(64);
let txPutAttempted = false;
env.JPCITE_ENV = "production";
env.JPCITE_X402_KV = {
  async get() {
    return null;
  },
  async put(key) {
    if (String(key).startsWith("tx:")) {
      txPutAttempted = true;
      throw new Error("redeemed tx write failed");
    }
  },
};

globalThis.fetch = async (url) => {
  if (String(url) === rpcUrl) {
    return Response.json({
      result: receiptWith([usdcTransferLog({ amount: quote.amount_usdc_micro })]),
    });
  }
  if (String(url) === `${apiBase}/v1/billing/x402/issue_key`) {
    return Response.json({ api_key: "jc_x402_test" });
  }
  throw new Error(`unexpected fetch ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: normalizedTx,
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
assert.equal(resp.status, 503);
assert.deepEqual(await responseJson(resp), { error: "x402_unavailable" });
assert.equal(txPutAttempted, true);
"""
    )


def test_x402_edge_verify_rejects_transfer_binding_mismatches_before_origin() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
let receipt = null;
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
  if (String(url) === rpcUrl) {
    return Response.json({ result: receipt });
  }
  throw new Error(`origin must not be called for mismatched receipt: ${url}`);
};

const cases = [
  {
    name: "wrong_transfer_topic",
    log: () => usdcTransferLog({ amount: quote.amount_usdc_micro, topic0: "0x" + "0".repeat(64) }),
  },
  {
    name: "wrong_amount",
    log: () => usdcTransferLog({ amount: BigInt(quote.amount_usdc_micro) - 1n }),
  },
  {
    name: "wrong_recipient",
    log: () => usdcTransferLog({ amount: quote.amount_usdc_micro, to: "0x" + "3".repeat(40) }),
  },
  {
    name: "wrong_payer",
    log: () => usdcTransferLog({ amount: quote.amount_usdc_micro, from: "0x" + "4".repeat(40) }),
  },
];

for (let i = 0; i < cases.length; i += 1) {
  receipt = receiptWith([cases[i].log()]);
  calls.length = 0;
  const resp = await invoke("/x402/verify", {
    tx_hash: "0x" + String(i + 1).repeat(64),
    quote_id: quote.quote_id,
    agent_id: "agent_1",
  });
  const body = await responseJson(resp);
  assert.equal(resp.status, 402, cases[i].name);
  assert.equal(body.reason, "wrong_amount_or_recipient", cases[i].name);
  assert.equal(calls.length, 1, cases[i].name);
  assert.equal(calls[0].url, rpcUrl, cases[i].name);
}
assert.equal(kv.putCalls.filter((call) => call.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_rejects_quote_agent_mismatch_without_rpc() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote("agent_signed");
globalThis.fetch = async (url) => {
  throw new Error(`fetch must not be called for agent mismatch: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "6".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_attacker",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402);
assert.equal(body.reason, "agent_mismatch");
assert.equal(kv.putCalls.filter((call) => call.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_rejects_unverified_payer_signature_without_rpc() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
globalThis.fetch = async (url) => {
  throw new Error(`fetch must not be called when payer_signature is supplied: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "5".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
  payer_signature: "0x" + "9".repeat(130),
});
const body = await responseJson(resp);
assert.equal(resp.status, 402);
assert.equal(body.reason, "payer_signature_verification_unavailable");
assert.equal(kv.putCalls.filter((call) => call.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_quote_and_verify_reject_oversized_json_without_parsing() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
globalThis.fetch = async (url) => {
  throw new Error(`fetch must not be called for oversized bodies: ${url}`);
};

const oversized = JSON.stringify({ filler: "x".repeat(9000) });
for (const path of ["/x402/quote", "/x402/verify"]) {
  const resp = await invokeRaw(path, oversized);
  const body = await responseJson(resp);
  assert.equal(resp.status, 413, path);
  assert.equal(body.error, "request_body_too_large", path);
  assert.equal(body.max_bytes, 8192, path);
}
"""
    )


def test_x402_edge_verify_times_out_rpc_fetches() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
let rpcCalls = 0;
globalThis.fetch = async (url, init = {}) => {
  if (String(url) !== rpcUrl) throw new Error(`origin must not be called on RPC timeout: ${url}`);
  rpcCalls += 1;
  return await new Promise((resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  });
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "7".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402);
assert.equal(body.reason, "rpc_timeout");
assert.equal(rpcCalls, 3);
"""
    )


def test_x402_edge_verify_negative_caches_unsettled_tx_hash() -> None:
    _run_node(
        EDGE_TEST_HELPERS
        + r"""
const quote = await issueQuote();
let rpcCalls = 0;
globalThis.fetch = async (url) => {
  if (String(url) !== rpcUrl) throw new Error(`origin must not be called for unsettled tx: ${url}`);
  rpcCalls += 1;
  return Response.json({ result: null });
};

const txHash = "0x" + "8".repeat(64);
for (let i = 0; i < 2; i += 1) {
  const resp = await invoke("/x402/verify", {
    tx_hash: txHash,
    quote_id: quote.quote_id,
    agent_id: "agent_1",
  });
  const body = await responseJson(resp);
  assert.equal(resp.status, 402);
  assert.equal(body.reason, "tx_not_settled");
}
assert.equal(rpcCalls, 3);
assert.equal(kv.store.get(`tx_fail:${txHash}`), "tx_not_settled");
"""
    )
