"""Static gates for monitoring and DR deploy readiness."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_monitoring_readme_documents_sentry_and_status_probe_gates() -> None:
    text = (REPO_ROOT / "monitoring" / "README.md").read_text(encoding="utf-8")
    required = [
        "Deploy Gate Contract",
        "SENTRY_DSN",
        "JPINTEL_ENV=prod",
        "/v1/am/health/deep",
        "sentry_active=true",
        "scripts/ops/status_probe.py",
        "scripts/cron/aggregate_status_alerts_hourly.py",
        "site/status/status_alerts_w41.json",
        "critical_count",
    ]
    for marker in required:
        assert marker in text, f"monitoring gate marker missing: {marker}"


def test_dr_runbook_rto_rpo_contract_is_present() -> None:
    text = (REPO_ROOT / "docs" / "runbook" / "disaster_recovery.md").read_text(
        encoding="utf-8"
    )
    for marker in [
        "| DB",
        "RPO",
        "RTO",
        "jpintel.db",
        "1 h",
        "30 min",
        "autonomath.db",
        "24 h",
        "2 h",
        "RTO/RPO deploy gate",
        "scripts/cron/verify_backup_daily.py",
        "VERIFY_MAX_AGE_HOURS",
        "VERIFY_BACKUP_PROD=1",
    ]:
        assert marker in text, f"DR RTO/RPO marker missing: {marker}"


def test_incident_runbooks_exist_for_dr_escalation() -> None:
    runbook_dir = REPO_ROOT / "docs" / "runbook"
    incidents = sorted(runbook_dir.glob("*incident*.md"))
    assert incidents, "expected at least one incident response runbook"
    assert any("db_boot_hang" in path.name for path in incidents), incidents
