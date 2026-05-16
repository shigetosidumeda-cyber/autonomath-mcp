"""Pydantic models for the Wave 51 L4 predictive_merge_daily layer.

Three canonical envelopes:

* :class:`MergedPrediction` — a single predictive event that has been
  *time-corrected* against a dim Q snapshot. Carries the original event
  identity plus the resolved snapshot lineage so a downstream consumer
  can reproduce the time-axis correction without re-running the merge.
* :class:`MergePolicy` — pure declarative knob bundle controlling the
  merge (lookback window, staleness threshold, dataset → event-type
  routing). Pinned by tests so a future tuning change is intentional
  rather than silent.
* :class:`MergedDailyArtifact` — the full snapshot of one daily merge
  run: catalog version, ``run_id``, the merged predictions, plus the
  per-event-type counters that the AX Layer 6 cron emits as CW metrics.

The models follow the same strict-by-default contract used elsewhere in
``agent_runtime.contracts`` (``extra='forbid'`` + ``frozen=True``) so a
typo in an ETL / cron payload fails loudly at the boundary rather than
silently corrupting the merged artifact.

Non-goals
---------
* **No live HTTP.** This package never imports ``httpx`` / ``requests``
  / ``aiohttp``. The merge layer is pure metadata transformation;
  delivery is the L3 ``notification_fanout`` cron's concern.
* **No LLM inference.** No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk`` import. The merge is a
  deterministic join + time-axis correction, no inference, no
  embedding lookup.
* **No DB.** The event source is the dim K JSONL log; the snapshot
  source is the dim Q file-based registry. No SQLite handles cross this
  boundary.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Schema version of the merged-daily artifact. Bumped on shape changes.
MERGE_SCHEMA_VERSION: Literal["jpcite.predictive_merge_daily.v1"] = (
    "jpcite.predictive_merge_daily.v1"
)

#: Allowed dim K event types we merge over. Mirrors
#: :data:`jpintel_mcp.predictive_service.models.EventType` exactly so the
#: merge boundary stays narrow.
MergeEventType = Literal[
    "houjin_watch",
    "program_window",
    "amendment_diff",
]

#: Why one event was corrected against a snapshot vs. left as-is.
#: ``stale_corrected`` — the event was older than ``staleness_threshold``
#: and we attached the nearest snapshot ≤ ``scheduled_at``.
#: ``within_window`` — the event is within the freshness window, no
#: snapshot correction needed.
#: ``no_snapshot`` — eligible for correction but no snapshot existed for
#: the dataset (dataset never captured, or all snapshots are after the
#: event's ``scheduled_at``).
CorrectionReason = Literal[
    "stale_corrected",
    "within_window",
    "no_snapshot",
]

#: Regex for ``run_id`` — must be ``daily@<yyyy_mm_dd>`` so the cron
#: artifact directory derives directly from the id.
_RUN_ID_RE: re.Pattern[str] = re.compile(r"^daily@\d{4}_(0[1-9]|1[0-2])_([0-2]\d|3[01])$")


class _StrictModel(BaseModel):
    """Forbid extra fields and freeze attribute mutation by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MergePolicy(_StrictModel):
    """Declarative knob bundle for one merge run.

    The policy is pure data — the same policy + same inputs produces
    byte-identical output. Operator pins the policy at cron-config time
    so re-running yesterday's merge always produces yesterday's artifact.

    Attributes
    ----------
    lookback_hours:
        How far back from ``now`` to scan dim K events. Default 48h to
        catch the previous-day predictions plus a 1-day grace window
        (covers GHA runner clock skew + cron retry).
    staleness_threshold_hours:
        Events whose ``scheduled_at`` is more than this many hours in
        the future trigger a dim Q snapshot lookup so the prediction
        can be re-anchored to the historical regulatory state. Default
        24h matches the dim K KPI from the design doc.
    dataset_for_event_type:
        Mapping from :data:`MergeEventType` to the ``source_dataset_id``
        the merge should consult in the dim Q registry. Pure data, no
        runtime computation, so a future dataset rename is a one-line
        policy change.
    """

    lookback_hours: int = Field(ge=1, le=720, default=48)
    staleness_threshold_hours: int = Field(ge=1, le=168, default=24)
    dataset_for_event_type: dict[str, str] = Field(
        default_factory=lambda: {
            "houjin_watch": "houjin_master",
            "program_window": "programs",
            "amendment_diff": "am_amendment_snapshot",
        },
        description=(
            "Routing table from MergeEventType → dim Q "
            "source_dataset_id. Keys MUST be the literal "
            "MergeEventType strings."
        ),
    )

    @field_validator("dataset_for_event_type")
    @classmethod
    def _validate_routing_keys(cls, value: dict[str, str]) -> dict[str, str]:
        allowed: set[str] = {"houjin_watch", "program_window", "amendment_diff"}
        bad_keys = set(value) - allowed
        if bad_keys:
            raise ValueError(
                f"dataset_for_event_type contains unknown event types: "
                f"{sorted(bad_keys)}; allowed={sorted(allowed)}"
            )
        for ds in value.values():
            if not re.fullmatch(r"^[a-z0-9_]{1,40}$", ds):
                raise ValueError(
                    f"dataset id {ds!r} must be lowercase [a-z0-9_]+ "
                    "(max 40 chars), matching dim Q source_dataset_id contract"
                )
        return value


