"""Frozen registry of the 6 curated federated-MCP partners.

The single source of truth for partner data is
``data/federated_partners.json``. This module loads the JSON once at
import time, validates every row through :class:`PartnerMcp`, and
exposes the validated tuple via :class:`FederatedRegistry`.

Hard constraints (mirrored from ``feedback_federated_mcp_recommendation``)
------------------------------------------------------------------------
* Exactly 6 partners (freee / mf / notion / slack / github / linear).
* No self-reference — ``jpcite`` / ``jpintel`` are NEVER listed.
* No aggregator MCP endpoints — first-party only.
* No LLM API import.
* Idempotent — calling :func:`load_default_registry` repeatedly returns
  the same frozen instance (cached at module load).
"""

from __future__ import annotations

import json
import pathlib
from typing import Final

from jpintel_mcp.federated_mcp.models import PartnerMcp

#: Path to the canonical curated JSON. Resolved relative to the repo
#: root so the loader works regardless of CWD.
FEDERATED_PARTNERS_JSON: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[3] / "data" / "federated_partners.json"
)

#: Frozen tuple of partner_ids in their canonical (alphabetical) order.
#: Pinned for wire-shape regression tests; bumping requires a
#: coordinated update to ``data/federated_partners.json`` +
#: ``scripts/etl/seed_federated_mcp_partners.py``.
PARTNER_IDS: Final[tuple[str, ...]] = (
    "freee",
    "github",
    "linear",
    "mf",
    "notion",
    "slack",
)

#: Forbidden ``partner_id`` slugs. The federation is to peers — jpcite
#: must never appear in its own partner shortlist.
_FORBIDDEN_SELF_SLUGS: Final[frozenset[str]] = frozenset({"jpcite", "jpintel", "autonomath"})


class FederatedRegistry:
    """Read-only registry of the curated federated-MCP partner shortlist.

    Instances are constructed via :func:`load_default_registry` (which
    caches), or via :meth:`FederatedRegistry.from_partners` for tests
    that need a custom shortlist. There is no mutation API — partners
    are immutable for the lifetime of the registry.
    """

    __slots__ = ("_by_id", "_partners")

    def __init__(self, partners: tuple[PartnerMcp, ...]) -> None:
        """Validate + index the partner tuple.

        Raises
        ------
        ValueError
            If duplicate ``partner_id`` slugs are present, or if any
            slug is in :data:`_FORBIDDEN_SELF_SLUGS`.
        """
        seen: set[str] = set()
        for p in partners:
            if p.partner_id in seen:
                raise ValueError(f"duplicate partner_id: {p.partner_id}")
            if p.partner_id in _FORBIDDEN_SELF_SLUGS:
                raise ValueError(f"self-reference forbidden in federation: {p.partner_id}")
            seen.add(p.partner_id)
        self._partners: tuple[PartnerMcp, ...] = partners
        self._by_id: dict[str, PartnerMcp] = {p.partner_id: p for p in partners}

    @classmethod
    def from_partners(cls, partners: tuple[PartnerMcp, ...]) -> FederatedRegistry:
        """Build a registry from an in-memory partner tuple (tests only)."""
        return cls(partners)

    def __len__(self) -> int:
        return len(self._partners)

    def __iter__(self) -> object:
        return iter(self._partners)

    def __contains__(self, partner_id: object) -> bool:
        if not isinstance(partner_id, str):
            return False
        return partner_id in self._by_id

    @property
    def partners(self) -> tuple[PartnerMcp, ...]:
        """Canonical partner tuple (alphabetical by partner_id)."""
        return self._partners

    @property
    def partner_ids(self) -> tuple[str, ...]:
        """Tuple of partner_id slugs in canonical order."""
        return tuple(p.partner_id for p in self._partners)

    def get(self, partner_id: str) -> PartnerMcp | None:
        """Return the partner row for ``partner_id``, or None if absent."""
        return self._by_id.get(partner_id)

    def require(self, partner_id: str) -> PartnerMcp:
        """Return the partner row for ``partner_id``, raising on miss.

        Raises
        ------
        KeyError
            If ``partner_id`` is not registered.
        """
        try:
            return self._by_id[partner_id]
        except KeyError as exc:
            raise KeyError(f"partner_id not registered: {partner_id!r}") from exc


def _load_partners_from_json(path: pathlib.Path) -> tuple[PartnerMcp, ...]:
    """Load + validate every row from the curated JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    partners_raw = raw["partners"]
    if not isinstance(partners_raw, list):
        raise ValueError(
            f"federated_partners.json `partners` must be a list, got {type(partners_raw)!r}"
        )
    return tuple(PartnerMcp.model_validate(row) for row in partners_raw)


_CACHED_REGISTRY: FederatedRegistry | None = None


def load_default_registry() -> FederatedRegistry:
    """Return the cached registry built from :data:`FEDERATED_PARTNERS_JSON`.

    The registry is loaded on first call and cached. Subsequent calls
    return the same instance — partners are immutable and the JSON is
    a shipped fixture, so re-reading is wasted I/O.
    """
    global _CACHED_REGISTRY
    if _CACHED_REGISTRY is None:
        partners = _load_partners_from_json(FEDERATED_PARTNERS_JSON)
        _CACHED_REGISTRY = FederatedRegistry(partners)
    return _CACHED_REGISTRY


__all__ = [
    "FEDERATED_PARTNERS_JSON",
    "PARTNER_IDS",
    "FederatedRegistry",
    "load_default_registry",
]
