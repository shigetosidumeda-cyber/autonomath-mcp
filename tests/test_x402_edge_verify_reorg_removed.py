"""x402 edge verifier must ignore reorg-removed receipt logs (R2 P2, 2026-05-13).

Geth-compatible RPCs flag logs that were emitted on an orphaned chain
branch with ``removed: true`` once a reorg supersedes them. ``hasSufficientUsdcTransfer``
walks ``receipt.logs`` looking for a settled USDC transfer that matches the
quoted payer/recipient/amount; without the ``removed`` guard a stale log
from a forked branch could authenticate a redemption against a quote that
will never finalise on the canonical chain.

Base finalises quickly, so the actual likelihood is low — but the guard is
a single ``if`` and the cost of a wrong grant is one minted API key
without USDC settlement, which is unacceptable. This test pins the guard
into place so a refactor cannot quietly drop it.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is required for x402 edge handler behavior tests")
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


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

async function issueQuote(agentId = "agent_1") {
  const resp = await invoke("/x402/quote", {
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


def test_x402_edge_verify_ignores_reorg_removed_transfer_log() -> None:
    """A receipt whose only matching log has ``removed: true`` must be refused."""
    _run_node(
        EDGE_HELPERS
        + r"""
const quote = await issueQuote();
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
  if (String(url) === rpcUrl) {
    return Response.json({
      result: receiptWith([
        usdcTransferLog({ amount: quote.amount_usdc_micro, removed: true }),
      ]),
    });
  }
  throw new Error(`origin must not be called when only removed logs match: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "b".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402, JSON.stringify(body));
assert.equal(body.reason, "wrong_amount_or_recipient");
assert.equal(calls.length, 1, "only rpc should be hit");
assert.equal(calls[0].url, rpcUrl);
assert.equal(kv.putCalls.filter((c) => c.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_accepts_non_removed_log_alongside_removed_ones() -> None:
    """If a removed log AND a live matching log are both present, the live one wins."""
    _run_node(
        EDGE_HELPERS
        + r"""
const quote = await issueQuote();
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  const body = init.body ? JSON.parse(init.body) : null;
  calls.push({ url: String(url), body });
  if (String(url) === rpcUrl) {
    return Response.json({
      result: receiptWith([
        // Stale reorg-removed entry FIRST so the loop must walk past it.
        usdcTransferLog({ amount: quote.amount_usdc_micro, removed: true }),
        // Live finalised transfer SECOND — the one the redemption is for.
        usdcTransferLog({ amount: quote.amount_usdc_micro }),
      ]),
    });
  }
  if (String(url) === `${apiBase}/v1/billing/x402/issue_key`) {
    return new Response(
      JSON.stringify({ api_key: "jc_x402_reorg_pass", expires_at: "2099-01-01T00:00:00Z" }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }
  throw new Error(`unexpected fetch ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "c".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 200, JSON.stringify(body));
assert.equal(body.api_key, "jc_x402_reorg_pass");
"""
    )


def test_x402_edge_verify_handler_source_contains_removed_guard() -> None:
    """Static guard: a refactor must not drop the ``removed`` check."""
    src = (REPO_ROOT / "functions/x402_handler.ts").read_text(encoding="utf-8")
    assert "log?.removed === true" in src, (
        "hasSufficientUsdcTransfer must skip logs flagged removed by the RPC"
    )


def test_x402_edge_verify_rejects_log_with_mismatched_block_hash() -> None:
    """D8 hardening (2026-05-13): a malicious RPC may splice a Transfer log
    from a different block into a receipt. The verifier must compare
    ``log.blockHash`` against ``receipt.blockHash`` and reject any mismatch
    before forwarding to the origin issue_key endpoint."""
    _run_node(
        EDGE_HELPERS
        + r"""
const quote = await issueQuote();
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
  if (String(url) === rpcUrl) {
    // Receipt itself lives in block 0xfff..., but the embedded Transfer log
    // claims to be from block 0xdead... — a classic splice attack.
    return Response.json({
      result: receiptWith(
        [
          usdcTransferLog({
            amount: quote.amount_usdc_micro,
            blockHash: "0x" + "d".repeat(64),
            transactionHash: DEFAULT_TX_HASH_BINDING,
          }),
        ],
      ),
    });
  }
  throw new Error(`origin must not be called for spliced log: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "e".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402, JSON.stringify(body));
assert.equal(body.reason, "wrong_amount_or_recipient");
assert.equal(calls.length, 1, "only rpc should be hit; origin must be untouched");
assert.equal(calls[0].url, rpcUrl);
assert.equal(kv.putCalls.filter((c) => c.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_rejects_log_with_mismatched_transaction_hash() -> None:
    """D8 hardening: a Transfer log whose ``transactionHash`` does not match the
    enclosing receipt's ``transactionHash`` must also be refused — the receipt
    binding is what proves the log was actually emitted by the funded tx."""
    _run_node(
        EDGE_HELPERS
        + r"""
const quote = await issueQuote();
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
  if (String(url) === rpcUrl) {
    return Response.json({
      result: receiptWith([
        usdcTransferLog({
          amount: quote.amount_usdc_micro,
          blockHash: DEFAULT_BLOCK_HASH,
          // Tx-hash splice: log claims to belong to a different transaction.
          transactionHash: "0x" + "9".repeat(64),
        }),
      ]),
    });
  }
  throw new Error(`origin must not be called for spliced log: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "7".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402, JSON.stringify(body));
assert.equal(body.reason, "wrong_amount_or_recipient");
assert.equal(calls.length, 1, "only rpc should be hit");
assert.equal(kv.putCalls.filter((c) => c.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_rejects_receipt_without_block_hash() -> None:
    """D8 hardening: receipts missing ``blockHash`` or ``transactionHash``
    cannot be authenticated and must be refused outright."""
    _run_node(
        EDGE_HELPERS
        + r"""
const quote = await issueQuote();
globalThis.fetch = async (url) => {
  if (String(url) === rpcUrl) {
    // Receipt is missing both blockHash and transactionHash — cannot bind logs.
    return Response.json({
      result: {
        status: "0x1",
        logs: [usdcTransferLog({ amount: quote.amount_usdc_micro })],
      },
    });
  }
  throw new Error(`origin must not be called for un-bindable receipt: ${url}`);
};

const resp = await invoke("/x402/verify", {
  tx_hash: "0x" + "6".repeat(64),
  quote_id: quote.quote_id,
  agent_id: "agent_1",
});
const body = await responseJson(resp);
assert.equal(resp.status, 402, JSON.stringify(body));
assert.equal(body.reason, "wrong_amount_or_recipient");
assert.equal(kv.putCalls.filter((c) => c.key.startsWith("tx:")).length, 0);
"""
    )


def test_x402_edge_verify_handler_source_contains_block_hash_guard() -> None:
    """Static guard: a refactor must not drop the D8 block_hash / tx_hash binding."""
    src = (REPO_ROOT / "functions/x402_handler.ts").read_text(encoding="utf-8")
    assert "logBlockHash !== receiptBlockHash" in src, (
        "hasSufficientUsdcTransfer must bind every log to receipt.blockHash"
    )
    assert "logTxHash !== receiptTxHash" in src, (
        "hasSufficientUsdcTransfer must bind every log to receipt.transactionHash"
    )
