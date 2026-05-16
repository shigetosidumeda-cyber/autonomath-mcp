"""Wave 46.E pydantic AliasChoices dual-read test.

Wave 46 rename plan ([[project_jpcite_internal_autonomath_rename]]) converts every
``AUTONOMATH_*`` / ``JPINTEL_*`` env alias on ``Settings`` to a
``validation_alias=AliasChoices("JPCITE_<NAME>", "<LEGACY_NAME>")`` pair so the new
``JPCITE_*`` env names take precedence while the legacy AUTONOMATH/JPINTEL aliases
remain readable (destruction-free rule [[feedback_destruction_free_organization]]).

This test sweeps the 20 most-load-bearing flags and verifies, for each one:

1. ``new`` — setting the ``JPCITE_<NAME>`` env yields the expected value.
2. ``legacy`` — setting only the ``AUTONOMATH_<NAME>`` / ``JPINTEL_<NAME>`` env yields
   the same expected value (legacy callers keep working).
3. ``default`` — with both names unset, the Field default is returned.

The matrix is parametrised so any regression on a single env shows up as one failed
case rather than aborting the whole sweep.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# Repository layout: ``src/`` is on PYTHONPATH at pytest collection time via the
# top-level conftest, so the import is plain ``jpintel_mcp.config``.
from jpintel_mcp.config import Settings

# --- matrix --------------------------------------------------------------------

# (attr, jpcite_env, legacy_env, default_value, override_value)
# default_value is what the Field declares; override_value is what we'll set the
# env to and assert ``settings.<attr> == override_value``.
ENV_MATRIX: list[tuple[str, str, str, object, object]] = [
    # bool flags — JPCITE primary + AUTONOMATH legacy
    ("autonomath_enabled", "JPCITE_ENABLED", "AUTONOMATH_ENABLED", True, False),
    (
        "rule_engine_enabled",
        "JPCITE_RULE_ENGINE_ENABLED",
        "AUTONOMATH_RULE_ENGINE_ENABLED",
        True,
        False,
    ),
    (
        "healthcare_enabled",
        "JPCITE_HEALTHCARE_ENABLED",
        "AUTONOMATH_HEALTHCARE_ENABLED",
        False,
        True,
    ),
    (
        "real_estate_enabled",
        "JPCITE_REAL_ESTATE_ENABLED",
        "AUTONOMATH_REAL_ESTATE_ENABLED",
        False,
        True,
    ),
    (
        "saburoku_kyotei_enabled",
        "JPCITE_36_KYOTEI_ENABLED",
        "AUTONOMATH_36_KYOTEI_ENABLED",
        False,
        True,
    ),
    (
        "r8_versioning_enabled",
        "JPCITE_R8_VERSIONING_ENABLED",
        "AUTONOMATH_R8_VERSIONING_ENABLED",
        True,
        False,
    ),
    (
        "autonomath_snapshot_enabled",
        "JPCITE_SNAPSHOT_ENABLED",
        "AUTONOMATH_SNAPSHOT_ENABLED",
        True,
        False,
    ),
    (
        "autonomath_reasoning_enabled",
        "JPCITE_REASONING_ENABLED",
        "AUTONOMATH_REASONING_ENABLED",
        False,
        True,
    ),
    (
        "autonomath_graph_enabled",
        "JPCITE_GRAPH_ENABLED",
        "AUTONOMATH_GRAPH_ENABLED",
        True,
        False,
    ),
    (
        "prerequisite_chain_enabled",
        "JPCITE_PREREQUISITE_CHAIN_ENABLED",
        "AUTONOMATH_PREREQUISITE_CHAIN_ENABLED",
        True,
        False,
    ),
    (
        "autonomath_nta_corpus_enabled",
        "JPCITE_NTA_CORPUS_ENABLED",
        "AUTONOMATH_NTA_CORPUS_ENABLED",
        True,
        False,
    ),
    (
        "autonomath_wave22_enabled",
        "JPCITE_WAVE22_ENABLED",
        "AUTONOMATH_WAVE22_ENABLED",
        True,
        False,
    ),
    (
        "autonomath_industry_packs_enabled",
        "JPCITE_INDUSTRY_PACKS_ENABLED",
        "AUTONOMATH_INDUSTRY_PACKS_ENABLED",
        True,
        False,
    ),
    (
        "prompt_injection_guard_enabled",
        "JPCITE_PROMPT_INJECTION_GUARD",
        "AUTONOMATH_PROMPT_INJECTION_GUARD",
        True,
        False,
    ),
    (
        "pii_redact_response_enabled",
        "JPCITE_PII_REDACT_RESPONSE_ENABLED",
        "AUTONOMATH_PII_REDACT_RESPONSE_ENABLED",
        True,
        False,
    ),
    (
        "uncertainty_enabled",
        "JPCITE_UNCERTAINTY_ENABLED",
        "AUTONOMATH_UNCERTAINTY_ENABLED",
        True,
        False,
    ),
    # string flag
    (
        "autonomath_disclaimer_level",
        "JPCITE_DISCLAIMER_LEVEL",
        "AUTONOMATH_DISCLAIMER_LEVEL",
        "standard",
        "strict",
    ),
    # JPINTEL legacy migration
    ("log_level", "JPCITE_LOG_LEVEL", "JPINTEL_LOG_LEVEL", "INFO", "DEBUG"),
    ("log_format", "JPCITE_LOG_FORMAT", "JPINTEL_LOG_FORMAT", "json", "text"),
    ("env", "JPCITE_ENV", "JPINTEL_ENV", "dev", "prod"),
]


# --- env scrubber --------------------------------------------------------------

# Every env key the matrix touches. Centralised so the fixture clears all of them
# before each parametrised case — leaks between cases would silently mask the
# 3-state check.
_ALL_KEYS = sorted({key for _, jp, lg, _, _ in ENV_MATRIX for key in (jp, lg)})


@pytest.fixture
def clean_env() -> Iterator[dict[str, str | None]]:
    """Strip every JPCITE_/AUTONOMATH_/JPINTEL_ key the matrix touches.

    Restores the original env after the test. Uses direct ``os.environ`` access
    rather than ``monkeypatch`` to side-step pydantic-settings interactions with
    pytest's monkeypatch helpers (Wave 46.E investigation 2026-05-12: monkeypatch
    setenv was observed to be ignored by ``Settings()`` when the legacy
    ``AUTONOMATH_*`` env was also unset earlier in the same fixture).
    """
    saved: dict[str, str | None] = {key: os.environ.get(key) for key in _ALL_KEYS}
    for key in _ALL_KEYS:
        os.environ.pop(key, None)
    try:
        yield saved
    finally:
        # Restore the original env exactly.
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _set_env(key: str, value: str) -> None:
    """Set an env var directly on ``os.environ`` (replacement for monkeypatch.setenv)."""
    os.environ[key] = value


def _as_env(value: object) -> str:
    """Coerce a Python value into the str representation pydantic-settings parses."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# --- the sweep -----------------------------------------------------------------


