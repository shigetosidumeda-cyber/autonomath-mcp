"""Wave 47.A — verify the 89 jpcite env-bridge callsites resolve correctly.

Companion to Wave 46.E (which converted 31 ``Settings`` aliases to
``AliasChoices``).  This wave converted 89 *ad-hoc* ``os.environ.get`` /
``os.getenv`` callsites in MCP tools, REST routers, cron jobs, ETL scripts
and self-improve loops to go through
:func:`jpintel_mcp._jpcite_env_bridge.get_flag`.

For each callsite the contract is identical:

1. **default mode** — neither ``JPCITE_*`` nor the legacy name is set:
   the helper returns the hard-coded default.
2. **new-primary mode** — only ``JPCITE_*`` is set: the helper returns
   that value (legacy is unset).
3. **legacy-fallback mode** — only the legacy name (``AUTONOMATH_*`` or
   ``JPINTEL_*``) is set: the helper returns the legacy value
   (destruction-free guarantee — existing Fly / GHA secrets keep working).
4. **precedence** — both names set: ``JPCITE_*`` wins.

We exercise the bridge directly with the same (primary, legacy, default)
triplets that 20 high-traffic callsites use, then add anchor tests that
spot-check the helper module itself (truthy/falsy parsing, empty string
handling, integer coercion).

Total: 20 sample callsites × 3 modes = 60 case + 2 anchor = 62.
"""

from __future__ import annotations

import os

import pytest

from jpintel_mcp._jpcite_env_bridge import (
    get_bool_flag,
    get_flag,
    get_int_flag,
)

