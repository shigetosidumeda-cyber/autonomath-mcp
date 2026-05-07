#!/usr/bin/env python3
"""Read-only release readiness checklist for production deploy gates.

The script inspects only local repository files. It performs no network calls,
does not mutate files or databases, and reports machine-readable JSON by
default.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_WORKFLOW = Path(".github/workflows/test.yml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
DEPLOY_WORKFLOW = Path(".github/workflows/deploy.yml")
WAF_DOCS = (
    Path("docs/_internal/waf_deploy_gate_prepare_2026-05-06.md"),
    Path("docs/_internal/jpcite_cloudflare_setup.md"),
)
PREFLIGHT_SCRIPT = Path("scripts/ops/preflight_production_improvement.py")
RELEASE_READINESS_TEST = Path("tests/test_release_readiness.py")


@dataclass(frozen=True)
class WorkflowTarget:
    source: str
    path: str


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read(repo_root: Path, rel: Path) -> str:
    return (repo_root / rel).read_text(encoding="utf-8", errors="replace")


def _exists(repo_root: Path, rel: Path) -> bool:
    return (repo_root / rel).exists()


def _pass(name: str, detail: str, evidence: list[str] | None = None) -> Check:
    return Check(name, "PASS", detail, evidence or [])


def _fail(name: str, detail: str, evidence: list[str] | None = None) -> Check:
    return Check(name, "FAIL", detail, evidence or [])


def _workflow_env_targets(repo_root: Path, workflow: Path, name: str) -> list[str] | None:
    try:
        text = _read(repo_root, workflow)
    except FileNotFoundError:
        return None
    match = re.search(rf"^  {re.escape(name)}: >-\n(?P<body>(?:    .+\n)+)", text, re.MULTILINE)
    if not match:
        return None
    return [line.strip() for line in match.group("body").splitlines() if line.strip()]


def _release_ruff_targets(repo_root: Path) -> list[str] | None:
    try:
        text = _read(repo_root, RELEASE_WORKFLOW)
    except FileNotFoundError:
        return None
    match = re.search(
        r"^          ruff check \\\n(?P<body>(?:            .+\n)+)", text, re.MULTILINE
    )
    if not match:
        return None
    targets: list[str] = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:") or stripped.startswith("run:"):
            break
        target = stripped.removesuffix(" \\")
        if target:
            targets.append(target)
    return targets


def _workflow_targets(repo_root: Path) -> list[WorkflowTarget]:
    targets: list[WorkflowTarget] = []
    for workflow, env_name in (
        (TEST_WORKFLOW, "RUFF_TARGETS"),
        (TEST_WORKFLOW, "PYTEST_TARGETS"),
        (RELEASE_WORKFLOW, "RUFF_TARGETS"),
        (RELEASE_WORKFLOW, "PYTEST_TARGETS"),
    ):
        workflow_targets = _workflow_env_targets(repo_root, workflow, env_name)
        if workflow_targets is None:
            continue
        targets.extend(
            WorkflowTarget(f"{workflow} env.{env_name}", target) for target in workflow_targets
        )

    release_ruff_targets = _release_ruff_targets(repo_root)
    if release_ruff_targets is not None:
        targets.extend(
            WorkflowTarget(f"{RELEASE_WORKFLOW} Ruff lint", target)
            for target in release_ruff_targets
        )
    return targets


def _git_tracked_paths(repo_root: Path) -> tuple[set[str] | None, str | None]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git ls-files failed").strip()
        return None, detail
    return {path for path in result.stdout.split("\0") if path}, None


def _is_tracked_target(target: str, tracked_paths: set[str]) -> bool:
    normalized = Path(target).as_posix().removeprefix("./").rstrip("/")
    if normalized in tracked_paths:
        return True
    return any(path.startswith(f"{normalized}/") for path in tracked_paths)


def check_workflow_targets_git_tracked(repo_root: Path) -> Check:
    workflow_targets = _workflow_targets(repo_root)
    if not workflow_targets:
        return _fail(
            "workflow_targets_git_tracked",
            "No workflow lint/test targets could be found to verify against git.",
            [],
        )

    tracked_paths, git_error = _git_tracked_paths(repo_root)
    if tracked_paths is None:
        return _fail(
            "workflow_targets_git_tracked",
            "Workflow target tracking could not be verified because git metadata is unavailable.",
            [git_error or "git metadata unavailable"],
        )

    sources_by_missing_target: dict[str, list[str]] = {}
    for target in workflow_targets:
        if _is_tracked_target(target.path, tracked_paths):
            continue
        sources_by_missing_target.setdefault(target.path, []).append(target.source)

    if sources_by_missing_target:
        evidence = [
            f"{target}: {', '.join(sources)}"
            for target, sources in sorted(sources_by_missing_target.items())
        ]
        return _fail(
            "workflow_targets_git_tracked",
            "Workflow lint/test targets must be committed with the workflow changes.",
            evidence,
        )

    unique_targets = {target.path for target in workflow_targets}
    return _pass(
        "workflow_targets_git_tracked",
        "All workflow lint/test targets are tracked by git.",
        [f"target_count={len(unique_targets)}"],
    )


def check_pytest_targets_synced(repo_root: Path) -> Check:
    test_targets = _workflow_env_targets(repo_root, TEST_WORKFLOW, "PYTEST_TARGETS")
    release_targets = _workflow_env_targets(repo_root, RELEASE_WORKFLOW, "PYTEST_TARGETS")
    if test_targets is None or release_targets is None:
        return _fail(
            "workflow_pytest_targets_synced",
            "test.yml and release.yml must both define env.PYTEST_TARGETS.",
            [
                f"{TEST_WORKFLOW}: {'missing' if test_targets is None else 'present'}",
                f"{RELEASE_WORKFLOW}: {'missing' if release_targets is None else 'present'}",
            ],
        )
    if test_targets != release_targets:
        return _fail(
            "workflow_pytest_targets_synced",
            "release.yml PYTEST_TARGETS must match test.yml exactly.",
            [
                f"test_count={len(test_targets)}",
                f"release_count={len(release_targets)}",
                f"only_in_test={sorted(set(test_targets) - set(release_targets))}",
                f"only_in_release={sorted(set(release_targets) - set(test_targets))}",
            ],
        )
    return _pass(
        "workflow_pytest_targets_synced",
        "release.yml PYTEST_TARGETS matches test.yml.",
        [f"target_count={len(test_targets)}"],
    )


def check_ruff_targets_synced(repo_root: Path) -> Check:
    test_targets = _workflow_env_targets(repo_root, TEST_WORKFLOW, "RUFF_TARGETS")
    release_env_targets = _workflow_env_targets(repo_root, RELEASE_WORKFLOW, "RUFF_TARGETS")
    release_targets = _release_ruff_targets(repo_root)
    if test_targets is None or release_env_targets is None or release_targets is None:
        return _fail(
            "workflow_ruff_targets_synced",
            "test.yml and release.yml RUFF_TARGETS plus release.yml Ruff lint target list must all exist.",
            [
                f"{TEST_WORKFLOW}: {'missing' if test_targets is None else 'present'}",
                f"{RELEASE_WORKFLOW} env.RUFF_TARGETS: {'missing' if release_env_targets is None else 'present'}",
                f"{RELEASE_WORKFLOW}: {'missing' if release_targets is None else 'present'}",
            ],
        )
    if test_targets != release_env_targets or test_targets != release_targets:
        return _fail(
            "workflow_ruff_targets_synced",
            "release.yml RUFF_TARGETS and Ruff lint targets must match test.yml RUFF_TARGETS exactly.",
            [
                f"test_count={len(test_targets)}",
                f"release_env_count={len(release_env_targets)}",
                f"release_count={len(release_targets)}",
                f"only_in_test_vs_release_env={sorted(set(test_targets) - set(release_env_targets))}",
                f"only_in_release_env={sorted(set(release_env_targets) - set(test_targets))}",
                f"only_in_test_vs_release_lint={sorted(set(test_targets) - set(release_targets))}",
                f"only_in_release_lint={sorted(set(release_targets) - set(test_targets))}",
            ],
        )
    return _pass(
        "workflow_ruff_targets_synced",
        "release.yml RUFF_TARGETS and Ruff lint targets match test.yml.",
        [f"target_count={len(test_targets)}"],
    )


def check_release_format_gate_present(repo_root: Path) -> Check:
    try:
        text = _read(repo_root, RELEASE_WORKFLOW)
    except FileNotFoundError:
        return _fail("release_format_gate_present", "release.yml is missing.", [])
    needle = "ruff format --check $RUFF_TARGETS"
    if needle not in text:
        return _fail(
            "release_format_gate_present",
            "release.yml must run the same Ruff format gate as test.yml.",
            [needle],
        )
    return _pass(
        "release_format_gate_present",
        "release.yml runs Ruff format check on RUFF_TARGETS.",
        [needle],
    )


def check_deploy_seed_gate_matches_entrypoint(repo_root: Path) -> Check:
    try:
        text = _read(repo_root, DEPLOY_WORKFLOW)
    except FileNotFoundError:
        return _fail("deploy_seed_gate_matches_entrypoint", "deploy.yml is missing.", [])
    required_tokens = [
        'programs = table_count("programs")',
        'jpi_programs = table_count("jpi_programs")',
        "catalog_count = max(programs, jpi_programs)",
        "if catalog_count < 10_000",
    ]
    missing = [token for token in required_tokens if token not in text]
    if missing:
        evidence: list[str] = []
        evidence.append(f"missing={missing}")
        return _fail(
            "deploy_seed_gate_matches_entrypoint",
            "Production seed gate must accept the transitional programs/jpi_programs catalog.",
            evidence,
        )
    return _pass(
        "deploy_seed_gate_matches_entrypoint",
        "deploy.yml seed gate accepts the programs/jpi_programs transitional catalog contract.",
        required_tokens,
    )


def check_deploy_preflight_gate_present(repo_root: Path) -> Check:
    try:
        text = _read(repo_root, DEPLOY_WORKFLOW)
    except FileNotFoundError:
        return _fail("deploy_preflight_gate_present", "deploy.yml is missing.", [])
    required_tokens = [
        "PRODUCTION_DEPLOY_OPERATOR_ACK_YAML",
        "scripts/ops/pre_deploy_verify.py",
        "scripts/ops/production_deploy_go_gate.py --operator-ack",
        "flyctl deploy --remote-only",
    ]
    missing = [token for token in required_tokens if token not in text]
    evidence: list[str] = []
    if missing:
        evidence.append(f"missing={missing}")
    try:
        preflight_index = text.index("scripts/ops/pre_deploy_verify.py")
        go_gate_index = text.index("scripts/ops/production_deploy_go_gate.py --operator-ack")
        deploy_index = text.index("flyctl deploy --remote-only")
    except ValueError:
        preflight_index = go_gate_index = deploy_index = -1
    if (
        preflight_index == -1
        or go_gate_index == -1
        or deploy_index == -1
        or not (preflight_index < deploy_index and go_gate_index < deploy_index)
    ):
        evidence.append("deploy_preflight_order:invalid")
    if "--warn-only" in text[max(0, preflight_index - 250) : deploy_index]:
        evidence.append("deploy_preflight_warn_only_present")
    if evidence:
        return _fail(
            "deploy_preflight_gate_present",
            "deploy.yml must run local pre-deploy and GO gates before flyctl deploy.",
            evidence,
        )
    return _pass(
        "deploy_preflight_gate_present",
        "deploy.yml runs local pre-deploy and GO gates before flyctl deploy.",
        required_tokens,
    )


def check_cloudflare_waf_docs(repo_root: Path) -> Check:
    present = [str(path) for path in WAF_DOCS if _exists(repo_root, path)]
    evidence: list[str] = []
    for path in WAF_DOCS:
        if not _exists(repo_root, path):
            continue
        text = _read(repo_root, path)
        if "Cloudflare" in text and "WAF" in text:
            evidence.append(str(path))
    if evidence:
        return _pass(
            "cloudflare_waf_docs_present",
            "Cloudflare WAF/deploy-gate documentation exists locally.",
            evidence,
        )
    return _fail(
        "cloudflare_waf_docs_present",
        "At least one local doc must mention both Cloudflare and WAF.",
        [f"present={present}"],
    )


def check_preflight_script_exists(repo_root: Path) -> Check:
    if not _exists(repo_root, PREFLIGHT_SCRIPT):
        return _fail(
            "preflight_script_exists",
            "Production preflight script is missing.",
            [str(PREFLIGHT_SCRIPT)],
        )
    text = _read(repo_root, PREFLIGHT_SCRIPT)
    evidence = [str(PREFLIGHT_SCRIPT)]
    if "read-only" not in text.lower() and "no migration" not in text.lower():
        return _fail(
            "preflight_script_exists",
            "Preflight script exists but does not state read-only/no-migration intent.",
            evidence,
        )
    return _pass(
        "preflight_script_exists",
        "Production preflight script exists and is documented as read-only.",
        evidence,
    )


def check_release_readiness_tests_exist(repo_root: Path) -> Check:
    if not _exists(repo_root, RELEASE_READINESS_TEST):
        return _fail(
            "release_readiness_tests_exist",
            "Release readiness tests are missing.",
            [str(RELEASE_READINESS_TEST)],
        )
    text = _read(repo_root, RELEASE_READINESS_TEST)
    expected_tests = [
        "test_build_report_passes_for_release_ready_repo",
        "test_build_report_flags_major_failures",
        "test_deploy_seed_gate_accepts_jpi_programs_transition",
        "test_build_report_flags_missing_deploy_preflight_gate",
        "test_build_report_flags_missing_release_ruff_targets",
        "test_build_report_flags_untracked_workflow_targets",
        "test_main_warn_only_exits_zero_on_failure",
    ]
    missing = [name for name in expected_tests if name not in text]
    if missing:
        return _fail(
            "release_readiness_tests_exist",
            "Release readiness tests exist but do not cover expected pass/fail/CLI paths.",
            [f"missing={missing}"],
        )
    return _pass(
        "release_readiness_tests_exist",
        "Release readiness tests exist for pass, fail, and warn-only CLI behavior.",
        [str(RELEASE_READINESS_TEST)],
    )


def run_checks(repo_root: Path) -> list[Check]:
    return [
        check_pytest_targets_synced(repo_root),
        check_ruff_targets_synced(repo_root),
        check_workflow_targets_git_tracked(repo_root),
        check_release_format_gate_present(repo_root),
        check_deploy_seed_gate_matches_entrypoint(repo_root),
        check_deploy_preflight_gate_present(repo_root),
        check_cloudflare_waf_docs(repo_root),
        check_preflight_script_exists(repo_root),
        check_release_readiness_tests_exist(repo_root),
    ]


def build_report(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    checks = run_checks(repo_root)
    failing = [check for check in checks if check.status == "FAIL"]
    return {
        "scope": "release readiness; local files only; no network; no mutation",
        "generated_at": _utc_now(),
        "repo_root": str(repo_root),
        "ok": not failing,
        "summary": {
            "pass": sum(1 for check in checks if check.status == "PASS"),
            "fail": len(failing),
            "total": len(checks),
        },
        "checks": [check.as_dict() for check in checks],
        "issues": [check.name for check in failing],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local release-readiness checks.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0 after printing JSON, even when checks fail.",
    )
    args = parser.parse_args(argv)

    report = build_report(args.repo_root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.warn_only:
        return 0
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
