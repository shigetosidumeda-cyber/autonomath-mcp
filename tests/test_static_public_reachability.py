from __future__ import annotations

import hashlib
import json
import re
from email.utils import parsedate_to_datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REDIRECTS = REPO_ROOT / "site" / "_redirects"
PUBLIC_DOCS = REPO_ROOT / "site" / "docs"
PAGES_WORKFLOWS = [
    REPO_ROOT / ".github" / "workflows" / "pages-preview.yml",
    REPO_ROOT / ".github" / "workflows" / "pages-regenerate.yml",
    REPO_ROOT / ".github" / "workflows" / "pages-deploy-main.yml",
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
PUBLIC_READINESS_SURFACES = [
    REPO_ROOT / "site" / "artifact.html",
    REPO_ROOT / "site" / "dashboard.html",
    REPO_ROOT / "site" / "data-freshness.html",
    REPO_ROOT / "site" / "login.html",
    REPO_ROOT / "site" / "success.html",
    REPO_ROOT / "site" / "support.html",
]
LLMS_HASH_TARGETS = {
    "llms_txt": REPO_ROOT / "site" / "llms.txt",
    "llms_full_txt": REPO_ROOT / "site" / "llms-full.txt",
    "llms_en_txt": REPO_ROOT / "site" / "llms.en.txt",
    "llms_full_en_txt": REPO_ROOT / "site" / "llms-full.en.txt",
}
PUBLIC_FACTS_REGISTRY_FILES = [
    REPO_ROOT / "site" / "data" / "facts_registry.json",
    REPO_ROOT / "site" / "data" / "facts_registry_full.json",
]
WEGENER_STATIC_UX_SURFACES = [
    REPO_ROOT / "site" / "en" / "index.html",
    REPO_ROOT / "site" / "en" / "products.html",
    REPO_ROOT / "site" / "onboarding.html",
    REPO_ROOT / "site" / "login.html",
    REPO_ROOT / "site" / "status.html",
    REPO_ROOT / "site" / "success.html",
    REPO_ROOT / "site" / "pricing.html",
    REPO_ROOT / "site" / "index.html",
    REPO_ROOT / "site" / "data-freshness.html",
]
TOP_LEVEL_CONNECT_ENTRY_SURFACES = [
    REPO_ROOT / "site" / "index.html",
    REPO_ROOT / "site" / "products.html",
    REPO_ROOT / "site" / "en" / "index.html",
    REPO_ROOT / "site" / "en" / "products.html",
]


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs if value is not None}
        for attr in ("href", "src"):
            if attr in attr_map:
                self.links.append((tag, attr, attr_map[attr]))


class _AlternateLinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.alternates: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        attr_map = {name: value for name, value in attrs if value is not None}
        rels = {value.lower() for value in attr_map.get("rel", "").split()}
        if "alternate" in rels:
            self.alternates.append(attr_map)


class _PublicCountCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self._current_key: str | None = None
        self._capture_value = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs if value is not None}
        classes = set(attr_map.get("class", "").split())
        if attr_map.get("data-stat-key") and "public-count" in classes:
            self._current_key = attr_map["data-stat-key"]
        if self._current_key and tag == "span" and "public-count-value" in classes:
            self._capture_value = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capture_value:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture_value and self._current_key:
            self.values[self._current_key] = "".join(self._chunks).strip()
            self._capture_value = False
            self._chunks = []
        if tag in {"li", "div", "section"} and self._current_key:
            self._current_key = None


def _headers_rules() -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in (REPO_ROOT / "site" / "_headers").read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[0].isspace():
            if current is not None and ":" in stripped:
                name, value = stripped.split(":", 1)
                rules[current][name] = value.strip()
            continue
        current = stripped
        rules[current] = {}
    return rules


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


def _static_target_candidates(site_root: Path, url_path: str) -> list[Path]:
    stripped = unquote(url_path).lstrip("/")
    if url_path == "/":
        return [site_root / "index.html"]
    if url_path.endswith("/"):
        return [site_root / stripped / "index.html"]
    return [
        site_root / (stripped + ".html"),
        site_root / stripped / "index.html",
        site_root / stripped,
    ]


def _static_target_exists(site_root: Path, url_path: str) -> bool:
    return any(candidate.exists() for candidate in _static_target_candidates(site_root, url_path))


def _public_sales_surfaces() -> list[Path]:
    paths = set(PUBLIC_SALES_SURFACE_PATHS)
    for pattern in PUBLIC_SALES_SURFACE_GLOBS:
        paths.update(REPO_ROOT.glob(pattern))
    return sorted(path for path in paths if path.exists())


def _docs_source_candidates(url_path: str) -> list[Path]:
    """MkDocs build output is gitignored; validate against the docs source."""
    if url_path in {"/docs", "/docs/"}:
        return [REPO_ROOT / "docs" / "index.md"]
    if not url_path.startswith("/docs/"):
        return []

    rel = url_path.removeprefix("/docs/").strip("/")
    if not rel or Path(rel).suffix:
        return []
    return [
        REPO_ROOT / "docs" / f"{rel}.md",
        REPO_ROOT / "docs" / rel / "index.md",
        REPO_ROOT / "docs" / rel / "README.md",
    ]


def _has_docs_source(url_path: str) -> bool:
    return any(path.exists() for path in _docs_source_candidates(url_path))


@lru_cache(maxsize=1)
def _generated_audience_matrix_paths() -> set[str]:
    from scripts import generate_geo_industry_pages as geo

    return {
        f"/audiences/{pref_slug}/{industry['slug']}/"
        for pref_slug, _pref_ja in geo.PREFECTURES
        for industry in geo.INDUSTRIES
    }


@lru_cache(maxsize=1)
def _sitemap_url_paths(*names: str) -> set[str]:
    paths: set[str] = set()
    for name in names:
        sitemap = REPO_ROOT / "site" / name
        if not sitemap.exists():
            continue
        text = sitemap.read_text(encoding="utf-8")
        paths.update(re.findall(r"<loc>https://jpcite\.com(/[^<]*)</loc>", text))
    return paths


@lru_cache(maxsize=1)
def _generated_program_paths() -> set[str]:
    return _sitemap_url_paths("sitemap-programs.xml")


@lru_cache(maxsize=1)
def _generated_prefecture_paths() -> set[str]:
    from scripts._pref_slugs import PREFECTURES

    return {"/prefectures/", *(f"/prefectures/{slug}/" for slug, _name in PREFECTURES)}


def _workflow_python_command_position(text: str, script: str) -> int | None:
    match = re.search(
        rf"(?m)^\s+python3?\s+{re.escape(script)}(?:\s|$)",
        text,
    )
    return match.start() if match else None


def _workflow_rsync_position(text: str) -> int | None:
    match = re.search(r"(?m)^\s+rsync\s+-a\s+--delete\b", text)
    return match.start() if match else None


@lru_cache(maxsize=1)
def _pages_workflows_generate_source_backed_targets() -> bool:
    generators = (
        "scripts/generate_program_pages.py",
        "scripts/generate_geo_industry_pages.py",
        "scripts/generate_prefecture_pages.py",
        "scripts/regen_structured_sitemap_and_llms_meta.py",
    )
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        rsync_pos = _workflow_rsync_position(text)
        if rsync_pos is None:
            return False
        for generator in generators:
            pos = _workflow_python_command_position(text, generator)
            if pos is None or pos > rsync_pos:
                return False
    return True


def _is_generated_static_target_backed_by_source(url_path: str) -> bool:
    if url_path.endswith(".html"):
        return _is_generated_static_target_backed_by_source(url_path.removesuffix(".html"))
    if _has_docs_source(url_path):
        return True
    if not _pages_workflows_generate_source_backed_targets():
        return False
    if url_path == "/sitemap-structured.xml":
        return True
    if url_path in _generated_program_paths():
        return True
    normalized = url_path if url_path.endswith("/") else f"{url_path}/"
    return (
        normalized in _generated_audience_matrix_paths()
        or normalized in _generated_prefecture_paths()
    )


def _active_status_states(body: str) -> set[str]:
    return {
        match.group("state")
        for match in re.finditer(
            r'<section\s+class="state\s+(?P<state>ok|warn|down)\s+active"\s+aria-label=',
            body,
        )
    }


