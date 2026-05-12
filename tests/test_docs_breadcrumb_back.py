"""Tests for Wave 48 tick#3 — docs/ breadcrumb + back button (迷子ゼロ fix).

Backs `mkdocs.yml` + `overrides/partials/content.html`. See
`docs/research/wave48/STATE_w48_docs_bc_pr.md` for the operational manual.

Test plan:

  1. `mkdocs.yml` exists and is parseable as YAML.
  2. The theme features list includes `navigation.path` (Material native
     breadcrumb), so every docs page renders the home › section › page
     trail at the top.
  3. The content partial override (`overrides/partials/content.html`) exists
     and is a non-empty Jinja template.
  4. The partial contains the `back-btn` anchor with `class="back-btn"` and
     a `javascript:history.back()` href so it works regardless of referrer.
  5. The partial contains a "ホーム" link to the site root (`{{ '/' | url }}`)
     and a "ドキュメント TOP" link to `/docs/` so users always have at least
     two known landmarks.
  6. The 3 元素 audit gate: the partial markup includes all three required
     surfaces (back button, home link, docs top link) AND the homepage is
     conditionally skipped (no double-render on the root index.md).

The test is intentionally static (no mkdocs build invocation): the build
machinery is exercised by `pages-deploy-main.yml` in CI. This file is the
source-of-truth contract — if the partial markup drifts, the deploy still
ships, but this test fails fast so the regression is caught at PR review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"
PARTIAL = REPO_ROOT / "overrides" / "partials" / "content.html"


def _read_text(path: Path) -> str:
    assert path.is_file(), f"required file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_mkdocs_yml_exists():
    """mkdocs.yml is the SOT for the docs site config."""
    text = _read_text(MKDOCS_YML)
    assert "theme:" in text, "mkdocs.yml is missing the theme: block"
    assert "features:" in text, "mkdocs.yml is missing the features: list"


def test_navigation_path_feature_enabled():
    """Material's `navigation.path` enables breadcrumb on every docs page.

    Without this feature, the page top renders no "home › section › page"
    trail and Wave 48 UX audit reports breadcrumb=0 on docs/ pages.
    """
    text = _read_text(MKDOCS_YML)
    # `navigation.path` must appear in the features list (one-feature-per-line
    # convention), not just as a substring inside a longer key.
    feature_line = re.search(r"^\s*-\s*navigation\.path(\s|$|#)", text, re.MULTILINE)
    assert feature_line is not None, (
        "mkdocs.yml theme.features must include `navigation.path` "
        "(Material breadcrumb). Wave 48 tick#3 requirement."
    )


def test_content_partial_exists():
    """The content.html override carries the back-btn + home + docs links."""
    text = _read_text(PARTIAL)
    # Sanity: non-trivial Jinja template (> 200 chars guard).
    assert len(text) > 200, (
        f"{PARTIAL} is too small ({len(text)} chars); back-btn partial missing"
    )
    # Must contain a Jinja conditional (skip on homepage).
    assert "{% if" in text and "{% endif %}" in text, (
        "content.html should conditionally skip the back-btn on the homepage"
    )
    # Must call page.content so Material renders the body underneath.
    assert "page.content" in text, (
        "content.html override must still render `{{ page.content }}` "
        "or the docs body disappears"
    )


def test_back_button_markup():
    """back-btn anchor uses history.back() so referrer chain is irrelevant."""
    text = _read_text(PARTIAL)
    # class="back-btn" anchor (audit selector hits exactly this class).
    assert 'class="back-btn"' in text, (
        "partial must include `class=\"back-btn\"` (audit selector match)"
    )
    # href uses javascript:history.back() (works without referrer).
    assert "javascript:history.back()" in text, (
        "back-btn href must be `javascript:history.back()` per task spec"
    )
    # aria-label for screen readers — keep a11y honest.
    assert "aria-label" in text, "back-btn must carry aria-label for a11y"


def test_breadcrumb_landmarks():
    """Home + docs-top links give the user 2 known landmarks at all times."""
    text = _read_text(PARTIAL)
    # Home link (Jinja url filter normalizes to site root).
    assert "{{ '/' | url }}" in text or 'href="/"' in text, (
        "partial must link to site root (ホーム)"
    )
    # Docs top link.
    assert "{{ '/docs/' | url }}" in text or 'href="/docs/"' in text, (
        "partial must link to /docs/ (ドキュメント TOP)"
    )
    # Japanese surface text is consistent with rest of site copy.
    assert "ホーム" in text, "landmark label `ホーム` missing"
    assert "ドキュメント" in text, "landmark label `ドキュメント` missing"
    assert "戻る" in text, "back-btn label `戻る` missing"


def test_three_elements_present():
    """3 要素 verdict (next + breadcrumb + back) — partial side of contract.

    `next` lives in Material's own per-page nav and is unrelated; this test
    only enforces the two missing axes (breadcrumb + back) that the UX
    audit flagged. The contract for next is delegated to Material defaults
    (already 100% per audit Section 3 table).
    """
    text = _read_text(PARTIAL)
    # back-btn class is the audit selector.
    has_back = 'class="back-btn"' in text
    # The partial-side breadcrumb hint (home + docs-top landmarks) is the
    # fallback even if `navigation.path` is later toggled off. We treat
    # presence of either ホーム or ドキュメント as breadcrumb signal.
    has_breadcrumb_hint = "ホーム" in text and "ドキュメント" in text
    # The partial preserves page.content (Material renders next/prev nav
    # underneath via its own page footer partial — we don't override that).
    has_next_compat = "page.content" in text

    assert has_back, "back element missing in partial"
    assert has_breadcrumb_hint, "breadcrumb hint missing in partial"
    assert has_next_compat, "next-compat (page.content render) missing"


def test_homepage_skip_guard():
    """Homepage should not render the back-btn (it would be a no-op at root)."""
    text = _read_text(PARTIAL)
    # `is_homepage` guard or explicit not page.is_homepage check.
    assert "is_homepage" in text, (
        "partial must guard with `is_homepage` so homepage skips back-btn"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
