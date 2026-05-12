"""W46.D — env dual-read bridge for jpcite rename plan.

This module is the canonical, non-destructive bridge used during the
AUTONOMATH_* → JPCITE_* (and JPINTEL_* → JPCITE_*) env rename. The legacy
variable names ship in production today (Fly secrets + GHA secrets +
``.env.local``); flipping every reading site at once would risk a config
blackout. Instead, every settings source can adopt :func:`get_flag`, which:

1. reads the new (canonical) name first, returning immediately when present;
2. falls back to one-or-more legacy aliases in order, emitting a
   :class:`DeprecationWarning` so operators see the alias in logs;
3. otherwise returns the supplied default.

Companion helpers wrap the same logic for typed (bool / int / list)
reads so the call sites stay one-liners. Nothing here mutates the
process environment — :mod:`os.environ` is read-only from the bridge
side per the destruction-free organization rule.

See ``project_jpcite_internal_autonomath_rename`` in user memory and
``docs/research/wave46/STATE_w46_46d_pr.md`` for the rollout plan.
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "get_flag",
    "get_bool",
    "get_int",
    "get_list",
    "DEFAULT_ALIAS_MAP",
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


def _emit_deprecation(legacy: str, canonical: str, *, stacklevel: int) -> None:
    """Single chokepoint so the warning text never drifts across helpers."""
    warnings.warn(
        f"env {legacy} deprecated, use {canonical}",
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def get_flag(
    new_name: str,
    *legacy_names: str,
    default: str | None = None,
) -> str | None:
    """W46.D: read new env first, fallback to legacy, log deprecation.

    Parameters
    ----------
    new_name:
        The canonical (post-rename) environment variable name. Looked
        up first; if present (even when set to the empty string), its
        value is returned verbatim with no warning.
    legacy_names:
        Zero or more legacy aliases tried in order after ``new_name``
        misses. The first hit returns that value AND triggers a
        :class:`DeprecationWarning` naming the alias.
    default:
        Returned when neither the canonical name nor any legacy alias
        is set. ``None`` by default so callers can distinguish unset
        from empty-string explicitly.
    """
    value = os.getenv(new_name)
    if value is not None:
        return value
    for legacy in legacy_names:
        value = os.getenv(legacy)
        if value is not None:
            _emit_deprecation(legacy, new_name, stacklevel=2)
            return value
    return default


def _truthy(raw: str) -> bool:
    """Match the boolean parsing semantics used elsewhere in jpcite."""
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def get_bool(
    new_name: str,
    *legacy_names: str,
    default: bool = False,
) -> bool:
    """Boolean variant of :func:`get_flag` (same dual-read + warn rules)."""
    raw = get_flag(new_name, *legacy_names, default=None)
    if raw is None:
        return default
    return _truthy(raw)


def get_int(
    new_name: str,
    *legacy_names: str,
    default: int = 0,
) -> int:
    """Integer variant. Returns ``default`` if the value is non-numeric.

    We deliberately swallow parse errors instead of raising — this
    function gets called during module import in some places, and a
    hard failure on a malformed env value would crash the boot path
    rather than degrade gracefully.
    """
    raw = get_flag(new_name, *legacy_names, default=None)
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
    raw = get_flag(new_name, *legacy_names, default=None)
    if raw is None:
        return list(default or [])
    parts = [piece.strip() for piece in raw.split(separator)]
    return [piece for piece in parts if piece]