def test_wegener_static_ux_audit_blockers_stay_fixed() -> None:
    offenders: list[str] = []

    for path in WEGENER_STATIC_UX_SURFACES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/dashboard.html#keys" in text or "jpcite.com/dashboard.html#keys" in text:
            offenders.append(f"{rel}: stale dashboard #keys anchor")

    for rel in ("site/en/index.html", "site/en/products.html"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if text.count("</body>") != 1 or text.count("</html>") != 1:
            offenders.append(f"{rel}: duplicate trailing document fragment")

    login = (REPO_ROOT / "site" / "login.html").read_text(encoding="utf-8", errors="ignore")
    for name in ("twitter:card", "twitter:title", "twitter:description", "twitter:image"):
        if f'<meta name="{name}"' not in login:
            offenders.append(f"site/login.html: missing {name}")

    expected_urls = {
        "site/status.html": {
            "canonical": "https://jpcite.com/status",
            "og": "https://jpcite.com/status",
            "ja": "https://jpcite.com/status",
            "en": "https://jpcite.com/en/status",
            "x-default": "https://jpcite.com/status",
        },
        "site/success.html": {
            "canonical": "https://jpcite.com/success",
            "og": "https://jpcite.com/success",
            "ja": "https://jpcite.com/success",
            "en": "https://jpcite.com/en/success",
            "x-default": "https://jpcite.com/success",
        },
    }
    for rel, expected in expected_urls.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if f'<link rel="canonical" href="{expected["canonical"]}">' not in text:
            offenders.append(f"{rel}: canonical URL shape drift")
        if f'<meta property="og:url" content="{expected["og"]}">' not in text:
            offenders.append(f"{rel}: og:url shape drift")
        for hreflang in ("ja", "en", "x-default"):
            needle = f'<link rel="alternate" hreflang="{hreflang}" href="{expected[hreflang]}">'
            if needle not in text:
                offenders.append(f"{rel}: {hreflang} alternate URL shape drift")

    for rel in ("site/pricing.html", "site/index.html", "site/data-freshness.html"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if "overflow-x:auto;-webkit-overflow-scrolling:touch;" not in text:
            offenders.append(f"{rel}: missing mobile table overflow wrapper")

    assert offenders == [], "\n".join(offenders)


def test_static_status_pages_match_machine_readable_status() -> None:
    status = json.loads((REPO_ROOT / "site" / "status" / "status.json").read_text(encoding="utf-8"))
    expected = {"ok": "ok", "degraded": "warn", "down": "down"}[status["overall"]]
    snapshot_at = status["snapshot_at"]

    for rel in ("site/status.html", "site/en/status.html"):
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert _active_status_states(body) == {expected}, rel
        assert snapshot_at in body, rel


def test_public_status_components_are_derived_from_status_snapshot() -> None:
    status = json.loads((REPO_ROOT / "site" / "status" / "status.json").read_text(encoding="utf-8"))
    components = json.loads(
        (REPO_ROOT / "site" / "status" / "status_components.json").read_text(encoding="utf-8")
    )

    assert components["snapshot_at"] == status["snapshot_at"]
    assert components["overall"] == status["overall"]
    by_id = {item["id"]: item for item in components["components"]}
    assert set(by_id) == set(status["components"])
    for component_id, source in status["components"].items():
        assert set(by_id[component_id]) == {"id", "label", "status", "last_check", "latency_ms"}
        assert by_id[component_id]["status"] == source["status"]
        assert by_id[component_id]["latency_ms"] == source["latency_ms"]
        assert by_id[component_id]["last_check"] == status["snapshot_at"]


def test_public_status_artifacts_do_not_leak_operator_internals() -> None:
    status_paths = [
        REPO_ROOT / "site" / "status" / "status.json",
        REPO_ROOT / "site" / "status" / "status_components.json",
        REPO_ROOT / "site" / "status" / "index.html",
        REPO_ROOT / "site" / "status.html",
        REPO_ROOT / "site" / "en" / "status.html",
        REPO_ROOT / "site" / "status" / "ax_5pillars.json",
    ]
    secret = "SE" + "CRET"
    key = "K" + "EY"
    token = "TO" + "KEN"
    forbidden_patterns = [
        re.compile(rf"\b[A-Z0-9_]*{secret}[A-Z0-9_]*\b"),
        re.compile(rf"\b[A-Z0-9_]*{key}[A-Z0-9_]*\b"),
        re.compile(rf"\b[A-Z0-9_]*{token}[A-Z0-9_]*\b"),
        re.compile(r"\b[A-Za-z]+Error:"),
        re.compile(r"\bTraceback\b"),
        re.compile(r"\bstack trace\b", re.IGNORECASE),
    ]

    offenders: list[tuple[str, str]] = []
    for path in status_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for pattern in forbidden_patterns:
            match = pattern.search(text)
            if match:
                offenders.append((rel, match.group(0)))

    assert offenders == []


def test_public_status_snapshot_uses_public_error_categories_only() -> None:
    status = json.loads((REPO_ROOT / "site" / "status" / "status.json").read_text(encoding="utf-8"))

    def walk(value: object, path: str = "$") -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "error":
                    hits.append(f"{path}.{key}")
                hits.extend(walk(child, f"{path}.{key}"))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                hits.extend(walk(child, f"{path}[{i}]"))
        return hits

    assert walk(status) == []
    public_categories = {
        "timeout",
        "network",
        "external_dependency_unavailable",
        "rate_limited",
        "maintenance",
        "data_stale",
    }
    for component in status["components"].values():
        assert "error_category" in component
        if component["status"] == "ok":
            assert component["error_category"] is None
        if component["error_category"] is not None:
            assert re.fullmatch(r"[a-z0-9_]+", component["error_category"])
            assert component["error_category"] in public_categories

    freshness = status["components"]["data-freshness"]
    if freshness["status"] != "ok":
        assert freshness["error_category"] == "data_stale"
        assert freshness["last_updated_at"] is not None
        assert freshness["max_age_days"] is not None


def test_public_rss_build_dates_are_valid_and_not_older_than_items() -> None:
    for rel in ("site/feed.rss", "site/status/rss.xml"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        build_match = re.search(r"<lastBuildDate>([^<]+)</lastBuildDate>", text)
        assert build_match is not None, rel
        build_raw = build_match.group(1)
        build_dt = parsedate_to_datetime(build_raw)
        assert build_raw.startswith(build_dt.strftime("%a, ")), rel

        pub_dates = []
        for raw in re.findall(r"<pubDate>([^<]+)</pubDate>", text):
            pub_dt = parsedate_to_datetime(raw)
            assert raw.startswith(pub_dt.strftime("%a, ")), f"{rel}: {raw}"
            pub_dates.append(pub_dt)
        if pub_dates:
            assert build_dt >= max(pub_dates), rel


def _rss_site_candidates(url_path: str) -> list[Path]:
    site_root = REPO_ROOT / "site"
    parsed_path = urlparse(url_path).path
    stripped = parsed_path.lstrip("/")
    if parsed_path == "/":
        return [site_root / "index.html"]
    if parsed_path.endswith("/"):
        return [site_root / stripped / "index.html"]
    if Path(stripped).suffix:
        return [site_root / stripped]
    return [site_root / f"{stripped}.html", site_root / stripped / "index.html"]


def test_public_rss_links_point_to_static_targets() -> None:
    offenders: list[str] = []
    rss_paths = [
        REPO_ROOT / "site" / "feed.rss",
        REPO_ROOT / "site" / "status" / "rss.xml",
        *sorted((REPO_ROOT / "site" / "rss").rglob("*.xml")),
    ]
    for path in rss_paths:
        text = path.read_text(encoding="utf-8")
        for url_path in re.findall(r"<link>https://jpcite\.com(/[^<]+)</link>", text):
            parsed_path = urlparse(url_path).path
            if not any(candidate.exists() for candidate in _rss_site_candidates(url_path)) and not (
                _is_generated_static_target_backed_by_source(parsed_path)
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {url_path}")
    assert offenders == []


def test_status_pages_advertise_status_rss_and_atom_feeds() -> None:
    expected = {
        "application/rss+xml": "/status/rss.xml",
        "application/atom+xml": "/status/feed.atom",
    }
    for rel in (
        "site/status.html",
        "site/status/index.html",
        "site/status/v2.html",
        "site/status/ab_test_results.html",
        "site/status/rum.html",
        "site/status/translation_review_queue.html",
        "site/en/status.html",
    ):
        collector = _AlternateLinkCollector()
        collector.feed((REPO_ROOT / rel).read_text(encoding="utf-8"))
        alternates = {
            attrs["type"]: urlparse(attrs["href"]).path
            for attrs in collector.alternates
            if attrs.get("type") in expected and attrs.get("href")
        }
        assert alternates == expected, rel


def test_status_feed_headers_keep_feeds_cacheable_and_indexable() -> None:
    headers = _headers_rules()
    expected = {
        "/status/rss.xml": "application/rss+xml; charset=utf-8",
        "/status/feed.atom": "application/atom+xml; charset=utf-8",
    }
    for route, content_type in expected.items():
        assert route in headers
        assert headers[route]["Content-Type"] == content_type
        assert headers[route]["Cache-Control"] == "public, max-age=3600"
        assert headers[route]["X-Robots-Tag"] == "index, follow"


def test_status_rss_has_incident_items_when_status_is_not_ok() -> None:
    status = json.loads((REPO_ROOT / "site" / "status" / "status.json").read_text(encoding="utf-8"))
    text = (REPO_ROOT / "site" / "status" / "rss.xml").read_text(encoding="utf-8")
    if status["overall"] == "ok":
        return

    degraded_components = [
        component_id
        for component_id, component in status["components"].items()
        if component["status"] != "ok"
    ]
    assert text.count("<item>") >= 1
    for component_id in degraded_components:
        assert f"jpcite:status:{component_id}:" in text


def test_public_frontend_discovery_links_do_not_point_at_missing_legacy_targets() -> None:
    redirects = REDIRECTS.read_text(encoding="utf-8")

    assert not re.search(r"^/sitemap-structured\.xml\s+", redirects, re.MULTILINE)
    assert (REPO_ROOT / "site" / "analytics" / "confidence_index.json").exists()

    monitoring = (REPO_ROOT / "site" / "status" / "monitoring.html").read_text(
        encoding="utf-8"
    )
    assert 'href="/v1/status' not in monitoring
    assert "https://api.jpcite.com/v1/status/" in monitoring

    aeo_dashboard = (REPO_ROOT / "site" / "status" / "aeo_dashboard.html").read_text(
        encoding="utf-8"
    )
    llms_meta = (REPO_ROOT / "site" / "llms-meta.json").read_text(encoding="utf-8")
    for text in (aeo_dashboard, llms_meta):
        assert "/legal/data_license" not in text
        assert "/licensing.html" not in text
        assert "/data-licensing.html" in text

    llms_full = (REPO_ROOT / "site" / "llms-full.txt").read_text(encoding="utf-8")
    assert "](./" not in llms_full
    assert "https://jpcite.com/openapi.json" not in (
        REPO_ROOT / "docs" / "agents.md"
    ).read_text(encoding="utf-8")


def test_status_html_renders_coarse_public_categories_only() -> None:
    body = (REPO_ROOT / "site" / "status" / "index.html").read_text(encoding="utf-8")

    assert "function detailCategory" in body
    assert "function publicErrorCategory" in body
    assert "c.details" not in body
    assert "c.error)" not in body
    assert "err=" not in body
    assert "msg.slice" not in body
    assert "TimeoutError" not in body


def test_ax_5pillars_does_not_overclaim_scoped_token_enforcement() -> None:
    payload = json.loads(
        (REPO_ROOT / "site" / "status" / "ax_5pillars.json").read_text(encoding="utf-8")
    )
    access = payload["pillars"]["Access"]
    evidence = "\n".join(access["evidence"])

    assert "scoped_api_token" not in evidence
    assert "[WARN] route_access_check" in evidence
    assert "route-level access checks are not yet broadly verified" in evidence
    assert any("route-level access checks" in item for item in access["missing_items"])


def test_openapi_discovery_tiers_match_committed_public_specs() -> None:
    discovery = json.loads(
        (REPO_ROOT / "site" / ".well-known" / "openapi-discovery.json").read_text(encoding="utf-8")
    )
    spec_paths = {
        "full": REPO_ROOT / "site" / "docs" / "openapi" / "v1.json",
        "agent": REPO_ROOT / "site" / "openapi.agent.json",
        "gpt30": REPO_ROOT / "site" / "openapi.agent.gpt30.json",
    }
    tiers = {tier["tier"]: tier for tier in discovery["tiers"]}

    assert (REPO_ROOT / "site" / "openapi" / "v1.json").read_text(encoding="utf-8") == spec_paths[
        "full"
    ].read_text(encoding="utf-8")
    assert tiers["full"]["mirror_url"] == "https://jpcite.com/openapi/v1.json"
    assert tiers["full"]["path_count"] == 302
    assert tiers["agent"]["path_count"] == 34
    assert tiers["agent"]["parent_tier"] == "full"
    assert tiers["gpt30"]["path_count"] == 30
    assert tiers["gpt30"]["parent_tier"] == "agent"
    for tier_name, spec_path in spec_paths.items():
        spec_text = spec_path.read_text(encoding="utf-8")
        spec = json.loads(spec_text)
        tier = tiers[tier_name]
        assert tier["path_count"] == len(spec["paths"])
        assert tier["size_bytes"] == spec_path.stat().st_size
        assert tier["sha256_prefix"] == hashlib.sha256(spec_text.encode("utf-8")).hexdigest()[:16]


def test_llms_json_hashes_match_public_llms_text_files() -> None:
    manifest = json.loads(
        (REPO_ROOT / "site" / ".well-known" / "llms.json").read_text(encoding="utf-8")
    )

    assert manifest["feeds"]["rss"] == "https://jpcite.com/feed.rss"
    assert manifest["feeds"]["release_rss"] == "https://jpcite.com/rss.xml"
    assert manifest["feeds"]["amendments_rss"] == "https://jpcite.com/rss/amendments.xml"
    assert manifest["content_hash"]["algorithm"] == "sha256"
    assert manifest["content_hash_md5"]["algorithm"] == "md5"
    for key, path in LLMS_HASH_TARGETS.items():
        payload = path.read_bytes()
        assert manifest["content_hash"][key] == hashlib.sha256(payload).hexdigest()
        assert manifest["content_hash_md5"][key] == hashlib.md5(payload).hexdigest()


def test_llms_meta_schema_and_file_metadata_resolve() -> None:
    site_root = REPO_ROOT / "site"
    meta = json.loads((site_root / "llms-meta.json").read_text(encoding="utf-8"))

    schema = urlparse(meta["$schema"])
    assert schema.scheme == "https"
    assert schema.netloc == "jpcite.com"
    schema_path = site_root / schema.path.lstrip("/")
    assert schema_path.exists()
    json.loads(schema_path.read_text(encoding="utf-8"))

    assert meta["total_files"] == len(meta["files"]) == 4
    assert meta["total_discovery_surfaces"] == len(meta["discovery_surfaces"]) == 4
    assert meta["total_indexed_surfaces"] == (
        meta["total_files"] + meta["total_discovery_surfaces"]
    )
    by_file = {entry["file"]: entry for entry in meta["files"]}
    assert set(by_file) == {
        "/llms.txt",
        "/llms.en.txt",
        "/llms-full.txt",
        "/llms-full.en.txt",
    }
    for public_path, entry in by_file.items():
        path = site_root / public_path.lstrip("/")
        text = path.read_text(encoding="utf-8")
        payload = path.read_bytes()
        expected_line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
        assert entry["size_bytes"] == path.stat().st_size
        assert entry["line_count"] == expected_line_count
        assert entry["content_hash_sha256"] == hashlib.sha256(payload).hexdigest()
        assert entry["anchors_total"] == len(entry["section_anchors"])
    assert meta["total_section_anchors"] == sum(
        entry["anchors_total"] for entry in meta["files"]
    )

    rendered = json.dumps(meta, ensure_ascii=False)
    assert not re.search(r"revenue model|R8 grow|cohort revenue", rendered, re.IGNORECASE)


def test_public_facts_registry_references_have_static_targets() -> None:
    for path in PUBLIC_FACTS_REGISTRY_FILES:
        assert path.exists(), path.relative_to(REPO_ROOT).as_posix()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"]
        assert payload["snapshot_at"]


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


def test_generated_program_related_links_resolve_after_static_normalization() -> None:
    """Program-page related links must resolve after .html/index normalization."""
    site_root = REPO_ROOT / "site"
    offenders: list[str] = []

    for path in sorted((site_root / "programs").glob("*.html")):
        if path.name in {"index.html", "share.html"}:
            continue
        collector = _LinkCollector()
        collector.feed(path.read_text(encoding="utf-8", errors="ignore"))
        for tag, attr, raw_url in collector.links:
            parsed = urlparse(raw_url)
            if parsed.scheme or parsed.netloc:
                continue
            if parsed.path.startswith(("/programs/", "/qa/")) and not _static_target_exists(
                site_root, parsed.path
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: {tag}[{attr}]={raw_url}"
                )
                if len(offenders) > 50:
                    offenders.append("... truncated")
                    break
        if len(offenders) > 50:
            break

    assert offenders == [], "\n".join(offenders)


def test_common_docs_audience_page_is_real_not_redirected() -> None:
    audience_html = REPO_ROOT / "site" / "docs" / "getting-started" / "audiences" / "index.html"
    if not audience_html.exists():
        pytest.skip("mkdocs build artifact, not tracked (site/docs/ in .gitignore)")
    redirects = REDIRECTS.read_text(encoding="utf-8")

    assert audience_html.exists()
    assert "/docs/getting-started/audiences/  /audiences/  301" not in redirects
    assert "/docs/getting-started/audiences   /audiences/  301" not in redirects


def test_common_docs_audience_page_keeps_mkdocs_search_runtime() -> None:
    audience_html = REPO_ROOT / "site" / "docs" / "getting-started" / "audiences" / "index.html"
    if not audience_html.exists():
        pytest.skip("mkdocs build artifact, not tracked (site/docs/ in .gitignore)")
    body = audience_html.read_text(encoding="utf-8")

    assert 'data-md-component="search-query"' in body
    assert '"search": "../../assets/javascripts/workers/search' in body
    assert (REPO_ROOT / "site" / "docs" / "search" / "search_index.json").exists()
    assert any(
        (REPO_ROOT / "site" / "docs" / "assets" / "javascripts" / "workers").glob("search.*.min.js")
    )


def test_docs_search_index_visible_snippets_do_not_expose_stale_current_doc_signals() -> None:
    search_index_path = REPO_ROOT / "site" / "docs" / "search" / "search_index.json"
    if not search_index_path.exists():
        pytest.skip("mkdocs search_index is generated after the clean checkout pytest shard")
    search_index = json.loads(search_index_path.read_text(encoding="utf-8"))
    docs = search_index["docs"]
    visible_snippets = "\n".join(
        f"{entry.get('title', '')}\n{entry.get('text', '')}" for entry in docs
    )

    stale_current_doc_signals = [
        "/v1/healthz",
        "182 paths",
        "/v0.3",
        "v0.3 path",
    ]
    offenders = [
        signal for signal in stale_current_doc_signals if signal in visible_snippets
    ]

    stale_recipe_tool_count = re.compile(
        r"(?:\b139\b.{0,40}\b(?:tools?|MCP tools?)\b|"
        r"\b(?:tools?|MCP tools?)\b.{0,40}\b139\b|"
        r"\b139\b.{0,40}ツール|ツール.{0,40}\b139\b)",
        re.IGNORECASE,
    )
    for entry in docs:
        location = entry.get("location", "")
        if not location.startswith(("recipes/r16", "recipes/r18", "recipes/r19")):
            continue
        visible = f"{entry.get('title', '')}\n{entry.get('text', '')}"
        if stale_recipe_tool_count.search(visible):
            offenders.append(f"{location}: stale recipe tool count 139")

    assert offenders == []


def test_404_search_form_routes_to_playground_search() -> None:
    body = (REPO_ROOT / "site" / "404.html").read_text(encoding="utf-8")

    assert 'form action="/playground" method="get" role="search"' in body
    assert 'name="endpoint" value="programs.search"' in body
    assert 'form action="/programs/"' not in body


def test_playground_can_be_deep_linked_to_program_search_query() -> None:
    body = (REPO_ROOT / "site" / "playground.html").read_text(encoding="utf-8")
    runtime = body
    bundle = REPO_ROOT / "site" / "assets" / "playground.bundle.js"
    if '<script src="/assets/playground.bundle.js" defer></script>' in body:
        assert bundle.exists()
        runtime += "\n" + bundle.read_text(encoding="utf-8")

    assert "qs.get('endpoint')" in runtime
    assert "applyQueryParamsToCurrentEndpoint(qs)" in runtime
    assert "ep.id === requestedEndpoint || ep.path === requestedEndpoint" in runtime


def test_widget_page_uses_static_demo_and_clear_owner_billing_copy() -> None:
    body = (REPO_ROOT / "site" / "widget.html").read_text(encoding="utf-8")

    assert "wgt_live_00000000000000000000000000000000" not in body
    assert 'data-key="wgt_live_000' not in body
    assert "相談前プレ診断の表示例" in body
    assert "ここではブラウザ用キー (<code>wgt_live_...</code>) や" in body
    assert "<code>/v1/widget/*</code> を使わず" in body
    assert not re.search(r"(?m)^\s*<div\s+data-jpcite-widget\b", body)
    assert "サーバー/API 用の <code>jc_...</code> key とは別物です" in body
    assert "課金はサイト訪問者ではなく" in body
    assert "公開API/Playgroundの匿名評価枠とは別" in body
    assert "path、query、末尾 slash は不要" in body
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


def test_home_and_products_surface_expanded_outputs_to_frontend() -> None:
    """The public frontend must explain expanded API/MCP work as user outputs."""
    home = (REPO_ROOT / "site" / "index.html").read_text(encoding="utf-8")
    products = (REPO_ROOT / "site" / "products.html").read_text(encoding="utf-8")
    en_home = (REPO_ROOT / "site" / "en" / "index.html").read_text(encoding="utf-8")
    en_products = (REPO_ROOT / "site" / "en" / "products.html").read_text(encoding="utf-8")
    about = (REPO_ROOT / "site" / "about.html").read_text(encoding="utf-8")
    facts = (REPO_ROOT / "site" / "facts.html").read_text(encoding="utf-8")
    playground = (REPO_ROOT / "site" / "playground.html").read_text(encoding="utf-8")
    en_playground = (REPO_ROOT / "site" / "en" / "playground.html").read_text(encoding="utf-8")

    assert "v0.4.0 output surface" in home
    assert "増えた機能は、12 種類の「保存できるアウトプット」" in home
    assert "AI が読む前の制度データ圧縮レイヤー" in home
    assert ">302</p>" in home

    required_outputs = [
        "Evidence Packet",
        "会社フォルダ",
        "M&A DD / 取引先公開情報チェック",
        "顧問先月次レビュー",
        "Application Evidence Pack / 申請前整理",
        "Funding Compatibility / 資金併用チェック",
        "インボイス取引先確認表",
        "Funding Traceback / Source Receipt",
        "法令・判例引用候補",
        "改正・保存検索通知",
        "費用・支払い制御",
        "Agent handoff",
    ]
    for label in required_outputs:
        assert label in home
        assert label in products

    assert "REST / MCP / OpenAPI Actions / Widget / Webhook / dataset は実行手段です" in products
    assert "拡張されたアウトプット一覧" in products
    assert "context-compression layer before an AI reads Japanese institutional evidence" in en_home
    assert "REST, MCP, OpenAPI Actions, widgets, webhooks, and datasets are entry surfaces" in en_products
    for label in [
        "Evidence Packet",
        "Company Folder",
        "M&A DD / Public-info Check",
        "Monthly Client Review",
        "Application Evidence Pack",
        "Funding Compatibility",
        "Invoice Counterparty Check",
        "Funding Traceback / Source Receipt",
        "Law / Case Citation Candidates",
        "Amendment/Saved Search Alerts",
        "Cost/Payment Control",
        "Agent Handoff",
    ]:
        assert label in en_home
        assert label in en_products
    assert en_playground.count("</html>") == 1
    assert not en_playground.split("</html>", 1)[1].strip()
    assert '<span class="num">151</span><span class="lbl">AI から呼べる MCP ツール</span>' in about
    assert '<span class="num">302</span><span class="lbl">REST paths (OpenAPI)</span>' in about
    assert '"endpoint_catalog_paths", "value": 302' in playground
    assert "v0.4.0 (public runtime cohort=151)" in facts


def test_expanded_output_surface_is_visible_before_lower_page_sections() -> None:
    """Counts, outputs, and setup paths must be visible near top-level entry surfaces."""
    surfaces = {
        "site/index.html": {
            "marker": '<section aria-labelledby="hero-industry-title"',
            "required": [
                "AI が読む前の制度データ圧縮レイヤー",
                "v0.4.0 output surface",
                "/connect/",
                "AI agent dev: 接続ガイド",
            ],
            "outputs": [
                "Evidence Packet",
                "会社フォルダ",
                "M&A DD / 取引先公開情報チェック",
                "顧問先月次レビュー",
                "Application Evidence Pack / 申請前整理",
                "Funding Compatibility / 資金併用チェック",
                "インボイス取引先確認表",
                "Funding Traceback / Source Receipt",
                "法令・判例引用候補",
                "改正・保存検索通知",
                "費用・支払い制御",
                "Agent handoff",
            ],
        },
        "site/products.html": {
            "marker": '<section aria-labelledby="cards-title"',
            "required": [
                "REST / MCP / OpenAPI Actions / Widget / Webhook / dataset は実行手段です",
                "接続・インストール",
                "/connect/",
                "/pricing.html#api-paid",
                "/playground.html?flow=evidence3",
            ],
            "outputs": [
                "Evidence Packet",
                "会社フォルダ",
                "M&A DD / 取引先公開情報チェック",
                "顧問先月次レビュー",
                "Application Evidence Pack / 申請前整理",
                "Funding Compatibility / 資金併用チェック",
                "インボイス取引先確認表",
                "Funding Traceback / Source Receipt",
                "法令・判例引用候補",
                "改正・保存検索通知",
                "費用・支払い制御",
                "Agent handoff",
            ],
        },
        "site/en/products.html": {
            "marker": '<section aria-labelledby="compare-title"',
            "required": [
                "context-compression layer before an AI reads Japanese institutional evidence",
                "Connect/install paths",
                "../connect/",
                "getting-started.html",
                "playground.html?flow=evidence3",
            ],
            "outputs": [
                "Evidence Packet",
                "Company Folder",
                "M&A DD / Public-info Check",
                "Monthly Client Review",
                "Application Evidence Pack",
                "Funding Compatibility",
                "Invoice Counterparty Check",
                "Funding Traceback / Source Receipt",
                "Law / Case Citation Candidates",
                "Amendment/Saved Search Alerts",
                "Cost/Payment Control",
                "Agent Handoff",
            ],
        },
    }

    stale_patterns = [
        ("stale REST count", re.compile(r"\b182\s+paths\b", re.IGNORECASE)),
        ("stale MCP count", re.compile(r"\b139\b.{0,40}\b(?:tools?|MCP tools?)\b", re.IGNORECASE)),
        ("stale version path", re.compile(r"/v0\.3|v0\.3 path", re.IGNORECASE)),
    ]
    offenders: list[str] = []
    for rel, expectation in surfaces.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        marker = expectation["marker"]
        assert marker in text, f"{rel}: marker {marker!r} missing"
        first_page = text.split(marker, 1)[0]
        for snippet in expectation["required"] + expectation["outputs"]:
            if snippet not in first_page:
                offenders.append(f"{rel}: first-page surface missing {snippet!r}")
        for label, pattern in stale_patterns:
            if pattern.search(first_page):
                offenders.append(f"{rel}: {label}")

    assert offenders == [], "\n".join(offenders)


def test_top_level_public_entry_surfaces_use_connect_chooser_for_agent_setup() -> None:
    """Keep public agent setup CTAs pointed at the multi-client chooser."""
    offenders: list[str] = []
    forbidden_phrase = "34 paths agent-safe subset"

    for path in TOP_LEVEL_CONNECT_ENTRY_SURFACES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        collector = _LinkCollector()
        collector.feed(text)
        hrefs = [value for _tag, attr, value in collector.links if attr == "href"]

        if not any(href in {"/connect/", "../connect/"} for href in hrefs):
            offenders.append(f"{rel}: missing multi-client chooser link")

        for href in hrefs:
            parsed_path = urlparse(href).path
            if parsed_path.startswith("/integrations/") or parsed_path.startswith("../integrations/"):
                offenders.append(f"{rel}: setup CTA still points to {href}")

        if forbidden_phrase in text.lower():
            offenders.append(f"{rel}: mentions {forbidden_phrase!r}")

    assert offenders == [], "\n".join(offenders)


def test_key_public_pages_do_not_use_req_price_shorthand() -> None:
    targets = [
        "site/index.html",
        "site/pricing.html",
        "site/products.html",
        "site/connect/index.html",
        "site/connect/chatgpt.html",
        "site/success.html",
        "site/en/success.html",
        "site/playground.html",
    ]
    forbidden = ["¥3/req", "¥3/request", "¥3.30/req", "¥3 / req", "¥3 per request"]
    offenders: list[str] = []
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                offenders.append(f"{rel}: {token}")

    assert offenders == []


def test_tos_hardening_covers_evidence_billing_and_external_costs() -> None:
    jp = (REPO_ROOT / "site" / "tos.html").read_text(encoding="utf-8")
    en = (REPO_ROOT / "site" / "en" / "tos.html").read_text(encoding="utf-8")

    for snippet in (
        "最終改定日: 2026-05-14",
        "evidence/output API",
        "Evidence Packet / output artifact",
        "外部 LLM 等の費用",
        "費用が実際に削減されることを保証しません",
        "課金契約の解約には該当しません",
        "source_fetched_at",
        "登録済み利用者向けの別個の無料 bundle はありません",
    ):
        assert snippet in jp

    for snippet in (
        "Last updated: 2026-05-14",
        "Japanese public-record evidence/output API",
        "Evidence Packet / output artifact",
        "External Provider Charges",
        "does not guarantee that use of the Service will actually reduce",
        "does not constitute billing cancellation",
        "known_gaps",
        "registered users do not receive a separate free request bundle",
    ):
        assert snippet in en

    forbidden = [
        "Stripe Customer Portal からクレジットカードを削除し、または当社ダッシュボードから API キーを無効化することにより",
        "本サービスは情報検索です。",
        "Charges are calculated on a per-request basis.",
        "JPY 3 per request",
        "Subject to completion of payment in accordance with Section 9",
    ]
    offenders = []
    for rel in ("site/tos.html", "site/en/tos.html"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for snippet in forbidden:
            if snippet in text:
                offenders.append(f"{rel}: stale legal copy {snippet!r}")

    assert offenders == []


def test_public_legal_support_surfaces_match_metered_tos() -> None:
    targets = {
        "site/tokushoho.html": [
            "1 billable unit あたり",
            "batch/export/fanout",
            "Stripe Customer Portal からサブスクリプションをキャンセル",
        ],
        "site/en/tokushoho.html": [
            "JPY 3 per billable unit tax exclusive",
            "API key deletion or rotation is not billing cancellation",
            "Statutory cooling-off does not apply to this online service",
        ],
        "site/support.html": [
            "API キーの無効化だけでは有償利用の解約にはなりません",
            "evidence/output API",
            "保証しません",
        ],
        "docs/compliance/terms_of_service.md": [
            "**最終改訂日**: 2026-05-14",
            "Evidence Packet / output artifact",
            "課金契約の解約には該当しません",
            "外部 LLM 等の費用を制限または保証するものではありません",
        ],
        "site/legal-fence.html": [
            "公的根拠情報の evidence/output",
            "税務 / 法律 / 申請 / 監査 / 登記 / 労務 / 知財 / 労基",
        ],
        "site/en/legal-fence.html": [
            "The 8 statutory fences",
            "public-source Evidence Packets and output artifacts",
            "patent-attorney, and labor-standards domains",
        ],
    }
    offenders = []
    for rel, snippets in targets.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                offenders.append(f"{rel}: missing {snippet!r}")
        if "匿名 3 リクエスト/日/IP の利用に戻ります" in text:
            offenders.append(f"{rel}: cancellation implies immediate anonymous fallback")

    assert offenders == []


def test_static_sitemap_includes_public_legal_surfaces() -> None:
    sitemap = (REPO_ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
    for loc in (
        "https://jpcite.com/tos",
        "https://jpcite.com/en/tos",
        "https://jpcite.com/tokushoho",
        "https://jpcite.com/en/tokushoho",
        "https://jpcite.com/legal-fence",
        "https://jpcite.com/en/legal-fence",
    ):
        assert f"<loc>{loc}</loc>" in sitemap
    assert '<xhtml:link rel="alternate" hreflang="en" href="https://jpcite.com/en/tokushoho"/>' in sitemap
    assert '<xhtml:link rel="alternate" hreflang="en" href="https://jpcite.com/en/legal-fence"/>' in sitemap
    assert "<lastmod>2026-05-14</lastmod>" in sitemap


def test_connect_chooser_is_rich_enough_for_agent_setup() -> None:
    text = (REPO_ROOT / "site" / "connect" / "index.html").read_text(encoding="utf-8")
    for href in (
        "/connect/claude-code.html",
        "/connect/cursor.html",
        "/connect/chatgpt.html",
        "/connect/codex.html",
    ):
        assert f'href="{href}"' in text
    for snippet in (
        "Claude",
        "Cursor",
        "ChatGPT",
        "Codex",
        "MCP",
        "OpenAPI",
        "X-API-Key",
        "8 業法",
        "Evidence Packet",
        "会社フォルダ",
        "M&A DD / 取引先公開情報チェック",
    ):
        assert snippet in text
    assert "/pricing.html#api-paid" in text
    assert "/legal-fence.html" in text


def test_chatgpt_connect_page_uses_x_api_key_and_gpt30_hierarchy() -> None:
    text = (REPO_ROOT / "site" / "connect" / "chatgpt.html").read_text(encoding="utf-8")
    assert "https://jpcite.com/openapi.agent.gpt30.json" in text
    assert "30 paths" in text or "30 path" in text
    assert "302" in text and "34" in text and "30" in text
    assert "X-API-Key" in text
    assert "Header name: X-API-Key" in text
    assert "Auth Type: Bearer" not in text
    assert "Bearer API Key" not in text


def test_success_page_mcp_config_uses_autonomath_package_name() -> None:
    text = (REPO_ROOT / "site" / "success.html").read_text(encoding="utf-8")
    assert "autonomath-mcp" in text
    assert '"args": ["autonomath-mcp"]' in text
    assert "jpcite-mcp" not in text


def test_products_output_entries_have_fragment_ids_and_ctas() -> None:
    text = (REPO_ROOT / "site" / "products.html").read_text(encoding="utf-8")
    expected_ids = [
        "evidence-packet",
        "company-folder",
        "public-dd",
        "monthly-review",
        "application-strategy-pack",
        "compatibility-check",
        "invoice-counterparty",
        "source-receipt",
        "citation-candidates",
        "alerts",
        "payment-control",
        "agent-handoff",
    ]
    for fragment in expected_ids:
        assert f'id="{fragment}"' in text
        assert f"https://jpcite.com/products#{fragment}" in text
    assert text.count('<article class="price-card"') == 12
    assert text.count('<a class="btn btn-secondary"') >= 12


def test_expanded_output_ctas_land_on_visible_or_interactive_surfaces() -> None:
    products = (REPO_ROOT / "site" / "products.html").read_text(encoding="utf-8")
    en_products = (REPO_ROOT / "site" / "en" / "products.html").read_text(encoding="utf-8")
    en_home = (REPO_ROOT / "site" / "en" / "index.html").read_text(encoding="utf-8")
    en_playground = (REPO_ROOT / "site" / "en" / "playground.html").read_text(encoding="utf-8")
    prompt_hub = (REPO_ROOT / "site" / "prompts" / "index.html").read_text(encoding="utf-8")
    playground = (REPO_ROOT / "site" / "playground.html").read_text(encoding="utf-8")

    hidden_dashboard_fragments = (
        "dashboard.html#saved-searches",
        "dashboard.html#dash2-alerts",
        "dashboard.html#dash2-webhooks",
    )
    for fragment in hidden_dashboard_fragments:
        assert fragment not in products
        assert fragment not in en_products
    assert "/dashboard.html#dashboard-workflows-title" in products
    assert "/en/dashboard.html#dashboard-workflows-title" in en_products

    assert 'href="playground.html?flow=evidence3"' not in en_home
    assert 'href="playground.html?flow=evidence3"' not in en_products
    assert 'href="/playground.html?flow=evidence3"' in en_home
    assert 'href="/en/playground.html?flow=evidence3"' in en_products
    assert "https://jpcite.com/playground.html?flow=evidence3" in en_playground

    assert "/products.html#" not in prompt_hub
    assert "/products#evidence-packet" in prompt_hub
    assert "/products#public-dd" in prompt_hub

    assert "Authorization: Bearer" not in playground
    assert "X-API-Key" in playground


def test_agent_connect_and_prompt_hubs_are_in_primary_navigation() -> None:
    targets = [
        "site/index.html",
        "site/products.html",
        "site/pricing.html",
        "site/dashboard.html",
        "site/support.html",
        "site/playground.html",
        "site/about.html",
    ]
    offenders: list[str] = []
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        nav_match = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', text, re.DOTALL)
        if not nav_match:
            offenders.append(f"{rel}: missing primary nav")
            continue
        nav = nav_match.group(1)
        for href in ('href="/connect/"', 'href="/prompts/"'):
            if href not in nav:
                offenders.append(f"{rel}: missing {href}")

    assert offenders == []


def test_common_jsonld_offer_catalog_lists_all_eight_outputs() -> None:
    source_targets = ["site/_assets/jsonld/_common.json"]
    required = [
        "Evidence Packet",
        "Company Folder",
        "M&A DD / Public-info Check",
        "Monthly Client Review Evidence",
        "Application Evidence Pack",
        "Funding Compatibility",
        "Invoice Counterparty Check",
        "Funding Traceback / Source Receipt",
        "Amendment and Saved Search Alerts",
        "Cost and Payment Control",
        "Agent Handoff",
    ]
    for rel in source_targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for label in required:
            assert label in text, f"{rel}: missing {label}"
        assert "Company Folder Pack" not in text
        assert "Pre-Consult Triage" not in text
        assert '"Public-info DD"' not in text
        assert '"Application Strategy Pack"' not in text

    injected_targets = [
        "site/index.html",
        "site/dashboard.html",
        "site/playground.html",
        "site/en/support.html",
    ]
    for rel in injected_targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert "M&A DD / Public-info Check" in text
        assert "Application Evidence Pack" in text
        assert "Monthly Client Review Evidence" in text
        assert "Funding Traceback / Funding Traceback" not in text
        assert '"Public-info DD"' not in text
        assert '"Application Strategy Pack"' not in text

    generated_targets = [
        "site/prefectures/index.html",
        "site/prefectures/tokyo.html",
        "site/cross/tokyo/index.html",
        "site/industries/P/index.html",
    ]
    for rel in generated_targets:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "M&A DD / Public-info Check" in text
        assert "Application Evidence Pack" in text
        assert "Monthly Client Review Evidence" in text
        assert "Funding Traceback / Funding Traceback" not in text
        assert '"Public-info DD"' not in text
        assert '"Application Strategy Pack"' not in text


def test_primary_public_chrome_uses_canonical_logo_and_nowrap_nav() -> None:
    pages = [
        "site/index.html",
        "site/products.html",
        "site/pricing.html",
        "site/connect/index.html",
        "site/connect/claude-code.html",
        "site/connect/cursor.html",
        "site/connect/chatgpt.html",
        "site/connect/codex.html",
        "site/prompts/index.html",
    ]
    offenders: list[str] = []
    for rel in pages:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if '<header class="site-header"' not in text:
            offenders.append(f"{rel}: missing canonical site-header")
        if "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: missing canonical logo lockup")
        if '<span class="brand-mark">jp</span>' in text:
            offenders.append(f"{rel}: still uses legacy jp mark")
        if 'href="/connect/"' not in text or 'href="/prompts/"' not in text:
            offenders.append(f"{rel}: missing connect/prompts nav")
        if "footer-brand-mark" not in text:
            offenders.append(f"{rel}: missing footer brand mark")

    css = (REPO_ROOT / "site" / "styles.src.css").read_text(encoding="utf-8")
    assert re.search(r"\.site-nav\s*\{[^}]*flex-wrap:\s*nowrap", css, re.S)
    assert re.search(r"\.site-nav\s*\{[^}]*white-space:\s*nowrap", css, re.S)
    assert re.search(r"\.site-nav\s*\.lang-switch\s*\{[^}]*position:\s*static", css, re.S)
    assert "footer-brand-mark" in css
    assert '-webkit-mask: url("/assets/brand/jpcite-mark-light-fill.svg")' in css
    assert 'mask: url("/assets/brand/jpcite-mark-light-fill.svg")' in css
    assert "jpcite-mark.svg" not in css
    assert ".brand-name" not in css
    assert offenders == []


def test_top_level_static_pages_do_not_drift_from_public_chrome() -> None:
    offenders: list[str] = []
    pages = set((REPO_ROOT / "site").glob("*.html"))
    pages.update((REPO_ROOT / "site").glob("*/index.html"))
    for path in sorted(pages):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '<header class="site-header"' not in text:
            offenders.append(f"{rel}: missing canonical site-header")
        if "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: missing canonical logo lockup")
        nav_match = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', text, re.S)
        if not nav_match:
            offenders.append(f"{rel}: missing primary site-nav")
        else:
            nav = nav_match.group(1)
            for href in ('href="/connect/"', 'href="/prompts/"'):
                if href not in nav:
                    offenders.append(f"{rel}: missing {href}")
        if '<span class="brand-mark">jp</span>' in text:
            offenders.append(f"{rel}: still uses legacy jp mark")
        if '<footer class="site-footer"' not in text:
            offenders.append(f"{rel}: missing site-footer")
        elif "footer-brand-mark" not in text:
            offenders.append(f"{rel}: missing footer brand mark")

    assert offenders == []


def test_nested_audience_pages_do_not_regress_to_legacy_chrome_or_program_endpoint() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "site" / "audiences").glob("*/*/index.html")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '<a class="brand" href="/" aria-label="jpcite ホーム">jpcite</a>' in text:
            offenders.append(f"{rel}: legacy text-only logo")
        if "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: missing canonical logo lockup")
        if "/v1/programs?prefecture=" in text:
            offenders.append(f"{rel}: uses legacy /v1/programs query example")
        if 'href="/pricing.html#api-paid">API キー発行' not in text:
            offenders.append(f"{rel}: API key CTA does not point to pricing paid anchor")
    assert offenders == []


def test_enforcement_pages_do_not_regress_to_legacy_chrome() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "site" / "enforcement").glob("*.html")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '<a class="brand" href="/" aria-label="jpcite ホーム">jpcite</a>' in text:
            offenders.append(f"{rel}: legacy text-only logo")
        if '<header class="site-header"' in text and "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: missing canonical logo lockup")
        if '<header class="site-header"' in text and 'class="lang-switch"' not in text:
            offenders.append(f"{rel}: missing JP/EN language switch")
        if "footer-brand-mark" not in text:
            offenders.append(f"{rel}: missing footer brand mark")
    assert offenders == []


