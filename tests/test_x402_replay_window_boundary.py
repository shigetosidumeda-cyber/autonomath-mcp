"""x402 nonce replay-protection 25h window boundary tests.

A5's documented fail-closed banner (functions/x402_handler.ts lines 7-61)
asserts that replay defence is one of the four conjunctive auth gates:

  (3) replay defence: ``tx_hash`` is recorded in ``JPCITE_X402_KV`` for
      ``NONCE_TTL_SECONDS`` (25 h) after the origin ``/v1/billing/x402/issue_key``
      accepts the redemption.

A6 + D7 + D8 hardened the receipt-binding axes (block hash, transaction
hash, reorg-removed log, payer-signature fail-closed). The replay axis
itself was untested in isolation. This module pins the **25h window
boundary** as a contract:

  - Within the window: a second ``/x402/verify`` with the same ``tx_hash``
    is refused with ``402 tx_already_redeemed``.
  - At/after the window: KV's ``expirationTtl`` evicts the key, the
    replay-gate becomes a no-op, and the request proceeds through the
    remaining auth gates (which may still fail for other reasons — that
    is fine; we are not testing those gates here).
  - Boundary precision: the TTL constant is exactly
    ``25 * 60 * 60 == 90000`` seconds. The ``put`` call after a success
    must pass that exact value to ``expirationTtl``.

We exercise the edge handler through the shared edge TypeScript runner so
the actual TypeScript source under ``functions/x402_handler.ts`` runs (the
same pattern used by ``test_x402_edge_verify_reorg_removed.py`` and
``test_x402_edge_verify_restoration.py``). The KV is a deterministic
in-memory mock that lets us pre-seed a redeemed nonce, simulate eviction
after expiry, and inspect the TTL captured on a successful ``put``.

No LLM SDK imports. No real RPC. No real Stripe.
"""

from __future__ import annotations

from pathlib import Path

from tests.edge_ts_runner import run_edge_node

REPO_ROOT = Path(__file__).resolve().parents[1]

# Authoritative constant the source pins at functions/x402_handler.ts:155.
# Tests below assert source + runtime + JS evaluation all agree on this
# exact value so a refactor cannot silently shrink the replay window.
EXPECTED_NONCE_TTL_SECONDS = 25 * 60 * 60  # 90000


def _run_node(script: str) -> None:
    run_edge_node(script, timeout=20)


EDGE_HELPERS = r"""
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

// Deterministic KV stub. ``evictedKeys`` lets a test simulate the
// Cloudflare KV TTL boundary by pre-marking a key as expired (returns null
// on get, just like an evicted key would). ``putCalls`` captures every
// write so the test can assert the exact ``expirationTtl`` passed to
// ``put`` for ``tx:`` keys.
function makeKv({ preSeeded = {}, evictedKeys = new Set() } = {}) {
  const store = new Map(Object.entries(preSeeded));
  return {
    putCalls: [],
    getCalls: [],
    store,
    evictedKeys,
    async get(key) {
      this.getCalls.push(key);
      // Boundary semantics: an evicted key (TTL elapsed) is indistinguishable
      // from never-written. We return null for both.
      if (this.evictedKeys.has(key)) return null;
      return this.store.get(key) ?? null;
    },
    async put(key, value, options) {
      this.putCalls.push({ key, value, options });
      this.store.set(key, value);
    },
  };
}

function makeEnv(kv) {
  return {
    JPCITE_X402_KV: kv,
    JPCITE_X402_ADDRESS: recipient,
    JPCITE_X402_QUOTE_SECRET: "quote-secret",
    JPCITE_X402_RPC_URL: rpcUrl,
    JPCITE_X402_ORIGIN_SECRET: "origin-secret",
    JPCITE_API_BASE: apiBase,
    JPCITE_X402_FALLBACK_JPY_PER_USDC: "150",
  };
}

async function invoke(env, path, body) {
  return await onRequest({
    request: new Request("https://jpcite.test" + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
    env,
  });
}

async function issueQuote(env, agentId = "agent_replay") {
  const resp = await invoke(env, "/x402/quote", {
    path: "/v1/programs/search",
    method: "GET",
    req_count: 1,
    agent_id: agentId,
    payer_address: payer,
  });
  if (resp.status !== 200) throw new Error(await resp.text());
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
  removed = false,
  blockHash = DEFAULT_BLOCK_HASH,
  transactionHash = DEFAULT_TX_HASH_BINDING,
}) {
  return {
    address,
    topics: [topic0, topicFor(from), topicFor(to)],
    data: hexAmount(amount),
    removed,
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


# ---------- Test 1: reuse within window -> 402 reject ----------------------


def test_x402_replay_reuse_within_window_rejected() -> None:
    """A ``tx_hash`` already present in the edge KV under ``tx:<hash>`` must
    short-circuit ``/x402/verify`` with HTTP 402 + reason
    ``tx_already_redeemed``. The RPC must not be called, and the origin
    ``/v1/billing/x402/issue_key`` must not be reached — the replay gate
    is the earliest of the three KV checks in ``verifyTx`` (line 701)."""
    _run_node(
        EDGE_HELPERS
        + r"""
