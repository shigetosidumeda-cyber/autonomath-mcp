"""Wave 51 L4 — predictive_merge_daily core (Dim K + Dim Q merge).

This module implements the **deterministic** daily merge that takes
:class:`PredictionEvent` rows from the dim K predictive registry and
applies dim Q ``query_as_of`` time-axis correction for predictions that
exceed the staleness threshold. The single public entry point is
:func:`run_daily_merge`.

Algorithmic contract
--------------------
* **Pure function.** ``run_daily_merge(...)`` is referentially transparent
  over its inputs (events + snapshots + policy + ``run_at``). Identical
  inputs → byte-identical :class:`MergedDailyArtifact`.
* **No clock / no random in core logic.** ``run_at`` is a mandatory
  argument so the caller controls the canonical wall-clock — eliminates
  GHA-runner-vs-Fly-machine clock skew flakiness.
* **No LLM, no DB, no HTTP.** Same hard constraints as the other Wave 51
  dim modules. Event source is the dim K JSONL; snapshot source is the
  dim Q file-based registry.

Merge formula
-------------
For each :class:`PredictionEvent`::

    horizon_hours = (scheduled_at - run_at) / 3600
    if horizon_hours <= -lookback_hours:
        skip  # event already past the lookback window
    elif horizon_hours <= staleness_threshold_hours:
        reason = "within_window"
        snapshot_triple = None
    else:
        dataset = policy.dataset_for_event_type[event_type]
        result = query_as_of(snapshot_registry, dataset, scheduled_date)
        if result.nearest is None:
            reason = "no_snapshot"
            snapshot_triple = None
        else:
            reason = "stale_corrected"
            snapshot_triple = (snap.snapshot_id, snap.source_dataset_id,
                               snap.as_of_date.isoformat())

The merge intentionally **does not** mutate the input event log — it
emits a derived :class:`MergedPrediction` per surviving event so the
upstream append-only contract stays intact.

Determinism notes
-----------------
* Event iteration order is preserved (dim K JSONL is append-only and
  read sequentially). Skipped events are dropped silently — they leave
  no row in the artifact so a downstream consumer that joins on
  ``event_id`` will simply find no match.
* When two events share the same ``scheduled_at`` and ``event_id``, the
  merge keeps the dim K read order. ``event_id`` uniqueness is the
  caller's contract (dim K design).

Public surface
--------------
    merge_event              — internal-grade helper, exported for diagnostics + tests.
    classify_horizon         — pure helper exposing the correction-reason logic.
    run_daily_merge          — single-call full snapshot facade.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from jpintel_mcp.predictive_merge.models import (
    CorrectionReason,
    MergedDailyArtifact,
    MergedPrediction,
    MergeEventType,
    MergePolicy,
)
from jpintel_mcp.predictive_service.models import PredictionEvent
from jpintel_mcp.time_machine.registry import SnapshotRegistry, query_as_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a UTC-aware ``datetime``.

    Mirrors the dim K helper exactly so two registries that disagree on
    timestamp format would both fail at the same boundary.
    """
    if not value:
        raise ValueError("ISO 8601 timestamp must be non-empty")
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"could not parse ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"ISO 8601 timestamp must be timezone-aware (got naive {value!r})"
        )
    return parsed.astimezone(UTC)


def classify_horizon(
    horizon_hours: float,
    *,
    lookback_hours: int,
    staleness_threshold_hours: int,
) -> str | None:
    """Return a classification tag for the event horizon.

    Returns one of:
    * ``'skip_past'`` — event is older than the lookback window; drop.
    * ``'within_window'`` — event is within the freshness window; no
      snapshot correction needed.
    * ``'stale_lookup'`` — event is beyond the staleness threshold; the
      caller should run ``query_as_of`` to resolve a snapshot.

    Pure function — no clock, no I/O. Exported so a test (or a future
    sensitivity sweep) can re-derive the classification with alternative
    thresholds.
    """
    if horizon_hours <= -float(lookback_hours):
        return "skip_past"
    if horizon_hours <= float(staleness_threshold_hours):
        return "within_window"
    return "stale_lookup"


