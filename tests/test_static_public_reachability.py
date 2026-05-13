from __future__ import annotations

import hashlib
import json
import re
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


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs if value is not None}
        for attr in ("href", "src"):
            if attr in attr_map:
                self.links.append((tag, attr, attr_map[attr]))


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
        if 'overflow-x:auto;-webkit-overflow-scrolling:touch;' not in text:
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
    for component in status["components"].values():
        assert "error_category" in component
        if component["error_category"] is not None:
            assert re.fullmatch(r"[a-z0-9_]+", component["error_category"])


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
        (REPO_ROOT / "site" / ".well-known" / "openapi-discovery.json").read_text(
            encoding="utf-8"
        )
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
    for tier_name, spec_path in spec_paths.items():
        spec_text = spec_path.read_text(encoding="utf-8")
        spec = json.loads(spec_text)
        tier = tiers[tier_name]
        assert tier["path_count"] == len(spec["paths"])
        assert tier["size_bytes"] == spec_path.stat().st_size
        assert tier["sha256_prefix"] == hashlib.sha256(
            spec_text.encode("utf-8")
        ).hexdigest()[:16]


def test_llms_json_hashes_match_public_llms_text_files() -> None:
    manifest = json.loads(
        (REPO_ROOT / "site" / ".well-known" / "llms.json").read_text(encoding="utf-8")
    )

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
    assert any((REPO_ROOT / "site" / "docs" / "assets" / "javascripts" / "workers").glob("search.*.min.js"))


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
    assert "サーバー/API 用の <code>am_...</code> key とは別物です" in body
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
            if not exists:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: {tag}[{attr}]={raw_url} -> missing {target.relative_to(site_root)}"
                )

    assert offenders == [], "\n".join(offenders)


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


def test_sitemap_shards_only_reference_existing_static_targets() -> None:
    """Every <loc> in every sitemap shard must resolve to a file on disk.

    Drift between sitemap entries and `site/` files causes crawlers to fetch
    404s, which is logged as a soft 404 in Google Search Console and burns
    crawl budget. We map each URL back to a candidate static file using the
    same rules Cloudflare Pages applies: ``/foo`` -> ``foo.html`` or
    ``foo/index.html``; ``/foo/`` -> ``foo/index.html``.

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


def test_public_readiness_surfaces_do_not_expose_internal_or_topup_copy() -> None:
    surfaces = PUBLIC_READINESS_SURFACES + [REPO_ROOT / "site" / "assets" / "rum_funnel_collector.js"]
    banned_patterns = [
        ("legacy codename", re.compile(r"autonomath|jpintel|zeimu-kaikei", re.IGNORECASE)),
        ("internal wave marker", re.compile(r"\bWave\s*\d+|\bW[0-9]+\b")),
        ("migration marker", re.compile(r"\bmig\s*\d+", re.IGNORECASE)),
        ("topup terminology", re.compile(r"top[- ]?up", re.IGNORECASE)),
    ]
    offenders: list[str] = []

    for path in surfaces:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            for label, pattern in banned_patterns:
                if pattern.search(line):
                    offenders.append(f"{rel}:L{lineno}:{label}: {line.strip()[:180]}")

    assert offenders == [], "\n".join(offenders)
