"""Lazy proxy for the stripe SDK (PERF-41).

Importing the real ``stripe`` package eagerly costs ~356 ms cumulative
(``stripe._stripe_client`` + ``stripe._v1_services`` cascade) which is the
single largest external-SDK contributor to ``autonomath-api`` cold start.

The Stripe SDK is only needed when an endpoint actually processes a
billing request, never at app initialization or middleware wiring.  This
module exposes a lazy attribute proxy: the real ``stripe`` package is
imported on first attribute access and cached, so every subsequent
access is the regular module-attribute hot path.

Usage at call sites::

    from jpintel_mcp._lazy_stripe import stripe

    def handler(...):
        stripe.api_key = settings.stripe_secret_key  # real import happens here
        customer = stripe.Customer.retrieve(...)

The proxy preserves the exact ``stripe.XXX`` call shape used across the
4 API routers + 2 billing helpers, so swapping the top-level
``import stripe`` for ``from jpintel_mcp._lazy_stripe import stripe`` is
a drop-in replacement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - mypy/IDE only, never executed
    import stripe as _stripe_module  # noqa: F401


class _LazyStripe:
    """Module-level proxy that defers ``import stripe`` until first use."""

    __slots__ = ("_module",)

    def __init__(self) -> None:
        object.__setattr__(self, "_module", None)

    def _load(self) -> Any:
        mod = object.__getattribute__(self, "_module")
        if mod is None:
            import stripe as _stripe  # noqa: PLC0415 - intentional lazy import

            mod = _stripe
            object.__setattr__(self, "_module", mod)
        return mod

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._load(), name, value)


stripe: Any = _LazyStripe()

__all__ = ["stripe"]
