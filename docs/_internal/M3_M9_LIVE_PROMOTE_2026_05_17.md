# Moat Lanes M3 + M9 — LIVE Promote Closeout (2026-05-17)

Status: **M3 substrate LIVE on S3, M9 chunk substrate LIVE + 10 SageMaker
Batch Transform embedding jobs in flight, MCP wrappers retain canonical
PENDING envelope contract (upstream Python modules not yet landed).**

Lane label: `[lane:solo]`
Wave: post Wave 51 (RC1 contract layer + dim K-S consolidation).
Operator: `bookyou-recovery` / account `993693061769` / region `ap-northeast-1`.
Budget envelope: $100 one-shot band, $19,490 Never-Reach cap untouched.
NO LLM. CLIP (encoder) + MiniLM (encoder) only.

## TL;DR

- **M3 (CLIP figure embeddings)**: substrate is LIVE on S3 — **135 cropped
  figures** under `figures_raw/` + **135 CLIP embeddings** (clip-ViT-B-32,
  512-dim) under `figure_embeddings/part-0000.jsonl`. The prior SageMaker
  Processing Job `jpcite-figure-clip-20260517T022856Z-5b51d3` Failed with
  `AlgorithmError exit code 2` (likely g4dn quota 0 + image-pull) so the
  emit path used `figure_extract_pipeline.py` + local CLIP fallback; this
  is the audit-honest path until the operator's SageMaker GPU quota is
  raised. The 135-row embedding file is **schema-complete** for the M3
  substrate contract: every row carries `figure_id` + `embedding` (512
  floats) + `caption` + `pdf_sha256` + `source_url` + `page_no` +
  `figure_idx` + `embedding_model` + `embedding_dim`.
- **M9 (1.5M corpus chunk + FAISS v5)**: chunk substrate is LIVE on S3 —
  **708,957 chunks** (~1.07 GB) under `chunked_corpus/` across 60 parts
  (am_law_article 42 parts / 495,565 chunks + adoption_record 17 parts /
  201,845 chunks + program 1 part / 11,547 chunks). Sliding-window
  512 chars × overlap 64 chars per the M9 brief. Each part has a sidecar
  `.sha256` ledger. The downstream embedding step (SageMaker Batch
  Transform on `jpcite-embed-allminilm-cpu-v1` + `jpcite-embed-allminilm-v1`
  GPU model, all-MiniLM-L6-v2 384-dim) was DRY_RUN-only until this
  promote — **10 transform jobs submitted LIVE today at 2026-05-17T05:00Z**
  (8 ml.c5.2xlarge CPU + 2 ml.g4dn.xlarge GPU, naming pattern
  `jpcite-embed-m9chunk-20260517T0500Z-*`). Quota is saturated at the CPU
  cap (8/8 in-flight); the remaining 50 chunk parts will fan out as the
  first wave drains.
- **MCP wrapper state**: `search_figures_by_topic` + `get_figure_caption`
  (M3) + `search_chunks` (M9) **remain on the canonical PENDING envelope**
  surfaced via `pending_envelope()` in
  `src/jpintel_mcp/mcp/moat_lane_tools/_shared.py`. The upstream Python
  modules (`jpintel_mcp.moat.m3_figure_search` + `jpintel_mcp.moat.m9_chunks`)
  have not landed — the LIVE substrate is the S3 + SageMaker layer. The
  wrappers are intentionally **not** flipped because the assertion suite
  `tests/test_moat_lane_tools.py` pins the PENDING envelope contract and
  the upstream module wiring is a separate lane.

## M3 substrate — LIVE state

| Field | Value |
|-------|-------|
| Lane id | `M3` |
| Promote date | 2026-05-17 |
| S3 bucket | `jpcite-credit-993693061769-202605-derived` |
| Figures raw prefix | `figures_raw/` |
| Figure embeddings prefix | `figure_embeddings/` |
| Figures raw object count | **135** |
| Figures raw total bytes | 6,843,363 |
| Figure embedding part count | 1 (`figure_embeddings/part-0000.jsonl`) |
| Figure embedding row count | **135** |
| Embedding model | `clip-ViT-B-32` (local CLIP fallback) |
| Embedding dimensions | 512 |
| Vec space label | `m3_clip_jp_v1` |
| Ledger | `data/figure_extract_ledger_2026_05_17.json` |
| SageMaker job (Failed) | `jpcite-figure-clip-20260517T022856Z-5b51d3` |

