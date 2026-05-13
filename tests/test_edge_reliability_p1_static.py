"""Static guard for edge reliability P1 Pages Function hardening."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.exists(), f"missing file: {rel}"
    return path.read_text(encoding="utf-8")


def _assert_before(src: str, first: str, second: str) -> None:
    assert first in src, f"missing marker: {first}"
    assert second in src, f"missing marker: {second}"
    assert src.index(first) < src.index(second), f"{first!r} must appear before {second!r}"


def test_api_proxy_caps_request_body_before_outbound_fetch() -> None:
    src = _read("functions/api_proxy.ts")
    assert "MAX_PROXY_BODY_BYTES = 1_048_576" in src
    assert "content-length" in src
    assert ".getReader()" in src
    assert "reader.cancel()" in src
    assert "UPSTREAM_FETCH_TIMEOUT_MS = 10_000" in src
    assert "AbortController" in src
    _assert_before(
        src,
        "readRequestBodyLimited(context.request, MAX_PROXY_BODY_BYTES)",
        "fetchWithTimeout(upstreamUrl, init, UPSTREAM_FETCH_TIMEOUT_MS)",
    )


def test_api_proxy_strips_spoofable_client_ip_headers_before_forwarding() -> None:
    src = _read("functions/api_proxy.ts")
    assert 'fwdHeaders.delete("fly-client-ip")' in src
    assert 'fwdHeaders.delete("x-forwarded-for")' in src
    _assert_before(
        src,
        'fwdHeaders.delete("fly-client-ip")',
        "fetchWithTimeout(upstreamUrl, init, UPSTREAM_FETCH_TIMEOUT_MS)",
    )
    _assert_before(
        src,
        'fwdHeaders.delete("x-forwarded-for")',
        "fetchWithTimeout(upstreamUrl, init, UPSTREAM_FETCH_TIMEOUT_MS)",
    )


def test_webhook_routers_cap_chunked_body_before_json_parse_and_timeout_fetch() -> None:
    for rel in ("functions/webhook_router.ts", "functions/webhook_router_v2.ts"):
        src = _read(rel)
        assert "OUTBOUND_FETCH_TIMEOUT_MS = 5_000" in src
        assert "fetchWithTimeout(url, {" in src
        assert "AbortController" in src
        assert "content-length" in src
        assert ".getReader()" in src
        assert "reader.cancel()" in src
        assert "ctx.request.text()" not in src
        assert "raw.length > MAX_BODY_BYTES" not in src
        _assert_before(
            src,
            "readRequestTextLimited(ctx.request, MAX_BODY_BYTES)",
            "parsed = JSON.parse(raw)",
        )


def test_rum_beacon_rejects_disallowed_origins_caps_body_and_defers_write() -> None:
    src = _read("functions/api/rum_beacon.ts")
    assert "MAX_BODY_BYTES = 4096" in src
    assert "isAllowedBrowserOrigin" in src
    assert "status: 403" in src
    assert 'headers["Access-Control-Allow-Origin"] = origin' in src
    assert "content-length" in src
    assert ".getReader()" in src
    assert "reader.cancel()" in src
    assert "request.json()" not in src
    assert "waitUntil.call(ctx, persist)" in src
    assert "await persist" in src
    _assert_before(
        src,
        "readRequestTextLimited(request, MAX_BODY_BYTES)",
        "JSON.parse(bodyRead.text)",
    )


def test_pages_routes_limit_function_invocations_to_dynamic_surfaces() -> None:
    routes = json.loads(_read("site/_routes.json"))
    assert routes["version"] == 1
    include = set(routes["include"])
    assert "/*" not in include
    assert "/api/*" in include
    assert "/x402/*" in include
    assert "/webhook/*" in include
    assert "/artifacts/*" in include
    assert "/laws/*" in include
    assert "/*.md" in include
    assert routes["exclude"] == []


def test_pages_routes_document_api_v1_and_x402_handler_expectations() -> None:
    """Lock the intended Pages routing contract for x402 audit review.

    `/api/*` is proxied through Pages Functions; `/v1/*` is intentionally not
    mounted there. The metered `/v1` branch in x402_handler is therefore a
    defensive/dead branch under the current `_routes.json`. Public x402
    endpoints are mounted by `/x402/*`.
    """
    routes = json.loads(_read("site/_routes.json"))
    include = set(routes["include"])

    assert "/api" in include
    assert "/api/*" in include
    assert "/v1" not in include
    assert "/v1/*" not in include
    assert "/x402" in include
    assert "/x402/*" in include

    x402_mount = _read("functions/x402/[[path]].ts")
    assert "../x402_handler" in x402_mount

    x402_src = _read("functions/x402_handler.ts")
    assert 'path === "/x402/quote" && method === "POST"' in x402_src
    assert 'path === "/x402/verify" && method === "POST"' in x402_src
    assert 'if (path.startsWith("/v1/")) return true;' in x402_src
    assert 'if (path.startsWith("/api/")) return true;' in x402_src


def test_status_static_headers_are_noindex_nofollow() -> None:
    src = _read("site/_headers")
    start = src.index("/status/*")
    end = src.index("\n\n", start)
    block = src[start:end]
    assert "X-Robots-Tag: noindex, nofollow" in block
    assert "X-Robots-Tag: index, follow" not in block


def test_edge_anon_limiter_does_not_trust_junk_auth_header_presence() -> None:
    src = _read("functions/anon_rate_limit_edge.ts")
    assert "function looksLikeApiKey" in src
    assert "/^(jc|am|sk)_[A-Za-z0-9_-]{24,}$/" in src
    assert "if (match && looksLikeApiKey(match[1])) return false;" in src
    assert "if (looksLikeApiKey(apiKey)) return false;" in src
    assert "apiKey.trim().length > 0" not in src


def test_edge_anon_limiter_ipv4_bucket_matches_origin_exact_ip() -> None:
    src = _read("functions/anon_rate_limit_edge.ts")
    assert "Exact IPv4, /64 for IPv6" in src
    assert "return trimmed;" in src
    assert '.slice(0, 3).join(".")' not in src
    assert "IPv4 → /24" not in src


def test_origin_anon_limiter_does_not_trust_bare_x_forwarded_for() -> None:
    src = _read("src/jpintel_mcp/api/anon_limit.py")
    start = src.index("def _client_ip(request: Request) -> str:")
    end = src.index("\ndef _normalize_ip_to_prefix", start)
    body = src[start:end]
    assert 'request.headers.get("fly-client-ip")' in body
    assert 'request.headers.get("x-forwarded-for")' not in body
    _assert_before(body, "fly_ip =", "if request.client:")


# ---------------------------------------------------------------------------
# A6: Edge Rate Limit Reliability — documented residual P1 + alignment guards
# ---------------------------------------------------------------------------


def test_edge_anon_limiter_documents_kv_non_atomic_residual_p1() -> None:
    """The edge limiter MUST carry a top-of-file note that Workers KV
    read-modify-write is not atomic and that origin remains authoritative.

    A6 calls this out as an explicit residual P1: until a Durable Object
    or origin-only authoritative limiter exists, the edge cannot give
    strict concurrent-burst guarantees. The doc block is the contract that
    keeps future contributors from "fixing" the apparent race by trusting
    the edge KV count.
    """
    src = _read("functions/anon_rate_limit_edge.ts")
    assert "RESIDUAL P1" in src, "missing RESIDUAL P1 banner in edge doc block"
    assert "Workers KV read-modify-write is NOT atomic" in src, (
        "edge doc must call out the KV RMW non-atomic property"
    )
    assert "Durable Object" in src, "edge doc must surface the DO upgrade path as the right answer"
    assert "Origin anon_limit.py remains" in src, (
        "edge doc must reaffirm origin authority on success grant"
    )
    assert "advisory" in src.lower(), (
        "edge doc must mark the KV count as advisory rather than authoritative"
    )


def test_edge_anon_limiter_keeps_origin_alignment_constants() -> None:
    """Edge IP bucket semantics MUST match origin /32 v4 + /64 v6.

    A divergence would mean the same anonymous caller burns a different
    bucket at the edge vs origin, producing impossible-to-reproduce 429s
    or impossible-to-detect bypasses. This guard locks the alignment in
    place so a refactor on either side trips a static test before deploy.
    """
    edge = _read("functions/anon_rate_limit_edge.ts")
    # Edge does IPv4 exact (returns the trimmed address) and IPv6 /64.
    assert "Exact IPv4, /64 for IPv6" in edge
    # R2 P2 hardening (2026-05-13): the naive `.slice(0, 4)` join produced
    # non-canonical text that drifted from the Python `IPv6Network(addr, 64)`
    # output for `::`-compressed and short-form inputs. Edge and origin now
    # share an RFC 5952 canonicaliser (`canonicalIpv6Slash64` / `canonical_ipv6_64`).
    assert "canonicalIpv6Slash64" in edge, (
        "edge must call canonicalIpv6Slash64 so the /64 text form matches origin"
    )
    assert '.slice(0, 4).join(":")' not in edge, (
        "edge must NOT use the legacy naive split — it drifts on `::` inputs"
    )

    origin = _read("src/jpintel_mcp/api/anon_limit.py")
    # Origin path: IPv4 -> full /32, IPv6 -> /64.
    assert "IPv4 -> full /32" in origin
    assert "first 64 bits (/64)" in origin
    assert "canonical_ipv6_64" in origin, (
        "origin must expose canonical_ipv6_64 helper as the edge contract anchor"
    )


def test_edge_anon_limiter_fails_open_on_kv_read_blip_but_not_on_count_decision() -> None:
    """Cloudflare KV blips on read must not 5xx the site, but they MUST
    NOT be treated as `count = 0` either — origin is the safety net.

    Pattern: a try/catch around `kv.get` returns `context.next()` so the
    request reaches origin where `anon_limit.py` does the authoritative
    count. The same pattern around `kv.put` swallows errors silently —
    the worst case is one extra request slipping through, which is the
    documented residual P1.
    """
    src = _read("functions/anon_rate_limit_edge.ts")
    # Fail open on read so origin still enforces.
    assert "// KV read failure" in src
    assert "fail open" in src.lower()
    # Best-effort write — never block.
    assert "Best-effort" in src
    # Origin remains the safety net (authoritative grant).
    assert "Origin anon_limit.py remains" in src


def test_origin_anon_limiter_documents_failure_mode_separation() -> None:
    """The origin limiter must distinguish backend outage from real
    over-quota in its 429 envelope so dashboards + clients can react
    differently (retry-on-outage vs upgrade-on-real-cap)."""
    src = _read("src/jpintel_mcp/api/anon_limit.py")
    assert '"rate_limit_unavailable"' in src
    assert '"rate_limit_exceeded"' in src
    # Both share the same upgrade URL so existing clients keep working.
    assert "UPGRADE_URL_FROM_429" in src


# ---------------------------------------------------------------------------
# R2 P1-3: missing-IP must NOT pass through (edge + origin)
# ---------------------------------------------------------------------------


def test_edge_rejects_missing_cf_connecting_ip_with_503() -> None:
    """When `CF-Connecting-IP` is absent (or blank), the edge MUST refuse
    with 503 `edge_ip_unavailable` instead of passing through to origin.

    Pass-through with no IP either bypasses edge burst-shedding entirely
    or lets an attacker who stripped the header skip counting toward
    their /32 bucket — both inflate the anon quota silently. 503 makes
    the failure visible. This guard locks the new behaviour in place so
    a refactor cannot regress to the old `return context.next()` path.
    """
    src = _read("functions/anon_rate_limit_edge.ts")
    # Top-of-file doc must surface the rejection contract.
    assert "503" in src
    assert "edge_ip_unavailable" in src
    # Old pass-through path on the "unknown" branch must be gone.
    assert 'if (ip === "unknown") return context.next();' not in src
    # New rejection must explicitly check for the absent header BEFORE
    # normalising — guards against silently buying empty-string IPs.
    assert 'context.request.headers.get("CF-Connecting-IP")' in src
    assert "X-Edge-Rate-Limit" in src
    assert "anon-prefilter-ip-missing" in src
    # Status code is 503, not 429 — we cannot make a quota decision
    # without an IP, so don't pretend the caller is over quota.
    assert "status: 503" in src


def test_origin_rejects_direct_to_fly_traffic_when_fly_client_ip_absent() -> None:
    """Origin MUST raise 503 when `Fly-Client-IP` is absent AND
    `request.client.host` is a loopback / RFC1918 / link-local literal.

    The Fly proxy always sets Fly-Client-IP; its absence with a private
    peer means the request bypassed the Fly proxy entirely. Without a
    trusted IP we cannot bucket the caller against
    `anon_rate_limit.call_count`, and falling back to "unknown" as a
    shared bucket would share one quota across every spoofed caller.
    """
    src = _read("src/jpintel_mcp/api/anon_limit.py")
    assert "_is_loopback_or_internal" in src
    assert "_raise_edge_ip_unavailable" in src
    assert "edge_ip_unavailable" in src
    assert "HTTP_503_SERVICE_UNAVAILABLE" in src
    # Header marker so dashboards can attribute the 503 to the direct-
    # to-Fly path specifically (separate from real outage).
    assert "origin-direct-to-fly-rejected" in src
    # The check must run inside _client_ip so every caller is gated.
    start = src.index("def _client_ip(request: Request) -> str:")
    end = src.index("\ndef _normalize_ip_to_prefix", start)
    body = src[start:end]
    assert "_is_loopback_or_internal" in body
    assert "_raise_edge_ip_unavailable" in body
