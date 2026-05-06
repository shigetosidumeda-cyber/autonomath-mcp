"""Integration tests for query telemetry (Task B).

Verifies that the autonomath.query logger emits one valid JSON line per
REST request with the expected fields.

Rules:
- Real app + TestClient (no DB mocking per CLAUDE.md).
- The seeded_db + client fixtures from conftest.py are reused as-is.
"""

from __future__ import annotations

import json
import logging

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "ts",
    "channel",
    "endpoint",
    "params_shape",
    "result_count",
    "latency_ms",
    "status",
    "error_class",
}


class _CapturingHandler(logging.Handler):
    """Collects formatted log records emitted to a given logger."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def last_message(self) -> str:
        return self.records[-1].getMessage() if self.records else ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def telemetry_handler() -> _CapturingHandler:
    """Attach a capturing handler to 'autonomath.query' for the test duration."""
    handler = _CapturingHandler()
    log = logging.getLogger("autonomath.query")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    yield handler
    log.removeHandler(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_telemetry_rest_success(client, telemetry_handler) -> None:
    """Hit /v1/programs/search and verify the telemetry log line is valid JSON
    with all required fields and correct channel/endpoint."""
    r = client.get("/v1/programs/search", params={"limit": 5})
    assert r.status_code == 200

    assert telemetry_handler.records, "Expected at least one telemetry log record"
    # Find the log line for our endpoint (middleware may emit one per request).
    messages = [rec.getMessage() for rec in telemetry_handler.records]
    search_messages = [m for m in messages if "/v1/programs/search" in m]
    assert search_messages, f"No telemetry for /v1/programs/search; got: {messages}"

    raw = search_messages[-1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"telemetry log is not valid JSON: {exc!r}\nraw={raw!r}")

    assert REQUIRED_FIELDS.issubset(data.keys()), f"Missing fields: {REQUIRED_FIELDS - data.keys()}"
    assert data["channel"] == "rest"
    assert data["endpoint"] == "/v1/programs/search"
    assert isinstance(data["latency_ms"], int)
    assert data["latency_ms"] >= 0
    assert data["status"] == 200
    assert data["error_class"] is None


def test_telemetry_rest_404(client, telemetry_handler) -> None:
    """Trigger a 404 and verify status=404 is logged.

    Note: FastAPI/Starlette handles unmatched routes internally and returns a
    404 response without raising an exception through the middleware stack.
    Therefore error_class is null (not 'HTTPException') — the status field
    alone distinguishes error responses.
    """
    r = client.get("/v1/programs/no-such-endpoint-xyzzy-404")
    assert r.status_code == 404

    messages = [rec.getMessage() for rec in telemetry_handler.records]
    target_messages = [m for m in messages if "/v1/programs/no-such-endpoint-xyzzy-404" in m]
    assert target_messages, f"No telemetry for 404 endpoint; got: {messages}"

    raw = target_messages[-1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"telemetry log is not valid JSON: {exc!r}\nraw={raw!r}")

    assert REQUIRED_FIELDS.issubset(data.keys()), f"Missing fields: {REQUIRED_FIELDS - data.keys()}"
    assert data["channel"] == "rest"
    assert data["status"] == 404
    # Starlette returns 404 as a response (not a raised exception) for
    # unmatched routes, so error_class stays null for these cases.
    assert data["error_class"] is None


def test_telemetry_fts_query_shape(client, telemetry_handler) -> None:
    """When q= is present, params_shape must include q_len and q_lang."""
    r = client.get("/v1/programs/search", params={"q": "テスト補助金"})
    assert r.status_code == 200

    messages = [rec.getMessage() for rec in telemetry_handler.records]
    search_messages = [m for m in messages if "/v1/programs/search" in m]
    assert search_messages

    data = json.loads(search_messages[-1])
    shape = data.get("params_shape", {})
    assert "q_len" in shape, f"q_len missing from params_shape: {shape}"
    assert "q_lang" in shape, f"q_lang missing from params_shape: {shape}"
    assert shape["q_len"] == len("テスト補助金")
    assert shape["q_lang"] in ("ja", "en", "mixed")