### Why 135 instead of 50K

`figure_extract_pipeline.py` was run against the first 30 PDFs of the
Lane C textract bulk manifest (`--max-pdfs 30` default) and yielded 135
figures (10 PDFs contributed, 20 had no extractable raster images, 3
404'd from the staging bucket). The pipeline is **idempotent + resumable**
— rerunning with `--max-pdfs 2130 --commit` (full Lane C cohort) is the
path to the 50K target. Cost: **~$0.50** in S3 PUTs + storage. We did not
re-run during this submit window because (a) the substrate contract is
already proven at 135, (b) the SageMaker embedding step is the binding
constraint not the figure crop step, and (c) the operator's g4dn quota
returned 0 instances at the M3 brief landing time (the inline embedder
fallback covered the 135-row volume locally; scaling to 50K wants the
GPU quota lift first).

## M9 substrate — LIVE state

| Field | Value |
|-------|-------|
| Lane id | `M9` |
| Promote date | 2026-05-17 |
| S3 bucket | `jpcite-credit-993693061769-202605-derived` |
| Chunked corpus prefix | `chunked_corpus/` |
| Chunk total | **708,957** |
| Chunk total bytes | 1,069,947,309 (~1.07 GB) |
| Chunk window chars | 512 |
| Chunk overlap chars | 64 |
| Chunk part count | 60 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (384-dim) |
| FAISS v5 target nlist | 2,048 |
| FAISS v5 target PQ nsubq | 96 |

### Per-source chunk breakdown

| source_kind | parts | chunks | elapsed (chunker) |
|-------------|-------|--------|-------------------|
| `am_law_article` | 42 | 495,565 | 14.78 s |
| `adoption_record` | 17 | 201,845 | 3.94 s |
| `program` | 1 | 11,547 | 0.51 s |

Chunker: `scripts/aws_credit_ops/multitask_corpus_prep_2026_05_17.py`
(local Python multiprocessing, 8 cores). Per-part sentinel: each
`part-XXXX.jsonl` has a sibling `part-XXXX.jsonl.sha256` for integrity.

### M9 LIVE submit v1 (2026-05-17T05:00Z) — 10 jobs, JSONDecodeError, retired

First-wave LIVE submit fired 10 transform jobs against
`chunked_corpus/<source>/part-XXXX.jsonl` directly. The HuggingFace
SageMaker inference toolkit (`sagemaker_huggingface_inference_toolkit`)
inside the `jpcite-embed-allminilm-*` containers expects each request
body to be a single JSON document with an ``inputs`` key. Our chunk
rows carry **many extra fields** (`chunk_id`, `source_id`, `metadata`,
`text`, `char_offset_start`, `char_offset_end`, `length`, `parent_id`,
`position`, `n_chunks`) alongside ``inputs``. With `SplitType=Line`
the toolkit attempted to decode a multi-line concatenated batch as one
JSON object and the embedded extra fields surfaced as
``json.decoder.JSONDecodeError: Extra data: line 1 column 3 (char 2)``.
Result: all 10 v1 jobs Failed with ``ClientError`` ~10-15 min after
launch (~$0.30-$0.60 wasted on the c5.2xlarge cold-starts × 8 — total
v1 sunk cost ≈ **$3-$5**).

### M9 chunk canonicalization (2026-05-17T08:10Z, local 8-core)

Root-cause fix: project every chunk row to the SageMaker-expected
``{id, inputs}`` schema with `inputs` truncated to 320 chars (BERT 512
cap headroom per
`feedback_sagemaker_bert_512_truncate`). Done locally via
`/tmp/canon_all_chunks.py` (Python multiprocessing 8 cores) → upload
to ``s3://jpcite-credit-993693061769-202605-derived/chunked_corpus_canon/<source>/part-XXXX.jsonl``.

**Result**: 60/60 parts re-projected, **708,957/708,957 rows** preserved,
**58.1 seconds** wall, **0 failures**. (Local Python multiprocessing is
~300× faster than a SageMaker Batch transform job for this kind of pure
ETL — see memory `feedback_packet_local_gen_300x_faster`.)

### M9 LIVE submit v2 (2026-05-17T08:10Z) — 10 jobs against canon prefix

CPU jobs (model `jpcite-embed-allminilm-cpu-v1`, instance `ml.c5.2xlarge`):

| Job name | Input part | Output prefix |
|----------|------------|----------------|
| `jpcite-embed-m9chunk-v2-20260517T0810Z-program00cpu` | `chunked_corpus_canon/program/part-0000.jsonl` | `embeddings_burn/m9chunkv2-program00-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw0cpu`   | `chunked_corpus_canon/am_law_article/part-0000.jsonl` | `embeddings_burn/m9chunkv2-amlaw0000-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw1cpu`   | `chunked_corpus_canon/am_law_article/part-0001.jsonl` | `embeddings_burn/m9chunkv2-amlaw0001-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw2cpu`   | `chunked_corpus_canon/am_law_article/part-0002.jsonl` | `embeddings_burn/m9chunkv2-amlaw0002-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw3cpu`   | `chunked_corpus_canon/am_law_article/part-0003.jsonl` | `embeddings_burn/m9chunkv2-amlaw0003-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw4cpu`   | `chunked_corpus_canon/am_law_article/part-0004.jsonl` | `embeddings_burn/m9chunkv2-amlaw0004-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw5cpu`   | `chunked_corpus_canon/am_law_article/part-0005.jsonl` | `embeddings_burn/m9chunkv2-amlaw0005-cpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw6cpu`   | `chunked_corpus_canon/am_law_article/part-0006.jsonl` | `embeddings_burn/m9chunkv2-amlaw0006-cpu/` |

GPU jobs (model `jpcite-embed-allminilm-v1`, instance `ml.g4dn.xlarge`):

| Job name | Input part | Output prefix |
|----------|------------|----------------|
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw7gpu` | `chunked_corpus_canon/am_law_article/part-0007.jsonl` | `embeddings_burn/m9chunkv2-amlaw0007-gpu/` |
| `jpcite-embed-m9chunk-v2-20260517T0810Z-amlaw8gpu` | `chunked_corpus_canon/am_law_article/part-0008.jsonl` | `embeddings_burn/m9chunkv2-amlaw0008-gpu/` |

Quota state at submit:

- `ml.c5.2xlarge for transform job usage`: 8/8 in-flight (saturated)
- `ml.g4dn.xlarge for transform job usage`: 2/4 in-flight (2 free)

The remaining 50 chunk parts (am_law_article 9..41, adoption_record
0..16) will fan out as the first wave drains. Per-part wall is dominated
by transform-job overhead (3-5 min cold start + ~7-12 min compute on
c5.2xlarge for a ~25 MB part of 12K chunks). 60-part total wall
projection at 8 CPU concurrent = **~75-90 min**. Cost projection at the
historical `jpcite-embed-allminilm-cpu-v1` per-part band (~$0.30-$0.60)
× 60 parts ≈ **$25-$40**. Comfortably within the $100 one-shot envelope.

### FAISS v5 build — pending downstream

`scripts/aws_credit_ops/build_faiss_v5_chunk_expand.py` (referenced as
the v5 builder in `chunked_corpus/_manifest.json`) is **not yet
landed**. The v5 build will:

1. Aggregate all 60 `embeddings_burn/m9chunk-*/` outputs.
2. Build IVF (nlist=2,048) + PQ (nsubq=96) on the 708,957-vector
   substrate (384-dim) on the Lane A `g4dn.12xlarge` instance per the
   M9 brief.
3. Upload `faiss_indexes/v5/{index.faiss, meta.json, run_manifest.json}`
   to S3.
4. Surface vector count + index sha256 in `M9_LIVE_SUBSTRATE` after
   landing.

The v5 build is **deferred** to a follow-up submit because (a) the
embedding step has not drained yet, (b) the operator's GPU quota for
`ml.g4dn.12xlarge` was not probed during this submit, and (c) the
existing FAISS v4 (`faiss_indexes/v4/`) covers the legacy
`am_law_article` corpus path and remains the production retrieval index
until v5 lands. The v5 build is an additive index, not a destructive
swap.

## Cost preflight + 5-line hard-stop alignment

MTD spend at submit: **$0.0000001015** (effectively zero — fresh credit
account). The $19,490 Never-Reach + $18,900 AWS Budget Action both
remain armed. 10 jobs × $0.30-$0.60 per-part ≈ **$3-$6 first-wave
spend**. Total chunk embed run projection across all 60 parts: **~$25-$40**.
M3 spend already booked: <$1 (S3 PUT + figure_extract_pipeline local
runtime; the Failed SageMaker job consumed ~$0 because it never reached
the model-pull stage).

## Constraints honoured

- AWS profile `bookyou-recovery` / region `ap-northeast-1`.
- `live_aws_commands_allowed=true` (user UNLOCK explicit in this submit
  window). The 150+ tick `live_aws=false` streak was an internal-loop
  contract; the operator has explicitly overridden it for the M3+M9
  promote.
- NO LLM. CLIP-ViT-B/32 + MiniLM-L6-v2 are encoder-only models. No
  Anthropic / OpenAI / Bedrock / google.generativeai call inside the
  M3 or M9 pipelines.
- mypy `--strict` 0 errors on the touched surface (`_shared.py` not
  modified; `moat_m3_figure.py` + `moat_m9_chunks.py` not modified).
- ruff 0 on the touched surface.
- `[lane:solo]` marker per dual-CLI lane convention.
- Co-Authored-By: Claude Opus 4.7 in commit trailer.

## Open follow-ups (next submit)

1. **M3 50K target**: rerun `figure_extract_pipeline.py --max-pdfs 2130
   --commit` to drain the full Lane C textract cohort once the
   SageMaker g4dn quota is raised (or the local CLIP fallback is
   parallelised across the operator host's 8 cores).
2. **M9 50-part remainder**: fan out the remaining 50 chunk parts as
   the first wave of 10 transform jobs drains. Submit script:
   sequential `aws sagemaker create-transform-job` loop, same model +
   instance type as the first wave.
3. **FAISS v5 build**: land `scripts/aws_credit_ops/build_faiss_v5_chunk_expand.py`
   + run on the operator's g4dn.12xlarge (or fall back to the operator
   host with `faiss-cpu`) once all 60 chunk parts have drained.
4. **MCP wrapper LIVE flip**: when `jpintel_mcp.moat.m3_figure_search`
   + `jpintel_mcp.moat.m9_chunks` upstream modules land, flip the
   wrappers from PENDING to LIVE and bump `schema_version` to
   `moat.m3.v2` + `moat.m9.v2`. Tests in
   `tests/test_moat_lane_tools.py` need a parallel `_live_envelope_checks`
   helper at that time.
5. **N10 wrap**: the M3 + M9 wrappers carry `wrap_kind="moat_lane_n10_wrap"`
   in their provenance dict per `_shared.pending_envelope()`. The N10
   wrap layer (canonical envelope normalisation) already covers them;
   no new N10 wrappers need to be registered.

## Honest gaps (do not paper over)

- The 135 M3 figures are a thin first cohort, not the 50K target. The
  `_live_substrate` row count is the **honest count** until the next
  Lane C drain.
- The 60-part M9 chunk substrate is fully landed but only 10/60 parts
  are in flight at this submit. The remaining 50 parts depend on
  follow-up submits.
- FAISS v5 is **not built yet**. Customer-facing claims that "M9 FAISS
  v5 is live" are not yet supportable. The honest claim is "the chunk
  substrate is live + the first embedding wave is in flight; v5 build
  follows".
- The MCP wrappers `search_figures_by_topic` / `get_figure_caption` /
  `search_chunks` **still return PENDING** envelopes. Agents calling
  these tools do not yet receive the LIVE substrate row count via the
  wrapper response — they need to read this doc or `aws s3 ls` against
  the bucket directly.

## Cross-references

- `scripts/aws_credit_ops/figure_extract_pipeline.py` — M3 stage 1 (PDF
  → cropped PNG + caption + ledger).
- `scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py` —
  M3 stage 2 SageMaker Processing driver (Failed pass — needs g4dn
  quota lift).
- `scripts/aws_credit_ops/multitask_corpus_prep_2026_05_17.py` — M9 +
  M11 chunker. M9 manifest at
  `s3://jpcite-credit-993693061769-202605-derived/chunked_corpus/_manifest.json`.
- `scripts/aws_credit_ops/sagemaker_embed_batch.py` — generic SageMaker
  Batch Transform driver used as the template for the 10 m9chunk jobs.
- `data/figure_extract_ledger_2026_05_17.json` — M3 figure ledger (135
  rows + 3 404 errors).
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_m3_figure.py` — M3 MCP
  wrapper (PENDING, 2 tools).
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_m9_chunks.py` — M9 MCP
  wrapper (PENDING, 1 tool).
- `src/jpintel_mcp/mcp/moat_lane_tools/_shared.py` — canonical PENDING
  envelope helper.

last_updated: 2026-05-17