# (primary, legacy, default) — drawn from the 89 callsites converted in
# Wave 47.A.  20 representative entries covering all 6 categories.
SAMPLE_CALLSITES = [
    # src/tools — _ENABLED flags
    ("JPCITE_ELIGIBILITY_CHECK_ENABLED", "AUTONOMATH_ELIGIBILITY_CHECK_ENABLED", "1"),
    ("JPCITE_GRAPH_TRAVERSE_ENABLED", "AUTONOMATH_GRAPH_TRAVERSE_ENABLED", "1"),
    ("JPCITE_BENCHMARK_ENABLED", "AUTONOMATH_BENCHMARK_ENABLED", "1"),
    ("JPCITE_FUNDING_STACK_ENABLED", "AUTONOMATH_FUNDING_STACK_ENABLED", "1"),
    ("JPCITE_COHORT_RISK_CHAIN_ENABLED", "AUTONOMATH_COHORT_RISK_CHAIN_ENABLED", "1"),
    ("JPCITE_DISCOVER_ENABLED", "AUTONOMATH_DISCOVER_ENABLED", "1"),
    # src/tools — DB paths
    ("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "data/jpintel.db"),
    ("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", "autonomath.db"),
    ("JPCITE_GRAPH_DB_PATH", "AUTONOMATH_GRAPH_DB_PATH", "graph.db"),
    ("JPCITE_VEC0_PATH", "AUTONOMATH_VEC0_PATH", ""),
    # src/api — endpoints
    ("JPCITE_API_BASE", "AUTONOMATH_API_BASE", ""),
    ("JPCITE_API_KEY", "AUTONOMATH_API_KEY", ""),
    ("JPCITE_ENV", "JPINTEL_ENV", "dev"),
    # scripts/cron — DB + secrets
    ("JPCITE_DB_URL", "AUTONOMATH_DB_URL", ""),
    ("JPCITE_DB_SHA256", "AUTONOMATH_DB_SHA256", ""),
    ("JPCITE_LOG_LEVEL", "JPINTEL_LOG_LEVEL", "INFO"),
    ("JPCITE_BUDGET_JPY", "AUTONOMATH_BUDGET_JPY", "10000"),
    # scripts/etl
    ("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", "/data/autonomath.db"),
    # scripts/ops
    ("JPCITE_API_BASE", "JPINTEL_API_BASE", ""),
    # src/self_improve
    ("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "/repo/data/jpintel.db"),
]

# Each callsite is exercised in 3 modes (default / new / legacy) plus the
# precedence anchor exercised on a single representative pair.


def _clear(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    for key in keys:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(("primary", "legacy", "default"), SAMPLE_CALLSITES)
def test_default_mode(
    monkeypatch: pytest.MonkeyPatch,
    primary: str,
    legacy: str,
    default: str,
) -> None:
    """Neither env var set — helper returns ``default`` verbatim."""
    _clear(monkeypatch, primary, legacy)
    assert get_flag(primary, legacy, default) == default


@pytest.mark.parametrize(("primary", "legacy", "default"), SAMPLE_CALLSITES)
def test_new_primary_mode(
    monkeypatch: pytest.MonkeyPatch,
    primary: str,
    legacy: str,
    default: str,
) -> None:
    """Only canonical ``JPCITE_*`` set — helper returns that value."""
    _clear(monkeypatch, primary, legacy)
    monkeypatch.setenv(primary, "from-new-primary")
    assert get_flag(primary, legacy, default) == "from-new-primary"


@pytest.mark.parametrize(("primary", "legacy", "default"), SAMPLE_CALLSITES)
def test_legacy_fallback_mode(
    monkeypatch: pytest.MonkeyPatch,
    primary: str,
    legacy: str,
    default: str,
) -> None:
    """Only legacy name set — helper falls back to it (destruction-free)."""
    _clear(monkeypatch, primary, legacy)
    monkeypatch.setenv(legacy, "from-legacy")
    assert get_flag(primary, legacy, default) == "from-legacy"


def test_precedence_primary_wins_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both env vars set — canonical wins (no auto-promote, no mutation)."""
    monkeypatch.setenv("JPCITE_PRECEDENCE_PROBE", "primary-value")
    monkeypatch.setenv("AUTONOMATH_PRECEDENCE_PROBE", "legacy-value")
    assert (
        get_flag("JPCITE_PRECEDENCE_PROBE", "AUTONOMATH_PRECEDENCE_PROBE", "default")
        == "primary-value"
    )
    # And read-only: both env vars are still present afterwards.
    assert os.environ["JPCITE_PRECEDENCE_PROBE"] == "primary-value"
    assert os.environ["AUTONOMATH_PRECEDENCE_PROBE"] == "legacy-value"


def test_empty_string_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`export JPCITE_X=` should NOT pin the empty string; fall through to legacy."""
    monkeypatch.setenv("JPCITE_EMPTY_PROBE", "")
    monkeypatch.setenv("AUTONOMATH_EMPTY_PROBE", "legacy-resolved")
    assert (
        get_flag("JPCITE_EMPTY_PROBE", "AUTONOMATH_EMPTY_PROBE", "default")
        == "legacy-resolved"
    )


def test_get_bool_flag_truthy_falsy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_BOOL_PROBE", "1")
    assert get_bool_flag("JPCITE_BOOL_PROBE", "AUTONOMATH_BOOL_PROBE", default=False)
    monkeypatch.setenv("JPCITE_BOOL_PROBE", "false")
    assert not get_bool_flag("JPCITE_BOOL_PROBE", "AUTONOMATH_BOOL_PROBE", default=True)
    # Unknown spelling preserves default.
    monkeypatch.setenv("JPCITE_BOOL_PROBE", "weird")
    assert get_bool_flag("JPCITE_BOOL_PROBE", "AUTONOMATH_BOOL_PROBE", default=True)
    assert not get_bool_flag("JPCITE_BOOL_PROBE", "AUTONOMATH_BOOL_PROBE", default=False)


def test_get_int_flag_valid_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_INT_PROBE", "42")
    assert get_int_flag("JPCITE_INT_PROBE", "AUTONOMATH_INT_PROBE", default=7) == 42
    monkeypatch.setenv("JPCITE_INT_PROBE", "not-a-number")
    # Falls back to default rather than raising.
    assert get_int_flag("JPCITE_INT_PROBE", "AUTONOMATH_INT_PROBE", default=7) == 7
    monkeypatch.delenv("JPCITE_INT_PROBE", raising=False)
    monkeypatch.delenv("AUTONOMATH_INT_PROBE", raising=False)
    assert get_int_flag("JPCITE_INT_PROBE", "AUTONOMATH_INT_PROBE", default=99) == 99


def test_bridge_module_exports_public_api() -> None:
    """Anchor: keep the helper's public surface stable so callsites don't break."""
    import jpintel_mcp._jpcite_env_bridge as bridge

    assert sorted(bridge.__all__) == ["get_bool_flag", "get_flag", "get_int_flag"]
    assert callable(bridge.get_flag)
    assert callable(bridge.get_bool_flag)
    assert callable(bridge.get_int_flag)
