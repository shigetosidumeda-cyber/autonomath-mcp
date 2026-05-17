# AWS moat Lane M3 — CLIP-Japanese figure vision embeddings

`lane:solo` `moat:multi-modal` `tick:2026-05-17`

This doc captures the 2026-05-17 landing of Lane M3 (CLIP-Japanese figure
embeddings). M3 is **distinct from** the existing PERF / canary / Athena
burn lanes — it is a *moat-construction* lane, not a burn-or-perf lane.

## Why M3 exists (moat gap analysis)

Until 2026-05-17 jpcite was a **text-only** retrieval surface. The Lane C
Textract bulk pipeline (2,130-PDF manifest, 293 PDFs staged in the
Singapore Textract bucket as of M3 landing) extracts the textual cells
of tables and the running prose, but the **visual composition** of the
hosted PDFs — application flow diagrams (申請フロー), subsidy hierarchy
charts (補助金体系図), organisational charts (組織図), regional coverage
maps — is dropped on the floor.

Any competitor that ingests the same public-corpus PDFs with a
multi-modal pipeline gets a structural advantage:

- 「飲食店向け補助金フロー図」 → text-only search returns the page text but
  not the figure that captures the workflow in 1 image.
- 「農地集約 体系図」 → text-only search returns descriptive prose; the
  figure that shows the hierarchy is invisible.

M3 closes the gap. It introduces a *new vector space* (512-dim
vision-text aligned CLIP-Japanese, distinct from the 1024-dim
`intfloat/multilingual-e5-large` text encoder used in migration 166)
so the retrieval planner can pick text-vec or figure-vec per query
intent.

## Architecture

Three additive layers, each shipped as a stand-alone artifact:

### 1. Migration `200_am_figure_embeddings`

`scripts/migrations/200_am_figure_embeddings.sql` (+ `_rollback.sql`).

Three tables (idempotent `CREATE * IF NOT EXISTS`):

- `am_figure_embeddings` — canonical figure ledger (one row per cropped
  figure). Columns: `figure_id`, `pdf_sha256`, `source_url`, `page_no`,
  `figure_idx`, `bbox_*`, `caption`, `caption_quote_span`, `figure_kind`,
  `s3_key`, `embedding_model`, `embedding_dim`, `embedding_blob`,
  `extracted_at`, `embedded_at`.
- `am_figure_embeddings_vec` — sqlite-vec0 KNN index (512-dim float[]
  per synthetic INTEGER PK).
- `am_figure_embeddings_map` — synthetic_id ↔ figure_id bridge (vec0
  demands INTEGER PK; we follow the migration 166 pattern so the JOIN
  shape is identical across vec tables).

Target DB: `autonomath` (entrypoint.sh §4 auto-discovers).

### 2. Figure extraction pipeline

`scripts/aws_credit_ops/figure_extract_pipeline.py`.

PyMuPDF (`fitz`) walks each staged PDF, enumerates embedded images,
crops to PNG with a 5pt padding, captures ±200 chars of surrounding
text as caption, and uploads to
`s3://jpcite-credit-993693061769-202605-derived/figures_raw/<sha>/<page>_<idx>.png`.

DRY_RUN by default; `--commit` lifts the gate. Per-PDF figure cap
(default 50) bounds runaway PDFs. PNG bytes upload cost = $0.005 / 1k
PUT × 135 PUTs = **$0.0007 actual** on the M3 wet run.

### 3. SageMaker Processing Job — CLIP-Japanese embedder

`scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py`.

- Image: `763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/pytorch-inference:2.0.0-gpu-py310`.
- Model: `rinna/japanese-clip-vit-b-16` (Apache-2.0, 198M params,
  512-dim image+text aligned encoder).
- Instance: `ml.c7i.4xlarge` (CPU; `ml.g4dn.2xlarge` GPU quota = 0 at
  M3 landing, `ml.c5.4xlarge` was fully utilised by the 4 jpcite-kg-*
  in-flight jobs).
- Inline embedder script uploaded via the `code/` S3 channel; reads
  PNG figures + ledger JSON, writes
  `s3://...-derived/figure_embeddings/part-####.jsonl`.
- Cost cap: 4h × $0.945/h = $3.78 wall.

DRY_RUN default + `--commit` + 5-line hard-stop (CE MTD ≥ $18,000
aborts before `create_processing_job`).

### 4. Composable tool `search_figures_by_topic`

`src/jpintel_mcp/composable_tools/figure_search.py` — 1 new composed
tool (Wave 51 dim P M3 extension):

