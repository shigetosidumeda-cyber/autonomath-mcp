"""Tests for ``scripts/etl/generate_enforcement_seo_pages.py``.

Coverage:

1. End-to-end run on a minimal in-memory fixture writes an index page,
   detail pages, and a sitemap.
2. The PII / E2 aggregation gate excludes rows that lack a 13-digit
   houjin_bangou OR lack a recognized 法人 suffix in target_name.
3. The disclaimer string is present verbatim on every emitted page
   (index + every detail).
4. Sitemap declares 1 + N URLs (N = number of detail pages) and is
   well-formed XML against the sitemaps.org namespace.
5. The master sitemap-index gets a single sitemap-enforcement.xml entry,
   and re-running the generator does NOT duplicate it (idempotency).
"""

from __future__ import annotations

import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import generate_enforcement_seo_pages as generator  # noqa: E402

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _build_autonomath_db(path: Path) -> None:
    """Create a minimal autonomath.db with am_enforcement_detail rows.

    Schema mirrors the production DDL. We seed 4 rows:

      - 株式会社 SEO Sample :  publicly attributable, recent
      - 医療法人 ヘルス :       publicly attributable, older
      - 株式会社 Future :        future-dated public row — must be excluded
      - 田中 太郎 :             individual (no suffix) — must be excluded
      - 株式会社 NoSource :     no source_url — must be excluded
    """
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE am_enforcement_detail (
          enforcement_id    INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id         TEXT NOT NULL,
          houjin_bangou     TEXT,
          target_name       TEXT,
          enforcement_kind  TEXT,
          issuing_authority TEXT,
          issuance_date     TEXT NOT NULL,
          exclusion_start   TEXT,
          exclusion_end     TEXT,
          reason_summary    TEXT,
          related_law_ref   TEXT,
          amount_yen        INTEGER,
          source_url        TEXT,
          source_fetched_at TEXT,
          created_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    con.executemany(
        """
        INSERT INTO am_enforcement_detail (
          entity_id, houjin_bangou, target_name, enforcement_kind,
          issuing_authority, issuance_date, exclusion_start, exclusion_end,
          reason_summary, related_law_ref, amount_yen,
          source_url, source_fetched_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                "AM-ENF-TEST-0001",
                "1234567890123",
                "株式会社 SEO Sample",
                "subsidy_exclude",
                "厚生労働省 千葉労働局",
                "2026-04-15",
                "2026-04-20",
                "2031-04-19",
                "テスト用の処分理由要約。",
                "雇用保険法施行規則 第120条",
                3187875,
                "https://jsite.mhlw.go.jp/test/sample.pdf",
                "2026-04-25T07:04:15Z",
            ),
            (
                "AM-ENF-TEST-0002",
                "9876543210987",
                "医療法人 ヘルスケア",
                "business_improvement",
                "厚生労働省",
                "2025-09-30",
                None,
                None,
                "別件のテストデータ。",
                None,
                None,
                "https://www.mhlw.go.jp/test/another.html",
                "2026-04-25T07:04:15Z",
            ),
            (
                "AM-ENF-TEST-FUTURE",
                "1111111111111",
                "株式会社 Future",
                "business_improvement",
                "金融庁",
                "2030-01-01",
                None,
                None,
                "未来日付のテストデータ。",
                None,
                None,
                "https://www.fsa.go.jp/test/future.html",
                "2026-04-25T07:04:15Z",
            ),
            (
                "AM-ENF-TEST-0003",
                None,  # individual / sole-proprietor — gate must drop
                "田中 太郎",
                "fine",
                "東京都",
                "2024-12-01",
                None,
                None,
                "個人氏名は de-anonymize リスクで除外。",
                None,
                None,
                "https://example.tokyo/individual.html",
                "2026-04-25T07:04:15Z",
            ),
            (
                "AM-ENF-TEST-0004",
                "5555555555555",
                "株式会社 NoSource",
                "other",
                "金融庁",
                "2024-01-01",
                None,
                None,
                "出典 URL なし — 検証不能なのでドロップ。",
                None,
                None,
                None,  # no source_url — gate must drop
                "2026-04-25T07:04:15Z",
            ),
        ],
    )
    con.commit()
    con.close()


@pytest.fixture()
def fixture_paths(tmp_path: Path) -> dict[str, Path]:
    autonomath = tmp_path / "autonomath.db"
    jpintel = tmp_path / "jpintel.db"
    site_dir = tmp_path / "site"
    _build_autonomath_db(autonomath)
    # jpintel.db is optional — generator falls back gracefully if absent.
    site_dir.mkdir()
    # Seed a sitemap-index.xml so we can test injection.
    (site_dir / "sitemap-index.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <sitemap>\n'
        '    <loc>https://jpcite.com/sitemap.xml</loc>\n'
        '    <lastmod>2026-05-01</lastmod>\n'
        '  </sitemap>\n'
        '</sitemapindex>\n',
        encoding="utf-8",
    )
    return {
        "autonomath": autonomath,
        "jpintel": jpintel,
        "site": site_dir,
    }


def test_generator_writes_index_and_detail_pages(fixture_paths: dict[str, Path]) -> None:
    report = generator._build(
        jpintel_db=fixture_paths["jpintel"],
        autonomath_db=fixture_paths["autonomath"],
        site_dir=fixture_paths["site"],
        domain="jpcite.com",
        detail_limit=10,
        today_iso="2026-05-01",
        generated_at="2026-05-01 00:00 UTC",
    )
    enf = fixture_paths["site"] / "enforcement"
    assert (enf / "index.html").is_file()
    # Two publicly-attributable rows survived the gate.
    assert report["publicly_attributable_rows"] == 2
    # Detail page count matches the limit-clamped survivors.
    assert report["detail_pages"] == 2
    # Index page is non-trivial.
    index_text = (enf / "index.html").read_text(encoding="utf-8")
    assert "<title>行政処分 公開記録 サマリー — jpcite</title>" in index_text
    assert "株式会社 SEO Sample" in index_text
    assert "医療法人 ヘルスケア" in index_text
    assert "収録対象期間: 2024年〜2026年" in index_text
    assert "収録対象期間: 2024年〜2030年" not in index_text


def test_pii_gate_excludes_individuals_and_sourceless_rows(
    fixture_paths: dict[str, Path],
) -> None:
    generator._build(
        jpintel_db=fixture_paths["jpintel"],
        autonomath_db=fixture_paths["autonomath"],
        site_dir=fixture_paths["site"],
        domain="jpcite.com",
        detail_limit=10,
        today_iso="2026-05-01",
        generated_at="2026-05-01 00:00 UTC",
    )
    enf = fixture_paths["site"] / "enforcement"
    detail_files = list(enf.glob("act-*.html"))
    bodies = "\n".join(p.read_text(encoding="utf-8") for p in detail_files)
    index_text = (enf / "index.html").read_text(encoding="utf-8")
    # Individual name MUST NOT appear.
    assert "田中 太郎" not in bodies
    assert "田中 太郎" not in index_text
    # Sourceless company MUST NOT appear.
    assert "株式会社 NoSource" not in bodies
    assert "株式会社 NoSource" not in index_text
    # Future-dated rows MUST NOT appear on public SEO pages.
    assert "株式会社 Future" not in bodies
    assert "株式会社 Future" not in index_text
    # Two surviving slugs.
    assert len(detail_files) == 2


def test_disclaimer_appears_on_every_page(fixture_paths: dict[str, Path]) -> None:
    generator._build(
        jpintel_db=fixture_paths["jpintel"],
        autonomath_db=fixture_paths["autonomath"],
        site_dir=fixture_paths["site"],
        domain="jpcite.com",
        detail_limit=10,
        today_iso="2026-05-01",
        generated_at="2026-05-01 00:00 UTC",
    )
    enf = fixture_paths["site"] / "enforcement"
    needle_kojin = "個人事業主"
    needle_quals = "弁護士・税理士・公認会計士"
    pages = [enf / "index.html"] + list(enf.glob("act-*.html"))
    assert pages, "no pages written"
    for p in pages:
        text = p.read_text(encoding="utf-8")
        assert needle_kojin in text, f"missing kojin disclaimer on {p.name}"
        assert needle_quals in text, f"missing 有資格者 disclaimer on {p.name}"
        # bookmarklet CTA must be on every page (jpcite primary growth surface).
        assert "/bookmarklet.html" in text, f"missing bookmarklet CTA on {p.name}"
        # Public SEO pages should not expose operator-internal identifiers.
        assert "T8010001213708" not in text, f"operator invoice id leaked on {p.name}"
        assert "梅田茂利" not in text, f"individual operator name leaked on {p.name}"
        assert "info@bookyou.net" not in text, f"operator email leaked on {p.name}"


def test_sitemap_structure_is_well_formed(fixture_paths: dict[str, Path]) -> None:
    generator._build(
        jpintel_db=fixture_paths["jpintel"],
        autonomath_db=fixture_paths["autonomath"],
        site_dir=fixture_paths["site"],
        domain="jpcite.com",
        detail_limit=10,
        today_iso="2026-05-01",
        generated_at="2026-05-01 00:00 UTC",
    )
    sitemap_path = fixture_paths["site"] / "sitemap-enforcement.xml"
    assert sitemap_path.is_file()
    tree = ET.parse(sitemap_path)
    root = tree.getroot()
    assert root.tag == f"{SITEMAP_NS}urlset"
    urls = root.findall(f"{SITEMAP_NS}url")
    # One index + one URL per detail page (=2 surviving rows).
    assert len(urls) == 1 + 2
    locs = [u.findtext(f"{SITEMAP_NS}loc") for u in urls]
    assert "https://jpcite.com/enforcement/" in locs
    # All other locs point to act-*.html.
    detail_locs = [
        loc for loc in locs if loc != "https://jpcite.com/enforcement/"
    ]
    for loc in detail_locs:
        assert loc.startswith("https://jpcite.com/enforcement/act-")
        assert loc.endswith(".html")
    # Every url has a lastmod, changefreq, priority.
    for u in urls:
        assert u.findtext(f"{SITEMAP_NS}lastmod"), "missing lastmod"
        assert u.findtext(f"{SITEMAP_NS}changefreq"), "missing changefreq"
        assert u.findtext(f"{SITEMAP_NS}priority"), "missing priority"


def test_sitemap_index_injection_is_idempotent(fixture_paths: dict[str, Path]) -> None:
    # Run twice — second run must not duplicate the sitemap-enforcement.xml entry.
    for _ in range(2):
        generator._build(
            jpintel_db=fixture_paths["jpintel"],
            autonomath_db=fixture_paths["autonomath"],
            site_dir=fixture_paths["site"],
            domain="jpcite.com",
            detail_limit=10,
            today_iso="2026-05-01",
            generated_at="2026-05-01 00:00 UTC",
        )
    text = (fixture_paths["site"] / "sitemap-index.xml").read_text(encoding="utf-8")
    assert text.count("https://jpcite.com/sitemap-enforcement.xml") == 1
    # The original sitemap.xml entry is still there.
    assert "https://jpcite.com/sitemap.xml" in text
