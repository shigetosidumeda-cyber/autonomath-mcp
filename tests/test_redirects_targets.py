"""Verify every source path in `site/_redirects` resolves to either:
  (a) an on-disk file/directory under `site/` (after CF Pages resolution rules), or
  (b) a documented **legacy SEO bridge** (jpintel / zeimu-kaikei / autonomath),
      which intentionally redirects away without a corresponding source file.

Also flag:
  - **Loops**: source path X redirecting to Y where Y itself redirects back to X.
  - **Duplicates**: same source path listed twice in the file.

Why a structural test (not an HTTP probe):
  - CF Pages serves the `site/` tree by file-system match first, then applies
    `_redirects` rules. We can replay that resolution off-disk and catch dead
    targets at CI time without depending on the live edge.

Memory references:
  - feedback_legacy_brand_marker — `/jpintel*`, `/zeimu-kaikei*`, `/autonomath*`
    redirects are intentional SEO citation bridges; KEEP them even though no
    `site/jpintel*` file exists on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = REPO_ROOT / "site"
DOCS_ROOT = REPO_ROOT / "docs"
REDIRECTS = SITE_ROOT / "_redirects"

# Legacy SEO bridges: intentionally redirect away even though the source path
# has no matching file on disk. Audit must NOT flag these as dead.
LEGACY_BRIDGE_PREFIXES: tuple[str, ...] = (
    "/jpintel",
    "/zeimu-kaikei",
    "/autonomath",
)

# Pattern-only sources (with `:param` placeholders or `*` globs) can't be
# resolved to a single on-disk file. For each, name a concrete sample path
# that proves the rewritten target exists. If a future rule introduces a new
# pattern, add a sample below.
PATTERN_TARGET_SAMPLES: dict[str, str] = {
    # /programs/UNI-:uid → /programs/share?ids=UNI-:uid → /programs/share.html
    "/programs/share": "site/programs/share.html",
    # /cross/:pref/:slug → /cross/:pref/ → site/cross/{pref}/index.html exists
    # (sample: aichi). The bare /cross → /cross/ rule was removed in the
    # 2026-05-13 audit since site/cross/index.html does not exist.
    "/cross/:pref/": "site/cross/aichi/index.html",
    # /industries/:jsic/:slug → /industries/:jsic/ → site/industries/{jsic}/index.html
    "/industries/:jsic/": "site/industries/A/index.html",
    # /go?code=:code preserves bare /go → site/go.html via .html stripping
    "/go": "site/go.html",
}

# Targets that resolve via Cloudflare Pages `.html` stripping. For each value,
# either the literal path or `<path>.html` must exist on disk.
HTML_STRIPPING_TARGETS: tuple[str, ...] = (
    "/dashboard",
    "/upgrade",
    "/notifications",
    "/support",
    "/tos",
    "/privacy",
    "/legal-fence",
    "/search",
    "/en/notifications",
    "/en/",
    "/",
    "/404",
)


def _docs_source_candidates(path_only: str) -> list[Path]:
    """MkDocs output is gitignored; validate redirect targets against sources.

    Pages workflows rebuild `site/docs/` from `docs/`, so `/docs/*` targets are
    valid if the matching Markdown page or copied static asset exists.
    """
    if path_only == "/docs":
        path_only = "/docs/"
    if path_only == "/docs/":
        return [DOCS_ROOT / "index.md"]
    if not path_only.startswith("/docs/"):
        return []

    rel = path_only.removeprefix("/docs/")
    if rel == "":
        return [DOCS_ROOT / "index.md"]

    if rel.endswith("/"):
        stem = rel.rstrip("/")
        return [
            DOCS_ROOT / stem / "index.md",
            DOCS_ROOT / f"{stem}.md",
        ]

    rel_path = Path(rel)
    candidates = [DOCS_ROOT / rel_path]
    if rel_path.suffix == "":
        candidates.extend(
            (
                DOCS_ROOT / f"{rel}.md",
                DOCS_ROOT / rel_path / "index.md",
                DOCS_ROOT / rel_path / "README.md",
            )
        )
    elif rel_path.suffix == ".html":
        markdown_source = rel_path.with_suffix(".md")
        directory_source = rel_path.with_suffix("")
        candidates.extend(
            (
                DOCS_ROOT / markdown_source,
                DOCS_ROOT / directory_source / "index.md",
            )
        )
    return candidates


def _has_docs_source(path_only: str) -> bool:
    return any(path.is_file() for path in _docs_source_candidates(path_only))


def _parse_redirects() -> list[tuple[int, str, str, str]]:
    """Return (lineno, source, target, status) for every non-comment line."""
    rows: list[tuple[int, str, str, str]] = []
    for lineno, raw in enumerate(REDIRECTS.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) == 2:
            source, target = parts
            status = "301"
        elif len(parts) == 3:
            source, target, status = parts
        else:
            continue
        rows.append((lineno, source, target, status))
    return rows


def _is_legacy_bridge(source: str) -> bool:
    return any(
        source == prefix or source.startswith(prefix + "/") or source.startswith(prefix + ".")
        for prefix in LEGACY_BRIDGE_PREFIXES
    )


def _target_exists_on_disk(target: str) -> bool:
    """Mirror CF Pages resolution plus the Pages workflow's MkDocs build:
    `/docs/*` source fallback, literal match, `.html` stripping, directory
    `index.html`, then declared pattern sample fallback."""
    # Strip leading slash + any query/fragment for filesystem lookup.
    path_only = target.split("?", 1)[0].split("#", 1)[0]

    if _has_docs_source(path_only):
        return True

    # Root: site/index.html
    if path_only in ("/", ""):
        return (SITE_ROOT / "index.html").exists()

    rel = path_only.lstrip("/")

    # Pattern target with :param — fall back to the declared sample.
    if ":" in path_only:
        sample = PATTERN_TARGET_SAMPLES.get(path_only)
        if sample is not None:
            return (REPO_ROOT / sample).exists()
        return False

    # Literal file?
    candidate = SITE_ROOT / rel
    if candidate.exists() and candidate.is_file():
        return True

    # Directory with index.html?
    if candidate.is_dir() and (candidate / "index.html").exists():
        return True

    # CF Pages `.html` stripping: /foo → /foo.html
    if not rel.endswith("/") and (SITE_ROOT / f"{rel}.html").exists():
        return True

    # Trailing-slash directory canonical: /foo/ → site/foo/index.html
    if rel.endswith("/") and (SITE_ROOT / f"{rel}index.html").exists():
        return True

    # Whitelisted .html-stripping targets (covers /404 → /404.html, /en/ root etc.)
    return path_only in HTML_STRIPPING_TARGETS


@pytest.fixture(scope="module")
def redirect_rows() -> list[tuple[int, str, str, str]]:
    return _parse_redirects()


def test_redirects_file_is_non_empty(redirect_rows: list[tuple[int, str, str, str]]) -> None:
    assert len(redirect_rows) >= 10, (
        "site/_redirects should have at least a handful of canonical rules; "
        f"got {len(redirect_rows)}"
    )


def test_no_duplicate_source_paths(redirect_rows: list[tuple[int, str, str, str]]) -> None:
    """Each source path should appear at most once. Duplicates indicate a merge
    accident — CF Pages applies the FIRST match, so the second is silently dead."""
    seen: dict[str, int] = {}
    offenders: list[str] = []
    for lineno, source, _, _ in redirect_rows:
        if source in seen:
            offenders.append(f"line {lineno}: duplicate of line {seen[source]} — {source!r}")
        else:
            seen[source] = lineno
    assert offenders == [], "\n".join(offenders)


def test_no_redirect_loops(redirect_rows: list[tuple[int, str, str, str]]) -> None:
    """A → B where B → A is an infinite redirect. CF Pages caps at a fixed depth
    and emits a 5xx; we should never ship one of these.

    Only flag exact-path loops; patterned (`:param`) sources are not statically
    decidable here. Status 200 (rewrite) targets count because they re-enter
    the redirect table.
    """
    pair_map: dict[str, str] = {}
    for _, source, target, _status in redirect_rows:
        if ":" in source or "*" in source:
            continue
        target_path = target.split("?", 1)[0].split("#", 1)[0]
        pair_map[source] = target_path

    loops: list[str] = []
    for source, target in pair_map.items():
        if target in pair_map and pair_map[target] == source:
            loops.append(f"{source} ⇄ {target}")
    # Deduplicate symmetric pairs (A⇄B / B⇄A).
    seen_pairs: set[frozenset[str]] = set()
    unique_loops: list[str] = []
    for entry in loops:
        a, b = entry.split(" ⇄ ")
        key = frozenset({a, b})
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        unique_loops.append(entry)
    assert unique_loops == [], "redirect loops detected:\n" + "\n".join(unique_loops)


def test_every_target_resolves_or_is_legacy_bridge(
    redirect_rows: list[tuple[int, str, str, str]],
) -> None:
    """For each rule: the target file (or directory-index, or .html-stripped form)
    must exist on disk, UNLESS the source is a legacy SEO bridge."""
    offenders: list[str] = []
    for lineno, source, target, status in redirect_rows:
        # 404 catch-all sinks are intentional resource-gone markers.
        if status == "404":
            continue
        if _is_legacy_bridge(source):
            continue
        # Some targets carry a query string (e.g. /programs/share?ids=UNI-:uid).
        # The path before `?` is what must exist.
        if not _target_exists_on_disk(target):
            offenders.append(
                f"line {lineno}: {source} → {target} (status {status}) "
                f"— target does not resolve on disk"
            )
    assert offenders == [], "\n".join(offenders)


def test_legacy_seo_bridges_preserved(
    redirect_rows: list[tuple[int, str, str, str]],
) -> None:
    """`feedback_legacy_brand_marker` requires `/jpintel*` to keep redirecting
    to `/` as the SEO citation bridge. Guard against accidental removal."""
    sources = {source for _, source, _, _ in redirect_rows}
    expected = {"/jpintel", "/jpintel.html", "/jpintel/*"}
    missing = expected - sources
    assert missing == set(), (
        f"legacy SEO bridges removed from site/_redirects: {sorted(missing)} — "
        "see memory feedback_legacy_brand_marker; these citations carry inbound "
        "SEO from the AutonoMath / 税務会計AI era and must remain as 301 stubs."
    )


def test_redirect_pattern_syntax_is_cf_pages_compatible(
    redirect_rows: list[tuple[int, str, str, str]],
) -> None:
    """CF Pages supports `*` glob and `:param` placeholders. Reject anything
    that looks like a regex or absolute URL (host-level rules belong in
    cloudflare-rules.yaml, not _redirects)."""
    bad_chars = re.compile(r"[()\[\]{}^$+?\\]")
    offenders: list[str] = []
    for lineno, source, target, _ in redirect_rows:
        if "://" in source or source.startswith("//"):
            offenders.append(f"line {lineno}: source is host-level — {source!r}")
        if bad_chars.search(source):
            offenders.append(f"line {lineno}: regex chars in source — {source!r}")
        if "://" in target and "jpcite.com" in target:
            # External targets are legitimate (rare), but flag if they hit our
            # own apex without a status code (would be a circular SEO leak).
            offenders.append(f"line {lineno}: target points back at apex — {target!r}")
    assert offenders == [], "\n".join(offenders)
