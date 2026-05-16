"""Unit tests for the follow-mode feature added to jpcite-crawler.

Covers:
    * FollowMode enum + manifest coercion
    * extract_followable_links pure parsing (no network)
    * Fetcher.fetch_many follow queue with a stub httpx client

Runs locally without AWS / network. Invoke:

    cd docker/jpcite-crawler
    python -m pytest test_follow_mode.py -q

NO LLM calls. NO external HTTP.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

# Ensure the sibling crawl/entrypoint/manifest modules are importable when
# this file is run directly (the container layout has them as top-level
# modules under /app, not a package).
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from crawl import (  # noqa: E402
    Fetcher,
    FollowMode,
    SourcePolicy,
    TargetSpec,
    _coerce_follow_mode,
    extract_followable_links,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_html(body: str) -> bytes:
    return body.encode("utf-8")


def _stub_client(routes: dict[str, tuple[int, dict[str, str], bytes]]) -> httpx.Client:
    """Return an httpx.Client whose transport answers from ``routes``.

    ``routes`` maps URL string to ``(status_code, headers, body)``. Any
    URL not in routes returns 404. robots.txt requests are auto-permissive
    (200 + empty body) so the test doesn't have to wire robots into every
    route table.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # Auto-allow robots fetches.
        if url.endswith("/robots.txt"):
            return httpx.Response(200, content=b"")
        if url in routes:
            status, headers, body = routes[url]
            return httpx.Response(status, headers=headers, content=body)
        return httpx.Response(404, content=b"not_found")

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, follow_redirects=True)


# ---------------------------------------------------------------------------
# FollowMode coercion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, FollowMode.NONE),
        ("", FollowMode.NONE),
        ("none", FollowMode.NONE),
        ("pdf_only", FollowMode.PDF_ONLY),
        ("PDF_ONLY", FollowMode.PDF_ONLY),  # case-insensitive via .strip().lower()
        ("same_domain", FollowMode.SAME_DOMAIN),
        ("all_anchors", FollowMode.ALL_ANCHORS),
        ("garbage_typo", FollowMode.NONE),  # unknown -> safe default
        (FollowMode.PDF_ONLY, FollowMode.PDF_ONLY),
        (123, FollowMode.NONE),  # non-str -> default
    ],
)
def test_coerce_follow_mode(value: Any, expected: FollowMode) -> None:
    assert _coerce_follow_mode(value) is expected


# ---------------------------------------------------------------------------
# extract_followable_links
# ---------------------------------------------------------------------------


SAMPLE_INDEX = _make_html("""
<html><body>
  <a href="https://www.meti.go.jp/policy/a.pdf">PDF A</a>
  <a href="/policy/b.pdf">PDF B (relative)</a>
  <a href="https://www.meti.go.jp/policy/sub.html">Sub HTML</a>
  <a href="https://other.go.jp/foo.pdf">Other domain PDF</a>
  <a href="mailto:foo@bar">mailto skip</a>
  <a href="javascript:void(0)">js skip</a>
  <a href="#anchor">fragment skip</a>
  <a href="https://www.meti.go.jp/policy/a.pdf#page=3">dup with fragment</a>
</body></html>
""")
SAMPLE_BASE = "https://www.meti.go.jp/policy/index.html"


def test_extract_none() -> None:
    out = extract_followable_links(
        body=SAMPLE_INDEX,
        base_url=SAMPLE_BASE,
        follow_mode=FollowMode.NONE,
        max_links=99,
    )
    assert out == []


def test_extract_pdf_only_dedupes_fragments() -> None:
    out = extract_followable_links(
        body=SAMPLE_INDEX,
        base_url=SAMPLE_BASE,
        follow_mode=FollowMode.PDF_ONLY,
        max_links=99,
    )
    # 3 distinct PDFs: meti a, meti b (resolved), other.go.jp foo
    assert "https://www.meti.go.jp/policy/a.pdf" in out
    assert "https://www.meti.go.jp/policy/b.pdf" in out
    assert "https://other.go.jp/foo.pdf" in out
    assert "https://www.meti.go.jp/policy/sub.html" not in out
    # Fragment variant must be deduped against the canonical URL.
    assert sum(1 for u in out if u.startswith("https://www.meti.go.jp/policy/a.pdf")) == 1
    assert len(out) == 3


