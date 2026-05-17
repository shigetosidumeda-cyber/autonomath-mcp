-- target_db: autonomath
-- migration 200_am_figure_embeddings
--
-- AWS moat Lane M3 (2026-05-17): multi-modal figure embeddings.
--
-- Background
-- ----------
-- The public-corpus PDFs ingested under Lane C / Lane K Textract carry
-- substantial information in **figure form** — application flow diagrams
-- (申請フロー), subsidy hierarchy charts (補助金体系図), organisational
-- charts (組織図), regional coverage maps, etc. Textract extracts the
-- textual cells of tables and the running prose, but the **visual
-- composition** of these diagrams is dropped. Until now jpcite has been
-- a text-only retrieval surface, which is a structural moat hole vs
-- any competitor that ingests the same PDFs with a multi-modal pipeline.
--
-- Lane M3 fills that hole. The pipeline (driven from
-- ``scripts/aws_credit_ops/figure_extract_pipeline.py`` +
-- ``scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py``)
-- decomposes the 293 staged Lane C PDFs (and the broader 2,130-PDF
-- manifest as it drains) into:
--
--   1. ``figure_extract_pipeline.py`` — opens each PDF with PyMuPDF,
--      enumerates rendered images + vector-drawing bounding boxes,
--      crops each region to PNG, and uploads to
--      ``s3://jpcite-credit-993693061769-202605-derived/figures_raw/<sha256_pdf>/<page>_<idx>.png``.
--      Per-figure caption is the surrounding text within ±200 chars
--      of the bbox on the same page.
--   2. ``sagemaker_clip_figure_submit_2026_05_17.py`` — SageMaker
--      Processing Job (``ml.g4dn.2xlarge``) running CLIP-Japanese
--      (``rinna/japanese-clip-vit-b-16``, 512-dim image+text aligned
--      encoder) over the cropped PNG corpus, writing JSONL embeddings
--      to ``s3://...-derived/figure_embeddings/part-####.jsonl``.
--   3. ``etl_raw_to_derived.py`` (existing) is extended to ingest the
--      JSONL stream into ``am_figure_embeddings`` (this migration) and
--      backfill the sidecar ``am_figure_embeddings_vec`` virtual table
--      so vec0 KNN search becomes available at app boot.
--
-- This migration introduces:
--
--   am_figure_embeddings              — canonical figure ledger (one
--                                       row per cropped figure).
--   am_figure_embeddings_vec          — sqlite-vec0 KNN index (512-dim
--                                       float vector per ``figure_id``).
--   am_figure_embeddings_map          — figure_id ↔ synthetic_id bridge
--                                       (vec0 demands INTEGER PK; we
--                                       follow the migration 166
--                                       ``am_canonical_vec_*_map``
--                                       pattern so the query JOIN stays
--                                       identical across vec tables).
--
-- CLIP-Japanese rationale
-- -----------------------
-- * ``rinna/japanese-clip-vit-b-16`` (Apache-2.0 license, 198M params,
--   512-dim image + text aligned encoder, released 2022-05). Trained
--   on Japanese-captioned image pairs, so 「飲食店向け補助金フロー図」
--   style queries are first-class — not a translation hop through
--   English CLIP.
-- * It is NOT a generative LLM. CLIP family models compute a single
--   pooled embedding per image / text; no token-by-token decoding,
--   no Anthropic / OpenAI / Bedrock dependency, and no breach of
--   the ``feedback_no_operator_llm_api`` memory.
--
-- vec dimension
-- -------------
-- 512-dim. This is intentionally different from the 1024-dim
-- ``intfloat/multilingual-e5-large`` text encoder used in migration
-- 166 (``am_canonical_vec_program`` / ``_enforcement`` etc.). The two
-- vec spaces are NOT cross-comparable — the M3 surface is a
-- vision-text aligned semantic space, the migration-166 surface is
-- a text-only encoder. The retrieval planner picks one or the other
-- per query intent; ``search_figures_by_topic`` (composable tool)
-- always hits the M3 vec.
--
-- Idempotency
-- -----------
-- ``CREATE TABLE / VIRTUAL TABLE / INDEX IF NOT EXISTS`` only. No
-- seed inserts. Safe to re-run on every Fly boot via entrypoint.sh §4.
-- Companion ``200_am_figure_embeddings_rollback.sql`` drops both the
-- vec table and the ledger.
--
-- Constraints honoured
-- --------------------
-- * Foreign keys ON — figure_id is the primary identifier.
-- * source_doc_id is a soft reference (TEXT) so the figure ledger can
--   land even before ``source_document`` (migration 174) is populated
--   for the parent PDF.
-- * page_no / bbox_x / bbox_y / bbox_w / bbox_h are stored as REAL so
--   PyMuPDF's float-precision PDF point coordinates round-trip exactly
--   (legal evidentiary chain).
-- * caption is the ±200 chars surrounding text — NOT model-generated;
--   no hallucination risk.
-- * source_url + caption_quote_span pair is sufficient to reproduce
--   the figure context from the original PDF.
-- * NO LLM. CLIP-Japanese is encoder-only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_figure_embeddings (
    figure_id              TEXT PRIMARY KEY,            -- "fig_<sha256_pdf[:12]>_<page>_<idx>"
    source_doc_id          TEXT,                        -- soft FK to source_document(source_doc_id)
    pdf_sha256             TEXT NOT NULL,               -- sha256 of source PDF (matches textract manifest)
    source_url             TEXT NOT NULL,               -- canonical primary source URL
    page_no                INTEGER NOT NULL,            -- 1-based PDF page number
    figure_idx             INTEGER NOT NULL,            -- 0-based index of figure on this page
    bbox_x                 REAL NOT NULL,               -- PDF-point top-left x
    bbox_y                 REAL NOT NULL,               -- PDF-point top-left y
    bbox_w                 REAL NOT NULL,               -- PDF-point width
    bbox_h                 REAL NOT NULL,               -- PDF-point height
    caption                TEXT,                        -- ±200 chars surrounding text
    caption_quote_span     TEXT,                        -- JSON {start_char, end_char} into PDF text
    figure_kind            TEXT,                        -- "raster" | "vector" | "table_image" | "unknown"
    s3_key                 TEXT NOT NULL,               -- s3://...-derived/figures_raw/<sha>/<page>_<idx>.png
    embedding_model        TEXT NOT NULL,               -- "rinna/japanese-clip-vit-b-16"
    embedding_dim          INTEGER NOT NULL,            -- 512
    embedding_blob         BLOB,                        -- f32 little-endian 512-dim vector
    extracted_at           TEXT NOT NULL DEFAULT (datetime('now')),
    embedded_at            TEXT,
    UNIQUE (pdf_sha256, page_no, figure_idx)
);

CREATE INDEX IF NOT EXISTS ix_am_figure_embeddings_source_doc
    ON am_figure_embeddings(source_doc_id);
CREATE INDEX IF NOT EXISTS ix_am_figure_embeddings_pdf
    ON am_figure_embeddings(pdf_sha256, page_no);
CREATE INDEX IF NOT EXISTS ix_am_figure_embeddings_kind
    ON am_figure_embeddings(figure_kind);

-- vec0 sidecar — INTEGER PK is mandatory per sqlite-vec contract; the
-- *_map below links the synthetic INTEGER PK back to figure_id (TEXT).
-- This mirrors the migration 166 ``am_canonical_vec_*`` pattern so the
-- JOIN shape across vec tables stays identical.
CREATE VIRTUAL TABLE IF NOT EXISTS am_figure_embeddings_vec USING vec0(
    synthetic_id INTEGER PRIMARY KEY,
    embedding    float[512]
);

CREATE TABLE IF NOT EXISTS am_figure_embeddings_map (
    synthetic_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    figure_id        TEXT NOT NULL UNIQUE,
    caption_summary  TEXT,
    embedded_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_am_figure_embeddings_map_figure
    ON am_figure_embeddings_map(figure_id);
