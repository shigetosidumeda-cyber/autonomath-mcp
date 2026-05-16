# FAISS IVF+PQ index build over derived corpus (2026-05-16)

First production FAISS index over the SageMaker batch-transform embedding
outputs that live in the AWS credit-burn derived bucket. Builder script
lives at `scripts/aws_credit_ops/build_faiss_index_from_embeddings.py`.

## Result

- **Index path**: `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v1/`
  - `index.faiss` — 4,035,484 bytes (~3.85 MiB)
  - `meta.json` — newline-delimited `{row, table, packet_id}` records
    (~4.02 MiB), used by retrieval to map a FAISS row back to the
    source packet ID.
  - `run_manifest.json` — full provenance + telemetry + per-query smoke
    results (~27 KiB).
- **Vectors indexed**: **57,979** total (post mean-pool over token axis).
  - `adoption_records`: 44,041 (from `embeddings/adoption_records/part-0001.jsonl.out`,
    aligned with `corpus_export/adoption_records/part-0001.jsonl`).
  - `invoice_registrants`: 13,801 (from `part-0000.jsonl.out`).
  - `nta_saiketsu`: 137 (from `part-0000.jsonl.out`).
- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2`
  (per SageMaker `run_manifest.json` `embedding_dim: 384`).
- **Index class**: `IndexIVFPQ` with `IndexFlatIP` quantizer, inner-product
  metric on L2-normalized vectors.
- **Hyperparameters**: `nlist=256`, `nsubq=48`, `nbits=8`, train sample
  = 9,984 (clamped to `nlist * 39`).
- **Smoke recall@10** (100 random queries drawn from the index, asserting
  the query's own row is in its top-10 neighbors with `nprobe=128`):
  **0.88** — exceeds the 0.80 acceptance threshold.
- **Train time**: 0.59 s. **Add time**: 0.59 s. **Load + mean-pool time**:
  314.54 s (single-threaded JSON parse over ~24 GB of embeddings).
- **AWS profile**: `bookyou-recovery` (region `ap-northeast-1`). Builder
  honors `AWS_PROFILE` env override and CLI `--profile` flag.

## How it works

SageMaker batch transform produced per-line JSON envelopes shaped as
`[[ [f0, f1, ... f383], ... up to ~227 token vectors ]]` — each line
corresponds to one input packet. Token-level vectors are mean-pooled
to derive one packet-level vector per line, then L2-normalized so
inner-product search matches cosine similarity.

`build_faiss_index_from_embeddings.py` is a CPU-side builder. It does
**not** re-encode from text — that workload is owned by
`build_faiss_index_gpu.py` (which is for the GPU credit-burn cohort and
calls sentence-transformers directly). This builder is the fast path
for consuming the pre-computed embedding output.

### Pipeline

1. List embedding part files under `s3://<derived>/embeddings/<table>/`.
2. Download to a local cache (default `/tmp/faiss_cache`).
3. Iterate line-by-line, mean-pool the token vectors, L2-normalize the
   resulting 384-d vector, append to the in-memory matrix.
4. Recover packet IDs by aligning embedding part-N with corpus part-N
   (basename digit, not concatenation order — important because
   `adoption_records` ships only `part-0001.jsonl.out` even though the
   corpus has `part-0000` + `part-0001`).
5. Train `IndexIVFPQ` on a random sample (clamped to ensure
   `n_train >= nlist * 39` and `>= 2^nbits = 256`).
6. Add all vectors. Serialize to bytes via temp file + `faiss.write_index`.
7. Smoke test: sample N queries, check whether each query's own row id
   appears in its own top-K. Reports `recall@k`.
8. Upload `index.faiss` + `meta.json` + `run_manifest.json` to
   `s3://<derived>/faiss_indexes/v1/` (versioned prefix — subsequent
   builds should land at `v2/`, `v3/`, ...).

## Constraints (acceptance criteria)

- **NO LLM**: FAISS k-means clustering + product quantization. No
  Anthropic / OpenAI / Gemini imports anywhere. Sentence-transformer
  was used **upstream** in the SageMaker batch transform; the build
  itself consumes only its float output.
- **bookyou-recovery profile** with `live_aws_commands_allowed=true`
  (implicit since this run actually wrote to S3). `[lane:solo]` marker
  required on the parent commit.
- **mypy --strict clean**, **ruff 0 warnings**.

## Honest gaps

- `embeddings/adoption_records/part-0000.jsonl.out` is missing in S3 —
  only part-0001 (44,041 packets) was produced by the upstream
  SageMaker job. The corpus manifest lists 116,335 rows in part-0000
  that did not embed; they should be back-filled in a future
  SageMaker batch transform rerun.
- `embeddings/programs/`, `embeddings/am_law_article/`,
  `embeddings/am_law_article_cpu_reembed/`, `embeddings/court_decisions/`,
  `embeddings/nta_tsutatsu_index/` each have a `run_manifest.json` but
  **no part-NNNN.jsonl.out**. Those source families were spec'd but
  the SageMaker output is empty — same back-fill applies.
- The 508K-file / 128 GB derived bucket figure includes packet
  artifacts beyond the 6 embedding source families. Only the
  6 sources above ever flow into the FAISS index; expanding coverage
  requires generating embeddings for additional families first.

## Re-running

```bash
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/build_faiss_index_from_embeddings.py \
  --tables nta_saiketsu,invoice_registrants,adoption_records \
  --smoke-queries 100 --smoke-k 10 --nlist 256 \
  --cache-dir /tmp/faiss_cache
```

Add `--no-upload` to dry-run without writing to S3. Bump the
`--index-prefix` (e.g. `faiss_indexes/v2`) when iterating to avoid
clobbering the current production blob.

## Smoke test interpretation

`recall@k` here measures whether the IVF+PQ approximation preserves
the trivial self-similarity ("a vector retrieved against itself should
be in its own top-K"). Exact `IndexFlatIP` would yield recall=1.0 by
construction; IVF+PQ's `nprobe + 8-bit quantization` lossiness gives
0.84-0.92 in typical configurations. For semantic search at production
serving time the relevant metric will be `recall@k` against held-out
relevance labels, not self-similarity — that is a separate evaluation
step downstream.

## File map

- Builder: `scripts/aws_credit_ops/build_faiss_index_from_embeddings.py`
- GPU sibling (re-encodes from text, used for credit burn):
  `scripts/aws_credit_ops/build_faiss_index_gpu.py`
- This doc: `docs/_internal/faiss_index_build_2026_05_16.md`
- S3 result: `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v1/{index.faiss,meta.json,run_manifest.json}`

last_updated: 2026-05-16
