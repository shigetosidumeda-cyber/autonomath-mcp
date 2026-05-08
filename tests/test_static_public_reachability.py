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
PUBLIC_LAW_COPY_SURFACES = [
    REPO_ROOT / "site" / "index.html",
    REPO_ROOT / "site" / "about.html",
    REPO_ROOT / "site" / "facts.html",
    REPO_ROOT / "site" / "trust.html",
    REPO_ROOT / "site" / "compare.html",
    REPO_ROOT / "site" / "compare" / "jgrants-mcp" / "index.html",
    REPO_ROOT / "site" / "compare" / "tax-law-mcp" / "index.html",
    REPO_ROOT / "site" / "press" / "index.html",
    REPO_ROOT / "site" / "docs" / "index.html",
    REPO_ROOT / "site" / "docs" / "honest_capabilities" / "index.html",
    REPO_ROOT / "site" / "docs" / "examples" / "index.html",
    REPO_ROOT / "docs" / "index.md",
    REPO_ROOT / "docs" / "honest_capabilities.md",
    REPO_ROOT / "docs" / "examples.md",
    REPO_ROOT / "docs" / "press_kit.md",
    REPO_ROOT / "docs" / "roadmap.md",
    REPO_ROOT / "overrides" / "partials" / "index_jsonld.html",
]
PUBLIC_SALES_SURFACE_PATHS = [
    REPO_ROOT / "site" / "index.html",
    REPO_ROOT / "site" / "about.html",
    REPO_ROOT / "site" / "products.html",
    REPO_ROOT / "site" / "pricing.html",
    REPO_ROOT / "site" / "trial.html",
    REPO_ROOT / "site" / "upgrade.html",
    REPO_ROOT / "site" / "line.html",
    REPO_ROOT / "site" / "widget.html",
    REPO_ROOT / "site" / "widget" / "demo.html",
    REPO_ROOT / "site" / "llms.txt",
    REPO_ROOT / "site" / "llms-full.txt",
    REPO_ROOT / "site" / "llms-full.en.txt",
]
PUBLIC_SALES_SURFACE_GLOBS = [
    "site/audiences/*.html",
    "site/en/audiences/*.html",
    "site/compare/*.html",
    "site/compare/*/index.html",
]
LINE_PUBLIC_SURFACES = [
    REPO_ROOT / "site" / "line.html",
    REPO_ROOT / "site" / "index.html",
    REPO_ROOT / "site" / "audiences" / "smb.html",
    REPO_ROOT / "site" / "en" / "audiences" / "index.html",
    REPO_ROOT / "site" / "en" / "audiences" / "smb.html",
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


def test_redirects_file_syntax_is_cloudflare_pages_compatible() -> None:
    """Keep site/_redirects parseable by Cloudflare Pages.

    Host-level canonicalization belongs in Cloudflare Redirect Rules, not in
    Pages `_redirects`, because Pages sources are path-only.
    """
    allowed_statuses = {"200", "301", "302", "303", "307", "308", "404"}
    offenders: list[str] = []
    for lineno, line in enumerate(REDIRECTS.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) not in (2, 3):
            offenders.append(f"{lineno}: expected 2 or 3 fields")
            continue
        source = parts[0]
        if not source.startswith("/"):
            offenders.append(f"{lineno}: source must be a path")
        if "://" in source or source.startswith("//"):
            offenders.append(f"{lineno}: source must not be host-level")
        if len(parts) == 3 and parts[2] not in allowed_statuses:
            offenders.append(f"{lineno}: unsupported status {parts[2]}")
        if "www.jpcite.com" in stripped:
            offenders.append(f"{lineno}: www canonicalization belongs in Cloudflare Redirect Rules")

    assert offenders == [], "\n".join(offenders)


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


def _public_sales_surfaces() -> list[Path]:
    paths = set(PUBLIC_SALES_SURFACE_PATHS)
    for pattern in PUBLIC_SALES_SURFACE_GLOBS:
        paths.update(REPO_ROOT.glob(pattern))
    return sorted(path for path in paths if path.exists())


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

    assert offenders == [], "\n".join(offenders)


def test_common_docs_audience_page_is_real_not_redirected() -> None:
    redirects = REDIRECTS.read_text(encoding="utf-8")

    assert (REPO_ROOT / "site" / "docs" / "getting-started" / "audiences" / "index.html").exists()
    assert "/docs/getting-started/audiences/  /audiences/  301" not in redirects
    assert "/docs/getting-started/audiences   /audiences/  301" not in redirects


def test_common_docs_audience_page_keeps_mkdocs_search_runtime() -> None:
    body = (
        REPO_ROOT / "site" / "docs" / "getting-started" / "audiences" / "index.html"
    ).read_text(encoding="utf-8")

    assert 'data-md-component="search-query"' in body
    assert '"search": "../../assets/javascripts/workers/search' in body
    assert (REPO_ROOT / "site" / "docs" / "search" / "search_index.json").exists()
    assert any((REPO_ROOT / "site" / "docs" / "assets" / "javascripts" / "workers").glob("search.*.min.js"))


def test_404_search_form_routes_to_playground_search() -> None:
    body = (REPO_ROOT / "site" / "404.html").read_text(encoding="utf-8")

    assert 'form action="/playground" method="get" role="search"' in body
    assert 'name="endpoint" value="programs.search"' in body
    assert 'form action="/programs/"' not in body


def test_playground_can_be_deep_linked_to_program_search_query() -> None:
    body = (REPO_ROOT / "site" / "playground.html").read_text(encoding="utf-8")

    assert "qs.get('endpoint')" in body
    assert "applyQueryParamsToCurrentEndpoint(qs)" in body
    assert "ep.id === requestedEndpoint || ep.path === requestedEndpoint" in body


def test_widget_page_uses_static_demo_and_clear_owner_billing_copy() -> None:
    body = (REPO_ROOT / "site" / "widget.html").read_text(encoding="utf-8")

    assert "wgt_live_00000000000000000000000000000000" not in body
    assert 'data-key="wgt_live_000' not in body
    assert "表示例 (静的mock)" in body
    assert "ここでは <code>wgt_live_...</code> key や" in body
    assert "<code>/v1/widget/*</code> を使わず" in body
    assert not re.search(r"(?m)^\s*<div\s+data-jpcite-widget\b", body)
    assert "サーバー/API 用の <code>am_...</code> key とは別物です" in body
    assert "課金はサイト訪問者ではなく" in body
    assert "公開API/Playgroundの匿名評価枠とは別" in body
    assert "path、query、末尾 slash は不可" in body
    assert "https://*.example.com</code> はサブドメイン用" in body
    assert "匿名 3 件/日" not in body


def test_phase_1a_public_sales_surfaces_do_not_expose_internal_progress_or_dummy_keys() -> None:
    forbidden_patterns = [
        ("dummy widget key", re.compile(r"wgt_live_000")),
        (
            "law full-text indexing progress",
            re.compile(r"本文完全索引|完全本文索引|154\s*件\s*本文|154\s*本文"),
        ),
        ("law full-text count progress", re.compile(r"うち本文索引\s*\d|本文索引\s*\d")),
        ("saturation jargon", re.compile(r"\bsaturation\b", re.IGNORECASE)),
        ("internal validation id", re.compile(r"\bDEEP-[A-Z0-9][A-Z0-9_-]*\b")),
        (
            "internal source coverage field",
            re.compile(r"\b(?:source_profile|artifact_coverage_delta|license_boundary)\b"),
        ),
    ]

    offenders: list[str] = []
    for path in _public_sales_surfaces():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in forbidden_patterns:
                if pattern.search(line):
                    offenders.append(f"{rel}:L{lineno}:{label}: {line.strip()[:180]}")

    assert offenders == [], "\n".join(offenders)


def test_phase_1a_line_waitlist_surfaces_do_not_assert_live_paid_usage() -> None:
    line_page = (REPO_ROOT / "site" / "line.html").read_text(encoding="utf-8", errors="ignore")
    waitlist_or_prelaunch = any(
        marker in line_page for marker in ["公開準備中", "提供状況", "利用開始通知"]
    )
    if not waitlist_or_prelaunch:
        return

    paid_assertions = [
        ("schema says LINE offer is in stock", re.compile(r"https://schema\.org/InStock")),
        (
            "per-question LINE charge",
            re.compile(
                r"¥3(?:\.30)?\s*/\s*(?:質問|question)|"
                r"¥3\s+per\s+question|¥3/question|1\s*質問\s*=\s*1\s*課金単位",
                re.IGNORECASE,
            ),
        ),
        (
            "post-free LINE charge",
            re.compile(
                r"(?:4\s*件目以降|4件目以降|匿名無料枠の超過後|超えたら|"
                r"beyond that|after the daily allowance).*?(?:課金|¥3|bill|pay)",
                re.IGNORECASE,
            ),
        ),
        (
            "live LINE friend-add claim",
            re.compile(
                r"友だち追加のみ|Add the LINE bot as a friend|Just add as a friend",
                re.IGNORECASE,
            ),
        ),
        ("LINE payment rail claim", re.compile(r"LINE Pay|Apple Pay|Google Pay", re.IGNORECASE)),
    ]

    offenders: list[str] = []
    for path in LINE_PUBLIC_SURFACES:
        if not path.exists():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in paid_assertions:
                if pattern.search(line):
                    offenders.append(f"{rel}:L{lineno}:{label}: {line.strip()[:180]}")

    assert offenders == [], "\n".join(offenders)


def test_public_law_count_copy_does_not_expose_internal_indexing_progress() -> None:
    banned_terms = [
        "154 件本文完全索引",
        "154 本文完全索引",
        "154 件 (率",
        "完全本文索引",
        "本文完全索引",
        "saturation",
        "登録総数",
        "飽和",
        "内部仮説",
        "本文ロード継続中",
        "ロード継続中",
        "still loading",
        "R8_DATA",
        "honest framing",
        "catalog stub",
        "subset + court cross-ref",
        "full corpus",
    ]

    offenders: list[tuple[str, str]] = []
    for path in PUBLIC_LAW_COPY_SURFACES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for term in banned_terms:
            if term in text:
                offenders.append((rel, term))

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
