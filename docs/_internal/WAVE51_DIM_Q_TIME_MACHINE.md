# Wave 51 dim Q — Time-machine snapshot + counterfactual query

last_updated: 2026-05-16

## Why

`feedback_time_machine_query_design` (Wave 43 → Wave 51 dim Q) ratified the
"as_of + counterfactual" primitive: customers (税理士 / M&A advisor) routinely
need "過去申告の正当性検証" and "過去 M&A 当時の法令での判定" — i.e. answer
"what would the answer have been at YYYY-MM-DD?" against a frozen monthly
snapshot. The current jpcite corpus is current-state-only; Wave 51 dim Q
delivers the **reusable, router-agnostic** filesystem primitive that REST +
MCP + ETL + offline scripts can all share without re-deriving "find nearest
snapshot ≤ as_of" or "JSON-level diff of two snapshots" inline.

The companion SQLite-backed `am_monthly_snapshot_log` table + ETL ship
separately under DEEP-22 / migration 277 — this module is the storage +
diff + retention layer those layers compose on top of.

## What landed

| artifact | path |
| --- | --- |
| `Snapshot` Pydantic model + `compute_content_hash` | `src/jpintel_mcp/time_machine/models.py` |
| `SnapshotResult` query envelope | `src/jpintel_mcp/time_machine/models.py` |
| `SnapshotRegistry` (put / get / list / prune) | `src/jpintel_mcp/time_machine/registry.py` |
| `query_as_of(...)` nearest-≤ resolver | `src/jpintel_mcp/time_machine/registry.py` |
| `counterfactual_diff(...)` JSON-level diff | `src/jpintel_mcp/time_machine/diff.py` |
| `DiffResult` envelope (added/removed/changed/unchanged) | `src/jpintel_mcp/time_machine/diff.py` |
| `RETENTION_MONTHS = 60` (5 years) | `src/jpintel_mcp/time_machine/registry.py` |
| Sample snapshot generator | `scripts/etl/generate_dim_q_sample_snapshots.py` |
| 12 quarterly sample snapshots | `data/snapshots/sample/<yyyy_mm>/programs.json` |
| 35 unit tests | `tests/test_time_machine_module.py` |

## Storage layout

```
data/snapshots/<yyyy_mm>/<dataset>.json   # production batch root
data/snapshots/sample/<yyyy_mm>/<dataset>.json   # synthetic fixture root
```

`yyyy_mm` is the **snapshot bucket** (the month the snapshot was taken), not
the as_of_date. `<dataset>.json` is one file per source dataset; the
on-disk shape mirrors `Snapshot` exactly.

## Retention rule (60 months / 5 years)

`SnapshotRegistry.prune_old_snapshots()` is **explicitly called** (e.g. by
a monthly cron), never silent. It:

1. Lists buckets ascending.
2. Keeps the newest `retention_months` (default `RETENTION_MONTHS = 60`).
3. For each bucket marked for deletion:
   * loads the snapshot,
   * fires `audit_emit(event)` callback (one event per snapshot),
   * appends a JSON line to `audit_path` (if provided),
   * deletes the file,
4. Removes the (now empty) bucket directory.

A `retention_months < 1` raises `ValueError` to prevent accidental purge.

## Counterfactual diff approach

`counterfactual_diff(snapshot_a, snapshot_b) -> DiffResult` walks **top-level
keys only** of `payload`. The four return tuples (`added` / `removed` /
`changed` / `unchanged`) are sorted ascending for deterministic audit logs.
`content_hash_changed` short-circuits "are the two snapshots identical?"
without re-walking.

Deep walks (nested-dict diffs) are intentionally out of scope: the
税理士 / M&A use case only needs "did the eligibility threshold change?" at
the top level. A future deep-walk variant can wrap this primitive without
changing the public return shape.

## Non-goals (per memo)

- **No LLM API.** Snapshots are deterministic batch artifacts; re-deriving
  with an LLM is banned.
- **No SQLite dependency.** Filesystem-only storage. Bridging to the
  production `am_monthly_snapshot_log` table is the caller's responsibility.
- **No mutation of current-state tables.** Snapshots run in parallel with
  the live corpus.

## Quality gates

- `mypy --strict`: clean on the 4 module files + tests + ETL.
- `ruff check`: clean on the same surface.
- `pytest tests/test_time_machine_module.py`: 35 / 35 PASS.
- Sibling `tests/test_time_machine.py` (DEEP-22 SQLite layer) + `tests/test_dim_q_time_machine.py` (mig 277 ETL): 21 / 21 PASS (no regression).
