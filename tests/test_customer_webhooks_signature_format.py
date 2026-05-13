"""Stability + forward-compat assertions for the customer webhook signature wire format.

Sister doc: ``docs/runbook/customer_webhook_signature.md``.

This suite pins the producer-side format and the customer-side parser
contract so that any drift in either direction (e.g. someone refactoring
``compute_signature`` to emit ``sha256=`` Stripe-style) trips the build
**before** the change reaches a live webhook. The complement
``test_customer_webhooks.py::test_compute_signature_matches_python_reference``
covers HMAC correctness for ONE known-good vector; this suite covers the
wire-format shape across many vectors plus the planned v2 rotation path.

Scope split (do not duplicate here):

  * HMAC correctness:           ``test_customer_webhooks.py``
  * Endpoint behaviour (auth, rate, 404, etc.): ``test_customer_webhooks.py``
  * Dispatcher cron retry / idempotency:        ``test_dispatch_webhooks.py``
  * **THIS FILE**:              the wire string the customer sees + the
                                forward-compat upgrade path documented in
                                the runbook.

NO LLM imports per CLAUDE.md. Pure stdlib + ``compute_signature``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

import pytest

from jpintel_mcp.api.customer_webhooks import compute_signature

# ---------------------------------------------------------------------------
# Format constants — mirror the wire contract in the runbook.
# ---------------------------------------------------------------------------

_V1_PREFIX = "hmac-sha256="
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_V1_HEADER_RE = re.compile(r"^hmac-sha256=[0-9a-f]{64}$")
# v2 (Stripe-style) rotation envelope. Element order MUST start with
# ``t=<unix>`` then ``v1=<hex>``. Tolerance window: ±300 s.
_V2_HEADER_RE = re.compile(r"^t=\d{10},v1=[0-9a-f]{64}$")
_REPLAY_TOLERANCE_S = 300


# ---------------------------------------------------------------------------
# Producer surface: compute_signature shape.
# ---------------------------------------------------------------------------


def test_compute_signature_shape_basic():
    """``hmac-sha256=`` literal + 64 lowercase hex chars, no whitespace."""
    secret = "whsec_" + secrets.token_urlsafe(32)
    body = b'{"event_type":"program.created","data":{}}'

    sig = compute_signature(secret, body)

    assert sig.startswith(_V1_PREFIX), sig
    presented = sig.removeprefix(_V1_PREFIX)
    assert _HEX_RE.match(presented), presented
    assert sig == sig.strip(), "no leading/trailing whitespace"
    assert _V1_HEADER_RE.match(sig), sig


@pytest.mark.parametrize(
    "body",
    [
        b"",  # empty body — corner case for new event types with no data
        b"{}",
        b'{"event_type":"test.ping"}',
        "日本語ペイロード".encode("utf-8"),  # multi-byte UTF-8
        b"\x00\x01\x02\xff" * 256,  # opaque binary (1 KiB)
        b"x" * 65536,  # 64 KiB upper-bound corpus
    ],
)
def test_compute_signature_shape_across_payloads(body: bytes):
    """Shape invariant must hold for every payload shape we might emit."""
    secret = "whsec_" + secrets.token_urlsafe(32)
    sig = compute_signature(secret, body)
    assert _V1_HEADER_RE.match(sig), (sig, len(body))


def test_compute_signature_is_deterministic():
    """Same secret + same body -> same signature, every time."""
    secret = "whsec_deterministic_test"
    body = b'{"event_type":"program.amended","timestamp":"2026-05-13T00:00:00Z"}'
    first = compute_signature(secret, body)
    again = compute_signature(secret, body)
    assert first == again


def test_compute_signature_differs_per_secret():
    """Different secrets MUST yield different signatures (sanity gate)."""
    body = b'{"event_type":"enforcement.added"}'
    a = compute_signature("whsec_" + "A" * 32, body)
    b = compute_signature("whsec_" + "B" * 32, body)
    assert a != b


def test_compute_signature_differs_per_body():
    """Different payloads MUST yield different signatures."""
    secret = "whsec_per_body_test"
    a = compute_signature(secret, b'{"k":1}')
    b = compute_signature(secret, b'{"k":2}')
    assert a != b


# ---------------------------------------------------------------------------
# Consumer surface: parser tolerance the runbook commits us to.
# ---------------------------------------------------------------------------


def _parse_v1_tolerant(header: str) -> str:
    """Reference v1 parser as documented in customer_webhook_signature.md.

    Strips whitespace + accepts a case-insensitive prefix. Returns the hex
    string (or raises ValueError). Mirrored verbatim from the runbook so
    the doc and the test cannot drift.
    """
    h = (header or "").strip()
    if not h.lower().startswith(_V1_PREFIX):
        raise ValueError("unknown signature scheme")
    presented = h.split("=", 1)[1].strip()
    if not _HEX_RE.match(presented):
        raise ValueError("not 64 hex chars")
    return presented


def test_parser_tolerates_whitespace():
    """Customer libraries that read header values commonly retain surrounding spaces."""
    secret = "whsec_whitespace_test"
    body = b"{}"
    raw = compute_signature(secret, body)
    expected_hex = raw.removeprefix(_V1_PREFIX)
    for variant in (
        raw,
        f"  {raw}",
        f"{raw}  ",
        f"\t{raw}\n",
        f"  {raw}  ",
    ):
        assert _parse_v1_tolerant(variant) == expected_hex, variant


def test_parser_prefix_case_insensitive():
    """``HMAC-SHA256=`` / ``Hmac-Sha256=`` MUST also verify against the same hex."""
    secret = "whsec_case_test"
    body = b'{"event_type":"tax_ruleset.amended"}'
    raw = compute_signature(secret, body)
    hex_part = raw.removeprefix(_V1_PREFIX)
    for upper in (
        "HMAC-SHA256=" + hex_part,
        "Hmac-Sha256=" + hex_part,
        "hMaC-sHa256=" + hex_part,
    ):
        assert _parse_v1_tolerant(upper) == hex_part, upper


def test_parser_rejects_unknown_scheme():
    """Anything not ``hmac-sha256=`` MUST be rejected — no silent fallback."""
    for bad in (
        "sha256=" + "0" * 64,  # Stripe v0 style — must NOT be parsed as v1
        "hmacsha256=" + "0" * 64,  # missing dash
        "hmac-sha512=" + "0" * 64,  # wrong algo
        "",
        "   ",
    ):
        with pytest.raises(ValueError):
            _parse_v1_tolerant(bad)


def test_parser_rejects_short_hex():
    """A truncated hex tail MUST fail length validation."""
    for bad in (
        _V1_PREFIX + "abcd",
        _V1_PREFIX + "0" * 63,
        _V1_PREFIX + "0" * 65,
        _V1_PREFIX + ("G" * 64),  # non-hex chars
    ):
        with pytest.raises(ValueError):
            _parse_v1_tolerant(bad)


# ---------------------------------------------------------------------------
# End-to-end verification on the customer side.
# ---------------------------------------------------------------------------


def test_customer_side_verification_round_trip():
    """Producer-side compute_signature MUST round-trip through the docs' verifier.

    This is the contract that breaks if anyone ever changes the HMAC
    construction (e.g. base64 instead of hex, or strips body whitespace).
    """
    secret = "whsec_round_trip_test"
    body = (
        b'{"event_type":"program.amended","timestamp":"2026-05-13T12:00:00+00:00",'
        b'"data":{"entity_id":"prog_001","diffs":[{"field":"deadline","before":null,"after":"2027-03-31"}]}}'
    )

    raw_header = compute_signature(secret, body)
    presented = _parse_v1_tolerant(raw_header)

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, presented)


def test_customer_side_verification_fails_on_body_tamper():
    """Tampered body MUST fail HMAC verification — basic integrity gate."""
    secret = "whsec_tamper_test"
    body = b'{"amount_yen":1000000}'
    presented = _parse_v1_tolerant(compute_signature(secret, body))

    tampered = b'{"amount_yen":9999999}'
    expected = hmac.new(secret.encode("utf-8"), tampered, hashlib.sha256).hexdigest()
    assert not hmac.compare_digest(expected, presented)


# ---------------------------------------------------------------------------
# Forward-compat: planned Stripe-style ``t=<unix>,v1=<hex>`` envelope.
# ---------------------------------------------------------------------------


def _compute_v2_signature(secret: str, body: bytes, unix_ts: int) -> str:
    """Reference v2 producer (NOT yet wired into dispatch_webhooks).

    Mirrors the rotation plan in ``docs/runbook/customer_webhook_signature.md``:
    signed input is ``f"{t}.".encode() + body``. Lives ONLY in this test —
    when production adopts v2 the implementation moves into
    ``customer_webhooks.compute_signature_v2`` and this helper is rewired to
    import it.
    """
    signed = f"{unix_ts}.".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={unix_ts},v1={digest}"


def _verify_dual_format(
    header: str,
    body: bytes,
    secret: str,
    now_unix: int,
) -> bool:
    """Customer-side verifier that handles BOTH v1 and v2 envelopes.

    Mirrors the example snippet in the runbook §2 so the doc and the
    forward-compat assertion cannot drift.
    """
    h = (header or "").strip()
    if h.lower().startswith(_V1_PREFIX):
        presented = h.split("=", 1)[1].strip()
        if not _HEX_RE.match(presented):
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, presented)
    if "t=" in h and "v1=" in h:
        parts = dict(kv.split("=", 1) for kv in h.split(","))
        try:
            t = int(parts["t"])
        except (KeyError, ValueError):
            return False
        v1 = parts.get("v1", "")
        if not _HEX_RE.match(v1):
            return False
        if abs(now_unix - t) > _REPLAY_TOLERANCE_S:
            return False
        signed = f"{t}.".encode("utf-8") + body
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    return False


def test_v2_signature_shape_matches_runbook():
    """Mocked v2 producer MUST emit ``t=<10digits>,v1=<64 hex>``."""
    secret = "whsec_v2_shape_test"
    body = b'{"event_type":"program.created"}'
    ts = 1_748_736_000  # 2025-06-01 00:00:00 UTC — fixed for determinism

    header = _compute_v2_signature(secret, body, ts)

    assert _V2_HEADER_RE.match(header), header
    assert header.startswith(f"t={ts},v1=")


def test_v2_signature_verifies_with_correct_timestamp():
    """A v2 header within the ±300 s window MUST verify."""
    secret = "whsec_v2_happy_test"
    body = b'{"event_type":"enforcement.added","data":{"case_id":1}}'
    now = int(time.time())
    header = _compute_v2_signature(secret, body, now)

    assert _verify_dual_format(header, body, secret, now_unix=now)


def test_v2_signature_rejected_when_replayed():
    """v2 enforces a ±300 s window; older signatures MUST be rejected."""
    secret = "whsec_v2_replay_test"
    body = b'{"event_type":"program.amended"}'
    issued_at = 1_748_736_000
    header = _compute_v2_signature(secret, body, issued_at)
    # 10 minutes after issuance — outside tolerance.
    later = issued_at + 600

    assert not _verify_dual_format(header, body, secret, now_unix=later)


def test_v2_upgrade_does_not_break_v1_verification():
    """Customers on the v1 verifier MUST keep working after the v2 producer ships.

    Captures the rotation invariant: even when dispatch_webhooks gains the
    capability to emit v2 headers, anything it emits as v1 today MUST stay
    verifiable by the v1-only parser the customer has in production.
    """
    secret = "whsec_rotation_test"
    body = b'{"event_type":"invoice_registrant.matched"}'

    # Today: dispatcher emits v1 only.
    v1_header = compute_signature(secret, body)
    assert _parse_v1_tolerant(v1_header)
    # The dual verifier covers the v1 path too — proves Phase 1 dual-emit
    # works for both legacy and upgraded customers.
    assert _verify_dual_format(v1_header, body, secret, now_unix=int(time.time()))


def test_v1_parser_does_not_misread_v2_header():
    """The v1 parser MUST NOT accept a v2 header as a v1 signature.

    A naive ``startswith("t=")`` is fine — but a buggy implementation that
    only checks ``"=" in header`` would silently pass and verify against the
    wrong input. This guards the v1 surface against accidental tolerance.
    """
    secret = "whsec_v1_strict_test"
    body = b'{"event_type":"program.created"}'
    v2_header = _compute_v2_signature(secret, body, int(time.time()))
    with pytest.raises(ValueError):
        _parse_v1_tolerant(v2_header)


def test_v2_signature_input_differs_from_v1():
    """v2 signs ``"<t>.<body>"``; v1 signs ``body``. The hex tails MUST diverge.

    Sanity gate on the rotation design: if someone ever ships v2 by
    re-using the v1 HMAC input the rotation gains zero replay defence.
    """
    secret = "whsec_input_diff_test"
    body = b'{"event_type":"tax_ruleset.amended"}'
    ts = 1_748_736_123

    v1_hex = compute_signature(secret, body).removeprefix(_V1_PREFIX)
    v2_header = _compute_v2_signature(secret, body, ts)
    v2_hex = dict(kv.split("=", 1) for kv in v2_header.split(","))["v1"]

    assert v1_hex != v2_hex
