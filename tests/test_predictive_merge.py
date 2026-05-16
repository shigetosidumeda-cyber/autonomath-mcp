"""Wave 51 L4 — tests for the predictive_merge module.

Covers the router-agnostic primitives under
``src/jpintel_mcp/predictive_merge/``:

    * ``classify_horizon`` — boundary classification (skip_past /
      within_window / stale_lookup).
    * ``merge_event`` — single-event merge (within window / stale
      with snapshot / stale without snapshot / past = skip).
    * ``run_daily_merge`` — full snapshot, count invariants, dataset
      routing, default policy, derived run_id, empty input.
    * ``MergedPrediction`` — Pydantic snapshot-triple consistency guards.
    * ``MergePolicy`` — routing key validation guards.
    * ``MergedDailyArtifact`` — count + run_id shape validators.

Every test is deterministic: no clock, no random, no real catalog
dependency. The fixtures pin ``run_at`` to a known UTC instant so the
horizon math is byte-stable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from jpintel_mcp.predictive_merge import (
    MERGE_SCHEMA_VERSION,
    MergedDailyArtifact,
    MergedPrediction,
    MergePolicy,
    classify_horizon,
    merge_event,
    run_daily_merge,
)
from jpintel_mcp.predictive_service.models import PredictionEvent
from jpintel_mcp.time_machine.models import Snapshot
from jpintel_mcp.time_machine.registry import SnapshotRegistry

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures — pinned clock + builder helpers
# ---------------------------------------------------------------------------

#: Canonical run instant. All horizon math is relative to this UTC clock.
RUN_AT = datetime(2026, 5, 17, 2, 0, 0, tzinfo=UTC)


def _evt(
    *,
    event_id: str,
    event_type: str = "program_window",
    target_id: str = "program:test-grant",
    scheduled_at: str = "2026-05-17T12:00:00+00:00",
    detected_at: str = "2026-05-17T01:30:00+00:00",
    payload: dict[str, object] | None = None,
) -> PredictionEvent:
    """Build one valid PredictionEvent (dim K) for testing."""
    return PredictionEvent(
        event_id=event_id,
        event_type=event_type,  # type: ignore[arg-type]
        target_id=target_id,
        scheduled_at=scheduled_at,
        detected_at=detected_at,
        payload=payload or {},
    )


def _seed_snapshot_registry(
    tmp_path: Path,
    *,
    dataset_id: str,
    bucket: str,
    as_of: date,
) -> SnapshotRegistry:
    """Drop one minimal snapshot into a tmp registry and return it."""
    payload = {"rows": [{"id": 1, "name": "alpha"}]}
    snap = Snapshot(
        snapshot_id=f"{dataset_id}@{bucket}",
        as_of_date=as_of,
        source_dataset_id=dataset_id,
        content_hash=Snapshot.compute_content_hash(payload),
        payload=payload,
    )
    registry = SnapshotRegistry(root=tmp_path / "snapshots")
    registry.put(snap)
    return registry


# ---------------------------------------------------------------------------
# classify_horizon
# ---------------------------------------------------------------------------


def test_classify_horizon_skip_past_at_boundary() -> None:
    # exactly at -lookback_hours → skip_past (boundary is inclusive past).
    assert classify_horizon(-48.0, lookback_hours=48, staleness_threshold_hours=24) == "skip_past"


def test_classify_horizon_within_window_just_inside() -> None:
    # just inside the lookback (negative, but > -lookback_hours).
    assert (
        classify_horizon(-47.99, lookback_hours=48, staleness_threshold_hours=24) == "within_window"
    )


def test_classify_horizon_within_window_at_staleness_boundary() -> None:
    # exactly at staleness threshold → still within window (inclusive).
    assert (
        classify_horizon(24.0, lookback_hours=48, staleness_threshold_hours=24) == "within_window"
    )


def test_classify_horizon_stale_lookup_beyond_threshold() -> None:
    # one second past 24h → stale_lookup.
    assert (
        classify_horizon(24.001, lookback_hours=48, staleness_threshold_hours=24) == "stale_lookup"
    )


# ---------------------------------------------------------------------------
# merge_event
# ---------------------------------------------------------------------------


def test_merge_event_within_window_emits_no_snapshot_triple() -> None:
    event = _evt(event_id="evt_within", scheduled_at="2026-05-17T20:00:00+00:00")
    merged = merge_event(event, run_at=RUN_AT, policy=MergePolicy(), snapshot_registry=None)
    assert merged is not None
    assert merged.correction_reason == "within_window"
    assert merged.snapshot_id is None
    assert merged.snapshot_dataset_id is None
    assert merged.snapshot_as_of is None
    # horizon = 18 hours.
    assert merged.horizon_hours == pytest.approx(18.0)


def test_merge_event_past_returns_none() -> None:
    # 49h before run_at → outside the 48h lookback → skip.
    event = _evt(event_id="evt_past", scheduled_at="2026-05-15T01:00:00+00:00")
    merged = merge_event(event, run_at=RUN_AT, policy=MergePolicy(), snapshot_registry=None)
    assert merged is None


def test_merge_event_stale_no_registry_falls_back_to_no_snapshot() -> None:
    # 48h+1 in the future → stale_lookup; without a registry → no_snapshot.
    event = _evt(event_id="evt_stale_nosrc", scheduled_at="2026-05-19T03:00:00+00:00")
    merged = merge_event(event, run_at=RUN_AT, policy=MergePolicy(), snapshot_registry=None)
    assert merged is not None
    assert merged.correction_reason == "no_snapshot"
    assert merged.snapshot_id is None


def test_merge_event_stale_with_registry_attaches_snapshot(tmp_path: Path) -> None:
    registry = _seed_snapshot_registry(
        tmp_path,
        dataset_id="programs",
        bucket="2026_05",
        as_of=date(2026, 5, 18),
    )
    event = _evt(event_id="evt_stale", scheduled_at="2026-05-19T03:00:00+00:00")
    merged = merge_event(
        event,
        run_at=RUN_AT,
        policy=MergePolicy(),
        snapshot_registry=registry,
    )
    assert merged is not None
    assert merged.correction_reason == "stale_corrected"
    assert merged.snapshot_id == "programs@2026_05"
    assert merged.snapshot_dataset_id == "programs"
    assert merged.snapshot_as_of == "2026-05-18"


def test_merge_event_stale_dataset_unmapped_yields_no_snapshot(tmp_path: Path) -> None:
    # Custom policy intentionally drops the program_window routing.
    policy = MergePolicy(
        dataset_for_event_type={"houjin_watch": "houjin_master"},
    )
    registry = _seed_snapshot_registry(
        tmp_path, dataset_id="programs", bucket="2026_05", as_of=date(2026, 5, 18)
    )
    event = _evt(event_id="evt_unmapped", scheduled_at="2026-05-19T03:00:00+00:00")
    merged = merge_event(event, run_at=RUN_AT, policy=policy, snapshot_registry=registry)
    assert merged is not None
    assert merged.correction_reason == "no_snapshot"


def test_merge_event_naive_run_at_rejected() -> None:
    event = _evt(event_id="evt_naive")
    with pytest.raises(ValueError, match="timezone-aware"):
        merge_event(
            event,
            run_at=datetime(2026, 5, 17, 2, 0, 0),  # naive
            policy=MergePolicy(),
            snapshot_registry=None,
        )


# ---------------------------------------------------------------------------
# run_daily_merge — facade
# ---------------------------------------------------------------------------


def test_run_daily_merge_empty_input_zero_counts() -> None:
    artifact = run_daily_merge(events=[], run_at=RUN_AT)
    assert artifact.merged_count == 0
    assert artifact.merged_predictions == ()
    assert artifact.counts_by_event_type == {
        "houjin_watch": 0,
        "program_window": 0,
        "amendment_diff": 0,
    }
    assert artifact.counts_by_correction_reason == {
        "stale_corrected": 0,
        "within_window": 0,
        "no_snapshot": 0,
    }


def test_run_daily_merge_derives_run_id_from_run_at() -> None:
    artifact = run_daily_merge(events=[], run_at=RUN_AT)
    assert artifact.run_id == "daily@2026_05_17"
    assert artifact.run_at == "2026-05-17T02:00:00+00:00"
    assert artifact.schema_version == MERGE_SCHEMA_VERSION


def test_run_daily_merge_invariant_counts_match(tmp_path: Path) -> None:
    registry = _seed_snapshot_registry(
        tmp_path, dataset_id="programs", bucket="2026_05", as_of=date(2026, 5, 16)
    )
    events = [
        _evt(event_id="e_within", scheduled_at="2026-05-17T20:00:00+00:00"),
        _evt(
            event_id="e_stale_ok",
            event_type="program_window",
            scheduled_at="2026-05-19T03:00:00+00:00",
        ),
        _evt(
            event_id="e_stale_nodata",
            event_type="houjin_watch",
            target_id="houjin:1234567890123",
            scheduled_at="2026-05-20T00:00:00+00:00",
        ),
        _evt(event_id="e_past", scheduled_at="2026-05-15T01:00:00+00:00"),
    ]
    artifact = run_daily_merge(events=events, run_at=RUN_AT, snapshot_registry=registry)
    # 4 events in → e_past dropped → 3 in artifact.
    assert artifact.merged_count == 3
    by_reason = artifact.counts_by_correction_reason
    assert by_reason["within_window"] == 1
    assert by_reason["stale_corrected"] == 1
    assert by_reason["no_snapshot"] == 1
    by_type = artifact.counts_by_event_type
    assert by_type["program_window"] == 2
    assert by_type["houjin_watch"] == 1
    assert by_type["amendment_diff"] == 0
    # Invariant: counts sum to merged_count.
    assert sum(by_reason.values()) == artifact.merged_count
    assert sum(by_type.values()) == artifact.merged_count


def test_run_daily_merge_explicit_run_id_override() -> None:
    artifact = run_daily_merge(events=[], run_at=RUN_AT, run_id="daily@2026_05_17")
    assert artifact.run_id == "daily@2026_05_17"


def test_run_daily_merge_naive_run_at_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        run_daily_merge(events=[], run_at=datetime(2026, 5, 17))


def test_run_daily_merge_byte_identical_repeat() -> None:
    """Same inputs → same output JSON (determinism gate)."""
    events = [
        _evt(event_id="e1", scheduled_at="2026-05-17T20:00:00+00:00"),
        _evt(event_id="e2", scheduled_at="2026-05-17T22:00:00+00:00"),
    ]
    a = run_daily_merge(events=events, run_at=RUN_AT)
    b = run_daily_merge(events=events, run_at=RUN_AT)
    assert a.model_dump_json() == b.model_dump_json()


# ---------------------------------------------------------------------------
# MergedPrediction — Pydantic guards
# ---------------------------------------------------------------------------


def test_merged_prediction_stale_corrected_requires_snapshot_triple() -> None:
    with pytest.raises(ValidationError, match="stale_corrected requires"):
        MergedPrediction(
            event_id="x",
            event_type="program_window",
            target_id="program:x",
            scheduled_at="2026-05-19T03:00:00+00:00",
            detected_at="2026-05-17T01:30:00+00:00",
            correction_reason="stale_corrected",
            snapshot_id=None,
            snapshot_dataset_id=None,
            snapshot_as_of=None,
            horizon_hours=49.0,
        )


def test_merged_prediction_within_window_rejects_snapshot_triple() -> None:
    with pytest.raises(ValidationError, match="must have snapshot_id"):
        MergedPrediction(
            event_id="x",
            event_type="program_window",
            target_id="program:x",
            scheduled_at="2026-05-17T20:00:00+00:00",
            detected_at="2026-05-17T01:30:00+00:00",
            correction_reason="within_window",
            snapshot_id="programs@2026_05",
            snapshot_dataset_id="programs",
            snapshot_as_of="2026-05-16",
            horizon_hours=18.0,
        )


def test_merged_prediction_frozen_and_extra_forbidden() -> None:
    p = MergedPrediction(
        event_id="x",
        event_type="program_window",
        target_id="program:x",
        scheduled_at="2026-05-17T20:00:00+00:00",
        detected_at="2026-05-17T01:30:00+00:00",
        correction_reason="within_window",
        horizon_hours=18.0,
    )
    # frozen: setattr is forbidden.
    with pytest.raises(ValidationError):
        p.event_id = "y"  # type: ignore[misc]
    # extra='forbid' surfaces on construction.
    with pytest.raises(ValidationError):
        MergedPrediction(
            event_id="x",
            event_type="program_window",
            target_id="program:x",
            scheduled_at="2026-05-17T20:00:00+00:00",
            detected_at="2026-05-17T01:30:00+00:00",
            correction_reason="within_window",
            horizon_hours=18.0,
            unknown_extra="boom",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# MergePolicy — Pydantic guards
# ---------------------------------------------------------------------------


def test_merge_policy_rejects_unknown_routing_key() -> None:
    with pytest.raises(ValidationError, match="unknown event types"):
        MergePolicy(dataset_for_event_type={"unknown_type": "programs"})


def test_merge_policy_rejects_bad_dataset_id_shape() -> None:
    with pytest.raises(ValidationError, match="lowercase"):
        MergePolicy(dataset_for_event_type={"program_window": "Bad-Dataset!"})


def test_merge_policy_lookback_lower_bound() -> None:
    with pytest.raises(ValidationError):
        MergePolicy(lookback_hours=0)


def test_merge_policy_staleness_upper_bound() -> None:
    # 168h = 7d is the documented max; 169 must fail.
    with pytest.raises(ValidationError):
        MergePolicy(staleness_threshold_hours=169)


# ---------------------------------------------------------------------------
# MergedDailyArtifact — Pydantic guards
# ---------------------------------------------------------------------------


def test_merged_daily_artifact_rejects_bad_run_id_shape() -> None:
    with pytest.raises(ValidationError, match="run_id must match"):
        MergedDailyArtifact(
            run_id="not_a_daily_id",
            run_at="2026-05-17T02:00:00+00:00",
            policy=MergePolicy(),
            merged_count=0,
            merged_predictions=(),
            counts_by_event_type={
                "houjin_watch": 0,
                "program_window": 0,
                "amendment_diff": 0,
            },
            counts_by_correction_reason={
                "stale_corrected": 0,
                "within_window": 0,
                "no_snapshot": 0,
            },
        )


def test_merged_daily_artifact_count_invariant_fails_when_sum_mismatch() -> None:
    with pytest.raises(ValidationError, match="sum\\(counts_by_correction_reason\\)"):
        MergedDailyArtifact(
            run_id="daily@2026_05_17",
            run_at="2026-05-17T02:00:00+00:00",
            policy=MergePolicy(),
            merged_count=1,
            merged_predictions=(
                MergedPrediction(
                    event_id="x",
                    event_type="program_window",
                    target_id="program:x",
                    scheduled_at="2026-05-17T20:00:00+00:00",
                    detected_at="2026-05-17T01:30:00+00:00",
                    correction_reason="within_window",
                    horizon_hours=18.0,
                ),
            ),
            counts_by_event_type={
                "houjin_watch": 0,
                "program_window": 1,
                "amendment_diff": 0,
            },
            counts_by_correction_reason={
                "stale_corrected": 5,  # intentional mismatch
                "within_window": 0,
                "no_snapshot": 0,
            },
        )


def test_merged_daily_artifact_schema_version_pinned() -> None:
    artifact = run_daily_merge(events=[], run_at=RUN_AT)
    assert artifact.schema_version == "jpcite.predictive_merge_daily.v1"
    assert artifact.schema_version == MERGE_SCHEMA_VERSION
