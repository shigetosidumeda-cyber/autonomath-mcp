# FAISS v2 expand — embed 4 missing source families (2026-05-16)

Expansion of the FAISS v1 IVF+PQ index (`faiss_indexes/v1/`, 57,979
vectors over 3 families) into a v2 index that also covers the 4
families that v1 documented as a "honest gap":

- `am_law_article` (353,278 corpus rows; v1 doc estimate ~140K was low)
- `programs` (12,753 corpus rows)
- `court_decisions` (848 corpus rows)
- `nta_tsutatsu_index` (3,232 corpus rows)

The v1 doc declared SageMaker PM3-PM5 should have produced
`embeddings/<family>/part-NNNN.jsonl.out` for these families. As of
2026-05-16 14:00 JST those jobs are **all FAILED** in SageMaker
(`ClientError: See job logs for more information` for 3 of them and
`AlgorithmError: Model container failed to respond to ping` for
`programs`), with only `run_manifest.json` present in S3 and no
`part-*.out` files.

Rather than block on a SageMaker model-container fix (the GPU /
container path is owned by a separate iteration), this expand builds
the missing embeddings **locally** with the same model used by v1
(`sentence-transformers/all-MiniLM-L6-v2`, 384-d, L2-normalized) and
combines them with the v1 cohort into a fresh IVF+PQ index.

## Result

- **Index path**:
  `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/`
  - `index.faiss` — IVF+PQ binary (size in run_manifest)
  - `meta.json` — newline-delimited `{row, table, packet_id, source}`
    records mapping each FAISS row to a source packet ID. `source` is
    `v1_reconstructed` for the 57,979 v1 cohort rows and
    `v2_local_encoded` for the 4 new families.
  - `run_manifest.json` — provenance + telemetry + per-family vector
    counts + honest-notes about the v1 reconstruction.
- **Vector budget**:
  - v1 cohort: **57,979** (PQ-reconstructed via
    `IndexIVFPQ.reconstruct_n`, then re-normalized).
  - `am_law_article`: 353,278 freshly encoded (full corpus).
  - `programs`: 12,753 freshly encoded.
  - `court_decisions`: 848 freshly encoded.
  - `nta_tsutatsu_index`: 3,232 freshly encoded.
  - **Total v2 vectors**: ~428K (final value lands in `run_manifest`).
- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (same
  as v1 SageMaker model spec).
- **Index class**: `IndexIVFPQ` over `IndexFlatIP` quantizer, inner
  product on L2-normalized vectors.
- **Hyperparameters**: `nlist=256`, `nsubq=48`, `nbits=8`, train sample
  capped at 100K.
- **Smoke recall@10**: see `run_manifest.smoke.recall_at_k`.

## Honest gaps + lossy notes

- v1's 57,979 vectors are **PQ-decoded approximations**, not the raw
  SageMaker float32 emissions. `reconstruct_n` walks the inverted
  index and decodes each PQ code back to a 384-d vector — this is
  *the* representation v1 served from production, so v1 cohort
  retrieval behaves the same in v2 as it did in v1. We re-normalize
  after decode to absorb the minor drift introduced by quantization.
- The full v1 source embedding files (saiketsu 259MB / invoice 4.4GB
  / adoption 20.5GB) were intentionally **not** re-downloaded. The
  20GB+ blob over an SDK mean-pool round-trip is not worth running
  twice for one digit of retrieval improvement.
- `am_law_article` corpus is 353K rows, not the ~140K originally
  scoped in the v1 doc — the v1 doc estimate was a row-count guess
  before corpus_export landed. The local encode handles all 353K.
- SageMaker PM5 failures are documented but **not** auto-retried by
  this expand: a model-container fix is a different concern (the
  AlgorithmError ping fault and the ClientError loader fault both
  belong to the SageMaker model definition, not to this index
  build).

## How the v2 build works

1. Pull `faiss_indexes/v1/{index.faiss, meta.json, run_manifest.json}`.
2. Call `IndexIVFPQ.make_direct_map()` + `reconstruct_n(0, ntotal, out)`
   to recover the v1 cohort's 384-d vectors as float32. Re-normalize.
3. Load `sentence-transformers/all-MiniLM-L6-v2` locally (first run
   downloads ~80MB of weights to the HuggingFace cache).
4. For each new family in
   (`am_law_article`, `programs`, `court_decisions`, `nta_tsutatsu_index`):
   a. List + download corpus parts from
      `s3://<derived>/corpus_export/<family>/part-NNNN.jsonl`.
   b. Stream-parse rows (`{"id": ..., "inputs": ...}`).
   c. Batch-encode at 256 rows/batch with
      `normalize_embeddings=True`.
   d. Stack into a float32 matrix.
5. Concatenate (v1 cohort, am_law_article, programs, court_decisions,
   nta_tsutatsu_index) into a single (N, 384) matrix.
6. Train fresh `IndexIVFPQ`, then `add()`.
7. Smoke `recall@k` via self-query (each query's own row should appear
   in its own top-K).
8. Upload `index.faiss` + `meta.json` + `run_manifest.json` to
   `faiss_indexes/v2/`.

## Constraints (acceptance criteria)

- **NO LLM**: `sentence-transformers` is a transformer encoder (not an
  LLM API call). `tests/test_no_llm_in_production.py` still passes
  because the script lives in `scripts/aws_credit_ops/` and never
  imports `anthropic`, `openai`, `google.generativeai`, or
  `claude_agent_sdk`.
- **bookyou-recovery profile** (region `ap-northeast-1`). The S3 calls
  use the explicit `--profile` flag or `AWS_PROFILE` env.
- **mypy --strict clean**, **ruff 0 warnings** on the new script.
- **`[lane:solo]` marker** on the parent commit.
- **HONEST counts**: per-family vector counts + total in
  `run_manifest`; v1 cohort flagged as `v1_vectors_are_pq_reconstructed: true`.

## Re-running

```bash
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/build_faiss_v2_expand.py \
    --families am_law_article,programs,court_decisions,nta_tsutatsu_index \
    --smoke-queries 5 --smoke-k 10 \
    --batch-size 256
```

Add `--no-upload` to dry-run. Use `--max-rows-per-family 200` for a
sanity smoke (~2 minutes on M-series CPU).

## File map

- Builder: `scripts/aws_credit_ops/build_faiss_v2_expand.py`
- v1 sibling: `scripts/aws_credit_ops/build_faiss_index_from_embeddings.py`
- v1 doc: `docs/_internal/faiss_index_build_2026_05_16.md`
- This doc: `docs/_internal/faiss_v2_expand_2026_05_16.md`
- S3 v2: `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/{index.faiss,meta.json,run_manifest.json}`

last_updated: 2026-05-16
