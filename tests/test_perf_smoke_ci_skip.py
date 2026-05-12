"""CI-runner skip behaviour for scripts/ops/perf_smoke.py.

These tests cover the `JPCITE_PREFLIGHT_ALLOW_MISSING_DB` escape hatch added
in Wave 48 so that pre_deploy_verify.py does not fail on a fresh GitHub
Actions runner that does not have autonomath.db checked out. The lever
mirrors scripts/ops/preflight_production_improvement.py.

Production invariant: when the env var is unset, behaviour is identical to
the pre-Wave-48 code path — the TestClient boot still runs and a missing DB
still surfaces real failures. We assert this explicitly to prevent silent
production drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ops import perf_smoke


def test_skip_flag_recognises_truthy_values(monkeypatch) -> None:
    truthy_values = ("1", "true", "yes", "on", "TRUE", "Yes")
    for value in truthy_values:
        monkeypatch.setenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", value)
        assert perf_smoke._skip_missing_db_enabled() is True, value


def test_skip_flag_ignores_falsy_values(monkeypatch) -> None:
    monkeypatch.delenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", raising=False)
    assert perf_smoke._skip_missing_db_enabled() is False

    for value in ("", "0", "false", "no", "off", "FALSE", "anything-else"):
        monkeypatch.setenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", value)
        assert perf_smoke._skip_missing_db_enabled() is False, value


def test_canonical_db_missing_reports_truthfully(tmp_path: Path) -> None:
    missing = tmp_path / "absent.db"
    assert perf_smoke._canonical_db_missing(missing) is True

    present = tmp_path / "present.db"
    present.write_bytes(b"\x00")
    assert perf_smoke._canonical_db_missing(present) is False


def test_skipped_results_are_marked_passing() -> None:
    endpoints = (
        perf_smoke.Endpoint("a", "/a"),
        perf_smoke.Endpoint("b", "/b"),
    )

    results = perf_smoke._skipped_results(endpoints, threshold_ms=1000.0)

    assert [result.name for result in results] == ["a", "b"]
    assert all(result.passed for result in results)
    assert all(result.samples == 0 for result in results)
    assert all(result.ok == 0 for result in results)
    assert perf_smoke.has_failure(results) is False


def test_main_skips_local_client_when_env_set_and_db_missing(monkeypatch, tmp_path, capsys) -> None:
    """Pre-deploy verify hand-shake: --json output is a JSON list, every
    entry has passed=True so _payload_ok returns ok=True, and the local
    TestClient (`_local_client`) is never invoked."""
    monkeypatch.setenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", "1")
    monkeypatch.setattr(perf_smoke, "DEFAULT_DB_PATH", tmp_path / "absent.db")

    invocations: list[str] = []

    def boom_local_client() -> object:
        invocations.append("local_client_called")
        raise AssertionError("local client must not be invoked in skip mode")

    monkeypatch.setattr(perf_smoke, "_local_client", boom_local_client)

    exit_code = perf_smoke.main(
        [
            "--samples",
            "1",
            "--warmups",
            "0",
            "--threshold-ms",
            "10000",
            "--json",
            "--ci",
        ]
    )

    assert exit_code == 0
    assert invocations == []
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert len(payload) == len(perf_smoke.DEFAULT_ENDPOINTS)
    assert all(item["passed"] is True for item in payload)
    assert all(item["samples"] == 0 for item in payload)


def test_main_runs_local_client_when_env_unset(monkeypatch, tmp_path) -> None:
    """Production-invariant guard. With the env-var absent, the local
    client path is taken even if the canonical DB is missing — preserving
    pre-Wave-48 behaviour exactly. This is what protects the live Fly app
    boot from accidentally short-circuiting smoke probes."""
    monkeypatch.delenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", raising=False)
    monkeypatch.setattr(perf_smoke, "DEFAULT_DB_PATH", tmp_path / "absent.db")

    invoked = {"local_client": False}

    class StubClient:
        def __enter__(self) -> StubClient:
            invoked["local_client"] = True
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(perf_smoke, "_local_client", lambda: StubClient())
    monkeypatch.setattr(
        perf_smoke,
        "run_smoke",
        lambda *_a, **_kw: [
            perf_smoke.EndpointResult(
                name="healthz",
                path="/healthz",
                samples=1,
                ok=1,
                status_codes={200: 1},
                p50_ms=1.0,
                p95_ms=1.0,
                max_ms=1.0,
                threshold_ms=10000.0,
                passed=True,
            )
        ],
    )

    exit_code = perf_smoke.main(["--samples", "1", "--warmups", "0", "--ci"])

    assert exit_code == 0
    assert invoked["local_client"] is True


def test_main_skips_only_when_both_conditions_hold(monkeypatch, tmp_path) -> None:
    """Env set but DB present: do not skip (production path with real DB)."""
    db_path = tmp_path / "present.db"
    db_path.write_bytes(b"\x00")
    monkeypatch.setenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", "1")
    monkeypatch.setattr(perf_smoke, "DEFAULT_DB_PATH", db_path)

    invoked = {"local_client": False}

    class StubClient:
        def __enter__(self) -> StubClient:
            invoked["local_client"] = True
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(perf_smoke, "_local_client", lambda: StubClient())
    monkeypatch.setattr(
        perf_smoke,
        "run_smoke",
        lambda *_a, **_kw: [
            perf_smoke.EndpointResult(
                name="healthz",
                path="/healthz",
                samples=1,
                ok=1,
                status_codes={200: 1},
                p50_ms=1.0,
                p95_ms=1.0,
                max_ms=1.0,
                threshold_ms=10000.0,
                passed=True,
            )
        ],
    )

    exit_code = perf_smoke.main(["--samples", "1", "--warmups", "0"])
    assert exit_code == 0
    assert invoked["local_client"] is True


def test_main_base_url_path_ignores_skip_env(monkeypatch) -> None:
    """Explicit --base-url means we are probing a live deployed target, so
    the skip lever must never short-circuit it regardless of env state."""
    import httpx

    monkeypatch.setenv("JPCITE_PREFLIGHT_ALLOW_MISSING_DB", "1")
    monkeypatch.setattr(perf_smoke, "DEFAULT_DB_PATH", Path("/nonexistent/perf_smoke_test.db"))

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"ok": True}, request=request)

    class MockedClient(httpx.Client):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(perf_smoke.httpx, "Client", MockedClient)

    exit_code = perf_smoke.main(
        [
            "--base-url",
            "https://example.invalid",
            "--samples",
            "1",
            "--warmups",
            "0",
            "--ci",
        ]
    )

    assert exit_code == 0
    assert seen_paths == ["/healthz", "/v1/programs/search", "/v1/meta"]
