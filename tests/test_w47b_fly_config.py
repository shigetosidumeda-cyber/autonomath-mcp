"""Structural parity tests for Wave 46.B Fly namespace overlay (2026-05-12).

Memory anchors:
    * ``project_jpcite_internal_autonomath_rename`` — jpcite-api is a NEW
      Fly app added alongside autonomath-api; no destructive op.
    * ``feedback_destruction_free_organization`` — legacy ``fly.toml`` MUST
      remain authoritative for the autonomath-api app. ``fly.jpcite.toml``
      is an additive overlay only.
    * ``feedback_no_quick_check_on_huge_sqlite`` — boot-time grace_period
      stays at 60s on both apps; the size-based gate in entrypoint.sh §2
      handles the 9 GB autonomath.db without a quick_check probe.

Scope:
    Verify that ``fly.jpcite.toml`` and ``fly.toml`` describe structurally
    equivalent apps (same image build, same env-var matrix, same VM size,
    same /healthz check, same mount layout), while differing on exactly
    the three fields the rename plan requires:

      * ``app`` (autonomath-api vs jpcite-api)
      * ``kill_signal`` (default-implicit SIGTERM vs explicit SIGINT)
      * ``kill_timeout`` (default-implicit vs explicit 30s)

    Also verifies the Dockerfile carries both the legacy OCI title and
    the new jpcite-mcp alt-title (additive label rename), and that the
    new dispatch workflow refuses to deploy to the legacy app name.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FLY_TOML = REPO_ROOT / "fly.toml"
FLY_JPCITE_TOML = REPO_ROOT / "fly.jpcite.toml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
JPCITE_DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-jpcite-api.yml"


@pytest.fixture(scope="module")
def fly_legacy() -> dict:
    return tomllib.loads(FLY_TOML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fly_jpcite() -> dict:
    return tomllib.loads(FLY_JPCITE_TOML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Structural parity
# ---------------------------------------------------------------------------


def test_fly_jpcite_toml_exists_and_parses() -> None:
    """The new overlay must exist as valid TOML — Fly refuses malformed config."""
    assert FLY_JPCITE_TOML.is_file(), f"missing {FLY_JPCITE_TOML}"
    parsed = tomllib.loads(FLY_JPCITE_TOML.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    assert parsed, "fly.jpcite.toml parsed to an empty document"


def test_app_names_differ_legacy_stays_autonomath(fly_legacy: dict, fly_jpcite: dict) -> None:
    """Legacy stays autonomath-api (SOT); new file targets jpcite-api only."""
    assert fly_legacy["app"] == "autonomath-api"
    assert fly_jpcite["app"] == "jpcite-api"
    assert fly_legacy["app"] != fly_jpcite["app"]


def test_primary_region_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    assert fly_jpcite["primary_region"] == fly_legacy["primary_region"] == "nrt"


def test_build_section_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    """Same Dockerfile drives both apps (single image, dual app targets)."""
    assert fly_jpcite["build"] == fly_legacy["build"]
    assert fly_jpcite["build"]["dockerfile"] == "Dockerfile"


def test_env_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    """Env-var matrix must match exactly — drift here means feature-flag skew."""
    assert fly_jpcite["env"] == fly_legacy["env"], (
        "env drift: jpcite-api would run with different feature flags than autonomath-api"
    )


def test_deploy_strategy_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    assert fly_jpcite["deploy"]["strategy"] == fly_legacy["deploy"]["strategy"] == "immediate"


def test_mount_layout_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    """Same volume name + same destination + same initial_size."""
    legacy_mount = fly_legacy["mounts"][0]
    jpcite_mount = fly_jpcite["mounts"][0]
    assert jpcite_mount == legacy_mount, (
        "mount drift between fly.toml and fly.jpcite.toml — destination or size mismatch"
    )


def test_http_service_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    legacy_http = fly_legacy["http_service"]
    jpcite_http = fly_jpcite["http_service"]
    for key in (
        "internal_port",
        "force_https",
        "auto_stop_machines",
        "auto_start_machines",
        "min_machines_running",
        "processes",
    ):
        assert jpcite_http[key] == legacy_http[key], f"http_service.{key} drift"
    assert jpcite_http["concurrency"] == legacy_http["concurrency"]


def test_healthz_check_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    legacy_checks = fly_legacy["http_service"]["checks"]
    jpcite_checks = fly_jpcite["http_service"]["checks"]
    assert len(legacy_checks) == len(jpcite_checks) == 1
    legacy_check = legacy_checks[0]
    jpcite_check = jpcite_checks[0]
    for key in ("interval", "timeout", "grace_period", "method", "path"):
        assert jpcite_check[key] == legacy_check[key], f"http_service.checks[0].{key} drift"
    assert jpcite_check["path"] == "/healthz"
    # Per `feedback_no_quick_check_on_huge_sqlite`: liveness MUST NOT depend on
    # the optional 9 GB autonomath.db deep-health path.
    assert "/v1/am/health/deep" not in jpcite_check["path"]


def test_metrics_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    assert fly_jpcite["metrics"] == fly_legacy["metrics"]
    assert fly_jpcite["metrics"]["path"] == "/metrics"
    assert fly_jpcite["metrics"]["port"] == 9091


def test_vm_parity(fly_legacy: dict, fly_jpcite: dict) -> None:
    legacy_vm = fly_legacy["vm"][0]
    jpcite_vm = fly_jpcite["vm"][0]
    assert jpcite_vm == legacy_vm, (
        f"VM size drift: legacy={legacy_vm} jpcite={jpcite_vm}; "
        "would create unexpected memory headroom delta on cutover"
    )


# ---------------------------------------------------------------------------
# Intentional drift (the three fields the rename plan demands)
# ---------------------------------------------------------------------------


def test_kill_signal_explicit_sigint_on_jpcite_only(fly_legacy: dict, fly_jpcite: dict) -> None:
    """jpcite-api documents drain semantics explicitly; legacy stays implicit."""
    assert fly_jpcite.get("kill_signal") == "SIGINT"
    assert "kill_signal" not in fly_legacy, (
        "legacy fly.toml MUST NOT be edited under feedback_destruction_free_organization"
    )


def test_kill_timeout_explicit_on_jpcite_only(fly_legacy: dict, fly_jpcite: dict) -> None:
    assert fly_jpcite.get("kill_timeout") == "30s"
    assert "kill_timeout" not in fly_legacy


# ---------------------------------------------------------------------------
# Dockerfile additive labels (Wave 46.B)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_dockerfile_keeps_legacy_oci_labels(dockerfile_text: str) -> None:
    """OCI title + vendor + licenses must stay intact — registries match on these."""
    assert 'LABEL org.opencontainers.image.title="AutonoMath API"' in dockerfile_text
    assert 'LABEL org.opencontainers.image.vendor="Bookyou株式会社"' in dockerfile_text
    assert 'LABEL org.opencontainers.image.licenses="MIT"' in dockerfile_text


def test_dockerfile_adds_jpcite_alt_labels(dockerfile_text: str) -> None:
    """New labels expose the jpcite brand without overwriting OCI standard ones."""
    assert 'LABEL org.opencontainers.image.alt-title="jpcite-mcp"' in dockerfile_text
    assert 'LABEL com.bookyou.jpcite.brand="jpcite"' in dockerfile_text
    assert 'LABEL com.bookyou.jpcite.app="jpcite-api"' in dockerfile_text
    assert 'LABEL com.bookyou.jpcite.rename-wave="46.B"' in dockerfile_text


def test_dockerfile_alt_labels_come_after_legacy(dockerfile_text: str) -> None:
    """Layer ordering: legacy OCI labels must appear before jpcite alt-labels so
    OCI-spec-compliant scanners that stop at the first title still see the
    historically-stable AutonoMath title."""
    legacy_idx = dockerfile_text.find('LABEL org.opencontainers.image.title="AutonoMath API"')
    alt_idx = dockerfile_text.find('LABEL org.opencontainers.image.alt-title="jpcite-mcp"')
    assert 0 <= legacy_idx < alt_idx


# ---------------------------------------------------------------------------
# Dispatch workflow safety
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jpcite_workflow_text() -> str:
    return JPCITE_DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_jpcite_workflow_exists(jpcite_workflow_text: str) -> None:
    assert jpcite_workflow_text, "deploy-jpcite-api.yml missing"


def test_jpcite_workflow_is_dispatch_only(jpcite_workflow_text: str) -> None:
    """Per task: deploy-jpcite-api.yml MUST NOT have cron or workflow_run trigger.
    Actual deploy is user-judgment-gated (separate wave)."""
    assert "workflow_dispatch:" in jpcite_workflow_text
    # No automated triggers
    assert "\n  schedule:" not in jpcite_workflow_text
    assert "\n  workflow_run:" not in jpcite_workflow_text
    assert "\n  push:" not in jpcite_workflow_text


def test_jpcite_workflow_targets_jpcite_api_not_autonomath(jpcite_workflow_text: str) -> None:
    """Hard guard: the dispatch must never accidentally deploy to autonomath-api."""
    assert "-c fly.jpcite.toml" in jpcite_workflow_text
    assert "-a jpcite-api" in jpcite_workflow_text
    # The workflow MUST NOT flyctl-deploy against the legacy app name.
    flyctl_lines = [line for line in jpcite_workflow_text.splitlines() if "flyctl deploy" in line]
    assert flyctl_lines, "no flyctl deploy invocation found"
    for line in flyctl_lines:
        assert "autonomath-api" not in line, (
            f"jpcite workflow MUST NOT deploy to autonomath-api; offending line: {line!r}"
        )


def test_jpcite_workflow_keeps_operator_ack_gate(jpcite_workflow_text: str) -> None:
    """Production safety: same operator-ack gate as deploy.yml."""
    assert "PRODUCTION_DEPLOY_OPERATOR_ACK_YAML" in jpcite_workflow_text
    assert "production_deploy_go_gate.py" in jpcite_workflow_text


def test_jpcite_workflow_smoke_default_targets_fly_dev_not_prod(jpcite_workflow_text: str) -> None:
    """Default smoke target is jpcite-api.fly.dev — api.jpcite.com cutover is its own wave."""
    assert 'default: "https://jpcite-api.fly.dev"' in jpcite_workflow_text


# ---------------------------------------------------------------------------
# Non-destructiveness invariants
# ---------------------------------------------------------------------------


def test_legacy_fly_toml_untouched_signature(fly_legacy: dict) -> None:
    """Pin specific values that must remain on legacy fly.toml so a future
    careless edit lights up here."""
    assert fly_legacy["app"] == "autonomath-api"
    assert fly_legacy["env"]["AUTONOMATH_ENABLED"] == "true"
    assert fly_legacy["http_service"]["internal_port"] == 8080
    assert fly_legacy["mounts"][0]["source"] == "jpintel_data"
