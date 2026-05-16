"""Stream W (2026-05-16): scorecard promote vs operator live-AWS unlock.

The ``--promote-scorecard`` flag (Stream Q authority) MUST only flip
``preflight_scorecard.state`` from AWS_BLOCKED_PRE_FLIGHT to AWS_CANARY_READY.
It MUST NOT set ``live_aws_commands_allowed`` to True under any condition.

The new ``--unlock-live-aws-commands`` flag (Stream I operator authority) is
the ONLY code path that may flip ``live_aws_commands_allowed`` to True. It
requires the operator-signed environment variable
``JPCITE_LIVE_AWS_UNLOCK_TOKEN`` to be non-empty (exit 64 otherwise) and the
scorecard state to already be AWS_CANARY_READY (or the same invocation must
combine ``--promote-scorecard`` and ``--unlock-live-aws-commands``).

These tests pin the concern separation so that future refactors cannot
accidentally re-couple the two flips.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "ops" / "run_preflight_simulations.py"
PYTHON = sys.executable


def _load_runner():
    name = "run_preflight_simulations"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses needs cls.__module__ resolvable
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _seed_capsule(tmp_path: Path) -> Path:
    """Copy the live rc1-p0-bootstrap capsule into a temp dir for mutation.

    The live scorecard / sim / state JSON files may be in any state
    (pre-promote or post-promote) at the time the tests run. To make the
    assertions deterministic, we reset the scorecard back to the canonical
    pre-promote shape (state=AWS_BLOCKED_PRE_FLIGHT, live_aws=false, with
    any promote/unlock authority + timestamps stripped) and reset the two
    simulation artifacts back to pass_state=false. This mirrors a fresh
    capsule snapshot."""

    src = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
    dst = tmp_path / "rc1-p0-bootstrap"
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file() and p.suffix == ".json":
            (dst / p.name).write_bytes(p.read_bytes())
    sub = src / "agent_surface"
    if sub.exists():
        sub_dst = dst / "agent_surface"
        sub_dst.mkdir(exist_ok=True)
        for p in sub.iterdir():
            if p.is_file():
                (sub_dst / p.name).write_bytes(p.read_bytes())

    # Force scorecard back to pre-promote shape so test assertions are stable
    # whether the live capsule has been promoted by an earlier --apply run.
    scorecard_path = dst / "preflight_scorecard.json"
    if scorecard_path.exists():
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        scorecard["state"] = "AWS_BLOCKED_PRE_FLIGHT"
        scorecard["live_aws_commands_allowed"] = False
        for transient_key in (
            "scorecard_promote_authority",
            "unlock_authority",
            "unlocked_at",
        ):
            scorecard.pop(transient_key, None)
        scorecard_path.write_text(
            json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    # Reset pass_state on both simulation artifacts.
    for sim_name in ("spend_simulation.json", "teardown_simulation.json"):
        sim_path = dst / sim_name
        if sim_path.exists():
            sim = json.loads(sim_path.read_text(encoding="utf-8"))
            sim["pass_state"] = False
            sim_path.write_text(
                json.dumps(sim, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return dst


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _force_all_pass(runner_mod, monkeypatch) -> None:
    """Stub the assertion registries so every check PASSES."""

    pass_a = runner_mod.Assertion(
        assertion_id="forced_pass",
        description="forced pass for test",
        check=lambda c: (True, "forced"),
    )
    monkeypatch.setattr(runner_mod, "_spend_assertions", lambda: [pass_a] * 22)
    monkeypatch.setattr(runner_mod, "_teardown_assertions", lambda: [pass_a] * 18)


# ---------------------------------------------------------------------------
# 1. --promote-scorecard alone: state flip + live_aws=False maintained
# ---------------------------------------------------------------------------


def test_promote_scorecard_flips_state_but_keeps_live_aws_false(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)

    result = runner.run(
        apply=True,
        capsule_dir=capsule,
        promote_scorecard=True,
    )
    scorecard = _load(capsule / "preflight_scorecard.json")

    # State flips to AWS_CANARY_READY ...
    assert scorecard["state"] == "AWS_CANARY_READY"
    # ... but live_aws_commands_allowed MUST stay False (concern separation).
    assert scorecard["live_aws_commands_allowed"] is False
    # The runner records who authored the promote (not the unlock).
    assert scorecard.get("scorecard_promote_authority") == "preflight_runner"
    # No unlock authority appears yet — that's Stream I's job.
    assert scorecard.get("unlock_authority") is None
    assert scorecard.get("unlocked_at") is None
    # The result object surfaces both axes for downstream introspection.
    assert result["preflight_scorecard_current_state"] == "AWS_CANARY_READY"
    assert result["preflight_scorecard_live_aws_commands_allowed"] is False


def test_promote_scorecard_force_resets_tampered_live_aws_true(tmp_path, runner, monkeypatch):
    """Defense-in-depth: if upstream tampering set live_aws=True, the promote
    path must force-reset it to False (the unlock path is the only authority)."""

    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)
    scorecard_path = capsule / "preflight_scorecard.json"
    tampered = _load(scorecard_path)
    tampered["live_aws_commands_allowed"] = True  # simulate tampering
    scorecard_path.write_text(json.dumps(tampered), encoding="utf-8")

    result = runner.run(
        apply=True,
        capsule_dir=capsule,
        promote_scorecard=True,
    )
    scorecard = _load(scorecard_path)
    assert scorecard["state"] == "AWS_CANARY_READY"
    assert scorecard["live_aws_commands_allowed"] is False  # force-reset
    assert any("force-reset" in a for a in result["actions"])


# ---------------------------------------------------------------------------
# 2. --unlock-live-aws-commands without token: exit 64, no mutation
# ---------------------------------------------------------------------------


def test_unlock_without_token_raises(tmp_path, runner, monkeypatch):
    """The python API surfaces UnlockTokenMissingError when token is missing."""

    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)
    # Pre-promote so scorecard is AWS_CANARY_READY (isolates the token check).
    runner.run(apply=True, capsule_dir=capsule, promote_scorecard=True)
    before = _load(capsule / "preflight_scorecard.json")

    with pytest.raises(runner.UnlockTokenMissingError):
        runner.run(
            apply=True,
            capsule_dir=capsule,
            unlock_live_aws_commands=True,
            unlock_token=None,
        )
    # Empty string also raises (whitespace-only is rejected too).
    with pytest.raises(runner.UnlockTokenMissingError):
        runner.run(
            apply=True,
            capsule_dir=capsule,
            unlock_live_aws_commands=True,
            unlock_token="",
        )
    with pytest.raises(runner.UnlockTokenMissingError):
        runner.run(
            apply=True,
            capsule_dir=capsule,
            unlock_live_aws_commands=True,
            unlock_token="   ",
        )
    # Scorecard MUST be unchanged after the failed attempts.
    after = _load(capsule / "preflight_scorecard.json")
    assert before == after
    assert after["live_aws_commands_allowed"] is False


def test_unlock_without_token_cli_exits_64(tmp_path, monkeypatch):
    """End-to-end: the CLI emits exit code 64 (EX_USAGE) on missing token."""

    capsule = _seed_capsule(tmp_path)
    # Need both flags so the runner attempts the unlock path.
    monkeypatch.delenv("JPCITE_LIVE_AWS_UNLOCK_TOKEN", raising=False)
    result = subprocess.run(
        [
            PYTHON,
            str(RUNNER_PATH),
            "--apply",
            "--promote-scorecard",
            "--unlock-live-aws-commands",
            "--capsule-dir",
            str(capsule),
        ],
        env={**__import__("os").environ},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 64, (
        f"expected exit 64, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "JPCITE_LIVE_AWS_UNLOCK_TOKEN" in result.stderr


# ---------------------------------------------------------------------------
# 3. --unlock-live-aws-commands with token: live_aws=True + operator authority
# ---------------------------------------------------------------------------


def test_unlock_with_token_sets_live_aws_true(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)

    # Run promote + unlock in one apply, with a valid token.
    result = runner.run(
        apply=True,
        capsule_dir=capsule,
        promote_scorecard=True,
        unlock_live_aws_commands=True,
        unlock_token="sig:v1:operator-signed-stub",
    )
    scorecard = _load(capsule / "preflight_scorecard.json")
    assert scorecard["state"] == "AWS_CANARY_READY"
    assert scorecard["live_aws_commands_allowed"] is True
    assert scorecard["unlock_authority"] == "operator"
    # Timestamp present and parseable as ISO 8601 UTC.
    unlocked_at = scorecard["unlocked_at"]
    assert isinstance(unlocked_at, str) and unlocked_at.endswith("Z")
    # The result also reflects the flipped value.
    assert result["preflight_scorecard_live_aws_commands_allowed"] is True


def test_unlock_requires_canary_ready_state(tmp_path, runner, monkeypatch):
    """If scorecard is still AWS_BLOCKED_PRE_FLIGHT (no promote), the unlock
    path must NOT flip live_aws=True even with a valid token."""

    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)
    # Skip --promote-scorecard so state stays AWS_BLOCKED_PRE_FLIGHT.
    result = runner.run(
        apply=True,
        capsule_dir=capsule,
        promote_scorecard=False,
        unlock_live_aws_commands=True,
        unlock_token="sig:v1:operator-signed-stub",
    )
    scorecard = _load(capsule / "preflight_scorecard.json")
    assert scorecard["state"] == "AWS_BLOCKED_PRE_FLIGHT"
    assert scorecard["live_aws_commands_allowed"] is False
    assert "requires AWS_CANARY_READY" in " ".join(result["actions"])


# ---------------------------------------------------------------------------
# 4. Plain --apply (no flags): pass_state flip only, scorecard unchanged
# ---------------------------------------------------------------------------


def test_plain_apply_does_not_touch_scorecard(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)
    scorecard_path = capsule / "preflight_scorecard.json"
    before = _load(scorecard_path)

    runner.run(
        apply=True,
        capsule_dir=capsule,
        promote_scorecard=False,
        unlock_live_aws_commands=False,
    )

    after = _load(scorecard_path)
    assert before == after
    # Both flags off => scorecard MUST be byte-for-byte identical.
    assert after["state"] == "AWS_BLOCKED_PRE_FLIGHT"
    assert after["live_aws_commands_allowed"] is False
    assert "unlock_authority" not in after
    assert "unlocked_at" not in after
    assert "scorecard_promote_authority" not in after


# ---------------------------------------------------------------------------
# 5. Dry-run does not mutate anything (covers both flags)
# ---------------------------------------------------------------------------


def test_dry_run_with_all_flags_does_not_mutate(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    _force_all_pass(runner, monkeypatch)
    scorecard_path = capsule / "preflight_scorecard.json"
    before = _load(scorecard_path)

    result = runner.run(
        apply=False,
        capsule_dir=capsule,
        promote_scorecard=True,
        unlock_live_aws_commands=True,
        unlock_token="sig:v1:operator-signed-stub",
    )

    after = _load(scorecard_path)
    assert before == after
    assert result["mode"] == "dry-run"
