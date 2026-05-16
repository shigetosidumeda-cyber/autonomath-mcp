"""Pydantic models for Wave 51 dim Q time-machine snapshots.

Every snapshot file under ``data/snapshots/<yyyy_mm>/<dataset>.json``
deserialises into exactly one :class:`Snapshot`. The model is frozen
and ``extra='forbid'`` so a typo at write time fails loudly at the
boundary rather than silently dropping a field that downstream
counterfactual diffs would later miss.

``content_hash`` is SHA-256 of the canonical-JSON-encoded
``payload`` dict and is computed by
:meth:`Snapshot.compute_content_hash` — never trust the caller's hash;
re-derive on load when integrity matters.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date  # noqa: TC003 — runtime presence required for Pydantic field type
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Regex for ``snapshot_id`` — must be ``<dataset>@<yyyy_mm>`` so the
#: registry can derive directory + file path from id alone.
_SNAPSHOT_ID_RE = re.compile(r"^[a-z0-9_]{1,40}@\d{4}_(0[1-9]|1[0-2])$")

#: Regex for ``yyyy_mm`` directory bucket — zero-padded month.
_YYYY_MM_RE = re.compile(r"^\d{4}_(0[1-9]|1[0-2])$")


class Snapshot(BaseModel):
    """A single point-in-time snapshot of one dataset.

    Attributes
    ----------
    snapshot_id:
        Canonical identifier ``<dataset>@<yyyy_mm>``. The dataset
        portion mirrors :attr:`source_dataset_id`; the ``yyyy_mm``
        portion mirrors the directory bucket (month the snapshot was
        taken). Enforced by regex so registry filename derivation is
        injective.
    as_of_date:
        ISO ``YYYY-MM-DD`` date the snapshot represents. Typically the
        last day of the bucket month, but the registry never assumes
        this — :func:`query_as_of` consults ``as_of_date`` directly.
    source_dataset_id:
        Stable identifier of the dataset (``programs`` / ``laws`` /
        ``tax_rulesets`` / ``court_decisions`` etc). Lowercase
        ``[a-z0-9_]+``; the regex check is folded into
        :attr:`snapshot_id` validation.
    content_hash:
        SHA-256 of the canonical-JSON-encoded ``payload``, lowercase
        hex, length 64. Recompute via :meth:`compute_content_hash`
        before trusting.
    payload:
        Deterministic dict captured at snapshot time. Counterfactual
        diffs walk this dict — keys MUST be JSON-safe (str / int /
        float / bool / list / dict). The ``extra='forbid'`` on the
        wrapping model does **not** propagate into ``payload`` since
        ``payload`` is a plain ``dict``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=80)
    as_of_date: date
    source_dataset_id: str = Field(min_length=1, max_length=40)
    content_hash: str = Field(min_length=64, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot_id(cls, v: str) -> str:
        if not _SNAPSHOT_ID_RE.fullmatch(v):
            raise ValueError(
                f"snapshot_id must match '<dataset>@<yyyy_mm>' "
                f"(e.g. 'programs@2024_03'); got {v!r}"
            )
        return v

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, v: str) -> str:
        if not re.fullmatch(r"^[0-9a-f]{64}$", v):
            raise ValueError(
                "content_hash must be 64-char lowercase hex SHA-256"
            )
        return v

    @field_validator("source_dataset_id")
    @classmethod
    def _validate_source_dataset_id(cls, v: str) -> str:
        if not re.fullmatch(r"^[a-z0-9_]{1,40}$", v):
            raise ValueError(
                "source_dataset_id must be lowercase [a-z0-9_]+ (max 40 chars)"
            )
        return v

    @staticmethod
    def compute_content_hash(payload: dict[str, Any]) -> str:
        """Return the canonical SHA-256 hex digest of ``payload``.

        The canonical encoding is ``json.dumps(payload, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"))``. Sorted keys make
        the hash stable across Python dict insertion order; the
        separators eliminate cosmetic whitespace; ``ensure_ascii=False``
        preserves the original Japanese byte sequence so two semantically
        identical payloads collapse to one digest.
        """
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def bucket(self) -> str:
        """Return the ``yyyy_mm`` directory bucket portion of the id."""
        return self.snapshot_id.split("@", 1)[1]


class SnapshotResult(BaseModel):
    """Return shape of :func:`query_as_of`.

    The model carries the resolved :class:`Snapshot` plus the structured
    reason the resolver picked it. Both ``nearest`` and ``reason`` are
    set on success; on miss, ``nearest`` is ``None`` and ``reason`` is
    one of ``'no_snapshots'`` / ``'before_first_capture'``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_as_of: date
    nearest: Snapshot | None
    reason: str = Field(min_length=1, max_length=80)


__all__ = [
    "Snapshot",
    "SnapshotResult",
]
