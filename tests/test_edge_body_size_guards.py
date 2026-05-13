"""R3 missing-guard cluster — body-size cap tests for edge handlers.

Background
----------
Three Cloudflare Pages Function entry points used to call
``await request.json()`` without any cap on payload size. A misbehaving
or malicious client could stream a multi-MB body and inflate worker
CPU + memory or trip Pages' opaque 1MB request-body limit on a non-
deterministic path. R3 wires the two missing-guard handlers
(``dpa_issue.ts`` and ``ab_assign.ts``) onto a shared helper
``functions/_body_limit.ts:readRequestTextLimited`` that:

  1. rejects via ``content-length`` short-circuit when the client
     advertises a size > maxBytes,
  2. streams the body and aborts the reader as soon as total bytes
     exceed maxBytes,
  3. returns a discriminated union so each handler picks its own
     413 envelope shape.

``x402_handler.ts`` already had its own ``readJsonBodyCapped`` +
``bodyTooLargeResponse`` (MAX_X402_JSON_BODY_BYTES=8KB); this test file
asserts the existing guard stayed intact rather than re-imposing one
(A5 owns that surface — body-parse gating is the only thing R3 touches
there, and that gating already exists).

This file mixes static-source assertions (cheap, no Node) with Node-
driven behavior tests (executes the actual handler against fabricated
``Request`` objects). Both are needed:

  - Static asserts pin the *pattern* — a future refactor that drops
    the cap or moves the parse before the cap fails fast.
  - Node behavior asserts pin the *semantics* — oversized bodies
    return 413 with ``payload_too_large`` / ``request_body_too_large``
    envelope and undersized bodies succeed.
"""

from __future__ import annotations

from pathlib import Path

from tests.edge_ts_runner import run_edge_node

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.exists(), f"missing file: {rel}"
    return path.read_text(encoding="utf-8")


def _assert_before(src: str, first: str, second: str) -> None:
    assert first in src, f"missing marker: {first}"
    assert second in src, f"missing marker: {second}"
    assert src.index(first) < src.index(second), f"{first!r} must appear before {second!r}"


def _run_node(script: str) -> None:
    run_edge_node(script, timeout=20)


# ---------------------------------------------------------------------------
# Static-source guards — pin the cap pattern across the three handlers.
# ---------------------------------------------------------------------------


def test_shared_body_limit_helper_exists_with_streaming_cap() -> None:
    src = _read("functions/_body_limit.ts")
    assert "export async function readRequestTextLimited" in src
    assert "export function contentLengthExceeds" in src
    assert ".getReader()" in src
    assert "reader.cancel()" in src
    # discriminated union signals 413 reject vs OK with payload
    assert "ok: true" in src and "ok: false" in src


def test_dpa_issue_caps_body_before_json_parse() -> None:
    src = _read("functions/dpa_issue.ts")
    assert 'from "./_body_limit.ts"' in src
    assert "MAX_BODY_BYTES = 4 * 1024" in src
    assert "readRequestTextLimited(request, MAX_BODY_BYTES)" in src
    assert '"payload_too_large"' in src
    assert "status: 413" in src
    # Cap MUST run before JSON.parse — else the parse already consumed
    # the unbounded body.
    _assert_before(
        src,
        "readRequestTextLimited(request, MAX_BODY_BYTES)",
        "JSON.parse(bodyRead.text)",
    )
    # The old unbounded `await request.json()` is gone.
    assert "await request.json()" not in src


def test_ab_assign_caps_conversion_body_before_json_parse() -> None:
    src = _read("functions/ab_assign.ts")
    assert 'from "./_body_limit.ts"' in src
    assert "MAX_BODY_BYTES = 2 * 1024" in src
    assert "readRequestTextLimited(context.request, MAX_BODY_BYTES)" in src
    assert '"payload_too_large"' in src
    assert "status: 413" in src
    _assert_before(
        src,
        "readRequestTextLimited(context.request, MAX_BODY_BYTES)",
        "JSON.parse(bodyRead.text)",
    )
    assert "await context.request.json()" not in src


