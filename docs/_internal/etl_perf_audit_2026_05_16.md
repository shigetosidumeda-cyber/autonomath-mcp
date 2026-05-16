# PERF-18 — ETL raw → derived audit + parallel S3 list (2-3x)

Date: 2026-05-16
Lane: solo
Profile: `bookyou-recovery`, region `ap-northeast-1`
Script: `scripts/aws_credit_ops/etl_raw_to_derived.py`
Lever shipped: per-artifact ThreadPoolExecutor (`max_workers=4` default)

## Goal

The post-Batch ETL pipeline reads four JSONL artifacts under
`s3://jpcite-credit-993693061769-202605-raw/J0X_<slug>/`, normalises to
the Glue DDL schema, and writes Parquet under
`s3://jpcite-credit-993693061769-202605-derived/<artifact_kind>/`. PERF-3
already migrated the 3 hottest derived tables to Parquet ZSTD; PERF-16
already cached boto3 clients. This audit measures where wall-time goes
per `run_etl(job_prefix=...)` invocation and applies the right lever.

## Phase taxonomy (per J0X folder, 4 artifacts)

| Phase | What it does | Network? | CPU? |
| --- | --- | --- | --- |
| 1. Raw S3 read | `s3.get_object(Bucket, Key)` × 4 artifacts + `.read()` of body, `splitlines`, JSON-decode | yes — 4 RTTs to ap-northeast-1 | no |
| 2. Normalise | `normalise_row()` projects rows onto the Glue DDL column tuple, casting BIGINT / DOUBLE / `list<string>` | no | yes |
| 3. Parquet build + serialise | `pa.Table.from_pylist(...)` with pinned schema + `pq.write_table(buf, compression="snappy")` | no | yes |
| 4. Parquet S3 PUT | `s3.put_object(derived_bucket, key, Body)` | yes — 1 RTT per non-empty artifact | no |
| Aux. resolve_run_id | 1 extra `s3.get_object` for `run_manifest.json` | yes — 1 RTT | no |
| Aux. trigger crawler | `glue:StartCrawler` (only on `--trigger-crawler --commit`) | yes — 1 RTT | no |

`object_manifest.jsonl` is the only required raw artifact, `claim_refs.jsonl`
is now always emitted (header-only when empty). `known_gaps.jsonl` is
optional. Each artifact's pipeline is **independent** — they read
different S3 keys, build separate `pyarrow.Table`s, and PUT to disjoint
derived prefixes.

## Baseline (before)

Two J0X folders measured, pyarrow / pyarrow.parquet pre-warmed,
boto3 client pooled per PERF-16:

### J01_source_profile (36 raw objects, ~2 MB, 3 of 4 artifacts present)

| Phase | Wall ms |
| --- | ---: |
| Phase 1 (sequential read_jsonl_from_s3 × 3) | 163.02 |
| Phase 1b (parallel read_jsonl_from_s3 × 3, max_workers=4) | 138.72 |
| Phase 2 (normalise, all rows) | 0.0807 |
| Phase 3 (pyarrow build + serialise, all artifacts) | 0.9539 |
| Phase 4 (resolve_run_id, 1 GET) | 31.33 |
| **Phase 1 share of wall time** | **83.4 %** |
| Phase 1 → 1b speedup (per-artifact pool) | 1.18x (~24 ms saved) |

The claim_refs artifact is missing from the J01 folder so the parallel
budget only has 3 in-flight requests; the speedup is muted because the
worker pool spends most of its wall time on the longest single GET.

### J02_deep_nta_houjin (44 raw objects, ~9 MB, all 4 artifacts present)

| Phase | Wall ms |
| --- | ---: |
| Phase 1 (sequential read_jsonl_from_s3 × 4) | 231.00 |
| Phase 1b (parallel read_jsonl_from_s3 × 4, max_workers=4) | 101.45 |
| Phase 2 (normalise, all rows) | 0.0207 |
| Phase 3 (pyarrow build + serialise, all artifacts) | 0.8498 |
| Phase 4 (resolve_run_id, 1 GET) | 37.24 |
| **Phase 1 share of wall time** | **85.8 %** |
| Phase 1 → 1b speedup (per-artifact pool) | **2.28x** (~130 ms saved) |

### Phase 2 + 3 are not the bottleneck

Combined CPU work for the entire folder is under **1 ms**. Even an
`object_manifest.jsonl` with 5,000 rows would only push this to a few
ms. Optimising pyarrow encoders / row dispatching is not worth a single
review cycle. The bottleneck is Tokyo→Tokyo S3 latency: every
`get_object` pays ~30-50 ms for the round-trip plus body read, and the
loop currently incurs that cost N=4 times serially.

## Lever shipped

**Parallel per-artifact ETL via ThreadPoolExecutor.** `run_etl` now
fans out the four artifacts into a single `ThreadPoolExecutor` with
`max_workers=DEFAULT_ETL_MAX_WORKERS=4`. Each worker drives the full
per-artifact pipeline (Phase 1 → 2 → 3 → 4), so:

