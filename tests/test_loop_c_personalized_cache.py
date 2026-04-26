"""Tests for loop_c_personalized_cache.

Covers the launch-v1 happy path: synthesised query_log_v2 rows feed the
loop, which extracts per-customer (tool, params_hash) histograms, emits
isolated cache-key proposals, and writes a JSON report.

Load-bearing assertion: customer-specific patterns produce isolated
key prefixes (`pcc:{api_key_hash[:8]}:...`) so customer A's cache hits
cannot collide with customer B's — the INV-21 PII boundary plus the
cross-customer leakage boundary both depend on this isolation.
"""

from __future__ import annotations

from pathlib import Path

from jpintel_mcp.self_improve import loop_c_personalized_cache as loop_c


def _fake_query_log_rows() -> list[dict[str, object]]:
    """Synthetic query_log_v2 rows.

    Customer 'ak_alpha_001' (tax shop) repeats `search_tax_incentives`
    with the same params_shape 4 times — that's a real pattern.
    Customer 'ak_beta_777' (loan brokerage) repeats `search_loans` 3
    times with one params_shape and 1 time with another — only the
    repeated shape is a pattern.
    Customer 'ak_gamma_xyz' has 2 distinct one-off queries — both below
    THRESHOLD_PER_CUSTOMER, no proposals expected.
    Anonymous-tier rows (api_key_hash empty) must be dropped entirely.
    """
    return [
        # ak_alpha_001 — clear pattern.
        {
            "api_key_hash": "ak_alpha_001",
            "tool": "search_tax_incentives",
            "params_shape": {"category": "GX", "tier": "S"},
        },
        {
            "api_key_hash": "ak_alpha_001",
            "tool": "search_tax_incentives",
            "params_shape": {"category": "GX", "tier": "S"},
        },
        {
            "api_key_hash": "ak_alpha_001",
            "tool": "search_tax_incentives",
            "params_shape": {"category": "GX", "tier": "S"},
        },
        {
            "api_key_hash": "ak_alpha_001",
            "tool": "search_tax_incentives",
            "params_shape": {"category": "GX", "tier": "S"},
        },
        # ak_beta_777 — pattern + 1 stray.
        {
            "api_key_hash": "ak_beta_777",
            "tool": "search_loans",
            "params_shape": {"region": "13"},
        },
        {
            "api_key_hash": "ak_beta_777",
            "tool": "search_loans",
            "params_shape": {"region": "13"},
        },
        {
            "api_key_hash": "ak_beta_777",
            "tool": "search_loans",
            "params_shape": {"region": "13"},
        },
        {
            "api_key_hash": "ak_beta_777",
            "tool": "search_loans",
            "params_shape": {"region": "27"},
        },
        # ak_gamma_xyz — sub-threshold, no proposals.
        {
            "api_key_hash": "ak_gamma_xyz",
            "tool": "get_law_article",
            "params_shape": {"law_id": "X1"},
        },
        {
            "api_key_hash": "ak_gamma_xyz",
            "tool": "get_law_article",
            "params_shape": {"law_id": "X2"},
        },
        # Anonymous tier — must be dropped (no api_key_hash).
        {
            "api_key_hash": "",
            "tool": "search_programs",
            "params_shape": {"q": "<redacted>"},
        },
    ]


def test_loop_c_isolates_customer_specific_patterns(tmp_path: Path):
    """customer-specific pattern -> key prefix isolation (INV-21 boundary).

    Two customers with overlapping tool labels must end up with disjoint
    cache key prefixes. The 8-char api_key_hash trim is the isolation
    boundary; without it, a shared `pcc:search_loans:<hash>` key would
    leak Customer A's cached payload into Customer B's response.
    """
    out_path = tmp_path / "personalized_cache_report.json"

    result = loop_c.run(
        dry_run=False,
        query_log_rows=_fake_query_log_rows(),
        out_path=out_path,
    )

    # Standard scaffold shape.
    assert result["loop"] == "loop_c_personalized_cache"
    assert result["scanned"] == 11  # all rows counted, even drops + anon
    # ak_alpha_001 (1 pattern) + ak_beta_777 (1 pattern) = 2 proposals.
    # ak_gamma_xyz (sub-threshold) and anonymous row contribute nothing.
    assert result["actions_proposed"] == 2
    assert result["actions_executed"] == 1

    # Inspect the proposals via helpers — load-bearing isolation check.
    by_customer = loop_c.extract_patterns(_fake_query_log_rows())
    assert set(by_customer.keys()) == {"ak_alpha_001", "ak_beta_777", "ak_gamma_xyz"}
    assert "" not in by_customer  # anonymous-tier excluded

    proposals = loop_c.build_cache_proposals(by_customer)
    assert len(proposals) == 2

    # Both proposals must carry the per-customer trim prefix — never the
    # bare tool label as a top-level cache namespace.
    for p in proposals:
        assert p["cache_key"].startswith("pcc:")
        assert p["ttl_s"] == loop_c.PERSONALIZED_CACHE_TTL_S
        assert p["hits"] >= loop_c.THRESHOLD_PER_CUSTOMER

    # Trim prefixes are disjoint -> cache keys cannot collide across
    # customers. This is the INV-21 + cross-customer-isolation contract.
    trims = {p["api_key_hash_trim"] for p in proposals}
    assert trims == {"ak_alpha", "ak_beta_"}  # 8-char trims, disjoint
    keys = {p["cache_key"] for p in proposals}
    assert len(keys) == 2  # no collisions

    alpha_keys = [p["cache_key"] for p in proposals if p["api_key_hash_trim"] == "ak_alpha"]
    beta_keys = [p["cache_key"] for p in proposals if p["api_key_hash_trim"] == "ak_beta_"]
    assert all(k.startswith("pcc:ak_alpha:search_tax_incentives:") for k in alpha_keys)
    assert all(k.startswith("pcc:ak_beta_:search_loans:") for k in beta_keys)

    # Report JSON exists and carries the disjoint key prefixes on disk.
    body = out_path.read_text(encoding="utf-8")
    assert "pcc:ak_alpha:search_tax_incentives:" in body
    assert "pcc:ak_beta_:search_loans:" in body
    # Sub-threshold customer must not appear as a proposal key, but may
    # appear in the per-customer summary (utilization=0 row is fine).
    assert "pcc:ak_gamma" not in body
    # PII boundary: raw api_key_hash full string never appears trimmed
    # past 8 chars in any cache_key (only in the summary `api_key_hash_trim`
    # which is itself the 8-char trim).
    assert "ak_alpha_001" not in body  # full hash never persisted
    assert "ak_beta_777" not in body
