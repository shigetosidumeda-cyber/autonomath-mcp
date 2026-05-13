from __future__ import annotations

import httpx

from scripts.ops import perf_smoke


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return FakeResponse(self.status_code)


def test_default_endpoints_are_light_public_surfaces() -> None:
    paths = [endpoint.path for endpoint in perf_smoke.DEFAULT_ENDPOINTS]

    assert paths == ["/healthz", "/v1/programs/search", "/v1/meta"]
    assert perf_smoke.DEFAULT_ENDPOINTS[1].params == {"q": "補助金", "limit": "1"}
    assert perf_smoke.DEFAULT_ENDPOINTS[1].expected_statuses == frozenset({200, 402})


def test_run_smoke_records_p50_p95_and_status_codes_without_network() -> None:
    client = FakeClient()

    results = perf_smoke.run_smoke(
        client,
        endpoints=(perf_smoke.Endpoint("healthz", "/healthz"),),
        samples=3,
        warmups=1,
        timeout_s=1.0,
        threshold_ms=10_000.0,
    )

    assert len(results) == 1
    assert results[0].ok == 3
    assert results[0].status_codes == {200: 3}
    assert results[0].p50_ms >= 0.0
    assert results[0].p95_ms >= 0.0
    assert results[0].passed is True
    assert len(client.calls) == 4


def test_run_smoke_treats_expected_402_as_passing_payment_boundary() -> None:
    client = FakeClient(status_code=402)
    endpoint = perf_smoke.Endpoint(
        "programs_search",
        "/v1/programs/search",
        {"q": "補助金", "limit": "1"},
        frozenset({200, 402}),
    )

    results = perf_smoke.run_smoke(
        client,
        endpoints=(endpoint,),
        samples=1,
        warmups=0,
        timeout_s=1.0,
        threshold_ms=10_000.0,
    )

    assert results[0].ok == 1
    assert results[0].status_codes == {402: 1}
    assert results[0].passed is True


def test_ci_exit_is_nonzero_only_when_ci_flag_is_set(monkeypatch, capsys) -> None:
    failing_result = perf_smoke.EndpointResult(
        name="meta",
        path="/v1/meta",
        samples=1,
        ok=0,
        status_codes={500: 1},
        p50_ms=1.0,
        p95_ms=1.0,
        max_ms=1.0,
        threshold_ms=1000.0,
        passed=False,
    )

    class DummyLocalClient:
        def __enter__(self) -> DummyLocalClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(perf_smoke, "_local_client", lambda: DummyLocalClient())
    monkeypatch.setattr(perf_smoke, "run_smoke", lambda *_args, **_kwargs: [failing_result])

    assert perf_smoke.main(["--samples", "1"]) == 0
    assert "WARN" in capsys.readouterr().out

    assert perf_smoke.main(["--samples", "1", "--ci"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_base_url_uses_httpx_mocktransport_without_external_network(monkeypatch) -> None:
    captured_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_paths.append(request.url.path)
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
    assert captured_paths == ["/healthz", "/v1/programs/search", "/v1/meta"]


def test_local_client_uses_trusted_fly_client_ip_header(monkeypatch) -> None:
    captured_headers: dict[str, str] = {}

    class DummyTestClient:
        def __init__(self, _app: object, **kwargs: object) -> None:
            headers = kwargs.get("headers", {})
            assert isinstance(headers, dict)
            captured_headers.update(headers)

    # Import path inside _local_client binds TestClient dynamically, so patch the
    # fastapi module object directly.
    import fastapi.testclient

    monkeypatch.setattr(fastapi.testclient, "TestClient", DummyTestClient)

    perf_smoke._local_client()

    assert "Fly-Client-IP" in captured_headers
    assert "X-Forwarded-For" not in captured_headers