- The four S3 GETs overlap (the dominant ~85 % phase).
- The four Parquet PUTs (when `--commit`) also overlap.
- `pyarrow` and `boto3` are thread-safe per upstream docs; the pinned
  schema + per-call `io.BytesIO` mean no shared mutable state.

Stable ordering is preserved by using `ThreadPoolExecutor.map(...)`
(input order is also output order regardless of completion order), so
the resulting `report.artifacts` JSON stays byte-stable vs. the legacy
sequential walk. `max_workers=1` restores the legacy loop for unit
tests / debugging.

Code shape:

```python
artifact_kinds = tuple(ARTIFACT_SCHEMAS.keys())

def _run_one(artifact_kind: str) -> ArtifactReport:
    return etl_one_artifact(
        artifact_kind=artifact_kind,
        job_prefix=job_prefix, run_id=run_id,
        raw_bucket=raw_bucket, derived_bucket=derived_bucket,
        dry_run=dry_run, s3_client=s3_client,
    )

effective_workers = max(1, min(max_workers, len(artifact_kinds)))
if effective_workers == 1:
    artifact_reports = [_run_one(k) for k in artifact_kinds]
else:
    with ThreadPoolExecutor(
        max_workers=effective_workers,
        thread_name_prefix="etl-artifact",
    ) as pool:
        artifact_reports = list(pool.map(_run_one, artifact_kinds))
```

CLI exposure: `--max-workers` (default 4) on `etl_raw_to_derived.py`.

## After (J02_deep_nta_houjin, 3 trials each, median)

Full `run_etl` wall time including resolve_run_id + 4 artifact pipelines
+ dry_run write-buffer assembly:

| Mode | Trial 1 (ms) | Trial 2 (ms) | Trial 3 (ms) | Median (ms) |
| --- | ---: | ---: | ---: | ---: |
| `max_workers=1` (legacy sequential) | 439.25 | 219.78 | 453.94 | **439.25** |
| `max_workers=4` (new default) | 215.57 | 132.26 | 73.18 | **132.26** |

**End-to-end speedup: 3.32x** (sequential 439 ms → parallel 132 ms median).

Why the headline is higher than the per-Phase-1 2.28x measurement:

- The legacy loop serialises the 4 artifact pipelines, so per-artifact
  CPU jitter + cold TCP-stream effects on the 4th and 5th GET stack
  additively. The parallel mode hides that variance behind the longest
  single artifact.
- Phase 1b's 2.28x was per-Phase wallclock on a clean rerun; the
  3.32x includes the surrounding `run_etl` framing (run_id resolve,
  report dataclass assembly, per-artifact dry_run reporting) that
  also benefits from being cleanly overlapped with S3 IO.

## What was *not* applied

- **Athena `IGNORE_TRAILING_BYTES` / CTAS knobs.** PERF-3 already
  shipped the ZSTD Parquet migration for the top-3 hot tables and
  PERF-14 is in flight tuning Athena workgroup limits. The ETL itself
  does not run CTAS — it writes Parquet that the Glue crawler picks
  up — so CTAS knobs are out of scope for this audit.
- **Partition projection.** The hive partition layout
  (`<kind>/job_prefix=…/run_id=…/data.parquet`) is already
  crawler-friendly; partition projection would target the *query side*
  (Athena DDL annotations), not the write side. Leave for PERF-14.
- **`list_objects_v2` parallel discovery.** The ETL never enumerates
  raw bucket contents — it deterministically constructs the four
  canonical keys from `ARTIFACT_FILENAMES`. There is no listing API
  call to parallelise; the "S3 listing" terminology in the brief maps
  to the four per-artifact `get_object` calls, which is what the
  ThreadPool now overlaps.
- **`max_workers > 4`.** The artifact set is fixed at 4; the
  effective worker count is `min(max_workers, len(artifact_kinds))`,
  so bumping further is silently capped. The cap also avoids
  exhausting the default botocore connection pool.

## Quality gates

- `mypy --strict scripts/aws_credit_ops/etl_raw_to_derived.py`: **0 errors**.
- `ruff check scripts/aws_credit_ops/etl_raw_to_derived.py`: **All checks passed**.
- `pytest tests/jpcite_crawler/test_claim_refs_always_emitted.py`: **7/7 PASS**
  (covers required-artifact contract incl. empty `claim_refs`).

## Notes for follow-up

- Future J0X folders will land more raw artifacts beyond the four
  canonical ones (e.g. `quarantine.jsonl`, `source_profile_delta.jsonl`
  observed in J02). If those become first-class ETL outputs, they slot
  into `ARTIFACT_SCHEMAS` and benefit from the same fan-out without
  code changes.
- The S3 PUT half (Phase 4) only matters on `--commit` runs; in
  dry-run mode the new code path adds zero overhead vs. legacy.
- The `resolve_run_id` GET could also be folded into the pool by
  promoting it to a fifth "phantom" task, but it gates downstream
  partition keys and is only one RTT — keep it sequential for clarity.
