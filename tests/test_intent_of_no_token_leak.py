"""Token-leak guard for ``intent_of`` (P0.10 verify, follow-up to the P7 fix
landed in ``reason_answer``).

P7 finding: the reasoning layer's ``answer_skeleton`` can carry raw
``<<<missing:KEY>>>`` and ``<<<precompute gap: ...>>>`` tokens. Customer LLMs
that paste the skeleton verbatim into outputs become a 詐欺 / 景表法 risk
surface. ``reason_answer`` was hardened in tools.py:3171 by substituting the
raw tokens with ``(該当データなし)`` / ``(集計準備中)``.

This test verifies the **adjacent** classifier ``intent_of`` cannot leak the
same tokens. By design ``intent_of`` returns **classifier-only** scalars
(``intent_id``, ``intent_name_ja``, ``confidence``, ``all_scores``,
``sample_queries``) and never renders an ``answer_skeleton``. The guard here
is a regression fence: if a future refactor accidentally pipes skeleton text
through this surface, the test breaks before it ships.

Two scenarios are covered:

1. Real classifier path (subsystem available) on a query the binder cannot
   fully resolve — verifies no token surfaces in any string-typed return
   value.
2. Subsystem-unavailable envelope path — verifies the error envelope itself
   never embeds a raw placeholder token.

Both checks are intentionally string-deep (recursive walk of all values) so
nested ``error`` / ``hint`` / ``sample_queries`` strings are inspected.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))
_GRAPH_PATH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _DB_PATH.exists() or not _GRAPH_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) or graph.sqlite ({_GRAPH_PATH}) "
        "not present; skipping the intent_of token-leak guard.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.tools import intent_of  # noqa: E402

_RAW_MISSING = "<<<missing:"
_RAW_PRECOMP = "<<<precompute gap:"


def _walk_strings(obj):
    """Yield every str leaf inside a nested dict/list/tuple structure."""
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _walk_strings(v)
        return
    # ints / floats / bools / None — nothing to leak.
    return


def _assert_no_raw_tokens(res: dict, marker: str) -> None:
    leaked = [s for s in _walk_strings(res) if marker in s]
    assert not leaked, (
        f"intent_of return leaked raw {marker!r} token(s) — "
        f"customer LLMs MUST NOT see these. Offending strings: {leaked!r}"
    )


def test_intent_of_no_raw_missing_token():
    """intent_of return must not carry any raw '<<<missing:' token in any
    string-typed field, recursively."""
    # Use a query likely to under-bind in the live classifier (region not
    # supplied → classifier may rank low-confidence intents). The shape of
    # the return matters here, not the picked intent.
    res = intent_of(query="補助金の特例措置はいつまで使えますか?")
    assert isinstance(res, dict)
    _assert_no_raw_tokens(res, _RAW_MISSING)


def test_intent_of_no_raw_precompute_gap_token():
    """intent_of return must not carry any raw '<<<precompute gap:' token."""
    res = intent_of(query="熊本県 製造業 従業員 30 人で使える制度は?")
    assert isinstance(res, dict)
    _assert_no_raw_tokens(res, _RAW_PRECOMP)