def test_extract_same_domain() -> None:
    out = extract_followable_links(
        body=SAMPLE_INDEX,
        base_url=SAMPLE_BASE,
        follow_mode=FollowMode.SAME_DOMAIN,
        max_links=99,
    )
    # Drops other.go.jp + the mailto/javascript/fragment-only entries.
    assert all("meti.go.jp" in u for u in out)
    assert "https://www.meti.go.jp/policy/a.pdf" in out
    assert "https://www.meti.go.jp/policy/b.pdf" in out
    assert "https://www.meti.go.jp/policy/sub.html" in out
    assert "https://other.go.jp/foo.pdf" not in out


def test_extract_all_anchors() -> None:
    out = extract_followable_links(
        body=SAMPLE_INDEX,
        base_url=SAMPLE_BASE,
        follow_mode=FollowMode.ALL_ANCHORS,
        max_links=99,
    )
    assert "https://other.go.jp/foo.pdf" in out
    assert "https://www.meti.go.jp/policy/sub.html" in out


def test_extract_respects_max_links() -> None:
    out = extract_followable_links(
        body=SAMPLE_INDEX,
        base_url=SAMPLE_BASE,
        follow_mode=FollowMode.PDF_ONLY,
        max_links=1,
    )
    assert len(out) == 1


def test_extract_non_html_content_type() -> None:
    out = extract_followable_links(
        body=b"%PDF-1.4 binary garbage",
        base_url="https://www.example.go.jp/x.pdf",
        follow_mode=FollowMode.PDF_ONLY,
        max_links=99,
        content_type="application/pdf",
    )
    assert out == []


def test_extract_malformed_html_does_not_crash() -> None:
    body = b"<html><body><a href='https://x/y.pdf'>open<a "
    out = extract_followable_links(
        body=body,
        base_url="https://x/",
        follow_mode=FollowMode.PDF_ONLY,
        max_links=99,
    )
    assert "https://x/y.pdf" in out


def test_extract_empty_body() -> None:
    assert (
        extract_followable_links(
            body=b"",
            base_url="https://x/",
            follow_mode=FollowMode.PDF_ONLY,
            max_links=99,
        )
        == []
    )


# ---------------------------------------------------------------------------
# Fetcher.fetch_many with follow queue
# ---------------------------------------------------------------------------


def test_fetcher_follow_pdf_only_appends_children() -> None:
    index_url = "https://www.meti.go.jp/policy/index.html"
    index_body = _make_html(
        f"""
        <html><body>
          <a href="{index_url.rsplit('/', 1)[0]}/c.pdf">C</a>
          <a href="{index_url.rsplit('/', 1)[0]}/d.html">D html ignored</a>
        </body></html>
        """
    )
    routes = {
        index_url: (200, {"content-type": "text/html"}, index_body),
        "https://www.meti.go.jp/policy/c.pdf": (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4 pdf bytes",
        ),
    }
    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        license_boundary="derived_fact",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.PDF_ONLY,
        follow_max_per_page=10,
        follow_max_total=100,
        follow_max_depth=1,
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=index_url, target_id="root")])
    finally:
        fetcher.close()

    urls = [r.target.url for r in results]
    assert index_url in urls
    assert "https://www.meti.go.jp/policy/c.pdf" in urls
    # d.html is NOT in pdf_only.
    assert "https://www.meti.go.jp/policy/d.html" not in urls
    # Provenance must be stamped on the followed child.
    pdf_result = next(
        r for r in results if r.target.url == "https://www.meti.go.jp/policy/c.pdf"
    )
    assert pdf_result.target.follow_parent_url == index_url
    assert pdf_result.target.follow_depth == 1
    assert pdf_result.ok is True
    assert pdf_result.content_bytes.startswith(b"%PDF")
    assert fetcher.follow_emitted_total == 1


def test_fetcher_follow_mode_none_does_not_follow() -> None:
    index_url = "https://www.meti.go.jp/policy/index.html"
    index_body = _make_html(
        f"""
        <html><body><a href="{index_url.rsplit('/', 1)[0]}/c.pdf">C</a></body></html>
        """
    )
    routes = {
        index_url: (200, {"content-type": "text/html"}, index_body),
        "https://www.meti.go.jp/policy/c.pdf": (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4",
        ),
    }
    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        respect_robots=True,
        request_delay_seconds=0.0,
        # follow_mode defaults to NONE
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=index_url, target_id="root")])
    finally:
        fetcher.close()

    urls = [r.target.url for r in results]
    assert urls == [index_url]
    assert fetcher.follow_emitted_total == 0


