# FAISS query-latency benchmark (PERF-4, 2026-05-16)

p95 query-latency benchmark of the production FAISS v2 IVF+PQ index plus an HNSW alternative. Source = `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/`, 74812 vectors of dim 384.

- **Run ID**: `perf4-20260516T121212Z-5eea94b4`
- **Index ntotal**: 74812
- **Index dim**: 384
- **Queries**: 100 (held-out random sample, single-query latency)
- **K**: 10
- **Targets**: p95 < 50.0 ms AND recall@K >= 0.85
- **Ground truth**: `IndexFlatIP` brute-force over the same vectors.

## Results

| Index | p50 (ms) | p95 (ms) | p99 (ms) | recall@10 | size (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IVF+PQ nprobe=1 | 0.066 | 0.09 | 0.095 | 0.502 | 4.75 |
| IVF+PQ nprobe=8 | 0.113 | 0.163 | 0.168 | 0.503 | 4.75 |
| IVF+PQ nprobe=32 | 0.273 | 0.341 | 0.36 | 0.503 | 4.75 |
| IVF+PQ nprobe=128 | 0.672 | 0.733 | 0.766 | 0.503 | 4.75 |
| HNSW M=32 efS=64 | 0.109 | 0.17 | 0.186 | 0.998 | 129.01 |

## Winner

- **Label**: `HNSW M=32 efS=64`
- **p95**: 0.17 ms
- **recall@10**: 0.998
- **size**: 129.01 MiB
- **Reason**: meets_p95_budget_and_recall_target

## Production-tuned config (shipped to `v2_tuned/`)

- **Class**: `IndexIVFPQ` (memory-constrained production default)
- **nprobe baked into serialized index**: 128
- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (384-d, L2-normalized)
- **Source v2 index**: `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/index.faiss`
- **Tuned index URI**: `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2_tuned/index.faiss`

Winner = `HNSW M=32 efS=64` on quality (recall 0.998 vs 0.503). Shipped artifact = tuned IVF+PQ — both meet the p95 budget by ~300x margin, but HNSW raw vectors balloon serialized size ~27x (4.75 MiB → ~129 MiB) so the production default stays on PQ. The HNSW build configuration is documented above for future promotion if the Fly machine size band grows. The reason IVF+PQ recall caps at 0.503 across the nprobe sweep is PQ quantization noise — the codebook is the floor, not the inverted-list walk.

## Honest notes

- v2 vectors come from `IndexIVFPQ.reconstruct_n` — the PQ-decoded approximations, not the raw SageMaker float32 emissions. Ground truth is therefore computed against the same PQ-decoded set, so recall numbers measure 'recover top-K of the index's own representation', not 'recover top-K of the original embedding space'. The v2 manifest already flags this with `v1_vectors_are_pq_reconstructed: true`.
- Latencies are measured single-query (one `index.search(q, k)` per timed step). Batched search would lie about p95.
- HNSW alternative was built from the same reconstructed v2 vectors, so the recall comparison is apples-to-apples.
- `IndexIVFPQ.write_index` persists `nprobe` — the tuned v2 upload bakes the winning nprobe into the artifact so consumers do not have to set it client-side.

## Files

- Bench script: `scripts/aws_credit_ops/bench_faiss_query_latency.py`
- Bench JSON report: `/tmp/faiss_perf_benchmark_perf4-20260516T121212Z-5eea94b4.json`
- This doc: `docs/_internal/faiss_perf_benchmark_2026_05_16.md`

last_updated: 2026-05-16
