from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REDIRECTS = REPO_ROOT / "site" / "_redirects"
PUBLIC_DOCS = REPO_ROOT / "site" / "docs"
PAGES_WORKFLOWS = [
    REPO_ROOT / ".github" / "workflows" / "pages-preview.yml",
    REPO_ROOT / ".github" / "workflows" / "pages-regenerate.yml",
]
PUBLIC_AI_AND_TOOL_SURFACES = [
    REPO_ROOT / "site" / "llms.txt",
    REPO_ROOT / "site" / "llms-full.txt",
    REPO_ROOT / "site" / "llms-full.en.txt",
    REPO_ROOT / "site" / "bookmarklet.html",
    REPO_ROOT / "site" / "qa" / "mcp" / "what-can-jpcite-mcp-do.html",
    REPO_ROOT / "site" / "qa" / "llm-evidence" / "custom-gpt-japanese-subsidy-api.html",
]


def _redirect_sources() -> list[str]:
    sources: list[str] = []
    for line in REDIRECTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if parts:
            sources.append(parts[0])
    return sources


def _redirect_source_matches(source: str, path: str) -> bool:
    escaped = re.escape(source)
    escaped = escaped.replace(r"\*", r".*")
    escaped = re.sub(r":[A-Za-z][A-Za-z0-9_]*", r"[^/]+", escaped)
    return re.fullmatch(escaped, path) is not None


def _first_static_path(pattern: str, fallback: str) -> str:
    sample = next((REPO_ROOT / "site").glob(pattern), None)
    if sample is None:
        return fallback
    return "/" + sample.relative_to(REPO_ROOT / "site").as_posix()


def test_redirects_do_not_shadow_existing_program_or_qa_html_pages() -> None:
    samples = [
        _first_static_path("programs/*.html", "/programs/sample-program.html"),
        _first_static_path("qa/*/*.html", "/qa/sample-topic/sample-answer.html"),
    ]

    offenders: list[tuple[str, str]] = []
    for source in _redirect_sources():
        for path in samples:
            if _redirect_source_matches(source, path):
                offenders.append((source, path))

    assert offenders == []


def test_qa_template_uses_public_links_and_search_endpoint() -> None:
    template = (REPO_ROOT / "site" / "_templates" / "qa.html").read_text(encoding="utf-8")

    assert 'href="../' not in template
    assert "..//" not in template
    assert "/_templates/qa.html" not in template
    assert "/v1/programs?q=" not in template
    assert "/v1/programs/search?q=" in template


def test_public_docs_do_not_regress_to_internal_or_legacy_copy() -> None:
    banned_terms = [
        "¥3/req",
        "¥3/request",
        "¥3.30/req",
        "¥3 / リクエスト",
        "¥3 per request",
        "One ¥3 charge per request",
        "Bookyou株式会社 (T8010001213708)",
        "AUTONOMATH_API_KEY",
        "include_excluded",
        "include_internal",
        "Tier X",
        "Review-held",
        "review-held",
        "quarantine rows",
        "Review-held/quarantine",
        "sitemap-structured",
        "/structured/",
    ]
    suffixes = {".html", ".json", ".xml", ".txt", ".csv"}

    offenders: list[tuple[str, str]] = []
    for path in PUBLIC_DOCS.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for term in banned_terms:
            if term in text:
                offenders.append((rel, term))

    assert offenders == []


def test_public_sitemap_controls_publish_structured_jsonld_shards() -> None:
    """Structured JSON-LD shards are an intentional AI discovery surface."""
    robots = (REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    sitemap_index = (REPO_ROOT / "site" / "sitemap-index.xml").read_text(
        encoding="utf-8"
    )
    headers = (REPO_ROOT / "site" / "_headers").read_text(encoding="utf-8")

    assert "Allow: /structured/" in robots
    assert "https://jpcite.com/sitemap-structured.xml" in robots
    assert "https://jpcite.com/sitemap-structured.xml" in sitemap_index
    assert "/structured/*.jsonld" in headers
    assert "application/ld+json" in headers


def test_key_ai_and_tool_surfaces_use_current_billing_and_evidence_copy() -> None:
    banned_terms = [
        "¥3/req",
        "¥3/request",
        "¥3.30/req",
        "¥3 / req",
        "税込¥3.30/request",
        "**Use first** for any 制度 query",
        "The five highest-leverage endpoints for agent flows: `GET /v1/programs/search`",
        '"tier_counts": {"S": 46',
        '"X": 1213',
        "source-allowed public-search rows",
        "source-allowed entries",
    ]

    offenders: list[tuple[str, str]] = []
    for path in PUBLIC_AI_AND_TOOL_SURFACES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for term in banned_terms:
            if term in text:
                offenders.append((rel, term))

    assert offenders == []


def test_pages_artifact_excludes_standalone_structured_shards() -> None:
    missing: list[tuple[str, str]] = []
    expected_snippets = [
        "--exclude 'structured/'",
        "--exclude 'sitemap-structured.xml'",
        "cat > dist/site/sitemap-structured.xml",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
    ]
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        rel = workflow.relative_to(REPO_ROOT).as_posix()
        for snippet in expected_snippets:
            if snippet not in text:
                missing.append((rel, snippet))

    assert missing == []
