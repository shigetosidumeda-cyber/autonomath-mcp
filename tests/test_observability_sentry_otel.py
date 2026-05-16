"""Stream T coverage gap: observability/ — cron_heartbeat / sentry / otel.

Targets ``src/jpintel_mcp/observability/`` — 3 modules. Existing
``tests/test_sentry_init.py`` / ``test_sentry_filters.py`` already
cover the API-side init pipeline; this file fills the cron-heartbeat
and OTel surface plus the cron-script sentry helper. All tests are
self-contained with an isolated tempdir + env vars.

No source mutation. Fixtures inline.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterator

import pytest

from jpintel_mcp.observability import cron_heartbeat as ch
from jpintel_mcp.observability import otel as otm
from jpintel_mcp.observability import sentry as sm

# ---------------------------------------------------------------------------
# cron_heartbeat — happy path, error path, table self-heal
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_db_path() -> Iterator[str]:
    """Return a path to a brand-new empty SQLite DB and clean up."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Remove the empty file so heartbeat's _ensure_table actually creates
    # cron_runs from scratch.
    os.unlink(path)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _read_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                "SELECT cron_name, status, rows_processed, rows_skipped, "
                "error_message, metadata_json FROM cron_runs"
            )
        )
    finally:
        conn.close()


def test_heartbeat_writes_success_row(fresh_db_path: str) -> None:
    with ch.heartbeat("unit_test_success", db_path=fresh_db_path) as state:
        state["rows_processed"] = 7
        state["rows_skipped"] = 2
        state["metadata"] = {"key": "value", "n": 1}

    rows = _read_rows(fresh_db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["cron_name"] == "unit_test_success"
    assert row["status"] == "ok"
    assert row["rows_processed"] == 7
    assert row["rows_skipped"] == 2
    assert row["error_message"] is None
    assert "key" in (row["metadata_json"] or "")


def test_heartbeat_writes_error_row_and_reraises(fresh_db_path: str) -> None:
    with pytest.raises(ValueError, match="boom"):  # noqa: SIM117 — context inside raises
        with ch.heartbeat("unit_test_error", db_path=fresh_db_path) as state:
            state["rows_processed"] = 3
            raise ValueError("boom")

    rows = _read_rows(fresh_db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "error"
    assert row["rows_processed"] == 3
    assert row["error_message"] is not None
    assert "ValueError" in row["error_message"]
    assert "boom" in row["error_message"]


def test_heartbeat_ensures_table_on_fresh_db(fresh_db_path: str) -> None:
    """The first heartbeat must create cron_runs idempotently."""
    with ch.heartbeat("ensure_table_test", db_path=fresh_db_path) as _state:
        pass
    # If _ensure_table did not run, the SELECT above would have raised.
    rows = _read_rows(fresh_db_path)
    assert rows


def test_heartbeat_truncates_long_error(fresh_db_path: str) -> None:
    long_msg = "x" * 1000
    with pytest.raises(RuntimeError):  # noqa: SIM117 — context inside raises
        with ch.heartbeat("trunc_test", db_path=fresh_db_path):
            raise RuntimeError(long_msg)
    rows = _read_rows(fresh_db_path)
    err = rows[0]["error_message"]
    assert err is not None
    assert len(err) <= 500


def test_heartbeat_default_db_path_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPINTEL_DB_PATH", "/tmp/probe_jpcite_unit.db")
    assert ch._default_db_path() == "/tmp/probe_jpcite_unit.db"


def test_heartbeat_default_db_path_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPINTEL_DB_PATH", raising=False)
    path = ch._default_db_path()
    assert path.endswith("jpintel.db")


def test_truncate_helper_passthrough_under_limit() -> None:
    assert ch._truncate("hello", 100) == "hello"


def test_truncate_helper_caps_at_limit() -> None:
    out = ch._truncate("a" * 200, 50)
    assert out is not None
    assert len(out) == 50
    assert out.endswith("...")


def test_truncate_helper_none_passthrough() -> None:
    assert ch._truncate(None) is None


def test_now_iso_returns_z_suffix() -> None:
    out = ch._now_iso()
    assert out.endswith("Z")
    # YYYY-MM-DDTHH:MM:SSZ
    assert len(out) == 20


# ---------------------------------------------------------------------------
# OTel — short-circuit + sample-rate + header parser + trace_id
# ---------------------------------------------------------------------------


def test_otel_init_no_endpoint_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    otm._reset_for_test()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otm.init_otel() is False


def test_otel_init_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    otm._reset_for_test()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otm.init_otel() is False
    # Second call should also be False, taking the short-circuit branch.
    assert otm.init_otel() is False


def test_otel_instrument_fastapi_noop_when_not_inited() -> None:
    otm._reset_for_test()
    # No init, no endpoint — instrument_fastapi must be a no-op returning False.
    # Pass any object; the function will short-circuit on _INIT_OK before
    # touching it.
    out = otm.instrument_fastapi(None)  # type: ignore[arg-type]
    assert out is False


def test_otel_current_trace_id_returns_none_when_not_inited() -> None:
    otm._reset_for_test()
    assert otm.current_trace_id() is None


def test_otel_resolve_sample_rate_prod_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_SAMPLE_RATE", raising=False)
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    assert otm._resolve_sample_rate() == 0.01


def test_otel_resolve_sample_rate_dev_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_SAMPLE_RATE", raising=False)
    monkeypatch.setenv("JPINTEL_ENV", "dev")
    assert otm._resolve_sample_rate() == 1.0


def test_otel_resolve_sample_rate_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SAMPLE_RATE", "0.5")
    assert otm._resolve_sample_rate() == 0.5


def test_otel_resolve_sample_rate_out_of_range_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SAMPLE_RATE", "9.0")
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    # 9.0 is out of range; falls through to prod default
    assert otm._resolve_sample_rate() == 0.01


def test_otel_resolve_sample_rate_garbage_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SAMPLE_RATE", "not-a-float")
    monkeypatch.setenv("JPINTEL_ENV", "dev")
    assert otm._resolve_sample_rate() == 1.0


def test_otel_resolve_headers_parses_comma_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "api-key=secret, x-source = pytest")
    out = otm._resolve_headers()
    assert out["api-key"] == "secret"
    assert out["x-source"] == "pytest"


def test_otel_resolve_headers_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    assert otm._resolve_headers() == {}


def test_otel_resolve_headers_ignores_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "no-equals,=empty-key,k=v")
    out = otm._resolve_headers()
    # The "no-equals" entry has no '=' → dropped.
    # The "=empty-key" entry has empty key → dropped.
    assert "k" in out
    assert out["k"] == "v"


