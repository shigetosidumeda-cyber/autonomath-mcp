"""Tests for the Agent Entry SOT (root ``AGENTS.md`` + vendor shims).

Backs Harness H3 — Agent Entry SOT migration (2026-05-17). The shim files
(``CLAUDE.md`` / ``.agent.md`` / ``.cursorrules`` / ``.windsurfrules`` /
``.mcp.json``) each defer to the root ``AGENTS.md``. Live counts (MCP tool
count, REST route count, OpenAPI path count, program counts) live in
``scripts/distribution_manifest.yml`` and the live runtime — never
hardcoded inside agent entry files.

Test plan
---------

1. ``AGENTS.md`` exists at repo root and contains the required canonical
   sections (project identity / hard constraints / architecture pointer /
   live counts / commands / what NOT to do / memory pointer / quality
   gates).
2. No agent entry file (``AGENTS.md`` / ``CLAUDE.md`` / ``.agent.md`` /
   ``.cursorrules`` / ``.windsurfrules`` / ``.mcp.json``) contains a
   hardcoded volatile count. The set of stale counts that previously drifted
   across these files is enumerated below.
3. Every vendor shim file points at ``AGENTS.md`` so a new coding agent has
   exactly one canonical entry to read.
4. ``CLAUDE.md`` has shrunk to a Claude-specific shim (≤ 200 lines).
   ``AGENTS.md`` itself fits in ≤ 250 lines.

These assertions intentionally do **not** auto-fix anything. They fail
loudly when a future edit reintroduces drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_ENTRY_FILES: tuple[Path, ...] = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / ".agent.md",
    REPO_ROOT / ".cursorrules",
    REPO_ROOT / ".windsurfrules",
    REPO_ROOT / ".mcp.json",
)

# Volatile counts that drifted across agent entry files in 2026-04 .. 2026-05.
# These are historical-state markers — NONE of them should appear as a live
# count inside an agent entry file. They are allowed inside *historical*
# documents under ``docs/_internal/historical/`` and inside
# ``scripts/distribution_manifest.yml`` (which is itself the SOT for the
# current value).
STALE_VOLATILE_COUNTS: tuple[str, ...] = (
    "139",  # old tool count
    "146",  # old runtime tool count
    "151",  # old tool count
    "155",  # old tool count
    "165",  # old tool count
    "169",  # old tool count
    "179",  # old tool count
    "184",  # historical-only — current canonical lives in distribution_manifest.yml
    "186",  # stale EXPECTED_OPENAPI_PATH_COUNT
    "219",  # historical openapi path count
    "220",  # historical openapi path count
    "221",  # historical runtime tool count
    "262",  # historical runtime tool / route count
    "306",  # historical openapi path count
    "307",  # historical openapi path count
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agents_md_exists_with_required_sections() -> None:
    """Root ``AGENTS.md`` exists and has the canonical SOT sections."""
    agents_md = REPO_ROOT / "AGENTS.md"
    assert agents_md.is_file(), f"AGENTS.md missing at {agents_md}"

    body = _read(agents_md)

    # Required canonical sections (substring match — heading text is stable).
    required_sections = (
        "Project identity",
        "Hard constraints",
        "Architecture pointer",
        "Live counts",
        "Key commands",
        "Quality gates",
        "What NOT to do",
        "Memory pointer",
    )
    missing = [s for s in required_sections if s not in body]
    assert not missing, (
        f"AGENTS.md missing required SOT sections: {missing}. "
        "Each section is part of the H3 Agent Entry SOT contract."
    )

    # Required project identity invariants.
    required_identity = (
        "Bookyou株式会社",
        "T8010001213708",
        "jpcite",
        "autonomath-mcp",
        "@bookyou/jpcite",
        "¥3",
    )
    missing_identity = [m for m in required_identity if m not in body]
    assert not missing_identity, (
        f"AGENTS.md missing project-identity invariants: {missing_identity}"
    )

    # AGENTS.md should point at the live-count sources, not hardcode them.
    assert "scripts/distribution_manifest.yml" in body, (
        "AGENTS.md must point at scripts/distribution_manifest.yml for canonical published counts."
    )
    assert "len(await mcp.list_tools())" in body, (
        "AGENTS.md must point at len(await mcp.list_tools()) for the runtime MCP tool count."
    )


def test_agents_md_length_budget() -> None:
    """``AGENTS.md`` fits within the ~250-line budget (H3 target ~200)."""
    agents_md = REPO_ROOT / "AGENTS.md"
    line_count = agents_md.read_text(encoding="utf-8").count("\n") + 1
    assert line_count <= 250, (
        f"AGENTS.md is {line_count} lines, exceeds the 250-line budget. "
        "Push deep detail into docs/_internal/ instead."
    )


def test_claude_md_is_claude_shim_within_budget() -> None:
    """``CLAUDE.md`` shrunk to Claude-specific shim (≤ 200 lines)."""
    claude_md = REPO_ROOT / "CLAUDE.md"
    assert claude_md.is_file(), "CLAUDE.md missing"
    body = _read(claude_md)
    line_count = body.count("\n") + 1
    assert line_count <= 200, (
        f"CLAUDE.md is {line_count} lines; H3 shim target is ≤ 200. "
        "Move historical content under docs/_internal/historical/."
    )
    # Must explicitly point at AGENTS.md.
    assert "AGENTS.md" in body, "CLAUDE.md must point at AGENTS.md as the canonical SOT."


def test_shim_files_point_at_agents_md() -> None:
    """Every vendor shim must defer to the root ``AGENTS.md``."""
    shims = (
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / ".agent.md",
        REPO_ROOT / ".cursorrules",
        REPO_ROOT / ".windsurfrules",
        REPO_ROOT / ".mcp.json",
    )
    missing_pointer: list[str] = []
    for shim in shims:
        if not shim.is_file():
            missing_pointer.append(f"{shim.name} (missing)")
            continue
        if "AGENTS.md" not in _read(shim):
            missing_pointer.append(shim.name)
    assert not missing_pointer, f"Vendor shim files missing AGENTS.md pointer: {missing_pointer}"


@pytest.mark.parametrize("entry_path", AGENT_ENTRY_FILES, ids=lambda p: p.name)
def test_no_hardcoded_volatile_counts_in_entry_files(entry_path: Path) -> None:
    """No agent entry file may hardcode a volatile count.

    Volatile counts (MCP tool count, REST route count, OpenAPI path count,
    program counts) live in ``scripts/distribution_manifest.yml`` and in
    the live runtime. Hardcoding them in agent entry files caused the
    2026-04..2026-05 drift between 139 / 151 / 155 / 169 / 179 / 184 etc.
    """
    if not entry_path.is_file():
        pytest.skip(f"{entry_path.name} not present")
    body = _read(entry_path)

    found_hardcoded: list[str] = []
    for stale_count in STALE_VOLATILE_COUNTS:
        # Word-boundary match so "184" matches "184 tools" but not "1846".
        pattern = re.compile(rf"\b{re.escape(stale_count)}\b")
        if pattern.search(body):
            found_hardcoded.append(stale_count)

    assert not found_hardcoded, (
        f"{entry_path.name} contains hardcoded volatile counts "
        f"{found_hardcoded}. Replace with a pointer to "
        "`scripts/distribution_manifest.yml` or `len(await mcp.list_tools())`."
    )


def test_historical_log_is_archived_out_of_root() -> None:
    """Wave 1..150 tick log lives in historical archive, not root."""
    archive = (
        REPO_ROOT
        / "docs"
        / "_internal"
        / "historical"
        / "CLAUDE_WAVE_HISTORY_2026_05_06_2026_05_16.md"
    )
    assert archive.is_file(), "Wave/tick history archive missing — H3 migration is incomplete."

    # Root CLAUDE.md must not still carry the long tick-history tail.
    claude_md_body = _read(REPO_ROOT / "CLAUDE.md")
    # The "tick NN — live_aws=false" pattern repeated 89 times in the old
    # root CLAUDE.md. None should remain.
    assert "live_aws=false (53 tick" not in claude_md_body
    assert "tick 150" not in claude_md_body
