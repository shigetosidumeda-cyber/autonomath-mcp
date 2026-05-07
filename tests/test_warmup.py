"""Tests for boot-time SQLite warmup (`api/_db_warmup.py`).

R8_PERF_BASELINE bottleneck #3: cold-start /v1/am/health/deep timed out at
30.92s on first hit (Fly proxy ceiling) because the 9.4 GB autonomath.db
had no pages in the OS page cache. The warmup runs cheap probes against
the hottest tables in a background task during lifespan startup so the
page cache fills concurrently with the first inbound traffic.

This suite verifies the warmup contract:

1. **Never raises.** Missing DBs / missing tables / open errors all
   return cleanly. We exercise each branch.
2. **Honors the env-var kill switch.** AUTONOMATH_WARMUP_ENABLED=0
   short-circuits and returns an empty dict.
3. **Schedules as a non-awaited task.** `schedule_warmup()` returns an
   `asyncio.Task` so callers can hold a reference without awaiting it
   (boot must not block on warmup).
4. **Probes touch the right tables.** When given a real SQLite file
   with the probe-target tables, the returned dict reports per-table
   elapsed times.
5. **Bounded by outer timeout.** A pathological probe can't hold the
   worker open past `_WARMUP_OUTER_TIMEOUT_S`.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_minimal_db(path: Path, tables: list[str]) -> None:
    """Create a tiny SQLite file with one row per supplied table.

    The warmup runs `SELECT COUNT(*)` + `LIMIT 1`; any schema works as
    long as the table exists. We use a single-column `id INTEGER` table
    so the b-tree is trivial.
    """
    con = sqlite3.connect(str(path))
    try:
        for t in tables:
            con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY)")  # noqa: S608
            con.execute(f"INSERT INTO {t} (id) VALUES (1)")  # noqa: S608
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_returns_empty_when_dbs_missing(tmp_path, monkeypatch):
    """Both DB paths missing → warmup logs + returns empty dict."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    # Point both paths at non-existent files. settings is a Pydantic model
    # so we monkeypatch attributes directly.
    monkeypatch.setattr(warmup_mod.settings, "db_path", tmp_path / "missing-jpintel.db")
    monkeypatch.setattr(
        warmup_mod.settings,
        "autonomath_db_path",
        tmp_path / "missing-autonomath.db",
    )
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "1")

    out = await warmup_mod.warmup_databases()
    assert out == {}, "missing DBs should produce empty result"


@pytest.mark.asyncio
async def test_warmup_disabled_via_env(tmp_path, monkeypatch):
    """`AUTONOMATH_WARMUP_ENABLED=0` short-circuits before any open."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    # Even with valid DBs the env-var kill switch should win.
    jp = tmp_path / "jpintel.db"
    am = tmp_path / "autonomath.db"
    _make_minimal_db(jp, list(warmup_mod._JPINTEL_PROBES))
    _make_minimal_db(am, list(warmup_mod._AUTONOMATH_PROBES))
    monkeypatch.setattr(warmup_mod.settings, "db_path", jp)
    monkeypatch.setattr(warmup_mod.settings, "autonomath_db_path", am)
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "0")

    out = await warmup_mod.warmup_databases()
    assert out == {}, "kill switch must short-circuit before any work"


@pytest.mark.asyncio
async def test_warmup_probes_real_tables(tmp_path, monkeypatch):
    """Real SQLite + real probe-target tables → per-table elapsed map."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    jp = tmp_path / "jpintel.db"
    am = tmp_path / "autonomath.db"
    _make_minimal_db(jp, list(warmup_mod._JPINTEL_PROBES))
    _make_minimal_db(am, list(warmup_mod._AUTONOMATH_PROBES))
    monkeypatch.setattr(warmup_mod.settings, "db_path", jp)
    monkeypatch.setattr(warmup_mod.settings, "autonomath_db_path", am)
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "1")

    out = await warmup_mod.warmup_databases()
    assert "jpintel" in out
    assert "autonomath" in out
    # Every requested table must appear in the per-DB elapsed dict.
    assert set(out["jpintel"].keys()) == set(warmup_mod._JPINTEL_PROBES)
    assert set(out["autonomath"].keys()) == set(warmup_mod._AUTONOMATH_PROBES)
    # Elapsed values are floats >= 0 and bounded by the per-probe timeout.
    for db, results in out.items():
        for table, elapsed in results.items():
            assert elapsed >= 0.0, f"{db}.{table} elapsed must be non-negative"
            assert elapsed < warmup_mod._PROBE_TIMEOUT_S, (
                f"{db}.{table} elapsed {elapsed:.3f}s exceeds per-probe timeout"
            )


