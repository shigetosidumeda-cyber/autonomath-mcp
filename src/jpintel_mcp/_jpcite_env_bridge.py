"""jpcite environment bridge (Wave 46 / 47 rename — destruction-free).

The jpcite rename (formerly AutonoMath / jpintel-mcp) deliberately keeps the
legacy ``AUTONOMATH_*`` / ``JPINTEL_*`` environment variable names alive while
introducing canonical ``JPCITE_*`` aliases.  Per ``feedback_destruction_free_organization``,
deleting the legacy env vars is forbidden — operators running prod, CI and Fly
secrets all rely on them today.

This module exposes a *read-only* lookup helper, ``get_flag``, which honours
the new canonical name first and falls back to the legacy name (and finally to
a default).  Use it anywhere a direct ``os.environ.get("AUTONOMATH_X", ...)``
or ``os.getenv("JPINTEL_X", ...)`` would otherwise live.

Design notes:

* No ``Settings`` dependency: deliberately keeps the helper importable from
  ``scripts/cron`` / ``scripts/etl`` boot paths that run *before* pydantic
  validation (and from ``self_improve`` loops which intentionally avoid the
  full ``Settings`` graph).
* Pure standard-library: zero new dependencies (we cannot add LLM/SDK imports
  per ``feedback_autonomath_no_api_use`` / ``feedback_no_operator_llm_api``).
* Idempotent: calling ``get_flag`` is side-effect free; no env mutation.
* Stable ordering: the canonical key (``primary``) is always checked first,
  then the legacy key (``legacy``).  Empty strings are treated as "unset" so
  CI runners that export blank values do not accidentally pin the wrong key.

Companion pattern: ``Settings`` (``src/jpintel_mcp/config.py``) handles its
own dual-read via ``AliasChoices`` (Wave 46.E).  This bridge covers all the
*non*-Settings callsites — ad-hoc reads scattered across MCP tools, REST
routers, cron jobs and ETL scripts.

Wave history:
  * 46.E (PR #132)  — ``Settings`` AliasChoices conversion (31 fields)
  * 47.A (this PR)  — 89 ad-hoc callsite migration via ``get_flag``
"""

from __future__ import annotations

import os
from typing import Final

__all__ = ["get_flag", "get_bool_flag", "get_int_flag"]


def _read(key: str) -> str | None:
    """Return env value if set and non-empty, else None."""
    raw = os.environ.get(key)
    if raw is None:
        return None
    if raw == "":
        # Treat empty as unset so a stray `export AUTONOMATH_X=` in CI does
        # not pin the legacy key when JPCITE_X is the real source of truth.
        return None
    return raw


def get_flag(primary: str, legacy: str, default: str | None = None) -> str | None:
    """Look up an env flag, preferring the canonical ``primary`` then ``legacy``.

    Parameters
    ----------
    primary:
        Canonical (``JPCITE_*``) env name — checked first.
    legacy:
        Legacy (``AUTONOMATH_*`` / ``JPINTEL_*``) env name — checked second.
    default:
        Returned when neither key is set (or both are empty strings).

    Returns
    -------
    The first non-empty value found, otherwise ``default``.

    Notes
    -----
    * This is read-only: callers must not mutate the environment based on the
      lookup result (no auto-promotion legacy -> primary), per
      ``feedback_destruction_free_organization``.
    * If ``primary == legacy`` (a typo guard or transition complete), the
      function still works and behaves as a single ``os.environ.get`` call.
    """
    value = _read(primary)
    if value is not None:
        return value
    value = _read(legacy)
    if value is not None:
        return value
    return default


_TRUTHY: Final = frozenset({"1", "true", "TRUE", "True", "yes", "YES", "on", "ON"})
_FALSY: Final = frozenset({"0", "false", "FALSE", "False", "no", "NO", "off", "OFF", ""})


def get_bool_flag(primary: str, legacy: str, default: bool) -> bool:
    """Boolean variant of :func:`get_flag`.

    Recognises common truthy / falsy spellings.  Anything unrecognised falls
    back to ``default`` (we deliberately do not raise — boot-time guards must
    not crash because a downstream operator typed ``ENABLED=on`` instead of
    ``1``).
    """
    raw = get_flag(primary, legacy, None)
    if raw is None:
        return default
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    # Unknown spelling — be permissive and return the default rather than
    # silently flipping the flag.
    return default


def get_int_flag(primary: str, legacy: str, default: int) -> int:
    """Integer variant of :func:`get_flag` with safe fallback.

    Returns ``default`` when the value is missing, empty, or not a valid int
    (so a typo in CI does not crash boot).
    """
    raw = get_flag(primary, legacy, None)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
