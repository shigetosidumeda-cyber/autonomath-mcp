"""Tests for loop_g_invariant_expansion.

Covers the launch-v1 happy path: a synthesized sanitizer-hit log feeds
the loop, which clusters by pattern_id and writes a proposals YAML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jpintel_mcp.self_improve import loop_g_invariant_expansion as loop_g

if TYPE_CHECKING:
    from pathlib import Path


def _fake_log_lines() -> list[str]:
    """Return a synthetic log capturing both REST + MCP sanitizer hits.

    Pattern frequencies:
        must-grant       -> 6  (high — REST x4, MCP x2)
        absolute-grant   -> 4  (medium — REST x4)
        warrant-self     -> 2  (below noise floor — should be dropped)
    Plus one unrelated line that must be ignored.
    """
    return [
        # REST hits — std `response_sanitized path=...` shape
        "2026-04-25 09:00:00 WARNING jpintel.sanitizer response_sanitized path=/v1/programs/search status=200 hits=must-grant,absolute-grant",
        "2026-04-25 09:01:00 WARNING jpintel.sanitizer response_sanitized path=/v1/programs/search status=200 hits=must-grant",
        "2026-04-25 09:02:00 WARNING jpintel.sanitizer response_sanitized path=/v1/programs/search status=200 hits=must-grant,absolute-grant",
        "2026-04-25 09:03:00 WARNING jpintel.sanitizer response_sanitized path=/v1/loans/search status=200 hits=absolute-grant",
        "2026-04-25 09:04:00 WARNING jpintel.sanitizer response_sanitized path=/v1/loans/search status=200 hits=absolute-grant,must-grant",
        # MCP hits — `mcp_response_sanitized tool=...` shape
        "2026-04-25 09:05:00 WARNING jpintel.sanitizer mcp_response_sanitized tool=search_programs hits=must-grant",
        "2026-04-25 09:06:00 WARNING jpintel.sanitizer mcp_response_sanitized tool=search_programs hits=must-grant",
        # warrant-self -> only 2 hits, should be dropped (below medium floor)
        "2026-04-25 09:07:00 WARNING jpintel.sanitizer response_sanitized path=/v1/loans/search status=200 hits=warrant-self",
        "2026-04-25 09:08:00 WARNING jpintel.sanitizer response_sanitized path=/v1/loans/search status=200 hits=warrant-self",
        # Unrelated line must be ignored
        "2026-04-25 09:09:00 INFO jpintel.api request_completed path=/healthz status=200",
    ]


def test_loop_g_proposes_candidates_from_sanitizer_hits(tmp_path: Path):
    log_path = tmp_path / "sanitizer_hits.log"
    log_path.write_text("\n".join(_fake_log_lines()) + "\n", encoding="utf-8")
    out_path = tmp_path / "invariants_proposed.yaml"

    # Real run (dry_run=False) so we exercise the YAML write path too.
    result = loop_g.run(dry_run=False, log_path=log_path, out_path=out_path)

    assert result["loop"] == "loop_g_invariant_expansion"
    assert result["scanned"] == 10  # all log lines counted
    # must-grant (6) + absolute-grant (4) qualify; warrant-self (2) drops out.
    assert result["actions_proposed"] == 2
    assert result["actions_executed"] == 1

    # Inspect the parsed proposals via the helper directly to verify ranking.
    raw = log_path.read_text(encoding="utf-8").splitlines()
    hits = loop_g.parse_sanitizer_log_lines(raw)
    proposals = loop_g.propose_invariants(hits)
    assert [p["id"] for p in proposals] == ["must-grant", "absolute-grant"]
    must = proposals[0]
    assert must["hits"] == 6
    assert must["confidence"] == "high"
    assert must["existing"] is True  # already in _AFFIRMATIVE_RULES
    # Sample targets should include both REST paths and MCP tool labels.
    assert "/v1/programs/search" in must["paths"]
    assert "search_programs" in must["paths"]

    abs_grant = proposals[1]
    assert abs_grant["hits"] == 4
    assert abs_grant["confidence"] == "medium"

    # YAML file should exist and mention the surviving pattern ids.
    body = out_path.read_text(encoding="utf-8")
    assert "must-grant" in body
    assert "absolute-grant" in body
    assert "warrant-self" not in body  # dropped — below noise floor


def test_loop_g_missing_log_returns_zeroed_scaffold(tmp_path: Path):
    """Pre-launch: log file absent -> orchestrator-friendly zero dict."""
    missing = tmp_path / "does_not_exist.log"
    out = loop_g.run(dry_run=True, log_path=missing)
    assert out == {
        "loop": "loop_g_invariant_expansion",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }
