"""W46.D — test coverage for the env dual-read bridge.

Verifies the three contractual behaviours laid out in
``docs/research/wave46/STATE_w46_46d_pr.md``:

1. canonical (new) env name wins over any legacy alias;
2. legacy fallback is honoured when the canonical name is unset; and
3. a :class:`DeprecationWarning` fires exactly once per legacy read,
   with a message that names both the legacy and canonical variables
   so operators can grep for it in logs.

Typed helpers (bool / int / list) get a lighter smoke each so the
shared core does not regress as the alias map grows.
"""

from __future__ import annotations

import warnings

import pytest

from jpintel_mcp._jpcite_env_bridge import (
    DEFAULT_ALIAS_MAP,
    get_bool,
    get_flag,
    get_int,
    get_list,
)

CANONICAL = "JPCITE_W46D_PROBE"
LEGACY_A = "AUTONOMATH_W46D_PROBE"
LEGACY_B = "JPINTEL_W46D_PROBE"


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no probe variable leaks between cases."""
    for name in (CANONICAL, LEGACY_A, LEGACY_B):
        monkeypatch.delenv(name, raising=False)


def test_new_name_wins_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CANONICAL, "new-value")
    monkeypatch.setenv(LEGACY_A, "legacy-value-should-not-win")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = get_flag(CANONICAL, LEGACY_A, default="fallback")
    assert result == "new-value"
    # No warning when the new name is the one consulted.
    assert not [w for w in captured if issubclass(w.category, DeprecationWarning)]


def test_legacy_fallback_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LEGACY_A, "legacy-value")
    result = get_flag(CANONICAL, LEGACY_A, default="fallback")
    assert result == "legacy-value"


def test_legacy_fallback_emits_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LEGACY_A, "legacy-value")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        get_flag(CANONICAL, LEGACY_A)
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1
    message = str(deprecations[0].message)
    assert LEGACY_A in message
    assert CANONICAL in message
    assert "deprecated" in message


def test_multiple_legacy_aliases_first_hit_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only the SECOND legacy is set; the function must try LEGACY_A,
    # miss, then return LEGACY_B and warn about LEGACY_B specifically.
    monkeypatch.setenv(LEGACY_B, "second-legacy")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = get_flag(CANONICAL, LEGACY_A, LEGACY_B, default=None)
    assert result == "second-legacy"
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1
    assert LEGACY_B in str(deprecations[0].message)


def test_default_returned_when_nothing_set() -> None:
    assert get_flag(CANONICAL, LEGACY_A, default="fallback") == "fallback"
    assert get_flag(CANONICAL, LEGACY_A) is None


def test_empty_string_canonical_returned_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string is a valid set value — must NOT trigger fallback."""
    monkeypatch.setenv(CANONICAL, "")
    monkeypatch.setenv(LEGACY_A, "not-used")
    result = get_flag(CANONICAL, LEGACY_A, default="fallback")
    assert result == ""


def test_get_bool_truthy_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("1", "true", "TRUE", "yes", "on", "T"):
        monkeypatch.setenv(CANONICAL, raw)
        assert get_bool(CANONICAL) is True


def test_get_bool_falsy_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CANONICAL, "0")
    assert get_bool(CANONICAL, default=True) is False
    monkeypatch.delenv(CANONICAL, raising=False)
    assert get_bool(CANONICAL, default=True) is True
    assert get_bool(CANONICAL, default=False) is False


def test_get_bool_legacy_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LEGACY_A, "true")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert get_bool(CANONICAL, LEGACY_A) is True
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1


def test_get_int_parses_and_handles_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CANONICAL, "42")
    assert get_int(CANONICAL) == 42
    monkeypatch.setenv(CANONICAL, "  17 ")
    assert get_int(CANONICAL) == 17
    monkeypatch.setenv(CANONICAL, "nan-here")
    assert get_int(CANONICAL, default=-1) == -1
    monkeypatch.setenv(CANONICAL, "")
    assert get_int(CANONICAL, default=9) == 9


def test_get_list_csv_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CANONICAL, "a, b ,c, ,")
    assert get_list(CANONICAL) == ["a", "b", "c"]
    monkeypatch.delenv(CANONICAL, raising=False)
    assert get_list(CANONICAL, default=["x"]) == ["x"]
    monkeypatch.setenv(CANONICAL, "")
    # Empty string env yields empty list explicitly, NOT default.
    assert get_list(CANONICAL, default=["x"]) == []


def test_default_alias_map_has_canonical_keys() -> None:
    # Defensive — guards against accidental rename of the map itself.
    assert "JPCITE_AUTONOMATH_DB_PATH" in DEFAULT_ALIAS_MAP
    aliases = DEFAULT_ALIAS_MAP["JPCITE_AUTONOMATH_DB_PATH"]
    assert "AUTONOMATH_DB_PATH" in aliases
    # All keys must start with the JPCITE_ canonical prefix.
    assert all(k.startswith("JPCITE_") for k in DEFAULT_ALIAS_MAP)
