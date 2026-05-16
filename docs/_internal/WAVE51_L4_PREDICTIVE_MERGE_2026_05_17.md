# Wave 51 L4 — predictive_merge_daily module landed (2026-05-17)

Status: **LANDED — module green**
Lane: `[lane:solo]`
Wave: 51 L4 (second of five AX Layer 6 cron lanes; follows L3
`cross_outcome_routing` from sha 13937dce9)
Parent design: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md`
(`predictive_merge_daily` row)

## Scope

Land the second L3 / AX Layer 6 lane from `WAVE51_L3_L4_L5_DESIGN.md`:
**`predictive_merge_daily`** — a deterministic merger that takes the
Dim K predictive event log (`predictive_service`) and applies Dim Q
time-axis correction (`time_machine.query_as_of`) for stale predictions
beyond the freshness window, producing the 24h-ahead artifact the AX
Layer 6 cron emits at 02:00 JST.

This is the **router-agnostic substrate** landing only. The companion
AX Layer 6 cron (`scripts/cron/ax_layer_6_predictive_merge.py`) and its
`.github/workflows/ax-layer-6-predictive-merge-daily.yml` are separate
landings — this module is the input both will consume, exactly mirroring
the L3 substrate-first split.

## Files landed

| Path | Role |
|------|------|
| `src/jpintel_mcp/predictive_merge/__init__.py` | Public surface — re-exports 10 names |
| `src/jpintel_mcp/predictive_merge/models.py` | Pydantic envelopes: `MergedPrediction` / `MergePolicy` / `MergedDailyArtifact` (+ `MergeEventType` / `CorrectionReason` literal aliases) |
| `src/jpintel_mcp/predictive_merge/merge.py` | Merger (`classify_horizon` / `merge_event`) + facade (`run_daily_merge`) |
| `tests/test_predictive_merge.py` | 26 tests (>=15 mandated) covering classifier + merge paths + Pydantic guards + count invariants |

## Merge formula (canonical reference)

For every `PredictionEvent`::

    horizon_hours = (scheduled_at - run_at) / 3600
    if horizon_hours <= -lookback_hours:
        skip                                  # event past the lookback window
    elif horizon_hours <= staleness_threshold_hours:
        reason = "within_window"              # fresh, no snapshot needed
        snapshot_triple = None
    else:
        dataset = policy.dataset_for_event_type[event_type]
        result  = query_as_of(snapshot_registry, dataset, scheduled.date())
        if result.nearest is None:
            reason = "no_snapshot"
            snapshot_triple = None
        else:
            reason = "stale_corrected"
            snapshot_triple = (snap.snapshot_id,
                               snap.source_dataset_id,
                               snap.as_of_date.isoformat())

Defaults: `lookback_hours=48`, `staleness_threshold_hours=24`. The 24h
threshold matches the Dim K KPI from the design doc; the 48h lookback
gives the cron one extra day of grace for GHA runner clock skew and
cron retry. Both bounds are operator-tunable via `MergePolicy` (no
env-var; production misconfig cannot widen the policy silently).

### Default dataset routing (`MergePolicy.dataset_for_event_type`)

| `MergeEventType` | dim Q `source_dataset_id` |
|---|---|
| `houjin_watch` | `houjin_master` |
| `program_window` | `programs` |
| `amendment_diff` | `am_amendment_snapshot` |

Pure data; operator can override at construction time. Routing keys
are validated against the closed `MergeEventType` literal so a typo
fails at the Pydantic boundary.

## Correction-reason invariants

`MergedPrediction` enforces a snapshot-triple consistency contract via
`model_validator(mode='after')`:

* `correction_reason == 'stale_corrected'` → all 3 of `snapshot_id` /
  `snapshot_dataset_id` / `snapshot_as_of` MUST be set.
* Any other reason → all 3 MUST be `None`.

This means a downstream JSON consumer can branch on `snapshot_id is
None` without re-deriving freshness, and a corrupt row in the artifact
fails loudly at deserialisation rather than silently feeding the wrong
snapshot lineage into the audit trail.

## Smoke against a synthetic in-process registry

```text
run_at:                2026-05-17T02:00:00+00:00
run_id (derived):      daily@2026_05_17
schema_version:        jpcite.predictive_merge_daily.v1
policy.lookback_hours: 48
policy.staleness_threshold_hours: 24

4 input events:
  e_within     program_window scheduled +18h → within_window  (no snapshot)
  e_stale_ok   program_window scheduled +49h → stale_corrected (programs@2026_05, as_of 2026-05-16)
  e_stale_nodata houjin_watch scheduled +70h → no_snapshot (no dim Q row for houjin_master)
  e_past       program_window scheduled -49h → SKIPPED (outside lookback)

