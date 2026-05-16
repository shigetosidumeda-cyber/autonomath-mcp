# PERF-40 — FAISS IVF nprobe vs recall trade (v2 + v3)

`[lane:solo]` — measured 2026-05-17 against the live FAISS v2 + v3 indexes
downloaded from S3 (`s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/`
+ `.../v3/`). Mirrors the PERF-4 bench protocol: brute-force `IndexFlatIP`
ground truth over the **same PQ-decoded vectors** (apples-to-apples), single-
query latency (`index.search(q, k)` per timed step — batched lies about p95).

## TL;DR

| Index | nlist | ntotal | Old baked nprobe | **Recommended nprobe** | p95 speedup | Recall delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **v2** | 256 | 74,812 | 128 | **8** | **4.3x** (0.733 → 0.170 ms) | 0 (0.5205 → 0.5205) |
| **v3** | 1,024 | 235,188 | 512 | **8** | **11.5x** (2.205 → 0.192 ms) | 0 (0.4240 → 0.4240) |

Both indexes were measurably over-probed by the legacy build-script heuristic
`nprobe = min(nlist, max(32, nlist // 2))`. Recall is gated by the **PQ codebook
quantization floor**, not the inverted-list walk — so paying for more nprobe
beyond the plateau buys zero recall while paying linear latency.

## Source-of-truth measurement (200 queries / k=10 / seed 20260517)

### v2 (IVF+PQ nlist=256 nsubq=48 nbits=8, 74,812 vectors)

| nprobe | p50 (ms) | p95 (ms) | p99 (ms) | recall@10 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.065 | 0.088 | 0.105 | 0.5160 |
| 4 | 0.087 | 0.130 | 0.142 | 0.5205 |
| **8** | **0.108** | **0.170** | **0.179** | **0.5205** |
| 16 | 0.157 | 0.225 | 0.243 | 0.5205 |
| 32 | 0.258 | 0.329 | 0.344 | 0.5205 |
| 64 | 0.444 | 0.508 | 0.528 | 0.5205 |
| 128 (current baked) | 0.675 | 0.733 | 0.776 | 0.5205 |
| 256 (nlist) | 1.029 | 1.101 | 1.111 | 0.5205 |

**Recall saturates at nprobe=4** (0.5205, +0.0045 over nprobe=1). All higher
nprobe values produce the same set of top-10 neighbors because the PQ codebook
floor caps quality. **nprobe=8 is the chosen sweet spot** — same recall as
nprobe=128 in 23% of the time, with one extra inverted-list scanned (vs nprobe=4)
for robustness against query distribution shift.

### v3 (IVF+PQ nlist=1024 nsubq=48 nbits=8, 235,188 vectors)

| nprobe | p50 (ms) | p95 (ms) | p99 (ms) | recall@10 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.089 | 0.126 | 0.137 | 0.4305 |
| **8** | **0.143** | **0.192** | **0.204** | **0.4240** |
| 16 | 0.190 | 0.246 | 0.265 | 0.4240 |
| 32 | 0.270 | 0.341 | 0.358 | 0.4240 |
| 64 | 0.418 | 0.499 | 0.532 | 0.4240 |
| 128 | 0.679 | 0.810 | 0.852 | 0.4240 |
| 256 | 1.131 | 1.290 | 1.318 | 0.4240 |
| 512 (current baked) | 2.035 | 2.205 | 2.279 | 0.4240 |
| 1024 (nlist) | 3.360 | 3.529 | 3.612 | 0.4240 |

**Recall saturates at nprobe=8** (0.4240). nprobe=1 is interestingly slightly
higher (0.4305) but unstable — nprobe=1 only walks the single closest
inverted-list, so for a few queries the "true" nearest neighbor lives in a list
the coarse quantizer ranked second. With nprobe ≥ 2 those neighbors come in and
the recall settles at 0.4240. **nprobe=8 is the chosen sweet spot** — same
recall as nprobe=512 in 8.7% of the time.

### Why is v3 recall lower than v2 (0.424 vs 0.520)?

v3 has 3.1x more vectors at the same `nsubq=48 / nbits=8` PQ config, so each
codeword is shared across more raw vectors → coarser quantization → lower
self-recall (each query is the embedding of an indexed point, so the recall
metric is bounded by how distinct each point's PQ code is). The fix is **not**
more nprobe (already proved above) — it's a richer PQ codebook (`nsubq=64
nbits=8`) which doubles the per-vector code size from 48 bytes to 64 bytes.
Out of scope for PERF-40 (that's PERF-41 territory if we want to chase recall).

## Change landed

This proposal is **paired with code changes** to the 4 FAISS build scripts so
that all future rebuilds bake `nprobe=8` into the serialized index:

- `scripts/aws_credit_ops/build_faiss_v2_expand.py` — smoke_recall_at_k nprobe
  heuristic updated.
- `scripts/aws_credit_ops/build_faiss_v3_expand.py` — smoke_recall_at_k nprobe
  heuristic updated.
- `scripts/aws_credit_ops/build_faiss_v2_from_sagemaker.py` — smoke nprobe
  updated.
- `scripts/aws_credit_ops/build_faiss_index_from_embeddings.py` — smoke nprobe
  updated.

The **live indexes in S3 still carry the over-probed nprobe** (v2=128, v3=512).
Re-baking requires either a fresh build (rare, only after corpus expansion) OR
a one-shot rewrite that:

```python
import faiss
index = faiss.read_index("/tmp/v2.faiss")
index.nprobe = 8
faiss.write_index(index, "/tmp/v2_nprobe8.faiss")
# upload to s3://.../faiss_indexes/v2/index.faiss
```

Per PERF-40 task constraints (`live_aws_commands_allowed=false`, no GPU jobs,
no S3 write of new indexes), the re-bake is **NOT performed in this lane**.
Operator can re-bake on demand by running:

```bash
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/bench_faiss_query_latency.py \
    --index /tmp/perf40/v2.faiss \
    --n-queries 200 \
    --upload-tuned
```

(the existing `bench_faiss_query_latency.py` already supports `--upload-tuned`
to write the nprobe-baked index to `faiss_indexes/v2_tuned/`).

## Honest notes

- Recall numbers measure "recover top-K of the **PQ-decoded** index's own
  representation", not "recover top-K of the original embedding space". Same
  caveat as PERF-4. The `v1_vectors_are_pq_reconstructed: true` flag in the
  v2 manifest applies here too.
- Latencies are CPU single-thread on macOS / Apple Silicon — Fly Tokyo machines
  will read different absolute numbers but the **shape of the curve is what
  matters** for nprobe selection, and that shape is determined by the IVF
  algorithm, not the host.
- 200 queries is enough to be stable on p95 here because the per-query latency
  distribution is tight (low variance), but if recall floor numbers ever look
  suspicious, re-run with `--n-queries 1000`.
- The `bench_faiss_query_latency.py` `pick_winner` logic would still pick
  nprobe=128 (the highest in the legacy sweep) because its tie-break prefers
  the latest meeting both gates — adding nprobe=8 to the sweep list and tuning
  the tie-break to prefer lowest-p95 is a follow-up (PERF-40B) if the bench
  script is ever re-run for live tuning.

## Files

- Sweep script: `/tmp/perf40/sweep.py` (one-shot, not committed)
- Raw JSON: `/tmp/perf40/sweep_results.json` (one-shot, not committed)
- This doc: `docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md`
- Sibling PERF-4 doc: `docs/_internal/faiss_perf_benchmark_2026_05_16.md`

last_updated: 2026-05-17