def test_generators_emit_current_public_chrome_when_regenerated() -> None:
    template_backed_generators = {
        "scripts/generate_industry_program_pages.py": "site/_templates/industry_program.html",
        "scripts/generate_program_pages.py": "site/_templates/program.html",
        "scripts/generate_prefecture_pages.py": "site/_templates/prefecture.html",
    }
    generator_paths = [
        "scripts/build_root_indexes.py",
        "scripts/generate_case_pages.py",
        "scripts/generate_city_pages.py",
        "scripts/generate_compare_pages.py",
        "scripts/generate_cross_hub_pages.py",
        "scripts/generate_geo_citation_pages.py",
        "scripts/generate_geo_industry_pages.py",
        "scripts/generate_industry_hub_pages.py",
        "scripts/generate_industry_program_pages.py",
        "scripts/generate_public_counts.py",
        "scripts/generate_program_pages.py",
        "scripts/generate_prefecture_pages.py",
        "scripts/generate_enforcement_pages.py",
        "scripts/etl/generate_enforcement_seo_pages.py",
    ]
    forbidden = [
        '<a class="brand" href="/" aria-label="jpcite ホーム">jpcite</a>',
        '<a href="/" class="logo">jpcite</a>',
        '<a class="logo" href="/">jpcite</a>',
        '<p class="footer-brand">jpcite</p>',
        '<p class="footer-tag">日本の制度 API</p>',
        "制度データ提供: jpcite",
        "&copy; 2026 jpcite",
        '<footer class="site-footer"><div class="container"><p>',
        '<span class="brand-mark">jp</span>',
        '<span class="brand-name">jpcite</span>',
        "/assets/favicon.svg",
        "/_assets/logo.svg",
        "/assets/logo.png",
        "AutonoMath",
    ]
    required_nav_tokens = [
        'href="/connect/"',
        'href="/prompts/"',
        'href="/pricing.html"',
        'class="nav-trust"',
        'href="/status.html"',
        'class="lang-switch"',
    ]
    offenders: list[str] = []
    for rel in generator_paths:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            if pattern in text:
                offenders.append(f"{rel}: emits old chrome `{pattern}`")
        if rel in template_backed_generators:
            template_rel = template_backed_generators[rel]
            template_text = (REPO_ROOT / template_rel).read_text(encoding="utf-8", errors="ignore")
            if "footer-brand-mark" not in template_text:
                offenders.append(f"{template_rel}: template missing footer brand mark")
            if "lockup-transparent-600-darklogo.png" not in template_text:
                offenders.append(f"{template_rel}: template missing canonical logo lockup")
            continue
        if '<nav class="site-nav"' in text:
            for token in required_nav_tokens:
                if token not in text:
                    offenders.append(f"{rel}: generator nav missing {token}")
        if "footer-brand-mark" not in text:
            offenders.append(f"{rel}: generator missing footer brand mark")
        if "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: generator missing canonical logo lockup")

    for path in sorted((REPO_ROOT / "site" / "_templates").glob("*.html")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            if pattern in text:
                offenders.append(f"{rel}: template emits stale chrome/copy `{pattern}`")
        if "footer-brand-mark" not in text:
            offenders.append(f"{rel}: template missing footer brand mark")
        if "lockup-transparent-600-darklogo.png" not in text:
            offenders.append(f"{rel}: template missing canonical logo lockup")
        if "日本の公的制度を、成果物として。" not in text:
            offenders.append(f"{rel}: template missing canonical footer tag")
        if "&copy; 2026 Bookyou株式会社" not in text:
            offenders.append(f"{rel}: template missing canonical operator copyright")

    assert offenders == []


def test_public_agent_and_billing_docs_use_current_auth_and_pricing_copy() -> None:
    targets = [
        "site/manifest.webmanifest",
        "docs/agents.md",
        "docs/cookbook/r18-chatgpt-custom-gpt.md",
        "site/about.html",
    ]
    offenders: list[str] = []
    banned = [
        "¥3/req",
        "¥3/request",
        "API Key\" (Bearer)",
        "API Key (Bearer)",
        "https://api.jpcite.com/v1/openapi.agent.json?src=cookbook_r18-chatgpt-custom-gpt",
        "(¥3 / 通知)",
    ]
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for token in banned:
            if token in text:
                offenders.append(f"{rel}: {token}")
    assert "https://jpcite.com/openapi.agent.gpt30.json" in (
        REPO_ROOT / "docs" / "cookbook" / "r18-chatgpt-custom-gpt.md"
    ).read_text(encoding="utf-8")
    assert "X-API-Key" in (REPO_ROOT / "docs" / "agents.md").read_text(encoding="utf-8")
    assert offenders == []


def test_mcp_cost_examples_match_public_pricing_scenarios() -> None:
    manifest = json.loads((REPO_ROOT / "site" / ".well-known" / "mcp.json").read_text())
    pricing = (REPO_ROOT / "site" / "pricing.html").read_text(encoding="utf-8")
    examples = {item["name"]: item for item in manifest["pricing"]["cost_examples"]}

    assert "M&A DD / 取引先公開情報チェック (200社)" in examples
    public_dd = examples["M&A DD / 取引先公開情報チェック (200社)"]
    assert public_dd["req"] == 9400
    assert public_dd["jpy_inc_tax"] == 31020
    assert "M&A DD / 取引先公開情報チェック (200 社)" in pricing
    assert "9,400 req" in pricing
    assert "¥31,020" in pricing


def test_notification_surfaces_do_not_sell_per_notification_billing() -> None:
    targets = [
        "site/about.html",
        "site/line.html",
        "site/notifications.html",
        "site/en/notifications.html",
        "site/dashboard.html",
        "site/en/dashboard.html",
        "site/products.html",
        "site/en/products.html",
        "site/.well-known/mcp.json",
    ]
    banned = [
        "¥3/通知",
        "¥3 / 通知",
        "¥3/notification",
        "per notification",
        "1 notification = 1 billable unit",
        "1 通知 = 1 billable unit",
        "free for all customers",
        "No monthly cap.",
    ]
    offenders: list[str] = []
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for token in banned:
            if token in text:
                offenders.append(f"{rel}: {token}")
    assert offenders == []


def test_notifications_pages_are_live_email_channels_not_waitlist_copy() -> None:
    ja = (REPO_ROOT / "site" / "notifications.html").read_text(encoding="utf-8")
    en = (REPO_ROOT / "site" / "en" / "notifications.html").read_text(encoding="utf-8")
    for token in ("準備中", "waitlist", "line_waitlist", "LINE連携の利用開始時"):
        assert token not in ja
    for token in ("being prepared", "channel in preparation", "future notification route"):
        assert token not in en
    assert "現行の通知はメールから開始できます" in ja
    assert "Current notifications start with email" in en
    assert "saved_search_notifications" in ja


def test_new_connect_and_prompt_hubs_have_social_and_jsonld_metadata() -> None:
    expectations = {
        "site/connect/index.html": ("https://jpcite.com/connect/", "WebPage"),
        "site/prompts/index.html": ("https://jpcite.com/prompts/", "CollectionPage"),
    }
    offenders: list[str] = []
    for rel, (canonical, jsonld_type) in expectations.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for snippet in (
            f'<link rel="canonical" href="{canonical}">',
            '<meta property="og:title"',
            '<meta property="og:description"',
            '<meta property="og:type" content="website">',
            f'<meta property="og:url" content="{canonical}">',
            '<meta property="og:image"',
            '<meta name="twitter:card" content="summary_large_image">',
            '<meta name="twitter:title"',
            '<meta name="twitter:description"',
            '<meta name="twitter:image"',
            '<script type="application/ld+json">',
            f'"@type": "{jsonld_type}"',
            f'"url": "{canonical}"',
        ):
            if snippet not in text:
                offenders.append(f"{rel}: missing {snippet}")

    assert offenders == []


def test_structured_data_uses_extensionless_product_canonical_urls() -> None:
    targets = [
        "site/products.html",
        "site/pricing.html",
        "site/dashboard.html",
        "site/success.html",
    ]
    offenders: list[str] = []
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if "https://jpcite.com/products.html#" in text:
            offenders.append(f"{rel}: products.html fragment in structured data")
    products = (REPO_ROOT / "site" / "products.html").read_text(encoding="utf-8")
    assert '"url": "https://jpcite.com/pricing"' in products
    assert '"url": "https://jpcite.com/dashboard"' in products
    sitemap_source = (REPO_ROOT / "scripts" / "regen_structured_sitemap_and_llms_meta.py").read_text(
        encoding="utf-8"
    )
    assert '("/pricing", "weekly", 0.9)' in sitemap_source
    assert '("/pricing.html", "weekly", 0.9)' not in sitemap_source
    assert offenders == []


def test_catalog_api_key_issuance_ctas_point_to_pricing() -> None:
    """New API key issuance belongs on Pricing; Dashboard is existing-key management."""
    targets = [
        "site/playground.html",
        "site/programs/index.html",
        "site/laws/index.html",
        "site/enforcement/index.html",
        "site/enforcement/case-mhlw_fraud_20260331_af10b0f854.html",
    ]
    offenders: list[str] = []
    for rel in targets:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if "API キー発行" not in text:
            offenders.append(f"{rel}: missing API key issuance CTA")
        if re.search(r'href="/dashboard(?:\.html)?"[^>]*>[^<]*API キー発行', text):
            offenders.append(f"{rel}: dashboard used for new API key issuance")
        if "/pricing.html#api-paid" not in text:
            offenders.append(f"{rel}: missing pricing API key issuance target")

    assert offenders == [], "\n".join(offenders)


def test_enforcement_catalog_count_matches_runtime_case_corpus() -> None:
    text = (REPO_ROOT / "site" / "enforcement" / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "site" / ".well-known" / "mcp.json").read_text())

    assert "取得済み処分件数" in text
    assert "22,025" in text
    assert "静的詳細ページ生成数" in text
    assert "300" in text
    assert "1,485" not in text
    companion_text = json.dumps(manifest.get("resources", []), ensure_ascii=False)
    assert "1,185" in companion_text
    assert "1,485" not in companion_text


