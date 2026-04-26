"""Loop A hallucination_guard runtime wire regression suite.

Covers layer 3 of `jpintel_mcp.api.response_sanitizer.sanitize_response_text`,
which substring-scans every JSON str leaf against the 60-phrase YAML at
`data/hallucination_guard.yaml` via
`jpintel_mcp.self_improve.loop_a_hallucination_guard.match`.

Per FIX_OPERATOR_BLOCKERS / P1.10 audit follow-up, the wire was missing —
`match()` had zero production callers. These three cases lock in the wire
so a future refactor cannot silently re-orphan the detector.

Three cases:
    1. forbidden YAML phrase produces a `loop_a-{severity}` hit
    2. legitimate text (no phrase match) preserves the body and emits no hit
    3. AUTONOMATH_HALLUCINATION_GUARD_ENABLED=0 short-circuits the layer
"""

from __future__ import annotations

import importlib

import pytest

yaml = pytest.importorskip("yaml")


def _reload_sanitizer():
    """Re-import the sanitizer so the module-level settings reference picks
    up monkeypatched env / settings overrides between cases.
    """
    from jpintel_mcp.api import response_sanitizer
    return importlib.reload(response_sanitizer)


def test_forbidden_phrase_detected() -> None:
    """A YAML phrase verbatim in the response must yield a `loop_a-*` hit.

    Picks the first entry from the canonical YAML cache so the test stays
    in sync if seed data is regenerated. We assert presence of the prefix
    only (severity is a downstream concern, covered by the schema test).
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text
    from jpintel_mcp.self_improve.loop_a_hallucination_guard import _load

    entries = _load()
    assert entries, "hallucination_guard.yaml must seed at least 1 entry"
    phrase = entries[0]["phrase"]
    severity = entries[0]["severity"]

    text = f"質問: {phrase} という説明を受けたが本当ですか？"
    _, hits = sanitize_response_text(text)
    # The phrase itself should not be 景表法-rewritten (test stays focused
    # on layer 3) — assert the loop_a prefix appears with the right severity.
    assert f"loop_a-{severity}" in hits, (
        f"expected loop_a-{severity} hit for phrase {phrase!r}, got {hits!r}"
    )


def test_legitimate_text_preserved() -> None:
    """Unrelated copy must pass through untouched, no `loop_a-*` hit."""
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "本日は晴天なり。散歩に最適な気候です。"
    clean, hits = sanitize_response_text(text)
    assert clean == text
    assert not any(h.startswith("loop_a-") for h in hits)


def test_env_disabled_skips_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """`AUTONOMATH_HALLUCINATION_GUARD_ENABLED=0` must skip the substring scan.

    Operator one-flag rollback: if a YAML edit goes wrong in production,
    flipping the env should disable layer 3 without redeploying. We verify
    by patching `settings.hallucination_guard_enabled` (the in-process
    handle the layer reads) and confirming a known-bad phrase no longer
    flags.
    """
    from jpintel_mcp.api import response_sanitizer as rs
    from jpintel_mcp.self_improve.loop_a_hallucination_guard import _load

    entries = _load()
    assert entries
    phrase = entries[0]["phrase"]

    monkeypatch.setattr(rs.settings, "hallucination_guard_enabled", False)

    _, hits = rs.sanitize_response_text(f"参考: {phrase}")
    assert not any(h.startswith("loop_a-") for h in hits), (
        f"layer 3 should be inert when disabled, got {hits!r}"
    )
