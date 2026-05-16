from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "production_deploy_readiness_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("production_deploy_readiness_gate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _seed_release_route(root: Path) -> None:
    _write(
        root / "functions/release/[[path]].ts",
        """
const ACTIVE_POINTER_PATH = "/releases/current/runtime_pointer.json";
const ACTIVE_CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15";
const ACTIVE_CAPSULE_DIR = "rc1-p0-bootstrap";
const CURRENT_ALIAS_TARGETS = {
  "/release/current/capsule_manifest.json": "release_capsule_manifest.json",
  "/release/current/agent_surface/p0_facade.json": "agent_surface/p0_facade.json",
  "/release/current/preflight_scorecard.json": "preflight_scorecard.json",
  "/release/current/zero_aws_posture_manifest.json": "preflight_scorecard.json",
};
function activeCapsuleDir(pointer) {
  if (pointer.live_aws_commands_allowed !== false) return null;
  if (pointer.aws_runtime_dependency_allowed !== false) return null;
  if (`/releases/${ACTIVE_CAPSULE_DIR}/release_capsule_manifest.json`) return ACTIVE_CAPSULE_DIR;
  return null;
}
export const onRequest = async ({ request }) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("release aliases are read-only", { status: 405 });
  }
  return new Response("capsule_pointer_invalid", { status: 503 });
};
""",
    )
    _write_json(root / "site/_routes.json", {"include": ["/release/*"]})
    _write(
        root / "site/_headers",
        """
/release/current/*
/release/rc1-p0-bootstrap/*
/releases/current/*
/releases/rc1-p0-bootstrap/*
""",
    )


def test_release_capsule_route_passes_for_checked_in_repo() -> None:
    module = _load_module()

    check = module.check_release_capsule_route(REPO_ROOT)

    assert check.ok is True
    assert check.issues == []


def test_release_capsule_route_fails_closed_when_route_unregistered(tmp_path: Path) -> None:
    module = _load_module()
    _seed_release_route(tmp_path)
    _write_json(tmp_path / "site/_routes.json", {"include": []})

    check = module.check_release_capsule_route(tmp_path)

    assert check.ok is False
    assert "routes_missing:/release/*" in check.issues


def test_aws_blocked_preflight_state_passes_for_checked_in_repo() -> None:
    module = _load_module()

    check = module.check_aws_blocked_preflight_state(REPO_ROOT)

    assert check.ok is True
    assert check.issues == []
    assert check.evidence["expected_state"] == "AWS_BLOCKED_PRE_FLIGHT"


def test_build_report_composes_required_checks(monkeypatch) -> None:
    module = _load_module()
    seen_commands: list[str] = []

    def fake_run(repo_root, command):
        seen_commands.append(command.name)
        return module.GateCheck(command.name, True, [], {"command": command.argv})

    monkeypatch.setattr(module, "_run_command", fake_run)
    monkeypatch.setattr(
        module,
        "check_release_capsule_route",
        lambda repo_root: module.GateCheck("release_capsule_route", True, [], {}),
    )
    monkeypatch.setattr(
        module,
        "check_aws_blocked_preflight_state",
        lambda repo_root: module.GateCheck("aws_blocked_preflight_state", True, [], {}),
    )

    report = module.build_report(REPO_ROOT)

    assert report["ok"] is True
    assert seen_commands == [
        "functions_typecheck",
        "release_capsule_validator",
        "agent_runtime_contracts",
        "openapi_drift",
        "mcp_drift",
    ]
    assert report["summary"] == {"pass": 7, "fail": 0, "total": 7}


def test_main_warn_only_exits_zero_on_failure(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "build_report",
        lambda repo_root: {
            "ok": False,
            "summary": {"pass": 0, "fail": 1, "total": 1},
            "checks": [],
            "issues": [{"name": "x", "issues": ["failed"]}],
        },
    )

    assert module.main(["--repo-root", str(REPO_ROOT), "--warn-only"]) == 0
    assert module.main(["--repo-root", str(REPO_ROOT)]) == 1
