"""MCP-side INV-22 (景表法) response sanitizer regression suite.

Covers the chokepoint at ``jpintel_mcp.mcp.server._envelope_merge``:
every ``@_with_mcp_telemetry``-decorated tool funnels through it, so
sanitizing there catches all 66 MCP tools at once. REST has its own
``ResponseSanitizerMiddleware`` — these tests target the stdio path.

Three cases:
    1. forbidden 「必ず採択」 → strip + ``_sanitized=1`` + hit recorded
    2. legitimate 「信用保証協会」「保証料」 → preserved untouched
    3. caller-provided ``_sanitized=1`` → regex skipped (no double-pass)
"""

from jpintel_mcp.mcp.server import _envelope_merge


def test_inv22_forbidden_phrase_sanitized() -> None:
    """A tool result containing 「必ず採択」 must be replaced before return."""
    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result={"results": [{"hint": "この補助金は必ず採択されます。"}]},
        kwargs={"q": "ものづくり"},
        latency_ms=1.0,
    )
    blob = str(out)
    assert "必ず採択" not in blob
    assert "対象となる場合があります" in blob
    assert out.get("_sanitized") == 1
    assert "must-grant" in out["_sanitize_hits"]


def test_legitimate_shinyou_hosho_preserved() -> None:
    """信用保証協会 / 保証料 are everyday financial terms — never strip."""
    out = _envelope_merge(
        tool_name="search_loans_am",
        result={
            "results": [
                {"name": "信用保証協会の保証付き融資", "desc": "保証料あり"},
            ],
        },
        kwargs={"q": "信用保証"},
        latency_ms=1.0,
    )
    blob = str(out)
    assert "信用保証協会" in blob
    assert "保証料" in blob
    # Negative case: no INV-22 hit, no sentinel flag should be set.
    assert not out.get("_sanitized")
    assert "_sanitize_hits" not in out


def test_no_double_sanitize() -> None:
    """If the caller already sanitized (``_sanitized=1``), skip the regex."""
    out = _envelope_merge(
        tool_name="x",
        result={
            "results": [{"hint": "必ず採択される"}],
            "_sanitized": 1,
        },
        kwargs={},
        latency_ms=1.0,
    )
    # Untouched: the forbidden phrase must remain because we trust the
    # upstream sanitizer. This guards against re-encoding cost / hit-list
    # duplication when REST wraps an MCP tool.
    assert "必ず採択" in str(out)
