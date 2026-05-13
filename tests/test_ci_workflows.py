from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DEPLOY_JPCITE_API_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-jpcite-api.yml"
RELEASE_READINESS_SCRIPT = REPO_ROOT / "scripts" / "ops" / "release_readiness.py"

REQUIRED_PYTEST_TARGETS = {
    "tests/test_appi_turnstile.py",
    "tests/test_boot_gate.py",
    "tests/test_ci_workflows.py",
    "tests/test_entrypoint_vec0_boot_gate.py",
    "tests/test_fly_health_check.py",
    "tests/test_perf_smoke.py",
    "tests/test_pre_deploy_verify.py",
    "tests/test_production_deploy_go_gate.py",
    "tests/test_production_improvement_preflight.py",
    "tests/test_release_readiness.py",
}
REQUIRED_RUFF_TARGETS = {
    "scripts/ops/perf_smoke.py",
    "scripts/ops/pre_deploy_verify.py",
    "scripts/ops/preflight_production_improvement.py",
    "scripts/ops/production_deploy_go_gate.py",
    "scripts/ops/repo_dirty_lane_report.py",
    "scripts/ops/release_readiness.py",
}


def _workflow_env_targets(workflow: Path, name: str) -> list[str]:
    text = workflow.read_text(encoding="utf-8")
    match = re.search(rf"^  {name}: >-\n(?P<body>(?:    .+\n)+)", text, re.MULTILINE)
    assert match is not None, f"{workflow.name} missing env.{name}"
    return [line.strip() for line in match.group("body").splitlines()]


def _release_ruff_targets() -> list[str]:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"      - name: Ruff lint .+?\n"
        r".+?"
        r"        run: \|\n"
        r"          ruff check \\\n"
        r"(?P<body>(?:            .+? \\\n)*            .+?\n)",
        text,
        re.DOTALL,
    )
    assert match is not None, "release.yml missing Ruff lint target list"
    return [line.strip().removesuffix(" \\") for line in match.group("body").splitlines()]


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {path for path in result.stdout.split("\0") if path}


