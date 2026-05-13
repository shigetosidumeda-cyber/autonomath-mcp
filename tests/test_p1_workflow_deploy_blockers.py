from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

SAME_DAY_PUSH = WORKFLOWS / "same-day-push-cron.yml"
DISPATCH_WEBHOOKS = WORKFLOWS / "dispatch-webhooks-cron.yml"
STRIPE_BACKFILL = WORKFLOWS / "stripe-backfill-30min.yml"
IDEMPOTENCY_SWEEP = WORKFLOWS / "idempotency-sweep-hourly.yml"
INGEST_DAILY = WORKFLOWS / "ingest-daily.yml"
PAGES_DEPLOY_MAIN = WORKFLOWS / "pages-deploy-main.yml"
EVOLUTION_DASHBOARD = WORKFLOWS / "evolution-dashboard-weekly.yml"
PRODUCTION_GATE_DASHBOARD = WORKFLOWS / "production-gate-dashboard-daily.yml"

PROD_DB_MUTATION_WORKFLOWS = [
    SAME_DAY_PUSH,
    DISPATCH_WEBHOOKS,
    STRIPE_BACKFILL,
    IDEMPOTENCY_SWEEP,
    INGEST_DAILY,
]
OWNED_SCHEDULED_WORKFLOWS = [
    *PROD_DB_MUTATION_WORKFLOWS,
    EVOLUTION_DASHBOARD,
    PRODUCTION_GATE_DASHBOARD,
]
DASHBOARD_PAGES_WORKFLOWS = [
    EVOLUTION_DASHBOARD,
    PRODUCTION_GATE_DASHBOARD,
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dry_run_input_block(path: Path) -> str:
    text = _text(path)
    match = re.search(
        r"      dry_run:\n(?P<body>.*?)(?=^      [a-zA-Z0-9_-]+:|^concurrency:)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{path.name} missing workflow_dispatch dry_run input"
    return match.group("body")


def _cron_specs(path: Path) -> list[str]:
    return re.findall(r'cron:\s*["\']([^"\']+)["\']', _text(path))


def _expand_cron_field(raw: str, *, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        if part == "*":
            values.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            values.update(range(lo, hi + 1, int(part.removeprefix("*/"))))
        else:
            values.add(int(part))
    return values


def test_fly_prod_mutation_jobs_require_ack_or_force_dry_run() -> None:
    for workflow in PROD_DB_MUTATION_WORKFLOWS:
        text = _text(workflow)
        dry_run_input = _dry_run_input_block(workflow)

        assert "flyctl ssh console -a autonomath-api" in text
        assert re.search(r'^\s*default:\s*"true"\s*$', dry_run_input, re.MULTILINE)
        assert "PROD_DB_MUTATION_OPERATOR_ACK: ${{ secrets.PROD_DB_MUTATION_OPERATOR_ACK }}" in text
        assert "I_ACK_PROD_DB_MUTATION" in text
        assert "forcing --dry-run" in text
        assert "--dry-run" in text


def test_owned_scheduled_workflows_do_not_share_utc_minute_hour() -> None:
    seen: dict[tuple[int, int], str] = {}

    for workflow in OWNED_SCHEDULED_WORKFLOWS:
        specs = _cron_specs(workflow)
        assert specs, f"{workflow.name} missing schedule cron"
        for spec in specs:
            minute_field, hour_field, *_ = spec.split()
            for minute in _expand_cron_field(minute_field, lo=0, hi=59):
                for hour in _expand_cron_field(hour_field, lo=0, hi=23):
                    key = (minute, hour)
                    assert key not in seen, (
                        f"{workflow.name} collides with {seen[key]} at UTC "
                        f"{hour:02d}:{minute:02d}"
                    )
                    seen[key] = workflow.name


def test_pages_deploy_fails_closed_when_cloudflare_secrets_missing() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    assert "CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}" in text
    assert "CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}" in text
    assert "::error::CF_API_TOKEN and CF_ACCOUNT_ID are required" in text
    assert "available=false" not in text
    assert "Skipping Cloudflare Pages deploy" not in text


def test_pages_md_route_smoke_is_hard_gate() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    step = text[text.index("Post-deploy smoke (Wave 45 .md catch-all Function)") :]

    assert "https://jpcite.com/laws/chusho-kihon.md?$Q" in step
    assert "https://jpcite.com/enforcement/act-10084.md?$Q" in step
    assert "https://jpcite.com/cases/mirasapo_case_118.md?$Q" in step
    assert "::error::Wave 45 .md smoke failed" in step
    assert re.search(r'if \[ "\$ok" != "true" \]; then\n\s+echo "::error::', step)
    assert re.search(r'if \[ "\$ok" != "true" \]; then.*?\n\s+exit 1', step, re.DOTALL)
    assert "transient failures" not in step
    assert "::warning::Wave 45 .md smoke failed" not in step


def test_dashboard_pages_deploys_use_canonical_project_and_secrets() -> None:
    for workflow in DASHBOARD_PAGES_WORKFLOWS:
        text = _text(workflow)
        assert "CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}" in text
        assert "CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}" in text
        assert "apiToken: ${{ secrets.CF_API_TOKEN }}" in text
        assert "accountId: ${{ secrets.CF_ACCOUNT_ID }}" in text
        assert "projectName: autonomath" in text
        assert "CLOUDFLARE_API_TOKEN" not in text
        assert "CLOUDFLARE_ACCOUNT_ID" not in text
        assert "projectName: jpcite-site" not in text
        assert "::error::CF_API_TOKEN and CF_ACCOUNT_ID are required" in text
