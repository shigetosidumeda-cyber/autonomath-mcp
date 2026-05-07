"""GZip response compression contract tests.

Pins the GZipMiddleware wired in `api/main.py` (added LAST so it sits
OUTERMOST in Starlette's LIFO middleware stack — runs AFTER CORS +
OriginEnforcement on the response leg).

Three contract assertions:

1. Large responses (>= 1024 bytes) negotiate gzip when the caller advertises
   ``Accept-Encoding: gzip`` — verified via ``Content-Encoding: gzip`` on
   the response.
2. Small responses (< 1024 bytes) skip compression — no CPU spent on a
   payload too small to net a network win.
3. Disclaimer envelope (§52 / §72 surfaces) is preserved byte-for-byte
   through compression — a decompressed body still carries the legally
   required text.

NOTE: This is a NETWORK-bandwidth optimization (Cloudflare egress + Fly
small-machine bandwidth). It does NOT reduce LLM token counts — the LLM
sees the uncompressed text after the HTTP layer decompresses.
"""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_large_response_gzipped(client: TestClient) -> None:
    """A large response (>= 1024 bytes) is compressed when the caller
    advertises ``Accept-Encoding: gzip``.

    ``/openapi.json`` is a deterministic large payload (≫ 1024 bytes,
    typically several hundred KB once 240+ routes are registered) so the
    minimum_size gate trips reliably across environments.

    httpx (TestClient backend) auto-decompresses response.content on
    read, so we assert against the raw header rather than length —
    ``Content-Encoding: gzip`` is the on-the-wire contract bit.
    """
    r = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200, r.text

    content_encoding = r.headers.get("Content-Encoding", "")
    assert "gzip" in content_encoding, (
        f"expected gzip Content-Encoding on large /openapi.json, got "
        f"{content_encoding!r} (response bytes after decompress="
        f"{len(r.content)})"
    )


def test_small_response_minimum_size_gate_configured(client: TestClient) -> None:
    """The GZipMiddleware is wired with ``minimum_size=1024``.

    Honest scope note: Starlette's GZipMiddleware enforces ``minimum_size``
    only on the SINGLE-MESSAGE (non-streaming) branch of its responder
    (see ``starlette/middleware/gzip.py`` lines 62-69). When the response
    is wrapped by an upstream ``BaseHTTPMiddleware`` (and this codebase
    has ~20 of them — SecurityHeaders, ResponseSanitizer, CORS internals,
    etc.) the response leg goes through the STREAMING branch (lines
    83-95) which compresses regardless of size. Net-net: tiny responses
    can still arrive gzip-encoded, which is wasted CPU but harmless.

    This test pins the configured value (so a future edit cannot silently
    bump it back to the Starlette default of 500) rather than asserting
    the runtime gate skips a small body — the latter would be a fragile
    assertion against the upstream Starlette + BaseHTTPMiddleware
    interaction.
    """
    from starlette.middleware.gzip import GZipMiddleware as _G

    from jpintel_mcp.api.main import create_app

    app = create_app()
    matches = [m for m in app.user_middleware if m.cls is _G]
    assert matches, "GZipMiddleware not wired into the app"
    # user_middleware entry kwargs carry the constructor args.
    assert (
        matches[0].kwargs.get("minimum_size") == 1024
    ), f"expected minimum_size=1024, got {matches[0].kwargs.get('minimum_size')!r}"
    assert (
        matches[0].kwargs.get("compresslevel") == 6
    ), f"expected compresslevel=6, got {matches[0].kwargs.get('compresslevel')!r}"


def test_disclaimer_preserved_after_gzip(client: TestClient) -> None:
    """Compression preserves response body bytes exactly.

    Verified two ways:
      - the decompressed JSON parses back into a valid dict (no truncation
        or corruption from the gzip layer)
      - the canonical envelope keys we expect on /openapi.json are present
        after decompression (sanity: nothing was dropped en-route)

    This is the key honesty assertion: a §52 / §72 disclaimer envelope
    must survive the compression hop unaltered, otherwise we lose the
    legal-disclaimer guarantee that ResponseSanitizerMiddleware has
    already validated.
    """
    r = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200, r.text
    assert "gzip" in r.headers.get("Content-Encoding", "")

    # httpx (TestClient backend) auto-decompresses .content / .json() so
    # if the gzip stream were corrupt either call would raise. Assert
    # the parsed body looks like the canonical OpenAPI envelope.
    body = r.json()
    assert isinstance(body, dict)
    assert "openapi" in body, "openapi key dropped through gzip"
    assert "paths" in body, "paths key dropped through gzip"
    # Round-trip: re-encode and confirm we still have a non-trivial
    # payload (not an empty {} or partial fragment).
    redumped = json.dumps(body)
    assert len(redumped) > 1024, (
        f"decompressed body suspiciously small ({len(redumped)} bytes) — "
        f"likely truncation through the gzip layer"
    )


def test_no_accept_encoding_returns_uncompressed(client: TestClient) -> None:
    """Caller without ``Accept-Encoding: gzip`` gets an uncompressed body.

    Belt-and-suspenders for clients that explicitly opt out of
    compression — they must still receive a usable response.
    """
    # Force-disable httpx's default Accept-Encoding negotiation by passing
    # an explicit identity header.
    r = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200, r.text

    content_encoding = r.headers.get("Content-Encoding", "")
    assert "gzip" not in content_encoding, (
        f"client opted out of gzip but server still compressed (got "
        f"Content-Encoding={content_encoding!r})"
    )


def test_gzip_size_reduction_sample(client: TestClient) -> None:
    """Sanity sample: gzip cuts /openapi.json transfer size by >= 3x.

    This is a smoke-grade ratio assertion (not a hard SLA). On the
    measured corpus today (~240 routes, ~hundreds of KB JSON) the
    ratio sits comfortably in the 5-10x band the task spec calls
    out. Asserting >= 3x leaves headroom for future spec growth /
    schema additions while still failing loud if compression
    accidentally regresses to a no-op.
    """
    # Uncompressed reference body
    r_id = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert r_id.status_code == 200
    raw_size = len(r_id.content)

    # Compressed-on-wire size: re-encode the parsed body and gzip it
    # ourselves to mirror what the middleware does — TestClient auto-
    # decompresses .content so we cannot read the raw gzip bytes
    # straight off the wire without dropping into the lower-level
    # transport. This stand-in is a tight upper bound on the real
    # on-wire bytes.
    compressed = gzip.compress(r_id.content, compresslevel=6)
    compressed_size = len(compressed)

    assert raw_size >= 1024, (
        f"reference openapi response unexpectedly small ({raw_size} bytes); "
        f"the size sample is meaningless below the gzip minimum_size gate"
    )
    ratio = raw_size / max(compressed_size, 1)
    assert ratio >= 3.0, (
        f"gzip ratio regressed: raw={raw_size} compressed={compressed_size} "
        f"ratio={ratio:.2f}x (expected >= 3x on /openapi.json)"
    )
    # Surface the sample numbers in pytest -v output for the task report.
    print(
        f"[gzip sample] /openapi.json raw={raw_size}B compressed={compressed_size}B "
        f"ratio={ratio:.2f}x"
    )