def test_public_runtime_counts_remain_visible_on_static_surfaces() -> None:
    """Keep runtime counts visible without making them the product pitch."""
    expectations = {
        "site/index.html": [
            "AI が読む前の制度データ圧縮レイヤー",
            "151 MCP ツール",
        ],
        "site/products.html": ["REST / MCP / OpenAPI Actions / Widget / Webhook / dataset は実行手段です"],
        "site/en/index.html": ["context-compression layer before an AI reads Japanese institutional evidence"],
        "site/en/products.html": ["REST, MCP, OpenAPI Actions, widgets, webhooks, and datasets are entry surfaces"],
        "site/about.html": [
            '<span class="num">151</span><span class="lbl">AI から呼べる MCP ツール</span>',
            '<span class="num">302</span><span class="lbl">REST paths (OpenAPI)</span>',
        ],
        "site/playground.html": ['"endpoint_catalog_paths", "value": 302'],
        "site/facts.html": ["v0.4.0 (public runtime cohort=151)"],
    }

    offenders: list[str] = []
    for rel, required_snippets in expectations.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for snippet in required_snippets:
            if snippet not in text:
                offenders.append(f"{rel}: missing {snippet!r}")

    assert offenders == [], "\n".join(offenders)


def test_products_page_surfaces_all_twelve_outputs() -> None:
    products = (REPO_ROOT / "site" / "products.html").read_text(encoding="utf-8")

    assert "5 つの成果物" not in products
    assert "5つの成果物" not in products

    required_outputs = [
        "Evidence Packet",
        "会社フォルダ",
        "M&A DD / 取引先公開情報チェック",
        "顧問先月次レビュー",
        "Application Evidence Pack / 申請前整理",
        "Funding Compatibility / 資金併用チェック",
        "インボイス取引先確認表",
        "Funding Traceback / Source Receipt",
        "法令・判例引用候補",
        "改正・保存検索通知",
        "費用・支払い制御",
        "Agent handoff",
    ]
    for label in required_outputs:
        assert label in products


