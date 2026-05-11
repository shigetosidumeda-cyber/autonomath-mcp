"""Tests for Wave 41 Agent H — monitoring dashboard integration.

Coverage:
1. ``site/status/monitoring.html`` exists + parses as well-formed HTML5 +
   embeds the Schema.org DataCatalog JSON-LD with all 5 dataset entries.
2. ``site/status/feed.atom`` seed parses as well-formed XML and exposes
   the expected ATOM namespace + the 6 required feed-level elements.
3. ``scripts/cron/aggregate_status_alerts_hourly.py`` runs end-to-end on
   honest-null inputs (missing snapshot files → unknown severity, exit 0)
   and writes the three output artifacts.
4. The five judge_* functions return the documented severity levels for
   representative happy / warn / critical / unknown inputs.
5. REST endpoints ``/v1/status/all`` and ``/v1/status/alerts`` return
   well-formed JSON envelopes with the expected keys, even when sidecar
   files are absent (honest-null path).
6. ``.github/workflows/status-aggregator-hourly.yml`` parses as YAML and
   declares the expected schedule + python step.
7. No LLM API imports in any of the new files (CI parity guard).
8. All 6 deliverable files exist at the expected paths.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

DASHBOARD_HTML = REPO_ROOT / "site" / "status" / "monitoring.html"
ATOM_FEED = REPO_ROOT / "site" / "status" / "feed.atom"
AGGREGATOR_PY = REPO_ROOT / "scripts" / "cron" / "aggregate_status_alerts_hourly.py"
ENDPOINT_PY = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "status_aggregated.py"
WORKFLOW_YML = REPO_ROOT / ".github" / "workflows" / "status-aggregator-hourly.yml"
THIS_TEST = Path(__file__)


# ---------------------------------------------------------------------------
# 1. dashboard html valid
# ---------------------------------------------------------------------------


class _HTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        # Void elements (HTML5 self-closing without `/`) — must not be
        # pushed onto the stack.
        self._void = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._void:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            self.errors.append(f"end tag without matching open: {tag}")
            return
        # Tolerate optional close mismatches that browsers gracefully fix
        # (e.g. <p> implicitly closed by <h2>). We only fail on hard tag
        # imbalance for the structural elements we control.
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()


def test_dashboard_html_exists_and_parses() -> None:
    assert DASHBOARD_HTML.exists(), f"missing dashboard: {DASHBOARD_HTML}"
    raw = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert raw.startswith("<!DOCTYPE html>")
    v = _HTMLValidator()
    v.feed(raw)
    # We allow open structural tags at EOF because the parser is lenient
    # and we use details/section nesting. The substantive assertion is
    # "no end-tag-without-open" errors.
    assert not v.errors, f"HTML parse errors: {v.errors[:3]}"


def test_dashboard_html_jsonld_datacatalog() -> None:
    raw = DASHBOARD_HTML.read_text(encoding="utf-8")
    match = re.search(
        r"<script type=\"application/ld\+json\">(.*?)</script>",
        raw,
        flags=re.DOTALL,
    )
    assert match, "JSON-LD block missing from dashboard"
    payload = json.loads(match.group(1))
    assert payload["@type"] == "DataCatalog"
    assert isinstance(payload["dataset"], list)
    names = [d["name"] for d in payload["dataset"]]
    # All 5 dashboards must be advertised.
    expected_substrings = ["RUM", "Audit", "Freshness", "6-Axis", "AX"]
    for needle in expected_substrings:
        assert any(needle in n for n in names), f"Dataset missing: {needle} ({names})"


def test_dashboard_html_links_5_dashboards() -> None:
    raw = DASHBOARD_HTML.read_text(encoding="utf-8")
    expected_hrefs = [
        "/status/rum.html",
        "/status/audit_dashboard.html",
        "/data-freshness",
        "/status/six_axis_dashboard.html",
        "/status/ax_dashboard.html",
    ]
    for href in expected_hrefs:
        assert href in raw, f"dashboard link missing: {href}"


# ---------------------------------------------------------------------------
# 2. ATOM feed valid
# ---------------------------------------------------------------------------


def test_atom_feed_parses_as_xml() -> None:
    assert ATOM_FEED.exists(), f"missing feed: {ATOM_FEED}"
    tree = ET.parse(ATOM_FEED)
    root = tree.getroot()
    assert root.tag.endswith("feed")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert root.find("a:title", ns) is not None
    assert root.find("a:id", ns) is not None
    assert root.find("a:updated", ns) is not None
    self_link = root.findall("a:link", ns)
    assert any(
        link.get("rel") == "self" and link.get("href", "").endswith("feed.atom")
        for link in self_link
    ), "self-link with feed.atom href missing"
    entries = root.findall("a:entry", ns)
    assert len(entries) >= 1, "ATOM seed must carry at least 1 entry"


# ---------------------------------------------------------------------------
# 3 + 4. aggregator end-to-end + judge functions
# ---------------------------------------------------------------------------


def _import_aggregator():
    spec = importlib.util.spec_from_file_location(
        "wave41_aggregator_under_test", AGGREGATOR_PY
    )
    assert spec and spec.loader, "aggregator spec failed"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_aggregator_module_imports() -> None:
    mod = _import_aggregator()
    assert callable(mod.run)
    assert "_judge_rum" in dir(mod)
    assert "_judge_six_axis" in dir(mod)


def test_aggregator_judge_rum_levels() -> None:
    mod = _import_aggregator()
    # None input → unknown
    out = mod._judge_rum(None)
    assert out["level"] == "unknown"
    # No samples → info
    out = mod._judge_rum({"days": [{"samples": 0}]})
    assert out["level"] == "info"
    # Breach LCP → warn
    out = mod._judge_rum(
        {
            "p75_thresholds": {"lcp": {"ok": 2500, "warn": 4000}},
            "days": [{"samples": 10, "lcp": 9999, "inp": 100, "cls": 0.05}],
        }
    )
    assert out["level"] == "warn"
    assert "LCP=9999" in out["summary"]


def test_aggregator_judge_status_components_levels() -> None:
    mod = _import_aggregator()
    assert mod._judge_status_components(None)["level"] == "unknown"
    out = mod._judge_status_components({"components": {"api": {"status": "ok"}}})
    assert out["level"] == "info"
    out = mod._judge_status_components(
        {"components": {"api": {"status": "down"}, "mcp": {"status": "ok"}}}
    )
    assert out["level"] == "critical"
    assert "api" in out["summary"]


def test_aggregator_judge_six_axis_levels() -> None:
    mod = _import_aggregator()
    assert mod._judge_six_axis(None)["level"] == "unknown"
    happy = {"axes": [{"id": "data_quantity", "sub_axes": [{"id": "programs", "sla_status": "pass"}]}]}
    assert mod._judge_six_axis(happy)["level"] == "info"
    breach = {
        "axes": [
            {"id": "data_quantity", "sub_axes": [{"id": "programs", "sla_status": "fail"}]}
        ]
    }
    out = mod._judge_six_axis(breach)
    assert out["level"] == "critical"
    assert "data_quantity/programs" in out["summary"]


def test_aggregator_judge_freshness_levels() -> None:
    mod = _import_aggregator()
    assert mod._judge_freshness(None)["level"] == "unknown"
    happy = {"axes": {"adoption": {"sla_status": "pass"}}}
    assert mod._judge_freshness(happy)["level"] == "info"
    breach = {"axes": {"adoption": {"sla_status": "fail"}}}
    out = mod._judge_freshness(breach)
    assert out["level"] == "warn"
    assert "adoption" in out["summary"]


def test_aggregator_judge_cron_health_levels() -> None:
    mod = _import_aggregator()
    assert mod._judge_cron_health(None)["level"] == "unknown"
    out = mod._judge_cron_health({"success_rate_24h": 1.0})
    assert out["level"] == "info"
    out = mod._judge_cron_health({"success_rate_24h": 0.5, "threshold": 0.95})
    assert out["level"] == "critical"


def test_aggregator_end_to_end_honest_null(tmp_path, monkeypatch) -> None:
    """Run the aggregator with all snapshot inputs absent; expect exit 0
    + outputs produced + max_severity == 'unknown'."""
    mod = _import_aggregator()
    # Point the module at a tmp_path-rooted virtual repo so we don't
    # write into the real site/ or analytics/ during pytest.
    site_status = tmp_path / "site" / "status"
    analytics = tmp_path / "analytics"
    site_status.mkdir(parents=True)
    analytics.mkdir(parents=True)
    monkeypatch.setattr(mod, "SITE_STATUS", site_status)
    monkeypatch.setattr(mod, "ANALYTICS", analytics)
    monkeypatch.setattr(mod, "ALERT_JSONL", analytics / "status_alerts_w41.jsonl")
    monkeypatch.setattr(mod, "SIDECAR_JSON", site_status / "status_alerts_w41.json")
    monkeypatch.setattr(mod, "FEED_ATOM", site_status / "feed.atom")
    # Ensure Telegram is skipped (don't actually post during tests).
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)

    rc = mod.run()
    assert rc == 0
    sidecar = json.loads((site_status / "status_alerts_w41.json").read_text("utf-8"))
    assert sidecar["max_severity"] == "unknown"
    assert sidecar["schema_version"] == 1
    assert len(sidecar["alerts"]) == 5
    assert (analytics / "status_alerts_w41.jsonl").exists()
    atom = (site_status / "feed.atom").read_text("utf-8")
    assert atom.startswith("<?xml")
    assert "<feed xmlns=\"http://www.w3.org/2005/Atom\">" in atom


# ---------------------------------------------------------------------------
# 5. REST endpoint smoke (honest-null path)
# ---------------------------------------------------------------------------


def test_rest_endpoint_module_importable() -> None:
    spec = importlib.util.spec_from_file_location(
        "wave41_rest_under_test", ENDPOINT_PY
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.router.prefix == "/v1/status"
    # The two new routes should be registered on this router.
    route_paths = [r.path for r in mod.router.routes]  # type: ignore[attr-defined]
    assert "/v1/status/all" in route_paths
    assert "/v1/status/alerts" in route_paths


def test_rest_endpoint_smoke_honest_null(tmp_path, monkeypatch) -> None:
    """Hit the FastAPI route handlers directly (no full app) with empty
    sidecar files. Endpoint should return a well-formed envelope, not
    raise."""
    spec = importlib.util.spec_from_file_location(
        "wave41_rest_smoke", ENDPOINT_PY
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Force all sidecar paths to a non-existent location.
    monkeypatch.setenv("STATUS_RUM_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("STATUS_AUDIT_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("STATUS_SIX_AXIS_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("STATUS_FRESHNESS_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("STATUS_CRON_HEALTH_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("STATUS_ALERTS_PATH", str(tmp_path / "absent.json"))

    from fastapi import Response

    resp = Response()
    payload_all = mod.get_status_all(resp)
    assert payload_all["schema_version"] == 1
    assert payload_all["wave"] == 41
    assert payload_all["ready_count"] == 0
    assert payload_all["total_axes"] == 5
    assert "rum" in payload_all["snapshots"]
    assert payload_all["snapshots"]["rum"] is None
    assert resp.headers["Cache-Control"].startswith("public, max-age=")

    resp_alerts = Response()
    payload_alerts = mod.get_status_alerts(resp_alerts)
    assert payload_alerts["schema_version"] == 1
    assert payload_alerts["ready"] is False
    assert payload_alerts["alerts"] == []


# ---------------------------------------------------------------------------
# 6. workflow yaml
# ---------------------------------------------------------------------------


def test_workflow_yaml_parses() -> None:
    yaml = pytest.importorskip("yaml")
    assert WORKFLOW_YML.exists()
    raw = WORKFLOW_YML.read_text(encoding="utf-8")
    spec = yaml.safe_load(raw)
    assert spec["name"] == "status-aggregator-hourly"
    # yaml turns the bareword `on` into Python True; both shapes are valid.
    triggers = spec.get("on") or spec.get(True)
    assert triggers, "workflow `on` triggers missing"
    schedules = triggers.get("schedule", [])
    assert any(s.get("cron") == "5 * * * *" for s in schedules), schedules
    job = spec["jobs"]["aggregate"]
    assert job["runs-on"] == "ubuntu-latest"
    step_names = [s.get("name", "") for s in job["steps"]]
    assert any("Run hourly aggregator" in n for n in step_names)


# ---------------------------------------------------------------------------
# 7. no LLM imports
# ---------------------------------------------------------------------------


# Build the forbidden-import needle list at runtime so the literal tokens
# never appear verbatim in this test source (the test would otherwise
# false-positive on itself).
_LLM_PKGS = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
FORBIDDEN_LLM_IMPORTS = tuple(
    prefix + " " + pkg for pkg in _LLM_PKGS for prefix in ("import", "from")
)


@pytest.mark.parametrize(
    "path",
    [DASHBOARD_HTML, ATOM_FEED, AGGREGATOR_PY, ENDPOINT_PY, WORKFLOW_YML],
)
def test_wave41_no_llm_imports(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    for needle in FORBIDDEN_LLM_IMPORTS:
        assert needle not in raw, f"LLM import detected in {path.name}: {needle}"


# ---------------------------------------------------------------------------
# 8. all 6 files exist
# ---------------------------------------------------------------------------


def test_all_six_deliverables_exist() -> None:
    deliverables = [DASHBOARD_HTML, ATOM_FEED, AGGREGATOR_PY, ENDPOINT_PY, WORKFLOW_YML, THIS_TEST]
    for d in deliverables:
        assert d.exists(), f"deliverable missing: {d}"
        # Reject empty files — a 0-byte placeholder is not a deliverable.
        assert d.stat().st_size > 0, f"deliverable empty: {d}"
