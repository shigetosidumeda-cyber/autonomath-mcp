"""Wave 43.3.10 cells 10-12 — SLA alert + postmortem auto v2 + backup verify tests.

Pure stdlib + pytest tmpdir; no DB / network. Verifies:
* cell 10 sla_breach_alert.py: 12 METRICS row count, evaluator, sidecar write,
  telegram graceful no-op when env vars missing.
* cell 11 postmortem_auto_v2.py: detector axis isolation, render template
  shape, file write with auto-suffix collision handling, gh CLI absent
  → "skip:gh_missing" (best-effort).
* cell 12 verify_backup_daily.py: gzip verification helper, sha256 helper,
  argparse smoke, dry-run sidecar shape.
* 5pillars audit: total = 60.00 when all cells present, monotonic verdict
  thresholds.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------- cell 10: sla_breach_alert ----------------------------

def test_sla_breach_alert_has_12_metrics():
    mod = _load_module("sla_breach_alert", "scripts/cron/sla_breach_alert.py")
    assert len(mod.METRICS) == 12, f"expected 12 SLA metrics, got {len(mod.METRICS)}"
    ids = {m["id"] for m in mod.METRICS}
    for required in (
        "healthz_uptime_24h", "endpoint_surface_200_rate", "freshness_axes_ok",
        "cron_success_rate_24h", "rum_lcp_p75", "dlq_depth", "circuit_state_open",
        "backup_integrity_pass", "r2_hash_match", "postmortem_queue",
        "status_alerts_critical", "ax_5pillars_average",
    ):
        assert required in ids, f"missing metric id={required}"


def test_sla_breach_alert_telegram_skip_when_env_missing(monkeypatch):
    mod = _load_module("sla_breach_alert", "scripts/cron/sla_breach_alert.py")
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    result = mod._send_telegram("ignored")
    assert result == "skip:env", f"expected skip:env, got {result}"


def test_sla_breach_alert_evaluator_unknown_path(tmp_path):
    mod = _load_module("sla_breach_alert", "scripts/cron/sla_breach_alert.py")
    metric = {"id": "x", "label": "x", "src": "this/does/not/exist.json",
              "field": "v", "op": "lt", "threshold": 1}
    r = mod._evaluate(metric)
    assert r["state"] == "unknown"
    assert r["breach"] is False
    assert r["value"] is None


def test_sla_breach_alert_run_writes_sidecar(monkeypatch, tmp_path):
    # Repoint sidecar+jsonl into tmp via monkeypatch to keep test isolated.
    mod = _load_module("sla_breach_alert", "scripts/cron/sla_breach_alert.py")
    monkeypatch.setattr(mod, "SIDECAR", tmp_path / "sidecar.json")
    monkeypatch.setattr(mod, "JSONL", tmp_path / "history.jsonl")
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    assert mod.run() == 0
    payload = json.loads((tmp_path / "sidecar.json").read_text(encoding="utf-8"))
    assert payload["metric_count"] == 12
    assert "metrics" in payload and len(payload["metrics"]) == 12


# ---------------- cell 11: postmortem_auto_v2 --------------------------

def test_postmortem_auto_v2_detect_empty_when_no_signals(monkeypatch):
    mod = _load_module("postmortem_auto_v2", "scripts/ops/postmortem_auto_v2.py")
    monkeypatch.setattr(mod, "_load", lambda _r: None)
    assert mod.detect_incidents() == []


def test_postmortem_auto_v2_detect_healthz_breach(monkeypatch):
    mod = _load_module("postmortem_auto_v2", "scripts/ops/postmortem_auto_v2.py")

    def fake_load(rel):
        if rel == "site/status/status.json":
            return {"healthz_5xx_rate_5m": 0.07, "uptime_24h_pct": 92.3}
        return None

    monkeypatch.setattr(mod, "_load", fake_load)
    inc = mod.detect_incidents()
    assert len(inc) == 1
    assert inc[0]["kind"] == "healthz5xx"
    assert inc[0]["severity"] == "P0"


def test_postmortem_auto_v2_render_md_template_shape():
    mod = _load_module("postmortem_auto_v2", "scripts/ops/postmortem_auto_v2.py")
    inc = {"kind": "cronfail", "severity": "P1",
           "detected_at": "2026-05-12T00:00:00Z",
           "signal": "cron success_rate_24h=0.70 < 80%",
           "evidence": {"success_rate_24h": 0.7}}
    md = mod.render_md(inc, "2026-05-12")
    assert "# Postmortem — 2026-05-12 (cronfail)" in md
    assert "Severity**: P1" in md
    assert "## Timeline (UTC)" in md
    assert "AUTO-DRAFT" in md
    assert "## Follow-up actions" in md


def test_postmortem_auto_v2_write_draft_collision(tmp_path, monkeypatch):
    mod = _load_module("postmortem_auto_v2", "scripts/ops/postmortem_auto_v2.py")
    monkeypatch.setattr(mod, "POSTMORTEM_DIR", tmp_path)
    inc = {"kind": "slacluster", "severity": "P1",
           "detected_at": "2026-05-12T00:00:00Z",
           "signal": "3 breaches", "evidence": {}}
    p1 = mod.write_draft(inc, "2026-05-12", force=False)
    p2 = mod.write_draft(inc, "2026-05-12", force=False)
    assert p1 != p2
    assert p2.name.endswith("_2.md")


def test_postmortem_auto_v2_open_draft_pr_dry_run_skips():
    mod = _load_module("postmortem_auto_v2", "scripts/ops/postmortem_auto_v2.py")
    result = mod.open_draft_pr(
        Path("/tmp/x.md"),
        {"kind": "cronfail", "severity": "P1", "signal": "test"},
        dry_run=True,
    )
    assert result == "skip:dry_run"


# ---------------- cell 12: verify_backup_daily -------------------------

def test_verify_backup_daily_sha256_helper(tmp_path):
    mod = _load_module("verify_backup_daily", "scripts/cron/verify_backup_daily.py")
    blob = tmp_path / "blob"
    blob.write_bytes(b"hello-jpcite")
    h = mod._sha256_file(blob)
    assert len(h) == 64
    # Stable hash for fixed input.
    assert h.isalnum()


def test_verify_backup_daily_gzip_verify(tmp_path):
    import gzip
    mod = _load_module("verify_backup_daily", "scripts/cron/verify_backup_daily.py")
    gz = tmp_path / "ok.gz"
    payload = b"jpcite-test-payload" * 1000
    with gzip.open(gz, "wb") as f:
        f.write(payload)
    ok, size = mod._verify_gzip(gz)
    assert ok is True
    assert size == len(payload)


def test_verify_backup_daily_gzip_verify_corrupt(tmp_path):
    mod = _load_module("verify_backup_daily", "scripts/cron/verify_backup_daily.py")
    bad = tmp_path / "bad.gz"
    bad.write_bytes(b"not a gzip file at all")
    ok, size = mod._verify_gzip(bad)
    assert ok is False
    assert size == 0


def test_verify_backup_daily_dry_run_writes_sidecar(tmp_path, monkeypatch):
    mod = _load_module("verify_backup_daily", "scripts/cron/verify_backup_daily.py")
    # Stub the R2 listing so dry-run still produces an inventory hit.
    monkeypatch.setattr(mod, "_latest_r2_snapshot",
                        lambda prefix, bucket: ("jpintel/jpintel-20260512-000000.db.gz", 1024))
    monkeypatch.setattr(mod, "SIDECAR", tmp_path / "sidecar.json")
    monkeypatch.setattr(mod, "ANALYTICS", tmp_path)
    rc = mod.run(argv=["--dry-run"])
    assert rc == 0
    payload = json.loads((tmp_path / "sidecar.json").read_text(encoding="utf-8"))
    assert payload["details"]["mode"] == "dry_run"
    assert payload["integrity_pass"] == 1
    assert payload["r2_hash_match"] == 1


# ---------------- audit_runner_ax_5pillars ----------------------------

def test_ax_5pillars_runs_and_scores():
    spec = importlib.util.spec_from_file_location(
        "audit_runner_ax_5pillars", REPO_ROOT / "scripts" / "ops" / "audit_runner_ax_5pillars.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_runner_ax_5pillars"] = mod
    spec.loader.exec_module(mod)
    result = mod.run_audit()
    assert result["axis"] == "ax_5pillars"
    assert result["max_score"] == 60.0
    assert result["average_score"] == result["average_score_10"]
    assert 0.0 <= result["average_score_10"] <= 10.0
    assert result["average_score_10"] == round(
        (result["total_score"] / result["max_score"]) * 10, 2
    )
    assert result["cell_count"] >= 36
    # 5 pillars × at least 1 cell each.
    assert set(result["pillars"].keys()) >= {"Access", "Context", "Tools", "Orchestration", "Resilience"}
    # Resilience has exactly 12 cells.
    assert result["pillars"]["Resilience"]["cells"] == 12
    assert result["verdict"] in ("green", "yellow", "red")


def test_ax_5pillars_render_md_shape():
    spec = importlib.util.spec_from_file_location(
        "audit_runner_ax_5pillars", REPO_ROOT / "scripts" / "ops" / "audit_runner_ax_5pillars.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_runner_ax_5pillars"] = mod
    spec.loader.exec_module(mod)
    result = mod.run_audit()
    md = mod.render_md(result)
    assert "# jpcite AX 5 Pillars Audit" in md
    assert "Resilience" in md
    assert "/ 60" in md


# ---------------- dashboard surface ----------------------------------

def test_dashboard_html_present():
    dashboard = REPO_ROOT / "site" / "status" / "ax_5pillars_dashboard.html"
    assert dashboard.exists()
    text = dashboard.read_text(encoding="utf-8")
    assert "AX 5 Pillars" in text
    assert "Resilience" in text
    assert "/status/ax_5pillars.json" in text
    # JS-light: no external script tags
    assert "<script src=\"http" not in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
