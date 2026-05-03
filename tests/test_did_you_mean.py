"""Tests for the did-you-mean suggester wired into StrictQueryMiddleware.

Covers R12 §2.1 / W2-3 D1: a typo'd query key (e.g. ``perfecture`` vs
``prefecture``) should round-trip through the 422
``unknown_query_parameter`` envelope with a machine-actionable
``did_you_mean`` hint, alongside the human-readable ``user_message``
nudge ``もしかして: perfecture → prefecture``.

What we cover:

* Single typo (``perfecture`` → ``prefecture``) lands the suggestion
  in both the structured field and the user_message hint.
* No close match -> ``did_you_mean: {}`` (empty dict, no human hint).
* Multiple typos -> all suggestions returned together.
* Pure unit coverage of :func:`suggest_query_keys` for the common cases.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _build_client() -> TestClient:
    """Fresh app per test so middleware registration is isolated."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Wire / integration
# ---------------------------------------------------------------------------


def test_typo_perfecture_suggests_prefecture(seeded_db):
    """`?perfecture=東京` must echo `did_you_mean: {perfecture: prefecture}`."""
    c = _build_client()
    r = c.get("/v1/programs/search?perfecture=東京")
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "unknown_query_parameter"
    assert err["unknown"] == ["perfecture"]
    # Structured machine-readable field.
    assert err["did_you_mean"] == {"perfecture": "prefecture"}
    # Plain-Japanese hint embedded in user_message.
    assert "もしかして" in err["user_message"]
    assert "perfecture → prefecture" in err["user_message"]
    # The full expected list still ships so callers without the hint
    # can still render the closed set.
    assert "prefecture" in err["expected"]


def test_no_close_match_returns_empty_did_you_mean(seeded_db):
    """A nonsense key (no close match) yields `did_you_mean: {}`."""
    c = _build_client()
    r = c.get("/v1/programs/search?xyzzyfoo=1")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["unknown"] == ["xyzzyfoo"]
    # Field present but empty — wire shape stays stable for SDKs.
    assert err["did_you_mean"] == {}
    # No human hint when nothing matched (keeps the message clean).
    assert "もしかして" not in err["user_message"]


def test_multiple_typos_all_suggested(seeded_db):
    """Every unknown key gets a per-key suggestion when one exists."""
    c = _build_client()
    r = c.get("/v1/programs/search?perfecture=x&teir=S")
    assert r.status_code == 422
    err = r.json()["error"]
    suggestions = err["did_you_mean"]
    assert suggestions.get("perfecture") == "prefecture"
    # `teir` (Levenshtein 1 from `tier`) should also resolve.
    assert suggestions.get("teir") == "tier"


# ---------------------------------------------------------------------------
# Unit-level coverage of the helper itself
# ---------------------------------------------------------------------------


def test_suggest_query_keys_basic_typo():
    from jpintel_mcp.api.middleware.did_you_mean import suggest_query_keys

    out = suggest_query_keys(["perfecture"], ["prefecture", "tier", "limit", "q"])
    assert out == {"perfecture": "prefecture"}


def test_suggest_query_keys_case_insensitive_match_canonical_echo():
    from jpintel_mcp.api.middleware.did_you_mean import suggest_query_keys

    out = suggest_query_keys(["PREFECTURE"], ["prefecture", "tier"])
    # Canonical (declared) casing is echoed back.
    assert out == {"PREFECTURE": "prefecture"}


def test_suggest_query_keys_no_match_returns_empty_dict():
    from jpintel_mcp.api.middleware.did_you_mean import suggest_query_keys

    out = suggest_query_keys(["xyzzyfoo"], ["prefecture", "tier"])
    assert out == {}


def test_suggest_query_keys_handles_empty_inputs():
    from jpintel_mcp.api.middleware.did_you_mean import suggest_query_keys

    assert suggest_query_keys([], ["prefecture"]) == {}
    assert suggest_query_keys(["perfecture"], []) == {}
    assert suggest_query_keys([], []) == {}
