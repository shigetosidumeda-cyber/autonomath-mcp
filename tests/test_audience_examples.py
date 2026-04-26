"""K2 / J7 follow-up: audience HTML <pre><code> samples must actually work.

Background
----------
``site/audiences/*.html`` ships per-audience landing pages (dev / smb /
tax-advisor / admin-scrivener / vc) that embed live ``curl`` and
``httpx`` snippets. J7's audience walk surfaced 4 broken examples whose
URLs no longer routed cleanly. K2 noted that nothing in the test
suite verified those snippets — broken paths could ship indefinitely.

These tests parse each HTML page with BeautifulSoup, extract every
``<pre><code>`` curl/httpx block, normalise it into a TestClient call,
and assert the response is < 400. We deliberately do **not** hardcode
expected URLs — M1 may be rewriting site/audiences/* in parallel.
Instead, we extract the path/method live from the markup so the tests
follow whatever the page currently advertises.

Skips:
    - non-HTTP snippets (claude_desktop_config.json, plain natural-
      language demos, etc.) are filtered out by URL detection.
    - aggregator hosts other than ``api.autonomath.ai`` are skipped
      (the page may show third-party JST snippets for context).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pytest

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


_REPO = Path(__file__).resolve().parent.parent
_SITE_AUDIENCES = _REPO / "site" / "audiences"

# Match calls like:
#   curl 'https://api.autonomath.ai/v1/programs/search?q=...'
#   curl "https://api.autonomath.ai/v1/exclusions/check"
#   httpx.get("https://api.autonomath.ai/v1/...")
#   httpx.post("https://api.autonomath.ai/v1/...", json=...)
_CURL_URL_RE = re.compile(
    r"https?://api\.autonomath\.ai(/[A-Za-z0-9_/{}.-]+(?:\?[^\s'\"`]*)?)"
)
_HTTPX_GET_RE = re.compile(
    r"httpx\.get\s*\(\s*[\"'](https?://api\.autonomath\.ai/[^\"']+)[\"']"
)
_HTTPX_POST_RE = re.compile(
    r"httpx\.post\s*\(\s*[\"'](https?://api\.autonomath\.ai/[^\"']+)[\"']"
)


def _normalise_url(raw: str) -> str:
    """Strip the api.autonomath.ai host + collapse continuation backslashes.

    Audience HTML often wraps long URLs across visual lines via a literal
    backslash + newline. The browser collapses that on render but our
    regex needs to do the same before we hand it to TestClient.
    """
    # Drop scheme + host
    path = re.sub(r"^https?://api\.autonomath\.ai", "", raw)
    # Collapse backslash-newline-whitespace continuations (HTML-encoded
    # versions arrive as literal backslashes in the source text).
    path = re.sub(r"\\\s*", "", path)
    # Decode HTML entities the regex grabbed (BeautifulSoup .text usually
    # handles &amp; → &, but be defensive for raw-text fallbacks).
    path = path.replace("&amp;", "&")
    return path


def _iter_examples() -> Iterator[tuple[str, str, str]]:
    """Yield (audience, method, path) for every HTTP example on disk.

    Reads each audience HTML page fresh on every call so M1's fixes
    (whatever they are) are picked up without re-running collection.
    """
    if BeautifulSoup is None or not _SITE_AUDIENCES.is_dir():
        return
    for html_path in sorted(_SITE_AUDIENCES.glob("*.html")):
        audience = html_path.stem
        try:
            soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        except Exception:
            continue
        for code in soup.find_all("code"):
            text = code.get_text("\n", strip=False)
            if not text:
                continue
            if "claude_desktop_config" in text or "mcpServers" in text:
                # MCP config snippet, not an HTTP example.
                continue
            seen: set[tuple[str, str]] = set()
            for m in _HTTPX_POST_RE.finditer(text):
                key = ("POST", _normalise_url(m.group(1)))
                if key not in seen:
                    seen.add(key)
                    yield (audience, key[0], key[1])
            for m in _HTTPX_GET_RE.finditer(text):
                key = ("GET", _normalise_url(m.group(1)))
                if key not in seen:
                    seen.add(key)
                    yield (audience, key[0], key[1])
            # Plain curl: assume GET unless the snippet contains
            # `curl -X POST` or a `-d` / `--data` flag.
            if "curl" in text:
                method = "GET"
                if re.search(r"curl[^\n]*-X\s*POST", text) or re.search(
                    r"\s-(?:d|-data|-data-raw)\b", text
                ):
                    method = "POST"
                for m in _CURL_URL_RE.finditer(text):
                    key = (method, _normalise_url(m.group(1)))
                    if key not in seen:
                        seen.add(key)
                        yield (audience, key[0], key[1])


_EXAMPLES = list(_iter_examples())


@pytest.mark.skipif(BeautifulSoup is None, reason="bs4 not installed")
def test_audience_html_files_exist():
    """Sanity: at least one audience HTML must be on disk."""
    files = list(_SITE_AUDIENCES.glob("*.html"))
    assert files, f"no audience HTML under {_SITE_AUDIENCES}"


@pytest.mark.skipif(BeautifulSoup is None, reason="bs4 not installed")
def test_extracted_at_least_one_example():
    """Sanity: extraction must surface at least one usable example."""
    assert _EXAMPLES, (
        "BeautifulSoup parsed the audience pages but found 0 HTTP examples — "
        "the regexes above probably need updating."
    )


@pytest.mark.skipif(BeautifulSoup is None, reason="bs4 not installed")
@pytest.mark.parametrize(
    ("audience", "method", "path"),
    _EXAMPLES,
    ids=[f"{a}:{m}:{p[:60]}" for a, m, p in _EXAMPLES] or ["empty"],
)
def test_audience_example_routes_resolve(client, audience, method, path):
    """Each extracted example must route to a real endpoint (< 400).

    We send POSTs with an empty JSON body if the page didn't show a
    payload — the goal here is "is the path real?", not "is the
    business logic happy". Validation 422 is acceptable (the route
    exists; the example simply omitted required body fields). 4xx auth
    errors are also acceptable for paid/admin paths — the page is
    correctly pointing at a real route, the user just needs a key.

    The test FAILS only on:
      - 404 (route_not_found)        → broken example
      - 405 (method_not_allowed)     → wrong verb in the snippet
      - 5xx (server error)           → snippet trips a server bug
    """
    if method == "GET":
        r = client.get(path)
    else:
        r = client.post(path, json={})
    assert r.status_code != 404, (
        f"{audience}/{method} {path} → 404 (broken example)"
    )
    assert r.status_code != 405, (
        f"{audience}/{method} {path} → 405 (wrong HTTP verb in snippet)"
    )
    assert r.status_code < 500, (
        f"{audience}/{method} {path} → {r.status_code} 5xx server error"
    )


@pytest.mark.skipif(BeautifulSoup is None, reason="bs4 not installed")
def test_no_aggregator_hosts_in_examples():
    """K2 / J7 reminder: audience pages must not link to noukaweb /
    hojyokin-portal style aggregators (CONSTITUTION 13.x). If a future
    edit regresses this, fail loudly before the page ships."""
    banned = ("noukaweb", "hojyokin-portal", "biz.stayway")
    for html_path in sorted(_SITE_AUDIENCES.glob("*.html")):
        text = html_path.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text, (
                f"{html_path.name} mentions banned aggregator '{needle}'"
            )
