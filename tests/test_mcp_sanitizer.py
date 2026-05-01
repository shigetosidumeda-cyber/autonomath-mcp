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

import sqlite3

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


def test_unexpected_mcp_tool_exception_is_incident_sanitized() -> None:
    """Unhandled server-tool exceptions must not leak raw internals."""
    from jpintel_mcp.mcp.server import _with_mcp_telemetry

    @_with_mcp_telemetry
    def boom() -> dict:
        raise RuntimeError(
            "OperationalError: no such table: am_secret_table at "
            "/Users/shigetoumeda/jpcite/scripts/migrations/121_secret.sql\n"
            "Traceback (most recent call last)"
        )

    out = boom()
    blob = str(out)

    assert isinstance(out, dict)
    assert out.get("status") == "error"
    assert out.get("error", {}).get("code") == "internal"
    assert "incident=" in out.get("error", {}).get("message", "")
    assert "RuntimeError" not in blob
    assert "OperationalError" not in blob
    assert "am_secret_table" not in blob
    assert "/Users/shigetoumeda" not in blob
    assert "migrations/121_secret.sql" not in blob
    assert "Traceback" not in blob


def test_autonomath_envelope_exception_is_incident_sanitized() -> None:
    """The AutonoMath envelope decorator must also sanitize raised errors."""
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import with_envelope

    @with_envelope("boom_am")
    def boom() -> dict:
        raise sqlite3.OperationalError(
            "no such table: am_tax_measure from /Users/me/autonomath.db"
        )

    out = boom()
    blob = str(out)

    assert out.get("status") == "error"
    assert out.get("error", {}).get("code") == "db_unavailable"
    assert "incident=" in out.get("error", {}).get("message", "")
    assert "OperationalError" not in blob
    assert "am_tax_measure" not in blob
    assert "/Users/me" not in blob
    assert "autonomath.db" not in blob