artifact merged_count: 3
counts_by_correction_reason: {stale_corrected: 1, within_window: 1, no_snapshot: 1}
counts_by_event_type:        {program_window: 2, houjin_watch: 1, amendment_diff: 0}
sum invariants: both dicts sum to merged_count (==3)
```

This is exactly the kind of "fresh + stale-corrected + missing-snapshot"
mix the AX Layer 6 cron will write daily, and that the L5 notification
fanout layer will use to schedule per-subscriber delivery within the
24h KPI.

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Module tests | `pytest tests/test_predictive_merge.py -q` | **26 passed in 0.69s** |
| mypy --strict | `mypy --strict src/jpintel_mcp/predictive_merge/` | **Success: no issues found in 3 source files** |
| ruff | `ruff check src/jpintel_mcp/predictive_merge/ tests/test_predictive_merge.py` | **All checks passed!** |
| ruff format | `ruff format src/jpintel_mcp/predictive_merge/ tests/test_predictive_merge.py` | **2 files reformatted, 2 left unchanged** |
| No-LLM invariant | `pytest tests/test_no_llm_in_production.py -q` | **10 passed in 28.20s** |

## Invariants enforced

1. **No LLM API import** — `anthropic` / `openai` / `google.generativeai`
   / `claude_agent_sdk` absent from the module tree. CI guard
   `tests/test_no_llm_in_production.py` continues to PASS (10/10).
2. **Pure deterministic** — `run_at` is a mandatory argument (no
   `datetime.now`), no random (`random.choice`), no I/O (HTTP / DB /
   socket). Identical inputs always produce byte-identical
   `MergedDailyArtifact` (gated by
   `test_run_daily_merge_byte_identical_repeat`).
3. **Pydantic strict-by-default** — `extra='forbid'` + `frozen=True`
   on every envelope. Snapshot-triple consistency + count-sum
   invariants enforced by `model_validator`. `run_id` shape +
   `dataset_for_event_type` routing keys + `MergeEventType` /
   `CorrectionReason` closed literals all field-validated.
4. **Append-only contract preserved** — the merge **never** mutates
   the dim K event log; it emits a derived `MergedPrediction` per
   surviving event. The upstream JSONL append-only contract from the
   dim K registry stays intact.
5. **¥3/req economics preserved** — pure CPU-bound Python set math +
   dim Q file read; no external paid API call, no LLM inference, no
   per-call cost beyond in-process ISO 8601 parsing and one
   filesystem `glob` per stale event. Fits the Wave 51 dim K-S
   "deterministic composition" pattern from
   `feedback_composable_tools_pattern.md`.

## Cross-reference

- Parent L3/L4/L5 design: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md`
- Wave 51 plan (§4.3 = L3 AX Layer 6 cron, this is lane 2 of 5):
  `docs/_internal/WAVE51_plan.md`
- L3 sibling lane: `docs/_internal/WAVE51_L3_CROSS_OUTCOME_ROUTING_2026_05_17.md`
- Wave 51 implementation roadmap (Day 8-14 = L3 range, Day 15-21 = L4
  range): `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md`
- Upstream Dim K source:
  `src/jpintel_mcp/predictive_service/` (`PredictionEvent` log)
- Upstream Dim Q source:
  `src/jpintel_mcp/time_machine/` (`query_as_of`)

## Next (not in this landing)

- `scripts/cron/ax_layer_6_predictive_merge.py` — daily 02:00 JST cron
  that calls `run_daily_merge()` and writes the
  `MergedDailyArtifact` to S3 + CW custom metrics for funnel
  observability (one metric per `MergeEventType` × `CorrectionReason`
  cell, 9 metrics per run).
- `.github/workflows/ax-layer-6-predictive-merge-daily.yml` — GHA
  scheduler binding (DISABLED default per Stream W concern separation
  convention).
- MCP wrapper tool `recommend_predictive_merge(subscriber_id)` that
  looks up the persisted artifact + intersects with the dim K
  subscriber's `watch_targets` and surfaces the merged predictions in
  the canonical `Evidence` envelope.
- The remaining 3 L3 cron lanes from `WAVE51_L3_L4_L5_DESIGN.md`:
  `notification_fanout` / `as_of_snapshot_5y` / `federated_partner_sync`.

## Lane marker

`[lane:solo]` — single-session land, no dual-CLI lane claim
(`feedback_dual_cli_lane_atomic.md` does not apply since this is a
single-author module + single-author test + single-author doc landing).

last_updated: 2026-05-17