def _workflow_step_block(workflow: Path, step_name: str) -> str:
    text = workflow.read_text(encoding="utf-8")
    match = re.search(
        rf"^      - name: {re.escape(step_name)}\n(?P<body>.*?)(?=^      - name: |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{workflow.name} missing step {step_name!r}"
    return match.group("body")


def _is_tracked_target(target: str, tracked_paths: set[str]) -> bool:
    normalized = Path(target).as_posix().removeprefix("./").rstrip("/")
    if normalized in tracked_paths:
        return True
    return any(path.startswith(f"{normalized}/") for path in tracked_paths)


def _load_release_readiness():
    spec = importlib.util.spec_from_file_location("release_readiness", RELEASE_READINESS_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_ruff_targets_match_test_workflow() -> None:
    assert _release_ruff_targets() == _workflow_env_targets(TEST_WORKFLOW, "RUFF_TARGETS")


def test_release_ruff_env_targets_match_test_workflow() -> None:
    assert _workflow_env_targets(RELEASE_WORKFLOW, "RUFF_TARGETS") == (
        _workflow_env_targets(TEST_WORKFLOW, "RUFF_TARGETS")
    )


def test_release_pytest_targets_match_test_workflow() -> None:
    assert _workflow_env_targets(RELEASE_WORKFLOW, "PYTEST_TARGETS") == (
        _workflow_env_targets(TEST_WORKFLOW, "PYTEST_TARGETS")
    )


def test_release_pytest_gate_runs_without_deselects() -> None:
    block = _workflow_step_block(RELEASE_WORKFLOW, "Pytest (PYTEST_TARGETS — matches test.yml)")

    assert "pytest $PYTEST_TARGETS -q --tb=short" in block
    for token in ("--deselect", "DESELECTS", "|| true", "continue-on-error: true"):
        assert token not in block


def test_test_workflow_pytest_targets_are_sharded() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    pytest_block = _workflow_step_block(TEST_WORKFLOW, "Pytest with coverage")

    assert "shard-index: [0, 1, 2, 3]" in text
    assert "shard-count: [4]" in text
    assert "Build pytest shard" in text
    assert "pytest-shard-targets.txt" in text
    assert 'pytest "${TARGETS[@]}" -q' in pytest_block
    assert "pytest $PYTEST_TARGETS -q" not in pytest_block


def test_release_runs_ruff_format_check() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "ruff format --check $RUFF_TARGETS" in text


def test_deploy_requires_fly_api_token_fail_closed() -> None:
    block = _workflow_step_block(DEPLOY_WORKFLOW, "Check Fly token")
    missing_token = re.search(
        r'if \[ -z "\$\{FLY_API_TOKEN:-\}" \]; then\n(?P<body>.*?)(?:\n\s*fi)',
        block,
        re.DOTALL,
    )
    assert missing_token is not None
    missing_token_body = missing_token.group("body")
    assert "::error::FLY_API_TOKEN" in missing_token_body
    assert re.search(r"^\s*exit 1\s*$", missing_token_body, re.MULTILINE)
    assert "available=false" not in missing_token_body


def test_deploy_runs_local_gates_before_fly_deploy() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "PRODUCTION_DEPLOY_OPERATOR_ACK_YAML" in text
    assert "python scripts/ops/pre_deploy_verify.py" in text
    assert "python scripts/ops/production_deploy_go_gate.py --operator-ack" in text
    assert (
        "--warn-only"
        not in text[
            text.index("python scripts/ops/pre_deploy_verify.py") : text.index(
                "flyctl deploy --remote-only"
            )
        ]
    )
    assert text.index("python scripts/ops/pre_deploy_verify.py") < text.index(
        "flyctl deploy --remote-only"
    )
    assert text.index("python scripts/ops/production_deploy_go_gate.py --operator-ack") < (
        text.index("flyctl deploy --remote-only")
    )


def test_deploy_checks_live_fly_secret_names_before_fly_deploy() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    gate = _workflow_step_block(DEPLOY_WORKFLOW, "Verify live Fly secret names before deploy")

    assert "flyctl secrets list -a autonomath-api" in gate
    assert "JPCITE_SESSION_SECRET" in gate
    assert "values not read" in gate
    assert text.index("Verify live Fly secret names before deploy") < text.index(
        "flyctl deploy --remote-only"
    )


def test_jpcite_api_deploy_checks_live_fly_secret_names_before_fly_deploy() -> None:
    text = DEPLOY_JPCITE_API_WORKFLOW.read_text(encoding="utf-8")
    gate = _workflow_step_block(
        DEPLOY_JPCITE_API_WORKFLOW,
        "Verify live Fly secret names before deploy",
    )

    assert "flyctl secrets list -a jpcite-api" in gate
    assert "JPCITE_SESSION_SECRET" in gate
    assert "values not read" in gate
    assert text.index("Verify live Fly secret names before deploy") < text.index(
        "flyctl deploy --remote-only"
    )


def test_deploy_manual_dispatch_requires_expected_sha() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    checkout = _workflow_step_block(DEPLOY_WORKFLOW, "Checkout")
    verify = _workflow_step_block(DEPLOY_WORKFLOW, "Resolve and verify deployment SHA")

    assert "workflow_dispatch:" in text
    assert "expected_sha:" in text
    assert "required: true" in text[text.index("expected_sha:") : text.index("concurrency:")]
    assert "github.event.inputs.expected_sha" in checkout
    assert 'DEPLOY_SHA="$(git rev-parse HEAD)"' in verify
    assert "EXPECTED_SHA=" in verify
    assert 'if [ "$DEPLOY_SHA" != "$EXPECTED_SHA" ]; then' in verify
    assert 'echo "sha=$DEPLOY_SHA"' in verify
    assert 'echo "short=${DEPLOY_SHA::7}"' in verify


def test_deploy_uses_resolved_sha_for_release_fly_labels_and_failure_notice() -> None:
    version = _workflow_step_block(DEPLOY_WORKFLOW, "Extract release version from pyproject.toml")
    deploy = _workflow_step_block(DEPLOY_WORKFLOW, "Deploy (remote builder)")
    pre_probe = _workflow_step_block(DEPLOY_WORKFLOW, "Verify Fly machine state pre-probe")
    notify = _workflow_step_block(DEPLOY_WORKFLOW, "Notify Slack on failure")

    assert "steps.deploy-sha.outputs.short" in version
    assert "GITHUB_SHA::7" not in version
    assert "--label GH_SHA=${{ steps.deploy-sha.outputs.sha }}" in deploy
    assert "--label org.opencontainers.image.revision=${{ steps.deploy-sha.outputs.sha }}" in deploy
    assert (
        "--image-label deployment-${{ steps.deploy-sha.outputs.short }}-${{ github.run_id }}"
        in deploy
    )
    assert "flyctl image show -a autonomath-api --json" in pre_probe
    assert 'os.environ["DEPLOY_SHA"]' in pre_probe
    assert "Fly image SHA mismatch" in pre_probe
    assert "steps.deploy-sha.outputs.short" in notify
    assert "GITHUB_SHA::7" not in notify


def test_deploy_preflight_missing_db_skip_is_limited_to_predeploy_step() -> None:
    predeploy = _workflow_step_block(DEPLOY_WORKFLOW, "Run local pre-deploy verification")

    assert 'JPCITE_PREFLIGHT_ALLOW_MISSING_DB: "1"' in predeploy
    assert "python scripts/ops/pre_deploy_verify.py" in predeploy
    assert predeploy.count('JPCITE_PREFLIGHT_ALLOW_MISSING_DB: "1"') == 1


def test_required_pytest_targets_are_in_ci() -> None:
    assert set(_workflow_env_targets(TEST_WORKFLOW, "PYTEST_TARGETS")) >= (REQUIRED_PYTEST_TARGETS)
    assert set(_workflow_env_targets(RELEASE_WORKFLOW, "PYTEST_TARGETS")) >= (
        REQUIRED_PYTEST_TARGETS
    )


def test_required_ruff_targets_are_in_ci() -> None:
    assert set(_workflow_env_targets(TEST_WORKFLOW, "RUFF_TARGETS")) >= (REQUIRED_RUFF_TARGETS)
    assert set(_workflow_env_targets(RELEASE_WORKFLOW, "RUFF_TARGETS")) >= (REQUIRED_RUFF_TARGETS)
    assert set(_release_ruff_targets()) >= REQUIRED_RUFF_TARGETS


def test_workflow_target_tracking_check_matches_current_repo_state() -> None:
    targets = set(_workflow_env_targets(TEST_WORKFLOW, "RUFF_TARGETS"))
    targets.update(_workflow_env_targets(TEST_WORKFLOW, "PYTEST_TARGETS"))
    targets.update(_workflow_env_targets(RELEASE_WORKFLOW, "RUFF_TARGETS"))
    targets.update(_workflow_env_targets(RELEASE_WORKFLOW, "PYTEST_TARGETS"))
    targets.update(_release_ruff_targets())

    tracked_paths = _tracked_paths()
    missing = sorted(target for target in targets if not _is_tracked_target(target, tracked_paths))
    check = _load_release_readiness().check_workflow_targets_git_tracked(REPO_ROOT)

    if missing:
        assert check.status == "FAIL"
        evidence_targets = sorted(item.split(": ", 1)[0] for item in check.evidence)
        assert evidence_targets == missing
    else:
        assert check.status == "PASS"
