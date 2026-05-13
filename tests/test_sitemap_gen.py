import re
import xml.etree.ElementTree as ET

from scripts import sitemap_gen


def _sitemap_locs(path):
    root = ET.parse(path).getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [node.text for node in root.findall("sm:url/sm:loc", ns)]


def test_discover_sitemaps_includes_robot_advertised_shards():
    robots = (sitemap_gen.REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    advertised = {
        url.removeprefix("https://jpcite.com/")
        for url in re.findall(r"^Sitemap:\s*(https://jpcite\.com/\S+)", robots, re.MULTILINE)
    }
    advertised.discard("sitemap-index.xml")

    discovered = {
        name for name, _lastmod in sitemap_gen.discover_sitemaps(sitemap_gen.DEFAULT_SITE_DIR)
    }

    assert advertised <= discovered


def test_discover_sitemaps_includes_existing_geo_detail_and_city_shards(tmp_path):
    (tmp_path / "docs").mkdir()
    for name in (
        "sitemap.xml",
        "sitemap-cross-detail.xml",
        "sitemap-industries-detail.xml",
        "sitemap-pages.xml",
        "sitemap-qa.xml",
        "sitemap-enforcement.xml",
        "sitemap-cities.xml",
        "sitemap-llms.xml",
        "sitemap-structured.xml",
        "docs/sitemap.xml",
    ):
        (tmp_path / name).write_text("<urlset />\n", encoding="utf-8")
    (tmp_path / "sitemap-unused-detail.xml").write_text("<urlset />\n", encoding="utf-8")

    names = [name for name, _lastmod in sitemap_gen.discover_sitemaps(tmp_path)]

    assert names == [
        "sitemap.xml",
        "sitemap-cross-detail.xml",
        "sitemap-industries-detail.xml",
        "sitemap-pages.xml",
        "sitemap-qa.xml",
        "sitemap-enforcement.xml",
        "sitemap-cities.xml",
        "sitemap-llms.xml",
        "sitemap-structured.xml",
        "docs/sitemap.xml",
    ]


def test_cases_sitemap_only_references_existing_case_pages():
    sitemap_path = sitemap_gen.REPO_ROOT / "site" / "sitemap-cases.xml"
    cases_dir = sitemap_gen.REPO_ROOT / "site" / "cases"

    expected_paths = {
        f"https://jpcite.com/cases/{path.name}"
        for path in cases_dir.glob("*.html")
        if path.name != "index.html"
    }

    locs = _sitemap_locs(sitemap_path)

    assert set(locs) == expected_paths
    assert len(locs) == len(expected_paths)
