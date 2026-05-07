"""Unit tests for ``api/middleware/language_resolver.py``.

Covers the three resolution branches:

  1. ``?lang=`` query param (highest priority, overrides Accept-Language).
  2. ``Accept-Language`` header q-value priority.
  3. Default ``"ja"`` when neither signal is present (or both are
     unsupported / malformed).

Plus the helper functions used by the middleware (``resolve_lang`` is
exposed at module level for direct unit testing without spinning up a
FastAPI app).

R8 i18n deep-audit follow-up. The contract this test pins:

* ``request.state.lang`` is ALWAYS one of ``"ja"`` | ``"en"`` after
  the middleware ran (even when the caller passes a malformed signal).
* ``"ja"`` is the default — every legacy caller is unaffected.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from jpintel_mcp.api.middleware.language_resolver import (
    LanguageResolverMiddleware,
    _parse_accept_language,
    _parse_query_lang,
    resolve_lang,
)

# ---------------------------------------------------------------------------
# Pure-function tests (no app, no fixtures)
# ---------------------------------------------------------------------------


class TestParseQueryLang:
    """`_parse_query_lang` accepts only ``ja`` | ``en``; everything else None."""

    def test_lang_ja(self) -> None:
        assert _parse_query_lang("lang=ja") == "ja"

    def test_lang_en(self) -> None:
        assert _parse_query_lang("lang=en") == "en"

    def test_lang_uppercase(self) -> None:
        # Case-folded — Accept-Language is case-insensitive per RFC 9110.
        assert _parse_query_lang("lang=EN") == "en"
        assert _parse_query_lang("lang=Ja") == "ja"

    def test_unsupported_lang_dropped(self) -> None:
        # 'fr' is not in the closed set — silently drop, never 4xx.
        assert _parse_query_lang("lang=fr") is None

    def test_garbage_value_dropped(self) -> None:
        assert _parse_query_lang("lang=") is None
        assert _parse_query_lang("lang=" + "x" * 100) is None

    def test_empty_query_string(self) -> None:
        assert _parse_query_lang("") is None
        assert _parse_query_lang(b"") is None

    def test_lang_among_other_params(self) -> None:
        # Real query strings carry many params; pick the right key.
        assert _parse_query_lang("q=hello&lang=en&offset=10") == "en"
        assert _parse_query_lang("offset=10&lang=ja&limit=5") == "ja"

    def test_first_lang_wins_when_repeated(self) -> None:
        # Multiple lang= keys: first one wins (matches FastAPI default).
        assert _parse_query_lang("lang=en&lang=ja") == "en"

    def test_no_lang_key_present(self) -> None:
        assert _parse_query_lang("q=hello&offset=10") is None

    def test_bytes_input(self) -> None:
        # Starlette ``request.url.query`` is a str, but ASGI scope passes
        # bytes — the helper accepts both for portability.
        assert _parse_query_lang(b"lang=en") == "en"


class TestParseAcceptLanguage:
    """`_parse_accept_language` does q-value priority + closed-set filter."""

    def test_simple_en(self) -> None:
        assert _parse_accept_language("en") == "en"

    def test_simple_ja(self) -> None:
        assert _parse_accept_language("ja") == "ja"

    def test_region_subtag_normalized_to_primary(self) -> None:
        # en-US, en-GB, ja-JP all map to their primary subtag.
        assert _parse_accept_language("en-US") == "en"
        assert _parse_accept_language("en-GB,en;q=0.9") == "en"
        assert _parse_accept_language("ja-JP") == "ja"

    def test_q_value_priority(self) -> None:
        # en wins over ja by q.
        assert _parse_accept_language("en;q=0.9,ja;q=0.5") == "en"
        # ja wins over en by q.
        assert _parse_accept_language("en;q=0.3,ja;q=0.9") == "ja"

    def test_unsupported_language_skipped(self) -> None:
        # fr unsupported, ja next-best.
        assert _parse_accept_language("fr;q=1.0,ja;q=0.5") == "ja"
        # No supported tags at all — None.
        assert _parse_accept_language("fr,de,es") is None

    def test_browser_default_string(self) -> None:
        # Common Chrome/Firefox default for English-locale users with
        # Japanese fallback.
        assert _parse_accept_language("en-US,en;q=0.9,ja;q=0.5,*;q=0.1") == "en"

    def test_browser_japanese_default(self) -> None:
        # Common Japanese-locale default — ja-JP first, en fallback.
        assert _parse_accept_language("ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7") == "ja"

    def test_q_zero_excluded(self) -> None:
        # RFC: q=0 means "do not use this language" — drop.
        assert _parse_accept_language("en;q=0,ja") == "ja"
        assert _parse_accept_language("ja;q=0,en") == "en"

    def test_wildcard_dropped(self) -> None:
        # `*` cannot steer a closed-set choice — drop.
        assert _parse_accept_language("*") is None
        assert _parse_accept_language("*,en;q=0.5") == "en"

    def test_empty_or_none_header(self) -> None:
        assert _parse_accept_language(None) is None
        assert _parse_accept_language("") is None

    def test_malformed_q_falls_back_to_one(self) -> None:
        # Garbage q value should not raise — degrade to q=1.0.
        assert _parse_accept_language("en;q=banana") == "en"


class TestResolveLang:
    """End-to-end resolution: query > header > default."""

    def test_query_overrides_header(self) -> None:
        assert resolve_lang("lang=en", "ja-JP,ja;q=0.9") == "en"
        assert resolve_lang("lang=ja", "en-US,en;q=0.9") == "ja"

    def test_header_when_no_query(self) -> None:
        assert resolve_lang("", "en-US,en;q=0.9,ja;q=0.5") == "en"

    def test_default_ja_when_neither(self) -> None:
        assert resolve_lang("", None) == "ja"
        assert resolve_lang("", "") == "ja"
        assert resolve_lang("q=hello", None) == "ja"

    def test_unsupported_query_falls_through_to_header(self) -> None:
        # ?lang=fr is silently dropped → header takes over.
        assert resolve_lang("lang=fr", "en-US,en;q=0.9") == "en"
        # ?lang=fr + no header → default ja.
        assert resolve_lang("lang=fr", None) == "ja"


# ---------------------------------------------------------------------------
# Middleware integration tests via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_resolver() -> FastAPI:
    """A minimal FastAPI app with only ``LanguageResolverMiddleware`` mounted.

    Exposes ``GET /lang_probe`` which returns the resolved
    ``request.state.lang`` so tests can assert the wire-side outcome
    end-to-end without dragging in the full production middleware stack
    (which would require a seeded SQLite DB).
    """
    app = FastAPI()
    app.add_middleware(LanguageResolverMiddleware)

    @app.get("/lang_probe")
    async def probe(request: Request) -> JSONResponse:
        return JSONResponse({"lang": request.state.lang})

    return app


@pytest.fixture
def lang_client(app_with_resolver: FastAPI) -> TestClient:
    return TestClient(app_with_resolver)


def test_default_lang_is_ja(lang_client: TestClient) -> None:
    """Backward-compat invariant: legacy callers (no signal) keep ``"ja"``."""
    res = lang_client.get("/lang_probe")
    assert res.status_code == 200
    assert res.json() == {"lang": "ja"}


def test_query_param_lang_en_wins(lang_client: TestClient) -> None:
    """`?lang=en` overrides everything."""
    res = lang_client.get("/lang_probe?lang=en")
    assert res.status_code == 200
    assert res.json() == {"lang": "en"}


def test_query_param_lang_ja_wins(lang_client: TestClient) -> None:
    res = lang_client.get("/lang_probe?lang=ja")
    assert res.status_code == 200
    assert res.json() == {"lang": "ja"}


def test_query_param_overrides_accept_language(lang_client: TestClient) -> None:
    """`?lang=en` beats `Accept-Language: ja` (and vice-versa)."""
    res = lang_client.get("/lang_probe?lang=en", headers={"Accept-Language": "ja-JP,ja;q=0.9"})
    assert res.json() == {"lang": "en"}

    res = lang_client.get("/lang_probe?lang=ja", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert res.json() == {"lang": "ja"}


def test_accept_language_en_us_ja(lang_client: TestClient) -> None:
    """`Accept-Language: en-US,ja` → en (en-US has implicit q=1.0)."""
    res = lang_client.get("/lang_probe", headers={"Accept-Language": "en-US,ja"})
    assert res.json() == {"lang": "en"}


def test_accept_language_japanese_browser(lang_client: TestClient) -> None:
    """Common ja-JP-locale Chrome string → ja."""
    res = lang_client.get(
        "/lang_probe",
        headers={"Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"},
    )
    assert res.json() == {"lang": "ja"}


def test_accept_language_unsupported_falls_back_to_ja(lang_client: TestClient) -> None:
    """`Accept-Language: fr,de` → no supported tags → default ``"ja"``."""
    res = lang_client.get("/lang_probe", headers={"Accept-Language": "fr,de,es"})
    assert res.json() == {"lang": "ja"}


def test_unsupported_query_lang_silently_dropped(lang_client: TestClient) -> None:
    """`?lang=fr` is silently dropped (never 4xx) — header / default takes over."""
    # No header — falls to default "ja".
    res = lang_client.get("/lang_probe?lang=fr")
    assert res.status_code == 200
    assert res.json() == {"lang": "ja"}

    # With Accept-Language: en — header wins.
    res = lang_client.get("/lang_probe?lang=fr", headers={"Accept-Language": "en"})
    assert res.json() == {"lang": "en"}


def test_request_state_lang_always_set(lang_client: TestClient) -> None:
    """Even on empty / missing signal, ``request.state.lang`` exists.

    The contract is "this attribute always exists after the middleware",
    so downstream call sites never need to ``getattr(..., default=...)``.
    """
    # No headers, no query — still sets attribute.
    res = lang_client.get("/lang_probe")
    payload = res.json()
    assert "lang" in payload
    assert payload["lang"] in ("ja", "en")


# ---------------------------------------------------------------------------
# Error-envelope integration: make_error reads request.state.lang
# ---------------------------------------------------------------------------


def test_make_error_default_is_japanese_primary() -> None:
    """No request → user_message is Japanese (backward-compat)."""
    from jpintel_mcp.api._error_envelope import make_error

    body = make_error("rate_limit_exceeded")
    err = body["error"]
    assert err["code"] == "rate_limit_exceeded"
    # Primary user_message is Japanese.
    assert "レート" in err["user_message"]
    # English mirror still present under the dedicated key.
    assert "user_message_en" in err
    assert "Rate limit" in err["user_message_en"]
    # No user_message_ja sibling on ja-primary path (saves bytes).
    assert "user_message_ja" not in err


def test_make_error_lang_en_flips_primary() -> None:
    """When ``request.state.lang == "en"``, English wins the primary slot."""
    from types import SimpleNamespace

    from jpintel_mcp.api._error_envelope import make_error

    fake_request = SimpleNamespace(state=SimpleNamespace(lang="en"))
    body = make_error("rate_limit_exceeded", request=fake_request)
    err = body["error"]
    # Primary user_message is English now.
    assert "Rate limit" in err["user_message"]
    # Both per-language siblings present so legacy consumers reading
    # either key still get their language.
    assert "user_message_en" in err
    assert "user_message_ja" in err
    assert "レート" in err["user_message_ja"]


def test_make_error_lang_ja_explicit_matches_default() -> None:
    """``request.state.lang == "ja"`` is byte-identical to no-request path."""
    from types import SimpleNamespace

    from jpintel_mcp.api._error_envelope import make_error

    fake_request = SimpleNamespace(state=SimpleNamespace(lang="ja"))
    body_with = make_error(
        "rate_limit_exceeded", request=fake_request, request_id="01TESTREQID00000000000000"
    )
    body_without = make_error("rate_limit_exceeded", request_id="01TESTREQID00000000000000")
    assert body_with == body_without


def test_safe_request_lang_handles_missing_state() -> None:
    """`safe_request_lang` defaults to ``"ja"`` on any error."""
    from types import SimpleNamespace

    from jpintel_mcp.api._error_envelope import safe_request_lang

    # Missing attribute.
    req = SimpleNamespace(state=SimpleNamespace())
    assert safe_request_lang(req) == "ja"

    # Bogus value.
    req2 = SimpleNamespace(state=SimpleNamespace(lang="klingon"))
    assert safe_request_lang(req2) == "ja"

    # No state at all — should not raise.
    class Bare:
        pass

    assert safe_request_lang(Bare()) == "ja"


def test_default_user_message_for_picks_correct_language() -> None:
    """`default_user_message_for` reads request.state.lang."""
    from types import SimpleNamespace

    from jpintel_mcp.api._envelope import default_user_message_for

    # No request → ja default.
    assert "レート" in default_user_message_for("RATE_LIMITED")

    # lang=ja → ja.
    req_ja = SimpleNamespace(state=SimpleNamespace(lang="ja"))
    assert "レート" in default_user_message_for("RATE_LIMITED", req_ja)

    # lang=en → en.
    req_en = SimpleNamespace(state=SimpleNamespace(lang="en"))
    assert "Rate limit" in default_user_message_for("RATE_LIMITED", req_en)
