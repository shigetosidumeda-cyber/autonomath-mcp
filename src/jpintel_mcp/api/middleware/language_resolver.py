"""Language resolver middleware (R8 i18n deep audit follow-up).

Stamps a single ``request.state.lang`` value (``"ja"`` | ``"en"``) onto every
incoming request so downstream envelope helpers (``api/_envelope.py`` /
``api/_error_envelope.py``) and route handlers can pick the correct language
copy without each one re-parsing headers / query strings.

Resolution order (highest priority wins):

    1. ``?lang=`` query param (caller opt-in, explicit user choice).
       Accepted values: ``ja`` | ``en`` (case-folded). Anything else is
       silently dropped — never 4xx — because language selection is a
       presentation concern, not a request validity gate.
    2. ``Accept-Language`` header (RFC 9110 §12.5.4 q-value priority).
       The first listed language tag whose primary subtag matches
       ``ja`` or ``en`` (after q-value sort, descending) wins. So
       ``Accept-Language: en-US,ja;q=0.5`` → ``"en"``;
       ``Accept-Language: fr;q=1.0,ja;q=0.9`` → ``"ja"`` (fr is unsupported,
       so the next-best supported wins).
    3. Default: ``"ja"`` — jpcite's primary audience. Backward-compatible
       with every existing caller that does not pass either signal.

Why a middleware
----------------
0/182 v1 endpoints carried a ``lang=`` query parameter pre-R8. Adding it
to every route signature would require 182 router edits and 182 OpenAPI
schema changes. Promoting the resolution to a middleware keeps:

  * Backward compat: existing callers unchanged, default ``"ja"``.
  * Single SOT: one regex / one parse path / one default.
  * OpenAPI noise-free: ``lang=`` is not surfaced as an explicit query
    parameter on every route schema (would inflate the SDK surface 182×
    for a presentation-only knob); instead, the contract is documented
    once on the response-envelope reference page.

Failure posture
---------------
Header / query parsing never raises into the request hot path. On any
exception the middleware sets ``request.state.lang = "ja"`` so downstream
helpers have a guaranteed attribute. The middleware is ~80 LOC, no DB
read, no I/O — its failure budget is "never block".

Integration with the i18n catalog
---------------------------------
``jpintel_mcp.i18n.t(key, lang)`` already accepts ``lang`` as a positional
kwarg and silently falls back to ``"ja"`` for unknown language codes
(see ``i18n/__init__.py``). Resolving language at the middleware layer
means call sites can simply do::

    from jpintel_mcp.i18n import t
    t("envelope.empty.search_tax_incentives", request.state.lang)

without re-implementing q-value parsing.

Existing ``lang=`` consumers
----------------------------
Two endpoints pre-date this middleware and carry a route-level ``lang`` /
``language`` query parameter:

  * ``/v1/citation/{request_id}`` — already accepts ``lang=`` per route
    handler (legacy). The middleware sets ``request.state.lang`` first;
    the handler's explicit query parameter still wins for that route.
  * ``/v1/widget/badge.svg`` — accepts ``language=ja|en`` (note: spelled
    out, NOT ``lang=``). Untouched by this middleware.

Both keep their existing behavior; ``request.state.lang`` is additive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, Literal

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response

_log = logging.getLogger("jpintel.language_resolver")

LangCode = Literal["ja", "en"]

#: Closed set of supported language codes. Mirrors
#: ``jpintel_mcp.i18n.supported_languages()`` — kept in sync by hand
#: rather than imported to avoid a cycle (i18n is a leaf module that
#: this middleware indirectly serves).
_SUPPORTED: Final[frozenset[str]] = frozenset({"ja", "en"})

#: Default when no signal can be resolved. ``"ja"`` is jpcite's primary
#: audience; foreign-FDI cohort callers explicitly pass ``?lang=en`` or
#: an ``Accept-Language: en`` header.
_DEFAULT: Final[LangCode] = "ja"


def _parse_query_lang(query_string: bytes | str) -> LangCode | None:
    """Pull a single ``lang=`` value off the raw query string.

    We avoid ``request.query_params`` because that would parse the entire
    query into a dict — overkill for this one-key lookup, and the parse
    has been the subject of past CVE noise (e.g. CVE-2025-62727 starlette
    multipart parsing). A flat scan is faster and safer.

    Returns the first ``lang=`` value found (case-folded) iff it is in
    the supported set; otherwise None. Multiple ``lang=`` instances pick
    the first one — same precedence FastAPI's default ``Query`` handler
    uses for unmarked-as-list params.
    """
    if not query_string:
        return None
    qs = (
        query_string.decode("ascii", errors="replace")
        if isinstance(query_string, bytes)
        else query_string
    )
    # Cheap scan: split on '&' / look for 'lang=' prefix on each segment.
    for segment in qs.split("&"):
        if not segment:
            continue
        # Tolerate leading whitespace; strip once.
        seg = segment.strip()
        if seg.startswith("lang="):
            value = seg[len("lang=") :]
            # urllib unquote: lang values are ASCII, but be defensive
            # against ``%6A%61`` style obfuscation. Not URL-decoding here
            # is fine because every legitimate value is plain ASCII; a
            # weird-encoded value is silently dropped (None return).
            value = value.split("&", 1)[0].strip().lower()
            if value in _SUPPORTED:
                return value  # type: ignore[return-value]
            return None
    return None


def _parse_accept_language(header: str | None) -> LangCode | None:
    """Pick the highest-q-value supported language tag.

    Implements just enough of RFC 9110 §12.5.4 / RFC 4647 to handle real
    browser + SDK Accept-Language strings:

        Accept-Language: en-US,en;q=0.9,ja;q=0.5,*;q=0.1

    Algorithm:
      1. Split on ',' to get tag tokens.
      2. For each, parse ``primary[;q=N]``. Default q=1.0 when absent.
      3. Map primary subtag to ``"ja"`` / ``"en"`` (case-folded). The
         primary subtag is the part before the first '-' (so ``en-US``
         and ``en-GB`` both map to ``"en"``, ``ja-JP`` maps to ``"ja"``).
      4. Sort by q descending; first supported wins.
      5. ``q=0`` entries are explicitly NOT supported (RFC: zero means
         "do not use this language") — we drop them.

    Wildcard ``*`` is ignored: the spec defines it as "any language not
    listed", but our supported set is closed (ja/en) so the wildcard
    cannot meaningfully steer the choice.
    """
    if not header:
        return None
    candidates: list[tuple[float, LangCode]] = []
    for raw in header.split(","):
        raw = raw.strip()
        if not raw:
            continue
        # Split tag and parameters.
        if ";" in raw:
            tag, *params = raw.split(";")
            tag = tag.strip().lower()
            q: float = 1.0
            for p in params:
                p = p.strip()
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 1.0
                    break
            if q <= 0.0:
                continue  # explicitly excluded by caller
        else:
            tag = raw.lower()
            q = 1.0
        # Wildcard handling — drop, see docstring rationale.
        if tag == "*":
            continue
        # Primary subtag is everything before the first '-'.
        primary = tag.split("-", 1)[0]
        if primary in _SUPPORTED:
            candidates.append((q, primary))  # type: ignore[arg-type]
    if not candidates:
        return None
    # Highest q wins; on tie, preserve the caller's original ordering by
    # using a stable sort (Python's sort is guaranteed stable).
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def resolve_lang(query_string: bytes | str, accept_language: str | None) -> LangCode:
    """Public helper — pure-function language resolution.

    Exposed for unit tests + downstream call sites that need the same
    resolution logic without going through a middleware (e.g. envelope
    helpers that build a response when ``request.state`` is unavailable
    — pre-mounted exception handlers, background tasks).
    """
    # 1. Query param override.
    qp = _parse_query_lang(query_string)
    if qp is not None:
        return qp
    # 2. Accept-Language fallback.
    al = _parse_accept_language(accept_language)
    if al is not None:
        return al
    # 3. Default.
    return _DEFAULT


class LanguageResolverMiddleware(BaseHTTPMiddleware):
    """Stamp ``request.state.lang`` on every request.

    Reads ``?lang=`` (highest priority) → ``Accept-Language`` header →
    falls back to ``"ja"``. Downstream envelope helpers + i18n catalog
    callers read ``request.state.lang`` to pick the user-message copy.

    Always sets the attribute (to ``"ja"`` on any error) so the
    downstream read site never has to ``getattr(..., default="ja")`` —
    the contract is "this attribute always exists after the middleware".
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            qs = request.url.query  # str
            al = request.headers.get("accept-language")
            request.state.lang = resolve_lang(qs, al)
        except Exception:  # pragma: no cover — defensive
            _log.warning("language_resolver parse failed", exc_info=True)
            request.state.lang = _DEFAULT
        return await call_next(request)


__all__ = [
    "LangCode",
    "LanguageResolverMiddleware",
    "resolve_lang",
]
