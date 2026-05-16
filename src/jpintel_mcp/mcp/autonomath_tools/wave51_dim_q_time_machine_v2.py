"""Wave 51 dim Q — Time-machine v2 MCP wrappers.

Two new MCP tools that expose the **file-backed** snapshot registry +
counterfactual diff primitives in
``jpintel_mcp.time_machine`` (Wave 51 dim Q). These are distinct from
``time_machine_tools.py``'s DEEP-22 ``query_at_snapshot_v2`` /
``query_program_evolution`` pair which read from
``am_amendment_snapshot``. The dim Q variants read deterministic monthly
JSON snapshots from ``data/snapshots/<yyyy_mm>/<dataset>.json`` so an
audit walker can ask "what would the answer have been at YYYY-MM-DD?"
without trusting the live current-state corpus.

Hard constraints (CLAUDE.md):

* NO LLM call. Pure filesystem + Python deterministic logic.
* 1 ¥3/billable unit per tool call (single billing event).
* 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 / 公認会計士法 §47条の2
  non-substitution disclaimer envelope.
* MCP tool registration is import-time side-effect; safe with FastMCP
  deferred tool list snapshot.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.time_machine import (
    SnapshotNotFoundError,
    SnapshotRegistry,
    counterfactual_diff,
    query_as_of,
)

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_dim_q_time_machine_v2")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_DIM_Q_V2_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_DISCLAIMER = (
    "本 response は data/snapshots/<yyyy_mm>/<dataset>.json に格納された "
    "monthly point-in-time JSON snapshot からの事実検索結果です。採択予測ではなく、"
    "申告 / M&A DD の正当性検証用に過去時点の制度状態を deterministic に再生するもの。"
    "税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / 行政書士法 §1 の代替ではありません。"
)


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshots_root() -> Path:
    """Resolve the snapshot registry root from env / default."""
    override = os.environ.get("AUTONOMATH_SNAPSHOTS_ROOT")
    if override:
        return Path(override)
    # Repo-root default — src/jpintel_mcp/.. -> ../../.. -> repo root.
    return Path(__file__).resolve().parents[4] / "data" / "snapshots"


def _build_outcome_contract(name: str, display: str) -> OutcomeContract:
    return OutcomeContract(
        outcome_contract_id=f"dim_q_v2_{name}",
        display_name=display,
        packet_ids=(f"packet_dim_q_v2_{name}",),
        billable=True,
    )


def _build_evidence(
    name: str,
    *,
    support_state: str,
    receipt_id: str,
    temporal_envelope: str,
) -> Evidence:
    evidence_type = "absence_observation" if support_state == "absent" else "structured_record"
    return Evidence(
        evidence_id=f"dim_q_v2_{name}_evidence",
        claim_ref_ids=(f"dim_q_v2_{name}_claim",),
        receipt_ids=(receipt_id,),
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=temporal_envelope,
        observed_at=_today_iso_utc(),
    )


def _wrap_envelope(
    *,
    tool_name: str,
    primary_result: dict[str, Any],
    support_state: str,
    receipt_id: str,
    temporal_envelope: str,
    citations: list[dict[str, Any]] | None = None,
    display_name: str,
) -> dict[str, Any]:
    evidence = _build_evidence(
        tool_name,
        support_state=support_state,
        receipt_id=receipt_id,
        temporal_envelope=temporal_envelope,
    )
    outcome = _build_outcome_contract(tool_name, display_name)
    return {
        "tool_name": tool_name,
        "schema_version": "wave51.dim_q.v1",
        "primary_result": primary_result,
        "evidence": evidence.model_dump(mode="json"),
        "outcome_contract": outcome.model_dump(mode="json"),
        "citations": list(citations or []),
        "results": [],
        "total": 0 if support_state == "absent" else 1,
        "limit": 1,
        "offset": 0,
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }


def _validate_iso_date(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value)


def _query_snapshot_as_of_v2_impl(
    dataset_id: str,
    as_of: str,
) -> dict[str, Any]:
    """Return the snapshot whose ``as_of_date`` is the largest ≤ as_of."""
    if not dataset_id or not dataset_id.strip():
        return make_error(
            code="missing_required_arg",
            message="dataset_id is required.",
            field="dataset_id",
            hint="Pass a dataset id like 'programs' / 'laws' / 'tax_rulesets'.",
        )

    try:
        as_of_date = _validate_iso_date(as_of)
    except (TypeError, ValueError) as exc:
        return make_error(
            code="invalid_date_format",
            message=f"as_of must be ISO YYYY-MM-DD ({exc}).",
            field="as_of",
            hint="Pass a string like '2024-06-01'.",
        )

    root = _snapshots_root()
    try:
        registry = SnapshotRegistry(root)
    except Exception as exc:  # pragma: no cover - filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"snapshot registry init failed: {exc}",
        )

    result = query_as_of(registry, dataset_id, as_of_date)

    if result.nearest is None:
        primary: dict[str, Any] = {
            "dataset_id": dataset_id,
            "requested_as_of": as_of_date.isoformat(),
            "snapshot": None,
            "reason": result.reason,
        }
        return _wrap_envelope(
            tool_name="query_snapshot_as_of_v2",
            primary_result=primary,
            support_state="absent",
            receipt_id=f"dim_q_v2_snapshot_{dataset_id}_{as_of_date.isoformat()}_miss",
            temporal_envelope=f"{as_of_date.isoformat()}/observed",
            display_name="Wave 51 dim Q — query snapshot as_of (v2, filesystem)",
        )

    snap = result.nearest
    primary = {
        "dataset_id": dataset_id,
        "requested_as_of": as_of_date.isoformat(),
        "snapshot": {
            "snapshot_id": snap.snapshot_id,
            "as_of_date": snap.as_of_date.isoformat(),
            "source_dataset_id": snap.source_dataset_id,
            "content_hash": snap.content_hash,
            "payload_keys": sorted(snap.payload.keys()),
        },
        "reason": result.reason,
    }
    return _wrap_envelope(
        tool_name="query_snapshot_as_of_v2",
        primary_result=primary,
        support_state="supported",
        receipt_id=f"dim_q_v2_snapshot_{snap.snapshot_id}",
        temporal_envelope=f"{snap.as_of_date.isoformat()}/observed",
        display_name="Wave 51 dim Q — query snapshot as_of (v2, filesystem)",
    )


def _counterfactual_diff_v2_impl(
    dataset_id: str,
    as_of_a: str,
    as_of_b: str,
) -> dict[str, Any]:
    """Run a top-level JSON-key diff of two as_of snapshots."""
    if not dataset_id or not dataset_id.strip():
        return make_error(
            code="missing_required_arg",
            message="dataset_id is required.",
            field="dataset_id",
        )
    try:
        date_a = _validate_iso_date(as_of_a)
        date_b = _validate_iso_date(as_of_b)
    except (TypeError, ValueError) as exc:
        return make_error(
            code="invalid_date_format",
            message=f"as_of_a / as_of_b must be ISO YYYY-MM-DD ({exc}).",
            field="as_of_a",
            hint="Pass strings like '2024-06-01'.",
        )

    root = _snapshots_root()
    try:
        registry = SnapshotRegistry(root)
    except Exception as exc:  # pragma: no cover - filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"snapshot registry init failed: {exc}",
        )

    result_a = query_as_of(registry, dataset_id, date_a)
    result_b = query_as_of(registry, dataset_id, date_b)

    if result_a.nearest is None or result_b.nearest is None:
        missing = []
        if result_a.nearest is None:
            missing.append(f"a={date_a.isoformat()}({result_a.reason})")
        if result_b.nearest is None:
            missing.append(f"b={date_b.isoformat()}({result_b.reason})")
        primary: dict[str, Any] = {
            "dataset_id": dataset_id,
            "as_of_a": date_a.isoformat(),
            "as_of_b": date_b.isoformat(),
            "diff": None,
            "missing_snapshots": missing,
        }
        return _wrap_envelope(
            tool_name="counterfactual_diff_v2",
            primary_result=primary,
            support_state="absent",
            receipt_id=f"dim_q_v2_diff_{dataset_id}_miss",
            temporal_envelope=f"{date_a.isoformat()}/{date_b.isoformat()}",
            display_name="Wave 51 dim Q — counterfactual diff (v2, filesystem)",
        )

    try:
        diff = counterfactual_diff(result_a.nearest, result_b.nearest)
    except SnapshotNotFoundError as exc:  # pragma: no cover - bounds guard
        return make_error(
            code="seed_not_found",
            message=f"snapshot resolution failed: {exc}",
        )

    primary = {
        "dataset_id": dataset_id,
        "as_of_a": date_a.isoformat(),
        "as_of_b": date_b.isoformat(),
        "snapshot_a_id": diff.snapshot_a_id,
        "snapshot_b_id": diff.snapshot_b_id,
        "added": list(diff.added),
        "removed": list(diff.removed),
        "changed": list(diff.changed),
        "unchanged": list(diff.unchanged),
        "content_hash_changed": diff.content_hash_changed,
    }
    return _wrap_envelope(
        tool_name="counterfactual_diff_v2",
        primary_result=primary,
        support_state="supported",
        receipt_id=f"dim_q_v2_diff_{diff.snapshot_a_id}_to_{diff.snapshot_b_id}",
        temporal_envelope=f"{date_a.isoformat()}/{date_b.isoformat()}",
        display_name="Wave 51 dim Q — counterfactual diff (v2, filesystem)",
    )


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def query_snapshot_as_of_v2(
        dataset_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description=(
                    "Dataset id (lowercase ascii). Example: 'programs', "
                    "'laws', 'tax_rulesets'. Maps to "
                    "data/snapshots/<yyyy_mm>/<dataset_id>.json."
                ),
            ),
        ],
        as_of: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description=(
                    "Snapshot pivot, ISO YYYY-MM-DD. Returns the snapshot "
                    "whose as_of_date is the largest <= this value."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim Q v2. Returns the file-backed monthly snapshot whose as_of_date is the largest <= the requested date. Reads data/snapshots/<yyyy_mm>/<dataset>.json (filesystem registry, 60-month retention). Returns content_hash + payload_keys + reason. Companion to (not replacement of) DEEP-22 query_at_snapshot_v2 which reads am_amendment_snapshot. NO LLM, single ¥3 unit."""
        return _query_snapshot_as_of_v2_impl(dataset_id=dataset_id, as_of=as_of)

    @mcp.tool(annotations=_READ_ONLY)
    def counterfactual_diff_v2(
        dataset_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description="Dataset id (lowercase ascii). Example: 'programs'.",
            ),
        ],
        as_of_a: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description="Baseline 'before' date, ISO YYYY-MM-DD.",
            ),
        ],
        as_of_b: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description="Counterfactual 'after' date, ISO YYYY-MM-DD.",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim Q v2 counterfactual. Resolves the file-backed monthly snapshots at as_of_a and as_of_b for the dataset, then returns the top-level JSON-key diff (added / removed / changed / unchanged + content_hash_changed flag). Deterministic — no LLM hop, sorted key sets. Surfaces missing_snapshots when either side has no nearest match. Single ¥3 unit."""
        return _counterfactual_diff_v2_impl(
            dataset_id=dataset_id,
            as_of_a=as_of_a,
            as_of_b=as_of_b,
        )


__all__ = [
    "_counterfactual_diff_v2_impl",
    "_query_snapshot_as_of_v2_impl",
]
