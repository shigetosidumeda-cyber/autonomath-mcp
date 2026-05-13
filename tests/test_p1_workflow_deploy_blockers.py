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
PAGES_PREVIEW = WORKFLOWS / "pages-preview.yml"
PAGES_REGENERATE = WORKFLOWS / "pages-regenerate.yml"
PAGES_CATCH_ALL_FUNCTION = REPO_ROOT / "functions" / "[[path]].ts"
PAGES_ROUTES = REPO_ROOT / "site" / "_routes.json"
STATUS_PROBE_CRON = WORKFLOWS / "status-probe-cron.yml"
STATUS_UPDATE = WORKFLOWS / "status_update.yml"
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
                        f"{workflow.name} collides with {seen[key]} at UTC {hour:02d}:{minute:02d}"
                    )
                    seen[key] = workflow.name


def test_pages_deploy_fails_closed_when_cloudflare_secrets_missing() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    assert "CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}" in text
    assert "CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}" in text
    assert "::error::CF_API_TOKEN and CF_ACCOUNT_ID are required" in text
    assert "available=false" not in text
    assert "Skipping Cloudflare Pages deploy" not in text


def test_pages_workflows_serialize_and_avoid_preview_main_publish() -> None:
    preview = _text(PAGES_PREVIEW)
    preview_push_block = re.search(
        r"  push:\n(?P<body>.*?)(?=^  workflow_dispatch:|^concurrency:)",
        preview,
        re.MULTILINE | re.DOTALL,
    )
    assert preview_push_block is not None
    assert "- main" not in preview_push_block.group("body")
    assert "github.ref_name != 'main'" in preview

    for workflow in (PAGES_PREVIEW, PAGES_DEPLOY_MAIN, PAGES_REGENERATE):
        text = _text(workflow)
        assert "group: cf-pages-autonomath-${{ github.ref }}" in text
        assert ".timeout 300000" in text
        assert "${GITHUB_RUN_ID}.${GITHUB_RUN_ATTEMPT}.db" in text
        assert "trap cleanup_remote_db EXIT" in text


def test_status_probe_cron_can_import_src_package() -> None:
    for workflow in (STATUS_PROBE_CRON, STATUS_UPDATE):
        text = _text(workflow)
        assert "PYTHONPATH: src" in text or "pip install -e" in text


def test_pages_source_backed_route_smoke_is_hard_gate() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    step = text[text.index("Post-deploy smoke (source-backed catch-all Function)") :]

    assert "https://jpcite.com/laws/chusho-kihon?$Q" in step
    assert "https://jpcite.com/laws/chusho-kihon.html?$Q" in step
    assert "https://jpcite.com/laws/chusho-kihon.md?$Q" in step
    assert "https://jpcite.com/enforcement/act-10084.md?$Q" in step
    assert "https://jpcite.com/cases/mirasapo_case_118.md?$Q" in step
    assert "::error::source-backed smoke failed" in step
    assert re.search(r'if \[ "\$ok" != "true" \]; then\n\s+echo "::error::', step)
    assert re.search(r'if \[ "\$ok" != "true" \]; then.*?\n\s+exit 1', step, re.DOTALL)
    assert "transient failures" not in step
    assert "::warning::source-backed smoke failed" not in step


def test_pages_law_html_artifact_trim_is_backed_by_function_proxy() -> None:
    for workflow in (PAGES_PREVIEW, PAGES_DEPLOY_MAIN, PAGES_REGENERATE):
        text = _text(workflow)
        assert "--include 'laws/index.html'" in text
        assert "--exclude 'laws/*.html'" in text
        assert text.index("--include 'laws/index.html'") < text.index("--exclude 'laws/*.html'")
        assert text.index("--exclude 'laws/*.html'") < text.index("--exclude '*.md'")

    function = _text(PAGES_CATCH_ALL_FUNCTION)
    assert "function sourceBackedLawHtmlPath(pathname: string): string | null" in function
    assert 'const prefix = "/laws/";' in function
    assert "return `${pathname}.html`;" in function
    assert 'const HTML_CONTENT_TYPE = "text/html; charset=utf-8";' in function
    assert 'sourceHeader: "x-jpcite-html-source"' in function
    assert '"content-type": MD_CONTENT_TYPE,' not in function

    routes = _text(PAGES_ROUTES)
    assert '"/laws/*"' in routes
    assert '"/*"' not in routes


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