def test_public_rss_entrypoints_are_role_specific() -> None:
    """Release, change-detection, and AI-discovery feeds must not be conflated."""
    home = (REPO_ROOT / "site" / "index.html").read_text(encoding="utf-8")
    en_home = (REPO_ROOT / "site" / "en" / "index.html").read_text(encoding="utf-8")
    monitoring = (REPO_ROOT / "site" / "status" / "monitoring.html").read_text(encoding="utf-8")
    news = (REPO_ROOT / "site" / "news" / "index.html").read_text(encoding="utf-8")
    llms = (REPO_ROOT / "site" / "llms.txt").read_text(encoding="utf-8")
    feeds = json.loads((REPO_ROOT / "site" / "assets" / "rss-feeds.json").read_text(encoding="utf-8"))

    assert 'title="jpcite お知らせ・リリース" href="/rss.xml"' in home
    assert 'title="jpcite お知らせ・リリース (Japanese)" href="/rss.xml"' in en_home
    assert 'title="jpcite — status RSS" href="/status/rss.xml"' in monitoring
    assert 'title="jpcite — 監視 alert feed" href="/status/feed.atom"' in monitoring
    assert 'href="https://jpcite.com/rss/amendments.xml"' in news
    assert '<a href="/rss/amendments.xml">/rss/amendments.xml</a>' in news

    assert "Public discovery RSS feed: https://jpcite.com/feed.rss" in llms
    assert "Announcements/release RSS feed: https://jpcite.com/rss.xml" in llms
    assert "Amendment/change-detection RSS feed: https://jpcite.com/rss/amendments.xml" in llms

    feed_urls = {feed["id"]: feed["url"] for feed in feeds["feeds"]}
    assert feed_urls["announcements"] == "https://jpcite.com/rss.xml"
    assert feed_urls["amendments"] == "https://jpcite.com/rss/amendments.xml"

    manifest = json.loads((REPO_ROOT / "site" / ".well-known" / "llms.json").read_text(encoding="utf-8"))
    assert manifest["feeds"]["rss"] == "https://jpcite.com/feed.rss"
    assert manifest["feeds"]["release_rss"] == "https://jpcite.com/rss.xml"
    assert manifest["feeds"]["amendments_rss"] == "https://jpcite.com/rss/amendments.xml"


