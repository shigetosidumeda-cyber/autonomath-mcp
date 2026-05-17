from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "release_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_readiness", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _track_all(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)


def _seed_ready_repo(root: Path) -> None:
    ruff_targets = "\n".join(
        [
            "    scripts/a.py",
            "    scripts/b.py",
        ]
    )
    pytest_targets = "\n".join(
        [
            "    tests/test_a.py",
            "    tests/test_b.py",
        ]
    )
    _write(
        root / ".github/workflows/test.yml",
        f"""name: test

env:
  RUFF_TARGETS: >-
{ruff_targets}
  PYTEST_TARGETS: >-
{pytest_targets}
""",
    )
    _write(
        root / ".github/workflows/release.yml",
        f"""name: release

env:
  RUFF_TARGETS: >-
{ruff_targets}
  PYTEST_TARGETS: >-
{pytest_targets}

jobs:
  test:
    steps:
      - name: Ruff lint (CLAUDE.md Quality gates target)
        run: |
          ruff check \\
            scripts/a.py \\
            scripts/b.py
      - name: Ruff format check
        run: ruff format --check $RUFF_TARGETS
      - name: Pytest
        run: pytest $PYTEST_TARGETS -q --tb=short
""",
    )
    _write(
        root / ".github/workflows/deploy.yml",
        """name: deploy
jobs:
  fly:
    steps:
      - name: Prepare production deploy operator ACK
        env:
          PRODUCTION_DEPLOY_OPERATOR_ACK_YAML: ${{ secrets.PRODUCTION_DEPLOY_OPERATOR_ACK_YAML }}
        run: |
          printf '%s\n' "$PRODUCTION_DEPLOY_OPERATOR_ACK_YAML" > "$RUNNER_TEMP/ack.yml"
      - name: Run local pre-deploy verification
        run: python scripts/ops/pre_deploy_verify.py
      - name: Run production deploy readiness gate
        run: python scripts/ops/production_deploy_readiness_gate.py
      - name: Run production deploy GO gate
        run: python scripts/ops/production_deploy_go_gate.py --operator-ack "$RUNNER_TEMP/ack.yml"
      - name: Hydrate jpintel seed DB for Docker build
        run: |
          programs = table_count("programs")
          jpi_programs = table_count("jpi_programs")
          catalog_count = max(programs, jpi_programs)
          if catalog_count < 10_000:
              raise SystemExit("catalog too small")
      - name: Deploy (remote builder)
        run: flyctl deploy --remote-only
""",
    )
    _write(root / "scripts/a.py", "print('a')\n")
    _write(root / "scripts/b.py", "print('b')\n")
    _write(root / "tests/test_a.py", "def test_a(): pass\n")
    _write(root / "tests/test_b.py", "def test_b(): pass\n")
    _write(root / "README.md", "jpcite production surface\n")
    _write(root / "site/llms.txt", "jpcite llms surface\n")
    _write(
        root / "docs/_internal/waf_deploy_gate_prepare_2026-05-06.md",
        "Cloudflare WAF deploy gate runbook\n",
    )
    _write(
        root / "scripts/ops/preflight_production_improvement.py",
        "# read-only preflight; no migration apply\n",
    )
    _write(
        root / "tests/test_release_readiness.py",
        "\n".join(
            [
                "def test_build_report_passes_for_release_ready_repo(): pass",
                "def test_build_report_flags_major_failures(): pass",
                "def test_deploy_seed_gate_accepts_jpi_programs_transition(): pass",
                "def test_build_report_flags_missing_deploy_preflight_gate(): pass",
                "def test_build_report_flags_missing_release_ruff_targets(): pass",
                "def test_main_warn_only_exits_zero_on_failure(): pass",
                "def test_build_report_flags_untracked_workflow_targets(): pass",
            ]
        ),
    )
    _track_all(root)


def test_build_report_passes_for_release_ready_repo(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)

    report = module.build_report(tmp_path)

    assert report["ok"] is True
    assert report["summary"] == {"pass": 10, "fail": 0, "total": 10}
    assert report["issues"] == []