def test_x402_handler_retains_existing_8kb_body_cap() -> None:
    # x402 surface is owned by A5; R3 only asserts the existing guard
    # is intact — no re-imposition.
    src = _read("functions/x402_handler.ts")
    assert "MAX_X402_JSON_BODY_BYTES = 8 * 1024" in src
    assert "function readJsonBodyCapped" in src
    assert "x402_body_too_large" in src
    assert "function bodyTooLargeResponse" in src
    # Both /x402/quote and /x402/verify must route oversized bodies
    # through bodyTooLargeResponse before any downstream work. Locate
    # the actual POST routing branches (the path-matcher list near the
    # top of the file uses the same string literal, so we pin on the
    # `method === "POST"` clause).
    quote_branch_idx = src.index('"/x402/quote" && method === "POST"')
    verify_branch_idx = src.index('"/x402/verify" && method === "POST"')
    quote_section = src[quote_branch_idx:verify_branch_idx]
    verify_section = src[verify_branch_idx:]
    for label, section in (("quote", quote_section), ("verify", verify_section)):
        assert "readJsonBodyCapped(request)" in section, (
            f"x402 {label} branch must use readJsonBodyCapped"
        )
        assert "bodyTooLargeResponse()" in section, (
            f"x402 {label} branch must return bodyTooLargeResponse on overflow"
        )


# ---------------------------------------------------------------------------
# Node-driven behavior guards — actually invoke the handlers with
# oversized + undersized bodies and assert the response envelope.
# ---------------------------------------------------------------------------


DPA_TEST_HARNESS = r"""
import assert from "node:assert/strict";

const { onRequestPost } = await import("./functions/dpa_issue.ts");

// Minimal ASSETS Fetcher stub — DPA only reaches it after the body
// guard passes, so the oversize test never invokes it. For the
// undersize-but-rejected-401 test we still need a stub so the import
// resolves.
const env = {
  ASSETS: {
    async fetch(_req) {
      return new Response("template_stub", { status: 500 });
    },
  },
  JPCITE_API_BASE: "https://api.local",
};

// Stub fetch to avoid hitting any real network during these tests.
globalThis.fetch = async (url) => {
  // /v1/me always 401 in this harness — we only care about the
  // body-size gate, which fires BEFORE auth.
  return new Response("{}", { status: 401 });
};

async function invokePost(bodyText, headers = {}) {
  return await onRequestPost({
    request: new Request("https://jpcite.test/dpa/issue", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: bodyText,
    }),
    env,
  });
}
"""


def test_dpa_issue_rejects_oversize_body_with_413() -> None:
    _run_node(
        DPA_TEST_HARNESS
        + r"""
// 5KB body > 4KB cap.
const oversize = JSON.stringify({
  company: "X".repeat(2500),
  user_name: "Y".repeat(2500),
});
assert.ok(oversize.length > 4096, "fixture must exceed 4KB cap");

const resp = await invokePost(oversize);
assert.equal(resp.status, 413, "oversize body must 413");
const body = JSON.parse(await resp.text());
assert.equal(body.error, "payload_too_large");
assert.equal(body.max_bytes, 4096);
"""
    )


def test_dpa_issue_allows_undersize_body_through_to_auth_gate() -> None:
    _run_node(
        DPA_TEST_HARNESS
        + r"""
// Tiny body (well under 4KB) — body guard passes, but the stub fetch
// returns 401 for /v1/me so the handler responds 401
// invalid_api_key. The point is: the response is NOT 413.
const tiny = JSON.stringify({ company: "Acme K.K.", user_name: "Taro Yamada" });
assert.ok(tiny.length < 4096);

const resp = await invokePost(tiny, { authorization: "Bearer jc_dummy" });
assert.notEqual(resp.status, 413, "undersize body must not 413");
// Auth stub returns 401, so the handler 401s. That's the expected
// pass-through.
assert.equal(resp.status, 401);
"""
    )


def test_dpa_issue_rejects_via_content_length_short_circuit() -> None:
    _run_node(
        DPA_TEST_HARNESS
        + r"""
// content-length advertises 999999 but the body itself is tiny. The
// helper MUST short-circuit on the header before reading a byte.
const tiny = JSON.stringify({ company: "Acme", user_name: "Taro" });
const resp = await onRequestPost({
  request: new Request("https://jpcite.test/dpa/issue", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": "999999",
    },
    body: tiny,
  }),
  env,
});
assert.equal(resp.status, 413, "content-length oversize must 413");
const body = JSON.parse(await resp.text());
assert.equal(body.error, "payload_too_large");
"""
    )


AB_TEST_HARNESS = r"""
import assert from "node:assert/strict";

const { onRequestPost } = await import("./functions/ab_assign.ts");

const env = { JPCITE_API_BASE: "https://api.local" };

// Stub upstream fetch — never reached by the oversize path.
globalThis.fetch = async () => new Response("{}", { status: 200 });

async function invokeConversion(bodyText, extraHeaders = {}) {
  return await onRequestPost({
    request: new Request("https://jpcite.test/ab/conversion", {
      method: "POST",
      headers: { "content-type": "application/json", ...extraHeaders },
      body: bodyText,
    }),
    env,
  });
}
"""


