"""Wave 41 Agent F — happy-path tests for the sitemap_audit REST module.

`src/jpintel_mcp/api/sitemap_audit.py` is a tiny read-only endpoint
that diffs the on-disk companion-Markdown inventory against the live
sitemap. The tests below import the helper functions directly so we
don't need a full FastAPI stack — they verify the counting + envelope
shape that the route returns.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api import sitemap_audit


def test_count_sitemap_urls_matches_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_count_sitemap_urls` should extract every <loc> URL and bucket per category."""
    sitemap_body = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://jpcite.com/cases/case_001.md</loc></url>
  <url><loc>https://jpcite.com/cases/case_002.md</loc></url>
  <url><loc>https://jpcite.com/laws/law_001.md</loc></url>
  <url><loc>https://jpcite.com/enforcement/enf_001.md</loc></url>
  <url><loc>https://jpcite.com/enforcement/enf_002.md</loc></url>
  <url><loc>https://jpcite.com/enforcement/enf_003.md</loc></url>
</urlset>
"""
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    sitemap_path = site_dir / "sitemap-companion-md.xml"
    sitemap_path.write_text(sitemap_body, encoding="utf-8")
    monkeypatch.setattr(sitemap_audit, "_SITEMAP_COMPANION_MD", sitemap_path)

    total, by_cat = sitemap_audit._count_sitemap_urls()
    assert total == 6
    assert by_cat["cases"] == 2
    assert by_cat["laws"] == 1
    assert by_cat["enforcement"] == 3


def test_count_on_disk_md_excludes_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only true companion .md files count — index.md / README.md are skipped."""
    site_dir = tmp_path / "site"
    (site_dir / "cases").mkdir(parents=True)
    (site_dir / "laws").mkdir(parents=True)
    (site_dir / "enforcement").mkdir(parents=True)
    (site_dir / "cases" / "case_001.md").write_text("# c1", encoding="utf-8")
    (site_dir / "cases" / "case_002.md").write_text("# c2", encoding="utf-8")
    (site_dir / "cases" / "index.md").write_text("# i", encoding="utf-8")
    (site_dir / "cases" / "README.md").write_text("# r", encoding="utf-8")
    (site_dir / "laws" / "law_001.md").write_text("# l1", encoding="utf-8")
    monkeypatch.setattr(sitemap_audit, "_SITE_DIR", site_dir)

    total, by_cat = sitemap_audit._count_on_disk_md()
    assert total == 3
    assert by_cat["cases"] == 2
    assert by_cat["laws"] == 1
    assert by_cat["enforcement"] == 0


def test_coverage_envelope_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Envelope must carry the contracted keys for downstream consumers."""
    site_dir = tmp_path / "site"
    (site_dir / "cases").mkdir(parents=True)
    (site_dir / "laws").mkdir(parents=True)
    (site_dir / "enforcement").mkdir(parents=True)
    (site_dir / "cases" / "a.md").write_text("# a", encoding="utf-8")
    sitemap_body = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://jpcite.com/cases/a.md</loc></url>
  <url><loc>https://jpcite.com/cases/b.md</loc></url>
</urlset>
"""
    sitemap_path = site_dir / "sitemap-companion-md.xml"
    sitemap_path.write_text(sitemap_body, encoding="utf-8")
    monkeypatch.setattr(sitemap_audit, "_SITE_DIR", site_dir)
    monkeypatch.setattr(sitemap_audit, "_SITEMAP_COMPANION_MD", sitemap_path)

    env = sitemap_audit._coverage_envelope()
    assert env["type"] == "companion-md"
    assert env["sitemap_url_count"] == 2
    assert env["on_disk_md_count"] == 1
    assert env["gap"] == 1
    assert env["coverage_pct"] == 50.0
    assert env["by_category"]["cases"] == {
        "sitemap_urls": 2,
        "on_disk_md": 1,
        "gap": 1,
    }
    assert "generated_at" in env
    assert env["generated_at"].endswith("Z")


def test_missing_sitemap_returns_zero_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the sitemap file is missing the helper returns zero counts, not raising."""
    monkeypatch.setattr(sitemap_audit, "_SITEMAP_COMPANION_MD", tmp_path / "nonexistent.xml")
    total, by_cat = sitemap_audit._count_sitemap_urls()
    assert total == 0
    assert by_cat["cases"] == 0