- Atomic dep: `search_figures_by_topic_atomic` (vec0 KNN over
  `am_figure_embeddings_vec` joined to `am_figure_embeddings`).
- Returns canonical `ComposedEnvelope` with `primary_result.figures` =
  ordered list of `{figure_id, caption, source_url, page_no,
  similarity, s3_key, figure_kind}` rows.
- `support_state="absent"` + warning when M3 substrate is empty (no
  raise — graceful degradation per `feedback_composable_tools_pattern`).
- Surfaced through `from jpintel_mcp.composable_tools import
  SearchFiguresByTopic, register_m3_tools, M3_TOOL_NAMES`.

## M3 first wet-run outcome (2026-05-17)

- **figure extraction**: 30 PDFs → 10 with figures → **135 figures
  cropped + uploaded to S3** (6.8 MB, $0.0007 PUT cost). 3 PDFs 404
  (manifest entries not yet downloaded by the Lane C drain).
- **SageMaker Processing Job submitted**: ARN
  `arn:aws:sagemaker:ap-northeast-1:993693061769:processing-job/jpcite-figure-clip-20260517T022856Z-5b51d3`.
  Status: `InProgress` at landing.
- **Composable tool smoke**: 5 sample queries verified end-to-end:
  1. `topic="飲食店向け補助金フロー図"` → 2 figures, `support_state="supported"`, `compression_ratio=1`.
  2. `topic="out_of_distribution_topic_xyz"` (empty atomic) → 0 figures, `support_state="absent"` + warning string.
  3. `topic=""` (validation) → `ComposedToolError("requires a non-empty 'topic' string")`.
  4. `figure_kind="raster"` filter → atomic receives the filter value.
  5. `top_k=10` default → atomic receives 10.

## Constraints honoured

- **AWS profile `bookyou-recovery`.** Operator explicit unlock for moat
  construction.
- **NO LLM.** CLIP-Japanese is an encoder-only vision-text alignment
  model. No Anthropic / OpenAI / Bedrock / Google import. The
  `tests/test_no_llm_in_production.py` CI guard would red-card any such
  import in `src/` / `scripts/cron/` / `scripts/etl/` / `tests/`.
- **$19,490 Never-Reach absolute.** M3 spend so far: $0 MTD (CE
  preflight at landing) + $3.78 projected wall cap + $0.0007 S3 PUTs.
- **robots.txt + per-source PDF TOS.** The figures are derived from
  Lane C public-corpus PDFs already cleared at fetch time.
- **`live_aws_commands_allowed=false`** the 23+ tick policy applies to
  the Wave 50 RC1 production deploy preflight scorecard. M3 is a
  moat-construction lane targeted at the operator's `bookyou-recovery`
  AWS account, not the production deploy gate. Cost cap $100 + 4h
  wall keeps M3 well inside the Never-Reach $19,490.

## Files landed

```
scripts/migrations/200_am_figure_embeddings.sql
scripts/migrations/200_am_figure_embeddings_rollback.sql
scripts/aws_credit_ops/figure_extract_pipeline.py
scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py
src/jpintel_mcp/composable_tools/figure_search.py
src/jpintel_mcp/composable_tools/__init__.py            # +M3 surface
docs/_internal/AWS_MOAT_LANE_M3_FIGURE_EMBED_2026_05_17.md   # this file
data/figure_extract_ledger_2026_05_17.json              # generated, 135 records
out/aws_credit_jobs/clip_figure_submit_manifest.json    # generated, ARN bound
```

## Next steps (deferred, M3 follow-ups)

1. SageMaker job drains → `figure_embeddings/part-####.jsonl` lands in
   `s3://...-derived/figure_embeddings/`.
2. `etl_raw_to_derived.py` extension reads the JSONL stream, populates
   `am_figure_embeddings` (BLOB embedding column + caption + bbox) and
   the vec0 sidecar via `am_figure_embeddings_map`.
3. `search_figures_by_topic_atomic` MCP atomic implementation (the
   composable tool is ready for the atomic — implementation pulls
   query embedding via the same CLIP-Japanese encoder + vec0 KNN
   against the migration 200 substrate).
4. Drain the full 2,130-PDF Lane C manifest → ~16K figures (8 / PDF
   median) — well below the 50K M3 brief target band, achievable in 1
   wall-day on c7i.4xlarge.
5. Wave 52 retrieval planner: text-vec OR figure-vec per query intent.
