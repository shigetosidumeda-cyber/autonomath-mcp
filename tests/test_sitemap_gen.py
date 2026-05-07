from scripts import sitemap_gen


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
        "docs/sitemap.xml",
    ]
