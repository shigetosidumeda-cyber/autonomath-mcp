"""Wave 51 dim Q — Time-machine snapshot + counterfactual query primitives.

This package is the **reusable, router-agnostic** core for the dim Q
"as_of + counterfactual" layer described in
``feedback_time_machine_query_design``:

    * Customer (税理士 / M&A advisor) routinely needs to answer
      "過去申告の正当性検証" and "過去 M&A 当時の法令での判定" — i.e.
      "what would the answer have been at YYYY-MM-DD?".
    * Current jpcite serves **current state only**. Bolting on
      ``as_of=YYYY-MM-DD`` query support + a deterministic monthly
      snapshot chain + a counterfactual diff layer is the **only** way to
      satisfy those workflows without re-running an LLM over the
      historical corpus (which would be slow, expensive, and
      non-deterministic).
    * Snapshots are deterministic, file-based, append-only, and retained
      for 60 months (5 years). Older snapshots are pruned by an explicit
      ``prune_old_snapshots()`` call that writes an audit row before the
      delete — never silent.

The companion REST surface (``api/time_machine.py``) and MCP wrapper
(``mcp/autonomath_tools/time_machine_tools.py``) call into the
primitives here. Keeping the storage + diff + retention logic in this
package means each call site reuses one verified implementation rather
than re-deriving "find nearest snapshot ≤ as_of" or "JSON-level diff
of two snapshots" inline.

Storage layout
--------------
The :class:`SnapshotRegistry` reads + writes JSON files under::

    data/snapshots/<yyyy_mm>/<dataset>.json

The ``yyyy_mm`` directory name is the *snapshot bucket* (the month the
snapshot was taken), not the as_of date. ``<dataset>.json`` is one
file per source dataset; multiple datasets can coexist in the same
month. The on-disk shape mirrors :class:`Snapshot` exactly so an
operator can ``cat`` a file and read every field.

Non-goals
---------
* Does **not** call any LLM API or external HTTP endpoint. Snapshots
  are deterministic batch artifacts — re-deriving with an LLM is
  banned by ``feedback_time_machine_query_design``.
* Does **not** depend on SQLite. Storage is **filesystem only** —
  caller responsibility to bridge to the production
  ``am_monthly_snapshot_log`` table if needed.
* Does **not** mutate the *current* state tables. Snapshots run in
  parallel with the live current-state corpus.

Public surface
--------------
    Snapshot                — Pydantic model for one snapshot row.
    SnapshotRegistry        — File-based registry with put/get/list/prune.
    SnapshotResult          — Return type of :func:`query_as_of`.
    DiffResult              — Return type of :func:`counterfactual_diff`.
    PruneResult             — Return type of :func:`SnapshotRegistry.prune_old_snapshots`.
    query_as_of(...)        — Find nearest snapshot ≤ as_of_date.
    counterfactual_diff(...)— JSON-level diff of two snapshots.

Constants
---------
    RETENTION_MONTHS        — 60 (== 5 years). Module constant.
"""

from __future__ import annotations

from jpintel_mcp.time_machine.diff import DiffResult, counterfactual_diff
from jpintel_mcp.time_machine.models import Snapshot, SnapshotResult
from jpintel_mcp.time_machine.registry import (
    RETENTION_MONTHS,
    PruneResult,
    SnapshotNotFoundError,
    SnapshotRegistry,
    query_as_of,
)

__all__ = [
    "RETENTION_MONTHS",
    "DiffResult",
    "PruneResult",
    "Snapshot",
    "SnapshotNotFoundError",
    "SnapshotRegistry",
    "SnapshotResult",
    "counterfactual_diff",
    "query_as_of",
]
