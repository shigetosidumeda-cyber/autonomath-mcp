"""Counterfactual JSON-level diff for Wave 51 dim Q.

The counterfactual layer compares two :class:`Snapshot` records and
emits a flat key-set summary:

* ``added``   — keys present in ``b.payload`` but not in ``a.payload``
* ``removed`` — keys present in ``a.payload`` but not in ``b.payload``
* ``changed`` — keys present in both with non-equal values
* ``unchanged`` — keys present in both with equal values

The diff is **structural / by top-level key** — deep recursion is out
of scope because the dim Q use case ("what would the answer have been
at YYYY-MM-DD?") only needs to surface "did the eligibility threshold
change between snapshot_a and snapshot_b?" at the top level. A future
deep-walk variant can wrap this primitive without changing the
return shape.

The returned :class:`DiffResult` is deterministic: every set is
returned as a sorted tuple so audit logs collapse cleanly. The
``content_hash_changed`` flag short-circuits "are the two snapshots
identical?" without re-walking the dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from jpintel_mcp.time_machine.models import Snapshot


class DiffResult(BaseModel):
    """JSON-level diff of two :class:`Snapshot` records.

    Attributes
    ----------
    snapshot_a_id:
        Source snapshot_id (the "before").
    snapshot_b_id:
        Target snapshot_id (the "after" / counterfactual variant).
    added:
        Keys present only in ``b.payload``. Sorted ascending.
    removed:
        Keys present only in ``a.payload``. Sorted ascending.
    changed:
        Keys present in both with differing values. Sorted ascending.
    unchanged:
        Keys present in both with equal values. Sorted ascending.
    content_hash_changed:
        ``True`` iff ``a.content_hash != b.content_hash``. Useful as a
        quick "are these identical?" probe before iterating the
        changed-key tuple.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_a_id: str = Field(min_length=1)
    snapshot_b_id: str = Field(min_length=1)
    added: tuple[str, ...] = Field(default_factory=tuple)
    removed: tuple[str, ...] = Field(default_factory=tuple)
    changed: tuple[str, ...] = Field(default_factory=tuple)
    unchanged: tuple[str, ...] = Field(default_factory=tuple)
    content_hash_changed: bool = False

    def is_identical(self) -> bool:
        """Return True iff the two snapshots are byte-identical.

        Convenience helper around :attr:`content_hash_changed` flipped.
        """
        return not self.content_hash_changed


def counterfactual_diff(
    snapshot_a: Snapshot,
    snapshot_b: Snapshot,
) -> DiffResult:
    """Return the structured top-level diff of two snapshots.

    Parameters
    ----------
    snapshot_a:
        "Before" / baseline snapshot.
    snapshot_b:
        "After" / counterfactual variant snapshot.

    Returns
    -------
    DiffResult
        Frozen Pydantic model — every set field is a sorted tuple so
        the result is fully deterministic for audit logging.

    Notes
    -----
    Top-level keys only. To compare a single nested dict (e.g.
    ``payload['eligibility']`` between two snapshots), the caller
    should pre-flatten or call this primitive on synthetic
    :class:`Snapshot` wrappers around the nested dict.
    """
    a_payload: dict[str, Any] = snapshot_a.payload
    b_payload: dict[str, Any] = snapshot_b.payload
    a_keys = set(a_payload.keys())
    b_keys = set(b_payload.keys())
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    common = a_keys & b_keys
    changed: list[str] = []
    unchanged: list[str] = []
    for key in sorted(common):
        if a_payload[key] != b_payload[key]:
            changed.append(key)
        else:
            unchanged.append(key)
    return DiffResult(
        snapshot_a_id=snapshot_a.snapshot_id,
        snapshot_b_id=snapshot_b.snapshot_id,
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        content_hash_changed=snapshot_a.content_hash != snapshot_b.content_hash,
    )


__all__ = ["DiffResult", "counterfactual_diff"]