def test_ab_assign_conversion_rejects_oversize_body_with_413() -> None:
    _run_node(
        AB_TEST_HARNESS
        + r"""
// 3KB body > 2KB cap.
const oversize = JSON.stringify({
  test_id: "landing_copy_v1",
  event: "conversion",
  cookie_bucket: "a",
  external_ref: "X".repeat(3000),
});
assert.ok(oversize.length > 2048);

const resp = await invokeConversion(oversize);
assert.equal(resp.status, 413);
const body = JSON.parse(await resp.text());
assert.equal(body.error, "payload_too_large");
assert.equal(body.max_bytes, 2048);
"""
    )


def test_ab_assign_conversion_allows_undersize_body_through() -> None:
    _run_node(
        AB_TEST_HARNESS
        + r"""
// Tiny conversion payload — passes the body guard. We don't care
// what the rest of the handler decides (it will validate test_id /
// bucket against KNOWN_TESTS); we only assert the response is NOT
// 413 payload_too_large.
const tiny = JSON.stringify({
  test_id: "landing_copy_v1",
  event: "conversion",
  cookie_bucket: "a",
});
assert.ok(tiny.length < 2048);

const resp = await invokeConversion(tiny);
assert.notEqual(resp.status, 413, "undersize body must not 413");
"""
    )


def test_ab_assign_conversion_rejects_via_content_length_short_circuit() -> None:
    _run_node(
        AB_TEST_HARNESS
        + r"""
const tiny = JSON.stringify({
  test_id: "landing_copy_v1",
  event: "conversion",
  cookie_bucket: "a",
});
const resp = await onRequestPost({
  request: new Request("https://jpcite.test/ab/conversion", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": "999999",
    },
    body: tiny,
  }),
  env,
});
assert.equal(resp.status, 413);
const body = JSON.parse(await resp.text());
assert.equal(body.error, "payload_too_large");
"""
    )


X402_TEST_HARNESS = r"""
import assert from "node:assert/strict";

const { onRequest } = await import("./functions/x402_handler.ts");

// Bare-bones env — body-size gate runs before any of these are read,
// but the import resolves cleanly only if they're present.
const env = {
  JPCITE_X402_KV: null,
  JPCITE_X402_ADDRESS: "0x" + "2".repeat(40),
  JPCITE_X402_QUOTE_SECRET: "quote-secret",
  JPCITE_X402_RPC_URL: "https://rpc.local",
  JPCITE_X402_ORIGIN_SECRET: "origin-secret",
  JPCITE_API_BASE: "https://api.local",
  JPCITE_X402_FALLBACK_JPY_PER_USDC: "150",
};

globalThis.fetch = async () => new Response("{}", { status: 500 });

async function invoke(path, bodyText, extraHeaders = {}) {
  return await onRequest({
    request: new Request("https://jpcite.test" + path, {
      method: "POST",
      headers: { "content-type": "application/json", ...extraHeaders },
      body: bodyText,
    }),
    env,
  });
}
"""


def test_x402_quote_rejects_oversize_body_with_413() -> None:
    # The existing guard at MAX_X402_JSON_BODY_BYTES=8KB must still
    # fire — A5 already owns this surface; R3 just verifies it's
    # intact and observable behaviorally.
    _run_node(
        X402_TEST_HARNESS
        + r"""
const oversize = JSON.stringify({
  path: "/v1/programs/search",
  method: "GET",
  agent_id: "agent_X",
  payer_address: "0x" + "1".repeat(40),
  pad: "X".repeat(9000),
});
assert.ok(oversize.length > 8192);

const resp = await invoke("/x402/quote", oversize);
assert.equal(resp.status, 413);
const body = JSON.parse(await resp.text());
assert.equal(body.error, "request_body_too_large");
assert.equal(body.max_bytes, 8192);
"""
    )


def test_x402_verify_rejects_oversize_body_with_413() -> None:
    _run_node(
        X402_TEST_HARNESS
        + r"""
const oversize = JSON.stringify({
  tx_hash: "0x" + "a".repeat(64),
  quote_id: "stub-quote-id",
  agent_id: "agent_X",
  pad: "X".repeat(9000),
});
assert.ok(oversize.length > 8192);

const resp = await invoke("/x402/verify", oversize);
assert.equal(resp.status, 413);
const body = JSON.parse(await resp.text());
assert.equal(body.error, "request_body_too_large");
assert.equal(body.max_bytes, 8192);
"""
    )
