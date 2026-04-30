from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REDIRECTS = REPO_ROOT / "site" / "_redirects"


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


def test_redirects_do_not_shadow_existing_program_or_qa_html_pages() -> None:
    samples = [
        next((REPO_ROOT / "site" / "programs").glob("*.html")),
        next((REPO_ROOT / "site" / "qa").glob("*/*.html")),
    ]
    paths = ["/" + sample.relative_to(REPO_ROOT / "site").as_posix() for sample in samples]

    offenders: list[tuple[str, str]] = []
    for source in _redirect_sources():
        for path in paths:
            if _redirect_source_matches(source, path):
                offenders.append((source, path))

    assert offenders == []


def test_qa_template_uses_public_links_and_search_endpoint() -> None:
    template = (REPO_ROOT / "site" / "_templates" / "qa.html").read_text(
        encoding="utf-8"
    )

    assert 'href="../' not in template
    assert "..//" not in template
    assert "/_templates/qa.html" not in template
    assert "/v1/programs?q=" not in template
    assert "/v1/programs/search?q=" in template