def test_ai_discovery_surfaces_token_cost_positioning() -> None:
    llms = (REPO_ROOT / "site" / "llms.txt").read_text(encoding="utf-8")
    llms_en = (REPO_ROOT / "site" / "llms.en.txt").read_text(encoding="utf-8")
    llms_json = json.loads((REPO_ROOT / "site" / ".well-known" / "llms.json").read_text(encoding="utf-8"))
    mcp_json = json.loads((REPO_ROOT / "site" / ".well-known" / "mcp.json").read_text(encoding="utf-8"))

    for text in (llms, llms_en):
        assert "long-document AI cost" in text
        assert "compact Evidence Packet" in text
        assert "Do not claim jpcite is always cheaper" in text

    assert "token-cost control" in llms_json["description"]
    assert "long_context_rag_formula" in llms_json["cost_positioning"]
    assert "external_llm_charges" in llms_json["cost_positioning"]
    assert "token-cost control" in mcp_json["description"]
    assert "long_context_rag_formula" in mcp_json["cost_positioning"]


def test_public_html_files_do_not_have_trailing_duplicate_documents() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "site").rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        close_count = text.count("</html>")
        if close_count != 1:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: html_close={close_count}")
            continue
        if text.split("</html>", 1)[1].strip():
            offenders.append(f"{path.relative_to(REPO_ROOT)}: trailing_after_html")

    assert offenders == [], "\n".join(offenders[:200])