def merge_event(
    event: PredictionEvent,
    *,
    run_at: datetime,
    policy: MergePolicy,
    snapshot_registry: SnapshotRegistry | None,
) -> MergedPrediction | None:
    """Merge one dim K event into a :class:`MergedPrediction` or skip.

    Returns ``None`` when the event is older than the policy lookback
    window. Otherwise returns a fully populated
    :class:`MergedPrediction` with the correction reason +
    snapshot triple already resolved.

    The function intentionally accepts ``snapshot_registry=None`` so
    callers in test or boot-time probe scenarios can run the merge
    without a snapshot tree (every ``stale_lookup`` collapses to
    ``no_snapshot``).
    """
    if run_at.tzinfo is None:
        raise ValueError("run_at= must be timezone-aware (UTC)")

    scheduled = _parse_iso_utc(event.scheduled_at)
    delta = scheduled - run_at
    horizon_hours = delta.total_seconds() / 3600.0

    tag = classify_horizon(
        horizon_hours,
        lookback_hours=policy.lookback_hours,
        staleness_threshold_hours=policy.staleness_threshold_hours,
    )
    if tag == "skip_past":
        return None

    reason: CorrectionReason
    snapshot_id: str | None = None
    snapshot_dataset_id: str | None = None
    snapshot_as_of: str | None = None

    if tag == "within_window":
        reason = "within_window"
    else:
        # tag == "stale_lookup" — run dim Q time-axis correction.
        dataset_id = policy.dataset_for_event_type.get(event.event_type)
        if dataset_id is None or snapshot_registry is None:
            reason = "no_snapshot"
        else:
            result = query_as_of(
                snapshot_registry,
                dataset_id,
                scheduled.date(),
            )
            if result.nearest is None:
                reason = "no_snapshot"
            else:
                reason = "stale_corrected"
                snapshot_id = result.nearest.snapshot_id
                snapshot_dataset_id = result.nearest.source_dataset_id
                snapshot_as_of = result.nearest.as_of_date.isoformat()

    # event.event_type is typed Literal["houjin_watch","program_window",
    # "amendment_diff"]; MergeEventType is the same Literal. We cast via
    # the type system because mypy --strict reads Literal type
    # equivalence as identical.
    typed_event_type: MergeEventType = event.event_type
    return MergedPrediction(
        event_id=event.event_id,
        event_type=typed_event_type,
        target_id=event.target_id,
        scheduled_at=event.scheduled_at,
        detected_at=event.detected_at,
        correction_reason=reason,
        snapshot_id=snapshot_id,
        snapshot_dataset_id=snapshot_dataset_id,
        snapshot_as_of=snapshot_as_of,
        horizon_hours=horizon_hours,
    )


def _derive_run_id(run_at: datetime) -> str:
    """Return the canonical ``daily@<yyyy_mm_dd>`` run id from ``run_at``.

    Always derives from the date portion of ``run_at`` (UTC) so a single
    run never spans two days in its id. Operator-overrideable via the
    explicit ``run_id=`` parameter on :func:`run_daily_merge`.
    """
    d = run_at.astimezone(UTC).date()
    return f"daily@{d.year:04d}_{d.month:02d}_{d.day:02d}"


def _aggregate(
    predictions: Sequence[MergedPrediction],
) -> tuple[dict[str, int], dict[str, int]]:
    """Build the two count-by-* dicts from a sequence of predictions.

    The dicts are populated even for keys that did not appear so the
    downstream CW metric emitter does not need to special-case
    missing-key absence. Keys that produced zero events are emitted with
    value 0.
    """
    counts_type: dict[str, int] = {
        "houjin_watch": 0,
        "program_window": 0,
        "amendment_diff": 0,
    }
    counts_reason: dict[str, int] = {
        "stale_corrected": 0,
        "within_window": 0,
        "no_snapshot": 0,
    }
    for p in predictions:
        counts_type[p.event_type] = counts_type.get(p.event_type, 0) + 1
        counts_reason[p.correction_reason] = (
            counts_reason.get(p.correction_reason, 0) + 1
        )
    return counts_type, counts_reason


def run_daily_merge(
    events: Iterable[PredictionEvent],
    *,
    run_at: datetime,
    policy: MergePolicy | None = None,
    snapshot_registry: SnapshotRegistry | None = None,
    run_id: str | None = None,
) -> MergedDailyArtifact:
    """Run the full daily merge and return a :class:`MergedDailyArtifact`.

    Parameters
    ----------
    events:
        Iterable of dim K :class:`PredictionEvent` rows. Typically the
        return of :func:`jpintel_mcp.predictive_service.read_events`,
        but tests should pass an in-memory list for isolation.
    run_at:
        Mandatory timezone-aware UTC wall-clock. The merge derives the
        run id from this and uses it as the horizon reference point.
    policy:
        Optional :class:`MergePolicy`. Defaults to the canonical
        production policy from the dim K + dim Q design (48h lookback,
        24h staleness threshold, dataset routing per design doc).
    snapshot_registry:
        Optional dim Q :class:`SnapshotRegistry`. When ``None``, every
        stale event collapses to ``no_snapshot`` — useful for boot-time
        smoke probes and tests that do not need the full snapshot tree.
    run_id:
        Optional override for the auto-derived ``daily@<yyyy_mm_dd>``.
        Validated via :class:`MergedDailyArtifact._validate_run_id_shape`.

    Returns
    -------
    MergedDailyArtifact
        Frozen snapshot of the run — same input → same artifact byte
        sequence (modulo Pydantic dump ordering, which is itself stable).

    Raises
    ------
    ValueError
        If ``run_at`` is naive, if ``policy.dataset_for_event_type``
        contains an unknown key, or if any ``run_id`` override does not
        match ``daily@<yyyy_mm_dd>``.
    """
    if run_at.tzinfo is None:
        raise ValueError("run_at= must be timezone-aware (UTC)")
    effective_policy = policy if policy is not None else MergePolicy()
    derived_run_id = run_id if run_id is not None else _derive_run_id(run_at)

    merged: list[MergedPrediction] = []
    for event in events:
        merged_one = merge_event(
            event,
            run_at=run_at,
            policy=effective_policy,
            snapshot_registry=snapshot_registry,
        )
        if merged_one is not None:
            merged.append(merged_one)

    counts_type, counts_reason = _aggregate(merged)

    return MergedDailyArtifact(
        run_id=derived_run_id,
        run_at=run_at.astimezone(UTC).isoformat(),
        policy=effective_policy,
        merged_count=len(merged),
        merged_predictions=tuple(merged),
        counts_by_event_type=counts_type,
        counts_by_correction_reason=counts_reason,
    )


__all__ = [
    "classify_horizon",
    "merge_event",
    "run_daily_merge",
]
