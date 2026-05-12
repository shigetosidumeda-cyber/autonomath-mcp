"""Wave 49 tick#3 — calculator LIVE 404 解消 verify.

問題 (前 tick#11 finding):
  PR #183 で `tools/cost_saving_calculator.html` + `docs/canonical/cost_saving_examples.md`
  が main に着地したが、`pages-deploy-main.yml` の rsync は `site/` のみを `dist/site/` に
  mirror するため、repo root の `tools/` / `docs/canonical/` は CF Pages に配信されない。
  → https://jpcite.com/tools/cost_saving_calculator.html = 404。

修正方針 (destruction-free):
  1. `site/tools/cost_saving_calculator.html` を hard copy (元 `tools/` は触らず)
  2. `site/tools/cost_saving_examples.md` を hard copy
     (`site/docs/` は MkDocs 出力で gitignored なため `tools/` 配下に集約)
  3. `pages-deploy-main.yml` + `pages-preview.yml` の rsync filter に
     `--include 'tools/*.md'` を追加 (.md デフォ exclude を局所開放)

この test は 4 軸を verify:
  - A. site/tools/cost_saving_calculator.html 存在 + HTML valid
  - B. site/tools/cost_saving_examples.md 存在 + .md valid
  - C. rsync rule が tools/*.md を include している (順序込み)
  - D. 元 tools/ + docs/canonical/ が destruction-free
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SITE_CALC = REPO_ROOT / "site" / "tools" / "cost_saving_calculator.html"
SITE_MD = REPO_ROOT / "site" / "tools" / "cost_saving_examples.md"
ORIG_CALC = REPO_ROOT / "tools" / "cost_saving_calculator.html"
ORIG_MD = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

DEPLOY_YML = REPO_ROOT / ".github" / "workflows" / "pages-deploy-main.yml"
PREVIEW_YML = REPO_ROOT / ".github" / "workflows" / "pages-preview.yml"


# ──────────────────────────────────────────────────────────────────────
# A. site/tools/ への .html hard-copy verify
# ──────────────────────────────────────────────────────────────────────

def test_site_calculator_html_exists():
    """A1: site/tools/cost_saving_calculator.html が存在する。"""
    assert SITE_CALC.exists(), (
        "site/tools/cost_saving_calculator.html missing — CF Pages does not "
        "rsync repo-root tools/ into dist/site/, so this copy is required."
    )


def test_site_calculator_html_valid():
    """A2: site/tools/ の HTML が valid (doctype + closing tag)。"""
    text = SITE_CALC.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text or "<!doctype html>" in text.lower()
    assert "</html>" in text
    assert "cost" in text.lower(), "HTML must reference cost-saving content"


def test_site_calculator_is_hard_copy_not_empty():
    """A3: hard copy が元 file と同一サイズ (destruction-free verify)。"""
    assert ORIG_CALC.exists(), "original tools/cost_saving_calculator.html missing"
    assert SITE_CALC.stat().st_size == ORIG_CALC.stat().st_size, (
        "site copy and repo-root copy diverged — re-run cp from origin"
    )


# ──────────────────────────────────────────────────────────────────────
# B. site/tools/ への .md hard-copy verify
# ──────────────────────────────────────────────────────────────────────

def test_site_examples_md_exists():
    """B1: site/tools/cost_saving_examples.md が存在する。"""
    assert SITE_MD.exists(), (
        "site/tools/cost_saving_examples.md missing — required for "
        "https://jpcite.com/tools/cost_saving_examples.md LIVE."
    )


def test_site_examples_md_valid():
    """B2: .md が valid (heading + 6 use case 言及)。"""
    text = SITE_MD.read_text(encoding="utf-8")
    assert text.startswith("# "), "must start with H1"
    # 6 use case の H2/H3 anchor を緩く verify
    for keyword in ["use case", "use-case", "use_case", "ユースケース", "case"]:
        if keyword.lower() in text.lower():
            break
    else:
        pytest.fail(".md does not reference any use-case anchor")


def test_site_examples_md_is_hard_copy_not_empty():
    """B3: hard copy が元 .md と同一サイズ。"""
    assert ORIG_MD.exists(), "original docs/canonical/cost_saving_examples.md missing"
    assert SITE_MD.stat().st_size == ORIG_MD.stat().st_size, (
        "site copy and repo-root canonical .md diverged"
    )


# ──────────────────────────────────────────────────────────────────────
# C. rsync filter の include rule verify
# ──────────────────────────────────────────────────────────────────────

def test_pages_deploy_main_rsync_includes_tools_md():
    """C1: pages-deploy-main.yml の rsync が tools/*.md を include する。"""
    text = DEPLOY_YML.read_text(encoding="utf-8")
    assert "tools/*.md" in text, (
        "pages-deploy-main.yml rsync filter must include tools/*.md "
        "to let canonical .md pass the default *.md exclude."
    )


def test_pages_preview_rsync_includes_tools_md():
    """C2: pages-preview.yml も同じ rule を持つ (workflow parity)。"""
    text = PREVIEW_YML.read_text(encoding="utf-8")
    assert "tools/*.md" in text, (
        "pages-preview.yml must mirror the tools/*.md include "
        "so PR-preview deploys match prod."
    )


def test_rsync_include_ordered_before_md_exclude():
    """C3: --include 'tools/*.md' が `--exclude '*.md'` より前にある。

    rsync は first-match-wins なので include が exclude より後だと無効化する。
    """
    for yml in (DEPLOY_YML, PREVIEW_YML):
        text = yml.read_text(encoding="utf-8")
        inc_pos = text.find("tools/*.md")
        # 直近の --exclude '*.md' を inc_pos 以降で探す
        exc_pos = text.find("--exclude '*.md'", inc_pos)
        assert exc_pos > inc_pos, (
            f"{yml.name}: --include 'tools/*.md' must appear BEFORE "
            f"`--exclude '*.md'` (rsync first-match-wins)."
        )


# ──────────────────────────────────────────────────────────────────────
# D. destruction-free invariant
# ──────────────────────────────────────────────────────────────────────

def test_original_tools_and_docs_canonical_untouched():
    """D1: 元 tools/ + docs/canonical/ が削除/move されていない。"""
    assert ORIG_CALC.exists()
    assert ORIG_MD.exists()