@pytest.mark.parametrize(
    "attr,jpcite_env,legacy_env,default_value,override_value",
    ENV_MATRIX,
    ids=[row[0] for row in ENV_MATRIX],
)
def test_aliaschoices_default(
    clean_env: dict[str, str | None],
    attr: str,
    jpcite_env: str,
    legacy_env: str,
    default_value: object,
    override_value: object,
) -> None:
    """Both env names unset → the Field default surfaces."""
    s = Settings()
    assert getattr(s, attr) == default_value, (
        f"{attr}: default mismatch (got {getattr(s, attr)!r}, want {default_value!r})"
    )


@pytest.mark.parametrize(
    "attr,jpcite_env,legacy_env,default_value,override_value",
    ENV_MATRIX,
    ids=[row[0] for row in ENV_MATRIX],
)
def test_aliaschoices_new_primary(
    clean_env: dict[str, str | None],
    attr: str,
    jpcite_env: str,
    legacy_env: str,
    default_value: object,
    override_value: object,
) -> None:
    """Setting the new JPCITE_<NAME> env reaches the Settings field."""
    _set_env(jpcite_env, _as_env(override_value))
    s = Settings()
    assert getattr(s, attr) == override_value, (
        f"{attr}: new alias {jpcite_env}={override_value!r} not honored (got {getattr(s, attr)!r})"
    )


@pytest.mark.parametrize(
    "attr,jpcite_env,legacy_env,default_value,override_value",
    ENV_MATRIX,
    ids=[row[0] for row in ENV_MATRIX],
)
def test_aliaschoices_legacy_fallback(
    clean_env: dict[str, str | None],
    attr: str,
    jpcite_env: str,
    legacy_env: str,
    default_value: object,
    override_value: object,
) -> None:
    """Only legacy env set → value is still read (backwards-compat)."""
    _set_env(legacy_env, _as_env(override_value))
    s = Settings()
    assert getattr(s, attr) == override_value, (
        f"{attr}: legacy alias {legacy_env}={override_value!r} not honored "
        f"(got {getattr(s, attr)!r})"
    )


def test_aliaschoices_jpcite_precedence_over_legacy(
    clean_env: dict[str, str | None],
) -> None:
    """When both names are set, JPCITE_<NAME> wins (first AliasChoices entry).

    Anchor case: ``autonomath_enabled``. Setting JPCITE_ENABLED=0 and
    AUTONOMATH_ENABLED=1 simultaneously must yield ``False`` — proving the
    JPCITE primary takes precedence per AliasChoices ordering.
    """
    _set_env("JPCITE_ENABLED", "0")
    _set_env("AUTONOMATH_ENABLED", "1")
    s = Settings()
    assert s.autonomath_enabled is False, (
        "JPCITE primary did not override AUTONOMATH legacy when both set"
    )


def test_aliaschoices_legacy_does_not_block_new() -> None:
    """Sanity import — every AliasChoices Field resolves on a fresh Settings()."""
    s = Settings()
    # 20 attrs from the matrix should all be readable without ValidationError.
    for row in ENV_MATRIX:
        attr = row[0]
        getattr(s, attr)
