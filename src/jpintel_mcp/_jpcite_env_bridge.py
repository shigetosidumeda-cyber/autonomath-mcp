"""jpcite environment bridge (Wave 46 / 47 rename — destruction-free).

The jpcite rename (formerly AutonoMath / jpintel-mcp) deliberately keeps the
legacy ``AUTONOMATH_*`` / ``JPINTEL_*`` environment variable names alive while
introducing canonical ``JPCITE_*`` aliases.  Per ``feedback_destruction_free_organization``,
deleting the legacy env vars is forbidden — operators running prod, CI and Fly
secrets all rely on them today.

This module exposes a *read-only* lookup helper, :func:`get_flag`, which honours
the canonical name first and falls back to the legacy name (and finally to a
default).  Use it anywhere a direct ``os.environ.get("AUTONOMATH_X", ...)`` or
``os.getenv("JPINTEL_X", ...)`` would otherwise live.

Design notes:

* No ``Settings`` dependency: deliberately keeps the helper importable from
  ``scripts/cron`` / ``scripts/etl`` boot paths that run *before* pydantic
  validation (and from ``self_improve`` loops which intentionally avoid the
  full ``Settings`` graph).
* Pure standard-library: zero new dependencies (we cannot add LLM/SDK imports
  per ``feedback_autonomath_no_api_use`` / ``feedback_no_operator_llm_api``).
* Idempotent: calling :func:`get_flag` is side-effect free; no env mutation.
* Stable ordering: the canonical key (``primary``) is always checked first,
  then the legacy key(s).  Empty strings are treated as "unset" so CI runners
  that export blank values do not accidentally pin the wrong key.
* Deprecation warnings: legacy hits emit a :class:`DeprecationWarning` so
  operators see the alias in logs and can plan a flip-day cutover.

Companion pattern: ``Settings`` (``src/jpintel_mcp/config.py``) handles its
own dual-read via ``AliasChoices`` (Wave 46.E).  This bridge covers all the
*non*-Settings callsites — ad-hoc reads scattered across MCP tools, REST
routers, cron jobs and ETL scripts.

Wave history:
  * 46.D (PR #131) — initial bridge with deprecation warnings + typed helpers
  * 46.E (PR #132) — ``Settings`` AliasChoices conversion (31 fields)
  * 47.A (this PR) — 89 ad-hoc callsite migration via :func:`get_flag`
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "get_flag",
    "get_bool_flag",
    "get_int_flag",
]


# Canonical new-name → legacy alias mapping. Kept as a small constant
# so callers that want to register a Pydantic ``AliasChoices`` block can
# pull the same source of truth instead of re-typing the legacy names
# (which is precisely how the rename has historically drifted).
DEFAULT_ALIAS_MAP: Final[dict[str, tuple[str, ...]]] = {
    # Two-rail rename: AUTONOMATH_* + JPINTEL_* both legacy under jpcite.
    "JPCITE_DB_PATH": ("JPINTEL_DB_PATH",),
    "JPCITE_AUTONOMATH_DB_PATH": ("AUTONOMATH_DB_PATH",),
    "JPCITE_AUTONOMATH_PATH": ("JPINTEL_AUTONOMATH_PATH",),
    "JPCITE_AUTONOMATH_ENABLED": ("AUTONOMATH_ENABLED",),
    "JPCITE_RULE_ENGINE_ENABLED": ("AUTONOMATH_RULE_ENGINE_ENABLED",),
}


_MISSING: Final = object()


def _read(key: str, *, allow_empty: bool = False) -> str | None:
    """Return env value if set, with optional empty-string preservation.

    We treat empty strings as unset so a stray ``export AUTONOMATH_X=`` in CI
    does not pin the legacy key when ``JPCITE_X`` is the real source of truth.
    The original Wave 46.D keyword-default API treated an explicitly set empty
    canonical value as meaningful, so ``allow_empty`` preserves that
    destruction-free compatibility path for callers using that signature.
    """
    raw = os.environ.get(key)
    if raw is None:
        return None
    if raw == "" and not allow_empty:
        return None
    return raw


def _emit_deprecation(legacy: str, canonical: str, *, stacklevel: int) -> None:
    """Single chokepoint so the warning text never drifts across helpers."""
    warnings.warn(
        f"env {legacy} deprecated, use {canonical}",
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def get_flag(
    primary: str,
    legacy: str | None = None,
    *extra_legacy: str,
    default: object = _MISSING,
) -> str | None:
    """Look up an env flag, preferring canonical ``primary`` then legacy alias(es).

    Parameters
    ----------
    primary:
        Canonical (``JPCITE_*``) env name — checked first.
    legacy:
        Primary legacy alias (``AUTONOMATH_*`` / ``JPINTEL_*``) — checked next.
        ``None`` means no legacy fallback (canonical-only lookup).
    extra_legacy:
        Either extra legacy aliases (Wave 46.D keyword-default signature) or,
        when ``default=`` is not supplied, the first positional value is treated
        as the Wave 47.A positional default.
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
    * Legacy hits emit a :class:`DeprecationWarning` (single chokepoint).
    * If ``primary == legacy`` (a typo guard or transition complete), the
      function still works and behaves as a single ``os.environ.get`` call.
    """
    keyword_default = default is not _MISSING
    if keyword_default:
        fallback = default
        aliases = extra_legacy
    elif extra_legacy:
        fallback = extra_legacy[0]
        aliases = extra_legacy[1:]
    else:
        fallback = None
        aliases = ()

    value = _read(primary, allow_empty=keyword_default)
    if value is not None:
        return value
    if legacy is not None:
        value = _read(legacy)
        if value is not None:
            if legacy != primary:
                _emit_deprecation(legacy, primary, stacklevel=2)
            return value
    for alias in aliases:
        value = _read(alias)
        if value is not None:
            _emit_deprecation(alias, primary, stacklevel=2)
            return value
    if fallback is _MISSING:
        return None
    return fallback if fallback is None or isinstance(fallback, str) else str(fallback)


_TRUTHY: Final = frozenset(
    {"1", "true", "TRUE", "True", "yes", "YES", "on", "ON", "y", "Y", "t", "T"}
)
_FALSY: Final = frozenset(
    {"0", "false", "FALSE", "False", "no", "NO", "off", "OFF", "n", "N", "f", "F", ""}
)


def _truthy(raw: str) -> bool:
    """Match the boolean parsing semantics used elsewhere in jpcite."""
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def get_bool_flag(primary: str, legacy: str, default: bool) -> bool:
    """Boolean variant of :func:`get_flag`.

    Recognises common truthy / falsy spellings.  Anything unrecognised falls
    back to ``default`` (we deliberately do not raise — boot-time guards must
    not crash because a downstream operator typed ``ENABLED=on`` instead of
    ``1``).
    """
    raw = get_flag(primary, legacy, default=None)
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
    raw = get_flag(primary, legacy, default=None)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 46.D-style variadic helpers (kept for code that was migrated against the
# initial PR #131 signatures).  Internally these forward to ``get_flag``.
# ---------------------------------------------------------------------------


def get_bool(
    new_name: str,
    *legacy_names: str,
    default: bool = False,
) -> bool:
    """Boolean variant accepting variadic legacy names (46.D signature)."""
    if not legacy_names:
        raw = get_flag(new_name, None, default=None)
    else:
        raw = get_flag(new_name, legacy_names[0], *legacy_names[1:], default=None)
    if raw is None:
        return default
    return _truthy(raw)


def get_int(
    new_name: str,
    *legacy_names: str,
    default: int = 0,
) -> int:
    """Integer variant accepting variadic legacy names (46.D signature)."""
    if not legacy_names:
        raw = get_flag(new_name, None, default=None)
    else:
        raw = get_flag(new_name, legacy_names[0], *legacy_names[1:], default=None)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def get_list(
    new_name: str,
    *legacy_names: str,
    default: Iterable[str] | None = None,
    separator: str = ",",
) -> list[str]:
    """CSV variant. Empty-string env yields an empty list (not default)."""
    if not legacy_names:
        raw = get_flag(new_name, None, default=None)
    else:
        raw = get_flag(new_name, legacy_names[0], *legacy_names[1:], default=None)
    if raw is None:
        return list(default or [])
    parts = [piece.strip() for piece in raw.split(separator)]
    return [piece for piece in parts if piece]
