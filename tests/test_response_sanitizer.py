"""Loop A hallucination_guard sanitization + header surface tests.

Covers the user-facing contract added when Loop A was wired into the
runtime response pipeline:

  1. A response body containing a high-severity YAML phrase has the
     phrase **stripped** (replaced with `[出典未確認のため削除]`) before it
     reaches the customer.
  2. The `X-Hallucination-Guard-Hits` response header carries the count
     of `loop_a-*` hits when the middleware re-emits a sanitized body.
  3. Medium-severity matches are annotated but the phrase is preserved
     (matches the operator-review-required design — corrections are
     factual claims and must not auto-substitute at runtime).
  4. Disabling the layer via `AUTONOMATH_HALLUCINATION_GUARD_ENABLED=0`
     short-circuits both strip + header.

The middleware tests build a tiny FastAPI app rather than spinning up
the full `create_app()` — that keeps the test fast and decouples it
from the (heavy) DB / FTS init path.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

yaml = pytest.importorskip("yaml")


def _first_phrase_with_severity(target: str) -> tuple[str, str]:
    """Return (phrase, severity) of the first YAML entry with the given severity."""
    from jpintel_mcp.self_improve.loop_a_hallucination_guard import _load

    entries = _load()
    for e in entries:
        if e["severity"] == target:
            return e["phrase"], e["severity"]
    raise AssertionError(f"YAML cache has no entry with severity={target!r}")


def _build_app(payload: dict) -> FastAPI:
    """Build a minimal FastAPI app with only ResponseSanitizerMiddleware.

    The route returns `payload` as JSON. We rebuild the middleware module
    every call so monkeypatched `settings.hallucination_guard_enabled`
    overrides take effect.
    """
    from jpintel_mcp.api import response_sanitizer

    importlib.reload(response_sanitizer)

    app = FastAPI()
    app.add_middleware(response_sanitizer.ResponseSanitizerMiddleware)

    @app.get("/echo")
    def echo() -> dict:
        return payload

    return app


# ─────────────────────────────────────────────────────────────────────
# Layer 3 strip + header (the new contract)
# ─────────────────────────────────────────────────────────────────────


def test_high_severity_phrase_gets_stripped() -> None:
    """A high-severity YAML phrase in the response body must be replaced."""
    phrase, _ = _first_phrase_with_severity("high")
    payload = {"answer": f"質問への回答です: {phrase} という案内があります"}
    app = _build_app(payload)
    client = TestClient(app)

    resp = client.get("/echo")
    assert resp.status_code == 200
    body = resp.json()
    assert phrase not in body["answer"], (
        f"high-severity phrase {phrase!r} must be stripped from response body"
    )
    assert "[出典未確認のため削除]" in body["answer"]


def test_x_hallucination_guard_hits_header_set() -> None:
    """`X-Hallucination-Guard-Hits` header must report the loop_a hit count."""
    phrase, _ = _first_phrase_with_severity("high")
    payload = {"answer": f"参考情報: {phrase}"}
    app = _build_app(payload)
    client = TestClient(app)

    resp = client.get("/echo")
    assert resp.status_code == 200
    # Starlette / httpx normalize header names case-insensitively.
    hits_header = resp.headers.get("X-Hallucination-Guard-Hits")
    assert hits_header is not None, (
        "X-Hallucination-Guard-Hits header missing on a body that "
        "contains a known YAML phrase"
    )
    assert int(hits_header) >= 1
    # Generic content-sanitized flag should also be present.
    assert resp.headers.get("x-content-sanitized") == "1"


def test_clean_body_omits_hits_header() -> None:
    """Bodies with no YAML match must NOT carry the X-Hallucination-Guard-Hits header.

    Operators rely on the header presence as a "something got stripped"
    signal in CDN logs — a stray header on every response would defeat
    that signal.
    """
    payload = {"answer": "本日は晴天なり。散歩に最適です。"}
    app = _build_app(payload)
    client = TestClient(app)

    resp = client.get("/echo")
    assert resp.status_code == 200
    assert "X-Hallucination-Guard-Hits" not in resp.headers
    # Body unchanged
    assert resp.json() == payload


def test_medium_severity_phrase_annotated_but_preserved() -> None:
    """Medium-severity matches should be flagged but NOT stripped from text.

    Strip is reserved for high severity (see response_sanitizer.py
    Layer 3 docstring). Medium / low get the envelope sentinel only.
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    phrase, severity = _first_phrase_with_severity("medium")
    text = f"参考: {phrase}"
    clean, hits = sanitize_response_text(text)
    assert clean == text, "medium-severity phrase must NOT be rewritten"
    assert f"loop_a-{severity}" in hits


# ─────────────────────────────────────────────────────────────────────
# Operator one-flag rollback
# ─────────────────────────────────────────────────────────────────────


def test_disabled_layer_skips_strip_and_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AUTONOMATH_HALLUCINATION_GUARD_ENABLED=0` must skip Layer 3 entirely."""
    from jpintel_mcp.api import response_sanitizer as rs

    importlib.reload(rs)
    monkeypatch.setattr(rs.settings, "hallucination_guard_enabled", False)

    phrase, _ = _first_phrase_with_severity("high")
    clean, hits = rs.sanitize_response_text(f"参考: {phrase}")
    assert phrase in clean, "disabled layer must not strip"
    assert not any(h.startswith("loop_a-") for h in hits)
