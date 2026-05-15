from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

SAME_DAY_PUSH = WORKFLOWS / "same-day-push-cron.yml"
DISPATCH_WEBHOOKS = WORKFLOWS / "dispatch-webhooks-cron.yml"
STRIPE_BACKFILL = WORKFLOWS / "stripe-backfill-30min.yml"
IDEMPOTENCY_SWEEP = WORKFLOWS / "idempotency-sweep-hourly.yml"
INGEST_DAILY = WORKFLOWS / "ingest-daily.yml"
PAGES_DEPLOY_MAIN = WORKFLOWS / "pages-deploy-main.yml"
DEPLOY = WORKFLOWS / "deploy.yml"
PAGES_PREVIEW = WORKFLOWS / "pages-preview.yml"
PAGES_REGENERATE = WORKFLOWS / "pages-regenerate.yml"
PAGES_CATCH_ALL_FUNCTION = REPO_ROOT / "functions" / "[[path]].ts"
PAGES_ROUTES = REPO_ROOT / "site" / "_routes.json"
STATUS_PROBE_CRON = WORKFLOWS / "status-probe-cron.yml"
STATUS_UPDATE = WORKFLOWS / "status_update.yml"
REFRESH_SOURCES_DAILY = WORKFLOWS / "refresh-sources-daily.yml"
NARRATIVE_SLA_BREACH = WORKFLOWS / "narrative-sla-breach-hourly.yml"
CHAOS_24_7 = WORKFLOWS / "chaos-24-7.yml"
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


def _workflow_yaml(path: Path) -> dict:
    data = yaml.safe_load(_text(path))
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


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


def test_deploy_live_fly_secret_gate_requires_edge_auth_secret_and_consistent_optional_x402() -> None:
    text = _text(DEPLOY)
    step = text[text.index("Verify live Fly secret names before deploy") :]

    assert "JPCITE_EDGE_AUTH_SECRET" in step
    assert "JPCITE_X402_ADDRESS" in step
    assert "JPCITE_X402_ORIGIN_SECRET" in step
    assert "JPCITE_X402_QUOTE_SECRET" in step
    assert "Partial x402 Fly secret configuration" in step
    assert "Set all or none" in step
    assert "x402 Fly origin bridge secrets are not configured" in step
    assert "Missing required Fly secret names for autonomath-api" in step


def test_deploy_presigns_fresh_r2_seed_or_fails_closed() -> None:
    text = _text(DEPLOY)
    step = text[text.index("Deploy (remote builder)") :]

    assert "autonomath-api/jpintel.db.gz" in step
    assert "autonomath-api/jpintel-" in step
    assert "JPINTEL_R2_SEED_MAX_AGE_SECONDS" in step
    assert "ContentLength" in step
    assert "R2 seed too small" in step
    assert "R2 seed is stale" in step
    assert "aws s3 presign" in step


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


def test_status_probe_cron_is_only_scheduled_status_writer() -> None:
    status_probe = _workflow_yaml(STATUS_PROBE_CRON)
    legacy_status_update = _workflow_yaml(STATUS_UPDATE)

    assert status_probe["on"] == {
        "schedule": [{"cron": "*/5 * * * *"}],
        "workflow_dispatch": {},
    }
    assert legacy_status_update["on"] == {"workflow_dispatch": {}}


def test_status_probe_workflow_permissions_are_minimal_for_commit_and_dispatch() -> None:
    for workflow in (STATUS_PROBE_CRON, STATUS_UPDATE):
        parsed = _workflow_yaml(workflow)
        assert parsed["permissions"] == {
            "contents": "write",
            "actions": "write",
        }


