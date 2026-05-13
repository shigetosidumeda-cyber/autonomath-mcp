import re
import xml.etree.ElementTree as ET

from scripts import sitemap_gen

PAGES_WORKFLOWS = (
    sitemap_gen.REPO_ROOT / ".github" / "workflows" / "pages-preview.yml",
    sitemap_gen.REPO_ROOT / ".github" / "workflows" / "pages-regenerate.yml",
    sitemap_gen.REPO_ROOT / ".github" / "workflows" / "pages-deploy-main.yml",
)


def _command_pos(workflow_text: str, script: str) -> int:
    match = re.search(rf"(?m)^\s+python3?\s+{re.escape(script)}(?:\s|$)", workflow_text)
    assert match is not None, f"missing workflow command for {script}"
    return match.start()


def _rsync_pos(workflow_text: str) -> int:
    match = re.search(r"(?m)^\s+rsync\s+-a\s+--delete\b", workflow_text)
    assert match is not None, "missing rsync artifact publish command"
    return match.start()


def _sitemap_locs(path):
    root = ET.parse(path).getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [node.text for node in root.findall("sm:url/sm:loc", ns)]


def test_discover_sitemaps_includes_robot_advertised_shards(tmp_path):
    robots = (sitemap_gen.REPO_ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    advertised = {
        url.removeprefix("https://jpcite.com/")
        for url in re.findall(r"^Sitemap:\s*(https://jpcite\.com/\S+)", robots, re.MULTILINE)
    }
    advertised.discard("sitemap-index.xml")

    for name in advertised:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<urlset />\n", encoding="utf-8")

    discovered = {name for name, _lastmod in sitemap_gen.discover_sitemaps(tmp_path)}

    assert advertised <= discovered


def test_pages_workflows_generate_audience_matrix_before_artifact_publish():
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        audience_pos = _command_pos(text, "scripts/generate_geo_industry_pages.py")
        rsync_pos = _rsync_pos(text)

        assert audience_pos < rsync_pos, f"{workflow.name} publishes before audience matrix"


def test_pages_workflows_generate_structured_sitemap_before_index_and_publish():
    for workflow in PAGES_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        structured_pos = _command_pos(text, "scripts/regen_structured_sitemap_and_llms_meta.py")
        sitemap_gen_pos = _command_pos(text, "scripts/sitemap_gen.py")
        rsync_pos = _rsync_pos(text)

        assert structured_pos < sitemap_gen_pos, (
            f"{workflow.name} indexes before structured sitemap"
        )
        assert structured_pos < rsync_pos, f"{workflow.name} publishes before structured sitemap"


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
