from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLY_TOML = REPO_ROOT / "fly.toml"


def test_fly_liveness_check_does_not_depend_on_autonomath_deep_health() -> None:
    config = tomllib.loads(FLY_TOML.read_text(encoding="utf-8"))
    checks = config["http_service"]["checks"]
    assert checks

    paths = [check.get("path", "") for check in checks]
    assert "/healthz" in paths
    assert all("/v1/am/health/deep" not in path for path in paths)
    assert all("fail_on_degraded" not in path for path in paths)