def test_build_report_flags_major_failures(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)
    release = tmp_path / ".github/workflows/release.yml"
    release.write_text(
        release.read_text(encoding="utf-8").replace("    tests/test_b.py\n", ""),
        encoding="utf-8",
    )
    deploy = tmp_path / ".github/workflows/deploy.yml"
    deploy.write_text(
        deploy.read_text(encoding="utf-8")
        .replace("catalog_count = max(programs, jpi_programs)\n", "")
        .replace("if catalog_count < 10_000:", "if programs < 10_000:"),
        encoding="utf-8",
    )
    (tmp_path / "tests/test_release_readiness.py").write_text(
        "def test_build_report_passes_for_release_ready_repo(): pass\n",
        encoding="utf-8",
    )

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert "workflow_pytest_targets_synced" in report["issues"]
    assert "deploy_seed_gate_matches_entrypoint" in report["issues"]
    assert "release_readiness_tests_exist" in report["issues"]


def test_deploy_seed_gate_accepts_jpi_programs_transition(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)

    check = module.check_deploy_seed_gate_matches_entrypoint(tmp_path)

    assert check.status == "PASS"
    assert "catalog_count = max(programs, jpi_programs)" in check.evidence


def test_build_report_flags_missing_deploy_preflight_gate(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)

    deploy = tmp_path / ".github/workflows/deploy.yml"
    deploy.write_text(
        deploy.read_text(encoding="utf-8").replace(
            "      - name: Run production deploy readiness gate\n        run: python scripts/ops/production_deploy_readiness_gate.py\n",
            "",
        ),
        encoding="utf-8",
    )

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert "deploy_preflight_gate_present" in report["issues"]


def test_build_report_flags_missing_release_ruff_targets(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)

    release = tmp_path / ".github/workflows/release.yml"
    release.write_text(
        release.read_text(encoding="utf-8").replace(
            "  RUFF_TARGETS: >-\n    scripts/a.py\n    scripts/b.py\n",
            "",
        ),
        encoding="utf-8",
    )

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert "workflow_ruff_targets_synced" in report["issues"]


def test_build_report_flags_untracked_workflow_targets(tmp_path):
    module = _load_module()
    _seed_ready_repo(tmp_path)
    _write(tmp_path / "tests/test_untracked_target.py", "def test_untracked(): pass\n")
    test_workflow = tmp_path / ".github/workflows/test.yml"
    test_workflow.write_text(
        test_workflow.read_text(encoding="utf-8").replace(
            "    tests/test_b.py\n",
            "    tests/test_b.py\n    tests/test_untracked_target.py\n",
        ),
        encoding="utf-8",
    )
    release_workflow = tmp_path / ".github/workflows/release.yml"
    release_workflow.write_text(
        release_workflow.read_text(encoding="utf-8").replace(
            "    tests/test_b.py\n",
            "    tests/test_b.py\n    tests/test_untracked_target.py\n",
        ),
        encoding="utf-8",
    )

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert "workflow_targets_git_tracked" in report["issues"]
    check = next(
        check for check in report["checks"] if check["name"] == "workflow_targets_git_tracked"
    )
    assert check["status"] == "FAIL"
    assert check["evidence"] == [
        "tests/test_untracked_target.py: "
        ".github/workflows/test.yml env.PYTEST_TARGETS, "
        ".github/workflows/release.yml env.PYTEST_TARGETS"
    ]


def test_workflow_targets_full_drift_skips_when_verifier_missing(tmp_path):
    """HARNESS-H4 (Wave 51, 2026-05-17): the new full-drift check must not
    explode when the verify script is absent — that is the synthetic seed
    case. It must degrade to PASS and leave the existing forward-direction
    check (workflow_targets_git_tracked) to catch the inverse drift."""

    module = _load_module()
    _seed_ready_repo(tmp_path)

    check = module.check_workflow_targets_full_drift(tmp_path)

    assert check.status == "PASS"
    assert "sync_workflow_targets_verify.py" in check.evidence[0]


def test_main_warn_only_exits_zero_on_failure(tmp_path, capsys):
    module = _load_module()
    _seed_ready_repo(tmp_path)
    (tmp_path / ".github/workflows/deploy.yml").write_text("name: deploy\n", encoding="utf-8")

    exit_code = module.main(["--repo-root", str(tmp_path), "--warn-only"])
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 0
    assert report["ok"] is False
    assert "deploy_seed_gate_matches_entrypoint" in report["issues"]