class MergedPrediction(_StrictModel):
    """One predictive event after dim Q time-axis correction.

    Pure transformation of a dim K :class:`PredictionEvent` — the
    original event is preserved verbatim via ``event_id`` /
    ``event_type`` / ``target_id`` / ``scheduled_at`` so a downstream
    auditor can re-fetch the dim K row by id and verify nothing was
    silently rewritten.

    The ``snapshot_id`` / ``snapshot_dataset_id`` / ``snapshot_as_of``
    triple is **only** populated when ``correction_reason ==
    'stale_corrected'``. For the other two reasons they remain
    ``None`` so a JSON consumer can branch on ``snapshot_id is None``
    without re-deriving freshness.
    """

    event_id: str = Field(min_length=1)
    event_type: MergeEventType
    target_id: str = Field(min_length=1)
    scheduled_at: str = Field(min_length=1)
    detected_at: str = Field(min_length=1)
    correction_reason: CorrectionReason
    snapshot_id: str | None = None
    snapshot_dataset_id: str | None = None
    snapshot_as_of: str | None = None
    horizon_hours: float = Field(
        description=(
            "scheduled_at - merge_run_at, in hours. May be negative "
            "(event already past — kept so the consumer can choose "
            "whether to drop or backfill)."
        ),
    )

    @model_validator(mode="after")
    def _snapshot_triple_consistency(self) -> MergedPrediction:
        """When stale_corrected, all 3 snapshot fields must be set."""
        triple = (
            self.snapshot_id,
            self.snapshot_dataset_id,
            self.snapshot_as_of,
        )
        if self.correction_reason == "stale_corrected":
            if any(v is None for v in triple):
                raise ValueError(
                    "stale_corrected requires snapshot_id + "
                    "snapshot_dataset_id + snapshot_as_of all set"
                )
        else:
            if any(v is not None for v in triple):
                raise ValueError(
                    f"correction_reason={self.correction_reason!r} "
                    "must have snapshot_id / snapshot_dataset_id / "
                    "snapshot_as_of all None"
                )
        return self


class MergedDailyArtifact(_StrictModel):
    """Full snapshot of one daily merge run.

    Returned by :func:`jpintel_mcp.predictive_merge.merge.run_daily_merge`.
    Consumers (cron writer, MCP wrapper, audit dump) read this single
    envelope rather than re-running the merge pipeline.
    """

    schema_version: Literal["jpcite.predictive_merge_daily.v1"] = MERGE_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    run_at: str = Field(min_length=1)
    policy: MergePolicy
    merged_count: int = Field(ge=0)
    merged_predictions: tuple[MergedPrediction, ...]
    counts_by_event_type: dict[str, int] = Field(
        description=(
            "Aggregate counts per MergeEventType. Keys are a subset of "
            "the MergeEventType literal so the CW metric emitter can "
            "fan-out one metric per key without re-derivation."
        ),
    )
    counts_by_correction_reason: dict[str, int] = Field(
        description=(
            "Aggregate counts per CorrectionReason. Sum equals merged_count by invariant."
        ),
    )

    @field_validator("run_id")
    @classmethod
    def _validate_run_id_shape(cls, value: str) -> str:
        if not _RUN_ID_RE.fullmatch(value):
            raise ValueError(
                f"run_id must match 'daily@<yyyy_mm_dd>' (e.g. 'daily@2026_05_17'); got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _counts_match(self) -> MergedDailyArtifact:
        if self.merged_count != len(self.merged_predictions):
            raise ValueError("merged_count must equal len(merged_predictions)")
        # Aggregate invariants: counts_by_correction_reason must sum to
        # merged_count (every prediction has exactly one reason);
        # counts_by_event_type likewise (every event has exactly one
        # event_type).
        if sum(self.counts_by_correction_reason.values()) != self.merged_count:
            raise ValueError("sum(counts_by_correction_reason) must equal merged_count")
        if sum(self.counts_by_event_type.values()) != self.merged_count:
            raise ValueError("sum(counts_by_event_type) must equal merged_count")
        allowed_reasons: set[str] = {
            "stale_corrected",
            "within_window",
            "no_snapshot",
        }
        bad_reasons = set(self.counts_by_correction_reason) - allowed_reasons
        if bad_reasons:
            raise ValueError(f"counts_by_correction_reason has unknown keys: {sorted(bad_reasons)}")
        allowed_types: set[str] = {
            "houjin_watch",
            "program_window",
            "amendment_diff",
        }
        bad_types = set(self.counts_by_event_type) - allowed_types
        if bad_types:
            raise ValueError(f"counts_by_event_type has unknown keys: {sorted(bad_types)}")
        return self


__all__ = [
    "MERGE_SCHEMA_VERSION",
    "CorrectionReason",
    "MergeEventType",
    "MergePolicy",
    "MergedDailyArtifact",
    "MergedPrediction",
]