def test_status_probe_workflows_commit_all_public_status_artifacts_and_dispatch_pages() -> None:
    for workflow in (STATUS_PROBE_CRON, STATUS_UPDATE):
        text = _text(workflow)
        assert "actions: write" in text
        assert "group: status-probe-${{ github.ref }}" in text
        assert "site/status/status.json" in text
        assert "site/status/status_components.json" in text
        assert "--badge-out site/status/badge.svg" in text
        assert "git push origin" in text
        assert "GITHUB_TOKEN pushes do not trigger downstream push workflows" in text
        assert "gh workflow run pages-deploy-main.yml --ref" in text

    pages_deploy = _text(PAGES_DEPLOY_MAIN)
    assert "- \"site/**\"" in pages_deploy


def test_pages_deploy_main_triggers_on_pages_functions_changes() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    push_block = re.search(
        r"  push:\n(?P<body>.*?)(?=^  workflow_dispatch:|^concurrency:)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert push_block is not None
    body = push_block.group("body")
    assert '- "functions/**"' in body
    assert '- "functions/package*.json"' in body
    assert '- "functions/tsconfig.json"' in body


def test_pages_deploy_main_typechecks_functions_before_publish() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    typecheck_step = text.index("Typecheck Pages Functions")
    publish_step = text.index("Publish to Cloudflare Pages")

    assert typecheck_step < publish_step
    assert "npm ci --prefix functions" in text
    assert "npm run --prefix functions typecheck" in text


def test_refresh_sources_daily_hydrates_live_db_or_writes_skipped_reports() -> None:
    text = _text(REFRESH_SOURCES_DAILY)

    assert "Install flyctl" in text
    assert "Hydrate jpintel.db from Fly volume" in text
    assert "FLY_API_TOKEN" in text
    assert "sqlite3 /data/jpintel.db" in text
    assert "mv jpintel.live.db data/jpintel.db" in text
    assert "python scripts/refresh_sources.py --db data/jpintel.db" in text
    assert "if: steps.hydrate_db.outputs.ready == 'true'" in text
    assert "Write skipped reports when DB unavailable" in text
    assert "missing_fly_api_token_or_db" in text


def test_narrative_sla_breach_remote_command_is_shell_wrapped() -> None:
    text = _text(NARRATIVE_SLA_BREACH)

    assert '-C "sh -lc ' in text
    assert "exec /opt/venv/bin/python /app/scripts/cron/narrative_report_sla_breach.py" in text


def test_chaos_24_7_uses_runner_side_toxiproxy_wait_and_module_uvicorn() -> None:
    text = _text(CHAOS_24_7)

    assert "Wait for Toxiproxy" in text
    assert "curl -fsS http://127.0.0.1:8474/version" in text
    assert "python -m uvicorn jpintel_mcp.api.main:app" in text
    assert "wget -q --spider" not in text
    assert ".venv/bin/uvicorn" not in text


def test_pages_source_backed_route_smoke_is_hard_gate() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    step = text[
        text.index("Post-deploy smoke (generated pages and source-backed Function)") :
    ]

    assert "https://jpcite.com/laws/chusho-kihon?$Q" in step
    assert "https://jpcite.com/laws/chusho-kihon.html?$Q" in step
    assert (
        "https://jpcite.com/programs/"
        "jizoku-ka-hojokin-ippankei-tsuujou-waku-shoukou-kai-han-dai-defacd.html?$Q"
        in step
    )
    assert "https://jpcite.com/enforcement/act-10084.html?$Q" in step
    assert "https://jpcite.com/cases/mirasapo_case_118.html?$Q" in step
    assert "https://jpcite.com/laws/chusho-kihon.md?$Q" in step
    assert "https://jpcite.com/enforcement/act-10084.md?$Q" in step
    assert "https://jpcite.com/cases/mirasapo_case_118.md?$Q" in step
    assert 'curl -s -L -o /dev/null -w "%{http_code}"' in step
    assert "::error::source-backed smoke failed" in step
    assert re.search(r'if \[ "\$ok" != "true" \]; then\n\s+echo "::error::', step)
    assert re.search(r'if \[ "\$ok" != "true" \]; then.*?\n\s+exit 1', step, re.DOTALL)
    assert "transient failures" not in step
    assert "::warning::source-backed smoke failed" not in step


def test_pages_deploy_smokes_x402_edge_quote() -> None:
    text = _text(PAGES_DEPLOY_MAIN)
    assert "Post-deploy smoke (x402 edge quote)" in text
    step = text[text.index("Post-deploy smoke (x402 edge quote)") :]

    assert "https://jpcite.com/x402/discovery?$Q" in step
    assert "https://jpcite.com/x402/quote?$Q" in step
    assert "x402 discovery smoke OK" in step
    assert 'print("x402 discovery smoke OK", file=sys.stderr)' in step
    assert "x402 quote smoke skipped: edge recipient secret not configured" in step
    assert (
        '"quote_id", "amount_usdc", "amount_usdc_micro", "recipient", '
        '"chain_id", "token_address", "signature"'
    ) in step
    assert "x402 quote response missing keys" in step
    assert "x402 quote smoke OK" in step


def test_pages_generated_html_artifact_trim_is_backed_by_function_proxy() -> None:
    trimmed_cohorts = ("laws", "cases", "enforcement")
    for workflow in (PAGES_PREVIEW, PAGES_DEPLOY_MAIN, PAGES_REGENERATE):
        text = _text(workflow)
        for cohort in trimmed_cohorts:
            assert f"--include '{cohort}/index.html'" in text
            assert f"--exclude '{cohort}/*.html'" in text
            assert text.index(f"--include '{cohort}/index.html'") < text.index(
                f"--exclude '{cohort}/*.html'"
            )
            assert text.index(f"--exclude '{cohort}/*.html'") < text.index(
                "--exclude '*.md'"
            )
        assert "--exclude 'programs/*.html'" not in text
        assert "--include 'programs/share.html'" not in text
        assert "Cloudflare Pages artifact has ${file_count} files" in text

    function = _text(PAGES_CATCH_ALL_FUNCTION)
    assert (
        "function sourceBackedGeneratedHtmlPath(pathname: string): string | null"
        in function
    )
    assert '"/laws/"' in function
    assert '"/programs/"' not in function
    assert '"/cases/"' in function
    assert '"/enforcement/"' in function
    assert "return `${pathname}.html`;" in function
    assert 'const HTML_CONTENT_TYPE = "text/html; charset=utf-8";' in function
    assert 'sourceHeader: "x-jpcite-html-source"' in function
    assert "raw.githubusercontent.com/shigetosidumeda-cyber/autonomath-mcp/main/site" not in function
    assert "CF_PAGES_COMMIT_SHA" in function
    assert "JPCITE_SOURCE_REF" in function
    assert "source_ref_unpinned" in function
    assert '"x-jpcite-source-ref"' in function
    assert '"Content-Security-Policy"' in function
    assert '"X-Frame-Options"' in function
    assert '"content-type": MD_CONTENT_TYPE,' not in function

    routes = _text(PAGES_ROUTES)
    assert '"/laws/*"' in routes
    assert '"/programs/*"' not in routes
    assert '"/cases/*"' in routes
    assert '"/enforcement/*"' in routes
    assert '"/*"' not in routes


def test_dashboard_workflows_cannot_bypass_central_pages_deploy() -> None:
    for workflow in DASHBOARD_PAGES_WORKFLOWS:
        text = _text(workflow)
        assert "Production deploy handoff" in text
        assert "Dashboard artifact uploaded only." in text
        assert "pages-deploy-main.yml" in text
        assert "cloudflare/pages-action" not in text
        assert "apiToken: ${{ secrets.CF_API_TOKEN }}" not in text
        assert "accountId: ${{ secrets.CF_ACCOUNT_ID }}" not in text
        assert "directory: site" not in text
        assert "branch: main" not in text
        assert "deployments: write" not in text
        assert "CLOUDFLARE_API_TOKEN" not in text
        assert "CLOUDFLARE_ACCOUNT_ID" not in text
        assert "projectName: jpcite-site" not in text
