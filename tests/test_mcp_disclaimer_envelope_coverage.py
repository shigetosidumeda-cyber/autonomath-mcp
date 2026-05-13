"""§52 / §47条の2 / §72 / §1 disclaimer envelope coverage CI guard.

Background
----------
Wave 22 + Wave 30 (manifests v0.3.1, 2026-04-29) marked 11 sensitive MCP
tools that MUST surface a ``_disclaimer`` envelope on every response to
maintain the 業法 fence:

  - 税理士法 §52 (税務代理)
  - 公認会計士法 §47条の2 (監査調書保存)
  - 弁護士法 §72 (法律事務)
  - 行政書士法 §1 (申請書面作成)

A regression where any one of these stops emitting ``_disclaimer`` would
silently strip the business-law fence — customer LLMs would relay our
output as if it were regulated advice. This test is the CI guard.

Approach
--------
1. **Anchor set** — pin the original 11 Wave 22 + Wave 30 tools so a typo
   or accidental removal trips the suite.
2. **Auto-discovery** — also parametrize across the full live
   ``SENSITIVE_TOOLS`` set so any future addition (Wave 21/22/23, R8
   post-deploy smoke wiring, etc.) is automatically covered.
3. **Minimal valid args** — use the canonical MCP server-side merge path
   (``_envelope_merge``) with an empty kwargs dict and a minimally
   shaped raw result, mirroring ``tests/test_disclaimer_envelope.py``.

No tool implementations are edited. No LLM imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure ``src/`` is on path for direct test runs (mirrors the pattern
# used by ``tests/test_disclaimer_envelope.py``).
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Lazy imports — server.py + envelope_wrapper.py are heavy to import at
# module scope when only a subset of the suite is selected.
# ---------------------------------------------------------------------------


def _import_envelope_merge():
    from jpintel_mcp.mcp.server import _envelope_merge

    return _envelope_merge


def _import_sensitive_surface():
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        SENSITIVE_TOOLS,
        build_envelope,
        disclaimer_for,
    )

    return SENSITIVE_TOOLS, build_envelope, disclaimer_for


# ---------------------------------------------------------------------------
# Anchor inventory: the original 11 sensitive tools per CLAUDE.md Wave 22 +
# Wave 30. A drift here means the disclaimer hardening regressed.
# Keep this list pinned even as new sensitive tools are added — new tools
# go into the auto-discovery surface below.
# ---------------------------------------------------------------------------

_WAVE22_WAVE30_ANCHOR: tuple[str, ...] = (
    "dd_profile_am",  # 行政書士法 §1 + 弁護士法 §72 + 社労士法 — DD scoring
    "regulatory_prep_pack",  # 行政書士法 §1 — 申請書面作成 fence
    "combined_compliance_check",  # 弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法
    "rule_engine_check",  # 公開ルール検索照合 — same 4 業法 fence
    "predict_subsidy_outcome",  # 行政書士法 §1 — 申請可否判断 fence
    "score_dd_risk",  # 弁護士法 §72 / 社労士法 — 与信・反社・労務 DD
    "intent_of",  # 4 業法 fence — intent classification
    "reason_answer",  # 4 業法 fence — 決定論 pipeline answer skeleton
    "search_tax_incentives",  # 税理士法 §52 — 税務助言 fence (Wave 30)
    "get_am_tax_rule",  # 税理士法 §52 — 単一税制措置 lookup (Wave 30)
    "list_tax_sunset_alerts",  # 税理士法 §52 — sunset_at 集計 (Wave 30)
)


def _minimal_raw_result() -> dict[str, object]:
    """Return a minimally-valid tool result for envelope merging.

    Matches the shape produced by the canonical search-style MCP tools
    (results[] + total/limit/offset). Empty kwargs + zero latency
    guarantees the envelope path is deterministic regardless of which
    sensitive tool is being tested.
    """
    return {
        "results": [{"id": "x"}],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }


def _invoke_and_extract_disclaimer(tool_name: str) -> tuple[dict, object]:
    """Invoke ``_envelope_merge`` with minimal valid args and return
    ``(merged_dict, disclaimer_value)``.

    Centralizing the invocation makes the parametrized tests below trivial
    and gives a single place to evolve the call shape if the server-side
    merge contract ever changes.
    """
    _envelope_merge = _import_envelope_merge()
    merged = _envelope_merge(
        tool_name=tool_name,
        result=_minimal_raw_result(),
        kwargs={},
        latency_ms=1.0,
    )
    assert isinstance(merged, dict), (
        f"{tool_name}: _envelope_merge dropped dict shape (got {type(merged).__name__})"
    )
    return merged, merged.get("_disclaimer")


# ---------------------------------------------------------------------------
# 1. Anchor — every Wave 22 + Wave 30 tool must surface `_disclaimer`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", _WAVE22_WAVE30_ANCHOR)
def test_wave22_wave30_anchor_tool_surfaces_disclaimer(tool_name: str) -> None:
    """The pinned 11 §52 / §47条の2 / §72 / §1 tools must each emit a
    non-empty ``_disclaimer`` envelope.

    Anchor regression = critical: an accidental removal from
    ``SENSITIVE_TOOLS`` or a typo in the disclaimer table silently strips
    the 業法 fence.
    """
    _, _, disclaimer_for = _import_sensitive_surface()

    # Direct disclaimer_for() lookup must resolve a non-None string.
    direct = disclaimer_for(tool_name)
    assert isinstance(direct, str) and len(direct) >= 20, (
        f"{tool_name}: disclaimer_for() returned {direct!r} "
        "(expected non-empty string ≥20 chars)"
    )

    # End-to-end via _envelope_merge must also surface the field.
    _, disclaimer = _invoke_and_extract_disclaimer(tool_name)
    assert isinstance(disclaimer, str), (
        f"{tool_name}: missing `_disclaimer` on merged envelope "
        "(business-law fence breach)"
    )
    assert len(disclaimer) >= 20, (
        f"{tool_name}: `_disclaimer` too short ({len(disclaimer)} chars) — "
        "fence text must be substantive enough to deter relay as advice"
    )


def test_anchor_set_is_subset_of_live_sensitive_tools() -> None:
    """The pinned 11 anchor names must still all appear in
    ``SENSITIVE_TOOLS`` — if not, a refactor silently removed one of them.
    """
    sensitive, _, _ = _import_sensitive_surface()
    missing = set(_WAVE22_WAVE30_ANCHOR) - set(sensitive)
    assert not missing, (
        f"Wave 22 + Wave 30 anchor tools dropped from SENSITIVE_TOOLS: "
        f"{sorted(missing)}. This silently strips the §52 / §47条の2 / "
        "§72 / §1 fence on those surfaces."
    )


def test_anchor_set_size_is_eleven() -> None:
    """The anchor set is exactly the 11 tools described in CLAUDE.md
    Wave 22 + Wave 30 §52 disclaimer hardening. A different number means
    the anchor drifted and needs an explicit decision to extend it.
    """
    assert len(_WAVE22_WAVE30_ANCHOR) == 11, (
        f"Anchor drifted from 11 to {len(_WAVE22_WAVE30_ANCHOR)}; "
        "if this is intentional, update CLAUDE.md and the docstring "
        "before adjusting the count."
    )
    assert len(set(_WAVE22_WAVE30_ANCHOR)) == 11, "Anchor has duplicates"


# ---------------------------------------------------------------------------
# 2. Auto-discovery — every CURRENT sensitive tool must also emit
# ``_disclaimer``. This scales to future Wave additions without code edits.
# ---------------------------------------------------------------------------


def _all_sensitive_tools() -> list[str]:
    """Return the live SENSITIVE_TOOLS set, sorted for deterministic
    test-id ordering. Imported lazily so pytest collection stays cheap.
    """
    sensitive, _, _ = _import_sensitive_surface()
    return sorted(sensitive)


@pytest.mark.parametrize("tool_name", _all_sensitive_tools())
def test_every_sensitive_tool_surfaces_disclaimer(tool_name: str) -> None:
    """Auto-discovery guard.

    Any tool registered in ``SENSITIVE_TOOLS`` must:
      (a) Have a ``disclaimer_for(name)`` -> non-empty string.
      (b) Pass that string through ``_envelope_merge`` to a ``_disclaimer``
          key on the merged envelope.

    Adding a new sensitive tool only requires appending its name to the
    SENSITIVE_TOOLS frozenset + populating ``_DISCLAIMER_STANDARD`` /
    ``_DISCLAIMER_MINIMAL`` — no test edit needed. The parametrization
    here picks it up on the next run.
    """
    _, _, disclaimer_for = _import_sensitive_surface()

    direct = disclaimer_for(tool_name)
    assert isinstance(direct, str) and direct.strip(), (
        f"{tool_name}: disclaimer_for() returned {direct!r}; "
        "every SENSITIVE_TOOLS entry must have a populated disclaimer "
        "in _DISCLAIMER_STANDARD."
    )
    assert len(direct) >= 20, (
        f"{tool_name}: disclaimer_for() string too short ({len(direct)} chars). "
        "Substantive fence text required so customer LLMs honor it."
    )

    merged, disclaimer = _invoke_and_extract_disclaimer(tool_name)
    assert isinstance(disclaimer, str), (
        f"{tool_name}: `_disclaimer` missing on merged envelope. "
        f"Keys present: {sorted(merged.keys())}"
    )
    assert disclaimer.strip(), f"{tool_name}: `_disclaimer` is empty/whitespace"
    assert len(disclaimer) >= 20, (
        f"{tool_name}: `_disclaimer` too short ({len(disclaimer)} chars) "
        "after envelope merge"
    )


def test_sensitive_inventory_has_at_least_eleven_tools() -> None:
    """The live sensitive inventory must contain ≥ 11 tools.

    11 is the Wave 22 + Wave 30 baseline; later waves grew it (Wave 21
    composition, Wave 22 composition, Wave 23 industry packs, Vector kNN,
    R8 post-deploy smoke, etc.). A drop below 11 means the fence shrank.
    """
    sensitive = _all_sensitive_tools()
    assert len(sensitive) >= 11, (
        f"SENSITIVE_TOOLS shrank to {len(sensitive)} entries "
        f"({sensitive}); minimum is 11 (Wave 22 + Wave 30 baseline)."
    )


# ---------------------------------------------------------------------------
# 3. build_envelope direct path — independent verification that the
# canonical envelope builder also surfaces ``_disclaimer`` for the anchor
# set. Belt-and-braces: ``_envelope_merge`` and ``build_envelope`` are two
# different code paths that both must carry the fence.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", _WAVE22_WAVE30_ANCHOR)
def test_build_envelope_direct_path_surfaces_disclaimer(tool_name: str) -> None:
    """``build_envelope`` (called by ``with_envelope`` decorator inside
    the tool body) must also surface ``_disclaimer`` independently of the
    server-side ``_envelope_merge`` post-processor.

    This guards against a regression where the disclaimer wiring lives
    in only one of the two code paths.
    """
    _, build_envelope, _ = _import_sensitive_surface()
    env = build_envelope(
        tool_name=tool_name,
        results=[{"id": "x"}],
        disclaimer_level="standard",
    )
    assert isinstance(env, dict)
    disclaimer = env.get("_disclaimer")
    assert isinstance(disclaimer, str), (
        f"{tool_name}: build_envelope() omitted `_disclaimer` — "
        "tool-body decorator path lost the fence."
    )
    assert len(disclaimer) >= 20, (
        f"{tool_name}: build_envelope() `_disclaimer` too short "
        f"({len(disclaimer)} chars)"
    )