def test_public_html_files_do_not_reintroduce_stale_footer_brand_copy() -> None:
    offenders: list[str] = []
    forbidden = [
        '<p class="footer-tag">日本の制度 API</p>',
        "制度データ提供: jpcite",
        "&copy; 2026 jpcite",
        '<footer class="site-footer"><div class="container"><p>',
    ]
    for path in sorted((REPO_ROOT / "site").rglob("*.html")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            if pattern in text:
                offenders.append(f"{rel}: stale footer brand copy `{pattern}`")

    assert offenders == [], "\n".join(offenders[:200])


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
    /structured/ standalone shard surface is no longer published. Inbound
    crawler URLs under /structured/ are 404'd by site/_redirects.

    Note: sitemap-structured.xml is NOT the retired surface — its purpose
    has been repurposed to act as a curated "golden route" shard listing
    HTML pages that carry inline application/ld+json (see file header).
    The R5 SEO/GEO audit (2026-05-13) requires this shard to be registered
    in both robots.txt and sitemap-index.xml so crawlers can discover the
    structured-data bearing pages. Therefore the registration assertions
    that were here previously have been removed; only the
    /structured/*.jsonld standalone surface stays retired.
    """
    robots = (REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    headers = (REPO_ROOT / "site" / "_headers").read_text(encoding="utf-8")
    redirects = (REPO_ROOT / "site" / "_redirects").read_text(encoding="utf-8")

    assert "Allow: /structured/" not in robots
    assert "/structured/*.jsonld" not in headers
    # Inline JSON-LD still emits the application/ld+json mime via inline <script>
    # tags, so Content-Type registration is no longer needed in _headers.
    assert "/structured/*  /404  404" in redirects


def test_headers_json_exact_public_routes_point_to_valid_discovery_manifests() -> None:
    headers = _headers_rules()
    exact_json_routes = {
        route: route_headers
        for route, route_headers in headers.items()
        if "*" not in route
        and route_headers.get("Content-Type") == "application/json; charset=utf-8"
    }

    assert exact_json_routes
    for route, route_headers in exact_json_routes.items():
        path = REPO_ROOT / "site" / route.lstrip("/")
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))
        assert route_headers["Cache-Control"] == "public, max-age=300, s-maxage=600"
        assert route_headers["CDN-Cache-Control"] == "public, max-age=600"
        assert route_headers["Access-Control-Allow-Origin"] == "*"
        assert route_headers["Cross-Origin-Resource-Policy"] == "cross-origin"


def test_public_count_static_fallbacks_match_committed_count_data_when_present() -> None:
    counts_path = REPO_ROOT / "site" / "_data" / "public_counts.json"
    assert counts_path.exists()
    counts = json.loads(counts_path.read_text(encoding="utf-8"))

    offenders: list[str] = []
    for rel in ("site/stats.html", "site/en/stats.html"):
        collector = _PublicCountCollector()
        collector.feed((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for key, fallback in collector.values.items():
            if key not in counts:
                continue
            expected = f"{counts[key]:,}" if isinstance(counts[key], int) else str(counts[key])
            if fallback != expected:
                offenders.append(f"{rel}: {key} fallback={fallback!r} json={expected!r}")

    assert offenders == []


def test_public_copy_version_and_navigation_surfaces_are_current() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "site" / "changelog" / "index.html").read_text(encoding="utf-8")
    redirects = (REPO_ROOT / "site" / "_redirects").read_text(encoding="utf-8")
    robots = (REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    trust = json.loads((REPO_ROOT / "site" / ".well-known" / "trust.json").read_text(encoding="utf-8"))
    evolution = (REPO_ROOT / "site" / "transparency" / "evolution.html").read_text(encoding="utf-8")

    assert "v0.4.0 LIVE on Fly.io Tokyo" in readme
    assert "median 7 day freshness" not in readme
    assert "Median 7-day freshness" not in readme
    assert "最新は v0.4.0 (2026-05-12)" in changelog
    assert "v0.3.4" not in changelog
    assert "/changelog          /  301" not in redirects
    assert "/changelog/*        /  301" not in redirects
    assert "Allow: /v1/programs" not in robots
    assert "Allow: /v1/laws" not in robots
    assert "Allow: /v1/cases" not in robots
    assert "Allow: /v1/meta/federation" not in robots
    assert trust["data_provenance"]["license_review_queue_size"] == 1425
    assert "jpcite v0.4.0 evolution dashboard" in evolution


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


def test_w20_public_static_legal_claim_blockers_stay_fixed() -> None:
    onboarding = (REPO_ROOT / "site" / "onboarding.html").read_text(encoding="utf-8")
    agent_doc = (
        REPO_ROOT / "docs" / "for-agent-devs" / "why-bundle-jpcite_2026_05_11.md"
    ).read_text(encoding="utf-8")
    llms_full_en = (REPO_ROOT / "site" / "llms-full.en.txt").read_text(encoding="utf-8")
    trust = (REPO_ROOT / "site" / "trust.html").read_text(encoding="utf-8")

    assert "節約額の目安" not in onboarding
    assert "取りこぼし回避" not in onboarding
    assert "historical ROI" not in onboarding
    assert "費用の目安" in onboarding

    assert '"amount_max_jpy": 50000000' not in agent_doc
    assert "金額フィールド caveat" in agent_doc
    assert "金額条件は枠・類型で分岐" in agent_doc

    assert "latest terms" not in llms_full_en
    assert "current public jpcite dataset" not in llms_full_en
    assert "not zero funding" in llms_full_en
    assert "Do not quote an amount unless source_url confirms" in llms_full_en

    assert "最新コーパス" not in trust
    assert "表示中のコーパス スナップショット ID" in trust


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


def test_pages_artifacts_generate_source_backed_sitemap_targets_before_rsync() -> None:
    """Generated sitemap URLs must be present in every Pages artifact."""
    offenders: list[str] = []
    generators = (
        "scripts/generate_geo_industry_pages.py",
        "scripts/regen_structured_sitemap_and_llms_meta.py",
    )
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        rel = workflow.relative_to(REPO_ROOT).as_posix()
        rsync_pos = _workflow_rsync_position(text)
        if rsync_pos is None:
            offenders.append(f"{rel}: missing rsync artifact build")
            continue
        for generator in generators:
            pos = _workflow_python_command_position(text, generator)
            if pos is None:
                offenders.append(f"{rel}: missing run command for {generator}")
            elif pos > rsync_pos:
                offenders.append(f"{rel}: {generator} runs after rsync")

    assert offenders == []


def test_public_readiness_surfaces_do_not_link_to_missing_static_targets() -> None:
    site_root = REPO_ROOT / "site"
    offenders: list[str] = []

    for path in PUBLIC_READINESS_SURFACES:
        collector = _LinkCollector()
        collector.feed(path.read_text(encoding="utf-8", errors="ignore"))
        for tag, attr, raw_url in collector.links:
            parsed = urlparse(raw_url)
            if (
                parsed.scheme
                or parsed.netloc
                or raw_url.startswith(("mailto:", "tel:", "data:", "javascript:"))
            ):
                continue
            if raw_url == "#":
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {tag}[{attr}] points to #")
                continue
            if not parsed.path:
                continue

            target = (
                site_root / unquote(parsed.path).lstrip("/")
                if parsed.path.startswith("/")
                else path.parent / unquote(parsed.path)
            )
            exists = (
                target.exists()
                or (target.suffix == "" and target.with_suffix(".html").exists())
                or (target / "index.html").exists()
            )
            if not exists and _is_generated_static_target_backed_by_source(parsed.path):
                continue
            if not exists:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: {tag}[{attr}]={raw_url} -> missing {target.relative_to(site_root)}"
                )

    assert offenders == [], "\n".join(offenders)


def test_static_fragment_scan_blockers_stay_fixed() -> None:
    calculator = (REPO_ROOT / "site" / "calculator.html").read_text(encoding="utf-8")
    prefecture_template = (
        REPO_ROOT / "site" / "_templates" / "prefecture_index.html"
    ).read_text(encoding="utf-8")
    smb = (REPO_ROOT / "site" / "audiences" / "smb.html").read_text(encoding="utf-8")
    share = (REPO_ROOT / "site" / "programs" / "share.html").read_text(encoding="utf-8")

    assert 'aria-describedby="clients-hint"' in calculator
    assert 'id="clients-hint"' in calculator
    assert 'aria-labelledby="region-{{loop.index}}-title"' in prefecture_template
    assert 'id="region-{{loop.index}}-title"' in prefecture_template
    assert "{{ loop.index }}" not in prefecture_template
    assert 'href="/audiences/smb.html#tax-advisor-handoff"' in share
    assert 'id="tax-advisor-handoff"' in smb


def test_artifact_discovery_urls_point_to_static_page() -> None:
    body = (REPO_ROOT / "site" / "artifact.html").read_text(encoding="utf-8")
    head = body.split("</head>", 1)[0]
    expected = "https://jpcite.com/artifact"

    assert (REPO_ROOT / "site" / "artifact.html").exists()
    assert f'<link rel="canonical" href="{expected}">' in head
    assert f'<meta property="og:url" content="{expected}">' in head
    assert f'<link rel="alternate" hreflang="ja" href="{expected}">' in head
    assert f'<link rel="alternate" hreflang="x-default" href="{expected}">' in head
    assert "https://jpcite.com/artifacts" not in head


def test_roi_calculator_legacy_stub_targets_cost_saving_calculator() -> None:
    body = (REPO_ROOT / "site" / "roi_calculator.html").read_text(encoding="utf-8")
    head = body.split("</head>", 1)[0]
    expected = "https://jpcite.com/tools/cost_saving_calculator"
    expected_path = "/tools/cost_saving_calculator"

    assert (REPO_ROOT / "site" / "tools" / "cost_saving_calculator.html").exists()
    assert f'<meta http-equiv="refresh" content="0; url={expected_path}">' in head
    assert '<meta name="robots" content="noindex, follow">' in head
    assert f'<link rel="canonical" href="{expected}">' in head
    assert f'<meta property="og:url" content="{expected}">' in head
    assert f'<link rel="alternate" hreflang="ja" href="{expected}">' in head
    assert f'<link rel="alternate" hreflang="x-default" href="{expected}">' in head
    assert "https://jpcite.com/roi_calculator" not in head


def test_robots_sitemap_block_aligns_with_sitemap_index() -> None:
    """robots.txt Sitemap entries and sitemap-index.xml children must agree.

    Drift between robots.txt and sitemap-index.xml causes crawlers to either
    miss a shard (under-indexed) or hit a 404 (wasted crawl budget). The two
    surfaces are independently maintained by hand, so an explicit alignment
    gate stops the divergence at PR time. The only legitimate divergence is
    ``sitemap-index.xml`` itself, which is referenced from robots.txt but
    is *not* a child of itself.
    """
    site_root = REPO_ROOT / "site"
    robots = (site_root / "robots.txt").read_text(encoding="utf-8")
    sitemap_index = (site_root / "sitemap-index.xml").read_text(encoding="utf-8")

    robots_sitemaps = set(re.findall(r"^Sitemap:\s*(\S+)", robots, re.MULTILINE))
    index_sitemaps = set(re.findall(r"<loc>(\S+?)</loc>", sitemap_index))

    # sitemap-index.xml is the top-level entry point — it lists shards, it
    # does not list itself. robots.txt still advertises it.
    self_ref = "https://jpcite.com/sitemap-index.xml"
    in_robots_only = (robots_sitemaps - index_sitemaps) - {self_ref}
    in_index_only = index_sitemaps - robots_sitemaps

    assert in_robots_only == set(), (
        f"robots.txt advertises sitemaps that are not in sitemap-index.xml: "
        f"{sorted(in_robots_only)}"
    )
    assert in_index_only == set(), (
        f"sitemap-index.xml lists sitemaps that are not advertised in robots.txt: "
        f"{sorted(in_index_only)}"
    )


def test_generated_sitemap_targets_are_source_backed_before_pages_publish() -> None:
    assert _pages_workflows_generate_source_backed_targets()
    assert _is_generated_static_target_backed_by_source("/sitemap-structured.xml")
    program_paths = _generated_program_paths()
    assert program_paths
    assert _is_generated_static_target_backed_by_source(next(iter(program_paths)))
    assert _is_generated_static_target_backed_by_source("/prefectures/")
    assert _is_generated_static_target_backed_by_source("/prefectures/tokyo")
    assert not _is_generated_static_target_backed_by_source("/prefectures/not-a-pref")
    assert not _is_generated_static_target_backed_by_source("/programs/not-in-sitemap")


def test_sitemap_shards_only_reference_existing_static_targets() -> None:
    """Every <loc> must resolve to disk or a source-backed generated target.

    Drift between sitemap entries and `site/` files causes crawlers to fetch
    404s, which is logged as a soft 404 in Google Search Console and burns
    crawl budget. We map each URL back to a candidate static file using the
    same rules Cloudflare Pages applies: ``/foo`` -> ``foo.html`` or
    ``foo/index.html``; ``/foo/`` -> ``foo/index.html``.

    MkDocs output and prefecture × industry audience pages are gitignored and
    generated after the pytest shard in CI. Those URLs stay valid when their
    source docs or generator constants exist.

    External URLs (e.g. links to docs JSON / llms.txt under different roots)
    are skipped — only same-host pages are reachability-checked.
    """
    site_root = REPO_ROOT / "site"
    sitemap_shards = sorted(site_root.glob("sitemap-*.xml")) + [site_root / "sitemap.xml"]

    skip_prefixes = (
        "/data/",  # JSON data assets, often generated
        "/openapi",  # JSON spec endpoints
        "/v1/",  # live API endpoints
        "/.well-known/",  # discovery endpoints
        "/llms",  # AI surface text files
        "/server.json",
        "/mcp-server.json",
        "/humans.txt",
        "/feed.atom",
        "/feed.rss",
    )

    offenders: list[str] = []
    for shard in sitemap_shards:
        if not shard.exists():
            continue
        text = shard.read_text(encoding="utf-8")
        for url_path in re.findall(r"<loc>https://jpcite\.com(/[^<]*)</loc>", text):
            if url_path.startswith(skip_prefixes):
                continue
            stripped = url_path.lstrip("/")
            if url_path == "/":
                candidates = [site_root / "index.html"]
            elif url_path.endswith("/"):
                candidates = [site_root / stripped / "index.html"]
            else:
                candidates = [
                    site_root / (stripped + ".html"),
                    site_root / stripped / "index.html",
                    site_root / stripped,
                ]
            if not any(c.exists() for c in candidates):
                if _is_generated_static_target_backed_by_source(url_path):
                    continue
                offenders.append(f"{shard.name}: {url_path}")
                if len(offenders) > 20:
                    offenders.append("... truncated")
                    break
        if len(offenders) > 20:
            break

    assert offenders == [], "\n".join(offenders)


def test_sitemap_shards_do_not_advertise_noindex_html_pages() -> None:
    """Sitemap entries must not point at HTML pages that carry meta robots noindex.

    A noindex page in the sitemap is internally contradictory: we ask the
    crawler to fetch it, then immediately tell it not to index it. This
    burns crawl budget and confuses search-quality signals. The gate maps
    each <loc> back to a candidate HTML file using the same rules
    Cloudflare Pages applies, then scans for `<meta name="robots" ... noindex>`.
    """
    site_root = REPO_ROOT / "site"

    noindex_url_paths: set[str] = set()
    noindex_pattern = re.compile(
        r"<meta\s+name=[\"']robots[\"']\s+content=[\"'][^\"']*noindex",
        re.IGNORECASE,
    )
    for html_path in site_root.rglob("*.html"):
        try:
            text = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not noindex_pattern.search(text):
            continue
        rel = html_path.relative_to(site_root).as_posix()
        if rel == "index.html":
            noindex_url_paths.add("/")
        elif rel.endswith("/index.html"):
            base = rel[: -len("/index.html")]
            noindex_url_paths.add("/" + base + "/")
            noindex_url_paths.add("/" + base)
        else:
            noindex_url_paths.add("/" + rel)
            if rel.endswith(".html"):
                noindex_url_paths.add("/" + rel[: -len(".html")])

    offenders: list[str] = []
    sitemap_shards = sorted(site_root.glob("sitemap-*.xml")) + [site_root / "sitemap.xml"]
    for shard in sitemap_shards:
        if not shard.exists():
            continue
        text = shard.read_text(encoding="utf-8")
        for url_path in re.findall(r"<loc>https://jpcite\.com(/[^<]*)</loc>", text):
            if url_path in noindex_url_paths:
                offenders.append(f"{shard.name}: {url_path}")

    assert offenders == [], "\n".join(offenders)


def test_enforcement_pages_do_not_link_to_missing_uni_program_pages() -> None:
    """Enforcement pages must not guess slugless `/programs/UNI-*` pages.

    Static program pages are generated from SEO slugs. When only a UNI id is
    available, the safe static target is `/programs/share.html?ids=UNI-...`.
    """
    offenders: list[str] = []
    site_root = REPO_ROOT / "site"

    for html_path in sorted((site_root / "enforcement").glob("*.html")):
        collector = _LinkCollector()
        collector.feed(html_path.read_text(encoding="utf-8", errors="ignore"))
        rel = html_path.relative_to(REPO_ROOT).as_posix()
        for _tag, attr, raw_url in collector.links:
            parsed = urlparse(raw_url)
            if parsed.netloc and parsed.netloc != "jpcite.com":
                continue
            path = parsed.path
            if not path.startswith("/programs/UNI-"):
                continue
            candidates = _rss_site_candidates(path)
            if not any(candidate.exists() for candidate in candidates):
                offenders.append(f"{rel}: {attr}={raw_url}")
                if len(offenders) > 20:
                    offenders.append("... truncated")
                    break
        if len(offenders) > 20:
            break

    assert offenders == [], "\n".join(offenders)


def test_generated_enforcement_pages_do_not_link_to_law_id_static_paths() -> None:
    """Generated enforcement pages must use resolvable law slugs, not `/laws/LAW-*` ids."""
    offenders: list[str] = []
    site_root = REPO_ROOT / "site"
    law_id_url = re.compile(r"(?:https://jpcite\.com)?/laws/LAW-[A-Za-z0-9_-]+")

    for page_path in sorted((site_root / "enforcement").glob("*")):
        if page_path.suffix not in {".html", ".md"}:
            continue
        text = page_path.read_text(encoding="utf-8", errors="ignore")
        rel = page_path.relative_to(REPO_ROOT).as_posix()
        for match in law_id_url.finditer(text):
            offenders.append(f"{rel}: {match.group(0)}")
            if len(offenders) > 20:
                offenders.append("... truncated")
                break
        if len(offenders) > 20:
            break

    assert offenders == [], "\n".join(offenders)


def test_generated_law_pages_do_not_link_to_missing_uni_program_query_pages() -> None:
    """Law pages with only a UNI id must use the static share target."""
    offenders: list[str] = []
    site_root = REPO_ROOT / "site"

    for law_root in (site_root / "laws", site_root / "en" / "laws"):
        if not law_root.exists():
            continue
        for law_path in sorted(
            path for path in law_root.glob("*") if path.suffix in {".html", ".md"}
        ):
            text = law_path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'href=["\']/en/programs/\?id=UNI-', text):
                offenders.append(f"{law_path.relative_to(REPO_ROOT)}: /en/programs/?id=UNI-*")
            if re.search(r'href=["\']/programs/\?id=UNI-', text):
                offenders.append(f"{law_path.relative_to(REPO_ROOT)}: /programs/?id=UNI-*")
            if re.search(r'\]\(/en/programs/\?id=UNI-', text):
                offenders.append(f"{law_path.relative_to(REPO_ROOT)}: ](/en/programs/?id=UNI-*")
            if re.search(r'\]\(/programs/\?id=UNI-', text):
                offenders.append(f"{law_path.relative_to(REPO_ROOT)}: ](/programs/?id=UNI-*")
            if len(offenders) > 20:
                offenders.append("... truncated")
                break
        if len(offenders) > 20:
            break

    assert (site_root / "programs" / "share.html").exists()
    assert offenders == [], "\n".join(offenders)


def test_public_readiness_surfaces_do_not_expose_internal_or_topup_copy() -> None:
    surfaces = PUBLIC_READINESS_SURFACES + [
        REPO_ROOT / "site" / "assets" / "rum_funnel_collector.js"
    ]
    banned_patterns = [
        ("legacy codename", re.compile(r"autonomath|jpintel|zeimu-kaikei", re.IGNORECASE)),
        ("internal wave marker", re.compile(r"\bWave\s*\d+|\bW[0-9]+\b")),
        ("migration marker", re.compile(r"\bmig\s*\d+", re.IGNORECASE)),
        ("topup terminology", re.compile(r"top[- ]?up", re.IGNORECASE)),
    ]
    offenders: list[str] = []

    for path in surfaces:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
            ):
                for label, pattern in banned_patterns:
                    match = pattern.search(line)
                    if not match:
                        continue
                    if (
                        label == "legacy codename"
                        and match.group(0).lower() == "autonomath"
                        and "autonomath-mcp" in line
                    ):
                        continue
                    offenders.append(f"{rel}:L{lineno}:{label}: {line.strip()[:180]}")

    assert offenders == [], "\n".join(offenders)
