"""Wave 38 — tests for the 6-axis sanity check + REST surface + dashboard.

Three contract assertions:

1. ``scripts/ops/six_axis_sanity_check.py`` runs to completion against
   *any* state of the repo (DBs present or absent), emitting valid JSON
   with all 6 axes populated. Honest-null is mandatory: when an input
   is missing the sub-axis is ``unknown`` and the overall verdict is NOT
   automatically ``breach``.

2. ``site/status/six_axis_dashboard.html`` is well-formed HTML with the
   Schema.org Dataset JSON-LD embedded and parseable.

3. ``src/jpintel_mcp/api/six_axis_status.py`` exposes a FastAPI router
   under ``/v1/status`` that returns the sidecar JSON when present and
   503 ``ready=false`` when it is not. Per-sub-axis drill-in is honored.

Pure stdlib + pytest + fastapi.testclient. No LLM imports.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_OPS = REPO_ROOT / "scripts" / "ops"
SITE_STATUS = REPO_ROOT / "site" / "status"


# ---------------------------------------------------------------------------
# 1. six_axis_sanity_check.py contract
# ---------------------------------------------------------------------------

def _import_sanity():
    sys.path.insert(0, str(SCRIPTS_OPS))
    try:
        import six_axis_sanity_check  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return six_axis_sanity_check


def test_sanity_runs_without_dbs():
    """The probe must run end-to-end even when both DBs are absent."""
    mod = _import_sanity()
    report = mod.run_all()
    assert report["schema_version"] == 1
    assert "generated_at" in report
    assert report["overall_verdict"] in {"ok", "degraded", "breach", "unknown"}
    assert len(report["axes"]) == 6
    axis_ids = {a["axis_id"] for a in report["axes"]}
    assert axis_ids == {"1", "2", "3", "4", "5", "6"}


def test_sanity_each_axis_has_sub_results():
    mod = _import_sanity()
    report = mod.run_all()
    for axis in report["axes"]:
        assert axis["sub_results"], f"axis {axis['axis_id']} has no sub_results"
        for sub in axis["sub_results"]:
            assert sub["status"] in {"ok", "warn", "fail", "unknown"}
            assert "label" in sub
            assert "threshold" in sub


def test_sanity_honest_null():
    """When the autonomath DB is absent every Axis-2 sub must be 'unknown'."""
    mod = _import_sanity()
    if mod.AUTONOMATH_DB is not None and mod.AUTONOMATH_DB.exists():
        pytest.skip("autonomath.db present locally — honest-null path skipped")
    axis2 = mod.run_axis2()
    statuses = {s.status for s in axis2.sub_results}
    assert statuses == {"unknown"}
    assert axis2.verdict == "unknown"


def test_sanity_emits_md_and_json(tmp_path):
    mod = _import_sanity()
    out_json = tmp_path / "status.json"
    out_md = tmp_path / "status.md"
    rc = mod.main([
        "--out-json", str(out_json),
        "--out-md", str(out_md),
    ])
    assert rc == 0
    data = json.loads(out_json.read_text())
    assert data["schema_version"] == 1
    assert "axes" in data
    md = out_md.read_text()
    assert "6-axis production sanity check" in md
    # All 6 axes appear in the table
    for axis_id in ("1", "2", "3", "4", "5", "6"):
        assert f"| {axis_id} |" in md


def test_sanity_breach_emits_alert(tmp_path, monkeypatch):
    """When verdict is breach the script writes the alert file."""
    mod = _import_sanity()
    # Construct a synthetic breach report and run the renderer directly.
    fake = {
        "schema_version": 1,
        "generated_at": "2026-05-12T00:00:00Z",
        "overall_verdict": "breach",
        "axes": [
            {
                "axis_id": "3",
                "label": "鮮度",
                "verdict": "breach",
                "sub_results": [
                    {
                        "sub_id": "3a", "label": "amendment_diff",
                        "status": "fail", "observed": 0, "threshold": 1,
                        "detail": "observed=0 < 1",
                    },
                ],
            },
        ],
        "_meta": {},
    }
    text = mod.render_alert(fake)
    assert text is not None
    assert "SLA breach" in text
    assert "3a" in text
    assert "amendment_diff" in text


# ---------------------------------------------------------------------------
# 2. dashboard HTML contract
# ---------------------------------------------------------------------------

def test_dashboard_html_present():
    f = SITE_STATUS / "six_axis_dashboard.html"
    assert f.exists(), "dashboard HTML missing"
    txt = f.read_text(encoding="utf-8")
    # Required scaffolding
    assert '<title>6-axis Monitoring Dashboard' in txt
    assert 'id="summary-bar"' in txt
    assert 'id="axes-detail"' in txt
    # Fetches the JSON status endpoint
    assert "/v1/status/six_axis" in txt
    # Canonical link points to jpcite.com (no legacy brand)
    assert "jpcite.com/status/six_axis_dashboard.html" in txt


def test_dashboard_jsonld_parses():
    f = SITE_STATUS / "six_axis_dashboard.html"
    txt = f.read_text(encoding="utf-8")
    m = re.search(
        r'<script type="application/ld\+json">(.*?)</script>',
        txt, re.DOTALL,
    )
    assert m, "JSON-LD block missing"
    data = json.loads(m.group(1))
    assert data["@type"] == "Dataset"
    # variableMeasured covers all 6 axes
    var_names = {v["name"] for v in data["variableMeasured"]}
    for axis_name in (
        "axis_1_data_volume",
        "axis_2_data_quality",
        "axis_3_freshness",
        "axis_4_combination",
        "axis_5_multilingual",
        "axis_6_output",
    ):
        assert axis_name in var_names


def test_dashboard_no_legacy_brand():
    f = SITE_STATUS / "six_axis_dashboard.html"
    txt = f.read_text(encoding="utf-8")
    for legacy in ("zeimu-kaikei.ai", "AutonoMath", "税務会計AI"):
        assert legacy not in txt, f"legacy brand leaked: {legacy}"


# ---------------------------------------------------------------------------
# 3. REST endpoint contract
# ---------------------------------------------------------------------------

def _build_test_app(status_path: Path):
    from fastapi import FastAPI
    from jpintel_mcp.api.six_axis_status import router

    app = FastAPI()
    app.include_router(router)
    # Point the resolver at the test sidecar
    import os
    os.environ["SIX_AXIS_STATUS_PATH"] = str(status_path)
    return app


def test_rest_returns_503_when_sidecar_missing(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    missing = tmp_path / "no_such.json"
    app = _build_test_app(missing)
    client = TestClient(app)
    r = client.get("/v1/status/six_axis")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert "six-axis" in body["message"].lower()


def test_rest_returns_full_when_sidecar_present(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    sidecar = tmp_path / "six.json"
    sidecar.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": "2026-05-12T06:30:00Z",
        "overall_verdict": "ok",
        "axes": [
            {
                "axis_id": "1", "label": "data 量", "verdict": "ok",
                "sub_results": [
                    {"sub_id": "1a", "label": "municipal_subsidies",
                     "status": "ok", "observed": 150, "threshold": 100,
                     "detail": "observed=150 >= 100"},
                ],
            },
            {"axis_id": "2", "label": "data 質", "verdict": "unknown",
             "sub_results": []},
            {"axis_id": "3", "label": "鮮度", "verdict": "unknown",
             "sub_results": []},
            {"axis_id": "4", "label": "組み合わせ", "verdict": "unknown",
             "sub_results": []},
            {"axis_id": "5", "label": "多言語", "verdict": "unknown",
             "sub_results": []},
            {"axis_id": "6", "label": "output", "verdict": "unknown",
             "sub_results": []},
        ],
    }))
    app = _build_test_app(sidecar)
    client = TestClient(app)
    r = client.get("/v1/status/six_axis")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["overall_verdict"] == "ok"
    assert len(body["axes"]) == 6
    # Cache header surfaced
    assert "max-age" in r.headers.get("Cache-Control", "")


def test_rest_sub_drill_in(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    sidecar = tmp_path / "six.json"
    sidecar.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": "2026-05-12T06:30:00Z",
        "overall_verdict": "ok",
        "axes": [{
            "axis_id": "1", "label": "data 量", "verdict": "ok",
            "sub_results": [{
                "sub_id": "1a", "label": "municipal_subsidies",
                "status": "ok", "observed": 150, "threshold": 100,
                "detail": "observed=150 >= 100",
            }],
        }],
    }))
    app = _build_test_app(sidecar)
    client = TestClient(app)
    r = client.get("/v1/status/six_axis/1/1a")
    assert r.status_code == 200
    body = r.json()
    assert body["axis_id"] == "1"
    assert body["sub"]["sub_id"] == "1a"
    # Unknown sub
    r2 = client.get("/v1/status/six_axis/1/zz")
    assert r2.status_code == 404
    r3 = client.get("/v1/status/six_axis/9/9z")
    assert r3.status_code == 404


# ---------------------------------------------------------------------------
# 4. Endpoint coverage audit contract (small smoke)
# ---------------------------------------------------------------------------

def test_endpoint_coverage_audit_runs(tmp_path):
    sys.path.insert(0, str(SCRIPTS_OPS))
    try:
        import audit_endpoint_coverage_v2 as mod  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    openapi = REPO_ROOT / "docs" / "openapi" / "v1.json"
    if not openapi.exists():
        pytest.skip("OpenAPI spec not built")
    out_json = tmp_path / "coverage.json"
    rc = mod.main([
        "--openapi", str(openapi),
        "--out-json", str(out_json),
    ])
    assert rc == 0
    data = json.loads(out_json.read_text())
    assert data["schema_version"] == 1
    assert data["paths_total"] > 0
    assert "verdict" in data
    assert data["verdict"] in {"ok", "degraded", "fail"}