def test_otel_init_returns_false_when_packages_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint is set but opentelemetry imports fail — graceful False."""
    otm._reset_for_test()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://example/otlp")
    # Inject a broken opentelemetry import path
    original = sys.modules.get("opentelemetry")
    sys.modules["opentelemetry"] = None  # type: ignore[assignment]
    try:
        assert otm.init_otel() is False
    finally:
        if original is None:
            sys.modules.pop("opentelemetry", None)
        else:
            sys.modules["opentelemetry"] = original


# ---------------------------------------------------------------------------
# Sentry helper (cron-side)
# ---------------------------------------------------------------------------


def _reset_sentry_state() -> None:
    sm._INIT_ATTEMPTED = False
    sm._INIT_OK = False


def test_sentry_is_inactive_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_sentry_state()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    assert sm.is_sentry_active() is False


def test_sentry_is_inactive_without_prod_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_sentry_state()
    monkeypatch.setenv("SENTRY_DSN", "https://x@example/1")
    monkeypatch.setenv("JPINTEL_ENV", "dev")
    assert sm.is_sentry_active() is False


def test_sentry_safe_capture_exception_swallows_when_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_sentry_state()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # Must NEVER raise — even when given a real exception.
    sm.safe_capture_exception(ValueError("ignored"), where="unit")


def test_sentry_safe_capture_message_swallows_when_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_sentry_state()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sm.safe_capture_message("test message", level="info", source="unit")


def test_sentry_ensure_init_caches_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_sentry_state()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # First call returns False, then idempotent — _INIT_ATTEMPTED must stick.
    assert sm._ensure_init() is False
    assert sm._INIT_ATTEMPTED is True
    assert sm._ensure_init() is False
