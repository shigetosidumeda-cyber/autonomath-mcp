"""Edge TS mirror of the IPv6 /64 canonical text-form contract.

Loads the Cloudflare Pages function from ``functions/anon_rate_limit_edge.ts``
directly in Node and asserts ``canonicalIpv6Slash64`` produces the same
output as Python's ``str(IPv6Network((addr, 64), strict=False).network_address)``
for every entry in the shared fixture vector.

Pairs with ``tests/test_anon_ipv6_canonical.py``. The two tests share
``CANONICAL_VECTORS`` (same input/output pairs) so a drift on either side
trips both checks.
"""

from __future__ import annotations

import json

from tests.edge_ts_runner import run_edge_node
from tests.test_anon_ipv6_canonical import CANONICAL_VECTORS


def _run_node(script: str) -> str:
    return run_edge_node(script, timeout=20).stdout


def test_edge_canonical_ipv6_slash_64_matches_origin() -> None:
    fixture_js = json.dumps(CANONICAL_VECTORS)
    out = _run_node(
        f"""
        import assert from "node:assert/strict";
        const mod = await import("./functions/anon_rate_limit_edge.ts");
        const fixtures = {fixture_js};
        const failures = [];
        for (const [raw, expected] of fixtures) {{
          const got = mod.canonicalIpv6Slash64(raw);
          if (got !== expected) {{
            failures.push({{ raw, expected, got }});
          }}
        }}
        if (failures.length > 0) {{
          console.error(JSON.stringify(failures, null, 2));
          process.exit(1);
        }}
        console.log(JSON.stringify({{ passed: fixtures.length }}));
        """
    )
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["passed"] == len(CANONICAL_VECTORS)


def test_edge_canonical_ipv6_slash_64_rejects_garbage() -> None:
    _run_node(
        """
        import assert from "node:assert/strict";
        const { canonicalIpv6Slash64 } = await import(
          "./functions/anon_rate_limit_edge.ts"
        );
        for (const bad of ["", "not-an-ip", "::g", "1:2:3", "1:2:3:4:5:6:7:8:9", "203.0.113.5", "fe80::1%eth0"]) {
          const got = canonicalIpv6Slash64(bad);
          assert.equal(got, null, `expected null for ${bad}, got ${got}`);
        }
        """
    )


def test_edge_normaliseip_uses_canonical_form() -> None:
    """``normaliseIp`` uses the canonical /64 for IPv6 inputs."""
    fixture_js = json.dumps(CANONICAL_VECTORS)
    _run_node(
        f"""
        import assert from "node:assert/strict";
        const {{ normaliseIp }} = await import("./functions/anon_rate_limit_edge.ts");
        const fixtures = {fixture_js};
        for (const [raw, expected] of fixtures) {{
          const got = normaliseIp(raw);
          assert.equal(got, expected, `normaliseIp(${{raw}}) -> ${{got}} != ${{expected}}`);
        }}
        // IPv4 path: returns trimmed address.
        assert.equal(normaliseIp("203.0.113.5"), "203.0.113.5");
        assert.equal(normaliseIp("  203.0.113.5  "), "203.0.113.5");
        // Garbage: returns "unknown" so the edge bypasses without bucketing.
        assert.equal(normaliseIp(""), "unknown");
        assert.equal(normaliseIp("1:2:3:4:5:6:7:8:9"), "unknown");
        """
    )
