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


def test_public_sitemap_controls_have_retired_standalone_jsonld_surface() -> None:
    """Standalone /structured/*.jsonld shards retired 2026-05-03.

    JSON-LD is now inlined in every /programs/<slug>.html page (one
    <script type="application/ld+json"> per page), so the alt-format
    /structured/ surface and its sitemap are no longer published. Inbound
    crawler URLs are 404'd by site/_redirects.
    """
    robots = (REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    sitemap_index = (REPO_ROOT / "site" / "sitemap-index.xml").read_text(encoding="utf-8")
    headers = (REPO_ROOT / "site" / "_headers").read_text(encoding="utf-8")
    redirects = (REPO_ROOT / "site" / "_redirects").read_text(encoding="utf-8")

    assert "Allow: /structured/" not in robots
    assert "sitemap-structured.xml" not in robots
    assert "sitemap-structured.xml" not in sitemap_index
    assert "/structured/*.jsonld" not in headers
    # Inline JSON-LD still emits the application/ld+json mime via inline <script>
    # tags, so Content-Type registration is no longer needed in _headers.
    assert "/structured/*  /404  404" in redirects


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
        if not path.exists():
            # llms-full.txt / llms-full.en.txt are generated by cron and
            # gitignored; they are not present in CI sandboxes.
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for term in banned_terms:
            if term in text:
                offenders.append((rel, term))

    assert offenders == []


def test_pages_artifact_no_longer_carries_structured_exclude_workaround() -> None:
    """The --exclude 'structured/' rsync workaround was retired 2026-05-03.

    Standalone JSON-LD shards are no longer generated (see
    scripts/generate_program_pages.py), so the Cloudflare Pages 20k-file
    deploy limit is satisfied without a special-case exclusion.
    """
    leaked: list[tuple[str, str]] = []
    forbidden_snippets = [
        "--exclude 'structured/'",
        "--exclude 'sitemap-structured.xml'",
        "cat > dist/site/sitemap-structured.xml",
    ]
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        rel = workflow.relative_to(REPO_ROOT).as_posix()
        for snippet in forbidden_snippets:
            if snippet in text:
                leaked.append((rel, snippet))

    assert leaked == []
