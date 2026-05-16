"""File-based snapshot registry for Wave 51 dim Q.

The registry persists :class:`Snapshot` records as JSON files under::

    <root>/<yyyy_mm>/<dataset>.json

It is **deliberately deterministic + filesystem-only** so the same
implementation runs across:

* production batch (``scripts/cron/snapshot_monthly_state.py`` writes,
  REST + MCP read),
* test runners (tmp_path fixture),
* offline operator scripts (auditing a customer claim about an
  ``as_of_date`` query result).

Retention is enforced by :meth:`SnapshotRegistry.prune_old_snapshots`,
not on every write — so a deploy that just crossed the 61st month does
not silently drop snapshots in the middle of an interactive query.
The prune emits a JSON-lines audit row per deleted snapshot via
``audit_emit`` callback so the deletion is never silent.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from jpintel_mcp.time_machine.models import Snapshot, SnapshotResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

#: 60 months (5 years) retention, per
#: ``feedback_time_machine_query_design`` "snapshot 期間: 5 年".
#: Override by passing ``retention_months`` to :meth:`prune_old_snapshots`
#: only — never via env-var so a production misconfig cannot widen the
#: retention silently.
RETENTION_MONTHS: Final[int] = 60


class SnapshotNotFoundError(LookupError):
    """Raised when a specific snapshot_id is requested but missing.

    Distinct from "no nearest match" — :func:`query_as_of` never raises
    on miss; it returns a :class:`SnapshotResult` with ``nearest=None``.
    This exception is only raised by direct ``get`` lookups.
    """


@dataclass(frozen=True, slots=True)
class PruneResult:
    """Outcome of :meth:`SnapshotRegistry.prune_old_snapshots`.

    Attributes
    ----------
    pruned_ids:
        Ordered list of snapshot_ids removed from disk. Ordered by the
        bucket they came from (oldest first) for stable audit
        comparison.
    retained_count:
        Number of snapshots that survived the prune (newest
        ``RETENTION_MONTHS`` buckets).
    audit_path:
        Path of the JSONL audit log the prune appended to, or ``None``
        when no ``audit_emit`` callback was passed.
    """

    pruned_ids: tuple[str, ...]
    retained_count: int
    audit_path: Path | None


def _bucket_to_sort_key(bucket: str) -> tuple[int, int]:
    """Convert ``'YYYY_MM'`` to ``(YYYY, MM)`` for ``sorted`` keys.

    Validated upstream by ``Snapshot._validate_snapshot_id``, so this
    helper trusts the regex. A malformed bucket reaching this function
    is a programmer error in the caller, not a user input.
    """
    yyyy_s, mm_s = bucket.split("_", 1)
    return (int(yyyy_s), int(mm_s))


class SnapshotRegistry:
    """File-based registry. One instance per ``root`` directory.

    Parameters
    ----------
    root:
        Directory under which the ``<yyyy_mm>/<dataset>.json`` tree
        lives. Created on first ``put`` if missing — never created by
        the constructor itself so an accidental wrong path does not
        silently litter the filesystem.

    Notes
    -----
    All write operations use ``os.replace`` to be atomic — a half-
    written snapshot file cannot exist on disk, so a concurrent
    reader either sees the old version or the new version.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    # -----------------------------------------------------------------
    # Path helpers
    # -----------------------------------------------------------------

    @property
    def root(self) -> Path:
        """Return the registry root path."""
        return self._root

    def _path_for(self, snapshot_id: str) -> Path:
        """Return the absolute file path for ``snapshot_id``.

        Does not check whether the file exists. Caller decides if a
        miss is an error (``get``) or a soft miss (``query_as_of``).
        """
        dataset, bucket = snapshot_id.split("@", 1)
        return self._root / bucket / f"{dataset}.json"

    # -----------------------------------------------------------------
    # Mutating ops
    # -----------------------------------------------------------------

    def put(self, snapshot: Snapshot) -> Path:
        """Persist ``snapshot`` to ``<root>/<yyyy_mm>/<dataset>.json``.

        Atomic via ``os.replace``. Re-deriving the ``content_hash`` is
        the caller's responsibility — this method writes the model
        verbatim. Use :meth:`Snapshot.compute_content_hash` before
        calling ``put`` if integrity matters at the call site.

        Returns
        -------
        Path
            The path that was written.
        """
        path = self._path_for(snapshot.snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        payload = snapshot.model_dump(mode="json")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
        return path

    # -----------------------------------------------------------------
    # Read ops
    # -----------------------------------------------------------------

    def get(self, snapshot_id: str) -> Snapshot:
        """Return the snapshot at ``snapshot_id``.

        Raises
        ------
        SnapshotNotFoundError
            If no file exists at the derived path.
        """
        path = self._path_for(snapshot_id)
        if not path.exists():
            raise SnapshotNotFoundError(
                f"snapshot_id={snapshot_id!r} not found under {self._root}"
            )
        return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list_for_dataset(self, dataset_id: str) -> list[Snapshot]:
        """Return every snapshot for ``dataset_id`` sorted by ``as_of_date``.

        Walks the registry root once per call. Cheap when there are
        ≤ ``RETENTION_MONTHS`` buckets; the dim Q use case never
        exceeds that.
        """
        if not self._root.exists():
            return []
        out: list[Snapshot] = []
        for bucket_dir in sorted(self._root.iterdir()):
            if not bucket_dir.is_dir():
                continue
            candidate = bucket_dir / f"{dataset_id}.json"
            if candidate.exists():
                out.append(
                    Snapshot.model_validate_json(
                        candidate.read_text(encoding="utf-8")
                    )
                )
        out.sort(key=lambda s: s.as_of_date)
        return out

    def list_buckets(self) -> list[str]:
        """Return every ``yyyy_mm`` bucket directory name, sorted asc."""
        if not self._root.exists():
            return []
        buckets = [
            d.name
            for d in self._root.iterdir()
            if d.is_dir() and len(d.name) == 7 and d.name[4] == "_"
        ]
        buckets.sort(key=_bucket_to_sort_key)
        return buckets

    # -----------------------------------------------------------------
    # Retention
    # -----------------------------------------------------------------

    def prune_old_snapshots(
        self,
        *,
        retention_months: int = RETENTION_MONTHS,
        audit_emit: Callable[[dict[str, object]], None] | None = None,
        audit_path: Path | str | None = None,
    ) -> PruneResult:
        """Delete buckets older than the ``retention_months`` newest.

        The prune is **bucket-granular**: the registry sorts the
        ``yyyy_mm`` directories ascending, keeps the newest
        ``retention_months``, and deletes every older bucket's
        contents (then the empty bucket directory).

        Parameters
        ----------
        retention_months:
            How many newest monthly buckets to keep. Must be ``>= 1``.
            Defaults to :data:`RETENTION_MONTHS` (60 == 5 years).
        audit_emit:
            Optional callable invoked once per deleted snapshot **before**
            the delete. Receives a dict with keys ``snapshot_id``,
            ``source_dataset_id``, ``as_of_date`` (ISO), ``bucket``.
            Use this to mirror the deletion into the production
            ``am_monthly_snapshot_log`` audit table.
        audit_path:
            Optional JSONL file path the prune **also** appends an audit
            row per deletion to. Caller-owned; the registry will create
            parent directories as needed.

        Returns
        -------
        PruneResult
            Pruned ids + retained count + the audit path actually
            written to (or ``None`` if no audit_path was given).
        """
        if retention_months < 1:
            raise ValueError(
                f"retention_months must be >= 1 (got {retention_months})"
            )
        buckets = self.list_buckets()
        if len(buckets) <= retention_months:
            return PruneResult(
                pruned_ids=(),
                retained_count=len(buckets),
                audit_path=None,
            )
        # Oldest buckets are prefix of sorted list; keep last
        # ``retention_months`` only.
        to_prune = buckets[: len(buckets) - retention_months]
        pruned_ids: list[str] = []
        audit_p = Path(audit_path) if audit_path is not None else None
        if audit_p is not None:
            audit_p.parent.mkdir(parents=True, exist_ok=True)
        for bucket in to_prune:
            bucket_dir = self._root / bucket
            for child in sorted(bucket_dir.iterdir()):
                if not child.is_file() or not child.name.endswith(".json"):
                    continue
                snap = Snapshot.model_validate_json(
                    child.read_text(encoding="utf-8")
                )
                event: dict[str, object] = {
                    "snapshot_id": snap.snapshot_id,
                    "source_dataset_id": snap.source_dataset_id,
                    "as_of_date": snap.as_of_date.isoformat(),
                    "bucket": bucket,
                }
                if audit_emit is not None:
                    audit_emit(event)
                if audit_p is not None:
                    with audit_p.open("a", encoding="utf-8") as fh:
                        fh.write(
                            json.dumps(event, ensure_ascii=False, sort_keys=True)
                            + "\n"
                        )
                pruned_ids.append(snap.snapshot_id)
                child.unlink()
            # Remove the (now empty) bucket directory. If anything
            # unexpected remains, leave the dir in place rather than
            # call ``shutil.rmtree`` — silent recursive delete is the
            # exact foot-gun we want to avoid for a retention layer.
            with contextlib.suppress(OSError):
                bucket_dir.rmdir()
        return PruneResult(
            pruned_ids=tuple(pruned_ids),
            retained_count=len(buckets) - len(to_prune),
            audit_path=audit_p,
        )


def query_as_of(
    registry: SnapshotRegistry,
    dataset_id: str,
    as_of_date: date,
) -> SnapshotResult:
    """Return the snapshot whose ``as_of_date`` is the **largest ≤** arg.

    Parameters
    ----------
    registry:
        The :class:`SnapshotRegistry` to query.
    dataset_id:
        Source dataset identifier (``'programs'`` etc).
    as_of_date:
        The target date. Calendar comparison only — time-of-day is
        irrelevant because snapshots are by-design daily-granularity.

    Returns
    -------
    SnapshotResult
        - On match: ``nearest`` is the snapshot, ``reason='ok'``.
        - When dataset has no snapshots at all: ``nearest=None``,
          ``reason='no_snapshots'``.
        - When all snapshots are strictly after ``as_of_date``:
          ``nearest=None``, ``reason='before_first_capture'``.
    """
    snaps = registry.list_for_dataset(dataset_id)
    if not snaps:
        return SnapshotResult(
            requested_as_of=as_of_date,
            nearest=None,
            reason="no_snapshots",
        )
    eligible = [s for s in snaps if s.as_of_date <= as_of_date]
    if not eligible:
        return SnapshotResult(
            requested_as_of=as_of_date,
            nearest=None,
            reason="before_first_capture",
        )
    # ``snaps`` is sorted ascending by as_of_date, so eligible[-1]
    # is the largest <= as_of_date.
    return SnapshotResult(
        requested_as_of=as_of_date,
        nearest=eligible[-1],
        reason="ok",
    )


__all__ = [
    "PruneResult",
    "RETENTION_MONTHS",
    "SnapshotNotFoundError",
    "SnapshotRegistry",
    "query_as_of",
]