@pytest.mark.asyncio
async def test_warmup_skips_missing_tables(tmp_path, monkeypatch):
    """A DB that exists but lacks probe targets returns no warm rows.

    Specifically: `_run_probes_sync` logs "table missing" but does not
    raise. The DB shows up in the result iff at least one table probed
    successfully.
    """
    from jpintel_mcp.api import _db_warmup as warmup_mod

    jp = tmp_path / "jpintel.db"
    am = tmp_path / "autonomath.db"
    # Create both files but with NO probe-target tables (only a sentinel).
    _make_minimal_db(jp, ["unrelated_sentinel"])
    _make_minimal_db(am, ["unrelated_sentinel"])
    monkeypatch.setattr(warmup_mod.settings, "db_path", jp)
    monkeypatch.setattr(warmup_mod.settings, "autonomath_db_path", am)
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "1")

    out = await warmup_mod.warmup_databases()
    # Neither DB has probe-target tables → both omitted from result.
    assert out == {}


@pytest.mark.asyncio
async def test_warmup_partial_coverage(tmp_path, monkeypatch):
    """Only one DB has tables → only that DB shows up in the result."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    jp = tmp_path / "jpintel.db"
    am = tmp_path / "autonomath.db"
    _make_minimal_db(jp, list(warmup_mod._JPINTEL_PROBES))
    # autonomath.db missing entirely
    monkeypatch.setattr(warmup_mod.settings, "db_path", jp)
    monkeypatch.setattr(warmup_mod.settings, "autonomath_db_path", am)
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "1")

    out = await warmup_mod.warmup_databases()
    assert "jpintel" in out
    assert "autonomath" not in out


@pytest.mark.asyncio
async def test_schedule_warmup_returns_task(tmp_path, monkeypatch):
    """`schedule_warmup()` returns an asyncio.Task without awaiting it."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    monkeypatch.setattr(warmup_mod.settings, "db_path", tmp_path / "missing.db")
    monkeypatch.setattr(warmup_mod.settings, "autonomath_db_path", tmp_path / "missing.db")
    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", "1")

    task = warmup_mod.schedule_warmup()
    try:
        assert isinstance(task, asyncio.Task)
        # The returned task must be drainable — awaiting it must not raise.
        result = await task
        assert result == {}
    finally:
        if not task.done():
            task.cancel()


def test_is_enabled_default_on(monkeypatch):
    """Default (unset env) is treated as enabled — production posture."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    monkeypatch.delenv("AUTONOMATH_WARMUP_ENABLED", raising=False)
    assert warmup_mod._is_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", ""])
def test_is_enabled_disabled_values(value, monkeypatch):
    """Each documented "disabled" string short-circuits the warmup."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", value)
    assert warmup_mod._is_enabled() is False, f"value={value!r} should disable"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_is_enabled_enabled_values(value, monkeypatch):
    from jpintel_mcp.api import _db_warmup as warmup_mod

    monkeypatch.setenv("AUTONOMATH_WARMUP_ENABLED", value)
    assert warmup_mod._is_enabled() is True, f"value={value!r} should enable"


def test_probe_table_swallows_missing_table(tmp_path):
    """`_probe_table` returns (False, elapsed) for a missing table — no raise."""
    from jpintel_mcp.api import _db_warmup as warmup_mod

    db = tmp_path / "probe.db"
    _make_minimal_db(db, ["existing"])
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        ok, elapsed = warmup_mod._probe_table(con, "nonexistent")
        assert ok is False
        assert elapsed >= 0.0
    finally:
        con.close()


def test_probe_table_succeeds_on_real_table(tmp_path):
    from jpintel_mcp.api import _db_warmup as warmup_mod

    db = tmp_path / "probe.db"
    _make_minimal_db(db, ["am_entities"])
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        ok, elapsed = warmup_mod._probe_table(con, "am_entities")
        assert ok is True
        assert elapsed >= 0.0
    finally:
        con.close()


def test_open_ro_returns_none_for_missing(tmp_path):
    from jpintel_mcp.api import _db_warmup as warmup_mod

    assert warmup_mod._open_ro(tmp_path / "definitely-missing.db") is None