def test_fetcher_follow_respects_max_total() -> None:
    index_url = "https://x.go.jp/i"
    body = _make_html(
        "<html><body>"
        + "".join(f'<a href="https://x.go.jp/p{i}.pdf">p{i}</a>' for i in range(5))
        + "</body></html>"
    )
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {
        index_url: (200, {"content-type": "text/html"}, body)
    }
    for i in range(5):
        routes[f"https://x.go.jp/p{i}.pdf"] = (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4",
        )

    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.PDF_ONLY,
        follow_max_per_page=10,
        follow_max_total=2,  # cap
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=index_url, target_id="root")])
    finally:
        fetcher.close()

    pdf_results = [r for r in results if r.target.url.endswith(".pdf")]
    assert len(pdf_results) == 2
    assert fetcher.follow_emitted_total == 2


def test_fetcher_follow_respects_max_depth() -> None:
    # Depth-1 index links to depth-1 PDF. Even with follow_max_depth=1,
    # we expect the PDF to land but the PDF body is binary so no
    # second-level following can occur.
    root = "https://y.go.jp/index"
    body_root = _make_html(f'<a href="{root}sub">sub</a>')
    sub_body = _make_html('<a href="https://y.go.jp/q.pdf">q</a>')
    routes = {
        root: (200, {"content-type": "text/html"}, body_root),
        f"{root}sub": (200, {"content-type": "text/html"}, sub_body),
        "https://y.go.jp/q.pdf": (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4",
        ),
    }
    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.SAME_DOMAIN,
        follow_max_per_page=10,
        follow_max_total=10,
        follow_max_depth=1,
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=root, target_id="root")])
    finally:
        fetcher.close()

    urls = [r.target.url for r in results]
    assert root in urls
    assert f"{root}sub" in urls
    # PDF was NOT followed because that would require depth 2.
    assert "https://y.go.jp/q.pdf" not in urls


def test_fetcher_follow_inherits_license_boundary() -> None:
    index_url = "https://z.go.jp/index"
    body = _make_html('<a href="https://z.go.jp/r.pdf">r</a>')
    routes = {
        index_url: (200, {"content-type": "text/html"}, body),
        "https://z.go.jp/r.pdf": (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4",
        ),
    }
    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        license_boundary="metadata_only",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.PDF_ONLY,
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many(
            [
                TargetSpec(
                    url=index_url,
                    target_id="root",
                    license_boundary="metadata_only",
                )
            ]
        )
    finally:
        fetcher.close()

    pdf = next(r for r in results if r.target.url.endswith(".pdf"))
    assert pdf.target.license_boundary == "metadata_only"


def test_fetcher_dedupes_followed_urls() -> None:
    # Two anchors point to the same PDF — must only be fetched once.
    index_url = "https://w.go.jp/index"
    body = _make_html(
        '<a href="https://w.go.jp/dup.pdf">a</a>'
        '<a href="https://w.go.jp/dup.pdf">b</a>'
    )
    routes = {
        index_url: (200, {"content-type": "text/html"}, body),
        "https://w.go.jp/dup.pdf": (
            200,
            {"content-type": "application/pdf"},
            b"%PDF-1.4",
        ),
    }
    client = _stub_client(routes)
    policy = SourcePolicy(
        source_id="test",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.PDF_ONLY,
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=index_url, target_id="root")])
    finally:
        fetcher.close()

    pdfs = [r for r in results if r.target.url.endswith(".pdf")]
    assert len(pdfs) == 1
    assert fetcher.follow_emitted_total == 1


def test_fetcher_follow_skips_when_parent_skipped_for_robots() -> None:
    # robots.txt that disallows the index page must skip the index AND
    # not follow anything (the body was never received).
    index_url = "https://q.go.jp/index"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(
                200, content=b"User-agent: *\nDisallow: /index\n"
            )
        return httpx.Response(404, content=b"unreachable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    policy = SourcePolicy(
        source_id="test",
        respect_robots=True,
        request_delay_seconds=0.0,
        follow_mode=FollowMode.PDF_ONLY,
    )
    fetcher = Fetcher(policy, client=client)
    try:
        results = fetcher.fetch_many([TargetSpec(url=index_url)])
    finally:
        fetcher.close()

    assert len(results) == 1
    assert results[0].skipped_reason == "robots_disallow"
    assert fetcher.follow_emitted_total == 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