const txHash = "0x" + "b".repeat(64);
// Pre-seed the replay key — exactly the value the handler writes on a
// successful redemption (functions/x402_handler.ts line 805 puts "1").
const kv = makeKv({ preSeeded: { [`tx:${txHash}`]: "1" } });
const env = makeEnv(kv);
const quote = await issueQuote(env);

let rpcHits = 0;
let originHits = 0;
globalThis.fetch = async (url) => {
  const s = String(url);
  if (s === rpcUrl) rpcHits += 1;
  else if (s.startsWith(apiBase)) originHits += 1;
  throw new Error(`replay-rejected path must not call ${url}`);
};

const resp = await invoke(env, "/x402/verify", {
  tx_hash: txHash,
  quote_id: quote.quote_id,
  agent_id: "agent_replay",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402, JSON.stringify(body));
assert.equal(body.error, "payment_required");
assert.equal(body.reason, "tx_already_redeemed");
assert.equal(rpcHits, 0, "RPC must not be called when replay gate trips");
assert.equal(originHits, 0, "origin issue_key must not be called when replay gate trips");
// Replay gate must not double-write the redemption marker.
assert.equal(
  kv.putCalls.filter((c) => c.key === `tx:${txHash}`).length,
  0,
  "replay-rejected path must not re-put tx: key",
);
"""
    )


# ---------- Test 2: reuse after expiry -> not rejected by replay path -----


def test_x402_replay_reuse_after_window_not_blocked_by_replay_gate() -> None:
    """After the 25h TTL elapses, Cloudflare KV evicts ``tx:<hash>``. A
    subsequent ``/x402/verify`` with the same ``tx_hash`` must NOT trip
    the replay gate. (Other gates — RPC settlement, amount match, agent
    binding — may still fail; this test asserts only that the replay gate
    is **not** the rejector, i.e. the response reason is not
    ``tx_already_redeemed``.)

    We simulate eviction by adding the key to ``evictedKeys`` so the
    in-memory KV returns ``null`` on ``get(`tx:<hash>`)`` — semantically
    identical to a key whose ``expirationTtl`` of 90000s has elapsed."""
    _run_node(
        EDGE_HELPERS
        + r"""
const txHash = "0x" + "c".repeat(64);
// Mark the redemption key as TTL-evicted. The KV ``get`` returns null
// (just like Cloudflare KV would 25h+1s after the put).
const kv = makeKv({ evictedKeys: new Set([`tx:${txHash}`]) });
const env = makeEnv(kv);
const quote = await issueQuote(env);

// Provide a settlement receipt that satisfies amount + recipient + binding
// so the replay gate is the ONLY axis that could have rejected. Any
// non-replay failure would still surface as 402 but with a DIFFERENT
// reason string.
let originHits = 0;
globalThis.fetch = async (url) => {
  const s = String(url);
  if (s === rpcUrl) {
    return Response.json({
      result: receiptWith([
        usdcTransferLog({ amount: quote.amount_usdc_micro }),
      ]),
    });
  }
  if (s === `${apiBase}/v1/billing/x402/issue_key`) {
    originHits += 1;
    return new Response(
      JSON.stringify({ api_key: "jc_x402_replay_after_window", expires_at: "2099-01-01T00:00:00Z" }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }
  throw new Error(`unexpected fetch ${url}`);
};

const resp = await invoke(env, "/x402/verify", {
  tx_hash: txHash,
  quote_id: quote.quote_id,
  agent_id: "agent_replay",
});
const body = await responseJson(resp);
// The replay gate did not reject. The request reached the origin and
// succeeded with a fresh api_key. This is the **expected** behavior once
// the 25h TTL window elapses.
assert.equal(resp.status, 200, JSON.stringify(body));
assert.notEqual(body.reason, "tx_already_redeemed");
assert.equal(body.api_key, "jc_x402_replay_after_window");
assert.equal(originHits, 1, "origin must be reached after replay window elapses");
// And the post-redemption ``put`` must rewrite the replay key with the
// fresh 25h TTL.
const putCalls = kv.putCalls.filter((c) => c.key === `tx:${txHash}`);
assert.equal(putCalls.length, 1, "successful redemption must re-put the tx: key");
assert.equal(
  putCalls[0].options.expirationTtl,
  90000,
  "post-redemption put must use NONCE_TTL_SECONDS=90000 (25h)",
);
"""
    )


# ---------- Test 3: window boundary precision (-1s / +1s) ------------------


def test_x402_replay_window_boundary_ttl_constant_is_exact() -> None:
    """Static source assertion + JS evaluation: ``NONCE_TTL_SECONDS`` is
    exactly ``25 * 60 * 60 == 90000`` seconds. A refactor that quietly
    shortens (or lengthens) the window would change the security
    contract documented in the FAIL-CLOSED banner (lines 7-61). Pin it."""
    src = (REPO_ROOT / "functions/x402_handler.ts").read_text(encoding="utf-8")
    # Source-grep: the literal that defines the window.
    assert "const NONCE_TTL_SECONDS = 25 * 60 * 60" in src, (
        "functions/x402_handler.ts must pin NONCE_TTL_SECONDS = 25 * 60 * 60"
    )
    # The put-site must reference the same constant (not a hard-coded
    # number that could drift). functions/x402_handler.ts line 806.
    assert "expirationTtl: NONCE_TTL_SECONDS" in src, (
        "tx: put must use NONCE_TTL_SECONDS, not a hard-coded number"
    )
    # The read-site must use the matching `tx:` key prefix.
    assert "`tx:${txHash}`" in src, "replay read must scan the tx:<hash> KV namespace"
    # And the value must be exactly 90000 — verify by running the module
    # and pulling the captured TTL out of a successful put.
    _run_node(
        EDGE_HELPERS
        + r"""
const kv = makeKv();
const env = makeEnv(kv);
const quote = await issueQuote(env);
globalThis.fetch = async (url) => {
  const s = String(url);
  if (s === rpcUrl) {
    return Response.json({
      result: receiptWith([
        usdcTransferLog({ amount: quote.amount_usdc_micro }),
      ]),
    });
  }
  if (s === `${apiBase}/v1/billing/x402/issue_key`) {
    return new Response(
      JSON.stringify({ api_key: "jc_x402_boundary", expires_at: "2099-01-01T00:00:00Z" }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }
  throw new Error(`unexpected fetch ${url}`);
};
const resp = await invoke(env, "/x402/verify", {
  tx_hash: "0x" + "d".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_replay",
});
assert.equal(resp.status, 200, await resp.text());
const txPuts = kv.putCalls.filter((c) => c.key.startsWith("tx:"));
assert.equal(txPuts.length, 1, "exactly one tx: put on successful redemption");
// -1s / +1s boundary precision: 89999 and 90001 are both wrong.
assert.notEqual(txPuts[0].options.expirationTtl, 89999, "TTL must not be -1s short");
assert.notEqual(txPuts[0].options.expirationTtl, 90001, "TTL must not be +1s long");
// Exact value must be 90000s == 25h.
assert.equal(txPuts[0].options.expirationTtl, 90000, "TTL must be exactly 25h (90000s)");
"""
    )


def test_x402_replay_window_boundary_minus_1s_and_plus_1s_behavior() -> None:
    """Window-edge behavior: at t = NONCE_TTL_SECONDS - 1s the key is
    still live (replay gate rejects); at t = NONCE_TTL_SECONDS + 1s the
    key is evicted (replay gate is silent).

    The edge handler itself does not measure time-since-put — it relies
    entirely on Cloudflare KV's ``expirationTtl`` semantics. So this test
    pins the **behavioral contract** at the boundary by:

      - ``-1s case`` (key still present in KV): replay gate rejects.
      - ``+1s case`` (key evicted from KV): replay gate is bypassed.

    The two cases together prove the boundary is correctly delegated to
    KV's TTL eviction and the handler does not silently widen or narrow
    the documented 25h window via its own time arithmetic."""
    _run_node(
        EDGE_HELPERS
        + r"""
// ---- t = TTL - 1s : key still present, replay gate rejects ----
{
  const txHash = "0x" + "1".repeat(64);
  const kv = makeKv({ preSeeded: { [`tx:${txHash}`]: "1" } });
  const env = makeEnv(kv);
  const quote = await issueQuote(env);
  globalThis.fetch = async (url) => {
    throw new Error(`-1s boundary must reject before any fetch: ${url}`);
  };
  const resp = await invoke(env, "/x402/verify", {
    tx_hash: txHash,
    quote_id: quote.quote_id,
    agent_id: "agent_replay",
  });
  const body = await responseJson(resp);
  assert.equal(resp.status, 402, "-1s: replay gate must reject");
  assert.equal(body.reason, "tx_already_redeemed", "-1s: reason must be tx_already_redeemed");
}

// ---- t = TTL + 1s : key evicted, replay gate silent ----
{
  const txHash = "0x" + "2".repeat(64);
  const kv = makeKv({ evictedKeys: new Set([`tx:${txHash}`]) });
  const env = makeEnv(kv);
  const quote = await issueQuote(env);
  let originHits = 0;
  globalThis.fetch = async (url) => {
    const s = String(url);
    if (s === rpcUrl) {
      return Response.json({
        result: receiptWith([
          usdcTransferLog({ amount: quote.amount_usdc_micro }),
        ]),
      });
    }
    if (s === `${apiBase}/v1/billing/x402/issue_key`) {
      originHits += 1;
      return new Response(
        JSON.stringify({ api_key: "jc_x402_post_window", expires_at: "2099-01-01T00:00:00Z" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const resp = await invoke(env, "/x402/verify", {
    tx_hash: txHash,
    quote_id: quote.quote_id,
    agent_id: "agent_replay",
  });
  const body = await responseJson(resp);
  assert.equal(resp.status, 200, JSON.stringify(body));
  assert.equal(body.api_key, "jc_x402_post_window", "+1s: fresh api_key minted");
  assert.equal(originHits, 1, "+1s: origin reached because replay gate is silent");
  // Fresh redemption rewrites the tx: key with the full 25h TTL again.
  const reput = kv.putCalls.find((c) => c.key === `tx:${txHash}`);
  assert.ok(reput, "+1s: successful redemption must re-put tx: key");
  assert.equal(reput.options.expirationTtl, 90000, "+1s: re-put TTL must be 25h");
}
"""
    )


# ---------- Test 4: anti-regression source guard ---------------------------


def test_x402_replay_handler_source_pins_25h_ttl_constant() -> None:
    """Anti-regression: the source file must keep the 25h replay window.

    Defends against three plausible refactor mistakes:

      1. Lowering the literal (e.g. ``25 * 60 * 60`` -> ``24 * 60 * 60``).
      2. Replacing the symbolic constant in the ``put`` site with a
         hard-coded number that could drift (e.g.
         ``expirationTtl: 86400``).
      3. Removing the ``tx:`` key-prefix probe in ``verifyTx`` so the
         replay gate becomes a no-op while the symbolic constant stays
         in place (silent failure mode).
    """
    src = (REPO_ROOT / "functions/x402_handler.ts").read_text(encoding="utf-8")
    # (1) constant must be exactly 25*60*60.
    assert "const NONCE_TTL_SECONDS = 25 * 60 * 60" in src, (
        "NONCE_TTL_SECONDS must be defined as 25 * 60 * 60"
    )
    # (2) put-site must use the symbol, not a hard-coded number.
    assert "expirationTtl: NONCE_TTL_SECONDS" in src, (
        "tx: KV put must reference the named constant, not a literal"
    )
    # (3) read-site must scan tx:<hash>.
    assert "env.JPCITE_X402_KV.get(`tx:${txHash}`)" in src, (
        "verifyTx must read the tx:<hash> namespace for replay defence"
    )
    # (4) the rejection reason string must remain stable for downstream
    # automation that branches on it.
    assert "tx_already_redeemed" in src, (
        "the tx_already_redeemed reason string is part of the public contract"
    )
    # (5) the documented 25h banner must still reference NONCE_TTL_SECONDS.
    assert "NONCE_TTL_SECONDS" in src and "25 h" in src, (
        "the FAIL-CLOSED banner must continue to document the 25h replay window"
    )
